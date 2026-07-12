from __future__ import annotations

import errno
import inspect
import json
import multiprocessing
import os
import stat
import threading
import time
import traceback
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fabric_cli import provider_accounts as accounts


PROVIDER = "openai-codex"
OTHER_PROVIDER = "xai-oauth"
NOW = datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc)


def _fixed_now(monkeypatch: pytest.MonkeyPatch, value: datetime = NOW) -> None:
    monkeypatch.setattr(accounts, "_utc_now", lambda: value)


def _error_code(exc: pytest.ExceptionInfo[accounts.ProviderAccountError]) -> str:
    return exc.value.code.value


def _write_private_state_bytes(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        try:
            os.fchmod(fd, 0o600)
        except AttributeError:  # pragma: no cover - legacy Windows Python
            pass
        if os.name == "nt":  # pragma: no cover - native Windows CI
            assert accounts._windows_private_fd(fd, apply=True)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(raw)
    finally:
        if fd >= 0:
            os.close(fd)


def _make_private_repair_directory(path: Path) -> None:
    path.mkdir(mode=0o700)
    if os.name == "nt":  # pragma: no cover - native Windows CI
        assert accounts._windows_private_directory(path, apply=True)
    else:
        path.chmod(0o700)


def _child_hold_lock(home: str, ready, release) -> None:
    from pathlib import Path

    from fabric_cli.provider_accounts import provider_account_lock

    with provider_account_lock(Path(home), timeout_seconds=5):
        ready.set()
        release.wait(10)


def _child_acquire_then_commit_late(home: str, intent, allow_late, output) -> None:
    from pathlib import Path

    from fabric_cli.provider_accounts import (
        ProviderAccountError,
        acquire_oauth_lease,
        commit_current_oauth_generation,
    )

    result = acquire_oauth_lease(
        home=Path(home), provider_id="openai-codex", captured_intent=intent
    )
    output.put(("acquired", result.generation, result.lease.operation_id))
    if not allow_late.wait(10):
        output.put(("late", "coordination_timeout", []))
        return
    writes: list[str] = []
    try:
        commit_current_oauth_generation(
            home=Path(home),
            provider_id="openai-codex",
            generation=result.generation,
            operation_id=result.lease.operation_id,
            credential_writer=lambda operation_id: writes.append(operation_id),
            captured_intent=intent,
        )
    except ProviderAccountError as exc:
        output.put(("late", exc.code.value, writes))
    else:
        output.put(("late", "committed", writes))


def _child_takeover_and_commit(home: str, intent, output) -> None:
    from pathlib import Path

    from fabric_cli.provider_accounts import (
        ProviderAccountError,
        acquire_oauth_lease,
        commit_current_oauth_generation,
    )

    writes: list[str] = []
    try:
        takeover = acquire_oauth_lease(
            home=Path(home),
            provider_id="openai-codex",
            captured_intent=intent,
            takeover=True,
        )
        completed = commit_current_oauth_generation(
            home=Path(home),
            provider_id="openai-codex",
            generation=takeover.generation,
            operation_id=takeover.lease.operation_id,
            credential_writer=lambda operation_id: writes.append(operation_id),
            captured_intent=intent,
        )
    except ProviderAccountError as exc:
        output.put(("takeover", exc.code.value, None, writes))
    else:
        output.put((
            "takeover",
            "completed",
            takeover.generation,
            writes,
            completed.replayed,
        ))


def _fork_child_try_lock(home: str, output) -> None:
    from pathlib import Path

    from fabric_cli.provider_accounts import ProviderAccountError, provider_account_lock

    try:
        with provider_account_lock(Path(home), timeout_seconds=0.2):
            output.put("acquired")
    except ProviderAccountError as exc:
        output.put(exc.code.value)


def _fork_child_write_auth_store(
    home: str,
    attempted,
    acquired,
    output,
    credential_id: str,
) -> None:
    from pathlib import Path

    from fabric_cli import auth as auth_mod
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    token = set_fabric_home_override(Path(home))
    try:
        attempted.set()
        with auth_mod._auth_store_lock(timeout_seconds=5):
            acquired.set()
            auth_mod.write_credential_pool(
                "openai-codex",
                [
                    {
                        "id": credential_id,
                        "label": "Fork child",
                        "auth_type": "oauth",
                        "priority": 1,
                        "source": "manual:device_code",
                        "access_token": f"{credential_id}-token",
                    }
                ],
            )
        output.put(("written", credential_id))
    except BaseException as exc:  # pragma: no cover - asserted by parent
        output.put(("error", type(exc).__name__))
    finally:
        reset_fabric_home_override(token)


def test_empty_snapshot_is_profile_local_and_does_not_infer_connection(
    tmp_path: Path,
) -> None:
    first_home = tmp_path / "one"
    second_home = tmp_path / "two"
    first_home.mkdir()
    second_home.mkdir()
    first = accounts.get_account_snapshot(home=first_home, provider_id=PROVIDER)
    second = accounts.get_account_snapshot(home=second_home, provider_id=PROVIDER)

    assert first == second
    assert first.revision == 0
    assert first.ownership_epoch == 0
    assert first.oauth_generation == 0
    assert first.oauth_lease is None
    assert first.desired_ownership == "unselected"
    assert first.active_request is None
    assert not (tmp_path / "one" / accounts.STATE_FILENAME).exists()


def test_missing_home_is_rejected_without_creation(tmp_path: Path) -> None:
    missing = tmp_path / "profiles" / "missing"
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=missing, provider_id=PROVIDER)
    assert _error_code(exc) == "invalid_input"
    assert not missing.exists()


def test_create_request_writes_exact_private_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    monkeypatch.setattr(accounts, "_new_request_id", lambda: "par_" + "ab" * 12)
    monkeypatch.setattr(accounts, "_new_store_instance_id", lambda: "pas_" + "cd" * 16)

    result = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label=" front   desk ",
        expected_revision=0,
    )

    assert result.created is True
    assert result.request.request_id == "par_" + "ab" * 12
    assert result.request.device_label == "front desk"
    assert result.snapshot.desired_ownership == "fabric_managed"
    assert result.snapshot.revision == 1
    assert result.snapshot.ownership_epoch == 1
    state_path = tmp_path / accounts.STATE_FILENAME
    state = {
        "schema_version": 1,
        "store_instance_id": "pas_" + "cd" * 16,
        "providers": {
            PROVIDER: {
                "revision": 1,
                "ownership_epoch": 1,
                "oauth_generation": 0,
                "oauth_lease": None,
                "oauth_completion": None,
                "desired_ownership": "fabric_managed",
                "active_request_id": "par_" + "ab" * 12,
                "pruned_terminal_count": 0,
                "requests": [
                    {
                        "request_id": "par_" + "ab" * 12,
                        "provider_id": PROVIDER,
                        "status": "requested",
                        "handoff_state": "offered",
                        "device_label": "front desk",
                        "requested_at": "2026-07-11T18:00:00Z",
                        "updated_at": "2026-07-11T18:00:00Z",
                        "expires_at": "2026-07-18T18:00:00Z",
                        "notification_policy_key": accounts.NOTIFICATION_POLICY_KEY,
                    }
                ],
            }
        },
    }
    expected = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert state_path.read_text(encoding="utf-8") == expected
    if os.name != "nt":
        assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / accounts.LOCK_FILENAME).stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_existing_state_with_non_private_mode_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    state_path = tmp_path / accounts.STATE_FILENAME
    state_path.chmod(0o644)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)

    assert _error_code(exc) == "invalid_state"


@pytest.mark.parametrize("provider_id", ["openai", "chatgpt", "grok", "xai"])
def test_only_two_canonical_providers_are_allowed(
    tmp_path: Path, provider_id: str
) -> None:
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=provider_id)
    assert _error_code(exc) == "invalid_provider"
    assert str(exc.value) == "invalid_provider"
    assert str(tmp_path) not in str(exc.value)


def test_managed_retry_precedes_stale_revision_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )

    retry = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )

    assert retry.created is False
    assert retry.request == created.request
    assert retry.snapshot.revision == 1
    assert len(retry.snapshot.requests) == 1


def test_active_personal_request_requires_revision_and_reuses_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    managed = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    personal = accounts.select_personal(
        home=tmp_path, provider_id=PROVIDER, expected_revision=managed.snapshot.revision
    )
    assert personal.snapshot.desired_ownership == "personal"
    assert personal.snapshot.ownership_epoch == 2

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.create_managed_request(
            home=tmp_path,
            provider_id=PROVIDER,
            device_label="ignored replacement",
            expected_revision=1,
        )
    assert _error_code(exc) == "stale_revision"

    restored = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="ignored replacement",
        expected_revision=personal.snapshot.revision,
    )
    assert restored.created is False
    assert restored.request.request_id == managed.request.request_id
    assert restored.request.device_label == "Fabric A"
    assert restored.snapshot.desired_ownership == "fabric_managed"
    assert restored.snapshot.ownership_epoch == 3
    assert restored.snapshot.revision == 3


def test_provider_revisions_are_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    first = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="One",
        expected_revision=0,
    )
    second = accounts.create_managed_request(
        home=tmp_path,
        provider_id=OTHER_PROVIDER,
        device_label="Two",
        expected_revision=0,
    )

    assert first.snapshot.revision == second.snapshot.revision == 1
    assert (
        accounts.get_account_snapshot(
            home=tmp_path, provider_id=PROVIDER
        ).active_request_id
        == first.request.request_id
    )
    assert (
        accounts.get_account_snapshot(
            home=tmp_path, provider_id=OTHER_PROVIDER
        ).active_request_id
        == second.request.request_id
    )


def test_handoff_attempt_is_orthogonal_to_request_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    _fixed_now(monkeypatch, NOW + timedelta(minutes=1))

    attempted = accounts.record_handoff_attempt(
        home=tmp_path,
        provider_id=PROVIDER,
        request_id=created.request.request_id,
        expected_revision=1,
    )

    assert attempted.request is not None
    assert attempted.request.status == "requested"
    assert attempted.request.handoff_state == "launch_attempted_unverified"
    assert attempted.request.notification_handoff_at == "2026-07-11T18:01:00Z"
    assert attempted.snapshot.active_request_id == created.request.request_id


def test_acknowledge_then_cancel_preserves_terminal_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    _fixed_now(monkeypatch, NOW + timedelta(minutes=1))
    acknowledged = accounts.record_admin_acknowledgement(
        home=tmp_path,
        provider_id=PROVIDER,
        request_id=created.request.request_id,
        expected_revision=1,
        source="local_operator",
    )
    assert acknowledged.request is not None
    assert acknowledged.request.status == "awaiting"
    assert acknowledged.request.decision_source == "local_operator"

    _fixed_now(monkeypatch, NOW + timedelta(minutes=2))
    cancelled = accounts.transition_request(
        home=tmp_path,
        provider_id=PROVIDER,
        request_id=created.request.request_id,
        target="cancelled",
        expected_revision=2,
        source="fabric_control_plane",
    )
    assert cancelled.request is not None
    assert cancelled.request.status == "cancelled"
    assert cancelled.request.decision_source == "fabric_control_plane"
    assert cancelled.snapshot.active_request is None

    before = (tmp_path / accounts.STATE_FILENAME).read_bytes()
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.record_admin_acknowledgement(
            home=tmp_path,
            provider_id=PROVIDER,
            request_id=created.request.request_id,
            expected_revision=3,
            source="local_operator",
        )
    assert _error_code(exc) == "not_found"
    assert (tmp_path / accounts.STATE_FILENAME).read_bytes() == before


