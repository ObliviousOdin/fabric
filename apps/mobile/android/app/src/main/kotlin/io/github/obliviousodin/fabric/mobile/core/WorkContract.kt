package io.github.obliviousodin.fabric.mobile.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

/**
 * Android implementation of the canonical `fabric.work` v1 wire contract.
 *
 * The source fixtures and the TypeScript reference implementation live under
 * `apps/mobile/contracts/fabric-work-v1` and `apps/shared/src/work-contract.ts`.
 * Unknown additive object keys are deliberately ignored. Unknown enum values
 * remain visible for diagnostic display, but make only the affected object
 * non-actionable.
 */
const val FABRIC_WORK_CLIENT_CONTRACT_VERSION = 1
const val FABRIC_WORK_SYNC_MAX_BYTES = 1024 * 1024
const val FABRIC_WORK_SYNC_MAX_ITEMS = 500
const val FABRIC_WORK_SUBJECT_MAX_BYTES = 32 * 1024
const val FABRIC_WORK_RESULT_PREVIEW_MAX_BYTES = 4 * 1024
const val FABRIC_WORK_ERROR_PREVIEW_MAX_BYTES = 8 * 1024
/** `job.get` bodies remain outside sync projections and are bounded separately. */
const val FABRIC_WORK_JOB_DETAIL_BODY_MAX_BYTES = 256 * 1024

const val FABRIC_WORK_MAXIMUM_SAFE_INTEGER = 9_007_199_254_740_991L

private val WORK_JOB_KINDS = setOf("background_prompt")
private val WORK_JOB_STATUSES = setOf(
    "queued",
    "claimed",
    "running",
    "waiting_attention",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
)
private val WORK_ATTENTION_KINDS = setOf("approval", "clarify", "sudo", "secret")
private val WORK_ATTENTION_STATES = setOf(
    "pending",
    "resolving",
    "resolved",
    "denied",
    "expired",
    "cancelled",
    "orphaned",
)
private val WORK_ATTENTION_ACTIONS = setOf("once", "session", "always", "deny", "submit", "cancel")
private val WORK_RUN_RUNTIME_KINDS = setOf("in_process_agent")
private val WORK_RUN_OWNER_STATES = setOf("creator_bound")
private val WORK_RESTART_BEHAVIORS = setOf("interrupt")
private val WORK_RESULT_OMITTED_REASONS = setOf("sensitive_input")
private val WORK_SYNC_MODES = setOf("bootstrap", "delta")
private val WORK_SUBJECT_TYPES = setOf("job", "attention")

private val WORK_ID_PATTERNS = mapOf(
    "attention" to Regex("^attn_[0-9a-f]{32}$"),
    "job" to Regex("^job_[0-9a-f]{32}$"),
    "ledger" to Regex("^ledger_[0-9a-f]{32}$"),
    "mutation" to Regex("^mut_[0-9a-f]{32}$"),
    "profile" to Regex("^profile_[0-9a-f]{32}$"),
    "run" to Regex("^run_[0-9a-f]{32}$"),
)

data class WorkUnknownEnum(val field: String, val raw: String)

data class WorkContractDescriptor(
    val name: String,
    val version: Long,
    val minimumCompatible: Long,
)

data class WorkRunSummary(
    val runId: String,
    val attempt: Long,
    val version: Long,
    val status: String,
    val runtimeKind: String,
    val ownerState: String,
    val restartBehavior: String,
    val claimedAt: Long?,
    val startedAt: Long?,
    val updatedAt: Long,
    val finishedAt: Long?,
    val actionable: Boolean,
    val unknownEnums: List<WorkUnknownEnum>,
)

sealed interface WorkEventSubject {
    val actionable: Boolean
    val unknownEnums: List<WorkUnknownEnum>
}

data class WorkJobSummary(
    val jobId: String,
    val version: Long,
    val kind: String,
    val status: String,
    val title: String,
    val summary: String?,
    val source: String,
    val sourceSessionKey: String?,
    val runtimeSessionId: String?,
    val attemptCount: Long,
    val openAttentionCount: Long,
    val createdAt: Long,
    val startedAt: Long?,
    val updatedAt: Long,
    val finishedAt: Long?,
    val cancelRequestedAt: Long?,
    val runtime: JsonObject,
    val currentRun: WorkRunSummary?,
    val resultPreview: JsonElement,
    val resultRef: String?,
    val resultOmittedReason: String?,
    val error: JsonElement,
    override val actionable: Boolean,
    override val unknownEnums: List<WorkUnknownEnum>,
) : WorkEventSubject

