package io.github.obliviousodin.fabric.mobile.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotNull
import org.junit.Test
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

class PairingUriTest {
    @Test
    fun parsesBrowserLandingUrlWithoutChangingPayload() {
        val pairing = "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=token&token=secret%2Fvalue"
        val encoded = URLEncoder.encode(pairing, StandardCharsets.UTF_8)

        val payload = PairingPayload.parse("https://agent.example.test/mobile/pair#pair=$encoded")

        assertNotNull(payload)
        assertEquals("https://agent.example.test", payload?.baseUrl)
        assertEquals("secret/value", payload?.token)
    }

    @Test
    fun rejectsLandingUrlOutsideMobilePairRoute() {
        val pairing = URLEncoder.encode(
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test",
            StandardCharsets.UTF_8,
        )
        assertNull(PairingPayload.parse("https://agent.example.test/other#pair=$pairing"))
    }

    @Test
    fun rejectsUnknownVersionAndCredentialBearingGatewayUrl() {
        assertNull(
            PairingPayload.parse("fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test")
        )
        assertNull(
            PairingPayload.parse(
                "fabric://pair?v=1&url=https%3A%2F%2Fuser%3Apass%40agent.example.test"
            )
        )
    }
}
