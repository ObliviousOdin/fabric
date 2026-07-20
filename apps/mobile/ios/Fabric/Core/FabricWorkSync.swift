import Foundation

/// Server-derived identity for one Work projection. `gatewayID` is opaque to
/// the phone; `profileID` is returned by the authorized server session and
/// must never be inferred from a user-visible profile label or local path.
struct FabricWorkSyncScope: Equatable {
    let gatewayID: String
    let profileID: String

    init(gatewayID: String, profileID: String) {
        self.gatewayID = gatewayID
        self.profileID = profileID
    }
}

enum FabricWorkProjectionPhase: String, Equatable {
    case empty
    case bootstrapping
    case syncing
    case current
}

struct FabricWorkUnknownProjectionSubject: Equatable {
    let subjectID: String
    let subjectType: String
    let version: Int
    let subject: FabricWorkEventSubject
}

/// A serializable reference projection. The `(gateway, profile, ledger,
/// cursor)` tuple is authority; `work.changed` is a wake-up hint only and must
/// never directly mutate this value.
struct FabricWorkProjection: Equatable {
    let gatewayID: String
    let profileID: String
    let ledgerID: String?
    let cursor: Int?
    let watermark: Int?
    let phase: FabricWorkProjectionPhase
    let nextPageToken: String?
    let resetLedgerHint: String?
    let jobs: [String: FabricWorkJobSummary]
    let attention: [String: FabricWorkAttention]
    let unknownSubjects: [String: FabricWorkUnknownProjectionSubject]
    /// Includes tombstone versions so a stale after-state cannot resurrect.
    let subjectVersions: [String: Int]
}

struct FabricWorkSyncRequestContext: Equatable {
    let scope: FabricWorkSyncScope
    /// The token supplied to fetch this bootstrap page; nil for page one.
    let pageToken: String?
    /// The cursor supplied to fetch this delta page.
    let after: Int?

    init(
        scope: FabricWorkSyncScope,
        pageToken: String? = nil,
        after: Int? = nil
    ) {
        self.scope = scope
        self.pageToken = pageToken
        self.after = after
    }
}

enum FabricWorkSyncApplyErrorCode: String, Equatable {
    case identityChanged = "identity_changed"
    case bootstrapSequenceInvalid = "bootstrap_sequence_invalid"
    case bootstrapRequired = "bootstrap_required"
    case cursorInvalid = "cursor_invalid"
    case ledgerChanged = "ledger_changed"
    case pageNonActionable = "page_non_actionable"
}

struct FabricWorkSyncApplyError: LocalizedError, Equatable {
    let code: FabricWorkSyncApplyErrorCode
    let message: String

    var errorDescription: String? { message }
}

/// Pure projection reducer shared by reconnect, foreground recovery, and
/// eventual UI stores. Each mutation starts from value-type copies and returns
/// only after the entire page is valid, so a failed page never advances the
/// durable cursor visible to the rest of the app.
enum FabricWorkProjectionReducer {
    static func create(scope: FabricWorkSyncScope) throws -> FabricWorkProjection {
        try validate(scope: scope)
        return FabricWorkProjection(
            gatewayID: scope.gatewayID,
            profileID: scope.profileID,
            ledgerID: nil,
            cursor: nil,
            watermark: nil,
            phase: .empty,
            nextPageToken: nil,
            resetLedgerHint: nil,
            jobs: [:],
            attention: [:],
            unknownSubjects: [:],
            subjectVersions: [:]
        )
    }

    /// Apply one already-verified page atomically. Compatible future enum
    /// objects remain displayable in the returned projection, but the page
    /// itself is rejected when its top-level mode is unknown.
    static func apply(
        _ state: FabricWorkProjection,
        page: FabricWorkSyncPage,
        context: FabricWorkSyncRequestContext
    ) throws -> FabricWorkProjection {
        try validate(scope: context.scope)
        guard page.workProfileID == context.scope.profileID else {
            throw error(
                .identityChanged,
                "The Work page belongs to a different profile."
            )
        }
        guard page.actionable else {
            throw error(
                .pageNonActionable,
                "This client does not understand the Work sync page mode."
            )
        }
        switch page.mode {
        case "bootstrap":
            return try applyBootstrap(state, page: page, context: context)
        case "delta":
            return try applyDelta(state, page: page, context: context)
        default:
            throw error(
                .pageNonActionable,
                "This client does not understand the Work sync page mode."
            )
        }
    }

