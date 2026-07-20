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
    @State private var otp = ""
    @State private var providerName: String?
    @State private var requiresTotp = false
    @State private var probeResult: String?
    @State private var probing = false
    @State private var showScanner = false

    private var parsedURL: URL? {
        GatewayBaseURL.parse(urlText)
    }

    private var canSave: Bool {
        guard parsedURL != nil, appModel.phase != .connecting else { return false }
        switch mode {
        case .token: return !token.trimmingCharacters(in: .whitespaces).isEmpty
        case .password:
            let credsOK = !username.isEmpty && !password.isEmpty
            return credsOK && (!requiresTotp || otp.trimmingCharacters(in: .whitespaces).count >= 6)
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
                    Text("On the machine: `fabric mobile` (add `--qr-url` for a tunnel).")
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
                        if requiresTotp {
                            TextField("6-digit code", text: $otp)
                                .keyboardType(.numberPad)
                                .textContentType(.oneTimeCode)
                        }
                        if let providerName {
                            Text(requiresTotp
                                 ? "Provider: \(providerName) · code from your authenticator app"
                                 : "Provider: \(providerName)")
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
                    QRScannerView(isActive: $showScanner) { scanned in
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
        if payload.enrollment != nil {
            probeResult = "This QR requires secure device enrollment. Update Fabric Mobile and the gateway together, then scan a new QR."
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
            requiresTotp = provider.requiresTotp
        }
    }

    private func save() async {
        guard let url = parsedURL else { return }
        switch mode {
        case .token:
            do {
                let gateway = try appModel.saveTokenGateway(
                    label: label,
                    baseURL: url,
                    token: token.trimmingCharacters(in: .whitespaces)
                )
                await appModel.connectToken(gateway)
            } catch {
                // Keep credential errors generic: no token or Security status
                // should enter UI text, analytics, or logs.
                probeResult = GatewayStoreError.credentialStorageUnavailable.localizedDescription
            }
        case .password:
            if providerName == nil { await resolvePasswordProvider() }
            guard let providerName else {
                probeResult = "This server offers no password sign-in (OAuth-only isn't supported yet)."
                return
            }
            let gateway = appModel.saveGatedGateway(label: label, baseURL: url, username: username)
            await appModel.connectGated(
                gateway,
                provider: providerName,
                password: password,
                otp: otp.trimmingCharacters(in: .whitespaces)
            )
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

    @State private var username: String
    @State private var password = ""
    @State private var otp = ""
    @State private var providerName: String?
    @State private var requiresTotp = false
    @State private var working = false
    @State private var error: String?

    init(gateway: SavedGateway) {
        self.gateway = gateway
        _username = State(initialValue: gateway.username)
    }

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
                    TextField("Username", text: $username)
                        .textInputAutocapitalization(.never)
                        .textContentType(.username)
                    SecureField("Password", text: $password)
                        .textContentType(.password)
                    if requiresTotp {
                        TextField("6-digit code", text: $otp)
                            .keyboardType(.numberPad)
                            .textContentType(.oneTimeCode)
                    }
                }
                Section {
                    Button {
                        Task { await signIn() }
                    } label: {
                        if working { ProgressView() } else { Text("Sign in and connect") }
                    }
                    .disabled(
                        username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || password.isEmpty || working
                            || (requiresTotp && otp.trimmingCharacters(in: .whitespaces).count < 6)
                    )
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
                if let provider = try? await GatewayAPI.listAuthProviders(baseURL: gateway.baseURL)
                    .first(where: { $0.supportsPassword }) {
                    providerName = provider.name
                    requiresTotp = provider.requiresTotp
                }
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
        let updated = appModel.saveGatedGateway(
            label: gateway.label,
            baseURL: gateway.baseURL,
            username: username.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        await appModel.connectGated(
            updated,
            provider: providerName,
            password: password,
            otp: otp.trimmingCharacters(in: .whitespaces)
        )
        if appModel.phase == .connected {
            dismiss()
        } else {
            error = appModel.lastConnectError ?? "Sign-in failed."
        }
    }
}
