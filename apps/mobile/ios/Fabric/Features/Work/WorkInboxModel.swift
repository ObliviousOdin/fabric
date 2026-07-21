import Foundation
import Observation

/// The already-typed Durable Work transport used by the hidden inbox model.
/// Keeping this seam on the existing wrappers prevents a second raw JSON-RPC
/// implementation from drifting away from the reviewed contract.
@MainActor
protocol FabricWorkInboxGateway {
    func syncWork(
        sessionID: String,
        request: FabricWorkSyncRequest,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkGatewayResponse

    func cancelWorkJob(
        sessionID: String,
        jobID: String,
        expectedVersion: Int,
        idempotencyKey: String,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkJobMutationReceipt

    func respondToWorkAttention(
        sessionID: String,
        attention: FabricWorkAttention,
        action: String,
        idempotencyKey: String,
        reason: String?,
        value: String?,
        negotiation: GatewayCapabilityNegotiation
    ) async throws -> FabricWorkAttentionMutationReceipt
}

extension GatewayAPI: FabricWorkInboxGateway {}

/// Exact authority for one inbox snapshot. The profile identity comes from
/// `session.info`; a display profile name can never construct this context.
struct FabricWorkInboxContext: Equatable, Hashable {
    let gatewayID: String
    let profileID: String
    let runtimeSessionID: String
    let connectionGeneration: Int

    init?(
        gatewayID: String,
        runtimeSessionID: String,
        workIdentity: FabricWorkSessionIdentity,
        connectionGeneration: Int
    ) {
        let gatewayID = gatewayID.trimmingCharacters(in: .whitespacesAndNewlines)
        let runtimeSessionID = runtimeSessionID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !gatewayID.isEmpty, !runtimeSessionID.isEmpty else { return nil }
        self.gatewayID = gatewayID
        profileID = workIdentity.profileID
        self.runtimeSessionID = runtimeSessionID
        self.connectionGeneration = connectionGeneration
    }

    var scope: FabricWorkSyncScope {
        FabricWorkSyncScope(gatewayID: gatewayID, profileID: profileID)
    }

    fileprivate func hasSameAuthority(as other: FabricWorkInboxContext) -> Bool {
        gatewayID == other.gatewayID
            && profileID == other.profileID
            && runtimeSessionID == other.runtimeSessionID
    }
}

enum FabricWorkInboxAvailability: Equatable {
    case unavailable
    case empty
    case syncing
    case current
    case stale
}

/// A route is emitted only for the exact `session:<runtime_session_id>` value
/// carried by the typed Job. Other reference schemes remain non-navigable.
struct FabricWorkInboxTranscriptRoute: Equatable {
    let runtimeSessionID: String
}

/// Bounded Attention metadata for list state. `publicPayload`, `requestID`,
/// and any submitted value intentionally never enter this type.
struct FabricWorkInboxAttentionSummary: Identifiable, Equatable {
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
    let canRespond: Bool
}

/// Summary-only Job state. Result and error bodies stay behind `job.get`;
/// this model publishes only their availability and an exact transcript route.
struct FabricWorkInboxJobSummary: Identifiable, Equatable {
    let id: String
    let version: Int
    let kind: String
    let status: String
    let title: String
    let summary: String?
    let openAttentionCount: Int
    let attemptCount: Int
    let createdAt: Int
    let startedAt: Int?
    let updatedAt: Int
    let finishedAt: Int?
    let attention: [FabricWorkInboxAttentionSummary]
    let hasResultPreview: Bool
    let hasErrorPreview: Bool
    let transcriptRoute: FabricWorkInboxTranscriptRoute?
    let canCancel: Bool
}

/// Compatible future subject types stay discoverable without copying their
/// raw object into app state or exposing a mutation surface.
struct FabricWorkInboxUnsupportedSubject: Identifiable, Equatable {
    let id: String
    let subjectType: String
    let version: Int
}

struct FabricWorkInboxSections: Equatable {
    var needsAttention: [FabricWorkInboxJobSummary] = []
    var active: [FabricWorkInboxJobSummary] = []
    var completed: [FabricWorkInboxJobSummary] = []
    var unsupportedJobs: [FabricWorkInboxJobSummary] = []
    var unboundAttention: [FabricWorkInboxAttentionSummary] = []
    var unsupportedAttention: [FabricWorkInboxAttentionSummary] = []
    var unsupportedSubjects: [FabricWorkInboxUnsupportedSubject] = []

    var isEmpty: Bool {
        needsAttention.isEmpty
            && active.isEmpty
            && completed.isEmpty
            && unsupportedJobs.isEmpty
            && unboundAttention.isEmpty
            && unsupportedAttention.isEmpty
            && unsupportedSubjects.isEmpty
    }
}

enum FabricWorkInboxAttentionResult: Equatable {
    case delivered(attentionID: String, version: Int, state: String, replayed: Bool)
    case unavailable
    case invalidState
    case reconciliationRequired
    case outcomeUnknown
    case stale
}

/// A successful cancellation RPC acknowledges a request, not final process
/// termination. The terminal case is reserved for a receipt whose Job was
/// already in an authoritative terminal state.
enum FabricWorkInboxCancellationResult: Equatable {
    case requestAccepted(jobID: String, version: Int, replayed: Bool)
    case alreadyTerminal(jobID: String, status: String, version: Int, replayed: Bool)
    case unavailable
    case invalidState
    case reconciliationRequired
    case outcomeUnknown
    case stale
}

/// Hidden summary-first Durable Work store. No view or navigation root owns
/// this model yet, and every entry point fails closed unless the complete
/// optional capability was explicitly negotiated.
@Observable
@MainActor
final class WorkInboxModel {
    private(set) var sections = FabricWorkInboxSections()
    private(set) var availability: FabricWorkInboxAvailability = .unavailable
    private(set) var isRefreshing = false
    private(set) var syncError: String?
    private(set) var lastUpdated: Date?

    private var context: FabricWorkInboxContext?
    private var projection: FabricWorkProjection?
    private var refreshGeneration = 0
    private var operationGeneration = 0
    private var cancellationMutations: [String: CancellationMutation] = [:]
    private var attentionMutations: [String: AttentionMutation] = [:]
    private let makeIdempotencyKey: () -> String

    private enum MutationState: Equatable {
        case inFlight
        case outcomeUnknown
        case acknowledged(version: Int)
    }

    private struct CancellationMutation: Equatable {
        let jobID: String
        let expectedVersion: Int
        let idempotencyKey: String
        var state: MutationState
    }

    private struct AttentionMutation: Equatable {
        let attentionID: String
        let expectedVersion: Int
        let idempotencyKey: String
        var state: MutationState
    }

    private enum LocalFailure: Error {
        case pageLimit
        case invalidReceipt
    }

    init(makeIdempotencyKey: @escaping () -> String = { UUID().uuidString }) {
        self.makeIdempotencyKey = makeIdempotencyKey
    }

    /// Reconcile from the durable cursor. A reconnect with the same authority
    /// retains the current projection and asks for a delta; a different
    /// gateway, profile, or runtime session starts from an empty namespace.
    func refresh(
        using gateway: any FabricWorkInboxGateway,
        context requestedContext: FabricWorkInboxContext,
        negotiation: GatewayCapabilityNegotiation
    ) async {
        guard negotiation.supportsDurableWork else {
            becomeUnavailable()
            return
        }

        adopt(requestedContext)
        refreshGeneration += 1
        let generation = refreshGeneration
        isRefreshing = true
        syncError = nil
        availability = .syncing

        do {
            var state: FabricWorkProjection
            if let projection,
               projection.gatewayID == requestedContext.gatewayID,
               projection.profileID == requestedContext.profileID {
                state = projection
            } else {
                state = try FabricWorkProjectionReducer.create(scope: requestedContext.scope)
            }

            var pageCount = 0
            while pageCount < 1_000 {
                pageCount += 1
                let request: FabricWorkSyncRequest
                let applyContext: FabricWorkSyncRequestContext

                switch state.phase {
                case .empty, .bootstrapping:
                    let token = state.nextPageToken
                    request = .bootstrap(pageToken: token, limit: FabricWorkLimits.syncPageItems)
                    applyContext = FabricWorkSyncRequestContext(
                        scope: requestedContext.scope,
                        pageToken: token
                    )
                case .syncing, .current:
                    guard let ledgerID = state.ledgerID, let cursor = state.cursor else {
                        state = try FabricWorkProjectionReducer.create(scope: requestedContext.scope)
                        continue
                    }
                    request = .delta(
                        ledgerID: ledgerID,
                        after: cursor,
                        limit: FabricWorkLimits.syncPageItems
                    )
                    applyContext = FabricWorkSyncRequestContext(
                        scope: requestedContext.scope,
                        after: cursor
                    )
                }

                let response = try await gateway.syncWork(
                    sessionID: requestedContext.runtimeSessionID,
                    request: request,
                    negotiation: negotiation
                )
                guard isCurrentRefresh(generation, context: requestedContext) else {
                    finishCancelledRefreshIfCurrent(generation, context: requestedContext)
                    return
                }

                switch response {
                case .page(let page):
                    state = try FabricWorkProjectionReducer.apply(
                        state,
                        page: page,
                        context: applyContext
                    )
                    if state.phase == .current {
                        publish(state)
                        isRefreshing = false
                        availability = .current
                        syncError = nil
                        lastUpdated = Date()
                        return
                    }

                case .reset(let reset):
                    state = try FabricWorkProjectionReducer.applyCursorReset(
                        state,
                        reset: reset,
                        scope: requestedContext.scope
                    )
                    // The reset is authoritative even if the following
                    // bootstrap fails. Do not keep displaying the old ledger.
                    publish(state)
                    lastUpdated = nil
                    availability = .syncing
                }
            }
            throw LocalFailure.pageLimit
        } catch {
            guard refreshGeneration == generation, context == requestedContext else { return }
            if Task.isCancelled {
                finishCancelledRefreshIfCurrent(generation, context: requestedContext)
                return
            }
            isRefreshing = false
            availability = projection?.phase == .current ? .stale : .empty
            // Transport and parser details can contain server-local context.
            // The model publishes fixed copy and never persists the raw error.
            syncError = "Work could not be refreshed."
        }
    }

    /// Resolve one exact current Attention version. The submitted value is a
    /// request-local argument passed directly to the typed wrapper and is never
    /// retained for retry, logging, or list projection.
    func respondToAttention(
        _ attentionID: String,
        action: String,
        reason: String? = nil,
        value: String? = nil,
        using gateway: any FabricWorkInboxGateway,
        context requestedContext: FabricWorkInboxContext,
        negotiation: GatewayCapabilityNegotiation
    ) async -> FabricWorkInboxAttentionResult {
        guard negotiation.supportsDurableWork else { return .unavailable }
        guard context == requestedContext,
              let attention = projection?.attention[attentionID],
              attention.actionable,
              attention.state == "pending",
              attention.allowedActions.contains(action)
        else { return .invalidState }
        guard attentionMutations[attentionID] == nil else {
            return .reconciliationRequired
        }

        let mutation = AttentionMutation(
            attentionID: attentionID,
            expectedVersion: attention.version,
            idempotencyKey: makeIdempotencyKey(),
            state: .inFlight
        )
        attentionMutations[attentionID] = mutation
        rebuildSections()
        let generation = operationGeneration

        do {
            let receipt = try await gateway.respondToWorkAttention(
                sessionID: requestedContext.runtimeSessionID,
                attention: attention,
                action: action,
                idempotencyKey: mutation.idempotencyKey,
                reason: reason,
                value: value,
                negotiation: negotiation
            )
            guard isCurrentOperation(generation, context: requestedContext),
                  !Task.isCancelled,
                  attentionMutations[attentionID]?.idempotencyKey == mutation.idempotencyKey
            else {
                markAttentionOutcomeUnknown(mutation)
                return .stale
            }
            guard receipt.attentionID == attentionID,
                  receipt.attentionVersion > attention.version,
                  receipt.delivered,
                  receipt.state == (action == "deny" || action == "cancel" ? "denied" : "resolved")
            else { throw LocalFailure.invalidReceipt }

            attentionMutations[attentionID]?.state = .acknowledged(
                version: receipt.attentionVersion
            )
            rebuildSections()
            return .delivered(
                attentionID: receipt.attentionID,
                version: receipt.attentionVersion,
                state: receipt.state,
                replayed: receipt.replayed
            )
        } catch {
            guard isCurrentOperation(generation, context: requestedContext) else {
                return .stale
            }
            if Self.isDefinitelyUnsent(error) {
                if attentionMutations[attentionID]?.idempotencyKey == mutation.idempotencyKey {
                    attentionMutations.removeValue(forKey: attentionID)
                    rebuildSections()
                }
                return .invalidState
            }
            markAttentionOutcomeUnknown(mutation)
            return .outcomeUnknown
        }
    }

    /// Send a version-bound cancellation request once. An unknown transport
    /// outcome retains its exact idempotency key and blocks a new mutation.
    func requestCancellation(
        for jobID: String,
        using gateway: any FabricWorkInboxGateway,
        context requestedContext: FabricWorkInboxContext,
        negotiation: GatewayCapabilityNegotiation
    ) async -> FabricWorkInboxCancellationResult {
        guard negotiation.supportsDurableWork else { return .unavailable }
        guard context == requestedContext,
              let job = projection?.jobs[jobID],
              Self.canCancel(job)
        else { return .invalidState }
        guard cancellationMutations[jobID] == nil else {
            return .reconciliationRequired
        }

        let mutation = CancellationMutation(
            jobID: jobID,
            expectedVersion: job.version,
            idempotencyKey: makeIdempotencyKey(),
            state: .inFlight
        )
        cancellationMutations[jobID] = mutation
        rebuildSections()
        return await executeCancellation(
            mutation,
            using: gateway,
            context: requestedContext,
            negotiation: negotiation
        )
    }

    /// The only retry path reuses the original key and version. Callers cannot
    /// accidentally create a second cancellation mutation after a timeout.
    func retryCancellation(
        for jobID: String,
        using gateway: any FabricWorkInboxGateway,
        context requestedContext: FabricWorkInboxContext,
        negotiation: GatewayCapabilityNegotiation
    ) async -> FabricWorkInboxCancellationResult {
        guard negotiation.supportsDurableWork else { return .unavailable }
        guard context == requestedContext,
              var mutation = cancellationMutations[jobID],
              mutation.state == .outcomeUnknown,
              let job = projection?.jobs[jobID],
              job.version == mutation.expectedVersion,
              Self.canCancel(job)
        else { return .reconciliationRequired }

        mutation.state = .inFlight
        cancellationMutations[jobID] = mutation
        rebuildSections()
        return await executeCancellation(
            mutation,
            using: gateway,
            context: requestedContext,
            negotiation: negotiation
        )
    }

    func transcriptRoute(for jobID: String) -> FabricWorkInboxTranscriptRoute? {
        guard let job = projection?.jobs[jobID] else { return nil }
        return Self.transcriptRoute(for: job)
    }

    func invalidate() {
        refreshGeneration += 1
        operationGeneration += 1
        context = nil
        projection = nil
        cancellationMutations.removeAll()
        attentionMutations.removeAll()
        sections = FabricWorkInboxSections()
        availability = .unavailable
        isRefreshing = false
        syncError = nil
        lastUpdated = nil
    }

    private func executeCancellation(
        _ mutation: CancellationMutation,
        using gateway: any FabricWorkInboxGateway,
        context requestedContext: FabricWorkInboxContext,
        negotiation: GatewayCapabilityNegotiation
    ) async -> FabricWorkInboxCancellationResult {
        let generation = operationGeneration
        do {
            let receipt = try await gateway.cancelWorkJob(
                sessionID: requestedContext.runtimeSessionID,
                jobID: mutation.jobID,
                expectedVersion: mutation.expectedVersion,
                idempotencyKey: mutation.idempotencyKey,
                negotiation: negotiation
            )
            guard isCurrentOperation(generation, context: requestedContext),
                  !Task.isCancelled,
                  cancellationMutations[mutation.jobID]?.idempotencyKey == mutation.idempotencyKey
            else {
                markCancellationOutcomeUnknown(mutation)
                return .stale
            }
            guard receipt.job.jobID == mutation.jobID,
                  let newlyCancelled = receipt.newlyCancelled
            else { throw LocalFailure.invalidReceipt }

            if newlyCancelled {
                guard receipt.job.version > mutation.expectedVersion,
                      receipt.job.status == "cancel_requested"
                else { throw LocalFailure.invalidReceipt }
            } else {
                guard Self.terminalStatuses.contains(receipt.job.status),
                      receipt.job.version >= mutation.expectedVersion
                else { throw LocalFailure.invalidReceipt }
            }

            cancellationMutations[mutation.jobID]?.state = .acknowledged(
                version: receipt.job.version
            )
            rebuildSections()
            if newlyCancelled {
                return .requestAccepted(
                    jobID: mutation.jobID,
                    version: receipt.job.version,
                    replayed: receipt.replayed
                )
            }
            return .alreadyTerminal(
                jobID: mutation.jobID,
                status: receipt.job.status,
                version: receipt.job.version,
                replayed: receipt.replayed
            )
        } catch {
            guard isCurrentOperation(generation, context: requestedContext) else {
                return .stale
            }
            if Self.isDefinitelyUnsent(error) {
                if cancellationMutations[mutation.jobID]?.idempotencyKey == mutation.idempotencyKey {
                    cancellationMutations.removeValue(forKey: mutation.jobID)
                    rebuildSections()
                }
                return .invalidState
            }
            markCancellationOutcomeUnknown(mutation)
            return .outcomeUnknown
        }
    }

    private func adopt(_ requestedContext: FabricWorkInboxContext) {
        guard context != requestedContext else { return }
        refreshGeneration += 1
        operationGeneration += 1

        if let context, context.hasSameAuthority(as: requestedContext) {
            markInFlightMutationsUnknown()
        } else {
            projection = nil
            cancellationMutations.removeAll()
            attentionMutations.removeAll()
            sections = FabricWorkInboxSections()
            lastUpdated = nil
        }
        context = requestedContext
    }

    private func becomeUnavailable() {
        refreshGeneration += 1
        operationGeneration += 1
        context = nil
        projection = nil
        cancellationMutations.removeAll()
        attentionMutations.removeAll()
        sections = FabricWorkInboxSections()
        availability = .unavailable
        isRefreshing = false
        syncError = nil
        lastUpdated = nil
    }

    private func publish(_ state: FabricWorkProjection) {
        projection = state
        reconcileMutationFences(with: state)
        rebuildSections()
    }

    private func reconcileMutationFences(with state: FabricWorkProjection) {
        cancellationMutations = cancellationMutations.filter { jobID, mutation in
            guard let job = state.jobs[jobID] else { return false }
            switch mutation.state {
            case .acknowledged(let version):
                return job.version < version
            case .inFlight, .outcomeUnknown:
                return job.version == mutation.expectedVersion && Self.canCancel(job)
            }
        }
        attentionMutations = attentionMutations.filter { attentionID, mutation in
            guard let attention = state.attention[attentionID] else { return false }
            switch mutation.state {
            case .acknowledged(let version):
                return attention.version < version
            case .inFlight, .outcomeUnknown:
                return attention.version == mutation.expectedVersion
                    && attention.state == "pending"
            }
        }
    }

    private func rebuildSections() {
        guard let projection else {
            sections = FabricWorkInboxSections()
            return
        }
        sections = Self.makeSections(
            projection,
            cancellingJobIDs: Set(cancellationMutations.keys),
            respondingAttentionIDs: Set(attentionMutations.keys)
        )
    }

    private func markInFlightMutationsUnknown() {
        cancellationMutations = cancellationMutations.mapValues { mutation in
            var mutation = mutation
            if mutation.state == .inFlight { mutation.state = .outcomeUnknown }
            return mutation
        }
        attentionMutations = attentionMutations.mapValues { mutation in
            var mutation = mutation
            if mutation.state == .inFlight { mutation.state = .outcomeUnknown }
            return mutation
        }
        rebuildSections()
    }

    private func markCancellationOutcomeUnknown(_ mutation: CancellationMutation) {
        guard cancellationMutations[mutation.jobID]?.idempotencyKey == mutation.idempotencyKey else {
            return
        }
        cancellationMutations[mutation.jobID]?.state = .outcomeUnknown
        rebuildSections()
    }

    private func markAttentionOutcomeUnknown(_ mutation: AttentionMutation) {
        guard attentionMutations[mutation.attentionID]?.idempotencyKey == mutation.idempotencyKey else {
            return
        }
        attentionMutations[mutation.attentionID]?.state = .outcomeUnknown
        rebuildSections()
    }

    private func isCurrentRefresh(
        _ generation: Int,
        context requestedContext: FabricWorkInboxContext
    ) -> Bool {
        refreshGeneration == generation
            && context == requestedContext
            && !Task.isCancelled
    }

    private func finishCancelledRefreshIfCurrent(
        _ generation: Int,
        context requestedContext: FabricWorkInboxContext
    ) {
        guard refreshGeneration == generation, context == requestedContext else { return }
        isRefreshing = false
        if projection?.phase == .current {
            availability = .current
        } else if projection == nil || projection?.phase == .empty {
            availability = .empty
        } else {
            availability = .stale
        }
    }

    private func isCurrentOperation(
        _ generation: Int,
        context requestedContext: FabricWorkInboxContext
    ) -> Bool {
        operationGeneration == generation && context == requestedContext
    }

    private static let activeStatuses: Set<String> = [
        "queued", "claimed", "running", "waiting_attention", "cancel_requested",
    ]
    private static let cancellableStatuses: Set<String> = [
        "queued", "claimed", "running", "waiting_attention",
    ]
    private static let terminalStatuses: Set<String> = [
        "succeeded", "failed", "cancelled", "interrupted",
    ]
    private static let openAttentionStates: Set<String> = ["pending", "resolving"]
    private static let terminalAttentionStates: Set<String> = [
        "resolved", "denied", "expired", "cancelled", "orphaned",
    ]

    private static func makeSections(
        _ projection: FabricWorkProjection,
        cancellingJobIDs: Set<String>,
        respondingAttentionIDs: Set<String>
    ) -> FabricWorkInboxSections {
        var result = FabricWorkInboxSections()
        let attention = projection.attention.values

        let supportedOpenAttention = attention.filter { item in
            item.unknownEnums.isEmpty && openAttentionStates.contains(item.state)
        }
        let unsupportedAttention = attention.filter { item in
            !item.unknownEnums.isEmpty
                || (!openAttentionStates.contains(item.state)
                    && !terminalAttentionStates.contains(item.state))
        }
        let supportedByJob = Dictionary(grouping: supportedOpenAttention.compactMap { item in
            item.jobID.map { ($0, item) }
        }, by: { $0.0 }).mapValues { rows in rows.map(\.1) }
        let unsupportedByJob = Dictionary(grouping: unsupportedAttention.compactMap { item in
            item.jobID.map { ($0, item) }
        }, by: { $0.0 }).mapValues { rows in rows.map(\.1) }

        var groupsByJob: [String: String] = [:]
        for job in projection.jobs.values {
            let linkedSupported = supportedByJob[job.jobID] ?? []
            let linkedUnsupported = unsupportedByJob[job.jobID] ?? []
            let linkedForRow = linkedSupported.map {
                makeAttentionSummary($0, respondingAttentionIDs: respondingAttentionIDs)
            }
            let isSupported = job.actionable
                && job.kind == "background_prompt"
                && (activeStatuses.contains(job.status) || terminalStatuses.contains(job.status))

            let group: String
            if !isSupported {
                group = "unsupported"
            } else if terminalStatuses.contains(job.status) {
                group = "completed"
            } else if job.status == "waiting_attention"
                || job.openAttentionCount > 0
                || !linkedSupported.isEmpty
                || !linkedUnsupported.isEmpty {
                group = "attention"
            } else {
                group = "active"
            }
            groupsByJob[job.jobID] = group

            let row = makeJobSummary(
                job,
                attention: group == "attention" ? linkedForRow : [],
                cancellationPending: cancellingJobIDs.contains(job.jobID)
            )
            switch group {
            case "attention": result.needsAttention.append(row)
            case "active": result.active.append(row)
            case "completed": result.completed.append(row)
            default: result.unsupportedJobs.append(row)
            }
        }

        result.unboundAttention = supportedOpenAttention.filter { attention in
            guard let jobID = attention.jobID else { return true }
            return groupsByJob[jobID] != "attention"
        }.map {
            makeAttentionSummary($0, respondingAttentionIDs: respondingAttentionIDs)
        }
        result.unsupportedAttention = unsupportedAttention.map {
            makeAttentionSummary($0, respondingAttentionIDs: respondingAttentionIDs)
        }
        result.unsupportedSubjects = projection.unknownSubjects.values.map { subject in
            FabricWorkInboxUnsupportedSubject(
                id: subject.subjectID,
                subjectType: subject.subjectType,
                version: subject.version
            )
        }

        result.needsAttention.sort(by: jobComesFirst)
        result.active.sort(by: jobComesFirst)
        result.completed.sort(by: completedJobComesFirst)
        result.unsupportedJobs.sort(by: jobComesFirst)
        result.unboundAttention.sort(by: attentionComesFirst)
        result.unsupportedAttention.sort(by: attentionComesFirst)
        result.unsupportedSubjects.sort {
            if $0.subjectType != $1.subjectType { return $0.subjectType < $1.subjectType }
            return $0.id < $1.id
        }
        return result
    }

    private static func makeJobSummary(
        _ job: FabricWorkJobSummary,
        attention: [FabricWorkInboxAttentionSummary],
        cancellationPending: Bool
    ) -> FabricWorkInboxJobSummary {
        FabricWorkInboxJobSummary(
            id: job.jobID,
            version: job.version,
            kind: job.kind,
            status: job.status,
            title: job.title,
            summary: job.summary,
            openAttentionCount: job.openAttentionCount,
            attemptCount: job.attemptCount,
            createdAt: job.createdAt,
            startedAt: job.startedAt,
            updatedAt: job.updatedAt,
            finishedAt: job.finishedAt,
            attention: attention.sorted(by: attentionComesFirst),
            hasResultPreview: !job.resultPreview.isNullValue,
            hasErrorPreview: !job.error.isNullValue,
            transcriptRoute: transcriptRoute(for: job),
            canCancel: canCancel(job) && !cancellationPending
        )
    }

    private static func makeAttentionSummary(
        _ attention: FabricWorkAttention,
        respondingAttentionIDs: Set<String>
    ) -> FabricWorkInboxAttentionSummary {
        FabricWorkInboxAttentionSummary(
            id: attention.attentionID,
            version: attention.version,
            jobID: attention.jobID,
            kind: attention.kind,
            state: attention.state,
            title: attention.title,
            blocking: attention.blocking,
            sensitive: attention.sensitive,
            allowedActions: attention.unknownEnums.isEmpty ? attention.allowedActions : [],
            updatedAt: attention.updatedAt,
            canRespond: attention.actionable
                && attention.state == "pending"
                && !respondingAttentionIDs.contains(attention.attentionID)
        )
    }

    private static func canCancel(_ job: FabricWorkJobSummary) -> Bool {
        job.actionable
            && job.kind == "background_prompt"
            && cancellableStatuses.contains(job.status)
    }

    /// The typed wrapper emits `invalidRequest` only from its local request
    /// validation, before opening the transport. Every network/RPC failure is
    /// still outcome-unknown and keeps its idempotency fence.
    private static func isDefinitelyUnsent(_ error: Error) -> Bool {
        guard let gatewayError = error as? FabricWorkGatewayError else { return false }
        if case .invalidRequest = gatewayError { return true }
        return false
    }

    private static func transcriptRoute(
        for job: FabricWorkJobSummary
    ) -> FabricWorkInboxTranscriptRoute? {
        guard let runtimeSessionID = job.runtimeSessionID,
              !runtimeSessionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              job.resultReference == "session:\(runtimeSessionID)"
        else { return nil }
        return FabricWorkInboxTranscriptRoute(runtimeSessionID: runtimeSessionID)
    }

    private static func jobComesFirst(
        _ lhs: FabricWorkInboxJobSummary,
        _ rhs: FabricWorkInboxJobSummary
    ) -> Bool {
        if lhs.updatedAt != rhs.updatedAt { return lhs.updatedAt > rhs.updatedAt }
        return lhs.id < rhs.id
    }

    private static func completedJobComesFirst(
        _ lhs: FabricWorkInboxJobSummary,
        _ rhs: FabricWorkInboxJobSummary
    ) -> Bool {
        let lhsTime = lhs.finishedAt ?? lhs.updatedAt
        let rhsTime = rhs.finishedAt ?? rhs.updatedAt
        if lhsTime != rhsTime { return lhsTime > rhsTime }
        return lhs.id < rhs.id
    }

    private static func attentionComesFirst(
        _ lhs: FabricWorkInboxAttentionSummary,
        _ rhs: FabricWorkInboxAttentionSummary
    ) -> Bool {
        if lhs.blocking != rhs.blocking { return lhs.blocking }
        if lhs.updatedAt != rhs.updatedAt { return lhs.updatedAt > rhs.updatedAt }
        return lhs.id < rhs.id
    }
}

private extension FabricWorkJSONValue {
    var isNullValue: Bool {
        if case .null = self { return true }
        return false
    }
}
