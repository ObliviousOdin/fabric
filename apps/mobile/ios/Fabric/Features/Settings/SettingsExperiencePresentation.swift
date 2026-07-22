import AVFoundation
import Foundation

enum SettingsExperienceTone: Equatable {
    case neutral
    case info
    case success
    case warning
    case danger
}

struct SettingsStatusPresentation: Equatable {
    let title: String
    let detail: String
    let systemImage: String
    let tone: SettingsExperienceTone
}

enum SettingsClientDisconnectPosture: Equatable {
    case workContinues
    case workMayStop
    case unverified
}

enum SettingsLocalDataAlert: String, Identifiable, Equatable {
    case cacheCleared
    case cacheClearFailed
    case forgetGatewayFailed
    case resetFailed

    var id: String { rawValue }

    var title: String {
        switch self {
        case .cacheCleared: return "Cached data cleared"
        case .cacheClearFailed: return "Couldn't clear cached data"
        case .forgetGatewayFailed: return "Couldn't forget server"
        case .resetFailed: return "Reset didn't complete"
        }
    }

    var message: String {
        switch self {
        case .cacheCleared:
            return "Stored Home and conversation snapshots were removed from this iPhone. Saved servers, credentials, and gateway data were not changed."
        case .cacheClearFailed:
            return "Fabric couldn't remove the stored presentation snapshots. Saved servers, credentials, and gateway data were not changed. Try again."
        case .forgetGatewayFailed:
            return "Fabric couldn't remove the saved credential, so this server is still saved on this iPhone. Unlock the device and try again."
        case .resetFailed:
            return "Fabric couldn't verify a complete reset. Saved server access may still be present on this iPhone. Unlock the device and try again."
        }
    }
}

enum SettingsServerManagementAction: Equatable {
    case switchServer
    case repairServer
    case forgetServer
    case clearCachedPresentationData
    case resetLocalApp

    var confirmationTitle: String {
        switch self {
        case .switchServer: return "Switch servers?"
        case .repairServer: return "Pair this phone again?"
        case .forgetServer: return "Forget this server?"
        case .clearCachedPresentationData: return "Clear cached presentation data?"
        case .resetLocalApp: return "Reset Fabric on this iPhone?"
        }
    }

    var confirmationMessage: String {
        confirmationMessage(disconnectPosture: .unverified)
    }

    func confirmationMessage(
        disconnectPosture: SettingsClientDisconnectPosture
    ) -> String {
        switch self {
        case .switchServer:
            switch disconnectPosture {
            case .workContinues:
                return "This disconnects only this iPhone. The gateway verifies that active work continues after this phone disconnects, as long as the gateway host stays online."
            case .workMayStop:
                return "This disconnects only this iPhone. The gateway reports that active work may stop when this phone disconnects. Review active conversations before switching. Gateway data is not deleted."
            case .unverified:
                return "This disconnects only this iPhone. Fabric cannot verify whether active work survives a client disconnect. Review active conversations before switching. Gateway data is not deleted."
            }
        case .repairServer:
            return "Scan or enter a fresh pairing credential. Existing work on the gateway is not stopped or deleted."
        case .forgetServer:
            return "Fabric will remove this server and its saved credential from this iPhone. Work and data on the gateway are not deleted."
        case .clearCachedPresentationData:
            return "Fabric will remove stored Home and conversation presentation snapshots from this iPhone. Saved servers, credentials, active gateway work, and gateway data are not changed."
        case .resetLocalApp:
            return "Fabric will remove all saved servers and credentials, plus device-only presentation state, from this iPhone. Work and data on every gateway are not deleted."
        }
    }

    var confirmationButtonTitle: String {
        switch self {
        case .switchServer: return "Switch Servers"
        case .repairServer: return "Pair Again"
        case .forgetServer: return "Forget Server"
        case .clearCachedPresentationData: return "Clear Cache"
        case .resetLocalApp: return "Reset Fabric"
        }
    }

