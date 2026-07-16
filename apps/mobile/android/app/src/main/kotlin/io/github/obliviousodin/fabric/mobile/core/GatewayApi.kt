package io.github.obliviousodin.fabric.mobile.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request

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

/** Result of `session.create` / `session.resume`. */
data class LiveSession(
    val sessionId: String,
    val storedSessionId: String?,
)

/**
 * Row shape returned by `session.active_list` — live in-memory sessions on
 * the gateway, unlike the historical `session.list`
 * (`_session_live_item` in tui_gateway/server.py).
 */
data class ActiveSession(
    val id: String,
    val title: String,
    val preview: String,
    /** "working" | "waiting" | "starting" | "idle" (`_session_live_status`). */
    val status: String,
    val model: String,
    val messageCount: Int,
    val lastActive: Double,
    val current: Boolean,
)

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
 * Public body of `GET /api/status`. `authRequired` distinguishes an
 * OAuth-gated gateway from legacy token auth (`authModeFromStatus` in
 * apps/desktop/electron/connection-config.ts).
 */
data class GatewayStatus(val authRequired: Boolean)

class GatewayHttpException(message: String) : Exception(message)

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
                    throw GatewayHttpException("HTTP ${response.code}: ${response.body?.string().orEmpty()}")
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
        fun websocketUrl(baseUrl: String, token: String): String {
            val base = normalizedBase(baseUrl)
            val wsScheme = if (base.scheme == "https") "wss" else "ws"
            val httpUrl = base.newBuilder()
                .addPathSegments("api/ws")
                .addQueryParameter("token", token)
                .build()
            // OkHttp's newWebSocket accepts http(s) URLs, but keep the ws(s)
            // form for parity with the shared client and easier debugging.
            return httpUrl.toString().replaceFirst(base.scheme, wsScheme)
        }

        private fun normalizedBase(baseUrl: String): HttpUrl {
            val trimmed = baseUrl.trim().trimEnd('/')
            return trimmed.toHttpUrlOrNull()
                ?: throw GatewayHttpException("Gateway URL must be http:// or https://")
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
        )
    }

    suspend fun resumeSession(storedSessionId: String): LiveSession {
        val params = buildJsonObject {
            put("session_id", storedSessionId)
            put("cols", 96)
        }
        val result = client.requestObject("session.resume", params)
        return LiveSession(
            sessionId = result.string("session_id") ?: storedSessionId,
            storedSessionId = storedSessionId,
        )
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

    /**
     * `choice` is "allow" or "deny"; `all` resolves every queued approval
     * (tools/approval.py, resolve_gateway_approval).
     */
    suspend fun respondToApproval(sessionId: String, choice: String, all: Boolean = false) {
        client.request(
            "approval.respond",
            buildJsonObject {
                put("session_id", sessionId)
                put("choice", choice)
                put("all", all)
            },
        )
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
            val obj = row as? JsonObject ?: return@mapNotNull null
            val id = obj.string("id") ?: return@mapNotNull null
            ActiveSession(
                id = id,
                title = obj.string("title").orEmpty(),
                preview = obj.string("preview").orEmpty(),
                status = obj.string("status") ?: "idle",
                model = obj.string("model").orEmpty(),
                messageCount = (obj["message_count"] as? JsonPrimitive)?.intOrNull ?: 0,
                lastActive = (obj["last_active"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                current = (obj["current"] as? JsonPrimitive)?.booleanOrNull ?: false,
            )
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

    // -- Blocking prompt responses (clarify / sudo / secret) ------------------
    // These unblock `_block(...)` waits keyed by `request_id`
    // (`_respond` in tui_gateway/server.py).

    suspend fun respondToClarify(requestId: String, answer: String) {
        client.request(
            "clarify.respond",
            buildJsonObject {
                put("request_id", requestId)
                put("answer", answer)
            },
        )
    }

    suspend fun respondToSudo(requestId: String, password: String) {
        client.request(
            "sudo.respond",
            buildJsonObject {
                put("request_id", requestId)
                put("password", password)
            },
        )
    }

    suspend fun respondToSecret(requestId: String, value: String) {
        client.request(
            "secret.respond",
            buildJsonObject {
                put("request_id", requestId)
                put("value", value)
            },
        )
    }
}

private fun JsonObject.string(key: String): String? =
    (this[key] as? JsonPrimitive)?.let { if (it is kotlinx.serialization.json.JsonNull) null else it.content }
