"""CLI integration coverage for profile-scoped provider-account lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import threading
from pathlib import Path

import pytest

from fabric_cli.auth_commands import auth_command
from fabric_cli.subcommands.auth import build_auth_parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    build_auth_parser(subparsers, cmd_auth=auth_command)
    return parser


def _run(argv: list[str]):
    args = _parser().parse_args(argv)
    return args.func(args)


def _select_home(monkeypatch, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FABRIC_HOME", str(home))
    monkeypatch.setenv("FABRIC_HOME", str(home))


@pytest.fixture(autouse=True)
def _isolated_personal_oauth_release_recovery():
    from fabric_cli import provider_account_oauth

    provider_account_oauth._personal_oauth_release_recoveries.reset_for_tests()
    yield
    provider_account_oauth._personal_oauth_release_recoveries.reset_for_tests()


def _read_json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _codex_credentials() -> dict:
    return {
        "tokens": {
            "access_token": "codex-access-sentinel",
            "refresh_token": "codex-refresh-sentinel",
        },
        "base_url": "https://chatgpt.com/backend-api/codex",
        "last_refresh": "2026-07-11T12:00:00Z",
    }


def _xai_credentials() -> dict:
    return {
        "tokens": {
            "access_token": "xai-access-sentinel",
            "refresh_token": "xai-refresh-sentinel",
            "token_type": "Bearer",
        },
        "discovery": {"issuer": "https://accounts.x.ai"},
        "redirect_uri": "https://console.x.ai/device",
        "last_refresh": "2026-07-11T12:00:00Z",
    }


def test_auth_account_parser_exposes_closed_action_shapes(capsys):
    parser = _parser()
    parsed = parser.parse_args([
        "auth",
        "account",
        "openai-codex",
        "request",
        "--device-label",
        "front desk",
        "--expected-revision",
        "3",
        "--json",
    ])
    assert parsed.auth_action == "account"
    assert parsed.provider == "openai-codex"
    assert parsed.account_action == "request"
    assert parsed.device_label == "front desk"
    assert parsed.expected_revision == 3
    assert parsed.json is True

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([
            "auth",
            "account",
            "xai-oauth",
            "request",
            "--device-label",
            "lobby",
            "--request-id",
            "not-accepted-on-request",
        ])
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([
            "auth",
            "account",
            "openai-codex",
            "status",
            "--expected-revision",
            "0",
        ])
    assert exc_info.value.code == 2

    help_text = parser.format_help()
    assert "auth" in help_text
    assert "provider" not in capsys.readouterr().out


def test_auth_accounts_repair_parser_shape():
    parsed = _parser().parse_args(["auth", "accounts", "repair", "--yes", "--json"])
    assert parsed.auth_action == "accounts"
    assert parsed.store_action == "repair"
    assert parsed.yes is True
    assert parsed.json is True


def test_status_json_uses_safe_shared_view(tmp_path, monkeypatch, capsys):
    home = tmp_path / "default"
    _select_home(monkeypatch, home)

    _run(["auth", "account", "openai-codex", "status", "--json"])

    payload = _read_json_output(capsys)
    assert payload == {
        "created": None,
        "request": None,
        "snapshot": {
            "active_request": None,
            "active_request_id": None,
            "desired_ownership": "unselected",
            "handoff": None,
            "ownership_epoch": 0,
            "provider_id": "openai-codex",
            "pruned_terminal_count": 0,
            "requests": [],
            "revision": 0,
        },
    }
    assert not (home / "provider-accounts.json").exists()


def test_json_mutation_requires_explicit_revision(tmp_path, monkeypatch, capsys):
    _select_home(monkeypatch, tmp_path / "default")

    with pytest.raises(SystemExit) as exc_info:
        _run([
            "auth",
            "account",
            "openai-codex",
            "request",
            "--device-label",
            "front desk",
            "--json",
        ])

    assert exc_info.value.code == 2
    payload = _read_json_output(capsys)
    assert payload == {"error": {"code": "invalid_input", "retryable": False}}


def test_human_request_reads_revision_and_labels_request_local_only(
    tmp_path, monkeypatch, capsys
):
    _select_home(monkeypatch, tmp_path / "default")

    _run([
        "auth",
        "account",
        "openai-codex",
        "request",
        "--device-label",
        "front desk",
    ])

    output = capsys.readouterr().out
    assert "openai-codex: fabric managed" in output
    assert "mailto:" not in output
    assert "remote handoff: not configured" in output
    assert "request is local state only" in output
    assert "OAuth code" in output  # fixed warning text, never a code value


def test_human_mutation_retries_once_when_same_request_remains_applicable(
    tmp_path, monkeypatch, capsys
):
    from fabric_cli import provider_account_cli

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    _run([
        "auth",
        "account",
        "openai-codex",
        "request",
        "--device-label",
        "retry fabric",
    ])
    capsys.readouterr()

    real_handoff = provider_account_cli.accounts.record_handoff_attempt
    calls = 0

    def race_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            provider_account_cli.accounts.select_personal(
                home=kwargs["home"],
                provider_id=kwargs["provider_id"],
                expected_revision=kwargs["expected_revision"],
            )
        return real_handoff(**kwargs)

    monkeypatch.setattr(
        provider_account_cli.accounts, "record_handoff_attempt", race_once
    )
    _run([
        "auth",
        "account",
        "openai-codex",
        "handoff-attempted",
    ])

    output = capsys.readouterr().out
    assert calls == 2
    assert "launch attempted unverified" in output
    assert "remote handoff: not configured" in output


def test_json_lifecycle_and_stale_revision_are_exact(tmp_path, monkeypatch, capsys):
    _select_home(monkeypatch, tmp_path / "default")
    _run([
        "auth",
        "account",
        "xai-oauth",
        "request",
        "--device-label",
        "lab fabric",
        "--expected-revision",
        "0",
        "--json",
    ])
    created = _read_json_output(capsys)
    request_id = created["request"]["request_id"]
    assert created["created"] is True
    assert created["snapshot"]["desired_ownership"] == "fabric_managed"
    assert created["snapshot"]["handoff"] is None

    with pytest.raises(SystemExit) as exc_info:
        _run([
            "auth",
            "account",
            "xai-oauth",
            "handoff-attempted",
            "--request-id",
            request_id,
            "--expected-revision",
            "0",
            "--json",
        ])
    assert exc_info.value.code == 3
    assert _read_json_output(capsys) == {
        "error": {"code": "stale_revision", "retryable": True}
    }

    _run([
        "auth",
        "account",
        "xai-oauth",
        "handoff-attempted",
        "--request-id",
        request_id,
        "--expected-revision",
        "1",
        "--json",
    ])
    handed_off = _read_json_output(capsys)
    assert handed_off["request"]["handoff_state"] == ("launch_attempted_unverified")
    assert handed_off["request"]["status"] == "requested"

    _run([
        "auth",
        "account",
        "xai-oauth",
        "acknowledge",
        "--request-id",
        request_id,
        "--expected-revision",
        "2",
        "--json",
    ])
    acknowledged = _read_json_output(capsys)
    assert acknowledged["request"]["status"] == "awaiting"
    assert acknowledged["request"]["decision_source"] == "local_operator"

    _run([
        "auth",
        "account",
        "xai-oauth",
        "reject",
        "--request-id",
        request_id,
        "--expected-revision",
        "3",
        "--json",
    ])
    rejected = _read_json_output(capsys)
    assert rejected["request"]["status"] == "rejected"
    assert rejected["snapshot"]["active_request"] is None


def test_default_and_named_profile_requests_are_isolated(tmp_path, monkeypatch, capsys):
    default_home = tmp_path / "fabric"
    named_home = default_home / "profiles" / "sales"

    _select_home(monkeypatch, default_home)
    _run([
        "auth",
        "account",
        "openai-codex",
        "request",
        "--device-label",
        "default fabric",
        "--expected-revision",
        "0",
        "--json",
    ])
    default_payload = _read_json_output(capsys)

    _select_home(monkeypatch, named_home)
    _run([
        "auth",
        "account",
        "openai-codex",
        "request",
        "--device-label",
        "sales fabric",
        "--expected-revision",
        "0",
        "--json",
    ])
    named_payload = _read_json_output(capsys)

    assert (
        default_payload["request"]["request_id"]
        != (named_payload["request"]["request_id"])
    )
    assert default_payload["request"]["device_label"] == "default fabric"
    assert named_payload["request"]["device_label"] == "sales fabric"
    assert (default_home / "provider-accounts.json").exists()
    assert (named_home / "provider-accounts.json").exists()


def test_personal_codex_is_fenced_pool_only_and_json_redacted(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    _run([
        "auth",
        "account",
        "openai-codex",
        "personal",
        "--expected-revision",
        "0",
        "--json",
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["snapshot"]["desired_ownership"] == "personal"
    for forbidden in (
        "codex-access-sentinel",
        "codex-refresh-sentinel",
        "oauth_generation",
        "oauth_lease",
        "operation_id",
        "store_instance_id",
    ):
        assert forbidden not in encoded

    auth_store = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    assert "openai-codex" not in auth_store.get("providers", {})
    entries = auth_store["credential_pool"]["openai-codex"]
    assert len(entries) == 1
    assert entries[0]["source"] == "manual:device_code"
    assert entries[0]["access_token"] == "codex-access-sentinel"


def test_legacy_auth_add_codex_routes_through_personal_intent_without_singleton(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    _run(["auth", "add", "openai-codex", "--type", "oauth"])
    added_output = capsys.readouterr().out
    assert "Added openai-codex OAuth credential #1" in added_output

    _run(["auth", "account", "openai-codex", "status", "--json"])
    snapshot = _read_json_output(capsys)["snapshot"]
    assert snapshot["desired_ownership"] == "personal"
    auth_store = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    assert "openai-codex" not in auth_store.get("providers", {})
    assert [
        entry["source"] for entry in auth_store["credential_pool"]["openai-codex"]
    ] == ["manual:device_code"]


def test_personal_writer_is_pinned_to_explicit_captured_profile(tmp_path, monkeypatch):
    from fabric_cli.provider_account_oauth import login_personal_provider

    ambient_home = tmp_path / "ambient"
    captured_home = tmp_path / "captured"
    _select_home(monkeypatch, ambient_home)
    captured_home.mkdir(parents=True)
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    result = login_personal_provider(
        home=captured_home,
        provider_id="openai-codex",
        expected_revision=0,
    )

    assert result.snapshot.desired_ownership == "personal"
    assert (captured_home / "auth.json").exists()
    assert not (ambient_home / "auth.json").exists()
    captured = json.loads((captured_home / "auth.json").read_text(encoding="utf-8"))
    assert captured["credential_pool"]["openai-codex"][0]["access_token"] == (
        "codex-access-sentinel"
    )


def test_personal_oauth_failure_preserves_managed_request_and_redacts_exception(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    _run([
        "auth",
        "account",
        "xai-oauth",
        "request",
        "--device-label",
        "fallback fabric",
        "--expected-revision",
        "0",
        "--json",
    ])
    created = _read_json_output(capsys)
    request_id = created["request"]["request_id"]
    secret_exception = "provider-body-secret-sentinel"

    def fail_login(**_kwargs):
        raise RuntimeError(secret_exception)

    monkeypatch.setattr("fabric_cli.auth._xai_oauth_device_code_login", fail_login)
    with pytest.raises(SystemExit) as exc_info:
        _run([
            "auth",
            "account",
            "xai-oauth",
            "personal",
            "--expected-revision",
            "1",
            "--json",
        ])
    assert exc_info.value.code == 75
    failed = capsys.readouterr()
    assert json.loads(failed.out) == {
        "error": {"code": "io_unavailable", "retryable": True}
    }
    assert secret_exception not in failed.out
    assert secret_exception not in failed.err

    _run(["auth", "account", "xai-oauth", "status", "--json"])
    status = _read_json_output(capsys)["snapshot"]
    assert status["desired_ownership"] == "personal"
    assert status["active_request_id"] == request_id
    assert status["active_request"]["status"] == "requested"


def test_raw_ceremony_exception_context_is_not_reachable(tmp_path, monkeypatch):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli.provider_account_oauth import login_personal_provider

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    sentinel = "RAW-SECRET-SENTINEL"

    def fail_login(**_kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr("fabric_cli.auth._xai_oauth_device_code_login", fail_login)
    with pytest.raises(accounts.ProviderAccountError) as exc_info:
        login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )

    assert exc_info.value.code is accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
    assert exc_info.value.__context__ is None
    assert sentinel not in str(exc_info.value)
    snapshot = accounts.get_account_snapshot(home=home, provider_id="xai-oauth")
    assert snapshot.oauth_lease is None


@pytest.mark.parametrize(
    "release_code",
    [
        "lock_timeout",
        "io_unavailable",
        "commit_uncertain",
    ],
)
def test_direct_login_retries_transient_exact_lease_release(
    tmp_path,
    monkeypatch,
    release_code,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_accounts as accounts
    from fabric_cli.provider_account_oauth import login_personal_provider

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    real_release = accounts.release_oauth_lease
    release_calls = 0

    def transient_release(**kwargs):
        nonlocal release_calls
        release_calls += 1
        if release_calls == 1:
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode(release_code)
            )
        return real_release(**kwargs)

    monkeypatch.setattr(accounts, "release_oauth_lease", transient_release)
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )

    with pytest.raises(accounts.ProviderAccountError) as failed:
        login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )

    assert failed.value.code is accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
    assert release_calls == 2
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


def test_direct_login_proves_post_effect_uncertain_release(tmp_path, monkeypatch):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_accounts as accounts
    from fabric_cli.provider_account_oauth import login_personal_provider

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    real_release = accounts.release_oauth_lease
    release_calls = 0

    def post_effect_uncertain_release(**kwargs):
        nonlocal release_calls
        release_calls += 1
        if release_calls == 1:
            real_release(**kwargs)
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN
            )
        return real_release(**kwargs)

    monkeypatch.setattr(
        accounts,
        "release_oauth_lease",
        post_effect_uncertain_release,
    )
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )

    with pytest.raises(accounts.ProviderAccountError) as failed:
        login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )

    assert failed.value.code is accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
    assert release_calls == 2
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX profile rename ABA fixture")
def test_direct_login_preserves_exact_cleanup_handle_across_profile_replacement(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "profile"
    displaced = tmp_path / "profile-original"
    successor = tmp_path / "profile-successor"
    _select_home(monkeypatch, home)
    captured = {}

    def replace_then_fail(**_kwargs):
        home.rename(displaced)
        home.mkdir()
        successor_state = home / accounts.STATE_FILENAME
        successor_state.write_bytes(
            (displaced / accounts.STATE_FILENAME).read_bytes()
        )
        successor_state.chmod(0o600)
        captured["successor_before"] = successor_state.read_bytes()
        raise RuntimeError("provider failure must remain private")

    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        replace_then_fail,
    )

    with pytest.raises(accounts.ProviderAccountError) as failed:
        provider_account_oauth.login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )
    assert failed.value.code is accounts.ProviderAccountErrorCode.NOT_FOUND
    successor_state = home / accounts.STATE_FILENAME
    assert successor_state.read_bytes() == captured["successor_before"]
    assert not (home / accounts.LOCK_FILENAME).exists()

    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        lambda **_kwargs: _xai_credentials(),
    )
    with pytest.raises(accounts.ProviderAccountError) as still_replaced:
        provider_account_oauth.login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=None,
        )
    assert (
        still_replaced.value.code
        is accounts.ProviderAccountErrorCode.OAUTH_IN_PROGRESS
    )
    assert successor_state.read_bytes() == captured["successor_before"]

    home.rename(successor)
    displaced.rename(home)
    connected = provider_account_oauth.login_personal_provider(
        home=home,
        provider_id="xai-oauth",
        expected_revision=None,
    )
    assert connected.snapshot.oauth_lease is None
    assert connected.snapshot.oauth_completion is not None
    assert (successor / accounts.STATE_FILENAME).read_bytes() == captured[
        "successor_before"
    ]


def test_completion_uncertainty_is_recovered_before_next_direct_login(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "profile"
    _select_home(monkeypatch, home)
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        lambda **_kwargs: _xai_credentials(),
    )
    real_persist = accounts.persist_personal_oauth_completion

    def always_uncertain(**_kwargs):
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN
        )

    monkeypatch.setattr(
        accounts,
        "persist_personal_oauth_completion",
        always_uncertain,
    )
    with pytest.raises(accounts.ProviderAccountError) as uncertain:
        provider_account_oauth.login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )
    assert uncertain.value.code is accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        ).oauth_lease
        is not None
    )

    monkeypatch.setattr(
        accounts,
        "persist_personal_oauth_completion",
        real_persist,
    )
    connected = provider_account_oauth.login_personal_provider(
        home=home,
        provider_id="xai-oauth",
        expected_revision=None,
    )

    assert connected.snapshot.oauth_lease is None
    assert connected.snapshot.oauth_completion is not None


def test_direct_release_recovery_capacity_never_evicts_a_live_exact_handle(
    tmp_path,
):
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "profile"
    home.mkdir()
    started = accounts.capture_personal_oauth_start(
        home=home,
        provider_id="xai-oauth",
        expected_revision=0,
    )
    lease = accounts.acquire_oauth_lease(
        home=home,
        provider_id="xai-oauth",
        captured_intent=started.intent,
    )
    registry = provider_account_oauth._PersonalOAuthReleaseRecoveryRegistry(
        maximum=1
    )
    slot = registry.reserve()
    registry.retain(
        slot,
        home=home,
        provider_id="xai-oauth",
        started=started,
        lease_result=lease,
    )

    with pytest.raises(accounts.ProviderAccountError) as full:
        registry.reserve()
    assert full.value.code is accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        ).oauth_lease
        is not None
    )

    assert registry.retry_for(home=home, provider_id="xai-oauth") == 1
    retry_slot = registry.reserve()
    registry.finish(retry_slot)
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


@pytest.mark.parametrize("release_code", ["lock_timeout", "io_unavailable"])
def test_direct_login_surfaces_persistent_exact_release_failure(
    tmp_path,
    monkeypatch,
    release_code,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_accounts as accounts
    from fabric_cli.provider_account_oauth import login_personal_provider

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    release_calls = 0

    def unavailable_release(**_kwargs):
        nonlocal release_calls
        release_calls += 1
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode(release_code)
        )

    monkeypatch.setattr(accounts, "release_oauth_lease", unavailable_release)
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )

    with pytest.raises(accounts.ProviderAccountError) as failed:
        login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )

    assert failed.value.code is accounts.ProviderAccountErrorCode(release_code)
    assert failed.value.retryable is True
    assert release_calls == 2
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        ).oauth_lease
        is not None
    )

    with pytest.raises(accounts.ProviderAccountError) as blocked:
        login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=None,
        )
    assert blocked.value.code is accounts.ProviderAccountErrorCode.OAUTH_IN_PROGRESS


@pytest.mark.parametrize(
    ("failure_kind", "expected_exception"),
    [
        ("auth_error", "account_error"),
        ("runtime_error", "account_error"),
        ("keyboard_interrupt", "keyboard_interrupt"),
        ("system_exit", "system_exit"),
    ],
)
def test_failed_personal_login_preserves_suppression_and_releases_lease(
    tmp_path,
    monkeypatch,
    failure_kind,
    expected_exception,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    auth_mod.suppress_credential_source("xai-oauth", "device_code")
    clear_calls: list[str] = []

    def clear_spy(provider_id: str) -> None:
        clear_calls.append(provider_id)

    def fail_login(**_kwargs):
        if failure_kind == "auth_error":
            raise auth_mod.AuthError(
                "invalid provider payload",
                provider="xai-oauth",
                code="device_code_invalid",
            )
        if failure_kind == "runtime_error":
            raise RuntimeError("provider failure")
        if failure_kind == "keyboard_interrupt":
            raise KeyboardInterrupt
        raise SystemExit(130)

    monkeypatch.setattr(
        provider_account_oauth,
        "clear_provider_suppressions",
        clear_spy,
    )
    monkeypatch.setattr(auth_mod, "_xai_oauth_device_code_login", fail_login)

    if expected_exception == "account_error":
        with pytest.raises(accounts.ProviderAccountError) as exc_info:
            provider_account_oauth.login_personal_provider(
                home=home,
                provider_id="xai-oauth",
                expected_revision=0,
            )
        assert exc_info.value.code is accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
    elif expected_exception == "keyboard_interrupt":
        with pytest.raises(KeyboardInterrupt):
            provider_account_oauth.login_personal_provider(
                home=home,
                provider_id="xai-oauth",
                expected_revision=0,
            )
    else:
        with pytest.raises(SystemExit) as exc_info:
            provider_account_oauth.login_personal_provider(
                home=home,
                provider_id="xai-oauth",
                expected_revision=0,
            )
        assert exc_info.value.code == 130

    assert clear_calls == []
    assert auth_mod.is_source_suppressed("xai-oauth", "device_code")
    snapshot = accounts.get_account_snapshot(home=home, provider_id="xai-oauth")
    assert snapshot.oauth_lease is None


def test_verified_personal_login_clears_suppression_exactly_once(tmp_path, monkeypatch):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    auth_mod.suppress_credential_source("xai-oauth", "device_code")
    real_clear = provider_account_oauth.clear_provider_suppressions
    clear_calls: list[str] = []

    def clear_spy(provider_id: str) -> None:
        clear_calls.append(provider_id)
        real_clear(provider_id)

    monkeypatch.setattr(
        provider_account_oauth,
        "clear_provider_suppressions",
        clear_spy,
    )
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        lambda **_kwargs: _xai_credentials(),
    )
    real_write_state = provider_account_oauth.accounts._write_state
    state_writes = 0

    def fail_first_completion_publication(canonical_home, state):
        nonlocal state_writes
        state_writes += 1
        if state_writes == 3:
            raise provider_account_oauth.accounts.ProviderAccountError(
                provider_account_oauth.accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
            )
        return real_write_state(canonical_home, state)

    monkeypatch.setattr(
        provider_account_oauth.accounts,
        "_write_state",
        fail_first_completion_publication,
    )

    result = provider_account_oauth.login_personal_provider(
        home=home,
        provider_id="xai-oauth",
        expected_revision=0,
    )

    assert result.snapshot.oauth_completion is not None
    assert clear_calls == ["xai-oauth"]
    assert state_writes == 4
    assert not auth_mod.is_source_suppressed("xai-oauth", "device_code")


@pytest.mark.parametrize(
    ("signal_type", "exit_code"),
    [(RuntimeError, None), (KeyboardInterrupt, None), (SystemExit, 130)],
)
def test_provider_suppression_reengagement_is_atomic_on_persistence_failure(
    tmp_path,
    monkeypatch,
    signal_type,
    exit_code,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli.auth_reengagement import clear_provider_suppressions

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    auth_mod.suppress_credential_source("openai-codex", "device_code")
    auth_mod.suppress_credential_source("openai-codex", "environment")

    def interrupt_publication(_auth_store, target_path=None):
        del target_path
        if signal_type is RuntimeError:
            raise RuntimeError("suppression publication failed")
        if signal_type is KeyboardInterrupt:
            raise KeyboardInterrupt
        raise SystemExit(exit_code)

    monkeypatch.setattr(auth_mod, "_save_auth_store", interrupt_publication)
    with pytest.raises(signal_type) as interrupted:
        clear_provider_suppressions("openai-codex")

    if signal_type is SystemExit:
        assert interrupted.value.code == exit_code
    auth_store = auth_mod._load_auth_store()
    assert set(auth_store["suppressed_sources"]["openai-codex"]) == {
        "device_code",
        "environment",
    }


def test_suppression_persistence_failure_cannot_commit_verified_login(
    tmp_path,
    monkeypatch,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    auth_mod.suppress_credential_source("xai-oauth", "device_code")
    monkeypatch.setattr(
        auth_mod,
        "_xai_oauth_device_code_login",
        lambda **_kwargs: _xai_credentials(),
    )
    clear_calls: list[str] = []

    def fail_clear(provider_id):
        clear_calls.append(provider_id)
        raise RuntimeError("suppression publication failed")

    monkeypatch.setattr(
        provider_account_oauth,
        "clear_provider_suppressions",
        fail_clear,
    )

    with pytest.raises(accounts.ProviderAccountError) as failed:
        provider_account_oauth.login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )

    assert failed.value.code is accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
    snapshot = accounts.get_account_snapshot(home=home, provider_id="xai-oauth")
    assert snapshot.oauth_completion is None
    assert snapshot.oauth_lease is None
    assert clear_calls == ["xai-oauth"]
    assert auth_mod.is_source_suppressed("xai-oauth", "device_code")


def test_legacy_cancel_exit_130_is_preserved_and_releases_lease(tmp_path, monkeypatch):
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "default"
    _select_home(monkeypatch, home)

    def cancel_login():
        raise SystemExit(130)

    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", cancel_login)
    with pytest.raises(SystemExit) as exc_info:
        _run(["auth", "add", "openai-codex", "--type", "oauth"])

    assert exc_info.value.code == 130
    assert exc_info.value.__context__ is None
    snapshot = accounts.get_account_snapshot(home=home, provider_id="openai-codex")
    assert snapshot.oauth_lease is None


def test_ceremony_keyboard_interrupt_is_preserved_and_releases_lease(
    tmp_path, monkeypatch
):
    from fabric_cli import provider_accounts as accounts
    from fabric_cli.provider_account_oauth import login_personal_provider

    home = tmp_path / "default"
    _select_home(monkeypatch, home)

    def cancel_login(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("fabric_cli.auth._xai_oauth_device_code_login", cancel_login)
    with pytest.raises(KeyboardInterrupt) as exc_info:
        login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )

    assert exc_info.value.__context__ is None
    snapshot = accounts.get_account_snapshot(home=home, provider_id="xai-oauth")
    assert snapshot.oauth_lease is None


@pytest.mark.parametrize(
    ("ceremony_signal", "cleanup_signal"),
    [(KeyboardInterrupt(), SystemExit(99)), (SystemExit(130), KeyboardInterrupt())],
)
def test_direct_login_preserves_original_signal_when_cleanup_is_interrupted(
    tmp_path,
    monkeypatch,
    ceremony_signal,
    cleanup_signal,
):
    from fabric_cli import auth as auth_mod
    from fabric_cli import provider_accounts as accounts
    from fabric_cli.provider_account_oauth import login_personal_provider

    home = tmp_path / "default"
    _select_home(monkeypatch, home)

    def interrupt_ceremony(**_kwargs):
        raise ceremony_signal

    def interrupt_cleanup(**_kwargs):
        raise cleanup_signal

    monkeypatch.setattr(auth_mod, "_xai_oauth_device_code_login", interrupt_ceremony)
    monkeypatch.setattr(accounts, "release_oauth_lease", interrupt_cleanup)

    with pytest.raises(type(ceremony_signal)) as interrupted:
        login_personal_provider(
            home=home,
            provider_id="xai-oauth",
            expected_revision=0,
        )

    if isinstance(ceremony_signal, SystemExit):
        assert interrupted.value.code == 130
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="xai-oauth",
        ).oauth_lease
        is not None
    )


def test_suppression_cleanup_keyboard_interrupt_is_preserved_and_releases_lease(
    tmp_path, monkeypatch
):
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    def cancel_cleanup(_provider_id):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        provider_account_oauth,
        "clear_provider_suppressions",
        cancel_cleanup,
    )
    with pytest.raises(KeyboardInterrupt) as exc_info:
        provider_account_oauth.login_personal_provider(
            home=home,
            provider_id="openai-codex",
            expected_revision=0,
        )

    assert exc_info.value.__context__ is None
    snapshot = accounts.get_account_snapshot(home=home, provider_id="openai-codex")
    assert snapshot.oauth_lease is None


def test_completion_keyboard_interrupt_is_preserved_and_releases_lease(
    tmp_path, monkeypatch
):
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    def cancel_completion(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        provider_account_oauth.accounts,
        "persist_personal_oauth_completion",
        cancel_completion,
    )
    with pytest.raises(KeyboardInterrupt) as exc_info:
        provider_account_oauth.login_personal_provider(
            home=home,
            provider_id="openai-codex",
            expected_revision=0,
        )

    assert exc_info.value.__context__ is None
    snapshot = accounts.get_account_snapshot(home=home, provider_id="openai-codex")
    assert snapshot.oauth_lease is None


def test_verified_personal_oauth_supersedes_the_captured_managed_request(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    _run([
        "auth",
        "account",
        "openai-codex",
        "request",
        "--device-label",
        "personal switch fabric",
        "--expected-revision",
        "0",
        "--json",
    ])
    request_id = _read_json_output(capsys)["request"]["request_id"]
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    _run([
        "auth",
        "account",
        "openai-codex",
        "personal",
        "--expected-revision",
        "1",
        "--json",
    ])
    snapshot = _read_json_output(capsys)["snapshot"]
    assert snapshot["desired_ownership"] == "personal"
    assert snapshot["active_request"] is None
    terminal = next(
        request
        for request in snapshot["requests"]
        if request["request_id"] == request_id
    )
    assert terminal["status"] == "cancelled"
    assert terminal["decision_source"] == "verified_personal_oauth"
    assert terminal["decision_reason"] == "superseded_by_verified_personal"


@pytest.mark.parametrize("uncertain_position", ["before", "after"])
def test_completion_commit_uncertain_replays_same_operation_to_success(
    tmp_path, monkeypatch, uncertain_position
):
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)
    real_persist = accounts.persist_personal_oauth_completion
    calls = 0

    def uncertain_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            if uncertain_position == "after":
                real_persist(**kwargs)
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN
            )
        return real_persist(**kwargs)

    monkeypatch.setattr(
        provider_account_oauth.accounts,
        "persist_personal_oauth_completion",
        uncertain_once,
    )
    result = provider_account_oauth.login_personal_provider(
        home=home,
        provider_id="openai-codex",
        expected_revision=0,
    )

    assert result.snapshot.oauth_lease is None
    assert result.snapshot.oauth_completion is not None
    assert calls == 2
    auth_store = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    assert len(auth_store["credential_pool"]["openai-codex"]) == 1


@pytest.mark.parametrize("failure_position", ["before", "after"])
def test_pool_persist_failure_retries_without_duplicate_or_false_activation(
    tmp_path,
    monkeypatch,
    failure_position,
):
    from agent.credential_pool import CredentialPool
    from fabric_cli import provider_account_oauth

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)
    real_persist = CredentialPool._persist
    calls = 0

    def fail_once(self, *, removed_ids=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure_position == "after":
                real_persist(self, removed_ids=removed_ids)
            raise RuntimeError("simulated pool persistence interruption")
        return real_persist(self, removed_ids=removed_ids)

    monkeypatch.setattr(CredentialPool, "_persist", fail_once)

    result = provider_account_oauth.login_personal_provider(
        home=home,
        provider_id="openai-codex",
        expected_revision=0,
    )

    auth_store = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    assert result.snapshot.oauth_completion is not None
    assert len(auth_store["credential_pool"]["openai-codex"]) == 1
    assert auth_store["active_provider"] == "openai-codex"


@pytest.mark.parametrize("uncertain_position", ["before", "after"])
def test_acquire_commit_uncertain_never_strands_a_lease(
    tmp_path, monkeypatch, uncertain_position
):
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)
    real_acquire = accounts.acquire_oauth_lease
    calls = 0

    def uncertain_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            if uncertain_position == "after":
                real_acquire(**kwargs)
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN
            )
        return real_acquire(**kwargs)

    monkeypatch.setattr(
        provider_account_oauth.accounts, "acquire_oauth_lease", uncertain_once
    )
    result = provider_account_oauth.login_personal_provider(
        home=home,
        provider_id="openai-codex",
        expected_revision=0,
    )

    assert result.snapshot.oauth_lease is None
    assert result.snapshot.oauth_completion is not None
    assert calls == 2


def test_acquire_uncertain_retry_never_adopts_rival_same_intent_lease(
    tmp_path, monkeypatch
):
    from fabric_cli import provider_account_oauth
    from fabric_cli import provider_accounts as accounts

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    real_acquire = accounts.acquire_oauth_lease
    first_a_acquire = threading.Event()
    rival_acquired = threading.Event()
    a_retry_finished = threading.Event()
    a_calls = 0
    ceremonies: list[str] = []
    results: dict[str, object] = {}
    failures: dict[str, accounts.ProviderAccountError] = {}

    def fenced_acquire(**kwargs):
        nonlocal a_calls
        worker = threading.current_thread().name
        if worker == "worker-a":
            a_calls += 1
            if a_calls == 1:
                first_a_acquire.set()
                raise accounts.ProviderAccountError(
                    accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN
                )
            assert rival_acquired.wait(2)
            try:
                return real_acquire(**kwargs)
            finally:
                a_retry_finished.set()

        acquired = real_acquire(**kwargs)
        rival_acquired.set()
        return acquired

    def ceremony():
        worker = threading.current_thread().name
        ceremonies.append(worker)
        assert a_retry_finished.wait(2)
        return _codex_credentials()

    def login(worker: str) -> None:
        try:
            results[worker] = provider_account_oauth.login_personal_provider(
                home=home,
                provider_id="openai-codex",
                expected_revision=None,
            )
        except accounts.ProviderAccountError as exc:
            failures[worker] = exc

    monkeypatch.setattr(
        provider_account_oauth.accounts,
        "acquire_oauth_lease",
        fenced_acquire,
    )
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", ceremony)
    worker_a = threading.Thread(target=login, args=("worker-a",), name="worker-a")
    worker_b = threading.Thread(target=login, args=("worker-b",), name="worker-b")

    worker_a.start()
    assert first_a_acquire.wait(2)
    worker_b.start()
    worker_a.join(5)
    worker_b.join(5)

    assert not worker_a.is_alive()
    assert not worker_b.is_alive()
    assert ceremonies == ["worker-b"]
    assert failures["worker-a"].code is (
        accounts.ProviderAccountErrorCode.OAUTH_IN_PROGRESS
    )
    assert "worker-b" in results
    snapshot = accounts.get_account_snapshot(home=home, provider_id="openai-codex")
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_completion is not None


@pytest.mark.parametrize(
    "argv",
    [
        [
            "auth",
            "account",
            "openai-codex",
            "personal",
            "--expected-revision",
            "0",
            "--json",
        ],
        ["auth", "add", "openai-codex", "--type", "oauth"],
    ],
    ids=["account-personal", "legacy-auth-add"],
)
def test_named_profile_codex_fresh_login_does_not_copy_root_pool(
    tmp_path, monkeypatch, capsys, argv
):
    root = tmp_path / "fabric"
    named = root / "profiles" / "design"
    _select_home(monkeypatch, named)
    root.mkdir(parents=True, exist_ok=True)
    (root / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "providers": {},
            "credential_pool": {
                "openai-codex": [
                    {
                        "id": "global-codex",
                        "label": "global",
                        "auth_type": "oauth",
                        "priority": 0,
                        "source": "manual:device_code",
                        "access_token": "GLOBAL-ACCESS",
                        "refresh_token": "GLOBAL-REFRESH",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("fabric_cli.auth._codex_device_code_login", _codex_credentials)

    _run(argv)
    if "account" in argv:
        _read_json_output(capsys)
    else:
        assert "Added openai-codex OAuth credential #1" in capsys.readouterr().out

    profile_auth = json.loads((named / "auth.json").read_text(encoding="utf-8"))
    profile_entries = profile_auth["credential_pool"]["openai-codex"]
    assert [entry["access_token"] for entry in profile_entries] == [
        "codex-access-sentinel"
    ]
    root_auth = json.loads((root / "auth.json").read_text(encoding="utf-8"))
    assert root_auth["credential_pool"]["openai-codex"][0]["access_token"] == (
        "GLOBAL-ACCESS"
    )


@pytest.mark.parametrize(
    "argv",
    [
        [
            "auth",
            "account",
            "xai-oauth",
            "personal",
            "--expected-revision",
            "0",
            "--json",
        ],
        ["auth", "add", "xai-oauth", "--type", "oauth"],
    ],
    ids=["account-personal", "legacy-auth-add"],
)
def test_named_profile_fresh_xai_login_never_writes_global_fallback(
    tmp_path, monkeypatch, capsys, argv
):
    root = tmp_path / "fabric"
    named = root / "profiles" / "design"
    _select_home(monkeypatch, named)
    root.mkdir(parents=True, exist_ok=True)
    (root / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "providers": {
                "xai-oauth": {
                    "root_only_marker": "must-not-be-copied",
                    "tokens": {
                        "access_token": "root-access",
                        "refresh_token": "root-refresh",
                    },
                }
            },
            "credential_pool": {
                "xai-oauth": [
                    {
                        "id": "global-xai",
                        "label": "global",
                        "auth_type": "oauth",
                        "priority": 0,
                        "source": "manual:device_code",
                        "access_token": "GLOBAL-X",
                        "refresh_token": "GLOBAL-X-REFRESH",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fabric_cli.auth._xai_oauth_device_code_login",
        lambda **_kwargs: _xai_credentials(),
    )

    _run(argv)
    if "account" in argv:
        payload = _read_json_output(capsys)
    else:
        assert "Saved xai-oauth OAuth credentials" in capsys.readouterr().out
        _run(["auth", "account", "xai-oauth", "status", "--json"])
        payload = _read_json_output(capsys)
    assert payload["snapshot"]["desired_ownership"] == "personal"

    profile_auth = json.loads((named / "auth.json").read_text(encoding="utf-8"))
    root_auth = json.loads((root / "auth.json").read_text(encoding="utf-8"))
    assert (
        profile_auth["providers"]["xai-oauth"]["tokens"]
        == (_xai_credentials()["tokens"])
    )
    assert "root_only_marker" not in profile_auth["providers"]["xai-oauth"]
    assert [
        entry["access_token"] for entry in profile_auth["credential_pool"]["xai-oauth"]
    ] == ["xai-access-sentinel"]
    assert root_auth["providers"]["xai-oauth"]["tokens"] == {
        "access_token": "root-access",
        "refresh_token": "root-refresh",
    }
    assert root_auth["credential_pool"]["xai-oauth"][0]["access_token"] == ("GLOBAL-X")


def test_legacy_xai_failure_does_not_materialize_root_fallback_in_profile(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "fabric"
    named = root / "profiles" / "sales"
    _select_home(monkeypatch, named)
    root.mkdir(parents=True, exist_ok=True)
    (root / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "providers": {
                "xai-oauth": {
                    "tokens": {
                        "access_token": "ROOT-SINGLETON",
                        "refresh_token": "ROOT-SINGLETON-REFRESH",
                    }
                }
            },
            "credential_pool": {
                "xai-oauth": [
                    {
                        "id": "root-device",
                        "label": "root",
                        "auth_type": "oauth",
                        "priority": 0,
                        "source": "device_code",
                        "access_token": "ROOT-SINGLETON",
                        "refresh_token": "ROOT-SINGLETON-REFRESH",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )

    def fail_login(**_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("fabric_cli.auth._xai_oauth_device_code_login", fail_login)
    with pytest.raises(SystemExit) as exc_info:
        _run(["auth", "add", "xai-oauth", "--type", "oauth"])

    assert exc_info.value.code == 75
    capsys.readouterr()
    if (named / "auth.json").exists():
        profile_auth = json.loads((named / "auth.json").read_text(encoding="utf-8"))
        assert not profile_auth.get("credential_pool", {}).get("xai-oauth")
        assert "xai-oauth" not in profile_auth.get("providers", {})


def test_default_profile_fresh_xai_login_persists_normally(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "fabric"
    _select_home(monkeypatch, home)
    monkeypatch.setattr(
        "fabric_cli.auth._xai_oauth_device_code_login",
        lambda **_kwargs: _xai_credentials(),
    )

    _run([
        "auth",
        "account",
        "xai-oauth",
        "personal",
        "--expected-revision",
        "0",
        "--json",
    ])
    _read_json_output(capsys)

    auth_store = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    assert (
        auth_store["providers"]["xai-oauth"]["tokens"] == (_xai_credentials()["tokens"])
    )


def test_repair_requires_confirmation_then_resets_with_safe_json_result(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    _run([
        "auth",
        "account",
        "openai-codex",
        "request",
        "--device-label",
        "repair sentinel",
        "--expected-revision",
        "0",
        "--json",
    ])
    _read_json_output(capsys)
    before = (home / "provider-accounts.json").read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        _run(["auth", "accounts", "repair", "--json"])
    assert exc_info.value.code == 2
    assert _read_json_output(capsys) == {
        "error": {"code": "invalid_input", "retryable": False}
    }
    assert (home / "provider-accounts.json").read_bytes() == before

    _run(["auth", "accounts", "repair", "--yes", "--json"])

    assert _read_json_output(capsys) == {
        "repair": {
            "backup_created": True,
            "providers_reset": True,
            "schema_version": 1,
        }
    }
    replacement = json.loads(
        (home / "provider-accounts.json").read_text(encoding="utf-8")
    )
    assert replacement["providers"] == {}
    backups = list((home / ".provider-account-repair").iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == before


def test_repair_invalid_json_preserves_exact_bytes_without_rendering_them(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    state_path = home / "provider-accounts.json"
    raw = b"not-json repair-cli-secret-sentinel"
    state_path.write_bytes(raw)
    if os.name != "nt":
        state_path.chmod(0o600)

    _run(["auth", "accounts", "repair", "--yes", "--json"])

    output = capsys.readouterr().out
    assert json.loads(output) == {
        "repair": {
            "backup_created": True,
            "providers_reset": True,
            "schema_version": 1,
        }
    }
    assert "repair-cli-secret-sentinel" not in output
    assert str(home) not in output
    backups = list((home / ".provider-account-repair").iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw


def test_repair_refuses_newer_schema_with_stable_redacted_error(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    state_path = home / "provider-accounts.json"
    raw = b'{"schema_version":2,"providers":{},"secret":"sentinel"}\n'
    state_path.write_bytes(raw)
    if os.name != "nt":
        state_path.chmod(0o600)

    with pytest.raises(SystemExit) as exc_info:
        _run(["auth", "accounts", "repair", "--yes", "--json"])

    assert exc_info.value.code == 5
    output = capsys.readouterr().out
    assert json.loads(output) == {"error": {"code": "newer_schema", "retryable": False}}
    assert "sentinel" not in output
    assert str(home) not in output
    assert state_path.read_bytes() == raw
    assert not (home / ".provider-account-repair").exists()


def test_repair_unexpected_failure_is_redacted_without_exposing_cause(
    tmp_path, monkeypatch, capsys
):
    from fabric_cli import provider_account_cli

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    sentinel = "raw-path-token-repair-sentinel"

    def fail_repair(**_kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(
        provider_account_cli.accounts,
        "repair_account_store",
        fail_repair,
    )
    with pytest.raises(SystemExit) as exc_info:
        _run(["auth", "accounts", "repair", "--yes", "--json"])

    assert exc_info.value.code == 5
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "error": {"code": "invalid_state", "retryable": False}
    }
    assert sentinel not in output
    assert str(home) not in output


def test_interactive_repair_accepts_yes_and_cancel_preserves_state(
    tmp_path, monkeypatch, capsys
):
    from fabric_cli import provider_account_cli

    home = tmp_path / "default"
    _select_home(monkeypatch, home)
    monkeypatch.setattr(provider_account_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    _run(["auth", "accounts", "repair"])

    assert "cancelled; no state changed" in capsys.readouterr().out
    assert not (home / "provider-accounts.json").exists()

    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    _run(["auth", "accounts", "repair"])

    output = capsys.readouterr().out
    assert "every provider record was reset" in output
    assert "private backup preserved: no existing state file" in output
    assert (
        json.loads((home / "provider-accounts.json").read_text(encoding="utf-8"))[
            "providers"
        ]
        == {}
    )


def test_interactive_repair_confirmation_names_only_logical_profile(
    tmp_path, monkeypatch, capsys
):
    from fabric_cli import provider_account_cli

    home = tmp_path / "deployment-root" / "profiles" / "work"
    _select_home(monkeypatch, home)
    monkeypatch.setattr(provider_account_cli.sys.stdin, "isatty", lambda: True)
    prompts: list[str] = []

    def capture_prompt(prompt: str) -> str:
        prompts.append(prompt)
        return "no"

    monkeypatch.setattr("builtins.input", capture_prompt)

    _run(["auth", "accounts", "repair"])

    assert len(prompts) == 1
    assert "profile 'work'" in prompts[0]
    assert str(home) not in prompts[0]
    assert str(tmp_path) not in prompts[0]
    assert "cancelled; no state changed" in capsys.readouterr().out