def test_awaiting_request_can_record_first_handoff_after_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    _fixed_now(monkeypatch, NOW + timedelta(minutes=1))
    acknowledged = accounts.record_admin_acknowledgement(
        home=tmp_path,
        provider_id=PROVIDER,
        request_id=created.request.request_id,
        expected_revision=created.snapshot.revision,
        source="local_operator",
    )
    _fixed_now(monkeypatch, NOW + timedelta(minutes=2))
    attempted = accounts.record_handoff_attempt(
        home=tmp_path,
        provider_id=PROVIDER,
        request_id=created.request.request_id,
        expected_revision=acknowledged.snapshot.revision,
    )
    assert attempted.request is not None
    assert attempted.request.status == "awaiting"
    assert attempted.request.decision_at == "2026-07-11T18:01:00Z"
    assert attempted.request.updated_at == "2026-07-11T18:02:00Z"


def test_lazy_expiry_is_durable_and_uses_system_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    _fixed_now(monkeypatch, NOW + accounts.REQUEST_TTL + timedelta(seconds=1))

    expired = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)

    assert expired.revision == 2
    assert expired.active_request is None
    assert expired.requests[0].status == "expired"
    assert expired.requests[0].decision_source == "system_expiry"
    assert expired.requests[0].decision_at == created.request.expires_at
    reloaded = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert reloaded == expired


def test_terminal_history_is_bounded_and_pruning_is_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    revision = 0
    first_id = None
    for index in range(accounts.MAX_TERMINAL_HISTORY + 1):
        monkeypatch.setattr(
            accounts, "_new_request_id", lambda i=index: f"par_{i:024x}"
        )
        created = accounts.create_managed_request(
            home=tmp_path,
            provider_id=PROVIDER,
            device_label=f"Fabric {index}",
            expected_revision=revision,
        )
        if first_id is None:
            first_id = created.request.request_id
        revision = created.snapshot.revision
        terminal = accounts.transition_request(
            home=tmp_path,
            provider_id=PROVIDER,
            request_id=created.request.request_id,
            target="cancelled",
            expected_revision=revision,
            source="local_operator",
        )
        revision = terminal.snapshot.revision

    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert len(snapshot.requests) == accounts.MAX_TERMINAL_HISTORY
    assert snapshot.pruned_terminal_count == 1
    assert all(request.status == "cancelled" for request in snapshot.requests)
    assert first_id not in {request.request_id for request in snapshot.requests}


@pytest.mark.parametrize(
    "bad_label",
    [
        "line one\nline two",
        "line one\rline two",
        "hidden\u0000value",
        "zero\u200bwidth",
        "right\u202eto-left",
        "   ",
    ],
)
def test_device_label_rejects_controls_and_bidi(bad_label: str) -> None:
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.normalize_device_label(bad_label)
    assert _error_code(exc) == "invalid_input"


def test_device_label_nfkc_whitespace_unicode_and_utf8_byte_bound() -> None:
    assert (
        accounts.normalize_device_label("  Ｆａｂｒｉｃ\u2003東京  ") == "Fabric 東京"
    )
    assert accounts.normalize_device_label("Cafe\u0301") == "Café"
    assert accounts.normalize_device_label("🙂" * 30) == "🙂" * 30
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.normalize_device_label("🙂" * 31)
    assert _error_code(exc) == "invalid_input"


