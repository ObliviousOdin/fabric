import SwiftUI

/// The saved Fabric library and first-run activation surface. Nothing here
/// infers that a saved gateway is online: rows describe only whether this
/// iPhone has enough local auth state to attempt a connection.
struct GatewayListView: View {
    @Environment(AppModel.self) private var appModel

    @State private var addEntry: AddGatewayEntry?
    @State private var signIn: SavedGateway?
    @State private var gatewayPendingRemoval: SavedGateway?
    @State private var showForgetFailure = false

    var body: some View {
        NavigationStack {
            ZStack {
                FabricTheme.canvas.ignoresSafeArea()
                if appModel.gateways.isEmpty {
                    FirstRunConnectView(
                        errorMessage: appModel.lastConnectError,
                        onScan: { addEntry = .scan },
                        onAdvanced: { addEntry = .advanced }
                    )
                } else {
                    savedGatewayLibrary
                }
            }
            .toolbarBackground(FabricTheme.canvas, for: .navigationBar)
            .toolbar {
                if !appModel.gateways.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            addEntry = .scan
                        } label: {
                            Label("Scan another pairing code", systemImage: "qrcode.viewfinder")
                        }
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                        .disabled(appModel.phase == .connecting)
                    }
                }
            }
            .overlay {
                if appModel.phase == .connecting {
                    ConnectingOverlay()
                }
            }
            .sheet(item: $addEntry) { entry in
                AddGatewayView(startsInAdvancedSetup: entry == .advanced)
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

    private var savedGatewayLibrary: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 16) {
                CompactFabricHeader()

                VStack(alignment: .leading, spacing: 6) {
                    Text("Choose your Fabric")
                        .font(.largeTitle.weight(.semibold))
                        .foregroundStyle(FabricTheme.text)
                    Text("Connect to a saved computer, or scan another pairing code.")
                        .font(.body)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.top, 8)

                if let error = appModel.lastConnectError {
                    ConnectErrorCard(message: error)
                }

                VStack(spacing: 12) {
                    ForEach(appModel.gateways) { gateway in
                        SavedGatewayCard(
                            gateway: gateway,
                            state: ConnectGatewayAvailability(
                                authMode: gateway.authMode,
                                canAutoConnect: appModel.canAutoConnect(gateway),
                                allowsTokenCredential: GatewayBaseURL.allowsTokenCredential(gateway.baseURL)
                            ),
                            isEnabled: appModel.phase != .connecting,
                            onConnect: { Task { await tap(gateway) } },
                            onRemove: { gatewayPendingRemoval = gateway }
                        )
                    }
                }

                Button {
                    addEntry = .scan
                } label: {
                    Label("Scan another pairing code", systemImage: "qrcode.viewfinder")
                }
                .buttonStyle(ConnectPrimaryButtonStyle())
                .disabled(appModel.phase == .connecting)

                Button("Advanced setup") {
                    addEntry = .advanced
                }
                .buttonStyle(.plain)
                .font(.headline)
                .foregroundStyle(FabricTheme.action)
                .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                .disabled(appModel.phase == .connecting)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 18)
        }
        .scrollBounceBehavior(.basedOnSize)
        .confirmationDialog(
            "Forget this Fabric?",
            isPresented: Binding(
                get: { gatewayPendingRemoval != nil },
                set: { if !$0 { gatewayPendingRemoval = nil } }
            ),
            presenting: gatewayPendingRemoval
        ) { gateway in
            Button("Forget \(gateway.label)", role: .destructive) {
                do {
                    try appModel.removeGateway(id: gateway.id)
                    gatewayPendingRemoval = nil
                } catch {
                    gatewayPendingRemoval = nil
                    showForgetFailure = true
                }
            }
            Button("Cancel", role: .cancel) {
                gatewayPendingRemoval = nil
            }
        } message: { gateway in
            Text("This removes the saved address and credential from this iPhone. It does not change the Fabric gateway on \(gateway.label).")
        }
        .alert("Couldn't forget this Fabric", isPresented: $showForgetFailure) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(AppLocalDataError.forgetGatewayUnavailable.localizedDescription)
        }
    }

    private func tap(_ gateway: SavedGateway) async {
        switch gateway.authMode {
        case .token:
            await appModel.connectToken(gateway)
        case .gated:
            // A live cookie session may reconnect without prompting. If it no
            // longer can, AppModel publishes a sign-in request only for an
            // authoritative auth failure. Offline and TLS failures remain on
            // this recovery surface instead of opening an unrelated form.
            await appModel.connectGated(gateway, provider: "", password: nil)
        }
    }
}

