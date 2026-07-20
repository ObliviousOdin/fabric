from __future__ import annotations

import inspect
import io
import json
import os
import sqlite3
import stat
import tarfile
import threading
import time
import uuid
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from fabric_cli.work_backup import (
    WORK_STORE_PRIVATE_BASENAMES,
    WorkStoreSnapshotError,
    snapshot_work_db_to_disk,
)
from fabric_cli.work_ledger import RuntimeOwner, WorkLedger


def _owner() -> RuntimeOwner:
    return RuntimeOwner(
        boot_token="backup-test-boot",
        pid=max(os.getpid(), 1),
        start_token="backup-test-start",
        generation="backup-test-generation",
    )


def _create_job(ledger: WorkLedger, counter: int) -> None:
    ledger.create_job(
        kind="background_prompt",
        title=f"Backup job {counter}",
        source="mobile",
        owner=_owner(),
        idempotency_key=f"work-backup-test-{counter:08d}",
        runtime_summary={"kind": "in_process_agent"},
        run_runtime={"kind": "in_process_agent"},
        source_session_key="backup-session",
        runtime_session_id="backup-runtime",
    )


def test_missing_work_db_does_not_create_source_or_destination(tmp_path: Path) -> None:
    source = tmp_path / "missing" / "work.db"
    destination = tmp_path / f"snapshot-{uuid.uuid4().hex}.db"

    assert snapshot_work_db_to_disk(source, destination) is None
    assert not source.exists()
    assert not source.parent.exists()
    assert not destination.exists()


def test_snapshot_is_closed_private_delete_journal_database(tmp_path: Path) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    for counter in range(3):
        _create_job(ledger, counter)
    destination = tmp_path / f"snapshot-{uuid.uuid4().hex}.db"

    assert snapshot_work_db_to_disk(ledger.path, destination) == destination

    connection = sqlite3.connect(destination)
    try:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3
    finally:
        connection.close()
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert not destination.with_name(destination.name + "-wal").exists()
    assert not destination.with_name(destination.name + "-shm").exists()


def test_snapshot_uses_no_in_memory_serialize_or_raw_copy_fallback() -> None:
    source = inspect.getsource(snapshot_work_db_to_disk)
    assert '":memory:"' not in source
    assert ".serialize(" not in source
    assert "copyfile" not in source
    assert "read_bytes" not in source


def test_continuous_wal_writer_snapshot_preserves_job_event_invariants(
    tmp_path: Path,
) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    ready = threading.Event()
    stop = threading.Event()
    failures: list[BaseException] = []

    def write_jobs() -> None:
        counter = 0
        try:
            while not stop.is_set():
                _create_job(ledger, counter)
                counter += 1
                if counter >= 5:
                    ready.set()
                time.sleep(0.002)
        except BaseException as exc:  # pragma: no cover - asserted by parent
            failures.append(exc)
            ready.set()

    writer = threading.Thread(target=write_jobs, daemon=True)
    writer.start()
    assert ready.wait(timeout=10)
    assert writer.is_alive()
    destination = tmp_path / f"snapshot-{uuid.uuid4().hex}.db"
    try:
        snapshot_work_db_to_disk(ledger.path, destination)
    finally:
        stop.set()
        writer.join(timeout=10)

    assert not writer.is_alive()
    assert failures == []
    connection = sqlite3.connect(destination)
    try:
        counts = {
            "jobs": connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            "runs": connection.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0],
            "events": connection.execute(
                "SELECT COUNT(*) FROM work_events WHERE event_type='job.created'"
            ).fetchone()[0],
            "receipts": connection.execute(
                "SELECT COUNT(*) FROM idempotency_keys WHERE operation='job.create' "
                "AND state='finalized'"
            ).fetchone()[0],
        }
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()
    assert counts["jobs"] > 0
    assert len(set(counts.values())) == 1


