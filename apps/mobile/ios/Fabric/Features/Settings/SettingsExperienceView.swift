import SwiftUI
import UIKit

/// Production entry point for the connected app shell. It intentionally owns
/// the server-management confirmations so every entry path keeps the same
/// offboarding language and client-disconnect semantics.
struct SettingsRootView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.scenePhase) private var scenePhase

    @State private var permissions = SettingsPermissionInventory.current()
    @State private var showPairing = false

    var body: some View {
        SettingsExperienceContent(
            presentation: SettingsExperiencePresentation(appModel: appModel),
            permissions: permissions,
            actions: SettingsExperienceActions(
                onSwitchServer: { appModel.disconnect() },
                onRepairServer: { showPairing = true },
                onForgetServer: {
                    guard let gatewayID = appModel.activeGatewayId else { return }
                    try appModel.removeGateway(id: gatewayID)
                },
                onClearCachedPresentationData: {
                    try appModel.clearCachedPresentationData()
                },
                onResetLocalApp: { try appModel.resetLocalAppData() },
                onOpenSystemSettings: Self.openSystemSettings
            )
        )
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showPairing) {
            AddGatewayView()
                .environment(appModel)
        }
        .onAppear(perform: refreshPermissions)
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            refreshPermissions()
        }
    }

    private func refreshPermissions() {
        permissions = .current()
    }

    private static func openSystemSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }
}

struct SettingsExperienceActions {
    let onSwitchServer: () -> Void
    let onRepairServer: () -> Void
    let onForgetServer: () throws -> Void
    let onClearCachedPresentationData: () throws -> Void
    let onResetLocalApp: () throws -> Void
    let onOpenSystemSettings: () -> Void
}

struct SettingsExperienceContent: View {
    let presentation: SettingsExperiencePresentation
    let permissions: SettingsPermissionInventory
    let actions: SettingsExperienceActions

    // Optional so the deterministic debug fixture can render without ever
    // constructing an AppModel; the pet row then presents as unsupported.
    @Environment(AppModel.self) private var appModel: AppModel?

