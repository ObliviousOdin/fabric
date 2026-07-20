import Foundation

/// Product-facing lifecycle derived from the durable `fabric.work` contract.
///
/// This type is intentionally narrower than the wire status enum. It gives
/// every native surface the same grouping semantics without letting a view
/// infer whether a future server status is safe to act on.
enum FabricGoalStage: String, Equatable {
    case queued
    case running
    case needsAttention
    case succeeded
    case failed
    case cancelled
    case interrupted
    case unsupported

    var isOutcome: Bool {
        switch self {
        case .succeeded, .failed, .cancelled, .interrupted:
            return true
        case .queued, .running, .needsAttention, .unsupported:
            return false
        }
    }
}

/// Bounded Attention metadata that can safely appear in a goal list. The
/// public payload and any submitted value deliberately remain behind the
/// detail/action boundary.
struct FabricGoalAttentionSnapshot: Identifiable, Equatable {
    let id: String
    let version: Int
    let jobID: String?
    let kind: String
    let state: String
    let title: String
    let blocking: Bool
    let sensitive: Bool
    let allowedActions: [String]
    let updatedAt: Int
    let actionable: Bool
}

/// Outcome availability, not outcome body. Result/error payloads stay in the
/// bounded `job.get` detail path and are fetched only after deliberate user
/// navigation.
struct FabricGoalOutcomeSnapshot: Equatable {
    let status: String
    let summary: String?
    let finishedAt: Int?
    let hasResultPreview: Bool
    let resultReference: String?
    let resultOmittedReason: String?
    let hasErrorPreview: Bool
}

/// One durable Work Job projected into the shared mobile product vocabulary.
/// Raw status and kind are retained for honest diagnostics; `stage` and the
/// action booleans fail closed for compatible future enum values.
struct FabricGoalSnapshot: Identifiable, Equatable {
    let id: String
    let version: Int
    let title: String
    let summary: String?
    let kind: String
    let rawStatus: String
    let source: String
    let stage: FabricGoalStage
    let attention: [FabricGoalAttentionSnapshot]
    let openAttentionCount: Int
    let attemptCount: Int
    let createdAt: Int
    let startedAt: Int?
    let updatedAt: Int
    let outcome: FabricGoalOutcomeSnapshot?
    /// Local navigation is always safe, including for a compatible future Job.
    /// Server mutations remain separately fail-closed through `canCancel`.
    let canInspect: Bool
    let canCancel: Bool
}

/// Shared collection model for conversation-first home, mission control, and
/// Dispatch inbox directions. A Job appears in exactly one section, while
/// open Attention not represented by a needs-attention Job remains visible
/// separately instead of being silently discarded.
struct FabricGoalPortfolio: Equatable {
    let syncPhase: FabricWorkProjectionPhase
    let needsAttention: [FabricGoalSnapshot]
    let active: [FabricGoalSnapshot]
    let outcomes: [FabricGoalSnapshot]
    let unsupported: [FabricGoalSnapshot]
    let unboundAttention: [FabricGoalAttentionSnapshot]

    var isCurrent: Bool { syncPhase == .current }

    var isEmpty: Bool {
        needsAttention.isEmpty
            && active.isEmpty
            && outcomes.isEmpty
            && unsupported.isEmpty
            && unboundAttention.isEmpty
    }

    init(projection: FabricWorkProjection) {
        syncPhase = projection.phase
        let openAttention = projection.attention.values
            .filter(Self.isOpenAttention)
            .map(Self.makeAttention)
            .sorted(by: Self.attentionComesFirst)
        let attentionByJob = Dictionary(grouping: openAttention.compactMap { item in
            item.jobID.map { ($0, item) }
        }, by: { $0.0 })
            .mapValues { rows in rows.map { $0.1 } }

        let jobs = projection.jobs.values.map { job in
            Self.makeGoal(job, attention: attentionByJob[job.jobID] ?? [])
        }
        let goalsByID = Dictionary(uniqueKeysWithValues: jobs.map { ($0.id, $0) })

        needsAttention = jobs
            .filter { $0.stage == .needsAttention }
            .sorted(by: Self.goalComesFirst)
        active = jobs
            .filter { $0.stage == .queued || $0.stage == .running }
            .sorted(by: Self.goalComesFirst)
        outcomes = jobs
            .filter { $0.stage.isOutcome }
            .sorted(by: Self.outcomeComesFirst)
        unsupported = jobs
            .filter { $0.stage == .unsupported }
            .sorted(by: Self.goalComesFirst)
        unboundAttention = openAttention.filter { item in
            guard let jobID = item.jobID else { return true }
            guard let goal = goalsByID[jobID] else { return true }
            return goal.stage != .needsAttention
        }
    }

