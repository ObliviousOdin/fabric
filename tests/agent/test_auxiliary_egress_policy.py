"""Profile-scoped local-AI policy tests for auxiliary routing."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import threading

import pytest

from agent.egress_policy import EgressPolicyViolation, policy_from_config
import agent.auxiliary_client as ac


def _local_policy(*cidrs: str):
    return policy_from_config(
        {
            "security": {
                "egress_mode": "local_ai",
                "local_ai_allowed_cidrs": list(cidrs),
            }
        }
    )


def _online_policy():
    return policy_from_config({"security": {"egress_mode": "online"}})


def _route_config(**overrides):
    config = {
        "security": {"egress_mode": "local_ai", "local_ai_allowed_cidrs": []},
        "model": {},
        "providers": {},
        "custom_providers": [],
    }
    config.update(overrides)
    return config


def _bomb(label: str):
    def fail(*_args, **_kwargs):
        raise AssertionError(f"{label} must not run before route authorization")

    return fail


def test_explicit_remote_auxiliary_is_rejected_before_credentials_or_client(monkeypatch):
    policy = _local_policy()
    config = _route_config(
        model={"provider": "openrouter", "default": "vendor/model"}
    )
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setattr(ac, "_validate_proxy_env_urls", _bomb("proxy validation"))
    monkeypatch.setattr(ac, "_try_openrouter", _bomb("OpenRouter credentials"))
    monkeypatch.setattr(ac, "_create_openai_client", _bomb("client construction"))

    with pytest.raises(EgressPolicyViolation) as caught:
        ac.resolve_provider_client("openrouter", model="vendor/model")

    assert caught.value.reason == "hostname_not_allowed"


def test_explicit_task_route_rejects_before_expanding_its_secret(monkeypatch):
    policy = _local_policy()
    config = _route_config(
        auxiliary={
            "title_generation": {
                "provider": "openrouter",
                "model": "vendor/model",
                "api_key": "${REMOTE_ONLY_KEY}",
            }
        }
    )
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setattr(
        ac, "_local_profile_secret", _bomb("task credential resolution")
    )

    with pytest.raises(EgressPolicyViolation):
        ac._resolve_task_provider_model("title_generation")


def test_local_auxiliary_is_literal_pinned_and_proxy_disabled(monkeypatch):
    policy = _local_policy()
    config = _route_config(
        model={
            "provider": "custom",
            "default": "local-model",
            "base_url": "http://localhost:11434/v1",
        }
    )
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            base_url=kwargs["base_url"], api_key=kwargs["api_key"]
        )

    monkeypatch.setattr(ac, "_create_openai_client", fake_create)

    client, model = ac.resolve_provider_client(
        "custom",
        model="local-model",
        explicit_base_url="http://localhost:11434/v1",
        explicit_api_key="local-key",
    )

    assert client is not None
    assert model == "local-model"
    assert captured["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["disable_environment_proxy"] is True


def test_proxy_disabled_transport_ignores_environment(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")

    kwargs = ac._openai_http_client_kwargs(
        "http://127.0.0.1:11434/v1",
        disable_environment_proxy=True,
    )
    client = kwargs["http_client"]
    try:
        assert client.trust_env is False
    finally:
        client.close()


def test_sync_local_transport_failure_never_falls_back_to_sdk_default(monkeypatch):
    monkeypatch.setattr("httpx.Client", _bomb("httpx transport construction"))
    monkeypatch.setattr(ac, "OpenAI", _bomb("OpenAI constructor"))

    with pytest.raises(
        RuntimeError, match="egress_policy:proxy_disabled_transport_unavailable"
    ):
        ac._create_openai_client(
            api_key="local-key",
            base_url="http://127.0.0.1:11434/v1",
            disable_environment_proxy=True,
        )


def test_async_local_transport_failure_never_invokes_async_sdk(monkeypatch):
    import openai

    monkeypatch.setattr(
        "httpx.AsyncClient", _bomb("async httpx transport construction")
    )
    monkeypatch.setattr(openai, "AsyncOpenAI", _bomb("AsyncOpenAI constructor"))
    sync_client = SimpleNamespace(
        api_key="local-key",
        base_url="http://127.0.0.1:11434/v1",
        _fabric_disable_environment_proxy=True,
    )

    with pytest.raises(
        RuntimeError, match="egress_policy:proxy_disabled_transport_unavailable"
    ):
        ac._to_async_client(sync_client, "local-model")


def test_task_fallback_skips_remote_before_resolving_local(monkeypatch):
    policy = _local_policy()
    config = _route_config(
        auxiliary={
            "compression": {
                "fallback_chain": [
                    {"provider": "openrouter", "model": "remote/model"},
                    {
                        "provider": "custom",
                        "model": "local-model",
                    "base_url": "http://localhost:11434/v1",
                    },
                ]
            }
        }
    )
    resolved = []

    def fake_resolve(entry, **kwargs):
        resolved.append((entry["provider"], kwargs["authorized_base_url"]))
        return SimpleNamespace(base_url=kwargs["authorized_base_url"]), entry["model"]

    monkeypatch.setattr(ac, "_resolve_fallback_entry", fake_resolve)
    monkeypatch.setattr(
        ac,
        "get_model_context_length",
        _bomb("probe-capable fallback context resolver"),
    )
    errors = []
    client, model, label = ac._try_configured_fallback_chain(
        "compression",
        "failed",
        policy=policy,
        route_config=config,
        policy_errors=errors,
    )

    assert client is not None
    assert model == "local-model"
    assert label == "fallback_chain[1](custom)"
    assert resolved == [("custom", "http://127.0.0.1:11434/v1")]
    assert [error.reason for error in errors] == ["hostname_not_allowed"]


def test_auto_skips_remote_main_and_task_fallback_then_uses_local_top_level(
    monkeypatch,
):
    policy = _local_policy()
    config = _route_config(
        model={"provider": "openrouter", "default": "remote/main"},
        auxiliary={
            "title_generation": {
                "fallback_chain": [
                    {"provider": "nous", "model": "remote/fallback"}
                ]
            }
        },
        fallback_providers=[
            {
                "provider": "custom",
                "model": "local-model",
                "base_url": "http://localhost:11434/v1",
                "api_key": "local-key",
            }
        ],
    )
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setattr(ac, "_try_openrouter", _bomb("remote discovery"))
    monkeypatch.setattr(ac, "_try_nous", _bomb("remote OAuth"))

    def fake_create(**kwargs):
        return SimpleNamespace(
            base_url=kwargs["base_url"], api_key=kwargs["api_key"]
        )

    monkeypatch.setattr(ac, "_create_openai_client", fake_create)

    client, model = ac.resolve_provider_client(
        "auto", task="title_generation"
    )

    assert client is not None
    assert str(client.base_url) == "http://127.0.0.1:11434/v1"
    assert model == "local-model"


def test_auto_without_authorized_candidate_surfaces_stable_policy_failure(
    monkeypatch,
):
    policy = _local_policy()
    config = _route_config(
        model={"provider": "openrouter", "default": "remote/main"}
    )
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setattr(ac, "_try_openrouter", _bomb("OpenRouter credentials"))
    monkeypatch.setattr(ac, "_try_nous", _bomb("Nous OAuth"))
    monkeypatch.setattr(ac, "_resolve_api_key_provider", _bomb("API key discovery"))

    with pytest.raises(EgressPolicyViolation) as caught:
        ac.resolve_provider_client("auto", task="title_generation")

    assert caught.value.mode.value == "local_ai"
    assert caught.value.reason == "remote_ai_forbidden"


def test_sequential_local_and_online_profiles_do_not_share_policy(monkeypatch):
    active = {"local": True}
    local = _local_policy()
    online = _online_policy()
    local_config = _route_config(
        model={"provider": "openrouter", "default": "vendor/model"}
    )
    online_config = {
        **local_config,
        "security": {"egress_mode": "online", "local_ai_allowed_cidrs": []},
    }
    monkeypatch.setattr(
        ac,
        "_load_auxiliary_egress_context",
        lambda: (local, local_config) if active["local"] else (online, online_config),
    )
    expected = SimpleNamespace(base_url="https://openrouter.ai/api/v1", api_key="k")
    monkeypatch.setattr(ac, "_try_openrouter", lambda **_kwargs: (expected, "vendor/model"))

    with pytest.raises(EgressPolicyViolation):
        ac.resolve_provider_client("openrouter", model="vendor/model")

    active["local"] = False
    client, model = ac.resolve_provider_client("openrouter", model="vendor/model")
    assert client is expected
    assert model == "vendor/model"


def test_named_local_provider_uses_only_each_profile_secret_scope(monkeypatch):
    from agent.secret_scope import reset_secret_scope, set_secret_scope

    policy = _local_policy()
    config = _route_config(
        custom_providers=[
            {
                "name": "lab",
                "provider_key": "lab",
                "model": "local-model",
                "base_url": "http://localhost:11434/v1",
                "key_env": "LAB_LOCAL_KEY",
            }
        ]
    )
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setenv("LAB_LOCAL_KEY", "launch-profile-must-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "launch-openai-key-must-not-leak")
    seen_keys = []

    def fake_create(**kwargs):
        seen_keys.append(kwargs["api_key"])
        return SimpleNamespace(
            base_url=kwargs["base_url"],
            api_key=kwargs["api_key"],
        )

    monkeypatch.setattr(ac, "_create_openai_client", fake_create)

    for scope in (
        {"LAB_LOCAL_KEY": "profile-a-key"},
        {"LAB_LOCAL_KEY": "profile-b-key"},
        {},
    ):
        token = set_secret_scope(scope)
        try:
            client, model = ac.resolve_provider_client("lab")
        finally:
            reset_secret_scope(token)
        assert client is not None
        assert model == "local-model"

    assert seen_keys == ["profile-a-key", "profile-b-key", "no-key-required"]


@pytest.mark.parametrize("provider", ["openrouter", "nous", "openai-codex"])
def test_authorized_named_cloud_identity_collapses_to_pinned_custom_transport(
    monkeypatch, provider
):
    policy = _local_policy()
    config = _route_config()
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setattr(ac, "_try_openrouter", _bomb("OpenRouter resolver"))
    monkeypatch.setattr(ac, "_try_nous", _bomb("Nous OAuth resolver"))
    monkeypatch.setattr(ac, "_read_codex_access_token", _bomb("Codex OAuth resolver"))
    captured = []

    def fake_create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            base_url=kwargs["base_url"],
            api_key=kwargs["api_key"],
        )

    monkeypatch.setattr(ac, "_create_openai_client", fake_create)

    client, _ = ac.resolve_provider_client(
        provider,
        model="local-model",
        explicit_base_url="http://localhost:11434/v1",
        explicit_api_key="local-key",
    )

    assert client is not None
    assert captured[0]["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured[0]["disable_environment_proxy"] is True


def test_post_construction_route_check_rejects_substituted_remote_client(monkeypatch):
    policy = _local_policy()
    config = _route_config()
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setattr(
        ac,
        "_create_openai_client",
        lambda **_kwargs: SimpleNamespace(
            base_url="https://api.openai.com/v1", api_key="local-key"
        ),
    )

    with pytest.raises(EgressPolicyViolation) as caught:
        ac.resolve_provider_client(
            "openrouter",
            model="local-model",
            explicit_base_url="http://localhost:11434/v1",
            explicit_api_key="local-key",
        )

    assert caught.value.reason == "hostname_not_allowed"


def test_local_auxiliary_reaches_loopback_with_proxy_environment_disabled(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("content-length", "0"))
            requests.append((self.path, json.loads(self.rfile.read(length))))
            body = json.dumps(
                {
                    "id": "local-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "local-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "local response",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    policy = _local_policy()
    config = _route_config()
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    try:
        response = ac.call_llm(
            provider="custom",
            model="local-model",
            base_url=f"http://localhost:{port}/v1",
            api_key="local-key",
            messages=[{"role": "user", "content": "hello"}],
            timeout=2,
        )
    finally:
        ac.shutdown_cached_clients()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.choices[0].message.content == "local response"
    assert requests[0][0] == "/v1/chat/completions"


class _LocalAuthError(Exception):
    status_code = 401


def _remote_recovery_bombs(monkeypatch):
    for name in (
        "_refresh_nous_recommended_model",
        "_nous_portal_account_has_fresh_paid_access",
        "_refresh_nous_auxiliary_client",
        "_refresh_provider_credentials",
        "_recover_provider_pool",
    ):
        monkeypatch.setattr(ac, name, _bomb(name))


def test_local_auxiliary_auth_error_never_refreshes_remote_credentials(
    monkeypatch,
):
    policy = _local_policy()
    config = _route_config()
    client = SimpleNamespace(
        base_url="http://127.0.0.1:11434/v1",
        api_key="local-key",
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: (_ for _ in ()).throw(
                    _LocalAuthError("local endpoint rejected credential")
                )
            )
        ),
    )
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setattr(
        ac,
        "_resolve_task_provider_model",
        lambda *_args, **_kwargs: (
            "nous",
            "local-model",
            "http://127.0.0.1:11434/v1",
            "local-key",
            "chat_completions",
        ),
    )
    monkeypatch.setattr(ac, "_get_cached_client", lambda *_args, **_kwargs: (client, "local-model"))
    _remote_recovery_bombs(monkeypatch)

    with pytest.raises(_LocalAuthError):
        ac.call_llm(
            task="compression",
            messages=[{"role": "user", "content": "hello"}],
        )


@pytest.mark.asyncio
async def test_async_local_auxiliary_auth_error_never_refreshes_remote_credentials(
    monkeypatch,
):
    policy = _local_policy()
    config = _route_config()

    async def fail(**_kwargs):
        raise _LocalAuthError("local endpoint rejected credential")

    client = SimpleNamespace(
        base_url="http://127.0.0.1:11434/v1",
        api_key="local-key",
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=fail)
        ),
    )
    monkeypatch.setattr(ac, "_load_auxiliary_egress_context", lambda: (policy, config))
    monkeypatch.setattr(
        ac,
        "_resolve_task_provider_model",
        lambda *_args, **_kwargs: (
            "nous",
            "local-model",
            "http://127.0.0.1:11434/v1",
            "local-key",
            "chat_completions",
        ),
    )
    monkeypatch.setattr(ac, "_get_cached_client", lambda *_args, **_kwargs: (client, "local-model"))
    _remote_recovery_bombs(monkeypatch)

    with pytest.raises(_LocalAuthError):
        await ac.async_call_llm(
            task="compression",
            messages=[{"role": "user", "content": "hello"}],
        )


def test_local_fallback_auth_error_skips_remote_refresh(monkeypatch):
    client = SimpleNamespace(
        base_url="http://127.0.0.1:11434/v1",
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: (_ for _ in ()).throw(
                    _LocalAuthError("stale local fallback key")
                )
            )
        ),
    )
    monkeypatch.setattr(ac, "_refresh_provider_credentials", _bomb("credential refresh"))

    result = ac._call_fallback_candidate_sync(
        client,
        "local-model",
        "custom",
        task="compression",
        messages=[{"role": "user", "content": "hello"}],
        temperature=None,
        max_tokens=None,
        tools=None,
        effective_timeout=2,
        effective_extra_body={},
        allow_remote_auth_refresh=False,
    )

    assert result is None
