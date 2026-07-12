"""Egress-policy contracts for the shared CLI/gateway model switch lane."""

from __future__ import annotations

from unittest.mock import Mock
import urllib.request

import pytest

from agent.egress_policy import EgressMode, EgressPolicyViolation
from fabric_cli.model_switch import list_authenticated_providers, switch_model
from fabric_cli.providers import ProviderDef


_ACCEPTED = {
    "accepted": True,
    "persist": True,
    "recognized": True,
    "message": None,
}


def _policy(mode: str, cidrs: list[str] | None = None) -> dict:
    return {
        "security": {
            "egress_mode": mode,
            "local_ai_allowed_cidrs": cidrs or [],
        },
        "model": {},
        "providers": {},
        "custom_providers": [],
    }


def _install_policy(monkeypatch: pytest.MonkeyPatch, config: dict) -> None:
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config",
        lambda: config,
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch._load_unexpanded_direct_aliases",
        lambda _provider: {},
    )


def _no_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_cli.model_switch.get_model_info", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "fabric_cli.model_switch.get_model_capabilities",
        lambda *_a, **_k: None,
    )


def test_forbidden_route_precedes_credentials_validation_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("local_ai"))
    calls = {"runtime": 0, "validate": 0, "restricted_validate": 0, "metadata": 0}

    def unexpected_runtime(**_kwargs):
        calls["runtime"] += 1
        raise AssertionError("credential/runtime resolution ran before authorization")

    def unexpected_validate(*_args, **_kwargs):
        calls["validate"] += 1
        raise AssertionError("live validation ran before authorization")

    def unexpected_restricted_validate(*_args, **_kwargs):
        calls["restricted_validate"] += 1
        raise AssertionError("restricted probe ran before authorization")

    def unexpected_metadata(*_args, **_kwargs):
        calls["metadata"] += 1
        raise AssertionError("provider metadata ran before authorization")

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        unexpected_runtime,
    )
    monkeypatch.setattr(
        "fabric_cli.models.validate_requested_model",
        unexpected_validate,
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch._restricted_validation",
        unexpected_restricted_validate,
    )
    monkeypatch.setattr("fabric_cli.model_switch.get_model_info", unexpected_metadata)
    monkeypatch.setattr(
        "fabric_cli.model_switch.get_model_capabilities",
        unexpected_metadata,
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch.resolve_provider_full",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("models.dev provider resolution ran before authorization")
        ),
    )

    result = switch_model(
        raw_input="remote-model",
        current_provider="custom",
        current_model="local-model",
        current_base_url="http://127.0.0.1:11434/v1",
        explicit_provider="remotebox",
        user_providers={
            "remotebox": {
                "name": "Remote Box",
                "base_url": "https://user:password@example.com/v1?token=TOPSECRET",
                "models": ["remote-model"],
            }
        },
    )

    assert result.success is False
    assert "egress_policy:invalid_endpoint" in result.error_message
    assert calls == {
        "runtime": 0,
        "validate": 0,
        "restricted_validate": 0,
        "metadata": 0,
    }
    serialized = repr(result)
    assert "password" not in serialized
    assert "TOPSECRET" not in serialized
    assert "example.com" not in serialized


def test_remote_direct_alias_cannot_bypass_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("local_ai"))
    from fabric_cli.model_switch import DirectAlias

    monkeypatch.setattr(
        "fabric_cli.model_switch._load_unexpanded_direct_aliases",
        lambda _provider: {
            "cloud-shortcut": DirectAlias(
                "cloud-model",
                "custom",
                "https://api.example.com/v1",
            )
        },
    )
    runtime = Mock(side_effect=AssertionError("direct alias reached credential resolver"))
    validate = Mock(side_effect=AssertionError("direct alias reached validation"))
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        runtime,
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch._restricted_validation",
        validate,
    )

    result = switch_model(
        raw_input="cloud-shortcut",
        current_provider="custom",
        current_model="local-model",
        current_base_url="http://127.0.0.1:11434/v1",
    )

    assert result.success is False
    assert "egress_policy:hostname_not_allowed" in result.error_message
    runtime.assert_not_called()
    validate.assert_not_called()


