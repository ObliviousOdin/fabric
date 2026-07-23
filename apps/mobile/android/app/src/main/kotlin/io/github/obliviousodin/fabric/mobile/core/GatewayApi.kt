package io.github.obliviousodin.fabric.mobile.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/** Row shape returned by the `session.list` RPC (tui_gateway/server.py). */
data class SessionSummary(
    val id: String,
    val title: String,
    val preview: String,
    val startedAt: Double,
    val messageCount: Int,
    val source: String,
) {
    val displayTitle: String
        get() = title.ifEmpty { preview.ifEmpty { "Untitled session" } }
}

/** One visible transcript row returned in `session.resume.messages`. */
data class SessionTranscriptMessage(
    val role: Role,
    val text: String,
    val reasoning: String? = null,
) {
    enum class Role { USER, ASSISTANT, SYSTEM, TOOL }

    companion object {
        internal fun fromJson(payload: JsonObject): SessionTranscriptMessage? {
            val role = when (payload.string("role")) {
                "user" -> Role.USER
                "assistant" -> Role.ASSISTANT
                "system" -> Role.SYSTEM
                "tool" -> Role.TOOL
                else -> return null
            }
            val text = if (role == Role.TOOL) {
                payload.string("context") ?: payload.string("name")
            } else {
                payload.string("text") ?: payload.string("content")
            }.orEmpty()
            val reasoning = if (role == Role.ASSISTANT) {
                listOf("reasoning", "reasoning_content", "reasoning_details", "codex_reasoning_items")
                    .firstNotNullOfOrNull { key -> reasoningText(payload[key]) }
            } else {
                null
            }
            if (text.isBlank() && reasoning.isNullOrBlank()) return null
            return SessionTranscriptMessage(role = role, text = text, reasoning = reasoning)
        }

        private fun reasoningText(value: JsonElement?): String? = when (value) {
            is JsonNull -> null
            is JsonPrimitive -> value.content.takeIf { it.isNotBlank() }
            is JsonArray -> value.mapNotNull(::reasoningText)
                .takeIf { it.isNotEmpty() }
                ?.joinToString("\n")
            is JsonObject -> {
                listOf("text", "summary", "content", "reasoning")
                    .firstNotNullOfOrNull { key -> reasoningText(value[key]) }
                    ?: value.toString().takeIf { value.isNotEmpty() }
            }
            else -> null
        }
    }
}

/** Current turn returned by `session.resume.inflight` while the agent is active. */
data class SessionInflight(
    val user: String,
    val assistant: String,
    val streaming: Boolean,
) {
    companion object {
        internal fun fromJson(payload: JsonObject): SessionInflight? {
            val inflight = SessionInflight(
                user = payload.string("user").orEmpty(),
                assistant = payload.string("assistant").orEmpty(),
                streaming = (payload["streaming"] as? JsonPrimitive)?.booleanOrNull ?: false,
            )
            return inflight.takeIf { it.user.isNotEmpty() || it.assistant.isNotEmpty() || it.streaming }
        }
    }
}

/**
 * The opaque Work namespace selected by the gateway for one session. This is
 * a validated server identity, never a display-profile name, URL, or local
 * session-key inference.
 */
class FabricWorkSessionIdentity private constructor(
    val profileId: String,
) {
    companion object {
        /** A missing or malformed identity is deliberately unavailable. */
        fun fromSessionInfo(payload: JsonObject): FabricWorkSessionIdentity? = runCatching {
            val value = payload["work_profile_id"]
                ?: throw WorkContractDecodeException("session.info is missing work_profile_id.")
            FabricWorkSessionIdentity(decodeWorkProfileId(value))
        }.getOrNull()
    }

    fun syncScope(gatewayId: String): WorkSyncScope? {
        if (gatewayId.trim().isEmpty()) return null
        return WorkSyncScope(gatewayId = gatewayId, profileId = profileId)
    }

    override fun equals(other: Any?): Boolean =
        other is FabricWorkSessionIdentity && other.profileId == profileId

    override fun hashCode(): Int = profileId.hashCode()

    override fun toString(): String = "FabricWorkSessionIdentity(profileId=<redacted>)"
}

/** Result of `session.create` / `session.resume`. */
data class LiveSession(
    val sessionId: String,
    val storedSessionId: String?,
    val messages: List<SessionTranscriptMessage> = emptyList(),
    val running: Boolean = false,
    val inflight: SessionInflight? = null,
    val historyVersion: Int? = null,
    val pendingInteractions: List<GatewayEvent> = emptyList(),
    /** Validated from `session.info.work_profile_id`, never inferred locally. */
    val workIdentity: FabricWorkSessionIdentity? = null,
) {
    companion object {
        internal fun fromResumePayload(
            payload: JsonObject,
            storedSessionId: String,
        ): LiveSession {
            val rows = (payload["messages"] as? JsonArray).orEmpty()
            return LiveSession(
                sessionId = payload.string("session_id") ?: storedSessionId,
                storedSessionId = payload.string("session_key")
                    ?: payload.string("stored_session_id")
                    ?: payload.string("resumed")
                    ?: storedSessionId,
                messages = rows.mapNotNull { row ->
                    (row as? JsonObject)?.let { SessionTranscriptMessage.fromJson(it) }
                },
                running = (payload["running"] as? JsonPrimitive)?.booleanOrNull ?: false,
                inflight = (payload["inflight"] as? JsonObject)?.let { SessionInflight.fromJson(it) },
                historyVersion = (payload["history_version"] as? JsonPrimitive)?.intOrNull,
                pendingInteractions = (payload["pending_interactions"] as? JsonArray)
                    .orEmpty()
                    .mapNotNull { interaction ->
                        val objectValue = interaction as? JsonObject ?: return@mapNotNull null
                        val type = objectValue.string("type") ?: return@mapNotNull null
                        GatewayEvent(
                            type = type,
                            sessionId = payload.string("session_id") ?: storedSessionId,
                            payload = objectValue["payload"] as? JsonObject ?: JsonObject(emptyMap()),
                        )
                    },
                workIdentity = (payload["info"] as? JsonObject)
                    ?.let(FabricWorkSessionIdentity::fromSessionInfo),
            )
        }
    }
}

/**
 * Row shape returned by `session.active_list` — live in-memory sessions on
 * the gateway, unlike the historical `session.list`
 * (`_session_live_item` in tui_gateway/server.py).
 */