private enum AddGatewayEntry: String, Identifiable {
    case scan
    case advanced

    var id: String { rawValue }
}

private struct CompactFabricHeader: View {
    var body: some View {
        HStack(spacing: 10) {
            Image("FabricMark")
                .resizable()
                .scaledToFit()
                .frame(width: 38, height: 38)
                .accessibilityHidden(true)
            Text("Fabric")
                .font(.title2.weight(.semibold))
                .foregroundStyle(FabricTheme.text)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Fabric")
    }
}

private struct FirstRunConnectView: View {
    let errorMessage: String?
    let onScan: () -> Void
    let onAdvanced: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: dynamicTypeSize.isAccessibilitySize ? 24 : 28) {
                CompactFabricHeader()

                VStack(alignment: .leading, spacing: 10) {
                    Text("Connect your Fabric")
                        .font(.largeTitle.weight(.semibold))
                        .foregroundStyle(FabricTheme.text)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Scan the pairing code on your computer.")
                        .font(.title3)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }

                PairingCodeIllustration()

                if let errorMessage {
                    ConnectErrorCard(message: errorMessage)
                }

                VStack(spacing: 12) {
                    Button(action: onScan) {
                        Label("Scan pairing code", systemImage: "qrcode.viewfinder")
                    }
                    .buttonStyle(ConnectPrimaryButtonStyle())
                    .accessibilityHint("Opens camera setup before requesting camera access")

                    Button("Advanced setup", action: onAdvanced)
                        .buttonStyle(.plain)
                        .font(.headline)
                        .foregroundStyle(FabricTheme.action)
                        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                        .accessibilityHint("Enter a Fabric address and credential manually")
                }

                Label {
                    Text("Your saved credential is protected by this iPhone.")
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                } icon: {
                    Image(systemName: "key.fill")
                        .foregroundStyle(FabricTheme.action)
                }
                .frame(maxWidth: .infinity, alignment: .center)
                .accessibilityElement(children: .combine)
            }
            .padding(.horizontal, 24)
            .padding(.top, 22)
            .padding(.bottom, 28)
        }
        .scrollBounceBehavior(.basedOnSize)
    }
}

