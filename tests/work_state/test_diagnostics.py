from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import fabric_cli.work_ledger as work_ledger
from fabric_cli.work_ledger import (
    WORK_APPLICATION_ID,
    WORK_SCHEMA_VERSION,
    RuntimeOwner,
    WorkLedger,
    inspect_work_store,
)


def _owner() -> RuntimeOwner:
    return RuntimeOwner(
        boot_token="diagnostics-test-boot",
        pid=max(os.getpid(), 1),
        start_token="diagnostics-test-start",
        generation="diagnostics-test-generation",
    )


def _create_job(ledger: WorkLedger) -> None:
    ledger.create_job(
        kind="background_prompt",
        title="Diagnostic job",
        source="mobile",
        owner=_owner(),
        idempotency_key="work-diagnostic-test-0001",
        runtime_summary={"kind": "in_process_agent"},
        run_runtime={"kind": "in_process_agent"},
        source_session_key="diagnostic-session",
        runtime_session_id="diagnostic-runtime",
    )


def _file_fingerprint(path: Path) -> tuple[bytes, int, int]:
    metadata = path.stat()
    return path.read_bytes(), metadata.st_mtime_ns, metadata.st_size


def test_inspect_missing_store_never_creates_a_profile_or_sidecar(tmp_path: Path) -> None:
    home = tmp_path / "missing-profile"

    inspection = inspect_work_store(home)

    assert inspection.status == "missing"
    assert inspection.path == home / "work.db"
    assert not home.exists()


