"""Test that overlay providers with mismatched models.dev keys resolve correctly.

FABRIC_OVERLAYS keys may be models.dev IDs (e.g. "github-copilot") while
_PROVIDER_MODELS and config.yaml use Fabric IDs ("copilot").  The slug
resolution in list_authenticated_providers() Section 2 must bridge this gap.

Covers: #5223, #6492
"""

import os
from unittest.mock import patch


from fabric_cli.model_switch import list_authenticated_providers


# -- Copilot slug resolution (env var path) ----------------------------------

@patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "fake-ghu"}, clear=False)
def test_copilot_uses_fabric_slug():
    """github-copilot overlay should resolve to slug='copilot' with curated models."""
    providers = list_authenticated_providers(current_provider="copilot")

    copilot = next((p for p in providers if p["slug"] == "copilot"), None)
    assert copilot is not None, "copilot should appear when COPILOT_GITHUB_TOKEN is set"
    assert copilot["total_models"] > 0, "copilot should have curated models"
    assert copilot["is_current"] is True

    # Must NOT appear under the models.dev key
    gh_copilot = next((p for p in providers if p["slug"] == "github-copilot"), None)
    assert gh_copilot is None, "github-copilot slug should not appear (resolved to copilot)"


@patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "fake-ghu"}, clear=False)
def test_copilot_no_duplicate_entries():
    """Copilot must appear only once — not as both 'copilot' (section 1) and 'github-copilot' (section 2)."""
    providers = list_authenticated_providers(current_provider="copilot")

    copilot_slugs = [p["slug"] for p in providers if "copilot" in p["slug"]]
    # Should have at most one copilot entry (may also have copilot-acp if creds exist)
    copilot_main = [s for s in copilot_slugs if s == "copilot"]
    assert len(copilot_main) == 1, f"Expected exactly one 'copilot' entry, got {copilot_main}"


# -- kimi-for-coding alias in auth.py ----------------------------------------

def test_kimi_for_coding_alias():
    """resolve_provider('kimi-for-coding') should return 'kimi-coding'."""
    from fabric_cli.auth import resolve_provider

    result = resolve_provider("kimi-for-coding")
    assert result == "kimi-coding"


# -- Generic slug mismatch providers -----------------------------------------

@patch.dict(os.environ, {"KIMI_API_KEY": "fake-key"}, clear=False)
def test_kimi_for_coding_overlay_uses_fabric_slug():
    """kimi-for-coding overlay should resolve to slug='kimi-coding'."""
    providers = list_authenticated_providers(current_provider="kimi-coding")

    kimi = next((p for p in providers if p["slug"] == "kimi-coding"), None)
    assert kimi is not None, "kimi-coding should appear when KIMI_API_KEY is set"
    assert kimi["is_current"] is True

    # Must NOT appear under the models.dev key
    kimi_mdev = next((p for p in providers if p["slug"] == "kimi-for-coding"), None)
    assert kimi_mdev is None, "kimi-for-coding slug should not appear (resolved to kimi-coding)"


@patch.dict(os.environ, {"KILOCODE_API_KEY": "fake-key"}, clear=False)
def test_kilo_overlay_uses_fabric_slug():
    """kilo overlay should resolve to slug='kilocode'."""
    providers = list_authenticated_providers(current_provider="kilocode")

    kilo = next((p for p in providers if p["slug"] == "kilocode"), None)
    assert kilo is not None, "kilocode should appear when KILOCODE_API_KEY is set"
    assert kilo["is_current"] is True

    kilo_mdev = next((p for p in providers if p["slug"] == "kilo"), None)
    assert kilo_mdev is None, "kilo slug should not appear (resolved to kilocode)"



