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

    @State private var pendingServerAction: SettingsServerManagementAction?
    @State private var localDataAlert: SettingsLocalDataAlert?

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 24) {
                connectionSection
                executionSection
                permissionsSection
                softwareSection
                supportSection
                serverManagementSection
            }
            .padding(.horizontal, 20)
            .padding(.top, 16)
            .padding(.bottom, 40)
        }
        .background(FabricTheme.canvas.ignoresSafeArea())
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

    private var connectionSection: some View {
        SettingsExperienceSection(title: "Connection") {
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
            }
        }
    }

    private var executionSection: some View {
        SettingsExperienceSection(title: "Execution") {
            SettingsStatusHeader(status: presentation.execution)
        }
    }

    private var permissionsSection: some View {
        SettingsExperienceSection(title: "iPhone permissions") {
            VStack(spacing: 0) {
                SettingsPermissionRow(permission: permissions.camera)
                Divider().overlay(FabricTheme.border)
                SettingsPermissionRow(permission: permissions.localNetwork)
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

    private var softwareSection: some View {
        SettingsExperienceSection(title: "App and gateway") {
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

    private var supportSection: some View {
        SettingsExperienceSection(title: "Privacy and support") {
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
                    Text("Fabric Mobile is a remote control for your Fabric gateway. Treat gateway access as machine-control access. Token credentials are protected in Keychain; gated passwords are used for sign-in and are not saved.")
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

    @ViewBuilder
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

        SettingsExperienceSection(title: "Device storage") {
            SettingsManagementButton(
                title: "Clear cached presentation data",
                detail: "Remove device-only Home and conversation snapshots; keep servers and credentials",
                systemImage: "arrow.clockwise.circle",
                color: FabricTheme.action
            ) {
                pendingServerAction = .clearCachedPresentationData
            }
        }

        SettingsExperienceSection(title: "Reset") {
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

    @ViewBuilder
    private var confirmationButtons: some View {
        switch pendingServerAction {
        case .switchServer:
            Button("Switch Servers") {
                pendingServerAction = nil
                actions.onSwitchServer()
            }
        case .repairServer:
            Button("Pair Again") {
                pendingServerAction = nil
                actions.onRepairServer()
            }
        case .forgetServer:
            Button("Forget Server", role: .destructive) {
                do {
                    try actions.onForgetServer()
                    pendingServerAction = nil
                } catch {
                    pendingServerAction = nil
                    localDataAlert = .forgetGatewayFailed
                }
            }
        case .clearCachedPresentationData:
            Button("Clear Cache") {
                do {
                    try actions.onClearCachedPresentationData()
                    pendingServerAction = nil
                    localDataAlert = .cacheCleared
                } catch {
                    pendingServerAction = nil
                    localDataAlert = .cacheClearFailed
                }
            }
        case .resetLocalApp:
            Button("Reset Fabric", role: .destructive) {
                do {
                    try actions.onResetLocalApp()
                    pendingServerAction = nil
                } catch {
                    pendingServerAction = nil
                    localDataAlert = .resetFailed
                }
            }
        case nil:
            EmptyView()
        }
        Button("Cancel", role: .cancel) {
            pendingServerAction = nil
        }
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
