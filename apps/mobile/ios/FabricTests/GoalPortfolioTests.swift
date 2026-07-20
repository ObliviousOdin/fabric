import XCTest
@testable import Fabric

final class GoalPortfolioTests: XCTestCase {
    func testPortfolioBuildsMutuallyExclusiveAttentionActiveAndOutcomeSections() {
        let attentionJob = makeJob(
            id: workID("job", 1),
            status: "running",
            updatedAt: 30,
            openAttentionCount: 1
        )
        let activeJob = makeJob(
            id: workID("job", 2),
            status: "running",
            updatedAt: 20
        )
        let completeJob = makeJob(
            id: workID("job", 3),
            status: "succeeded",
            updatedAt: 10,
            finishedAt: 12
        )
        let attention = makeAttention(
            id: workID("attn", 1),
            jobID: attentionJob.jobID,
            updatedAt: 31
        )

        let portfolio = FabricGoalPortfolio(projection: makeProjection(
            jobs: [attentionJob, activeJob, completeJob],
            attention: [attention]
        ))

        XCTAssertEqual(portfolio.needsAttention.map(\.id), [attentionJob.jobID])
        XCTAssertEqual(portfolio.active.map(\.id), [activeJob.jobID])
        XCTAssertEqual(portfolio.outcomes.map(\.id), [completeJob.jobID])
        XCTAssertTrue(portfolio.unsupported.isEmpty)
        XCTAssertTrue(portfolio.unboundAttention.isEmpty)
        XCTAssertEqual(portfolio.needsAttention.first?.attention.map(\.id), [attention.attentionID])
    }

    func testFutureJobEnumFailsClosedIntoUnsupportedSection() {
        let future = makeJob(
            id: workID("job", 4),
            status: "teleporting",
            updatedAt: 40,
            actionable: false
        )

        let portfolio = FabricGoalPortfolio(projection: makeProjection(jobs: [future]))

        XCTAssertEqual(portfolio.unsupported.map(\.id), [future.jobID])
        XCTAssertEqual(portfolio.unsupported.first?.stage, .unsupported)
        XCTAssertEqual(portfolio.unsupported.first?.rawStatus, "teleporting")
        XCTAssertEqual(portfolio.unsupported.first?.canInspect, true)
        XCTAssertEqual(portfolio.unsupported.first?.canCancel, false)
    }

    func testUnknownJobKindCannotBecomeAnActionableGoal() {
        let future = makeJob(
            id: workID("job", 5),
            kind: "scheduled_recipe",
            status: "running",
            updatedAt: 50,
            actionable: false
        )

        let portfolio = FabricGoalPortfolio(projection: makeProjection(jobs: [future]))

        XCTAssertEqual(portfolio.unsupported.map(\.id), [future.jobID])
        XCTAssertTrue(try! XCTUnwrap(portfolio.unsupported.first).canInspect)
    }

    func testSensitiveAndUnboundAttentionRemainsVisibleWithoutPayload() {
        let attention = makeAttention(
            id: workID("attn", 2),
            jobID: nil,
            kind: "secret",
            title: "Credential requested",
            sensitive: true,
            updatedAt: 60
        )

        let portfolio = FabricGoalPortfolio(projection: makeProjection(attention: [attention]))

        let projected = try! XCTUnwrap(portfolio.unboundAttention.first)
        XCTAssertEqual(projected.id, attention.attentionID)
        XCTAssertEqual(projected.title, "Credential requested")
        XCTAssertTrue(projected.sensitive)
        XCTAssertTrue(projected.actionable)
    }

    func testAuthoritativeOpenAttentionCountPreventsActiveMisclassification() {
        let waiting = makeJob(
            id: workID("job", 11),
            status: "running",
            updatedAt: 61,
            openAttentionCount: 1
        )

        let portfolio = FabricGoalPortfolio(projection: makeProjection(jobs: [waiting]))

        XCTAssertEqual(portfolio.needsAttention.map(\.id), [waiting.jobID])
        XCTAssertTrue(portfolio.active.isEmpty)
        XCTAssertTrue(try! XCTUnwrap(portfolio.needsAttention.first).canCancel)
    }

    func testOutcomeExposesAvailabilityButKeepsBodiesBehindDetailFetch() {
        let completed = makeJob(
            id: workID("job", 6),
            status: "succeeded",
            updatedAt: 70,
            finishedAt: 72,
            resultPreview: .object(["secret": .string("redacted-preview")]),
            resultReference: "artifact://result",
            error: .null
        )

        let portfolio = FabricGoalPortfolio(projection: makeProjection(jobs: [completed]))

        let outcome = try! XCTUnwrap(portfolio.outcomes.first?.outcome)
        XCTAssertEqual(outcome.status, "succeeded")
        XCTAssertTrue(outcome.hasResultPreview)
        XCTAssertEqual(outcome.resultReference, "artifact://result")
        XCTAssertFalse(outcome.hasErrorPreview)
    }

