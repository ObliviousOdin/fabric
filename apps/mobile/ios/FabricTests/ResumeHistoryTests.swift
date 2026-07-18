import XCTest
@testable import Fabric

@MainActor
final class ResumeHistoryTests: XCTestCase {
    func testResumePayloadRestoresHistoryAndInflightTurnInOrder() {
        let payload: [String: Any] = [
            "session_id": "runtime-123",
            "session_key": "stored-authoritative",
            "history_version": 7,
            "running": true,
            "pending_interactions": [
                [
                    "type": "clarify.request",
                    "payload": ["request_id": "clarify-1", "question": "Choose one"],
                ],
                [
                    "type": "approval.request",
                    "payload": ["description": "Run a command"],
                ],
            ] as [[String: Any]],
            "inflight": [
                "user": "Follow-up question",
                "assistant": "Partial answer",
                "streaming": true,
            ] as [String: Any],
            "messages": [
                ["role": "user", "text": "Hello from the phone"],
                ["role": "assistant", "text": "Hello from Fabric"],
                ["role": "tool", "name": "terminal", "context": "terminal · pwd"],
                ["role": "system", "text": "Conversation restored"],
                ["role": "assistant", "text": "", "reasoning": "Considering the options"],
                [
                    "role": "assistant",
                    "text": "",
                    "codex_reasoning_items": [["summary": "Structured thought"]],
                ],
                ["role": "assistant", "text": "   "],
                ["role": "unknown", "text": "ignored"],
            ] as [[String: Any]],
        ]

        let live = LiveSession(resumePayload: payload, storedSessionId: "stored-456")

        XCTAssertEqual(live.sessionId, "runtime-123")
        XCTAssertEqual(live.storedSessionId, "stored-authoritative")
        XCTAssertEqual(live.historyVersion, 7)
        XCTAssertTrue(live.running)
        XCTAssertEqual(live.pendingInteractions.map(\.type), ["clarify.request", "approval.request"])
        XCTAssertEqual(live.pendingInteractions.map(\.sessionId), ["runtime-123", "runtime-123"])
        XCTAssertEqual(
            live.inflight,
            SessionInflight(user: "Follow-up question", assistant: "Partial answer", streaming: true)
        )
        XCTAssertEqual(
            live.messages,
            [
                SessionTranscriptMessage(role: .user, text: "Hello from the phone"),
                SessionTranscriptMessage(role: .assistant, text: "Hello from Fabric"),
                SessionTranscriptMessage(role: .tool, text: "terminal · pwd"),
                SessionTranscriptMessage(role: .system, text: "Conversation restored"),
                SessionTranscriptMessage(role: .assistant, text: "", reasoning: "Considering the options"),
                SessionTranscriptMessage(role: .assistant, text: "", reasoning: "Structured thought"),
            ]
        )

        let transcript = ChatViewModel.restoredMessages(from: live)
        XCTAssertEqual(
            transcript.map(\.role),
            [.user, .assistant, .info, .info, .info, .info, .user, .assistant]
        )
        XCTAssertEqual(
            transcript.map(\.text),
            [
                "Hello from the phone",
                "Hello from Fabric",
                "terminal · pwd",
                "Conversation restored",
                "Thinking…\nConsidering the options",
                "Thinking…\nStructured thought",
                "Follow-up question",
                "Partial answer",
            ]
        )
        XCTAssertEqual(transcript.map(\.streaming), [false, false, false, false, false, false, false, true])
    }

    func testResumePayloadFallsBackToStoredSessionId() {
        let live = LiveSession(
            resumePayload: ["messages": []],
            storedSessionId: "stored-session"
        )

        XCTAssertEqual(live.sessionId, "stored-session")
        XCTAssertTrue(live.messages.isEmpty)
        XCTAssertFalse(live.running)
        XCTAssertNil(live.inflight)
    }