    var isDestructive: Bool {
        switch self {
        case .forgetServer, .resetLocalApp: return true
        case .switchServer, .repairServer, .clearCachedPresentationData: return false
        }
    }
}

struct SettingsClientBuildInfo: Equatable {
    let version: String
    let build: String
    let sourceRevision: String

    static func current(bundle: Bundle = .main) -> SettingsClientBuildInfo {
        SettingsClientBuildInfo(
            version: nonempty(bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)
                ?? "Unknown",
            build: nonempty(bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String)
                ?? "Unknown",
            sourceRevision: nonempty(bundle.object(forInfoDictionaryKey: "FabricSourceRevision") as? String)
                ?? "Unknown"
        )
    }

    var displaySourceRevision: String {
        guard sourceRevision != "development" else { return "Development build" }
        guard sourceRevision.count > 12 else { return sourceRevision }
        return String(sourceRevision.prefix(12))
    }

    private static func nonempty(_ value: String?) -> String? {
        guard let value,
              !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return value
    }
}

struct SettingsGatewayIdentity: Equatable {
    let label: String
    let endpoint: String
    let authentication: String
    let transport: String
    let transportWarning: String?

    init(gateway: SavedGateway) {
        label = gateway.label.isEmpty ? "Fabric gateway" : gateway.label
        endpoint = Self.displayEndpoint(gateway.baseURL)
        transport = GatewayTransportPresentation.label(for: gateway.baseURL)
        transportWarning = GatewayTransportPresentation.warning(for: gateway.baseURL)
        switch gateway.authMode {
        case .token:
            authentication = "Credential protected in Keychain"
        case .gated:
            authentication = "Password protected; password is not saved"
        }
    }

    static func displayEndpoint(_ url: URL) -> String {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return "Endpoint unavailable"
        }
        components.user = nil
        components.password = nil
        components.query = nil
        components.fragment = nil
        return components.string ?? "Endpoint unavailable"
    }
}

struct SettingsGatewayContractPresentation: Equatable {
    let serverVersion: String
    let serverReleaseDate: String
    let contractVersion: String
    let baselineStatus: String
    let advertisedFeatureCount: Int?
    let publishedMethodCount: Int?
    let advertisedFeatures: [String]

    static func make(negotiation: GatewayCapabilityNegotiation?) -> SettingsGatewayContractPresentation {
        switch negotiation {
        case .verified(let capabilities):
            let enabledFeatures = capabilities.features
                .filter(\.value)
                .map(\.key)
                .sorted()
                .map(featureLabel)
            return SettingsGatewayContractPresentation(
                serverVersion: capabilities.server.version,
                serverReleaseDate: capabilities.server.releaseDate,
                contractVersion: "\(capabilities.contract.version)",
                baselineStatus: capabilities.methods.isSuperset(of: requiredMobileMethodsForSettings)
                    ? "Verified"
                    : "Unavailable",
                advertisedFeatureCount: enabledFeatures.count,
                publishedMethodCount: capabilities.methods.count,
                advertisedFeatures: enabledFeatures
            )
        case .legacy:
            return SettingsGatewayContractPresentation(
                serverVersion: "Not reported",
                serverReleaseDate: "Not reported",
                contractVersion: "Legacy compatibility",
                baselineStatus: "Compatibility mode",
                advertisedFeatureCount: nil,
                publishedMethodCount: legacyMobileMethods.count,
                advertisedFeatures: []
            )
        case .incompatible(let minimum):
            return SettingsGatewayContractPresentation(
                serverVersion: "Unavailable",
                serverReleaseDate: "Unavailable",
                contractVersion: "Requires mobile contract \(minimum)",
                baselineStatus: "Mobile update required",
                advertisedFeatureCount: nil,
                publishedMethodCount: nil,
                advertisedFeatures: []
            )
        case .invalid:
            return SettingsGatewayContractPresentation(
                serverVersion: "Unavailable",
                serverReleaseDate: "Unavailable",
                contractVersion: "Invalid response",
                baselineStatus: "Disabled for safety",
                advertisedFeatureCount: nil,
                publishedMethodCount: nil,
                advertisedFeatures: []
            )
        case .negotiating:
            return SettingsGatewayContractPresentation(
                serverVersion: "Checking…",
                serverReleaseDate: "Checking…",
                contractVersion: "Checking…",
                baselineStatus: "Checking…",
                advertisedFeatureCount: nil,
                publishedMethodCount: nil,
                advertisedFeatures: []
            )
        case nil:
            return SettingsGatewayContractPresentation(
                serverVersion: "Unavailable offline",
                serverReleaseDate: "Unavailable offline",
                contractVersion: "Not connected",
                baselineStatus: "Not verified",
                advertisedFeatureCount: nil,
                publishedMethodCount: nil,
                advertisedFeatures: []
            )
        }
    }

