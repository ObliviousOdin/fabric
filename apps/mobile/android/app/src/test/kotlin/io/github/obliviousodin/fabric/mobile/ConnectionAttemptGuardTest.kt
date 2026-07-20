package io.github.obliviousodin.fabric.mobile

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionAttemptGuardTest {
    @Test
    fun acceptsOnlyTheCurrentForegroundAttemptInItsExpectedPhase() {
        assertTrue(
            isCurrentConnectionAttempt(
                attempt = 4,
                currentAttempt = 4,
                phase = ConnectionPhase.Connecting,
                expectedPhase = ConnectionPhase.Connecting,
                isForeground = true,
            ),
        )
    }

    @Test
    fun rejectsLateServerSwitchAndBackgroundedResults() {
        assertFalse(
            isCurrentConnectionAttempt(
                attempt = 4,
                currentAttempt = 5,
                phase = ConnectionPhase.Connecting,
                expectedPhase = ConnectionPhase.Connecting,
                isForeground = true,
            ),
        )
        assertFalse(
            isCurrentConnectionAttempt(
                attempt = 4,
                currentAttempt = 4,
                phase = ConnectionPhase.Connecting,
                expectedPhase = ConnectionPhase.Connecting,
                isForeground = false,
            ),
        )
        assertFalse(
            isCurrentConnectionAttempt(
                attempt = 4,
                currentAttempt = 4,
                phase = ConnectionPhase.Disconnected,
                expectedPhase = ConnectionPhase.Connecting,
                isForeground = true,
            ),
        )
    }
}
