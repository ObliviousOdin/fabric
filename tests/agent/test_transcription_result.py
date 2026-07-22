from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from agent.transcription_result import (
    VoiceContractError,
    VoiceContractIncompatible,
    coerce_transcription_result,
    validate_phone_audio,
    validate_transcription_result,
)

FIXTURES = (
    Path(__file__).parents[2] / "apps" / "mobile" / "contracts" / "fabric-voice-v1"
)


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_canonical_schemas_accept_positive_fixture_corpus():
    transcription_schema = fixture("transcription-result.schema.json")
    phone_schema = fixture("phone-audio.schema.json")
    Draft202012Validator.check_schema(transcription_schema)
    Draft202012Validator.check_schema(phone_schema)
    registry = Registry().with_resources([
        (
            transcription_schema["$id"],
            Resource.from_contents(transcription_schema),
        ),
        (phone_schema["$id"], Resource.from_contents(phone_schema)),
    ])
    transcription_validator = Draft202012Validator(
        transcription_schema, registry=registry
    )
    phone_validator = Draft202012Validator(phone_schema, registry=registry)

    for name in (
        "transcription-completed.json",
        "transcription-failed.json",
        "transcription-additive-future.json",
    ):
        transcription_validator.validate(fixture(name))
    for name in ("phone-audio-voice-note.json", "phone-audio-chat.json"):
        phone_validator.validate(fixture(name))


@pytest.mark.parametrize(
    "name",
    [
        "transcription-completed.json",
        "transcription-failed.json",
        "transcription-additive-future.json",
    ],
)
def test_transcription_v1_accepts_canonical_fixtures(name):
    value = fixture(name)
    assert validate_transcription_result(value) == value


def test_transcription_v1_distinguishes_incompatible_and_invalid():
    with pytest.raises(VoiceContractIncompatible):
        validate_transcription_result(fixture("transcription-incompatible.json"))
    with pytest.raises(VoiceContractError):
        validate_transcription_result(fixture("transcription-malformed.json"))


def test_transcription_v1_rejects_error_field_for_non_failed_status():
    schema = fixture("transcription-result.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    value = fixture("transcription-completed.json")
    validator.validate(value)
    value["error"] = None

    with pytest.raises(VoiceContractError, match="only failed"):
        validate_transcription_result(value)

    errors = list(validator.iter_errors(value))
    assert errors, "the canonical schema must reject error on a completed result"


@pytest.mark.parametrize(
    "name", ["phone-audio-voice-note.json", "phone-audio-chat.json"]
)
def test_phone_audio_accepts_client_owned_capture_fixtures(name):
    value = fixture(name)
    assert validate_phone_audio(value) == value


def test_phone_audio_rejects_gateway_like_or_malformed_capture():
    with pytest.raises(VoiceContractError):
        validate_phone_audio(fixture("phone-audio-malformed.json"))


def test_phone_audio_requires_canonical_mime_type():
    mime_schema = fixture("phone-audio.schema.json")["properties"]["mime_type"]
    validator = Draft202012Validator(mime_schema)
    envelope = fixture("phone-audio-voice-note.json")

    for mime_type in ("Audio/WAV", "audio/", "audio/webm;Codecs=opus", "audio/wav\n"):
        envelope["mime_type"] = mime_type
        with pytest.raises(VoiceContractError, match="MIME|mime_type"):
            validate_phone_audio(envelope)
        assert list(validator.iter_errors(mime_type))


def test_malformed_enum_types_raise_contract_errors():
    result = fixture("transcription-completed.json")
    result["status"] = []
    with pytest.raises(VoiceContractError, match="status must be a string"):
        validate_transcription_result(result)

    envelope = fixture("phone-audio-voice-note.json")
    envelope["mode"] = {}
    with pytest.raises(VoiceContractError, match="mode must be a string"):
        validate_phone_audio(envelope)


def test_string_limits_count_unicode_code_points():
    result = fixture("transcription-completed.json")
    result["provider"] = "😀" * 128
    validate_transcription_result(result)

    result["provider"] = "😀" * 129
    with pytest.raises(VoiceContractError, match="character limit"):
        validate_transcription_result(result)

    result["provider"] = "e\u0301" * 65
    with pytest.raises(VoiceContractError, match="character limit"):
        validate_transcription_result(result)


def test_coerce_preserves_valid_additive_result():
    value = fixture("transcription-additive-future.json")
    assert (
        coerce_transcription_result(
            value,
            request_id=value["request_id"],
            transcript=value["text"],
            provider="fixture",
        )
        == value
    )


def test_coerce_synthesizes_v1_for_legacy_or_mismatched_provider_result():
    result = coerce_transcription_result(
        {"schema": "wrong"},
        request_id="capture-legacy-1",
        transcript="legacy transcript",
        provider="local",
    )
    assert result == {
        "schema": "fabric.transcription",
        "version": 1,
        "request_id": "capture-legacy-1",
        "status": "completed",
        "text": "legacy transcript",
        "provider": "local",
        "segments": [],
        "warnings": [],
    }


def test_coerce_replaces_structured_result_with_mismatched_request_id():
    value = fixture("transcription-additive-future.json")
    value["request_id"] = "stale-request"

    result = coerce_transcription_result(
        value,
        request_id="expected-request",
        transcript=value["text"],
        provider="fixture",
    )

    assert result["request_id"] == "expected-request"
    assert "future_metadata" not in result
    validate_transcription_result(result)


def test_coerce_rejects_results_that_exceed_contract_limits():
    with pytest.raises(VoiceContractError, match="character limit"):
        coerce_transcription_result(
            None,
            request_id="capture-too-long",
            transcript="x" * 1_000_001,
            provider="fixture",
        )


def test_coerce_does_not_flatten_an_explicit_future_contract():
    with pytest.raises(VoiceContractIncompatible):
        coerce_transcription_result(
            fixture("transcription-incompatible.json"),
            request_id="capture-v2-1",
            transcript="A v1 client must reject this result.",
            provider="future-provider",
        )
