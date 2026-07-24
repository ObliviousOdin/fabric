import Foundation
import XCTest
@testable import Fabric

final class WorkBoardPresentationTests: XCTestCase {
    private func attention(
        id: String,
        kind: String = "approval",
        state: String = "pending",
        blocking: Bool = true,
        sensitive: Bool = false,
        allowedActions: [String] = ["once", "deny"],
        canRespond: Bool = true
    ) -> FabricWorkInboxAttentionSummary {
        FabricWorkInboxAttentionSummary(
            id: id,
            version: 1,
            jobID: "job",
            kind: kind,
            state: state,
            title: "Attention \(id)",
            blocking: blocking,
            sensitive: sensitive,
            allowedActions: allowedActions,
            updatedAt: 1_784_451_600_000,
            canRespond: canRespond
        )
    }

    private func job(
        id: String,
        status: String,
        title: String = "Job",
        summary: String? = nil,
        attention: [FabricWorkInboxAttentionSummary] = [],
        hasResultPreview: Bool = false,
        hasErrorPreview: Bool = false,
        transcriptRoute: FabricWorkInboxTranscriptRoute? = nil,
        canCancel: Bool = false,
        updatedAt: Int = 1_784_451_600_000
    ) -> FabricWorkInboxJobSummary {
        FabricWorkInboxJobSummary(
            id: id,
            version: 1,
            kind: "background_prompt",
            status: status,
            title: title,
            summary: summary,
            openAttentionCount: attention.count,
            attemptCount: 1,
            createdAt: 1_784_451_000_000,
            startedAt: 1_784_451_100_000,
            updatedAt: updatedAt,
            finishedAt: nil,
            attention: attention,
            hasResultPreview: hasResultPreview,
            hasErrorPreview: hasErrorPreview,
            transcriptRoute: transcriptRoute,
            canCancel: canCancel
        )
    }

    // MARK: - Lane mapping

    func testSectionsMapToOrderedLanes() {
        var sections = FabricWorkInboxSections()
        sections.needsAttention = [job(id: "a", status: "waiting_attention")]
        sections.active = [job(id: "b", status: "running"), job(id: "c", status: "queued")]
        sections.completed = [job(id: "d", status: "succeeded")]

        let board = WorkBoardPresentation.make(from: sections)
        XCTAssertEqual(board.lanes.map(\.kind), [.needsAttention, .active, .done])
        XCTAssertEqual(board.lane(.needsAttention).cards.map(\.id), ["a"])
        XCTAssertEqual(board.lane(.active).cards.map(\.id), ["b", "c"])
        XCTAssertEqual(board.lane(.done).cards.map(\.id), ["d"])
    }

    func testUnsupportedCountSumsEveryUnsupportedCollection() {
        var sections = FabricWorkInboxSections()
        sections.unsupportedJobs = [job(id: "u1", status: "future_status")]
        sections.unsupportedAttention = [attention(id: "ua1", state: "resolving")]
        sections.unsupportedSubjects = [
            FabricWorkInboxUnsupportedSubject(id: "s1", subjectType: "mission", version: 1)
        ]
        let board = WorkBoardPresentation.make(from: sections)
        XCTAssertEqual(board.unsupportedCount, 3)
    }

    func testUnboundAttentionSurfacesSeparately() {
        var sections = FabricWorkInboxSections()
        sections.unboundAttention = [attention(id: "orphan", kind: "clarify")]
        let board = WorkBoardPresentation.make(from: sections)
        XCTAssertEqual(board.unboundAttention.map(\.id), ["orphan"])
        XCTAssertEqual(board.unboundAttention.first?.label, "Question")
    }

    // MARK: - Card projection

    func testCardTrimsBlankSummaryToNil() {
        let card = WorkCardPresentation(job: job(id: "j", status: "running", summary: "   "))
        XCTAssertNil(card.subtitle)
    }

    func testCardExposesOutcomeAvailabilityWithoutBodies() {
        let card = WorkCardPresentation(
            job: job(id: "j", status: "failed", hasErrorPreview: true)
        )
        XCTAssertTrue(card.hasErrorPreview)
        XCTAssertFalse(card.hasResultPreview)
    }

    func testCardCarriesTranscriptRouteAvailabilityOnly() {
        let routed = WorkCardPresentation(
            job: job(
                id: "j",
                status: "running",
                transcriptRoute: FabricWorkInboxTranscriptRoute(runtimeSessionID: "s")
            )
        )
        XCTAssertTrue(routed.hasTranscriptRoute)
    }

    // MARK: - Sensitive attention

    func testSensitiveAttentionBadgeCarriesNoPayload() {
        let badge = WorkAttentionBadge(summary: attention(id: "secret", kind: "secret", sensitive: true))
        // The badge type only carries id/label/blocking/sensitive — there is no
        // field that could leak a secret's public payload or value.
        XCTAssertEqual(badge.label, "Secret")
        XCTAssertTrue(badge.sensitive)
    }

    // MARK: - Status styling

    func testKnownStatusesMapToLabelAndTone() {
        XCTAssertEqual(WorkBoardPresentation.statusStyle(for: "running").tone, .running)
        XCTAssertEqual(WorkBoardPresentation.statusStyle(for: "waiting_attention").label, "Needs attention")
        XCTAssertEqual(WorkBoardPresentation.statusStyle(for: "succeeded").tone, .success)
        XCTAssertEqual(WorkBoardPresentation.statusStyle(for: "failed").tone, .failure)
        XCTAssertEqual(WorkBoardPresentation.statusStyle(for: "cancelled").tone, .cancelled)
    }

    func testUnknownStatusFallsBackToTitleCasedNeutral() {
        let style = WorkBoardPresentation.statusStyle(for: "future_state")
        XCTAssertEqual(style.label, "Future state")
        XCTAssertEqual(style.tone, .neutral)
    }

    func testAttentionLabelsAreHumanReadable() {
        XCTAssertEqual(WorkBoardPresentation.attentionLabel(for: "approval"), "Approval")
        XCTAssertEqual(WorkBoardPresentation.attentionLabel(for: "clarify"), "Question")
        XCTAssertEqual(WorkBoardPresentation.attentionLabel(for: "sudo"), "Admin access")
        XCTAssertEqual(WorkBoardPresentation.attentionLabel(for: "mystery_kind"), "Mystery kind")
    }

    // MARK: - Detail action messaging

    func testCancellationMessagesAreStable() {
        XCTAssertEqual(
            WorkJobDetailView.message(for: .requestAccepted(jobID: "j", version: 2, replayed: false)),
            "Cancellation requested."
        )
        XCTAssertEqual(
            WorkJobDetailView.message(for: .alreadyTerminal(jobID: "j", status: "succeeded", version: 3, replayed: false)),
            "This work already finished."
        )
    }

    func testAttentionResponseMessagesAreStable() {
        XCTAssertEqual(
            WorkJobDetailView.message(for: .delivered(attentionID: "a", version: 2, state: "resolved", replayed: false)),
            "Response sent."
        )
        XCTAssertEqual(WorkJobDetailView.message(for: FabricWorkInboxAttentionResult.outcomeUnknown), "Couldn't confirm the response. Pull to refresh.")
    }

    func testAttentionActionLabels() {
        XCTAssertEqual(WorkAttentionAction.label(for: "once"), "Allow once")
        XCTAssertEqual(WorkAttentionAction.label(for: "deny"), "Deny")
        XCTAssertEqual(WorkAttentionAction.label(for: "always"), "Always allow")
    }
}
