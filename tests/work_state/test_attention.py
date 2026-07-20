from __future__ import annotations

import json
import sqlite3

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


def _mutation_snapshot(ledger: WorkLedger) -> tuple[list[tuple], list[tuple], list[tuple]]:
    conn = sqlite3.connect(ledger.path)
    try:
        attention = conn.execute(
            "SELECT attention_id, version, state, resolution_token, terminal_reason, "
            "updated_at, resolved_at FROM attention_items ORDER BY attention_id"
        ).fetchall()
        events = conn.execute(
            "SELECT event_id, event_type, subject_id, subject_version, subject_json "
            "FROM work_events ORDER BY event_id"
        ).fetchall()
        idempotency = conn.execute(
            "SELECT operation, idempotency_key, request_hash, state, subject_id, "
            "binding_json, response_json, created_at, updated_at "
            "FROM idempotency_keys ORDER BY operation, idempotency_key"
        ).fetchall()
    finally:
        conn.close()
    return attention, events, idempotency


def _open_attention(
    ledger: WorkLedger,
    owner: RuntimeOwner,
    *,
    request_id: str = "approval-request-00000001",
    kind: str = "approval",
    now: float | None = None,
) -> dict:
    return ledger.create_attention(
        source_session_key="source-session-key",
        runtime_session_id="runtime-session-id",
        request_id=request_id,
        kind=kind,
        title="Action required",
        public_payload={"description": "Run the reviewed command"},
        owner=owner,
        waiter_generation="waiter-generation",
        sensitive=kind in {"sudo", "secret"},
        now=now,
    )


def test_attention_transition_table_and_atomic_events(
    ledger: WorkLedger, owner: RuntimeOwner
) -> None:
    attention = _open_attention(ledger, owner)
    attention_id = attention["attention_id"]

    with pytest.raises(InvalidTransition):
        ledger.transition_attention(
            attention_id, expected_version=1, next_state="resolved"
        )
    assert ledger.get_attention(attention_id)["version"] == 1
    assert len(ledger.list_events()) == 1

    resolving = ledger.transition_attention(
        attention_id,
        expected_version=1,
        next_state="resolving",
        resolution_token="resolution-token",
    )
    resolved = ledger.transition_attention(
        attention_id, expected_version=2, next_state="resolved"
    )

    assert resolving["version"] == 2
    assert resolving["state"] == "resolving"
    assert resolved["version"] == 3
    assert resolved["state"] == "resolved"
    assert resolved["allowed_actions"] == []
    assert [event["subject_version"] for event in ledger.list_events()] == [1, 2, 3]

    with pytest.raises(InvalidTransition):
        ledger.transition_attention(
            attention_id, expected_version=3, next_state="orphaned"
        )


def test_attention_stale_version_and_wrong_owner_leave_item_pending(
    ledger: WorkLedger, owner: RuntimeOwner
) -> None:
    attention = _open_attention(ledger, owner)
    attention_id = attention["attention_id"]
    wrong_owner = RuntimeOwner(
        boot_token="other-boot",
        pid=owner.pid,
        start_token=owner.start_token,
        generation=owner.generation,
    )

    with pytest.raises(RuntimeOwnerMismatch):
        ledger.begin_attention_resolution(
            attention_id,
            expected_version=1,
            idempotency_key="attention-key-000000001",
            kind="approval",
            action="once",
            owner=wrong_owner,
            waiter_generation="waiter-generation",
        )
    with pytest.raises(VersionConflict):
        ledger.begin_attention_resolution(
            attention_id,
            expected_version=2,
            idempotency_key="attention-key-000000002",
            kind="approval",
            action="once",
            owner=owner,
            waiter_generation="waiter-generation",
        )

    assert ledger.get_attention(attention_id)["state"] == "pending"
    assert ledger.get_idempotency(
        operation="attention.respond", idempotency_key="attention-key-000000001"
    ) is None


@pytest.mark.parametrize(
    ("kind", "action"),
    [
        ("approval", "submit"),
        ("clarify", "once"),
        ("sudo", "always"),
        ("secret", "deny"),
    ],
)
def test_invalid_kind_action_is_rejected_without_any_durable_mutation(
    ledger: WorkLedger,
    owner: RuntimeOwner,
    kind: str,
    action: str,
) -> None:
    attention = _open_attention(ledger, owner, kind=kind)
    before = _mutation_snapshot(ledger)

    with pytest.raises(InvalidPublicData):
        ledger.begin_attention_resolution(
            attention["attention_id"],
            expected_version=1,
            idempotency_key=f"invalid-{kind}-action-0001",
            kind=kind,
            action=action,
            owner=owner,
            waiter_generation="waiter-generation",
        )

    assert _mutation_snapshot(ledger) == before


