import SwiftUI

/// First-run / reconnect screen. Three ways in:
///
/// 1. **Scan** the pairing QR from `fabric serve --qr` — token QRs connect
///    immediately; gated QRs drop into the sign-in form.
/// 2. Type a URL + session token (loopback/tunnel gateways).
/// 3. Type a URL + username/password (gated gateways, e.g. a direct
///    Tailscale bind with the bundled password provider).
struct ConnectView: View {
    @Environment(AppModel.self) private var appModel

    private enum Mode: String, CaseIterable, Identifiable {
        case token = "Token"
        case password = "Sign in"
        var id: String { rawValue }
    }

    @State private var urlText = ""
    @State private var mode: Mode = .token
    @State private var token = ""
    @State private var username = ""
    @State private var password = ""
    @State private var providerName: String?
    @State private var probeResult: String?
    @State private var probing = false
    @State private var showScanner = false

    private var parsedURL: URL? {
        guard
            let url = URL(string: urlText.trimmingCharacters(in: .whitespacesAndNewlines)),
            url.scheme == "http" || url.scheme == "https",
            url.host() != nil
        else { return nil }
        return url
    }

    private var canConnect: Bool {
        guard parsedURL != nil, appModel.phase != .connecting else { return false }
        switch mode {
        case .token:
            return !token.trimmingCharacters(in: .whitespaces).isEmpty
        case .password:
            return !username.isEmpty && !password.isEmpty
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Button {
                        showScanner = true
                    } label: {
                        Label("Scan pairing QR", systemImage: "qrcode.viewfinder")
                    }
                } footer: {
                    Text("On the machine running Fabric: `fabric serve --qr` (or `--qr-url` for a tunnel). Tailscale, LAN, and SSH-tunnel addresses all work.")
                }

                Section("Gateway") {
                    TextField("http://my-machine:9119", text: $urlText)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)

                    Picker("Auth", selection: $mode) {
                        ForEach(Mode.allCases) { mode in
                            Text(mode.rawValue).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)

                    switch mode {
                    case .token:
                        SecureField("Session token", text: $token)
                    case .password:
                        TextField("Username", text: $username)
                            .textContentType(.username)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                        SecureField("Password", text: $password)
                            .textContentType(.password)
                        if let providerName {
                            Text("Provider: \(providerName)")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
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
                        Task { await connect() }
                    } label: {
                        if appModel.phase == .connecting {
                            ProgressView()
                        } else {
                            Text("Connect")
                        }
                    }
                    .disabled(!canConnect)

                    if let error = appModel.lastConnectError {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Fabric")
            .sheet(isPresented: $showScanner) {
                NavigationStack {
                    QRScannerView { scanned in
                        showScanner = false
                        handleScan(scanned)
                    }
                    .ignoresSafeArea()
                    .navigationTitle("Scan pairing QR")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button("Cancel") { showScanner = false }
                        }
                    }
                }
            }
            .onAppear {
                if let saved = appModel.settings {
                    urlText = saved.baseURL.absoluteString
                    token = saved.token
                    username = saved.username
                    mode = saved.authMode == .gated ? .password : .token
                }
            }
        }
    }

    private func handleScan(_ raw: String) {
        guard let payload = PairingPayload.parse(raw) else {
            probeResult = "Scanned code is not a Fabric pairing QR."
            return
        }
        urlText = payload.baseURL.absoluteString
        if let scannedToken = payload.token {
            mode = .token
            token = scannedToken
            // Token QRs are complete credentials — connect immediately.
            Task { await connect() }
        } else {
            mode = .password
            probeResult = "Gateway requires sign-in — enter your username and password."
            Task { await resolvePasswordProvider() }
        }
    }

    /// Find the gateway's password-capable provider (`/api/auth/providers`).
    private func resolvePasswordProvider() async {
        guard let url = parsedURL else { return }
        do {
            let providers = try await GatewayAPI.listAuthProviders(baseURL: url)
            if let passwordProvider = providers.first(where: { $0.supportsPassword }) {
                providerName = passwordProvider.name
            } else if !providers.isEmpty {
                probeResult = "This gateway only offers OAuth sign-in (\(providers.map(\.displayName).joined(separator: ", "))), which the app does not support yet."
            }
        } catch {
            // Non-fatal: connect() re-resolves and surfaces a real error.
        }
    }

    private func connect() async {
        guard let url = parsedURL else { return }
        switch mode {
        case .token:
            await appModel.connect(settings: ConnectionSettings(
                baseURL: url,
                token: token.trimmingCharacters(in: .whitespaces)
            ))
        case .password:
            if providerName == nil {
                await resolvePasswordProvider()
            }
            guard let providerName else { return }
            await appModel.connectGated(
                baseURL: url,
                provider: providerName,
                username: username,
                password: password
            )
        }
    }

    private func probe() async {
        guard let url = parsedURL else { return }
        probing = true
        defer { probing = false }
        do {
            let status = try await GatewayAPI.probeStatus(baseURL: url)
            if status.authRequired {
                probeResult = "Gateway reachable — sign-in required."
                mode = .password
                await resolvePasswordProvider()
            } else {
                probeResult = "Gateway reachable — token auth."
                mode = .token
            }
        } catch {
            probeResult = "Unreachable: \(error.localizedDescription)"
        }
    }
}
