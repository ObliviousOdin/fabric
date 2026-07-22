package io.github.obliviousodin.fabric.mobile.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull

const val FABRIC_TRANSCRIPTION_CONTRACT_VERSION = 1
const val FABRIC_PHONE_AUDIO_CONTRACT_VERSION = 1

data class TranscriptionSegmentV1(
    val startMs: Int,
    val endMs: Int,
    val text: String,
)

data class TranscriptionErrorV1(
    val code: String,
    val message: String,
    val retryable: Boolean,
)

data class TranscriptionResultV1(
    val requestId: String,
    val status: String,
    val text: String,
    val provider: String?,
    val language: String?,
    val durationMs: Int?,
    val processingMs: Int?,
    val model: String?,
    val segments: List<TranscriptionSegmentV1>,
    val warnings: List<String>,
    val error: TranscriptionErrorV1?,
)

data class PhoneAudioEnvelopeV1(
    val captureId: String,
    val mode: String,
    val mimeType: String,
    val durationMs: Int,
    val result: TranscriptionResultV1,
)

sealed interface VoiceContractParseResult<out T> {
    data class Verified<T>(val value: T) : VoiceContractParseResult<T>
    data class Incompatible(val contract: String, val version: Int) : VoiceContractParseResult<Nothing>
    data class Invalid(val message: String) : VoiceContractParseResult<Nothing>
}

private class VoiceContractDecodeException(message: String) : IllegalArgumentException(message)
private class VoiceContractIncompatibleException(
    val contract: String,
    val version: Int,
) : IllegalArgumentException("$contract version $version is incompatible.")

private const val MAX_AUDIO_MS = 3_600_000
private const val MAX_TEXT_CHARACTERS = 1_000_000
private val TRANSCRIPTION_STATUSES = setOf("completed", "no_speech", "cancelled", "failed")
private val PHONE_AUDIO_MODES = setOf("dictate", "voice_note", "ask_fabric", "chat")

private fun fail(message: String): Nothing = throw VoiceContractDecodeException(message)

private fun objectValue(value: JsonElement?, path: String): JsonObject =
    value as? JsonObject ?: fail("$path must be an object.")

private fun required(value: JsonObject, key: String, path: String): JsonElement =
    value[key] ?: fail("$path.$key is required.")

private fun stringValue(
    value: JsonElement?,
    path: String,
    maximum: Int,
    allowEmpty: Boolean = false,
): String {
    val primitive = value as? JsonPrimitive ?: fail("$path must be a string.")
    if (!primitive.isString) fail("$path must be a string.")
    val result = primitive.content
    if (!allowEmpty && result.isBlank()) fail("$path must not be empty.")
    if (result.length > maximum) fail("$path is too long.")
    return result
}

private fun optionalString(value: JsonObject, key: String, path: String, maximum: Int): String? =
    value[key]?.let { stringValue(it, "$path.$key", maximum) }

private fun integerValue(value: JsonElement?, path: String): Int {
    val result = (value as? JsonPrimitive)?.intOrNull ?: fail("$path must be an integer.")
    if (result !in 0..MAX_AUDIO_MS) fail("$path is outside the supported range.")
    return result
}

