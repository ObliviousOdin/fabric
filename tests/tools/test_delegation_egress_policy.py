"""Local-AI route policy at the delegation credential boundary."""

from types import SimpleNamespace

import pytest

from agent.egress_policy import EgressPolicyUnavailable, EgressPolicyViolation
from tools import delegate_tool as dt


def _parent(base_url="http://localhost:11434/v1", provider="custom"):
    return SimpleNamespace(
        base_url=base_url,
        provider=provider,
        api_key="parent-key",
        model="parent-model",
        _delegate_depth=0,
    )


def _policy_config(mode, *, model=None, providers=None, cidrs=None):
    return {
        "security": {
            "egress_mode": mode,
            "local_ai_allowed_cidrs": list(cidrs or []),
        },
        "model": model or {},
        "providers": providers or {},
        "custom_providers": [],
    }


def _set_policy(monkeypatch, config):
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )


def test_online_direct_route_is_byte_compatible(monkeypatch):
    _set_policy(monkeypatch, _policy_config("online"))
    creds = dt._resolve_delegation_credentials(
        {
            "provider": "custom",
            "model": "model",
            "base_url": "http://localhost:11434/v1/",
            "api_key": "key",
        },
        _parent(),
    )
    assert creds["base_url"] == "http://localhost:11434/v1/"
    assert creds["api_key"] == "key"


def test_local_direct_route_is_normalized_before_key_use(monkeypatch):
    _set_policy(monkeypatch, _policy_config("local_ai"))
    creds = dt._resolve_delegation_credentials(
        {
            "provider": "custom",
            "model": "model",
            "base_url": "http://localhost:11434/v1/",
            "api_key": "local-key",
        },
        _parent(),
    )
    assert creds["base_url"] == "http://127.0.0.1:11434/v1"
    assert creds["api_key"] == "local-key"


def test_local_remote_route_rejects_before_runtime_credentials(monkeypatch):
    _set_policy(monkeypatch, _policy_config("local_ai"))
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("credential resolver must not run")
        ),
    )
    with pytest.raises(EgressPolicyViolation) as caught:
        dt._resolve_delegation_credentials(
            {
                "provider": "openrouter",
                "model": "model",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "must-not-matter",
            },
            _parent(),
        )
    assert caught.value.reason == "hostname_not_allowed"
    assert "openrouter.ai" not in str(caught.value)


def test_local_named_custom_route_is_pinned_into_runtime_resolver(monkeypatch):
    config = _policy_config(
        "local_ai",
        model={"provider": "custom:lab", "default": "model"},
        providers={
            "lab": {
                "base_url": "http://localhost:11434/v1",
                "key_env": "LAB_KEY",
            }
        },
    )
    _set_policy(monkeypatch, config)
    seen = {}

    def resolve(**kwargs):
        seen.update(kwargs)
        return {
            "provider": "custom",
            "base_url": kwargs["explicit_base_url"],
            "api_key": "resolved-key",
            "api_mode": "chat_completions",
        }

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    creds = dt._resolve_delegation_credentials(
        {"provider": "custom:lab", "model": "model"}, _parent()
    )
    assert seen["explicit_base_url"] == "http://127.0.0.1:11434/v1"
    assert creds["base_url"] == "http://127.0.0.1:11434/v1"


def test_local_codex_route_without_explicit_key_never_refreshes_oauth(monkeypatch):
    _set_policy(monkeypatch, _policy_config("local_ai"))
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_codex_runtime_credentials",
        lambda: (_ for _ in ()).throw(
            AssertionError("remote OAuth refresh must not run")
        ),
    )

    creds = dt._resolve_delegation_credentials(
        {
            "provider": "openai-codex",
            "model": "gpt-5-codex",
            "base_url": "http://127.0.0.1:11434/v1",
        },
        _parent(),
    )

    # A direct OpenAI-compatible endpoint intentionally collapses to the
    # custom transport; it may inherit the already-local parent's key, but it
    # must never resolve or refresh the named cloud subscription identity.
    assert creds["provider"] == "custom"
    assert creds["base_url"] == "http://127.0.0.1:11434/v1"
    assert creds["api_key"] is None


def test_local_inherited_parent_route_is_concrete_not_virtual(monkeypatch):
    _set_policy(monkeypatch, _policy_config("local_ai"))
    creds = dt._resolve_delegation_credentials({}, _parent())
    assert creds["provider"] is None
    assert creds["base_url"] == "http://127.0.0.1:11434/v1"

    with pytest.raises(EgressPolicyViolation):
        dt._resolve_delegation_credentials(
            {}, _parent(base_url="moa://local", provider="moa")
        )


def test_air_gapped_delegation_is_unavailable(monkeypatch):
    _set_policy(monkeypatch, _policy_config("air_gapped"))
    with pytest.raises(EgressPolicyUnavailable):
        dt._resolve_delegation_credentials({}, _parent())


def test_delegate_task_rejects_before_ordinary_config_load(monkeypatch):
    _set_policy(monkeypatch, _policy_config("local_ai"))
    monkeypatch.setattr(
        dt,
        "_load_unexpanded_delegation_config",
        lambda: {
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "${SECRET}",
        },
    )
    monkeypatch.setattr(
        dt,
        "_load_config",
        lambda: (_ for _ in ()).throw(
            AssertionError("ordinary config/secret expansion must not run")
        ),
    )
    result = dt.delegate_task(goal="work", parent_agent=_parent())
    assert "hostname_not_allowed" in result


def test_sequential_policies_do_not_bleed(monkeypatch):
    active = {"config": _policy_config("local_ai")}
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config",
        lambda: active["config"],
    )
    local = dt._resolve_delegation_credentials({}, _parent())
    active["config"] = _policy_config("online")
    online = dt._resolve_delegation_credentials({}, _parent())
    active["config"] = _policy_config("local_ai")
    local_again = dt._resolve_delegation_credentials({}, _parent())

    assert local["base_url"] == "http://127.0.0.1:11434/v1"
    assert online["base_url"] is None
    assert local_again["base_url"] == local["base_url"]
