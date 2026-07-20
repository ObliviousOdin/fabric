package io.github.obliviousodin.fabric.mobile.core

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
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

    @Test
    fun interactionReceiptMustMatchExactRequestAndResolution() {
        requireMatchingInteractionReceipt(
            buildJsonObject {
                put("request_id", "approval-2")
                put("resolved", 1)
            },
            requestId = "approval-2",
            approval = true,
        )

        assertThrows(GatewayRpcException::class.java) {
            requireMatchingInteractionReceipt(
                buildJsonObject {
                    put("request_id", "approval-1")
                    put("resolved", 1)
                },
                requestId = "approval-2",
                approval = true,
            )
        }
        assertThrows(GatewayRpcException::class.java) {
            requireMatchingInteractionReceipt(
                buildJsonObject {
                    put("request_id", "approval-2")
                    put("resolved", 0)
                },
                requestId = "approval-2",
                approval = true,
            )
        }
    }

    @Test
    fun genericInteractionReceiptMustMatchExactRequest() {
        requireMatchingInteractionReceipt(
            buildJsonObject { put("request_id", "prompt-2") },
            requestId = "prompt-2",
        )

        assertThrows(GatewayRpcException::class.java) {
            requireMatchingInteractionReceipt(
                buildJsonObject { put("request_id", "prompt-1") },
                requestId = "prompt-2",
            )
        }
        assertThrows(GatewayRpcException::class.java) {
            requireMatchingInteractionReceipt(
                buildJsonObject {},
                requestId = "prompt-2",
            )
        }
    }
}
