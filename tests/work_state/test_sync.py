from __future__ import annotations

import sqlite3
import time

import pytest

from fabric_cli.work_ledger import (
    CursorExpired,
    WorkLedger,
    WorkNotFound,
    WorkStoreReplacedError,
    VersionConflict,
    new_work_id,
)


def test_delta_sync_uses_fixed_watermark_and_count_pages(
    ledger: WorkLedger, create_job
) -> None:
    jobs = [create_job()["job"] for _ in range(3)]

    first = ledger.sync_delta(ledger_id=ledger.ledger_id, after=0, limit=2)
    assert first["mode"] == "delta"
    assert first["watermark"] == 3
    assert first["cursor"] == 2
    assert first["has_more"] is True
    assert [event["subject_id"] for event in first["events"]] == [
        jobs[0]["job_id"],
        jobs[1]["job_id"],
    ]

    second = ledger.sync_delta(
        ledger_id=ledger.ledger_id, after=first["cursor"], limit=2
    )
    assert second["watermark"] == 3
    assert second["cursor"] == 3
    assert second["has_more"] is False
    assert [event["subject_id"] for event in second["events"]] == [
        jobs[2]["job_id"]
    ]


def test_delta_rejects_wrong_newer_and_pruned_cursors(
    ledger: WorkLedger, create_job
) -> None:
    create_job()
    with pytest.raises(CursorExpired):
        ledger.sync_delta(ledger_id=new_work_id("ledger"), after=0)
    with pytest.raises(CursorExpired):
        ledger.sync_delta(ledger_id=ledger.ledger_id, after=2)

    result = ledger.run_retention(
        now=time.time() + 31 * 24 * 60 * 60,
        retention_seconds=30 * 24 * 60 * 60,
    )
    assert result["events_deleted"] == 1
    assert result["event_floor"] == 2
    # The Job is still queued, so its finalized create receipt remains within
    # the dedupe horizon regardless of age.
    conn = sqlite3.connect(ledger.path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0] == 1
    finally:
        conn.close()
    with pytest.raises(CursorExpired):
        ledger.sync_delta(ledger_id=ledger.ledger_id, after=0)
    current = ledger.sync_delta(ledger_id=ledger.ledger_id, after=1)
    assert current["cursor"] == 1
    assert current["events"] == []


def test_retention_tombstones_old_terminal_subjects_before_deleting_them(
    ledger: WorkLedger, create_job, owner
) -> None:
    created_at = 1_000.0
    retained_at = created_at + 31 * 24 * 60 * 60
    job = create_job(now=created_at)["job"]
    job_id = job["job_id"]
    claimed = ledger.transition_job(
        job_id,
        expected_version=1,
        next_status="claimed",
        now=created_at,
    )
    running = ledger.transition_job(
        job_id,
        expected_version=claimed["version"],
        next_status="running",
        now=created_at,
    )
    ledger.transition_job(
        job_id,
        expected_version=running["version"],
        next_status="succeeded",
        now=created_at,
    )
    attention = ledger.create_attention(
        source_session_key="retention-session",
        runtime_session_id="retention-runtime",
        request_id="retention-attention-0001",
        kind="approval",
        title="Old approval",
        public_payload={"description": "reviewed action"},
        owner=owner,
        waiter_generation="retention-waiter",
        now=created_at,
    )
    resolving = ledger.transition_attention(
        attention["attention_id"],
        expected_version=1,
        next_state="resolving",
        resolution_token="retention-token",
        now=created_at,
    )
    ledger.transition_attention(
        attention["attention_id"],
        expected_version=resolving["version"],
        next_state="resolved",
        now=created_at,
    )
    old_cursor = ledger.cursor_state()["high_water"]

    result = ledger.run_retention(
        now=retained_at,
        retention_seconds=30 * 24 * 60 * 60,
        event_batch_size=100,
        idempotency_batch_size=100,
        subject_batch_size=10,
    )

    assert result["jobs_deleted"] == 1
    assert result["attention_deleted"] == 1
    assert result["events_deleted"] == old_cursor
    with pytest.raises(WorkNotFound):
        ledger.get_job(job_id)
    with pytest.raises(WorkNotFound):
        ledger.get_attention(attention["attention_id"])
    delta = ledger.sync_delta(ledger_id=ledger.ledger_id, after=old_cursor)
    assert {event["event_type"] for event in delta["events"]} == {
        "job.deleted",
        "attention.deleted",
    }
    assert all(event["tombstone"] is True for event in delta["events"])
    assert ledger.bootstrap_snapshot()["jobs"] == []
    assert ledger.bootstrap_snapshot()["attention"] == []
    with pytest.raises(CursorExpired):
        ledger.sync_delta(ledger_id=ledger.ledger_id, after=0)


