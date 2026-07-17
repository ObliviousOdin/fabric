"""Model-picker integration with profile-owned provider-account OAuth."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from fabric_cli import provider_accounts as accounts


def _select_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FABRIC_HOME", str(home))
    monkeypatch.setenv("FABRIC_HOME", str(home))


def _codex_credentials() -> dict[str, object]:
    return {
        "tokens": {
            "access_token": "model-codex-access",
            "refresh_token": "model-codex-refresh",
        },
        "base_url": "https://chatgpt.com/backend-api/codex",
        "last_refresh": "2026-07-11T12:00:00Z",
    }


def _xai_credentials() -> dict[str, object]:
    return {
        "tokens": {
            "access_token": "model-xai-access",
            "refresh_token": "model-xai-refresh",
            "token_type": "Bearer",
        },
        "discovery": {"issuer": "https://accounts.x.ai"},
        "redirect_uri": "",
        "base_url": "https://api.x.ai/v1",
        "last_refresh": "2026-07-11T12:00:00Z",
    }


def _disable_model_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "fabric_cli.codex_models.get_codex_model_ids",
        lambda access_token=None: ["gpt-5.4"],
    )


def test_codex_model_fresh_login_uses_personal_coordinator_pool_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from fabric_cli import main as main_mod

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    _disable_model_selection(monkeypatch)
    created = accounts.create_managed_request(
        home=home,
        provider_id="openai-codex",
        device_label="default fabric",
        expected_revision=0,
    )
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    main_mod._model_flow_openai_codex({}, current_model="gpt-5.4")

    output = capsys.readouterr().out
    assert "Connected personal openai-codex credential" in output
    snapshot = accounts.get_account_snapshot(home=home, provider_id="openai-codex")
    assert snapshot.desired_ownership == "personal"
    assert snapshot.oauth_lease is None
    assert snapshot.active_request is None
    terminal = next(
        request
        for request in snapshot.requests
        if request.request_id == created.request.request_id
    )
    assert terminal.status == "cancelled"
    assert terminal.decision_source == "verified_personal_oauth"
    assert terminal.decision_reason == "superseded_by_verified_personal"

    store = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    assert "openai-codex" not in store.get("providers", {})
    entries = store["credential_pool"]["openai-codex"]
    assert [entry["source"] for entry in entries] == ["manual:device_code"]
    assert entries[0]["access_token"] == "model-codex-access"


def test_codex_model_relogin_preserves_multiple_local_pool_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import auth as auth_mod
    from fabric_cli import main as main_mod

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    _disable_model_selection(monkeypatch)
    auth_mod.write_credential_pool(
        "openai-codex",
        [
            {
                "id": "first1",
                "label": "first",
                "auth_type": "oauth",
                "priority": 0,
                "source": "manual:device_code",
                "access_token": "existing-access-1",
                "refresh_token": "existing-refresh-1",
            },
            {
                "id": "second",
                "label": "second",
                "auth_type": "oauth",
                "priority": 1,
                "source": "manual:device_code",
                "access_token": "existing-access-2",
                "refresh_token": "existing-refresh-2",
            },
        ],
    )
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda _title: "reauth",
    )
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    main_mod._model_flow_openai_codex({}, current_model="gpt-5.4")

    store = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    entries = store["credential_pool"]["openai-codex"]
    assert [entry["access_token"] for entry in entries] == [
        "existing-access-1",
        "existing-access-2",
        "model-codex-access",
    ]
    assert all(entry["source"] == "manual:device_code" for entry in entries)
    assert "openai-codex" not in store.get("providers", {})


def test_named_xai_model_relogin_writes_profile_without_overwriting_global_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import main as main_mod

    root = tmp_path / "fabric"
    named = root / "profiles" / "design"
    _select_home(monkeypatch, named)
    root.mkdir(parents=True, exist_ok=True)
    (root / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "providers": {
                "xai-oauth": {
                    "root_only_marker": "keep-at-root",
                    "tokens": {
                        "access_token": "root-access",
                        "refresh_token": "root-refresh",
                    },
                }
            },
            "credential_pool": {
                "xai-oauth": [
                    {
                        "id": "root01",
                        "label": "root",
                        "auth_type": "oauth",
                        "priority": 0,
                        "source": "device_code",
                        "access_token": "root-access",
                        "refresh_token": "root-refresh",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )
    _disable_model_selection(monkeypatch)
    monkeypatch.setattr(
        "fabric_cli.model_setup_flows._prompt_auth_credentials_choice",
        lambda _title: "reauth",
    )
    monkeypatch.setattr(
        "fabric_cli.auth._xai_oauth_device_code_login",
        lambda **_kwargs: _xai_credentials(),
    )

    main_mod._model_flow_xai_oauth(
        {},
        current_model="grok-build-0.1",
        args=argparse.Namespace(no_browser=True, timeout=3),
    )

    snapshot = accounts.get_account_snapshot(home=named, provider_id="xai-oauth")
    assert snapshot.desired_ownership == "personal"
    assert snapshot.oauth_lease is None
    profile_store = json.loads((named / "auth.json").read_text(encoding="utf-8"))
    root_store = json.loads((root / "auth.json").read_text(encoding="utf-8"))
    assert (
        profile_store["providers"]["xai-oauth"]["tokens"]
        == (_xai_credentials()["tokens"])
    )
    assert "root_only_marker" not in profile_store["providers"]["xai-oauth"]
    assert [
        entry["access_token"] for entry in profile_store["credential_pool"]["xai-oauth"]
    ] == ["model-xai-access"]
    assert root_store["providers"]["xai-oauth"]["tokens"] == {
        "access_token": "root-access",
        "refresh_token": "root-refresh",
    }


@pytest.mark.parametrize(
    ("failure", "expected_output"),
    [
        (SystemExit(1), "Login cancelled or failed."),
        (SystemExit(130), "Login cancelled."),
        (
            RuntimeError("/private/profile?access_token=RAW-SECRET-SENTINEL"),
            "Login failed (io_unavailable): Preserve state and retry later.",
        ),
    ],
    ids=["denied", "cancelled", "unexpected-error"],
)
def test_xai_model_failure_releases_lease_preserves_request_and_redacts_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: BaseException,
    expected_output: str,
) -> None:
    from fabric_cli import main as main_mod

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    created = accounts.create_managed_request(
        home=home,
        provider_id="xai-oauth",
        device_label="front desk",
        expected_revision=0,
    )

    def fail_login(**_kwargs):
        raise failure

    monkeypatch.setattr("fabric_cli.auth._xai_oauth_device_code_login", fail_login)
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("model picker must not run after failed login")
        ),
    )

    main_mod._model_flow_xai_oauth({}, current_model="grok-build-0.1")

    output = capsys.readouterr().out
    assert expected_output in output
    assert "RAW-SECRET-SENTINEL" not in output
    assert "/private/profile" not in output
    snapshot = accounts.get_account_snapshot(home=home, provider_id="xai-oauth")
    assert snapshot.desired_ownership == "personal"
    assert snapshot.active_request_id == created.request.request_id
    assert snapshot.active_request is not None
    assert snapshot.active_request.status == "requested"
    assert snapshot.oauth_lease is None


def test_model_setup_never_renders_unexpected_coordinator_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from fabric_cli import main as main_mod

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    sentinel = "/private/captured-home?refresh_token=RAW-COORDINATOR-SECRET"

    def fail_coordinator(**_kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(
        "fabric_cli.provider_account_oauth.login_personal_provider",
        fail_coordinator,
    )
    monkeypatch.setattr(
        "fabric_cli.auth._prompt_model_selection",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("model picker must not run after failed login")
        ),
    )

    main_mod._model_flow_openai_codex({}, current_model="gpt-5.4")

    output = capsys.readouterr().out
    assert (
        "Login failed (invalid_state): Local operator repair or upgrade is required."
    ) in output
    assert sentinel not in output
    assert "RAW-COORDINATOR-SECRET" not in output
