package io.github.obliviousodin.fabric.mobile.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Conformance for the Kotlin artifact parser. Mirrors the shared fixture at
 * apps/mobile/contracts/social-extraction-v1.json (validated against the
 * TypeScript implementation in apps/shared/src/social-contract.test.ts).
 */
class SocialArtifactsTest {
    private data class Msg(
        override val role: String,
        override val content: String?,
        override val timestamp: Long? = null,
    ) : SocialSourceMessage

    @Test
    fun capturesCaptionAndMarkdownImage() {
        val artifacts =
            extractSocialArtifacts(
                listOf(
                    Msg("user", "Draft me a launch post."),
                    Msg(
                        "assistant",
                        "Here you go:\n\n```linkedin-post\nWe shipped Fabric.\n\n" +
                            "Here is why it matters.\n```\n\n## Artifacts\n\n" +
                            "![Launch graphic](assets/launch.png)",
                        1_700_000_000L,
                    ),
                ),
            )

        assertEquals(1, artifacts.size)
        assertEquals("We shipped Fabric.\n\nHere is why it matters.", artifacts[0].caption)
        assertEquals("assets/launch.png", artifacts[0].imagePath)
        assertEquals(1, artifacts[0].messageIndex)
        assertEquals(1_700_000_000L, artifacts[0].timestamp)
        assertEquals("1:0", artifacts[0].id)
    }

    @Test
    fun ignoresUserMessageNamingTheFence() {
        val messages = listOf(Msg("user", "Put the result in a ```linkedin-post``` block please."))
        assertTrue(extractSocialArtifacts(messages).isEmpty())
        assertFalse(hasSocialArtifacts(messages))
    }

    @Test
    fun textOnlyPostHasNullImageAndTimestamp() {
        val artifact = extractSocialArtifacts(listOf(Msg("assistant", "```linkedin-post\nText only post.\n```")))[0]
        assertEquals("Text only post.", artifact.caption)
        assertNull(artifact.imagePath)
        assertNull(artifact.timestamp)
    }

    @Test
    fun bareImagePathUnderArtifactsIsNotSwallowedByBullet() {
        val artifact =
            extractSocialArtifacts(
                listOf(Msg("assistant", "```linkedin-post\nA lesson learned.\n```\n\nArtifacts:\n- ./out/post-image.jpg")),
            )[0]
        assertEquals("./out/post-image.jpg", artifact.imagePath)
    }

    @Test
    fun ignoresUnrelatedCodeFence() {
        val artifacts =
            extractSocialArtifacts(
                listOf(
                    Msg("assistant", "```python\nprint('not a post')\n```"),
                    Msg("assistant", "Some prose without any fence."),
                ),
            )
        assertTrue(artifacts.isEmpty())
    }

    @Test
    fun capturesMultipleDraftsInOrder() {
        val artifacts =
            extractSocialArtifacts(
                listOf(
                    Msg("assistant", "```linkedin-post\nDraft one.\n```"),
                    Msg("user", "try another angle"),
                    Msg("assistant", "```linkedin-post\nDraft two.\n```"),
                ),
            )
        assertEquals(listOf("Draft one.", "Draft two."), artifacts.map { it.caption })
        assertEquals(listOf("0:0", "2:0"), artifacts.map { it.id })
    }

    @Test
    fun distinguishesRemoteImages() {
        assertTrue(isRemoteImage("https://example.com/a.png"))
        assertFalse(isRemoteImage("assets/launch.png"))
        assertFalse(isRemoteImage("/home/user/out.png"))
    }
}
