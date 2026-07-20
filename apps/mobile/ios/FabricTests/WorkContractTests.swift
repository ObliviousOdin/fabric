import Foundation
import XCTest
@testable import Fabric

final class WorkContractTests: XCTestCase {
    private let scope = FabricWorkSyncScope(
        gatewayID: "gateway-local",
        profileID: "profile_11111111111111111111111111111111"
    )

    func testCanonicalFixtureManifestHasTheExpectedDecodeOutcomes() throws {
        let manifest = try fixtureObject("manifest.json")
        let cases = try XCTUnwrap(manifest["cases"] as? [[String: Any]])
        XCTAssertEqual(cases.count, 11)

        for fixtureCase in cases {
            let id = try XCTUnwrap(fixtureCase["id"] as? String)
            let file = try XCTUnwrap(fixtureCase["file"] as? String)
            let kind = try XCTUnwrap(fixtureCase["kind"] as? String)
            let expected = try XCTUnwrap(fixtureCase["expected"] as? String)
            let value = try fixtureValue(file)

            switch kind {
            case "page":
                switch (expected, FabricWorkParser.parseSyncPage(value)) {
                case ("verified", .verified):
                    break
                case ("invalid", .invalid):
                    break
                case ("incompatible", .incompatible):
                    break
                default:
                    XCTFail("Fixture \(id) did not produce canonical \(expected) outcome")
                }
            case "reset":
                switch FabricWorkParser.parseCursorReset(value) {
                case .verified:
                    XCTAssertEqual(expected, "verified", "Fixture \(id) must be verified")
                case .invalid(let message):
                    XCTFail("Fixture \(id) reset was invalid: \(message)")
                }
            default:
                XCTFail("Unknown fixture kind \(kind)")
            }
        }
    }

    func testMalformedAndIncompatibleFixturesFailClosed() throws {
        switch FabricWorkParser.parseSyncPage(try fixtureValue("malformed.json")) {
        case .invalid(let message):
            XCTAssertTrue(message.contains("finished_at"))
        default:
            XCTFail("Malformed fixture must not create a usable page")
        }

        switch FabricWorkParser.parseSyncPage(try fixtureValue("incompatible.json")) {
        case .incompatible(let minimum):
            XCTAssertEqual(minimum, 2)
        default:
            XCTFail("Future minimum compatibility must fail closed")
        }

        var missingNullable = try fixtureObject("bootstrap-page-2.json")
        var jobs = try XCTUnwrap(missingNullable["jobs"] as? [[String: Any]])
        jobs[0].removeValue(forKey: "finished_at")
        missingNullable["jobs"] = jobs
        guard case .invalid(let message) = FabricWorkParser.parseSyncPage(missingNullable) else {
            return XCTFail("Required nullable field omission must be invalid")
        }
        XCTAssertTrue(message.contains("finished_at"))
    }

    func testCompatibleAdditiveFutureValuesRemainVisibleButNonActionable() throws {
        let page = try verifiedPage("additive-future.json")
        XCTAssertEqual(page.contract.version, 2)
        XCTAssertEqual(page.contract.minimumCompatibleVersion, 1)
        XCTAssertTrue(page.actionable)
        let job = try XCTUnwrap(page.jobs.first)
        XCTAssertEqual(job.kind, "future_workflow")
        XCTAssertEqual(job.status, "materializing")
        XCTAssertFalse(job.actionable)
        XCTAssertEqual(job.unknownEnums.map(\.raw), ["future_workflow", "materializing"])

        let projection = try FabricWorkProjectionReducer.apply(
            FabricWorkProjectionReducer.create(scope: FabricWorkSyncScope(
                gatewayID: "future-gateway",
                profileID: "profile_99999999999999999999999999999999"
            )),
            page: page,
            context: FabricWorkSyncRequestContext(scope: FabricWorkSyncScope(
                gatewayID: "future-gateway",
                profileID: "profile_99999999999999999999999999999999"
            ))
        )
        XCTAssertEqual(projection.phase, .current)
        XCTAssertFalse(projection.jobs[job.jobID]?.actionable ?? true)
    }

