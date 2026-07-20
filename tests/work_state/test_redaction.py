from __future__ import annotations

import math

import pytest

from fabric_cli.work_ledger import (
    InvalidPublicData,
    canonical_public_json,
    hash_attention_response_envelope,
    hash_job_create_envelope,
    new_work_id,
)


def test_canonical_public_json_is_stable_unicode_and_byte_bounded() -> None:
    left = canonical_public_json({"z": "é", "a": [2, 1]})
    right = canonical_public_json({"a": [2, 1], "z": "é"})
    assert left == right == '{"a":[2,1],"z":"é"}'

    with pytest.raises(InvalidPublicData):
        canonical_public_json({"value": "é" * 10}, max_bytes=20)
    with pytest.raises(InvalidPublicData):
        canonical_public_json({"bad": math.nan})
    with pytest.raises(InvalidPublicData):
        canonical_public_json({"bad": object()})


def test_job_hash_surface_has_no_prompt_parameter() -> None:
    first = hash_job_create_envelope(kind="background_prompt", title="Build")
    second = hash_job_create_envelope(kind="background_prompt", title="Build")
    changed = hash_job_create_envelope(kind="background_prompt", title="Ship")

    assert first == second
    assert first != changed

def test_attention_hash_surface_excludes_value_reason_and_answer() -> None:
    attention_id = new_work_id("attn")
    first = hash_attention_response_envelope(
        attention_id=attention_id,
        expected_version=1,
        kind="secret",
        action="submit",
    )
    second = hash_attention_response_envelope(
        attention_id=attention_id,
        expected_version=1,
        kind="secret",
        action="submit",
    )
    changed = hash_attention_response_envelope(
        attention_id=attention_id,
        expected_version=1,
        kind="secret",
        action="cancel",
    )

    assert first == second
    assert first != changed
