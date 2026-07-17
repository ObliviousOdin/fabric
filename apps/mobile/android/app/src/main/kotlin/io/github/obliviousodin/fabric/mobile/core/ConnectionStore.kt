package io.github.obliviousodin.fabric.mobile.core

import android.content.Context

/** How the app authenticates to a gateway. */
enum class GatewayAuthMode {
    /** Loopback/tunnel deployments: the session token is the credential. */
    TOKEN,

    /** Non-loopback binds: provider login (password/OAuth) + WS tickets. */
    GATED,
}

data class ConnectionSettings(
    val baseUrl: String,
    val token: String,
    val authMode: GatewayAuthMode = GatewayAuthMode.TOKEN,
    val username: String = "",
)

/**
 * Persisted connection settings in app-private SharedPreferences.
 *
 * The token is a secret; app-private storage is sandboxed but a
 * Keystore-encrypted store is the tracked follow-up before any release
 * build (see apps/mobile/README.md roadmap). Passwords are never persisted
 * — gated sessions live in the in-memory cookie jar and the user signs in
 * again after a process restart.
 */
object ConnectionStore {
    private const val PREFS = "fabric-gateway"
    private const val KEY_URL = "baseUrl"
    private const val KEY_TOKEN = "token"
    private const val KEY_AUTH_MODE = "authMode"
    private const val KEY_USERNAME = "username"

    fun load(context: Context): ConnectionSettings? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val url = prefs.getString(KEY_URL, null)?.takeIf { it.isNotEmpty() } ?: return null
        val mode = runCatching {
            GatewayAuthMode.valueOf(prefs.getString(KEY_AUTH_MODE, null) ?: "TOKEN")
        }.getOrDefault(GatewayAuthMode.TOKEN)
        val token = prefs.getString(KEY_TOKEN, null).orEmpty()
        if (mode == GatewayAuthMode.TOKEN && token.isEmpty()) return null
        return ConnectionSettings(
            baseUrl = url,
            token = token,
            authMode = mode,
            username = prefs.getString(KEY_USERNAME, null).orEmpty(),
        )
    }

    fun save(context: Context, settings: ConnectionSettings) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_URL, settings.baseUrl)
            .putString(KEY_TOKEN, settings.token)
            .putString(KEY_AUTH_MODE, settings.authMode.name)
            .putString(KEY_USERNAME, settings.username)
            .apply()
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .apply()
    }
}
