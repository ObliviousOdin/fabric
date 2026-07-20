"""Strict backup and privacy primitives for the profile-scoped Work store.

``work.db`` is a live WAL database.  A backup must therefore be made through
SQLite's online-backup API and materialized as a closed, standalone database
before an archive reads it.  This module intentionally has no raw-copy or
in-memory fallback: either callers get a verified on-disk snapshot, or they
get a typed failure and publish nothing.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import stat
from pathlib import Path

from fabric_cli.work_ledger import WORK_DB_FILENAME


WORK_STORE_PRIVATE_BASENAMES = frozenset(
    {
        WORK_DB_FILENAME,
        f"{WORK_DB_FILENAME}-wal",
        f"{WORK_DB_FILENAME}-shm",
        f"{WORK_DB_FILENAME}-journal",
        f"{WORK_DB_FILENAME}.init.lock",
        # Reserved lifecycle-guard names.  The guard itself lands in a later
        # step, but privacy/export allowlists must be safe before it exists.
        f"{WORK_DB_FILENAME}.lock",
        f"{WORK_DB_FILENAME}.lifecycle.lock",
        f"{WORK_DB_FILENAME}.lifecycle.guard",
        f"{WORK_DB_FILENAME}.owners.json",
    }
)


def is_work_store_private_basename(name: str) -> bool:
    """Return whether *name* is Work history or Work lifecycle state."""
    lowered = name.casefold()
    if lowered in WORK_STORE_PRIVATE_BASENAMES:
        return True
    # Keep future guard/lock implementations private without accidentally
    # classifying arbitrary ``work.db.*`` user files.
    return lowered.startswith(f"{WORK_DB_FILENAME}.") and (
        lowered.endswith(".lock")
        or lowered.endswith(".guard")
        or lowered.endswith(".owners.json")
    )


class WorkStoreSnapshotError(OSError):
    """A consistent, verified Work-store snapshot could not be produced."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _destination_matches(descriptor: int, path: Path) -> bool:
    try:
        opened = os.fstat(descriptor)
        visible = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    structurally_valid = bool(
        stat.S_ISREG(opened.st_mode)
        and stat.S_ISREG(visible.st_mode)
        and not stat.S_ISLNK(visible.st_mode)
        and not getattr(visible, "st_file_attributes", 0) & reparse_flag
        and getattr(opened, "st_nlink", 1) == 1
        and _identity(opened) == _identity(visible)
    )
    if not structurally_valid:
        return False
    if os.name == "nt":  # pragma: no cover - native Windows CI
        try:
            from fabric_cli.provider_accounts import _windows_private_fd

            return _windows_private_fd(descriptor, apply=False)
        except Exception:
            return False
    return stat.S_IMODE(opened.st_mode) == stat.S_IMODE(visible.st_mode) == 0o600


def _create_private_destination(path: Path) -> int:
    if os.name == "nt":  # pragma: no cover - native Windows CI
        from fabric_cli.provider_accounts import _windows_open_private_file

        try:
            descriptor = _windows_open_private_file(path, create_new=True)
        except Exception as exc:
            raise WorkStoreSnapshotError(
                "destination_unavailable",
                f"cannot create private Work snapshot destination: {exc}",
            ) from exc
        if _destination_matches(descriptor, path):
            return descriptor
        _discard_precreated_destination(path, descriptor)
        raise WorkStoreSnapshotError(
            "destination_changed",
            "Work snapshot destination is not one private regular file",
        )
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise WorkStoreSnapshotError(
            "destination_unavailable",
            f"cannot create private Work snapshot destination: {exc}",
        ) from exc
    try:
        os.fchmod(descriptor, 0o600)
        if not _destination_matches(descriptor, path):
            raise WorkStoreSnapshotError(
                "destination_changed",
                "Work snapshot destination is not one private regular file",
            )
        return descriptor
    except BaseException:
        _discard_precreated_destination(path, descriptor)
        raise


def _sqlite_uri(path: Path, *, mode: str) -> str:
    return f"{path.as_uri()}?mode={mode}"


def _copy_sqlite_snapshot(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
) -> None:
    """Narrow injection seam for deterministic failure-path tests."""
    source.backup(destination)


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":  # pragma: no cover - native Windows CI
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_snapshot_files(
    destination: Path,
    *,
    expected_identity: tuple[int, int] | None,
) -> None:
    """Remove only the exact main file we created and its private sidecars."""
    if expected_identity is None:
        return
    try:
        visible = os.stat(destination, follow_symlinks=False)
    except OSError:
        return
    if (
        not stat.S_ISREG(visible.st_mode)
        or stat.S_ISLNK(visible.st_mode)
        or _identity(visible) != expected_identity
    ):
        return
    _remove_snapshot_sidecars(destination)
    with contextlib.suppress(OSError):
        destination.unlink()


