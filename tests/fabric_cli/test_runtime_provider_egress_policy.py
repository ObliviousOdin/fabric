"""Primary runtime enforcement for profile-scoped AI egress policy."""

from __future__ import annotations

import socket

import httpx
import pytest
import yaml

from agent.egress_policy import (
    EgressPolicyConfigurationError,
    EgressPolicyUnavailable,
    EgressPolicyViolation,
)
from fabric_cli import runtime_provider as rp
from fabric_constants import reset_fabric_home_override, set_fabric_home_override


def _config(mode, *, provider="custom", base_url="", cidrs=None):
    return {
        "security": {
            "egress_mode": mode,
            "local_ai_allowed_cidrs": list(cidrs or []),
        },
        "model": {
            "provider": provider,
            "default": "test-model",
            "base_url": base_url,
        },
    }


def _patch_config(monkeypatch, config):
    monkeypatch.setattr(rp, "load_egress_policy_config", lambda: config)
    monkeypatch.setattr(rp, "load_config", lambda: config)


def test_online_delegates_with_identical_arguments_and_result(monkeypatch):
    config = _config(
        "online",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
    )
    sentinel = {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sentinel-key",
    }
    seen = {}

    def unchecked(**kwargs):
        seen.update(kwargs)
        return sentinel

    _patch_config(monkeypatch, config)
    monkeypatch.setattr(rp, "_resolve_runtime_provider_unchecked", unchecked)

    result = rp.resolve_runtime_provider(
        requested="openrouter",
        explicit_api_key="explicit-key",
        explicit_base_url="https://proxy.example/v1/",
        target_model="test-model",
    )

    assert result is sentinel
    assert seen == {
        "requested": "openrouter",
        "explicit_api_key": "explicit-key",
        "explicit_base_url": "https://proxy.example/v1/",
        "target_model": "test-model",
    }
    assert "egress_mode" not in result
    assert "allow_environment_proxy" not in result


def test_remote_primary_rejected_before_credentials_dns_or_client(monkeypatch):
    _patch_config(monkeypatch, _config("local_ai", provider="openrouter"))
    calls = []

    def unexpected(label):
        def fail(*_args, **_kwargs):
            calls.append(label)
            raise AssertionError(f"{label} must not run before policy rejection")

        return fail

    monkeypatch.setattr(rp, "_resolve_runtime_provider_unchecked", unexpected("resolver"))
    monkeypatch.setattr(rp, "_get_secret", unexpected("secret"))
    monkeypatch.setattr(rp, "load_pool", unexpected("pool"))
    monkeypatch.setattr(
        rp, "resolve_codex_runtime_credentials", unexpected("oauth")
    )
    monkeypatch.setattr(socket, "getaddrinfo", unexpected("dns"))
    monkeypatch.setattr(httpx, "Client", unexpected("client"))

    with pytest.raises(EgressPolicyViolation) as caught:
        rp.resolve_runtime_provider(requested="openrouter")

    assert caught.value.reason == "hostname_not_allowed"
    assert calls == []


@pytest.mark.parametrize(
    ("requested", "resolver_path"),
    [
        (
            "qwen-oauth",
            "fabric_cli.runtime_provider.resolve_qwen_runtime_credentials",
        ),
        (
            "qwen-cli",
            "fabric_cli.runtime_provider.resolve_qwen_runtime_credentials",
        ),
        (
            "xai-oauth",
            "fabric_cli.runtime_provider.resolve_xai_oauth_runtime_credentials",
        ),
        (
            "minimax-oauth",
            "fabric_cli.auth.resolve_minimax_oauth_runtime_credentials",
        ),
    ],
)
def test_immutable_provider_rejects_before_oauth_despite_local_explicit_url(
    monkeypatch, requested, resolver_path
):
    config = _config("local_ai", provider=requested)
    _patch_config(monkeypatch, config)
    calls = []

    def unexpected(*_args, **_kwargs):
        calls.append(resolver_path)
        raise AssertionError("immutable provider OAuth must not run")

    monkeypatch.setattr(resolver_path, unexpected)
    monkeypatch.setattr(
        rp,
        "load_pool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("credential pool must not run")
        ),
    )

    with pytest.raises(EgressPolicyViolation) as caught:
        rp.resolve_runtime_provider(
            requested=requested,
            explicit_base_url="http://127.0.0.1:11434/v1",
        )

    assert caught.value.reason in {"hostname_not_allowed", "invalid_endpoint"}
    assert calls == []


