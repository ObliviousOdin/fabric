"""Policy-first model picker and live-switch surface tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tui_gateway import server


def _write_local_config(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        """
security:
  egress_mode: local_ai
model:
  provider: custom
  default: local-main
  base_url: http://localhost:11434/v1
providers:
  localbox:
    name: Local Box
    api: http://127.0.0.1:8000/v1
    models: [local-a, local-b]
  remotebox:
    name: Remote Box
    api: https://api.example.com/v1
    api_key: ${REMOTE_KEY}
    models: [remote-model]
""".strip(),
        encoding="utf-8",
    )


def _bomb(label):
    def fail(*_args, **_kwargs):
        raise AssertionError(f"{label} must not run in restricted picker flow")

    return fail


def test_restricted_model_options_skips_secret_scope_and_all_discovery(
    tmp_path, monkeypatch
):
    home = tmp_path / "profiles" / "local"
    _write_local_config(home)
    sid = "restricted-options"
    server._sessions[sid] = {
        "profile_home": str(home),
        "agent": None,
    }
    monkeypatch.setattr(
        "agent.secret_scope.build_profile_secret_scope", _bomb("secret scope")
    )
    monkeypatch.setattr("fabric_cli.config.load_config", _bomb("expanded config"))
    monkeypatch.setattr(
        "fabric_cli.model_switch.list_authenticated_providers",
        _bomb("provider discovery"),
    )
    monkeypatch.setattr(server, "_resolve_model", _bomb("legacy model config"))

    try:
        response = server._methods["model.options"](
            "1",
            {
                "session_id": sid,
                "include_unconfigured": True,
                "refresh": True,
            },
        )
    finally:
        server._sessions.pop(sid, None)

    assert "error" not in response, response
    rows = response["result"]["providers"]
    assert [row["slug"] for row in rows] == [
        "custom",
        "custom:localbox",
    ]
    assert "remote-model" not in repr(response)
    assert rows[0]["api_url"] == "http://127.0.0.1:11434/v1"


def test_restricted_live_switch_rejects_before_secret_or_runtime_resolution(
    tmp_path, monkeypatch
):
    home = tmp_path / "profiles" / "local-switch"
    _write_local_config(home)
    monkeypatch.setattr(
        "agent.secret_scope.build_profile_secret_scope", _bomb("secret scope")
    )
    monkeypatch.setattr("fabric_cli.config.load_config", _bomb("expanded config"))
    monkeypatch.setattr(
        "fabric_cli.runtime_provider.resolve_runtime_provider",
        _bomb("runtime credential resolution"),
    )
    monkeypatch.setattr(
        "fabric_cli.model_switch.resolve_provider_full",
        _bomb("provider metadata discovery"),
    )
    monkeypatch.setattr(server, "_resolve_model", _bomb("legacy model config"))

    with pytest.raises(ValueError, match="egress_policy:remote_ai_forbidden"):
        server._apply_model_switch(
            "restricted-switch",
            {"profile_home": str(home), "agent": None},
            "remote-model --provider openrouter",
        )


def test_online_model_options_keeps_legacy_expanded_and_discovery_path(
    monkeypatch,
):
    expanded = {
        "security": {"egress_mode": "online"},
        "model": {
            "provider": "openrouter",
            "default": "vendor/model",
            "base_url": "https://openrouter.ai/api/v1",
        },
        "providers": {},
        "custom_providers": [],
    }
    monkeypatch.setattr(
        "fabric_cli.config.load_egress_policy_config",
        lambda: {
            "security": {"egress_mode": "online"},
            "model": {},
            "providers": {},
            "custom_providers": [],
        },
    )
    load_config_calls = []
    monkeypatch.setattr(
        "fabric_cli.config.load_config",
        lambda: load_config_calls.append(True) or expanded,
    )
    discovered = []
    monkeypatch.setattr(
        "fabric_cli.model_switch.list_authenticated_providers",
        lambda **kwargs: (
            discovered.append(kwargs)
            or [
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
        ),
    )
    monkeypatch.setattr("fabric_cli.inventory._moa_provider_row", lambda *_a: None)
    monkeypatch.setattr("fabric_cli.inventory._apply_pricing", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "fabric_cli.inventory._apply_capabilities", lambda *_a, **_k: None
    )
    monkeypatch.setattr(server, "_resolve_model", lambda: "vendor/model")

    response = server._methods["model.options"]("2", {"session_id": ""})

    assert "error" not in response, response
    assert load_config_calls
    assert discovered
    assert response["result"]["providers"][0]["slug"] == "openrouter"