    /// Cursor expiry or ledger replacement immediately discards the old
    /// namespace. Only a fresh page-one bootstrap can establish the next one.
    static func applyCursorReset(
        _ state: FabricWorkProjection,
        reset: FabricWorkCursorReset,
        scope: FabricWorkSyncScope
    ) throws -> FabricWorkProjection {
        try validate(scope: scope)
        guard sameScope(state, scope) else {
            throw error(
                .identityChanged,
                "A cursor reset from a different gateway or profile was ignored."
            )
        }
        let empty = try create(scope: scope)
        return FabricWorkProjection(
            gatewayID: empty.gatewayID,
            profileID: empty.profileID,
            ledgerID: empty.ledgerID,
            cursor: empty.cursor,
            watermark: empty.watermark,
            phase: empty.phase,
            nextPageToken: empty.nextPageToken,
            resetLedgerHint: reset.data.ledgerID,
            jobs: empty.jobs,
            attention: empty.attention,
            unknownSubjects: empty.unknownSubjects,
            subjectVersions: empty.subjectVersions
        )
    }

    private struct MutableSubjects {
        var jobs: [String: FabricWorkJobSummary]
        var attention: [String: FabricWorkAttention]
        var unknownSubjects: [String: FabricWorkUnknownProjectionSubject]
        var versions: [String: Int]

        init(_ state: FabricWorkProjection? = nil) {
            jobs = state?.jobs ?? [:]
            attention = state?.attention ?? [:]
            unknownSubjects = state?.unknownSubjects ?? [:]
            versions = state?.subjectVersions ?? [:]
        }
    }

    private static func applyBootstrap(
        _ state: FabricWorkProjection,
        page: FabricWorkSyncPage,
        context: FabricWorkSyncRequestContext
    ) throws -> FabricWorkProjection {
        let requestedToken = context.pageToken
        let subjects: MutableSubjects
        if requestedToken == nil {
            // A page-one bootstrap is an explicit replacement. It is the only
            // page allowed to establish a new ledger identity.
            subjects = MutableSubjects()
        } else {
            guard sameScope(state, context.scope) else {
                throw error(
                    .identityChanged,
                    "A bootstrap continuation belongs to a different gateway or profile."
                )
            }
            guard state.phase == .bootstrapping,
                  state.nextPageToken == requestedToken
            else {
                throw error(
                    .bootstrapSequenceInvalid,
                    "Bootstrap page token does not match the pending page."
                )
            }
            guard state.ledgerID == page.ledgerID else {
                throw error(
                    .ledgerChanged,
                    "The Work ledger changed during bootstrap; restart at page one."
                )
            }
            guard state.watermark == page.watermark else {
                throw error(
                    .cursorInvalid,
                    "The fixed bootstrap watermark changed between pages."
                )
            }
            subjects = MutableSubjects(state)
        }

        // Copy before mutation. If one future implementation adds a throwing
        // subject transform, `state` still remains untouched.
        var next = subjects
        for job in page.jobs { apply(job, to: &next) }
        for attention in page.attention { apply(attention, to: &next) }
        return finish(
            gatewayID: context.scope.gatewayID,
            profileID: context.scope.profileID,
            ledgerID: page.ledgerID,
            cursor: page.hasMore ? nil : page.cursor,
            watermark: page.watermark,
            phase: page.hasMore ? .bootstrapping : .current,
            nextPageToken: page.nextPageToken,
            resetLedgerHint: nil,
            subjects: next
        )
    }

    private static func applyDelta(
        _ state: FabricWorkProjection,
        page: FabricWorkSyncPage,
        context: FabricWorkSyncRequestContext
    ) throws -> FabricWorkProjection {
        guard sameScope(state, context.scope) else {
            throw error(
                .identityChanged,
                "The delta belongs to a different gateway or profile; bootstrap first."
            )
        }
        guard state.phase == .current || state.phase == .syncing else {
            throw error(.bootstrapRequired, "A delta cannot be applied before bootstrap completes.")
        }
        guard state.ledgerID == page.ledgerID else {
            throw error(
                .ledgerChanged,
                "The Work ledger changed; discard the projection and bootstrap."
            )
        }
        guard let currentCursor = state.cursor else {
            throw error(.bootstrapRequired, "The projection has no durable cursor.")
        }
        let requestedAfter = context.after ?? currentCursor
        guard (0...FabricWorkLimits.maximumSafeInteger).contains(requestedAfter) else {
            throw error(.cursorInvalid, "The requested Work cursor is invalid.")
        }
        guard requestedAfter == currentCursor else {
            throw error(
                .cursorInvalid,
                "A stale or future Work response cannot advance this projection."
            )
        }
        guard page.cursor >= currentCursor, page.watermark >= currentCursor else {
            throw error(.cursorInvalid, "The Work page is behind the persisted cursor.")
        }
        guard page.cursor == currentCursor || !page.events.isEmpty else {
            throw error(
                .cursorInvalid,
                "A Work cursor cannot advance without the intervening events."
            )
        }
        guard !page.hasMore || page.cursor > currentCursor else {
            throw error(
                .cursorInvalid,
                "A truncated Work page must advance beyond the persisted cursor."
            )
        }

        var next = MutableSubjects(state)
        var expectedEventID = currentCursor + 1
        for event in page.events {
            // Replays are safe because a durable event ID is also the cursor
            // dedupe fence. Do not mutate the subject namespace for them.
            if event.eventID <= currentCursor { continue }
            guard event.eventID == expectedEventID else {
                throw error(
                    .cursorInvalid,
                    "The Work page skipped one or more events after the persisted cursor."
                )
            }
            try apply(event, to: &next)
            expectedEventID += 1
        }
        guard expectedEventID - 1 == page.cursor else {
            throw error(
                .cursorInvalid,
                "The Work page cursor does not match its final contiguous event."
            )
        }
        return finish(
            gatewayID: state.gatewayID,
            profileID: state.profileID,
            ledgerID: state.ledgerID,
            cursor: page.cursor,
            watermark: page.watermark,
            phase: page.hasMore ? .syncing : .current,
            nextPageToken: nil,
            resetLedgerHint: nil,
            subjects: next
        )
    }

