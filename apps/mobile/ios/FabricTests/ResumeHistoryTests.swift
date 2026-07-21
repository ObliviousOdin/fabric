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
                    "payload": ["request_id": "approval-1", "description": "Run a command"],
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

    func testApprovalEventsRequireAnAuthoritativeRequestID() {
        let missing = GatewayEvent(
            type: "approval.request",
            sessionId: "runtime-123",
            payload: ["description": "Run a command"]
        )
        let blank = GatewayEvent(
            type: "approval.request",
            sessionId: "runtime-123",
            payload: ["request_id": "  "]
        )
        let valid = GatewayEvent(
            type: "approval.request",
            sessionId: "runtime-123",
            payload: ["request_id": "approval-1", "command": "pwd"]
        )

        XCTAssertNil(ChatViewModel.approval(from: missing))
        XCTAssertNil(ChatViewModel.approval(from: blank))
        XCTAssertEqual(ChatViewModel.approval(from: valid)?.requestId, "approval-1")
    }

    func testRichTranscriptParsesMarkdownCodeAndDiffInSourceOrder() {
        let source = """
        # Release **plan**

        Use the [runbook](https://example.test/runbook) before shipping.

        - Keep the plain path
        2. Ship the verified build

        ```swift
        let ready = true
        print("你好 👋")
        ```

        ```diff
        --- a/Foo.swift
        +++ b/Foo.swift
        @@ -1 +1 @@
        -old
        +new
        ```
        """

        let document = AssistantTranscriptDocument(source)

        XCTAssertEqual(
            document.blocks,
            [
                .heading(level: 1, text: "Release **plan**"),
                .paragraph("Use the [runbook](https://example.test/runbook) before shipping."),
                .listItem(marker: .unordered, depth: 0, text: "Keep the plain path"),
                .listItem(marker: .ordered("2."), depth: 0, text: "Ship the verified build"),
                .code(language: "swift", text: "let ready = true\nprint(\"你好 👋\")"),
                .diff("--- a/Foo.swift\n+++ b/Foo.swift\n@@ -1 +1 @@\n-old\n+new"),
            ]
        )
        XCTAssertTrue(document.containsTechnicalBlock)
    }

    func testNativeInlineMarkdownPreservesEmphasisAndLinkIntent() throws {
        let attributed = AssistantMarkdownSafety.attributedString(
            from: "Use **strong**, *emphasis*, and [docs](https://example.test/docs)."
        )

        XCTAssertEqual(String(attributed.characters), "Use strong, emphasis, and docs.")
        XCTAssertTrue(attributed.runs.contains {
            $0.inlinePresentationIntent?.contains(.stronglyEmphasized) == true
        })
        XCTAssertTrue(attributed.runs.contains {
            $0.inlinePresentationIntent?.contains(.emphasized) == true
        })
        XCTAssertEqual(
            attributed.runs.compactMap { $0.link?.absoluteString },
            ["https://example.test/docs"]
        )
    }

    func testNativeInlineMarkdownMakesNonWebLinksInert() {
        let attributed = AssistantMarkdownSafety.attributedString(
            from: "[web](https://example.test) [pair](fabric://pair?auth=token) "
                + "[file](file:///private/tmp/item) [relative](/mobile/pair) "
                + "[mail](mailto:person@example.test)"
        )

        XCTAssertEqual(
            String(attributed.characters),
            "web pair file relative mail"
        )
        XCTAssertEqual(
            attributed.runs.compactMap { $0.link?.absoluteString },
            ["https://example.test"]
        )
    }

    func testMarkdownImagesAreNeutralizedBeforeNativeParsing() {
        let source = """
        Before ![diagram](https://images.example.test/private.png)
        <IMG SRC="https://images.example.test/also-private.png" ALT="private">
        after
        """

        let sanitized = AssistantMarkdownSafety.sanitizedInline(source)
        let attributed = AssistantMarkdownSafety.attributedString(from: source)

        XCTAssertFalse(sanitized.contains("!["))
        XCTAssertFalse(sanitized.lowercased().contains("<img"))
        XCTAssertTrue(sanitized.contains("Image: [diagram]"))
        XCTAssertEqual(
            String(attributed.characters),
            "Before Image: diagram\nImage\nafter"
        )
    }

    func testMalformedFenceFallsBackToVerbatimProse() {
        let source = "Intro\n```swift\nlet value = **unfinished"
        let document = AssistantTranscriptDocument(source)

        XCTAssertEqual(document.blocks, [.paragraph(source)])
        XCTAssertFalse(document.containsTechnicalBlock)
        XCTAssertEqual(
            String(AssistantMarkdownSafety.attributedString(from: source).characters),
            source
        )
    }

    func testPlainTextRemainsOneLosslessParagraph() {
        let source = "Plain path_with_underscores\n中文 👋 مرحبًا — עברית"
        let document = AssistantTranscriptDocument(source)

        XCTAssertEqual(document.blocks, [.paragraph(source)])
        XCTAssertEqual(
            String(AssistantMarkdownSafety.attributedString(from: source).characters),
            source
        )
    }

    func testRawUnifiedDiffIsOneDeterministicTechnicalBlock() {
        let diff = """
        diff --git a/File.swift b/File.swift
        --- a/File.swift
        +++ b/File.swift
        @@ -1,2 +1,2 @@
        -let value = 1
        +let value = 2
         print(value)
        """

        XCTAssertEqual(AssistantTranscriptDocument(diff).blocks, [.diff(diff)])
    }

    func testStreamingAssistantStaysPlainUntilItsOwnCompletion() {
        let completed = TranscriptMessage(role: .assistant, text: "# Earlier answer")
        var streaming = TranscriptMessage(role: .assistant, text: "# Curr", streaming: true)

        XCTAssertEqual(AssistantTranscriptPresentationMode.mode(for: completed), .rich)
        XCTAssertEqual(AssistantTranscriptPresentationMode.mode(for: streaming), .streamingPlain)

        streaming.text += "ent answer\n```swift"
        XCTAssertEqual(AssistantTranscriptPresentationMode.mode(for: streaming), .streamingPlain)
        XCTAssertEqual(AssistantTranscriptPresentationMode.mode(for: completed), .rich)

        streaming.streaming = false
        XCTAssertEqual(AssistantTranscriptPresentationMode.mode(for: streaming), .rich)
        XCTAssertEqual(AssistantTranscriptPresentationMode.mode(for: completed), .rich)
    }

    func testLongCodeAndMultilingualProseRemainLossless() {
        let longLine = String(repeating: "x", count: 20_000)
        let code = "  indented\tvalue  \n\(longLine)"
        let prose = "中文 👋 مرحبًا — עברית"
        let source = "\(prose)\n\n```text\n\(code)\n```"
        let document = AssistantTranscriptDocument(source)

        XCTAssertEqual(
            document.blocks,
            [
                .paragraph(prose),
                .code(language: "text", text: code),
            ]
        )
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
