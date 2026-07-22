#if DEBUG
import SwiftUI

/// App-wide deterministic launch fixtures used by XCUITest and visual QA.
/// They bypass persistence and transport so captures cannot mutate a real
/// server or accidentally send a prompt.
enum FabricUIDebugFixture: String, CaseIterable {
    case onboarding
    case returning
    case scannerDenied = "scanner-denied"
    case connectionSuccess = "connection-success"
    case connectionLegacy = "connection-legacy"
    case sessions
    case chatActivity = "chat-activity"
    case settings

    static var requested: FabricUIDebugFixture? {
        let arguments = ProcessInfo.processInfo.arguments
        if let index = arguments.firstIndex(of: "-fabric-ui-fixture"),
           arguments.indices.contains(index + 1) {
            return FabricUIDebugFixture(rawValue: arguments[index + 1])
        }
        if let inline = arguments.first(where: { $0.hasPrefix("--fabric-ui-fixture=") }) {
            return FabricUIDebugFixture(
                rawValue: String(inline.dropFirst("--fabric-ui-fixture=".count))
            )
        }
        return ProcessInfo.processInfo.environment["FABRIC_UI_FIXTURE"]
            .flatMap(FabricUIDebugFixture.init(rawValue:))
    }
}

/// Debug-only integration entry point for a disposable local gateway. This is
/// intentionally separate from visual fixtures: it exercises the production
/// pairing parser, Keychain write, socket, and capability negotiation. Never
/// pass a reusable credential here because process arguments are observable.
enum FabricUIDebugPairingLaunch {
    static var requestedURL: URL? {
        requestedURL(
            arguments: ProcessInfo.processInfo.arguments,
            environment: ProcessInfo.processInfo.environment
        )
    }

    static func requestedURL(
        arguments: [String],
        environment: [String: String]
    ) -> URL? {
        guard let index = arguments.firstIndex(of: "-fabric-e2e-pairing-url"),
              arguments.indices.contains(index + 1) else {
            return environment["FABRIC_E2E_PAIRING_URL"].flatMap(URL.init(string:))
        }
        return URL(string: arguments[index + 1])
    }
}

struct FabricUIDebugFixtureView: View {
    let fixture: FabricUIDebugFixture

    var body: some View {
        Group {
            switch fixture {
            case .onboarding:
                ConnectExperienceDebugFixtureView(state: .onboarding)
            case .returning:
                ConnectExperienceDebugFixtureView(state: .returning)
            case .scannerDenied:
                ConnectExperienceDebugFixtureView(state: .scannerDenied)
            case .connectionSuccess:
                ConnectedGatewayIntroView(
                    gateway: Self.gateway,
                    negotiation: Self.negotiation,
                    onContinue: {},
                    onSwitchServer: {}
                )
            case .connectionLegacy:
                ConnectedGatewayIntroView(
                    gateway: Self.gateway,
                    negotiation: .legacy,
                    onContinue: {},
                    onSwitchServer: {}
                )
            case .sessions:
                SessionLibraryDebugFixtureView()
            case .chatActivity:
                ChatExperienceDebugFixtureView()
            case .settings:
                SettingsExperienceDebugFixtureView()
            }
        }
        .accessibilityIdentifier("fabric-ui-fixture-\(fixture.rawValue)")
    }

    private static let gateway = SavedGateway(
        id: "fixture-personal-mac",
        label: "Personal Mac",
        baseURL: URL(string: "https://personal-mac.example.test")!,
        authMode: .token
    )

    private static let negotiation = GatewayCapabilityNegotiation.verified(
        GatewayCapabilities(
            contract: GatewayCapabilityContract(
                name: "fabric.gateway",
                version: 1,
                minimumCompatibleVersion: 1
            ),
            server: GatewayServerContract(version: "0.4.0", releaseDate: "2026-07-21"),
            execution: GatewayExecutionContract(
                location: "gateway",
                toolExecution: "gateway",
                survivesClientDisconnect: true,
                survivesGatewayRestart: false,
                requiresGatewayHostOnline: true
            ),
            features: [:],
            methods: legacyMobileMethods
        )
    )
}
#endif
