import XCTest
@testable import Fabric

final class InteractionReceiptTests: XCTestCase {
    func testApprovalReceiptRequiresExactRequestAndOneResolution() throws {
        XCTAssertNoThrow(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "approval-2", "resolved": 1],
                requestId: "approval-2",
                approval: true
            )
        )

        XCTAssertThrowsError(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "approval-1", "resolved": 1],
                requestId: "approval-2",
                approval: true
            )
        )
        XCTAssertThrowsError(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "approval-2", "resolved": 0],
                requestId: "approval-2",
                approval: true
            )
        )
    }

    func testGenericPromptReceiptRequiresExactRequest() throws {
        XCTAssertNoThrow(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "secret-2"],
                requestId: "secret-2"
            )
        )
        XCTAssertThrowsError(
            try GatewayAPI.requireMatchingInteractionReceipt(
                ["request_id": "secret-1"],
                requestId: "secret-2"
            )
        )
    }

    func testCommandFilteringIsDiacriticInsensitiveAndPreservesCatalogOrder() {
        let categories = [
            SlashCommandCategory(
                name: "Session",
                commands: [
                    SlashCommand(name: "/resume", detail: "Résumé a session"),
                    SlashCommand(name: "/new", detail: "Start a conversation"),
                ]
            ),
            SlashCommandCategory(
                name: "Info",
                commands: [
                    SlashCommand(name: "/status", detail: "Gateway health"),
                ]
            ),
        ]

        XCTAssertEqual(
            RemoteControlPresentation.filteredCategories(categories, query: "RESUME"),
            [
                SlashCommandCategory(
                    name: "Session",
                    commands: [SlashCommand(name: "/resume", detail: "Résumé a session")]
                ),
            ]
        )
        XCTAssertEqual(
            RemoteControlPresentation.filteredCategories(categories, query: "  gateway  "),
            [categories[1]]
        )
        XCTAssertEqual(
            RemoteControlPresentation.filteredCategories(categories, query: "   "),
            categories
        )
        XCTAssertTrue(
            RemoteControlPresentation.filteredCategories(categories, query: "not-present").isEmpty
        )
    }

    func testProcessOutputIsBoundedToTheNewestCharacters() {
        let prefix = String(repeating: "a", count: 200)
        let newest = String(repeating: "z", count: RemoteControlPresentation.outputCharacterLimit)
        let bounded = RemoteControlPresentation.boundedOutput(prefix + newest)

        XCTAssertEqual(bounded.count, RemoteControlPresentation.outputCharacterLimit)
        XCTAssertEqual(bounded, newest)
        XCTAssertEqual(RemoteControlPresentation.boundedOutput("short output"), "short output")
    }

    func testProcessStatusAlwaysHasALiteralLabel() {
        XCTAssertEqual(RemoteControlPresentation.statusLabel("running"), "Running")
        XCTAssertEqual(RemoteControlPresentation.statusLabel(" EXITED "), "Exited")
        XCTAssertEqual(RemoteControlPresentation.statusLabel(""), "Unknown")
    }

    func testProcessStopRequiresRunningCapabilityAndAnIdleMutationGate() {
        XCTAssertTrue(
            RemoteControlPresentation.canStopProcess(
                status: " RUNNING ",
                supportsKill: true,
                mutationInFlight: false,
                hasAuthoritativeSnapshot: true
            )
        )
        XCTAssertFalse(
            RemoteControlPresentation.canStopProcess(
                status: "running",
                supportsKill: false,
                mutationInFlight: false,
                hasAuthoritativeSnapshot: true
            )
        )
        XCTAssertFalse(
            RemoteControlPresentation.canStopProcess(
                status: "running",
                supportsKill: true,
                mutationInFlight: true,
                hasAuthoritativeSnapshot: true
            )
        )
        XCTAssertFalse(
            RemoteControlPresentation.canStopProcess(
                status: "exited",
                supportsKill: true,
                mutationInFlight: false,
                hasAuthoritativeSnapshot: true
            )
        )
        XCTAssertFalse(
            RemoteControlPresentation.canStopProcess(
                status: "running",
                supportsKill: true,
                mutationInFlight: false,
                hasAuthoritativeSnapshot: false
            )
        )
    }

    func testProcessStopStaysDisabledUntilAuthoritativeRefreshAfterFeedback() throws {
        var mutation = ProcessKillMutationState()
        let identity = try XCTUnwrap(
            mutation.begin(sessionId: "session-a", processId: "process-a")
        )

        mutation.record(.outcomeUnknown, for: identity)
        XCTAssertTrue(mutation.finish(identity))
        XCTAssertFalse(
            mutation.canStop(
                status: "running",
                supportsKill: true,
                loadState: .loaded
            )
        )

        mutation.didLoadAuthoritativeSnapshot()
        XCTAssertTrue(
            mutation.canStop(
                status: "running",
                supportsKill: true,
                loadState: .loaded
            )
        )
        XCTAssertFalse(
            mutation.canStop(
                status: "running",
                supportsKill: true,
                loadState: .failed("offline")
            )
        )
    }

    func testProcessStopIdentityPreventsOldCompletionFromClearingNewMutation() throws {
        var mutation = ProcessKillMutationState()
        let oldIdentity = try XCTUnwrap(
            mutation.begin(sessionId: "session-a", processId: "process-a")
        )
        XCTAssertNil(mutation.begin(sessionId: "session-a", processId: "process-a"))

        mutation.reset()
        let newIdentity = try XCTUnwrap(
            mutation.begin(sessionId: "session-b", processId: "process-b")
        )

        mutation.record(.rejected, for: oldIdentity)
        XCTAssertFalse(mutation.finish(oldIdentity))
        XCTAssertEqual(mutation.inFlight, newIdentity)
        XCTAssertNil(mutation.feedback)

        XCTAssertTrue(mutation.finish(newIdentity))
        XCTAssertNil(mutation.inFlight)
    }

    func testProcessKillReceiptRequiresAuthoritativeApplicationStatus() throws {
        XCTAssertEqual(
            try GatewayAPI.requireProcessKillReceipt(["status": "killed"]),
            .killed
        )
        XCTAssertEqual(
            try GatewayAPI.requireProcessKillReceipt(["status": "already_exited"]),
            .alreadyExited
        )
        XCTAssertEqual(
            try GatewayAPI.requireProcessKillReceipt(["status": "error"]),
            .rejected
        )
        XCTAssertEqual(
            try GatewayAPI.requireProcessKillReceipt(["status": "not_found"]),
            .rejected
        )
        XCTAssertThrowsError(try GatewayAPI.requireProcessKillReceipt([:]))
        XCTAssertThrowsError(
            try GatewayAPI.requireProcessKillReceipt(["status": "future_status"])
        )
    }

    func testAmbiguousKillFailureRequiresReadOnlyRefreshInsteadOfReplay() {
        XCTAssertEqual(
            ProcessKillFeedback.classify(
                GatewayClientError.requestTimedOut(method: "process.kill")
            ),
            .outcomeUnknown
        )
        XCTAssertEqual(
            ProcessKillFeedback.classify(GatewayClientError.socketClosed),
            .outcomeUnknown
        )
        XCTAssertEqual(
            ProcessKillFeedback.classify(GatewayClientError.notConnected),
            .outcomeUnknown
        )
        XCTAssertEqual(
            ProcessKillFeedback.classify(
                GatewayClientError.connectFailed(underlying: "offline")
            ),
            .outcomeUnknown
        )
        XCTAssertTrue(ProcessKillFeedback.outcomeUnknown.message.contains("Refresh status"))
        XCTAssertFalse(ProcessKillFeedback.outcomeUnknown.message.lowercased().contains("retry"))
    }

    func testRejectedKillIsDistinctFromAnUnknownOutcome() {
        XCTAssertEqual(
            ProcessKillFeedback.classify(
                GatewayClientError.rpc(message: "not allowed", code: -32_000)
            ),
            .rejected
        )
        XCTAssertNotEqual(ProcessKillFeedback.rejected, .outcomeUnknown)
    }

    func testLoadIdentityRejectsStaleGenerationAndChangedSession() {
        let identity = RemoteControlLoadIdentity(generation: 4, sessionId: "session-a")

        XCTAssertTrue(identity.isCurrent(generation: 4, sessionId: "session-a"))
        XCTAssertFalse(identity.isCurrent(generation: 5, sessionId: "session-a"))
        XCTAssertFalse(identity.isCurrent(generation: 4, sessionId: "session-b"))
        XCTAssertFalse(identity.isCurrent(generation: 4, sessionId: nil))
    }
}