    func testCancelRequestedStaysActiveButCannotBeCancelledAgain() {
        let cancelling = makeJob(
            id: workID("job", 7),
            status: "cancel_requested",
            updatedAt: 80
        )

        let portfolio = FabricGoalPortfolio(projection: makeProjection(jobs: [cancelling]))

        let goal = try! XCTUnwrap(portfolio.active.first)
        XCTAssertEqual(goal.stage, .running)
        XCTAssertFalse(goal.canCancel)
    }

    func testOrderingUsesNewestActivityThenStableIdentifier() {
        let older = makeJob(id: workID("job", 8), status: "running", updatedAt: 10)
        let newestB = makeJob(id: workID("job", 10), status: "running", updatedAt: 20)
        let newestA = makeJob(id: workID("job", 9), status: "running", updatedAt: 20)

        let portfolio = FabricGoalPortfolio(projection: makeProjection(
            jobs: [newestB, older, newestA]
        ))

        XCTAssertEqual(portfolio.active.map(\.id), [newestA.jobID, newestB.jobID, older.jobID])
    }

    func testPortfolioCarriesSyncFreshnessWithoutInventingContent() {
        let portfolio = FabricGoalPortfolio(projection: makeProjection(phase: .bootstrapping))

        XCTAssertEqual(portfolio.syncPhase, .bootstrapping)
        XCTAssertFalse(portfolio.isCurrent)
        XCTAssertTrue(portfolio.isEmpty)
    }

    private func makeProjection(
        phase: FabricWorkProjectionPhase = .current,
        jobs: [FabricWorkJobSummary] = [],
        attention: [FabricWorkAttention] = []
    ) -> FabricWorkProjection {
        FabricWorkProjection(
            gatewayID: "gateway-1",
            profileID: workID("profile", 1),
            ledgerID: workID("ledger", 1),
            cursor: 1,
            watermark: 1,
            phase: phase,
            nextPageToken: nil,
            resetLedgerHint: nil,
            jobs: Dictionary(uniqueKeysWithValues: jobs.map { ($0.jobID, $0) }),
            attention: Dictionary(uniqueKeysWithValues: attention.map { ($0.attentionID, $0) }),
            unknownSubjects: [:],
            subjectVersions: [:]
        )
    }

    private func makeJob(
        id: String,
        kind: String = "background_prompt",
        status: String,
        updatedAt: Int,
        finishedAt: Int? = nil,
        openAttentionCount: Int = 0,
        actionable: Bool = true,
        resultPreview: FabricWorkJSONValue = .null,
        resultReference: String? = nil,
        error: FabricWorkJSONValue = .null
    ) -> FabricWorkJobSummary {
        FabricWorkJobSummary(
            jobID: id,
            version: 1,
            kind: kind,
            status: status,
            title: "Goal \(id.suffix(2))",
            summary: "A bounded summary",
            source: "mobile",
            sourceSessionKey: "session-key",
            runtimeSessionID: "runtime-session",
            attemptCount: 1,
            openAttentionCount: openAttentionCount,
            createdAt: 1,
            startedAt: status == "queued" ? nil : 2,
            updatedAt: updatedAt,
            finishedAt: finishedAt,
            cancelRequestedAt: status == "cancel_requested" ? updatedAt : nil,
            runtime: [:],
            currentRun: nil,
            resultPreview: resultPreview,
            resultReference: resultReference,
            resultOmittedReason: nil,
            error: error,
            actionable: actionable,
            unknownEnums: []
        )
    }

    private func makeAttention(
        id: String,
        jobID: String?,
        kind: String = "approval",
        title: String = "Approval required",
        sensitive: Bool = false,
        updatedAt: Int
    ) -> FabricWorkAttention {
        FabricWorkAttention(
            attentionID: id,
            version: 1,
            jobID: jobID,
            runID: nil,
            sourceSessionKey: "session-key",
            runtimeSessionID: "runtime-session",
            requestID: "request-1",
            kind: kind,
            state: "pending",
            blocking: true,
            sensitive: sensitive,
            title: title,
            publicPayload: ["redacted": .string("value")],
            allowedActions: kind == "approval" ? ["once", "deny"] : ["submit", "cancel"],
            createdAt: 1,
            updatedAt: updatedAt,
            expiresAt: nil,
            resolvedAt: nil,
            terminalReason: nil,
            actionable: true,
            unknownEnums: []
        )
    }

    private func workID(_ prefix: String, _ value: Int) -> String {
        "\(prefix)_\(String(format: "%032x", value))"
    }
}