def test_corrupt_unknown_and_newer_state_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / accounts.STATE_FILENAME
    _write_private_state_bytes(path, b"not-json secret=sentinel")
    original = path.read_bytes()
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(exc) == "invalid_state"
    assert path.read_bytes() == original
    assert "sentinel" not in str(exc.value)

    _write_private_state_bytes(path, b'{"schema_version": 2, "providers": {}}\n')
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(exc) == "newer_schema"

    _write_private_state_bytes(
        path,
        b'{"schema_version": 1, "providers": {}, "access_token": "sentinel"}\n',
    )
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(exc) == "invalid_state"
    assert "sentinel" not in str(exc.value)


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json secret=repair-sentinel",
        b'{"schema_version":1,"providers":{},"access_token":"repair-sentinel"}',
        b'{"schema_version":1,"schema_version":1,"providers":{}}',
    ],
)
def test_repair_preserves_exact_private_backup_and_resets_malformed_store(
    tmp_path: Path, raw: bytes
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    _write_private_state_bytes(state_path, raw)

    result = accounts.repair_account_store(home=tmp_path)

    assert result == accounts.RepairResult(schema_version=1, backup_created=True)
    repair_dir = tmp_path / accounts.REPAIR_DIRNAME
    backups = list(repair_dir.iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    replacement = json.loads(state_path.read_text(encoding="utf-8"))
    assert replacement == {
        "providers": {},
        "schema_version": 1,
        "store_instance_id": replacement["store_instance_id"],
    }
    assert replacement["store_instance_id"].startswith("pas_")
    assert "repair-sentinel" not in repr(result)
    assert str(tmp_path) not in repr(result)
    if os.name != "nt":
        assert stat.S_IMODE(repair_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
        assert stat.S_IMODE(state_path.stat().st_mode) == 0o600


def test_repair_valid_store_rotates_incarnation_and_clears_all_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Repair A",
        expected_revision=0,
    )
    accounts.create_managed_request(
        home=tmp_path,
        provider_id=OTHER_PROVIDER,
        device_label="Repair B",
        expected_revision=0,
    )
    state_path = tmp_path / accounts.STATE_FILENAME
    before = state_path.read_bytes()
    prior_instance = json.loads(before)["store_instance_id"]

    result = accounts.repair_account_store(home=tmp_path)

    replacement = json.loads(state_path.read_text(encoding="utf-8"))
    assert result.backup_created is True
    assert replacement["providers"] == {}
    assert replacement["store_instance_id"] != prior_instance
    backups = list((tmp_path / accounts.REPAIR_DIRNAME).iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == before


def test_repair_missing_store_creates_empty_store_without_backup(
    tmp_path: Path,
) -> None:
    result = accounts.repair_account_store(home=tmp_path)

    assert result == accounts.RepairResult(schema_version=1, backup_created=False)
    replacement = json.loads(
        (tmp_path / accounts.STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert replacement["providers"] == {}
    assert not (tmp_path / accounts.REPAIR_DIRNAME).exists()


def test_repair_missing_store_never_overwrites_concurrent_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    concurrent = b"invalid-json concurrent-missing-repair-sentinel"
    real_publish = accounts._publish_repair_replacement

    def create_then_publish(home: Path, temporary_path: Path) -> None:
        _write_private_state_bytes(state_path, concurrent)
        real_publish(home, temporary_path)

    monkeypatch.setattr(accounts, "_publish_repair_replacement", create_then_publish)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "io_unavailable"
    assert state_path.read_bytes() == concurrent
    assert not (tmp_path / accounts.REPAIR_DIRNAME).exists()
    assert "repair-sentinel" not in str(exc.value)


def test_repair_never_overwrites_newer_schema(tmp_path: Path) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b'{"schema_version":2,"providers":{},"future":"sentinel"}\n'
    _write_private_state_bytes(state_path, raw)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "newer_schema"
    assert state_path.read_bytes() == raw
    assert not (tmp_path / accounts.REPAIR_DIRNAME).exists()
    assert "sentinel" not in str(exc.value)


def test_repair_oversized_source_is_unchanged_without_backup_or_reset(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = (
        b'{"schema_version":2,"padding":"' + (b"x" * accounts.MAX_STATE_BYTES) + b'"}\n'
    )
    assert len(raw) > accounts.MAX_STATE_BYTES
    _write_private_state_bytes(state_path, raw)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "invalid_state"
    assert state_path.read_bytes() == raw
    assert not (tmp_path / accounts.REPAIR_DIRNAME).exists()


def test_repair_stage_failure_restores_exact_source_without_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json repair-write-sentinel"
    _write_private_state_bytes(state_path, raw)

    def fail_stage(_home: Path, _state: dict[str, object]) -> Path:
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
        )

    monkeypatch.setattr(accounts, "_stage_repair_replacement", fail_stage)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "io_unavailable"
    assert state_path.read_bytes() == raw
    backups = list((tmp_path / accounts.REPAIR_DIRNAME).iterdir())
    assert backups == []
    assert "repair-write-sentinel" not in str(exc.value)


@pytest.mark.parametrize(
    ("post_effect_failure", "expected_exception"),
    [
        (OSError(errno.EIO, "commit-then-oserror"), accounts.ProviderAccountError),
        (KeyboardInterrupt(), KeyboardInterrupt),
    ],
    ids=("oserror", "keyboard-interrupt"),
)
def test_repair_claim_post_effect_failure_restores_without_deleting_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post_effect_failure: BaseException,
    expected_exception: type[BaseException],
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json claim-post-effect-sentinel"
    _write_private_state_bytes(state_path, raw)
    real_replace = accounts._atomic_replace_entry

    def replace_then_fail(*args, **kwargs) -> None:
        real_replace(*args, **kwargs)
        raise post_effect_failure

    monkeypatch.setattr(accounts, "_atomic_replace_entry", replace_then_fail)

    with pytest.raises(expected_exception) as exc:
        accounts.repair_account_store(home=tmp_path)

    if isinstance(exc.value, accounts.ProviderAccountError):
        assert exc.value.code is accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
    assert state_path.read_bytes() == raw
    assert state_path.stat().st_nlink == 1
    assert list((tmp_path / accounts.REPAIR_DIRNAME).iterdir()) == []

    # Prove the recovered state is not merely present but remains repairable.
    monkeypatch.setattr(accounts, "_atomic_replace_entry", real_replace)
    result = accounts.repair_account_store(home=tmp_path)
    assert result.backup_created is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["providers"] == {}


def test_repair_backup_directory_fsync_failure_never_resets_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json repair-fsync-sentinel"
    _write_private_state_bytes(state_path, raw)
    repair_dir = tmp_path / accounts.REPAIR_DIRNAME
    _make_private_repair_directory(repair_dir)
    real_fsync_directory = accounts._fsync_directory
    failed = False

    def fail_repair_directory(directory: Path) -> None:
        nonlocal failed
        if directory == repair_dir and not failed:
            failed = True
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
            )
        real_fsync_directory(directory)

    monkeypatch.setattr(accounts, "_fsync_directory", fail_repair_directory)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "io_unavailable"
    assert failed is True
    assert state_path.read_bytes() == raw
    backups = list(repair_dir.iterdir())
    assert backups == []


def test_repair_post_replace_fsync_failure_is_commit_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json repair-uncertain-sentinel"
    _write_private_state_bytes(state_path, raw)
    repair_dir = tmp_path / accounts.REPAIR_DIRNAME
    _make_private_repair_directory(repair_dir)
    real_fsync_directory = accounts._fsync_directory
    home_syncs = 0

    def fail_home_directory(directory: Path) -> None:
        nonlocal home_syncs
        if directory == tmp_path:
            home_syncs += 1
        if directory == tmp_path and home_syncs == 3:
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
            )
        real_fsync_directory(directory)

    monkeypatch.setattr(accounts, "_fsync_directory", fail_home_directory)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "commit_uncertain"
    assert exc.value.retryable is False
    assert json.loads(state_path.read_text(encoding="utf-8"))["providers"] == {}
    backups = list(repair_dir.iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    assert "repair-uncertain-sentinel" not in str(exc.value)


@pytest.mark.parametrize(
    "post_effect_failure",
    [
        OSError(errno.EIO, "publish-commit-then-oserror"),
        KeyboardInterrupt(),
    ],
    ids=("oserror", "keyboard-interrupt"),
)
def test_repair_publish_post_effect_failure_is_commit_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post_effect_failure: BaseException,
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json publish-post-effect-sentinel"
    _write_private_state_bytes(state_path, raw)
    real_move = accounts._atomic_move_noreplace

    def move_then_fail(*args, **kwargs) -> None:
        real_move(*args, **kwargs)
        raise post_effect_failure

    monkeypatch.setattr(accounts, "_atomic_move_noreplace", move_then_fail)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "commit_uncertain"
    assert exc.value.retryable is False
    assert json.loads(state_path.read_text(encoding="utf-8"))["providers"] == {}
    assert state_path.stat().st_nlink == 1
    backups = list((tmp_path / accounts.REPAIR_DIRNAME).iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    assert not list(tmp_path.glob(f".{accounts.STATE_FILENAME}.tmp.*"))
    assert "post-effect-sentinel" not in str(exc.value)


def test_repair_atomic_publish_survives_every_temp_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json repair-cleanup-uncertain-sentinel"
    _write_private_state_bytes(state_path, raw)
    unlink_attempts = 0

    def fail_every_unlink(*_args, **_kwargs) -> None:
        nonlocal unlink_attempts
        unlink_attempts += 1
        raise OSError(errno.EIO, "all cleanup unavailable")

    monkeypatch.setattr(
        accounts,
        "_unlink_pinned_entry",
        fail_every_unlink,
    )

    result = accounts.repair_account_store(home=tmp_path)

    assert result.backup_created is True
    assert unlink_attempts == 0
    assert json.loads(state_path.read_text(encoding="utf-8"))["providers"] == {}
    assert state_path.stat().st_nlink == 1
    backups = list((tmp_path / accounts.REPAIR_DIRNAME).iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    assert not list(tmp_path.glob(f".{accounts.STATE_FILENAME}.tmp.*"))


def test_repair_restore_post_effect_failure_remains_readable_and_repairable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json restore-post-effect-sentinel"
    _write_private_state_bytes(state_path, raw)
    real_stage = accounts._stage_repair_replacement
    real_move = accounts._atomic_move_noreplace

    def fail_stage(_home: Path, _state: dict[str, object]) -> Path:
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
        )

    def restore_then_fail(
        source: Path,
        target: Path,
        **kwargs,
    ) -> None:
        real_move(source, target, **kwargs)
        if source.parent.name == accounts.REPAIR_DIRNAME:
            raise OSError(errno.EIO, "restore committed before error")

    monkeypatch.setattr(accounts, "_stage_repair_replacement", fail_stage)
    monkeypatch.setattr(accounts, "_atomic_move_noreplace", restore_then_fail)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "io_unavailable"
    assert state_path.read_bytes() == raw
    assert state_path.stat().st_nlink == 1
    assert list((tmp_path / accounts.REPAIR_DIRNAME).iterdir()) == []

    monkeypatch.setattr(accounts, "_stage_repair_replacement", real_stage)
    monkeypatch.setattr(accounts, "_atomic_move_noreplace", real_move)
    result = accounts.repair_account_store(home=tmp_path)
    assert result.backup_created is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["providers"] == {}


def test_repair_claim_backs_up_the_exact_latest_source_before_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json original-repair-sentinel"
    changed = b"invalid-json changed-repair-sentinel"
    _write_private_state_bytes(state_path, raw)
    real_claim = accounts._claim_repair_source

    def change_then_claim(
        home: Path,
        repair_path: Path,
        pinned_repair: accounts._PinnedHome,
    ) -> Path:
        _write_private_state_bytes(state_path, changed)
        return real_claim(home, repair_path, pinned_repair)

    monkeypatch.setattr(accounts, "_claim_repair_source", change_then_claim)
    result = accounts.repair_account_store(home=tmp_path)

    assert result.backup_created is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["providers"] == {}
    backups = list((tmp_path / accounts.REPAIR_DIRNAME).iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == changed


def test_repair_claim_restores_racing_newer_schema_without_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    initial = b"invalid-json initial-repair-sentinel"
    newer = b'{"schema_version":2,"providers":{},"future":"racing-sentinel"}\n'
    _write_private_state_bytes(state_path, initial)
    real_claim = accounts._claim_repair_source

    def replace_with_newer_then_claim(
        home: Path,
        repair_path: Path,
        pinned_repair: accounts._PinnedHome,
    ) -> Path:
        _write_private_state_bytes(state_path, newer)
        return real_claim(home, repair_path, pinned_repair)

    monkeypatch.setattr(
        accounts,
        "_claim_repair_source",
        replace_with_newer_then_claim,
    )

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "newer_schema"
    assert state_path.read_bytes() == newer
    assert list((tmp_path / accounts.REPAIR_DIRNAME).iterdir()) == []
    assert "racing-sentinel" not in str(exc.value)


def test_repair_never_erases_source_recreated_after_atomic_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / accounts.STATE_FILENAME
    raw = b"invalid-json original-repair-sentinel"
    concurrent = b"invalid-json concurrent-repair-sentinel"
    _write_private_state_bytes(state_path, raw)
    real_publish = accounts._publish_repair_replacement

    def recreate_then_publish(home: Path, temporary_path: Path) -> None:
        _write_private_state_bytes(state_path, concurrent)
        real_publish(home, temporary_path)

    monkeypatch.setattr(
        accounts,
        "_publish_repair_replacement",
        recreate_then_publish,
    )
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)

    assert _error_code(exc) == "io_unavailable"
    assert state_path.read_bytes() == concurrent
    backups = list((tmp_path / accounts.REPAIR_DIRNAME).iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    assert "repair-sentinel" not in str(exc.value)


def test_repair_reentry_and_credential_writer_reentry_fail_closed(
    tmp_path: Path,
) -> None:
    accounts._repair_state.active = True
    try:
        with pytest.raises(accounts.ProviderAccountError) as exc:
            accounts.repair_account_store(home=tmp_path)
        assert _error_code(exc) == "invalid_state"
    finally:
        accounts._repair_state.active = False

    accounts._credential_writer_state.active = True
    try:
        with pytest.raises(accounts.ProviderAccountError) as exc:
            accounts.repair_account_store(home=tmp_path)
        assert _error_code(exc) == "oauth_in_progress"
    finally:
        accounts._credential_writer_state.active = False
    assert not (tmp_path / accounts.STATE_FILENAME).exists()


def test_repair_isolated_to_explicit_named_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    default_home = tmp_path / "fabric"
    named_home = default_home / "profiles" / "work"
    default_home.mkdir()
    named_home.mkdir(parents=True)
    accounts.create_managed_request(
        home=default_home,
        provider_id=PROVIDER,
        device_label="Default",
        expected_revision=0,
    )
    accounts.create_managed_request(
        home=named_home,
        provider_id=PROVIDER,
        device_label="Work",
        expected_revision=0,
    )
    default_before = (default_home / accounts.STATE_FILENAME).read_bytes()
    named_before = (named_home / accounts.STATE_FILENAME).read_bytes()

    accounts.repair_account_store(home=named_home)

    assert (default_home / accounts.STATE_FILENAME).read_bytes() == default_before
    assert (
        json.loads((named_home / accounts.STATE_FILENAME).read_text(encoding="utf-8"))[
            "providers"
        ]
        == {}
    )
    assert list((named_home / accounts.REPAIR_DIRNAME).iterdir())[0].read_bytes() == (
        named_before
    )
    assert not (default_home / accounts.REPAIR_DIRNAME).exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows pins deny profile rename")
def test_repair_backup_and_store_stay_in_same_pinned_profile_after_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = tmp_path / "profile"
    moved_home = tmp_path / "profile-moved"
    profile_home.mkdir()
    state_path = profile_home / accounts.STATE_FILENAME
    raw = b"invalid-json pinned-profile-repair-sentinel"
    _write_private_state_bytes(state_path, raw)
    real_validate = accounts._validate_private_repair_directory
    validation_count = 0

    def validate_then_replace_profile(path: Path, *, created: bool) -> None:
        nonlocal validation_count
        real_validate(path, created=created)
        validation_count += 1
        if validation_count == 1:
            profile_home.rename(moved_home)
            profile_home.mkdir()
            _make_private_repair_directory(profile_home / accounts.REPAIR_DIRNAME)

    monkeypatch.setattr(
        accounts,
        "_validate_private_repair_directory",
        validate_then_replace_profile,
    )

    result = accounts.repair_account_store(home=profile_home)

    assert result.backup_created is True
    moved_state = moved_home / accounts.STATE_FILENAME
    assert json.loads(moved_state.read_text(encoding="utf-8"))["providers"] == {}
    moved_backups = list((moved_home / accounts.REPAIR_DIRNAME).iterdir())
    assert len(moved_backups) == 1
    assert moved_backups[0].read_bytes() == raw
    assert list((profile_home / accounts.REPAIR_DIRNAME).iterdir()) == []
    assert not (profile_home / accounts.STATE_FILENAME).exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX link and mode fixtures")
def test_repair_refuses_hardlinks_redirected_directory_and_unsafe_modes(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-state"
    outside.write_text("invalid", encoding="utf-8")
    outside.chmod(0o600)
    state_path = tmp_path / accounts.STATE_FILENAME
    os.link(outside, state_path)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)
    assert _error_code(exc) == "path_redirect"
    state_path.unlink()

    state_path.write_text("invalid", encoding="utf-8")
    state_path.chmod(0o644)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)
    assert _error_code(exc) == "invalid_state"
    state_path.chmod(0o600)

    outside_dir = tmp_path / "outside-repair"
    outside_dir.mkdir(mode=0o700)
    repair_dir = tmp_path / accounts.REPAIR_DIRNAME
    repair_dir.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)
    assert _error_code(exc) == "path_redirect"
    repair_dir.unlink()

    repair_dir.mkdir(mode=0o755)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.repair_account_store(home=tmp_path)
    assert _error_code(exc) == "invalid_state"
    assert state_path.read_bytes() == b"invalid"


def test_repair_has_posix_and_windows_private_creation_guards() -> None:
    directory_source = inspect.getsource(accounts._private_repair_directory)
    pin_child_source = inspect.getsource(accounts._pin_child_directory)
    reserve_source = inspect.getsource(accounts._reserve_repair_backup)
    claim_source = inspect.getsource(accounts._claim_repair_source)
    publish_source = inspect.getsource(accounts._publish_repair_replacement)
    atomic_move_source = inspect.getsource(accounts._atomic_move_noreplace)
    posix_move_source = inspect.getsource(accounts._posix_move_noreplace)
    atomic_replace_source = inspect.getsource(accounts._atomic_replace_entry)
    move_source = inspect.getsource(accounts._windows_move_write_through)
    windows_source = inspect.getsource(accounts._windows_private_directory)

    assert "REPAIR_DIR_MODE" in directory_source
    assert "O_DIRECTORY" in directory_source
    assert "O_NOFOLLOW" in directory_source
    assert "dir_fd=parent.dir_fd" in pin_child_source
    assert "O_EXCL" in reserve_source
    assert "_windows_private_fd" in reserve_source
    assert "_atomic_replace_entry" in claim_source
    assert "os.replace" in atomic_replace_source
    assert "_atomic_move_noreplace" in publish_source
    assert "os.link" not in publish_source
    assert "replace_existing=False" in atomic_move_source
    assert "renameatx_np" in posix_move_source
    assert "renameat2" in posix_move_source
    assert "RENAME_EXCL" in posix_move_source
    assert "RENAME_NOREPLACE" in posix_move_source
    assert "shutil" not in claim_source + publish_source
    assert "movefile_write_through" in move_source
    assert "file_flag_open_reparse_point" in windows_source
    assert "write_dac" in windows_source
    assert "_windows_private_dacl" in windows_source


def test_forbidden_extra_fields_never_reach_state(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        accounts.create_managed_request(
            home=tmp_path,
            provider_id=PROVIDER,
            device_label="Fabric A",
            expected_revision=0,
            access_token="sentinel-secret",  # type: ignore[call-arg]
        )
    assert not (tmp_path / accounts.STATE_FILENAME).exists()


def test_profile_isolation_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    first_home = tmp_path / "default"
    second_home = tmp_path / "profiles" / "other"
    first_home.mkdir()
    second_home.mkdir(parents=True)
    first = accounts.create_managed_request(
        home=first_home,
        provider_id=PROVIDER,
        device_label="One",
        expected_revision=0,
    )
    second = accounts.create_managed_request(
        home=second_home,
        provider_id=PROVIDER,
        device_label="Two",
        expected_revision=0,
    )

    assert first.request.request_id != second.request.request_id
    assert (
        accounts.get_account_snapshot(
            home=first_home, provider_id=PROVIDER
        ).active_request_id
        == first.request.request_id
    )
    assert (
        accounts.get_account_snapshot(
            home=second_home, provider_id=PROVIDER
        ).active_request_id
        == second.request.request_id
    )
    assert first.request.request_id not in (
        second_home / accounts.STATE_FILENAME
    ).read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="symlink setup is privilege-dependent")
def test_symlink_backed_home_is_allowed_but_state_and_lock_redirects_fail(
    tmp_path: Path,
) -> None:
    real_home = tmp_path / "real"
    real_home.mkdir()
    linked_home = tmp_path / "linked"
    linked_home.symlink_to(real_home, target_is_directory=True)
    snapshot = accounts.get_account_snapshot(home=linked_home, provider_id=PROVIDER)
    assert snapshot.revision == 0

    state_target = tmp_path / "outside-state"
    state_target.write_text("outside", encoding="utf-8")
    (real_home / accounts.STATE_FILENAME).symlink_to(state_target)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=linked_home, provider_id=PROVIDER)
    assert _error_code(exc) == "path_redirect"
    assert state_target.read_text(encoding="utf-8") == "outside"

    (real_home / accounts.STATE_FILENAME).unlink()
    (real_home / accounts.LOCK_FILENAME).unlink()
    lock_target = tmp_path / "outside-lock"
    lock_target.write_text("outside", encoding="utf-8")
    (real_home / accounts.LOCK_FILENAME).symlink_to(lock_target)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=linked_home, provider_id=PROVIDER)
    assert _error_code(exc) == "path_redirect"
    assert lock_target.read_text(encoding="utf-8") == "outside"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor/symlink race fixture")
def test_lock_mode_tightening_uses_descriptor_and_detects_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / accounts.LOCK_FILENAME
    outside = tmp_path / "outside"
    outside.write_text("do not chmod", encoding="utf-8")
    outside.chmod(0o644)
    original_mode = stat.S_IMODE(outside.stat().st_mode)
    real_fchmod = accounts.os.fchmod

    def swap_after_descriptor_chmod(fd: int, mode: int) -> None:
        real_fchmod(fd, mode)
        lock_path.unlink()
        lock_path.symlink_to(outside)

    monkeypatch.setattr(accounts.os, "fchmod", swap_after_descriptor_chmod)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(exc) == "path_redirect"
    assert stat.S_IMODE(outside.stat().st_mode) == original_mode
    assert outside.read_text(encoding="utf-8") == "do not chmod"


@pytest.mark.skipif(os.name == "nt", reason="POSIX dirfd pin fixture")
def test_profile_home_swap_after_pin_cannot_redirect_store_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_home = tmp_path / "profile"
    moved_home = tmp_path / "profile-moved"
    outside_home = tmp_path / "outside"
    profile_home.mkdir()
    outside_home.mkdir()
    real_open_lock = accounts._open_lock_file
    swapped = [False]

    def swap_home_then_open(lock_path: Path) -> int:
        if not swapped[0]:
            swapped[0] = True
            profile_home.rename(moved_home)
            profile_home.symlink_to(outside_home, target_is_directory=True)
        return real_open_lock(lock_path)

    monkeypatch.setattr(accounts, "_open_lock_file", swap_home_then_open)
    created = accounts.create_managed_request(
        home=profile_home,
        provider_id=PROVIDER,
        device_label="Pinned Fabric",
        expected_revision=0,
    )

    assert created.request.device_label == "Pinned Fabric"
    assert (moved_home / accounts.STATE_FILENAME).is_file()
    assert (moved_home / accounts.LOCK_FILENAME).is_file()
    assert not (outside_home / accounts.STATE_FILENAME).exists()
    assert not (outside_home / accounts.LOCK_FILENAME).exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows pinned handles deny rename")
def test_oauth_credential_reads_and_writes_follow_pinned_home_after_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Account completion and every auth.json field share one dirfd authority."""

    from fabric_cli import auth as auth_mod
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    _fixed_now(monkeypatch)
    profile_home = tmp_path / "profile"
    moved_home = tmp_path / "profile-original"
    profile_home.mkdir()
    auth_path = profile_home / "auth.json"
    auth_path.write_text(
        json.dumps({
            "version": 1,
            "providers": {},
            "suppressed_sources": {PROVIDER: ["manual:device_code", "environment"]},
        }),
        encoding="utf-8",
    )
    auth_path.chmod(0o600)
    started = accounts.capture_personal_oauth_start(
        home=profile_home,
        provider_id=PROVIDER,
        expected_revision=0,
    )
    lease = accounts.acquire_oauth_lease(
        home=profile_home,
        provider_id=PROVIDER,
        captured_intent=started.intent,
    )
    replacement_payload = {
        "version": 1,
        "providers": {"replacement": {"access_token": "must-not-change"}},
        "suppressed_sources": {PROVIDER: ["replacement-source"]},
    }

    home_token = set_fabric_home_override(profile_home)
    try:

        def credential_writer(_operation_id: str) -> None:
            profile_home.rename(moved_home)
            profile_home.mkdir()
            replacement_auth = profile_home / "auth.json"
            replacement_auth.write_text(
                json.dumps(replacement_payload),
                encoding="utf-8",
            )
            replacement_auth.chmod(0o600)

            auth_mod.write_credential_pool(
                PROVIDER,
                [
                    {
                        "id": "oauth1",
                        "label": "Personal ChatGPT",
                        "auth_type": "oauth",
                        "priority": 0,
                        "source": "manual:device_code",
                        "access_token": "pinned-access-token",
                    }
                ],
            )
            auth_mod.mark_provider_active_if_unset(PROVIDER)
            assert auth_mod.unsuppress_credential_source(PROVIDER, "manual:device_code")
            assert auth_mod.unsuppress_credential_source(PROVIDER, "environment")

        completed = accounts.commit_current_oauth_generation(
            home=profile_home,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=credential_writer,
            captured_intent=started.intent,
        )
    finally:
        reset_fabric_home_override(home_token)

    assert completed.snapshot.oauth_completion is not None
    pinned_auth = json.loads((moved_home / "auth.json").read_text(encoding="utf-8"))
    assert pinned_auth["credential_pool"][PROVIDER][0]["access_token"] == (
        "pinned-access-token"
    )
    assert pinned_auth["active_provider"] == PROVIDER
    assert PROVIDER not in pinned_auth.get("suppressed_sources", {})
    assert json.loads((profile_home / "auth.json").read_text(encoding="utf-8")) == (
        replacement_payload
    )
    assert (moved_home / accounts.STATE_FILENAME).is_file()
    assert not (profile_home / accounts.STATE_FILENAME).exists()
    assert accounts.current_oauth_profile_write_capability() is None


@pytest.mark.skipif(os.name == "nt", reason="Windows pinned handles deny rename")
def test_oauth_auth_lock_follows_pinned_home_and_blocks_moved_home_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auth data and its advisory lock use the same pinned directory object."""

    from fabric_cli import auth as auth_mod
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    _fixed_now(monkeypatch)
    profile_home = tmp_path / "profile"
    moved_home = tmp_path / "profile-original"
    profile_home.mkdir()
    initial_store = {
        "version": 1,
        "providers": {},
        "credential_pool": {
            PROVIDER: [
                {
                    "id": "existing",
                    "label": "Existing",
                    "auth_type": "oauth",
                    "priority": 0,
                    "source": "manual:device_code",
                    "access_token": "existing-token",
                }
            ]
        },
    }
    auth_path = profile_home / "auth.json"
    auth_path.write_text(json.dumps(initial_store), encoding="utf-8")
    auth_path.chmod(0o600)
    started = accounts.capture_personal_oauth_start(
        home=profile_home,
        provider_id=PROVIDER,
        expected_revision=0,
    )
    lease = accounts.acquire_oauth_lease(
        home=profile_home,
        provider_id=PROVIDER,
        captured_intent=started.intent,
    )
    replacement_store = {
        "version": 1,
        "providers": {"replacement": {"access_token": "do-not-touch"}},
    }
    writer_started = threading.Event()
    writer_finished = threading.Event()
    writer_failures: list[BaseException] = []

    def concurrent_writer() -> None:
        token = set_fabric_home_override(moved_home)
        try:
            writer_started.set()
            auth_mod.write_credential_pool(
                PROVIDER,
                [
                    {
                        "id": "concurrent",
                        "label": "Concurrent",
                        "auth_type": "oauth",
                        "priority": 1,
                        "source": "manual:device_code",
                        "access_token": "concurrent-token",
                    }
                ],
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_failures.append(exc)
        finally:
            reset_fabric_home_override(token)
            writer_finished.set()

    thread: threading.Thread | None = None
    home_token = set_fabric_home_override(profile_home)
    try:

        def credential_writer(_operation_id: str) -> None:
            nonlocal thread
            profile_home.rename(moved_home)
            profile_home.mkdir()
            replacement_auth = profile_home / "auth.json"
            replacement_auth.write_text(
                json.dumps(replacement_store),
                encoding="utf-8",
            )
            replacement_auth.chmod(0o600)

            # Acquiring after the pathname replacement is the important case:
            # only the capability-bound opener can still reach the original.
            with auth_mod._auth_store_lock(timeout_seconds=3):
                thread = threading.Thread(target=concurrent_writer, daemon=True)
                thread.start()
                assert writer_started.wait(1)
                time.sleep(0.15)
                assert not writer_finished.is_set()
                auth_mod.write_credential_pool(
                    PROVIDER,
                    [
                        {
                            "id": "oauth",
                            "label": "OAuth completion",
                            "auth_type": "oauth",
                            "priority": 1,
                            "source": "manual:device_code",
                            "access_token": "oauth-token",
                        }
                    ],
                )

        accounts.commit_current_oauth_generation(
            home=profile_home,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=credential_writer,
            captured_intent=started.intent,
        )
    finally:
        reset_fabric_home_override(home_token)

    assert thread is not None
    thread.join(3)
    assert writer_finished.is_set()
    assert writer_failures == []
    original = json.loads((moved_home / "auth.json").read_text(encoding="utf-8"))
    assert {entry["id"] for entry in original["credential_pool"][PROVIDER]} == {
        "oauth",
        "existing",
        "concurrent",
    }
    assert json.loads((profile_home / "auth.json").read_text(encoding="utf-8")) == (
        replacement_store
    )
    assert (moved_home / "auth.lock").is_file()
    assert not (profile_home / "auth.lock").exists()


def test_auth_lock_reentrancy_is_scoped_to_store_identity(tmp_path: Path) -> None:
    from fabric_cli import auth as auth_mod
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    first = tmp_path / "first-profile"
    second = tmp_path / "second-profile"
    first.mkdir()
    second.mkdir()
    first_token = set_fabric_home_override(first)
    try:
        with auth_mod._auth_store_lock(timeout_seconds=2):
            second_token = set_fabric_home_override(second)
            try:
                with auth_mod._auth_store_lock(timeout_seconds=2):
                    assert (second / "auth.lock").is_file()
            finally:
                reset_fabric_home_override(second_token)
    finally:
        reset_fabric_home_override(first_token)

    assert (first / "auth.lock").is_file()
    assert (second / "auth.lock").is_file()
    assert getattr(auth_mod._auth_lock_holder, "depths", {}) == {}


def test_auth_lock_is_reentrant_for_same_store(tmp_path: Path) -> None:
    from fabric_cli import auth as auth_mod
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    token = set_fabric_home_override(tmp_path)
    try:
        with auth_mod._auth_store_lock(timeout_seconds=2):
            with auth_mod._auth_store_lock(timeout_seconds=2):
                auth_mod.write_credential_pool(
                    PROVIDER,
                    [
                        {
                            "id": "nested",
                            "label": "Nested",
                            "auth_type": "oauth",
                            "priority": 0,
                            "source": "manual:device_code",
                            "access_token": "nested-token",
                        }
                    ],
                )
    finally:
        reset_fabric_home_override(token)

    stored = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))
    assert stored["credential_pool"][PROVIDER][0]["id"] == "nested"
    assert getattr(auth_mod._auth_lock_holder, "depths", {}) == {}


@pytest.mark.skipif(
    not hasattr(os, "register_at_fork")
    or "fork" not in multiprocessing.get_all_start_methods(),
    reason="requires POSIX fork",
)
def test_fork_child_waits_for_ordinary_auth_lock_before_write(tmp_path: Path) -> None:
    from fabric_cli import auth as auth_mod
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    context = multiprocessing.get_context("fork")
    attempted = context.Event()
    acquired = context.Event()
    output = context.Queue()
    token = set_fabric_home_override(tmp_path)
    process = None
    try:
        with auth_mod._auth_store_lock(timeout_seconds=5):
            process = context.Process(
                target=_fork_child_write_auth_store,
                args=(
                    str(tmp_path),
                    attempted,
                    acquired,
                    output,
                    "ordinary-child",
                ),
            )
            process.start()
            assert attempted.wait(2)
            assert not acquired.wait(0.25)
        assert acquired.wait(2)
        process.join(5)
    finally:
        reset_fabric_home_override(token)
        if process is not None and process.is_alive():
            process.terminate()
            process.join(5)

    assert process is not None
    assert process.exitcode == 0
    assert output.get(timeout=2) == ("written", "ordinary-child")
    stored = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))
    assert stored["credential_pool"][PROVIDER][0]["id"] == "ordinary-child"


