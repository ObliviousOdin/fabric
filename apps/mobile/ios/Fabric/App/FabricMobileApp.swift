import SwiftUI

@main
struct FabricMobileApp: App {
    @State private var appModel = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(appModel)
                // The Fabric action accent drives every interactive control;
                // neutral surfaces carry the rest (design contract).
                .tint(FabricTheme.action)
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        switch appModel.phase {
        case .disconnected, .connecting:
            // The saved-server library is home; connecting shows an overlay
            // there rather than a separate screen.
            GatewayListView()
        case .connected:
            NavigationStack {
                SessionListView()
            }
        }
    }
}