data class ActiveSession(
    val id: String,
    val sessionKey: String,
    val title: String,
    val preview: String,
    /** "working" | "waiting" | "starting" | "idle" (`_session_live_status`). */
    val status: String,
    val model: String,
    val messageCount: Int,
    val lastActive: Double,
    val current: Boolean,
) {
    companion object {
        internal fun fromJson(payload: JsonObject): ActiveSession? {
            val id = payload.string("id") ?: return null
            return ActiveSession(
                id = id,
                sessionKey = payload.string("session_key") ?: id,
                title = payload.string("title").orEmpty(),
                preview = payload.string("preview").orEmpty(),
                status = payload.string("status") ?: "idle",
                model = payload.string("model").orEmpty(),
                messageCount = (payload["message_count"] as? JsonPrimitive)?.intOrNull ?: 0,
                lastActive = (payload["last_active"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                current = (payload["current"] as? JsonPrimitive)?.booleanOrNull ?: false,
            )
        }
    }
}

/** One slash command from `commands.catalog` (name includes the leading `/`). */
data class SlashCommand(
    val name: String,
    val detail: String,
)

/** A category of slash commands, in the catalog's display order. */
data class SlashCommandCategory(
    val name: String,
    val commands: List<SlashCommand>,
)

/** A read-only screen capture from `computer.screenshot`. */
data class ScreenCapture(
    val pngBase64: String,
    val width: Int,
    val height: Int,
)

/**
 * Row shape from `process.list` — background processes owned by a session
 * (`_session_processes` / tools/process_registry.py).
 */
data class BackgroundProcess(
    val id: String,
    val command: String,
    val pid: Int,
    /** "running" | "exited". */
    val status: String,
    val uptimeSeconds: Int,
    val outputTail: String,
)

/**
 * Public body of `GET /api/status`. `authRequired` distinguishes a gated
 * gateway (provider login + WS tickets) from direct token auth
 * (`authModeFromStatus` in apps/desktop/electron/connection-config.ts).
 */
data class GatewayStatus(val authRequired: Boolean)

const val GATEWAY_CLIENT_CONTRACT_VERSION = 1
const val GATEWAY_CAPABILITY_CONTRACT_NAME = "fabric.gateway"

/**
 * Methods shipped by the first mobile clients, before capability negotiation
 * existed. Only a `-32601 Method not found` response from
 * `gateway.capabilities` enables this compatibility set.
 */
val LEGACY_MOBILE_METHODS = setOf(
    "session.create",
    "session.resume",
    "session.list",
    "session.active_list",
    "session.close",
    "prompt.submit",
    "prompt.background",
    "session.steer",
    "session.interrupt",
    "approval.respond",
    "clarify.respond",
    "sudo.respond",
    "secret.respond",
    "commands.catalog",
    "slash.exec",
    "process.list",
    "process.kill",
    "computer.screenshot",
)

private val REQUIRED_MOBILE_SESSION_METHODS = setOf(
    "session.create",
    "session.resume",
    "session.list",
    "prompt.submit",
)

// Gateway-host voice RPCs are intentionally absent: they record and play on
// the gateway machine, not this phone. Phone voice needs its own wire contract.
val GATEWAY_FEATURE_METHODS = mapOf(
    "automation" to setOf("cron.manage"),
    "background_work" to setOf(
        "session.active_list",
        "prompt.background",
        "session.steer",
    ),
    "baseline_chat" to REQUIRED_MOBILE_SESSION_METHODS,
    "code_session_baseline" to setOf(
        "projects.discover_repos",
        "session.branch",
        "session.undo",
    ),
    "delegation" to setOf("delegation.status", "spawn_tree.list"),
    "files" to setOf("image.attach_bytes", "pdf.attach", "file.attach"),
    "handoff" to setOf("handoff.request"),
    "live_view" to setOf("visual.status", "visual.frame"),
)

/**
 * `durable_work` is an additive gate. Its absence is deliberately false so a
 * current Android client can still connect to a gateway that predates FMB-002.
 * This list does not advertise anything: it only verifies a server that chose
 * to advertise the feature against its complete RPC surface.
 */
val DURABLE_WORK_GATEWAY_METHODS = setOf(
    "job.create",
    "job.sync",
    "job.get",
    "job.list",
    "job.events",
    "job.cancel",
    "attention.get",
    "attention.list",
    "attention.respond",
)

/**
 * Additive feature gates introduced after the original version-1 fixture.
 * Their absence means "not advertised" so an older gateway remains a valid
 * version-1 peer; when present, the same method/feature invariant applies.
 */
val OPTIONAL_GATEWAY_FEATURE_METHODS = mapOf(
    "artifact_fetch" to setOf("artifact.list", "artifact.fetch"),
    "connected_nodes" to setOf("node.list", "node.revoke"),
    "device_node" to setOf("node.enroll"),
    "durable_work" to DURABLE_WORK_GATEWAY_METHODS,
    "node_invoke" to setOf("node.announce", "node.result", "node.reject"),
    "pets" to setOf(
        "pet.info",
        "pet.info.meta",
        "pet.gallery",
        "pet.select",
        "pet.disable",
        "pet.thumb",
    ),
    "push" to setOf("push.register_device", "push.deregister_device"),
    "session_admin" to setOf("session.rename", "session.archive"),
    "session_transcript" to setOf("session.transcript"),
    "trust_center" to setOf(
        "trust.audit.list",
        "grant.list",
        "grant.create",
        "grant.revoke",
    ),
    "workspace_read" to setOf("fs.list", "fs.read"),
)

/**
 * Optional features advertised as a bare boolean with no dedicated methods
 * (scoped_grants extends approval.respond params), so no method/feature
 * consistency check applies. Absence still means "not advertised" -> false.
 */
val OPTIONAL_GATEWAY_FEATURE_FLAGS = setOf("scoped_grants")

data class GatewayExecutionContract(
    val location: String,
    val toolExecution: String,
    val survivesClientDisconnect: Boolean,
    val survivesGatewayRestart: Boolean,
    val requiresGatewayHostOnline: Boolean,
)

data class GatewayCapabilities(
    val contractVersion: Int,
    val minimumCompatibleVersion: Int,
    val serverVersion: String,
    val releaseDate: String,
    val execution: GatewayExecutionContract,
    val features: Map<String, Boolean>,
    val methods: Set<String>,
)

/** Result of negotiating the authenticated mobile JSON-RPC contract. */
sealed interface GatewayCapabilityNegotiation {
    data object Negotiating : GatewayCapabilityNegotiation
    data class Verified(val capabilities: GatewayCapabilities) : GatewayCapabilityNegotiation
    data object Legacy : GatewayCapabilityNegotiation
    data class Incompatible(val minimumCompatibleVersion: Int) : GatewayCapabilityNegotiation
    data class Invalid(val reason: String) : GatewayCapabilityNegotiation
}

/**
 * Registered method support is intentionally separate from runtime readiness:
 * a gateway can advertise `computer.screenshot` while its computer backend is
 * unavailable. RPC errors remain the source of truth for host readiness.
 */
fun GatewayCapabilityNegotiation?.supportsGatewayMethod(method: String): Boolean = when (this) {
    is GatewayCapabilityNegotiation.Verified -> method in capabilities.methods
    GatewayCapabilityNegotiation.Legacy -> method in LEGACY_MOBILE_METHODS
    else -> false
}

/**
 * Durable Work calls are never inferred just because one new RPC happens to
 * exist. The server must explicitly advertise the complete reviewed feature.
 */
fun GatewayCapabilityNegotiation?.supportsDurableWork(): Boolean = when (this) {
    is GatewayCapabilityNegotiation.Verified ->
        capabilities.features["durable_work"] == true &&
            capabilities.methods.containsAll(DURABLE_WORK_GATEWAY_METHODS)
    else -> false
}

/**
 * Whether a feature family is usable on this gateway. Mirrors the durable_work
 * precedent: an optional family only exists when a verified contract advertises
 * it true — a legacy gateway predates every optional family, and an
 * incompatible or invalid contract fails closed, even when the raw method
 * names would appear to overlap.
 */
fun GatewayCapabilityNegotiation?.supportsGatewayFeature(feature: String): Boolean = when (this) {
    is GatewayCapabilityNegotiation.Verified -> capabilities.features[feature] == true
    else -> false
}

class FabricWorkUnavailableException : IllegalStateException(
    "This gateway has not advertised the complete durable Work protocol.",
)

class FabricWorkIncompatibleException(val minimum: Long) : IllegalStateException(
    "This gateway requires fabric.work contract $minimum or newer.",
)

class FabricWorkInvalidResponseException(message: String) : IllegalStateException(message)

class FabricWorkCursorResetException(val reset: WorkCursorReset) : IllegalStateException(reset.message)

data class WorkJobMutationReceipt(
    val job: WorkJobSummary,
    val mutationId: String,
    val replayed: Boolean,
    val runtimeStarted: Boolean?,
    val taskId: String?,
)

data class WorkAttentionMutationReceipt(
    val attentionId: String,
    val attentionVersion: Long,
    val delivered: Boolean,
    val mutationId: String,
    val replayed: Boolean,
    val state: String,
)

data class WorkJobListResponse(
    val workProfileId: String,
    val jobs: List<WorkJobSummary>,
    val nextBefore: String?,
)

data class WorkAttentionListResponse(
    val workProfileId: String,
    val attention: List<WorkAttention>,
    val nextBefore: String?,
)

data class WorkJobEventsResponse(
    val workProfileId: String,
    val cursor: Long,
    val events: List<WorkEvent>,
)

fun GatewayCapabilityNegotiation?.allowsBaselineSessionCalls(): Boolean = when (this) {
    is GatewayCapabilityNegotiation.Verified ->
        capabilities.methods.containsAll(REQUIRED_MOBILE_SESSION_METHODS)
    GatewayCapabilityNegotiation.Legacy -> true
    else -> false
}

fun GatewayCapabilityNegotiation.blockingMessage(): String? = when (this) {
    is GatewayCapabilityNegotiation.Incompatible ->
        "Update Fabric Mobile to connect. This gateway requires mobile contract " +
            "$minimumCompatibleVersion or newer."
    is GatewayCapabilityNegotiation.Invalid ->
        "This gateway returned an invalid capability contract: $reason"
    else -> null
}

/** Row from `GET /api/auth/providers` (gated gateways only). */
data class AuthProviderInfo(
    val name: String,
    val displayName: String,
    val supportsPassword: Boolean,
    /** Provider requires a TOTP second factor — show a code field. */
    val requiresTotp: Boolean,
)

class GatewayHttpException(message: String, val statusCode: Int? = null) : Exception(message)

/**
 * Typed wrappers around the raw JSON-RPC client for the methods the mobile
 * slice uses. Method names and parameter shapes mirror the desktop
 * renderer's call sites (use-session-actions, use-prompt-actions).
 */
class GatewayApi(val client: JsonRpcGatewayClient) {

    companion object {
        private val json = Json { ignoreUnknownKeys = true }
        private val probeClient = OkHttpClient()

        /** Public liveness probe; also classifies the gateway's auth mode. */
        suspend fun probeStatus(baseUrl: String): GatewayStatus = withContext(Dispatchers.IO) {
            val url = normalizedBase(baseUrl).newBuilder()
                .addPathSegments("api/status")
                .build()
            val request = Request.Builder().url(url).get().build()
            probeClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    throw GatewayHttpException(
                        "HTTP ${response.code}: ${response.body?.string().orEmpty()}",
                        response.code,
                    )
                }
                val body = response.body?.string().orEmpty()
                val parsed = runCatching { json.parseToJsonElement(body).jsonObject }.getOrNull()
                val authRequired =
                    (parsed?.get("auth_required") as? JsonPrimitive)?.booleanOrNull ?: false
                GatewayStatus(authRequired = authRequired)
            }
        }

        /**
         * `ws(s)://host[/prefix]/api/ws?token=…` — the token-mode WS URL,
         * same construction as `buildGatewayWsUrl` in the desktop config.
         */
        fun websocketUrl(baseUrl: String, token: String): String =
            websocketUrl(baseUrl, "token" to token)

        /**
         * `ws(s)://…/api/ws?ticket=…` — the gated-mode WS URL. Tickets are
         * single-use with a 30s TTL: mint one immediately before every connect.
         */
        fun websocketUrlWithTicket(baseUrl: String, ticket: String): String =
            websocketUrl(baseUrl, "ticket" to ticket)

        private fun websocketUrl(baseUrl: String, authParam: Pair<String, String>): String {
            val base = normalizedBase(baseUrl)
            val wsScheme = if (base.scheme == "https") "wss" else "ws"
            val httpUrl = base.newBuilder()
                .addPathSegments("api/ws")
                .addQueryParameter(authParam.first, authParam.second)
                .build()
            // OkHttp's newWebSocket accepts http(s) URLs, but keep the ws(s)
            // form for parity with the shared client and easier debugging.
            return httpUrl.toString().replaceFirst(base.scheme, wsScheme)
        }

        private fun normalizedBase(baseUrl: String): HttpUrl {
            val trimmed = baseUrl.trim().trimEnd('/')
            val url = trimmed.toHttpUrlOrNull()
                ?: throw GatewayHttpException("Gateway URL must be http:// or https://")
            // Enforce the local-only cleartext policy at the transport choke
            // point (every probe/WS/auth/ticket call funnels through here), not
            // just at add/scan time in GatewayBaseUrl.parse. This revalidates
            // gateways saved before the network-security config permitted
            // cleartext, so a previously-stored public http:// server is refused
            // at connect instead of silently opening a plaintext socket.
            if (url.scheme == "http" && !GatewayBaseUrl.isLocalOrPrivateHost(url.host)) {
                throw GatewayHttpException(
                    "Plain http is only allowed for a local or private gateway; " +
                        "use https for ${url.host}.",
                )
            }
            return url
        }
    }

    // -- Gated auth (provider login + WS tickets) -----------------------------
    // OkHttp has no cookie handling by default; this client carries the
    // dashboard access and refresh cookies that `/auth/password-login`
    // sets so the ticket mint below is authenticated — mirroring the browser
    // SPA's flow. In-memory only: the session dies with the process and the
    // user signs in again (password persistence is deliberately avoided).
    private val authClient = OkHttpClient.Builder()
        .cookieJar(MemoryCookieJar())
        .build()

    /**
     * Negotiate the mobile control-plane contract immediately after the socket
     * opens and before any session RPC. Legacy mode is entered only when the
     * authenticated server explicitly reports JSON-RPC `-32601`.
     */
    suspend fun capabilities(): GatewayCapabilityNegotiation = try {
        parseGatewayCapabilities(
            client.requestObject(
                "gateway.capabilities",
                timeoutMs = JsonRpcGatewayClient.DEFAULT_CONNECT_TIMEOUT_MS,
            ),
        )
    } catch (error: GatewayRpcException) {
        legacyCapabilityFallback(error) ?: throw error
    }

    // -- Durable Work --------------------------------------------------------
    //
    // These are intentionally typed transport wrappers only. Nothing in the
    // Android UI calls them until the gateway has truthfully advertised the
    // complete feature. In particular, a failed durable call must never fall
    // back to prompt.background: that would risk executing a second intent.

    suspend fun createBackgroundWork(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        text: String,
        title: String,
        idempotencyKey: String,
    ): WorkJobMutationReceipt {
        requireDurableWork(negotiation)
        val runtimeSessionId = requireWorkSessionId(sessionId)
        val prompt = text.trim()
        val resolvedTitle = title.trim()
        if (prompt.isEmpty() || prompt.codePointCount(0, prompt.length) > 200_000) {
            throw IllegalArgumentException("Background work prompt must be 1 to 200000 characters.")
        }
        if (resolvedTitle.isEmpty() || resolvedTitle.codePointCount(0, resolvedTitle.length) > 200) {
            throw IllegalArgumentException("Background work title must be 1 to 200 characters.")
        }
        requireWorkIdempotencyKey(idempotencyKey)
        val receipt = parseWorkJobMutationReceipt(
            client.requestObject(
                "job.create",
                buildJsonObject {
                    put("session_id", runtimeSessionId)
                    put("kind", "background_prompt")
                    put("text", prompt)
                    put("title", resolvedTitle)
                    put("idempotency_key", idempotencyKey)
                },
            ),
        )
        if (receipt.job.kind != "background_prompt" || receipt.job.title != resolvedTitle) {
            throw FabricWorkInvalidResponseException(
                "Job creation receipt did not match the submitted durable intent.",
            )
        }
        return receipt
    }

    /** Fetch and fail-close parse one authoritative bootstrap or delta page. */
    suspend fun syncWork(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        after: Long? = null,
        ledgerId: String? = null,
        limit: Int? = null,
        pageToken: String? = null,
    ): WorkSyncPage {
        requireDurableWork(negotiation)
        val runtimeSessionId = requireWorkSessionId(sessionId)
        if ((after == null) != (ledgerId == null)) {
            throw IllegalArgumentException("ledgerId and after are required together for a Work delta.")
        }
        if (pageToken != null && after != null) {
            throw IllegalArgumentException("A Work bootstrap token cannot be mixed with delta fields.")
        }
        if (limit != null && limit !in 1..FABRIC_WORK_SYNC_MAX_ITEMS) {
            throw IllegalArgumentException("Work sync limit must be between 1 and $FABRIC_WORK_SYNC_MAX_ITEMS.")
        }
        if (
            after != null &&
            (after < 0 || after > FABRIC_WORK_MAXIMUM_SAFE_INTEGER)
        ) {
            throw IllegalArgumentException("Work sync cursor must be a safe non-negative integer.")
        }
        val requestedLedgerId = ledgerId?.let(::requireWorkLedgerId)
        val requestedPageToken = pageToken?.let {
            requireWorkOpaqueString(it, field = "page_token", maximumCodePoints = 4_096)
        }
        val raw = try {
            client.requestObject(
                "job.sync",
                buildJsonObject {
                    put("session_id", runtimeSessionId)
                    if (after != null) put("after", after)
                    if (requestedLedgerId != null) put("ledger_id", requestedLedgerId)
                    if (limit != null) put("limit", limit)
                    if (requestedPageToken != null) put("page_token", requestedPageToken)
                },
            )
        } catch (error: GatewayRpcException) {
            if (error.code == -32047) {
                val reset = parseWorkCursorReset(
                    buildJsonObject {
                        put("code", -32047)
                        put("message", error.message ?: "Work cursor expired.")
                        put("data", error.data ?: JsonNull)
                    },
                )
                if (reset is WorkCursorResetParseResult.Verified) {
                    throw FabricWorkCursorResetException(reset.reset)
                }
            }
            throw error
        }
        return when (val parsed = parseWorkSyncPage(raw)) {
            is WorkContractParseResult.Verified -> parsed.page
            is WorkContractParseResult.Incompatible -> throw FabricWorkIncompatibleException(parsed.minimum)
            is WorkContractParseResult.Invalid -> throw FabricWorkInvalidResponseException(parsed.message)
        }
    }

    suspend fun getWorkJob(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        jobId: String,
    ): WorkJobSummary = getWorkJobDetail(
        negotiation = negotiation,
        sessionId = sessionId,
        jobId = jobId,
    ).job

    /**
     * `job.get` appends bounded bodies to a public Job after-state. Decode
     * those bodies only into this detail DTO; they never enter sync state.
     */
    suspend fun getWorkJobDetail(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        jobId: String,
    ): WorkJobDetail {
        requireDurableWork(negotiation)
        val runtimeSessionId = requireWorkSessionId(sessionId)
        val requestedJobId = requireWorkJobId(jobId)
        val raw = client.requestObject(
            "job.get",
            buildJsonObject {
                put("session_id", runtimeSessionId)
                put("job_id", requestedJobId)
            },
        )
        val detail = decodeWorkValue("Job detail response") {
            decodeWorkJobDetail(raw)
        }
        if (detail.job.jobId != requestedJobId) {
            throw FabricWorkInvalidResponseException("Job response did not match job_id.")
        }
        return detail
    }

    suspend fun listWorkJobs(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        statuses: List<String>? = null,
        kinds: List<String>? = null,
        sourceSessionKey: String? = null,
        limit: Int? = null,
        before: String? = null,
    ): WorkJobListResponse {
        requireDurableWork(negotiation)
        if (limit != null && limit !in 1..100) throw IllegalArgumentException("Work job limit must be 1..100.")
        val runtimeSessionId = requireWorkSessionId(sessionId)
        val requestedStatuses = statuses?.let { requireWorkStringList(it, "statuses") }
        val requestedKinds = kinds?.let { requireWorkStringList(it, "kinds") }
        val requestedSourceSessionKey = sourceSessionKey?.let {
            requireWorkOpaqueString(it, field = "source_session_key", maximumCodePoints = 512)
        }
        val requestedBefore = before?.let {
            requireWorkOpaqueString(it, field = "before", maximumCodePoints = 4_096)
        }
        val result = client.requestObject(
            "job.list",
            buildJsonObject {
                put("session_id", runtimeSessionId)
                if (requestedStatuses != null) put("statuses", JsonArray(requestedStatuses.map { JsonPrimitive(it) }))
                if (requestedKinds != null) put("kinds", JsonArray(requestedKinds.map { JsonPrimitive(it) }))
                if (requestedSourceSessionKey != null) put("source_session_key", requestedSourceSessionKey)
                if (limit != null) put("limit", limit)
                if (requestedBefore != null) put("before", requestedBefore)
            },
        )
        val rows = result["jobs"] as? JsonArray
            ?: throw FabricWorkInvalidResponseException("Work job list is missing jobs.")
        return WorkJobListResponse(
            workProfileId = requireWorkProfileId(result, "Work job list"),
            jobs = rows.mapIndexed { index, value ->
                decodeWorkValue("Work job list item $index") { decodeWorkJobSummary(value) }
            },
            nextBefore = result.optionalWorkString("next_before", "Work job list"),
        )
    }

    suspend fun listWorkEvents(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        after: Long,
        jobId: String? = null,
        limit: Int? = null,
    ): WorkJobEventsResponse {
        requireDurableWork(negotiation)
        val runtimeSessionId = requireWorkSessionId(sessionId)
        if (after < 0 || after > FABRIC_WORK_MAXIMUM_SAFE_INTEGER) {
            throw IllegalArgumentException("Work event cursor must be a safe non-negative integer.")
        }
        if (limit != null && limit !in 1..FABRIC_WORK_SYNC_MAX_ITEMS) {
            throw IllegalArgumentException("Work event limit must be 1..$FABRIC_WORK_SYNC_MAX_ITEMS.")
        }
        val requestedJobId = jobId?.let(::requireWorkJobId)
        val result = client.requestObject(
            "job.events",
            buildJsonObject {
                put("session_id", runtimeSessionId)
                put("after", after)
                if (requestedJobId != null) put("job_id", requestedJobId)
                if (limit != null) put("limit", limit)
            },
        )
        val rows = result["events"] as? JsonArray
            ?: throw FabricWorkInvalidResponseException("Work event list is missing events.")
        return WorkJobEventsResponse(
            workProfileId = requireWorkProfileId(result, "Work event list"),
            cursor = result.requireWorkPositiveOrZeroLong("cursor", "Work event list"),
            events = rows.mapIndexed { index, value ->
                decodeWorkValue("Work event list item $index") { decodeWorkEvent(value) }
            },
        ).also { response ->
            if (response.cursor < after) {
                throw FabricWorkInvalidResponseException("Work event cursor moved backwards.")
            }
            var previous = after
            for (event in response.events) {
                if (event.eventId <= previous || event.eventId > response.cursor) {
                    throw FabricWorkInvalidResponseException(
                        "Work events are not an ordered cursor range.",
                    )
                }
                previous = event.eventId
            }
        }
    }

    suspend fun cancelWorkJob(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        jobId: String,
        expectedVersion: Long,
        idempotencyKey: String,
    ): WorkJobMutationReceipt {
        requireDurableWork(negotiation)
        if (expectedVersion.toLong() !in 1..FABRIC_WORK_MAXIMUM_SAFE_INTEGER) {
            throw IllegalArgumentException("Work Job version must be a positive safe integer.")
        }
        val runtimeSessionId = requireWorkSessionId(sessionId)
        val requestedJobId = requireWorkJobId(jobId)
        requireWorkIdempotencyKey(idempotencyKey)
        val receipt = parseWorkJobMutationReceipt(
            client.requestObject(
                "job.cancel",
                buildJsonObject {
                    put("session_id", runtimeSessionId)
                    put("job_id", requestedJobId)
                    put("expected_version", expectedVersion)
                    put("idempotency_key", idempotencyKey)
                },
            ),
        )
        if (receipt.job.jobId != requestedJobId) {
            throw FabricWorkInvalidResponseException("Work cancel receipt did not match the requested Job.")
        }
        return receipt
    }

    suspend fun getWorkAttention(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        attentionId: String,
    ): WorkAttention {
        requireDurableWork(negotiation)
        val runtimeSessionId = requireWorkSessionId(sessionId)
        val requestedAttentionId = requireWorkAttentionId(attentionId)
        val raw = client.requestObject(
            "attention.get",
            buildJsonObject {
                put("session_id", runtimeSessionId)
                put("attention_id", requestedAttentionId)
            },
        )
        val attention = decodeWorkValue("Attention response") {
            decodeWorkAttention(raw)
        }
        if (attention.attentionId != requestedAttentionId) {
            throw FabricWorkInvalidResponseException("Attention response did not match attention_id.")
        }
        return attention
    }

    suspend fun listWorkAttention(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        states: List<String>? = null,
        kinds: List<String>? = null,
        jobId: String? = null,
        limit: Int? = null,
        before: String? = null,
    ): WorkAttentionListResponse {
        requireDurableWork(negotiation)
        if (limit != null && limit !in 1..100) {
            throw IllegalArgumentException("Work Attention limit must be 1..100.")
        }
        val runtimeSessionId = requireWorkSessionId(sessionId)
        val requestedStates = states?.let { requireWorkStringList(it, "states") }
        val requestedKinds = kinds?.let { requireWorkStringList(it, "kinds") }
        val requestedJobId = jobId?.let(::requireWorkJobId)
        val requestedBefore = before?.let {
            requireWorkOpaqueString(it, field = "before", maximumCodePoints = 4_096)
        }
        val result = client.requestObject(
            "attention.list",
            buildJsonObject {
                put("session_id", runtimeSessionId)
                if (requestedStates != null) put("states", JsonArray(requestedStates.map { JsonPrimitive(it) }))
                if (requestedKinds != null) put("kinds", JsonArray(requestedKinds.map { JsonPrimitive(it) }))
                if (requestedJobId != null) put("job_id", requestedJobId)
                if (limit != null) put("limit", limit)
                if (requestedBefore != null) put("before", requestedBefore)
            },
        )
        val rows = result["attention"] as? JsonArray
            ?: throw FabricWorkInvalidResponseException("Work Attention list is missing attention.")
        return WorkAttentionListResponse(
            workProfileId = requireWorkProfileId(result, "Work Attention list"),
            attention = rows.mapIndexed { index, value ->
                decodeWorkValue("Work Attention list item $index") { decodeWorkAttention(value) }
            },
            nextBefore = result.optionalWorkString("next_before", "Work Attention list"),
        )
    }

    /**
     * Resolve one exact durable Attention item. Sensitive values only flow to
     * the WebSocket request; this method neither logs nor caches them.
     */
    suspend fun respondToWorkAttention(
        negotiation: GatewayCapabilityNegotiation,
        sessionId: String,
        attention: WorkAttention,
        action: String,
        idempotencyKey: String,
        reason: String? = null,
        value: String? = null,
    ): WorkAttentionMutationReceipt {
        requireDurableWork(negotiation)
        if (!attention.actionable || action !in attention.allowedActions) {
            throw IllegalArgumentException("That Attention action is no longer available.")
        }
        val runtimeSessionId = requireWorkSessionId(sessionId)
        val requestedAttentionId = requireWorkAttentionId(attention.attentionId)
        if (attention.version !in 1..FABRIC_WORK_MAXIMUM_SAFE_INTEGER) {
            throw IllegalArgumentException("Attention version must be a positive safe integer.")
        }
        requireWorkIdempotencyKey(idempotencyKey)
        // Reject invalid local envelopes before a secret/value ever leaves the
        // phone. The server repeats these checks as the authority boundary.
        if (attention.kind == "approval") {
            if (value != null) throw IllegalArgumentException("Approval responses do not accept a value.")
            if (reason != null &&
                (action != "deny" || reason.codePointCount(0, reason.length) > 1_000)
            ) {
                throw IllegalArgumentException(
                    "An approval reason is accepted only when denying and must be at most 1000 characters.",
                )
            }
        } else {
            if (reason != null) throw IllegalArgumentException("A reason is accepted only for approval.")
            if (action == "submit" && value == null) {
                throw IllegalArgumentException("This Attention item requires a value to submit.")
            }
            if (action != "submit" && value != null) {
                throw IllegalArgumentException("This Attention action does not accept a value.")
            }
        }
        val result = client.requestObject(
            "attention.respond",
            buildJsonObject {
                put("session_id", runtimeSessionId)
                put("attention_id", requestedAttentionId)
                put("expected_version", attention.version)
                put("idempotency_key", idempotencyKey)
                put("action", action)
                if (reason != null) put("reason", reason)
                if (value != null) put("value", value)
            },
        )
        val receipt = parseWorkAttentionMutationReceipt(result)
        val expectedState = if (action == "deny" || action == "cancel") "denied" else "resolved"
        if (
            receipt.attentionId != requestedAttentionId ||
            receipt.attentionVersion <= attention.version ||
            receipt.state != expectedState ||
            !receipt.delivered
        ) {
            throw FabricWorkInvalidResponseException(
                "Attention response did not match the pending durable item.",
            )
        }
        return receipt
    }

    /** `GET /api/auth/providers` — which sign-in options this gateway offers. */
    suspend fun listAuthProviders(baseUrl: String): List<AuthProviderInfo> =
        withContext(Dispatchers.IO) {
            val url = normalizedBase(baseUrl).newBuilder()
                .addPathSegments("api/auth/providers")
                .build()
            authClient.newCall(Request.Builder().url(url).get().build()).execute().use { response ->
                if (!response.isSuccessful) {
                    throw GatewayHttpException(
                        "HTTP ${response.code}: ${response.body?.string().orEmpty()}",
                        response.code,
                    )
                }
                val parsed = runCatching {
                    json.parseToJsonElement(response.body?.string().orEmpty()).jsonObject
                }.getOrNull() ?: return@use emptyList()
                val rows = parsed["providers"] as? JsonArray ?: return@use emptyList()
                rows.mapNotNull { row ->
                    val obj = row as? JsonObject ?: return@mapNotNull null
                    val name = obj.string("name") ?: return@mapNotNull null
                    AuthProviderInfo(
                        name = name,
                        displayName = obj.string("display_name") ?: name,
                        supportsPassword = (obj["supports_password"] as? JsonPrimitive)
                            ?.booleanOrNull ?: false,
                        requiresTotp = (obj["requires_totp"] as? JsonPrimitive)
                            ?.booleanOrNull ?: false,
                    )
                }
            }
        }

    /**
     * `POST /auth/password-login` — authenticates and stores the session
     * cookies in [authClient]'s jar. 401 means bad credentials; 429
     * rate-limited.
     */
    suspend fun passwordLogin(
        baseUrl: String,
        provider: String,
        username: String,
        password: String,
        otp: String = "",
    ): Unit = withContext(Dispatchers.IO) {
        val url = normalizedBase(baseUrl).newBuilder()
            .addPathSegments("auth/password-login")
            .build()
        val body = buildJsonObject {
            put("provider", provider)
            put("username", username)
            put("password", password)
            put("otp", otp)
        }.toString().toRequestBody("application/json".toMediaType())
        authClient.newCall(Request.Builder().url(url).post(body).build()).execute().use { response ->
            if (!response.isSuccessful) {
                val detail = runCatching {
                    json.parseToJsonElement(response.body?.string().orEmpty())
                        .jsonObject.string("detail")
                }.getOrNull()
                throw GatewayHttpException(
                    detail ?: "Sign-in failed (HTTP ${response.code})",
                    response.code,
                )
            }
        }
    }

    /**
     * `POST /api/auth/ws-ticket` — single-use 30s WS credential for the
     * cookie session. A 401 here means the session has expired (or was never
     * established): re-run [passwordLogin].
     */
    suspend fun mintWsTicket(baseUrl: String): String = withContext(Dispatchers.IO) {
        val url = normalizedBase(baseUrl).newBuilder()
            .addPathSegments("api/auth/ws-ticket")
            .build()
        val body = ByteArray(0).toRequestBody(null)
        authClient.newCall(Request.Builder().url(url).post(body).build()).execute().use { response ->
            if (!response.isSuccessful) {
                throw GatewayHttpException(
                    "HTTP ${response.code}: ${response.body?.string().orEmpty()}",
                    response.code,
                )
            }
            val parsed = runCatching {
                json.parseToJsonElement(response.body?.string().orEmpty()).jsonObject
            }.getOrNull()
            parsed?.string("ticket")?.takeIf { it.isNotEmpty() }
                ?: throw GatewayHttpException("Gateway returned no ticket")
        }
    }

    // -- Sessions -----------------------------------------------------------

    suspend fun listSessions(limit: Int = 100): List<SessionSummary> {
        val result = client.requestObject("session.list", buildJsonObject { put("limit", limit) })
        val rows = result["sessions"] as? JsonArray ?: return emptyList()
        return rows.mapNotNull { row ->
            val obj = row as? JsonObject ?: return@mapNotNull null
            val id = obj.string("id") ?: return@mapNotNull null
            SessionSummary(
                id = id,
                title = obj.string("title").orEmpty(),
                preview = obj.string("preview").orEmpty(),
                startedAt = (obj["started_at"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                messageCount = (obj["message_count"] as? JsonPrimitive)?.intOrNull ?: 0,
                source = obj.string("source").orEmpty(),
            )
        }
    }

    suspend fun createSession(profile: String? = null): LiveSession {
        val params = buildJsonObject {
            put("cols", 96)
            put("source", "mobile")
            if (!profile.isNullOrEmpty()) put("profile", profile)
        }
        val result = client.requestObject("session.create", params)
        return LiveSession(
            sessionId = result.string("session_id").orEmpty(),
            storedSessionId = result.string("stored_session_id"),
            workIdentity = (result["info"] as? JsonObject)
                ?.let(FabricWorkSessionIdentity::fromSessionInfo),
        )
    }

    suspend fun resumeSession(storedSessionId: String): LiveSession {
        val params = buildJsonObject {
            put("session_id", storedSessionId)
            put("cols", 96)
            put("source", "mobile")
        }
        val result = client.requestObject("session.resume", params)
        return LiveSession.fromResumePayload(result, storedSessionId)
    }

    /** Read persisted display history without creating or resuming a live session. */
    suspend fun sessionTranscript(
        storedSessionId: String,
        limit: Int = 250,
    ): List<SessionTranscriptMessage> {
        val result = client.requestObject(
            "session.transcript",
            buildJsonObject {
                put("session_id", storedSessionId)
                put("limit", limit)
            },
        )
        return (result["messages"] as? JsonArray)
            ?.mapNotNull { (it as? JsonObject)?.let(SessionTranscriptMessage::fromJson) }
            .orEmpty()
    }

    // -- Turns --------------------------------------------------------------

    suspend fun submitPrompt(sessionId: String, text: String) {
        client.request(
            "prompt.submit",
            buildJsonObject {
                put("session_id", sessionId)
                put("text", text)
            },
        )
    }

    suspend fun interrupt(sessionId: String) {
        client.request("session.interrupt", buildJsonObject { put("session_id", sessionId) })
    }

    /** Resolve exactly one authoritative approval request. */
    suspend fun respondToApproval(
        sessionId: String,
        requestId: String,
        choice: String,
    ) {
        val result = client.requestObject(
            "approval.respond",
            buildJsonObject {
                put("session_id", sessionId)
                put("request_id", requestId)
                put("choice", choice)
            },
        )
        requireMatchingInteractionReceipt(result, requestId, approval = true)
    }

    // -- Remote control / dispatch -------------------------------------------

    /**
     * Inject a mid-turn note without interrupting (`AIAgent.steer`). Returns
     * true when the gateway queued it, false when the agent rejected it.
     */
    suspend fun steer(sessionId: String, text: String): Boolean {
        val result = client.requestObject(
            "session.steer",
            buildJsonObject {
                put("session_id", sessionId)
                put("text", text)
            },
        )
        return result.string("status") == "queued"
    }

    /**
     * Run a prompt as a detached background task. The result arrives later
     * as a `background.complete` event with `{task_id, text}`.
     */
    suspend fun submitBackgroundPrompt(sessionId: String, text: String): String? {
        val result = client.requestObject(
            "prompt.background",
            buildJsonObject {
                put("session_id", sessionId)
                put("text", text)
            },
        )
        return result.string("task_id")
    }

    /**
     * Dispatch a slash command exactly as the TUI composer does. Some
     * commands return inline `output`; others act via streamed events.
     */
    suspend fun execSlashCommand(sessionId: String, command: String): String? {
        val result = client.requestObject(
            "slash.exec",
            buildJsonObject {
                put("session_id", sessionId)
                put("command", command)
            },
        )
        return result.string("output")
    }

    /** The registry-backed slash-command catalog, grouped by category. */
    suspend fun commandCatalog(): List<SlashCommandCategory> {
        val result = client.requestObject("commands.catalog")
        val categories = result["categories"] as? JsonArray ?: return emptyList()
        return categories.mapNotNull { categoryEl ->
            val category = categoryEl as? JsonObject ?: return@mapNotNull null
            val name = category.string("name") ?: return@mapNotNull null
            val pairs = category["pairs"] as? JsonArray ?: return@mapNotNull null
            val commands = pairs.mapNotNull { pairEl ->
                val pair = pairEl as? JsonArray ?: return@mapNotNull null
                val cmdName = (pair.getOrNull(0) as? JsonPrimitive)?.content
                    ?: return@mapNotNull null
                val detail = (pair.getOrNull(1) as? JsonPrimitive)?.content.orEmpty()
                SlashCommand(cmdName, detail)
            }
            if (commands.isEmpty()) null else SlashCommandCategory(name, commands)
        }
    }

    /** Live gateway sessions (running turns, waiting prompts, idle agents). */
    suspend fun activeSessions(currentSessionId: String? = null): List<ActiveSession> {
        val params = buildJsonObject {
            if (currentSessionId != null) put("current_session_id", currentSessionId)
        }
        val result = client.requestObject("session.active_list", params)
        val rows = result["sessions"] as? JsonArray ?: return emptyList()
        return rows.mapNotNull { row ->
            (row as? JsonObject)?.let { ActiveSession.fromJson(it) }
        }
    }

    /** Background processes owned by a session (preview servers, watchers…). */
    suspend fun listProcesses(sessionId: String): List<BackgroundProcess> {
        val result = client.requestObject(
            "process.list",
            buildJsonObject { put("session_id", sessionId) },
        )
        val rows = result["processes"] as? JsonArray ?: return emptyList()
        return rows.mapNotNull { row ->
            val obj = row as? JsonObject ?: return@mapNotNull null
            val id = obj.string("session_id") ?: return@mapNotNull null
            BackgroundProcess(
                id = id,
                command = obj.string("command").orEmpty(),
                pid = (obj["pid"] as? JsonPrimitive)?.intOrNull ?: 0,
                status = obj.string("status") ?: "running",
                uptimeSeconds = (obj["uptime_seconds"] as? JsonPrimitive)?.intOrNull ?: 0,
                outputTail = obj.string("output_tail").orEmpty(),
            )
        }
    }

    suspend fun killProcess(sessionId: String, processId: String) {
        client.request(
            "process.kill",
            buildJsonObject {
                put("session_id", sessionId)
                put("process_id", processId)
            },
        )
    }

    // -- Computer use (live view) --------------------------------------------

    /**
     * A read-only screen capture from the gateway host (`computer.screenshot`).
     * The gateway returns a plain PNG (no overlays, no accessibility data).
     */
    suspend fun captureScreen(): ScreenCapture {
        val result = client.requestObject("computer.screenshot")
        val b64 = result.string("png_b64")
            ?: throw GatewayRpcException("Live view unavailable on this server.")
        return ScreenCapture(
            pngBase64 = b64,
            width = (result["width"] as? JsonPrimitive)?.intOrNull ?: 0,
            height = (result["height"] as? JsonPrimitive)?.intOrNull ?: 0,
        )
    }

    // -- Blocking prompt responses (clarify / sudo / secret) ------------------
    // These unblock `_block(...)` waits keyed by `request_id`
    // (`_respond` in tui_gateway/server.py).

    suspend fun respondToClarify(sessionId: String, requestId: String, answer: String) {
        val result = client.requestObject(
            "clarify.respond",
            buildJsonObject {
                put("session_id", sessionId)
                put("request_id", requestId)
                put("answer", answer)
            },
        )
        requireMatchingInteractionReceipt(result, requestId)
    }

    suspend fun respondToSudo(sessionId: String, requestId: String, password: String) {
        val result = client.requestObject(
            "sudo.respond",
            buildJsonObject {
                put("session_id", sessionId)
                put("request_id", requestId)
                put("password", password)
            },
        )
        requireMatchingInteractionReceipt(result, requestId)
    }

    suspend fun respondToSecret(sessionId: String, requestId: String, value: String) {
        val result = client.requestObject(
            "secret.respond",
            buildJsonObject {
                put("session_id", sessionId)
                put("request_id", requestId)
                put("value", value)
            },
        )
        requireMatchingInteractionReceipt(result, requestId)
    }
}

private fun requireDurableWork(negotiation: GatewayCapabilityNegotiation) {
    if (!negotiation.supportsDurableWork()) throw FabricWorkUnavailableException()
}

private fun requireWorkSessionId(value: String): String {
    if (value.trim().isEmpty()) throw IllegalArgumentException("session_id must be non-empty.")
    return value
}

private fun requireWorkJobId(value: String): String = try {
    decodeWorkJobId(JsonPrimitive(value))
} catch (_: WorkContractDecodeException) {
    throw IllegalArgumentException("job_id must be a valid Work Job identifier.")
}

private fun requireWorkLedgerId(value: String): String = try {
    decodeWorkLedgerId(JsonPrimitive(value))
} catch (_: WorkContractDecodeException) {
    throw IllegalArgumentException("ledger_id must be a valid Work ledger identifier.")
}

private fun requireWorkAttentionId(value: String): String = try {
    decodeWorkAttentionId(JsonPrimitive(value))
} catch (_: WorkContractDecodeException) {
    throw IllegalArgumentException("attention_id must be a valid Work Attention identifier.")
}

private fun requireWorkIdempotencyKey(value: String) {
    if (!Regex("^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$").matches(value)) {
        throw IllegalArgumentException("idempotency_key must contain 16 to 128 safe characters.")
    }
}

private fun requireWorkStringList(values: List<String>, field: String): List<String> {
    if (values.size > 100) throw IllegalArgumentException("$field must contain at most 100 values.")
    return values.mapIndexed { index, value ->
        requireWorkOpaqueString(value, field = "$field[$index]", maximumCodePoints = 128)
    }
}

private fun requireWorkOpaqueString(
    value: String,
    field: String,
    maximumCodePoints: Int,
): String {
    if (value.trim().isEmpty() || value.codePointCount(0, value.length) > maximumCodePoints) {
        throw IllegalArgumentException(
            "$field must be a non-empty string of at most $maximumCodePoints characters.",
        )
    }
    return value
}

private fun <T> decodeWorkValue(label: String, decode: () -> T): T = try {
    decode()
} catch (error: Exception) {
    if (error is FabricWorkInvalidResponseException) throw error
    val detail = (error as? WorkContractDecodeException)?.message
    throw FabricWorkInvalidResponseException(
        if (detail.isNullOrBlank()) "$label is invalid." else "$label is invalid: $detail",
    )
}

private fun JsonObject.requireWorkString(key: String, label: String): String =
    string(key)?.takeIf { it.isNotBlank() }
        ?: throw FabricWorkInvalidResponseException("$label is missing $key.")

private fun JsonObject.optionalWorkString(key: String, label: String): String? {
    if (!containsKey(key) || this[key] is JsonNull) return null
    return requireWorkString(key, label)
}

private fun JsonObject.requireWorkBoolean(key: String, label: String): Boolean =
    boolean(key) ?: throw FabricWorkInvalidResponseException("$label is missing $key.")

private fun JsonObject.requireWorkPositiveOrZeroLong(key: String, label: String): Long {
    val primitive = this[key] as? JsonPrimitive
        ?: throw FabricWorkInvalidResponseException("$label is missing $key.")
    val value = if (primitive.isString) null else primitive.longOrNull
    if (value == null || value < 0 || value > FABRIC_WORK_MAXIMUM_SAFE_INTEGER) {
        throw FabricWorkInvalidResponseException("$label has an invalid $key.")
    }
    return value
}

private fun requireWorkProfileId(result: JsonObject, label: String): String {
    val raw = result["work_profile_id"]
        ?: throw FabricWorkInvalidResponseException("$label is missing work_profile_id.")
    return try {
        decodeWorkProfileId(raw)
    } catch (_: WorkContractDecodeException) {
        throw FabricWorkInvalidResponseException("$label has an invalid work_profile_id.")
    }
}

private fun parseWorkJobMutationReceipt(result: JsonObject): WorkJobMutationReceipt {
    val rawJob = result["job"]
        ?: throw FabricWorkInvalidResponseException("Job mutation receipt is missing job.")
    val job = decodeWorkValue("Job mutation receipt") { decodeWorkJobSummary(rawJob) }
    val runtimeStarted = if (result.containsKey("runtime_started")) {
        result.requireWorkBoolean("runtime_started", "Job mutation receipt")
    } else {
        null
    }
    val taskId = if (result.containsKey("task_id")) {
        result.requireWorkString("task_id", "Job mutation receipt")
    } else {
        null
    }
    return WorkJobMutationReceipt(
        job = job,
        mutationId = decodeWorkValue("Job mutation receipt") {
            decodeWorkMutationId(
                result["mutation_id"]
                    ?: throw FabricWorkInvalidResponseException("Job mutation receipt is missing mutation_id."),
            )
        },
        replayed = result.requireWorkBoolean("replayed", "Job mutation receipt"),
        runtimeStarted = runtimeStarted,
        taskId = taskId,
    )
}

private fun parseWorkAttentionMutationReceipt(result: JsonObject): WorkAttentionMutationReceipt {
    val attentionId = decodeWorkValue("Attention mutation receipt") {
        decodeWorkAttentionId(
            result["attention_id"]
                ?: throw FabricWorkInvalidResponseException("Attention mutation receipt is missing attention_id."),
        )
    }
    val version = result.requireWorkPositiveOrZeroLong("attention_version", "Attention mutation receipt")
    if (version < 1) {
        throw FabricWorkInvalidResponseException("Attention mutation receipt has an invalid Attention item.")
    }
    return WorkAttentionMutationReceipt(
        attentionId = attentionId,
        attentionVersion = version,
        delivered = result.requireWorkBoolean("delivered", "Attention mutation receipt"),
        mutationId = decodeWorkValue("Attention mutation receipt") {
            decodeWorkMutationId(
                result["mutation_id"]
                    ?: throw FabricWorkInvalidResponseException("Attention mutation receipt is missing mutation_id."),
            )
        },
        replayed = result.requireWorkBoolean("replayed", "Attention mutation receipt"),
        state = result.requireWorkString("state", "Attention mutation receipt"),
    )
}

internal fun requireMatchingInteractionReceipt(
    result: JsonObject,
    requestId: String,
    approval: Boolean = false,
) {
    if (result.string("request_id") != requestId || (approval && result.integer("resolved") != 1)) {
        throw GatewayRpcException("Response did not match the pending request")
    }
}

internal fun legacyCapabilityFallback(
    error: GatewayRpcException,
): GatewayCapabilityNegotiation.Legacy? = if (error.code == -32601) {
    GatewayCapabilityNegotiation.Legacy
} else {
    null
}

internal fun parseGatewayCapabilities(payload: JsonObject): GatewayCapabilityNegotiation {
    val contract = payload["contract"] as? JsonObject
        ?: return GatewayCapabilityNegotiation.Invalid("missing contract object")
    if (contract.string("name") != GATEWAY_CAPABILITY_CONTRACT_NAME) {
        return GatewayCapabilityNegotiation.Invalid("unsupported contract name")
    }
    val contractVersion = contract.integer("version")
        ?: return GatewayCapabilityNegotiation.Invalid("missing contract version")
    val minimumCompatible = contract.integer("min_compatible")
        ?: return GatewayCapabilityNegotiation.Invalid("missing minimum compatible version")
    if (contractVersion < 1 || minimumCompatible < 1 || minimumCompatible > contractVersion) {
        return GatewayCapabilityNegotiation.Invalid("invalid contract version range")
    }
    val execution = payload["execution"] as? JsonObject
        ?: return GatewayCapabilityNegotiation.Invalid("missing execution contract")
    val location = execution.string("location")
        ?: return GatewayCapabilityNegotiation.Invalid("missing execution location")
    val toolExecution = execution.string("tool_execution")
        ?: return GatewayCapabilityNegotiation.Invalid("missing tool execution location")
    val survivesClientDisconnect = execution.boolean("survives_client_disconnect")
        ?: return GatewayCapabilityNegotiation.Invalid("missing client-disconnect behavior")
    val survivesGatewayRestart = execution.boolean("survives_gateway_restart")
        ?: return GatewayCapabilityNegotiation.Invalid("missing gateway-restart behavior")
    val requiresGatewayHostOnline = execution.boolean("requires_gateway_host_online")
        ?: return GatewayCapabilityNegotiation.Invalid("missing gateway-host requirement")
    if (
        location != "gateway" ||
        toolExecution != "gateway" ||
        !survivesClientDisconnect ||
        survivesGatewayRestart ||
        !requiresGatewayHostOnline
    ) {
        return GatewayCapabilityNegotiation.Invalid(
            "gateway capabilities contradict the version-1 execution contract",
        )
    }

    val methodsArray = payload["methods"] as? JsonArray
        ?: return GatewayCapabilityNegotiation.Invalid("missing methods array")
    val methods = mutableSetOf<String>()
    for (element in methodsArray) {
        val method = (element as? JsonPrimitive)?.takeIf { it.isString }?.content
            ?: return GatewayCapabilityNegotiation.Invalid("methods must be strings")
        if (method.isBlank() || !methods.add(method)) {
            return GatewayCapabilityNegotiation.Invalid("methods must be unique non-empty strings")
        }
    }
    val featuresObject = payload["features"] as? JsonObject
        ?: return GatewayCapabilityNegotiation.Invalid("missing features object")
    val features = mutableMapOf<String, Boolean>()
    for ((name, requiredMethods) in GATEWAY_FEATURE_METHODS) {
        val value = (featuresObject[name] as? JsonPrimitive)
            ?.takeIf { !it.isString }
            ?.booleanOrNull
            ?: return GatewayCapabilityNegotiation.Invalid("feature $name must be a boolean")
        if (value != methods.containsAll(requiredMethods)) {
            return GatewayCapabilityNegotiation.Invalid(
                "feature $name contradicts its advertised methods",
            )
        }
        features[name] = value
    }
    // These additive features are optional in the v1 gateway capability
    // contract. Absent means false; present must still exactly match the
    // feature's full RPC set.
    for ((name, requiredMethods) in OPTIONAL_GATEWAY_FEATURE_METHODS) {
        val rawValue = featuresObject[name]
        if (rawValue == null) {
            features[name] = false
            continue
        }
        val value = (rawValue as? JsonPrimitive)
            ?.takeIf { !it.isString }
            ?.booleanOrNull
            ?: return GatewayCapabilityNegotiation.Invalid("feature $name must be a boolean")
        if (value != methods.containsAll(requiredMethods)) {
            return GatewayCapabilityNegotiation.Invalid(
                "feature $name contradicts its advertised methods",
            )
        }
        features[name] = value
    }
    // Flag-only optional features carry no dedicated methods, so only the
    // boolean shape is checked. Absent still means "not advertised".
    for (name in OPTIONAL_GATEWAY_FEATURE_FLAGS) {
        val rawValue = featuresObject[name]
        if (rawValue == null) {
            features[name] = false
            continue
        }
        val value = (rawValue as? JsonPrimitive)
            ?.takeIf { !it.isString }
            ?.booleanOrNull
            ?: return GatewayCapabilityNegotiation.Invalid("feature $name must be a boolean")
        features[name] = value
    }

    val server = payload["server"] as? JsonObject
        ?: return GatewayCapabilityNegotiation.Invalid("missing server metadata")
    val serverVersion = server.string("version")?.takeIf { it.isNotBlank() }
        ?: return GatewayCapabilityNegotiation.Invalid("invalid server version")
    val releaseDate = server.string("release_date")?.takeIf { it.isNotBlank() }
        ?: return GatewayCapabilityNegotiation.Invalid("invalid server release date")
    if (minimumCompatible > GATEWAY_CLIENT_CONTRACT_VERSION) {
        return GatewayCapabilityNegotiation.Incompatible(minimumCompatible)
    }

    return GatewayCapabilityNegotiation.Verified(
        GatewayCapabilities(
            contractVersion = contractVersion,
            minimumCompatibleVersion = minimumCompatible,
            serverVersion = serverVersion,
            releaseDate = releaseDate,
            execution = GatewayExecutionContract(
                location = location,
                toolExecution = toolExecution,
                survivesClientDisconnect = survivesClientDisconnect,
                survivesGatewayRestart = survivesGatewayRestart,
                requiresGatewayHostOnline = requiresGatewayHostOnline,
            ),
            features = features.toMap(),
            methods = methods.toSet(),
        ),
    )
}

private fun JsonObject.string(key: String): String? =
    (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

private fun JsonObject.integer(key: String): Int? =
    (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull

private fun JsonObject.boolean(key: String): Boolean? =
    (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