    @State private var pendingServerAction: SettingsServerManagementAction?
    @State private var localDataAlert: SettingsLocalDataAlert?
    @State private var showPetPicker = false
    @State private var petActionError: String?
    @AppStorage(DeviceVoicePreferences.selectedVoiceIdentifierKey)
    private var selectedVoiceIdentifier = ""
    @AppStorage(ConnectedAppTabPreferences.storageKey)
    private var hiddenTabsRaw = ""

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 24) {
                serverSection
                fabricLinkSection
                personalizationSection
                permissionsSection
                aboutSection
                privacySection
                serverManagementSection
                deviceDataSection
            }
            .padding(.horizontal, 20)
            .padding(.top, 16)
            .padding(.bottom, 40)
        }
        .background(FabricTheme.canvas.ignoresSafeArea())
        .sheet(isPresented: $showPetPicker) {
            if let appModel {
                SettingsPetPickerSheet(appModel: appModel)
            }
        }
        .confirmationDialog(
            pendingServerAction?.confirmationTitle ?? "Server action",
            isPresented: Binding(
                get: { pendingServerAction != nil },
                set: { isPresented in
                    if !isPresented { pendingServerAction = nil }
                }
            ),
            titleVisibility: .visible
        ) {
            confirmationButtons
        } message: {
            Text(pendingServerAction?.confirmationMessage(
                disconnectPosture: presentation.clientDisconnectPosture
            ) ?? "")
        }
        .alert(item: $localDataAlert) { alert in
            Alert(
                title: Text(alert.title),
                message: Text(alert.message),
                dismissButton: .default(Text("OK"))
            )
        }
    }

    private var serverSection: some View {
        SettingsExperienceSection(title: "Server") {
            VStack(alignment: .leading, spacing: 16) {
                SettingsStatusHeader(status: presentation.connection)

                if let gateway = presentation.gateway {
                    Divider().overlay(FabricTheme.border)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(gateway.label)
                            .font(.title3.weight(.semibold))
                            .foregroundStyle(FabricTheme.text)
                        GatewayEndpointIdentityText(
                            endpoint: gateway.endpoint,
                            style: .footnote
                        )
                        Label(gateway.authentication, systemImage: "key.fill")
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.textMuted)
                            .padding(.top, 3)
                        Label(
                            gateway.transport,
                            systemImage: gateway.transportWarning == nil
                                ? "lock.shield.fill"
                                : "exclamationmark.triangle.fill"
                        )
                        .font(.footnote)
                        .foregroundStyle(
                            gateway.transportWarning == nil
                                ? FabricTheme.textMuted
                                : FabricTheme.warning
                        )
                        if let warning = gateway.transportWarning {
                            Text(warning)
                                .font(.footnote)
                                .foregroundStyle(FabricTheme.warning)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("Connected server")
                    .accessibilityValue("\(gateway.label), \(gateway.endpoint), \(gateway.authentication), \(gateway.transport)")
                } else {
                    Text("No server identity is available until this phone connects to a Fabric gateway.")
                        .font(.body)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Divider().overlay(FabricTheme.border)
                SettingsStatusHeader(status: presentation.execution)
            }
        }
    }

    private var fabricLinkSection: some View {
        SettingsExperienceSection(title: "Fabric Link") {
            NavigationLink {
                FabricLinkMachinesView()
            } label: {
                SettingsNavigationRow(
                    title: "Linked machines",
                    detail: "Dispatch Work or open an exact `/remote` session with device-key E2EE",
                    systemImage: "lock.shield.fill"
                )
            }
            .buttonStyle(.plain)
            .accessibilityHint("Manage end-to-end encrypted machine access without social login")
        }
    }

    private var personalizationSection: some View {
        SettingsExperienceSection(title: "Personalization") {
            VStack(alignment: .leading, spacing: 0) {
                petRows
                Divider().overlay(FabricTheme.border)
                voiceRow
                Divider().overlay(FabricTheme.border)
                pagesRows
            }
        }
    }

    @ViewBuilder
    private var pagesRows: some View {
        let availability = ConnectedAppTabAvailability.resolve(
            negotiation: appModel?.capabilityNegotiation ?? nil
        )
        let hideable = ConnectedAppTabPolicy.hideableTabs(availability: availability)
        let hidden = ConnectedAppTabPreferences.parse(hiddenTabsRaw)

        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "square.grid.2x2")
                    .foregroundStyle(FabricTheme.textMuted)
                    .frame(width: 24, height: 24)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Pages")
                        .font(.body.weight(.medium))
                        .foregroundStyle(FabricTheme.text)
                    Text("Choose which pages appear in the tab bar. Home and Settings always stay. Hidden pages return with Reset local app data.")
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.vertical, 12)
            .accessibilityElement(children: .combine)

            ForEach(hideable, id: \.self) { tab in
                Divider().overlay(FabricTheme.border)
                pageToggleRow(
                    tab: tab,
                    isVisible: !hidden.contains(tab.rawValue)
                )
            }
        }
    }

    private func pageToggleRow(tab: ConnectedAppTab, isVisible: Bool) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: tab.tabSystemImage)
                .foregroundStyle(FabricTheme.textMuted)
                .frame(width: 24, height: 24)
                .accessibilityHidden(true)
            Text(tab.tabTitle)
                .font(.body.weight(.medium))
                .foregroundStyle(FabricTheme.text)
            Spacer(minLength: 12)
            Toggle("Show \(tab.tabTitle)", isOn: pageVisibilityBinding(tab: tab))
                .labelsHidden()
                .tint(FabricTheme.action)
        }
        .frame(minHeight: FabricTheme.minTarget)
        .padding(.vertical, 8)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Show \(tab.tabTitle) page")
        .accessibilityValue(isVisible ? "On" : "Off")
        .accessibilityIdentifier("settings-page-toggle-\(tab.rawValue)")
    }

    private func pageVisibilityBinding(tab: ConnectedAppTab) -> Binding<Bool> {
        Binding(
            get: {
                !ConnectedAppTabPreferences.parse(hiddenTabsRaw).contains(tab.rawValue)
            },
            set: { isVisible in
                hiddenTabsRaw = ConnectedAppTabPreferences.setHidden(
                    !isVisible,
                    tab: tab,
                    in: hiddenTabsRaw
                )
            }
        )
    }

    @ViewBuilder
    private var petRows: some View {
        let petState = appModel?.petState ?? .unsupported
        let pet = SettingsPetPresentation.make(
            supportsPets: appModel?.supportsPets == true,
            state: petState
        )
        switch petState {
        case .active(let display):
            activePetRows(display: display, pet: pet)
        case .disabled:
            disabledPetRow(pet: pet)
        case .loading:
            petStatusRow(pet: pet, showsProgress: true)
        case .unsupported:
            petStatusRow(pet: pet, showsProgress: appModel?.supportsPets == true)
        case .unavailable:
            petStatusRow(pet: pet, showsProgress: false)
        }
        if let petActionError {
            Text(petActionError)
                .font(.footnote)
                .foregroundStyle(FabricTheme.warning)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.bottom, 10)
        }
    }

    private func petStatusRow(pet: SettingsPetPresentation, showsProgress: Bool) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: pet.systemImage)
                .foregroundStyle(pet.tone.color)
                .frame(width: 24, height: 24)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(pet.title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(FabricTheme.text)
                Text(pet.detail)
                    .font(.footnote)
                    .foregroundStyle(pet.tone == .warning ? FabricTheme.warning : FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 12)
            if showsProgress {
                ProgressView()
            }
        }
        .padding(.vertical, 12)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("settings-pets-row")
    }

    private func disabledPetRow(pet: SettingsPetPresentation) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: pet.systemImage)
                .foregroundStyle(FabricTheme.textMuted)
                .frame(width: 24, height: 24)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(pet.title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(FabricTheme.text)
                Text(pet.detail)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 12)
            Toggle("Pet companion", isOn: petToggle)
                .labelsHidden()
                .tint(FabricTheme.action)
        }
        .frame(minHeight: FabricTheme.minTarget)
        .padding(.vertical, 8)
        .accessibilityIdentifier("settings-pets-row")
    }

    private func activePetRows(display: PetDisplay, pet: SettingsPetPresentation) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                PetSpriteView(sheet: display.sheet, state: .idle, height: 56)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(pet.title)
                        .font(.body.weight(.medium))
                        .foregroundStyle(FabricTheme.text)
                    Text(pet.detail)
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                }
                Spacer(minLength: 12)
                Toggle("Pet companion", isOn: petToggle)
                    .labelsHidden()
                    .tint(FabricTheme.action)
            }
            .frame(minHeight: FabricTheme.minTarget)
            .padding(.vertical, 8)
            .accessibilityIdentifier("settings-pets-row")

            Divider().overlay(FabricTheme.border)

            Button {
                petActionError = nil
                showPetPicker = true
            } label: {
                SettingsNavigationRow(
                    title: "Choose pet",
                    detail: "Browse and adopt a different companion",
                    systemImage: "pawprint.circle"
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("settings-pets-choose")
        }
    }

    private var petToggle: Binding<Bool> {
        Binding(
            get: {
                if case .active = appModel?.petState { return true }
                return false
            },
            set: { enabled in
                if enabled {
                    enablePetCompanion()
                } else {
                    disablePetCompanion()
                }
            }
        )
    }

    private func enablePetCompanion() {
        guard let appModel else { return }
        petActionError = nil
        Task { @MainActor in
            do {
                let gallery = try await appModel.loadPetGallery(localOnly: true)
                let adoptable = gallery.active.isEmpty
                    ? gallery.pets.first(where: \.installed)?.slug
                    : gallery.active
                if let adoptable {
                    try await appModel.adoptPet(slug: adoptable)
                } else {
                    showPetPicker = true
                }
            } catch {
                petActionError = "Couldn't turn on the pet companion. Try again."
            }
        }
    }

    private func disablePetCompanion() {
        guard let appModel else { return }
        petActionError = nil
        Task { @MainActor in
            do {
                try await appModel.disablePet()
            } catch {
                petActionError = "Couldn't turn off the pet companion. Try again."
            }
        }
    }

    private var voiceRow: some View {
        let voice = SettingsVoicePresentation.make(
            selectedVoiceName: DeviceVoicePreferences.displayName(
                for: selectedVoiceIdentifier
            )
        )
        return NavigationLink {
            DeviceVoiceSettingsView()
        } label: {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: voice.systemImage)
                    .foregroundStyle(voice.tone.color)
                    .frame(width: 24, height: 24)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(voice.title)
                        .font(.body.weight(.medium))
                        .foregroundStyle(FabricTheme.text)
                    Text(voice.detail)
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 12)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(FabricTheme.textMuted)
                    .accessibilityHidden(true)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.vertical, 12)
        .accessibilityIdentifier("settings-voice-row")
        .accessibilityHint("Choose a read-aloud voice and review dictation privacy")
    }

    private var permissionsSection: some View {
        SettingsExperienceSection(title: "iPhone permissions") {
            VStack(alignment: .leading, spacing: 0) {
                SettingsPermissionRow(permission: permissions.camera)
                Divider().overlay(FabricTheme.border)
                SettingsPermissionRow(permission: permissions.microphone)
                Divider().overlay(FabricTheme.border)
                SettingsPermissionRow(permission: permissions.speechRecognition)
                Divider().overlay(FabricTheme.border)
                Text("Local Network access: status not exposed by iOS.")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 12)
                Divider().overlay(FabricTheme.border)
                Button(action: actions.onOpenSystemSettings) {
                    HStack(spacing: 12) {
                        Image(systemName: "gear")
                            .foregroundStyle(FabricTheme.action)
                            .frame(width: 24)
                            .accessibilityHidden(true)
                        Text("Open iOS Settings")
                            .font(.body.weight(.medium))
                            .foregroundStyle(FabricTheme.action)
                        Spacer(minLength: 12)
                        Image(systemName: "arrow.up.forward.app")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(FabricTheme.textMuted)
                            .accessibilityHidden(true)
                    }
                    .frame(minHeight: FabricTheme.minTarget)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Opens the system settings for Fabric")
            }
        }
    }

    private var aboutSection: some View {
        SettingsExperienceSection(title: "About") {
            VStack(spacing: 0) {
                SettingsValueRow(label: "Fabric Mobile", value: presentation.clientBuild.version)
                SettingsValueRow(label: "Build", value: presentation.clientBuild.build)
                SettingsValueRow(label: "Source", value: presentation.clientBuild.displaySourceRevision)
                Divider().overlay(FabricTheme.border)
                SettingsValueRow(label: "Gateway", value: presentation.gatewayContract.serverVersion)
                SettingsValueRow(label: "Gateway release", value: presentation.gatewayContract.serverReleaseDate)
                SettingsValueRow(label: "Mobile contract", value: presentation.gatewayContract.contractVersion)
                SettingsValueRow(label: "Session controls", value: presentation.gatewayContract.baselineStatus)

                if let featureCount = presentation.gatewayContract.advertisedFeatureCount,
                   let methodCount = presentation.gatewayContract.publishedMethodCount {
                    SettingsValueRow(label: "Gateway advertises", value: "\(featureCount) feature families · \(methodCount) methods")
                }

                if !presentation.gatewayContract.advertisedFeatures.isEmpty {
                    Divider().overlay(FabricTheme.border)
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Advertised by this gateway")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(FabricTheme.textMuted)
                        LazyVGrid(
                            columns: [GridItem(.adaptive(minimum: 128), spacing: 8)],
                            alignment: .leading,
                            spacing: 8
                        ) {
                            ForEach(presentation.gatewayContract.advertisedFeatures, id: \.self) { feature in
                                Text(feature)
                                    .font(.caption.weight(.medium))
                                    .foregroundStyle(FabricTheme.text)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 6)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(
                                        FabricTheme.surfaceInset,
                                        in: RoundedRectangle(cornerRadius: FabricTheme.radiusChip)
                                    )
                            }
                        }
                        Text("An advertised gateway capability is not a promise that every Fabric Mobile screen is available in this build.")
                            .font(.caption)
                            .foregroundStyle(FabricTheme.textMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.top, 12)
                }
            }
        }
    }

    private var privacySection: some View {
        SettingsExperienceSection(title: "Privacy and diagnostics") {
            VStack(alignment: .leading, spacing: 0) {
                NavigationLink {
                    SettingsDiagnosticsView(
                        presentation: presentation,
                        permissions: permissions
                    )
                } label: {
                    SettingsNavigationRow(
                        title: "Diagnostics",
                        detail: "Review and copy a redacted report",
                        systemImage: "stethoscope"
                    )
                }
                .buttonStyle(.plain)

                Divider().overlay(FabricTheme.border)

                VStack(alignment: .leading, spacing: 10) {
                    Label("About Fabric Mobile", systemImage: "lock.shield")
                        .font(.body.weight(.semibold))
                        .foregroundStyle(FabricTheme.text)
                    Text("Fabric Mobile is a remote control for your Fabric gateway. Treat gateway access as machine-control access. Token credentials are protected in Keychain; gated passwords are saved only when you opt in on this iPhone.")
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("The diagnostics report is created on this iPhone only when you open it. Fabric never sends that report automatically.")
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 14)
                .accessibilityElement(children: .combine)
            }
        }
    }

    private var serverManagementSection: some View {
        SettingsExperienceSection(title: "Server management") {
            VStack(spacing: 0) {
                SettingsManagementButton(
                    title: "Switch server",
                    detail: "Return to your saved servers",
                    systemImage: "arrow.left.arrow.right",
                    color: FabricTheme.action
                ) {
                    pendingServerAction = .switchServer
                }
                Divider().overlay(FabricTheme.border)
                SettingsManagementButton(
                    title: "Pair again",
                    detail: "Scan or enter a fresh connection credential",
                    systemImage: "qrcode.viewfinder",
                    color: FabricTheme.action
                ) {
                    pendingServerAction = .repairServer
                }
                Divider().overlay(FabricTheme.border)
                SettingsManagementButton(
                    title: "Forget this server",
                    detail: "Remove its details and saved credential from this iPhone",
                    systemImage: "trash",
                    color: FabricTheme.danger
                ) {
                    pendingServerAction = .forgetServer
                }
            }
            .disabled(presentation.gateway == nil)
        }
    }

    private var deviceDataSection: some View {
        SettingsExperienceSection(title: "Device data") {
            VStack(spacing: 0) {
                SettingsManagementButton(
                    title: "Clear cached presentation data",
                    detail: "Remove device-only Home and conversation snapshots; keep servers and credentials",
                    systemImage: "arrow.clockwise.circle",
                    color: FabricTheme.action
                ) {
                    pendingServerAction = .clearCachedPresentationData
                }
                Divider().overlay(FabricTheme.border)
                SettingsManagementButton(
                    title: "Reset Fabric on this iPhone",
                    detail: "Remove all saved servers, credentials, and device-only presentation state",
                    systemImage: "iphone.and.arrow.forward.outward",
                    color: FabricTheme.danger
                ) {
                    pendingServerAction = .resetLocalApp
                }
            }
        }
    }

    @ViewBuilder
    private var confirmationButtons: some View {
        // Titles and destructive styling come from the tested action enum so
        // the dialog can never drift from the copy the tests pin down.
        if let action = pendingServerAction {
            Button(
                action.confirmationButtonTitle,
                role: action.isDestructive ? .destructive : nil
            ) {
                pendingServerAction = nil
                perform(action)
            }
        }
        Button("Cancel", role: .cancel) {
            pendingServerAction = nil
        }
    }

    private func perform(_ action: SettingsServerManagementAction) {
        switch action {
        case .switchServer:
            actions.onSwitchServer()
        case .repairServer:
            actions.onRepairServer()
        case .forgetServer:
            do {
                try actions.onForgetServer()
            } catch {
                localDataAlert = .forgetGatewayFailed
            }
        case .clearCachedPresentationData:
            do {
                try actions.onClearCachedPresentationData()
                localDataAlert = .cacheCleared
            } catch {
                localDataAlert = .cacheClearFailed
            }
        case .resetLocalApp:
            do {
                try actions.onResetLocalApp()
            } catch {
                localDataAlert = .resetFailed
            }
        }
    }
}

