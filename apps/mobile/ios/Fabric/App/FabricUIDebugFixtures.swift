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
    case mithuru
    case workBoard = "work-board"
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
            case .mithuru:
                MithuruOnboardingDebugFixtureView()
            case .workBoard:
                WorkBoardDebugFixtureView()
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

/// Deterministic Work board for visual QA. Real gateways never advertise the
/// `durable_work` family yet (FMB-002), so the populated board is only
/// reachable through this fixture.
struct WorkBoardDebugFixtureView: View {
    var body: some View {
        NavigationStack {
            WorkBoardScreen(
                state: .ready(Self.fixture),
                onRefresh: {},
                onCancel: { _ in .unavailable },
                onRespond: { _, _ in .unavailable }
            )
            .navigationTitle("Work")
            .navigationBarTitleDisplayMode(.inline)
        }
        .accessibilityIdentifier("fabric-ui-fixture-work-board")
    }

    private static var fixture: WorkBoardReadyState {
        WorkBoardReadyState(
            sections: sections,
            availability: .current,
            isRefreshing: false,
            syncError: nil,
            lastUpdated: Date()
        )
    }

    private static var sections: FabricWorkInboxSections {
        var result = FabricWorkInboxSections()
        result.needsAttention = [
            FabricWorkInboxJobSummary(
                id: "job-approve",
                version: 3,
                kind: "background_prompt",
                status: "waiting_attention",
                title: "Deploy staging build",
                summary: "Waiting for approval to run the deploy script.",
                openAttentionCount: 1,
                attemptCount: 1,
                createdAt: 1784451600000,
                startedAt: 1784451601000,
                updatedAt: 1784451602500,
                finishedAt: nil,
                attention: [
                    FabricWorkInboxAttentionSummary(
                        id: "att-1",
                        version: 1,
                        jobID: "job-approve",
                        kind: "approval",
                        state: "pending",
                        title: "Run deploy.sh?",
                        blocking: true,
                        sensitive: false,
                        allowedActions: ["once", "session", "always", "deny"],
                        updatedAt: 1784451602500,
                        canRespond: true
                    )
                ],
                hasResultPreview: false,
                hasErrorPreview: false,
                transcriptRoute: nil,
                canCancel: true
            )
        ]
        result.active = [
            FabricWorkInboxJobSummary(
                id: "job-run",
                version: 5,
                kind: "background_prompt",
                status: "running",
                title: "Summarize weekly analytics",
                summary: "Reading dashboards…",
                openAttentionCount: 0,
                attemptCount: 1,
                createdAt: 1784451500000,
                startedAt: 1784451510000,
                updatedAt: 1784451590000,
                finishedAt: nil,
                attention: [],
                hasResultPreview: false,
                hasErrorPreview: false,
                transcriptRoute: FabricWorkInboxTranscriptRoute(runtimeSessionID: "sess-run"),
                canCancel: true
            )
        ]
        result.completed = [
            FabricWorkInboxJobSummary(
                id: "job-done",
                version: 8,
                kind: "background_prompt",
                status: "succeeded",
                title: "Draft release notes",
                summary: "Posted the v0.4 notes.",
                openAttentionCount: 0,
                attemptCount: 1,
                createdAt: 1784450000000,
                startedAt: 1784450010000,
                updatedAt: 1784450900000,
                finishedAt: 1784450900000,
                attention: [],
                hasResultPreview: true,
                hasErrorPreview: false,
                transcriptRoute: FabricWorkInboxTranscriptRoute(runtimeSessionID: "sess-done"),
                canCancel: false
            )
        ]
        return result
    }
}
#endif
