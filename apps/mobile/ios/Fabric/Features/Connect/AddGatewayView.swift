import SwiftUI

/// Add a server to the library. Scan a pairing QR or enter the address plus
/// a token (loopback/tunnel) or username/password (gated). Saving stores the
/// server and connects; the library remembers it for next time.
struct AddGatewayView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    private enum Mode: String, CaseIterable, Identifiable {
        case token = "Token"
        case password = "Sign in"
        var id: String { rawValue }
    }

    @State private var label = ""
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

    private var canSave: Bool {
        guard parsedURL != nil, appModel.phase != .connecting else { return false }
        switch mode {
        case .token: return !token.trimmingCharacters(in: .whitespaces).isEmpty
        case .password: return !username.isEmpty && !password.isEmpty
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
                    Text("On the machine: `fabric serve --qr` (add `--qr-url` for a tunnel).")
                }

                Section("Server") {
                    TextField("Name (optional)", text: $label)
                        .autocorrectionDisabled()
                    TextField("http://my-machine:9119", text: $urlText)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)

                    Picker("Auth", selection: $mode) {
                        ForEach(Mode.allCases) { Text($0.rawValue).tag($0) }
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
                                .foregroundStyle(FabricTheme.textMuted)
                        }
                    }
                }

                Section {
                    Button {
                        Task { await probe() }
                    } label: {
                        if probing { ProgressView() } else { Text("Test connection") }
                    }
                    .disabled(parsedURL == nil || probing)

                    if let probeResult {
                        Text(probeResult)
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                }

                Section {
                    Button {
                        Task { await save() }
                    } label: {
                        if appModel.phase == .connecting {
                            ProgressView()
                        } else {
                            Text("Save and connect")
                        }
                    }
                    .disabled(!canSave)

                    if let error = appModel.lastConnectError {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.danger)
                    }
                }
            }
            .navigationTitle("Add server")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
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
            Task { await save() }
        } else {
            mode = .password
            probeResult = "Server requires sign-in — enter your username and password."
            Task { await resolvePasswordProvider() }
        }
    }

    private func resolvePasswordProvider() async {
        guard let url = parsedURL else { return }
        if let provider = try? await GatewayAPI.listAuthProviders(baseURL: url)
            .first(where: { $0.supportsPassword }) {
            providerName = provider.name
        }
    }

    private func save() async {
        guard let url = parsedURL else { return }
        switch mode {
        case .token:
            let gateway = appModel.saveTokenGateway(
                label: label,
                baseURL: url,
                token: token.trimmingCharacters(in: .whitespaces)
            )
            await appModel.connectToken(gateway)
        case .password:
            if providerName == nil { await resolvePasswordProvider() }
            guard let providerName else {
                probeResult = "This server offers no password sign-in (OAuth-only isn't supported yet)."
                return
            }
            let gateway = appModel.saveGatedGateway(label: label, baseURL: url, username: username)
            await appModel.connectGated(gateway, provider: providerName, password: password)
        }
        if appModel.phase == .connected { dismiss() }
    }

    private func probe() async {
        guard let url = parsedURL else { return }
        probing = true
        defer { probing = false }
        do {
            let status = try await GatewayAPI.probeStatus(baseURL: url)
            if status.authRequired {
                mode = .password
                await resolvePasswordProvider()
                probeResult = providerName == nil
                    ? "Reachable, but no password sign-in is offered (OAuth-only isn't supported yet)."
                    : "Reachable — sign-in required."
            } else {
                mode = .token
                probeResult = "Reachable — token auth."
            }
        } catch {
            probeResult = "Unreachable: \(error.localizedDescription)"
        }
    }
}

/// Password re-auth for a saved gated server whose cookie session has lapsed.
struct SignInSheet: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    let gateway: SavedGateway

    @State private var password = ""
    @State private var providerName: String?
    @State private var working = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(gateway.label).font(.headline)
                    Text(gateway.baseURL.absoluteString)
                        .font(.caption.monospaced())
                        .foregroundStyle(FabricTheme.textMuted)
                }
                Section("Sign in") {
                    LabeledContent("Username", value: gateway.username)
                    SecureField("Password", text: $password)
                        .textContentType(.password)
                }
                Section {
                    Button {
                        Task { await signIn() }
                    } label: {
                        if working { ProgressView() } else { Text("Sign in and connect") }
                    }
                    .disabled(password.isEmpty || working)
                    if let error {
                        Text(error).font(.footnote).foregroundStyle(FabricTheme.danger)
                    }
                }
            }
            .navigationTitle("Sign in")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task {
                providerName = try? await GatewayAPI.listAuthProviders(baseURL: gateway.baseURL)
                    .first(where: { $0.supportsPassword })?.name
            }
        }
    }

    private func signIn() async {
        working = true
        defer { working = false }
        guard let providerName else {
            error = "This server offers no password sign-in."
            return
        }
        await appModel.connectGated(gateway, provider: providerName, password: password)
        if appModel.phase == .connected {
            dismiss()
        } else {
            error = appModel.lastConnectError ?? "Sign-in failed."
        }
    }
}