private struct DeviceVoiceSettingsView: View {
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage(DeviceVoicePreferences.selectedVoiceIdentifierKey)
    private var selectedVoiceIdentifier = ""
    @AppStorage(DictationCleanup.enabledKey) private var cleanupEnabled = true
    @State private var previewVoice = DeviceVoiceController()

    private static let previewMessageID = UUID()

    var body: some View {
        Form {
            Section("Speech to text") {
                Label("Dictate into the Chat composer", systemImage: "mic.fill")
                Text("Fabric asks for Microphone and Speech Recognition access only after you tap the microphone. Audio is not sent to your Fabric gateway or stored by Fabric.")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                Text("Fabric requires on-device recognition whenever the current Apple Speech recognizer supports it. For other languages or devices, iOS may use Apple's speech service.")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
            }

            Section("Clean up") {
                Toggle("Show Clean up button", isOn: $cleanupEnabled)
                Text("Adds a Clean up button to the composer that removes filler words (um, uh), collapses repeated words, and tidies spacing and punctuation in your draft. It runs only when you tap it, entirely on this iPhone — URLs and code in backticks are left untouched.")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
            }

            Section("Read aloud") {
                Picker("Voice", selection: normalizedVoiceSelection) {
                    Text("Best installed voice").tag("")
                    ForEach(DeviceVoicePreferences.options()) { option in
                        Text(option.displayName).tag(option.identifier)
                    }
                }

                Button {
                    previewVoice.toggleReadAloud(
                        messageID: Self.previewMessageID,
                        text: "Fabric voice is ready on this iPhone."
                    )
                } label: {
                    Label(
                        previewVoice.isSpeaking ? "Stop preview" : "Preview voice",
                        systemImage: previewVoice.isSpeaking
                            ? "stop.circle.fill"
                            : "speaker.wave.2.fill"
                    )
                }
                .accessibilityHint("Plays a short sample using the selected installed voice")

                Text("Read-aloud uses AVSpeechSynthesizer and an installed iPhone voice. Add enhanced or premium voices in iOS Accessibility settings if your device offers them.")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
            }
        }
        .navigationTitle("Voice")
        .navigationBarTitleDisplayMode(.inline)
        .alert(item: previewIssueBinding) { issue in
            Alert(
                title: Text(issue.title),
                message: Text(issue.message),
                dismissButton: .default(Text("OK"), action: previewVoice.clearIssue)
            )
        }
        .onChange(of: selectedVoiceIdentifier) { _, _ in
            previewVoice.stopSpeaking()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { previewVoice.stopAll() }
        }
        .onAppear {
            let voiceOptions = DeviceVoicePreferences.options()
            selectedVoiceIdentifier = DeviceVoicePreferences.normalizedIdentifier(
                selectedVoiceIdentifier,
                options: voiceOptions
            )
        }
        .onDisappear {
            previewVoice.stopAll()
        }
    }