    private static let requiredMobileMethodsForSettings: Set<String> = [
        "prompt.submit",
        "session.create",
        "session.list",
        "session.resume",
    ]

    private static func featureLabel(_ feature: String) -> String {
        let labels = [
            "artifact_fetch": "Artifact downloads",
            "automation": "Automation",
            "background_work": "Background work",
            "baseline_chat": "Conversations",
            "code_session_baseline": "Code session controls",
            "connected_nodes": "Connected nodes",
            "delegation": "Delegation status",
            "device_node": "Device enrollment",
            "durable_work": "Durable work",
            "files": "Gateway attachments",
            "handoff": "Handoff",
            "live_view": "Live View",
            "node_invoke": "Node actions",
            "push": "Push notifications",
            "scoped_grants": "Scoped grants",
            "session_admin": "Session management",
            "trust_center": "Trust Center",
            "workspace_read": "Workspace reading",
        ]
        if let label = labels[feature] { return label }
        return feature
            .split(separator: "_")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }
}

struct SettingsExperiencePresentation: Equatable {
    let gateway: SettingsGatewayIdentity?
    let connection: SettingsStatusPresentation
    let execution: SettingsStatusPresentation
    let clientBuild: SettingsClientBuildInfo
    let gatewayContract: SettingsGatewayContractPresentation
    let authModeDiagnostic: String
    let clientDisconnectPosture: SettingsClientDisconnectPosture

    @MainActor
    init(appModel: AppModel, clientBuild: SettingsClientBuildInfo = .current()) {
        self.init(
            gateway: appModel.activeGateway,
            phase: appModel.phase,
            negotiation: appModel.capabilityNegotiation,
            clientBuild: clientBuild
        )
    }

    init(
        gateway: SavedGateway?,
        phase: AppModel.Phase,
        negotiation: GatewayCapabilityNegotiation?,
        clientBuild: SettingsClientBuildInfo
    ) {
        self.gateway = gateway.map(SettingsGatewayIdentity.init(gateway:))
        connection = Self.connectionPresentation(
            phase: phase,
            gatewayLabel: self.gateway?.label
        )
        execution = Self.executionPresentation(negotiation: negotiation)
        clientDisconnectPosture = Self.clientDisconnectPosture(negotiation: negotiation)
        self.clientBuild = clientBuild
        gatewayContract = .make(negotiation: negotiation)
        switch gateway?.authMode {
        case .token: authModeDiagnostic = "token"
        case .gated: authModeDiagnostic = "gated"
        case nil: authModeDiagnostic = "none"
        }
    }

    private static func clientDisconnectPosture(
        negotiation: GatewayCapabilityNegotiation?
    ) -> SettingsClientDisconnectPosture {
        guard case .verified(let capabilities) = negotiation else {
            return .unverified
        }
        return capabilities.execution.survivesClientDisconnect
            ? .workContinues
            : .workMayStop
    }

