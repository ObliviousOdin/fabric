import Foundation
import Observation

enum AppLocalDataError: LocalizedError, Equatable {
    case presentationCacheRemovalUnavailable
    case forgetGatewayUnavailable
    case fullResetUnavailable

    var errorDescription: String? {
        switch self {
        case .presentationCacheRemovalUnavailable:
            return "Fabric couldn't clear cached presentation data on this iPhone. Saved servers, credentials, and gateway data were not changed."
        case .forgetGatewayUnavailable:
            return "Fabric couldn't remove the saved credential, so this server is still saved on this iPhone. Unlock the device and try again."
        case .fullResetUnavailable:
            return "Fabric couldn't complete the reset on this iPhone. Saved server access may still be present. Unlock the device and try again."
        }
    }
}

/// Owns only the bounded, device-local Home and conversation snapshots. The
/// directories contain no saved-server metadata or Keychain credentials.
struct DevicePresentationCacheStore {
    private let directoryURLs: [URL]
    private let fileManager: FileManager

    init(
        directoryURLs: [URL]? = nil,
        fileManager: FileManager = .default
    ) {
        self.fileManager = fileManager
        if let directoryURLs {
            self.directoryURLs = directoryURLs
        } else {
            let applicationSupport = fileManager.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first
            let caches = fileManager.urls(
                for: .cachesDirectory,
                in: .userDomainMask
            ).first
            self.directoryURLs = [applicationSupport, caches]
                .compactMap { $0 }
                .map { $0.appending(path: "Fabric", directoryHint: .isDirectory) }
        }
    }

    func removeAll() throws {
        for directoryURL in directoryURLs where fileManager.fileExists(atPath: directoryURL.path) {
            do {
                try fileManager.removeItem(at: directoryURL)
            } catch let error as CocoaError where error.code == .fileNoSuchFile {
                // A cache writer may have removed the last file between the
                // existence check and deletion. The desired state still holds.
            } catch {
                throw AppLocalDataError.presentationCacheRemovalUnavailable
            }
        }
    }
}

/// Root app state: the saved-gateway library, the shared gateway client, and
/// the connect/disconnect lifecycle. One socket is active at a time (the
/// desktop renderer is single-socket too); switching servers closes the
/// current socket and opens the next. The library lets the app hold many
/// Fabric servers and auto-login to token ones.
@Observable
@MainActor
final class AppModel {
    enum Phase {
        case disconnected
        case connecting
        case reconnecting
        case connected
    }

    private(set) var phase: Phase = .disconnected
    private(set) var gateways: [SavedGateway] = []
    private(set) var activeGatewayId: String?
    private(set) var lastConnectError: String?
    private(set) var pendingSignInGateway: SavedGateway?
    private(set) var connectedIntroGatewayId: String?
    private(set) var connectionGeneration = 0
    private(set) var capabilityNegotiation: GatewayCapabilityNegotiation?

    private let client: JsonRpcGatewayClient
    private var connectionAttempt = 0
    private var connectingGatewayId: String?
    private var reconnectTask: Task<Void, Never>?
    private var reconnectFailures = 0
    private var isForeground = true
    private var permitsAutomaticReconnect = false
    private let pairingExecutionGate = PairingFlowExecutionGate()
    private let presentationCacheStore: DevicePresentationCacheStore
    private let removeGatewayFromStore: (String) throws -> Void
    private let resetGatewayStore: () throws -> Void
    let api: GatewayAPI

    var activeGateway: SavedGateway? {
        gateways.first { $0.id == activeGatewayId }
    }

    init(
        client: JsonRpcGatewayClient = JsonRpcGatewayClient(),
        presentationCacheStore: DevicePresentationCacheStore = DevicePresentationCacheStore(),
        removeGatewayFromStore: @escaping (String) throws -> Void = GatewayStore.remove,
        resetGatewayStore: @escaping () throws -> Void = GatewayStore.removeAll
    ) {
        self.client = client
        self.presentationCacheStore = presentationCacheStore
        self.removeGatewayFromStore = removeGatewayFromStore
        self.resetGatewayStore = resetGatewayStore
        self.api = GatewayAPI(client: client)
        gateways = GatewayStore.all()
        client.onStateChange = { [weak self] state in
            MainActor.assumeIsolated {
                guard let self else { return }
                guard self.phase == .connected else { return }
                if state == .closed || state == .error {
                    self.capabilityNegotiation = .negotiating
                    self.phase = .reconnecting
                    self.lastConnectError = "Connection lost. Reconnecting to \(self.activeGateway?.label ?? "Fabric")…"
                    self.permitsAutomaticReconnect = true
                    self.scheduleReconnect()
                }
            }
        }
    }

