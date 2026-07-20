from __future__ import annotations

import contextlib
import io
import os
import sqlite3
from pathlib import Path

from fabric_cli import doctor
from fabric_cli.work_ledger import RuntimeOwner, WorkLedger


def _owner() -> RuntimeOwner:
    return RuntimeOwner(
        boot_token="doctor-test-boot",
        pid=max(os.getpid(), 1),
        start_token="doctor-test-start",
        generation="doctor-test-generation",
    )


def _create_job(ledger: WorkLedger) -> None:
    ledger.create_job(
        kind="background_prompt",
        title="Doctor job",
        source="mobile",
        owner=_owner(),
        idempotency_key="work-doctor-test-0001",
        runtime_summary={"kind": "in_process_agent"},
        run_runtime={"kind": "in_process_agent"},
        source_session_key="doctor-session",
        runtime_session_id="doctor-runtime",
    )


def _run_work_check(issues: list[str] | None = None) -> str:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        doctor._check_work_store(issues)
    return output.getvalue()


def test_work_doctor_missing_store_does_not_create_profile(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "missing-profile"
    monkeypatch.setattr(doctor, "FABRIC_HOME", home)
    monkeypatch.setattr(doctor, "_DHH", str(home))

    output = _run_work_check([])

    assert "work.db not created yet" in output
    assert not home.exists()


def test_work_doctor_reports_read_only_store_health_and_owner(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "profile"
    ledger = WorkLedger(home)
    _create_job(ledger)
    before = (ledger.path.read_bytes(), ledger.path.stat().st_mtime_ns)
    sidecars_before = {
        name: (home / name).exists()
        for name in ("work.db-wal", "work.db-shm", "work.db-journal")
    }
    monkeypatch.setattr(doctor, "FABRIC_HOME", home)
    monkeypatch.setattr(doctor, "_DHH", str(home))
    monkeypatch.setattr(
        doctor,
        "_classify_work_owner_summaries",
        lambda summaries: {summary.owner: "live" for summary in summaries},
    )

    output = _run_work_check([])

    assert "Durable Work store" in output
    assert "work.db is readable" in output
    assert f"ledger={ledger.ledger_id}" in output
    assert "event_floor=1" in output
    assert f"Work owner pid={_owner().pid} is live" in output
    assert (ledger.path.read_bytes(), ledger.path.stat().st_mtime_ns) == before
    assert {
        name: (home / name).exists()
        for name in ("work.db-wal", "work.db-shm", "work.db-journal")
    } == sidecars_before


def test_work_doctor_reports_stale_owner_without_reconciling(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "profile"
    ledger = WorkLedger(home)
    _create_job(ledger)
    before = ledger.path.read_bytes()
    monkeypatch.setattr(doctor, "FABRIC_HOME", home)
    monkeypatch.setattr(doctor, "_DHH", str(home))
    monkeypatch.setattr(
        doctor,
        "_classify_work_owner_summaries",
        lambda summaries: {summary.owner: "dead" for summary in summaries},
    )
    issues: list[str] = []

    output = _run_work_check(issues)

    assert "is stale" in output
    assert "next Work-service startup reconciles it" in output
    assert len(issues) == 1
    assert "stale owner" in issues[0]
    assert ledger.path.read_bytes() == before


def test_work_doctor_reports_live_wal_without_deep_inspection(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "profile"
    ledger = WorkLedger(home)
    _create_job(ledger)
    writer = sqlite3.connect(ledger.path)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("UPDATE work_meta SET value=value WHERE key='event_floor'")
        writer.commit()
        wal_path = home / "work.db-wal"
        shm_path = home / "work.db-shm"
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (ledger.path, wal_path, shm_path)
        }
        monkeypatch.setattr(doctor, "FABRIC_HOME", home)
        monkeypatch.setattr(doctor, "_DHH", str(home))

        output = _run_work_check([])

        assert "live WAL" in output
        assert "deep inspection skipped" in output
        assert "ledger=" not in output
        assert {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (ledger.path, wal_path, shm_path)
        } == before
    finally:
        writer.close()