def test_retention_preserves_old_nonterminal_subjects_and_receipts(
    ledger: WorkLedger, create_job, owner
) -> None:
    created_at = 1_000.0
    retained_at = created_at + 31 * 24 * 60 * 60
    job = create_job(now=created_at)["job"]
    attention = ledger.create_attention(
        source_session_key="retention-session",
        runtime_session_id="retention-runtime",
        request_id="retention-pending-000001",
        kind="approval",
        title="Pending approval",
        public_payload={"description": "reviewed action"},
        owner=owner,
        waiter_generation="retention-waiter",
        job_id=job["job_id"],
        run_id=job["current_run"]["run_id"],
        now=created_at,
    )

    result = ledger.run_retention(
        now=retained_at,
        retention_seconds=30 * 24 * 60 * 60,
        event_batch_size=100,
        idempotency_batch_size=100,
        subject_batch_size=10,
    )

    assert result["jobs_deleted"] == 0
    assert result["attention_deleted"] == 0
    assert ledger.get_job(job["job_id"])["status"] == "queued"
    assert ledger.get_attention(attention["attention_id"])["state"] == "pending"
    conn = sqlite3.connect(ledger.path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_retention_subject_batch_is_bounded(ledger: WorkLedger, owner) -> None:
    created_at = 1_000.0
    retained_at = created_at + 31 * 24 * 60 * 60
    attention_ids: list[str] = []
    for number in range(2):
        attention = ledger.create_attention(
            source_session_key=f"retention-session-{number}",
            runtime_session_id="retention-runtime",
            request_id=f"retention-batch-{number:08d}",
            kind="approval",
            title="Old approval",
            public_payload={"description": "reviewed action"},
            owner=owner,
            waiter_generation=f"retention-waiter-{number}",
            now=created_at,
        )
        resolving = ledger.transition_attention(
            attention["attention_id"],
            expected_version=1,
            next_state="resolving",
            resolution_token=f"retention-token-{number}",
            now=created_at,
        )
        ledger.transition_attention(
            attention["attention_id"],
            expected_version=resolving["version"],
            next_state="resolved",
            now=created_at,
        )
        attention_ids.append(attention["attention_id"])

    first = ledger.run_retention(
        now=retained_at,
        retention_seconds=30 * 24 * 60 * 60,
        event_batch_size=100,
        subject_batch_size=1,
    )
    assert first["attention_deleted"] == 1
    remaining: list[str] = []
    for attention_id in attention_ids:
        try:
            attention = ledger.get_attention(attention_id)
        except WorkNotFound:
            continue
        assert attention["state"] == "resolved"
        remaining.append(attention_id)
    assert len(remaining) == 1
    second = ledger.run_retention(
        now=retained_at,
        retention_seconds=30 * 24 * 60 * 60,
        event_batch_size=100,
        subject_batch_size=1,
    )
    assert second["attention_deleted"] == 1
    for attention_id in attention_ids:
        with pytest.raises(WorkNotFound):
            ledger.get_attention(attention_id)


def test_retention_merges_subject_types_so_attention_cannot_starve_jobs(
    ledger: WorkLedger, create_job, owner
) -> None:
    job_created_at = 1_000.0
    job = create_job(now=job_created_at)["job"]
    claimed = ledger.transition_job(
        job["job_id"], expected_version=1, next_status="claimed", now=job_created_at
    )
    running = ledger.transition_job(
        job["job_id"],
        expected_version=claimed["version"],
        next_status="running",
        now=job_created_at,
    )
    ledger.transition_job(
        job["job_id"],
        expected_version=running["version"],
        next_status="succeeded",
        now=job_created_at,
    )

    # Simulate a continuous stream of expired standalone Attention.  The
    # already-older Job must still be selected even when the total subject
    # budget is one.
    attention_created_at = 2_000.0
    attention = ledger.create_attention(
        source_session_key="retention-fairness-session",
        runtime_session_id="retention-fairness-runtime",
        request_id="retention-fairness-0001",
        kind="approval",
        title="Later approval",
        public_payload={"description": "reviewed action"},
        owner=owner,
        waiter_generation="retention-fairness-waiter",
        now=attention_created_at,
    )
    resolving = ledger.transition_attention(
        attention["attention_id"],
        expected_version=1,
        next_state="resolving",
        resolution_token="retention-fairness-token",
        now=attention_created_at,
    )
    ledger.transition_attention(
        attention["attention_id"],
        expected_version=resolving["version"],
        next_state="resolved",
        now=attention_created_at,
    )

    result = ledger.run_retention(
        now=job_created_at + 31 * 24 * 60 * 60,
        retention_seconds=30 * 24 * 60 * 60,
        event_batch_size=100,
        subject_batch_size=1,
    )

    assert result["jobs_deleted"] == 1
    assert result["attention_deleted"] == 0
    with pytest.raises(WorkNotFound):
        ledger.get_job(job["job_id"])
    assert ledger.get_attention(attention["attention_id"])["state"] == "resolved"


def test_retention_uses_attention_terminal_time_not_creation_time(
    ledger: WorkLedger, owner
) -> None:
    attention = ledger.create_attention(
        source_session_key="retention-terminal-time-session",
        runtime_session_id="retention-terminal-time-runtime",
        request_id="retention-terminal-time-0001",
        kind="approval",
        title="Long-lived approval",
        public_payload={"description": "reviewed action"},
        owner=owner,
        waiter_generation="retention-terminal-time-waiter",
        now=1_000.0,
    )
    terminal_at = 100_000_000.0
    resolving = ledger.transition_attention(
        attention["attention_id"],
        expected_version=1,
        next_state="resolving",
        resolution_token="retention-terminal-time-token",
        now=terminal_at,
    )
    ledger.transition_attention(
        attention["attention_id"],
        expected_version=resolving["version"],
        next_state="resolved",
        now=terminal_at,
    )

    still_fresh = ledger.run_retention(
        now=terminal_at + 29 * 24 * 60 * 60,
        retention_seconds=30 * 24 * 60 * 60,
        subject_batch_size=1,
    )
    assert still_fresh["attention_deleted"] == 0
    assert ledger.get_attention(attention["attention_id"])["state"] == "resolved"

    expired = ledger.run_retention(
        now=terminal_at + 31 * 24 * 60 * 60,
        retention_seconds=30 * 24 * 60 * 60,
        subject_batch_size=1,
    )
    assert expired["attention_deleted"] == 1
    with pytest.raises(WorkNotFound):
        ledger.get_attention(attention["attention_id"])


def test_attention_clock_rollback_is_clamped_before_terminal_retention(
    ledger: WorkLedger, owner
) -> None:
    created_at = 100_000.0
    attention = ledger.create_attention(
        source_session_key="retention-clock-session",
        runtime_session_id="retention-clock-runtime",
        request_id="retention-clock-rollback-0001",
        kind="approval",
        title="Clock-safe approval",
        public_payload={"description": "reviewed action"},
        owner=owner,
        waiter_generation="retention-clock-waiter",
        now=created_at,
    )
    resolving = ledger.transition_attention(
        attention["attention_id"],
        expected_version=1,
        next_state="resolving",
        resolution_token="retention-clock-token",
        now=1_000.0,
    )
    terminal = ledger.transition_attention(
        attention["attention_id"],
        expected_version=resolving["version"],
        next_state="resolved",
        now=1_001.0,
    )

    assert resolving["updated_at"] == int(created_at * 1000)
    assert terminal["updated_at"] == int(created_at * 1000)
    assert terminal["resolved_at"] == int(created_at * 1000)

    still_fresh = ledger.run_retention(
        now=created_at + 29 * 24 * 60 * 60,
        retention_seconds=30 * 24 * 60 * 60,
        subject_batch_size=1,
    )
    assert still_fresh["attention_deleted"] == 0
    assert ledger.get_attention(attention["attention_id"])["state"] == "resolved"


def test_retention_candidate_plans_are_indexed_and_bounded_at_10k_rows(
    ledger: WorkLedger,
) -> None:
    """Keep retention candidate walks out of full-backlog sort/materialization."""

    conn = sqlite3.connect(ledger.path)
    try:
        conn.executemany(
            "INSERT INTO attention_items("
            "attention_id, version, job_id, run_id, source_session_key, runtime_session_id, "
            "request_id, kind, state, blocking, sensitive, title, public_payload_json, "
            "owner_boot_token, owner_pid, owner_start_token, owner_generation, "
            "waiter_generation, resolution_token, terminal_reason, created_at, updated_at, "
            "expires_at, resolved_at"
            ") VALUES (?, 1, NULL, NULL, 'retention-plan-session', 'retention-plan-runtime', "
            "?, 'approval', 'resolved', 0, 0, 'Old approval', '{}', 'boot', 1, 'start', "
            "'generation', 'waiter', NULL, NULL, 100000.0, 1000.0, NULL, 1000.0)",
            (
                (f"attn_{number:032x}", f"retention-plan-{number:08d}")
                for number in range(10_000)
            ),
        )
        conn.commit()

        attention_sql = (
            "SELECT attention_id, version, state, job_id, run_id, "
            "COALESCE(resolved_at, updated_at) AS eligible_at "
            "FROM attention_items WHERE state=? "
            "AND COALESCE(resolved_at, updated_at)<? "
            "ORDER BY COALESCE(resolved_at, updated_at), attention_id LIMIT ?"
        )
        job_sql = (
            "SELECT job_id, version, status, current_run_id, finished_at AS eligible_at "
            "FROM jobs j WHERE j.status=? AND j.finished_at<? "
            "AND NOT EXISTS (SELECT 1 FROM attention_items a WHERE a.job_id=j.job_id) "
            "AND NOT EXISTS (SELECT 1 FROM job_runs r WHERE r.job_id=j.job_id "
            "AND r.status NOT IN (?,?,?,?)) "
            "ORDER BY j.finished_at, j.job_id LIMIT ?"
        )
        idempotency_sql = (
            "SELECT operation, idempotency_key, updated_at FROM idempotency_keys "
            "WHERE state=? AND updated_at<? "
            "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.job_id=subject_id "
            "AND j.status NOT IN (?,?,?,?)) "
            "AND NOT EXISTS (SELECT 1 FROM attention_items a WHERE a.attention_id=subject_id "
            "AND a.state IN ('pending','resolving')) "
            "ORDER BY updated_at, idempotency_key LIMIT ?"
        )
        terminal_states = ("cancelled", "failed", "interrupted", "succeeded")
        plans = {
            "attention": "\n".join(
                str(row[3])
                for row in conn.execute(
                    "EXPLAIN QUERY PLAN " + attention_sql,
                    ("resolved", 2_000.0, 7),
                )
            ),
            "job": "\n".join(
                str(row[3])
                for row in conn.execute(
                    "EXPLAIN QUERY PLAN " + job_sql,
                    ("succeeded", 2_000.0, *terminal_states, 7),
                )
            ),
            "idempotency": "\n".join(
                str(row[3])
                for row in conn.execute(
                    "EXPLAIN QUERY PLAN " + idempotency_sql,
                    ("finalized", 2_000.0, *terminal_states, 7),
                )
            ),
        }
        assert "USING INDEX idx_attention_state_terminal_time" in plans["attention"]
        assert "USING INDEX idx_jobs_terminal_finished" in plans["job"]
        assert "USING INDEX idx_idempotency_state_updated" in plans["idempotency"]
        assert all("USE TEMP B-TREE" not in plan for plan in plans.values())

        steps = 0

        def count_steps() -> int:
            nonlocal steps
            steps += 1
            return 0

        conn.set_progress_handler(count_steps, 1)
        rows = conn.execute(attention_sql, ("resolved", 2_000.0, 7)).fetchall()
        conn.set_progress_handler(None, 0)
        assert len(rows) == 7
        # The direct fixture models a skewed legacy/corrupt row that the
        # public state machine no longer writes. It proves retention never
        # restores an unindexed creation-time residual predicate: the indexed
        # LIMIT walk stays proportional to seven returned rows, not 10,000.
        assert steps < 1_000
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def test_terminal_attention_tombstone_uses_exact_version(
    ledger: WorkLedger, owner
) -> None:
    attention = ledger.create_attention(
        source_session_key="retention-session",
        runtime_session_id="retention-runtime",
        request_id="retention-cas-00000001",
        kind="approval",
        title="Old approval",
        public_payload={"description": "reviewed action"},
        owner=owner,
        waiter_generation="retention-waiter",
    )
    resolving = ledger.transition_attention(
        attention["attention_id"],
        expected_version=1,
        next_state="resolving",
        resolution_token="retention-token",
    )
    terminal = ledger.transition_attention(
        attention["attention_id"],
        expected_version=resolving["version"],
        next_state="resolved",
    )

    with pytest.raises(VersionConflict):
        ledger.tombstone_terminal_attention(
            attention["attention_id"],
            expected_version=terminal["version"] - 1,
        )
    assert ledger.tombstone_terminal_attention(
        attention["attention_id"],
        expected_version=terminal["version"],
    ) == {"attention_deleted": 1}
    with pytest.raises(WorkNotFound):
        ledger.get_attention(attention["attention_id"])
    tombstone = ledger.list_events()[-1]
    assert tombstone["event_type"] == "attention.deleted"
    assert tombstone["tombstone"] is True


def test_bootstrap_snapshot_captures_current_projection_and_watermark(
    ledger: WorkLedger, create_job
) -> None:
    job = create_job()["job"]
    ledger.transition_job(job["job_id"], expected_version=1, next_status="claimed")

    snapshot = ledger.bootstrap_snapshot()

    assert snapshot["ledger_id"] == ledger.ledger_id
    assert snapshot["watermark"] == 2
    assert snapshot["event_floor"] == 1
    assert len(snapshot["jobs"]) == 1
    assert snapshot["jobs"][0]["status"] == "claimed"


def test_cursor_state_is_projection_free_and_constant_query_count(
    ledger: WorkLedger,
    create_job,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = create_job()["job"]
    conn = sqlite3.connect(ledger.path)
    try:
        conn.execute(
            "WITH RECURSIVE seq(n) AS (SELECT 2 UNION ALL SELECT n+1 FROM seq WHERE n<10000) "
            "INSERT INTO work_events("
            "event_type, subject_type, subject_id, job_id, run_id, subject_version, "
            "subject_json, tombstone, created_at) "
            "SELECT 'job.updated', 'job', ?, ?, ?, n, "
            "'{\"status\":\"queued\",\"updated_at\":1}', 0, 1 FROM seq",
            (job["job_id"], job["job_id"], job["current_run"]["run_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    statements: list[str] = []
    original_connect = ledger._connect

    def traced_connect(*, for_write: bool):
        traced = original_connect(for_write=for_write)
        traced.set_trace_callback(
            lambda statement: statements.append(statement)
            if statement.lstrip().upper().startswith(("SELECT", "WITH"))
            else None
        )
        return traced

    monkeypatch.setattr(ledger, "_connect", traced_connect)
    state = ledger.cursor_state()

    assert state == {
        "ledger_id": ledger.ledger_id,
        "event_floor": 1,
        "high_water": 10_000,
    }
    assert len(statements) <= 4


def test_bootstrap_subject_pages_freeze_membership_but_allow_newer_versions(
    ledger: WorkLedger,
    create_job,
) -> None:
    initial = [create_job()["job"] for _ in range(3)]
    first = ledger.bootstrap_subject_page(subject_type="job", limit=1)
    seen = {first["items"][0]["job_id"]}
    unseen = next(job for job in initial if job["job_id"] not in seen)
    updated = ledger.transition_job(
        unseen["job_id"],
        expected_version=1,
        next_status="claimed",
        claim_token="post-watermark-claim",
    )
    created_late = create_job()["job"]

    after = first["items"][-1]["job_id"]
    while True:
        page = ledger.bootstrap_subject_page(
            subject_type="job",
            watermark=first["watermark"],
            event_floor=first["event_floor"],
            after_id=after,
            limit=1,
        )
        seen.update(item["job_id"] for item in page["items"])
        if any(item["job_id"] == unseen["job_id"] for item in page["items"]):
            assert page["items"][0]["version"] == updated["version"]
        if not page["has_more"]:
            break
        after = page["items"][-1]["job_id"]

    assert seen == {job["job_id"] for job in initial}
    assert created_late["job_id"] not in seen


def test_bootstrap_subject_page_query_count_is_constant_at_ten_thousand_rows(
    ledger: WorkLedger,
    create_job,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = create_job()["job"]
    template_job_id = template["job_id"]
    template_run_id = template["current_run"]["run_id"]
    conn = sqlite3.connect(ledger.path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n<10000) "
            "INSERT INTO job_runs("
            "run_id, job_id, attempt, version, status, runtime_json, owner_boot_token, "
            "owner_pid, owner_start_token, owner_generation, claim_token, claimed_at, "
            "started_at, updated_at, finished_at, result_json, error_json) "
            "SELECT 'run_' || printf('%032x', n), 'job_' || printf('%032x', n), "
            "r.attempt, r.version, r.status, r.runtime_json, r.owner_boot_token, r.owner_pid, "
            "r.owner_start_token, r.owner_generation, r.claim_token, r.claimed_at, "
            "r.started_at, r.updated_at, r.finished_at, r.result_json, r.error_json "
            "FROM seq CROSS JOIN job_runs AS r WHERE r.run_id=?",
            (template_run_id,),
        )
        conn.execute(
            "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n<10000) "
            "INSERT INTO jobs("
            "job_id, version, kind, status, title, summary, source, source_session_key, "
            "runtime_session_id, prompt_preview, current_run_id, attempt_count, "
            "runtime_summary_json, result_json, result_omitted_reason, error_json, "
            "open_attention_count, created_at, started_at, updated_at, finished_at, "
            "cancel_requested_at) "
            "SELECT 'job_' || printf('%032x', n), j.version, j.kind, j.status, "
            "'Bulk job', j.summary, j.source, j.source_session_key, 'bulk-runtime', "
            "j.prompt_preview, 'run_' || printf('%032x', n), j.attempt_count, "
            "j.runtime_summary_json, j.result_json, j.result_omitted_reason, j.error_json, "
            "j.open_attention_count, j.created_at, j.started_at, j.updated_at, j.finished_at, "
            "j.cancel_requested_at FROM seq CROSS JOIN jobs AS j WHERE j.job_id=?",
            (template_job_id,),
        )
        conn.execute(
            "INSERT INTO work_events("
            "event_type, subject_type, subject_id, job_id, run_id, subject_version, "
            "subject_json, tombstone, created_at) "
            "SELECT 'job.created', 'job', job_id, job_id, current_run_id, 1, "
            "'{\"status\":\"queued\",\"updated_at\":1}', 0, created_at "
            "FROM jobs WHERE job_id<>?",
            (template_job_id,),
        )
        conn.commit()
    finally:
        conn.close()

    statements: list[str] = []
    original_connect = ledger._connect

    def traced_connect(*, for_write: bool):
        traced = original_connect(for_write=for_write)
        traced.set_trace_callback(
            lambda statement: statements.append(statement)
            if statement.lstrip().upper().startswith(("SELECT", "WITH"))
            else None
        )
        return traced

    monkeypatch.setattr(ledger, "_connect", traced_connect)
    page = ledger.bootstrap_subject_page(subject_type="job", limit=37)

    assert len(page["items"]) == 37
    assert page["has_more"] is True
    # Store identity, cursor state, one indexed membership page, and one bulk
    # Run lookup: query count stays constant as the table grows.
    assert len(statements) <= 6


def test_old_service_is_fenced_when_ledger_id_rotates(
    ledger: WorkLedger, create_job
) -> None:
    job = create_job()["job"]
    replacement_id = new_work_id("ledger")
    conn = sqlite3.connect(ledger.path)
    try:
        conn.execute(
            "UPDATE work_meta SET value=? WHERE key='ledger_id'", (replacement_id,)
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(WorkStoreReplacedError):
        ledger.transition_job(
            job["job_id"], expected_version=1, next_status="claimed"
        )

    reopened = WorkLedger(ledger.profile_home)
    assert reopened.ledger_id == replacement_id
    assert reopened.get_job(job["job_id"])["status"] == "queued"


def test_tombstone_is_committed_before_terminal_subject_deletion(
    ledger: WorkLedger, create_job
) -> None:
    job = create_job()["job"]
    job_id = job["job_id"]
    ledger.transition_job(job_id, expected_version=1, next_status="claimed")
    ledger.transition_job(job_id, expected_version=2, next_status="running")
    terminal = ledger.transition_job(
        job_id, expected_version=3, next_status="succeeded"
    )

    deleted = ledger.tombstone_terminal_job(
        job_id, expected_version=terminal["version"]
    )

    assert deleted == {"jobs_deleted": 1, "attention_deleted": 0}
    with pytest.raises(WorkNotFound):
        ledger.get_job(job_id)
    tombstone = ledger.list_events(after=4)[0]
    assert tombstone["event_type"] == "job.deleted"
    assert tombstone["tombstone"] is True
    assert tombstone["subject"] is None
    assert tombstone["subject_version"] == terminal["version"] + 1
