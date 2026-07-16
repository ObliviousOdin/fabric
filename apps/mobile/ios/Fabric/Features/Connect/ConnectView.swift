import SwiftUI

/// First-run / reconnect screen: gateway URL + session token, with an
/// explicit reachability test against the public `/api/status` probe.
struct ConnectView: View {
    @Environment(AppModel.self) private var appModel

    @State private var urlText = ""
    @State private var token = ""
    @State private var probeResult: String?
    @State private var probing = false

    private var parsedURL: URL? {
        guard
            let url = URL(string: urlText.trimmingCharacters(in: .whitespacesAndNewlines)),
            url.scheme == "http" || url.scheme == "https",
            url.host() != nil
        else { return nil }
        return url
    }

    private var canConnect: Bool {
        parsedURL != nil && !token.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://my-machine:9119", text: $urlText)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    SecureField("Session token", text: $token)
                } header: {
                    Text("Gateway")
                } footer: {
                    Text("Run `fabric serve` on the machine that hosts your Fabric profile, then enter its URL and dashboard session token. LAN, Tailscale, and SSH-tunnel addresses all work.")
                }

                Section {
                    Button {
                        Task { await probe() }
                    } label: {
                        if probing {
                            ProgressView()
                        } else {
                            Text("Test connection")
                        }
                    }
                    .disabled(parsedURL == nil || probing)

                    if let probeResult {
                        Text(probeResult)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }

                Section {
                    Button {
                        guard let url = parsedURL else { return }
                        let settings = ConnectionSettings(
                            baseURL: url,
                            token: token.trimmingCharacters(in: .whitespaces)
                        )
                        Task { await appModel.connect(settings: settings) }
                    } label: {
                        if appModel.phase == .connecting {
                            ProgressView()
                        } else {
                            Text("Connect")
                        }
                    }
                    .disabled(!canConnect || appModel.phase == .connecting)

                    if let error = appModel.lastConnectError {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Fabric")
            .onAppear {
                if let saved = appModel.settings {
                    urlText = saved.baseURL.absoluteString
                    token = saved.token
                }
            }
        }
    }

    private func probe() async {
        guard let url = parsedURL else { return }
        probing = true
        defer { probing = false }
        do {
            let status = try await GatewayAPI.probeStatus(baseURL: url)
            probeResult = status.authRequired
                ? "Reachable, but OAuth-gated — token auth will be rejected."
                : "Gateway reachable."
        } catch {
            probeResult = "Unreachable: \(error.localizedDescription)"
        }
    }
}