def test_local_switch_pins_localhost_before_runtime_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("local_ai"))
    _no_metadata(monkeypatch)
    runtime_calls: list[dict] = []
    validation_calls: list[dict] = []

    def resolve_runtime(**kwargs):
        runtime_calls.append(kwargs)
        return {
            "provider": "localbox",
            "api_key": "local-secret",
            "base_url": kwargs["explicit_base_url"],
            "api_mode": "chat_completions",
        }

    def validate(model, **kwargs):
        validation_calls.append({"model": model, **kwargs})
        return dict(_ACCEPTED)

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        resolve_runtime,
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch._restricted_validation",
        validate,
    )
    legacy_validate = Mock(side_effect=AssertionError("legacy proxy-aware probe used"))
    monkeypatch.setattr(
        "fabric_cli.models.validate_requested_model",
        legacy_validate,
    )

    result = switch_model(
        raw_input="qwen3:8b",
        current_provider="custom",
        current_model="old-model",
        current_base_url="http://127.0.0.1:9999/v1",
        explicit_provider="localbox",
        user_providers={
            "localbox": {
                "name": "Local Box",
                "base_url": "http://localhost:11434/v1/",
                "models": ["qwen3:8b"],
            }
        },
    )

    assert result.success is True, result.error_message
    assert result.base_url == "http://127.0.0.1:11434/v1"
    assert runtime_calls == [
        {
            "requested": "localbox",
            "explicit_api_key": None,
            "explicit_base_url": "http://127.0.0.1:11434/v1",
            "target_model": "qwen3:8b",
        }
    ]
    assert validation_calls[0]["base_url"] == "http://127.0.0.1:11434/v1"
    legacy_validate.assert_not_called()


def test_restricted_user_key_missing_from_profile_scope_never_uses_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.secret_scope import reset_secret_scope, set_secret_scope

    _install_policy(monkeypatch, _policy("local_ai"))
    _no_metadata(monkeypatch)
    monkeypatch.setenv("LOCALBOX_KEY", "launch-profile-secret")
    captured: list[dict] = []

    def resolve_runtime(**kwargs):
        captured.append(kwargs)
        return {
            "provider": "localbox",
            "api_key": kwargs.get("explicit_api_key") or "",
            "base_url": kwargs["explicit_base_url"],
            "api_mode": "chat_completions",
        }

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        resolve_runtime,
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch._restricted_validation",
        lambda *_a, **_k: dict(_ACCEPTED),
    )
    scope_token = set_secret_scope({})
    try:
        result = switch_model(
            raw_input="local-model",
            current_provider="custom",
            current_model="old-model",
            current_base_url="http://127.0.0.1:9999/v1",
            explicit_provider="localbox",
            user_providers={
                "localbox": {
                    "base_url": "http://127.0.0.1:11434/v1",
                    "api_key": "${LOCALBOX_KEY}",
                    "models": ["local-model"],
                }
            },
        )
    finally:
        reset_secret_scope(scope_token)

    assert result.success is True, result.error_message
    assert captured[0]["explicit_api_key"] is None
    assert "launch-profile-secret" not in repr(result)


def test_restricted_user_keys_follow_sequential_profile_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.secret_scope import reset_secret_scope, set_secret_scope

    _install_policy(monkeypatch, _policy("local_ai"))
    _no_metadata(monkeypatch)
    captured_keys: list[str | None] = []

    def resolve_runtime(**kwargs):
        captured_keys.append(kwargs.get("explicit_api_key"))
        return {
            "provider": "localbox",
            "api_key": kwargs.get("explicit_api_key") or "",
            "base_url": kwargs["explicit_base_url"],
            "api_mode": "chat_completions",
        }

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        resolve_runtime,
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch._restricted_validation",
        lambda *_a, **_k: dict(_ACCEPTED),
    )
    kwargs = {
        "raw_input": "local-model",
        "current_provider": "custom",
        "current_model": "old-model",
        "current_base_url": "http://127.0.0.1:9999/v1",
        "explicit_provider": "localbox",
        "user_providers": {
            "localbox": {
                "base_url": "http://127.0.0.1:11434/v1",
                "key_env": "LOCALBOX_KEY",
                "models": ["local-model"],
            }
        },
    }

    first_token = set_secret_scope({"LOCALBOX_KEY": "profile-a-key"})
    try:
        first = switch_model(**kwargs)
    finally:
        reset_secret_scope(first_token)
    second_token = set_secret_scope({"LOCALBOX_KEY": "profile-b-key"})
    try:
        second = switch_model(**kwargs)
    finally:
        reset_secret_scope(second_token)

    assert first.success is True, first.error_message
    assert second.success is True, second.error_message
    assert captured_keys == ["profile-a-key", "profile-b-key"]