    // MARK: - Library management

    func reloadGateways() {
        gateways = GatewayStore.all()
    }

    /// Save a token-mode server (and its token) into the library.
    func saveTokenGateway(label: String, baseURL: URL, token: String) throws -> SavedGateway {
        let existing = gateways.first { $0.endpointKey == SavedGateway.endpointKey(for: baseURL) }
        let gateway = SavedGateway(
            id: existing?.id ?? UUID().uuidString,
            label: label.isEmpty ? (existing?.label ?? SavedGateway.defaultLabel(for: baseURL)) : label,
            baseURL: baseURL,
            authMode: .token
        )
        let updatedGateways = try GatewayStore.upsert(gateway, token: token)
        // A re-pair can switch an existing endpoint from provider auth to a
        // direct token. Its old cookie jar must not survive that mode change.
        GatewayAPI.clearAuthSession(for: gateway.id)
        gateways = updatedGateways
        return gateway
    }

    /// Save a gated (sign-in) server. No token; the password is entered at
    /// connect time and never persisted.
    func saveGatedGateway(label: String, baseURL: URL, username: String) -> SavedGateway {
        let existing = gateways.first { $0.endpointKey == SavedGateway.endpointKey(for: baseURL) }
        let gateway = SavedGateway(
            id: existing?.id ?? UUID().uuidString,
            label: label.isEmpty ? (existing?.label ?? SavedGateway.defaultLabel(for: baseURL)) : label,
            baseURL: baseURL,
            authMode: .gated,
            username: username
        )
        gateways = GatewayStore.upsert(gateway)
        return gateway
    }

    func removeGateway(id: String) throws {
        let shouldDisconnect = activeGatewayId == id || connectingGatewayId == id
        do {
            try removeGatewayFromStore(id)
        } catch {
            // The store contract leaves every local record in place on a
            // credential failure. Do not close a live connection or expose a
            // raw Security framework status to presentation code.
            throw AppLocalDataError.forgetGatewayUnavailable
        }

        // Offboarding is scoped to exactly the forgotten saved gateway. Other
        // gated servers retain their independent process-only sessions.
        GatewayAPI.clearAuthSession(for: id)
        if shouldDisconnect {
            disconnect()
        }
        gateways = GatewayStore.all()
    }

    /// Remove only bounded, device-local presentation snapshots. This does not
    /// disconnect, mutate the saved-server library, touch credentials, or send
    /// any request to the gateway.
    func clearCachedPresentationData() throws {
        try presentationCacheStore.removeAll()
    }

    /// Full device-local offboarding. The Settings surface owns the destructive
    /// confirmation; this operation removes presentation caches first, then
    /// requires service-wide protected-credential cleanup before saved metadata
    /// is cleared. It never sends a delete request to the gateway.
    func resetLocalAppData() throws {
        disconnect()
        // `disconnect()` invalidates only the active/in-flight gateway. A full
        // device reset must also remove every inactive gateway's cookie jar,
        // even if protected Keychain cleanup later fails.
        GatewayAPI.clearAllAuthSessions()
        do {
            try clearCachedPresentationData()
            try resetGatewayStore()
        } catch let error as AppLocalDataError {
            gateways = GatewayStore.all()
            throw error
        } catch {
            gateways = GatewayStore.all()
            throw AppLocalDataError.fullResetUnavailable
        }
        if let bundleID = Bundle.main.bundleIdentifier {
            UserDefaults.standard.removePersistentDomain(forName: bundleID)
        }
        gateways = []
        pendingSignInGateway = nil
        lastConnectError = nil
    }

    /// Classify either native pairing entry point against the current library.
    /// This is intentionally side-effect free; callers decide how their
    /// existing surface presents gated auth and errors.
    func pairingOutcome(for input: PairingFlowInput) -> PairingFlowOutcome {
        PairingFlowModel(gateways: gateways).accept(input)
    }

