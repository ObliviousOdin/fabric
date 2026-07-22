import SwiftUI

/// Scanner-led gateway activation. Manual addresses and credentials remain
/// available, but stay behind Advanced setup so first launch has one primary
/// path. Saving and auth continue to use AppModel's existing Keychain,
/// password/TOTP, pairing-classification, and connection boundaries.
struct AddGatewayView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    private enum Mode: String, CaseIterable, Identifiable {
        case token = "Token"
        case password = "Sign in"
        var id: String { rawValue }
    }

    @State private var showingAdvanced: Bool
    @State private var label = ""
    @State private var urlText = ""
    @State private var mode: Mode = .token
    @State private var rememberPassword = true
    @State private var credentialState = GatewayEndpointCredentialState()
    @State private var providerName: String?
    @State private var requiresTotp = false
    @State private var providerDiscoveryFailed = false
    @State private var resolvingProvider = false
    @State private var providerDiscoveryFence = GatewayEndpointRequestFence()
    @State private var pairingAttemptInFlight = false
    @State private var notice: String?
    @State private var probing = false
    @State private var probeFence = GatewayEndpointRequestFence()
    @State private var showScanner = false

    private enum ProviderDiscoveryOutcome: Equatable {
        case available
        case unsupported
        case failed
        case stale
    }

    init(startsInAdvancedSetup: Bool = false) {
        _showingAdvanced = State(initialValue: startsInAdvancedSetup)
    }

    private var parsedURL: URL? {
        GatewayBaseURL.parse(urlText)
    }

    private var urlFieldBinding: Binding<String> {
        Binding(
            get: { urlText },
            set: { updateURLText($0) }
        )
    }

    private var modeBinding: Binding<Mode> {
        Binding(
            get: { mode },
            set: { updateMode($0) }
        )
    }

    private var canSave: Bool {
        guard let parsedURL, appModel.phase != .connecting else { return false }
        switch mode {
        case .token:
            return GatewayTransportPresentation.allowsTokenCredential(parsedURL)
                && (!credentialState.token.trimmingCharacters(in: .whitespaces).isEmpty
                    || scannedRetryGateway != nil)
        case .password:
            let credsOK = !credentialState.username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !credentialState.password.isEmpty
            return credsOK && !resolvingProvider
                && (!requiresTotp || credentialState.otp.trimmingCharacters(in: .whitespaces).count >= 6)
        }
    }

    /// Scanned tokens move directly to Keychain. A failed network handshake
    /// retries from that protected credential rather than copying it back into
    /// observable SwiftUI state.
    private var scannedRetryGateway: SavedGateway? {
        guard
            mode == .token,
            credentialState.token.trimmingCharacters(in: .whitespaces).isEmpty,
            let scannedGatewayID = credentialState.scannedGatewayID,
            let parsedURL
        else { return nil }
        let endpointKey = SavedGateway.endpointKey(for: parsedURL)
        return appModel.gateways.first {
            $0.id == scannedGatewayID && $0.endpointKey == endpointKey
        }
    }

    var body: some View {
        Group {
            if showingAdvanced {
                advancedNavigation
            } else {
                initialScanner
            }
        }
        .sheet(isPresented: $showScanner) {
            PairingScannerFlow(
                onScan: { raw in
                    let disposition = handleScan(raw)
                    if disposition == .accepted { showScanner = false }
                    return disposition
                },
                onCancel: { showScanner = false },
                onAdvancedSetup: {
                    showScanner = false
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showingAdvanced = true
                    }
                }
            )
        }
    }

    private var initialScanner: some View {
        PairingScannerFlow(
            onScan: handleScan,
            onCancel: { dismiss() },
            onAdvancedSetup: {
                withAnimation(.easeInOut(duration: 0.2)) {
                    showingAdvanced = true
                }
            }
        )
    }

    private var advancedNavigation: some View {
        NavigationStack {
            ZStack {
                FabricTheme.canvas.ignoresSafeArea()
                advancedSetup
            }
            .navigationTitle("Advanced setup")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(FabricTheme.canvas, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                        .frame(minHeight: FabricTheme.minTarget)
                }
            }
        }
    }

    private var advancedSetup: some View {
        Form {
            Section {
                Button {
                    notice = nil
                    showScanner = true
                } label: {
                    Label("Scan pairing code instead", systemImage: "qrcode.viewfinder")
                        .frame(minHeight: FabricTheme.minTarget)
                }
                .disabled(pairingAttemptInFlight || appModel.phase == .connecting)
            } footer: {
                Text("Scanning is the fastest setup path. Use the fields below only when you already have a Fabric address and credential.")
            }

            Section("Fabric computer") {
                TextField("Name (optional)", text: $label)
                    .autocorrectionDisabled()
                    .accessibilityLabel("Fabric computer name")
                TextField("https://my-computer.example", text: urlFieldBinding)
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .accessibilityLabel("Fabric server address")

                Picker("Authentication", selection: modeBinding) {
                    ForEach(Mode.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)

                switch mode {
                case .token:
                    SecureField("Session token", text: $credentialState.token)
                        .textContentType(.password)
                case .password:
                    TextField("Username", text: $credentialState.username)
                        .textContentType(.username)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    SecureField("Password", text: $credentialState.password)
                        .textContentType(.password)
                    if requiresTotp {
                        TextField("6-digit code", text: $credentialState.otp)
                            .keyboardType(.numberPad)
                            .textContentType(.oneTimeCode)
                    }
                    if let parsedURL, GatewayTransportPresentation.allowsTokenCredential(parsedURL) {
                        Toggle("Remember password on this iPhone", isOn: $rememberPassword)
                            .frame(minHeight: FabricTheme.minTarget)
                        if rememberPassword {
                            Text("The password is protected by the device Keychain and used to sign back in when this Fabric's session expires.")
                                .font(.footnote)
                                .foregroundStyle(FabricTheme.textMuted)
                        }
                    }
                    if let providerName {
                        Text(requiresTotp
                             ? "Provider: \(providerName) · enter the code from your authenticator app."
                             : "Provider: \(providerName)")
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.textMuted)
                    } else if resolvingProvider {
                        ProgressView("Checking sign-in options…")
                    }
                }

                if let parsedURL,
                   mode == .token,
                   !GatewayTransportPresentation.allowsTokenCredential(parsedURL) {
                    PairingNotice(
                        message: "Token connections require HTTPS. Use a trusted HTTPS or Tailscale Serve address before entering a token.",
                        isError: true
                    )
                } else if let parsedURL,
                          let warning = GatewayTransportPresentation.warning(for: parsedURL) {
                    PairingNotice(message: warning, isError: true)
                }
            }

            Section {
                Button {
                    Task { await save() }
                } label: {
                    HStack {
                        Spacer()
                        if appModel.phase == .connecting {
                            ProgressView()
                                .tint(FabricTheme.textOnBrand)
                        } else {
                            Text(scannedRetryGateway == nil ? "Save and connect" : "Retry connection")
                                .font(.headline)
                        }
                        Spacer()
                    }
                    .frame(minHeight: FabricTheme.minTarget)
                }
                .listRowBackground(canSave ? FabricTheme.action : FabricTheme.surfaceInset)
                .foregroundStyle(canSave ? FabricTheme.textOnBrand : FabricTheme.textDisabled)
                .disabled(!canSave)

                Button {
                    Task { await probe() }
                } label: {
                    HStack {
                        Spacer()
                        if probing { ProgressView() } else { Text("Test address") }
                        Spacer()
                    }
                    .frame(minHeight: FabricTheme.minTarget)
                }
                .disabled(parsedURL == nil || probing || appModel.phase == .connecting)
            }

            if let notice {
                Section {
                    PairingNotice(message: notice)
                }
            }

            if let error = appModel.lastConnectError {
                Section {
                    PairingNotice(message: error, isError: true)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(FabricTheme.canvas)
    }

    private func handleScan(_ raw: String) -> PairingScannerDisposition {
        switch appModel.pairingOutcome(for: .scan(raw)) {
        case .invalid:
            credentialState.scannedGatewayID = nil
            let message = "That isn’t a Fabric pairing code. Show a new code with `fabric mobile`, then scan again."
            notice = message
            return .retry(message: message)
        case .unsupportedEnrollment:
            credentialState.scannedGatewayID = nil
            let message = "This code uses a newer enrollment flow that this app cannot complete yet. Update Fabric Mobile and the gateway together, then scan a new code."
            notice = message
            return .retry(message: message)
        case .token(let acceptance):
            guard !pairingAttemptInFlight else {
                let message = "Pairing is already in progress."
                notice = message
                return .retry(message: message)
            }
            pairingAttemptInFlight = true
            credentialState.scannedGatewayID = nil
            updateURLText(acceptance.target.baseURL.absoluteString)
            updateMode(.token)
            credentialState.token = ""
            Task { await connectScannedToken(acceptance) }
            return .accepted
        case .gated(let target):
            credentialState.scannedGatewayID = nil
            updateURLText(target.baseURL.absoluteString)
            updateMode(.password)
            credentialState.username = target.existingUsername(in: appModel.gateways)
            credentialState.password = ""
            credentialState.otp = ""
            providerName = nil
            requiresTotp = false
            providerDiscoveryFailed = false
            notice = "This Fabric requires sign-in. Enter your username and password to continue."
            showingAdvanced = true
            Task { await resolvePasswordProvider() }
            return .accepted
        }
    }

    private func connectScannedToken(_ acceptance: PairingTokenAcceptance) async {
        defer { pairingAttemptInFlight = false }
        do {
            switch try await appModel.connectPairingToken(acceptance) {
            case .attempted(let gateway):
                credentialState.scannedGatewayID = gateway.id
            case .alreadyInFlight:
                notice = "Pairing is already in progress for this Fabric."
            }
        } catch {
            notice = GatewayStoreError.credentialStorageUnavailable.localizedDescription
        }
        if appModel.phase == .connected {
            dismiss()
        } else if credentialState.scannedGatewayID != nil {
            showingAdvanced = true
            notice = "The pairing code was saved, but Fabric couldn’t reach this computer. Make sure Fabric is running and this iPhone is on the same network or tailnet, then retry."
        }
    }

    private func resolvePasswordProvider() async -> ProviderDiscoveryOutcome {
        guard let url = parsedURL, mode == .password else { return .stale }
        let request = providerDiscoveryFence.begin(for: url)
        resolvingProvider = true
        providerDiscoveryFailed = false
        providerName = nil
        requiresTotp = false
        defer {
            if providerDiscoveryFence.accepts(
                request,
                currentURL: parsedURL,
                applicable: mode == .password
            ) {
                resolvingProvider = false
            }
        }
        do {
            let provider = try await GatewayAPI.listAuthProviders(baseURL: url)
                .first(where: { $0.supportsPassword })
            guard providerDiscoveryFence.accepts(
                request,
                currentURL: parsedURL,
                applicable: mode == .password
            ) else { return .stale }
            guard let provider else { return .unsupported }
            providerName = provider.name
            requiresTotp = provider.requiresTotp
            return .available
        } catch {
            guard providerDiscoveryFence.accepts(
                request,
                currentURL: parsedURL,
                applicable: mode == .password
            ) else { return .stale }
            providerDiscoveryFailed = true
            return .failed
        }
    }

    private func save() async {
        guard let url = parsedURL else { return }
        notice = nil
        switch mode {
        case .token:
            if let scannedRetryGateway {
                await appModel.connectToken(scannedRetryGateway)
            } else {
                do {
                    let gateway = try appModel.saveTokenGateway(
                        label: label.trimmingCharacters(in: .whitespacesAndNewlines),
                        baseURL: url,
                        token: credentialState.token.trimmingCharacters(in: .whitespaces)
                    )
                    await appModel.connectToken(gateway)
                } catch {
                    notice = GatewayStoreError.credentialStorageUnavailable.localizedDescription
                }
            }
        case .password:
            let requestedEndpoint = SavedGateway.endpointKey(for: url)
            if providerName == nil { _ = await resolvePasswordProvider() }
            guard
                mode == .password,
                let currentURL = parsedURL,
                SavedGateway.endpointKey(for: currentURL) == requestedEndpoint
            else { return }
            guard let providerName else {
                notice = providerDiscoveryFailed
                    ? "Fabric couldn’t load this server’s sign-in options. Check the connection, then try again."
                    : "This Fabric does not offer password sign-in. OAuth sign-in is not supported in this app yet."
                return
            }
            let gateway = appModel.saveGatedGateway(
                label: label.trimmingCharacters(in: .whitespacesAndNewlines),
                baseURL: currentURL,
                username: credentialState.username.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            await appModel.connectGated(
                gateway,
                provider: providerName,
                password: credentialState.password,
                otp: credentialState.otp.trimmingCharacters(in: .whitespaces),
                rememberPassword: GatewayTransportPresentation.allowsTokenCredential(currentURL)
                    ? rememberPassword
                    : nil
            )
        }
        if appModel.phase == .connected {
            dismiss()
        } else if notice == nil {
            notice = "Fabric couldn’t connect. Check that the computer is running and reachable, then try again."
        }
    }

    private func probe() async {
        guard let url = parsedURL else { return }
        let request = probeFence.begin(for: url)
        probing = true
        notice = nil
        defer {
            if probeFence.accepts(request, currentURL: parsedURL) {
                probing = false
            }
        }
        do {
            let status = try await GatewayAPI.probeStatus(baseURL: url)
            guard probeFence.accepts(request, currentURL: parsedURL) else { return }
            if status.authRequired {
                updateMode(.password, preservingProbe: true)
                let outcome = await resolvePasswordProvider()
                guard probeFence.accepts(request, currentURL: parsedURL) else { return }
                if outcome == .failed {
                    notice = "Address found, but Fabric couldn’t load its sign-in options. Check the connection, then try again."
                } else if outcome == .unsupported {
                    notice = "Address found, but it does not offer password sign-in. OAuth sign-in is not supported in this app yet."
                } else if outcome == .available {
                    notice = "Address found. Sign-in is required."
                }
            } else {
                updateMode(.token, preservingProbe: true)
                notice = "Address found. Enter its session token to connect."
            }
        } catch {
            guard probeFence.accepts(request, currentURL: parsedURL) else { return }
            notice = ConnectRouteDiagnosis.message(for: error)
        }
    }

    private func updateURLText(_ value: String) {
        guard value != urlText else { return }
        credentialState.resetIfEndpointChanged(from: urlText, to: value)
        urlText = value
        invalidateProviderDiscovery()
        probeFence.invalidate()
        probing = false
        notice = nil
    }

    private func updateMode(_ value: Mode, preservingProbe: Bool = false) {
        guard value != mode else { return }
        mode = value
        invalidateProviderDiscovery()
        if !preservingProbe {
            probeFence.invalidate()
            probing = false
        }
    }

    private func invalidateProviderDiscovery() {
        providerDiscoveryFence.invalidate()
        resolvingProvider = false
        providerDiscoveryFailed = false
        providerName = nil
        requiresTotp = false
    }
}

private struct PairingNotice: View {
    let message: String
    var isError = false

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: isError ? "exclamationmark.circle.fill" : "info.circle.fill")
                .foregroundStyle(isError ? FabricTheme.danger : FabricTheme.info)
                .accessibilityHidden(true)
            Text(message)
                .font(.footnote)
                .foregroundStyle(FabricTheme.textMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
        .accessibilityElement(children: .combine)
    }
}

/// Password re-auth for a saved gated Fabric whose cookie session has lapsed.
struct SignInSheet: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    let gateway: SavedGateway

    @State private var username: String
    @State private var password = ""
    @State private var otp = ""
    @State private var rememberPassword = true
    @State private var providerName: String?
    @State private var requiresTotp = false
    @State private var providerDiscoveryFailed = false
    @State private var resolvingProvider = true
    @State private var working = false
    @State private var error: String?

    init(gateway: SavedGateway) {
        self.gateway = gateway
        _username = State(initialValue: gateway.username)
    }

    private var canKeepPassword: Bool {
        GatewayTransportPresentation.allowsTokenCredential(gateway.baseURL)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(gateway.label).font(.headline)
                            GatewayEndpointIdentityText(
                                endpoint: gateway.baseURL.host() ?? gateway.baseURL.absoluteString,
                                style: .caption
                            )
                        }
                    } icon: {
                        Image(systemName: "desktopcomputer")
                            .foregroundStyle(FabricTheme.action)
                    }
                }
                if let warning = GatewayTransportPresentation.warning(for: gateway.baseURL) {
                    Section("Transport") {
                        PairingNotice(message: warning, isError: true)
                    }
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
                    if canKeepPassword {
                        Toggle("Remember password on this iPhone", isOn: $rememberPassword)
                            .frame(minHeight: FabricTheme.minTarget)
                        if rememberPassword {
                            Text("The password is protected by the device Keychain and used to sign back in when this Fabric's session expires.")
                                .font(.footnote)
                                .foregroundStyle(FabricTheme.textMuted)
                        }
                    }
                    if resolvingProvider {
                        ProgressView("Checking sign-in options…")
                    } else if providerDiscoveryFailed {
                        PairingNotice(
                            message: "Fabric couldn’t load this server’s sign-in options. Check the connection, then try again.",
                            isError: true
                        )
                        Button("Retry sign-in options") {
                            Task { await resolvePasswordProvider() }
                        }
                        .frame(minHeight: FabricTheme.minTarget)
                    } else if providerName == nil {
                        PairingNotice(
                            message: "This Fabric does not offer password sign-in. OAuth sign-in is not supported in this app yet."
                        )
                    }
                }
                Section {
                    Button {
                        Task { await signIn() }
                    } label: {
                        HStack {
                            Spacer()
                            if working { ProgressView() } else { Text("Sign in and connect") }
                            Spacer()
                        }
                        .frame(minHeight: FabricTheme.minTarget)
                    }
                    .disabled(
                        username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || password.isEmpty || working
                            || providerName == nil || resolvingProvider
                            || (requiresTotp && otp.trimmingCharacters(in: .whitespaces).count < 6)
                    )
                    if let error {
                        PairingNotice(message: error, isError: true)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(FabricTheme.canvas)
            .navigationTitle("Sign in")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                        .frame(minHeight: FabricTheme.minTarget)
                }
            }
            .task {
                await resolvePasswordProvider()
            }
        }
    }

    private func signIn() async {
        working = true
        defer { working = false }
        guard let providerName else {
            error = providerDiscoveryFailed
                ? "Fabric couldn’t load this server’s sign-in options. Check the connection, then try again."
                : "This Fabric does not offer password sign-in."
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
            otp: otp.trimmingCharacters(in: .whitespaces),
            rememberPassword: canKeepPassword ? rememberPassword : nil
        )
        if appModel.phase == .connected {
            dismiss()
        } else {
            error = appModel.lastConnectError ?? "Sign-in failed. Check your details and try again."
        }
    }

    private func resolvePasswordProvider() async {
        resolvingProvider = true
        providerDiscoveryFailed = false
        providerName = nil
        requiresTotp = false
        error = nil
        defer { resolvingProvider = false }
        do {
            let provider = try await GatewayAPI.listAuthProviders(baseURL: gateway.baseURL)
                .first(where: { $0.supportsPassword })
            guard let provider else { return }
            providerName = provider.name
            requiresTotp = provider.requiresTotp
            // A TOTP provider can never auto-sign-in with a stale code, so
            // this sheet appears on every session lapse. Prefill the kept
            // password so only the fresh 6-digit code needs typing.
            if provider.requiresTotp,
               password.isEmpty,
               let kept = GatewayStore.password(id: gateway.id),
               !kept.isEmpty {
                password = kept
            }
        } catch {
            providerDiscoveryFailed = true
        }
    }
}
