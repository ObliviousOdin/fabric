package io.github.obliviousodin.fabric.mobile.core

import java.net.URI
import java.net.URLDecoder

/** Validation for a server address entered directly by the user. */
object GatewayBaseUrl {
    fun parse(raw: String): String? {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isEmpty() || trimmed.any { it.code <= 32 }) return null
        val uri = runCatching { URI(trimmed) }.getOrNull() ?: return null
        val scheme = uri.scheme?.lowercase()
        if (
            scheme !in setOf("http", "https") ||
            uri.host.isNullOrEmpty() ||
            uri.userInfo != null ||
            uri.rawQuery != null ||
            uri.rawFragment != null
        ) return null
        // Cleartext is only allowed to a local/private host, matching iOS's
        // NSAllowsLocalNetworking. Android has no ATS equivalent and the
        // release build permits cleartext at the OS layer (see
        // res/xml/network_security_config.xml), so this is the app-layer guard
        // that keeps a plain-http socket from ever reaching a public gateway.
        if (scheme == "http" && !isLocalOrPrivateHost(uri.host)) return null
        return uri.toString().trimEnd('/')
    }

    private val ipv4 = Regex("""^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$""")

    /**
     * True when cleartext http to [rawHost] stays on the local machine or a
     * private/tailnet network: loopback, RFC1918, link-local, CGNAT
     * (100.64.0.0/10, Tailscale), IPv6 loopback/link-local/ULA, `.local`
     * mDNS names, and single-label hostnames. Public hosts return false and
     * must use https.
     */
    internal fun isLocalOrPrivateHost(rawHost: String?): Boolean {
        var host = rawHost?.trim()?.lowercase() ?: return false
        if (host.startsWith("[") && host.endsWith("]")) host = host.substring(1, host.length - 1)
        if (host.isEmpty()) return false
        if (host.contains(':')) return isPrivateIpv6(host)
        val match = ipv4.matchEntire(host)
        if (match != null) return isPrivateIpv4(match)
        if (!host.contains('.')) return true // single-label host (localhost, raspberrypi)
        return host.endsWith(".local")
    }

    private fun isPrivateIpv4(match: MatchResult): Boolean {
        val (a, b, c, d) = match.destructured
        val octets = listOf(a, b, c, d).map { it.toInt() }
        if (octets.any { it > 255 }) return false
        val (o0, o1) = octets
        return when {
            o0 == 127 -> true // loopback 127.0.0.0/8
            o0 == 10 -> true // private 10.0.0.0/8
            o0 == 172 && o1 in 16..31 -> true // private 172.16.0.0/12
            o0 == 192 && o1 == 168 -> true // private 192.168.0.0/16
            o0 == 169 && o1 == 254 -> true // link-local 169.254.0.0/16
            o0 == 100 && o1 in 64..127 -> true // CGNAT/Tailscale 100.64.0.0/10
            else -> false
        }
    }

    private fun isPrivateIpv6(host: String): Boolean = when {
        host == "::1" -> true // loopback
        Regex("^fe[89ab]").containsMatchIn(host) -> true // fe80::/10 link-local
        host.startsWith("fc") || host.startsWith("fd") -> true // fc00::/7 ULA
        else -> false
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