private struct PairingCodeIllustration: View {
    var body: some View {
        Image("PairingLaptopHero")
            .resizable()
            .scaledToFit()
            .aspectRatio(1024 / 1214, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
            .overlay {
                RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                    .stroke(FabricTheme.border, lineWidth: 1)
            }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("A Fabric pairing code shown on a computer")
        .accessibilityHint("Run fabric mobile on your computer to show its pairing code")
    }
}

private struct SavedGatewayCard: View {
    let gateway: SavedGateway
    let state: ConnectGatewayAvailability
    let isEnabled: Bool
    let onConnect: () -> Void
    let onRemove: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var statusColor: Color {
        switch state {
        case .ready: FabricTheme.success
        case .savedSignIn: FabricTheme.info
        case .credentialRequired, .secureTransportRequired: FabricTheme.warning
        }
    }

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    connectButton
                    HStack {
                        Spacer()
                        optionsMenu
                    }
                }
            } else {
                HStack(spacing: 8) {
                    connectButton
                    optionsMenu
                }
            }
        }
        .padding(14)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                .stroke(FabricTheme.border, lineWidth: 1)
        }
    }

    private var connectButton: some View {
        Button(action: onConnect) {
            Group {
                if dynamicTypeSize.isAccessibilitySize {
                    VStack(alignment: .leading, spacing: 10) {
                        gatewayIcon
                        gatewayDetails
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    HStack(spacing: 14) {
                        gatewayIcon
                        gatewayDetails
                        Spacer(minLength: 6)
                        Image(systemName: "chevron.right")
                            .font(.caption.bold())
                            .foregroundStyle(FabricTheme.textMuted)
                            .accessibilityHidden(true)
                    }
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .accessibilityLabel(
            "\(gateway.label), \(gateway.baseURL.host() ?? gateway.baseURL.absoluteString), \(state.label)"
        )
        .accessibilityHint(
            state.detail + (state == .secureTransportRequired
                ? " Double tap for recovery guidance."
                : " Double tap to connect.")
        )
    }

    private var gatewayIcon: some View {
        Image(systemName: "desktopcomputer")
            .font(.title3)
            .foregroundStyle(FabricTheme.action)
            .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
            .background(FabricTheme.surfaceBrand, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
    }

    private var gatewayDetails: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(gateway.label)
                .font(.headline)
                .foregroundStyle(FabricTheme.text)
                .fixedSize(horizontal: false, vertical: true)
            GatewayEndpointIdentityText(
                endpoint: gateway.baseURL.host() ?? gateway.baseURL.absoluteString,
                style: .caption,
                selectable: false
            )
            Label(state.label, systemImage: state.systemImage)
                .font(.caption)
                .foregroundStyle(statusColor)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var optionsMenu: some View {
        Menu {
            Button("Forget this Fabric", systemImage: "trash", role: .destructive, action: onRemove)
        } label: {
            Image(systemName: "ellipsis")
                .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
                .contentShape(Rectangle())
        }
        .accessibilityLabel("Options for \(gateway.label)")
        .disabled(!isEnabled)
    }
}

private struct ConnectErrorCard: View {
    let message: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(FabricTheme.danger)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text("Couldn’t connect")
                    .font(.headline)
                    .foregroundStyle(FabricTheme.text)
                Text(message)
                    .font(.subheadline)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(FabricTheme.danger)
                .frame(width: 3)
                .clipShape(.rect(cornerRadius: 2))
        }
        .accessibilityElement(children: .combine)
    }
}

private struct ConnectingOverlay: View {
    var body: some View {
        VStack(spacing: 12) {
            ProgressView()
            Text("Connecting to Fabric…")
                .font(.headline)
                .foregroundStyle(FabricTheme.text)
        }
        .padding(24)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                .stroke(FabricTheme.border, lineWidth: 1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Connecting to Fabric")
    }
}

#if DEBUG
/// Stateless visual fixtures for simulator screenshot and accessibility QA.
/// They never construct AppModel and therefore never read or mutate the real
/// saved-gateway library or Keychain.
enum ConnectExperienceDebugFixtureState: String, CaseIterable {
    case onboarding
    case returning
    case scannerDenied = "scanner-denied"
}

struct ConnectExperienceDebugFixtureView: View {
    let state: ConnectExperienceDebugFixtureState

    @State private var addEntry: AddGatewayEntry?

    var body: some View {
        Group {
            switch state {
            case .onboarding:
                ZStack {
                    FabricTheme.canvas.ignoresSafeArea()
                    FirstRunConnectView(
                        errorMessage: nil,
                        onScan: { addEntry = .scan },
                        onAdvanced: { addEntry = .advanced }
                    )
                }
            case .returning:
                ReturningConnectFixture()
            case .scannerDenied:
                PairingScannerFlow(
                    initialPermission: .denied,
                    onScan: { _ in .accepted },
                    onCancel: {},
                    onAdvancedSetup: {}
                )
            }
        }
        .tint(FabricTheme.action)
        .sheet(item: $addEntry) { entry in
            AddGatewayView(startsInAdvancedSetup: entry == .advanced)
        }
    }
}

private struct ReturningConnectFixture: View {
    private let gateway = SavedGateway(
        id: "connect-fixture-personal-mac",
        label: "Personal Mac",
        baseURL: URL(string: "https://personal-mac.example")!,
        authMode: .token
    )

    var body: some View {
        NavigationStack {
            ZStack {
                FabricTheme.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        CompactFabricHeader()
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Choose your Fabric")
                                .font(.largeTitle.weight(.semibold))
                                .foregroundStyle(FabricTheme.text)
                            Text("Connect to a saved computer, or scan another pairing code.")
                                .font(.body)
                                .foregroundStyle(FabricTheme.textMuted)
                        }
                        SavedGatewayCard(
                            gateway: gateway,
                            state: .ready,
                            isEnabled: true,
                            onConnect: {},
                            onRemove: {}
                        )
                        Button(action: {}) {
                            Label("Scan another pairing code", systemImage: "qrcode.viewfinder")
                        }
                        .buttonStyle(ConnectPrimaryButtonStyle())
                        Button("Advanced setup", action: {})
                            .font(.headline)
                            .foregroundStyle(FabricTheme.action)
                            .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                    }
                    .padding(20)
                }
            }
            .toolbarBackground(FabricTheme.canvas, for: .navigationBar)
        }
    }
}
#endif
