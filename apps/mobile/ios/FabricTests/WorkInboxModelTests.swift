import XCTest
@testable import Fabric

@MainActor
final class WorkInboxModelTests: XCTestCase {
    func testCapabilityGateMakesNoWorkRequest() async throws {
        let gateway = ScriptedWorkInboxGateway()
        let model = WorkInboxModel()

        await model.refresh(
            using: gateway,
            context: try context(),
            negotiation: .legacy
        )

        XCTAssertEqual(model.availability, .unavailable)
        XCTAssertTrue(model.sections.isEmpty)
        XCTAssertTrue(gateway.syncCalls.isEmpty)
    }

    func testSyncFailurePublishesOnlyFixedRedactedCopy() async throws {
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [{ _, _, _ in
            throw FixtureFailure("PRIVATE-SERVER-DETAIL-MUST-NOT-PUBLISH")
        }]
        let model = WorkInboxModel()

        await model.refresh(
            using: gateway,
            context: try context(),
            negotiation: durableNegotiation
        )

        XCTAssertEqual(model.syncError, "Work could not be refreshed.")
        XCTAssertFalse(try XCTUnwrap(model.syncError).contains("PRIVATE-SERVER-DETAIL"))
        XCTAssertEqual(model.availability, .empty)
    }

    func testBootstrapPaginationThenReconnectUsesDurableDeltaCursor() async throws {
        let first = makeJob(id: workID("job", 1), status: "queued", version: 1, updatedAt: 5)
        let second = makeJob(id: workID("job", 2), status: "running", version: 1, updatedAt: 6)
        let completed = makeJob(
            id: first.jobID,
            status: "succeeded",
            version: 2,
            updatedAt: 11,
            finishedAt: 11
        )
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [
            immediate(.page(bootstrapPage(
                ledger: workID("ledger", 1),
                cursor: 10,
                hasMore: true,
                nextToken: "page-two",
                jobs: [first]
            ))),
            immediate(.page(bootstrapPage(
                ledger: workID("ledger", 1),
                cursor: 10,
                jobs: [second]
            ))),
            immediate(.page(deltaPage(
                ledger: workID("ledger", 1),
                cursor: 11,
                events: [jobEvent(11, job: completed)]
            ))),
        ]
        let model = WorkInboxModel()
        let firstConnection = try context(connectionGeneration: 1)

        await model.refresh(
            using: gateway,
            context: firstConnection,
            negotiation: durableNegotiation
        )

        XCTAssertEqual(model.availability, .current)
        XCTAssertEqual(model.sections.active.map(\.id), [second.jobID, first.jobID])
        XCTAssertEqual(gateway.syncCalls.map(\.request), [
            .bootstrap(pageToken: nil, limit: FabricWorkLimits.syncPageItems),
            .bootstrap(pageToken: "page-two", limit: FabricWorkLimits.syncPageItems),
        ])

        let reconnectedContext = try context(connectionGeneration: 2)
        await model.refresh(
            using: gateway,
            context: reconnectedContext,
            negotiation: durableNegotiation
        )

        XCTAssertEqual(gateway.syncCalls.last?.request, .delta(
            ledgerID: workID("ledger", 1),
            after: 10,
            limit: FabricWorkLimits.syncPageItems
        ))
        XCTAssertEqual(model.sections.completed.map(\.id), [first.jobID])
        XCTAssertEqual(model.sections.active.map(\.id), [second.jobID])
    }

    func testCursorExpiryDiscardsOldLedgerBeforeFreshBootstrap() async throws {
        let oldJob = makeJob(id: workID("job", 3), status: "running", version: 1, updatedAt: 3)
        let newJob = makeJob(id: workID("job", 4), status: "queued", version: 1, updatedAt: 4)
        let oldLedger = workID("ledger", 3)
        let newLedger = workID("ledger", 4)
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [
            immediate(.page(bootstrapPage(ledger: oldLedger, cursor: 3, jobs: [oldJob]))),
            immediate(.reset(FabricWorkCursorReset(
                message: "Cursor expired",
                data: .init(reason: "retention", ledgerID: newLedger, eventFloor: 0, highWater: 4)
            ))),
            immediate(.page(bootstrapPage(ledger: newLedger, cursor: 4, jobs: [newJob]))),
        ]
        let model = WorkInboxModel()
        let firstContext = try context(connectionGeneration: 1)
        await model.refresh(using: gateway, context: firstContext, negotiation: durableNegotiation)

        await model.refresh(
            using: gateway,
            context: try context(connectionGeneration: 2),
            negotiation: durableNegotiation
        )

        XCTAssertEqual(Array(gateway.syncCalls.suffix(2)).map(\.request), [
            .delta(ledgerID: oldLedger, after: 3, limit: FabricWorkLimits.syncPageItems),
            .bootstrap(pageToken: nil, limit: FabricWorkLimits.syncPageItems),
        ])
        XCTAssertEqual(model.sections.active.map(\.id), [newJob.jobID])
        XCTAssertFalse(model.sections.active.contains { $0.id == oldJob.jobID })
        XCTAssertEqual(model.availability, .current)
    }

    func testCursorResetFollowedByFailureDoesNotRestoreTheOldLedger() async throws {
        let oldJob = makeJob(id: workID("job", 21), status: "running", version: 1, updatedAt: 21)
        let oldLedger = workID("ledger", 21)
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [
            immediate(.page(bootstrapPage(ledger: oldLedger, cursor: 21, jobs: [oldJob]))),
            immediate(.reset(FabricWorkCursorReset(
                message: "Cursor expired",
                data: .init(
                    reason: "retention",
                    ledgerID: workID("ledger", 22),
                    eventFloor: 0,
                    highWater: 22
                )
            ))),
            { _, _, _ in throw FixtureFailure("PRIVATE-BOOTSTRAP-FAILURE") },
        ]
        let model = WorkInboxModel()
        await model.refresh(
            using: gateway,
            context: try context(connectionGeneration: 1),
            negotiation: durableNegotiation
        )

        await model.refresh(
            using: gateway,
            context: try context(connectionGeneration: 2),
            negotiation: durableNegotiation
        )

        XCTAssertTrue(model.sections.isEmpty)
        XCTAssertEqual(model.availability, .empty)
        XCTAssertEqual(model.syncError, "Work could not be refreshed.")
        XCTAssertNil(model.lastUpdated)
        XCTAssertEqual(Array(gateway.syncCalls.suffix(2)).map(\.request), [
            .delta(ledgerID: oldLedger, after: 21, limit: FabricWorkLimits.syncPageItems),
            .bootstrap(pageToken: nil, limit: FabricWorkLimits.syncPageItems),
        ])
    }

