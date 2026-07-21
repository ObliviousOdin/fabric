import XCTest
@testable import Fabric

@MainActor
final class ConversationHomeModelTests: XCTestCase {
    func testHomePrioritizesAttentionAndKeepsLiveRowsOutOfRecent() {
        let waiting = active(
            id: "runtime-waiting",
            sessionKey: "session-waiting",
            status: "waiting",
            lastActive: 10
        )
        let working = active(
            id: "runtime-working",
            sessionKey: "session-working",
            status: "working",
            lastActive: 20
        )
        let model = ConversationHomeModel(
            sessions: [
                session(id: "session-waiting", startedAt: 50),
                session(id: "session-working", startedAt: 40),
                session(id: "recent-one", startedAt: 30),
                session(id: "recent-two", startedAt: 20),
                session(id: "recent-three", startedAt: 10),
            ],
            activeSessions: [working, waiting],
            lastUpdated: Date()
        )

        XCTAssertEqual(model.highlightedSession?.id, waiting.id)
        XCTAssertEqual(model.additionalActiveCount, 1)
        XCTAssertEqual(model.recentSessions.map(\.id), ["recent-one", "recent-two"])
    }

    func testHomeUsesActivityAndStableIDToOrderEqualStatus() {
        let older = active(id: "runtime-old", sessionKey: "old", status: "working", lastActive: 10)
        let newestB = active(id: "runtime-b", sessionKey: "b", status: "working", lastActive: 20)
        let newestA = active(id: "runtime-a", sessionKey: "a", status: "working", lastActive: 20)
        let model = ConversationHomeModel(
            activeSessions: [newestB, older, newestA],
            lastUpdated: Date()
        )

        XCTAssertEqual(model.highlightedSession?.id, newestA.id)
        XCTAssertEqual(model.additionalActiveCount, 2)
    }

    func testIdleAndUnknownActiveRowsRemainEligibleForRecent() {
        let idle = active(id: "runtime-idle", sessionKey: "session-idle", status: "idle", lastActive: 20)
        let future = active(id: "runtime-future", sessionKey: "session-future", status: "future-state", lastActive: 30)
        let model = ConversationHomeModel(
            sessions: [
                session(id: "session-future", startedAt: 30),
                session(id: "session-idle", startedAt: 20),
            ],
            activeSessions: [idle, future],
            lastUpdated: Date()
        )

        XCTAssertNil(model.highlightedSession)
        XCTAssertEqual(model.recentSessions.map(\.id), ["session-future", "session-idle"])
    }

    func testStatusCopyIsSentenceCaseAndFailClosed() {
        XCTAssertEqual(ConversationHomeModel.statusLabel(for: "waiting"), "Needs attention")
        XCTAssertEqual(ConversationHomeModel.statusLabel(for: "working"), "Running")
        XCTAssertEqual(ConversationHomeModel.statusLabel(for: "starting"), "Starting")
        XCTAssertEqual(ConversationHomeModel.statusLabel(for: "idle"), "Ready")
        XCTAssertEqual(ConversationHomeModel.statusLabel(for: "future-state"), "Status unavailable")
    }

    func testRecentListStillPublishesWhenLiveStatusRequestFails() async {
        let loader = ImmediateHomeLoader(
            sessions: [session(id: "recent", startedAt: 1)],
            activeError: FixtureError("live status unavailable")
        )
        let model = ConversationHomeModel()
        let context = ConversationHomeLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        await model.reload(using: loader, context: context, supportsActiveSessions: true)

        XCTAssertEqual(model.recentSessions.map(\.id), ["recent"])
        XCTAssertTrue(model.activeSessionsUnavailable)
        XCTAssertNil(model.loadError)
        XCTAssertNotNil(model.lastUpdated)
    }

    func testMissingLiveCapabilityIsExplicit() async {
        let loader = ImmediateHomeLoader(
            sessions: [session(id: "recent", startedAt: 1)]
        )
        let model = ConversationHomeModel()
        let context = ConversationHomeLoadContext(gatewayID: "legacy", connectionGeneration: 1)

        await model.reload(using: loader, context: context, supportsActiveSessions: false)

        XCTAssertEqual(model.recentSessions.map(\.id), ["recent"])
        XCTAssertTrue(model.activeSessionsUnavailable)
        XCTAssertNil(model.highlightedSession)
        XCTAssertNotNil(model.lastUpdated)
    }

    func testFailedRecentRequestNeverStartsLiveStatusRequest() async {
        let loader = RecentFailureHomeLoader()
        let model = ConversationHomeModel()
        let context = ConversationHomeLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        await model.reload(using: loader, context: context, supportsActiveSessions: true)
        await Task.yield()

        XCTAssertEqual(loader.activeCallCount, 0)
        XCTAssertEqual(model.loadError, "recent unavailable")
        XCTAssertFalse(model.isLoading)
    }

    func testOlderGatewayResponseCannotReplaceNewConnectionSnapshot() async {
        let oldLoader = SuspendedHomeLoader()
        let newLoader = ImmediateHomeLoader(
            sessions: [session(id: "new", startedAt: 2)]
        )
        let model = ConversationHomeModel()
        let oldContext = ConversationHomeLoadContext(gatewayID: "gateway-a", connectionGeneration: 1)
        let newContext = ConversationHomeLoadContext(gatewayID: "gateway-b", connectionGeneration: 2)

        let oldRequest = Task {
            await model.reload(
                using: oldLoader,
                context: oldContext,
                supportsActiveSessions: false
            )
        }
        await oldLoader.waitUntilSuspended()

        await model.reload(
            using: newLoader,
            context: newContext,
            supportsActiveSessions: false
        )
        oldLoader.succeed(with: [session(id: "old", startedAt: 1)])
        await oldRequest.value

        XCTAssertEqual(model.recentSessions.map(\.id), ["new"])
        XCTAssertNil(model.loadError)
    }

