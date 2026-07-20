from __future__ import annotations

import sqlite3
import threading
from typing import Callable

import pytest

from fabric_cli.work_ledger import (
    IdempotencyConflict,
    InvalidPublicData,
    InvalidTransition,
    RuntimeOwner,
    RuntimeOwnerMismatch,
    VersionConflict,
    WorkLedger,
)


def test_create_job_commits_run_receipt_and_self_contained_event(
    ledger: WorkLedger,
    create_job: Callable[..., dict],
) -> None:
    receipt = create_job(title="Compile the release")

    assert receipt["mutation_id"].startswith("mut_")
    assert receipt["replayed"] is False
    job = receipt["job"]
    assert job["job_id"].startswith("job_")
    assert job["status"] == "queued"
    assert job["version"] == 1
    assert job["current_run"]["run_id"].startswith("run_")
    assert job["current_run"]["status"] == "queued"
    assert job["current_run"]["restart_behavior"] == "interrupt"

    events = ledger.list_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "job.created"
    assert events[0]["subject"] == job
    assert events[0]["subject_version"] == job["version"]
    assert events[0]["tombstone"] is False

    conn = sqlite3.connect(ledger.path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_job_create_hash_excludes_prompt_preview_and_replays_first_receipt(
    ledger: WorkLedger,
    owner: RuntimeOwner,
) -> None:
    params = {
        "kind": "background_prompt",
        "title": "Same public intent",
        "source": "mobile",
        "owner": owner,
        "idempotency_key": "same-create-key-00000001",
        "runtime_summary": {"kind": "in_process_agent"},
        "run_runtime": {"kind": "in_process_agent"},
    }
    first = ledger.create_job(**params, prompt_preview="first redacted preview")
    replay = ledger.create_job(**params, prompt_preview="different raw-derived preview")

    assert replay["replayed"] is True
    assert replay["mutation_id"] == first["mutation_id"]
    assert replay["job"] == first["job"]
    assert len(ledger.list_jobs()) == 1
    assert len(ledger.list_events()) == 1
    assert ledger.get_job(first["job"]["job_id"])["prompt_preview"] == "first redacted preview"


def test_job_create_changed_public_envelope_conflicts_without_second_row(
    ledger: WorkLedger,
    owner: RuntimeOwner,
) -> None:
    params = {
        "kind": "background_prompt",
        "source": "mobile",
        "owner": owner,
        "idempotency_key": "same-create-key-00000002",
        "runtime_summary": {},
        "run_runtime": {},
    }
    ledger.create_job(**params, title="First title")

    with pytest.raises(IdempotencyConflict):
        ledger.create_job(**params, title="Changed title")

    assert len(ledger.list_jobs()) == 1
    assert len(ledger.list_events()) == 1


def test_job_transition_is_strict_and_versions_job_run_event_together(
    ledger: WorkLedger,
    create_job: Callable[..., dict],
) -> None:
    created = create_job()["job"]
    job_id = created["job_id"]

    with pytest.raises(InvalidTransition):
        ledger.transition_job(job_id, expected_version=1, next_status="succeeded")
    assert ledger.get_job(job_id)["version"] == 1
    assert len(ledger.list_events()) == 1

    claimed = ledger.transition_job(
        job_id,
        expected_version=1,
        next_status="claimed",
        claim_token="claim-token",
    )
    running = ledger.transition_job(
        job_id, expected_version=2, next_status="running"
    )
    succeeded = ledger.transition_job(
        job_id,
        expected_version=3,
        next_status="succeeded",
        result={"answer": 42},
    )

    assert claimed["version"] == 2
    assert running["version"] == 3
    assert succeeded["version"] == 4
    assert succeeded["status"] == "succeeded"
    assert succeeded["current_run"]["version"] == 4
    assert succeeded["current_run"]["status"] == "succeeded"
    assert ledger.get_job(job_id)["result"] == {"answer": 42}
    events = ledger.list_events()
    assert [event["subject_version"] for event in events] == [1, 2, 3, 4]
    assert [event["subject"]["status"] for event in events] == [
        "queued",
        "claimed",
        "running",
        "succeeded",
    ]

    with pytest.raises(InvalidTransition):
        ledger.transition_job(job_id, expected_version=4, next_status="running")


def test_stale_job_cas_appends_no_event(
    ledger: WorkLedger,
    create_job: Callable[..., dict],
) -> None:
    job_id = create_job()["job"]["job_id"]
    ledger.transition_job(job_id, expected_version=1, next_status="claimed")

    with pytest.raises(VersionConflict):
        ledger.transition_job(job_id, expected_version=1, next_status="claimed")

    assert ledger.get_job(job_id)["version"] == 2
    assert len(ledger.list_events()) == 2


def test_tainted_result_body_is_structurally_omitted(
    ledger: WorkLedger,
    create_job: Callable[..., dict],
) -> None:
    job_id = create_job()["job"]["job_id"]
    ledger.transition_job(job_id, expected_version=1, next_status="claimed")
    running = ledger.transition_job(job_id, expected_version=2, next_status="running")
    with pytest.raises(InvalidPublicData):
        ledger.transition_job(
            job_id,
            expected_version=running["version"],
            next_status="waiting_attention",
            result={"must_not": "persist early"},
        )
    terminal = ledger.transition_job(
        job_id,
        expected_version=3,
        next_status="succeeded",
        result_omitted_reason="sensitive_input",
    )

    assert terminal["result_preview"] is None
    assert terminal["result_omitted_reason"] == "sensitive_input"
    detail = ledger.get_job(job_id)
    assert detail["result"] is None
    assert detail["result_omitted_reason"] == "sensitive_input"


def test_cancel_job_commits_cas_event_and_receipt_atomically(
    ledger: WorkLedger,
    owner: RuntimeOwner,
    create_job: Callable[..., dict],
) -> None:
    job = create_job()["job"]
    key = "atomic-cancel-key-000001"

    first = ledger.cancel_job(
        job["job_id"],
        expected_version=1,
        idempotency_key=key,
        owner=owner,
    )
    replay = ledger.cancel_job(
        job["job_id"],
        expected_version=1,
        idempotency_key=key,
        owner=owner,
    )

    assert first["job"]["status"] == "cancel_requested"
    assert first["job"]["version"] == 2
    assert first["job"]["current_run"]["status"] == "cancel_requested"
    assert replay == {**first, "replayed": True}
    assert [event["event_type"] for event in ledger.list_events()] == [
        "job.created",
        "job.cancel_requested",
    ]
    idempotency = ledger.get_idempotency(
        operation="job.cancel",
        idempotency_key=key,
    )
    assert idempotency["state"] == "finalized"
    assert idempotency["response"] == first

    with pytest.raises(IdempotencyConflict):
        ledger.cancel_job(
            job["job_id"],
            expected_version=2,
            idempotency_key=key,
            owner=owner,
        )


def test_cancel_job_wrong_owner_or_event_failure_rolls_back_every_table(
    ledger: WorkLedger,
    owner: RuntimeOwner,
    create_job: Callable[..., dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = create_job()["job"]
    wrong_owner = RuntimeOwner(
        boot_token=owner.boot_token,
        pid=owner.pid,
        start_token=owner.start_token,
        generation="foreign-generation",
    )
    before = ledger.get_job(job["job_id"])
    before_events = ledger.list_events()

    with pytest.raises(RuntimeOwnerMismatch):
        ledger.cancel_job(
            job["job_id"],
            expected_version=1,
            idempotency_key="wrong-owner-cancel-key-01",
            owner=wrong_owner,
        )
    assert ledger.get_job(job["job_id"]) == before
    assert ledger.list_events() == before_events
    assert ledger.get_idempotency(
        operation="job.cancel",
        idempotency_key="wrong-owner-cancel-key-01",
    ) is None

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("simulated event append failure")

    monkeypatch.setattr(ledger, "_append_event", fail_event)
    with pytest.raises(RuntimeError, match="simulated event append failure"):
        ledger.cancel_job(
            job["job_id"],
            expected_version=1,
            idempotency_key="rollback-cancel-key-0001",
            owner=owner,
        )
    assert ledger.get_job(job["job_id"]) == before
    assert ledger.list_events() == before_events
    assert ledger.get_idempotency(
        operation="job.cancel",
        idempotency_key="rollback-cancel-key-0001",
    ) is None


@pytest.mark.parametrize("completion_first", [True, False])
def test_cancel_and_completion_race_returns_one_stable_terminal_receipt(
    ledger: WorkLedger,
    owner: RuntimeOwner,
    create_job: Callable[..., dict],
    completion_first: bool,
) -> None:
    job = create_job()["job"]
    job_id = job["job_id"]
    ledger.transition_job(
        job_id,
        expected_version=1,
        next_status="claimed",
        claim_token="race-claim",
    )
    ledger.transition_job(job_id, expected_version=2, next_status="running")
    start = threading.Barrier(3)
    winner_done = threading.Event()
    cancel_results: list[dict] = []
    completion_results: list[dict] = []
    completion_errors: list[BaseException] = []

    def complete() -> None:
        start.wait()
        if not completion_first:
            assert winner_done.wait(timeout=5)
        try:
            completion_results.append(
                ledger.transition_job(
                    job_id,
                    expected_version=3,
                    next_status="succeeded",
                    result={"completed": True},
                )
            )
        except BaseException as exc:
            completion_errors.append(exc)
        finally:
            if completion_first:
                winner_done.set()

    def cancel() -> None:
        start.wait()
        if completion_first:
            assert winner_done.wait(timeout=5)
        try:
            cancel_results.append(
                ledger.cancel_job(
                    job_id,
                    expected_version=3,
                    idempotency_key=f"cancel-complete-race-{completion_first}",
                    owner=owner,
                )
            )
        finally:
            if not completion_first:
                winner_done.set()

    completion_thread = threading.Thread(target=complete)
    cancel_thread = threading.Thread(target=cancel)
    completion_thread.start()
    cancel_thread.start()
    start.wait()
    completion_thread.join(timeout=5)
    cancel_thread.join(timeout=5)

    assert not completion_thread.is_alive() and not cancel_thread.is_alive()
    assert len(cancel_results) == 1
    receipt = cancel_results[0]
    if completion_first:
        assert completion_errors == []
        assert len(completion_results) == 1
        assert receipt["newly_cancelled"] is False
        assert receipt["job"]["status"] == "succeeded"
        assert ledger.get_job(job_id)["status"] == "succeeded"
    else:
        assert completion_results == []
        assert len(completion_errors) == 1
        assert isinstance(completion_errors[0], VersionConflict)
        assert receipt["newly_cancelled"] is True
        assert receipt["job"]["status"] == "cancel_requested"
        assert ledger.get_job(job_id)["status"] == "cancel_requested"
    idempotency = ledger.get_idempotency(
        operation="job.cancel",
        idempotency_key=f"cancel-complete-race-{completion_first}",
    )
    assert idempotency is not None and idempotency["state"] == "finalized"
