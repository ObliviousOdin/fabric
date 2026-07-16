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
}

private fun JsonObject.string(key: String): String? =
    (this[key] as? JsonPrimitive)?.let { if (it is kotlinx.serialization.json.JsonNull) null else it.content }
