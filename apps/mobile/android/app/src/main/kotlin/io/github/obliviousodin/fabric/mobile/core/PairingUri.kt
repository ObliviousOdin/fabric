package io.github.obliviousodin.fabric.mobile.core

import java.net.URI
import java.net.URLDecoder

/**
 * Parsed `fabric://pair` payload from a pairing QR
 * (emitted by `fabric mobile`; contract in fabric_cli/mobile_pairing.py).
 *
 * - `gated == false`: [token] is the session credential; connect directly.
 * - `gated == true`: the gateway requires a provider login; the app asks for
 *   username/password after the scan.
 */
data class PairingPayload(
    val baseUrl: String,
    val gated: Boolean,
    val token: String?,
) {
    companion object {
        /**
         * Parse a scanned string. Accepts the canonical `fabric://pair?...`
         * URI and, as a convenience, a plain `http(s)://...` URL (treated as
         * gated unless it carries a `token` query parameter).
         */
        fun parse(raw: String): PairingPayload? {
            val trimmed = raw.trim()
            val uri = runCatching { URI(trimmed) }.getOrNull() ?: return null

            when (uri.scheme?.lowercase()) {
                "fabric" -> {
                    if (uri.authority != "pair") return null
                    val params = parseQuery(uri.rawQuery)
                    if (params["v"] != "1") return null
                    val url = params["url"]?.let(::validatedBaseUrl) ?: return null
                    val token = params["token"]
                    val gated = params["auth"] != "token" || token.isNullOrEmpty()
                    return PairingPayload(
                        baseUrl = url.trimEnd('/'),
                        gated = gated,
                        token = if (gated) null else token,
                    )
                }

                "http", "https" -> {
                    if (uri.path == "/mobile/pair" && !uri.rawFragment.isNullOrEmpty()) {
                        val wrapped = parseQuery(uri.rawFragment)["pair"] ?: return null
                        return parse(wrapped)
                    }
                    if (!uri.rawFragment.isNullOrEmpty()) return null
                    val params = parseQuery(uri.rawQuery)
                    val token = params["token"]
                    val base = URI(
                        uri.scheme,
                        uri.userInfo,
                        uri.host,
                        uri.port,
                        uri.path,
                        null,
                        null,
                    ).toString().let(::validatedBaseUrl) ?: return null
                    return if (!token.isNullOrEmpty()) {
                        PairingPayload(baseUrl = base, gated = false, token = token)
                    } else {
                        PairingPayload(baseUrl = base, gated = true, token = null)
                    }
                }

                else -> return null
            }
        }

        private fun validatedBaseUrl(raw: String): String? {
            val uri = runCatching { URI(raw) }.getOrNull() ?: return null
            if (
                uri.scheme?.lowercase() !in setOf("http", "https") ||
                uri.host.isNullOrEmpty() ||
                uri.userInfo != null ||
                uri.rawQuery != null ||
                uri.rawFragment != null
            ) return null
            return uri.toString().trimEnd('/')
        }

        private fun parseQuery(rawQuery: String?): Map<String, String> {
            if (rawQuery.isNullOrEmpty()) return emptyMap()
            return rawQuery.split('&').mapNotNull { pair ->
                val idx = pair.indexOf('=')
                if (idx <= 0) return@mapNotNull null
                val key = pair.substring(0, idx)
                val value = runCatching {
                    URLDecoder.decode(pair.substring(idx + 1), "UTF-8")
                }.getOrNull() ?: return@mapNotNull null
                key to value
            }.toMap()
        }
    }
}