def test_mapped_provider_credential_pool_visibility(monkeypatch):
    """Mapped providers should appear when credentials live only in auth-store credential_pool."""
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {"google-ai-studio": {"env": ["GEMINI_API_KEY"]}})
    monkeypatch.setattr("agent.models_dev.PROVIDER_TO_MODELS_DEV", {"gemini": "google-ai-studio"})
    monkeypatch.setattr(
        "fabric_cli.auth._load_auth_store",
        lambda: {
            "providers": {},
            "credential_pool": {
                "gemini": [{
                    "id": "gemini-key",
                    "auth_type": "api_key",
                    "priority": 0,
                    "source": "manual",
                    "access_token": "fake",
                }]
            },
        },
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    providers = list_authenticated_providers(current_provider="gemini")

    gemini = next((p for p in providers if p["slug"] == "gemini"), None)
    assert gemini is not None, "gemini should appear when auth-store credential_pool has creds"
    assert gemini["is_current"] is True
    assert gemini["total_models"] > 0


def test_anthropic_legacy_oauth_pool_is_not_advertised(
    tmp_path, monkeypatch
):
    """The picker must not offer a provider runtime will immediately reject."""
    import json

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(fabric_home))
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    (fabric_home / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "credential_pool": {
                "anthropic": [{
                    "id": "retired-oauth",
                    "auth_type": "oauth",
                    "priority": 0,
                    "source": "manual:anthropic_pkce",
                    "access_token": "sk-ant-oat01-retired",
                }]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent.models_dev.fetch_models_dev",
        lambda: {"anthropic": {"env": ["ANTHROPIC_API_KEY"]}},
    )
    monkeypatch.setattr(
        "agent.models_dev.PROVIDER_TO_MODELS_DEV",
        {"anthropic": "anthropic"},
    )

    providers = list_authenticated_providers(current_provider="openrouter")

    assert not any(row["slug"] == "anthropic" for row in providers)


def test_anthropic_oauth_shape_in_api_key_env_is_not_advertised(
    tmp_path, monkeypatch
):
    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(fabric_home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat01-wrong-slot")
    monkeypatch.setattr(
        "agent.models_dev.fetch_models_dev",
        lambda: {"anthropic": {"env": ["ANTHROPIC_API_KEY"]}},
    )
    monkeypatch.setattr(
        "agent.models_dev.PROVIDER_TO_MODELS_DEV",
        {"anthropic": "anthropic"},
    )

    providers = list_authenticated_providers(current_provider="openrouter")

    assert not any(row["slug"] == "anthropic" for row in providers)


def test_anthropic_offline_overlay_rejects_legacy_credentials(
    tmp_path, monkeypatch
):
    """Section 2 must keep filtered status authoritative when models.dev is empty."""
    import json

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(fabric_home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat01-wrong-slot")
    (fabric_home / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "providers": {
                "anthropic": {
                    "access_token": "sk-ant-oat01-retired-singleton"
                }
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})
    monkeypatch.setattr(
        "agent.models_dev.PROVIDER_TO_MODELS_DEV",
        {"anthropic": "anthropic"},
    )

    providers = list_authenticated_providers(current_provider="openrouter")

    assert not any(row["slug"] == "anthropic" for row in providers)


def test_anthropic_offline_overlay_accepts_manual_api_key_pool(
    tmp_path, monkeypatch
):
    import json

    fabric_home = tmp_path / ".fabric"
    fabric_home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(fabric_home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (fabric_home / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "credential_pool": {
                "anthropic": [{
                    "id": "manual-key",
                    "label": "work key",
                    "auth_type": "api_key",
                    "priority": 0,
                    "source": "manual",
                    "access_token": "sk-ant-api03-valid",
                }]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})
    monkeypatch.setattr(
        "agent.models_dev.PROVIDER_TO_MODELS_DEV",
        {"anthropic": "anthropic"},
    )

    providers = list_authenticated_providers(current_provider="anthropic")

    anthropic = next(
        (row for row in providers if row["slug"] == "anthropic"),
        None,
    )
    assert anthropic is not None
    assert anthropic["is_current"] is True
    assert anthropic["total_models"] > 0
