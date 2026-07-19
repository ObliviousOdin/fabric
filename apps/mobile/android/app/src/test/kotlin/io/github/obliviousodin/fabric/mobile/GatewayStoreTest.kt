package io.github.obliviousodin.fabric.mobile

import io.github.obliviousodin.fabric.mobile.core.SavedGateway
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class GatewayStoreTest {
    @Test
    fun endpointKeyNormalizesCosmeticUrlDifferences() {
        assertEquals(
            SavedGateway.endpointKey("http://example.com"),
            SavedGateway.endpointKey("HTTP://Example.COM:80/"),
        )
    }

    @Test
    fun endpointKeyPreservesPathAndNonDefaultPort() {
        val first = SavedGateway.endpointKey("https://example.com:8443/fabric/")
        val same = SavedGateway.endpointKey("https://EXAMPLE.com:8443/fabric")
        val differentPort = SavedGateway.endpointKey("https://example.com:9443/fabric")

        assertEquals(first, same)
        assertNotEquals(first, differentPort)
    }
}
