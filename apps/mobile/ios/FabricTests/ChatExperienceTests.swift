import XCTest
@testable import Fabric

final class ChatExperienceTests: XCTestCase {
    func testAssistantActivityFoldsInTranscriptOrderAndPersistsToolCompletion() {
        var message = TranscriptMessage(role: .assistant, text: "", streaming: true)
        let events: [AssistantTurnEvent] = [
            .reasoningDelta("Checking the branch."),
            .toolGenerating(name: "xcodebuild"),
            .toolStarted(
                callID: "call-1",
                name: "xcodebuild",
                detail: "Running simulator tests"
            ),
            .toolProgress(
                callID: "call-1",
                name: "xcodebuild",
                detail: "42 tests passed"
            ),
            .toolCompleted(
                callID: "call-1",
                name: "xcodebuild",
                detail: "128 tests passed",
                failed: false,
                durationSeconds: 12.4
            ),
            .textDelta("Ready to ship."),
            .messageComplete(authoritativeText: "Ready to ship."),
        ]

        for event in events {
            message = AssistantTurnReducer.reducing(message, event: event)
        }

        XCTAssertFalse(message.streaming)
        XCTAssertEqual(message.text, "Ready to ship.")
        XCTAssertEqual(message.assistantParts.count, 3)
        guard case .reasoning(let reasoning) = message.assistantParts[0].content,
              case .tool(let tool) = message.assistantParts[1].content,
              case .text(let text) = message.assistantParts[2].content else {
            return XCTFail("Expected reasoning, tool, and text in event order")
        }
        XCTAssertEqual(reasoning.text, "Checking the branch.")
        XCTAssertEqual(tool.state, .complete)
        XCTAssertEqual(tool.detail, "128 tests passed")
        XCTAssertEqual(tool.durationSeconds, 12.4)
        XCTAssertEqual(text, "Ready to ship.")
    }

    func testMirroredSubagentHeaderKeepsAnswerAfterInterveningReasoning() throws {
        var message = TranscriptMessage(role: .assistant, text: "", streaming: true)
        let events = [
            GatewayEvent(
                type: "message.delta",
                sessionId: "child-runtime",
                payload: ["text": "Audit the release.\n"]
            ),
            GatewayEvent(
                type: "reasoning.delta",
                sessionId: "child-runtime",
                payload: ["text": "Checking the hosted gates."]
            ),
            GatewayEvent(
                type: "message.delta",
                sessionId: "child-runtime",
                payload: ["text": "The hosted gates "]
            ),
            GatewayEvent(
                type: "message.delta",
                sessionId: "child-runtime",
                payload: ["text": "passed."]
            ),
        ]

        for event in events {
            message = AssistantTurnReducer.reducing(
                message,
                event: try XCTUnwrap(AssistantTurnReducer.event(from: event))
            )
        }

        XCTAssertEqual(
            message.text,
            "Audit the release.\nThe hosted gates passed."
        )
        XCTAssertEqual(message.assistantParts.count, 3)
        guard case .text(let header) = message.assistantParts[0].content,
              case .reasoning(let reasoning) = message.assistantParts[1].content,
              case .text(let answer) = message.assistantParts[2].content else {
            return XCTFail("Expected the child header, reasoning, and joined answer in order")
        }
        XCTAssertEqual(header, "Audit the release.\n")
        XCTAssertEqual(reasoning.text, "Checking the hosted gates.")
        XCTAssertEqual(answer, "The hosted gates passed.")
    }

    func testMidSentenceTextStillCoalescesAcrossReasoningWithinOneSegment() {
        var message = TranscriptMessage(role: .assistant, text: "", streaming: true)
        message = AssistantTurnReducer.reducing(message, event: .textDelta("Let me "))
        message = AssistantTurnReducer.reducing(
            message,
            event: .reasoningDelta("Checking the file.")
        )
        message = AssistantTurnReducer.reducing(
            message,
            event: .textDelta("verify the result.")
        )

        XCTAssertEqual(message.assistantParts.count, 2)
        guard case .text(let text) = message.assistantParts[0].content,
              case .reasoning(let reasoning) = message.assistantParts[1].content else {
            return XCTFail("Expected one text segment and its reasoning disclosure")
        }
        XCTAssertEqual(text, "Let me verify the result.")
        XCTAssertEqual(reasoning.text, "Checking the file.")
    }

    func testFailedToolIgnoresRawArgumentsAndResultBodies() {
        let event = GatewayEvent(
            type: "tool.complete",
            sessionId: "session-1",
            payload: [
                "tool_id": "call-1",
                "name": "terminal",
                "summary": "Command failed",
                "error": "password=hunter2",
                "args": ["token": "raw-secret"],
                "result": ["authorization": "Bearer raw-secret"],
                "result_text": "sk-1234567890",
            ]
        )

        guard let parsed = AssistantTurnReducer.event(from: event) else {
            return XCTFail("Expected a tool event")
        }
        var message = TranscriptMessage(role: .assistant, text: "", streaming: true)
        message = AssistantTurnReducer.reducing(message, event: parsed)

        guard case .tool(let tool) = message.assistantParts.first?.content else {
            return XCTFail("Expected a tool card")
        }
        XCTAssertEqual(tool.state, .failed)
        XCTAssertEqual(tool.detail, "Command failed")
        let description = String(describing: tool)
        XCTAssertFalse(description.contains("hunter2"))
        XCTAssertFalse(description.contains("raw-secret"))
        XCTAssertFalse(description.contains("sk-1234567890"))
    }

