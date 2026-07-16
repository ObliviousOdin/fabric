import Foundation
import Observation

/// Root app state: connection settings, the shared gateway client, and the
/// connect/disconnect lifecycle. One socket serves the whole app (the
/// desktop renderer does the same); per-screen models subscribe to its
/// event stream.
@Observable
@MainActor
final class AppModel {
    enum Phase {
        case disconnected
        case connecting
        case connected
    }

    private(set) var phase: Phase = .disconnected
    private(set) var settings: ConnectionSettings?
    private(set) var lastConnectError: String?

    let client = JsonRpcGatewayClient()
    var api: GatewayAPI { GatewayAPI(client: client) }

    init() {
        settings = ConnectionStore.load()
        // The client dispatches state changes on the main queue.
        client.onStateChange = { [weak self] state in
            MainActor.assumeIsolated {
                guard let self else { return }
                // Server-side close or transport error while connected drops
                // the app back to the connect screen with the state as context.
                if self.phase == .connected, state == .closed || state == .error {
                    self.phase = .disconnected
                    self.lastConnectError = "Connection lost (\(state.rawValue))."
                }
            }
        }
    }

    func connect(settings: ConnectionSettings) async {
        phase = .connecting
        lastConnectError = nil
        do {
            // Probe first: fail fast with a readable error and refuse the
            // token path against an OAuth-gated gateway instead of dying on
            // an opaque 4401 at WS upgrade.
            let status = try await GatewayAPI.probeStatus(baseURL: settings.baseURL)
            if status.authRequired {
                throw GatewayClientError.rpc(
                    message: "This gateway requires OAuth sign-in, which the mobile app does not support yet. Use a token-authenticated gateway."
                )
            }
            let wsURL = try GatewayAPI.websocketURL(baseURL: settings.baseURL, token: settings.token)
            try await client.connect(to: wsURL)
            ConnectionStore.save(settings)
            self.settings = settings
            phase = .connected
        } catch {
            lastConnectError = error.localizedDescription
            phase = .disconnected
        }
    }

    func disconnect() {
        client.close()
        phase = .disconnected
    }

    func forgetGateway() {
        disconnect()
        ConnectionStore.clear()
        settings = nil
    }
}
