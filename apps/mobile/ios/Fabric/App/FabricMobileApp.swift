import SwiftUI

@main
struct FabricMobileApp: App {
    @State private var appModel = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(appModel)
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        switch appModel.phase {
        case .disconnected, .connecting:
            ConnectView()
        case .connected:
            NavigationStack {
                SessionListView()
            }
        }
    }
}
