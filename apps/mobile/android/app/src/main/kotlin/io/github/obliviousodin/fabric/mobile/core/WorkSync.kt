package io.github.obliviousodin.fabric.mobile.core

/** Scope of one physical gateway/profile Work ledger. */
data class WorkSyncScope(
    val gatewayId: String,
    val profileId: String,
)

enum class WorkProjectionPhase { EMPTY, BOOTSTRAPPING, SYNCING, CURRENT }

data class WorkUnknownProjectionSubject(
    val subjectId: String,
    val subjectType: String,
    val version: Long,
    val subject: WorkEventSubject,
)

/**
 * Serializable projection of the authoritative Work ledger.
 *
 * The `(gatewayId, profileId, ledgerId, cursor)` tuple is state authority.
 * `work.changed` transport hints must cause a sync request, never mutate this
 * object directly.
 */
data class WorkProjection(
    val gatewayId: String,
    val profileId: String,
    val ledgerId: String? = null,
    val cursor: Long? = null,
    val watermark: Long? = null,
    val phase: WorkProjectionPhase = WorkProjectionPhase.EMPTY,
    val nextPageToken: String? = null,
    val resetLedgerHint: String? = null,
    val jobs: Map<String, WorkJobSummary> = emptyMap(),
    val attention: Map<String, WorkAttention> = emptyMap(),
    val unknownSubjects: Map<String, WorkUnknownProjectionSubject> = emptyMap(),
    /** Includes tombstone versions, preventing stale events from resurrecting a row. */
    val subjectVersions: Map<String, Long> = emptyMap(),
)

enum class WorkSyncApplyErrorCode {
    IDENTITY_CHANGED,
    BOOTSTRAP_SEQUENCE_INVALID,
    BOOTSTRAP_REQUIRED,
    CURSOR_INVALID,
    LEDGER_CHANGED,
    PAGE_NON_ACTIONABLE,
}

class WorkSyncApplyException(
    val code: WorkSyncApplyErrorCode,
    message: String,
) : IllegalStateException(message)

data class WorkSyncRequestContext(
    val gatewayId: String,
    val profileId: String,
    /** Token submitted for this bootstrap page; null only for page one. */
    val pageToken: String? = null,
    /** Cursor submitted for this delta page. */
    val after: Long? = null,
)

private fun nonemptyWorkScope(value: String, field: String): String {
    if (value.trim().isEmpty()) throw IllegalArgumentException("$field must be non-empty.")
    return value
}

private fun checkedScope(scope: WorkSyncScope): WorkSyncScope = WorkSyncScope(
    gatewayId = nonemptyWorkScope(scope.gatewayId, "gateway_id"),
    profileId = nonemptyWorkScope(scope.profileId, "profile_id"),
)

private fun checkedContext(context: WorkSyncRequestContext): WorkSyncScope = checkedScope(
    WorkSyncScope(context.gatewayId, context.profileId),
)

fun createWorkProjection(scope: WorkSyncScope): WorkProjection {
    val checked = checkedScope(scope)
    return WorkProjection(gatewayId = checked.gatewayId, profileId = checked.profileId)
}

private fun sameScope(state: WorkProjection, scope: WorkSyncScope): Boolean =
    state.gatewayId == scope.gatewayId && state.profileId == scope.profileId

private fun subjectKey(type: String, id: String): String = "$type:$id"

private data class MutableProjectionSubjects(
    val jobs: MutableMap<String, WorkJobSummary>,
    val attention: MutableMap<String, WorkAttention>,
    val unknown: MutableMap<String, WorkUnknownProjectionSubject>,
    val versions: MutableMap<String, Long>,
)

private fun mutableSubjects(state: WorkProjection? = null): MutableProjectionSubjects =
    MutableProjectionSubjects(
        jobs = state?.jobs?.toMutableMap() ?: mutableMapOf(),
        attention = state?.attention?.toMutableMap() ?: mutableMapOf(),
        unknown = state?.unknownSubjects?.toMutableMap() ?: mutableMapOf(),
        versions = state?.subjectVersions?.toMutableMap() ?: mutableMapOf(),
    )

private fun applyJob(subjects: MutableProjectionSubjects, job: WorkJobSummary) {
    val key = subjectKey("job", job.jobId)
    if ((subjects.versions[key] ?: 0) >= job.version) return
    subjects.jobs[job.jobId] = job
    subjects.unknown.remove(key)
    subjects.versions[key] = job.version
}