def test_forced_snapshot_failure_is_typed_and_removes_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fabric_cli import work_backup

    ledger = WorkLedger(tmp_path / "profile")
    _create_job(ledger, 1)
    destination = tmp_path / f"snapshot-{uuid.uuid4().hex}.db"

    def fail_backup(*_args: object) -> None:
        raise sqlite3.OperationalError("forced backup failure")

    monkeypatch.setattr(work_backup, "_copy_sqlite_snapshot", fail_backup)
    with pytest.raises(WorkStoreSnapshotError, match="forced backup failure"):
        snapshot_work_db_to_disk(ledger.path, destination)

    assert not destination.exists()
    assert not destination.with_name(destination.name + "-wal").exists()
    connection = sqlite3.connect(ledger.path)
    try:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    ledger = WorkLedger(tmp_path / "profile")
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"prior-artifact")

    with pytest.raises(WorkStoreSnapshotError) as raised:
        snapshot_work_db_to_disk(ledger.path, destination)

    assert raised.value.code == "destination_unavailable"
    assert destination.read_bytes() == b"prior-artifact"


def test_full_archive_contains_only_consistent_work_main(tmp_path: Path) -> None:
    from fabric_cli.backup import _write_full_zip_backup

    home = tmp_path / ".fabric"
    ledger = WorkLedger(home)
    _create_job(ledger, 1)
    hold = sqlite3.connect(ledger.path)
    hold.execute("PRAGMA journal_mode=WAL")
    hold.execute("SELECT COUNT(*) FROM jobs").fetchone()
    assert (home / "work.db.init.lock").exists()
    archive = tmp_path / "backup.zip"
    try:
        assert _write_full_zip_backup(archive, home) == archive
    finally:
        hold.close()

    with zipfile.ZipFile(archive) as backup:
        names = set(backup.namelist())
        assert "work.db" in names
        assert not any(name in names for name in WORK_STORE_PRIVATE_BASENAMES - {"work.db"})
        extracted = tmp_path / "archived-work.db"
        extracted.write_bytes(backup.read("work.db"))
    connection = sqlite3.connect(extracted)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    finally:
        connection.close()


def test_full_snapshot_failure_preserves_prior_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fabric_cli import backup

    home = tmp_path / ".fabric"
    WorkLedger(home)
    (home / "config.yaml").write_text("model: local\n")
    archive = tmp_path / "backup.zip"
    archive.write_bytes(b"prior-good-archive")

    def fail_snapshot(*_args: object, **_kwargs: object) -> Path:
        raise WorkStoreSnapshotError("forced", "forced work snapshot failure")

    monkeypatch.setattr(backup, "snapshot_work_db_to_disk", fail_snapshot)
    with pytest.raises(WorkStoreSnapshotError, match="forced work snapshot failure"):
        backup._write_full_zip_backup(archive, home)

    assert archive.read_bytes() == b"prior-good-archive"
    assert list(tmp_path.glob(".fabric-private-backup-*.zip")) == []
    assert list(tmp_path.glob(".fabric-private-work-*")) == []


def test_full_snapshot_source_disappearance_preserves_prior_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    home = tmp_path / ".fabric"
    WorkLedger(home)
    (home / "config.yaml").write_text("model: local\n")
    archive = tmp_path / "backup.zip"
    archive.write_bytes(b"prior-good-archive")
    monkeypatch.setattr(backup, "snapshot_work_db_to_disk", lambda *_args, **_kwargs: None)

    with pytest.raises(WorkStoreSnapshotError) as raised:
        backup._write_full_zip_backup(archive, home)

    assert raised.value.code == "source_disappeared"
    assert archive.read_bytes() == b"prior-good-archive"
    assert list(tmp_path.glob(".fabric-private-backup-*.zip")) == []
    assert list(tmp_path.glob(".fabric-private-work-*")) == []


def test_quick_snapshot_failure_publishes_no_manifest_and_preserves_prior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fabric_cli import backup

    home = tmp_path / ".fabric"
    WorkLedger(home)
    prior_id = backup.create_quick_snapshot(fabric_home=home)
    assert prior_id is not None
    prior_manifest = (
        home / "state-snapshots" / prior_id / "manifest.json"
    ).read_bytes()

    def fail_snapshot(*_args: object, **_kwargs: object) -> Path:
        raise WorkStoreSnapshotError("forced", "forced work snapshot failure")

    monkeypatch.setattr(backup, "snapshot_work_db_to_disk", fail_snapshot)
    with pytest.raises(WorkStoreSnapshotError, match="forced work snapshot failure"):
        backup.create_quick_snapshot(fabric_home=home)

    manifests = list((home / "state-snapshots").glob("*/manifest.json"))
    assert manifests == [home / "state-snapshots" / prior_id / "manifest.json"]
    assert manifests[0].read_bytes() == prior_manifest


