"""Fabric default capability catalog tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _use_default_capability_config(monkeypatch):
    """These tests exercise the curated defaults, unlike the suite default."""
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )


def test_fabric_catalog_enabled_defaults_on(monkeypatch):
    from fabric_cli.fabric_capabilities import fabric_catalog_enabled

    assert fabric_catalog_enabled() is True


def test_fabric_catalog_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {"enabled": True},
    )

    from fabric_cli.fabric_capabilities import fabric_catalog_enabled

    assert fabric_catalog_enabled() is True


def test_fabric_catalog_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {"enabled": False},
    )

    from fabric_cli.fabric_capabilities import fabric_catalog_enabled

    assert fabric_catalog_enabled() is False


def test_filter_fabric_keys_preserves_allowed_order(monkeypatch):
    from fabric_cli.fabric_capabilities import FABRIC_GATEWAY_PLATFORMS, filter_fabric_keys

    values = ["telegram", "discord", "slack", "api_server", "openai-codex"]

    assert filter_fabric_keys(values, FABRIC_GATEWAY_PLATFORMS) == [
        "discord",
        "slack",
        "api_server",
    ]


def test_filter_fabric_keys_returns_all_when_catalog_disabled(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {"enabled": False},
    )

    from fabric_cli.fabric_capabilities import FABRIC_GATEWAY_PLATFORMS, filter_fabric_keys

    values = ["telegram", "discord", "slack", "api_server"]

    assert filter_fabric_keys(values, FABRIC_GATEWAY_PLATFORMS) == values


def test_fabric_provider_sets_are_curated():
    from fabric_cli.fabric_capabilities import (
        FABRIC_GATEWAY_PLATFORMS,
        FABRIC_MEMORY_PROVIDERS,
        FABRIC_MODEL_PROVIDERS,
    )

    assert FABRIC_GATEWAY_PLATFORMS == ("discord", "slack", "api_server")
    # Keep the proven multi-model baseline while excluding the opt-in Nous
    # Portal integration. Additions remain welcome without turning this into
    # an enumeration-count/change-detector test.
    expected_major_providers = {
        "openrouter",
        "ollama",
        "lmstudio",
        "anthropic",
        "openai-codex",
        "openai-api",
        "xai-oauth",
        "gemini",
        "deepseek",
        "xai",
        "ollama-cloud",
    }
    assert expected_major_providers.issubset(FABRIC_MODEL_PROVIDERS)
    assert "nous" not in FABRIC_MODEL_PROVIDERS
    assert "honcho" in FABRIC_MEMORY_PROVIDERS


def test_canonical_providers_are_fabric_filtered(monkeypatch):
    import fabric_cli.models as models
    from fabric_cli.fabric_capabilities import FABRIC_MODEL_PROVIDERS

    slugs = [p.slug for p in models.fabric_canonical_providers()]

    assert slugs == [
        p.slug
        for p in models.CANONICAL_PROVIDERS
        if p.slug in set(FABRIC_MODEL_PROVIDERS)
    ]


def test_canonical_providers_can_show_upstream_catalog(monkeypatch):
    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"enabled": False})

    import fabric_cli.models as models

    slugs = [p.slug for p in models.fabric_canonical_providers()]

    assert "openai-codex" in slugs
    assert "xai-oauth" in slugs
    assert "anthropic" in slugs


def test_nous_visibility_requires_explicit_opt_in(monkeypatch):
    from fabric_cli.fabric_capabilities import fabric_model_provider_visible

    assert fabric_model_provider_visible("openai-codex") is True
    assert fabric_model_provider_visible("xai") is True
    assert fabric_model_provider_visible("nous") is False

    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"model_providers": "openai-api,nous".split(",")})
    assert fabric_model_provider_visible("nous") is True

    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"enabled": False})
    assert fabric_model_provider_visible("nous") is True


def test_model_inventory_unconfigured_rows_are_fabric_filtered(monkeypatch):
    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"model_providers": "openai-codex,xai-oauth".split(",")})

    from fabric_cli.inventory import ConfigContext, build_models_payload

    ctx = ConfigContext(
        current_provider="",
        current_model="",
        current_base_url="",
        user_providers={},
        custom_providers=[],
    )
    with patch("fabric_cli.model_switch.list_authenticated_providers", return_value=[]):
        payload = build_models_payload(ctx, include_unconfigured=True, canonical_order=True)

    assert [row["slug"] for row in payload["providers"]] == ["openai-codex", "xai-oauth"]


def test_model_inventory_authenticated_rows_are_fabric_filtered(monkeypatch):

    from fabric_cli.inventory import ConfigContext, build_models_payload

    ctx = ConfigContext(
        current_provider="",
        current_model="",
        current_base_url="",
        user_providers={},
        custom_providers=[],
    )
    rows = [
        {"slug": "anthropic", "name": "Anthropic", "models": ["claude"], "total_models": 1},
        {"slug": "bedrock", "name": "AWS Bedrock", "models": ["claude"], "total_models": 1},
        {"slug": "openai-codex", "name": "OpenAI Codex", "models": ["gpt"], "total_models": 1},
        {"slug": "xai-oauth", "name": "xAI Grok OAuth", "models": ["grok"], "total_models": 1},
    ]
    with patch("fabric_cli.model_switch.list_authenticated_providers", return_value=rows):
        payload = build_models_payload(ctx, include_unconfigured=False, canonical_order=True)

    assert [row["slug"] for row in payload["providers"]] == [
        "anthropic",
        "openai-codex",
        "xai-oauth",
    ]


def test_classic_model_picker_requests_visible_unconfigured_providers(monkeypatch):
    """`/model` must show Codex before authentication, with setup affordance."""
    import cli as cli_mod
    import fabric_cli.inventory as inventory

    ctx = SimpleNamespace(
        user_providers={},
        custom_providers=[],
        model_config={},
        restricted_egress=False,
    )
    ctx.with_overrides = lambda **_kwargs: ctx
    captured = {}

    def build_payload(_ctx, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "providers": [
                {
                    "slug": "openai-codex",
                    "name": "OpenAI Codex",
                    "authenticated": False,
                    "models": [],
                    "total_models": 0,
                    "warning": "run `fabric model` to configure (oauth_device_code)",
                }
            ]
        }

    monkeypatch.setattr(inventory, "load_picker_context", lambda: ctx)
    monkeypatch.setattr(inventory, "build_models_payload", build_payload)
    monkeypatch.setattr(
        "fabric_cli.model_switch.parse_model_flags",
        lambda _raw: ("", "", False, False, False),
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch.resolve_persist_behavior",
        lambda *_args, **_kwargs: False,
    )

    def open_picker(providers, *_args, **_kwargs):
        captured["providers"] = providers

    self_ = SimpleNamespace(
        model="grok-4.5",
        provider="xai-oauth",
        base_url="",
        api_key="",
        _open_model_picker=open_picker,
    )

    cli_mod.FabricCLI._handle_model_switch(self_, "/model")

    assert captured["kwargs"] == {
        "include_unconfigured": True,
        "picker_hints": True,
        "canonical_order": True,
    }
    assert [row["slug"] for row in captured["providers"]] == ["openai-codex"]


def test_classic_model_picker_routes_unconfigured_codex_to_setup(monkeypatch):
    import cli as cli_mod

    messages = []
    monkeypatch.setattr(cli_mod, "_cprint", messages.append)
    self_ = SimpleNamespace(
        _model_picker_state={
            "stage": "provider",
            "providers": [
                {
                    "slug": "openai-codex",
                    "name": "OpenAI Codex",
                    "authenticated": False,
                }
            ],
            "selected": 0,
        },
    )
    self_._close_model_picker = lambda: setattr(self_, "_model_picker_state", None)

    cli_mod.FabricCLI._handle_model_picker_selection(self_)

    assert self_._model_picker_state is None
    assert any("OpenAI Codex needs setup" in line for line in messages)
    assert any("fabric auth add openai-codex" in line for line in messages)


def test_config_list_narrows_a_catalog(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {"model_providers": ["anthropic"]},
    )

    import fabric_cli.models as models

    slugs = [p.slug for p in models.fabric_canonical_providers()]

    assert slugs == ["anthropic"]


def test_config_list_widens_beyond_the_default(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {
            "model_providers": ["openai-codex", " Bedrock ", "azure-foundry"]
        },
    )

    import fabric_cli.models as models

    slugs = [p.slug for p in models.fabric_canonical_providers()]

    assert slugs == ["openai-codex", "bedrock", "azure-foundry"]


def test_null_lifts_filtering_for_one_catalog(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {"model_providers": None},
    )

    import fabric_cli.models as models
    from fabric_cli.fabric_capabilities import FABRIC_GATEWAY_PLATFORMS, filter_fabric_keys

    slugs = [p.slug for p in models.fabric_canonical_providers()]
    assert slugs == [p.slug for p in models.CANONICAL_PROVIDERS]

    # Other catalogs stay on their defaults.
    values = ["telegram", "discord", "slack", "api_server"]
    assert filter_fabric_keys(values, FABRIC_GATEWAY_PLATFORMS) == [
        "discord",
        "slack",
        "api_server",
    ]


def test_null_lifts_gateway_filtering(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {"gateway_platforms": None},
    )

    from fabric_cli.fabric_capabilities import FABRIC_GATEWAY_PLATFORMS, filter_fabric_keys

    values = ["telegram", "discord", "slack", "api_server", "whatsapp"]
    assert filter_fabric_keys(values, FABRIC_GATEWAY_PLATFORMS) == values


def test_missing_config_list_falls_back_to_default(monkeypatch):
    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {})

    from fabric_cli.fabric_capabilities import FABRIC_GATEWAY_PLATFORMS, filter_fabric_keys

    values = ["telegram", "discord", "slack", "api_server"]
    assert filter_fabric_keys(values, FABRIC_GATEWAY_PLATFORMS) == [
        "discord",
        "slack",
        "api_server",
    ]


def test_config_override_reaches_the_memory_picker(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {"memory_providers": ["mem0", "supermemory"]},
    )

    from fabric_cli import memory_setup

    class FakeProvider:
        def get_config_schema(self):
            return []

    raw = [
        ("mem0", "Mem0", True),
        ("honcho", "Honcho", True),
        ("supermemory", "Supermemory", True),
        ("hindsight", "Hindsight", True),
    ]
    with patch("plugins.memory.discover_memory_providers", return_value=raw), patch(
        "plugins.memory.load_memory_provider",
        side_effect=lambda name: FakeProvider(),
    ):
        providers = memory_setup._get_available_providers()

    assert [name for name, _desc, _provider in providers] == ["mem0", "supermemory"]


def test_every_catalog_has_a_distinct_config_key():
    # A content collision between two default tuples would make one config
    # field unreachable, so catch that invariant here.
    from fabric_cli import fabric_capabilities as fc

    assert len(fc._CATALOG_CONFIG_KEYS) == 5


def test_fabric_canonical_providers_fails_open(monkeypatch):
    # If the catalog module misbehaves, pickers must degrade to the full
    # catalog rather than crashing.
    import fabric_cli.models as models

    def boom(*_args, **_kwargs):
        raise RuntimeError("fork hook broken")

    monkeypatch.setattr("fabric_cli.fabric_capabilities.filter_fabric_keys", boom)
    slugs = [p.slug for p in models.fabric_canonical_providers()]
    assert slugs == [p.slug for p in models.CANONICAL_PROVIDERS]


def test_custom_allow_lists_are_not_config_overridable(monkeypatch):
    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"model_providers": None})

    from fabric_cli.fabric_capabilities import filter_fabric_keys

    # An ad-hoc allow-list that is not one of the module catalogs must filter
    # exactly as passed, regardless of catalog config overrides.
    assert filter_fabric_keys(["a", "b", "c"], ("b",)) == ["b"]


def test_fabric_memory_provider_filter_keeps_honcho_and_localish_defaults(monkeypatch):
    from fabric_cli.fabric_capabilities import FABRIC_MEMORY_PROVIDERS, filter_fabric_keys

    providers = [
        ("mem0", "requires API key", object()),
        ("honcho", "API key / local", object()),
        ("holographic", "local", object()),
        ("supermemory", "requires API key", object()),
        ("hindsight", "local", object()),
    ]

    filtered = filter_fabric_keys(providers, FABRIC_MEMORY_PROVIDERS, key=lambda item: item[0])

    assert [name for name, _desc, _provider in filtered] == [
        "honcho",
        "holographic",
        "hindsight",
    ]


def test_memory_setup_picker_filters_to_fabric_defaults(monkeypatch):
    from fabric_cli import memory_setup

    class FakeProvider:
        def get_config_schema(self):
            return []

    raw = [
        ("mem0", "Mem0", True),
        ("honcho", "Honcho", True),
        ("holographic", "Holographic", True),
        ("supermemory", "Supermemory", True),
        ("hindsight", "Hindsight", True),
    ]
    with patch("plugins.memory.discover_memory_providers", return_value=raw), patch(
        "plugins.memory.load_memory_provider",
        side_effect=lambda name: FakeProvider(),
    ):
        providers = memory_setup._get_available_providers()

    assert [name for name, _desc, _provider in providers] == [
        "honcho",
        "holographic",
        "hindsight",
    ]


def test_memory_picker_keeps_configured_and_user_installed_providers(
    tmp_path, monkeypatch
):
    from fabric_cli import memory_setup
    from plugins import memory as memory_plugins

    class FakeProvider:
        def get_config_schema(self):
            return []

    raw = [
        ("honcho", "Honcho", True),
        ("mem0", "Mem0", True),
        ("user-memory", "User", True),
    ]
    bundled_root = memory_plugins._MEMORY_PLUGINS_DIR.resolve()
    user_dir = tmp_path / "plugins" / "user-memory"
    user_dir.mkdir(parents=True)

    with patch("plugins.memory.discover_memory_providers", return_value=raw), patch(
        "plugins.memory.load_memory_provider", side_effect=lambda _name: FakeProvider()
    ), patch(
        "plugins.memory.find_provider_dir",
        side_effect=lambda name: user_dir if name == "user-memory" else bundled_root / name,
    ), patch(
        "fabric_cli.config.load_config",
        return_value={"memory": {"provider": "mem0"}},
    ):
        providers = memory_setup._get_available_providers()

    assert [name for name, _desc, _provider in providers] == [
        "honcho",
        "mem0",
        "user-memory",
    ]
