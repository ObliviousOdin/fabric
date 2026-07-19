package io.github.obliviousodin.fabric.mobile.core

import java.net.URI
import java.net.URLDecoder

/** Validation for a server address entered directly by the user. */
object GatewayBaseUrl {
    fun parse(raw: String): String? {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isEmpty() || trimmed.any { it.code <= 32 }) return null
        val uri = runCatching { URI(trimmed) }.getOrNull() ?: return null
        if (
            uri.scheme?.lowercase() !in setOf("http", "https") ||
            uri.host.isNullOrEmpty() ||
            uri.userInfo != null ||
            uri.rawQuery != null ||
            uri.rawFragment != null
        ) return null
        return uri.toString().trimEnd('/')
    }
}

/**
 * Parsed version-1 `fabric://pair` payload from a pairing QR
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
        private val gatedKeys = setOf("v", "url", "auth")
        private val tokenKeys = gatedKeys + "token"

        /**
         * Parse either the canonical payload or the browser landing URL whose
         * fragment contains that payload. Direct server addresses belong to
         * [GatewayBaseUrl], not this machine-readable contract.
         */
        fun parse(raw: String): PairingPayload? {
            val trimmed = raw.trim()
            val uri = runCatching { URI(trimmed) }.getOrNull() ?: return null
            if (uri.scheme?.lowercase() == "fabric") return parsePayload(uri)

            if (
                uri.scheme?.lowercase() !in setOf("http", "https") ||
                uri.host.isNullOrEmpty() ||
                uri.userInfo != null ||
                uri.path != "/mobile/pair" ||
                uri.rawQuery != null ||
                uri.rawFragment.isNullOrEmpty()
            ) return null
            val fragment = parseParameters(uri.rawFragment) ?: return null
            if (fragment.keys != setOf("pair")) return null
            val payloadUri = runCatching { URI(fragment.getValue("pair")) }.getOrNull()
                ?: return null
            return parsePayload(payloadUri)
        }

        private fun parsePayload(uri: URI): PairingPayload? {
            if (
                uri.scheme?.lowercase() != "fabric" ||
                uri.authority != "pair" ||
                uri.path.orEmpty().isNotEmpty() ||
                uri.rawFragment != null
            ) return null
            val params = parseParameters(uri.rawQuery) ?: return null
            if (params["v"] != "1") return null
            val baseUrl = params["url"]?.let(GatewayBaseUrl::parse) ?: return null

            return when (params["auth"]) {
                "gated" -> {
                    if (params.keys != gatedKeys) return null
                    PairingPayload(baseUrl = baseUrl, gated = true, token = null)
                }

                "token" -> {
                    val token = params["token"]?.takeIf { it.isNotEmpty() } ?: return null
                    if (params.keys != tokenKeys) return null
                    PairingPayload(baseUrl = baseUrl, gated = false, token = token)
                }

                else -> null
            }
        }

        private fun parseParameters(raw: String?): Map<String, String>? {
            if (raw.isNullOrEmpty()) return emptyMap()
            val values = mutableMapOf<String, String>()
            for (pair in raw.split('&')) {
                val index = pair.indexOf('=')
                if (index <= 0) return null
                val key = decode(pair.substring(0, index)) ?: return null
                val value = decode(pair.substring(index + 1)) ?: return null
                if (values.put(key, value) != null) return null
            }
            return values
        }

        private fun decode(value: String): String? = runCatching {
            URLDecoder.decode(value, "UTF-8")
        }.getOrNull()
    }
}