def test_quick_snapshot_source_disappearance_publishes_no_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_cli import backup

    home = tmp_path / ".fabric"
    WorkLedger(home)
    prior_id = backup.create_quick_snapshot(fabric_home=home)
    assert prior_id is not None
    prior_path = home / "state-snapshots" / prior_id / "manifest.json"
    prior_manifest = prior_path.read_bytes()
    monkeypatch.setattr(backup, "snapshot_work_db_to_disk", lambda *_args, **_kwargs: None)

    with pytest.raises(WorkStoreSnapshotError) as raised:
        backup.create_quick_snapshot(fabric_home=home)

    assert raised.value.code == "source_disappeared"
    manifests = list((home / "state-snapshots").glob("*/manifest.json"))
    assert manifests == [prior_path]
    assert prior_path.read_bytes() == prior_manifest


def test_quick_destination_staging_failure_is_typed_and_manifestless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fabric_cli import backup

    home = tmp_path / ".fabric"
    WorkLedger(home)
    original = backup._QuickSnapshotWriter.create_file

    def fail_work_destination(
        writer: backup._QuickSnapshotWriter,
        relative: str | Path,
    ) -> tuple[Path, int]:
        if Path(relative) == Path("work.db"):
            raise PermissionError("forced destination failure")
        return original(writer, relative)

    monkeypatch.setattr(
        backup._QuickSnapshotWriter,
        "create_file",
        fail_work_destination,
    )
    with pytest.raises(WorkStoreSnapshotError) as raised:
        backup.create_quick_snapshot(fabric_home=home)

    assert raised.value.code == "destination_unavailable"
    assert list((home / "state-snapshots").glob("*/manifest.json")) == []


def test_quick_restore_does_not_replace_work_db_without_lifecycle_guard(
    tmp_path: Path,
) -> None:
    from fabric_cli.backup import restore_quick_snapshot

    home = tmp_path / ".fabric"
    home.mkdir()
    live = home / "work.db"
    live.write_bytes(b"live-ledger")
    snapshot = home / "state-snapshots" / "safe-snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "work.db").write_bytes(b"archived-ledger")
    (snapshot / "config.yaml").write_text("restored: true\n")
    (snapshot / "manifest.json").write_text(
        json.dumps({"files": {"work.db": 15, "config.yaml": 15}})
    )

    assert restore_quick_snapshot("safe-snapshot", fabric_home=home)
    assert live.read_bytes() == b"live-ledger"
    assert (home / "config.yaml").read_text() == "restored: true\n"


def test_full_import_excludes_work_store_until_lifecycle_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fabric_cli import backup

    home = tmp_path / ".fabric"
    home.mkdir()
    live = home / "work.db"
    live.write_bytes(b"live-ledger")
    archive = tmp_path / "incoming.zip"
    with zipfile.ZipFile(archive, "w") as incoming:
        incoming.writestr("config.yaml", "restored: true\n")
        incoming.writestr("work.db", b"archived-ledger")
        incoming.writestr("work.db-wal", b"stale-wal")
        incoming.writestr("work.db.init.lock", b"foreign-lock")

    monkeypatch.setattr(backup, "get_default_fabric_root", lambda: home)
    monkeypatch.setattr(backup, "display_fabric_home", lambda: str(home))
    backup.run_import(Namespace(zipfile=str(archive), force=True))

    assert live.read_bytes() == b"live-ledger"
    assert not (home / "work.db-wal").exists()
    assert not (home / "work.db.init.lock").exists()
    assert (home / "config.yaml").read_text() == "restored: true\n"