    func testCancelledLoadCannotPublishAfterTheTransportReturns() async {
        let loader = SuspendedHomeLoader()
        let model = ConversationHomeModel()
        let context = ConversationHomeLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        let request = Task {
            await model.reload(
                using: loader,
                context: context,
                supportsActiveSessions: true
            )
        }
        await loader.waitUntilSuspended()
        request.cancel()
        loader.succeed(with: [session(id: "stale", startedAt: 1)])
        await request.value

        XCTAssertTrue(model.sessions.isEmpty)
        XCTAssertEqual(loader.activeCallCount, 0)
        XCTAssertFalse(model.isLoading)
        XCTAssertNil(model.lastUpdated)
    }

    func testInitialPromptDispatchWaitsForSessionAndConsumesSynchronouslyOnce() {
        var dispatch = InitialPromptDispatch(prompt: "  Ship the build  ")
        var attempts: [String] = []

        XCTAssertNil(dispatch.beginIfReady(false, onAttempt: { attempts.append("early") }))
        XCTAssertFalse(dispatch.attempted)
        XCTAssertTrue(attempts.isEmpty)
        XCTAssertEqual(
            dispatch.beginIfReady(true, onAttempt: { attempts.append("admitted") }),
            "Ship the build"
        )
        XCTAssertEqual(attempts, ["admitted"])
        XCTAssertTrue(dispatch.attempted)
        XCTAssertNil(dispatch.beginIfReady(true, onAttempt: { attempts.append("duplicate") }))
        XCTAssertEqual(attempts, ["admitted"])
    }

    func testInitialPromptDispatchIgnoresBlankLaunchIntent() {
        var dispatch = InitialPromptDispatch(prompt: "  \n ")

        XCTAssertNil(dispatch.beginIfReady(true))
        XCTAssertFalse(dispatch.attempted)
    }

    func testUnknownCreateOutcomeCannotOfferNonIdempotentRetry() {
        XCTAssertEqual(
            SessionRecoveryAction(storedSessionId: nil),
            .returnToConversations
        )
        XCTAssertEqual(
            SessionRecoveryAction(storedSessionId: ""),
            .returnToConversations
        )
        XCTAssertEqual(
            SessionRecoveryAction(storedSessionId: "durable-session"),
            .retryResume
        )
    }

    private func session(id: String, startedAt: TimeInterval) -> SessionSummary {
        SessionSummary(
            id: id,
            title: "Conversation \(id)",
            preview: "Preview",
            startedAt: startedAt,
            messageCount: 3,
            source: "mobile"
        )
    }

    private func active(
        id: String,
        sessionKey: String,
        status: String,
        lastActive: TimeInterval
    ) -> ActiveSession {
        ActiveSession(payload: [
            "id": id,
            "session_key": sessionKey,
            "title": "Conversation \(id)",
            "preview": "Preview",
            "status": status,
            "model": "test-model",
            "message_count": 3,
            "last_active": lastActive,
            "current": false,
        ])!
    }
}

@MainActor
private final class ImmediateHomeLoader: ConversationHomeLoading {
    let sessions: [SessionSummary]
    let active: [ActiveSession]
    let sessionError: Error?
    let activeError: Error?

    init(
        sessions: [SessionSummary] = [],
        active: [ActiveSession] = [],
        sessionError: Error? = nil,
        activeError: Error? = nil
    ) {
        self.sessions = sessions
        self.active = active
        self.sessionError = sessionError
        self.activeError = activeError
    }

    func listSessions(limit: Int) async throws -> [SessionSummary] {
        if let sessionError { throw sessionError }
        return Array(sessions.prefix(limit))
    }

    func activeSessions(currentSessionId: String?) async throws -> [ActiveSession] {
        if let activeError { throw activeError }
        return active
    }
}

@MainActor
private final class SuspendedHomeLoader: ConversationHomeLoading {
    private var continuation: CheckedContinuation<[SessionSummary], Error>?
    private(set) var activeCallCount = 0

    func listSessions(limit: Int) async throws -> [SessionSummary] {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    func activeSessions(currentSessionId: String?) async throws -> [ActiveSession] {
        activeCallCount += 1
        return []
    }

    func waitUntilSuspended() async {
        while continuation == nil { await Task.yield() }
    }

    func succeed(with sessions: [SessionSummary]) {
        let pending = continuation
        continuation = nil
        pending?.resume(returning: sessions)
    }
}

@MainActor
private final class RecentFailureHomeLoader: ConversationHomeLoading {
    private(set) var activeCallCount = 0

    func listSessions(limit: Int) async throws -> [SessionSummary] {
        throw FixtureError("recent unavailable")
    }

    func activeSessions(currentSessionId: String?) async throws -> [ActiveSession] {
        activeCallCount += 1
        return []
    }
}

private struct FixtureError: LocalizedError {
    let message: String

    init(_ message: String) {
        self.message = message
    }

    var errorDescription: String? { message }
}
