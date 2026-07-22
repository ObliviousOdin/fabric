"""Versioned, provider-neutral voice result contracts.

`fabric.transcription` describes terminal speech-to-text output.
`fabric.phone_audio` describes a completed capture owned by a phone client; it
does not claim that the gateway recorded the phone microphone.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

TRANSCRIPTION_SCHEMA = "fabric.transcription"
TRANSCRIPTION_VERSION = 1
PHONE_AUDIO_CONTRACT = "fabric.phone_audio"
PHONE_AUDIO_VERSION = 1
TRANSCRIPTION_STATUSES = frozenset({"completed", "no_speech", "cancelled", "failed"})
PHONE_AUDIO_MODES = frozenset({"dictate", "voice_note", "ask_fabric", "chat"})

_MAX_AUDIO_MS = 3_600_000
_MAX_TEXT_CHARS = 1_000_000
_MAX_SEGMENTS = 10_000
_MAX_WARNINGS = 64


class VoiceContractError(ValueError):
    """The value is malformed for the advertised contract version."""


class VoiceContractIncompatible(VoiceContractError):
    """The value advertises a contract version this client cannot consume."""


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VoiceContractError(f"{path} must be an object")
    return value


def _required(value: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in value:
        raise VoiceContractError(f"{path}.{key} is required")
    return value[key]


def _string(
    value: Any,
    path: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise VoiceContractError(f"{path} must be a string")
    if not allow_empty and not value.strip():
        raise VoiceContractError(f"{path} must not be empty")
    if len(value) > maximum:
        raise VoiceContractError(f"{path} exceeds its {maximum}-character limit")
    return value


def _integer(value: Any, path: str, *, maximum: int = _MAX_AUDIO_MS) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VoiceContractError(f"{path} must be an integer")
    if value < 0 or value > maximum:
        raise VoiceContractError(f"{path} must be between 0 and {maximum}")
    return value


def _optional_string(
    value: Mapping[str, Any], key: str, path: str, maximum: int
) -> None:
    if key in value:
        _string(value[key], f"{path}.{key}", maximum=maximum)


def validate_transcription_result(value: Any) -> dict[str, Any]:
    """Return a defensive copy of a verified `fabric.transcription` v1 result."""
    result = _object(value, "transcription")
    if _required(result, "schema", "transcription") != TRANSCRIPTION_SCHEMA:
        raise VoiceContractError("transcription.schema is unsupported")
    version = _required(result, "version", "transcription")
    if isinstance(version, bool) or not isinstance(version, int):
        raise VoiceContractError("transcription.version must be an integer")
    if version != TRANSCRIPTION_VERSION:
        raise VoiceContractIncompatible(
            f"transcription.version {version} is incompatible with v{TRANSCRIPTION_VERSION}"
        )

    _string(
        _required(result, "request_id", "transcription"),
        "transcription.request_id",
        maximum=128,
    )
    status = _required(result, "status", "transcription")
    if status not in TRANSCRIPTION_STATUSES:
        raise VoiceContractError("transcription.status is invalid")
    text = _string(
        _required(result, "text", "transcription"),
        "transcription.text",
        maximum=_MAX_TEXT_CHARS,
        allow_empty=True,
    )
    _optional_string(result, "provider", "transcription", 128)
    _optional_string(result, "language", "transcription", 64)
    _optional_string(result, "model", "transcription", 128)

    duration_ms = None
    if "duration_ms" in result:
        duration_ms = _integer(result["duration_ms"], "transcription.duration_ms")
    if "processing_ms" in result:
        _integer(result["processing_ms"], "transcription.processing_ms")

    segments = result.get("segments", [])
    if not isinstance(segments, list) or len(segments) > _MAX_SEGMENTS:
        raise VoiceContractError("transcription.segments must be a bounded array")
    for index, segment_value in enumerate(segments):
        path = f"transcription.segments[{index}]"
        segment = _object(segment_value, path)
        start_ms = _integer(_required(segment, "start_ms", path), f"{path}.start_ms")
        end_ms = _integer(_required(segment, "end_ms", path), f"{path}.end_ms")
        if end_ms < start_ms:
            raise VoiceContractError(f"{path}.end_ms must not precede start_ms")
        if duration_ms is not None and end_ms > duration_ms:
            raise VoiceContractError(f"{path}.end_ms exceeds transcription.duration_ms")
        _string(
            _required(segment, "text", path),
            f"{path}.text",
            maximum=_MAX_TEXT_CHARS,
            allow_empty=True,
        )

    warnings = result.get("warnings", [])
    if not isinstance(warnings, list) or len(warnings) > _MAX_WARNINGS:
        raise VoiceContractError("transcription.warnings must be a bounded array")
    for index, warning in enumerate(warnings):
        _string(
            warning,
            f"transcription.warnings[{index}]",
            maximum=1000,
            allow_empty=True,
        )

    error_value = result.get("error")
    if status == "failed":
        if text:
            raise VoiceContractError("failed transcription text must be empty")
        error = _object(error_value, "transcription.error")
        _string(
            _required(error, "code", "transcription.error"),
            "transcription.error.code",
            maximum=128,
        )
        _string(
            _required(error, "message", "transcription.error"),
            "transcription.error.message",
            maximum=4000,
        )
        if not isinstance(_required(error, "retryable", "transcription.error"), bool):
            raise VoiceContractError("transcription.error.retryable must be a boolean")
    elif error_value is not None:
        raise VoiceContractError("only failed transcriptions may contain error")
    elif status in {"no_speech", "cancelled"} and text:
        raise VoiceContractError(f"{status} transcription text must be empty")

    return copy.deepcopy(dict(result))


def validate_phone_audio(value: Any) -> dict[str, Any]:
    """Return a defensive copy of a verified client-owned phone capture."""
    envelope = _object(value, "phone_audio")
    if _required(envelope, "contract", "phone_audio") != PHONE_AUDIO_CONTRACT:
        raise VoiceContractError("phone_audio.contract is unsupported")
    version = _required(envelope, "version", "phone_audio")
    if isinstance(version, bool) or not isinstance(version, int):
        raise VoiceContractError("phone_audio.version must be an integer")
    if version != PHONE_AUDIO_VERSION:
        raise VoiceContractIncompatible(
            f"phone_audio.version {version} is incompatible with v{PHONE_AUDIO_VERSION}"
        )
    _string(
        _required(envelope, "capture_id", "phone_audio"),
        "phone_audio.capture_id",
        maximum=128,
    )
    mode = _required(envelope, "mode", "phone_audio")
    if mode not in PHONE_AUDIO_MODES:
        raise VoiceContractError("phone_audio.mode is invalid")
    mime_type = _string(
        _required(envelope, "mime_type", "phone_audio"),
        "phone_audio.mime_type",
        maximum=128,
    ).lower()
    if not (mime_type.startswith("audio/") or mime_type == "video/webm"):
        raise VoiceContractError("phone_audio.mime_type must describe audio")
    _integer(
        _required(envelope, "duration_ms", "phone_audio"), "phone_audio.duration_ms"
    )
    validate_transcription_result(_required(envelope, "result", "phone_audio"))
    return copy.deepcopy(dict(envelope))


def coerce_transcription_result(
    value: Any,
    *,
    request_id: str,
    transcript: str,
    provider: str | None,
) -> dict[str, Any]:
    """Use a valid provider result or synthesize v1 for a legacy provider."""
    if isinstance(value, Mapping):
        try:
            parsed = validate_transcription_result(value)
            if (
                parsed["status"] in {"completed", "no_speech"}
                and parsed["text"] == transcript
                and (
                    not provider
                    or not parsed.get("provider")
                    or parsed["provider"] == provider
                )
            ):
                return parsed
        except VoiceContractIncompatible:
            raise
        except VoiceContractError:
            pass

    normalized_request_id = _string(request_id, "transcription.request_id", maximum=128)
    result: dict[str, Any] = {
        "schema": TRANSCRIPTION_SCHEMA,
        "version": TRANSCRIPTION_VERSION,
        "request_id": normalized_request_id,
        "status": "completed" if transcript else "no_speech",
        "text": transcript,
        "segments": [],
        "warnings": [],
    }
    if provider:
        result["provider"] = _string(provider, "transcription.provider", maximum=128)
    return result
