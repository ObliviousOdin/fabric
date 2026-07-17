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
        case connected
    }

    private(set) var phase: Phase = .disconnected
    private(set) var gateways: [SavedGateway] = []
    private(set) var activeGatewayId: String?
    private(set) var lastConnectError: String?

    let client = JsonRpcGatewayClient()
    var api: GatewayAPI { GatewayAPI(client: client) }

    var activeGateway: SavedGateway? {
        gateways.first { $0.id == activeGatewayId }
    }

    init() {
        gateways = GatewayStore.all()
        client.onStateChange = { [weak self] state in
            MainActor.assumeIsolated {
                guard let self else { return }
                if self.phase == .connected, state == .closed || state == .error {
                    self.phase = .disconnected
                    self.lastConnectError = "Connection lost (\(state.rawValue))."
                }
            }
        }
    }

    // MARK: - Library management

    func reloadGateways() {
        gateways = GatewayStore.all()
    }

    /// Save a token-mode server (and its token) into the library.
    func saveTokenGateway(label: String, baseURL: URL, token: String) -> SavedGateway {
        let gateway = SavedGateway(
            label: label.isEmpty ? SavedGateway.defaultLabel(for: baseURL) : label,
            baseURL: baseURL,
            authMode: .token
        )
        gateways = GatewayStore.upsert(gateway, token: token)
        return gateway
    }

    /// Save a gated (sign-in) server. No token; the password is entered at
    /// connect time and never persisted.
    func saveGatedGateway(label: String, baseURL: URL, username: String) -> SavedGateway {
        let gateway = SavedGateway(
            label: label.isEmpty ? SavedGateway.defaultLabel(for: baseURL) : label,
            baseURL: baseURL,
            authMode: .gated,
            username: username
        )
        gateways = GatewayStore.upsert(gateway)
        return gateway
    }

    func removeGateway(id: String) {
        GatewayStore.remove(id: id)
        gateways = GatewayStore.all()
        if activeGatewayId == id { disconnect() }
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
        await connect(gateway: gateway) {
            let status = try await GatewayAPI.probeStatus(baseURL: gateway.baseURL)
            if status.authRequired {
                throw GatewayClientError.rpc(
                    message: "This server now requires sign-in — edit it and switch to a username and password."
                )
            }
            return try await GatewayAPI.websocketURL(baseURL: gateway.baseURL, token: token)
        }
    }

    /// Connect to a saved gated server. Tries the ticket mint first (a live
    /// cookie session from earlier this run needs no password); falls back to
    /// `passwordLogin` when a password is supplied, else surfaces a re-auth
    /// prompt to the caller.
    func connectGated(
        _ gateway: SavedGateway,
        provider: String,
        password: String?,
        otp: String = ""
    ) async {
        await connect(gateway: gateway) {
            do {
                let ticket = try await GatewayAPI.mintWsTicket(baseURL: gateway.baseURL)
                return try await GatewayAPI.websocketURL(baseURL: gateway.baseURL, ticket: ticket)
            } catch {
                guard let password, !password.isEmpty else {
                    throw GatewayClientError.rpc(message: "Sign in to \(gateway.label) to connect.")
                }
                try await GatewayAPI.passwordLogin(
                    baseURL: gateway.baseURL,
                    provider: provider,
                    username: gateway.username,
                    password: password,
                    otp: otp
                )
                let ticket = try await GatewayAPI.mintWsTicket(baseURL: gateway.baseURL)
                return try await GatewayAPI.websocketURL(baseURL: gateway.baseURL, ticket: ticket)
            }
        }
    }

    /// Shared connect scaffold: close any current socket, run `resolveWsURL`,
    /// open the socket, and record the active gateway on success.
    private func connect(gateway: SavedGateway, resolveWsURL: () async throws -> URL) async {
        if phase == .connected { client.close() }
        phase = .connecting
        lastConnectError = nil
        do {
            let wsURL = try await resolveWsURL()
            try await client.connect(to: wsURL)
            activeGatewayId = gateway.id
            GatewayStore.setLastActive(gateway.id)
            phase = .connected
        } catch {
            lastConnectError = error.localizedDescription
            phase = .disconnected
        }
    }

    func disconnect() {
        client.close()
        activeGatewayId = nil
        phase = .disconnected
    }
}