    func testBootstrapPublishesCursorOnlyAfterAllPagesApply() throws {
        let empty = try FabricWorkProjectionReducer.create(scope: scope)
        let first = try FabricWorkProjectionReducer.apply(
            empty,
            page: try verifiedPage("bootstrap-page-1.json"),
            context: FabricWorkSyncRequestContext(scope: scope)
        )
        XCTAssertEqual(first.phase, .bootstrapping)
        XCTAssertNil(first.cursor)
        XCTAssertEqual(first.watermark, 100)
        XCTAssertEqual(first.nextPageToken, "work-page-v1.first-to-second")
        XCTAssertEqual(first.jobs.count, 1)
        XCTAssertEqual(first.attention.count, 1)

        let complete = try FabricWorkProjectionReducer.apply(
            first,
            page: try verifiedPage("bootstrap-page-2.json"),
            context: FabricWorkSyncRequestContext(
                scope: scope,
                pageToken: first.nextPageToken
            )
        )
        XCTAssertEqual(complete.phase, .current)
        XCTAssertEqual(complete.cursor, 100)
        XCTAssertNil(complete.nextPageToken)
        XCTAssertEqual(complete.jobs.count, 2)

        XCTAssertThrowsError(
            try FabricWorkProjectionReducer.apply(
                first,
                page: try verifiedPage("bootstrap-page-2.json"),
                context: FabricWorkSyncRequestContext(scope: scope, pageToken: "wrong-token")
            )
        ) { error in
            XCTAssertEqual((error as? FabricWorkSyncApplyError)?.code, .bootstrapSequenceInvalid)
        }
    }

    func testDeltaAppliesAfterStatesAndDedupesReplays() throws {
        let initial = try bootstrappedProjection()
        let delta = try verifiedPage("delta.json")
        let next = try FabricWorkProjectionReducer.apply(
            initial,
            page: delta,
            context: FabricWorkSyncRequestContext(scope: scope, after: initial.cursor)
        )
        let jobID = "job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        XCTAssertEqual(next.cursor, 101)
        XCTAssertEqual(next.jobs[jobID]?.version, 2)
        XCTAssertEqual(next.jobs[jobID]?.status, "running")

        let replay = try FabricWorkProjectionReducer.apply(
            next,
            page: delta,
            context: FabricWorkSyncRequestContext(scope: scope)
        )
        XCTAssertEqual(replay, next)
    }

    func testTombstoneVersionsPreventStaleResurrection() throws {
        let running = try applyDelta(to: try bootstrappedProjection(), fixture: "delta.json")
        let deleted = try FabricWorkProjectionReducer.apply(
            running,
            page: try verifiedPage("tombstone.json"),
            context: FabricWorkSyncRequestContext(scope: scope, after: running.cursor)
        )
        let attentionID = "attn_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        XCTAssertNil(deleted.attention[attentionID])
        XCTAssertNil(deleted.jobs["job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"])
        XCTAssertEqual(deleted.subjectVersions["attention:\(attentionID)"], 3)

        var stale = try fixtureObject("sensitive-attention.json")
        var events = try XCTUnwrap(stale["events"] as? [[String: Any]])
        var event = events[0]
        event["subject_id"] = attentionID
        event["subject_version"] = 1
        var subject = try XCTUnwrap(event["subject"] as? [String: Any])
        subject["attention_id"] = attentionID
        subject["version"] = 1
        event["subject"] = subject
        events[0] = event
        stale["events"] = events

        let noResurrection = try FabricWorkProjectionReducer.apply(
            deleted,
            page: try verifiedPage(stale),
            context: FabricWorkSyncRequestContext(scope: scope, after: deleted.cursor)
        )
        XCTAssertNil(noResurrection.attention[attentionID])
        XCTAssertEqual(noResurrection.cursor, 104)
    }