    /// Persist one accepted pairing token and start one connection attempt.
    /// The credential leaves its redacting wrapper only inside the synchronous
    /// Keychain write, and is never copied into observable app state.
    func connectPairingToken(_ acceptance: PairingTokenAcceptance) async throws -> PairingTokenConnectResult {
        try await pairingExecutionGate.execute(acceptance.target) {
            let gateway = try acceptance.withUnsafeToken { token in
                try saveTokenGateway(
                    label: "",
                    baseURL: acceptance.target.baseURL,
                    token: token
                )
            }
            await connectToken(gateway)
            return .attempted(gateway)
        }
    }

    /// Accept a native deep link from the browser pairing page. Token-mode
    /// links connect immediately; gated links open the existing sign-in sheet.
    /// An unimplemented v2 handoff fails closed instead of becoming a password
    /// sign-in or persisting its opaque enrollment handle.
    func receivePairingURL(_ url: URL) {
        switch pairingOutcome(for: .deepLink(url)) {
        case .invalid:
            lastConnectError = "This link is not a valid Fabric pairing link."
        case .unsupportedEnrollment:
            lastConnectError = "This QR requires secure device enrollment. Update Fabric Mobile and the gateway together, then scan a new QR."
        case .token(let acceptance):
            Task { [weak self] in
                guard let self else { return }
                do {
                    if try await self.connectPairingToken(acceptance) == .alreadyInFlight {
                        self.lastConnectError = "Pairing is already in progress for this server."
                    }
                } catch {
                    self.lastConnectError = GatewayStoreError.credentialStorageUnavailable.localizedDescription
                }
            }
        case .gated(let target):
            pendingSignInGateway = saveGatedGateway(
                label: "",
                baseURL: target.baseURL,
                username: target.existingUsername(in: gateways)
            )
        }
    }

    func takePendingSignInGateway() -> SavedGateway? {
        defer { pendingSignInGateway = nil }
        return pendingSignInGateway
    }

    func canAutoConnect(_ gateway: SavedGateway) -> Bool {
        GatewayStore.canAutoConnect(gateway)
    }

    // MARK: - Connect

    /// Connect to a saved token-mode server using its stored token. Suitable
    /// for one-tap / auto reconnect.
    func connectToken(_ gateway: SavedGateway) async {
        guard GatewayBaseURL.allowsTokenCredential(gateway.baseURL) else {
            lastConnectError = GatewayTokenTransportError.secureTransportRequired.localizedDescription
            return
        }
        GatewayAPI.clearAuthSession(for: gateway.id)
        guard let token = GatewayStore.token(id: gateway.id), !token.isEmpty else {
            lastConnectError = "No saved token for \(gateway.label)."
            return
        }
        await connect(gateway) {
            let status = try await GatewayAPI.probeStatus(baseURL: gateway.baseURL)
            if status.authRequired {
                throw GatewayClientError.rpc(
                    message: "This server now requires sign-in — edit it and switch to a username and password."
                )
            }
            return try GatewayAPI.websocketURL(baseURL: gateway.baseURL, token: token)
        }
    }

    /// Connect to a saved gated server. A supplied password is authoritative:
    /// sign in immediately instead of spending a round trip on a ticket request
    /// that is expected to fail for a fresh or expired cookie session. Saved
    /// servers with no supplied password still try a silent cookie reconnect.
    func connectGated(
        _ gateway: SavedGateway,
        provider: String,
        password: String?,
        otp: String = ""
    ) async {
        let hasFreshPassword = password?.isEmpty == false
        let authSession = GatewayAPI.beginAuthSession(
            for: gateway,
            preservingExistingCookies: !hasFreshPassword
        )
        await connect(gateway) {
            if let password, !password.isEmpty {
                try await GatewayAPI.passwordLogin(
                    gateway: gateway,
                    using: authSession,
                    provider: provider,
                    username: gateway.username,
                    password: password,
                    otp: otp
                )
                let ticket = try await GatewayAPI.mintWsTicket(
                    gateway: gateway,
                    using: authSession
                )
                return try GatewayAPI.websocketURL(baseURL: gateway.baseURL, ticket: ticket)
            }

            do {
                let ticket = try await GatewayAPI.mintWsTicket(
                    gateway: gateway,
                    using: authSession
                )
                return try GatewayAPI.websocketURL(baseURL: gateway.baseURL, ticket: ticket)
            } catch GatewayAPIError.httpStatus(let code, _) where code == 401 || code == 403 {
                throw GatewayClientError.rpc(message: "Sign in to \(gateway.label) to connect.")
            } catch {
                throw error
            }
        }
    }

