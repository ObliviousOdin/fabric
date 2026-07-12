from __future__ import annotations

import builtins
import logging
from types import SimpleNamespace

import pytest

from fabric_cli import provider_accounts as accounts


@pytest.mark.parametrize("remote", [False, True])
def test_setup_xai_login_uses_canonical_profile_service_and_remote_browser_policy(
    tmp_path,
    monkeypatch,
    remote,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import setup

    home = tmp_path / "profile"
    home.mkdir()
    captured = {}

    def login_personal_provider(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(credential_label="safe-label")

    monkeypatch.setattr(setup, "get_fabric_home", lambda: home)
    monkeypatch.setattr(auth_mod, "_is_remote_session", lambda: remote)
    monkeypatch.setattr(
        provider_account_oauth,
        "login_personal_provider",
        login_personal_provider,
    )
    monkeypatch.setattr(
        auth_mod,
        "_update_config_for_provider",
        lambda provider_id, base_url: captured.update(
            configured=(provider_id, base_url)
        ),
    )

    assert setup._run_xai_oauth_login_from_setup() is True
    assert captured["home"] == home
    assert captured["provider_id"] == "xai-oauth"
    assert captured["expected_revision"] is None
    assert captured["no_browser"] is remote
    assert captured["configured"][0] == "xai-oauth"


def test_setup_xai_login_renders_only_stable_safe_failure(
    tmp_path,
    monkeypatch,
    capsys,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import setup

    home = tmp_path / "profile"
    home.mkdir()
    sentinel = "raw provider response and /private/profile/path"
    config_updates = []
    monkeypatch.setattr(setup, "get_fabric_home", lambda: home)
    monkeypatch.setattr(auth_mod, "_is_remote_session", lambda: False)
    monkeypatch.setattr(
        provider_account_oauth,
        "login_personal_provider",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(sentinel)),
    )
    monkeypatch.setattr(
        auth_mod,
        "_update_config_for_provider",
        lambda *_args: config_updates.append("forbidden"),
    )

    assert setup._run_xai_oauth_login_from_setup() is False
    output = capsys.readouterr().out
    assert "invalid_state" in output
    assert sentinel not in output
    assert str(home) not in output
    assert config_updates == []


def test_setup_xai_login_reports_connected_when_only_model_config_update_fails(
    tmp_path,
    monkeypatch,
    capsys,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import setup

    home = tmp_path / "profile"
    home.mkdir()
    sentinel = "raw config path /private/profile/config.yaml"
    monkeypatch.setattr(setup, "get_fabric_home", lambda: home)
    monkeypatch.setattr(auth_mod, "_is_remote_session", lambda: False)
    monkeypatch.setattr(
        provider_account_oauth,
        "login_personal_provider",
        lambda **_kwargs: SimpleNamespace(credential_label="connected"),
    )
    monkeypatch.setattr(
        auth_mod,
        "_update_config_for_provider",
        lambda *_args: (_ for _ in ()).throw(RuntimeError(sentinel)),
    )

    assert setup._run_xai_oauth_login_from_setup() is True
    output = capsys.readouterr().out
    assert "OAuth is connected" in output
    assert "xAI TTS and tools can use" in output
    assert "fabric model" in output
    assert "login failed" not in output
    assert sentinel not in output


def test_setup_xai_login_honors_concurrent_managed_supersession(
    tmp_path,
    monkeypatch,
    capsys,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import setup

    home = tmp_path / "profile"
    home.mkdir()
    managed = accounts.create_managed_request(
        home=home,
        provider_id="xai-oauth",
        device_label="Fabric",
        expected_revision=0,
    )
    config_updates = []

    def supersede_personal_flow(**_kwargs):
        personal = accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        )
        accounts.create_managed_request(
            home=home,
            provider_id="xai-oauth",
            device_label="Fabric",
            expected_revision=personal.revision,
        )
        return {
            "tokens": {
                "access_token": "must-not-persist",
                "refresh_token": "must-not-persist",
            },
            "discovery": {"issuer": "https://accounts.x.ai"},
            "base_url": "https://api.x.ai/v1",
        }

    monkeypatch.setattr(setup, "get_fabric_home", lambda: home)
    monkeypatch.setattr(auth_mod, "_is_remote_session", lambda: False)
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        supersede_personal_flow,
    )
    monkeypatch.setattr(
        auth_mod,
        "_update_config_for_provider",
        lambda *_args, **_kwargs: config_updates.append("forbidden"),
    )

    assert setup._run_xai_oauth_login_from_setup() is True
    output = capsys.readouterr().out
    assert "must-not-persist" not in output
    assert config_updates == ["forbidden"]
    snapshot = accounts.get_account_snapshot(
        home=home,
        provider_id="xai-oauth",
    )
    assert snapshot.desired_ownership == "fabric_managed"
    assert snapshot.active_request_id == managed.request.request_id
    assert snapshot.active_request is not None
    assert snapshot.active_request.status == "requested"
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_completion is not None
    assert snapshot.oauth_completion.intent_matched is False
    assert (home / "auth.json").exists()


def test_tts_xai_choice_routes_through_shared_account_login(
    monkeypatch,
):
    from fabric_cli import setup

    choices = iter([3, 0])
    calls = []
    config = {}
    monkeypatch.setattr(setup, "managed_nous_tools_enabled", lambda: False)
    monkeypatch.setattr(
        setup,
        "get_nous_subscription_features",
        lambda _config, **_kwargs: SimpleNamespace(nous_auth_present=False),
    )
    monkeypatch.setattr(
        setup,
        "prompt_choice",
        lambda *_args, **_kwargs: next(choices),
    )
    monkeypatch.setattr(setup, "prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(setup, "get_env_value", lambda _key: None)
    monkeypatch.setattr(setup, "_xai_oauth_logged_in_for_setup", lambda: False)
    monkeypatch.setattr(
        setup,
        "_run_xai_oauth_login_from_setup",
        lambda: calls.append("login") or True,
    )
    monkeypatch.setattr(setup, "save_config", lambda _config: None)

    setup._setup_tts_provider(config)

    assert calls == ["login"]
    assert config["tts"]["provider"] == "xai"


def test_tools_config_xai_post_setup_routes_through_shared_account_login(
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import setup
    from fabric_cli import tools_config

    calls = []
    monkeypatch.setattr(
        auth_mod,
        "get_xai_oauth_auth_status",
        lambda: {"logged_in": False},
    )
    monkeypatch.setattr(tools_config, "get_env_value", lambda _key: None)
    monkeypatch.setattr(setup, "prompt_choice", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        setup,
        "_run_xai_oauth_login_from_setup",
        lambda: calls.append("login") or True,
    )

    tools_config._run_post_setup("xai_grok")

    assert calls == ["login"]


def test_tools_config_xai_setup_import_failure_is_stable_and_trace_only(
    monkeypatch,
    capsys,
    caplog,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import tools_config

    sentinel = "raw import path /private/setup.py and secret"
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "fabric_cli.setup":
            raise RuntimeError(sentinel)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(
        auth_mod,
        "get_xai_oauth_auth_status",
        lambda: {"logged_in": False},
    )
    monkeypatch.setattr(tools_config, "get_env_value", lambda _key: None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    caplog.set_level(logging.WARNING, logger=tools_config.__name__)

    tools_config._run_post_setup("xai_grok")

    output = capsys.readouterr().out
    assert "setup_helpers_unavailable" in output
    assert "fabric auth add xai-oauth" in output
    assert sentinel not in output
    assert sentinel not in caplog.text
    assert "code=setup_helpers_unavailable" in caplog.text
    assert "trace=" in caplog.text
