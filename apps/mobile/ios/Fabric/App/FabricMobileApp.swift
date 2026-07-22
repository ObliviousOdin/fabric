import SwiftUI

@main
struct FabricMobileApp: App {
    @State private var appModel = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            Group {
#if DEBUG
                if let fixture = FabricUIDebugFixture.requested {
                    FabricUIDebugFixtureView(fixture: fixture)
                } else if let fixture = ConversationHomeDebugFixture.requested {
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
                .task {
#if DEBUG
                    if let url = FabricUIDebugPairingLaunch.requestedURL {
                        appModel.receivePairingURL(url)
                    }
#endif
                }
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
    @State private var signIn: SavedGateway?

    var body: some View {
        Group {
            if appModel.activeGatewayId == nil {
                GatewayListView()
            } else if appModel.phase == .connected,
                      appModel.connectedIntroGatewayId == appModel.activeGatewayId,
                      let gateway = appModel.activeGateway {
                ConnectedGatewayIntroView(
                    gateway: gateway,
                    negotiation: appModel.capabilityNegotiation,
                    hasStoredPassword: appModel.hasStoredPassword(gateway),
                    onContinue: {
                        ConnectedAppShellSelection.resetForCompletedIntro()
                        appModel.completeConnectedIntro()
                    },
                    onSwitchServer: { appModel.disconnect() }
                )
            } else {
                ConnectedAppShellView()
            }
        }
        .sheet(item: $signIn) { gateway in
            SignInSheet(gateway: gateway)
        }
        .onChange(of: appModel.pendingSignInGateway?.id, initial: true) {
            guard appModel.pendingSignInGateway != nil else { return }
            signIn = appModel.takePendingSignInGateway()
        }
    }
}

enum ConnectedAppTab: String {
    case home
    case sessions
    case settings
}

enum ConnectedAppShellSelection {
    static let storageKey = "fabric.mobile.selected-tab.v1"

    static func resetForCompletedIntro(defaults: UserDefaults = .standard) {
        defaults.set(ConnectedAppTab.home.rawValue, forKey: storageKey)
    }
}

private struct ConnectedAppShellView: View {
    @Environment(AppModel.self) private var appModel
    @AppStorage(ConnectedAppShellSelection.storageKey)
    private var selectedTab = ConnectedAppTab.home.rawValue

    var body: some View {
        VStack(spacing: 0) {
            if appModel.phase != .connected {
                ConnectionRecoveryBanner()
            }
            TabView(selection: $selectedTab) {
                NavigationStack {
                    ConversationHomeView()
                }
                .tag(ConnectedAppTab.home.rawValue)
                .tabItem {
                    Label("Home", systemImage: "sparkles")
                }
                .accessibilityIdentifier("app-tab-home")

                NavigationStack {
                    SessionListView()
                }
                .tag(ConnectedAppTab.sessions.rawValue)
                .tabItem {
                    Label("Sessions", systemImage: "bubble.left.and.bubble.right")
                }
                .accessibilityIdentifier("app-tab-sessions")

                NavigationStack {
                    SettingsRootView()
                }
                .tag(ConnectedAppTab.settings.rawValue)
                .tabItem {
                    Label("Settings", systemImage: "gearshape")
                }
                .accessibilityIdentifier("app-tab-settings")
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
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
            if usesVerticalLayout {
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

    private var usesVerticalLayout: Bool {
        switch dynamicTypeSize {
        case .xxLarge, .xxxLarge,
             .accessibility1, .accessibility2, .accessibility3,
             .accessibility4, .accessibility5:
            return true
        default:
            return false
        }
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
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) {
                retryButton
                serversButton
            }
            VStack(spacing: 8) {
                retryButton.frame(maxWidth: .infinity)
                serversButton.frame(maxWidth: .infinity)
            }
        }
    }

    private var retryButton: some View {
        Button("Retry", action: onRetry)
            .buttonStyle(.bordered)
            .frame(minHeight: FabricTheme.minTarget)
    }

    private var serversButton: some View {
        Button("Servers", action: onServers)
            .buttonStyle(.plain)
            .frame(minHeight: FabricTheme.minTarget)
    }
}