    private func connect(
        _ gateway: SavedGateway,
        automaticReconnect: Bool = false,
        wsURL: @escaping () async throws -> URL
    ) async {
        guard !automaticReconnect || phase == .reconnecting else { return }
        let supersededGatewayIDs = Set(
            [activeGatewayId, connectingGatewayId]
                .compactMap { $0 }
                .filter { $0 != gateway.id }
        )
        for gatewayID in supersededGatewayIDs {
            GatewayAPI.clearAuthSession(for: gatewayID)
        }
        if !automaticReconnect {
            reconnectTask?.cancel()
            reconnectTask = nil
            reconnectFailures = 0
            permitsAutomaticReconnect = false
        }
        // Invalidate an open or half-open socket before resolving credentials
        // for the new target. The transport also generations each attempt, so
        // a slower superseded handshake cannot become the active connection.
        client.close()
        connectionAttempt += 1
        let attempt = connectionAttempt
        phase = automaticReconnect ? .reconnecting : .connecting
        connectingGatewayId = gateway.id
        capabilityNegotiation = .negotiating
        if !automaticReconnect { activeGatewayId = nil }
        lastConnectError = nil
        do {
            let url = try await wsURL()
            guard connectionAttempt == attempt,
                  phase == (automaticReconnect ? .reconnecting : .connecting) else { return }
            try await client.connect(to: url)
            guard connectionAttempt == attempt,
                  phase == (automaticReconnect ? .reconnecting : .connecting) else { return }
            let negotiation = try await api.capabilities()
            guard connectionAttempt == attempt,
                  phase == (automaticReconnect ? .reconnecting : .connecting) else { return }
            capabilityNegotiation = negotiation
            guard negotiation.allowsBaselineSessionCalls else {
                connectingGatewayId = nil
                activeGatewayId = gateway.id
                GatewayStore.setLastActive(gateway.id)
                permitsAutomaticReconnect = false
                lastConnectError = negotiation.blockingMessage
                    ?? "This gateway cannot provide the required mobile session controls."
                phase = .disconnected
                client.close()
                return
            }
            connectingGatewayId = nil
            activeGatewayId = gateway.id
            GatewayStore.setLastActive(gateway.id)
            reconnectFailures = 0
            permitsAutomaticReconnect = true
            connectionGeneration += 1
            lastConnectError = nil
            phase = .connected
            if !GatewayStore.hasCompletedConnectionIntro(id: gateway.id) {
                connectedIntroGatewayId = gateway.id
            }
        } catch {
            guard connectionAttempt == attempt else { return }
            connectingGatewayId = nil
            lastConnectError = GatewayConnectionIssue.message(for: error, gateway: gateway)
            if gateway.authMode == .gated,
               GatewayConnectionIssue.requiresSignIn(error) {
                permitsAutomaticReconnect = false
                reconnectFailures = 0
                capabilityNegotiation = nil
                activeGatewayId = gateway.id
                phase = .disconnected
                pendingSignInGateway = gateway
                return
            }
            if automaticReconnect,
               permitsAutomaticReconnect,
               activeGatewayId == gateway.id,
               reconnectFailures < 4 {
                reconnectFailures += 1
                phase = .reconnecting
                scheduleReconnect()
            } else {
                permitsAutomaticReconnect = false
                if !automaticReconnect { activeGatewayId = nil }
                capabilityNegotiation = nil
                phase = .disconnected
            }
        }
    }

    func sceneBecameActive() {
        isForeground = true
        if phase == .reconnecting { scheduleReconnect(immediate: true) }
    }

