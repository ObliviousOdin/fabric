package io.github.obliviousodin.fabric.mobile.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
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
    fun rejectsDirectServerAddresses() {
        assertNull(PairingPayload.parse("https://agent.example.test"))
        assertNull(PairingPayload.parse("https://agent.example.test?token=secret"))
    }

    @Test
    fun rejectsMissingOrContradictoryAuthenticationPayloads() {
        val invalid = listOf(
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=token",
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=gated&token=unexpected",
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=other",
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test",
        )

        invalid.forEach { assertNull(PairingPayload.parse(it)) }
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

    @Test
    fun validatesManualServerAddressesSeparately() {
        assertEquals(
            "https://agent.example.test/fabric",
            GatewayBaseUrl.parse(" https://agent.example.test/fabric/ "),
        )
        assertNull(GatewayBaseUrl.parse("fabric://pair?v=1"))
        assertNull(GatewayBaseUrl.parse("https://user:pass@agent.example.test"))
        assertNull(GatewayBaseUrl.parse("https://agent.example.test?token=secret"))
        assertNull(GatewayBaseUrl.parse("https://agent.example.test/#fragment"))
    }
}