    private var normalizedVoiceSelection: Binding<String> {
        Binding(
            get: {
                DeviceVoicePreferences.normalizedIdentifier(selectedVoiceIdentifier)
            },
            set: { selectedVoiceIdentifier = $0 }
        )
    }

    private var previewIssueBinding: Binding<DeviceVoiceIssue?> {
        Binding(
            get: { previewVoice.issue },
            set: { newValue in
                if newValue == nil { previewVoice.clearIssue() }
            }
        )
    }
}

private struct SettingsExperienceSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.headline.weight(.semibold))
                .foregroundStyle(FabricTheme.text)
                .accessibilityAddTraits(.isHeader)
            content
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    FabricTheme.surface,
                    in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                )
                .overlay {
                    RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                        .stroke(FabricTheme.border, lineWidth: 1)
                }
        }
    }
}

private struct SettingsStatusHeader: View {
    let status: SettingsStatusPresentation

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: status.systemImage)
                .font(.body.weight(.semibold))
                .foregroundStyle(status.tone.color)
                .frame(width: 28, height: 28)
                .background(
                    status.tone.color.fabricTint(),
                    in: RoundedRectangle(cornerRadius: FabricTheme.radiusChip)
                )
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 5) {
                Text(status.title)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(status.tone.color)
                Text(status.detail)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

private struct SettingsPermissionRow: View {
    let permission: SettingsPermissionPresentation

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var tone: SettingsExperienceTone {
        switch permission.state {
        case .allowed: return .success
        case .denied, .restricted: return .warning
        case .notRequested, .notInspectable: return .neutral
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: permission.systemImage)
                .foregroundStyle(tone.color)
                .frame(width: 24, height: 24)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                if dynamicTypeSize.isAccessibilitySize {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(permission.name)
                            .font(.body.weight(.medium))
                            .foregroundStyle(FabricTheme.text)
                        Text(permission.value)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(tone.color)
                    }
                } else {
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text(permission.name)
                            .font(.body.weight(.medium))
                            .foregroundStyle(FabricTheme.text)
                        Spacer(minLength: 8)
                        Text(permission.value)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(tone.color)
                            .multilineTextAlignment(.trailing)
                    }
                }
                Text(permission.detail)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 12)
        .accessibilityElement(children: .combine)
    }
}

