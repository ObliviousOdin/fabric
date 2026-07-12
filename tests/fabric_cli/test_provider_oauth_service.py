"""Direct lifecycle and ownership tests for the framework-neutral OAuth service."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from fabric_cli import provider_accounts as accounts
from fabric_cli.provider_oauth_service import (
    OAuthFlowError,
    OAuthFlowErrorCode,
    OAuthFlowService,
    serialize_oauth_error,
)


def test_same_process_duplicate_start_is_idempotent(tmp_path: Path) -> None:
    service = OAuthFlowService()

    first = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )
    second = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )

    assert first.created is True
    assert second.created is False
    assert second.session_id == first.session_id
    public = service.publish_start(
        first.session_id,
        first.session,
        {
            "flow": "device_code",
            "user_code": "NOUS-1234",
            "verification_url": "https://example.test/device",
            "expires_in": 600,
            "poll_interval": 5,
            "device_code": "must-not-leave-service",
        },
    )
    assert service.wait_for_start(second) == public
    assert public == {
        "session_id": first.session_id,
        "flow": "device_code",
        "user_code": "NOUS-1234",
        "verification_url": "https://example.test/device",
        "expires_in": 600,
        "poll_interval": 5,
    }
    assert first.session["_flow_trace_id"] not in str(public)


def test_cancel_wakes_same_process_start_waiter_with_not_found(tmp_path: Path) -> None:
    service = OAuthFlowService()
    first = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )
    replay = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )

    service.cancel(
        home=tmp_path,
        provider_id="nous",
        session_id=first.session_id,
    )

    with pytest.raises(OAuthFlowError) as cancelled:
        service.wait_for_start(replay, timeout_seconds=0.01)
    assert cancelled.value.code is OAuthFlowErrorCode.NOT_FOUND


def test_concurrent_starts_share_one_process_local_session(tmp_path: Path) -> None:
    service = OAuthFlowService()
    barrier = threading.Barrier(8)
    results: list[tuple[str, bool]] = []

    def reserve() -> None:
        barrier.wait()
        result = service.reserve_start(
            home=tmp_path,
            provider_id="minimax-oauth",
            flow="device_code",
            profile_name=None,
        )
        results.append((result.session_id, result.created))

    threads = [threading.Thread(target=reserve) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(results) == 8
    assert len({session_id for session_id, _created in results}) == 1
    assert sum(created for _session_id, created in results) == 1


def test_owner_and_provider_mismatch_are_identical_not_found(tmp_path: Path) -> None:
    service = OAuthFlowService()
    other = tmp_path / "other"
    other.mkdir()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )

    failures: list[OAuthFlowError] = []
    for home, provider_id, session_id in (
        (other, "nous", started.session_id),
        (tmp_path, "xai-oauth", started.session_id),
        (tmp_path, "nous", "missing-session"),
    ):
        with pytest.raises(OAuthFlowError) as caught:
            service.poll(
                home=home,
                provider_id=provider_id,
                session_id=session_id,
            )
        failures.append(caught.value)

    assert {failure.code for failure in failures} == {OAuthFlowErrorCode.NOT_FOUND}
    assert {str(failure) for failure in failures} == {"not_found"}
    assert {str(serialize_oauth_error(failure)) for failure in failures} == {
        "{'error': {'code': 'not_found', 'retryable': False}}"
    }


def test_directory_replacement_fences_generic_worker_before_credential_write(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    displaced = tmp_path / "displaced"
    home.mkdir()
    service = OAuthFlowService()
    started = service.reserve_start(
        home=home,
        provider_id="nous",
        flow="device_code",
        profile_name="profile",
    )

    home.rename(displaced)
    home.mkdir()
    writes: list[str] = []

    assert not service.commit_if_active(
        started.session_id,
        started.session,
        lambda: writes.append("forbidden"),
    )
    assert writes == []
    assert started.session["_stale_generation"] is True
    with pytest.raises(OAuthFlowError) as stale:
        service.poll(
            home=home,
            provider_id="nous",
            session_id=started.session_id,
        )
    assert stale.value.code is OAuthFlowErrorCode.NOT_FOUND


@pytest.mark.skipif(os.name == "nt", reason="POSIX profile rename ABA fixture")
def test_shutdown_retains_exact_release_across_profile_replacement_and_rename_back(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    displaced = tmp_path / "profile-original"
    successor = tmp_path / "profile-successor"
    home.mkdir()
    service = OAuthFlowService()
    started = service.reserve_start(
        home=home,
        provider_id="openai-codex",
        flow="device_code",
        profile_name="profile",
    )

    home.rename(displaced)
    home.mkdir()
    successor_state = home / accounts.STATE_FILENAME
    successor_state.write_bytes(
        (displaced / accounts.STATE_FILENAME).read_bytes()
    )
    successor_state.chmod(0o600)
    before = successor_state.read_bytes()

    first = service.shutdown()
    assert first == {
        "cancelled": 1,
        "release_attempts": 1,
        "release_failures": 1,
    }
    assert started.session["status"] == "cancelled"
    assert started.session["_release_pending"] is True
    assert successor_state.read_bytes() == before
    assert not (home / accounts.LOCK_FILENAME).exists()

    home.rename(successor)
    displaced.rename(home)
    second = service.shutdown()
    assert second == {
        "cancelled": 0,
        "release_attempts": 1,
        "release_failures": 0,
    }
    assert service.sessions == {}
    assert (
        accounts.get_account_snapshot(
            home=home,
            provider_id="openai-codex",
        ).oauth_lease
        is None
    )
    assert (successor / accounts.STATE_FILENAME).read_bytes() == before


def test_transient_generation_read_error_does_not_misclassify_session_as_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
    )

    monkeypatch.setattr(
        accounts,
        "get_account_snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(
            accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.LOCK_TIMEOUT
            )
        ),
    )

    with pytest.raises(OAuthFlowError) as unavailable:
        service.poll(
            home=tmp_path,
            provider_id="openai-codex",
            session_id=started.session_id,
        )
    assert unavailable.value.code is OAuthFlowErrorCode.LOCK_TIMEOUT
    assert started.session["status"] == "pending"
    assert started.session["_stale_generation"] is False
    assert not started.session["_cancel_event"].is_set()


def test_registry_expiry_signals_worker_and_returns_expired_once(
    tmp_path: Path,
) -> None:
    now = [100.0]
    service = OAuthFlowService(
        ttl_seconds=10,
        terminal_retention_seconds=5,
        clock=lambda: now[0],
    )
    started = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )
    now[0] = 111.0

    response = service.poll(
        home=tmp_path,
        provider_id="nous",
        session_id=started.session_id,
    )

    assert response["status"] == "expired"
    assert started.session["_cancel_event"].is_set()
    replacement = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )
    assert replacement.created is True
    assert replacement.session_id != started.session_id
    now[0] = 117.0
    service.gc()
    assert started.session_id not in service.sessions


def test_cross_process_conflict_takeover_and_stale_writer_fence(tmp_path: Path) -> None:
    first_process = OAuthFlowService()
    second_process = OAuthFlowService()
    first = first_process.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
        expected_revision=0,
    )

    with pytest.raises(OAuthFlowError) as conflict:
        second_process.reserve_start(
            home=tmp_path,
            provider_id="openai-codex",
            flow="device_code",
            profile_name=None,
        )
    assert conflict.value.code is OAuthFlowErrorCode.OAUTH_IN_PROGRESS

    takeover = second_process.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
        takeover=True,
    )
    first_lease = first.session["_lease_result"].lease
    replacement_lease = takeover.session["_lease_result"].lease
    assert replacement_lease.generation > first_lease.generation

    # Once another process advances the durable generation, the old process
    # must neither replay its cached URL nor expose/cancel that stale session.
    with pytest.raises(OAuthFlowError) as stale_poll:
        first_process.poll(
            home=tmp_path,
            provider_id="openai-codex",
            session_id=first.session_id,
        )
    assert stale_poll.value.code is OAuthFlowErrorCode.NOT_FOUND
    with pytest.raises(OAuthFlowError) as stale_cancel:
        first_process.cancel(
            home=tmp_path,
            provider_id="openai-codex",
            session_id=first.session_id,
        )
    assert stale_cancel.value.code is OAuthFlowErrorCode.NOT_FOUND
    with pytest.raises(OAuthFlowError) as stale_replay:
        first_process.reserve_start(
            home=tmp_path,
            provider_id="openai-codex",
            flow="device_code",
            profile_name=None,
        )
    assert stale_replay.value.code is OAuthFlowErrorCode.OAUTH_IN_PROGRESS

    stale_writes: list[str] = []
    assert (
        first_process.commit_if_active(
            first.session_id,
            first.session,
            lambda: stale_writes.append("forbidden"),
        )
        is False
    )
    assert stale_writes == []
    assert first_process.session_is_cancelled(first.session) is True

    assert (
        second_process.cancel(
            home=tmp_path,
            provider_id="openai-codex",
            session_id=takeover.session_id,
        )["ok"]
        is True
    )
    snapshot = accounts.get_account_snapshot(
        home=tmp_path,
        provider_id="openai-codex",
    )
    assert snapshot.oauth_lease is None


@pytest.mark.parametrize("uncertain_position", ["before", "after"])
@pytest.mark.parametrize("takeover", [False, True])
def test_uncertain_lease_acquire_replays_only_its_caller_known_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    uncertain_position: str,
    takeover: bool,
) -> None:
    first_process = OAuthFlowService()
    initial = None
    if takeover:
        initial = first_process.reserve_start(
            home=tmp_path,
            provider_id="openai-codex",
            flow="device_code",
            profile_name=None,
        )

    real_acquire = accounts.acquire_oauth_lease
    calls: list[tuple[str | None, bool]] = []

    def uncertain_once(**kwargs):
        calls.append((kwargs.get("operation_id"), kwargs.get("takeover", False)))
        if len(calls) == 1:
            if uncertain_position == "after":
                real_acquire(**kwargs)
            raise accounts.ProviderAccountError(
                accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN
            )
        return real_acquire(**kwargs)

    monkeypatch.setattr(accounts, "acquire_oauth_lease", uncertain_once)
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
        takeover=takeover,
    )

    assert len(calls) == 2
    assert calls[0][0] == calls[1][0]
    assert calls[0][1] is takeover
    assert calls[1][1] is (takeover and uncertain_position == "before")
    if initial is not None:
        assert (
            started.session["_lease_result"].lease.generation
            == initial.session["_lease_result"].lease.generation + 1
        )


def test_cancel_releases_lease_but_preserves_managed_request(tmp_path: Path) -> None:
    requested = accounts.create_managed_request(
        home=tmp_path,
        provider_id="xai-oauth",
        device_label="front desk",
        expected_revision=0,
    )
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="xai-oauth",
        flow="device_code",
        profile_name=None,
        expected_revision=requested.snapshot.revision,
    )

    cancelled = service.cancel(
        home=tmp_path,
        provider_id="xai-oauth",
        session_id=started.session_id,
    )
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id="xai-oauth")

    assert cancelled == {"ok": True, "session_id": started.session_id}
    assert snapshot.oauth_lease is None
    assert snapshot.desired_ownership == "personal"
    assert snapshot.active_request_id == requested.request.request_id
    assert snapshot.active_request is not None
    assert snapshot.active_request.status == "requested"


def test_cancel_reports_release_failure_and_exact_retry_finishes_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OAuthFlowService(terminal_retention_seconds=0)
    started = service.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
    )
    real_release = accounts.release_oauth_lease

    def unavailable_release(**_kwargs):
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
        )

    monkeypatch.setattr(accounts, "release_oauth_lease", unavailable_release)
    with pytest.raises(OAuthFlowError) as failed:
        service.cancel(
            home=tmp_path,
            provider_id="openai-codex",
            session_id=started.session_id,
        )

    assert failed.value.code is OAuthFlowErrorCode.IO_UNAVAILABLE
    assert started.session["status"] == "cancelled"
    assert started.session["_release_pending"] is True
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="openai-codex",
        ).oauth_lease
        is not None
    )

    # GC must retain the only retry handle while release is unconfirmed.
    started.session["_terminal_at"] = 0
    service.gc()
    assert started.session_id in service.sessions

    monkeypatch.setattr(accounts, "release_oauth_lease", real_release)
    assert service.cancel(
        home=tmp_path,
        provider_id="openai-codex",
        session_id=started.session_id,
    ) == {"ok": True, "session_id": started.session_id}
    assert started.session["_release_pending"] is False
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="openai-codex",
        ).oauth_lease
        is None
    )


def test_graceful_shutdown_cancels_worker_and_releases_durable_lease(
    tmp_path: Path,
) -> None:
    service = OAuthFlowService()
    personal = service.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
    )
    generic = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )

    result = service.shutdown()

    assert result == {
        "cancelled": 2,
        "release_attempts": 1,
        "release_failures": 0,
    }
    assert personal.session["_cancel_event"].is_set()
    assert generic.session["_cancel_event"].is_set()
    assert service.sessions == {}
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="openai-codex",
        ).oauth_lease
        is None
    )
    assert service.shutdown() == {
        "cancelled": 0,
        "release_attempts": 0,
        "release_failures": 0,
    }


def test_shutdown_retains_failed_release_for_retry_and_explicit_takeover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
    )
    real_release = accounts.release_oauth_lease

    def unavailable_release(**_kwargs):
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.IO_UNAVAILABLE
        )

    monkeypatch.setattr(accounts, "release_oauth_lease", unavailable_release)
    assert service.shutdown() == {
        "cancelled": 1,
        "release_attempts": 1,
        "release_failures": 1,
    }
    assert started.session_id in service.sessions
    assert started.session["_release_pending"] is True

    # A new process/service can explicitly take over the retained durable
    # generation; shutdown failure never silently adopts or clears it.
    replacement = OAuthFlowService()
    takeover = replacement.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
        takeover=True,
    )
    assert takeover.created is True
    assert takeover.session_id != started.session_id

    monkeypatch.setattr(accounts, "release_oauth_lease", real_release)
    assert replacement.shutdown()["release_failures"] == 0
    assert service.shutdown()["release_failures"] == 0


def test_start_progress_timeout_is_atomic_and_releases_personal_lease(
    tmp_path: Path,
) -> None:
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="xai-oauth",
        flow="device_code",
        profile_name=None,
    )

    progress = service.start_progress(
        started.session_id,
        started.session,
        fail_if_unready=True,
    )

    assert progress == {
        "status": "error",
        "user_code": None,
        "verification_url": None,
        "expires_in": None,
        "interval": None,
    }
    assert started.session["_cancel_event"].is_set()
    assert started.session["_release_pending"] is False
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


def test_worker_expiry_releases_exact_personal_lease(tmp_path: Path) -> None:
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="xai-oauth",
        flow="device_code",
        profile_name=None,
    )

    assert service.expire_if_active(started.session_id, started.session) is True
    assert started.session["status"] == "expired"
    assert started.session["_cancel_event"].is_set()
    assert started.session["_release_pending"] is False
    assert service.expire_if_active(started.session_id, started.session) is False
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is None
    )


def test_verified_commit_writes_once_and_supersedes_only_captured_request(
    tmp_path: Path,
) -> None:
    requested = accounts.create_managed_request(
        home=tmp_path,
        provider_id="openai-codex",
        device_label="front desk",
        expected_revision=0,
    )
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
        expected_revision=requested.snapshot.revision,
    )
    writes: list[str] = []

    assert service.commit_if_active(
        started.session_id,
        started.session,
        lambda: writes.append("credential"),
    )
    snapshot = accounts.get_account_snapshot(
        home=tmp_path,
        provider_id="openai-codex",
    )

    assert writes == ["credential"]
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_completion is not None
    assert snapshot.active_request is None
    terminal = next(
        request
        for request in snapshot.requests
        if request.request_id == requested.request.request_id
    )
    assert terminal.status == "cancelled"
    assert terminal.decision_source == "verified_personal_oauth"
    assert terminal.decision_reason == "superseded_by_verified_personal"


@pytest.mark.parametrize("provider_id", ["openai-codex", "xai-oauth"])
@pytest.mark.parametrize(
    ("signal_type", "exit_code"),
    [(KeyboardInterrupt, None), (SystemExit, 130)],
)
def test_signal_during_personal_commit_stabilizes_session_and_releases_lease(
    tmp_path: Path,
    provider_id: str,
    signal_type: type[BaseException],
    exit_code: int | None,
) -> None:
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id=provider_id,
        flow="device_code",
        profile_name=None,
    )

    def interrupt_commit() -> None:
        if signal_type is KeyboardInterrupt:
            raise KeyboardInterrupt
        raise SystemExit(exit_code)

    with pytest.raises(signal_type) as interrupted:
        service.commit_if_active(
            started.session_id,
            started.session,
            interrupt_commit,
        )

    if signal_type is SystemExit:
        assert interrupted.value.code == exit_code
    assert started.session["status"] == "error"
    assert started.session["error_code"] == "io_unavailable"
    assert started.session["_cancel_event"].is_set()
    assert started.session["_release_pending"] is False
    snapshot = accounts.get_account_snapshot(home=tmp_path, provider_id=provider_id)
    assert snapshot.oauth_lease is None
    assert snapshot.oauth_completion is None


def test_signal_cleanup_retains_exact_release_handle_when_storage_is_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="openai-codex",
        flow="device_code",
        profile_name=None,
    )
    lease = started.session["_lease_result"].lease
    release_keys: list[tuple[int, str, str]] = []

    def busy_release(**kwargs):
        release_keys.append((
            kwargs["generation"],
            kwargs["operation_id"],
            kwargs["store_instance_id"],
        ))
        raise accounts.ProviderAccountError(
            accounts.ProviderAccountErrorCode.LOCK_TIMEOUT
        )

    monkeypatch.setattr(accounts, "release_oauth_lease", busy_release)
    with pytest.raises(KeyboardInterrupt):
        service.commit_if_active(
            started.session_id,
            started.session,
            lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    expected_key = (lease.generation, lease.operation_id, lease.store_instance_id)
    assert release_keys == [expected_key, expected_key]
    assert started.session["status"] == "error"
    assert started.session["_release_pending"] is True
    assert started.session["_release_error_code"] == "lock_timeout"
    active = accounts.get_account_snapshot(
        home=tmp_path,
        provider_id="openai-codex",
    ).oauth_lease
    assert active is not None
    assert (active.generation, active.operation_id, active.store_instance_id) == (
        expected_key
    )


def test_process_control_stabilization_retains_handle_if_marking_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="xai-oauth",
        flow="device_code",
        profile_name=None,
    )
    monkeypatch.setattr(
        service,
        "_mark_failed_locked",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit(91)),
    )

    service.stabilize_worker_process_control(started.session_id)

    assert started.session["status"] == "error"
    assert started.session["error_code"] == "io_unavailable"
    assert started.session["_cancel_event"].is_set()
    assert started.session["_release_pending"] is True
    assert started.session["_release_error_code"] == "io_unavailable"
    assert (
        accounts.get_account_snapshot(
            home=tmp_path,
            provider_id="xai-oauth",
        ).oauth_lease
        is not None
    )


def test_credential_writer_exception_is_reduced_to_stable_session_error(
    tmp_path: Path,
) -> None:
    service = OAuthFlowService()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )

    assert not service.commit_if_active(
        started.session_id,
        started.session,
        lambda: (_ for _ in ()).throw(RuntimeError("raw credential/path sentinel")),
    )
    assert started.session["status"] == "error"
    assert started.session["error_code"] == "io_unavailable"
    assert started.session["error_message"] == (
        "OAuth provider or local credential storage is unavailable."
    )
    assert "sentinel" not in str(started.session)


def test_legacy_provider_lookup_requires_exact_owner(tmp_path: Path) -> None:
    service = OAuthFlowService()
    other = tmp_path / "other"
    other.mkdir()
    started = service.reserve_start(
        home=tmp_path,
        provider_id="nous",
        flow="device_code",
        profile_name=None,
    )

    assert (
        service.legacy_provider_for_owner(
            home=tmp_path,
            session_id=started.session_id,
        )
        == "nous"
    )
    with pytest.raises(OAuthFlowError) as mismatch:
        service.legacy_provider_for_owner(
            home=other,
            session_id=started.session_id,
        )
    assert mismatch.value.code is OAuthFlowErrorCode.NOT_FOUND