/**
 * The direct `job.get` response can append larger, potentially sensitive
 * bodies to a normal public Job after-state. Keep those bodies typed and
 * bounded, but never let them enter a sync projection.
 */
data class WorkJobDetail(
    val job: WorkJobSummary,
    val promptPreview: String?,
    val result: JsonElement?,
    val errorDetail: JsonElement?,
)

data class WorkAttention(
    val attentionId: String,
    val version: Long,
    val jobId: String?,
    val runId: String?,
    val sourceSessionKey: String?,
    val runtimeSessionId: String?,
    val requestId: String,
    val kind: String,
    val state: String,
    val blocking: Boolean,
    val sensitive: Boolean,
    val title: String,
    val publicPayload: JsonObject,
    val allowedActions: List<String>,
    val createdAt: Long,
    val updatedAt: Long,
    val expiresAt: Long?,
    val resolvedAt: Long?,
    val terminalReason: String?,
    override val actionable: Boolean,
    override val unknownEnums: List<WorkUnknownEnum>,
) : WorkEventSubject

data class WorkUnknownSubject(
    val raw: JsonObject,
    override val actionable: Boolean = false,
    override val unknownEnums: List<WorkUnknownEnum>,
) : WorkEventSubject

data class WorkEvent(
    val eventId: Long,
    val eventType: String,
    val subjectType: String,
    val subjectId: String,
    val jobId: String?,
    val runId: String?,
    val subjectVersion: Long,
    val subject: WorkEventSubject?,
    val tombstone: Boolean,
    val createdAt: Long,
    val actionable: Boolean,
    val unknownEnums: List<WorkUnknownEnum>,
)

data class WorkSyncPage(
    val contract: WorkContractDescriptor,
    val ledgerId: String,
    val workProfileId: String,
    val mode: String,
    val watermark: Long,
    val cursor: Long,
    val hasMore: Boolean,
    val nextPageToken: String?,
    val jobs: List<WorkJobSummary>,
    val attention: List<WorkAttention>,
    val events: List<WorkEvent>,
    val encodedBytes: Long,
    val actionable: Boolean,
    val unknownEnums: List<WorkUnknownEnum>,
)

sealed interface WorkContractParseResult {
    data class Verified(val page: WorkSyncPage) : WorkContractParseResult
    data class Incompatible(val minimum: Long) : WorkContractParseResult
    data class Invalid(val message: String) : WorkContractParseResult
}

data class WorkCursorResetData(
    val reason: String?,
    val ledgerId: String?,
    val eventFloor: Long?,
    val highWater: Long?,
)

data class WorkCursorReset(
    val code: Int,
    val message: String,
    val data: WorkCursorResetData,
)

sealed interface WorkCursorResetParseResult {
    data class Verified(val reset: WorkCursorReset) : WorkCursorResetParseResult
    data class Invalid(val message: String) : WorkCursorResetParseResult
}

/** Raised only by direct DTO decoders; page/reset entry points return Invalid instead. */
class WorkContractDecodeException(message: String) : IllegalArgumentException(message)

private fun fail(message: String): Nothing = throw WorkContractDecodeException(message)

private fun JsonObject.required(key: String, path: String): JsonElement {
    if (!containsKey(key)) fail("$path.$key is required, including when its value is null.")
    return getValue(key)
}

private fun asObject(value: JsonElement, path: String): JsonObject =
    value as? JsonObject ?: fail("$path must be an object.")

private fun asArray(value: JsonElement, path: String): JsonArray =
    value as? JsonArray ?: fail("$path must be an array.")

private fun stringValue(
    value: JsonElement,
    path: String,
    maximumCodePoints: Int? = null,
    nonempty: Boolean = true,
): String {
    val primitive = value as? JsonPrimitive
        ?: fail("$path must be a string.")
    if (!primitive.isString) fail("$path must be a string.")
    val result = primitive.content
    if (nonempty && result.trim().isEmpty()) fail("$path must be a non-empty string.")
    if (maximumCodePoints != null && result.codePointCount(0, result.length) > maximumCodePoints) {
        fail("$path must contain at most $maximumCodePoints characters.")
    }
    return result
}