private struct SettingsValueRow: View {
    let label: String
    let value: String

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 3) {
                    Text(label)
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                    Text(value)
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(FabricTheme.text)
                        .textSelection(.enabled)
                }
            } else {
                HStack(alignment: .firstTextBaseline, spacing: 16) {
                    Text(label)
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                    Spacer(minLength: 8)
                    Text(value)
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(FabricTheme.text)
                        .multilineTextAlignment(.trailing)
                        .textSelection(.enabled)
                }
            }
        }
        .padding(.vertical, 7)
        .accessibilityElement(children: .combine)
    }
}

private struct SettingsNavigationRow: View {
    let title: String
    let detail: String
    let systemImage: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .foregroundStyle(FabricTheme.action)
                .frame(width: 24)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(FabricTheme.text)
                Text(detail)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
            }
            Spacer(minLength: 12)
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(FabricTheme.textMuted)
                .accessibilityHidden(true)
        }
        .frame(minHeight: FabricTheme.minTarget)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}

private struct SettingsManagementButton: View {
    let title: String
    let detail: String
    let systemImage: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: systemImage)
                    .foregroundStyle(color)
                    .frame(width: 24)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.body.weight(.medium))
                        .foregroundStyle(color)
                    Text(detail)
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                        .multilineTextAlignment(.leading)
                }
                Spacer(minLength: 12)
            }
            .frame(minHeight: FabricTheme.minTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// Two-phase pet gallery picker: the installed-only gallery renders instantly,
/// then the full petdex merge replaces it when the network fetch lands. A
/// failed full fetch keeps the local rows usable.
private struct SettingsPetPickerSheet: View {
    let appModel: AppModel

    @Environment(\.dismiss) private var dismiss

    @State private var gallery: PetGalleryState?
    @State private var searchText = ""
    @State private var loadFailed = false
    @State private var adoptingSlug: String?
    @State private var adoptionError: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if let adoptionError {
                        Text(adoptionError)
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.warning)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.vertical, 10)
                    }
                    if visiblePets.isEmpty {
                        emptyState
                    } else {
                        ForEach(visiblePets) { entry in
                            petRow(entry)
                            if entry.id != visiblePets.last?.id {
                                Divider().overlay(FabricTheme.border)
                            }
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
            }
            .background(FabricTheme.canvas.ignoresSafeArea())
            .searchable(text: $searchText, prompt: "Search pets")
            .navigationTitle("Choose a pet")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task { await loadGallery() }
        }
        .tint(FabricTheme.action)
    }

    private var visiblePets: [PetGalleryEntry] {
        guard let gallery else { return [] }
        let pets = gallery.pets.filter { !Self.isHiddenSlug($0.slug) }
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !query.isEmpty else { return pets }
        return pets.filter {
            $0.displayName.lowercased().contains(query) || $0.slug.lowercased().contains(query)
        }
    }

    /// The default `clawd` family stays a host-surface concern; matches
    /// `^clawd(-|$)` case-insensitively.
    private static func isHiddenSlug(_ slug: String) -> Bool {
        let lowered = slug.lowercased()
        return lowered == "clawd" || lowered.hasPrefix("clawd-")
    }

    @ViewBuilder
    private var emptyState: some View {
        if gallery == nil {
            if loadFailed {
                Text("Couldn't load the pet gallery from the gateway. Try again later.")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.warning)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.vertical, 24)
            } else {
                HStack {
                    Spacer(minLength: 0)
                    ProgressView()
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 24)
            }
        } else {
            Text("No pets match your search.")
                .font(.footnote)
                .foregroundStyle(FabricTheme.textMuted)
                .padding(.vertical, 24)
        }
    }

    private func petRow(_ entry: PetGalleryEntry) -> some View {
        let isActive = entry.slug == gallery?.active
        return Button {
            adopt(entry)
        } label: {
            HStack(spacing: 12) {
                SettingsPetThumbView(entry: entry, appModel: appModel)
                VStack(alignment: .leading, spacing: 3) {
                    Text(entry.displayName)
                        .font(.body.weight(.medium))
                        .foregroundStyle(FabricTheme.text)
                    if let caption = Self.caption(for: entry, isActive: isActive) {
                        Text(caption)
                            .font(.footnote)
                            .foregroundStyle(isActive ? FabricTheme.action : FabricTheme.textMuted)
                    }
                }
                Spacer(minLength: 12)
                if adoptingSlug == entry.slug {
                    ProgressView()
                } else if isActive {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(FabricTheme.action)
                        .accessibilityHidden(true)
                }
            }
            .frame(minHeight: FabricTheme.minTarget)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(adoptingSlug != nil)
        .accessibilityLabel(isActive ? "\(entry.displayName), active pet" : entry.displayName)
    }

    private static func caption(for entry: PetGalleryEntry, isActive: Bool) -> String? {
        var parts: [String] = []
        if isActive { parts.append("Active") }
        if entry.generated { parts.append("Generated") }
        if entry.installed { parts.append("Installed") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func loadGallery() async {
        if let local = try? await appModel.loadPetGallery(localOnly: true) {
            gallery = local
        }
        do {
            gallery = try await appModel.loadPetGallery(localOnly: false)
            loadFailed = false
        } catch {
            loadFailed = gallery == nil
        }
    }

    private func adopt(_ entry: PetGalleryEntry) {
        guard adoptingSlug == nil else { return }
        adoptionError = nil
        adoptingSlug = entry.slug
        Task { @MainActor in
            do {
                try await appModel.adoptPet(slug: entry.slug)
                adoptingSlug = nil
                dismiss()
            } catch {
                adoptingSlug = nil
                adoptionError = "Couldn't adopt \(entry.displayName). Try again."
            }
        }
    }
}

/// One picker thumbnail, resolved fail-open through the AppModel cache. The
/// dataUri payload after the comma is base64 PNG; anything malformed keeps
/// the placeholder symbol.
private struct SettingsPetThumbView: View {
    let entry: PetGalleryEntry
    let appModel: AppModel

    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .interpolation(.none)
                    .resizable()
                    .scaledToFit()
            } else {
                Image(systemName: "pawprint.fill")
                    .foregroundStyle(FabricTheme.textMuted)
            }
        }
        .frame(width: 44, height: 44)
        .accessibilityHidden(true)
        .task(id: entry.slug) {
            guard image == nil else { return }
            guard let dataUri = await appModel.petThumbnail(
                slug: entry.slug,
                url: entry.spritesheetUrl.isEmpty ? nil : entry.spritesheetUrl
            ),
                let comma = dataUri.firstIndex(of: ","),
                let data = Data(base64Encoded: String(dataUri[dataUri.index(after: comma)...])),
                let decoded = UIImage(data: data)
            else { return }
            image = decoded
        }
    }
}

private extension SettingsExperienceTone {
    var color: Color {
        switch self {
        case .neutral: return FabricTheme.textMuted
        case .info: return FabricTheme.info
        case .success: return FabricTheme.success
        case .warning: return FabricTheme.warning
        case .danger: return FabricTheme.danger
        }
    }
}

#if DEBUG
/// Deterministic screenshot target. It never constructs AppModel, reads the
/// saved-server store, opens a socket, or invokes a production action.
struct SettingsExperienceDebugFixtureView: View {
    var body: some View {
        NavigationStack {
            SettingsExperienceContent(
                presentation: .preview,
                permissions: .preview,
                actions: SettingsExperienceActions(
                    onSwitchServer: {},
                    onRepairServer: {},
                    onForgetServer: {},
                    onClearCachedPresentationData: {},
                    onResetLocalApp: {},
                    onOpenSystemSettings: {}
                )
            )
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
        }
        .tint(FabricTheme.action)
    }
}

#Preview("Settings — connected") {
    SettingsExperienceDebugFixtureView()
}
#endif