    private static func connectionPresentation(
        phase: AppModel.Phase,
        gatewayLabel: String?
    ) -> SettingsStatusPresentation {
        let target = gatewayLabel ?? "Fabric gateway"
        switch phase {
        case .connected:
            return SettingsStatusPresentation(
                title: "Connected",
                detail: "This iPhone is connected to \(target).",
                systemImage: "checkmark.circle.fill",
                tone: .success
            )
        case .connecting:
            return SettingsStatusPresentation(
                title: "Connecting",
                detail: "Establishing a connection to \(target).",
                systemImage: "arrow.triangle.2.circlepath",
                tone: .info
            )
        case .reconnecting:
            return SettingsStatusPresentation(
                title: "Reconnecting",
                detail: "The connection dropped. Fabric is trying \(target) again.",
                systemImage: "wifi.exclamationmark",
                tone: .warning
            )
        case .disconnected:
            return SettingsStatusPresentation(
                title: gatewayLabel == nil ? "Not connected" : "Offline",
                detail: gatewayLabel == nil
                    ? "Choose or pair a Fabric gateway to continue."
                    : "This iPhone is disconnected from \(target).",
                systemImage: "bolt.horizontal.circle",
                tone: .warning
            )
        }
    }

    private static func executionPresentation(
        negotiation: GatewayCapabilityNegotiation?
    ) -> SettingsStatusPresentation {
        switch negotiation {
        case .verified(let capabilities):
            let execution = capabilities.execution
            let location = execution.location == "gateway" && execution.toolExecution == "gateway"
                ? "Work and tools run on the gateway, not on this iPhone."
                : "Execution location is not verified."
            let disconnect = execution.survivesClientDisconnect
                ? "Active work continues if this phone disconnects."
                : "Active work may stop if this phone disconnects."
            let restart = execution.survivesGatewayRestart
                ? "Active work survives a gateway restart."
                : "A gateway restart interrupts active work."
            let online = execution.requiresGatewayHostOnline
                ? "Keep the gateway host online."
                : "The gateway does not report an online-host requirement."
            return SettingsStatusPresentation(
                title: "Runs on your gateway",
                detail: [location, disconnect, restart, online].joined(separator: " "),
                systemImage: "server.rack",
                tone: .info
            )
        case .legacy:
            return SettingsStatusPresentation(
                title: "Compatibility mode",
                detail: "The gateway supports the original mobile controls but cannot verify where work runs or what survives a disconnect. Update Fabric to restore verified execution guarantees.",
                systemImage: "exclamationmark.arrow.triangle.2.circlepath",
                tone: .warning
            )
        case .incompatible(let minimum):
            return SettingsStatusPresentation(
                title: "Mobile update required",
                detail: "This gateway requires mobile contract \(minimum) or newer. Remote controls are disabled until Fabric Mobile is updated.",
                systemImage: "arrow.down.app",
                tone: .danger
            )
        case .invalid:
            return SettingsStatusPresentation(
                title: "Gateway contract invalid",
                detail: "Remote controls are disabled because the gateway could not prove a safe mobile execution contract.",
                systemImage: "exclamationmark.shield",
                tone: .danger
            )
        case .negotiating:
            return SettingsStatusPresentation(
                title: "Verifying execution",
                detail: "Remote controls unlock after the authenticated gateway contract is verified.",
                systemImage: "checkmark.shield",
                tone: .info
            )
        case nil:
            return SettingsStatusPresentation(
                title: "Execution not verified",
                detail: "Reconnect to verify where work runs and which mobile controls are available.",
                systemImage: "wifi.exclamationmark",
                tone: .warning
            )
        }
    }
}

enum SettingsPermissionState: String, Equatable {
    case allowed
    case denied
    case restricted
    case notRequested
    case notInspectable
}

struct SettingsPermissionPresentation: Equatable {
    let name: String
    let value: String
    let detail: String
    let systemImage: String
    let state: SettingsPermissionState
}

struct SettingsPermissionInventory: Equatable {
    let camera: SettingsPermissionPresentation
    let localNetwork: SettingsPermissionPresentation