def test_expanded_user_provider_key_is_never_serialized_in_restricted_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("local_ai"))
    expanded_secret = "expanded-profile-secret"

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **kwargs: {
            "provider": "localbox",
            "api_key": kwargs.get("explicit_api_key") or "",
            "base_url": kwargs["explicit_base_url"],
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch._restricted_validation",
        lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError(f"validator received {expanded_secret}")
        ),
    )

    result = switch_model(
        raw_input="local-model",
        current_provider="custom",
        current_model="old-model",
        current_base_url="http://127.0.0.1:9999/v1",
        explicit_provider="localbox",
        user_providers={
            "localbox": {
                "base_url": "http://127.0.0.1:11434/v1",
                "api_key": expanded_secret,
            }
        },
    )

    assert result.success is False
    assert expanded_secret not in repr(result)
    assert result.error_message == "Could not validate the requested model."


def test_runtime_cannot_substitute_a_different_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("local_ai"))
    validate = Mock(side_effect=AssertionError("substituted route was validated"))
    monkeypatch.setattr("fabric_cli.model_switch._restricted_validation", validate)
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "provider": "localbox",
            "api_key": "local-secret",
            "base_url": "https://remote.example/v1",
            "api_mode": "chat_completions",
        },
    )

    result = switch_model(
        raw_input="local-model",
        current_provider="custom",
        current_model="old-model",
        current_base_url="http://127.0.0.1:9999/v1",
        explicit_provider="localbox",
        user_providers={
            "localbox": {
                "base_url": "http://127.0.0.1:11434/v1",
                "models": ["local-model"],
            }
        },
    )

    assert result.success is False
    assert "egress_policy:hostname_not_allowed" in result.error_message
    validate.assert_not_called()


def test_restricted_validation_uses_empty_proxy_handler_and_literal_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli.model_switch import _restricted_validation

    captured: dict = {}

    class Response:
        headers = {"Content-Encoding": "identity"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            captured["read_limit"] = limit
            return b'{"data":[{"id":"local-model"}]}'

    class Opener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response()

    def build_opener(*handlers):
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)

    validation = _restricted_validation(
        "local-model",
        api_key="local-key",
        base_url="http://127.0.0.1:11434/v1",
        api_mode="chat_completions",
    )

    assert validation["accepted"] is True
    proxy_handler = next(
        handler
        for handler in captured["handlers"]
        if isinstance(handler, urllib.request.ProxyHandler)
    )
    assert proxy_handler.proxies == {}
    assert any(
        isinstance(handler, urllib.request.HTTPRedirectHandler)
        for handler in captured["handlers"]
    )
    assert captured["url"] == "http://127.0.0.1:11434/v1/models"
    assert captured["timeout"] == 5.0
    assert captured["read_limit"] == 1024 * 1024 + 1


def test_same_provider_policy_error_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("local_ai"))
    validate = Mock(side_effect=AssertionError("policy error was swallowed"))
    monkeypatch.setattr("fabric_cli.model_switch._restricted_validation", validate)

    def reject_runtime(**_kwargs):
        raise EgressPolicyViolation(
            "remote_ai_forbidden",
            mode=EgressMode.LOCAL_AI,
            purpose="primary",
            provider="custom",
            origin_digest="0123456789ab",
        )

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        reject_runtime,
    )

    result = switch_model(
        raw_input="local-model",
        current_provider="custom",
        current_model="old-model",
        current_base_url="http://127.0.0.1:11434/v1",
    )

    assert result.success is False
    assert result.error_message == (
        "egress_policy:remote_ai_forbidden mode=local_ai purpose=primary "
        "provider=custom origin=0123456789ab"
    )
    validate.assert_not_called()


def test_user_provider_policy_error_is_not_converted_to_fallback_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("local_ai"))
    validate = Mock(side_effect=AssertionError("user-provider policy error was swallowed"))
    monkeypatch.setattr("fabric_cli.model_switch._restricted_validation", validate)

    def reject_runtime(**_kwargs):
        policy_error = EgressPolicyViolation(
            "remote_ai_forbidden",
            mode=EgressMode.LOCAL_AI,
            purpose="primary",
            provider="localbox",
            origin_digest="abcdef012345",
        )
        raise RuntimeError("provider wrapped policy failure") from policy_error

    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        reject_runtime,
    )

    result = switch_model(
        raw_input="local-model",
        current_provider="custom",
        current_model="old-model",
        current_base_url="http://127.0.0.1:9999/v1",
        explicit_provider="localbox",
        user_providers={
            "localbox": {
                "base_url": "http://127.0.0.1:11434/v1",
                "api_key": "must-not-appear",
                "models": ["local-model"],
            }
        },
    )

    assert result.success is False
    assert "egress_policy:remote_ai_forbidden" in result.error_message
    assert "must-not-appear" not in repr(result)
    validate.assert_not_called()


