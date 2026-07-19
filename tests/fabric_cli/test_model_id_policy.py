"""Product-boundary tests for external model catalog identifiers."""

from __future__ import annotations

from fabric_cli.model_id_policy import (
    filter_current_model_ids,
    model_id_is_current,
    sanitize_model_catalog_payload,
)


RETIRED = bytes.fromhex("6865726d6573").decode("ascii")


def test_current_model_ids_are_preserved_without_fabric_rewrites() -> None:
    values = ["openai/gpt-5", "anthropic/claude-opus", "openai/gpt-5"]

    assert filter_current_model_ids(values) == values[:2]


def test_retired_third_party_model_ids_are_removed_not_rebranded() -> None:
    retired_id = f"nousresearch/{RETIRED}-4-405b"

    assert model_id_is_current(retired_id.upper()) is False
    assert filter_current_model_ids([retired_id, "openai/gpt-5"]) == ["openai/gpt-5"]


def test_nested_catalog_entries_and_identifier_keys_are_removed() -> None:
    retired_id = f"vendor/{RETIRED}-model"
    payload = {
        "models": [
            {"id": "vendor/current", "name": "Current"},
            {"id": retired_id, "name": "Retired"},
        ],
        retired_id: {"context_length": 4096},
        "metadata": {"provider": "vendor"},
    }

    assert sanitize_model_catalog_payload(payload) == {
        "models": [{"id": "vendor/current", "name": "Current"}],
        "metadata": {"provider": "vendor"},
    }