private fun nullableString(
    value: JsonElement,
    path: String,
    maximumCodePoints: Int? = null,
    nonempty: Boolean = false,
): String? = if (value is JsonNull) null else stringValue(value, path, maximumCodePoints, nonempty)

private fun safeInteger(value: JsonElement, path: String, minimum: Long = 0): Long {
    val primitive = value as? JsonPrimitive ?: fail("$path must be a safe integer greater than or equal to $minimum.")
    if (primitive.isString) fail("$path must be a safe integer greater than or equal to $minimum.")
    val result = primitive.longOrNull
        ?: fail("$path must be a safe integer greater than or equal to $minimum.")
    if (result < minimum || result > FABRIC_WORK_MAXIMUM_SAFE_INTEGER) {
        fail("$path must be a safe integer greater than or equal to $minimum.")
    }
    return result
}

private fun nullableTimestamp(value: JsonElement, path: String): Long? =
    if (value is JsonNull) null else safeInteger(value, path)

private fun booleanValue(value: JsonElement, path: String): Boolean {
    val primitive = value as? JsonPrimitive ?: fail("$path must be a boolean.")
    if (primitive.isString) fail("$path must be a boolean.")
    return primitive.booleanOrNull ?: fail("$path must be a boolean.")
}

private fun workId(value: JsonElement, kind: String, path: String): String {
    val result = stringValue(value, path)
    if (WORK_ID_PATTERNS.getValue(kind).matches(result).not()) {
        fail("$path must be a 128-bit $kind identifier.")
    }
    return result
}

private fun nullableWorkId(value: JsonElement, kind: String, path: String): String? =
    if (value is JsonNull) null else workId(value, kind, path)

private fun jsonObject(value: JsonElement, path: String): JsonObject = asObject(value, path)

private fun jsonByteLength(value: JsonElement): Long = value.toString().toByteArray(Charsets.UTF_8).size.toLong()

private fun enforceByteLimit(value: JsonElement, maximum: Int, path: String) {
    if (jsonByteLength(value) > maximum) fail("$path exceeds its $maximum-byte wire limit.")
}

private fun enumValue(
    value: JsonElement,
    known: Set<String>,
    path: String,
    unknown: MutableList<WorkUnknownEnum>,
): String {
    val result = stringValue(value, path, maximumCodePoints = 128)
    if (result !in known) unknown += WorkUnknownEnum(path, result)
    return result
}

/** Render an unknown compatible enum without making it look like a known action. */
fun displayWorkEnum(value: String, known: Set<String>): String =
    if (value in known) value else "unknown($value)"

private fun parseRunSummary(value: JsonElement, path: String): WorkRunSummary {
    val raw = asObject(value, path)
    val unknown = mutableListOf<WorkUnknownEnum>()
    return WorkRunSummary(
        runId = workId(raw.required("run_id", path), "run", "$path.run_id"),
        attempt = safeInteger(raw.required("attempt", path), "$path.attempt", 1),
        version = safeInteger(raw.required("version", path), "$path.version", 1),
        status = enumValue(raw.required("status", path), WORK_JOB_STATUSES, "$path.status", unknown),
        runtimeKind = enumValue(
            raw.required("runtime_kind", path),
            WORK_RUN_RUNTIME_KINDS,
            "$path.runtime_kind",
            unknown,
        ),
        ownerState = enumValue(
            raw.required("owner_state", path),
            WORK_RUN_OWNER_STATES,
            "$path.owner_state",
            unknown,
        ),
        restartBehavior = enumValue(
            raw.required("restart_behavior", path),
            WORK_RESTART_BEHAVIORS,
            "$path.restart_behavior",
            unknown,
        ),
        claimedAt = nullableTimestamp(raw.required("claimed_at", path), "$path.claimed_at"),
        startedAt = nullableTimestamp(raw.required("started_at", path), "$path.started_at"),
        updatedAt = safeInteger(raw.required("updated_at", path), "$path.updated_at"),
        finishedAt = nullableTimestamp(raw.required("finished_at", path), "$path.finished_at"),
        actionable = unknown.isEmpty(),
        unknownEnums = unknown.toList(),
    )
}