    func testSensitiveAttentionAndTerminalJobStayInProjectionWithoutRawValues() throws {
        var state = try applyDelta(to: try bootstrappedProjection(), fixture: "delta.json")
        state = try FabricWorkProjectionReducer.apply(
            state,
            page: try verifiedPage("tombstone.json"),
            context: FabricWorkSyncRequestContext(scope: scope, after: state.cursor)
        )
        state = try FabricWorkProjectionReducer.apply(
            state,
            page: try verifiedPage("sensitive-attention.json"),
            context: FabricWorkSyncRequestContext(scope: scope, after: state.cursor)
        )
        let sensitiveID = "attn_ffffffffffffffffffffffffffffffff"
        let attention = try XCTUnwrap(state.attention[sensitiveID])
        XCTAssertTrue(attention.sensitive)
        XCTAssertEqual(attention.kind, "secret")
        XCTAssertEqual(attention.allowedActions, ["submit", "cancel"])
        XCTAssertTrue(attention.actionable)
        XCTAssertEqual(attention.publicPayload.keys.sorted(), ["purpose", "service"])
        XCTAssertFalse(attention.publicPayload.keys.contains("value"))

        state = try FabricWorkProjectionReducer.apply(
            state,
            page: try verifiedPage("terminal.json"),
            context: FabricWorkSyncRequestContext(scope: scope, after: state.cursor)
        )
        let terminal = try XCTUnwrap(state.jobs["job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"])
        XCTAssertEqual(state.cursor, 105)
        XCTAssertEqual(terminal.status, "succeeded")
        XCTAssertEqual(terminal.version, 3)
        XCTAssertEqual(terminal.resultPreview, .object([
            "text": .string("QA brief prepared"),
            "artifact": .string("mobile-qa-brief.md"),
        ]))
    }

    func testReplacedAndExpiredLedgerResetDiscardOldNamespace() throws {
        let initial = try bootstrappedProjection()
        let replaced = try verifiedReset("replaced-ledger.json")
        let reset = try FabricWorkProjectionReducer.applyCursorReset(initial, reset: replaced, scope: scope)
        XCTAssertEqual(reset.phase, .empty)
        XCTAssertNil(reset.ledgerID)
        XCTAssertNil(reset.cursor)
        XCTAssertEqual(reset.resetLedgerHint, "ledger_22222222222222222222222222222222")
        XCTAssertTrue(reset.jobs.isEmpty)
        XCTAssertTrue(reset.attention.isEmpty)

        XCTAssertThrowsError(
            try FabricWorkProjectionReducer.apply(
                reset,
                page: try verifiedPage("delta.json"),
                context: FabricWorkSyncRequestContext(scope: scope, after: 0)
            )
        ) { error in
            XCTAssertEqual((error as? FabricWorkSyncApplyError)?.code, .bootstrapRequired)
        }

        let expired = try verifiedReset("cursor-expired.json")
        XCTAssertEqual(expired.data.ledgerID, "ledger_11111111111111111111111111111111")
        XCTAssertEqual(expired.data.eventFloor, 80)
        XCTAssertEqual(expired.data.highWater, 105)
    }

    func testGatewayWorkWrapperDecodesOnlyTypedPagesAndResets() throws {
        let pageResponse = try GatewayAPI.decodeWorkSyncResponse(
            try fixtureValue("bootstrap-page-1.json")
        )
        guard case .page(let page) = pageResponse else {
            return XCTFail("Expected typed Work page")
        }
        XCTAssertEqual(page.mode, "bootstrap")

        let resetResponse = try GatewayAPI.decodeWorkCursorReset(
            try fixtureValue("replaced-ledger.json")
        )
        guard case .reset(let reset) = resetResponse else {
            return XCTFail("Expected typed Work reset")
        }
        XCTAssertEqual(reset.data.ledgerID, "ledger_22222222222222222222222222222222")

        XCTAssertThrowsError(
            try GatewayAPI.decodeWorkSyncResponse(try fixtureValue("incompatible.json"))
        ) { error in
            XCTAssertEqual(
                error as? FabricWorkGatewayError,
                .incompatibleContract(minimumCompatibleVersion: 2)
            )
        }
        XCTAssertThrowsError(
            try GatewayAPI.decodeWorkSyncResponse(try fixtureValue("malformed.json"))
        ) { error in
            guard case .invalidContract = error as? FabricWorkGatewayError else {
                return XCTFail("Malformed page must not become a Work response")
            }
        }
    }