@pytest.mark.skipif(
    not hasattr(os, "register_at_fork")
    or "fork" not in multiprocessing.get_all_start_methods(),
    reason="requires POSIX fork",
)
def test_fork_child_waits_for_pinned_auth_lock_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fabric_cli import auth as auth_mod
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    _fixed_now(monkeypatch)
    context = multiprocessing.get_context("fork")
    profile_home = tmp_path / "profile"
    moved_home = tmp_path / "profile-original"
    profile_home.mkdir()
    auth_path = profile_home / "auth.json"
    auth_path.write_text(
        json.dumps({
            "version": 1,
            "providers": {},
            "credential_pool": {
                PROVIDER: [
                    {
                        "id": "existing",
                        "label": "Existing",
                        "auth_type": "oauth",
                        "priority": 0,
                        "source": "manual:device_code",
                        "access_token": "existing-token",
                    }
                ]
            },
        }),
        encoding="utf-8",
    )
    auth_path.chmod(0o600)
    started = accounts.capture_personal_oauth_start(
        home=profile_home,
        provider_id=PROVIDER,
        expected_revision=0,
    )
    lease = accounts.acquire_oauth_lease(
        home=profile_home,
        provider_id=PROVIDER,
        captured_intent=started.intent,
    )
    replacement_store = {
        "version": 1,
        "providers": {"replacement": {"access_token": "do-not-touch"}},
    }
    process = None
    output = context.Queue()
    attempted = context.Event()
    acquired = context.Event()
    token = set_fabric_home_override(profile_home)
    try:

        def credential_writer(_operation_id: str) -> None:
            nonlocal process
            profile_home.rename(moved_home)
            profile_home.mkdir()
            replacement_auth = profile_home / "auth.json"
            replacement_auth.write_text(
                json.dumps(replacement_store),
                encoding="utf-8",
            )
            replacement_auth.chmod(0o600)

            with auth_mod._auth_store_lock(timeout_seconds=5):
                process = context.Process(
                    target=_fork_child_write_auth_store,
                    args=(
                        str(moved_home),
                        attempted,
                        acquired,
                        output,
                        "pinned-child",
                    ),
                )
                process.start()
                assert attempted.wait(2)
                assert not acquired.wait(0.25)
                auth_mod.write_credential_pool(
                    PROVIDER,
                    [
                        {
                            "id": "oauth-completion",
                            "label": "OAuth completion",
                            "auth_type": "oauth",
                            "priority": 1,
                            "source": "manual:device_code",
                            "access_token": "oauth-token",
                        }
                    ],
                )

            assert acquired.wait(2)
            process.join(5)
            assert process.exitcode == 0

        accounts.commit_current_oauth_generation(
            home=profile_home,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=credential_writer,
            captured_intent=started.intent,
        )
    finally:
        reset_fabric_home_override(token)
        if process is not None and process.is_alive():
            process.terminate()
            process.join(5)

    assert process is not None
    assert output.get(timeout=2) == ("written", "pinned-child")
    original = json.loads((moved_home / "auth.json").read_text(encoding="utf-8"))
    assert {entry["id"] for entry in original["credential_pool"][PROVIDER]} == {
        "existing",
        "oauth-completion",
        "pinned-child",
    }
    assert json.loads((profile_home / "auth.json").read_text(encoding="utf-8")) == (
        replacement_store
    )