    func testRuntimeSessionChangeClearsAProjectionInTheSameGatewayProfile() async throws {
        let oldJob = makeJob(id: workID("job", 23), status: "running", version: 1, updatedAt: 23)
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [
            immediate(.page(bootstrapPage(
                ledger: workID("ledger", 23),
                cursor: 23,
                jobs: [oldJob]
            ))),
            { _, _, _ in throw FixtureFailure("PRIVATE-NEW-SESSION-FAILURE") },
        ]
        let model = WorkInboxModel()
        await model.refresh(
            using: gateway,
            context: try context(session: "runtime-old"),
            negotiation: durableNegotiation
        )
        XCTAssertEqual(model.sections.active.map(\.id), [oldJob.jobID])

        await model.refresh(
            using: gateway,
            context: try context(session: "runtime-new", connectionGeneration: 2),
            negotiation: durableNegotiation
        )

        XCTAssertTrue(model.sections.isEmpty)
        XCTAssertEqual(model.availability, .empty)
        XCTAssertEqual(
            gateway.syncCalls.last?.request,
            .bootstrap(pageToken: nil, limit: FabricWorkLimits.syncPageItems)
        )
    }

    func testDifferentGatewayAndProfileFenceAnOlderCompletion() async throws {
        let suspension = WorkSyncSuspension()
        let oldGateway = ScriptedWorkInboxGateway()
        oldGateway.syncHandlers = [{ _, _, _ in try await suspension.response() }]
        let newGateway = ScriptedWorkInboxGateway()
        let newJob = makeJob(id: workID("job", 6), status: "running", version: 1, updatedAt: 6)
        newGateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 6),
            cursor: 6,
            profile: 2,
            jobs: [newJob]
        )))]
        let model = WorkInboxModel()
        let oldContext = try context(gateway: "gateway-old", profile: 1, session: "runtime-old")
        let newContext = try context(gateway: "gateway-new", profile: 2, session: "runtime-new")

        let oldRefresh = Task {
            await model.refresh(using: oldGateway, context: oldContext, negotiation: durableNegotiation)
        }
        await suspension.waitUntilWaiting()

        await model.refresh(using: newGateway, context: newContext, negotiation: durableNegotiation)
        suspension.succeed(.page(bootstrapPage(
            ledger: workID("ledger", 5),
            cursor: 5,
            jobs: [makeJob(id: workID("job", 5), status: "running", version: 1, updatedAt: 5)]
        )))
        await oldRefresh.value

        XCTAssertEqual(model.sections.active.map(\.id), [newJob.jobID])
        XCTAssertEqual(model.availability, .current)
        XCTAssertNil(model.syncError)
    }

    func testCancelledRefreshCannotPublishAfterTransportReturns() async throws {
        let original = makeJob(id: workID("job", 7), status: "running", version: 1, updatedAt: 7)
        let changed = makeJob(
            id: original.jobID,
            status: "succeeded",
            version: 2,
            updatedAt: 8,
            finishedAt: 8
        )
        let suspension = WorkSyncSuspension()
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [
            immediate(.page(bootstrapPage(
                ledger: workID("ledger", 7),
                cursor: 7,
                jobs: [original]
            ))),
            { _, _, _ in try await suspension.response() },
        ]
        let model = WorkInboxModel()
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)

        let refresh = Task {
            await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)
        }
        await suspension.waitUntilWaiting()
        refresh.cancel()
        suspension.succeed(.page(deltaPage(
            ledger: workID("ledger", 7),
            cursor: 8,
            events: [jobEvent(8, job: changed)]
        )))
        await refresh.value

        XCTAssertEqual(model.sections.active.map(\.id), [original.jobID])
        XCTAssertTrue(model.sections.completed.isEmpty)
        XCTAssertEqual(model.availability, .current)
        XCTAssertFalse(model.isRefreshing)
    }

    func testTypedGroupingKeepsUnknownValuesVisibleAndPayloadsRedacted() async throws {
        let secretMarker = "DO-NOT-PUBLISH-ATTENTION-PAYLOAD"
        let attentionJob = makeJob(
            id: workID("job", 8),
            status: "running",
            version: 1,
            updatedAt: 20,
            openAttentionCount: 1
        )
        let activeJob = makeJob(id: workID("job", 9), status: "queued", version: 1, updatedAt: 19)
        let completeJob = makeJob(
            id: workID("job", 10),
            status: "succeeded",
            version: 2,
            updatedAt: 18,
            finishedAt: 18,
            runtimeSessionID: "result-runtime",
            resultReference: "session:result-runtime",
            resultPreview: .object(["private": .string("RESULT-BODY-MUST-STAY-OUT")])
        )
        let futureJob = makeJob(
            id: workID("job", 11),
            status: "teleporting",
            version: 1,
            updatedAt: 17,
            actionable: false,
            unknownEnums: [.init(field: "work.job.status", raw: "teleporting")]
        )
        let sensitive = makeAttention(
            id: workID("attn", 8),
            jobID: attentionJob.jobID,
            kind: "secret",
            state: "pending",
            version: 3,
            updatedAt: 21,
            sensitive: true,
            payloadMarker: secretMarker
        )
        let futureAttention = makeAttention(
            id: workID("attn", 9),
            jobID: nil,
            kind: "future_prompt",
            state: "pending",
            version: 1,
            updatedAt: 16,
            actionable: false,
            unknownEnums: [.init(field: "work.attention.kind", raw: "future_prompt")],
            payloadMarker: "FUTURE-PAYLOAD-MUST-STAY-OUT"
        )
        let ledger = workID("ledger", 8)
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [
            immediate(.page(bootstrapPage(
                ledger: ledger,
                cursor: 30,
                jobs: [attentionJob, activeJob, completeJob, futureJob],
                attention: [sensitive, futureAttention]
            ))),
            immediate(.page(deltaPage(
                ledger: ledger,
                cursor: 31,
                events: [unknownSubjectEvent(31, marker: "RAW-FUTURE-SUBJECT-MUST-STAY-OUT")]
            ))),
        ]
        let model = WorkInboxModel()
        await model.refresh(using: gateway, context: try context(), negotiation: durableNegotiation)
        let reconnectedContext = try context(connectionGeneration: 2)
        await model.refresh(
            using: gateway,
            context: reconnectedContext,
            negotiation: durableNegotiation
        )

        XCTAssertEqual(model.sections.needsAttention.map(\.id), [attentionJob.jobID])
        XCTAssertEqual(model.sections.active.map(\.id), [activeJob.jobID])
        XCTAssertEqual(model.sections.completed.map(\.id), [completeJob.jobID])
        XCTAssertEqual(model.sections.unsupportedJobs.map(\.id), [futureJob.jobID])
        XCTAssertTrue(model.sections.unsupportedJobs.allSatisfy { !$0.canCancel })
        XCTAssertEqual(model.sections.unsupportedAttention.map(\.id), [futureAttention.attentionID])
        XCTAssertFalse(try XCTUnwrap(model.sections.unsupportedAttention.first).canRespond)
        XCTAssertEqual(model.sections.unsupportedSubjects.map(\.subjectType), ["future_record"])
        XCTAssertEqual(
            model.transcriptRoute(for: completeJob.jobID),
            FabricWorkInboxTranscriptRoute(runtimeSessionID: "result-runtime")
        )

        let published = String(reflecting: model.sections)
        XCTAssertFalse(published.contains(secretMarker))
        XCTAssertFalse(published.contains("RESULT-BODY-MUST-STAY-OUT"))
        XCTAssertFalse(published.contains("FUTURE-PAYLOAD-MUST-STAY-OUT"))
        XCTAssertFalse(published.contains("RAW-FUTURE-SUBJECT-MUST-STAY-OUT"))

        let futureAttentionResult = await model.respondToAttention(
            futureAttention.attentionID,
            action: "submit",
            value: "must-not-send",
            using: gateway,
            context: reconnectedContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(futureAttentionResult, .invalidState)
        let futureCancelResult = await model.requestCancellation(
            for: futureJob.jobID,
            using: gateway,
            context: reconnectedContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(futureCancelResult, .invalidState)
        XCTAssertTrue(gateway.attentionCalls.isEmpty)
        XCTAssertTrue(gateway.cancelCalls.isEmpty)
    }

    func testAttentionResponseUsesCurrentVersionAndFreshIdempotencyWithoutRetainingValue() async throws {
        let secretValue = "VALUE-MUST-NEVER-ENTER-MODEL-STATE"
        let attention = makeAttention(
            id: workID("attn", 12),
            jobID: nil,
            kind: "secret",
            state: "pending",
            version: 7,
            updatedAt: 12,
            sensitive: true,
            payloadMarker: "PAYLOAD-MUST-NEVER-ENTER-MODEL-STATE"
        )
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 12),
            cursor: 12,
            attention: [attention]
        )))]
        gateway.attentionHandlers = [immediate(FabricWorkAttentionMutationReceipt(
            attentionID: attention.attentionID,
            attentionVersion: 8,
            delivered: true,
            mutationID: workID("mut", 12),
            replayed: false,
            state: "resolved"
        ))]
        let model = WorkInboxModel(makeIdempotencyKey: { "attention-key-0000000001" })
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)

        let result = await model.respondToAttention(
            attention.attentionID,
            action: "submit",
            value: secretValue,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )

        XCTAssertEqual(result, .delivered(
            attentionID: attention.attentionID,
            version: 8,
            state: "resolved",
            replayed: false
        ))
        XCTAssertEqual(gateway.attentionCalls.count, 1)
        XCTAssertEqual(gateway.attentionCalls[0].version, 7)
        XCTAssertEqual(gateway.attentionCalls[0].idempotencyKey, "attention-key-0000000001")
        XCTAssertEqual(gateway.attentionCalls[0].value, secretValue)
        XCTAssertFalse(String(reflecting: model).contains(secretValue))
        XCTAssertFalse(String(reflecting: model.sections).contains("PAYLOAD-MUST-NEVER-ENTER-MODEL-STATE"))
        let duplicateResponse = await model.respondToAttention(
            attention.attentionID,
            action: "submit",
            value: "second-value",
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(duplicateResponse, .reconciliationRequired)
        XCTAssertEqual(gateway.attentionCalls.count, 1)
    }

    func testDefinitelyUnsentAttentionValidationDoesNotPoisonTheCurrentVersion() async throws {
        let attention = makeAttention(
            id: workID("attn", 20),
            jobID: nil,
            kind: "secret",
            state: "pending",
            version: 4,
            updatedAt: 20,
            sensitive: true
        )
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 20),
            cursor: 20,
            attention: [attention]
        )))]
        gateway.attentionHandlers = [
            { _, _, _, _, _, _, _ in
                throw FabricWorkGatewayError.invalidRequest("Rejected before transport")
            },
            immediate(FabricWorkAttentionMutationReceipt(
                attentionID: attention.attentionID,
                attentionVersion: 5,
                delivered: true,
                mutationID: workID("mut", 20),
                replayed: false,
                state: "resolved"
            )),
        ]
        var keys = ["attention-key-0000000003", "attention-key-0000000004"]
        let model = WorkInboxModel(makeIdempotencyKey: { keys.removeFirst() })
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)

        let invalid = await model.respondToAttention(
            attention.attentionID,
            action: "submit",
            value: nil,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(invalid, .invalidState)
        XCTAssertTrue(try XCTUnwrap(model.sections.unboundAttention.first).canRespond)

        let delivered = await model.respondToAttention(
            attention.attentionID,
            action: "submit",
            value: "request-local-value",
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(delivered, .delivered(
            attentionID: attention.attentionID,
            version: 5,
            state: "resolved",
            replayed: false
        ))
        XCTAssertEqual(gateway.attentionCalls.map(\.idempotencyKey), [
            "attention-key-0000000003",
            "attention-key-0000000004",
        ])
    }

    func testUnknownAttentionOutcomeBlocksAnotherMutationWithoutRetainingValue() async throws {
        let secretValue = "ATTENTION-VALUE-MUST-NOT-BE-RETAINED"
        let attention = makeAttention(
            id: workID("attn", 24),
            jobID: nil,
            kind: "secret",
            state: "pending",
            version: 4,
            updatedAt: 24,
            sensitive: true
        )
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 24),
            cursor: 24,
            attention: [attention]
        )))]
        gateway.attentionHandlers = [{ _, _, _, _, _, _, _ in
            throw FixtureFailure("PRIVATE-ATTENTION-TRANSPORT-DETAIL")
        }]
        let model = WorkInboxModel(makeIdempotencyKey: { "attention-key-0000000005" })
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)

        let unknown = await model.respondToAttention(
            attention.attentionID,
            action: "submit",
            value: secretValue,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(unknown, .outcomeUnknown)
        XCTAssertFalse(try XCTUnwrap(model.sections.unboundAttention.first).canRespond)
        XCTAssertFalse(String(reflecting: model).contains(secretValue))

        let duplicate = await model.respondToAttention(
            attention.attentionID,
            action: "submit",
            value: "second-value",
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(duplicate, .reconciliationRequired)
        XCTAssertEqual(gateway.attentionCalls.count, 1)
    }

    func testUnknownCancellationOutcomeCannotCreateANewMutationAndRetryReusesExactKey() async throws {
        let running = makeJob(id: workID("job", 13), status: "running", version: 3, updatedAt: 13)
        let requested = makeJob(
            id: running.jobID,
            status: "cancel_requested",
            version: 4,
            updatedAt: 14,
            cancelRequestedAt: 14
        )
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 13),
            cursor: 13,
            jobs: [running]
        )))]
        gateway.cancelHandlers = [
            failing(FixtureFailure("PRIVATE-TRANSPORT-DETAIL")),
            immediate(FabricWorkJobMutationReceipt(
                job: requested,
                mutationID: workID("mut", 13),
                replayed: true,
                runtimeStarted: false,
                taskID: nil,
                newlyCancelled: true
            )),
        ]
        let model = WorkInboxModel(makeIdempotencyKey: { "cancel-key-000000000001" })
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)

        let unknownOutcome = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(unknownOutcome, .outcomeUnknown)
        let duplicateCancellation = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(duplicateCancellation, .reconciliationRequired)
        XCTAssertEqual(gateway.cancelCalls.count, 1)
        XCTAssertFalse(try XCTUnwrap(model.sections.active.first).canCancel)
        XCTAssertFalse(String(reflecting: model).contains("PRIVATE-TRANSPORT-DETAIL"))

        let replay = await model.retryCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(
            replay,
            .requestAccepted(jobID: running.jobID, version: 4, replayed: true)
        )
        XCTAssertEqual(gateway.cancelCalls.count, 2)
        XCTAssertEqual(gateway.cancelCalls.map(\.idempotencyKey), [
            "cancel-key-000000000001",
            "cancel-key-000000000001",
        ])
        XCTAssertEqual(gateway.cancelCalls.map(\.expectedVersion), [3, 3])
    }

    func testTerminalCancelReceiptDoesNotClaimARequestWasAccepted() async throws {
        let running = makeJob(id: workID("job", 14), status: "running", version: 4, updatedAt: 14)
        let terminal = makeJob(
            id: running.jobID,
            status: "succeeded",
            version: 5,
            updatedAt: 15,
            finishedAt: 15
        )
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 14),
            cursor: 14,
            jobs: [running]
        )))]
        gateway.cancelHandlers = [immediate(FabricWorkJobMutationReceipt(
            job: terminal,
            mutationID: workID("mut", 14),
            replayed: false,
            runtimeStarted: false,
            taskID: nil,
            newlyCancelled: false
        ))]
        let model = WorkInboxModel(makeIdempotencyKey: { "cancel-key-000000000002" })
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)

        let result = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )

        XCTAssertEqual(result, .alreadyTerminal(
            jobID: running.jobID,
            status: "succeeded",
            version: 5,
            replayed: false
        ))
    }

    func testDefinitelyUnsentCancelCanRestartButInvalidReceiptKeepsItsFence() async throws {
        let running = makeJob(id: workID("job", 30), status: "running", version: 2, updatedAt: 30)
        let invalidReceiptJob = makeJob(
            id: running.jobID,
            status: "cancel_requested",
            version: 2,
            updatedAt: 30,
            cancelRequestedAt: 30
        )
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 30),
            cursor: 30,
            jobs: [running]
        )))]
        gateway.cancelHandlers = [
            { _, _, _, _, _ in
                throw FabricWorkGatewayError.invalidRequest("Rejected before transport")
            },
            immediate(FabricWorkJobMutationReceipt(
                job: invalidReceiptJob,
                mutationID: workID("mut", 30),
                replayed: false,
                runtimeStarted: false,
                taskID: nil,
                newlyCancelled: true
            )),
        ]
        var keys = ["cancel-key-000000000005", "cancel-key-000000000006"]
        let model = WorkInboxModel(makeIdempotencyKey: { keys.removeFirst() })
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)

        let definitelyUnsent = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(definitelyUnsent, .invalidState)
        XCTAssertTrue(try XCTUnwrap(model.sections.active.first).canCancel)

        let invalidReceipt = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(invalidReceipt, .outcomeUnknown)
        XCTAssertFalse(try XCTUnwrap(model.sections.active.first).canCancel)
        let duplicate = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(duplicate, .reconciliationRequired)
        XCTAssertEqual(gateway.cancelCalls.map(\.idempotencyKey), [
            "cancel-key-000000000005",
            "cancel-key-000000000006",
        ])
    }

    func testCancelledCancellationTaskKeepsTheExactMutationFenced() async throws {
        let running = makeJob(id: workID("job", 25), status: "running", version: 6, updatedAt: 25)
        let requested = makeJob(
            id: running.jobID,
            status: "cancel_requested",
            version: 7,
            updatedAt: 26,
            cancelRequestedAt: 26
        )
        let suspension = CancellationSuspension()
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 25),
            cursor: 25,
            jobs: [running]
        )))]
        gateway.cancelHandlers = [{ _, _, _, _, _ in try await suspension.response() }]
        let model = WorkInboxModel(makeIdempotencyKey: { "cancel-key-000000000003" })
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)

        let cancellation = Task {
            await model.requestCancellation(
                for: running.jobID,
                using: gateway,
                context: inboxContext,
                negotiation: durableNegotiation
            )
        }
        await suspension.waitUntilWaiting()
        cancellation.cancel()
        suspension.succeed(FabricWorkJobMutationReceipt(
            job: requested,
            mutationID: workID("mut", 25),
            replayed: false,
            runtimeStarted: false,
            taskID: nil,
            newlyCancelled: true
        ))

        let result = await cancellation.value
        XCTAssertEqual(result, .stale)
        XCTAssertFalse(try XCTUnwrap(model.sections.active.first).canCancel)
        let duplicate = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(duplicate, .reconciliationRequired)
        XCTAssertEqual(gateway.cancelCalls.map(\.idempotencyKey), ["cancel-key-000000000003"])
        XCTAssertEqual(gateway.cancelCalls.map(\.expectedVersion), [6])
    }

    func testReconnectKeepsInFlightMutationsFencedUntilAuthoritativeDelta() async throws {
        let running = makeJob(id: workID("job", 26), status: "running", version: 1, updatedAt: 26)
        let cancelRequested = makeJob(
            id: running.jobID,
            status: "cancel_requested",
            version: 2,
            updatedAt: 27,
            cancelRequestedAt: 27
        )
        let pending = makeAttention(
            id: workID("attn", 26),
            jobID: nil,
            kind: "approval",
            state: "pending",
            version: 1,
            updatedAt: 26
        )
        let resolved = makeAttention(
            id: pending.attentionID,
            jobID: nil,
            kind: "approval",
            state: "resolved",
            version: 2,
            updatedAt: 28,
            actionable: false
        )
        let ledger = workID("ledger", 26)
        let cancellationSuspension = CancellationSuspension()
        let attentionSuspension = AttentionSuspension()
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [
            immediate(.page(bootstrapPage(
                ledger: ledger,
                cursor: 26,
                jobs: [running],
                attention: [pending]
            ))),
            immediate(.page(deltaPage(ledger: ledger, cursor: 26, events: []))),
            immediate(.page(deltaPage(
                ledger: ledger,
                cursor: 28,
                events: [
                    jobEvent(27, job: cancelRequested),
                    attentionEvent(28, attention: resolved),
                ]
            ))),
        ]
        gateway.cancelHandlers = [{ _, _, _, _, _ in try await cancellationSuspension.response() }]
        gateway.attentionHandlers = [{ _, _, _, _, _, _, _ in try await attentionSuspension.response() }]
        var keys = ["cancel-key-000000000004", "attention-key-0000000006"]
        let model = WorkInboxModel(makeIdempotencyKey: { keys.removeFirst() })
        let firstContext = try context(connectionGeneration: 1)
        await model.refresh(using: gateway, context: firstContext, negotiation: durableNegotiation)

        let cancellation = Task {
            await model.requestCancellation(
                for: running.jobID,
                using: gateway,
                context: firstContext,
                negotiation: durableNegotiation
            )
        }
        await cancellationSuspension.waitUntilWaiting()
        let response = Task {
            await model.respondToAttention(
                pending.attentionID,
                action: "once",
                using: gateway,
                context: firstContext,
                negotiation: durableNegotiation
            )
        }
        await attentionSuspension.waitUntilWaiting()

        let secondContext = try context(connectionGeneration: 2)
        await model.refresh(using: gateway, context: secondContext, negotiation: durableNegotiation)
        XCTAssertFalse(try XCTUnwrap(model.sections.active.first).canCancel)
        XCTAssertFalse(try XCTUnwrap(model.sections.unboundAttention.first).canRespond)

        cancellationSuspension.succeed(FabricWorkJobMutationReceipt(
            job: cancelRequested,
            mutationID: workID("mut", 26),
            replayed: false,
            runtimeStarted: false,
            taskID: nil,
            newlyCancelled: true
        ))
        attentionSuspension.succeed(FabricWorkAttentionMutationReceipt(
            attentionID: pending.attentionID,
            attentionVersion: 2,
            delivered: true,
            mutationID: workID("mut", 27),
            replayed: false,
            state: "resolved"
        ))
        let cancellationResult = await cancellation.value
        let attentionResult = await response.value
        XCTAssertEqual(cancellationResult, .stale)
        XCTAssertEqual(attentionResult, .stale)

        await model.refresh(
            using: gateway,
            context: try context(connectionGeneration: 3),
            negotiation: durableNegotiation
        )
        XCTAssertEqual(model.sections.active.map(\.id), [running.jobID])
        XCTAssertFalse(try XCTUnwrap(model.sections.active.first).canCancel)
        XCTAssertTrue(model.sections.unboundAttention.isEmpty)
    }

    func testInvalidateClearsProjectionAndUnknownMutationFence() async throws {
        let running = makeJob(id: workID("job", 29), status: "running", version: 1, updatedAt: 29)
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 29),
            cursor: 29,
            jobs: [running]
        )))]
        gateway.cancelHandlers = [failing(FixtureFailure("PRIVATE-CANCEL-FAILURE"))]
        let model = WorkInboxModel()
        let inboxContext = try context()
        await model.refresh(using: gateway, context: inboxContext, negotiation: durableNegotiation)
        let unknown = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(unknown, .outcomeUnknown)

        model.invalidate()

        XCTAssertEqual(model.availability, .unavailable)
        XCTAssertTrue(model.sections.isEmpty)
        XCTAssertFalse(model.isRefreshing)
        XCTAssertNil(model.syncError)
        XCTAssertNil(model.lastUpdated)
        let staleRequest = await model.requestCancellation(
            for: running.jobID,
            using: gateway,
            context: inboxContext,
            negotiation: durableNegotiation
        )
        XCTAssertEqual(staleRequest, .invalidState)
        XCTAssertEqual(gateway.cancelCalls.count, 1)
        XCTAssertFalse(gateway.cancelCalls[0].idempotencyKey.isEmpty)
    }

    func testAttentionCompletionFromPriorAuthorityIsIgnored() async throws {
        let attention = makeAttention(
            id: workID("attn", 15),
            jobID: nil,
            kind: "approval",
            state: "pending",
            version: 1,
            updatedAt: 15
        )
        let oldGateway = ScriptedWorkInboxGateway()
        let actionSuspension = AttentionSuspension()
        oldGateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 15),
            cursor: 15,
            attention: [attention]
        )))]
        oldGateway.attentionHandlers = [{ _, _, _, _, _, _, _ in
            try await actionSuspension.response()
        }]
        let newGateway = ScriptedWorkInboxGateway()
        let newJob = makeJob(id: workID("job", 16), status: "queued", version: 1, updatedAt: 16)
        newGateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 16),
            cursor: 16,
            profile: 2,
            jobs: [newJob]
        )))]
        let model = WorkInboxModel(makeIdempotencyKey: { "attention-key-0000000002" })
        let oldContext = try context(gateway: "gateway-a", profile: 1, session: "runtime-a")
        let newContext = try context(gateway: "gateway-b", profile: 2, session: "runtime-b")
        await model.refresh(using: oldGateway, context: oldContext, negotiation: durableNegotiation)

        let response = Task {
            await model.respondToAttention(
                attention.attentionID,
                action: "once",
                using: oldGateway,
                context: oldContext,
                negotiation: durableNegotiation
            )
        }
        await actionSuspension.waitUntilWaiting()
        await model.refresh(using: newGateway, context: newContext, negotiation: durableNegotiation)
        actionSuspension.succeed(FabricWorkAttentionMutationReceipt(
            attentionID: attention.attentionID,
            attentionVersion: 2,
            delivered: true,
            mutationID: workID("mut", 15),
            replayed: false,
            state: "resolved"
        ))

        let staleResult = await response.value
        XCTAssertEqual(staleResult, .stale)
        XCTAssertEqual(model.sections.active.map(\.id), [newJob.jobID])
        XCTAssertTrue(model.sections.unboundAttention.isEmpty)
    }

    func testTranscriptRoutingRejectsNonSessionAndMismatchedReferences() async throws {
        let valid = makeJob(
            id: workID("job", 17),
            status: "succeeded",
            version: 2,
            updatedAt: 17,
            finishedAt: 17,
            runtimeSessionID: "runtime-valid",
            resultReference: "session:runtime-valid"
        )
        let nonSession = makeJob(
            id: workID("job", 18),
            status: "succeeded",
            version: 2,
            updatedAt: 18,
            finishedAt: 18,
            runtimeSessionID: "runtime-other",
            resultReference: "artifact://result"
        )
        let mismatch = makeJob(
            id: workID("job", 19),
            status: "succeeded",
            version: 2,
            updatedAt: 19,
            finishedAt: 19,
            runtimeSessionID: "runtime-one",
            resultReference: "session:runtime-two"
        )
        let gateway = ScriptedWorkInboxGateway()
        gateway.syncHandlers = [immediate(.page(bootstrapPage(
            ledger: workID("ledger", 17),
            cursor: 17,
            jobs: [valid, nonSession, mismatch]
        )))]
        let model = WorkInboxModel()
        await model.refresh(using: gateway, context: try context(), negotiation: durableNegotiation)

        XCTAssertEqual(
            model.transcriptRoute(for: valid.jobID),
            FabricWorkInboxTranscriptRoute(runtimeSessionID: "runtime-valid")
        )
        XCTAssertNil(model.transcriptRoute(for: nonSession.jobID))
        XCTAssertNil(model.transcriptRoute(for: mismatch.jobID))
    }

    private var durableNegotiation: GatewayCapabilityNegotiation {
        .verified(GatewayCapabilities(
            contract: GatewayCapabilityContract(
                name: "fabric.gateway",
                version: 1,
                minimumCompatibleVersion: 1
            ),
            server: GatewayServerContract(version: "test", releaseDate: "2026-07-20"),
            execution: GatewayExecutionContract(
                location: "gateway",
                toolExecution: "gateway",
                survivesClientDisconnect: true,
                survivesGatewayRestart: false,
                requiresGatewayHostOnline: true
            ),
            features: ["durable_work": true],
            methods: durableWorkGatewayMethods
        ))
    }

    private func context(
        gateway: String = "gateway-1",
        profile: Int = 1,
        session: String = "runtime-1",
        connectionGeneration: Int = 1
    ) throws -> FabricWorkInboxContext {
        let identity = try FabricWorkSessionIdentity(sessionInfo: [
            "work_profile_id": workID("profile", profile),
        ])
        return try XCTUnwrap(FabricWorkInboxContext(
            gatewayID: gateway,
            runtimeSessionID: session,
            workIdentity: identity,
            connectionGeneration: connectionGeneration
        ))
    }

    private func bootstrapPage(
        ledger: String,
        cursor: Int,
        profile: Int = 1,
        hasMore: Bool = false,
        nextToken: String? = nil,
        jobs: [FabricWorkJobSummary] = [],
        attention: [FabricWorkAttention] = []
    ) -> FabricWorkSyncPage {
        FabricWorkSyncPage(
            contract: .init(name: "fabric.work", version: 1, minimumCompatibleVersion: 1),
            ledgerID: ledger,
            workProfileID: workID("profile", profile),
            mode: "bootstrap",
            watermark: cursor,
            cursor: cursor,
            hasMore: hasMore,
            nextPageToken: nextToken,
            jobs: jobs,
            attention: attention,
            events: [],
            encodedBytes: 1,
            actionable: true,
            unknownEnums: []
        )
    }

    private func deltaPage(
        ledger: String,
        cursor: Int,
        events: [FabricWorkEvent]
    ) -> FabricWorkSyncPage {
        FabricWorkSyncPage(
            contract: .init(name: "fabric.work", version: 1, minimumCompatibleVersion: 1),
            ledgerID: ledger,
            workProfileID: workID("profile", 1),
            mode: "delta",
            watermark: cursor,
            cursor: cursor,
            hasMore: false,
            nextPageToken: nil,
            jobs: [],
            attention: [],
            events: events,
            encodedBytes: 1,
            actionable: true,
            unknownEnums: []
        )
    }

    private func jobEvent(_ eventID: Int, job: FabricWorkJobSummary) -> FabricWorkEvent {
        FabricWorkEvent(
            eventID: eventID,
            eventType: "job.updated",
            subjectType: "job",
            subjectID: job.jobID,
            jobID: job.jobID,
            runID: nil,
            subjectVersion: job.version,
            subject: .job(job),
            tombstone: false,
            createdAt: eventID,
            actionable: job.actionable,
            unknownEnums: job.unknownEnums
        )
    }

    private func attentionEvent(
        _ eventID: Int,
        attention: FabricWorkAttention
    ) -> FabricWorkEvent {
        FabricWorkEvent(
            eventID: eventID,
            eventType: "attention.updated",
            subjectType: "attention",
            subjectID: attention.attentionID,
            jobID: attention.jobID,
            runID: attention.runID,
            subjectVersion: attention.version,
            subject: .attention(attention),
            tombstone: false,
            createdAt: eventID,
            actionable: attention.actionable,
            unknownEnums: attention.unknownEnums
        )
    }

    private func unknownSubjectEvent(_ eventID: Int, marker: String) -> FabricWorkEvent {
        FabricWorkEvent(
            eventID: eventID,
            eventType: "future.updated",
            subjectType: "future_record",
            subjectID: "future-record-1",
            jobID: nil,
            runID: nil,
            subjectVersion: 1,
            subject: .unknown(FabricWorkUnknownSubject(
                raw: ["private": .string(marker)],
                unknownEnums: [.init(field: "work.event.subject_type", raw: "future_record")]
            )),
            tombstone: false,
            createdAt: eventID,
            actionable: false,
            unknownEnums: [.init(field: "work.event.subject_type", raw: "future_record")]
        )
    }

    private func makeJob(
        id: String,
        status: String,
        version: Int,
        updatedAt: Int,
        finishedAt: Int? = nil,
        cancelRequestedAt: Int? = nil,
        openAttentionCount: Int = 0,
        actionable: Bool = true,
        unknownEnums: [FabricWorkUnknownEnum] = [],
        runtimeSessionID: String? = "runtime-1",
        resultReference: String? = nil,
        resultPreview: FabricWorkJSONValue = .null
    ) -> FabricWorkJobSummary {
        FabricWorkJobSummary(
            jobID: id,
            version: version,
            kind: "background_prompt",
            status: status,
            title: "Work \(id.suffix(2))",
            summary: "Bounded public summary",
            source: "mobile",
            sourceSessionKey: "stored-session",
            runtimeSessionID: runtimeSessionID,
            attemptCount: 1,
            openAttentionCount: openAttentionCount,
            createdAt: 1,
            startedAt: status == "queued" ? nil : 2,
            updatedAt: updatedAt,
            finishedAt: finishedAt,
            cancelRequestedAt: cancelRequestedAt,
            runtime: [:],
            currentRun: nil,
            resultPreview: resultPreview,
            resultReference: resultReference,
            resultOmittedReason: nil,
            error: .null,
            actionable: actionable,
            unknownEnums: unknownEnums
        )
    }

    private func makeAttention(
        id: String,
        jobID: String?,
        kind: String,
        state: String,
        version: Int,
        updatedAt: Int,
        sensitive: Bool = false,
        actionable: Bool = true,
        unknownEnums: [FabricWorkUnknownEnum] = [],
        payloadMarker: String = "redacted"
    ) -> FabricWorkAttention {
        FabricWorkAttention(
            attentionID: id,
            version: version,
            jobID: jobID,
            runID: nil,
            sourceSessionKey: "stored-session",
            runtimeSessionID: "runtime-1",
            requestID: "request-1",
            kind: kind,
            state: state,
            blocking: true,
            sensitive: sensitive,
            title: "Response required",
            publicPayload: ["private": .string(payloadMarker)],
            allowedActions: state == "pending"
                ? (kind == "approval" ? ["once", "deny"] : ["submit", "cancel"])
                : [],
            createdAt: 1,
            updatedAt: updatedAt,
            expiresAt: nil,
            resolvedAt: nil,
            terminalReason: nil,
            actionable: actionable,
            unknownEnums: unknownEnums
        )
    }

    private func workID(_ prefix: String, _ value: Int) -> String {
        "\(prefix)_\(String(format: "%032x", value))"
    }
}