@pytest.mark.parametrize(
    "requested",
    [
        "x-ai-oauth",
        "qwen",
        "minimax-global",
        "minimax-oauth-io",
        "aws-bedrock",
        "github-copilot-acp",
        "vertex-ai",
        "moa",
    ],
)
def test_immutable_provider_alias_cannot_hide_behind_local_route_hint(
    monkeypatch, requested
):
    config = _config("local_ai", provider=requested)
    _patch_config(monkeypatch, config)
    calls = []

    def unexpected(**_kwargs):
        calls.append("resolver")
        raise AssertionError("immutable alias must stop at policy preflight")

    monkeypatch.setattr(rp, "_resolve_runtime_provider_unchecked", unexpected)

    with pytest.raises(EgressPolicyViolation):
        rp.resolve_runtime_provider(
            requested=requested,
            explicit_base_url="http://127.0.0.1:11434/v1",
        )

    assert calls == []


@pytest.mark.parametrize(
    ("requested", "resolver_path"),
    [
        (
            "anthropic",
            "agent.anthropic_adapter.resolve_anthropic_token",
        ),
        (
            "claude",
            "agent.anthropic_adapter.resolve_anthropic_token",
        ),
        (
            "claude-oauth",
            "agent.anthropic_adapter.resolve_anthropic_token",
        ),
        (
            "claude-code",
            "agent.anthropic_adapter.resolve_anthropic_token",
        ),
        (
            "copilot",
            "fabric_cli.runtime_provider.resolve_api_key_provider_credentials",
        ),
        (
            "github",
            "fabric_cli.runtime_provider.resolve_api_key_provider_credentials",
        ),
        (
            "github-copilot",
            "fabric_cli.runtime_provider.resolve_api_key_provider_credentials",
        ),
        (
            "github-models",
            "fabric_cli.runtime_provider.resolve_api_key_provider_credentials",
        ),
        (
            "github-model",
            "fabric_cli.runtime_provider.resolve_api_key_provider_credentials",
        ),
        (
            "openai-codex",
            "fabric_cli.runtime_provider.resolve_codex_runtime_credentials",
        ),
        (
            "codex",
            "fabric_cli.runtime_provider.resolve_codex_runtime_credentials",
        ),
        (
            "openai_codex",
            "fabric_cli.runtime_provider.resolve_codex_runtime_credentials",
        ),
        (
            "nous",
            "fabric_cli.runtime_provider.resolve_nous_runtime_credentials",
        ),
        (
            "nous-portal",
            "fabric_cli.runtime_provider.resolve_nous_runtime_credentials",
        ),
        (
            "nousresearch",
            "fabric_cli.runtime_provider.resolve_nous_runtime_credentials",
        ),
    ],
)
def test_local_override_without_explicit_key_rejects_before_remote_auth(
    monkeypatch, requested, resolver_path
):
    config = _config("local_ai", provider=requested)
    _patch_config(monkeypatch, config)
    calls = []

    def unexpected(*_args, **_kwargs):
        calls.append(resolver_path)
        raise AssertionError("remote credential refresh must not run")

    monkeypatch.setattr(resolver_path, unexpected)

    with pytest.raises(EgressPolicyViolation) as caught:
        rp.resolve_runtime_provider(
            requested=requested,
            explicit_base_url="http://127.0.0.1:11434/v1",
        )

    assert caught.value.reason == "hostname_not_allowed"
    assert calls == []