    static func current() -> SettingsPermissionInventory {
        SettingsPermissionInventory(
            camera: cameraPermission(AVCaptureDevice.authorizationStatus(for: .video)),
            localNetwork: SettingsPermissionPresentation(
                name: "Local Network",
                value: "Status not exposed by iOS",
                detail: "iOS checks this permission when Fabric connects to a gateway on your local network. Review or change it in iOS Settings.",
                systemImage: "network",
                state: .notInspectable
            )
        )
    }

    static func cameraPermission(_ status: AVAuthorizationStatus) -> SettingsPermissionPresentation {
        switch status {
        case .authorized:
            return SettingsPermissionPresentation(
                name: "Camera",
                value: "Allowed",
                detail: "Used only when you scan a Fabric pairing code.",
                systemImage: "camera",
                state: .allowed
            )
        case .denied:
            return SettingsPermissionPresentation(
                name: "Camera",
                value: "Denied",
                detail: "QR scanning is unavailable. You can allow Camera access in iOS Settings or pair manually.",
                systemImage: "camera.fill",
                state: .denied
            )
        case .restricted:
            return SettingsPermissionPresentation(
                name: "Camera",
                value: "Restricted",
                detail: "This device does not currently permit Fabric to use the camera.",
                systemImage: "camera.fill",
                state: .restricted
            )
        case .notDetermined:
            return SettingsPermissionPresentation(
                name: "Camera",
                value: "Not requested",
                detail: "Fabric asks only when you choose to scan a pairing code.",
                systemImage: "camera",
                state: .notRequested
            )
        @unknown default:
            return SettingsPermissionPresentation(
                name: "Camera",
                value: "Unavailable",
                detail: "This iOS version returned an unknown camera permission state.",
                systemImage: "questionmark.circle",
                state: .restricted
            )
        }
    }
}

struct SettingsDiagnosticsEnvironment: Equatable {
    let operatingSystem: String
    let generatedAt: Date

    static func current(now: Date = Date()) -> SettingsDiagnosticsEnvironment {
        SettingsDiagnosticsEnvironment(
            operatingSystem: "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)",
            generatedAt: now
        )
    }
}

enum SettingsDiagnosticsReport {
    static func make(
        presentation: SettingsExperiencePresentation,
        permissions: SettingsPermissionInventory,
        environment: SettingsDiagnosticsEnvironment = .current()
    ) -> String {
        let contract = presentation.gatewayContract
        let executionState: String
        switch contract.baselineStatus {
        case "Verified": executionState = "verified"
        case "Compatibility mode", "Not verified", "Checking…": executionState = "unverified"
        case "Unavailable", "Mobile update required", "Disabled for safety": executionState = "blocked"
        default: executionState = "unknown"
        }

        let lines = [
            "Fabric Mobile Diagnostics (redacted)",
            "generated_utc: \(ISO8601DateFormatter().string(from: environment.generatedAt))",
            "app_version: \(safeMetadata(presentation.clientBuild.version))",
            "app_build: \(safeMetadata(presentation.clientBuild.build))",
            "source_revision: \(safeMetadata(presentation.clientBuild.sourceRevision))",
            "operating_system: \(safeMetadata(environment.operatingSystem))",
            "connection_state: \(diagnosticConnectionState(presentation.connection.title))",
            "gateway_identity: [redacted]",
            "authentication_mode: \(safeMetadata(presentation.authModeDiagnostic))",
            "gateway_server_version: \(safeMetadata(contract.serverVersion))",
            "gateway_release_date: \(safeMetadata(contract.serverReleaseDate))",
            "gateway_contract: \(safeMetadata(contract.contractVersion))",
            "baseline_session_controls: \(safeMetadata(contract.baselineStatus))",
            "advertised_feature_families: \(contract.advertisedFeatureCount.map(String.init) ?? "unavailable")",
            "published_gateway_methods: \(contract.publishedMethodCount.map(String.init) ?? "unavailable")",
            "execution_contract: \(executionState)",
            "camera_permission: \(permissions.camera.state.rawValue)",
            "local_network_permission: \(permissions.localNetwork.state.rawValue)",
            "raw_connection_error: [excluded]",
            "credentials_auth_material: [excluded]",
            "prompts_transcripts_sessions: [excluded]",
        ]
        return SettingsDiagnosticsRedactor.redact(lines.joined(separator: "\n"))
    }