def test_atomic_replace_failure_preserves_prior_valid_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    path = tmp_path / accounts.STATE_FILENAME
    before = path.read_bytes()

    def fail_replace(*_args, **_kwargs) -> None:
        raise OSError("cross-device sentinel")

    monkeypatch.setattr(accounts.os, "replace", fail_replace)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.select_personal(
            home=tmp_path,
            provider_id=PROVIDER,
            expected_revision=created.snapshot.revision,
        )
    assert _error_code(exc) == "io_unavailable"
    assert "sentinel" not in str(exc.value)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(f".{accounts.STATE_FILENAME}.tmp.*"))


@pytest.mark.parametrize(
    "post_effect_failure",
    [OSError(errno.EIO, "state-commit-then-oserror"), KeyboardInterrupt()],
    ids=("oserror", "keyboard-interrupt"),
)
def test_state_writer_post_effect_failure_is_commit_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post_effect_failure: BaseException,
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    real_replace = accounts._atomic_replace_entry

    def replace_then_fail(*args, **kwargs) -> None:
        real_replace(*args, **kwargs)
        raise post_effect_failure

    monkeypatch.setattr(accounts, "_atomic_replace_entry", replace_then_fail)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.select_personal(
            home=tmp_path,
            provider_id=PROVIDER,
            expected_revision=created.snapshot.revision,
        )

    assert _error_code(exc) == "commit_uncertain"
    assert exc.value.retryable is False
    reread = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert reread.desired_ownership == "personal"
    assert reread.revision == created.snapshot.revision + 1
    state_path = tmp_path / accounts.STATE_FILENAME
    assert state_path.stat().st_nlink == 1
    assert not list(tmp_path.glob(f".{accounts.STATE_FILENAME}.tmp.*"))


def test_stage_fsync_failure_is_precommit_io_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    path = tmp_path / accounts.STATE_FILENAME
    before = path.read_bytes()
    real_fsync = accounts.os.fsync

    def fail_regular_file(fd: int) -> None:
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("sentinel-stage-fsync")
        real_fsync(fd)

    monkeypatch.setattr(accounts.os, "fsync", fail_regular_file)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.select_personal(
            home=tmp_path,
            provider_id=PROVIDER,
            expected_revision=created.snapshot.revision,
        )
    assert _error_code(exc) == "io_unavailable"
    assert exc.value.retryable is True
    assert path.read_bytes() == before


def test_parent_fsync_failure_reports_commit_uncertain_and_requires_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )

    def fail_parent_fsync(_directory: Path) -> None:
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
        )

    monkeypatch.setattr(accounts, "_fsync_directory", fail_parent_fsync)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.select_personal(
            home=tmp_path,
            provider_id=PROVIDER,
            expected_revision=created.snapshot.revision,
        )
    assert _error_code(exc) == "commit_uncertain"
    assert exc.value.retryable is False

    # Replacement happened before the durability failure.  A caller must read
    # the authoritative current bytes instead of blindly retrying the mutation.
    reread = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert reread.desired_ownership == "personal"
    assert reread.revision == created.snapshot.revision + 1


def test_writer_fsyncs_file_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    calls: list[int] = []
    real_fsync = accounts.os.fsync

    def recording_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(accounts.os, "fsync", recording_fsync)
    accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    # Lock initialization, staging file, and parent directory are all durable.
    assert len(calls) >= 3


def test_lock_timeout_is_bounded_and_makes_no_state_write(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_child_hold_lock,
        args=(str(tmp_path), ready, release),
    )
    process.start()
    try:
        assert ready.wait(5)
        started = accounts.time.monotonic()
        with pytest.raises(accounts.ProviderAccountError) as exc:
            accounts.create_managed_request(
                home=tmp_path,
                provider_id=PROVIDER,
                device_label="Fabric A",
                expected_revision=0,
                lock_timeout_seconds=0.2,
            )
        elapsed = accounts.time.monotonic() - started
        assert _error_code(exc) == "lock_timeout"
        assert elapsed < 2
        assert not (tmp_path / accounts.STATE_FILENAME).exists()
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0


