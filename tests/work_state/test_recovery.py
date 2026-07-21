from __future__ import annotations

import pytest

from fabric_cli.work_ledger import InvalidPublicData, RuntimeOwner, WorkLedger


def test_positive_dead_owner_reconciles_queued_run_and_pending_attention(
    ledger: WorkLedger, owner: RuntimeOwner, create_job
) -> None:
    job = create_job()["job"]
    attention = ledger.create_attention(
        source_session_key="session-key",
        request_id="recovery-request-0000001",
        kind="approval",
        title="Approve",
        public_payload={},
        owner=owner,
        waiter_generation="waiter-generation",
        job_id=job["job_id"],
        run_id=job["current_run"]["run_id"],
    )
    candidates = ledger.list_nonterminal_owners()
    assert candidates == [
        {"owner": owner, "run_count": 1, "attention_count": 1}
    ]

    result = ledger.reconcile_owner(owner, "dead")

    assert result == {
        "classification": "dead",
        "runs_reconciled": 1,
        "attention_reconciled": 1,
        "has_more": False,
    }
    interrupted = ledger.get_job(job["job_id"])
    assert interrupted["status"] == "interrupted"
    assert interrupted["error"]["code"] == "runner_never_started"
    assert interrupted["open_attention_count"] == 0
    orphaned = ledger.get_attention(attention["attention_id"])
    assert orphaned["state"] == "orphaned"
    assert orphaned["terminal_reason"] == "waiter_lost"
    assert ledger.list_nonterminal_owners() == []


def test_reconcile_resolving_attention_marks_receipt_uncertain_without_replay(
    ledger: WorkLedger, owner: RuntimeOwner, create_job
) -> None:
    job = create_job()["job"]
    job_id = job["job_id"]
    claimed = ledger.transition_job(job_id, expected_version=1, next_status="claimed")
    running = ledger.transition_job(
        job_id, expected_version=claimed["version"], next_status="running"
    )
    attention = ledger.create_attention(
        source_session_key="session-key",
        request_id="recovery-request-0000002",
        kind="secret",
        title="Secret",
        public_payload={"name": "TOKEN"},
        owner=owner,
        waiter_generation="waiter-generation",
        sensitive=True,
        job_id=job_id,
        run_id=running["current_run"]["run_id"],
    )
    claim = ledger.begin_attention_resolution(
        attention["attention_id"],
        expected_version=1,
        idempotency_key="recovery-response-0000001",
        kind="secret",
        action="submit",
        owner=owner,
        waiter_generation="waiter-generation",
    )
    assert claim.replayed is False

    ledger.reconcile_owner(owner, "pid_reused")

    orphaned = ledger.get_attention(attention["attention_id"])
    assert orphaned["state"] == "orphaned"
    assert orphaned["terminal_reason"] == "delivery_outcome_unknown"
    receipt = ledger.get_idempotency(
        operation="attention.respond",
        idempotency_key="recovery-response-0000001",
    )
    assert receipt["state"] == "uncertain"
    assert receipt["response"] is None
    interrupted = ledger.get_job(job_id)
    assert interrupted["status"] == "interrupted"
    assert interrupted["error"]["code"] == "runtime_owner_lost"


def test_cancel_requested_dead_owner_reconciles_to_cancelled(
    ledger: WorkLedger, owner: RuntimeOwner, create_job
) -> None:
    job = create_job()["job"]
    cancel_requested = ledger.transition_job(
        job["job_id"], expected_version=1, next_status="cancel_requested"
    )

    ledger.reconcile_owner(owner, "different_boot")

    cancelled = ledger.get_job(job["job_id"])
    assert cancelled["version"] == cancel_requested["version"] + 1
    assert cancelled["status"] == "cancelled"
    assert cancelled["error"]["code"] == "cancel_confirmed_owner_lost"


@pytest.mark.parametrize("classification", ["live", "owner_unverifiable", "stale"])
def test_reconcile_rejects_nonpositive_owner_evidence_without_mutation(
    ledger: WorkLedger,
    owner: RuntimeOwner,
    create_job,
    classification: str,
) -> None:
    job = create_job()["job"]

    with pytest.raises(InvalidPublicData):
        ledger.reconcile_owner(owner, classification)

    assert ledger.get_job(job["job_id"])["status"] == "queued"
    assert len(ledger.list_events()) == 1


def test_reconcile_exact_owner_does_not_touch_foreign_owner(
    ledger: WorkLedger, owner: RuntimeOwner, create_job
) -> None:
    foreign = RuntimeOwner(
        boot_token="foreign-boot",
        pid=owner.pid + 1,
        start_token="foreign-start",
        generation="foreign-generation",
    )
    local_job = create_job()["job"]
    foreign_job = create_job(owner=foreign)["job"]

    result = ledger.reconcile_owner(owner, "dead")

    assert result["runs_reconciled"] == 1
    assert ledger.get_job(local_job["job_id"])["status"] == "interrupted"
    assert ledger.get_job(foreign_job["job_id"])["status"] == "queued"


def test_running_job_without_attention_interrupts_under_dead_owner(
    ledger: WorkLedger, owner: RuntimeOwner, create_job
) -> None:
    """A plain running Run with no open Attention, owned by a proven-dead
    owner, reconciles to a truthful interrupted terminal state."""
    job = create_job()["job"]
    job_id = job["job_id"]
    claimed = ledger.transition_job(job_id, expected_version=1, next_status="claimed")
    ledger.transition_job(
        job_id, expected_version=claimed["version"], next_status="running"
    )
    assert ledger.list_nonterminal_owners() == [
        {"owner": owner, "run_count": 1, "attention_count": 0}
    ]

    result = ledger.reconcile_owner(owner, "dead")

    assert result["runs_reconciled"] == 1
    assert result["attention_reconciled"] == 0
    interrupted = ledger.get_job(job_id)
    assert interrupted["status"] == "interrupted"
    assert interrupted["error"]["code"] == "runtime_owner_lost"
    assert interrupted["open_attention_count"] == 0
    assert ledger.list_nonterminal_owners() == []
