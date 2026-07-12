"""REST model picker must enter policy before profile secret loading."""

from __future__ import annotations

from unittest.mock import Mock

from fabric_cli import web_server


def _local_config():
    return {
        "security": {
            "egress_mode": "local_ai",
            "local_ai_allowed_cidrs": [],
        },
        "model": {
            "provider": "custom",
            "default": "local-model",
            "base_url": "http://localhost:11434/v1",
        },
        "providers": {
            "localbox": {
                "api": "http://127.0.0.1:8000/v1",
                "models": ["local-a"],
            },
            "remote": {
                "api": "https://api.example.com/v1",
                "api_key": "${REMOTE_KEY}",
                "models": ["remote-model"],
            },
        },
        "custom_providers": [],
    }


def _bomb(label):
    def fail(*_args, **_kwargs):
        raise AssertionError(f"{label} must not run for restricted REST picker")

    return fail


def test_rest_model_options_restricted_before_secrets_and_discovery(monkeypatch):
    strict = _local_config()
    monkeypatch.setattr("fabric_cli.config.load_egress_policy_config", lambda: strict)
    monkeypatch.setattr("fabric_cli.config.load_config", _bomb("expanded config"))
    monkeypatch.setattr(
        "agent.secret_scope.build_profile_secret_scope", _bomb("profile secrets")
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch.list_authenticated_providers",
        _bomb("provider discovery"),
    )
    monkeypatch.setattr("fabric_cli.inventory._apply_pricing", _bomb("pricing"))
    monkeypatch.setattr(
        "fabric_cli.inventory._apply_capabilities", _bomb("capabilities")
    )

    payload = web_server.get_model_options(
        refresh=True,
        include_unconfigured=True,
        explicit_only=True,
    )

    assert [row["slug"] for row in payload["providers"]] == [
        "custom",
        "custom:localbox",
    ]
    assert "remote-model" not in repr(payload)
    assert "REMOTE_KEY" not in repr(payload)


def test_rest_model_options_online_preserves_secret_scope_and_discovery(
    monkeypatch,
):
    strict = {
        "security": {"egress_mode": "online"},
        "model": {},
        "providers": {},
        "custom_providers": [],
    }
    expanded = {
        "security": {"egress_mode": "online"},
        "model": {"provider": "openrouter", "default": "vendor/model"},
        "providers": {},
        "custom_providers": [],
    }
    monkeypatch.setattr("fabric_cli.config.load_egress_policy_config", lambda: strict)
    load_config = Mock(return_value=expanded)
    profile_secrets = Mock(return_value={})
    discovery = Mock(
        return_value=[
            {
                "slug": "openrouter",
                "name": "OpenRouter",
                "models": ["vendor/model"],
                "total_models": 1,
                "is_current": True,
                "is_user_defined": False,
                "source": "built-in",
            }
        ]
    )
    monkeypatch.setattr("fabric_cli.config.load_config", load_config)
    monkeypatch.setattr(
        "agent.secret_scope.build_profile_secret_scope", profile_secrets
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch.list_authenticated_providers", discovery
    )
    monkeypatch.setattr("fabric_cli.inventory._moa_provider_row", lambda *_a: None)
    monkeypatch.setattr("fabric_cli.inventory._apply_pricing", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "fabric_cli.inventory._apply_capabilities", lambda *_a, **_k: None
    )

    payload = web_server.get_model_options()

    assert payload["providers"][0]["slug"] == "openrouter"
    assert load_config.called
    profile_secrets.assert_called_once()
    discovery.assert_called_once()
