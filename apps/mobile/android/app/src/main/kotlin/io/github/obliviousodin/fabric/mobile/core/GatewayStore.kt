package io.github.obliviousodin.fabric.mobile.core

import android.content.Context
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/** How the app authenticates to a gateway. */
enum class GatewayAuthMode {
    /** Loopback/tunnel deployments: the session token is the credential. */
    TOKEN,

    /** Non-loopback binds: provider login (password/OAuth) + WS tickets. */
    GATED,
}

/**
 * One saved Fabric server in the library. Metadata is JSON in
 * SharedPreferences; the token (token mode) is stored in a separate
 * per-id preference key. Passwords are never stored — a gated server
 * auto-logs-in only while its cookie session is alive.
 */
@Serializable
data class SavedGateway(
    val id: String,
    val label: String,
    val baseUrl: String,
    val authMode: GatewayAuthMode,
    val username: String = "",
) {
    companion object {
        /** A readable label from the URL host when the user didn't name it. */
        fun defaultLabel(baseUrl: String): String =
            runCatching { java.net.URI(baseUrl).host }.getOrNull()?.takeIf { it.isNotEmpty() }
                ?: baseUrl
    }
}

/**
 * The saved-server library: an ordered list plus the id last connected to.
 * Replaces the single-record store so the app can hold many Fabric servers
 * and switch between them.
 */
object GatewayStore {
    private const val PREFS = "fabric-gateways"
    private const val KEY_LIST = "list.v1"
    private const val KEY_LAST_ACTIVE = "lastActive"
    private const val KEY_TOKEN_PREFIX = "token."

    private val json = Json { ignoreUnknownKeys = true }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun all(context: Context): List<SavedGateway> {
        val raw = prefs(context).getString(KEY_LIST, null) ?: return emptyList()
        return runCatching { json.decodeFromString<List<SavedGateway>>(raw) }.getOrDefault(emptyList())
    }

    fun lastActiveId(context: Context): String? =
        prefs(context).getString(KEY_LAST_ACTIVE, null)

    fun setLastActive(context: Context, id: String?) {
        prefs(context).edit().apply {
            if (id == null) remove(KEY_LAST_ACTIVE) else putString(KEY_LAST_ACTIVE, id)
        }.apply()
    }

    /** Insert or update by id, then persist. Returns the stored list. */
    fun upsert(context: Context, gateway: SavedGateway, token: String? = null): List<SavedGateway> {
        val list = all(context).toMutableList()
        val idx = list.indexOfFirst { it.id == gateway.id }
        if (idx >= 0) list[idx] = gateway else list.add(gateway)
        prefs(context).edit()
            .putString(KEY_LIST, json.encodeToString(list))
            .apply()
        if (token != null) {
            prefs(context).edit().putString(KEY_TOKEN_PREFIX + gateway.id, token).apply()
        }
        return list
    }

    fun remove(context: Context, id: String) {
        val list = all(context).filterNot { it.id == id }
        prefs(context).edit()
            .putString(KEY_LIST, json.encodeToString(list))
            .remove(KEY_TOKEN_PREFIX + id)
            .apply()
        if (lastActiveId(context) == id) setLastActive(context, null)
    }

    fun token(context: Context, id: String): String? =
        prefs(context).getString(KEY_TOKEN_PREFIX + id, null)

    /**
     * A token-mode server with a stored token can reconnect with no prompt.
     * (Gated readiness depends on the live cookie session, checked at connect
     * time, so it isn't answerable synchronously here.)
     */
    fun canAutoConnect(context: Context, gateway: SavedGateway): Boolean =
        gateway.authMode == GatewayAuthMode.TOKEN && !token(context, gateway.id).isNullOrEmpty()
}