    func testActivityTextRedactsCredentialShapesAndHonorsExactBound() {
        let source = "Authorization: Bearer abcdef token=supersecret --password hunter2 sk-1234567890"
        let safe = ChatPresentationSafety.sanitized(source, maximumCharacters: 64)

        XCTAssertLessThanOrEqual(safe.count, 64)
        XCTAssertFalse(safe.contains("abcdef"))
        XCTAssertFalse(safe.contains("supersecret"))
        XCTAssertFalse(safe.contains("hunter2"))
        XCTAssertFalse(safe.contains("sk-1234567890"))
        XCTAssertTrue(safe.contains("[REDACTED]"))
    }

    func testUserVisibleFailureNeverIncludesRawGatewayErrorBody() {
        let error = GatewayClientError.rpc(
            message: "token=supersecret private server traceback",
            code: -32_000,
            data: ["authorization": "Bearer raw-secret"]
        )
        let safe = ChatPresentationSafety.userVisibleFailure(
            for: error,
            fallback: "The command couldn't be completed. Check the gateway connection, then try again."
        )

        XCTAssertEqual(
            safe,
            "The command couldn't be completed. Check the gateway connection, then try again."
        )
        XCTAssertFalse(safe.contains("supersecret"))
        XCTAssertFalse(safe.contains("traceback"))
        XCTAssertFalse(safe.contains("raw-secret"))
    }

    func testReasoningAndActivityCountsStayBoundedWithUniqueStableIDs() {
        var message = TranscriptMessage(role: .assistant, text: "", streaming: true)
        for index in 0..<(AssistantTurnReducer.maximumActivityParts + 20) {
            message = AssistantTurnReducer.reducing(
                message,
                event: .toolStarted(
                    callID: "call-\(index)",
                    name: "tool-\(index)",
                    detail: String(repeating: "x", count: 2_000)
                )
            )
        }

        let activity = message.assistantParts.filter {
            if case .text = $0.content { return false }
            return true
        }
        XCTAssertEqual(activity.count, AssistantTurnReducer.maximumActivityParts)
        XCTAssertEqual(Set(activity.map(\.id)).count, activity.count)
        for part in activity {
            guard case .tool(let tool) = part.content else { continue }
            XCTAssertLessThanOrEqual(
                tool.detail?.count ?? 0,
                ChatPresentationSafety.maximumActivityDetailCharacters
            )
        }

        message = AssistantTurnReducer.reducing(
            message,
            event: .reasoningAvailable(String(repeating: "r", count: 10_000))
        )
        guard case .reasoning(let reasoning) = message.assistantParts.last?.content else {
            return XCTFail("Expected bounded reasoning")
        }
        XCTAssertTrue(reasoning.wasTruncated)
        XCTAssertLessThanOrEqual(
            reasoning.text.count,
            ChatPresentationSafety.maximumReasoningCharacters
        )
    }

    func testReasoningAvailableReplacesTheCurrentDisclosureWithoutMovingIt() {
        var message = TranscriptMessage(role: .assistant, text: "", streaming: true)
        message = AssistantTurnReducer.reducing(message, event: .reasoningDelta("Draft"))
        let stableID = message.assistantParts[0].id
        message = AssistantTurnReducer.reducing(
            message,
            event: .reasoningAvailable("Final reasoning summary")
        )

        XCTAssertEqual(message.assistantParts[0].id, stableID)
        guard case .reasoning(let reasoning) = message.assistantParts[0].content else {
            return XCTFail("Expected reasoning")
        }
        XCTAssertEqual(reasoning.text, "Final reasoning summary")
    }

    func testRestoredAssistantTextRetainsReasoningBeforeTheAnswer() throws {
        let message = try XCTUnwrap(TranscriptMessage(restoring: SessionTranscriptMessage(
            role: .assistant,
            text: "Ready to ship.",
            reasoning: "Checked the release gates."
        )))

        XCTAssertEqual(message.role, .assistant)
        XCTAssertEqual(message.text, "Ready to ship.")
        XCTAssertEqual(message.assistantParts.count, 2)
        guard case .reasoning(let reasoning) = message.assistantParts[0].content,
              case .text(let text) = message.assistantParts[1].content else {
            return XCTFail("Expected restored reasoning followed by assistant text")
        }
        XCTAssertEqual(reasoning.text, "Checked the release gates.")
        XCTAssertFalse(reasoning.wasTruncated)
        XCTAssertEqual(text, "Ready to ship.")
    }

    func testRestoredReasoningIsRedactedAndBounded() throws {
        let source = "token=restore-secret "
            + String(repeating: "r", count: ChatPresentationSafety.maximumReasoningCharacters + 500)
        let message = try XCTUnwrap(TranscriptMessage(restoring: SessionTranscriptMessage(
            role: .assistant,
            text: "A bounded answer.",
            reasoning: source
        )))

        guard case .reasoning(let reasoning) = message.assistantParts.first?.content else {
            return XCTFail("Expected restored reasoning disclosure")
        }
        XCTAssertFalse(reasoning.text.contains("restore-secret"))
        XCTAssertTrue(reasoning.text.contains("[REDACTED]"))
        XCTAssertLessThanOrEqual(
            reasoning.text.count,
            ChatPresentationSafety.maximumReasoningCharacters
        )
        XCTAssertTrue(reasoning.wasTruncated)
    }

