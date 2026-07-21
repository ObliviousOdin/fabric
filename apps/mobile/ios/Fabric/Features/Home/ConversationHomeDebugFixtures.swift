#if DEBUG
import SwiftUI

/// Deterministic launch fixtures for simulator capture and design QA.
///
/// Launch a Debug build with `-fabric-home-fixture running` (or ready, empty,
/// loading, error, offline). The fixture bypasses gateway persistence and
/// never opens a socket. `ready` proves the enabled primary action;
/// light/dark remains controlled by the simulator.
enum ConversationHomeDebugFixture: String, CaseIterable {
    case running
    case ready
    case empty
    case loading
    case error
    case offline

    static var requested: ConversationHomeDebugFixture? {
        let arguments = ProcessInfo.processInfo.arguments
        if let index = arguments.firstIndex(of: "-fabric-home-fixture"),
           arguments.indices.contains(index + 1) {
            return ConversationHomeDebugFixture(rawValue: arguments[index + 1])
        }
        if let inline = arguments.first(where: { $0.hasPrefix("--fabric-home-fixture=") }) {
            return ConversationHomeDebugFixture(
                rawValue: String(inline.dropFirst("--fabric-home-fixture=".count))
            )
        }
        return ProcessInfo.processInfo.environment["FABRIC_HOME_FIXTURE"]
            .flatMap(ConversationHomeDebugFixture.init(rawValue:))
    }
}

@MainActor
struct ConversationHomeDebugFixtureView: View {
    let fixture: ConversationHomeDebugFixture

    @State private var model: ConversationHomeModel
    @State private var draft = ""

    init(fixture: ConversationHomeDebugFixture) {
        self.fixture = fixture
        _model = State(initialValue: fixture.makeModel())
        _draft = State(
            initialValue: fixture == .ready
                ? "Prepare the next verified TestFlight build"
                : ""
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            if fixture == .offline {
                ConnectionRecoveryBannerContent(
                    isReconnecting: false,
                    message: "Fabric is offline.",
                    showActions: true,
                    onRetry: {},
                    onServers: {}
                )
            }
            NavigationStack {
                ConversationHomeContent(
                    model: model,
                    draft: $draft,
                    gatewayLabel: "Personal Mac",
                    gatewayStatusLabel: fixture == .offline
                        ? "Offline · Personal Mac"
                        : "Connected to Personal Mac",
                    isConnected: fixture != .offline,
                    canCreate: fixture != .offline,
                    canResume: fixture != .offline,
                    onStartGoal: { _ in },
                    onNewChat: {},
                    onOpenActive: { _ in },
                    onOpenRecent: { _ in },
                    onSeeAll: {},
                    onRetry: {},
                    onSwitchServer: {},
                    onDisconnect: {}
                )
                .toolbar(.hidden, for: .navigationBar)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

@MainActor
private extension ConversationHomeDebugFixture {
    func makeModel() -> ConversationHomeModel {
        let now = Date()
        switch self {
        case .running, .ready:
            return ConversationHomeModel(
                sessions: Self.recentSessions(now: now),
                activeSessions: [Self.runningSession(now: now)],
                lastUpdated: now.addingTimeInterval(-18)
            )
        case .empty:
            return ConversationHomeModel(lastUpdated: now.addingTimeInterval(-8))
        case .loading:
            return ConversationHomeModel(isLoading: true)
        case .error:
            return ConversationHomeModel(
                loadError: "The gateway did not return the conversation list. Check that Fabric is still running, then try again."
            )
        case .offline:
            return ConversationHomeModel(
                sessions: Self.recentSessions(now: now),
                activeSessions: [Self.runningSession(now: now)],
                lastUpdated: now.addingTimeInterval(-180)
            )
        }
    }

    static func runningSession(now: Date) -> ActiveSession {
        ActiveSession(payload: [
            "id": "runtime-testflight",
            "session_key": "session-testflight",
            "title": "Ship the next TestFlight build",
            "preview": "Running the release checks and preparing the verified iOS archive.",
            "status": "working",
            "model": "gpt-5",
            "message_count": 18,
            "last_active": now.addingTimeInterval(-46).timeIntervalSince1970,
            "current": false,
        ])!
    }

    static func recentSessions(now: Date) -> [SessionSummary] {
        [
            SessionSummary(
                id: "session-design-review",
                title: "Review the mobile home",
                preview: "Compared the selected direction with the native build.",
                startedAt: now.addingTimeInterval(-820).timeIntervalSince1970,
                messageCount: 12,
                source: "mobile"
            ),
            SessionSummary(
                id: "session-ci",
                title: "Fix the release workflow",
                preview: "Verified the Xcode Cloud post-clone hook and source revision.",
                startedAt: now.addingTimeInterval(-7_400).timeIntervalSince1970,
                messageCount: 24,
                source: "mobile"
            ),
        ]
    }
}

#Preview("Home · Running") {
    ConversationHomeDebugFixtureView(fixture: .running)
}

#Preview("Home · Empty") {
    ConversationHomeDebugFixtureView(fixture: .empty)
}

#Preview("Home · Ready") {
    ConversationHomeDebugFixtureView(fixture: .ready)
}

#Preview("Home · Offline") {
    ConversationHomeDebugFixtureView(fixture: .offline)
}
#endif