def test_inspect_current_store_is_query_only_and_reports_bounded_owners(
    tmp_path: Path,
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    _create_job(ledger)
    before = _file_fingerprint(ledger.path)
    sidecars_before = {
        name: (ledger.path.parent / name).exists()
        for name in ("work.db-wal", "work.db-shm", "work.db-journal")
    }

    inspection = inspect_work_store(ledger.profile_home)

    assert inspection.status == "healthy"
    assert inspection.integrity_ok is True
    assert inspection.application_id == WORK_APPLICATION_ID
    assert inspection.schema_version == WORK_SCHEMA_VERSION
    assert inspection.ledger_id == ledger.ledger_id
    assert inspection.event_floor == 1
    assert inspection.owners_truncated is False
    assert len(inspection.owner_summaries) == 1
    owner = inspection.owner_summaries[0]
    assert owner.owner == _owner()
    assert owner.run_count == 1
    assert owner.attention_count == 0
    assert _file_fingerprint(ledger.path) == before
    assert {
        name: (ledger.path.parent / name).exists()
        for name in ("work.db-wal", "work.db-shm", "work.db-journal")
    } == sidecars_before


def test_inspect_live_wal_reports_size_without_changing_database_or_wal(
    tmp_path: Path,
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    _create_job(ledger)
    writer = sqlite3.connect(ledger.path)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("UPDATE work_meta SET value=value WHERE key='event_floor'")
        writer.commit()
        wal_path = ledger.path.with_name("work.db-wal")
        shm_path = ledger.path.with_name("work.db-shm")
        assert wal_path.exists()
        assert shm_path.exists()
        before_db = _file_fingerprint(ledger.path)
        before_wal = _file_fingerprint(wal_path)
        before_shm = _file_fingerprint(shm_path)

        inspection = inspect_work_store(ledger.profile_home)

        assert inspection.status == "live_wal"
        assert inspection.integrity_ok is None
        assert inspection.owner_summaries == ()
        assert inspection.wal_size_bytes == before_wal[2]
        assert _file_fingerprint(ledger.path) == before_db
        assert _file_fingerprint(wal_path) == before_wal
        assert _file_fingerprint(shm_path) == before_shm
    finally:
        writer.close()


def test_inspect_live_rollback_journal_without_reading_uncommitted_pages(
    tmp_path: Path,
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    _create_job(ledger)
    writer = sqlite3.connect(ledger.path)
    try:
        assert writer.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        writer.execute("PRAGMA cache_size=1")
        writer.execute("PRAGMA cache_spill=ON")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE work_meta SET value='999' WHERE key='event_floor'")
        journal_path = ledger.path.with_name("work.db-journal")
        assert journal_path.exists()
        before_db = _file_fingerprint(ledger.path)
        before_journal = _file_fingerprint(journal_path)

        inspection = inspect_work_store(ledger.profile_home)

        assert inspection.status == "live_rollback_journal"
        assert inspection.event_floor is None
        assert inspection.rollback_journal_size_bytes == before_journal[2]
        assert _file_fingerprint(ledger.path) == before_db
        assert _file_fingerprint(journal_path) == before_journal
    finally:
        writer.rollback()
        writer.close()


def test_inspect_future_schema_reports_without_migrating_or_repairing(
    tmp_path: Path,
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    connection = sqlite3.connect(ledger.path)
    try:
        connection.execute(f"PRAGMA user_version={WORK_SCHEMA_VERSION + 1}")
        connection.commit()
    finally:
        connection.close()
    before = _file_fingerprint(ledger.path)

    inspection = inspect_work_store(ledger.profile_home)

    assert inspection.status == "future_schema"
    assert inspection.schema_version == WORK_SCHEMA_VERSION + 1
    assert inspection.integrity_ok is True
    assert _file_fingerprint(ledger.path) == before


def test_inspect_refuses_a_stale_main_file_when_a_wal_appears_mid_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    original_open = work_ledger._read_only_work_store_connection
    writer_holder: list[sqlite3.Connection] = []
    source_after_writer: dict[str, tuple[bytes, int, int]] = {}

    def introduce_live_wal(path: Path) -> sqlite3.Connection:
        writer = sqlite3.connect(path)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE work_meta SET value='999' WHERE key='event_floor'")
        writer.commit()
        writer_holder.append(writer)
        source_after_writer["db"] = _file_fingerprint(path)
        source_after_writer["wal"] = _file_fingerprint(path.with_name("work.db-wal"))
        source_after_writer["shm"] = _file_fingerprint(path.with_name("work.db-shm"))
        return original_open(path)

    monkeypatch.setattr(work_ledger, "_read_only_work_store_connection", introduce_live_wal)
    try:
        inspection = inspect_work_store(ledger.profile_home)

        assert inspection.status == "inspection_raced"
        assert inspection.event_floor is None
        assert _file_fingerprint(ledger.path) == source_after_writer["db"]
        assert _file_fingerprint(ledger.path.with_name("work.db-wal")) == source_after_writer[
            "wal"
        ]
        assert _file_fingerprint(ledger.path.with_name("work.db-shm")) == source_after_writer[
            "shm"
        ]
    finally:
        for writer in writer_holder:
            writer.close()


def test_inspect_refuses_a_rollback_journal_that_appears_mid_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    original_open = work_ledger._read_only_work_store_connection
    writer_holder: list[sqlite3.Connection] = []
    source_after_writer: dict[str, tuple[bytes, int, int]] = {}

    def introduce_live_journal(path: Path) -> sqlite3.Connection:
        writer = sqlite3.connect(path)
        assert writer.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE work_meta SET value='999' WHERE key='event_floor'")
        writer_holder.append(writer)
        source_after_writer["db"] = _file_fingerprint(path)
        source_after_writer["journal"] = _file_fingerprint(
            path.with_name("work.db-journal")
        )
        return original_open(path)

    monkeypatch.setattr(work_ledger, "_read_only_work_store_connection", introduce_live_journal)
    try:
        inspection = inspect_work_store(ledger.profile_home)

        assert inspection.status == "inspection_raced"
        assert inspection.event_floor is None
        assert _file_fingerprint(ledger.path) == source_after_writer["db"]
        assert _file_fingerprint(ledger.path.with_name("work.db-journal")) == source_after_writer[
            "journal"
        ]
    finally:
        for writer in writer_holder:
            writer.rollback()
            writer.close()


def test_inspect_rejects_non_sqlite_file_without_changing_it(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    home.mkdir()
    path = home / "work.db"
    path.write_bytes(b"not a sqlite database")
    before = _file_fingerprint(path)

    inspection = inspect_work_store(home)

    assert inspection.status == "invalid_header"
    assert _file_fingerprint(path) == before


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires extra Windows privileges")
def test_inspect_rejects_work_store_symlink_without_following_target(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    home.mkdir()
    target = tmp_path / "target.db"
    target.write_bytes(b"not a Fabric Work store")
    path = home / "work.db"
    path.symlink_to(target)
    before = _file_fingerprint(target)

    inspection = inspect_work_store(home)

    assert inspection.status == "invalid_path"
    assert _file_fingerprint(target) == before