private fun parseJobSummary(value: JsonElement, path: String): WorkJobSummary {
    val raw = asObject(value, path)
    enforceByteLimit(raw, FABRIC_WORK_SUBJECT_MAX_BYTES, path)
    val unknown = mutableListOf<WorkUnknownEnum>()
    val resultPreview = raw.required("result_preview", path)
    val error = raw.required("error", path)
    enforceByteLimit(resultPreview, FABRIC_WORK_RESULT_PREVIEW_MAX_BYTES, "$path.result_preview")
    enforceByteLimit(error, FABRIC_WORK_ERROR_PREVIEW_MAX_BYTES, "$path.error")
    val omittedRaw = raw.required("result_omitted_reason", path)
    val resultOmittedReason = if (omittedRaw is JsonNull) {
        null
    } else {
        enumValue(omittedRaw, WORK_RESULT_OMITTED_REASONS, "$path.result_omitted_reason", unknown)
    }
    if (resultOmittedReason != null && resultPreview !is JsonNull) {
        fail("$path.result_preview must be null when a result is omitted.")
    }
    val runtime = jsonObject(raw.required("runtime", path), "$path.runtime")
    enforceByteLimit(runtime, FABRIC_WORK_SUBJECT_MAX_BYTES, "$path.runtime")
    val currentRunRaw = raw.required("current_run", path)
    val currentRun = if (currentRunRaw is JsonNull) null else parseRunSummary(currentRunRaw, "$path.current_run")
    if (currentRun != null) unknown += currentRun.unknownEnums

    val result = WorkJobSummary(
        jobId = workId(raw.required("job_id", path), "job", "$path.job_id"),
        version = safeInteger(raw.required("version", path), "$path.version", 1),
        kind = enumValue(raw.required("kind", path), WORK_JOB_KINDS, "$path.kind", unknown),
        status = enumValue(raw.required("status", path), WORK_JOB_STATUSES, "$path.status", unknown),
        title = stringValue(raw.required("title", path), "$path.title", 200),
        summary = nullableString(raw.required("summary", path), "$path.summary"),
        source = stringValue(raw.required("source", path), "$path.source", 128),
        sourceSessionKey = nullableString(
            raw.required("source_session_key", path),
            "$path.source_session_key",
            512,
        ),
        runtimeSessionId = nullableString(
            raw.required("runtime_session_id", path),
            "$path.runtime_session_id",
            512,
        ),
        attemptCount = safeInteger(raw.required("attempt_count", path), "$path.attempt_count"),
        openAttentionCount = safeInteger(
            raw.required("open_attention_count", path),
            "$path.open_attention_count",
        ),
        createdAt = safeInteger(raw.required("created_at", path), "$path.created_at"),
        startedAt = nullableTimestamp(raw.required("started_at", path), "$path.started_at"),
        updatedAt = safeInteger(raw.required("updated_at", path), "$path.updated_at"),
        finishedAt = nullableTimestamp(raw.required("finished_at", path), "$path.finished_at"),
        cancelRequestedAt = nullableTimestamp(
            raw.required("cancel_requested_at", path),
            "$path.cancel_requested_at",
        ),
        runtime = runtime,
        currentRun = currentRun,
        resultPreview = resultPreview,
        resultRef = nullableString(raw.required("result_ref", path), "$path.result_ref", 2048),
        resultOmittedReason = resultOmittedReason,
        error = error,
        actionable = unknown.isEmpty(),
        unknownEnums = unknown.toList(),
    )
    if (currentRun != null && currentRun.attempt > result.attemptCount) {
        fail("$path.current_run.attempt cannot exceed attempt_count.")
    }
    return result
}

/** The public after-state fields that a `job.get` detail response must carry. */
private val WORK_JOB_SUMMARY_FIELDS = listOf(
    "job_id",
    "version",
    "kind",
    "status",
    "title",
    "summary",
    "source",
    "source_session_key",
    "runtime_session_id",
    "attempt_count",
    "open_attention_count",
    "created_at",
    "started_at",
    "updated_at",
    "finished_at",
    "cancel_requested_at",
    "runtime",
    "current_run",
    "result_preview",
    "result_ref",
    "result_omitted_reason",
    "error",
)

private fun optionalDetailJson(raw: JsonObject, key: String, path: String): JsonElement? {
    if (!raw.containsKey(key) || raw[key] is JsonNull) return null
    val value = raw.getValue(key)
    enforceByteLimit(value, FABRIC_WORK_JOB_DETAIL_BODY_MAX_BYTES, "$path.$key")
    return value
}