@pytest.mark.parametrize(
    ("kind", "action", "required_state", "inconsistent_state"),
    [
        ("approval", "once", "resolved", "denied"),
        ("approval", "deny", "denied", "resolved"),
        ("clarify", "submit", "resolved", "denied"),
        ("sudo", "cancel", "denied", "resolved"),
        ("secret", "submit", "resolved", "denied"),
    ],
)
def test_action_binding_rejects_inconsistent_finalize_without_mutation(
    ledger: WorkLedger,
    owner: RuntimeOwner,
    kind: str,
    action: str,
    required_state: str,
    inconsistent_state: str,
) -> None:
    attention = _open_attention(ledger, owner, kind=kind)
    key = f"binding-{kind}-{action}-000001"
    claim = ledger.begin_attention_resolution(
        attention["attention_id"],
        expected_version=1,
        idempotency_key=key,
        kind=kind,
        action=action,
        owner=owner,
        waiter_generation="waiter-generation",
    )
    conn = sqlite3.connect(ledger.path)
    try:
        binding_raw = conn.execute(
            "SELECT binding_json FROM idempotency_keys "
            "WHERE operation='attention.respond' AND idempotency_key=?",
            (key,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert json.loads(binding_raw) == {
        "action": action,
        "expected_version": 1,
        "kind": kind,
        "terminal_state": required_state,
    }
    before = _mutation_snapshot(ledger)

    with pytest.raises(InvalidTransition):
        ledger.finalize_attention_resolution(
            claim,
            state=inconsistent_state,
            delivered=True,
        )

    assert _mutation_snapshot(ledger) == before
    receipt = ledger.finalize_attention_resolution(
        claim,
        state=required_state,
        delivered=True,
    )
    assert receipt["state"] == required_state


def test_exact_attention_resolution_finalizes_sanitized_replay_once(
    ledger: WorkLedger, owner: RuntimeOwner
) -> None:
    attention = _open_attention(ledger, owner)
    attention_id = attention["attention_id"]
    key = "attention-key-000000003"
    claim = ledger.begin_attention_resolution(
        attention_id,
        expected_version=1,
        idempotency_key=key,
        kind="approval",
        action="once",
        owner=owner,
        waiter_generation="waiter-generation",
    )
    in_flight_retry = ledger.begin_attention_resolution(
        attention_id,
        expected_version=1,
        idempotency_key=key,
        kind="approval",
        action="once",
        owner=owner,
        waiter_generation="waiter-generation",
    )
    assert in_flight_retry.resolution_token == claim.resolution_token
    assert in_flight_retry.attention_version == claim.attention_version
    receipt = ledger.finalize_attention_resolution(
        claim, state="resolved", delivered=True
    )

    assert claim.replayed is False
    assert receipt["attention_id"] == attention_id
    assert receipt["attention_version"] == 3
    assert receipt["state"] == "resolved"
    assert receipt["delivered"] is True
    assert "value" not in receipt

    replay_claim = ledger.begin_attention_resolution(
        attention_id,
        expected_version=1,
        idempotency_key=key,
        kind="approval",
        action="once",
        owner=owner,
        waiter_generation="waiter-generation",
    )
    before_inconsistent_replay = _mutation_snapshot(ledger)
    with pytest.raises(InvalidTransition):
        ledger.finalize_attention_resolution(
            replay_claim, state="denied", delivered=True
        )
    assert _mutation_snapshot(ledger) == before_inconsistent_replay
    replay = ledger.finalize_attention_resolution(
        replay_claim, state="resolved", delivered=True
    )
    assert replay_claim.replayed is True
    assert replay["mutation_id"] == receipt["mutation_id"]
    assert replay["replayed"] is True
    assert len(ledger.list_events()) == 3

    with pytest.raises(IdempotencyConflict):
        ledger.begin_attention_resolution(
            attention_id,
            expected_version=1,
            idempotency_key=key,
            kind="approval",
            action="deny",
            owner=owner,
            waiter_generation="waiter-generation",
        )


def test_attention_clock_rollback_keeps_final_receipt_with_terminal_state(
    ledger: WorkLedger, owner: RuntimeOwner
) -> None:
    created_at = 100_000.0
    attention = _open_attention(ledger, owner, now=created_at)
    key = "attention-clock-receipt-0001"
    claim = ledger.begin_attention_resolution(
        attention["attention_id"],
        expected_version=1,
        idempotency_key=key,
        kind="approval",
        action="once",
        owner=owner,
        waiter_generation="waiter-generation",
        now=1_000.0,
    )
    ledger.finalize_attention_resolution(
        claim,
        state="resolved",
        delivered=True,
        now=1_001.0,
    )

    conn = sqlite3.connect(ledger.path)
    try:
        receipt_times = conn.execute(
            "SELECT created_at, updated_at FROM idempotency_keys "
            "WHERE operation='attention.respond' AND idempotency_key=?",
            (key,),
        ).fetchone()
        assert receipt_times == (created_at, created_at)
    finally:
        conn.close()

    retained = ledger.run_retention(
        now=created_at + 29 * 24 * 60 * 60,
        retention_seconds=30 * 24 * 60 * 60,
        subject_batch_size=1,
    )
    assert retained["attention_deleted"] == 0
    assert retained["idempotency_deleted"] == 0
    assert ledger.get_attention(attention["attention_id"])["state"] == "resolved"
    assert ledger.get_idempotency(
        operation="attention.respond", idempotency_key=key
    )["state"] == "finalized"


def test_resolving_waiter_teardown_atomically_orphans_and_uncertains_receipt(
    ledger: WorkLedger,
    owner: RuntimeOwner,
) -> None:
    attention = _open_attention(ledger, owner, kind="clarify")
    key = "attention-teardown-key-0001"
    ledger.begin_attention_resolution(
        attention["attention_id"],
        expected_version=1,
        idempotency_key=key,
        kind="clarify",
        action="submit",
        owner=owner,
        waiter_generation="waiter-generation",
    )

    orphaned = ledger.terminate_attention_waiter(
        attention["attention_id"],
        expected_version=2,
        owner=owner,
        waiter_generation="waiter-generation",
        terminal_reason="session_closed",
    )

    assert orphaned["state"] == "orphaned"
    assert orphaned["terminal_reason"] == "session_closed"
    receipt = ledger.get_idempotency(
        operation="attention.respond",
        idempotency_key=key,
    )
    assert receipt is not None
    assert receipt["state"] == "uncertain"
    assert receipt["response"] is None


def test_secret_response_value_never_enters_ledger_hash_receipt_or_wal(
    ledger: WorkLedger, owner: RuntimeOwner
) -> None:
    sentinel = "FMB002_SECRET_SENTINEL_DO_NOT_PERSIST"
    attention = _open_attention(
        ledger,
        owner,
        request_id="secret-request-0000000001",
        kind="secret",
    )
    claim = ledger.begin_attention_resolution(
        attention["attention_id"],
        expected_version=1,
        idempotency_key="attention-key-000000004",
        kind="secret",
        action="submit",
        owner=owner,
        waiter_generation="waiter-generation",
    )
    # ``sentinel`` is delivered by WorkService directly to its waiter.  No
    # work-ledger API accepts it, its hash, or an encrypted form.
    assert sentinel
    ledger.finalize_attention_resolution(claim, state="resolved", delivered=True)

    conn = sqlite3.connect(ledger.path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    assert sentinel.encode() not in ledger.path.read_bytes()
    wal = ledger.path.with_name(ledger.path.name + "-wal")
    if wal.exists():
        assert sentinel.encode() not in wal.read_bytes()
    receipt = ledger.get_idempotency(
        operation="attention.respond",
        idempotency_key="attention-key-000000004",
    )
    assert sentinel not in repr(receipt)


def test_attention_terminal_transition_updates_job_count_and_version(
    ledger: WorkLedger,
    owner: RuntimeOwner,
    create_job,
) -> None:
    job = create_job()["job"]
    attention = ledger.create_attention(
        source_session_key="source-session-key",
        request_id="job-attention-0000000001",
        kind="clarify",
        title="Need detail",
        public_payload={"question": "Which target?"},
        owner=owner,
        waiter_generation="waiter-generation",
        job_id=job["job_id"],
        run_id=job["current_run"]["run_id"],
    )
    after_open = ledger.get_job(job["job_id"])
    assert after_open["open_attention_count"] == 1
    assert after_open["version"] == 2

    ledger.transition_attention(
        attention["attention_id"],
        expected_version=1,
        next_state="cancelled",
        terminal_reason="session_closed",
    )
    after_close = ledger.get_job(job["job_id"])
    assert after_close["open_attention_count"] == 0
    assert after_close["version"] == 3
    assert [event["subject_type"] for event in ledger.list_events()] == [
        "job",
        "attention",
        "job",
        "attention",
        "job",
    ]