@pytest.mark.parametrize(
    ("requested", "resolver_path"),
    [
        (
            "anthropic",
            "agent.anthropic_adapter.resolve_anthropic_token",
        ),
        (
            "copilot",
            "fabric_cli.runtime_provider.resolve_api_key_provider_credentials",
        ),
        (
            "openai-codex",
            "fabric_cli.runtime_provider.resolve_codex_runtime_credentials",
        ),
        (
            "nous",
            "fabric_cli.runtime_provider.resolve_nous_runtime_credentials",
        ),
    ],
)
def test_local_override_with_explicit_key_never_refreshes_remote_auth(
    monkeypatch, requested, resolver_path
):
    config = _config("local_ai", provider=requested)
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        resolver_path,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("explicit local credential must suppress remote auth")
        ),
    )
    if requested == "nous":
        monkeypatch.setattr(rp.auth_mod, "get_provider_auth_state", lambda _p: {})

    runtime = rp.resolve_runtime_provider(
        requested=requested,
        explicit_api_key="local-inert-key",
        explicit_base_url="http://localhost:11434/v1",
    )

    assert runtime["provider"] == requested
    assert runtime["api_key"] == "local-inert-key"
    assert runtime["base_url"] == "http://127.0.0.1:11434/v1"
    assert runtime["allow_environment_proxy"] is False


@pytest.mark.parametrize("requested", ["azure-foundry", "azure", "azure-ai"])
def test_local_azure_entra_rejects_before_token_provider(
    monkeypatch, requested
):
    config = _config(
        "local_ai",
        provider="azure-foundry",
        base_url="http://127.0.0.1:11434/v1",
    )
    config["model"]["auth_mode"] = "entra_id"
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        "agent.azure_identity_adapter.build_token_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Entra token provider must not be constructed")
        ),
    )

    with pytest.raises(EgressPolicyViolation) as caught:
        rp.resolve_runtime_provider(
            requested=requested,
            explicit_base_url="http://127.0.0.1:11434/v1",
        )

    assert caught.value.reason == "hostname_not_allowed"


def test_local_azure_entra_allows_explicit_inert_key_without_token_provider(
    monkeypatch,
):
    config = _config(
        "local_ai",
        provider="azure-foundry",
        base_url="http://127.0.0.1:11434/v1",
    )
    config["model"]["auth_mode"] = "entra_id"
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        "agent.azure_identity_adapter.build_token_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("explicit key must suppress Entra token provider")
        ),
    )

    runtime = rp.resolve_runtime_provider(
        requested="azure",
        explicit_api_key="local-inert-key",
        explicit_base_url="http://localhost:11434/v1",
    )

    assert runtime["provider"] == "azure-foundry"
    assert runtime["api_key"] == "local-inert-key"
    assert runtime["base_url"] == "http://127.0.0.1:11434/v1"


def test_private_hostname_rejected_without_dns_or_credentials(monkeypatch):
    config = _config(
        "local_ai",
        provider="custom",
        base_url="http://model.internal:11434/v1",
        cidrs=["192.168.0.0/16"],
    )
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        rp,
        "_resolve_runtime_provider_unchecked",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("resolver must not run")
        ),
    )
    monkeypatch.setattr(
        rp,
        "_get_secret",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("credential lookup must not run")
        ),
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("DNS must not run")
        ),
    )

    with pytest.raises(EgressPolicyViolation) as caught:
        rp.resolve_runtime_provider(requested="custom")
    assert caught.value.reason == "hostname_not_allowed"


def test_air_gapped_fails_unavailable_before_runtime_work(monkeypatch):
    _patch_config(monkeypatch, _config("air_gapped", provider="custom"))
    monkeypatch.setattr(
        rp,
        "_resolve_runtime_provider_unchecked",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unavailable policy must stop before resolution")
        ),
    )

    with pytest.raises(EgressPolicyUnavailable) as caught:
        rp.resolve_runtime_provider(requested="custom")
    assert caught.value.reason == "whole_process_network_boundary_missing"