/**
 * Decode a direct `job.get` response without weakening the small public Job
 * boundary used by sync/list/event subjects. Unknown detail keys are additive
 * and ignored; known detail bodies remain non-projection values.
 */
fun decodeWorkJobDetail(value: JsonElement): WorkJobDetail {
    val raw = asObject(value, "work.job_detail")
    val summary = JsonObject(
        WORK_JOB_SUMMARY_FIELDS.associateWith { key ->
            raw.required(key, "work.job_detail")
        },
    )
    val job = parseJobSummary(summary, "work.job_detail")
    val promptPreview = when (val rawPrompt = raw["prompt_preview"]) {
        null, JsonNull -> null
        else -> stringValue(
            rawPrompt,
            "work.job_detail.prompt_preview",
            maximumCodePoints = 1_000,
            nonempty = false,
        )
    }
    val result = optionalDetailJson(raw, "result", "work.job_detail")
    val errorDetail = optionalDetailJson(raw, "error_detail", "work.job_detail")
    if (job.resultOmittedReason != null && result != null) {
        fail("work.job_detail.result must be null when a result is omitted.")
    }
    return WorkJobDetail(
        job = job,
        promptPreview = promptPreview,
        result = result,
        errorDetail = errorDetail,
    )
}

private fun validActionsForKind(kind: String): Set<String> = when (kind) {
    "approval" -> setOf("once", "session", "always", "deny")
    "clarify", "sudo", "secret" -> setOf("submit", "cancel")
    else -> emptySet()
}

private fun parseAttention(value: JsonElement, path: String): WorkAttention {
    val raw = asObject(value, path)
    enforceByteLimit(raw, FABRIC_WORK_SUBJECT_MAX_BYTES, path)
    val unknown = mutableListOf<WorkUnknownEnum>()
    val kind = enumValue(raw.required("kind", path), WORK_ATTENTION_KINDS, "$path.kind", unknown)
    val state = enumValue(raw.required("state", path), WORK_ATTENTION_STATES, "$path.state", unknown)
    val actions = asArray(raw.required("allowed_actions", path), "$path.allowed_actions").mapIndexed { index, item ->
        enumValue(item, WORK_ATTENTION_ACTIONS, "$path.allowed_actions[$index]", unknown)
    }
    if (actions.toSet().size != actions.size) fail("$path.allowed_actions must not contain duplicates.")
    val validActions = validActionsForKind(kind)
    val containsUnknownEnum = unknown.isNotEmpty()
    if (!containsUnknownEnum && validActions.isNotEmpty() && actions.any { it !in validActions }) {
        fail("$path.allowed_actions contains an action invalid for $kind.")
    }
    if (!containsUnknownEnum && state == "pending" && validActions.isNotEmpty() && actions.isEmpty()) {
        fail("$path.allowed_actions cannot be empty while Attention is pending.")
    }
    if (!containsUnknownEnum && state != "pending" && actions.isNotEmpty()) {
        fail("$path.allowed_actions must be empty when Attention is not pending.")
    }
    val publicPayload = jsonObject(raw.required("public_payload", path), "$path.public_payload")
    enforceByteLimit(publicPayload, FABRIC_WORK_SUBJECT_MAX_BYTES, "$path.public_payload")
    return WorkAttention(
        attentionId = workId(raw.required("attention_id", path), "attention", "$path.attention_id"),
        version = safeInteger(raw.required("version", path), "$path.version", 1),
        jobId = nullableWorkId(raw.required("job_id", path), "job", "$path.job_id"),
        runId = nullableWorkId(raw.required("run_id", path), "run", "$path.run_id"),
        sourceSessionKey = nullableString(
            raw.required("source_session_key", path),
            "$path.source_session_key",
            512,
        ),
        runtimeSessionId = nullableString(
            raw.required("runtime_session_id", path),
            "$path.runtime_session_id",
            512,
        ),
        requestId = stringValue(raw.required("request_id", path), "$path.request_id", 128),
        kind = kind,
        state = state,
        blocking = booleanValue(raw.required("blocking", path), "$path.blocking"),
        sensitive = booleanValue(raw.required("sensitive", path), "$path.sensitive"),
        title = stringValue(raw.required("title", path), "$path.title", 200),
        publicPayload = publicPayload,
        allowedActions = actions,
        createdAt = safeInteger(raw.required("created_at", path), "$path.created_at"),
        updatedAt = safeInteger(raw.required("updated_at", path), "$path.updated_at"),
        expiresAt = nullableTimestamp(raw.required("expires_at", path), "$path.expires_at"),
        resolvedAt = nullableTimestamp(raw.required("resolved_at", path), "$path.resolved_at"),
        terminalReason = nullableString(
            raw.required("terminal_reason", path),
            "$path.terminal_reason",
            256,
        ),
        actionable = unknown.isEmpty() && state == "pending",
        unknownEnums = unknown.toList(),
    )
}

