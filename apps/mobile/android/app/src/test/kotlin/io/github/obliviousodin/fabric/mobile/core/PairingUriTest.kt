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

    @Test
    fun allowsCleartextOnlyToLocalOrPrivateHosts() {
        // Local / private / tailnet gateways may use plain http (the
        // `fabric mobile` LAN quick-start); the app permits the cleartext
        // socket at the OS layer only because these stay off the public net.
        assertEquals("http://127.0.0.1:9119", GatewayBaseUrl.parse("http://127.0.0.1:9119"))
        assertEquals("http://192.168.1.50:9119", GatewayBaseUrl.parse("http://192.168.1.50:9119"))
        assertEquals("http://10.0.0.4:9119", GatewayBaseUrl.parse("http://10.0.0.4:9119"))
        assertEquals("http://100.100.7.7:9119", GatewayBaseUrl.parse("http://100.100.7.7:9119"))
        assertEquals("http://raspberrypi:9119", GatewayBaseUrl.parse("http://raspberrypi:9119"))
        assertEquals("http://mymac.local:9119", GatewayBaseUrl.parse("http://mymac.local:9119"))

        // Public hosts must use https — cleartext to them is rejected.
        assertNull(GatewayBaseUrl.parse("http://agent.example.test"))
        assertNull(GatewayBaseUrl.parse("http://8.8.8.8"))
        assertNull(GatewayBaseUrl.parse("http://172.32.0.1")) // just outside 172.16/12
        assertNull(GatewayBaseUrl.parse("http://100.63.0.1")) // just outside CGNAT /10

        // https is always fine, local or public.
        assertEquals("https://agent.example.test", GatewayBaseUrl.parse("https://agent.example.test"))
        assertEquals("https://192.168.1.50", GatewayBaseUrl.parse("https://192.168.1.50"))
    }

    @Test
    fun classifiesLocalAndPrivateHosts() {
        listOf(
            "127.0.0.1", "10.2.3.4", "172.16.0.1", "172.31.255.1", "192.168.1.50",
            "169.254.1.1", "100.64.0.1", "100.127.9.9", "localhost", "raspberrypi",
            "mymac.local", "::1", "[::1]", "fe80::1", "fd00::1", "fc00::abcd",
        ).forEach { assertEquals("$it should be local", true, GatewayBaseUrl.isLocalOrPrivateHost(it)) }

        listOf(
            "8.8.8.8", "1.1.1.1", "172.32.0.1", "172.15.0.1", "192.169.0.1",
            "100.128.0.1", "100.63.0.1", "example.com", "agent.example.test",
            "machine.tailnet.ts.net", "2001:4860:4860::8888", "256.1.1.1", "",
        ).forEach { assertEquals("$it should be public", false, GatewayBaseUrl.isLocalOrPrivateHost(it)) }
    }
}
