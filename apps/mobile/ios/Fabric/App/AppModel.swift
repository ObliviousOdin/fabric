import Foundation
import Observation

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
    private(set) var connectionGeneration = 0
    private(set) var capabilityNegotiation: GatewayCapabilityNegotiation?

    private let client: JsonRpcGatewayClient
    private var connectionAttempt = 0
    private var connectingGatewayId: String?
    private var reconnectTask: Task<Void, Never>?
    private var reconnectFailures = 0
    private var isForeground = true
    private var permitsAutomaticReconnect = false
    private var pairingExecutionGate = PairingFlowExecutionGate()
    let api: GatewayAPI

    var activeGateway: SavedGateway? {
        gateways.first { $0.id == activeGatewayId }
    }

    init(client: JsonRpcGatewayClient = JsonRpcGatewayClient()) {
        self.client = client
        self.api = GatewayAPI(client: client)
        gateways = GatewayStore.all()
        client.onStateChange = { [weak self] state in
            MainActor.assumeIsolated {
                guard let self else { return }
                guard self.phase == .connected else { return }
                if state == .closed || state == .error {
                    self.capabilityNegotiation = .negotiating
                    self.phase = .reconnecting
                    self.lastConnectError = "Connection lost (\(state.rawValue))."
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
        gateways = try GatewayStore.upsert(gateway, token: token)
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

    func removeGateway(id: String) {
        if activeGatewayId == id || connectingGatewayId == id { disconnect() }
        GatewayStore.remove(id: id)
        gateways = GatewayStore.all()
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
    func connectPairingToken(_ acceptance: PairingTokenAcceptance) async throws {
        guard pairingExecutionGate.begin(acceptance.target) else { return }
        defer { pairingExecutionGate.finish(acceptance.target) }

        let gateway = try acceptance.withUnsafeToken { token in
            try saveTokenGateway(
                label: "",
                baseURL: acceptance.target.baseURL,
                token: token
            )
        }
        await connectToken(gateway)
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
                    try await self.connectPairingToken(acceptance)
                } catch {
                    self.lastConnectError = GatewayStoreError.credentialStorageUnavailable.localizedDescription
                }
            }
        case .gated(let target):
            let username = target.existingGatewayID
                .flatMap { existingID in gateways.first { $0.id == existingID }?.username }
                ?? ""
            pendingSignInGateway = saveGatedGateway(
                label: "",
                baseURL: target.baseURL,
                username: username
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
        await connect(gateway) {
            if let password, !password.isEmpty {
                try await GatewayAPI.passwordLogin(
                    baseURL: gateway.baseURL,
                    provider: provider,
                    username: gateway.username,
                    password: password,
                    otp: otp
                )
                let ticket = try await GatewayAPI.mintWsTicket(baseURL: gateway.baseURL)
                return try GatewayAPI.websocketURL(baseURL: gateway.baseURL, ticket: ticket)
            }

            do {
                let ticket = try await GatewayAPI.mintWsTicket(baseURL: gateway.baseURL)
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
            phase = .connected
        } catch {
            guard connectionAttempt == attempt else { return }
            connectingGatewayId = nil
            lastConnectError = error.localizedDescription
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
            await connect(gateway, automaticReconnect: true) {
                let ticket = try await GatewayAPI.mintWsTicket(baseURL: gateway.baseURL)
                return try GatewayAPI.websocketURL(baseURL: gateway.baseURL, ticket: ticket)
            }
        }
    }

    func disconnect() {
        connectionAttempt += 1
        permitsAutomaticReconnect = false
        reconnectTask?.cancel()
        reconnectTask = nil
        reconnectFailures = 0
        connectingGatewayId = nil
        activeGatewayId = nil
        capabilityNegotiation = nil
        phase = .disconnected
        client.close()
        GatewayAPI.clearAuthSession()
    }

    func supportsGatewayMethod(_ method: String) -> Bool {
        capabilityNegotiation?.supportsGatewayMethod(method) ?? false
    }
}