@pytest.mark.skipif(
    not hasattr(os, "register_at_fork")
    or "fork" not in multiprocessing.get_all_start_methods(),
    reason="requires POSIX fork",
)
def test_fork_child_cannot_inherit_reentrant_lock_bypass(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    output = context.Queue()
    with accounts.provider_account_lock(tmp_path, timeout_seconds=5):
        process = context.Process(
            target=_fork_child_try_lock,
            args=(str(tmp_path), output),
        )
        process.start()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0
    assert output.get(timeout=2) == "lock_timeout"


def test_personal_oauth_epoch_prevents_stale_intent_supersession(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    managed = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    flow_a = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=1
    )
    lease_a = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=flow_a.intent
    )
    restored = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=lease_a.snapshot.revision,
    )
    assert restored.request.request_id == managed.request.request_id

    writes: list[str] = []
    completed = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease_a.generation,
        operation_id=lease_a.lease.operation_id,
        credential_writer=lambda _operation_id: writes.append("persisted"),
        captured_intent=flow_a.intent,
    )
    assert writes == ["persisted"]
    assert completed.intent_matched is False
    assert completed.superseded_request_id is None
    assert completed.snapshot.desired_ownership == "fabric_managed"
    assert completed.snapshot.active_request_id == managed.request.request_id


def test_matching_personal_oauth_completion_supersedes_only_captured_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    managed = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=1
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )

    completed = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        credential_writer=lambda _operation_id: None,
        captured_intent=started.intent,
    )

    assert completed.intent_matched is True
    assert completed.superseded_request_id == managed.request.request_id
    assert completed.snapshot.active_request is None
    terminal = completed.snapshot.requests[-1]
    assert terminal.status == "cancelled"
    assert terminal.decision_source == "verified_personal_oauth"
    assert terminal.decision_reason == "superseded_by_verified_personal"
    assert completed.snapshot.oauth_lease is None


def test_oauth_completion_expires_overdue_request_before_intent_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    managed = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    _fixed_now(monkeypatch, NOW + accounts.REQUEST_TTL - timedelta(minutes=10))
    started = accounts.capture_personal_oauth_start(
        home=tmp_path,
        provider_id=PROVIDER,
        expected_revision=managed.snapshot.revision,
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    _fixed_now(monkeypatch, NOW + accounts.REQUEST_TTL + timedelta(minutes=1))
    writes: list[str] = []

    completed = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        credential_writer=lambda _operation_id: writes.append("persisted"),
        captured_intent=started.intent,
    )

    assert writes == ["persisted"]
    assert completed.intent_matched is False
    assert completed.superseded_request_id is None
    assert completed.snapshot.active_request is None
    terminal = completed.snapshot.requests[-1]
    assert terminal.status == "expired"
    assert terminal.decision_source == "system_expiry"


def test_flow_owner_mismatch_is_public_not_found_and_does_not_write_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    first_home = tmp_path / "one"
    other_home = tmp_path / "two"
    first_home.mkdir()
    other_home.mkdir()
    started = accounts.capture_personal_oauth_start(
        home=first_home, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=first_home, provider_id=PROVIDER, captured_intent=started.intent
    )
    writes: list[str] = []

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.commit_current_oauth_generation(
            home=other_home,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=lambda _operation_id: writes.append("bad"),
            captured_intent=started.intent,
        )
    assert _error_code(exc) == "not_found"
    assert writes == []


def test_oauth_lease_is_durable_across_processes_and_takeover_fences_stale_writer(
    tmp_path: Path,
) -> None:
    # Both competing workers use real time. Worker B completes before worker A
    # reports its late provider success, proving the credential callback is
    # fenced in the process that originally owned the superseded lease.
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    context = multiprocessing.get_context("spawn")
    allow_late = context.Event()
    output = context.Queue()
    worker_a = context.Process(
        target=_child_acquire_then_commit_late,
        args=(str(tmp_path), started.intent, allow_late, output),
    )
    worker_a.start()
    acquired = output.get(timeout=10)
    assert acquired[0] == "acquired"
    first_generation = acquired[1]

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.acquire_oauth_lease(
            home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
        )
    assert _error_code(exc) == "oauth_in_progress"

    worker_b = context.Process(
        target=_child_takeover_and_commit,
        args=(str(tmp_path), started.intent, output),
    )
    worker_b.start()
    worker_b.join(10)
    if worker_b.is_alive():
        worker_b.terminate()
        worker_b.join(5)
    allow_late.set()
    worker_a.join(10)
    if worker_a.is_alive():
        worker_a.terminate()
        worker_a.join(5)

    assert worker_b.exitcode == 0
    assert worker_a.exitcode == 0
    takeover_result = output.get(timeout=2)
    late_result = output.get(timeout=2)
    assert takeover_result[:3] == (
        "takeover",
        "completed",
        first_generation + 1,
    )
    assert takeover_result[3] != []
    assert takeover_result[4] is False
    assert late_result == ("late", "not_found", [])


def test_expired_oauth_lease_never_invokes_credential_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    _fixed_now(monkeypatch, NOW + accounts.OAUTH_LEASE_TTL + timedelta(seconds=1))
    writes: list[str] = []

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.commit_current_oauth_generation(
            home=tmp_path,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=lambda _operation_id: writes.append("expired"),
            captured_intent=started.intent,
        )
    assert _error_code(exc) == "not_found"
    assert writes == []
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_generation == lease.generation


def test_oauth_expiry_clock_is_captured_after_lock_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    clock = [NOW]
    monkeypatch.setattr(accounts, "_utc_now", lambda: clock[0])
    entered = threading.Event()
    writes: list[str] = []
    failures: list[accounts.ProviderAccountError] = []

    def complete() -> None:
        entered.set()
        try:
            accounts.commit_current_oauth_generation(
                home=tmp_path,
                provider_id=PROVIDER,
                generation=lease.generation,
                operation_id=lease.lease.operation_id,
                credential_writer=lambda _operation_id: writes.append("too late"),
                captured_intent=started.intent,
            )
        except accounts.ProviderAccountError as exc:
            failures.append(exc)

    with accounts.provider_account_lock(tmp_path, timeout_seconds=5):
        worker = threading.Thread(target=complete)
        worker.start()
        assert entered.wait(2)
        time.sleep(0.1)
        assert worker.is_alive()
        clock[0] = NOW + accounts.OAUTH_LEASE_TTL + timedelta(seconds=1)
    worker.join(5)

    assert not worker.is_alive()
    assert writes == []
    assert [failure.code.value for failure in failures] == ["not_found"]


def test_request_mutation_clock_is_captured_after_lock_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    clock = [NOW]
    monkeypatch.setattr(accounts, "_utc_now", lambda: clock[0])
    entered = threading.Event()
    failures: list[accounts.ProviderAccountError] = []

    def attempt_handoff() -> None:
        entered.set()
        try:
            accounts.record_handoff_attempt(
                home=tmp_path,
                provider_id=PROVIDER,
                request_id=created.request.request_id,
                expected_revision=created.snapshot.revision,
            )
        except accounts.ProviderAccountError as exc:
            failures.append(exc)

    with accounts.provider_account_lock(tmp_path, timeout_seconds=5):
        worker = threading.Thread(target=attempt_handoff)
        worker.start()
        assert entered.wait(2)
        time.sleep(0.1)
        clock[0] = NOW + accounts.REQUEST_TTL + timedelta(seconds=1)
    worker.join(5)

    assert [failure.code.value for failure in failures] == ["not_found"]
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert snapshot.requests[-1].status == "expired"


def test_release_oauth_lease_only_accepts_current_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    first = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    second = accounts.acquire_oauth_lease(
        home=tmp_path,
        provider_id=PROVIDER,
        captured_intent=started.intent,
        takeover=True,
    )
    stale_release = accounts.release_oauth_lease(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=first.generation,
        operation_id=first.lease.operation_id,
        store_instance_id=started.intent.store_instance_id,
        captured_intent=started.intent,
    )
    assert stale_release.snapshot.oauth_lease == second.lease
    released = accounts.release_oauth_lease(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=second.generation,
        operation_id=second.lease.operation_id,
        store_instance_id=started.intent.store_instance_id,
        captured_intent=started.intent,
    )
    assert released.snapshot.oauth_lease is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX profile rename ABA fixture")
def test_release_binds_captured_profile_owner_before_touching_successor_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    home = tmp_path / "profile"
    displaced = tmp_path / "profile-original"
    successor = tmp_path / "profile-successor"
    home.mkdir()
    started = accounts.capture_personal_oauth_start(
        home=home,
        provider_id=PROVIDER,
        expected_revision=0,
    )
    lease = accounts.acquire_oauth_lease(
        home=home,
        provider_id=PROVIDER,
        captured_intent=started.intent,
    )

    home.rename(displaced)
    home.mkdir()
    successor_state = home / accounts.STATE_FILENAME
    successor_state.write_bytes(
        (displaced / accounts.STATE_FILENAME).read_bytes()
    )
    successor_state.chmod(0o600)
    before = successor_state.read_bytes()

    with pytest.raises(accounts.ProviderAccountError) as wrong_owner:
        accounts.release_oauth_lease(
            home=home,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            store_instance_id=lease.lease.store_instance_id,
            captured_intent=started.intent,
        )
    assert _error_code(wrong_owner) == "not_found"
    assert successor_state.read_bytes() == before
    assert not (home / accounts.LOCK_FILENAME).exists()

    home.rename(successor)
    displaced.rename(home)
    released = accounts.release_oauth_lease(
        home=home,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        store_instance_id=lease.lease.store_instance_id,
        captured_intent=started.intent,
    )
    assert released.snapshot.oauth_lease is None
    assert (successor / accounts.STATE_FILENAME).read_bytes() == before


def test_takeover_never_reuses_active_writer_operation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    first_operation_id = "pao_" + "a" * 32
    second_operation_id = "pao_" + "b" * 32
    generated_ids = iter([first_operation_id, first_operation_id, second_operation_id])
    monkeypatch.setattr(
        accounts, "_new_oauth_operation_id", lambda: next(generated_ids)
    )
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    first = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )

    takeover = accounts.acquire_oauth_lease(
        home=tmp_path,
        provider_id=PROVIDER,
        captured_intent=started.intent,
        takeover=True,
    )

    assert first.lease.operation_id == first_operation_id
    assert takeover.lease.operation_id == second_operation_id


def test_caller_known_operation_id_replays_exact_live_lease_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    operation_id = accounts.new_oauth_operation_id()
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    first = accounts.acquire_oauth_lease(
        home=tmp_path,
        provider_id=PROVIDER,
        captured_intent=started.intent,
        operation_id=operation_id,
    )

    monkeypatch.setattr(
        accounts,
        "_write_state",
        lambda *_args, **_kwargs: pytest.fail("exact lease replay mutated state"),
    )
    replay = accounts.acquire_oauth_lease(
        home=tmp_path,
        provider_id=PROVIDER,
        captured_intent=started.intent,
        operation_id=operation_id,
    )

    assert replay.lease == first.lease
    assert replay.snapshot.revision == first.snapshot.revision
    assert replay.snapshot.oauth_generation == first.snapshot.oauth_generation
    assert replay.takeover is False


def test_different_operation_id_cannot_adopt_live_lease_or_reuse_takeover_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    first_operation_id = "pao_" + "a" * 32
    second_operation_id = "pao_" + "b" * 32
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    first = accounts.acquire_oauth_lease(
        home=tmp_path,
        provider_id=PROVIDER,
        captured_intent=started.intent,
        operation_id=first_operation_id,
    )

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.acquire_oauth_lease(
            home=tmp_path,
            provider_id=PROVIDER,
            captured_intent=started.intent,
            operation_id=second_operation_id,
        )
    assert _error_code(exc) == "oauth_in_progress"

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.acquire_oauth_lease(
            home=tmp_path,
            provider_id=PROVIDER,
            captured_intent=started.intent,
            operation_id=first_operation_id,
            takeover=True,
        )
    assert _error_code(exc) == "invalid_input"

    takeover = accounts.acquire_oauth_lease(
        home=tmp_path,
        provider_id=PROVIDER,
        captured_intent=started.intent,
        operation_id=second_operation_id,
        takeover=True,
    )
    assert first.lease.operation_id == first_operation_id
    assert takeover.lease.operation_id == second_operation_id
    assert takeover.generation == first.generation + 1
    assert takeover.takeover is True