def test_malformed_profile_stops_before_resolver_or_secret_access(
    tmp_path, monkeypatch
):
    home = tmp_path / "malformed-profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        "security:\n  egress_mode: [\n", encoding="utf-8"
    )
    calls = []

    def unexpected(label):
        def fail(*_args, **_kwargs):
            calls.append(label)
            raise AssertionError(f"{label} must not run")

        return fail

    monkeypatch.setattr(
        rp, "_resolve_runtime_provider_unchecked", unexpected("resolver")
    )
    monkeypatch.setattr(rp, "_get_secret", unexpected("secret"))
    monkeypatch.setattr(rp, "load_pool", unexpected("pool"))

    token = set_fabric_home_override(home)
    try:
        with pytest.raises(EgressPolicyConfigurationError) as caught:
            rp.resolve_runtime_provider(requested="openrouter")
    finally:
        reset_fabric_home_override(token)

    assert caught.value.reason == "config_unreadable"
    assert calls == []


def test_rejected_profile_does_not_expand_embedded_secret_reference(
    tmp_path, monkeypatch
):
    home = tmp_path / "remote-profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security": {"egress_mode": "local_ai"},
                "model": {
                    "provider": "custom:remote",
                    "default": "remote-model",
                },
                "providers": {
                    "remote": {
                        "base_url": "https://example.com/v1",
                        "api_key": "${REMOTE_API_KEY}",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fabric_cli.config._config_env_value",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("rejected route must not expand credentials")
        ),
    )
    monkeypatch.setattr(
        rp,
        "_resolve_runtime_provider_unchecked",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("rejected route must not enter credential resolver")
        ),
    )

    token = set_fabric_home_override(home)
    try:
        with pytest.raises(EgressPolicyViolation) as caught:
            rp.resolve_runtime_provider(requested="custom:remote")
    finally:
        reset_fabric_home_override(token)

    assert caught.value.reason == "hostname_not_allowed"


def test_named_custom_local_route_is_pinned_then_credentials_resolve(monkeypatch):
    config = {
        "security": {
            "egress_mode": "local_ai",
            "local_ai_allowed_cidrs": [],
        },
        "model": {"provider": "custom:lab", "default": "qwen-test"},
        "providers": {
            "lab": {
                "name": "Lab",
                "base_url": "http://localhost:11434/v1/",
                "key_env": "LAB_API_KEY",
                "default_model": "qwen-test",
            }
        },
    }
    credential_reads = []

    def scoped_getenv(name, default=""):
        credential_reads.append(name)
        return "lab-secret" if name == "LAB_API_KEY" else default

    _patch_config(monkeypatch, config)
    monkeypatch.setattr(rp, "_getenv", scoped_getenv)
    monkeypatch.setattr(rp, "_try_resolve_from_custom_pool", lambda *_a, **_k: None)
    monkeypatch.setattr(
        rp,
        "_auto_detect_local_model",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("local model auto-probe must be suppressed")
        ),
    )

    runtime = rp.resolve_runtime_provider(requested="custom:lab")

    assert runtime["provider"] == "custom"
    assert runtime["base_url"] == "http://127.0.0.1:11434/v1"
    assert runtime["api_key"] == "lab-secret"
    assert runtime["egress_mode"] == "local_ai"
    assert runtime["allow_environment_proxy"] is False
    assert "LAB_API_KEY" in credential_reads


def test_auto_preflight_follows_the_profile_selected_local_provider(monkeypatch):
    config = _config(
        "local_ai",
        provider="custom",
        base_url="http://localhost:11434/v1/",
    )
    _patch_config(monkeypatch, config)
    seen = {}

    def unchecked(**kwargs):
        seen.update(kwargs)
        return {
            "provider": "custom",
            "base_url": kwargs["explicit_base_url"],
            "api_key": "local-key",
        }

    monkeypatch.setattr(rp, "_resolve_runtime_provider_unchecked", unchecked)

    runtime = rp.resolve_runtime_provider(requested="auto")

    assert seen["requested"] == "auto"
    assert seen["explicit_base_url"] == "http://127.0.0.1:11434/v1"
    assert runtime["egress_mode"] == "local_ai"


