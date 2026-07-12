"""Primary local_ai clients must never inherit environment proxies."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from run_agent import AIAgent
from agent import anthropic_adapter
from agent.egress_policy import EgressPolicyViolation


def _config(mode: str):
    return {
        "security": {
            "egress_mode": mode,
            "local_ai_allowed_cidrs": [],
        },
        "model": {
            "provider": "custom",
            "default": "test-model",
            "base_url": "http://127.0.0.1:11434/v1",
        },
    }


def _agent():
    return AIAgent(
        api_key="no-key-required",
        base_url="http://127.0.0.1:11434/v1",
        provider="custom",
        model="test-model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )


@patch("run_agent.OpenAI")
def test_local_ai_init_skips_metadata_prewarm_preload_and_context_probes(
    mock_openai, monkeypatch
):
    config = _config("local_ai")
    config["model"]["provider"] = "openrouter"
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    monkeypatch.setattr(
        "agent.agent_init.fetch_model_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("remote metadata prewarm must not run")
        ),
    )
    monkeypatch.setattr(
        AIAgent,
        "_ensure_lmstudio_runtime_loaded",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("LM Studio preload must not run")
        ),
    )
    for name in (
        "_resolve_endpoint_context_length",
        "_query_ollama_api_show",
        "_query_local_context_length",
        "fetch_model_metadata",
    ):
        monkeypatch.setattr(
            f"agent.model_metadata.{name}",
            lambda *_args, _name=name, **_kwargs: (_ for _ in ()).throw(
                AssertionError(f"context probe {_name} must not run")
            ),
        )

    import run_agent

    run_agent._openrouter_prewarm_done.clear()
    agent = AIAgent(
        api_key="local-inert-key",
        base_url="http://127.0.0.1:11434/v1",
        provider="openrouter",
        model="unknown-local-model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )

    assert run_agent._openrouter_prewarm_done.is_set() is False
    assert agent.context_compressor.context_length == 256_000
    mock_openai.call_args.kwargs["http_client"].close()


@patch("run_agent.OpenAI")
def test_online_init_preserves_openrouter_metadata_prewarm(
    mock_openai, monkeypatch
):
    config = _config("online")
    config["model"].update({"provider": "openrouter", "context_length": 131_072})
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    called = threading.Event()
    monkeypatch.setattr(
        "agent.agent_init.fetch_model_metadata",
        lambda *_args, **_kwargs: called.set(),
    )

    import run_agent

    run_agent._openrouter_prewarm_done.clear()
    AIAgent(
        api_key="online-key",
        base_url="http://127.0.0.1:11434/v1",
        provider="openrouter",
        model="online-model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )

    assert called.wait(1.0)
    assert run_agent._openrouter_prewarm_done.is_set() is True
    mock_openai.call_args.kwargs["http_client"].close()


def _proxy_pool_types(client: httpx.Client):
    return {
        type(mount._pool).__name__
        for mount in client._mounts.values()
        if mount is not None and hasattr(mount, "_pool")
    }


@patch("run_agent.OpenAI")
def test_local_ai_disables_trust_env_while_online_keeps_proxy_behavior(
    mock_openai, monkeypatch
):
    for key in (
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")

    active = {"config": _config("online")}
    monkeypatch.setattr(
        "fabric_cli.config.load_config", lambda: active["config"]
    )
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: active["config"]
    )

    _agent()
    online_http = mock_openai.call_args.kwargs["http_client"]
    assert isinstance(online_http, httpx.Client)
    assert "HTTPProxy" in _proxy_pool_types(online_http)
    assert online_http.trust_env is True

    active["config"] = _config("local_ai")
    _agent()
    local_http = mock_openai.call_args.kwargs["http_client"]
    assert isinstance(local_http, httpx.Client)
    assert "HTTPProxy" not in _proxy_pool_types(local_http)
    assert local_http.trust_env is False

    online_http.close()
    local_http.close()


def test_anthropic_builder_disables_proxy_only_when_requested(monkeypatch):
    captured = []
    normalized_proxy_env = []

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            captured.append(kwargs)
            if kwargs.get("api_key") == "constructor-fails":
                raise RuntimeError("constructor failed")

        def close(self):
            http_client = self.kwargs.get("http_client")
            if http_client is not None:
                http_client.close()

    monkeypatch.setattr(
        anthropic_adapter,
        "_get_anthropic_sdk",
        lambda: SimpleNamespace(Anthropic=FakeAnthropic),
    )
    monkeypatch.setattr(
        anthropic_adapter,
        "normalize_proxy_env_vars",
        lambda: normalized_proxy_env.append(True),
    )

    local = anthropic_adapter.build_anthropic_client(
        "test-key",
        "http://127.0.0.1:11434/anthropic",
        disable_environment_proxy=True,
    )
    local_http = captured[-1]["http_client"]
    assert isinstance(local_http, httpx.Client)
    assert local_http.trust_env is False
    assert "HTTPProxy" not in _proxy_pool_types(local_http)
    assert normalized_proxy_env == []

    online = anthropic_adapter.build_anthropic_client(
        "test-key",
        "https://api.anthropic.com",
    )
    assert "http_client" not in captured[-1]
    assert normalized_proxy_env == [True]

    with pytest.raises(RuntimeError, match="constructor failed"):
        anthropic_adapter.build_anthropic_client(
            "constructor-fails",
            "http://127.0.0.1:11434/anthropic",
            disable_environment_proxy=True,
        )
    assert captured[-1]["http_client"].is_closed is True

    local.close()
    online.close()


@patch("run_agent.OpenAI")
def test_direct_local_primary_without_key_never_invokes_generic_router(
    mock_openai, monkeypatch
):
    config = _config("local_ai")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    monkeypatch.setattr(
        "agent.auxiliary_client.resolve_provider_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local direct caller must not construct routed client")
        ),
    )

    agent = AIAgent(
        base_url="http://localhost:11434/v1",
        provider="custom",
        model="test-model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["api_key"] == "no-key-required"
    assert str(kwargs["base_url"]) == "http://127.0.0.1:11434/v1"
    assert kwargs["http_client"].trust_env is False
    kwargs["http_client"].close()


@patch("run_agent.OpenAI")
def test_openai_pool_rotation_rejects_remote_route_atomically(
    mock_openai, monkeypatch
):
    config = _config("local_ai")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    agent = _agent()
    old_client = agent.client
    old_state = (
        agent.api_key,
        agent.base_url,
        dict(agent._client_kwargs),
    )
    prompt_cache_state = (
        id(agent.tools),
        repr(agent.tools),
        agent._use_prompt_caching,
        agent._use_native_cache_layout,
    )
    initial_calls = mock_openai.call_count

    with pytest.raises(EgressPolicyViolation):
        agent._swap_credential(
            SimpleNamespace(
                runtime_api_key="rotated-key",
                runtime_base_url="https://api.example.invalid/v1",
            )
        )

    assert agent.client is old_client
    assert (agent.api_key, agent.base_url, agent._client_kwargs) == old_state
    assert (
        id(agent.tools),
        repr(agent.tools),
        agent._use_prompt_caching,
        agent._use_native_cache_layout,
    ) == prompt_cache_state
    assert mock_openai.call_count == initial_calls

    initial_http = mock_openai.call_args.kwargs["http_client"]
    mock_openai.side_effect = RuntimeError("constructor failed")
    with pytest.raises(RuntimeError, match="Failed to rebuild rotated primary client"):
        agent._swap_credential(
            SimpleNamespace(
                runtime_api_key="authorized-rotated-key",
                runtime_base_url="http://127.0.0.1:11434/v1",
            )
        )
    assert agent.client is old_client
    assert (agent.api_key, agent.base_url, agent._client_kwargs) == old_state
    assert (
        id(agent.tools),
        repr(agent.tools),
        agent._use_prompt_caching,
        agent._use_native_cache_layout,
    ) == prompt_cache_state
    failed_http = mock_openai.call_args.kwargs["http_client"]
    assert failed_http.is_closed is True
    initial_http.close()


@patch("run_agent.OpenAI")
def test_local_ai_fails_closed_when_safe_http_transport_cannot_be_built(
    mock_openai, monkeypatch
):
    config = _config("local_ai")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    monkeypatch.setattr(
        AIAgent,
        "_build_keepalive_http_client",
        staticmethod(lambda *_args, **_kwargs: None),
    )

    with pytest.raises(RuntimeError) as caught:
        _agent()

    assert "egress_policy:proxy_disabled_transport_unavailable" in str(
        caught.value
    )
    assert mock_openai.call_count == 0


@pytest.mark.parametrize(
    ("provider", "api_mode"),
    [
        ("bedrock", "bedrock_converse"),
        ("aws-bedrock", "chat_completions"),
        ("copilot-acp", "chat_completions"),
        ("github-copilot-acp", "chat_completions"),
        ("moa", "chat_completions"),
        ("custom", "codex_app_server"),
        ("qwen-oauth", "chat_completions"),
        ("qwen", "chat_completions"),
        ("xai-oauth", "codex_responses"),
        ("minimax-oauth", "anthropic_messages"),
        ("minimax-oauth-io", "anthropic_messages"),
        ("vertex", "chat_completions"),
        ("vertex-ai", "chat_completions"),
    ],
)
def test_direct_primary_transport_that_ignores_base_url_is_rejected_preinit(
    monkeypatch, provider, api_mode
):
    config = _config("local_ai")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    with patch("run_agent.OpenAI") as mock_openai:
        with pytest.raises(EgressPolicyViolation):
            AIAgent(
                api_key="local-inert-key",
                base_url="http://127.0.0.1:11434/v1",
                provider=provider,
                api_mode=api_mode,
                model="test-model",
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
            )
    assert mock_openai.call_count == 0


@pytest.mark.parametrize(
    ("provider", "api_mode"),
    [
        ("anthropic", "anthropic_messages"),
        ("claude", "anthropic_messages"),
        ("claude-oauth", "anthropic_messages"),
        ("copilot", "chat_completions"),
        ("github", "chat_completions"),
        ("github-models", "chat_completions"),
        ("openai-codex", "codex_responses"),
        ("codex", "codex_responses"),
        ("nous", "chat_completions"),
        ("nousresearch", "chat_completions"),
    ],
)
def test_direct_remote_auth_identity_requires_explicit_local_credential(
    monkeypatch, provider, api_mode
):
    config = _config("local_ai")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    with patch("run_agent.OpenAI") as mock_openai:
        with pytest.raises(EgressPolicyViolation):
            AIAgent(
                base_url="http://127.0.0.1:11434/v1",
                provider=provider,
                api_mode=api_mode,
                model="test-model",
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
            )
    assert mock_openai.call_count == 0


def test_direct_local_azure_entra_callable_is_rejected_preinit(monkeypatch):
    config = _config("local_ai")
    config["model"].update(
        {
            "provider": "azure-foundry",
            "auth_mode": "entra_id",
        }
    )
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )

    with patch("run_agent.OpenAI") as mock_openai:
        with pytest.raises(EgressPolicyViolation):
            AIAgent(
                api_key=lambda: "remote-entra-token",
                base_url="http://127.0.0.1:11434/v1",
                provider="azure",
                model="test-model",
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
            )

    assert mock_openai.call_count == 0


@patch("run_agent.OpenAI")
def test_local_explicit_credentials_never_refresh_through_remote_auth_plane(
    mock_openai, monkeypatch
):
    config = _config("local_ai")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    cases = [
        (
            "copilot",
            "chat_completions",
            "_try_refresh_copilot_client_credentials",
            "fabric_cli.copilot_auth.resolve_copilot_token",
        ),
        (
            "openai-codex",
            "codex_responses",
            "_try_refresh_codex_client_credentials",
            "fabric_cli.auth.resolve_codex_runtime_credentials",
        ),
        (
            "nous",
            "chat_completions",
            "_try_refresh_nous_client_credentials",
            "fabric_cli.auth.resolve_nous_runtime_credentials",
        ),
    ]

    for provider, api_mode, method_name, resolver_path in cases:
        agent = AIAgent(
            api_key="local-inert-key",
            base_url="http://127.0.0.1:11434/v1",
            provider=provider,
            api_mode=api_mode,
            model="test-model",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        with monkeypatch.context() as scoped:
            scoped.setattr(
                resolver_path,
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("remote auth refresh must not run")
                ),
            )
            assert getattr(agent, method_name)() is False

    for call in mock_openai.call_args_list:
        call.kwargs["http_client"].close()


def test_local_anthropic_primary_rebuilds_keep_proxy_disabled(
    monkeypatch,
):
    captured = []

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            captured.append(kwargs)

        def close(self):
            http_client = self.kwargs.get("http_client")
            if http_client is not None and not http_client.is_closed:
                http_client.close()

    config = {
        "security": {
            "egress_mode": "local_ai",
            "local_ai_allowed_cidrs": [],
        },
        "model": {
            "provider": "anthropic",
            "default": "test-model",
            "base_url": "http://127.0.0.1:11434/anthropic",
        },
    }
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config", lambda: config
    )
    monkeypatch.setattr(
        anthropic_adapter,
        "_get_anthropic_sdk",
        lambda: SimpleNamespace(Anthropic=FakeAnthropic),
    )
    monkeypatch.setattr(
        anthropic_adapter,
        "resolve_anthropic_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local Anthropic must not resolve global OAuth")
        ),
    )

    agent = AIAgent(
        api_key="test-key",
        base_url="http://127.0.0.1:11434/anthropic",
        provider="anthropic",
        api_mode="anthropic_messages",
        model="test-model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    assert captured[-1]["http_client"].trust_env is False

    assert agent._try_refresh_anthropic_client_credentials() is False

    agent._rebuild_anthropic_client()
    assert captured[-1]["http_client"].trust_env is False

    agent._swap_credential(
        SimpleNamespace(
            runtime_api_key="rotated-key",
            runtime_base_url="http://127.0.0.1:11434/anthropic",
        )
    )
    assert captured[-1]["http_client"].trust_env is False

    live_client = agent._anthropic_client
    live_base = agent._anthropic_base_url
    live_key = agent._anthropic_api_key
    before_rejected_rotation = len(captured)
    with pytest.raises(EgressPolicyViolation):
        agent._swap_credential(
            SimpleNamespace(
                runtime_api_key="remote-key",
                runtime_base_url="https://api.example.invalid/anthropic",
            )
        )
    assert agent._anthropic_client is live_client
    assert agent._anthropic_base_url == live_base
    assert agent._anthropic_api_key == live_key
    assert len(captured) == before_rejected_rotation
    assert live_client.kwargs["http_client"].is_closed is False

    monkeypatch.setattr(
        anthropic_adapter,
        "build_anthropic_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("constructor failed")
        ),
    )
    with pytest.raises(RuntimeError, match="constructor failed"):
        agent._swap_credential(
            SimpleNamespace(
                runtime_api_key="authorized-new-key",
                runtime_base_url="http://127.0.0.1:11434/anthropic",
            )
        )
    assert agent._anthropic_client is live_client
    assert agent._anthropic_base_url == live_base
    assert agent._anthropic_api_key == live_key
    assert live_client.kwargs["http_client"].is_closed is False
    agent._anthropic_client.close()