private fun applyAttention(subjects: MutableProjectionSubjects, attention: WorkAttention) {
    val key = subjectKey("attention", attention.attentionId)
    if ((subjects.versions[key] ?: 0) >= attention.version) return
    subjects.attention[attention.attentionId] = attention
    subjects.unknown.remove(key)
    subjects.versions[key] = attention.version
}

private fun applyEvent(subjects: MutableProjectionSubjects, event: WorkEvent) {
    val key = subjectKey(event.subjectType, event.subjectId)
    if ((subjects.versions[key] ?: 0) >= event.subjectVersion) return

    if (event.tombstone) {
        when (event.subjectType) {
            "job" -> subjects.jobs.remove(event.subjectId)
            "attention" -> subjects.attention.remove(event.subjectId)
        }
        subjects.unknown.remove(key)
        subjects.versions[key] = event.subjectVersion
        return
    }

    val subject = event.subject ?: throw WorkSyncApplyException(
        WorkSyncApplyErrorCode.PAGE_NON_ACTIONABLE,
        "A non-tombstone work event has no subject.",
    )
    when (subject) {
        is WorkJobSummary -> applyJob(subjects, subject)
        is WorkAttention -> applyAttention(subjects, subject)
        is WorkUnknownSubject -> {
            subjects.unknown[key] = WorkUnknownProjectionSubject(
                subjectId = event.subjectId,
                subjectType = event.subjectType,
                version = event.subjectVersion,
                subject = subject,
            )
            subjects.versions[key] = event.subjectVersion
        }
    }
}

private fun finishProjection(
    base: WorkProjection,
    subjects: MutableProjectionSubjects,
): WorkProjection = base.copy(
    jobs = subjects.jobs.toMap(),
    attention = subjects.attention.toMap(),
    unknownSubjects = subjects.unknown.toMap(),
    subjectVersions = subjects.versions.toMap(),
)

private fun applyBootstrap(
    state: WorkProjection,
    page: WorkSyncPage,
    context: WorkSyncRequestContext,
): WorkProjection {
    val requestedToken = context.pageToken
    val firstPage = requestedToken == null
    val subjects = if (firstPage) {
        // A page-one bootstrap is the only flow allowed to replace state identity.
        mutableSubjects()
    } else {
        if (!sameScope(state, WorkSyncScope(context.gatewayId, context.profileId))) {
            throw WorkSyncApplyException(
                WorkSyncApplyErrorCode.IDENTITY_CHANGED,
                "A bootstrap continuation belongs to a different gateway or profile.",
            )
        }
        if (state.phase != WorkProjectionPhase.BOOTSTRAPPING || state.nextPageToken != requestedToken) {
            throw WorkSyncApplyException(
                WorkSyncApplyErrorCode.BOOTSTRAP_SEQUENCE_INVALID,
                "Bootstrap page token does not match the pending page.",
            )
        }
        if (state.ledgerId != page.ledgerId) {
            throw WorkSyncApplyException(
                WorkSyncApplyErrorCode.LEDGER_CHANGED,
                "The Work ledger changed during bootstrap; restart at page one.",
            )
        }
        if (state.watermark != page.watermark) {
            throw WorkSyncApplyException(
                WorkSyncApplyErrorCode.CURSOR_INVALID,
                "The fixed bootstrap watermark changed between pages.",
            )
        }
        mutableSubjects(state)
    }

    // All work happens on local copies. A malformed row cannot publish a
    // cursor or identity before its entire page has applied.
    page.jobs.forEach { applyJob(subjects, it) }
    page.attention.forEach { applyAttention(subjects, it) }
    return finishProjection(
        WorkProjection(
            gatewayId = context.gatewayId,
            profileId = context.profileId,
            ledgerId = page.ledgerId,
            cursor = if (page.hasMore) null else page.cursor,
            watermark = page.watermark,
            phase = if (page.hasMore) WorkProjectionPhase.BOOTSTRAPPING else WorkProjectionPhase.CURRENT,
            nextPageToken = page.nextPageToken,
            resetLedgerHint = null,
        ),
        subjects,
    )
}