private fun parseUnknownSubject(value: JsonElement, path: String, subjectType: String): WorkUnknownSubject =
    WorkUnknownSubject(
        raw = jsonObject(value, path),
        unknownEnums = listOf(WorkUnknownEnum("$path.subject_type", subjectType)),
    )

private fun parseEvent(value: JsonElement, path: String): WorkEvent {
    val raw = asObject(value, path)
    enforceByteLimit(raw, FABRIC_WORK_SUBJECT_MAX_BYTES, path)
    val unknown = mutableListOf<WorkUnknownEnum>()
    val subjectType = enumValue(
        raw.required("subject_type", path),
        WORK_SUBJECT_TYPES,
        "$path.subject_type",
        unknown,
    )
    val subjectId = stringValue(raw.required("subject_id", path), "$path.subject_id", 128)
    when (subjectType) {
        "job" -> workId(JsonPrimitive(subjectId), "job", "$path.subject_id")
        "attention" -> workId(JsonPrimitive(subjectId), "attention", "$path.subject_id")
    }
    val subjectVersion = safeInteger(raw.required("subject_version", path), "$path.subject_version", 1)
    val tombstone = booleanValue(raw.required("tombstone", path), "$path.tombstone")
    val subjectRaw = raw.required("subject", path)
    val subject: WorkEventSubject? = if (tombstone) {
        if (subjectRaw !is JsonNull) fail("$path.subject must be null for a tombstone.")
        null
    } else {
        if (subjectRaw is JsonNull) fail("$path.subject is required for a live event.")
        val parsed = when (subjectType) {
            "job" -> parseJobSummary(subjectRaw, "$path.subject")
            "attention" -> parseAttention(subjectRaw, "$path.subject")
            else -> parseUnknownSubject(subjectRaw, "$path.subject", subjectType)
        }
        val actualId = when (parsed) {
            is WorkJobSummary -> parsed.jobId
            is WorkAttention -> parsed.attentionId
            is WorkUnknownSubject -> subjectId
        }
        val actualVersion = when (parsed) {
            is WorkJobSummary -> parsed.version
            is WorkAttention -> parsed.version
            is WorkUnknownSubject -> subjectVersion
        }
        if (actualId != subjectId || actualVersion != subjectVersion) {
            fail("$path.subject must match subject_id and subject_version.")
        }
        unknown += parsed.unknownEnums
        parsed
    }
    return WorkEvent(
        eventId = safeInteger(raw.required("event_id", path), "$path.event_id", 1),
        eventType = stringValue(raw.required("event_type", path), "$path.event_type", 128),
        subjectType = subjectType,
        subjectId = subjectId,
        jobId = nullableWorkId(raw.required("job_id", path), "job", "$path.job_id"),
        runId = nullableWorkId(raw.required("run_id", path), "run", "$path.run_id"),
        subjectVersion = subjectVersion,
        subject = subject,
        tombstone = tombstone,
        createdAt = safeInteger(raw.required("created_at", path), "$path.created_at"),
        actionable = unknown.isEmpty() && (tombstone || subject?.actionable == true),
        unknownEnums = unknown.toList(),
    )
}

private sealed interface ParsedContract {
    data class Verified(val descriptor: WorkContractDescriptor) : ParsedContract
    data class Incompatible(val minimum: Long) : ParsedContract
}

