import SwiftUI

@main
struct FabricWatchApp: App {
    @State private var model = WatchAppModel()

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                WatchHomeView()
            }
            .environment(model)
        }
    }
}