def test_policy_is_reloaded_for_sequential_profiles_without_bleed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs = iter([_policy("local_ai"), _policy("online")])
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config",
        lambda: next(configs),
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch._load_unexpanded_direct_aliases",
        lambda _provider: {},
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch.resolve_provider_full",
        lambda *_a, **_k: ProviderDef(
            id="remotebox",
            name="Remote Box",
            transport="openai_chat",
            api_key_env_vars=(),
            base_url="https://api.example.com/v1",
        ),
    )
    monkeypatch.setattr("fabric_cli.model_switch.resolve_alias", lambda *_a: None)
    monkeypatch.setattr("fabric_cli.model_switch.get_label", lambda _p: "Remote Box")
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "provider": "remotebox",
            "api_key": "online-key",
            "base_url": "https://api.example.com/v1",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr(
        "fabric_cli.models.validate_requested_model",
        lambda *_a, **_k: dict(_ACCEPTED),
    )
    _no_metadata(monkeypatch)

    kwargs = {
        "raw_input": "remote-model",
        "current_provider": "custom",
        "current_model": "local-model",
        "current_base_url": "http://127.0.0.1:11434/v1",
        "explicit_provider": "remotebox",
        "user_providers": {
            "remotebox": {
                "name": "Remote Box",
                "base_url": "https://api.example.com/v1",
                "models": ["remote-model"],
            }
        },
    }
    restricted = switch_model(**kwargs)
    online = switch_model(**kwargs)

    assert restricted.success is False
    assert "egress_policy:hostname_not_allowed" in restricted.error_message
    assert online.success is True, online.error_message
    assert online.base_url == "https://api.example.com/v1"


def test_air_gapped_is_configured_but_unavailable_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("air_gapped"))
    runtime = Mock(side_effect=AssertionError("air_gapped reached runtime resolution"))
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        runtime,
    )

    result = switch_model(
        raw_input="local-model",
        current_provider="custom",
        current_model="old-model",
        current_base_url="http://127.0.0.1:11434/v1",
    )

    assert result.success is False
    assert "egress_policy:whole_process_network_boundary_missing" in result.error_message
    assert "mode=air_gapped" in result.error_message
    runtime.assert_not_called()


def test_local_picker_is_config_only_and_never_discovers_credentials_or_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _policy("local_ai")
    config["providers"] = {
        "localbox": {
            "name": "Local Box",
            "base_url": "http://localhost:11434/v1",
            "key_env": "LOCALBOX_KEY",
            "models": ["local-a", "local-b"],
        },
        "cloudbox": {
            "name": "Cloud Box",
            "base_url": "https://api.example.com/v1",
            "models": ["remote-model"],
        },
    }
    _install_policy(monkeypatch, config)
    monkeypatch.setenv("LOCALBOX_KEY", "must-not-be-read")
    monkeypatch.setattr(
        "agent.models_dev.fetch_models_dev",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("picker fetched models.dev")
        ),
    )
    monkeypatch.setattr(
        "fabric_cli.models.fetch_api_models",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("picker probed /models")
        ),
    )
    monkeypatch.setattr(
        "agent.credential_pool.load_pool",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("picker resolved credential pool")
        ),
    )

    rows = list_authenticated_providers(
        current_provider="localbox",
        current_base_url="http://localhost:11434/v1",
        current_model="local-a",
        refresh=True,
        probe_custom_providers=True,
    )

    assert [row["slug"] for row in rows] == ["localbox"]
    assert rows[0]["api_url"] == "http://127.0.0.1:11434/v1"
    assert rows[0]["models"] == ["local-a", "local-b"]


def test_air_gapped_picker_returns_no_rows_without_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_policy(monkeypatch, _policy("air_gapped"))
    metadata = Mock(side_effect=AssertionError("air_gapped picker performed discovery"))
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", metadata)

    rows = list_authenticated_providers(
        current_provider="custom",
        current_base_url="http://127.0.0.1:11434/v1",
        current_model="local-model",
        refresh=True,
    )

    assert rows == []
    metadata.assert_not_called()
