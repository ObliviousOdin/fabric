import argparse
from types import SimpleNamespace


def test_xai_model_flow_reauth_uses_standard_radio_prompt(monkeypatch):
    from fabric_cli import main as main_mod

    captured = {"login_calls": 0}

    monkeypatch.setattr(
        "fabric_cli.auth.get_xai_oauth_auth_status",
        lambda: {"logged_in": True},
    )
    monkeypatch.setattr(
        "fabric_cli.setup._curses_prompt_choice",
        lambda title, choices, default, description=None: 1,
    )

    def _fake_login(**kwargs):
        captured["login_calls"] += 1
        captured.update(kwargs)
        return SimpleNamespace(credential_label="fresh-xai")

    monkeypatch.setattr(
        "fabric_cli.provider_account_oauth.login_personal_provider", _fake_login
    )
    monkeypatch.setattr(
        "fabric_cli.auth.resolve_xai_oauth_runtime_credentials",
        lambda *args, **kwargs: {"base_url": "https://api.x.ai/v1"},
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda model_ids, current_model="": None,
    )

    main_mod._model_flow_xai_oauth(
        {},
        current_model="grok-build-0.1",
        args=argparse.Namespace(no_browser=True, timeout=3),
    )

    assert captured["login_calls"] == 1
    assert captured["provider_id"] == "xai-oauth"
    assert captured["expected_revision"] is None
    assert captured["no_browser"] is True
    assert captured["timeout_seconds"] == 3


def test_xai_model_flow_cancel_skips_reauth(monkeypatch):
    from fabric_cli import main as main_mod

    monkeypatch.setattr(
        "fabric_cli.auth.get_xai_oauth_auth_status",
        lambda: {"logged_in": True},
    )
    monkeypatch.setattr(
        "fabric_cli.setup._curses_prompt_choice",
        lambda title, choices, default, description=None: 2,
    )
    monkeypatch.setattr(
        "fabric_cli.auth._login_xai_oauth",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not reauthenticate")),
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not pick a model")),
    )

    main_mod._model_flow_xai_oauth({}, current_model="grok-build-0.1")


def test_auth_credentials_choice_falls_back_to_numbered_prompt(monkeypatch):
    from fabric_cli import main as main_mod

    monkeypatch.setattr(
        "fabric_cli.setup._curses_prompt_choice",
        lambda title, choices, default, description=None: -1,
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")

    assert main_mod._prompt_auth_credentials_choice("Credentials:") == "reauth"