def _remove_snapshot_sidecars(destination: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        with contextlib.suppress(OSError):
            destination.with_name(destination.name + suffix).unlink()


def _discard_precreated_destination(destination: Path, descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        expected_identity = _identity(os.fstat(descriptor))
    except OSError:
        expected_identity = None
    with contextlib.suppress(OSError):
        os.close(descriptor)
    _remove_snapshot_files(destination, expected_identity=expected_identity)


def snapshot_work_db_to_disk(
    source: Path,
    destination: Path,
    *,
    _destination_fd: int | None = None,
) -> Path | None:
    """Create a consistent, closed Work-store snapshot at *destination*.

    The source is opened read-only, so a missing source returns ``None``
    without creating either database.  The destination must be a unique path;
    normal callers let this function create it with ``O_EXCL``.  The private
    descriptor hook is used only by quick-backup's already-pinned attempt
    writer and must identify that exact 0600 file.
    """
    source = Path(source)
    destination = Path(destination)
    try:
        source_metadata = os.stat(source, follow_symlinks=False)
    except FileNotFoundError:
        _discard_precreated_destination(destination, _destination_fd)
        return None
    except OSError as exc:
        _discard_precreated_destination(destination, _destination_fd)
        raise WorkStoreSnapshotError(
            "source_unavailable", f"cannot inspect work.db: {exc}"
        ) from exc

    if not stat.S_ISREG(source_metadata.st_mode) or stat.S_ISLNK(source_metadata.st_mode):
        _discard_precreated_destination(destination, _destination_fd)
        raise WorkStoreSnapshotError(
            "source_not_regular", "work.db must be a regular non-symlink file"
        )
    source_identity = _identity(source_metadata)
    try:
        source_resolved = source.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        _discard_precreated_destination(destination, _destination_fd)
        raise WorkStoreSnapshotError(
            "source_unavailable", f"cannot resolve work.db: {exc}"
        ) from exc

    try:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        _discard_precreated_destination(destination, _destination_fd)
        raise WorkStoreSnapshotError(
            "destination_unavailable",
            f"cannot create Work snapshot parent directory: {exc}",
        ) from exc
    descriptor = _destination_fd
    if descriptor is None:
        descriptor = _create_private_destination(destination)
    elif not _destination_matches(descriptor, destination):
        _discard_precreated_destination(destination, descriptor)
        raise WorkStoreSnapshotError(
            "destination_changed",
            "Work snapshot destination changed before SQLite backup",
        )
    try:
        destination_identity = _identity(os.fstat(descriptor))
    except OSError as exc:
        _discard_precreated_destination(destination, descriptor)
        raise WorkStoreSnapshotError(
            "destination_unavailable",
            f"cannot inspect Work snapshot destination: {exc}",
        ) from exc

    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None
    succeeded = False
    try:
        source_connection = sqlite3.connect(
            _sqlite_uri(source_resolved, mode="ro"),
            uri=True,
            timeout=5.0,
        )
        destination_connection = sqlite3.connect(
            _sqlite_uri(destination.resolve(strict=True), mode="rw"),
            uri=True,
            timeout=5.0,
        )
        _copy_sqlite_snapshot(source_connection, destination_connection)

        journal_mode = destination_connection.execute(
            "PRAGMA journal_mode=DELETE"
        ).fetchone()
        if not journal_mode or str(journal_mode[0]).casefold() != "delete":
            raise WorkStoreSnapshotError(
                "journal_mode_failed",
                "Work snapshot could not be normalized to DELETE journal mode",
            )
        quick_check = destination_connection.execute("PRAGMA quick_check").fetchall()
        if quick_check != [("ok",)]:
            raise WorkStoreSnapshotError(
                "integrity_check_failed", "Work snapshot quick_check failed"
            )
        destination_connection.commit()

        current_source = os.stat(source_resolved, follow_symlinks=False)
        if _identity(current_source) != source_identity:
            raise WorkStoreSnapshotError(
                "source_replaced", "work.db was replaced while it was being backed up"
            )
        if not _destination_matches(descriptor, destination):
            raise WorkStoreSnapshotError(
                "destination_changed", "Work snapshot destination changed during backup"
            )
        succeeded = True
    except WorkStoreSnapshotError:
        raise
    except Exception as exc:
        raise WorkStoreSnapshotError(
            "snapshot_failed", f"could not snapshot work.db: {exc}"
        ) from exc
    finally:
        if destination_connection is not None:
            with contextlib.suppress(Exception):
                destination_connection.close()
        if source_connection is not None:
            with contextlib.suppress(Exception):
                source_connection.close()
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if not succeeded:
            _remove_snapshot_files(
                destination,
                expected_identity=destination_identity,
            )

    try:
        if os.name == "nt":  # pragma: no cover - native Windows CI
            os.chmod(destination, 0o600)
        else:
            os.chmod(destination, 0o600, follow_symlinks=False)
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        file_flags |= getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(destination, file_flags)
        try:
            if not _destination_matches(file_descriptor, destination):
                raise WorkStoreSnapshotError(
                    "destination_changed", "closed Work snapshot is not private and stable"
                )
            _remove_snapshot_sidecars(destination)
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
        _fsync_parent(destination.parent)
    except WorkStoreSnapshotError:
        _remove_snapshot_files(
            destination,
            expected_identity=destination_identity,
        )
        raise
    except OSError as exc:
        _remove_snapshot_files(
            destination,
            expected_identity=destination_identity,
        )
        raise WorkStoreSnapshotError(
            "snapshot_fsync_failed", f"could not fsync Work snapshot: {exc}"
        ) from exc

    return destination


__all__ = [
    "WORK_STORE_PRIVATE_BASENAMES",
    "WorkStoreSnapshotError",
    "is_work_store_private_basename",
    "snapshot_work_db_to_disk",
]