@pytest.mark.parametrize("name", sorted(WORK_STORE_PRIVATE_BASENAMES))
def test_work_artifacts_are_private_to_model_media_dashboard_and_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    from agent.file_safety import get_read_block_error
    from fabric_cli.provider_account_privacy import is_private_provider_account_path
    from fabric_cli.web_server import _is_sensitive_filename
    from gateway.platforms.base import BasePlatformAdapter

    home = tmp_path / ".fabric"
    home.mkdir()
    artifact = home / name
    artifact.write_bytes(b"private work state")

    assert is_private_provider_account_path(
        artifact,
        active_home=home,
        fabric_root=home,
    )
    with (
        patch("agent.file_safety._fabric_home_path", return_value=home),
        patch("agent.file_safety._fabric_root_path", return_value=home),
    ):
        assert get_read_block_error(str(artifact)) is not None
    monkeypatch.setattr("gateway.platforms.base._FABRIC_HOME", home)
    monkeypatch.setattr("gateway.platforms.base._FABRIC_ROOT", home)
    monkeypatch.setattr("gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS", (home,))
    assert BasePlatformAdapter.validate_media_delivery_path(str(artifact)) is None
    assert _is_sensitive_filename(name)

    archive = tmp_path / f"{name.replace('/', '-')}.zip"
    with zipfile.ZipFile(archive, "w") as candidate:
        candidate.writestr(name, b"private work state")
    assert is_private_provider_account_path(
        archive,
        active_home=home,
        fabric_root=home,
    )


def test_profile_clone_exports_import_and_distribution_exclude_work_artifacts(
    tmp_path: Path,
) -> None:
    from fabric_cli.profile_distribution import USER_OWNED_EXCLUDE
    from fabric_cli.profiles import (
        _clone_all_copytree_ignore,
        _default_export_ignore,
        _named_export_ignore,
        _safe_extract_profile_archive,
    )

    source = tmp_path / "source"
    source.mkdir()
    names = ["config.yaml", *sorted(WORK_STORE_PRIVATE_BASENAMES)]
    clone_ignored = set(_clone_all_copytree_ignore(source)(str(source), names))
    named_ignored = set(_named_export_ignore(source)(str(source), names))
    default_ignored = set(_default_export_ignore(source)(str(source), names))
    for name in WORK_STORE_PRIVATE_BASENAMES:
        assert name in clone_ignored
        assert name in named_ignored
        assert name in default_ignored
        assert name in USER_OWNED_EXCLUDE

    archive = tmp_path / "profile.tar.gz"
    with tarfile.open(archive, "w:gz") as profile_tar:
        for relative, payload in [
            ("source/config.yaml", b"model: local\n"),
            *((f"source/{name}", b"private") for name in WORK_STORE_PRIVATE_BASENAMES),
        ]:
            info = tarfile.TarInfo(relative)
            info.size = len(payload)
            profile_tar.addfile(info, io.BytesIO(payload))
    destination = tmp_path / "extracted"
    _safe_extract_profile_archive(archive, destination)

    assert (destination / "source" / "config.yaml").exists()
    for name in WORK_STORE_PRIVATE_BASENAMES:
        assert not (destination / "source" / name).exists()


def test_disk_usage_counts_work_store_files_once_as_persistent_database(
    tmp_path: Path,
) -> None:
    from fabric_cli.disk import scan_categories

    sizes = {
        name: 11 + index * 2
        for index, name in enumerate(sorted(WORK_STORE_PRIVATE_BASENAMES))
    }
    for name, size in sizes.items():
        (tmp_path / name).write_bytes(b"x" * size)

    usages = {usage.category.key: usage for usage in scan_categories(tmp_path)}
    assert usages["databases"].bytes == sum(sizes.values())
    assert usages["databases"].files == len(sizes)
    assert usages["other"].bytes == 0
    assert usages["other"].files == 0


def test_docker_user_owned_allowlist_mirrors_work_artifacts() -> None:
    stage2 = (Path(__file__).parents[2] / "docker" / "stage2-hook.sh").read_text()
    for name in WORK_STORE_PRIVATE_BASENAMES:
        assert name in stage2
