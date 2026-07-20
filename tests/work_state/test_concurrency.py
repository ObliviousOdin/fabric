from __future__ import annotations

import multiprocessing
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from fabric_cli.work_ledger import (
    SCHEMA_TABLE_SQL,
    SCHEMA_V1_INDEX_SQL,
    WORK_APPLICATION_ID,
    WORK_SCHEMA_VERSION,
    VersionConflict,
    WorkLedger,
    WorkStoreBusy,
    new_work_id,
)


def _initialize_worker(profile: str, gate, output) -> None:
    gate.wait(timeout=10)
    try:
        ledger = WorkLedger(profile)
        output.put(("ok", ledger.ledger_id))
    except Exception as exc:  # pragma: no cover - reported to parent assertion
        output.put(("error", f"{type(exc).__name__}: {exc}"))


def _create_signed_v1_ledger(profile: Path) -> str:
    profile.mkdir()
    ledger_id = new_work_id("ledger")
    conn = sqlite3.connect(profile / "work.db")
    try:
        for sql in SCHEMA_TABLE_SQL.values():
            conn.execute(sql)
        for sql in SCHEMA_V1_INDEX_SQL.values():
            conn.execute(sql)
        conn.execute(f"PRAGMA application_id={WORK_APPLICATION_ID}")
        conn.execute("PRAGMA user_version=1")
        conn.executemany(
            "INSERT INTO work_meta(key, value) VALUES (?, ?)",
            (
                ("ledger_id", ledger_id),
                ("event_floor", "1"),
                ("created_at", "1000.0"),
                ("last_maintenance_at", "1000.0"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return ledger_id


def test_two_os_processes_racing_fresh_init_share_one_valid_ledger(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    ctx = multiprocessing.get_context("spawn")
    gate = ctx.Event()
    output = ctx.Queue()
    workers = [
        ctx.Process(target=_initialize_worker, args=(str(profile), gate, output))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    gate.set()
    results = [output.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0

    assert [status for status, _ in results] == ["ok", "ok"]
    assert results[0][1] == results[1][1]
    assert WorkLedger(profile).ledger_id == results[0][1]
    conn = sqlite3.connect(profile / "work.db")
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM work_meta").fetchone()[0] == 4
    finally:
        conn.close()


def test_two_os_processes_racing_v1_migration_share_one_valid_ledger(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    v1_ledger_id = _create_signed_v1_ledger(profile)
    ctx = multiprocessing.get_context("spawn")
    gate = ctx.Event()
    output = ctx.Queue()
    workers = [
        ctx.Process(target=_initialize_worker, args=(str(profile), gate, output))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    gate.set()
    results = [output.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0

    assert [status for status, _ in results] == ["ok", "ok"]
    assert {ledger_id for _, ledger_id in results} == {v1_ledger_id}
    conn = sqlite3.connect(profile / "work.db")
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == WORK_SCHEMA_VERSION
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='idx_attention_state_terminal_time'"
            ).fetchone()
            == (1,)
        )
    finally:
        conn.close()


def test_independent_connection_cas_race_has_one_winner_and_one_event(
    ledger: WorkLedger,
    create_job,
) -> None:
    job_id = create_job()["job"]["job_id"]
    other = WorkLedger(ledger.profile_home)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []
    outcome_lock = threading.Lock()

    def transition(candidate: WorkLedger) -> None:
        barrier.wait()
        try:
            candidate.transition_job(
                job_id, expected_version=1, next_status="claimed"
            )
        except VersionConflict:
            outcome = "conflict"
        else:
            outcome = "won"
        with outcome_lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=transition, args=(candidate,))
        for candidate in (ledger, other)
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(outcomes) == ["conflict", "won"]
    assert ledger.get_job(job_id)["version"] == 2
    assert len(ledger.list_events()) == 2


def test_begin_immediate_deadline_is_bounded_and_body_never_runs_under_lock(
    tmp_path: Path,
) -> None:
    ledger = WorkLedger(
        tmp_path / "profile",
        busy_timeout_ms=5,
        write_deadline_seconds=0.12,
    )
    blocker = sqlite3.connect(ledger.path, isolation_level=None, timeout=0.1)
    blocker.execute("BEGIN IMMEDIATE")
    body_calls = 0

    def body(conn: sqlite3.Connection) -> None:
        nonlocal body_calls
        body_calls += 1
        conn.execute(
            "UPDATE work_meta SET value=value WHERE key='last_maintenance_at'"
        )

    started = time.monotonic()
    try:
        with pytest.raises(WorkStoreBusy) as raised:
            ledger._write(body)
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    elapsed = time.monotonic() - started

    assert raised.value.retryable is True
    assert body_calls == 0
    assert 0.08 <= elapsed < 1.0