private fun parseContract(raw: JsonObject): ParsedContract {
    val contract = asObject(raw.required("contract", "work"), "work.contract")
    if (stringValue(contract.required("name", "work.contract"), "work.contract.name") != "fabric.work") {
        fail("work.contract.name must be fabric.work.")
    }
    val version = safeInteger(contract.required("version", "work.contract"), "work.contract.version", 1)
    val minimum = safeInteger(
        contract.required("min_compatible", "work.contract"),
        "work.contract.min_compatible",
        1,
    )
    if (minimum > version) fail("work.contract.min_compatible cannot exceed contract.version.")
    if (minimum > FABRIC_WORK_CLIENT_CONTRACT_VERSION) return ParsedContract.Incompatible(minimum)
    return ParsedContract.Verified(WorkContractDescriptor("fabric.work", version, minimum))
}

/**
 * Parse and normalize one complete authoritative `job.sync` page.
 *
 * [encodedBytes] is useful when a transport has already measured the exact
 * payload. Both it and the normalized JSON must remain below the wire limit.
 */
fun parseWorkSyncPage(value: JsonElement, encodedBytes: Long? = null): WorkContractParseResult {
    return try {
    val measuredBytes = jsonByteLength(value)
    val reportedBytes = encodedBytes ?: measuredBytes
    if (reportedBytes < 0 || reportedBytes > FABRIC_WORK_SYNC_MAX_BYTES || measuredBytes > FABRIC_WORK_SYNC_MAX_BYTES) {
        fail("work sync page exceeds its $FABRIC_WORK_SYNC_MAX_BYTES-byte wire limit.")
    }
    val raw = asObject(value, "work")
    val contract = when (val parsed = parseContract(raw)) {
        is ParsedContract.Incompatible -> return WorkContractParseResult.Incompatible(parsed.minimum)
        is ParsedContract.Verified -> parsed.descriptor
    }
    val unknown = mutableListOf<WorkUnknownEnum>()
    val mode = enumValue(raw.required("mode", "work"), WORK_SYNC_MODES, "work.mode", unknown)
    val watermark = safeInteger(raw.required("watermark", "work"), "work.watermark")
    val cursor = safeInteger(raw.required("cursor", "work"), "work.cursor")
    if (cursor > watermark) fail("work.cursor cannot exceed work.watermark.")
    val hasMore = booleanValue(raw.required("has_more", "work"), "work.has_more")
    val nextPageToken = nullableString(raw.required("next_page_token", "work"), "work.next_page_token", 4096, true)
    val jobs = asArray(raw.required("jobs", "work"), "work.jobs").mapIndexed { index, item ->
        parseJobSummary(item, "work.jobs[$index]")
    }
    val attention = asArray(raw.required("attention", "work"), "work.attention").mapIndexed { index, item ->
        parseAttention(item, "work.attention[$index]")
    }
    val events = asArray(raw.required("events", "work"), "work.events").mapIndexed { index, item ->
        parseEvent(item, "work.events[$index]")
    }

    when (mode) {
        "bootstrap" -> {
            if (events.isNotEmpty()) fail("bootstrap pages cannot contain events.")
            if (jobs.size + attention.size > FABRIC_WORK_SYNC_MAX_ITEMS) {
                fail("bootstrap pages cannot exceed $FABRIC_WORK_SYNC_MAX_ITEMS subjects.")
            }
            if (cursor != watermark) fail("bootstrap page cursor must equal its fixed watermark.")
            if (hasMore != (nextPageToken != null)) {
                fail("bootstrap has_more must match next_page_token presence.")
            }
        }
        "delta" -> {
            if (jobs.isNotEmpty() || attention.isNotEmpty()) {
                fail("delta pages carry subjects only inside events.")
            }
            if (events.size > FABRIC_WORK_SYNC_MAX_ITEMS) {
                fail("delta pages cannot exceed $FABRIC_WORK_SYNC_MAX_ITEMS events.")
            }
            if (nextPageToken != null) fail("delta next_page_token must be null.")
            if (hasMore && events.isEmpty()) {
                fail("a truncated delta page must advance with at least one event.")
            }
            if (!hasMore && cursor != watermark) {
                fail("a complete delta page cursor must equal its watermark.")
            }
            var previousEventId = 0L
            for (event in events) {
                if (event.eventId <= previousEventId) fail("delta event_id values must be strictly increasing.")
                if (event.eventId > cursor) fail("delta events cannot exceed the returned cursor.")
                previousEventId = event.eventId
            }
            if (events.isNotEmpty() && events.last().eventId != cursor) {
                fail("a delta cursor must equal its final event_id.")
            }
        }
    }

    if (jobs.map { it.jobId }.toSet().size != jobs.size) fail("work.jobs contains a duplicate job_id.")
    if (attention.map { it.attentionId }.toSet().size != attention.size) {
        fail("work.attention contains a duplicate attention_id.")
    }
    WorkContractParseResult.Verified(
        WorkSyncPage(
            contract = contract,
            ledgerId = workId(raw.required("ledger_id", "work"), "ledger", "work.ledger_id"),
            workProfileId = workId(
                raw.required("work_profile_id", "work"),
                "profile",
                "work.work_profile_id",
            ),
            mode = mode,
            watermark = watermark,
            cursor = cursor,
            hasMore = hasMore,
            nextPageToken = nextPageToken,
            jobs = jobs,
            attention = attention,
            events = events,
            encodedBytes = reportedBytes,
            actionable = unknown.isEmpty(),
            unknownEnums = unknown.toList(),
        ),
    )
    } catch (error: Exception) {
        WorkContractParseResult.Invalid(
            (error as? WorkContractDecodeException)?.message ?: "Work sync page is malformed.",
        )
    }
}

