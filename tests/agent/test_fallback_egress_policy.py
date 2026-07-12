"""Local-AI policy tests for live primary fallback activation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.egress_policy import EgressPolicyViolation, policy_from_config
from agent.chat_completion_helpers import try_activate_fallback


def _policy():
    return policy_from_config(
        {
            "security": {
                "egress_mode": "local_ai",
                "local_ai_allowed_cidrs": [],
            }
        }
    )


def _config():
    return {
        "security": {"egress_mode": "local_ai", "local_ai_allowed_cidrs": []},
        "model": {
            "provider": "custom",
            "default": "primary-local",
            "base_url": "http://127.0.0.1:11434/v1",
        },
        "providers": {},
        "custom_providers": [],
    }


def _agent(chain):
    old_client = object()
    agent = SimpleNamespace(
        _egress_policy=_policy(),
        _fallback_chain=chain,
        _fallback_index=0,
        _fallback_activated=False,
        _primary_runtime={},
        provider="primary-local",
        model="primary-model",
        base_url="http://127.0.0.1:11434/v1",
        api_mode="chat_completions",
        api_key="primary-key",
        client=old_client,
        _credential_pool=None,
        _transport_cache={},
        context_compressor=None,
        _cached_system_prompt=None,
        _is_azure_openai_url=lambda _url: False,
        _is_direct_openai_url=lambda _url: False,
        _provider_model_requires_responses_api=lambda *_args, **_kwargs: False,
        _anthropic_prompt_cache_policy=lambda **_kwargs: (False, False),
        _ensure_lmstudio_runtime_loaded=lambda: None,
        _buffer_status=lambda _message: None,
        _replace_primary_openai_client=lambda **_kwargs: None,
    )
    agent._try_activate_fallback = lambda reason=None: try_activate_fallback(
        agent, reason
    )
    return agent, old_client


def _bomb(label):
    def fail(*_args, **_kwargs):
        raise AssertionError(f"{label} must not run for a prohibited fallback")

    return fail


def test_remote_only_live_fallback_fails_stably_without_mutating_runtime(monkeypatch):
    agent, old_client = _agent(
        [
            {
                "provider": "openrouter",
                "model": "remote/model",
                "key_env": "REMOTE_FALLBACK_KEY",
            }
        ]
    )
    monkeypatch.setattr(
        "agent.auxiliary_client._load_auxiliary_egress_context",
        lambda: (agent._egress_policy, _config()),
    )
    monkeypatch.setattr(
        "agent.auxiliary_client.resolve_provider_client",
        _bomb("provider credential/client resolution"),
    )
    monkeypatch.setattr(
        "agent.auxiliary_client._local_profile_secret",
        _bomb("remote fallback credential"),
    )

    with pytest.raises(EgressPolicyViolation) as caught:
        try_activate_fallback(agent)

    assert caught.value.reason == "hostname_not_allowed"
    assert agent.provider == "primary-local"
    assert agent.model == "primary-model"
    assert agent.base_url == "http://127.0.0.1:11434/v1"
    assert agent.client is old_client


def test_live_fallback_skips_remote_then_activates_authorized_local(monkeypatch):
    agent, _ = _agent(
        [
            {"provider": "openrouter", "model": "remote/model"},
            {
                "provider": "custom",
                "model": "local-fallback",
                "base_url": "http://localhost:11434/v1",
                "key_env": "LOCAL_FALLBACK_KEY",
            },
        ]
    )
    monkeypatch.setattr(
        "agent.auxiliary_client._load_auxiliary_egress_context",
        lambda: (agent._egress_policy, _config()),
    )
    secret_reads = []

    def get_env_value(name):
        secret_reads.append(name)
        assert name == "LOCAL_FALLBACK_KEY"
        return "local-key"

    monkeypatch.setattr("agent.auxiliary_client._local_profile_secret", get_env_value)
    resolved = []

    def resolve(provider, model=None, **kwargs):
        resolved.append((provider, model, kwargs))
        return (
            SimpleNamespace(
                base_url="http://127.0.0.1:11434/v1",
                api_key="local-key",
                _custom_headers={},
            ),
            model,
        )

    monkeypatch.setattr("agent.auxiliary_client.resolve_provider_client", resolve)
    monkeypatch.setattr(
        "fabric_cli.model_normalize.normalize_model_for_provider",
        lambda model, _provider: model,
    )
    monkeypatch.setattr("agent.credential_pool.load_pool", lambda _provider: None)
    monkeypatch.setattr(
        "agent.chat_completion_helpers.get_provider_request_timeout",
        lambda _provider, _model: None,
    )

    assert try_activate_fallback(agent) is True

    assert secret_reads == ["LOCAL_FALLBACK_KEY"]
    assert len(resolved) == 1
    provider, model, kwargs = resolved[0]
    assert provider == "custom"
    assert model == "local-fallback"
    assert kwargs["explicit_base_url"] == "http://127.0.0.1:11434/v1"
    assert kwargs["explicit_api_key"] == "local-key"
    assert agent.provider == "custom"
    assert agent.model == "local-fallback"
    assert agent.base_url == "http://127.0.0.1:11434/v1"
    assert agent._disable_environment_proxy is True


def test_local_anthropic_fallback_preserves_api_mode_and_disables_proxies(
    monkeypatch,
):
    agent, _ = _agent(
        [
            {
                "provider": "custom",
                "model": "local-anthropic",
                "base_url": "http://localhost:11434/v1",
                "api_key": "local-key",
                "api_mode": "anthropic_messages",
            }
        ]
    )
    monkeypatch.setattr(
        "agent.auxiliary_client._load_auxiliary_egress_context",
        lambda: (agent._egress_policy, _config()),
    )
    resolved = []

    def resolve(provider, model=None, **kwargs):
        resolved.append((provider, model, kwargs))
        return (
            SimpleNamespace(
                base_url="http://127.0.0.1:11434/v1",
                api_key="local-key",
                _custom_headers={},
            ),
            model,
        )

    monkeypatch.setattr("agent.auxiliary_client.resolve_provider_client", resolve)
    monkeypatch.setattr(
        "fabric_cli.model_normalize.normalize_model_for_provider",
        lambda model, _provider: model,
    )
    monkeypatch.setattr("agent.credential_pool.load_pool", lambda _provider: None)
    monkeypatch.setattr(
        "agent.chat_completion_helpers.get_provider_request_timeout",
        lambda _provider, _model: None,
    )
    built = []
    local_anthropic_client = object()

    def build_anthropic_client(api_key, base_url, **kwargs):
        built.append((api_key, base_url, kwargs))
        return local_anthropic_client

    monkeypatch.setattr(
        "agent.anthropic_adapter.build_anthropic_client",
        build_anthropic_client,
    )

    assert try_activate_fallback(agent) is True

    assert resolved[0][2]["api_mode"] == "anthropic_messages"
    assert agent.provider == "custom"
    assert agent.api_mode == "anthropic_messages"
    assert agent._anthropic_client is local_anthropic_client
    assert agent._disable_environment_proxy is True
    assert built == [
        (
            "local-key",
            "http://127.0.0.1:11434/v1",
            {"timeout": None, "disable_environment_proxy": True},
        )
    ]


def test_live_fallback_rejects_router_route_substitution_before_runtime_swap(
    monkeypatch,
):
    agent, old_client = _agent(
        [
            {
                "provider": "custom",
                "model": "local-fallback",
                "base_url": "http://localhost:11434/v1",
                "api_key": "local-key",
            }
        ]
    )
    monkeypatch.setattr(
        "agent.auxiliary_client._load_auxiliary_egress_context",
        lambda: (agent._egress_policy, _config()),
    )
    monkeypatch.setattr(
        "agent.auxiliary_client.resolve_provider_client",
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                base_url="https://api.openai.com/v1",
                api_key="remote-key",
            ),
            "local-fallback",
        ),
    )

    with pytest.raises(EgressPolicyViolation):
        try_activate_fallback(agent)

    assert agent._fallback_index == 1
    assert agent.provider == "primary-local"
    assert agent.model == "primary-model"
    assert agent.base_url == "http://127.0.0.1:11434/v1"
    assert agent.api_key == "primary-key"
    assert agent.client is old_client
