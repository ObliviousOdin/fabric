"""Regression tests for the Anthropic model-picker dropping curated aliases.

Bug — newly-routed curated aliases vanished on a native Anthropic setup
    ``provider_model_ids("anthropic")`` returned the live ``/v1/models`` dump
    verbatim whenever Anthropic credentials were configured. Anthropic's API
    lags behind freshly-routed aliases (e.g. ``claude-fable-5``, which is
    reachable on Anthropic before the models endpoint enumerates it), so the
    curated entry disappeared from the picker. The picker now merges the
    curated ``_PROVIDER_MODELS["anthropic"]`` list with the live catalog —
    curated entries first, live-only models appended, deduped — mirroring the
    OpenAI curated-merge philosophy.
"""

import json
from unittest.mock import patch

from fabric_cli import models as M


def test_anthropic_curated_alias_survives_when_live_omits_it():
    """A curated alias missing from /v1/models still surfaces (first)."""
    curated = M._PROVIDER_MODELS["anthropic"]
    assert "claude-fable-5" in curated  # sanity: the alias is curated

    # Live catalog the API would actually return — no fable-5.
    live = ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
    with patch.object(M, "_fetch_anthropic_models", return_value=live):
        result = M.provider_model_ids("anthropic")

    assert "claude-fable-5" in result
    # Curated order is preserved at the front.
    assert result[:len(curated)] == list(curated)


def test_anthropic_merge_dedupes_overlap_and_appends_live_only():
    """Models in both lists appear once; live-only models are appended."""
    live = [
        "claude-opus-4-8",          # overlaps curated
        "claude-sonnet-4-6",        # overlaps curated
        "claude-future-9-99",       # live-only, not curated
    ]
    with patch.object(M, "_fetch_anthropic_models", return_value=live):
        result = M.provider_model_ids("anthropic")

    # No duplicates introduced by the merge.
    assert result.count("claude-opus-4-8") == 1
    # Live-only entry is preserved (discovery still works for unknown models).
    assert "claude-future-9-99" in result
    # Curated entries lead, live-only trails.
    assert result.index("claude-fable-5") < result.index("claude-future-9-99")


def test_anthropic_falls_back_to_curated_when_live_unavailable():
    """No creds / live failure -> curated list verbatim (alias still present)."""
    with patch.object(M, "_fetch_anthropic_models", return_value=None):
        result = M.provider_model_ids("anthropic")

    assert result == list(M._PROVIDER_MODELS["anthropic"])
    assert "claude-fable-5" in result


def test_anthropic_live_fetch_resolves_key_for_target_endpoint():
    base_url = "https://gateway.example/anthropic"
    with (
        patch(
            "fabric_cli.auth.resolve_api_key_provider_credentials",
            return_value={
                "api_key": "eyJ.proxy.signature",
                "base_url": base_url,
            },
        ) as resolve,
        patch("urllib.request.urlopen", side_effect=OSError("offline")),
    ):
        assert M._fetch_anthropic_models(base_url=base_url) is None

    resolve.assert_called_once_with("anthropic")


def test_anthropic_live_fetch_keeps_env_proxy_key_and_endpoint_paired(
    monkeypatch,
):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"data": [{"id": "proxy-model"}]}).encode()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "eyJ.gateway-a.signature")
    monkeypatch.setenv(
        "ANTHROPIC_BASE_URL",
        "https://gateway-a.example/anthropic",
    )
    with patch(
        "fabric_cli.models.urllib.request.urlopen",
        return_value=_Response(),
    ) as urlopen:
        assert M._fetch_anthropic_models() == ["proxy-model"]

    request = urlopen.call_args.args[0]
    assert request.full_url == (
        "https://gateway-a.example/anthropic/v1/models"
    )
    assert request.get_header("X-api-key") == "eyJ.gateway-a.signature"


def test_anthropic_live_fetch_rejects_key_endpoint_mismatch():
    with patch(
        "fabric_cli.auth.resolve_api_key_provider_credentials",
        return_value={
            "api_key": "eyJ.gateway-a.signature",
            "base_url": "https://gateway-a.example/anthropic",
        },
    ), patch("fabric_cli.models.urllib.request.urlopen") as urlopen:
        assert M._fetch_anthropic_models(
            base_url="https://gateway-b.example/anthropic"
        ) is None

    urlopen.assert_not_called()
