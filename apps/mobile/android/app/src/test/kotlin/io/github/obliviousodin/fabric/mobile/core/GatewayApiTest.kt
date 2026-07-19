package io.github.obliviousodin.fabric.mobile.core

import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class GatewayApiTest {
    @Test
    fun buildsWebsocketUrlForLocalHttpGateway() {
        val url = GatewayApi.websocketUrl("http://192.168.1.5:9119", "secret")
        assertTrue(url, url.startsWith("ws://192.168.1.5:9119/api/ws?token="))
    }

    @Test
    fun buildsSecureWebsocketUrlForHttpsGateway() {
        val url = GatewayApi.websocketUrl("https://agent.example.test", "secret")
        assertTrue(url, url.startsWith("wss://agent.example.test/api/ws?token="))
    }

    @Test
    fun rejectsCleartextToPublicGatewayAtConnectTime() {
        // Guards saved gateways too: connect paths route baseUrl straight into
        // GatewayApi, so the transport layer — not just add/scan — must refuse
        // cleartext to a public host now that the OS permits it.
        assertThrows(GatewayHttpException::class.java) {
            GatewayApi.websocketUrl("http://agent.example.test", "secret")
        }
        assertThrows(GatewayHttpException::class.java) {
            GatewayApi.websocketUrlWithTicket("http://8.8.8.8:9119", "ticket")
        }
    }
}