    func sceneEnteredBackground() {
        isForeground = false
        reconnectTask?.cancel()
        reconnectTask = nil
        if phase == .connected {
            permitsAutomaticReconnect = true
            capabilityNegotiation = .negotiating
            phase = .reconnecting
            client.close()
        }
    }

    func retryActiveGateway() {
        guard activeGateway != nil, phase != .connected, phase != .connecting else { return }
        reconnectFailures = 0
        permitsAutomaticReconnect = true
        phase = .reconnecting
        scheduleReconnect(immediate: true)
    }

    private func scheduleReconnect(immediate: Bool = false) {
        guard isForeground,
              permitsAutomaticReconnect,
              phase == .reconnecting,
              activeGateway != nil,
              reconnectTask == nil else { return }

        let delay = immediate ? 0.0 : min(pow(2.0, Double(reconnectFailures)) * 0.5, 8.0)
        reconnectTask = Task { [weak self] in
            if delay > 0 {
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            }
            guard !Task.isCancelled, let self else { return }
            self.reconnectTask = nil
            await self.reconnectActiveGateway()
        }
    }

    private func reconnectActiveGateway() async {
        guard phase == .reconnecting, let gateway = activeGateway else { return }
        switch gateway.authMode {
        case .token:
            guard GatewayBaseURL.allowsTokenCredential(gateway.baseURL) else {
                permitsAutomaticReconnect = false
                reconnectTask?.cancel()
                reconnectTask = nil
                reconnectFailures = 0
                capabilityNegotiation = nil
                phase = .disconnected
                lastConnectError = GatewayTokenTransportError.secureTransportRequired.localizedDescription
                client.close()
                return
            }
            guard let token = GatewayStore.token(id: gateway.id), !token.isEmpty else {
                permitsAutomaticReconnect = false
                capabilityNegotiation = nil
                phase = .disconnected
                lastConnectError = "The saved credential is unavailable. Add this server again."
                return
            }
            await connect(gateway, automaticReconnect: true) {
                let status = try await GatewayAPI.probeStatus(baseURL: gateway.baseURL)
                if status.authRequired {
                    throw GatewayClientError.rpc(message: "This server now requires sign-in.")
                }
                return try GatewayAPI.websocketURL(baseURL: gateway.baseURL, token: token)
            }
        case .gated:
            let authSession = GatewayAPI.beginAuthSession(
                for: gateway,
                preservingExistingCookies: true
            )
            await connect(gateway, automaticReconnect: true) {
                let ticket = try await GatewayAPI.mintWsTicket(
                    gateway: gateway,
                    using: authSession
                )
                return try GatewayAPI.websocketURL(baseURL: gateway.baseURL, ticket: ticket)
            }
        }
    }

    func disconnect() {
        let authGatewayIDs = Set([activeGatewayId, connectingGatewayId].compactMap { $0 })
        connectionAttempt += 1
        permitsAutomaticReconnect = false
        reconnectTask?.cancel()
        reconnectTask = nil
        reconnectFailures = 0
        connectingGatewayId = nil
        connectedIntroGatewayId = nil
        activeGatewayId = nil
        capabilityNegotiation = nil
        phase = .disconnected
        client.close()
        for gatewayID in authGatewayIDs {
            GatewayAPI.clearAuthSession(for: gatewayID)
        }
    }

    func completeConnectedIntro() {
        guard let id = connectedIntroGatewayId else { return }
        GatewayStore.setCompletedConnectionIntro(true, id: id)
        connectedIntroGatewayId = nil
    }

    func dismissConnectedIntro() {
        connectedIntroGatewayId = nil
    }

    func supportsGatewayMethod(_ method: String) -> Bool {
        capabilityNegotiation?.supportsGatewayMethod(method) ?? false
    }

#if DEBUG
    /// Narrow behavioral-test seam for transaction ordering. It does not open
    /// a socket or bypass production pairing and is absent from Release builds.
    func installConnectionStateForTesting(gatewayID: String, phase: Phase) {
        activeGatewayId = gatewayID
        self.phase = phase
    }

    /// Deterministically exercises the production reconnect decision without
    /// waiting on the scheduler. This remains behind DEBUG and does not relax
    /// any transport, credential, or connection policy.
    func reconnectActiveGatewayForTesting() async {
        await reconnectActiveGateway()
    }
#endif
}