def test_acquire_rejects_malformed_caller_operation_id(tmp_path: Path) -> None:
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.acquire_oauth_lease(
            home=tmp_path,
            provider_id=PROVIDER,
            captured_intent=started.intent,
            operation_id="not-an-operation",
        )

    assert _error_code(exc) == "invalid_input"
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert snapshot.oauth_lease is None


def test_oauth_completion_is_idempotent_after_lost_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    calls: list[str] = []

    first = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        credential_writer=lambda operation_id: calls.append(operation_id),
        captured_intent=started.intent,
    )
    replay = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        credential_writer=lambda _operation_id: pytest.fail("writer replayed"),
        captured_intent=started.intent,
    )

    assert calls == [lease.lease.operation_id]
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.operation_id == first.operation_id
    assert replay.snapshot.oauth_completion is not None


def test_writer_retry_reuses_operation_id_after_precommit_account_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    calls: list[str] = []
    effects: set[str] = set()

    def idempotent_writer(operation_id: str) -> None:
        calls.append(operation_id)
        effects.add(operation_id)

    real_replace = accounts.os.replace
    fail_once = [True]

    def flaky_replace(*args, **kwargs) -> None:
        if fail_once[0]:
            fail_once[0] = False
            raise OSError("sentinel-before-account-commit")
        real_replace(*args, **kwargs)

    monkeypatch.setattr(accounts.os, "replace", flaky_replace)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.commit_current_oauth_generation(
            home=tmp_path,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=idempotent_writer,
            captured_intent=started.intent,
        )
    assert _error_code(exc) == "io_unavailable"

    completed = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        credential_writer=idempotent_writer,
        captured_intent=started.intent,
    )
    assert completed.replayed is False
    assert calls == [lease.lease.operation_id, lease.lease.operation_id]
    assert effects == {lease.lease.operation_id}


def test_credential_writer_cannot_reenter_account_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )

    def reentrant_writer(_operation_id: str) -> None:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.commit_current_oauth_generation(
            home=tmp_path,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=reentrant_writer,
            captured_intent=started.intent,
        )
    assert _error_code(exc) == "oauth_in_progress"
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert snapshot.oauth_lease is not None
    assert snapshot.oauth_completion is None


def test_store_instance_and_operation_id_fence_recreated_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    old_start = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    old_lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=old_start.intent
    )
    (tmp_path / accounts.STATE_FILENAME).unlink()

    new_start = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    new_lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=new_start.intent
    )
    assert old_start.intent.store_instance_id != new_start.intent.store_instance_id
    assert old_lease.generation == new_lease.generation == 1
    assert old_lease.lease.operation_id != new_lease.lease.operation_id

    writes: list[str] = []
    with pytest.raises(accounts.ProviderAccountError) as commit_error:
        accounts.commit_current_oauth_generation(
            home=tmp_path,
            provider_id=PROVIDER,
            generation=old_lease.generation,
            operation_id=old_lease.lease.operation_id,
            credential_writer=lambda operation_id: writes.append(operation_id),
            captured_intent=old_start.intent,
        )
    assert _error_code(commit_error) == "not_found"
    with pytest.raises(accounts.ProviderAccountError) as release_error:
        accounts.release_oauth_lease(
            home=tmp_path,
            provider_id=PROVIDER,
            generation=old_lease.generation,
            operation_id=old_lease.lease.operation_id,
            store_instance_id=old_start.intent.store_instance_id,
            captured_intent=old_start.intent,
        )
    assert _error_code(release_error) == "not_found"
    assert writes == []
    assert (
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER).oauth_lease
        == new_lease.lease
    )


def test_rebind_restored_store_preserves_requests_and_clears_oauth_fences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    managed = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    started = accounts.capture_personal_oauth_start(
        home=tmp_path,
        provider_id=PROVIDER,
        expected_revision=managed.snapshot.revision,
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    before_revision = lease.snapshot.revision

    accounts.rebind_restored_account_store(home=tmp_path)

    rebound = accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert rebound.revision == before_revision + 1
    assert rebound.desired_ownership == "personal"
    assert rebound.active_request_id == managed.request.request_id
    assert rebound.oauth_lease is None
    assert rebound.oauth_completion is None
    writes: list[str] = []
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.commit_current_oauth_generation(
            home=tmp_path,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=lambda operation_id: writes.append(operation_id),
            captured_intent=started.intent,
        )
    assert _error_code(exc) == "not_found"
    assert writes == []


def test_next_unrelated_mutation_clears_completion_tombstone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    completed = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        credential_writer=lambda _operation_id: None,
        captured_intent=started.intent,
    )
    assert completed.snapshot.oauth_completion is not None

    managed = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=completed.snapshot.revision,
    )
    assert managed.snapshot.oauth_completion is None


def test_internal_oauth_fences_are_absent_from_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    for rendered in (repr(started), repr(lease), repr(lease.snapshot)):
        assert started.intent.store_instance_id not in rendered
        assert lease.lease.operation_id not in rendered
        assert str(tmp_path) not in rendered

    completed = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        credential_writer=lambda _operation_id: None,
        captured_intent=started.intent,
    )
    assert lease.lease.operation_id not in repr(completed)
    assert started.intent.store_instance_id not in repr(completed.snapshot)


def test_acquire_rejects_intent_after_desired_lane_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    managed = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=started.snapshot.revision,
    )
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.acquire_oauth_lease(
            home=tmp_path,
            provider_id=PROVIDER,
            captured_intent=started.intent,
        )
    assert _error_code(exc) == "not_found"
    assert managed.snapshot.oauth_generation == 0


def test_strict_parser_rejects_secret_shaped_oauth_lease_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    path = tmp_path / accounts.STATE_FILENAME
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["providers"][PROVIDER]["oauth_lease"]["session_id"] = "sentinel"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(exc) == "invalid_state"
    assert "sentinel" not in str(exc.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("desired_ownership", []),
        ("status", []),
        ("handoff_state", {}),
        ("decision_source", []),
    ],
)
def test_strict_parser_maps_unhashable_membership_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    raw = json.loads((tmp_path / accounts.STATE_FILENAME).read_text(encoding="utf-8"))
    provider = raw["providers"][PROVIDER]
    if field == "desired_ownership":
        provider[field] = value
    else:
        request = provider["requests"][0]
        if field == "decision_source":
            request["status"] = "awaiting"
            request["decision_at"] = request["updated_at"]
        request[field] = value
    (tmp_path / accounts.STATE_FILENAME).write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(exc) == "invalid_state"
    assert exc.value.__context__ is None
    assert created.request.request_id not in str(exc.value)


def test_deep_json_and_callback_errors_have_stable_context_free_tracebacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / accounts.STATE_FILENAME
    path.write_text("[" * 2_000 + "0" + "]" * 2_000, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    with pytest.raises(accounts.ProviderAccountError) as invalid:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(invalid) == "invalid_state"
    assert invalid.value.__context__ is None

    path.write_text("9" * 5_000, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    with pytest.raises(accounts.ProviderAccountError) as huge_integer:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(huge_integer) == "invalid_state"
    assert huge_integer.value.__context__ is None

    path.unlink()
    _fixed_now(monkeypatch)
    started = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )

    def secret_writer(_operation_id: str) -> None:
        raise RuntimeError("sentinel-access-token")

    with pytest.raises(accounts.ProviderAccountError) as unavailable:
        accounts.commit_current_oauth_generation(
            home=tmp_path,
            provider_id=PROVIDER,
            generation=lease.generation,
            operation_id=lease.lease.operation_id,
            credential_writer=secret_writer,
            captured_intent=started.intent,
        )
    rendered = "".join(traceback.format_exception(unavailable.value))
    assert _error_code(unavailable) == "io_unavailable"
    assert unavailable.value.__context__ is None
    assert "sentinel-access-token" not in rendered


def test_personal_oauth_intent_is_bound_to_exact_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    intent = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=PROVIDER, expected_revision=0
    ).intent
    other_intent = accounts.capture_personal_oauth_start(
        home=tmp_path, provider_id=OTHER_PROVIDER, expected_revision=0
    ).intent
    other_lease = accounts.acquire_oauth_lease(
        home=tmp_path,
        provider_id=OTHER_PROVIDER,
        captured_intent=other_intent,
    )
    writes: list[str] = []

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.commit_current_oauth_generation(
            home=tmp_path,
            provider_id=OTHER_PROVIDER,
            generation=other_lease.generation,
            operation_id=other_lease.lease.operation_id,
            credential_writer=lambda _operation_id: writes.append("cross-provider"),
            captured_intent=intent,
        )
    assert _error_code(exc) == "not_found"
    assert writes == []


def test_strict_provider_epoch_revision_and_terminal_time_invariants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    created = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    path = tmp_path / accounts.STATE_FILENAME
    base = json.loads(path.read_text(encoding="utf-8"))

    def assert_invalid(raw: dict[str, object]) -> None:
        path.write_text(json.dumps(raw), encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o600)
        with pytest.raises(accounts.ProviderAccountError) as exc:
            accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
        assert _error_code(exc) == "invalid_state"

    zero_revision = deepcopy(base)
    zero_revision["providers"][PROVIDER]["revision"] = 0
    assert_invalid(zero_revision)

    zero_epoch = deepcopy(base)
    zero_epoch["providers"][PROVIDER]["ownership_epoch"] = 0
    assert_invalid(zero_epoch)

    epoch_ahead_of_revision = deepcopy(base)
    epoch_ahead_of_revision["providers"][PROVIDER]["ownership_epoch"] = (
        created.snapshot.revision + 1
    )
    assert_invalid(epoch_ahead_of_revision)

    generation_ahead_of_revision = deepcopy(base)
    generation_ahead_of_revision["providers"][PROVIDER]["oauth_generation"] = (
        created.snapshot.revision + 1
    )
    assert_invalid(generation_ahead_of_revision)

    unrecorded_event_drift = deepcopy(base)
    unrecorded_event_drift["providers"][PROVIDER]["requests"][0]["updated_at"] = (
        "2026-07-11T18:01:00Z"
    )
    assert_invalid(unrecorded_event_drift)

    far_expiry = deepcopy(base)
    far_expiry["providers"][PROVIDER]["requests"][0]["expires_at"] = (
        "2026-07-19T18:00:00Z"
    )
    assert_invalid(far_expiry)

    cancelled_after_expiry = deepcopy(base)
    provider = cancelled_after_expiry["providers"][PROVIDER]
    provider["active_request_id"] = None
    request = provider["requests"][0]
    request.update(
        status="cancelled",
        updated_at="2026-07-18T18:00:01Z",
        decision_at="2026-07-18T18:00:01Z",
        decision_source="local_operator",
    )
    assert_invalid(cancelled_after_expiry)

    early_expiry = deepcopy(base)
    provider = early_expiry["providers"][PROVIDER]
    provider["active_request_id"] = None
    request = provider["requests"][0]
    request.update(
        status="expired",
        updated_at="2026-07-12T18:00:00Z",
        decision_at="2026-07-12T18:00:00Z",
        decision_source="system_expiry",
    )
    assert_invalid(early_expiry)

    terminal_mismatch = deepcopy(base)
    provider = terminal_mismatch["providers"][PROVIDER]
    provider["active_request_id"] = None
    request = provider["requests"][0]
    request.update(
        status="cancelled",
        updated_at="2026-07-12T18:01:00Z",
        decision_at="2026-07-12T18:00:00Z",
        decision_source="local_operator",
    )
    assert_invalid(terminal_mismatch)
    assert created.snapshot.revision == 1


