package io.github.obliviousodin.fabric.mobile.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SocialPromptTest {
    private val base =
        SocialRequest(
            brief = "Shipping our new agent dashboard after six weeks of work",
            includeImage = true,
        )

    @Test
    fun includesBriefChannelAndFenceTag() {
        val prompt = buildSocialPrompt(base)
        assertTrue(prompt.contains(base.brief))
        assertTrue(prompt.contains("LinkedIn"))
        assertTrue(prompt.contains("`$SOCIAL_POST_FENCE`"))
    }

    @Test
    fun asksForImageOnlyWhenRequested() {
        assertTrue(buildSocialPrompt(base.copy(includeImage = true)).contains("Artifacts"))
        val noImage = buildSocialPrompt(base.copy(includeImage = false))
        assertTrue(noImage.lowercase().contains("text only"))
        assertFalse(noImage.contains("Artifacts"))
    }

    @Test
    fun variesWithToneGoalAndFormat() {
        assertNotEquals(
            buildSocialPrompt(base.copy(tone = SocialTone.CANDID)),
            buildSocialPrompt(base.copy(tone = SocialTone.ANALYTICAL)),
        )
        assertNotEquals(
            buildSocialPrompt(base.copy(goal = SocialGoal.AUTHORITY)),
            buildSocialPrompt(base.copy(goal = SocialGoal.ENGAGEMENT)),
        )
        assertNotEquals(
            buildSocialPrompt(base.copy(format = SocialFormat.HOOK_STORY)),
            buildSocialPrompt(base.copy(format = SocialFormat.TIPS)),
        )
    }

    @Test
    fun normalizesWhitespaceAndControlCharacters() {
        val prompt = buildSocialPrompt(base.copy(brief = "line one\n\tline two   spaced"))
        assertTrue(prompt.contains("line one line two spaced"))
        assertFalse(prompt.contains("\t"))
    }

    @Test
    fun isDeterministic() {
        assertEquals(buildSocialPrompt(base), buildSocialPrompt(base))
    }
}
