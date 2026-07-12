"""Local-AI policy must reject live model switches atomically."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.agent_runtime_helpers import (
    authorize_model_switch_runtime,
    switch_model,
)
from agent.egress_policy import (
    EgressPolicyUnavailable,
    EgressPolicyViolation,
    policy_from_config,
)


def _policy(mode: str):
    return policy_from_config(
        {
            "security": {
                "egress_mode": mode,
                "local_ai_allowed_cidrs": [],
            }
        }
    )


def _bare_agent(mode: str = "local_ai"):
    client = object()
    agent = SimpleNamespace(
        _egress_policy=_policy(mode),
        model="old-model",
        provider="custom",
        base_url="http://127.0.0.1:11434/v1",
        api_key="old-key",
        api_mode="chat_completions",
        client=client,
        _transport_cache={"old": object()},
        _client_kwargs={
            "api_key": "old-key",
            "base_url": "http://127.0.0.1:11434/v1",
        },
        _credential_pool=object(),
        _cached_system_prompt="stable-prompt",
        _use_prompt_caching=True,
        _use_native_cache_layout=False,
        _fallback_activated=False,
        _fallback_index=0,
        _fallback_chain=[],
        _fallback_model=None,
        _config_context_length=32768,
    )
    return agent


def _runtime_snapshot(agent):
    return {
        "model": agent.model,
        "provider": agent.provider,
        "base_url": agent.base_url,
        "api_key": agent.api_key,
        "api_mode": agent.api_mode,
        "client": agent.client,
        "transport_cache": dict(agent._transport_cache),
        "client_kwargs": dict(agent._client_kwargs),
        "credential_pool": agent._credential_pool,
        "cached_system_prompt": agent._cached_system_prompt,
        "use_prompt_caching": agent._use_prompt_caching,
        "use_native_cache_layout": agent._use_native_cache_layout,
        "fallback_activated": agent._fallback_activated,
        "fallback_index": agent._fallback_index,
        "config_context_length": agent._config_context_length,
    }


def test_remote_live_switch_rejects_before_any_runtime_mutation(monkeypatch):
    agent = _bare_agent()
    before = _runtime_snapshot(agent)
    monkeypatch.setattr(
        "fabric_cli.providers.determine_api_mode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("transport resolution must not run")
        ),
    )

    with pytest.raises(EgressPolicyViolation) as caught:
        switch_model(
            agent,
            "remote-model",
            "openrouter",
            api_key="remote-key",
            base_url="https://openrouter.ai/api/v1",
        )

    assert caught.value.reason == "hostname_not_allowed"
    assert _runtime_snapshot(agent) == before


@pytest.mark.parametrize(
    ("provider", "api_mode"),
    [
        ("bedrock", "bedrock_converse"),
        ("aws-bedrock", "chat_completions"),
        ("copilot-acp", "chat_completions"),
        ("github-copilot-acp", "chat_completions"),
        ("moa", "chat_completions"),
        ("qwen-oauth", "chat_completions"),
        ("qwen", "chat_completions"),
        ("minimax-oauth-io", "anthropic_messages"),
        ("vertex", "chat_completions"),
        ("vertex-ai", "chat_completions"),
        ("custom", "codex_app_server"),
    ],
)
def test_transport_that_ignores_url_cannot_hide_behind_loopback(
    provider, api_mode
):
    agent = _bare_agent()
    before = _runtime_snapshot(agent)

    with pytest.raises(EgressPolicyViolation):
        switch_model(
            agent,
            "new-model",
            provider,
            api_key="inert-local-key",
            base_url="http://127.0.0.1:11434/v1",
            api_mode=api_mode,
        )

    assert _runtime_snapshot(agent) == before


@pytest.mark.parametrize(
    "provider",
    [
        "anthropic",
        "claude",
        "claude-oauth",
        "copilot",
        "github",
        "github-models",
        "openai-codex",
        "codex",
        "nous",
        "nousresearch",
    ],
)
def test_auth_backed_local_identity_requires_an_explicit_key(provider):
    agent = _bare_agent()
    agent.api_key = ""
    agent._client_kwargs["api_key"] = ""

    with pytest.raises(EgressPolicyViolation):
        authorize_model_switch_runtime(
            agent,
            provider=provider,
            base_url="http://127.0.0.1:11434/v1",
            api_key="",
            api_mode="chat_completions",
        )


def test_azure_entra_callable_cannot_hide_behind_loopback():
    agent = _bare_agent()

    with pytest.raises(EgressPolicyViolation):
        authorize_model_switch_runtime(
            agent,
            provider="azure",
            base_url="http://127.0.0.1:11434/v1",
            api_key=lambda: "remote-entra-token",
            api_mode="chat_completions",
        )


def test_omitted_local_url_reuses_and_canonicalizes_live_route():
    agent = _bare_agent()
    agent.base_url = "http://localhost:11434/v1/"

    assert authorize_model_switch_runtime(
        agent,
        provider="custom",
        base_url="",
        api_key="local-key",
        api_mode="chat_completions",
    ) == "http://127.0.0.1:11434/v1"


def test_online_returns_base_url_byte_for_byte():
    agent = _bare_agent("online")
    raw = " HTTPS://Example.COM/v1/ "

    assert authorize_model_switch_runtime(
        agent,
        provider="openrouter",
        base_url=raw,
        api_key="key",
        api_mode="chat_completions",
    ) == raw


def test_air_gapped_switch_is_unavailable_before_mutation():
    agent = _bare_agent("air_gapped")
    before = _runtime_snapshot(agent)

    with pytest.raises(EgressPolicyUnavailable):
        switch_model(
            agent,
            "new-model",
            "custom",
            api_key="key",
            base_url="http://127.0.0.1:11434/v1",
        )

    assert _runtime_snapshot(agent) == before


@pytest.mark.parametrize(
    ("configured_context", "expected_context"),
    [
        (32_768, 32_768),
        (True, 256_000),
        (0, 256_000),
        (-1, 256_000),
        ("65536", 256_000),
    ],
)
def test_local_live_switch_skips_preload_and_probe_capable_context_resolver(
    monkeypatch, configured_context, expected_context
):
    agent = _bare_agent()
    agent._config_context_length = configured_context
    updates = []

    def update_model(**kwargs):
        updates.append(kwargs)
        for key, value in kwargs.items():
            setattr(agent.context_compressor, key, value)

    agent.context_compressor = SimpleNamespace(
        model="old-model",
        base_url=agent.base_url,
        api_key=agent.api_key,
        provider=agent.provider,
        api_mode=agent.api_mode,
        context_length=128_000,
        threshold_tokens=64_000,
        update_model=update_model,
    )
    agent._primary_runtime = {}
    agent._anthropic_prompt_cache_policy = lambda **_kwargs: (True, False)
    agent._ensure_lmstudio_runtime_loaded = lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(
            AssertionError("LM Studio preload must not run")
        )
    )
    agent._create_openai_client = lambda *_args, **_kwargs: object()
    monkeypatch.setattr(
        "agent.model_metadata.get_model_context_length",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("probe-capable context resolver must not run")
        ),
    )

    switch_model(
        agent,
        "unknown-local-model",
        "custom",
        api_key="local-key",
        base_url="http://127.0.0.1:11434/v1",
        api_mode="chat_completions",
    )

    assert updates[-1]["context_length"] == expected_context
    assert agent.context_compressor.model == "unknown-local-model"