@MainActor
private final class ScriptedWorkInboxGateway: FabricWorkInboxGateway {
    struct SyncCall: Equatable {
        let sessionID: String
        let request: FabricWorkSyncRequest
    }

    struct CancellationCall: Equatable {
        let sessionID: String
        let jobID: String
        let expectedVersion: Int
        let idempotencyKey: String
    }

    struct AttentionCall: Equatable {
        let sessionID: String
        let attentionID: String
        let version: Int
        let action: String
        let idempotencyKey: String
        let reason: String?
        let value: String?
    }

    typealias SyncHandler = @MainActor (
        String,
        FabricWorkSyncRequest,
        GatewayCapabilityNegotiation
    ) async throws -> FabricWorkGatewayResponse
    typealias CancellationHandler = @MainActor (
        String,
        String,
        Int,
        String,
        GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobMutationReceipt
    typealias AttentionHandler = @MainActor (
        String,
        FabricWorkAttention,
        String,
        String,
        String?,
        String?,
        GatewayCapabilityNegotiation
    ) async throws -> FabricWorkAttentionMutationReceipt

    var syncHandlers: [SyncHandler] = []
    var cancelHandlers: [CancellationHandler] = []
    var attentionHandlers: [AttentionHandler] = []
    private(set) var syncCalls: [SyncCall] = []
    private(set) var cancelCalls: [CancellationCall] = []
    private(set) var attentionCalls: [AttentionCall] = []

    func syncWork(
        sessionID: String,
        request: FabricWorkSyncRequest,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkGatewayResponse {
        syncCalls.append(.init(sessionID: sessionID, request: request))
        guard !syncHandlers.isEmpty else { throw FixtureFailure("No sync response") }
        return try await syncHandlers.removeFirst()(sessionID, request, negotiation)
    }

    func cancelWorkJob(
        sessionID: String,
        jobID: String,
        expectedVersion: Int,
        idempotencyKey: String,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobMutationReceipt {
        cancelCalls.append(.init(
            sessionID: sessionID,
            jobID: jobID,
            expectedVersion: expectedVersion,
            idempotencyKey: idempotencyKey
        ))
        guard !cancelHandlers.isEmpty else { throw FixtureFailure("No cancellation response") }
        return try await cancelHandlers.removeFirst()(
            sessionID,
            jobID,
            expectedVersion,
            idempotencyKey,
            negotiation
        )
    }

    func respondToWorkAttention(
        sessionID: String,
        attention: FabricWorkAttention,
        action: String,
        idempotencyKey: String,
        reason: String?,
        value: String?,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkAttentionMutationReceipt {
        attentionCalls.append(.init(
            sessionID: sessionID,
            attentionID: attention.attentionID,
            version: attention.version,
            action: action,
            idempotencyKey: idempotencyKey,
            reason: reason,
            value: value
        ))
        guard !attentionHandlers.isEmpty else { throw FixtureFailure("No Attention response") }
        return try await attentionHandlers.removeFirst()(
            sessionID,
            attention,
            action,
            idempotencyKey,
            reason,
            value,
            negotiation
        )
    }
}

@MainActor
private final class WorkSyncSuspension {
    private var continuation: CheckedContinuation<FabricWorkGatewayResponse, Error>?

    func response() async throws -> FabricWorkGatewayResponse {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    func waitUntilWaiting() async {
        while continuation == nil { await Task.yield() }
    }

    func succeed(_ response: FabricWorkGatewayResponse) {
        let continuation = continuation
        self.continuation = nil
        continuation?.resume(returning: response)
    }
}

@MainActor
private final class AttentionSuspension {
    private var continuation: CheckedContinuation<FabricWorkAttentionMutationReceipt, Error>?

    func response() async throws -> FabricWorkAttentionMutationReceipt {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    func waitUntilWaiting() async {
        while continuation == nil { await Task.yield() }
    }

    func succeed(_ response: FabricWorkAttentionMutationReceipt) {
        let continuation = continuation
        self.continuation = nil
        continuation?.resume(returning: response)
    }
}

@MainActor
private final class CancellationSuspension {
    private var continuation: CheckedContinuation<FabricWorkJobMutationReceipt, Error>?

    func response() async throws -> FabricWorkJobMutationReceipt {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    func waitUntilWaiting() async {
        while continuation == nil { await Task.yield() }
    }

    func succeed(_ response: FabricWorkJobMutationReceipt) {
        let continuation = continuation
        self.continuation = nil
        continuation?.resume(returning: response)
    }
}

@MainActor
private func immediate<T>(_ value: T) -> @MainActor (
    String,
    FabricWorkSyncRequest,
    GatewayCapabilityNegotiation
) async throws -> T {
    { _, _, _ in value }
}

@MainActor
private func immediate<T>(_ value: T) -> @MainActor (
    String,
    String,
    Int,
    String,
    GatewayCapabilityNegotiation
) async throws -> T {
    { _, _, _, _, _ in value }
}

@MainActor
private func immediate<T>(_ value: T) -> @MainActor (
    String,
    FabricWorkAttention,
    String,
    String,
    String?,
    String?,
    GatewayCapabilityNegotiation
) async throws -> T {
    { _, _, _, _, _, _, _ in value }
}

@MainActor
private func failing<T>(_ error: Error) -> @MainActor (
    String,
    String,
    Int,
    String,
    GatewayCapabilityNegotiation
) async throws -> T {
    { _, _, _, _, _ in throw error }
}

private struct FixtureFailure: LocalizedError {
    let message: String

    init(_ message: String) {
        self.message = message
    }

    var errorDescription: String? { message }
}