    func testCanonicalApprovalChoicesMatchGatewayContract() {
        XCTAssertEqual(
            ApprovalChoice.allCases.map(\.rawValue),
            ["once", "session", "always", "deny"]
        )
        XCTAssertEqual(ApprovalChoice.session.label, "For this session")
        XCTAssertEqual(ApprovalChoice.once.accessibilityLabel, "Allow once")
        XCTAssertEqual(ApprovalChoice.always.accessibilityHint, "Saves a permanent matching approval rule")
    }

    func testChatActionCompositionIncludesOnlyAdvertisedCapabilities() {
        let supported: Set<String> = [
            "commands.catalog",
            "slash.exec",
            "process.list",
        ]
        let actions = ChatAdvertisedActions(
            supportsMethod: supported.contains,
            supportsDurableWork: false,
            liveViewSupported: false
        )

        XCTAssertTrue(actions.commands)
        XCTAssertFalse(actions.background)
        XCTAssertTrue(actions.processes)
        XCTAssertFalse(actions.liveView)
        XCTAssertFalse(actions.isEmpty)

        let incompleteCommands = ChatAdvertisedActions(
            supportsMethod: { $0 == "commands.catalog" },
            supportsDurableWork: false,
            liveViewSupported: false
        )
        XCTAssertFalse(incompleteCommands.commands)
        XCTAssertTrue(incompleteCommands.isEmpty)
    }

    func testAdvertisedDurableWorkKeepsBackgroundActionDiscoverable() {
        let actions = ChatAdvertisedActions(
            supportsMethod: { _ in false },
            supportsDurableWork: true,
            liveViewSupported: false
        )

        XCTAssertTrue(actions.background)
        XCTAssertFalse(actions.isEmpty)
    }

    func testBlockingInteractionAccessibilityCueCoalescesDuplicateEvents() {
        var coordinator = PendingInteractionAccessibilityCoordinator()
        let approval = PendingInteraction.approval(PendingApproval(
            command: "deploy --token secret",
            requestId: "approval-1",
            summary: "Deploy with password=hunter2",
            allowPermanent: false
        ))

        let first = coordinator.cue(for: approval)
        XCTAssertEqual(first?.identity, "approval:approval-1")
        XCTAssertEqual(
            first?.announcement,
            "Approval needed. Review the request and choose a response."
        )
        XCTAssertFalse(first?.announcement.contains("secret") ?? true)
        XCTAssertNil(coordinator.cue(for: approval), "Duplicate events must not interrupt VoiceOver")

        let question = PendingInteraction.prompt(PendingPrompt(
            kind: .clarify,
            requestId: "question-1",
            question: "Choose a protected environment",
            choices: ["Staging", "Production"]
        ))
        XCTAssertEqual(coordinator.cue(for: question)?.identity, "clarify:question-1")
        XCTAssertNil(coordinator.cue(for: question))

        XCTAssertNil(coordinator.cue(for: nil))
        XCTAssertNotNil(
            coordinator.cue(for: approval),
            "A later appearance after the blocking queue clears is a new announcement"
        )
    }

    func testPromptPresentationRedactsAndBoundsChromeWithoutChangingChoiceResponses() {
        let rawChoice = "Deploy with token=choice-secret"
        let prompt = PendingPrompt(
            kind: .clarify,
            requestId: "question-1",
            question: "Authorization: Bearer question-secret "
                + String(repeating: "q", count: 2_000),
            choices: [rawChoice, rawChoice, "Staging"]
        )

        XCTAssertLessThanOrEqual(
            prompt.presentationQuestion.count,
            ChatPresentationSafety.maximumActivityDetailCharacters
        )
        XCTAssertFalse(prompt.presentationQuestion.contains("question-secret"))
        XCTAssertEqual(prompt.presentationChoices.map(\.id), [0, 1, 2])
        XCTAssertFalse(prompt.presentationChoices[0].label.contains("choice-secret"))
        XCTAssertEqual(prompt.presentationChoices[0].response, rawChoice)
        XCTAssertEqual(prompt.presentationChoices[1].response, rawChoice)
        XCTAssertEqual(prompt.choices, [rawChoice, rawChoice, "Staging"])
    }

    @MainActor
    func testApprovalParserRedactsSummaryCommandAndHonorsPermanentGate() {
        let approval = ChatViewModel.approval(from: GatewayEvent(
            type: "approval.request",
            sessionId: "session-1",
            payload: [
                "request_id": "approval-1",
                "description": "Run with token=secret-value",
                "command": "deploy --password hunter2",
                "cwd": "/workspace/fabric",
                "allow_permanent": false,
            ]
        ))

        XCTAssertEqual(approval?.requestId, "approval-1")
        XCTAssertEqual(approval?.summary, "Run with token=[REDACTED]")
        XCTAssertEqual(approval?.command, "deploy --password [REDACTED]")
        XCTAssertEqual(approval?.cwd, "/workspace/fabric")
        XCTAssertFalse(approval?.allowPermanent ?? true)
    }

    func testMutationFailureClassificationSeparatesRejectionFromAmbiguityWithoutRawCopy() {
        let rejection = ChatMutationFailurePresentation.classify(
            GatewayClientError.rpc(
                message: "Authorization: Bearer raw-secret /Users/private/file",
                code: -32_000,
                data: ["token": "server-secret"]
            ),
            action: .slashCommand
        )
        XCTAssertEqual(rejection.disposition, .rejected)
        XCTAssertNil(rejection.outcomeDescription)
        XCTAssertEqual(rejection.message, "Fabric rejected this command. Review it and try again.")

        let ambiguous = ChatMutationFailurePresentation.classify(
            GatewayClientError.socketClosed,
            action: .legacyBackground
        )
        XCTAssertEqual(ambiguous.disposition, .outcomeUnknown)
        XCTAssertNotNil(ambiguous.outcomeDescription)
        XCTAssertTrue(ambiguous.message.contains("outcome is unknown"))
        XCTAssertTrue(ambiguous.message.contains("No automatic retry"))

        for copy in [rejection.message, ambiguous.message] {
            XCTAssertFalse(copy.contains("raw-secret"))
            XCTAssertFalse(copy.contains("/Users/private"))
            XCTAssertFalse(copy.contains("server-secret"))
        }
    }

