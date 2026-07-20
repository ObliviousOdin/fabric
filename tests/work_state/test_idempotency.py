from __future__ import annotations

import pytest

from fabric_cli.work_ledger import (
    IdempotencyConflict,
    InvalidTransition,
    WorkLedger,
    WorkOperationInProgress,
    hash_job_create_envelope,
)


def test_idempotency_state_machine_only_replays_finalized_receipt(
    ledger: WorkLedger,
) -> None:
    operation = "job.cancel"
    key = "idempotency-state-000001"
    request_hash = hash_job_create_envelope(
        kind="background_prompt", title="Cancel envelope"
    )
    reserved = ledger.reserve_idempotency(
        operation=operation,
        idempotency_key=key,
        request_hash=request_hash,
        subject_id="job_subject_for_test",
    )
    assert reserved["state"] == "reserved"

    with pytest.raises(WorkOperationInProgress):
        ledger.reserve_idempotency(
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
        )
    delivering = ledger.transition_idempotency(
        operation=operation,
        idempotency_key=key,
        request_hash=request_hash,
        next_state="delivering",
    )
    assert delivering["state"] == "delivering"
    finalized = ledger.transition_idempotency(
        operation=operation,
        idempotency_key=key,
        request_hash=request_hash,
        next_state="finalized",
        response={"mutation_id": "mut_test", "delivered": True},
    )
    assert finalized["state"] == "finalized"

    replay = ledger.reserve_idempotency(
        operation=operation,
        idempotency_key=key,
        request_hash=request_hash,
    )
    assert replay == {
        "replayed": True,
        "receipt": {"delivered": True, "mutation_id": "mut_test"},
    }

    with pytest.raises(InvalidTransition):
        ledger.transition_idempotency(
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
            next_state="failed",
        )


def test_idempotency_changed_non_sensitive_hash_conflicts(
    ledger: WorkLedger,
) -> None:
    operation = "job.cancel"
    key = "idempotency-state-000002"
    first_hash = hash_job_create_envelope(kind="background_prompt", title="First")
    second_hash = hash_job_create_envelope(kind="background_prompt", title="Second")
    ledger.reserve_idempotency(
        operation=operation,
        idempotency_key=key,
        request_hash=first_hash,
    )

    with pytest.raises(IdempotencyConflict):
        ledger.reserve_idempotency(
            operation=operation,
            idempotency_key=key,
            request_hash=second_hash,
        )