def test_strict_lease_and_completion_fence_invariants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    managed = accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    started = accounts.capture_personal_oauth_start(
        home=tmp_path,
        provider_id=PROVIDER,
        expected_revision=managed.snapshot.revision,
    )
    lease = accounts.acquire_oauth_lease(
        home=tmp_path, provider_id=PROVIDER, captured_intent=started.intent
    )
    path = tmp_path / accounts.STATE_FILENAME
    live = json.loads(path.read_text(encoding="utf-8"))

    def assert_invalid(raw: dict[str, object]) -> None:
        path.write_text(json.dumps(raw), encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o600)
        with pytest.raises(accounts.ProviderAccountError) as exc:
            accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
        assert _error_code(exc) == "invalid_state"

    zero_lease_epoch = deepcopy(live)
    zero_lease_epoch["providers"][PROVIDER]["oauth_lease"]["ownership_epoch"] = 0
    assert_invalid(zero_lease_epoch)

    malformed_captured_id = deepcopy(live)
    malformed_captured_id["providers"][PROVIDER]["oauth_lease"][
        "active_request_id_at_start"
    ] = "not-a-request"
    assert_invalid(malformed_captured_id)

    # Restore valid live bytes before completing the flow.
    path.write_text(json.dumps(live), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    completed = accounts.commit_current_oauth_generation(
        home=tmp_path,
        provider_id=PROVIDER,
        generation=lease.generation,
        operation_id=lease.lease.operation_id,
        credential_writer=lambda _operation_id: None,
        captured_intent=started.intent,
    )
    assert completed.superseded_request_id == managed.request.request_id
    terminal = json.loads(path.read_text(encoding="utf-8"))

    stale_generation = deepcopy(terminal)
    stale_generation["providers"][PROVIDER]["oauth_generation"] += 1
    assert_invalid(stale_generation)

    false_match = deepcopy(terminal)
    false_match["providers"][PROVIDER]["oauth_completion"]["intent_matched"] = False
    assert_invalid(false_match)

    wrong_superseded = deepcopy(terminal)
    wrong_superseded["providers"][PROVIDER]["oauth_completion"][
        "superseded_request_id"
    ] = "par_" + "f" * 24
    assert_invalid(wrong_superseded)

    missing_superseded = deepcopy(terminal)
    missing_superseded["providers"][PROVIDER]["oauth_completion"][
        "superseded_request_id"
    ] = None
    assert_invalid(missing_superseded)


@pytest.mark.skipif(os.name == "nt", reason="hardlink fixture uses POSIX ownership")
def test_state_and_lock_hardlinks_are_rejected_across_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    first_home = tmp_path / "first"
    second_home = tmp_path / "second"
    first_home.mkdir()
    second_home.mkdir()
    accounts.create_managed_request(
        home=first_home,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    accounts.get_account_snapshot(home=second_home, provider_id=PROVIDER)

    first_state = first_home / accounts.STATE_FILENAME
    second_state = second_home / accounts.STATE_FILENAME
    os.link(first_state, second_state)
    with pytest.raises(accounts.ProviderAccountError) as state_error:
        accounts.get_account_snapshot(home=second_home, provider_id=PROVIDER)
    assert _error_code(state_error) == "path_redirect"
    second_state.unlink()

    first_lock = first_home / accounts.LOCK_FILENAME
    second_lock = second_home / accounts.LOCK_FILENAME
    second_lock.unlink()
    os.link(first_lock, second_lock)
    with pytest.raises(accounts.ProviderAccountError) as lock_error:
        accounts.get_account_snapshot(home=second_home, provider_id=PROVIDER)
    assert _error_code(lock_error) == "path_redirect"


def test_windows_security_contract_uses_pinned_handle_dacl_and_write_through() -> None:
    from fabric_cli import auth as auth_mod

    pin_source = inspect.getsource(accounts._windows_pin_directory_tree)
    dacl_source = inspect.getsource(accounts._windows_private_dacl)
    move_source = inspect.getsource(accounts._windows_move_write_through)
    replace_source = inspect.getsource(accounts._atomic_replace_entry)
    private_create_source = inspect.getsource(accounts._windows_open_private_file)
    from fabric_cli.provider_account_privacy import PinnedFileCapability

    pinned_open_source = inspect.getsource(PinnedFileCapability.open)
    security_attributes_source = inspect.getsource(
        accounts._windows_current_user_security_attributes
    )
    state_write_source = inspect.getsource(accounts._write_state)
    oauth_write_source = inspect.getsource(
        accounts.OAuthProfileWriteCapability.atomic_write_bytes
    )
    account_lock_source = inspect.getsource(accounts._open_lock_file)
    auth_write_source = inspect.getsource(auth_mod._save_auth_store)
    auth_lock_source = inspect.getsource(auth_mod._open_advisory_lock_file)
    assert "file_flag_backup_semantics = 0x02000000" in pin_source
    assert "file_flag_open_reparse_point = 0x00200000" in pin_source
    assert "file_share_read | file_share_write" in pin_source
    assert "file_share_delete" not in pin_source
    assert "protected_dacl_security_information = 0x80000000" in dacl_source
    assert "SetSecurityInfo" in dacl_source
    assert "GetSecurityInfo" in dacl_source
    assert "EqualSid" in dacl_source
    assert "movefile_replace_existing = 0x00000001" in move_source
    assert "movefile_write_through = 0x00000008" in move_source
    assert "if replace_existing" in move_source
    assert "file_share_write if share_write else 0" in private_create_source
    assert "open_existing_disposition = 3" in private_create_source
    assert "share_write=False" in pinned_open_source
    assert "open_existing=True" in pinned_open_source
    assert "replace_existing=True" in replace_source
    assert (
        "generic_read | generic_write | read_control | write_dac"
        in private_create_source
    )
    assert "file_flag_open_reparse_point" in private_create_source
    assert "open_osfhandle" in private_create_source
    assert "share_delete: bool = False" in private_create_source
    assert "(file_share_delete if share_delete else 0)" in private_create_source
    assert "D:P(A;;FA;;;" in security_attributes_source
    assert "ConvertStringSecurityDescriptorToSecurityDescriptorW" in (
        security_attributes_source
    )
    for consumer in (
        state_write_source,
        oauth_write_source,
        account_lock_source,
        auth_write_source,
        auth_lock_source,
    ):
        assert "_windows_open_private" in consumer
        assert "share_delete=True" not in consumer


@pytest.mark.skipif(os.name != "nt", reason="native Windows ACL/handle contract")
def test_windows_native_state_acl_and_directory_rename_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Windows Fabric",
        expected_revision=0,
    )
    state_path = tmp_path / accounts.STATE_FILENAME
    fd = os.open(state_path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        assert accounts._windows_private_fd(fd, apply=False) is True
    finally:
        os.close(fd)
    moved = tmp_path.with_name(tmp_path.name + "-moved")
    with accounts.provider_account_lock(tmp_path):
        with pytest.raises(OSError):
            tmp_path.rename(moved)


@pytest.mark.skipif(os.name != "nt", reason="native Windows private-file matrix")
def test_windows_native_state_auth_and_lock_creation_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fabric_cli import auth as auth_mod
    from fabric_constants import reset_fabric_home_override, set_fabric_home_override

    _fixed_now(monkeypatch)
    accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    token = set_fabric_home_override(tmp_path)
    try:
        with auth_mod._auth_store_lock():
            auth_mod._save_auth_store({
                "version": 1,
                "providers": {},
                "credential_pool": {},
            })
    finally:
        reset_fabric_home_override(token)

    for path in (
        tmp_path / accounts.STATE_FILENAME,
        tmp_path / accounts.LOCK_FILENAME,
        tmp_path / "auth.json",
        tmp_path / "auth.lock",
    ):
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            assert accounts._windows_private_fd(fd, apply=False) is True
        finally:
            os.close(fd)

    native_temp = tmp_path / "native-private.tmp"
    fd = accounts._windows_open_private_file(native_temp, create_new=True)
    try:
        assert accounts._windows_private_fd(fd, apply=False) is True
        os.write(fd, b"private")
        os.fsync(fd)
    finally:
        os.close(fd)
    assert native_temp.read_bytes() == b"private"


def test_read_state_closes_descriptor_when_entry_validation_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_now(monkeypatch)
    accounts.create_managed_request(
        home=tmp_path,
        provider_id=PROVIDER,
        device_label="Fabric A",
        expected_revision=0,
    )
    real_open = os.open
    opened_fds: list[int] = []

    def tracked_open(*args: object, **kwargs: object) -> int:
        fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
        opened_fds.append(fd)
        return fd

    def fail_entry_validation(*_args: object) -> bool:
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.PATH_REDIRECT
        )

    monkeypatch.setattr(accounts.os, "open", tracked_open)
    monkeypatch.setattr(accounts, "_same_opened_entry", fail_entry_validation)

    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts._read_state(tmp_path)
    assert _error_code(exc) == "path_redirect"
    assert len(opened_fds) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(opened_fds[0])
    assert closed.value.errno == errno.EBADF


def test_unexpected_windows_lock_error_is_io_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenMsvcrt:
        LK_NBLCK = 1

        @staticmethod
        def locking(_fd: int, _mode: int, _size: int) -> None:
            raise OSError(errno.EIO, "injected")

    lock_path = tmp_path / "lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        monkeypatch.setattr(accounts, "fcntl", None)
        monkeypatch.setattr(accounts, "msvcrt", BrokenMsvcrt)
        with pytest.raises(accounts.ProviderAccountError) as exc:
            accounts._acquire_kernel_lock(fd, time.monotonic() + 10)
    finally:
        os.close(fd)
    assert _error_code(exc) == "io_unavailable"


def test_strict_parser_rejects_duplicate_keys_and_oversized_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / accounts.STATE_FILENAME
    path.write_text(
        '{"schema_version": 1, "schema_version": 1, "providers": {}}',
        encoding="utf-8",
    )
    if os.name != "nt":
        path.chmod(0o600)
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(exc) == "invalid_state"

    path.write_bytes(b"{" + b" " * accounts.MAX_STATE_BYTES + b"}")
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(home=tmp_path, provider_id=PROVIDER)
    assert _error_code(exc) == "invalid_state"


@pytest.mark.parametrize("timeout", [True, "1", float("nan"), float("inf"), 0, -1])
def test_lock_timeout_input_is_stable(tmp_path: Path, timeout: object) -> None:
    with pytest.raises(accounts.ProviderAccountError) as exc:
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id=PROVIDER,
            lock_timeout_seconds=timeout,  # type: ignore[arg-type]
        )
    assert _error_code(exc) == "invalid_input"