    func testCursorExpiredTransportErrorReconstructsTheFullResetEnvelope() async throws {
        let resetEnvelope = try fixtureObject("cursor-expired.json")
        let error = GatewayClientError.rpc(
            message: try XCTUnwrap(resetEnvelope["message"] as? String),
            code: -32_047,
            data: resetEnvelope["data"]
        )

        let response = try await GatewayAPI.decodeWorkSyncTransport {
            throw error
        }
        guard case .reset(let reset) = response else {
            return XCTFail("The WebSocket cursor-expiry error must become a typed reset")
        }
        XCTAssertEqual(reset.data.ledgerID, "ledger_11111111111111111111111111111111")

        do {
            _ = try await GatewayAPI.decodeWorkSyncTransport {
                throw GatewayClientError.rpc(
                    message: "ordinary RPC failure",
                    code: -32_046,
                    data: resetEnvelope["data"]
                )
            }
            XCTFail("Only -32047 may reset a Work projection")
        } catch let received as GatewayClientError {
            guard case .rpc(_, let code, _) = received else {
                return XCTFail("Expected the original RPC error")
            }
            XCTAssertEqual(code, -32_046)
        }
    }

    func testNonSyncWorkResponsesAreStrictlyDecoded() throws {
        let bootstrap = try fixtureObject("bootstrap-page-1.json")
        let job = try XCTUnwrap((bootstrap["jobs"] as? [[String: Any]])?.first)
        let profileID = try XCTUnwrap(bootstrap["work_profile_id"] as? String)
        let jobID = try XCTUnwrap(job["job_id"] as? String)

        let jobReceipt = try GatewayAPI.decodeWorkJobMutationReceipt([
            "job": job,
            "mutation_id": "mut_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "replayed": false,
            "runtime_started": true,
            "task_id": "bg_1234567890abcdef",
        ])
        XCTAssertEqual(jobReceipt.job.jobID, jobID)
        XCTAssertEqual(jobReceipt.mutationID, "mut_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        XCTAssertEqual(jobReceipt.runtimeStarted, true)

        // `job.get` includes bodies that are deliberately larger than the
        // sync/list subject cap. The detail decoder retains them only in its
        // bounded detail value and parses the projection-safe summary
        // independently.
        let detailBody = String(repeating: "x", count: 33 * 1_024)
        var detailedJob = job
        detailedJob["prompt_preview"] = "redacted prompt preview"
        detailedJob["result"] = detailBody
        detailedJob["error_detail"] = ["code": "detail"]
        let detail = try GatewayAPI.decodeWorkJobDetailResponse(detailedJob)
        XCTAssertEqual(detail.job.jobID, jobID)
        XCTAssertEqual(detail.promptPreview, "redacted prompt preview")
        XCTAssertEqual(detail.result, .string(detailBody))

        let jobList = try GatewayAPI.decodeWorkJobListResponse([
            "work_profile_id": profileID,
            "jobs": [job],
            "next_before": NSNull(),
        ])
        XCTAssertEqual(jobList.workProfileID, profileID)
        XCTAssertEqual(jobList.jobs.map(\.jobID), [jobID])
        XCTAssertNil(jobList.nextBefore)

        let sensitive = try fixtureObject("sensitive-attention.json")
        let sensitiveEvent = try XCTUnwrap((sensitive["events"] as? [[String: Any]])?.first)
        let attention = try XCTUnwrap(sensitiveEvent["subject"] as? [String: Any])
        let attentionID = try XCTUnwrap(attention["attention_id"] as? String)
        let attentionReceipt = try GatewayAPI.decodeWorkAttentionMutationReceipt([
            "attention_id": attentionID,
            "attention_version": 2,
            "delivered": true,
            "mutation_id": "mut_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "replayed": false,
            "state": "resolved",
        ])
        XCTAssertEqual(attentionReceipt.attentionID, attentionID)
        XCTAssertEqual(attentionReceipt.attentionVersion, 2)

        let attentionList = try GatewayAPI.decodeWorkAttentionListResponse([
            "work_profile_id": profileID,
            "attention": [attention],
            "next_before": "opaque-attention-page-token",
        ])
        XCTAssertEqual(attentionList.attention.map(\.attentionID), [attentionID])
        XCTAssertEqual(attentionList.nextBefore, "opaque-attention-page-token")

        let delta = try fixtureObject("delta.json")
        let event = try XCTUnwrap((delta["events"] as? [[String: Any]])?.first)
        let eventList = try GatewayAPI.decodeWorkJobEventsResponse([
            "work_profile_id": profileID,
            "cursor": 101,
            "events": [event],
        ])
        XCTAssertEqual(eventList.cursor, 101)
        XCTAssertEqual(eventList.events.map(\.eventID), [101])

        XCTAssertThrowsError(
            try GatewayAPI.decodeWorkJobListResponse(["jobs": [job]])
        ) { error in
            guard case .invalidResponse = error as? FabricWorkGatewayError else {
                return XCTFail("A list without a profile identity must fail closed")
            }
        }
    }

    func testSessionInfoRetainsOnlyAValidatedWorkProfileIdentity() throws {
        let profileID = "profile_11111111111111111111111111111111"
        let identity = try FabricWorkSessionIdentity(sessionInfo: ["work_profile_id": profileID])
        XCTAssertEqual(identity.profileID, profileID)
        XCTAssertEqual(identity.syncScope(gatewayID: "gateway-local")?.profileID, profileID)
        XCTAssertNil(identity.syncScope(gatewayID: "   "))

        let live = LiveSession(
            resumePayload: [
                "session_id": "runtime-1",
                "session_key": "stored-1",
                "info": ["work_profile_id": profileID],
            ],
            storedSessionId: "stored-1"
        )
        XCTAssertEqual(live.workIdentity, identity)
        XCTAssertNil(FabricWorkSessionIdentity.from(sessionInfo: [:]))
        XCTAssertNil(FabricWorkSessionIdentity.from(sessionInfo: ["work_profile_id": "profile-not-valid"]))
    }

    func testGatewayWorkRequestNeverMixesBootstrapAndDeltaFields() throws {
        let bootstrap = try FabricWorkSyncRequest.bootstrap.parameters(sessionID: "runtime-1")
        XCTAssertEqual(bootstrap["session_id"] as? String, "runtime-1")
        XCTAssertEqual(bootstrap["limit"] as? Int, 500)
        XCTAssertNil(bootstrap["ledger_id"])
        XCTAssertNil(bootstrap["after"])

        let delta = try FabricWorkSyncRequest.delta(
            ledgerID: "ledger_11111111111111111111111111111111",
            after: 100,
            limit: 50
        ).parameters(sessionID: "runtime-1")
        XCTAssertEqual(delta["ledger_id"] as? String, "ledger_11111111111111111111111111111111")
        XCTAssertEqual(delta["after"] as? Int, 100)
        XCTAssertNil(delta["page_token"])

        XCTAssertThrowsError(
            try FabricWorkSyncRequest.delta(ledgerID: "ledger", after: -1, limit: 500)
                .parameters(sessionID: "runtime-1")
        )
    }

    func testWorkContractDoesNotAdvertiseOrEnableWorkOnLegacyGateways() throws {
        let negotiation = GatewayCapabilitiesParser.parse(
            try fixtureValue("gateway-capabilities-v1.json")
        )
        guard case .verified(let capabilities) = negotiation else {
            return XCTFail("Expected canonical gateway capability contract")
        }
        XCTAssertEqual(capabilities.features["durable_work"], false)
        XCTAssertFalse(negotiation.supportsDurableWork)
        XCTAssertFalse(negotiation.supportsGatewayMethod("job.sync"))
        XCTAssertFalse(GatewayCapabilityNegotiation.legacy.supportsGatewayMethod("job.sync"))
        XCTAssertFalse(GatewayCapabilityNegotiation.legacy.supportsDurableWork)
    }

    func testDurableWorkGateRequiresExplicitFeatureAndCompleteMethodSet() throws {
        var payload = try fixtureObject("gateway-capabilities-v1.json")
        var methods = try XCTUnwrap(payload["methods"] as? [Any])
        methods.append(contentsOf: durableWorkGatewayMethods.sorted())
        payload["methods"] = methods
        var features = try XCTUnwrap(payload["features"] as? [String: Any])
        features["durable_work"] = true
        payload["features"] = features

        let enabled = GatewayCapabilitiesParser.parse(payload)
        XCTAssertTrue(enabled.supportsDurableWork)

        var missingMethod = payload
        missingMethod["methods"] = methods.filter { ($0 as? String) != "attention.respond" }
        guard case .invalid(let message) = GatewayCapabilitiesParser.parse(missingMethod) else {
            return XCTFail("Partial Work method set must be rejected")
        }
        XCTAssertTrue(message.contains("durable_work"))

        var disabledWithMethods = payload
        features["durable_work"] = false
        disabledWithMethods["features"] = features
        guard case .invalid = GatewayCapabilitiesParser.parse(disabledWithMethods) else {
            return XCTFail("False durable_work cannot conceal a complete Work method set")
        }
    }

    func testWorkGatewayWrapperFailsBeforeAnyLegacyTransportCall() async {
        let api = GatewayAPI(client: JsonRpcGatewayClient())
        do {
            _ = try await api.syncWork(
                sessionID: "runtime-1",
                request: .bootstrap,
                negotiation: .legacy
            )
            XCTFail("Legacy gateway must not issue a Work RPC")
        } catch {
            XCTAssertEqual(error as? FabricWorkGatewayError, .unavailableOnGateway)
        }
    }

    func testEveryWorkOperationFailsBeforeTransportWhenCapabilityIsAbsent() async throws {
        let api = GatewayAPI(client: JsonRpcGatewayClient())
        let jobID = "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        let sensitive = try fixtureObject("sensitive-attention.json")
        let sensitiveEvents = try XCTUnwrap(sensitive["events"] as? [[String: Any]])
        let rawAttention = try XCTUnwrap(sensitiveEvents.first?["subject"])
        let attention = try FabricWorkParser.decodeAttention(rawAttention)
        let unavailable = FabricWorkGatewayError.unavailableOnGateway

        func assertUnavailable<T>(_ operation: () async throws -> T) async {
            do {
                _ = try await operation()
                XCTFail("Work must not probe a legacy gateway")
            } catch {
                XCTAssertEqual(error as? FabricWorkGatewayError, unavailable)
            }
        }

        await assertUnavailable {
            try await api.createBackgroundWork(
                sessionID: "runtime-1",
                text: "prepare release notes",
                idempotencyKey: "mobile-create-key-0001",
                negotiation: .legacy
            )
        }
        await assertUnavailable {
            try await api.getWorkJob(sessionID: "runtime-1", jobID: jobID, negotiation: .legacy)
        }
        await assertUnavailable {
            try await api.listWorkJobs(sessionID: "runtime-1", negotiation: .legacy)
        }
        await assertUnavailable {
            try await api.listWorkEvents(sessionID: "runtime-1", after: 0, negotiation: .legacy)
        }
        await assertUnavailable {
            try await api.cancelWorkJob(
                sessionID: "runtime-1",
                jobID: jobID,
                expectedVersion: 1,
                idempotencyKey: "mobile-cancel-key-0001",
                negotiation: .legacy
            )
        }
        await assertUnavailable {
            try await api.getWorkAttention(
                sessionID: "runtime-1",
                attentionID: attention.attentionID,
                negotiation: .legacy
            )
        }
        await assertUnavailable {
            try await api.listWorkAttention(sessionID: "runtime-1", negotiation: .legacy)
        }
        await assertUnavailable {
            try await api.respondToWorkAttention(
                sessionID: "runtime-1",
                attention: attention,
                action: "submit",
                idempotencyKey: "mobile-attention-key-1",
                value: "sensitive value",
                negotiation: .legacy
            )
        }
    }

    func testWorkCreateRejectsAnOversizedPromptBeforeOpeningTransport() async throws {
        let api = GatewayAPI(client: JsonRpcGatewayClient())
        let negotiation = try durableWorkNegotiation()
        do {
            _ = try await api.createBackgroundWork(
                sessionID: "runtime-1",
                text: String(repeating: "x", count: 200_001),
                idempotencyKey: "mobile-create-key-0001",
                negotiation: negotiation
            )
            XCTFail("A prompt above the durable Work request cap must not be sent")
        } catch {
            guard case .invalidRequest(let message) = error as? FabricWorkGatewayError else {
                return XCTFail("Expected local request validation, received \(error)")
            }
            XCTAssertTrue(message.contains("200000"))
        }
    }

    private func bootstrappedProjection() throws -> FabricWorkProjection {
        let first = try FabricWorkProjectionReducer.apply(
            FabricWorkProjectionReducer.create(scope: scope),
            page: try verifiedPage("bootstrap-page-1.json"),
            context: FabricWorkSyncRequestContext(scope: scope)
        )
        return try FabricWorkProjectionReducer.apply(
            first,
            page: try verifiedPage("bootstrap-page-2.json"),
            context: FabricWorkSyncRequestContext(scope: scope, pageToken: first.nextPageToken)
        )
    }

    private func durableWorkNegotiation() throws -> GatewayCapabilityNegotiation {
        var payload = try fixtureObject("gateway-capabilities-v1.json")
        var methods = try XCTUnwrap(payload["methods"] as? [Any])
        methods.append(contentsOf: durableWorkGatewayMethods.sorted())
        payload["methods"] = methods
        var features = try XCTUnwrap(payload["features"] as? [String: Any])
        features["durable_work"] = true
        payload["features"] = features
        let negotiation = GatewayCapabilitiesParser.parse(payload)
        guard negotiation.supportsDurableWork else {
            throw FixtureError("Synthetic durable Work capability negotiation was invalid")
        }
        return negotiation
    }

    private func applyDelta(
        to state: FabricWorkProjection,
        fixture: String
    ) throws -> FabricWorkProjection {
        try FabricWorkProjectionReducer.apply(
            state,
            page: try verifiedPage(fixture),
            context: FabricWorkSyncRequestContext(scope: scope, after: state.cursor)
        )
    }

    private func verifiedPage(_ name: String) throws -> FabricWorkSyncPage {
        try verifiedPage(try fixtureValue(name))
    }

    private func verifiedPage(_ value: Any) throws -> FabricWorkSyncPage {
        switch FabricWorkParser.parseSyncPage(value) {
        case .verified(let page): return page
        case .incompatible(let minimum): throw FixtureError("Fixture is incompatible: \(minimum)")
        case .invalid(let message): throw FixtureError("Fixture is invalid: \(message)")
        }
    }

    private func verifiedReset(_ name: String) throws -> FabricWorkCursorReset {
        switch FabricWorkParser.parseCursorReset(try fixtureValue(name)) {
        case .verified(let reset): return reset
        case .invalid(let message): throw FixtureError("Reset is invalid: \(message)")
        }
    }

    private func fixtureObject(_ name: String) throws -> [String: Any] {
        try XCTUnwrap(try fixtureValue(name) as? [String: Any])
    }

    private func fixtureValue(_ name: String) throws -> Any {
        let fileURL = URL(fileURLWithPath: name)
        let fixtureURL = try XCTUnwrap(Bundle(for: Self.self).url(
            forResource: fileURL.deletingPathExtension().lastPathComponent,
            withExtension: fileURL.pathExtension
        ))
        return try JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL))
    }

    private struct FixtureError: Error, LocalizedError {
        let message: String

        init(_ message: String) { self.message = message }
        var errorDescription: String? { message }
    }
}
