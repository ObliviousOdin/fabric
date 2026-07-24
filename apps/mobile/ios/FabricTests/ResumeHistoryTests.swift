import SwiftUI
import UIKit
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
                SessionTranscriptMessage(role: .tool, text: "terminal · pwd", toolName: "terminal"),
                SessionTranscriptMessage(role: .system, text: "Conversation restored"),
                SessionTranscriptMessage(role: .assistant, text: "", reasoning: "Considering the options"),
                SessionTranscriptMessage(role: .assistant, text: "", reasoning: "Structured thought"),
            ]
        )

        // Stored tool rows restore as completed activity cards inside an
        // assistant turn (the shape a live stream produces) and stored
        // reasoning restores as the turn's disclosure — not mono info rows.
        let transcript = ChatViewModel.restoredMessages(from: live)
        XCTAssertEqual(
            transcript.map(\.role),
            [.user, .assistant, .assistant, .info, .assistant, .user, .assistant]
        )
        XCTAssertEqual(
            transcript.map(\.text),
            [
                "Hello from the phone",
                "Hello from Fabric",
                "",
                "Conversation restored",
                "",
                "Follow-up question",
                "Partial answer",
            ]
        )
        XCTAssertEqual(
            transcript.map(\.streaming),
            [false, false, false, false, false, false, true]
        )

        guard case .tool(let tool) = transcript[2].assistantParts.first?.content else {
            return XCTFail("Expected the stored tool row to restore as an activity card")
        }
        XCTAssertEqual(tool.name, "terminal")
        XCTAssertEqual(tool.detail, "terminal · pwd")
        XCTAssertEqual(tool.state, .complete)

        let reasoningTexts = transcript[4].assistantParts.compactMap { part -> String? in
            guard case .reasoning(let reasoning) = part.content else { return nil }
            return reasoning.text
        }
        XCTAssertEqual(reasoningTexts, ["Considering the options", "Structured thought"])
    }

    func testResumeRestoresGeneratedImageAsOpaqueArtifact() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            messages: [
                SessionTranscriptMessage(role: .user, text: "Make a picture"),
                SessionTranscriptMessage(
                    role: .tool,
                    text: "image_generate",
                    toolName: "image_generate",
                    imageArtifactID: "image-call-1"
                ),
                SessionTranscriptMessage(role: .assistant, text: "Done.")
            ]
        )

        let transcript = ChatViewModel.restoredMessages(from: live)
        let restoredImage = transcript[1].assistantParts.compactMap { part -> AssistantTurnPart.GeneratedImage? in
            guard case .generatedImage(let image) = part.content else { return nil }
            return image
        }.first
        guard let image = restoredImage else {
            return XCTFail("Expected a restored generated-image part")
        }
        XCTAssertEqual(image.callID, "image-call-1")
        guard case .gatewayArtifact = image.source else {
            return XCTFail("Resume must retain an opaque gateway artifact")
        }
    }

    func testRestoredToolRowsFoldIntoTheFollowingAssistantTurn() {
        let live = LiveSession(
            sessionId: "runtime-123",
            storedSessionId: "stored-456",
            messages: [
                SessionTranscriptMessage(role: .user, text: "Check the build"),
                SessionTranscriptMessage(
                    role: .tool,
                    text: "terminal · xcodebuild test",
                    toolName: "terminal"
                ),
                SessionTranscriptMessage(
                    role: .tool,
                    text: "read_file · Package.swift",
                    toolName: "read_file"
                ),
                SessionTranscriptMessage(
                    role: .assistant,
                    text: "All 128 tests pass.",
                    reasoning: "Verified the log tail."
                ),
            ]
        )

        let transcript = ChatViewModel.restoredMessages(from: live)

        XCTAssertEqual(transcript.map(\.role), [.user, .assistant])
        XCTAssertEqual(transcript[1].text, "All 128 tests pass.")
        let kinds = transcript[1].assistantParts.map { part -> String in
            switch part.content {
            case .tool: return "tool"
            case .reasoning: return "reasoning"
            case .generatedImage: return "image"
            case .text: return "text"
            }
        }
        XCTAssertEqual(kinds, ["tool", "tool", "reasoning", "text"])
        XCTAssertEqual(
            Set(transcript[1].assistantParts.map(\.id)).count,
            transcript[1].assistantParts.count,
            "Restored part identifiers must be unique for SwiftUI identity"
        )
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

    func testGatewayDiscoveryHTTPSessionIsStatelessAndNonPersistent() {
        let configuration = GatewayAPI.httpSession.configuration

        XCTAssertNil(configuration.urlCache)
        XCTAssertNil(configuration.httpCookieStorage)
        XCTAssertFalse(configuration.httpShouldSetCookies)
        XCTAssertEqual(configuration.httpCookieAcceptPolicy, .never)
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

    func testActiveMarkdownAndRawImagesBecomeInertAltText() {
        let source = """
        Before ![diagram **v2**](https://images.example.test/private.png)
        <IMG SRC="https://images.example.test/also-private.png" ALT="private **diagram** & notes">
        after
        """

        let sanitized = AssistantMarkdownSafety.sanitizedInline(source)
        let attributed = AssistantMarkdownSafety.attributedString(from: source)

        XCTAssertTrue(sanitized.contains("![diagram **v2**]"))
        XCTAssertFalse(sanitized.lowercased().contains("<img"))
        XCTAssertFalse(sanitized.contains("also-private.png"))
        XCTAssertTrue(attributed.runs.allSatisfy { $0.imageURL == nil })
        XCTAssertEqual(
            String(attributed.characters),
            "Before Image: diagram v2\nImage: private **diagram** & notes\nafter"
        )
    }

    func testImageSanitizerPreservesEscapedAndInlineCodeExamples() {
        let source = #"""
        Escaped \![diagram](https://images.example.test/escaped.png)
        Escaped \<img alt="escaped" src="https://images.example.test/escaped-html.png">
        Code `![inline](https://images.example.test/code.png)` and `<img alt="inline" src="https://images.example.test/code-html.png">`
        Double ``literal ` ![nested](https://images.example.test/nested.png) <img alt="nested" src="https://images.example.test/nested-html.png">``
        """#

        XCTAssertEqual(AssistantMarkdownSafety.sanitizedInline(source), source)
        XCTAssertTrue(
            String(AssistantMarkdownSafety.attributedString(from: source).characters)
                .contains("![inline](https://images.example.test/code.png)")
        )
    }

    func testImageSanitizerHandlesReferenceRawAltAndMalformedBoundaries() {
        let active = "![](https://private.test/empty.png) "
            + "![apostrophe](https://private.test/a'b.png) "
            + "![title](https://private.test/x \"title ) still\") "
            + "<iMg data-alt=wrong ALT='one > two' src=https://private.test/x> <img src=x>"
        let activeAttributed = AssistantMarkdownSafety.attributedString(from: active)

        XCTAssertEqual(
            String(activeAttributed.characters),
            "Image Image: apostrophe Image: title Image: one > two Image"
        )
        XCTAssertTrue(activeAttributed.runs.allSatisfy { $0.imageURL == nil })
        XCTAssertFalse(String(activeAttributed.characters).contains("private.test"))

        let literal = "Reference ![reference][asset] bare ![shortcut] "
            + "broken ![image](https://private.test/x <img alt='unfinished'"
        XCTAssertEqual(AssistantMarkdownSafety.sanitizedInline(literal), literal)
        XCTAssertTrue(
            AssistantMarkdownSafety.attributedString(from: literal).runs
                .allSatisfy { $0.imageURL == nil }
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

    func testCompletedTranscriptCachesInlineRenderingAcrossLaterStreamingDeltas() {
        let completedInput = AssistantTranscriptRenderInput(
            text: "# Earlier **answer**\n\n- Read the [runbook](https://example.test/runbook)",
            streaming: false
        )
        var documentBuildCount = 0
        var inlineParseCount = 0
        var stateWriteCount = 0
        var cache = AssistantTranscriptRenderCache()

        func buildDocument(_ source: String) -> AssistantTranscriptDocument {
            documentBuildCount += 1
            return AssistantTranscriptDocument(source) { markdown in
                inlineParseCount += 1
                return AssistantMarkdownSafety.attributedString(from: markdown)
            }
        }

        func reconcile(_ input: AssistantTranscriptRenderInput) {
            guard let updated = cache.reconciled(
                for: input,
                documentBuilder: buildDocument
            ) else { return }
            stateWriteCount += 1
            cache = updated
        }

        reconcile(completedInput)
        XCTAssertEqual(documentBuildCount, 1)
        XCTAssertEqual(inlineParseCount, 2, "Heading and list item render once at completion")
        XCTAssertEqual(stateWriteCount, 1)
        XCTAssertEqual(cache.document?.renderBlocks.count, 2)

        var liveCache = AssistantTranscriptRenderCache()
        var liveStateWriteCount = 0
        for delta in ["# N", "# Ne", "# New answer"] {
            // A later row's delta rebuilds the visible transcript, but this
            // completed row still reconciles against its unchanged input.
            if let updated = liveCache.reconciled(
                for: AssistantTranscriptRenderInput(text: delta, streaming: true)
            ) {
                liveStateWriteCount += 1
                liveCache = updated
            }
            reconcile(completedInput)
            _ = cache.document?.renderBlocks
        }

        XCTAssertEqual(documentBuildCount, 1)
        XCTAssertEqual(inlineParseCount, 2)
        XCTAssertEqual(stateWriteCount, 1)
        XCTAssertEqual(liveStateWriteCount, 0, "Streaming deltas never mutate an empty rich cache")
    }

    func testStreamingCacheClearsRichStateOnlyOnActualTransition() {
        var documentBuildCount = 0
        var stateWriteCount = 0
        var cache = AssistantTranscriptRenderCache()

        func buildDocument(_ source: String) -> AssistantTranscriptDocument {
            documentBuildCount += 1
            return AssistantTranscriptDocument(source)
        }

        func reconcile(_ input: AssistantTranscriptRenderInput) {
            guard let updated = cache.reconciled(
                for: input,
                documentBuilder: buildDocument
            ) else { return }
            stateWriteCount += 1
            cache = updated
        }

        reconcile(AssistantTranscriptRenderInput(text: "Earlier answer", streaming: false))
        XCTAssertNotNil(cache.document)
        XCTAssertEqual(documentBuildCount, 1)
        XCTAssertEqual(stateWriteCount, 1)

        reconcile(AssistantTranscriptRenderInput(text: "N", streaming: true))
        XCTAssertNil(cache.document)
        XCTAssertEqual(stateWriteCount, 2, "Rich-to-streaming clears the cached document once")

        reconcile(AssistantTranscriptRenderInput(text: "Ne", streaming: true))
        reconcile(AssistantTranscriptRenderInput(text: "New", streaming: true))
        XCTAssertEqual(documentBuildCount, 1)
        XCTAssertEqual(stateWriteCount, 2, "Later deltas do not write the same nil state")

        reconcile(AssistantTranscriptRenderInput(text: "New answer", streaming: false))
        XCTAssertNotNil(cache.document)
        XCTAssertEqual(documentBuildCount, 2)
        XCTAssertEqual(stateWriteCount, 3)

        reconcile(AssistantTranscriptRenderInput(text: "New answer", streaming: false))
        XCTAssertEqual(documentBuildCount, 2)
        XCTAssertEqual(stateWriteCount, 3, "Unchanged rich input is already cached")
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

    func testCompletingTallRichReplyKeepsTranscriptAtBottomAfterRelayout() async {
        var message = TranscriptMessage(
            role: .assistant,
            text: "Working…",
            streaming: true
        )
        let host = UIHostingController(rootView: TranscriptView(messages: [message]))
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 320, height: 180))
        window.rootViewController = host
        window.isHidden = false
        defer { window.isHidden = true }

        host.view.frame = window.bounds
        host.view.setNeedsLayout()
        host.view.layoutIfNeeded()
        try? await Task.sleep(for: .milliseconds(20))

        let code = (0..<40)
            .map { "let row\($0) = \($0)" }
            .joined(separator: "\n")
        let completedText = """
        # Finished

        - Verified the complete response
        - Preserved the final code block

        ```swift
        \(code)
        ```
        """
        message = AssistantTurnReducer.reducing(
            message,
            event: .messageComplete(authoritativeText: completedText)
        )
        host.rootView = TranscriptView(messages: [message])

        var lastMetrics: (offset: CGFloat, maximum: CGFloat, content: CGFloat, viewport: CGFloat)?
        for _ in 0..<100 {
            host.view.setNeedsLayout()
            host.view.layoutIfNeeded()
            if let scrollView = transcriptScrollView(in: host.view) {
                let maximum = max(
                    -scrollView.adjustedContentInset.top,
                    scrollView.contentSize.height
                        - scrollView.bounds.height
                        + scrollView.adjustedContentInset.bottom
                )
                lastMetrics = (
                    scrollView.contentOffset.y,
                    maximum,
                    scrollView.contentSize.height,
                    scrollView.bounds.height
                )
                // `scrollTo(lastMessage, anchor: .bottom)` intentionally
                // leaves the LazyVStack's standard trailing padding below
                // the fully visible row. A rich relayout regression leaves
                // substantially more than that one padding interval hidden.
                if scrollView.contentSize.height > scrollView.bounds.height + 40,
                   abs(scrollView.contentOffset.y - maximum) <= 20 {
                    return
                }
            }
            try? await Task.sleep(for: .milliseconds(10))
        }

        guard let lastMetrics else {
            var scrollViews: [UIScrollView] = []
            collectScrollViews(in: host.view, into: &scrollViews)
            let metrics = scrollViews.map {
                "content=\($0.contentSize), bounds=\($0.bounds), offset=\($0.contentOffset)"
            }
            return XCTFail(
                "Expected the hosted transcript to contain a vertical scroll view; "
                    + "candidates=\(metrics)"
            )
        }
        XCTFail(
            "Expected rich completion at bottom; offset=\(lastMetrics.offset), "
                + "maximum=\(lastMetrics.maximum), content=\(lastMetrics.content), "
                + "viewport=\(lastMetrics.viewport)"
        )
    }

    private func transcriptScrollView(in root: UIView) -> UIScrollView? {
        var candidates: [UIScrollView] = []
        collectScrollViews(in: root, into: &candidates)
        return candidates
            .filter { $0.contentSize.height > $0.bounds.height + 1 }
            .max { $0.contentSize.height < $1.contentSize.height }
    }

    private func collectScrollViews(in view: UIView, into result: inout [UIScrollView]) {
        if let scrollView = view as? UIScrollView {
            result.append(scrollView)
        }
        for child in view.subviews {
            collectScrollViews(in: child, into: &result)
        }
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