private fun applyDelta(
    state: WorkProjection,
    page: WorkSyncPage,
    context: WorkSyncRequestContext,
): WorkProjection {
    val scope = WorkSyncScope(context.gatewayId, context.profileId)
    if (!sameScope(state, scope)) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.IDENTITY_CHANGED,
            "The delta belongs to a different gateway or profile; bootstrap first.",
        )
    }
    if (state.phase != WorkProjectionPhase.CURRENT && state.phase != WorkProjectionPhase.SYNCING) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.BOOTSTRAP_REQUIRED,
            "A delta cannot be applied before bootstrap completes.",
        )
    }
    if (state.ledgerId != page.ledgerId) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.LEDGER_CHANGED,
            "The Work ledger changed; discard the projection and bootstrap.",
        )
    }
    val stateCursor = state.cursor ?: throw WorkSyncApplyException(
        WorkSyncApplyErrorCode.BOOTSTRAP_REQUIRED,
        "The projection has no durable cursor.",
    )
    val requestedAfter = context.after ?: stateCursor
    if (requestedAfter < 0) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.CURSOR_INVALID,
            "The requested Work cursor is invalid.",
        )
    }
    if (requestedAfter != stateCursor) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.CURSOR_INVALID,
            "A stale or future Work response cannot advance this projection.",
        )
    }
    if (page.cursor < stateCursor || page.watermark < stateCursor) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.CURSOR_INVALID,
            "The Work page is behind the persisted cursor.",
        )
    }
    if (page.cursor > stateCursor && page.events.isEmpty()) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.CURSOR_INVALID,
            "A Work cursor cannot advance without the intervening events.",
        )
    }
    if (page.hasMore && page.cursor == stateCursor) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.CURSOR_INVALID,
            "A truncated Work page must advance beyond the persisted cursor.",
        )
    }

    val subjects = mutableSubjects(state)
    var expectedEventId = stateCursor + 1
    for (event in page.events) {
        // Replayed committed events cannot overwrite a newer subject.
        if (event.eventId <= stateCursor) continue
        if (event.eventId != expectedEventId) {
            throw WorkSyncApplyException(
                WorkSyncApplyErrorCode.CURSOR_INVALID,
                "The Work page skipped one or more events after the persisted cursor.",
            )
        }
        applyEvent(subjects, event)
        expectedEventId += 1
    }
    if (expectedEventId - 1 != page.cursor) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.CURSOR_INVALID,
            "The Work page cursor does not match its final contiguous event.",
        )
    }
    return finishProjection(
        WorkProjection(
            gatewayId = state.gatewayId,
            profileId = state.profileId,
            ledgerId = state.ledgerId,
            cursor = page.cursor,
            watermark = page.watermark,
            phase = if (page.hasMore) WorkProjectionPhase.SYNCING else WorkProjectionPhase.CURRENT,
            nextPageToken = null,
            resetLedgerHint = null,
        ),
        subjects,
    )
}

/** Apply one verified page atomically. */
fun applyWorkSyncPage(
    state: WorkProjection,
    page: WorkSyncPage,
    context: WorkSyncRequestContext,
): WorkProjection {
    val scope = checkedContext(context)
    if (page.workProfileId != scope.profileId) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.IDENTITY_CHANGED,
            "The Work page belongs to a different profile.",
        )
    }
    if (!page.actionable) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.PAGE_NON_ACTIONABLE,
            "This client does not understand the Work sync page mode.",
        )
    }
    return when (page.mode) {
        "bootstrap" -> applyBootstrap(state, page, context)
        "delta" -> applyDelta(state, page, context)
        else -> throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.PAGE_NON_ACTIONABLE,
            "This client does not understand the Work sync page mode.",
        )
    }
}

/** A cursor reset discards the old ledger immediately; bootstrap replaces it. */
fun applyWorkCursorReset(
    state: WorkProjection,
    reset: WorkCursorReset,
    scope: WorkSyncScope,
): WorkProjection {
    val checked = checkedScope(scope)
    if (!sameScope(state, checked)) {
        throw WorkSyncApplyException(
            WorkSyncApplyErrorCode.IDENTITY_CHANGED,
            "A cursor reset from a different gateway or profile was ignored.",
        )
    }
    return createWorkProjection(checked).copy(resetLedgerHint = reset.data.ledgerId)
}
