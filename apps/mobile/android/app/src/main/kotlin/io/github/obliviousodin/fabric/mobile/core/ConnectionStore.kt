package io.github.obliviousodin.fabric.mobile.core

import android.content.Context

data class ConnectionSettings(
    val baseUrl: String,
    val token: String,
)

/**
 * Persisted connection settings in app-private SharedPreferences.
 *
 * The token is a secret; app-private storage is sandboxed but a
 * Keystore-encrypted store is the tracked follow-up before any release
 * build (see apps/mobile/README.md roadmap).
 */
object ConnectionStore {
    private const val PREFS = "fabric-gateway"
    private const val KEY_URL = "baseUrl"
    private const val KEY_TOKEN = "token"

    fun load(context: Context): ConnectionSettings? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val url = prefs.getString(KEY_URL, null) ?: return null
        val token = prefs.getString(KEY_TOKEN, null) ?: return null
        if (url.isEmpty() || token.isEmpty()) return null
        return ConnectionSettings(url, token)
    }

    fun save(context: Context, settings: ConnectionSettings) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_URL, settings.baseUrl)
            .putString(KEY_TOKEN, settings.token)
            .apply()
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .apply()
    }
}