    private static func apply(_ job: FabricWorkJobSummary, to subjects: inout MutableSubjects) {
        let key = subjectKey(type: "job", id: job.jobID)
        guard (subjects.versions[key] ?? 0) < job.version else { return }
        subjects.jobs[job.jobID] = job
        subjects.unknownSubjects.removeValue(forKey: key)
        subjects.versions[key] = job.version
    }

    private static func apply(_ attention: FabricWorkAttention, to subjects: inout MutableSubjects) {
        let key = subjectKey(type: "attention", id: attention.attentionID)
        guard (subjects.versions[key] ?? 0) < attention.version else { return }
        subjects.attention[attention.attentionID] = attention
        subjects.unknownSubjects.removeValue(forKey: key)
        subjects.versions[key] = attention.version
    }

    private static func apply(_ event: FabricWorkEvent, to subjects: inout MutableSubjects) throws {
        let key = subjectKey(type: event.subjectType, id: event.subjectID)
        guard (subjects.versions[key] ?? 0) < event.subjectVersion else { return }

        if event.tombstone {
            if event.subjectType == "job" {
                subjects.jobs.removeValue(forKey: event.subjectID)
            } else if event.subjectType == "attention" {
                subjects.attention.removeValue(forKey: event.subjectID)
            }
            subjects.unknownSubjects.removeValue(forKey: key)
            subjects.versions[key] = event.subjectVersion
            return
        }

        guard let subject = event.subject else {
            throw error(.pageNonActionable, "A non-tombstone work event has no subject.")
        }
        switch subject {
        case .job(let job):
            apply(job, to: &subjects)
        case .attention(let attention):
            apply(attention, to: &subjects)
        case .unknown:
            subjects.unknownSubjects[key] = FabricWorkUnknownProjectionSubject(
                subjectID: event.subjectID,
                subjectType: event.subjectType,
                version: event.subjectVersion,
                subject: subject
            )
            subjects.versions[key] = event.subjectVersion
        }
    }

    private static func finish(
        gatewayID: String,
        profileID: String,
        ledgerID: String?,
        cursor: Int?,
        watermark: Int?,
        phase: FabricWorkProjectionPhase,
        nextPageToken: String?,
        resetLedgerHint: String?,
        subjects: MutableSubjects
    ) -> FabricWorkProjection {
        FabricWorkProjection(
            gatewayID: gatewayID,
            profileID: profileID,
            ledgerID: ledgerID,
            cursor: cursor,
            watermark: watermark,
            phase: phase,
            nextPageToken: nextPageToken,
            resetLedgerHint: resetLedgerHint,
            jobs: subjects.jobs,
            attention: subjects.attention,
            unknownSubjects: subjects.unknownSubjects,
            subjectVersions: subjects.versions
        )
    }

    private static func validate(scope: FabricWorkSyncScope) throws {
        guard !scope.gatewayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw error(.identityChanged, "gateway_id must be non-empty.")
        }
        guard !scope.profileID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw error(.identityChanged, "profile_id must be non-empty.")
        }
    }

    private static func sameScope(_ state: FabricWorkProjection, _ scope: FabricWorkSyncScope) -> Bool {
        state.gatewayID == scope.gatewayID && state.profileID == scope.profileID
    }

    private static func subjectKey(type: String, id: String) -> String {
        "\(type):\(id)"
    }

    private static func error(
        _ code: FabricWorkSyncApplyErrorCode,
        _ message: String
    ) -> FabricWorkSyncApplyError {
        FabricWorkSyncApplyError(code: code, message: message)
    }
}
