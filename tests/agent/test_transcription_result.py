from __future__ import annotations

import json
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "name", ["phone-audio-voice-note.json", "phone-audio-chat.json"]
)
def test_phone_audio_accepts_client_owned_capture_fixtures(name):
    value = fixture(name)
    assert validate_phone_audio(value) == value


def test_phone_audio_rejects_gateway_like_or_malformed_capture():
    with pytest.raises(VoiceContractError):
        validate_phone_audio(fixture("phone-audio-malformed.json"))


def test_coerce_preserves_valid_additive_result():
    value = fixture("transcription-additive-future.json")
    assert (
        coerce_transcription_result(
            value,
            request_id="fallback",
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


def test_coerce_does_not_flatten_an_explicit_future_contract():
    with pytest.raises(VoiceContractIncompatible):
        coerce_transcription_result(
            fixture("transcription-incompatible.json"),
            request_id="capture-v2-1",
            transcript="A v1 client must reject this result.",
            provider="future-provider",
        )
