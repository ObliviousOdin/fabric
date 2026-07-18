import SwiftUI

@main
struct FabricMobileApp: App {
    @State private var appModel = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(appModel)
                // The Fabric action accent drives every interactive control;
                // neutral surfaces carry the rest (design contract).
                .tint(FabricTheme.action)
                .onOpenURL { appModel.receivePairingURL($0) }
                .onChange(of: scenePhase) { _, phase in
                    switch phase {
                    case .active:
                        appModel.sceneBecameActive()
                    case .background:
                        appModel.sceneEnteredBackground()
                    case .inactive:
                        break
                    @unknown default:
                        break
                    }
                }
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        if appModel.activeGatewayId == nil {
            // The saved-server library is home; connecting shows an overlay
            // there rather than a separate screen.
            GatewayListView()
        } else {
            NavigationStack {
                SessionListView()
            }
            .safeAreaInset(edge: .top, spacing: 0) {
                if appModel.phase != .connected {
                    ConnectionRecoveryBanner()
                }
            }
        }
    }
}

private struct ConnectionRecoveryBanner: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        HStack(spacing: 10) {
            if appModel.phase == .reconnecting {
                ProgressView().controlSize(.small)
            } else {
                Image(systemName: "wifi.exclamationmark")
            }
            Text(appModel.phase == .reconnecting
                ? "Reconnecting to Fabric…"
                : (appModel.lastConnectError ?? "Fabric is offline."))
                .font(.footnote)
                .lineLimit(2)
            Spacer(minLength: 8)
            if appModel.phase == .disconnected {
                Button("Retry") { appModel.retryActiveGateway() }
                    .buttonStyle(.bordered)
                Button("Servers") { appModel.disconnect() }
                    .buttonStyle(.plain)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(FabricTheme.warning.fabricTint())
        .accessibilityElement(children: .combine)
    }
}