/** Parse the sanitized `cursor_expired` error body returned by `job.sync`. */
fun parseWorkCursorReset(value: JsonElement): WorkCursorResetParseResult = try {
    val raw = asObject(value, "work reset")
    if (safeInteger(raw.required("code", "work reset"), "work reset.code", -32047) != -32047L) {
        fail("work reset.code must be -32047.")
    }
    val data = asObject(raw.required("data", "work reset"), "work reset.data")
    if (stringValue(data.required("code", "work reset.data"), "work reset.data.code") != "cursor_expired") {
        fail("work reset.data.code must be cursor_expired.")
    }
    if (!booleanValue(data.required("bootstrap", "work reset.data"), "work reset.data.bootstrap")) {
        fail("work reset.data.bootstrap must be true.")
    }
    fun optionalInteger(key: String): Long? = if (!data.containsKey(key) || data[key] is JsonNull) {
        null
    } else {
        safeInteger(data.getValue(key), "work reset.data.$key")
    }
    fun optionalString(key: String): String? = if (!data.containsKey(key) || data[key] is JsonNull) {
        null
    } else {
        stringValue(data.getValue(key), "work reset.data.$key", 128)
    }
    val ledgerId = if (!data.containsKey("ledger_id") || data["ledger_id"] is JsonNull) {
        null
    } else {
        workId(data.getValue("ledger_id"), "ledger", "work reset.data.ledger_id")
    }
    val eventFloor = optionalInteger("event_floor")
    val highWater = optionalInteger("high_water")
    if (eventFloor != null && highWater != null && eventFloor > highWater + 1) {
        fail("work reset event_floor cannot exceed high_water + 1.")
    }
    WorkCursorResetParseResult.Verified(
        WorkCursorReset(
            code = -32047,
            message = stringValue(raw.required("message", "work reset"), "work reset.message", 512),
            data = WorkCursorResetData(
                reason = optionalString("reason"),
                ledgerId = ledgerId,
                eventFloor = eventFloor,
                highWater = highWater,
            ),
        ),
    )
} catch (error: Exception) {
    WorkCursorResetParseResult.Invalid(
        (error as? WorkContractDecodeException)?.message ?: "Work cursor reset is malformed.",
    )
}

/** Direct decoders are used by typed get/list/mutation RPC receipts. */
fun decodeWorkJobSummary(value: JsonElement): WorkJobSummary = parseJobSummary(value, "work.job")

fun decodeWorkJobId(value: JsonElement): String = workId(value, "job", "work.job_id")

fun decodeWorkProfileId(value: JsonElement): String = workId(value, "profile", "work.work_profile_id")

fun decodeWorkLedgerId(value: JsonElement): String = workId(value, "ledger", "work.ledger_id")

fun decodeWorkMutationId(value: JsonElement): String = workId(value, "mutation", "work.mutation_id")

fun decodeWorkAttentionId(value: JsonElement): String = workId(value, "attention", "work.attention_id")

fun decodeWorkAttention(value: JsonElement): WorkAttention = parseAttention(value, "work.attention")

fun decodeWorkEvent(value: JsonElement): WorkEvent = parseEvent(value, "work.event")