def test_bare_custom_preflight_follows_named_custom_profile_identity(monkeypatch):
    config = {
        "security": {"egress_mode": "local_ai"},
        "model": {"provider": "custom:lab", "default": "qwen-test"},
        "providers": {
            "lab": {
                "name": "Lab",
                "base_url": "http://localhost:11434/v1/",
            }
        },
    }
    _patch_config(monkeypatch, config)

    def unchecked(**kwargs):
        return {
            "provider": "custom",
            "base_url": kwargs["explicit_base_url"],
            "api_key": "local-key",
        }

    monkeypatch.setattr(rp, "_resolve_runtime_provider_unchecked", unchecked)

    runtime = rp.resolve_runtime_provider(requested="custom")

    assert runtime["base_url"] == "http://127.0.0.1:11434/v1"
    assert runtime["egress_mode"] == "local_ai"


def test_first_class_local_default_is_authorized_before_key_resolution(monkeypatch):
    config = _config("local_ai", provider="lmstudio")
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        rp,
        "resolve_api_key_provider_credentials",
        lambda provider: {
            "provider": provider,
            "api_key": "dummy-lm-api-key",
            "base_url": "https://must-not-override-authorized-route.example/v1",
            "source": "test",
        },
    )

    runtime = rp.resolve_runtime_provider(requested="lmstudio")

    assert runtime["base_url"] == "http://127.0.0.1:1234/v1"
    assert runtime["egress_mode"] == "local_ai"


def test_secret_bearing_route_failure_is_sanitized(monkeypatch):
    raw = "http://user:password@127.0.0.1/v1?api_key=secret-value"
    _patch_config(
        monkeypatch,
        _config("local_ai", provider="custom", base_url=raw),
    )

    with pytest.raises(EgressPolicyViolation) as caught:
        rp.resolve_runtime_provider(requested="custom")

    rendered = str(caught.value)
    for forbidden in (raw, "user", "password", "api_key", "secret-value"):
        assert forbidden not in rendered


def test_defense_in_depth_rejects_route_changed_after_preflight(monkeypatch):
    config = _config(
        "local_ai", provider="custom", base_url="http://127.0.0.1:11434/v1"
    )
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(
        rp,
        "_resolve_runtime_provider_unchecked",
        lambda **_kwargs: {
            "provider": "custom",
            "base_url": "https://example.com/v1",
            "api_key": "already-resolved",
        },
    )

    with pytest.raises(EgressPolicyViolation):
        rp.resolve_runtime_provider(requested="custom")


def test_sequential_profile_homes_do_not_share_policy(tmp_path, monkeypatch):
    local_home = tmp_path / "profiles" / "local"
    online_home = tmp_path / "profiles" / "online"
    local_home.mkdir(parents=True)
    online_home.mkdir(parents=True)
    (local_home / "config.yaml").write_text(
        yaml.safe_dump(
            _config(
                "local_ai",
                provider="custom",
                base_url="http://localhost:11434/v1",
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (online_home / "config.yaml").write_text(
        yaml.safe_dump(
            _config(
                "online",
                provider="openrouter",
                base_url="https://openrouter.ai/api/v1",
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def unchecked(**kwargs):
        base_url = kwargs.get("explicit_base_url")
        if base_url:
            return {
                "provider": "custom",
                "base_url": base_url,
                "api_key": "local-key",
            }
        return {
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "remote-key",
        }

    monkeypatch.setattr(rp, "_resolve_runtime_provider_unchecked", unchecked)

    local_token = set_fabric_home_override(local_home)
    try:
        local_runtime = rp.resolve_runtime_provider(requested="custom")
    finally:
        reset_fabric_home_override(local_token)

    online_token = set_fabric_home_override(online_home)
    try:
        online_runtime = rp.resolve_runtime_provider(requested="openrouter")
    finally:
        reset_fabric_home_override(online_token)

    local_again_token = set_fabric_home_override(local_home)
    try:
        with pytest.raises(EgressPolicyViolation):
            rp.resolve_runtime_provider(
                requested="custom",
                explicit_base_url="https://example.com/v1",
            )
    finally:
        reset_fabric_home_override(local_again_token)

    assert local_runtime["base_url"] == "http://127.0.0.1:11434/v1"
    assert local_runtime["egress_mode"] == "local_ai"
    assert online_runtime == {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "remote-key",
    }
