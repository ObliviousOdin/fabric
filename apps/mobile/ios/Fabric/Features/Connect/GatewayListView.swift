import SwiftUI

/// The saved-server library — the app's home when no socket is open. Tap a
/// token server to connect instantly; a gated server prompts for its
/// password unless a live session is still around. Add servers here or by
/// scanning a pairing QR.
struct GatewayListView: View {
    @Environment(AppModel.self) private var appModel

    @State private var showAdd = false
    @State private var signIn: SavedGateway?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(appModel.gateways) { gateway in
                        Button {
                            Task { await tap(gateway) }
                        } label: {
                            GatewayRow(
                                gateway: gateway,
                                autoReady: appModel.canAutoConnect(gateway)
                            )
                        }
                        .foregroundStyle(.primary)
                    }
                    .onDelete { indexSet in
                        for index in indexSet {
                            appModel.removeGateway(id: appModel.gateways[index].id)
                        }
                    }
                } header: {
                    Text("Servers")
                } footer: {
                    if appModel.gateways.isEmpty {
                        Text("Add the machine running `fabric serve`. Scan its `--qr` code or enter the address and credential.")
                    }
                }

                if let error = appModel.lastConnectError {
                    Section {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.danger)
                    }
                }
            }
            .navigationTitle("Fabric")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showAdd = true
                    } label: {
                        Label("Add server", systemImage: "plus")
                    }
                }
            }
            .overlay {
                if appModel.phase == .connecting {
                    ProgressView("Connecting…")
                        .padding(20)
                        .background(FabricTheme.surfaceRaised, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
                }
            }
            .sheet(isPresented: $showAdd) {
                AddGatewayView()
            }
            .sheet(item: $signIn) { gateway in
                SignInSheet(gateway: gateway)
            }
        }
    }

    private func tap(_ gateway: SavedGateway) async {
        switch gateway.authMode {
        case .token:
            await appModel.connectToken(gateway)
        case .gated:
            // Try a silent reconnect on a live cookie session; if that fails,
            // ask for the password.
            await appModel.connectGated(gateway, provider: "", password: nil)
            if appModel.phase != .connected {
                signIn = gateway
            }
        }
    }
}

private struct GatewayRow: View {
    let gateway: SavedGateway
    let autoReady: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: gateway.authMode == .token ? "key.horizontal" : "person.badge.key")
                .foregroundStyle(FabricTheme.textMuted)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(gateway.label)
                    .font(.body)
                Text(gateway.baseURL.absoluteString)
                    .font(.caption.monospaced())
                    .foregroundStyle(FabricTheme.textMuted)
                    .lineLimit(1)
            }
            Spacer()
            Text(autoReady ? "Tap to connect" : (gateway.authMode == .gated ? "Sign in" : "Add token"))
                .font(.caption)
                .foregroundStyle(FabricTheme.textMuted)
        }
        .padding(.vertical, 4)
    }
}