    private static func makeGoal(
        _ job: FabricWorkJobSummary,
        attention: [FabricGoalAttentionSnapshot]
    ) -> FabricGoalSnapshot {
        let stage = goalStage(for: job, attention: attention)
        let supportsKnownActions = job.kind == "background_prompt" && job.actionable
        let canCancel = supportsKnownActions && [
            "queued",
            "claimed",
            "running",
            "waiting_attention",
        ].contains(job.status)
        let outcome = stage.isOutcome
            ? FabricGoalOutcomeSnapshot(
                status: job.status,
                summary: job.summary,
                finishedAt: job.finishedAt,
                hasResultPreview: !job.resultPreview.isNull,
                resultReference: job.resultReference,
                resultOmittedReason: job.resultOmittedReason,
                hasErrorPreview: !job.error.isNull
            )
            : nil

        return FabricGoalSnapshot(
            id: job.jobID,
            version: job.version,
            title: job.title,
            summary: job.summary,
            kind: job.kind,
            rawStatus: job.status,
            source: job.source,
            stage: stage,
            attention: stage == .needsAttention ? attention : [],
            openAttentionCount: job.openAttentionCount,
            attemptCount: job.attemptCount,
            createdAt: job.createdAt,
            startedAt: job.startedAt,
            updatedAt: job.updatedAt,
            outcome: outcome,
            canInspect: true,
            canCancel: canCancel
        )
    }

    private static func goalStage(
        for job: FabricWorkJobSummary,
        attention: [FabricGoalAttentionSnapshot]
    ) -> FabricGoalStage {
        guard job.kind == "background_prompt", job.actionable else {
            return .unsupported
        }

        switch job.status {
        case "succeeded": return .succeeded
        case "failed": return .failed
        case "cancelled": return .cancelled
        case "interrupted": return .interrupted
        case "waiting_attention": return .needsAttention
        case "queued", "claimed":
            return job.openAttentionCount > 0 || attention.contains(where: \.actionable)
                ? .needsAttention
                : .queued
        case "running", "cancel_requested":
            return job.openAttentionCount > 0 || attention.contains(where: \.actionable)
                ? .needsAttention
                : .running
        default:
            return .unsupported
        }
    }

    private static func isOpenAttention(_ attention: FabricWorkAttention) -> Bool {
        attention.state == "pending" || attention.state == "resolving"
    }

    private static func makeAttention(
        _ attention: FabricWorkAttention
    ) -> FabricGoalAttentionSnapshot {
        FabricGoalAttentionSnapshot(
            id: attention.attentionID,
            version: attention.version,
            jobID: attention.jobID,
            kind: attention.kind,
            state: attention.state,
            title: attention.title,
            blocking: attention.blocking,
            sensitive: attention.sensitive,
            allowedActions: attention.allowedActions,
            updatedAt: attention.updatedAt,
            actionable: attention.actionable && attention.state == "pending"
        )
    }

    private static func goalComesFirst(
        _ lhs: FabricGoalSnapshot,
        _ rhs: FabricGoalSnapshot
    ) -> Bool {
        if lhs.updatedAt != rhs.updatedAt { return lhs.updatedAt > rhs.updatedAt }
        return lhs.id < rhs.id
    }

    private static func outcomeComesFirst(
        _ lhs: FabricGoalSnapshot,
        _ rhs: FabricGoalSnapshot
    ) -> Bool {
        let lhsTime = lhs.outcome?.finishedAt ?? lhs.updatedAt
        let rhsTime = rhs.outcome?.finishedAt ?? rhs.updatedAt
        if lhsTime != rhsTime { return lhsTime > rhsTime }
        return lhs.id < rhs.id
    }

    private static func attentionComesFirst(
        _ lhs: FabricGoalAttentionSnapshot,
        _ rhs: FabricGoalAttentionSnapshot
    ) -> Bool {
        if lhs.blocking != rhs.blocking { return lhs.blocking }
        if lhs.updatedAt != rhs.updatedAt { return lhs.updatedAt > rhs.updatedAt }
        return lhs.id < rhs.id
    }
}

extension FabricWorkJSONValue {
    fileprivate var isNull: Bool {
        if case .null = self { return true }
        return false
    }
}