    func testReplayDropsOnlyFramesAlreadyRepresentedByHistorySnapshot() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            messages: [SessionTranscriptMessage(role: .assistant, text: "Completed answer")],
            historyVersion: 1
        )
        let restored = ChatViewModel.restoredMessages(from: live)
        let events = [
            GatewayEvent(type: "message.start", sessionId: live.sessionId, payload: [:]),
            GatewayEvent(type: "message.delta", sessionId: live.sessionId, payload: ["text": "Completed answer"]),
            GatewayEvent(type: "thinking.delta", sessionId: live.sessionId, payload: ["text": "Stale thought"]),
            GatewayEvent(type: "tool.start", sessionId: live.sessionId, payload: ["name": "terminal"]),
            GatewayEvent(type: "status.update", sessionId: live.sessionId, payload: ["text": "Done"]),
            GatewayEvent(
                type: "message.complete",
                sessionId: live.sessionId,
                payload: ["text": "Completed answer", "history_version": 1, "history_persisted": true]
            ),
            GatewayEvent(type: "message.start", sessionId: live.sessionId, payload: [:]),
            GatewayEvent(type: "message.delta", sessionId: live.sessionId, payload: ["text": "Next answer"]),
        ]

        let replay = ChatViewModel.eventsForReplay(events, live: live, restoredMessages: restored)

        XCTAssertEqual(replay.map(\.type), ["message.start", "message.delta"])
    }

    func testReplayDoesNotInferSnapshotCoverageFromEqualTextWithoutHistoryVersion() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            messages: [SessionTranscriptMessage(role: .assistant, text: "Repeated answer")]
        )
        let events = [
            GatewayEvent(type: "message.start", sessionId: live.sessionId, payload: [:]),
            GatewayEvent(type: "message.delta", sessionId: live.sessionId, payload: ["text": "Repeated answer"]),
            GatewayEvent(type: "message.complete", sessionId: live.sessionId, payload: ["text": "Repeated answer"]),
        ]

        let replay = ChatViewModel.eventsForReplay(events, live: live, restoredMessages: [])

        XCTAssertEqual(replay.map(\.type), ["message.start", "message.delta", "message.complete"])
    }

    func testInflightSnapshotKeepsAuthoritativeCompletionForRepeatedReply() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            messages: [SessionTranscriptMessage(role: .assistant, text: "Same answer")],
            running: true,
            inflight: SessionInflight(user: "Ask again", assistant: "Same answer", streaming: true)
        )
        let restored = ChatViewModel.restoredMessages(from: live)
        let events = [
            GatewayEvent(type: "message.start", sessionId: live.sessionId, payload: [:]),
            GatewayEvent(type: "message.delta", sessionId: live.sessionId, payload: ["text": "Same answer"]),
            GatewayEvent(type: "message.complete", sessionId: live.sessionId, payload: ["text": "Same answer"]),
        ]

        let replay = ChatViewModel.eventsForReplay(events, live: live, restoredMessages: restored)

        XCTAssertEqual(restored.map(\.role), [.assistant, .user, .assistant])
        XCTAssertEqual(replay.map(\.type), ["message.complete"])
    }

    func testInflightReplayIgnoresOtherSessionsAsCompletionBoundaries() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            running: true,
            inflight: SessionInflight(user: "Question", assistant: "Partial", streaming: true)
        )
        let events = [
            GatewayEvent(type: "message.complete", sessionId: "other-session", payload: ["text": "Other"]),
            GatewayEvent(type: "message.start", sessionId: live.sessionId, payload: [:]),
            GatewayEvent(type: "message.delta", sessionId: live.sessionId, payload: ["text": "Partial"]),
            GatewayEvent(type: "message.complete", sessionId: live.sessionId, payload: ["text": "Final"]),
        ]

        let replay = ChatViewModel.eventsForReplay(events, live: live, restoredMessages: [])

        XCTAssertEqual(replay.map(\.sessionId), ["other-session", live.sessionId])
        XCTAssertEqual(replay.map(\.type), ["message.complete", "message.complete"])
    }

    func testHistoryVersionPreservesLegitimateRepeatedReplyAfterSnapshot() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            messages: [SessionTranscriptMessage(role: .assistant, text: "Same answer")],
            historyVersion: 3
        )
        let restored = ChatViewModel.restoredMessages(from: live)
        let events = [
            GatewayEvent(type: "message.start", sessionId: live.sessionId, payload: [:]),
            GatewayEvent(type: "message.delta", sessionId: live.sessionId, payload: ["text": "Same answer"]),
            GatewayEvent(
                type: "message.complete",
                sessionId: live.sessionId,
                payload: ["text": "Same answer", "history_version": 4, "history_persisted": true]
            ),
        ]

        let replay = ChatViewModel.eventsForReplay(events, live: live, restoredMessages: restored)

        XCTAssertEqual(replay.map(\.type), ["message.start", "message.delta", "message.complete"])
    }

    func testHistoryVersionDropsCompletionAlreadyCoveredBySnapshot() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            messages: [SessionTranscriptMessage(role: .assistant, text: "Completed answer")],
            historyVersion: 3
        )
        let restored = ChatViewModel.restoredMessages(from: live)
        let events = [
            GatewayEvent(type: "message.start", sessionId: live.sessionId, payload: [:]),
            GatewayEvent(type: "message.delta", sessionId: live.sessionId, payload: ["text": "Completed answer"]),
            GatewayEvent(
                type: "message.complete",
                sessionId: live.sessionId,
                payload: ["text": "Completed answer", "history_version": 3, "history_persisted": true]
            ),
            GatewayEvent(type: "status.update", sessionId: live.sessionId, payload: ["text": "Done"]),
        ]

        let replay = ChatViewModel.eventsForReplay(events, live: live, restoredMessages: restored)

        XCTAssertEqual(replay.map(\.type), ["status.update"])
    }

    func testUnpersistedCompletionIsNotHiddenByHistoryVersion() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            messages: [SessionTranscriptMessage(role: .assistant, text: "Earlier answer")],
            historyVersion: 3
        )
        let restored = ChatViewModel.restoredMessages(from: live)
        let completion = GatewayEvent(
            type: "message.complete",
            sessionId: live.sessionId,
            payload: ["text": "Unsaved response", "history_version": 3, "history_persisted": false]
        )

        let replay = ChatViewModel.eventsForReplay([completion], live: live, restoredMessages: restored)

        XCTAssertEqual(replay.map(\.type), ["message.complete"])
    }

    func testUnpersistedCompletionSurfacesServerWarning() {
        let event = GatewayEvent(
            type: "message.complete",
            sessionId: "runtime-123",
            payload: [
                "history_persisted": false,
                "warning": "History storage is unavailable.",
            ]
        )

        XCTAssertEqual(
            ChatViewModel.persistenceWarning(from: event),
            "History storage is unavailable."
        )
        XCTAssertNil(ChatViewModel.persistenceWarning(from: GatewayEvent(
            type: "message.complete",
            sessionId: "runtime-123",
            payload: ["history_persisted": true]
        )))
    }

    func testGatewayHTTPSessionDoesNotUsePersistentSharedStorage() {
        let configuration = GatewayAPI.httpSession.configuration

        XCTAssertNil(configuration.urlCache)
        XCTAssertFalse(configuration.urlCredentialStorage === URLCredentialStorage.shared)
        XCTAssertFalse(configuration.httpCookieStorage === HTTPCookieStorage.shared)
    }

    func testRpcErrorPreservesCodeAndData() {
        let error = GatewayClientError.rpc(body: [
            "message": "Approval expired",
            "code": -32_001,
            "data": ["retryable": false],
        ])

        guard case .rpc(let message, let code, let data) = error else {
            return XCTFail("Expected RPC error")
        }
        XCTAssertEqual(message, "Approval expired")
        XCTAssertEqual(code, -32_001)
        XCTAssertEqual((data as? [String: Bool])?["retryable"], false)
    }

    func testPendingInteractionQueuePreservesOrderAndDeduplicatesByIdentity() {
        let approval = PendingInteraction.approval(PendingApproval(
            command: "pwd", requestId: "approval-1", summary: "Run command"
        ))
        let duplicateCommandApproval = PendingInteraction.approval(PendingApproval(
            command: "pwd", requestId: "approval-2", summary: "Run command"
        ))
        let promptOne = PendingInteraction.prompt(PendingPrompt(
            kind: .clarify,
            requestId: "prompt-1",
            question: "First version",
            choices: []
        ))
        let promptTwo = PendingInteraction.prompt(PendingPrompt(
            kind: .secret,
            requestId: "prompt-2",
            question: "Secret",
            choices: []
        ))
        let updatedPromptOne = PendingInteraction.prompt(PendingPrompt(
            kind: .clarify,
            requestId: "prompt-1",
            question: "Updated version",
            choices: ["Yes"]
        ))

        var queue = PendingInteractionQueue()
        queue.enqueue(approval)
        queue.enqueue(duplicateCommandApproval)
        queue.enqueue(promptOne)
        queue.enqueue(promptTwo)
        queue.enqueue(updatedPromptOne)

        XCTAssertEqual(
            queue.items.map(\.identity),
            [
                approval.identity,
                duplicateCommandApproval.identity,
                promptTwo.identity,
                updatedPromptOne.identity,
            ]
        )
        XCTAssertEqual(queue.items.last, updatedPromptOne)
        queue.remove(approval)
        XCTAssertEqual(queue.first, duplicateCommandApproval)
        queue.clear()
        XCTAssertTrue(queue.items.isEmpty)
    }

    func testActiveSessionUsesStableSessionKeyForNavigation() {
        let session = ActiveSession(payload: [
            "id": "runtime-123",
            "session_key": "stored-456",
            "title": "Active chat",
            "status": "working",
        ])

        XCTAssertEqual(session?.id, "runtime-123")
        XCTAssertEqual(session?.sessionKey, "stored-456")
    }
}
