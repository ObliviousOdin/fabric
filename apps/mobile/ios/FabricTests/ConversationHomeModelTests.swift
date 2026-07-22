import XCTest
@testable import Fabric

@MainActor
final class ConversationHomeModelTests: XCTestCase {
    private var temporarySnapshotDirectories: [URL] = []

    override func tearDownWithError() throws {
        for directory in temporarySnapshotDirectories {
            try? FileManager.default.removeItem(at: directory)
        }
        temporarySnapshotDirectories.removeAll()
        try super.tearDownWithError()
    }

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
        let model = isolatedHomeModel()
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
        let model = isolatedHomeModel()
        let context = ConversationHomeLoadContext(gatewayID: "legacy", connectionGeneration: 1)

        await model.reload(using: loader, context: context, supportsActiveSessions: false)

        XCTAssertEqual(model.recentSessions.map(\.id), ["recent"])
        XCTAssertTrue(model.activeSessionsUnavailable)
        XCTAssertNil(model.highlightedSession)
        XCTAssertNotNil(model.lastUpdated)
    }

    func testSessionLibrarySearchIgnoresCaseAndDiacriticsAcrossServerFields() {
        let titleMatch = session(
            id: "title",
            startedAt: 30,
            title: "Résumé planning",
            preview: "Outline",
            source: "mobile"
        )
        let previewMatch = session(
            id: "preview",
            startedAt: 20,
            title: "Launch notes",
            preview: "Meet at the Café",
            source: "mobile"
        )
        let activeHistory = session(
            id: "active-source",
            startedAt: 10,
            title: "Historical server title",
            preview: "Older preview",
            source: "Cöworker"
        )
        let live = active(
            id: "runtime-source",
            sessionKey: activeHistory.id,
            status: "working",
            lastActive: 40,
            title: "Current server title",
            preview: "Live preview"
        )
        let rows = [titleMatch, previewMatch, activeHistory]

        let titleProjection = SessionLibraryProjection(
            sessions: rows,
            activeSessions: [live],
            pinnedSessionKeys: [],
            query: "RESUME"
        )
        XCTAssertEqual(titleProjection.recent.map(\.durableSessionKey), ["title"])
        XCTAssertEqual(titleProjection.recent.first?.displayTitle, titleMatch.title)

        let previewProjection = SessionLibraryProjection(
            sessions: rows,
            activeSessions: [live],
            pinnedSessionKeys: [],
            query: "cafe"
        )
        XCTAssertEqual(previewProjection.recent.map(\.durableSessionKey), ["preview"])

        let sourceProjection = SessionLibraryProjection(
            sessions: rows,
            activeSessions: [live],
            pinnedSessionKeys: [],
            query: "coworker"
        )
        XCTAssertEqual(sourceProjection.active.map(\.durableSessionKey), ["active-source"])
        XCTAssertTrue(sourceProjection.recent.isEmpty)
        XCTAssertEqual(sourceProjection.active.first?.displayTitle, live.title)
    }

    func testSessionLibraryPinsFirstThenUsesActivityAndStableIDWithoutDuplicates() {
        let duplicateHistory = session(
            id: "duplicate",
            startedAt: 100,
            title: "Server title"
        )
        let projection = SessionLibraryProjection(
            sessions: [
                duplicateHistory,
                session(id: "recent-b", startedAt: 50),
                session(id: "recent-a", startedAt: 50),
                session(id: "pinned-recent", startedAt: 5),
            ],
            activeSessions: [
                active(
                    id: "runtime-duplicate-old",
                    sessionKey: duplicateHistory.id,
                    status: "working",
                    lastActive: 10,
                    title: "Stale live title"
                ),
                active(
                    id: "runtime-duplicate-new",
                    sessionKey: duplicateHistory.id,
                    status: "working",
                    lastActive: 20,
                    title: "Current live title"
                ),
                active(
                    id: "runtime-b",
                    sessionKey: "active-b",
                    status: "working",
                    lastActive: 20
                ),
                active(
                    id: "runtime-a",
                    sessionKey: "active-a",
                    status: "working",
                    lastActive: 20
                ),
                active(
                    id: "runtime-pinned",
                    sessionKey: "pinned-active",
                    status: "idle",
                    lastActive: 6
                ),
            ],
            pinnedSessionKeys: ["pinned-active", "pinned-recent"],
            query: ""
        )

        XCTAssertEqual(
            projection.pinned.map(\.durableSessionKey),
            ["pinned-active", "pinned-recent"]
        )
        XCTAssertEqual(
            projection.active.map(\.durableSessionKey),
            ["active-a", "active-b", "duplicate"]
        )
        XCTAssertEqual(
            projection.recent.map(\.durableSessionKey),
            ["recent-b", "recent-a"]
        )
        XCTAssertEqual(
            projection.active.filter { $0.durableSessionKey == duplicateHistory.id }.count,
            1
        )
        XCTAssertFalse(
            projection.recent.contains { $0.durableSessionKey == duplicateHistory.id }
        )
        XCTAssertEqual(
            projection.active.last?.displayTitle,
            "Current live title",
            "The newest active server row remains the title authority"
        )
    }

    func testSessionLibraryWithoutActiveCapabilityStillPublishesRecentAndPins() {
        let projection = SessionLibraryProjection(
            sessions: [
                session(id: "recent", startedAt: 20),
                session(id: "pinned", startedAt: 10),
            ],
            activeSessions: [],
            pinnedSessionKeys: ["pinned"],
            query: ""
        )

        XCTAssertTrue(projection.active.isEmpty)
        XCTAssertEqual(projection.pinned.map(\.durableSessionKey), ["pinned"])
        XCTAssertEqual(projection.recent.map(\.durableSessionKey), ["recent"])
    }

    func testSessionLibraryKeepsGatewayRecencyOrderInsteadOfCreationTime() {
        let projection = SessionLibraryProjection(
            sessions: [
                session(id: "recently-used-old-conversation", startedAt: 1),
                session(id: "less-recent-new-conversation", startedAt: 500),
                session(id: "oldest-result", startedAt: 200),
            ],
            activeSessions: [],
            pinnedSessionKeys: [],
            query: ""
        )

        XCTAssertEqual(
            projection.recent.map(\.durableSessionKey),
            [
                "recently-used-old-conversation",
                "less-recent-new-conversation",
                "oldest-result",
            ],
            "session.list order represents effective last activity; creation time must not re-rank it"
        )
    }

    func testSessionLibraryPinsPersistPerGatewayAndDurableSessionKey() throws {
        let suiteName = "SessionLibraryPinStoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = SessionLibraryPinStore(defaults: defaults)

        store.setPinned(true, gatewayID: "gateway-a", sessionKey: "shared-session")
        store.setPinned(true, gatewayID: "gateway-a", sessionKey: "only-on-a")
        store.setPinned(true, gatewayID: "gateway-b", sessionKey: "shared-session")

        XCTAssertEqual(
            store.pinnedSessionKeys(for: "gateway-a"),
            ["shared-session", "only-on-a"]
        )
        XCTAssertEqual(store.pinnedSessionKeys(for: "gateway-b"), ["shared-session"])

        store.setPinned(false, gatewayID: "gateway-a", sessionKey: "shared-session")

        XCTAssertEqual(store.pinnedSessionKeys(for: "gateway-a"), ["only-on-a"])
        XCTAssertEqual(
            store.pinnedSessionKeys(for: "gateway-b"),
            ["shared-session"],
            "Unpinning one saved gateway must not affect another gateway"
        )
    }

    func testSessionLibraryModelMissingListCapabilityNeverCallsTransport() async {
        let loader = CountingSessionLibraryLoader()
        let model = SessionLibraryModel()
        let context = SessionLibraryLoadContext(gatewayID: "legacy", connectionGeneration: 1)

        await model.reload(
            using: loader,
            context: context,
            supportsSessionList: false,
            supportsActiveSessions: false,
            unavailableMessage: "Upgrade required"
        )

        XCTAssertEqual(loader.listCallCount, 0)
        XCTAssertEqual(loader.activeCallCount, 0)
        XCTAssertTrue(model.sessions.isEmpty)
        XCTAssertTrue(model.activeSessions.isEmpty)
        XCTAssertTrue(model.activeSessionsUnavailable)
        XCTAssertEqual(model.loadError, "Upgrade required")
        XCTAssertFalse(model.isLoading)
    }

    func testSessionLibraryModelPublishesHistoryBeforeLiveStatusCompletes() async {
        let historical = session(id: "recent", startedAt: 1)
        let live = active(
            id: "runtime-live",
            sessionKey: historical.id,
            status: "working",
            lastActive: 2
        )
        let loader = SuspendedActiveSessionLibraryLoader(sessions: [historical])
        let model = SessionLibraryModel()
        let context = SessionLibraryLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        let request = Task {
            await model.reload(
                using: loader,
                context: context,
                supportsSessionList: true,
                supportsActiveSessions: true
            )
        }
        await loader.waitUntilActiveSuspended()

        XCTAssertEqual(model.sessions.map(\.id), [historical.id])
        XCTAssertTrue(model.activeSessions.isEmpty)
        XCTAssertTrue(model.isLoadingActiveSessions)
        XCTAssertNil(model.loadError)
        XCTAssertFalse(model.isLoading)

        loader.succeedActive(with: [live])
        await request.value

        XCTAssertEqual(model.activeSessions.map(\.id), [live.id])
        XCTAssertFalse(model.isLoadingActiveSessions)
        XCTAssertFalse(model.activeSessionsUnavailable)
    }

    func testSessionLibraryModelCancelledLiveStatusBecomesExplicitlyUnavailable() async {
        let historical = session(id: "recent", startedAt: 1)
        let loader = SuspendedActiveSessionLibraryLoader(sessions: [historical])
        let model = SessionLibraryModel()
        let context = SessionLibraryLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        let request = Task {
            await model.reload(
                using: loader,
                context: context,
                supportsSessionList: true,
                supportsActiveSessions: true
            )
        }
        await loader.waitUntilActiveSuspended()
        request.cancel()
        loader.succeedActive(with: [])
        await request.value

        XCTAssertEqual(model.sessions.map(\.id), [historical.id])
        XCTAssertTrue(model.activeSessions.isEmpty)
        XCTAssertFalse(model.isLoadingActiveSessions)
        XCTAssertTrue(model.activeSessionsUnavailable)
        XCTAssertNil(model.loadError)
        XCTAssertFalse(model.isLoading)
    }

    func testSessionLibraryModelKeepsHistoryWhenLiveStatusFails() async {
        let loader = ImmediateHomeLoader(
            sessions: [session(id: "recent", startedAt: 1)],
            activeError: FixtureError("live unavailable")
        )
        let model = SessionLibraryModel()
        let context = SessionLibraryLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        await model.reload(
            using: loader,
            context: context,
            supportsSessionList: true,
            supportsActiveSessions: true
        )

        XCTAssertEqual(model.sessions.map(\.id), ["recent"])
        XCTAssertTrue(model.activeSessions.isEmpty)
        XCTAssertFalse(model.isLoadingActiveSessions)
        XCTAssertTrue(model.activeSessionsUnavailable)
        XCTAssertNil(model.loadError)
        XCTAssertFalse(model.isLoading)
    }

    func testSessionLibraryFailureUsesSafeRecoveryCopy() async {
        let model = SessionLibraryModel()
        let context = SessionLibraryLoadContext(
            gatewayID: "gateway",
            connectionGeneration: 1
        )

        await model.reload(
            using: SessionListFailureLoader(),
            context: context,
            supportsSessionList: true,
            supportsActiveSessions: true
        )

        XCTAssertEqual(
            model.loadError,
            "Couldn't load sessions. Check the connection and pull to retry."
        )
        XCTAssertFalse(model.loadError?.contains("raw-secret") == true)
        XCTAssertFalse(model.loadError?.contains("/Users/private") == true)
        XCTAssertFalse(model.isLoading)
    }

    func testSessionLibraryModelNewerSameGatewayReloadRejectsOlderCompletion() async {
        let oldLoader = SuspendedHomeLoader()
        let newLoader = ImmediateHomeLoader(
            sessions: [session(id: "new", startedAt: 2)]
        )
        let model = SessionLibraryModel()
        let context = SessionLibraryLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        let oldRequest = Task {
            await model.reload(
                using: oldLoader,
                context: context,
                supportsSessionList: true,
                supportsActiveSessions: false
            )
        }
        await oldLoader.waitUntilSuspended()

        await model.reload(
            using: newLoader,
            context: context,
            supportsSessionList: true,
            supportsActiveSessions: false
        )
        oldLoader.succeed(with: [session(id: "old", startedAt: 1)])
        await oldRequest.value

        XCTAssertEqual(model.sessions.map(\.id), ["new"])
        XCTAssertNil(model.loadError)
    }

    func testSessionLibraryModelGatewaySwitchRejectsOlderCompletion() async {
        let oldLoader = SuspendedHomeLoader()
        let newLoader = ImmediateHomeLoader(
            sessions: [session(id: "new-gateway", startedAt: 2)]
        )
        let model = SessionLibraryModel()
        let oldContext = SessionLibraryLoadContext(gatewayID: "gateway-a", connectionGeneration: 1)
        let newContext = SessionLibraryLoadContext(gatewayID: "gateway-b", connectionGeneration: 2)

        let oldRequest = Task {
            await model.reload(
                using: oldLoader,
                context: oldContext,
                supportsSessionList: true,
                supportsActiveSessions: false
            )
        }
        await oldLoader.waitUntilSuspended()

        await model.reload(
            using: newLoader,
            context: newContext,
            supportsSessionList: true,
            supportsActiveSessions: false
        )
        oldLoader.succeed(with: [session(id: "old-gateway", startedAt: 1)])
        await oldRequest.value

        XCTAssertEqual(model.sessions.map(\.id), ["new-gateway"])
        XCTAssertNil(model.loadError)
    }

    func testSessionLibraryModelCancelledLoadCannotPublish() async {
        let loader = SuspendedHomeLoader()
        let model = SessionLibraryModel()
        let context = SessionLibraryLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        let request = Task {
            await model.reload(
                using: loader,
                context: context,
                supportsSessionList: true,
                supportsActiveSessions: false
            )
        }
        await loader.waitUntilSuspended()
        request.cancel()
        loader.succeed(with: [session(id: "stale", startedAt: 1)])
        await request.value

        XCTAssertTrue(model.sessions.isEmpty)
        XCTAssertTrue(model.activeSessions.isEmpty)
        XCTAssertNil(model.loadError)
        XCTAssertFalse(model.isLoading)
    }

    func testFailedRecentRequestNeverStartsLiveStatusRequest() async {
        let loader = RecentFailureHomeLoader()
        let model = isolatedHomeModel()
        let context = ConversationHomeLoadContext(gatewayID: "gateway", connectionGeneration: 1)

        await model.reload(using: loader, context: context, supportsActiveSessions: true)
        await Task.yield()

        XCTAssertEqual(loader.activeCallCount, 0)
        XCTAssertEqual(
            model.loadError,
            "Couldn't refresh Home. Check the connection and pull to retry."
        )
        XCTAssertFalse(model.loadError?.contains("recent unavailable") == true)
        XCTAssertFalse(model.isLoading)
    }

    func testOlderGatewayResponseCannotReplaceNewConnectionSnapshot() async {
        let oldLoader = SuspendedHomeLoader()
        let newLoader = ImmediateHomeLoader(
            sessions: [session(id: "new", startedAt: 2)]
        )
        let model = isolatedHomeModel()
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
        let model = isolatedHomeModel()
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

    private func isolatedHomeModel() -> ConversationHomeModel {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ConversationHomeModelTests", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        temporarySnapshotDirectories.append(directory)
        return ConversationHomeModel(
            snapshotStore: ConversationHomeSnapshotStore(directoryURL: directory)
        )
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

    private func session(
        id: String,
        startedAt: TimeInterval,
        title: String? = nil,
        preview: String = "Preview",
        source: String = "mobile"
    ) -> SessionSummary {
        SessionSummary(
            id: id,
            title: title ?? "Conversation \(id)",
            preview: preview,
            startedAt: startedAt,
            messageCount: 3,
            source: source
        )
    }

    private func active(
        id: String,
        sessionKey: String,
        status: String,
        lastActive: TimeInterval,
        title: String? = nil,
        preview: String = "Preview"
    ) -> ActiveSession {
        ActiveSession(payload: [
            "id": id,
            "session_key": sessionKey,
            "title": title ?? "Conversation \(id)",
            "preview": preview,
            "status": status,
            "model": "test-model",
            "message_count": 3,
            "last_active": lastActive,
            "current": false,
        ])!
    }
}

@MainActor
private final class ImmediateHomeLoader: ConversationHomeLoading, SessionLibraryLoading {
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
private final class SuspendedHomeLoader: ConversationHomeLoading, SessionLibraryLoading {
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
private final class CountingSessionLibraryLoader: SessionLibraryLoading {
    private(set) var listCallCount = 0
    private(set) var activeCallCount = 0

    func listSessions(limit: Int) async throws -> [SessionSummary] {
        listCallCount += 1
        return []
    }

    func activeSessions(currentSessionId: String?) async throws -> [ActiveSession] {
        activeCallCount += 1
        return []
    }
}

@MainActor
private final class SessionListFailureLoader: SessionLibraryLoading {
    func listSessions(limit: Int) async throws -> [SessionSummary] {
        throw FixtureError("Authorization: Bearer raw-secret /Users/private/.fabric")
    }

    func activeSessions(currentSessionId: String?) async throws -> [ActiveSession] {
        XCTFail("A failed authoritative session list must not start live-status loading")
        return []
    }
}

@MainActor
private final class SuspendedActiveSessionLibraryLoader: SessionLibraryLoading {
    let sessions: [SessionSummary]
    private var continuation: CheckedContinuation<[ActiveSession], Error>?

    init(sessions: [SessionSummary]) {
        self.sessions = sessions
    }

    func listSessions(limit: Int) async throws -> [SessionSummary] {
        Array(sessions.prefix(limit))
    }

    func activeSessions(currentSessionId: String?) async throws -> [ActiveSession] {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    func waitUntilActiveSuspended() async {
        while continuation == nil { await Task.yield() }
    }

    func succeedActive(with sessions: [ActiveSession]) {
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
