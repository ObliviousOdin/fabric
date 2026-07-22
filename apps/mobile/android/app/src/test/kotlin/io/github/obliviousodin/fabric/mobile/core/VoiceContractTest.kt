package io.github.obliviousodin.fabric.mobile.core

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceContractTest {
    @Test
    fun canonicalFixtureCorpusMatchesEveryExpectedResult() {
        val manifest = fixture("voice-manifest.json").jsonObject
        assertEquals("fabric.voice.fixture-manifest", manifest["name"]?.jsonPrimitive?.content)
        val cases = manifest["cases"] as JsonArray
        cases.forEach { item ->
            val fixtureCase = item.jsonObject
            val file = fixtureCase.getValue("file").jsonPrimitive.content
            val kind = fixtureCase.getValue("kind").jsonPrimitive.content
            val expected = fixtureCase.getValue("expected").jsonPrimitive.content
            val parsed = if (kind == "phone_audio") {
                parsePhoneAudio(fixture(file))
            } else {
                parseTranscriptionResult(fixture(file))
            }
            assertEquals(file, expected, resultKind(parsed))
        }
    }

    @Test
    fun voiceNoteKeepsCaptureModeAndClientOwnershipExplicit() {
        val parsed = parsePhoneAudio(fixture("phone-audio-voice-note.json"))
        assertTrue(parsed is VoiceContractParseResult.Verified)
        val value = (parsed as VoiceContractParseResult.Verified).value
        assertEquals("voice_note", value.mode)
        assertEquals("audio/mp4", value.mimeType)
        assertEquals("completed", value.result.status)
    }

    private fun resultKind(value: VoiceContractParseResult<*>): String = when (value) {
        is VoiceContractParseResult.Verified -> "verified"
        is VoiceContractParseResult.Incompatible -> "incompatible"
        is VoiceContractParseResult.Invalid -> "invalid"
    }

    private fun fixture(name: String) = Json.parseToJsonElement(
        fixtureFile(name).readText(),
    )

    private fun fixtureFile(name: String): File {
        val roots = listOf(
            File(System.getProperty("user.dir")),
            File(System.getProperty("user.dir")).parentFile,
            File(System.getProperty("user.dir")).parentFile?.parentFile,
            File(System.getProperty("user.dir")).parentFile?.parentFile?.parentFile,
        ).filterNotNull()
        return roots
            .map { root -> File(root, "apps/mobile/contracts/fabric-voice-v1/$name") }
            .firstOrNull { it.isFile }
            ?: error("Could not find canonical voice fixture $name")
    }
}