    @MainActor
    func testAmbiguousPromptSubmitLocksRepeatAndNeverReplaysTheRequest() async {
        let counter = ChatMutationCounter()
        let operations = makeOperations(counter: counter, failure: .socketClosed)
        let model = makeModel(
            methods: ["session.create", "session.resume", "prompt.submit"],
            operations: operations
        )
        await model.start()

        await model.send("Ship the verified build")
        await model.send("Ship the verified build")

        XCTAssertEqual(counter.prompt, 1)
        XCTAssertEqual(model.unknownSendOutcome?.action, .prompt)
        XCTAssertTrue(model.unknownSendOutcome?.description.contains("not be retried") == true)
        XCTAssertEqual(
            model.messages.filter { $0.role == .user }.map(\.text),
            ["Ship the verified build"]
        )
        XCTAssertTrue(model.messages.last?.text.contains("outcome is unknown") == true)

        await model.checkConversationAfterUnknownSend()
        XCTAssertEqual(counter.resume, 1)
        XCTAssertEqual(counter.prompt, 1, "Authoritative resume must never replay prompt.submit")
        XCTAssertNil(model.unknownSendOutcome)
        model.stop()
    }

    @MainActor
    func testAmbiguousRemoteMutationsLockRepeatWhileExplicitRejectionsRemainRetryable() async {
        for action in [
            ChatMutationAction.steering,
            .slashCommand,
            .legacyBackground,
        ] {
            let ambiguousCounter = ChatMutationCounter()
            let ambiguousModel = makeModel(
                methods: [
                    "session.create", "session.steer", "slash.exec", "prompt.background",
                ],
                operations: makeOperations(
                    counter: ambiguousCounter,
                    failure: .requestTimedOut(method: action.rawValue)
                )
            )
            await ambiguousModel.start()
            await invoke(action, on: ambiguousModel)
            await invoke(action, on: ambiguousModel)

            XCTAssertEqual(ambiguousCounter.count(for: action), 1, "\(action) repeated after ambiguity")
            XCTAssertEqual(ambiguousModel.unknownSendOutcome?.action, action)
            XCTAssertTrue(ambiguousModel.messages.last?.text.contains("No automatic retry") == true)
            ambiguousModel.stop()

            let rejectedCounter = ChatMutationCounter()
            let rejectedModel = makeModel(
                methods: [
                    "session.create", "session.steer", "slash.exec", "prompt.background",
                ],
                operations: makeOperations(
                    counter: rejectedCounter,
                    failure: .rpc(message: "token=raw-secret /private/path")
                )
            )
            await rejectedModel.start()
            await invoke(action, on: rejectedModel)
            await invoke(action, on: rejectedModel)

            XCTAssertEqual(rejectedCounter.count(for: action), 2, "\(action) rejection should allow correction")
            XCTAssertNil(rejectedModel.unknownSendOutcome)
            XCTAssertFalse(rejectedModel.messages.map(\.text).joined().contains("raw-secret"))
            XCTAssertFalse(rejectedModel.messages.map(\.text).joined().contains("/private/path"))
            rejectedModel.stop()
        }
    }

    @MainActor
    func testCachedTranscriptRemainsVisibleReadOnlyWithRetryStateWhenResumeFails() async {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let cache = ChatPresentationCache(directoryURL: temporary)
        let key = "gateway-1\u{1F}stored-1"
        cache.replace(key: key, messages: [
            TranscriptMessage(role: .user, text: "Preserved goal"),
            TranscriptMessage(role: .assistant, text: "Preserved response"),
        ])
        let counter = ChatMutationCounter()
        let operations = ChatGatewayOperations(
            createSession: { throw GatewayClientError.notConnected },
            resumeSession: { _ in
                counter.resume += 1
                throw GatewayClientError.socketClosed
            },
            submitPrompt: { _, _ in counter.prompt += 1 },
            steer: { _, _ in counter.steering += 1; return true },
            execSlash: { _, _ in counter.slash += 1; return nil },
            submitLegacyBackground: { _, _ in counter.background += 1; return nil }
        )
        let model = ChatViewModel(
            api: GatewayAPI(client: JsonRpcGatewayClient()),
            resumeStoredSessionId: "stored-1",
            supportsMethod: { ["session.resume", "prompt.submit"].contains($0) },
            workGatewayID: { "gateway-1" },
            presentationCache: cache,
            operations: operations
        )

        await model.start()

        XCTAssertEqual(counter.resume, 1)
        XCTAssertEqual(model.messages.map(\.text), ["Preserved goal", "Preserved response"])
        XCTAssertTrue(model.showingCachedTranscript)
        XCTAssertTrue(model.hasReadOnlyCachedTranscriptAfterResumeFailure)
        XCTAssertFalse(model.sessionReady)
        XCTAssertNotNil(model.sessionError)
        let attempted = await model.sendInitialPrompt("Must not send while cached")
        XCTAssertFalse(attempted)
        await model.send("Must not mutate")
        XCTAssertEqual(counter.prompt, 0)
        XCTAssertEqual(model.messages.map(\.text), ["Preserved goal", "Preserved response"])
        model.stop()
    }

