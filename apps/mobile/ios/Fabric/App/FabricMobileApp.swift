import SwiftUI

@main
struct FabricMobileApp: App {
    @State private var appModel = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            Group {
#if DEBUG
                if let fixture = ConversationHomeDebugFixture.requested {
                    ConversationHomeDebugFixtureView(fixture: fixture)
                } else {
                    RootView()
                }
#else
                RootView()
#endif
            }
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
            VStack(spacing: 0) {
                if appModel.phase != .connected {
                    ConnectionRecoveryBanner()
                }
                NavigationStack {
                    ConversationHomeView()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}

private struct ConnectionRecoveryBanner: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        ConnectionRecoveryBannerContent(
            isReconnecting: appModel.phase == .reconnecting,
            message: appModel.phase == .reconnecting
                ? "Reconnecting to Fabric…"
                : (appModel.lastConnectError ?? "Fabric is offline."),
            showActions: appModel.phase == .disconnected,
            onRetry: { appModel.retryActiveGateway() },
            onServers: { appModel.disconnect() }
        )
    }
}

/// Shared connection chrome for production and deterministic offline QA.
/// Keeping the actions separate from the status accessibility element avoids
/// collapsing multiple controls into one VoiceOver target.
struct ConnectionRecoveryBannerContent: View {
    let isReconnecting: Bool
    let message: String
    let showActions: Bool
    let onRetry: () -> Void
    let onServers: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    status
                    if showActions { actions }
                }
            } else {
                HStack(spacing: 10) {
                    status
                    Spacer(minLength: 8)
                    if showActions { actions }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(FabricTheme.warning.fabricTint())
    }

    private var status: some View {
        HStack(spacing: 10) {
            if isReconnecting {
                ProgressView().controlSize(.small)
            } else {
                Image(systemName: "wifi.exclamationmark")
            }
            Text(message)
                .font(.footnote)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }

    private var actions: some View {
        HStack(spacing: 10) {
            Button("Retry", action: onRetry)
                .buttonStyle(.bordered)
                .frame(minHeight: FabricTheme.minTarget)
            Button("Servers", action: onServers)
                .buttonStyle(.plain)
                .frame(minHeight: FabricTheme.minTarget)
        }
    }
}
