from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import pytest

from fabric_cli.work_ledger import (
    EXPECTED_INDEX_COLUMNS,
    EXPECTED_TABLE_COLUMNS,
    SCHEMA_TABLE_SQL,
    SCHEMA_V1_INDEX_SQL,
    WORK_APPLICATION_ID,
    WORK_SCHEMA_VERSION,
    WorkLedger,
    WorkStoreCorruptError,
    WorkStoreFutureSchemaError,
    WorkStoreSchemaError,
    WorkStoreSignatureError,
    WorkStoreUnavailable,
    new_work_id,
)


def _set_signature(path: Path, *, application_id: int, user_version: int) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA application_id={application_id}")
        conn.execute(f"PRAGMA user_version={user_version}")
    finally:
        conn.close()


def _create_signed_v1_ledger(path: Path) -> str:
    """Build an exact, populated v1 file without running current code."""

    ledger_id = new_work_id("ledger")
    conn = sqlite3.connect(path)
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


def test_fresh_real_file_has_fixed_signature_schema_metadata_and_secure_mode(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "named-profile"
    ledger = WorkLedger(profile)

    assert ledger.path == profile.resolve() / "work.db"
    assert ledger.ledger_id.startswith("ledger_")
    assert ledger.path.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(ledger.path.stat().st_mode) == 0o600

    conn = sqlite3.connect(ledger.path)
    try:
        assert conn.execute("PRAGMA application_id").fetchone()[0] == WORK_APPLICATION_ID
        assert conn.execute("PRAGMA user_version").fetchone()[0] == WORK_SCHEMA_VERSION
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == set(EXPECTED_TABLE_COLUMNS)
        assert indexes == set(EXPECTED_INDEX_COLUMNS)
        meta = dict(conn.execute("SELECT key, value FROM work_meta"))
        assert set(meta) == {
            "ledger_id",
            "event_floor",
            "created_at",
            "last_maintenance_at",
        }
        assert meta["ledger_id"] == ledger.ledger_id
        assert meta["event_floor"] == "1"
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()

    assert WorkLedger(profile).ledger_id == ledger.ledger_id


def test_initialization_uses_shared_wal_fallback_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fabric_state

    calls: list[str] = []

    def force_delete(conn: sqlite3.Connection, *, db_label: str) -> str:
        calls.append(db_label)
        conn.execute("PRAGMA journal_mode=DELETE")
        return "delete"

    monkeypatch.setattr(fabric_state, "apply_wal_with_fallback", force_delete)
    ledger = WorkLedger(tmp_path / "profile")

    assert calls == [f"work.db ({ledger.profile_home})"]
    conn = sqlite3.connect(ledger.path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()


def test_exact_populated_v1_migrates_retention_schema_without_losing_metadata(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    legacy_ledger_id = _create_signed_v1_ledger(path)

    ledger = WorkLedger(profile)

    assert ledger.ledger_id == legacy_ledger_id
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA application_id").fetchone()[0] == WORK_APPLICATION_ID
        assert conn.execute("PRAGMA user_version").fetchone()[0] == WORK_SCHEMA_VERSION
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert indexes == set(EXPECTED_INDEX_COLUMNS)
        assert dict(conn.execute("SELECT key, value FROM work_meta")) == {
            "ledger_id": legacy_ledger_id,
            "event_floor": "1",
            "created_at": "1000.0",
            "last_maintenance_at": "1000.0",
        }
    finally:
        conn.close()


def test_v1_migration_normalizes_clock_skewed_attention_and_receipt_retention(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    _create_signed_v1_ledger(path)
    attention_id = new_work_id("attn")
    receipt_key = "migration-clock-receipt-0001"
    created_at = 100_000.0
    receipt_created_at = 200_000.0
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO attention_items("
            "attention_id, version, job_id, run_id, source_session_key, runtime_session_id, "
            "request_id, kind, state, blocking, sensitive, title, public_payload_json, "
            "owner_boot_token, owner_pid, owner_start_token, owner_generation, "
            "waiter_generation, resolution_token, terminal_reason, created_at, updated_at, "
            "expires_at, resolved_at"
            ") VALUES (?, 3, NULL, NULL, 'migration-session', 'migration-runtime', "
            "'migration-clock-request-0001', 'approval', 'resolved', 1, 0, 'Old approval', "
            "'{}', 'boot', 1, 'start', 'generation', 'waiter', NULL, NULL, ?, ?, NULL, ?)",
            (attention_id, created_at, 1_000.0, 1_000.0),
        )
        conn.execute(
            "INSERT INTO idempotency_keys("
            "operation, idempotency_key, request_hash, state, subject_id, binding_json, "
            "response_json, created_at, updated_at"
            ") VALUES ('attention.respond', ?, ?, 'finalized', ?, '{}', '{}', ?, ?)",
            (receipt_key, "0" * 64, attention_id, receipt_created_at, 1_000.0),
        )
        conn.commit()
    finally:
        conn.close()

    ledger = WorkLedger(profile)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute(
            "SELECT created_at, updated_at, resolved_at FROM attention_items "
            "WHERE attention_id=?",
            (attention_id,),
        ).fetchone() == (created_at, receipt_created_at, receipt_created_at)
        assert conn.execute(
            "SELECT created_at, updated_at FROM idempotency_keys "
            "WHERE operation='attention.respond' AND idempotency_key=?",
            (receipt_key,),
        ).fetchone() == (receipt_created_at, receipt_created_at)
    finally:
        conn.close()

    retained = ledger.run_retention(
        now=receipt_created_at + 29 * 24 * 60 * 60,
        retention_seconds=30 * 24 * 60 * 60,
        subject_batch_size=1,
    )
    assert retained["attention_deleted"] == 0
    assert retained["idempotency_deleted"] == 0
    assert ledger.get_attention(attention_id)["state"] == "resolved"
    assert ledger.get_idempotency(
        operation="attention.respond", idempotency_key=receipt_key
    )["state"] == "finalized"


def test_populated_malformed_v1_is_preserved_and_rejected(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    _create_signed_v1_ledger(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("DROP INDEX idx_jobs_terminal_finished")
        conn.commit()
    finally:
        conn.close()
    before = path.read_bytes()

    with pytest.raises(WorkStoreSchemaError):
        WorkLedger(profile)

    assert path.read_bytes() == before


def test_v1_migration_rolls_back_if_the_additive_index_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    legacy_ledger_id = _create_signed_v1_ledger(path)
    original_migrate = WorkLedger._migrate_v1_to_v2

    def migrate_then_fail(conn: sqlite3.Connection) -> None:
        original_migrate(conn)
        raise RuntimeError("forced migration failure")

    monkeypatch.setattr(
        WorkLedger,
        "_migrate_v1_to_v2",
        staticmethod(migrate_then_fail),
    )

    with pytest.raises(RuntimeError, match="forced migration failure"):
        WorkLedger(profile)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert indexes == set(SCHEMA_V1_INDEX_SQL)
        assert dict(conn.execute("SELECT key, value FROM work_meta"))["ledger_id"] == legacy_ledger_id
    finally:
        conn.close()


def test_post_init_open_does_not_recreate_db_deleted_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    original_validate_header = ledger._validate_header

    def validate_then_unlink() -> None:
        original_validate_header()
        ledger.path.unlink()

    # Deterministically exercise the lstat/header -> sqlite3.connect TOCTOU
    # window.  A default SQLite open would recreate an empty work.db here;
    # the post-init connector's URI mode=rw must instead fail closed.
    monkeypatch.setattr(ledger, "_validate_header", validate_then_unlink)

    with pytest.raises(WorkStoreUnavailable):
        ledger.assert_store_identity()

    assert not ledger.path.exists()


def test_future_schema_fails_closed_without_changing_file(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    _set_signature(
        path,
        application_id=WORK_APPLICATION_ID,
        user_version=WORK_SCHEMA_VERSION + 1,
    )
    before = path.read_bytes()
    before_stat = path.stat()

    with pytest.raises(WorkStoreFutureSchemaError):
        WorkLedger(profile)

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_stat.st_mtime_ns


def test_wrong_application_id_fails_closed(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    _set_signature(path, application_id=0x12345678, user_version=1)
    before = path.read_bytes()

    with pytest.raises(WorkStoreSignatureError):
        WorkLedger(profile)

    assert path.read_bytes() == before


def test_sqlite_header_with_corrupt_pages_is_typed_and_preserved(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    corrupt = b"SQLite format 3\x00" + (b"\x00" * 240)
    path.write_bytes(corrupt)

    with pytest.raises(WorkStoreCorruptError):
        WorkLedger(profile)

    assert path.read_bytes() == corrupt


def test_empty_recognizable_prerelease_schema_is_rebuilt(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE work_meta (wrong_column TEXT)")
        conn.execute(f"PRAGMA application_id={WORK_APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version={WORK_SCHEMA_VERSION}")
    finally:
        conn.close()

    ledger = WorkLedger(profile)

    conn = sqlite3.connect(path)
    try:
        columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(work_meta)"))
        assert columns == ("key", "value")
    finally:
        conn.close()
    assert ledger.ledger_id.startswith("ledger_")


def test_populated_malformed_schema_is_preserved_and_rejected(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    path = profile / "work.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE work_meta (wrong_column TEXT)")
        conn.execute("INSERT INTO work_meta VALUES ('evidence')")
        conn.execute(f"PRAGMA application_id={WORK_APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version={WORK_SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()
    before = path.read_bytes()

    with pytest.raises(WorkStoreSchemaError):
        WorkLedger(profile)

    assert path.read_bytes() == before


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_work_db_symlink_is_rejected(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    target = tmp_path / "outside.db"
    target.write_bytes(b"")
    (profile / "work.db").symlink_to(target)

    with pytest.raises(WorkStoreUnavailable):
        WorkLedger(profile)

    assert target.read_bytes() == b""