    @MainActor
    func testLiveTranscriptRemainsVisibleReadOnlyWhenReconnectResumeFails() async {
        var resumeCount = 0
        let operations = ChatGatewayOperations(
            createSession: { throw GatewayClientError.notConnected },
            resumeSession: { _ in
                resumeCount += 1
                if resumeCount == 1 {
                    return LiveSession(
                        sessionId: "runtime-1",
                        storedSessionId: "stored-1",
                        messages: [
                            SessionTranscriptMessage(role: .user, text: "Preserved live goal"),
                            SessionTranscriptMessage(role: .assistant, text: "Preserved live response"),
                        ]
                    )
                }
                throw GatewayClientError.socketClosed
            },
            submitPrompt: { _, _ in },
            steer: { _, _ in true },
            execSlash: { _, _ in nil },
            submitLegacyBackground: { _, _ in nil }
        )
        let model = ChatViewModel(
            api: GatewayAPI(client: JsonRpcGatewayClient()),
            resumeStoredSessionId: "stored-1",
            supportsMethod: { ["session.resume", "prompt.submit"].contains($0) },
            workGatewayID: { "gateway-1" },
            operations: operations
        )

        await model.start()
        XCTAssertTrue(model.sessionReady)
        XCTAssertFalse(model.showingCachedTranscript)

        model.connectionDidClose()
        await model.resumeAfterReconnect()

        XCTAssertEqual(resumeCount, 2)
        XCTAssertEqual(
            model.messages.map(\.text),
            ["Preserved live goal", "Preserved live response"]
        )
        XCTAssertTrue(model.showingCachedTranscript)
        XCTAssertTrue(model.hasReadOnlyCachedTranscriptAfterResumeFailure)
        XCTAssertFalse(model.sessionReady)
        XCTAssertNotNil(model.sessionError)
        model.stop()
    }

    @MainActor
    func testRawGatewayErrorPayloadNeverEntersTranscriptOrPresentationCache() async throws {
        let event = GatewayEvent(
            type: "error",
            sessionId: "runtime-1",
            payload: [
                "message": "Authorization: Bearer raw-secret",
                "path": "/Users/private/.fabric/config.yaml",
                "token": "gateway-token",
            ]
        )
        let safe = ChatViewModel.safeGatewayErrorMessage(from: event)
        XCTAssertLessThanOrEqual(safe.count, ChatPresentationSafety.maximumActivityDetailCharacters)
        XCTAssertFalse(safe.contains("raw-secret"))
        XCTAssertFalse(safe.contains("/Users/private"))
        XCTAssertFalse(safe.contains("gateway-token"))

        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let cache = ChatPresentationCache(directoryURL: temporary)
        let client = JsonRpcGatewayClient()
        let model = ChatViewModel(
            api: GatewayAPI(client: client),
            resumeStoredSessionId: nil,
            supportsMethod: { $0 == "session.create" },
            workGatewayID: { "gateway" },
            presentationCache: cache,
            operations: ChatGatewayOperations(
                createSession: {
                    LiveSession(sessionId: "runtime-1", storedSessionId: "session")
                },
                resumeSession: { _ in
                    LiveSession(sessionId: "runtime-1", storedSessionId: "session")
                },
                submitPrompt: { _, _ in },
                steer: { _, _ in true },
                execSlash: { _, _ in nil },
                submitLegacyBackground: { _, _ in nil }
            )
        )
        await model.start()
        client.onEvent?(event)

        XCTAssertEqual(model.messages.map(\.text), [safe])
        let diskText = String(
            decoding: try Data(contentsOf: cache.snapshotURL(for: "gateway\u{1F}session")),
            as: UTF8.self
        )
        XCTAssertFalse(diskText.contains("raw-secret"))
        XCTAssertFalse(diskText.contains("/Users/private"))
        XCTAssertFalse(diskText.contains("gateway-token"))
        model.stop()
    }

    @MainActor
    func testServerOperationalChromeIsRedactedBoundedAndCachedSafely() async throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let cache = ChatPresentationCache(directoryURL: temporary)
        let client = JsonRpcGatewayClient()
        let model = ChatViewModel(
            api: GatewayAPI(client: client),
            resumeStoredSessionId: nil,
            supportsMethod: { $0 == "session.create" },
            workGatewayID: { "gateway" },
            presentationCache: cache,
            operations: ChatGatewayOperations(
                createSession: {
                    LiveSession(sessionId: "runtime-1", storedSessionId: "session")
                },
                resumeSession: { _ in
                    LiveSession(sessionId: "runtime-1", storedSessionId: "session")
                },
                submitPrompt: { _, _ in },
                steer: { _, _ in true },
                execSlash: { _, _ in nil },
                submitLegacyBackground: { _, _ in nil }
            )
        )
        await model.start()

        client.onEvent?(GatewayEvent(
            type: "status.update",
            sessionId: "runtime-1",
            payload: [
                "text": "Authorization: Bearer status-secret "
                    + String(repeating: "s", count: 2_000),
            ]
        ))
        let safeStatus = try XCTUnwrap(model.statusLine)
        XCTAssertLessThanOrEqual(
            safeStatus.count,
            ChatPresentationSafety.maximumActivityDetailCharacters
        )
        XCTAssertFalse(safeStatus.contains("status-secret"))