private fun parseTranscription(value: JsonElement): TranscriptionResultV1 {
    val raw = objectValue(value, "transcription")
    if (stringValue(required(raw, "schema", "transcription"), "transcription.schema", 128) != "fabric.transcription") {
        fail("transcription.schema is unsupported.")
    }
    val version = (required(raw, "version", "transcription") as? JsonPrimitive)?.intOrNull
        ?: fail("transcription.version must be an integer.")
    if (version != FABRIC_TRANSCRIPTION_CONTRACT_VERSION) {
        throw VoiceContractIncompatibleException("fabric.transcription", version)
    }
    val requestId = stringValue(required(raw, "request_id", "transcription"), "transcription.request_id", 128)
    val status = stringValue(required(raw, "status", "transcription"), "transcription.status", 32)
    if (status !in TRANSCRIPTION_STATUSES) fail("transcription.status is invalid.")
    val text = stringValue(
        required(raw, "text", "transcription"),
        "transcription.text",
        MAX_TEXT_CHARACTERS,
        allowEmpty = true,
    )
    val duration = raw["duration_ms"]?.let { integerValue(it, "transcription.duration_ms") }
    val processing = raw["processing_ms"]?.let { integerValue(it, "transcription.processing_ms") }

    val segmentValues = raw["segments"] ?: JsonArray(emptyList())
    val segmentArray = segmentValues as? JsonArray ?: fail("transcription.segments must be an array.")
    if (segmentArray.size > 10_000) fail("transcription.segments is too large.")
    val segments = segmentArray.mapIndexed { index, item ->
        val path = "transcription.segments[$index]"
        val segment = objectValue(item, path)
        val start = integerValue(required(segment, "start_ms", path), "$path.start_ms")
        val end = integerValue(required(segment, "end_ms", path), "$path.end_ms")
        if (end < start) fail("$path.end_ms must not precede start_ms.")
        if (duration != null && end > duration) fail("$path.end_ms exceeds transcription.duration_ms.")
        TranscriptionSegmentV1(
            startMs = start,
            endMs = end,
            text = stringValue(required(segment, "text", path), "$path.text", MAX_TEXT_CHARACTERS, true),
        )
    }

    val warningValues = raw["warnings"] ?: JsonArray(emptyList())
    val warningArray = warningValues as? JsonArray ?: fail("transcription.warnings must be an array.")
    if (warningArray.size > 64) fail("transcription.warnings is too large.")
    val warnings = warningArray.mapIndexed { index, item ->
        stringValue(item, "transcription.warnings[$index]", 1_000, true)
    }

    val error = if (status == "failed") {
        if (text.isNotEmpty()) fail("failed transcription text must be empty.")
        val errorValue = objectValue(required(raw, "error", "transcription"), "transcription.error")
        val retryable = (required(errorValue, "retryable", "transcription.error") as? JsonPrimitive)
            ?.booleanOrNull ?: fail("transcription.error.retryable must be a boolean.")
        TranscriptionErrorV1(
            code = stringValue(required(errorValue, "code", "transcription.error"), "transcription.error.code", 128),
            message = stringValue(
                required(errorValue, "message", "transcription.error"),
                "transcription.error.message",
                4_000,
            ),
            retryable = retryable,
        )
    } else {
        if (raw["error"] != null) fail("only failed transcriptions may contain error.")
        if (status in setOf("no_speech", "cancelled") && text.isNotEmpty()) {
            fail("$status transcription text must be empty.")
        }
        null
    }

    return TranscriptionResultV1(
        requestId = requestId,
        status = status,
        text = text,
        provider = optionalString(raw, "provider", "transcription", 128),
        language = optionalString(raw, "language", "transcription", 64),
        durationMs = duration,
        processingMs = processing,
        model = optionalString(raw, "model", "transcription", 128),
        segments = segments,
        warnings = warnings,
        error = error,
    )
}

private inline fun <T> parseContract(block: () -> T): VoiceContractParseResult<T> =
    try {
        VoiceContractParseResult.Verified(block())
    } catch (error: VoiceContractIncompatibleException) {
        VoiceContractParseResult.Incompatible(error.contract, error.version)
    } catch (error: VoiceContractDecodeException) {
        VoiceContractParseResult.Invalid(error.message ?: "Voice contract is malformed.")
    } catch (_: Exception) {
        VoiceContractParseResult.Invalid("Voice contract is malformed.")
    }

fun parseTranscriptionResult(value: JsonElement): VoiceContractParseResult<TranscriptionResultV1> =
    parseContract { parseTranscription(value) }

fun parsePhoneAudio(value: JsonElement): VoiceContractParseResult<PhoneAudioEnvelopeV1> =
    parseContract {
        val raw = objectValue(value, "phone_audio")
        val contract = stringValue(required(raw, "contract", "phone_audio"), "phone_audio.contract", 128)
        if (contract != "fabric.phone_audio") fail("phone_audio.contract is unsupported.")
        val version = (required(raw, "version", "phone_audio") as? JsonPrimitive)?.intOrNull
            ?: fail("phone_audio.version must be an integer.")
        if (version != FABRIC_PHONE_AUDIO_CONTRACT_VERSION) {
            throw VoiceContractIncompatibleException(contract, version)
        }
        val mode = stringValue(required(raw, "mode", "phone_audio"), "phone_audio.mode", 32)
        if (mode !in PHONE_AUDIO_MODES) fail("phone_audio.mode is invalid.")
        val mimeType = stringValue(
            required(raw, "mime_type", "phone_audio"),
            "phone_audio.mime_type",
            128,
        ).lowercase()
        if (!mimeType.startsWith("audio/") && mimeType != "video/webm") {
            fail("phone_audio.mime_type must describe audio.")
        }
        PhoneAudioEnvelopeV1(
            captureId = stringValue(
                required(raw, "capture_id", "phone_audio"),
                "phone_audio.capture_id",
                128,
            ),
            mode = mode,
            mimeType = mimeType,
            durationMs = integerValue(required(raw, "duration_ms", "phone_audio"), "phone_audio.duration_ms"),
            result = parseTranscription(required(raw, "result", "phone_audio")),
        )
    }