    private static func diagnosticConnectionState(_ title: String) -> String {
        switch title {
        case "Connected": return "connected"
        case "Connecting": return "connecting"
        case "Reconnecting": return "reconnecting"
        case "Offline": return "offline"
        default: return "not_connected"
        }
    }

    /// Diagnostics are whitelist-built, but every metadata field is still
    /// constrained so an unexpected bundle or gateway value cannot inject a
    /// new key/value line into the copied report.
    private static func safeMetadata(_ value: String) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 120 else { return "[redacted]" }
        let allowed = CharacterSet.alphanumerics
            .union(.whitespaces)
            .union(CharacterSet(charactersIn: ".,_+()/-"))
        guard trimmed.unicodeScalars.allSatisfy(allowed.contains) else {
            return "[redacted]"
        }
        return trimmed
    }
}

/// Defense in depth for the copied report. The report generator never accepts
/// endpoint, error, prompt, transcript, or session fields; this redactor also
/// strips common credential shapes if future safe metadata is added later.
enum SettingsDiagnosticsRedactor {
    private static let replacements: [(pattern: String, template: String)] = [
        (#"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/=-]+"#, "Bearer [redacted]"),
        (#"(?i)\bfabric://[^\s]+"#, "[redacted pairing URL]"),
        (#"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"#, "[redacted token]"),
        (#"(?im)^([ \t]*(?:token|password|cookie|ticket|secret|authorization|api[_-]?key|prompt|transcript|session(?:[_-]?(?:id|key|data))?)[ \t]*[:=])[^\r\n]*"#, "$1 [redacted]"),
    ]

    static func redact(_ value: String) -> String {
        replacements.reduce(value) { result, replacement in
            guard let expression = try? NSRegularExpression(
                pattern: replacement.pattern,
                options: []
            ) else { return result }
            let range = NSRange(result.startIndex..<result.endIndex, in: result)
            return expression.stringByReplacingMatches(
                in: result,
                options: [],
                range: range,
                withTemplate: replacement.template
            )
        }
    }
}

#if DEBUG
extension SettingsExperiencePresentation {
    static let preview = SettingsExperiencePresentation(
        gateway: SavedGateway(
            id: "preview-gateway",
            label: "Studio Mac",
            baseURL: URL(string: "https://fabric.example.invalid")!,
            authMode: .token
        ),
        phase: .connected,
        negotiation: .verified(GatewayCapabilities(
            contract: GatewayCapabilityContract(
                name: "fabric.gateway",
                version: 1,
                minimumCompatibleVersion: 1
            ),
            server: GatewayServerContract(version: "preview", releaseDate: "2026-07-21"),
            execution: GatewayExecutionContract(
                location: "gateway",
                toolExecution: "gateway",
                survivesClientDisconnect: true,
                survivesGatewayRestart: false,
                requiresGatewayHostOnline: true
            ),
            features: [
                "background_work": true,
                "baseline_chat": true,
                "live_view": true,
            ],
            methods: [
                "prompt.submit",
                "session.create",
                "session.list",
                "session.resume",
            ]
        )),
        clientBuild: SettingsClientBuildInfo(
            version: "Preview",
            build: "Preview",
            sourceRevision: "preview"
        )
    )
}

extension SettingsPermissionInventory {
    static let preview = SettingsPermissionInventory(
        camera: SettingsPermissionPresentation(
            name: "Camera",
            value: "Not requested",
            detail: "Fabric asks only when you choose to scan a pairing code.",
            systemImage: "camera",
            state: .notRequested
        ),
        localNetwork: SettingsPermissionPresentation(
            name: "Local Network",
            value: "Status not exposed by iOS",
            detail: "iOS checks this permission when Fabric connects to a gateway on your local network.",
            systemImage: "network",
            state: .notInspectable
        )
    )
}
#endif