        client.onEvent?(GatewayEvent(
            type: "background.complete",
            sessionId: "runtime-1",
            payload: [
                "task_id": "token=task-secret",
                "text": "Authorization: Bearer result-secret "
                    + String(repeating: "r", count: 2_000),
            ]
        ))
        let background = try XCTUnwrap(model.messages.last(where: { $0.role == .info }))
        XCTAssertLessThanOrEqual(
            background.text.count,
            ChatPresentationSafety.maximumActivityDetailCharacters
        )
        XCTAssertFalse(background.text.contains("task-secret"))
        XCTAssertFalse(background.text.contains("result-secret"))

        client.onEvent?(GatewayEvent(
            type: "message.complete",
            sessionId: "runtime-1",
            payload: [
                "text": "Done",
                "history_persisted": false,
                "warning": "Authorization: Bearer persistence-secret "
                    + String(repeating: "p", count: 2_000),
            ]
        ))
        let warning = try XCTUnwrap(model.persistenceWarning)
        XCTAssertLessThanOrEqual(
            warning.count,
            ChatPresentationSafety.maximumActivityDetailCharacters
        )
        XCTAssertFalse(warning.contains("persistence-secret"))

        let diskText = String(
            decoding: try Data(contentsOf: cache.snapshotURL(for: "gateway\u{1F}session")),
            as: UTF8.self
        )
        for secret in ["status-secret", "task-secret", "result-secret", "persistence-secret"] {
            XCTAssertFalse(diskText.contains(secret))
        }
        model.stop()
    }

    func testPresentationCacheIsBoundedRedactedAndNeverRestoresStreamingState() throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let cache = ChatPresentationCache(directoryURL: temporary)
        let assistant = TranscriptMessage(
            role: .assistant,
            text: "Result token=assistant-secret",
            streaming: true,
            assistantParts: [
                AssistantTurnPart(
                    id: "tool:1",
                    content: .tool(.init(
                        callID: "call-1",
                        name: "terminal",
                        detail: "Authorization: Bearer tool-secret",
                        state: .complete,
                        durationSeconds: 1
                    ))
                ),
            ]
        )
        let messages = Array(repeating: TranscriptMessage(
            role: .user,
            text: "password=hunter2 " + String(repeating: "x", count: 20_000)
        ), count: ChatPresentationCache.maximumMessages + 10) + [assistant]

        let presentation = ChatPresentationCache.presentationStrings(from: messages).joined()
        XCTAssertLessThanOrEqual(presentation.count, ChatPresentationCache.maximumTotalCharacters)
        XCTAssertFalse(presentation.contains("hunter2"))
        XCTAssertFalse(presentation.contains("assistant-secret"))
        XCTAssertFalse(presentation.contains("tool-secret"))

        cache.replace(key: "gateway\u{1F}session", messages: messages)
        let restored = cache.load(key: "gateway\u{1F}session")
        XCTAssertLessThanOrEqual(restored.count, ChatPresentationCache.maximumMessages)
        XCTAssertFalse(restored.contains(where: \.streaming))
        XCTAssertFalse(restored.map(\.text).joined().contains("hunter2"))

        cache.replace(key: "gateway\u{1F}session", messages: [])
        XCTAssertTrue(cache.load(key: "gateway\u{1F}session").isEmpty)
    }

    func testPresentationCacheRequiresCompleteProtectionAndBackupExclusion() throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let cache = ChatPresentationCache(directoryURL: temporary)
        let key = "gateway\u{1F}protected"
        cache.replace(
            key: key,
            messages: [TranscriptMessage(role: .assistant, text: "Protected preview")]
        )

        let file = cache.snapshotURL(for: key)
        XCTAssertTrue(FileManager.default.fileExists(atPath: file.path))
        XCTAssertEqual(ChatPresentationCache.requiredFileProtection, .complete)
        XCTAssertTrue(ChatPresentationCache.hasRequiredFileProtection(FileProtectionType.complete))
        XCTAssertFalse(
            ChatPresentationCache.hasRequiredFileProtection(
                FileProtectionType.completeUntilFirstUserAuthentication
            )
        )
        XCTAssertFalse(ChatPresentationCache.hasRequiredFileProtection(nil))
        for url in [temporary, file] {
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            let raw = attributes[.protectionKey]
            if raw != nil {
                XCTAssertTrue(ChatPresentationCache.hasRequiredFileProtection(raw))
            }
            let values = try url.resourceValues(forKeys: [.isExcludedFromBackupKey])
            XCTAssertEqual(values.isExcludedFromBackup, true)
        }
    }

    func testPresentationCacheUsesDistinctOpaquePathsForDistinctConversationKeys() throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let cache = ChatPresentationCache(directoryURL: temporary)
        let first = cache.snapshotURL(for: "gateway-a\u{1F}session")
        let second = cache.snapshotURL(for: "gateway-b\u{1F}session")

        XCTAssertNotEqual(first, second)
        XCTAssertEqual(first.deletingPathExtension().lastPathComponent.count, 64)
        XCTAssertEqual(second.deletingPathExtension().lastPathComponent.count, 64)
        XCTAssertFalse(first.lastPathComponent.contains("gateway"))
        XCTAssertFalse(first.lastPathComponent.contains("session"))
    }

    func testPresentationCacheEncodedBytesStayBoundedAndRetainNewestRows() throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let byteLimit = 2_048
        let cache = ChatPresentationCache(
            directoryURL: temporary,
            policy: .init(
                maximumEncodedBytes: byteLimit,
                maximumDirectoryBytes: 8_192,
                maximumSessions: 8,
                maximumAge: 3_600
            )
        )
        let key = "gateway\u{1F}bounded"
        let messages = (0..<50).map { index in
            TranscriptMessage(
                role: .assistant,
                text: "row-\(index)-" + String(repeating: "🧵", count: 40)
            )
        }

        cache.replace(key: key, messages: messages)

        let file = cache.snapshotURL(for: key)
        let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? .max
        XCTAssertLessThanOrEqual(size, byteLimit)
        let restored = cache.load(key: key)
        XCTAssertFalse(restored.isEmpty)
        XCTAssertEqual(restored.last?.text, messages.last?.text)
    }

    func testPresentationCachePrunesByAgeAndSessionCountUsingAccessLRU() throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let policy = ChatPresentationCache.Policy(
            maximumEncodedBytes: 16_384,
            maximumDirectoryBytes: 64_000,
            maximumSessions: 2,
            maximumAge: 60
        )
        let cache = ChatPresentationCache(directoryURL: temporary, policy: policy)
        let now = Date()
        cache.replace(key: "a", messages: [TranscriptMessage(role: .user, text: "A")])
        cache.replace(key: "b", messages: [TranscriptMessage(role: .user, text: "B")])
        try FileManager.default.setAttributes(
            [.modificationDate: now.addingTimeInterval(-20)],
            ofItemAtPath: cache.snapshotURL(for: "a").path
        )
        try FileManager.default.setAttributes(
            [.modificationDate: now.addingTimeInterval(-10)],
            ofItemAtPath: cache.snapshotURL(for: "b").path
        )

        XCTAssertEqual(cache.load(key: "a").first?.text, "A", "Load should refresh the LRU clock")
        cache.replace(key: "c", messages: [TranscriptMessage(role: .user, text: "C")])
        XCTAssertTrue(FileManager.default.fileExists(atPath: cache.snapshotURL(for: "a").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: cache.snapshotURL(for: "b").path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: cache.snapshotURL(for: "c").path))

        try FileManager.default.setAttributes(
            [.modificationDate: now.addingTimeInterval(-120)],
            ofItemAtPath: cache.snapshotURL(for: "a").path
        )
        cache.replace(key: "d", messages: [TranscriptMessage(role: .user, text: "D")])
        XCTAssertFalse(FileManager.default.fileExists(atPath: cache.snapshotURL(for: "a").path))
    }

    func testPresentationCachePrunesGlobalEncodedByteBudget() throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let generous = ChatPresentationCache(
            directoryURL: temporary,
            policy: .init(
                maximumEncodedBytes: 16_384,
                maximumDirectoryBytes: 64_000,
                maximumSessions: 10,
                maximumAge: 3_600
            )
        )
        let payload = String(repeating: "x", count: 1_000)
        generous.replace(key: "older", messages: [TranscriptMessage(role: .user, text: payload)])
        generous.replace(key: "newer", messages: [TranscriptMessage(role: .user, text: payload)])
        let older = generous.snapshotURL(for: "older")
        let newer = generous.snapshotURL(for: "newer")
        let newerSize = try newer.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        try FileManager.default.setAttributes(
            [.modificationDate: Date().addingTimeInterval(-20)],
            ofItemAtPath: older.path
        )
        try FileManager.default.setAttributes(
            [.modificationDate: Date().addingTimeInterval(-10)],
            ofItemAtPath: newer.path
        )

        let tight = ChatPresentationCache(
            directoryURL: temporary,
            policy: .init(
                maximumEncodedBytes: 16_384,
                maximumDirectoryBytes: newerSize,
                maximumSessions: 10,
                maximumAge: 3_600
            )
        )
        XCTAssertEqual(tight.load(key: "newer").first?.text, payload)
        XCTAssertFalse(FileManager.default.fileExists(atPath: older.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: newer.path))
    }

    func testAuthoritativeCompletionReplacesConflictingTextWithoutDroppingToolCard() {
        var message = TranscriptMessage(role: .assistant, text: "", streaming: true)
        message = AssistantTurnReducer.reducing(message, event: .textDelta("Partial"))
        message = AssistantTurnReducer.reducing(
            message,
            event: .toolCompleted(
                callID: "call-1",
                name: "read_file",
                detail: "Read one file",
                failed: false,
                durationSeconds: nil
            )
        )
        message = AssistantTurnReducer.reducing(
            message,
            event: .messageComplete(authoritativeText: "Authoritative final")
        )

        XCTAssertEqual(message.text, "Authoritative final")
        XCTAssertTrue(message.assistantParts.contains {
            if case .tool = $0.content { return true }
            return false
        })
        XCTAssertEqual(message.assistantParts.compactMap { part -> String? in
            if case .text(let text) = part.content { return text }
            return nil
        }, ["Authoritative final"])
    }

    // MARK: - Streaming scroll follow mode (Issue #90)

    func testFollowStateStartsEngagedAndChasesLatestAtBottom() {
        var follow = TranscriptFollowState()
        XCTAssertTrue(follow.isFollowing)
        XCTAssertFalse(follow.showsJumpToLatest)
        XCTAssertEqual(follow.transcriptDidGrow(newUserTurn: false), .scrollToLatest)
        XCTAssertTrue(follow.isFollowing)
        XCTAssertFalse(follow.showsJumpToLatest)
    }

    func testManualScrollUpDisengagesFollowAndHoldsPositionForDeltas() {
        var follow = TranscriptFollowState()
        follow.readerDidDrag(distanceFromBottom: TranscriptFollowState.bottomTolerance + 200)
        XCTAssertFalse(follow.isFollowing)

        // Streaming deltas below the viewport must not move the reader.
        XCTAssertEqual(follow.transcriptDidGrow(newUserTurn: false), .hold)
        XCTAssertEqual(follow.transcriptDidGrow(newUserTurn: false), .hold)
        XCTAssertTrue(follow.showsJumpToLatest)
    }

    func testDragThatStaysWithinToleranceKeepsFollowing() {
        var follow = TranscriptFollowState()
        follow.readerDidDrag(distanceFromBottom: TranscriptFollowState.bottomTolerance)
        XCTAssertTrue(follow.isFollowing, "A drag within tolerance is not a disengagement")
        follow.readerDidDrag(distanceFromBottom: TranscriptFollowState.bottomTolerance + 0.5)
        XCTAssertFalse(follow.isFollowing, "Crossing the tolerance disengages follow")
    }

    func testRichLayoutFollowUpOnlyScrollsWhileFollowing() {
        var follow = TranscriptFollowState()
        XCTAssertTrue(follow.richLayoutReadyShouldScroll())
        follow.readerDidDrag(distanceFromBottom: 400)
        XCTAssertFalse(
            follow.richLayoutReadyShouldScroll(),
            "A completed row's rich relayout must not yank a scrolled-up reader"
        )
    }

    func testReturningToBottomReengagesFollowAndClearsPendingAffordance() {
        var follow = TranscriptFollowState()
        follow.readerDidDrag(distanceFromBottom: 400)
        _ = follow.transcriptDidGrow(newUserTurn: false)
        XCTAssertTrue(follow.showsJumpToLatest)

        follow.viewportDidSettle(distanceFromBottom: 0)
        XCTAssertTrue(follow.isFollowing)
        XCTAssertFalse(follow.showsJumpToLatest)
        XCTAssertEqual(follow.transcriptDidGrow(newUserTurn: false), .scrollToLatest)
    }

    func testContentGrowthDriftNeverReengagesAScrolledUpReader() {
        var follow = TranscriptFollowState()
        follow.readerDidDrag(distanceFromBottom: 400)
        _ = follow.transcriptDidGrow(newUserTurn: false)
        // Geometry settling far from the bottom (content grew below the reader)
        // must never re-arm follow — only reaching the bottom does.
        follow.viewportDidSettle(distanceFromBottom: 800)
        XCTAssertFalse(follow.isFollowing)
        XCTAssertTrue(follow.showsJumpToLatest)
    }

    func testJumpToLatestReengagesFollowAndClearsAffordance() {
        var follow = TranscriptFollowState()
        follow.readerDidDrag(distanceFromBottom: 400)
        _ = follow.transcriptDidGrow(newUserTurn: false)
        follow.jumpToLatest()
        XCTAssertTrue(follow.isFollowing)
        XCTAssertFalse(follow.showsJumpToLatest)
    }

    func testSendingANewUserTurnAlwaysReturnsToLatest() {
        var follow = TranscriptFollowState()
        follow.readerDidDrag(distanceFromBottom: 400)
        _ = follow.transcriptDidGrow(newUserTurn: false)
        XCTAssertFalse(follow.isFollowing)
        // Sending a message re-engages follow and snaps to the new turn.
        XCTAssertEqual(follow.transcriptDidGrow(newUserTurn: true), .scrollToLatest)
        XCTAssertTrue(follow.isFollowing)
        XCTAssertFalse(follow.showsJumpToLatest)
    }

    func testJumpToLatestAffordanceHiddenUntilContentArrivesBelow() {
        var follow = TranscriptFollowState()
        follow.readerDidDrag(distanceFromBottom: 400)
        // Away from the bottom, but nothing new has streamed in yet.
        XCTAssertFalse(follow.showsJumpToLatest)
        _ = follow.transcriptDidGrow(newUserTurn: false)
        XCTAssertTrue(follow.showsJumpToLatest)
    }

    @MainActor
    private func makeModel(
        methods: Set<String>,
        operations: ChatGatewayOperations
    ) -> ChatViewModel {
        ChatViewModel(
            api: GatewayAPI(client: JsonRpcGatewayClient()),
            resumeStoredSessionId: nil,
            supportsMethod: methods.contains,
            operations: operations
        )
    }

    private func makeOperations(
        counter: ChatMutationCounter,
        failure: GatewayClientError
    ) -> ChatGatewayOperations {
        ChatGatewayOperations(
            createSession: {
                LiveSession(sessionId: "runtime-1", storedSessionId: "stored-1")
            },
            resumeSession: { _ in
                counter.resume += 1
                return LiveSession(sessionId: "runtime-1", storedSessionId: "stored-1")
            },
            submitPrompt: { _, _ in
                counter.prompt += 1
                throw failure
            },
            steer: { _, _ in
                counter.steering += 1
                throw failure
            },
            execSlash: { _, _ in
                counter.slash += 1
                throw failure
            },
            submitLegacyBackground: { _, _ in
                counter.background += 1
                throw failure
            }
        )
    }

    @MainActor
    private func invoke(_ action: ChatMutationAction, on model: ChatViewModel) async {
        switch action {
        case .prompt:
            await model.send("A message")
        case .steering:
            await model.steer("Adjust course")
        case .slashCommand:
            await model.execSlash("/status")
        case .legacyBackground:
            await model.sendInBackground("Run checks")
        }
    }
}

private final class ChatMutationCounter {
    var prompt = 0
    var steering = 0
    var slash = 0
    var background = 0
    var resume = 0

    func count(for action: ChatMutationAction) -> Int {
        switch action {
        case .prompt: return prompt
        case .steering: return steering
        case .slashCommand: return slash
        case .legacyBackground: return background
        }
    }
}
