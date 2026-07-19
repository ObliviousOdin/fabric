package io.github.obliviousodin.fabric.mobile.core

import java.util.concurrent.ConcurrentHashMap
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl

/**
 * Minimal in-memory cookie jar for the gated-auth REST flow (OkHttp ships
 * with no cookie handling). Holds the gateway session cookies
 * (the dashboard access and refresh cookies, including secure variants) for
 * the life of the process. Deliberately not persisted: restarting the app
 * means signing in again, which beats storing auth material on disk before
 * the Keystore hardening lands.
 */
class MemoryCookieJar : CookieJar {
    private val store = ConcurrentHashMap<String, MutableMap<String, Cookie>>()

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        val hostStore = store.getOrPut(url.host) { ConcurrentHashMap() }
        for (cookie in cookies) {
            hostStore[cookie.name] = cookie
        }
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val hostStore = store[url.host] ?: return emptyList()
        val now = System.currentTimeMillis()
        val valid = hostStore.values.filter { it.expiresAt > now && it.matches(url) }
        // Drop expired entries so a dead access-token cookie doesn't linger.
        hostStore.values.removeAll { it.expiresAt <= now }
        return valid
    }
}
