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
 * SharedPreferences; the token (token mode) is encrypted with a non-exportable
 * Android Keystore key. Passwords are never stored — a gated server
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

        /** Stable identity for a server across case/default-port/trailing-slash differences. */
        fun endpointKey(baseUrl: String): String = runCatching {
            val source = java.net.URI(baseUrl.trim())
            val scheme = source.scheme?.lowercase()
            val host = source.host?.lowercase()
            val port = when {
                scheme == "http" && source.port == 80 -> -1
                scheme == "https" && source.port == 443 -> -1
                else -> source.port
            }
            val path = source.path.orEmpty().trimEnd('/').takeUnless { it == "/" }.orEmpty()
            java.net.URI(scheme, null, host, port, path, null, null).normalize().toString()
        }.getOrElse { baseUrl.trim().trimEnd('/') }
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
        val list = runCatching { json.decodeFromString<List<SavedGateway>>(raw) }
            .getOrDefault(emptyList())
        val seenEndpoints = mutableSetOf<String>()
        val deduplicated = list.asReversed()
            .filter { seenEndpoints.add(SavedGateway.endpointKey(it.baseUrl)) }
            .asReversed()
        if (deduplicated.size == list.size) return list

        val keptIds = deduplicated.map { it.id }.toSet()
        val removed = list.filter { it.id !in keptIds }
        prefs(context).edit().apply {
            putString(KEY_LIST, json.encodeToString(deduplicated))
            removed.forEach { remove(KEY_TOKEN_PREFIX + it.id) }
        }.apply()
        removed.forEach { GatewayCredentialStore.remove(context, it.id) }
        val lastActive = lastActiveId(context)
        val removedActive = removed.firstOrNull { it.id == lastActive }
        val replacement = removedActive?.let { old ->
            deduplicated.firstOrNull {
                SavedGateway.endpointKey(it.baseUrl) == SavedGateway.endpointKey(old.baseUrl)
            }
        }
        if (replacement != null) setLastActive(context, replacement.id)
        return deduplicated
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
        val duplicateIds = list
            .filter {
                it.id != gateway.id &&
                    SavedGateway.endpointKey(it.baseUrl) == SavedGateway.endpointKey(gateway.baseUrl)
            }
            .map { it.id }
            .toSet()
        if (token != null) {
            // Protect the machine-control credential before publishing metadata
            // that would make this gateway appear auto-connectable.
            GatewayCredentialStore.write(context, gateway.id, token)
        }
        list.removeAll { it.id in duplicateIds }
        prefs(context).edit().apply {
            putString(KEY_LIST, json.encodeToString(list))
            remove(KEY_TOKEN_PREFIX + gateway.id)
            duplicateIds.forEach { remove(KEY_TOKEN_PREFIX + it) }
        }.apply()
        duplicateIds.forEach { GatewayCredentialStore.remove(context, it) }
        if (lastActiveId(context)?.let { it in duplicateIds } == true) {
            setLastActive(context, gateway.id)
        }
        if (gateway.authMode == GatewayAuthMode.GATED) {
            GatewayCredentialStore.remove(context, gateway.id)
        }
        return list
    }

    fun remove(context: Context, id: String) {
        val list = all(context).filterNot { it.id == id }
        prefs(context).edit()
            .putString(KEY_LIST, json.encodeToString(list))
            .remove(KEY_TOKEN_PREFIX + id)
            .apply()
        GatewayCredentialStore.remove(context, id)
        if (lastActiveId(context) == id) setLastActive(context, null)
    }

    fun token(context: Context, id: String): String? {
        GatewayCredentialStore.read(context, id)?.let { return it }

        // One-time migration from the scaffold's plain app-private preference.
        val legacy = prefs(context).getString(KEY_TOKEN_PREFIX + id, null) ?: return null
        val migrated = runCatching {
            GatewayCredentialStore.write(context, id, legacy)
            legacy
        }.getOrNull()
        // Fail closed: never retain the legacy plaintext after a migration
        // attempt, even when the platform keystore is unavailable.
        prefs(context).edit().remove(KEY_TOKEN_PREFIX + id).apply()
        return migrated
    }

    /**
     * A token-mode server with a stored token can reconnect with no prompt.
     * (Gated readiness depends on the live cookie session, checked at connect
     * time, so it isn't answerable synchronously here.)
     */
    fun canAutoConnect(context: Context, gateway: SavedGateway): Boolean =
        gateway.authMode == GatewayAuthMode.TOKEN && !token(context, gateway.id).isNullOrEmpty()
}
