"""Journaled, profile-scoped capability-pack filesystem transactions.

The read-only planner remains in :mod:`fabric_cli.capability_pack_lifecycle`.
This private, unwired mutation edge invokes the strict source-backed catalog
loader, stages and scans exact admitted trees, writes a complete journal,
promotes under shared profile locks, and commits state only after every
filesystem operation succeeds.

Recovery infers reality from state and tree digests.  Journal progress fields
are diagnostic only and are never trusted as proof that a move occurred.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from fabric_cli import capability_pack_lifecycle as lifecycle
from fabric_cli.capability_pack_lifecycle import (
    MutationPlanStatus,
    PackPlanResult,
    plan_pack,
)
from fabric_cli.capability_packs import canonical_json_bytes, load_compiled_catalog
from tools.skill_install import (
    UnsafePathError,
    is_path_redirect,
    normalize_relative_path,
    resolve_relative_path,
    sha256_tree,
)
from tools.skill_mutation import (
    PackMutationLocks,
    SkillMutationLockError,
    SkillMutationLockTimeout,
    pack_mutation_locks,
    validate_pack_mutation_locks,
)
from tools.skills_guard import scan_skill


MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_STATE_BYTES = lifecycle.MAX_PACK_STATE_BYTES
MAX_SKILL_FILE_BYTES = 16 * 1024 * 1024
MAX_SKILL_TREE_BYTES = 64 * 1024 * 1024
_SHA256_EMPTY = hashlib.sha256(b"").hexdigest()
_TERMINAL_PHASES = frozenset({"committed", "rolled_back"})


class PackTransactionIssueCode(StrEnum):
    IO_UNAVAILABLE = "IO_UNAVAILABLE"
    JOURNAL_INVALID = "JOURNAL_INVALID"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    OPERATION_REQUIRED = "OPERATION_REQUIRED"
    PLAN_CONFLICT = "PLAN_CONFLICT"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    SCAN_BLOCKED = "SCAN_BLOCKED"
    SOURCE_DIGEST_MISMATCH = "SOURCE_DIGEST_MISMATCH"
    USER_MODIFIED_CONFLICT = "USER_MODIFIED_CONFLICT"


class PackMutationStatus(StrEnum):
    APPLIED = "applied"
    UPDATED = "updated"
    REPAIRED = "repaired"
    UNCHANGED = "unchanged"
    BLOCKED = "blocked"
    CONFLICT = "conflict"
    REVISION_CONFLICT = "revision_conflict"
    PLAN_CONFLICT = "plan_conflict"
    ROLLED_BACK = "rolled_back"
    RECOVERY_REQUIRED = "recovery_required"


class RecoveryStatus(StrEnum):
    CLEAN = "clean"
    RECOVERED = "recovered"
    MANUAL_INTERVENTION = "manual_intervention"


@dataclass(frozen=True)
class PackMutationIssue:
    code: PackTransactionIssueCode
    message: str
    transaction_id: str | None = None


@dataclass(frozen=True)
class PackMutationResult:
    status: PackMutationStatus
    pack_id: str
    version: str
    revision: int | None
    transaction_id: str | None
    plan: PackPlanResult | None
    issues: tuple[PackMutationIssue, ...] = ()


@dataclass(frozen=True)
class RecoveryDisposition:
    transaction_id: str
    outcome: Literal["committed", "rolled_back"]


@dataclass(frozen=True)
class RecoveryResult:
    status: RecoveryStatus
    dispositions: tuple[RecoveryDisposition, ...] = ()
    manual_transactions: tuple[str, ...] = ()
    issues: tuple[PackMutationIssue, ...] = ()


class _MutationFailure(RuntimeError):
    def __init__(self, code: PackTransactionIssueCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class _PinnedDirectory:
    path: Path
    fd: int | None = None
    identity: tuple[int, int] | None = None
    windows_handles: tuple[int, ...] = ()


def _windows_open_directory_handle(path: Path) -> int:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    file_read_attributes = 0x0080
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    invalid_handle_value = ctypes.c_void_p(-1).value

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    raw_handle = kernel32.CreateFileW(
        os.fspath(path),
        file_read_attributes,
        file_share_read | file_share_write,
        None,
        open_existing,
        file_flag_backup_semantics | file_flag_open_reparse_point,
        None,
    )
    handle = ctypes.cast(raw_handle, ctypes.c_void_p).value
    if handle in (None, invalid_handle_value):
        raise ctypes.WinError(ctypes.get_last_error())
    information = BY_HANDLE_FILE_INFORMATION()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(information)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise ctypes.WinError(error)
    if (
        not information.dwFileAttributes & file_attribute_directory
        or information.dwFileAttributes & file_attribute_reparse_point
    ):
        kernel32.CloseHandle(handle)
        raise OSError("pinned directory is not a regular directory")
    return handle


def _windows_close_handle(handle: int) -> None:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)


def _windows_replace_write_through(
    source: Path, destination: Path
) -> None:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    movefile_replace_existing = 0x00000001
    movefile_write_through = 0x00000008
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    kernel32.MoveFileExW.restype = wintypes.BOOL
    if not kernel32.MoveFileExW(
        os.fspath(source),
        os.fspath(destination),
        movefile_replace_existing | movefile_write_through,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


@contextlib.contextmanager
def _pinned_directory(
    root: Path,
    directory: Path,
    *,
    create: bool = False,
):
    """Pin one descendant directory across a filesystem mutation."""

    try:
        resolved_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "mutation root could not be resolved",
        ) from exc
    canonical_root = _safe_existing_directory(resolved_root, label="mutation root")
    try:
        candidate = Path(directory).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "mutation directory could not be resolved",
        ) from exc
    try:
        relative = candidate.relative_to(canonical_root)
    except ValueError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "mutation directory escaped its fixed root",
        ) from exc
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "mutation directory is not canonical",
        )

    if os.name == "nt":  # pragma: no cover - Windows
        handles: list[int] = []
        cursor = canonical_root
        try:
            handles.append(_windows_open_directory_handle(cursor))
            for component in relative.parts:
                cursor = cursor / component
                if not cursor.exists() and not cursor.is_symlink():
                    if not create:
                        raise FileNotFoundError(cursor)
                    cursor.mkdir(mode=0o700)
                if is_path_redirect(cursor):
                    raise OSError("mutation directory became a redirect")
                handles.append(_windows_open_directory_handle(cursor))
            yield _PinnedDirectory(cursor, windows_handles=tuple(handles))
        except _MutationFailure:
            raise
        except OSError as exc:
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "could not pin mutation directory",
            ) from exc
        finally:
            for handle in reversed(handles):
                with contextlib.suppress(OSError):
                    _windows_close_handle(handle)
        return

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    try:
        root_before = canonical_root.lstat()
        descriptor = os.open(canonical_root, flags)
        root_opened = os.fstat(descriptor)
        if (root_before.st_dev, root_before.st_ino) != (
            root_opened.st_dev,
            root_opened.st_ino,
        ):
            raise OSError("mutation root changed before open")
        cursor = canonical_root
        for component in relative.parts:
            cursor = cursor / component
            try:
                before = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                before = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise OSError("mutation path component is not a directory")
            child = os.open(component, flags, dir_fd=descriptor)
            opened = os.fstat(child)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                os.close(child)
                raise OSError("mutation directory changed before open")
            os.close(descriptor)
            descriptor = child
        final = os.fstat(descriptor)
        yield _PinnedDirectory(
            cursor,
            fd=descriptor,
            identity=(final.st_dev, final.st_ino),
        )
    except _MutationFailure:
        raise
    except OSError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "could not pin mutation directory",
        ) from exc
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _create_directory(root: Path, path: Path, *, mode: int = 0o700) -> None:
    """Create one leaf directory relative to a pinned existing parent."""

    with _pinned_directory(root, path.parent) as parent:
        try:
            _validate_pinned_directory(parent)
            if parent.fd is not None:
                os.mkdir(path.name, mode=mode, dir_fd=parent.fd)
                os.fsync(parent.fd)
            else:  # pragma: no cover - Windows
                (parent.path / path.name).mkdir(mode=mode)
            _validate_pinned_directory(parent)
        except OSError as exc:
            raise _MutationFailure(
                PackTransactionIssueCode.IO_UNAVAILABLE,
                f"could not create directory {path.name}",
            ) from exc


def _validate_pinned_directory(pinned: _PinnedDirectory) -> None:
    """Prove the pinned directory still occupies its expected pathname."""

    try:
        if is_path_redirect(pinned.path):
            raise OSError("pinned directory path became a redirect")
        current = pinned.path.lstat()
        if not stat.S_ISDIR(current.st_mode):
            raise OSError("pinned directory path changed type")
        if pinned.identity is not None and (current.st_dev, current.st_ino) != (
            pinned.identity
        ):
            raise OSError("pinned directory path changed identity")
    except OSError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.USER_MODIFIED_CONFLICT,
            "mutation directory changed while pinned",
        ) from exc


def _safe_existing_directory(path: Path, *, label: str) -> Path:
    try:
        if is_path_redirect(path):
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                f"{label} must not be a redirect",
            )
        mode = path.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                f"{label} must be a directory",
            )
        return path.resolve(strict=True)
    except _MutationFailure:
        raise
    except OSError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.IO_UNAVAILABLE,
            f"could not inspect {label}",
        ) from exc


def _ensure_profile_roots(home: Path) -> tuple[Path, Path, Path]:
    explicit_home = Path(home).resolve(strict=False)
    if explicit_home.exists() and not explicit_home.is_dir():
        raise _MutationFailure(
            PackTransactionIssueCode.IO_UNAVAILABLE,
            "profile home must be a directory",
        )
    explicit_home.mkdir(parents=True, exist_ok=True)
    skills = explicit_home / "skills"
    packs = explicit_home / "capability-packs"
    for path, label in ((skills, "skills root"), (packs, "pack state root")):
        if path.exists() or path.is_symlink():
            _safe_existing_directory(path, label=label)
        else:
            _create_directory(explicit_home, path)
            _safe_existing_directory(path, label=label)
    transactions = packs / "transactions"
    if transactions.exists() or transactions.is_symlink():
        _safe_existing_directory(transactions, label="transactions root")
    else:
        _create_directory(explicit_home, transactions)
        _safe_existing_directory(transactions, label="transactions root")
    return explicit_home, skills, packs


def _read_regular_bytes(path: Path, *, limit: int, label: str) -> bytes | None:
    try:
        if not path.exists() and not path.is_symlink():
            return None
        if is_path_redirect(path):
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                f"{label} must not be a redirect",
            )
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise OSError(f"{label} is not a bounded regular file")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError(f"{label} changed type")
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise OSError(f"{label} changed identity")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise OSError(f"{label} exceeds its byte limit")
            after = os.fstat(descriptor)
            if (
                opened.st_size,
                getattr(opened, "st_mtime_ns", None),
                getattr(opened, "st_ctime_ns", None),
            ) != (
                after.st_size,
                getattr(after, "st_mtime_ns", None),
                getattr(after, "st_ctime_ns", None),
            ):
                raise OSError(f"{label} changed while reading")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    except _MutationFailure:
        raise
    except OSError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.IO_UNAVAILABLE,
            f"could not safely read {label}",
        ) from exc


def _atomic_write(
    path: Path,
    payload: bytes,
    *,
    root: Path,
    mode: int = 0o600,
) -> None:
    temporary_name = f".{path.name}.{uuid.uuid4()}.tmp"
    descriptor: int | None = None
    pinned: _PinnedDirectory | None = None
    try:
        with _pinned_directory(root, path.parent) as pinned_directory:
            pinned = pinned_directory
            temporary = pinned.path / temporary_name
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            if pinned.fd is not None:
                descriptor = os.open(temporary_name, flags, mode, dir_fd=pinned.fd)
            else:  # pragma: no cover - Windows
                descriptor = os.open(temporary, flags, mode)
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, mode)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            _validate_pinned_directory(pinned)
            if pinned.fd is not None:
                try:
                    existing = os.stat(
                        path.name,
                        dir_fd=pinned.fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    existing = None
                if existing is not None and not stat.S_ISREG(existing.st_mode):
                    raise _MutationFailure(
                        PackTransactionIssueCode.JOURNAL_INVALID,
                        f"refused to replace non-regular {path.name}",
                    )
                os.replace(
                    temporary_name,
                    path.name,
                    src_dir_fd=pinned.fd,
                    dst_dir_fd=pinned.fd,
                )
                os.fsync(pinned.fd)
            else:  # pragma: no cover - Windows
                if is_path_redirect(path):
                    raise _MutationFailure(
                        PackTransactionIssueCode.JOURNAL_INVALID,
                        f"refused to replace redirected {path.name}",
                    )
                _windows_replace_write_through(temporary, pinned.path / path.name)
            _validate_pinned_directory(pinned)
    except _MutationFailure:
        raise
    except OSError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.IO_UNAVAILABLE,
            f"could not atomically write {path.name}",
        ) from exc
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        # A successful replace consumes the temporary.  On failure, leave an
        # untrusted-path-safe orphan inside the pinned parent rather than
        # re-resolving a parent that may have been swapped by a racing writer.


def _replace_path(source: Path, destination: Path, *, root: Path) -> None:
    """Replace one path after immediately revalidating both parent roots."""

    try:
        with _pinned_directory(root, source.parent) as source_parent:
            with _pinned_directory(root, destination.parent) as destination_parent:
                _validate_pinned_directory(source_parent)
                _validate_pinned_directory(destination_parent)
                if source_parent.fd is not None and destination_parent.fd is not None:
                    source_state = os.stat(
                        source.name,
                        dir_fd=source_parent.fd,
                        follow_symlinks=False,
                    )
                    if not stat.S_ISDIR(source_state.st_mode):
                        raise OSError("move source is not a directory")
                    try:
                        destination_state = os.stat(
                            destination.name,
                            dir_fd=destination_parent.fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        destination_state = None
                    if destination_state is not None and not stat.S_ISDIR(
                        destination_state.st_mode
                    ):
                        raise OSError("move destination is not a directory")
                    os.replace(
                        source.name,
                        destination.name,
                        src_dir_fd=source_parent.fd,
                        dst_dir_fd=destination_parent.fd,
                    )
                    promoted = os.stat(
                        destination.name,
                        dir_fd=destination_parent.fd,
                        follow_symlinks=False,
                    )
                    if (source_state.st_dev, source_state.st_ino) != (
                        promoted.st_dev,
                        promoted.st_ino,
                    ):
                        raise OSError("moved directory changed identity")
                    os.fsync(source_parent.fd)
                    if destination_parent.fd != source_parent.fd:
                        os.fsync(destination_parent.fd)
                else:  # pragma: no cover - Windows
                    if is_path_redirect(source) or is_path_redirect(destination):
                        raise OSError("refused to move a redirected skill path")
                    _windows_replace_write_through(
                        source_parent.path / source.name,
                        destination_parent.path / destination.name,
                    )
                _validate_pinned_directory(source_parent)
                _validate_pinned_directory(destination_parent)
    except OSError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.IO_UNAVAILABLE,
            "atomic capability-pack path promotion failed",
        ) from exc


def _safe_mkdir_parents(root: Path, relative: str) -> Path:
    normalized = normalize_relative_path(relative)
    target = resolve_relative_path(root, normalized, must_exist=False)
    parent_relative = Path(normalized).parent
    parent = Path(root).resolve(strict=True) / parent_relative
    with _pinned_directory(root, parent, create=True):
        pass
    return target


def _tree_digest(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if is_path_redirect(path):
            raise UnsafePathError("redirect roots are not allowed")
        return sha256_tree(
            path,
            max_file_bytes=MAX_SKILL_FILE_BYTES,
            max_total_bytes=MAX_SKILL_TREE_BYTES,
        )
    except (OSError, RuntimeError, UnsafePathError, ValueError) as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.USER_MODIFIED_CONFLICT,
            f"could not safely hash capability-pack path: {path}",
        ) from exc


def _strict_json(raw: bytes, *, label: str) -> Mapping[str, Any]:
    def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite number: {value}")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            f"{label} is not strict UTF-8 JSON",
        ) from exc
    if not isinstance(value, Mapping):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            f"{label} must contain an object",
        )
    return value


def _state_raw(home: Path) -> bytes | None:
    return _read_regular_bytes(
        Path(home) / "capability-packs" / "state.json",
        limit=MAX_STATE_BYTES,
        label="capability-pack state",
    )


def _installed_pack_mapping(installed: lifecycle._InstalledPack) -> dict[str, Any]:
    return {
        "installed_at": installed.installed_at,
        "manifest_sha256": installed.manifest_sha256,
        "members": {
            name: {
                "effective_path": member.effective_path,
                "installed_sha256": member.installed_sha256,
                "ownership": member.ownership,
                "source_sha256": member.source_sha256,
            }
            for name, member in sorted(installed.members.items())
        },
        "owned": {
            path: {"kind": record.kind, "sha256": record.sha256}
            for path, record in sorted(installed.owned.items())
        },
        "updated_at": installed.updated_at,
        "version": installed.version,
    }


def _build_new_state(
    *,
    home: Path,
    catalog: Mapping[str, Any],
    plan: PackPlanResult,
    transaction_id: str,
    now: datetime,
) -> tuple[dict[str, Any], bytes]:
    state = lifecycle._load_pack_state(home)
    release, artifacts = lifecycle._select_release(
        catalog, plan.pack_id, plan.to_version
    )
    installed = {
        pack_id: _installed_pack_mapping(pack)
        for pack_id, pack in sorted(state.installed.items())
        if pack_id != plan.pack_id
    }
    old = state.installed.get(plan.pack_id)
    timestamp = now.astimezone(timezone.utc).isoformat()
    member_statuses = {member.name: member for member in plan.members}
    owned: dict[str, dict[str, str]] = {}
    members: dict[str, dict[str, str | None]] = {}
    for artifact in artifacts:
        status = member_statuses[artifact.name]
        if not status.enabled:
            continue
        if artifact.ownership == "pack":
            assert artifact.install_path is not None
            owned[artifact.install_path] = {
                "kind": artifact.artifact_kind,
                "sha256": artifact.source_tree_sha256,
            }
        if artifact.artifact_kind == "router":
            continue
        effective_path = (
            artifact.install_path
            if artifact.ownership == "pack"
            else status.effective_path or artifact.source_path
        )
        assert effective_path is not None
        members[artifact.name] = {
            "effective_path": effective_path,
            "installed_sha256": (
                artifact.source_tree_sha256 if artifact.ownership == "pack" else None
            ),
            "ownership": artifact.ownership,
            "source_sha256": artifact.source_tree_sha256,
        }
    manifest = lifecycle._mapping(
        release.get("authoring_manifest"), "authoring_manifest"
    )
    installed[plan.pack_id] = {
        "installed_at": old.installed_at if old is not None else timestamp,
        "manifest_sha256": manifest["sha256"],
        "members": members,
        "owned": owned,
        "updated_at": timestamp,
        "version": plan.to_version,
    }
    value = {
        "installed": installed,
        "last_transaction_id": transaction_id,
        "revision": state.revision + 1,
        "schema_version": 1,
    }
    return value, canonical_json_bytes(value)


def _source_root(
    source_kind: str,
    *,
    capability_packs_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
) -> Path:
    roots = {
        "pack": capability_packs_root,
        "bundled": bundled_skills_root,
        "optional": optional_skills_root,
    }
    try:
        root = Path(roots[source_kind]).resolve(strict=True)
    except (KeyError, OSError, RuntimeError) as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.SOURCE_DIGEST_MISMATCH,
            f"unavailable source root for {source_kind!r}",
        ) from exc
    if not root.is_dir():
        raise _MutationFailure(
            PackTransactionIssueCode.SOURCE_DIGEST_MISMATCH,
            f"source root for {source_kind!r} is not a directory",
        )
    return root


def _copy_verified_tree(source: Path, stage: Path, expected_sha256: str) -> None:
    before = _tree_digest(source)
    if before != expected_sha256:
        raise _MutationFailure(
            PackTransactionIssueCode.SOURCE_DIGEST_MISMATCH,
            f"source tree digest mismatch for {source}",
        )
    try:
        shutil.copytree(source, stage, symlinks=False)
    except OSError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.IO_UNAVAILABLE,
            f"could not stage admitted source tree {source}",
        ) from exc
    staged = _tree_digest(stage)
    after = _tree_digest(source)
    if staged != expected_sha256 or after != expected_sha256:
        raise _MutationFailure(
            PackTransactionIssueCode.SOURCE_DIGEST_MISMATCH,
            f"source tree changed while staging {source}",
        )
    # Pack signatures cover the complete source tree. Ignore files therefore
    # cannot narrow admission: every byte whose digest is signed and promoted
    # is scanned, including `.skillignore` and paths it names.
    scan = scan_skill(
        stage,
        source="fabric/capability-packs",
        respect_skillignore=False,
    )
    if scan.verdict != "safe":
        raise _MutationFailure(
            PackTransactionIssueCode.SCAN_BLOCKED,
            f"staged skill {stage.name} failed the safety scan: {scan.verdict}",
        )
    if _tree_digest(stage) != expected_sha256:
        raise _MutationFailure(
            PackTransactionIssueCode.SOURCE_DIGEST_MISMATCH,
            f"staged tree changed during safety scan: {stage}",
        )


def _journal_path(transaction_root: Path) -> Path:
    return transaction_root / "journal.json"


def _write_journal(transaction_root: Path, journal: Mapping[str, Any]) -> None:
    _atomic_write(
        _journal_path(transaction_root),
        canonical_json_bytes(journal),
        root=transaction_root.parents[2],
    )


def _update_journal(
    transaction_root: Path,
    journal: dict[str, Any],
    *,
    phase: str | None = None,
    operation_index: int | None = None,
    observed_phase: str | None = None,
) -> None:
    if phase is not None:
        journal["phase"] = phase
    if operation_index is not None and observed_phase is not None:
        journal["operations"][operation_index]["observed_phase"] = observed_phase
    _write_journal(transaction_root, journal)


def _prepare_transaction(
    *,
    home: Path,
    locks: PackMutationLocks,
    transaction_id: str,
    catalog: Mapping[str, Any],
    plan: PackPlanResult,
    capability_packs_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    now: datetime,
) -> tuple[Path, dict[str, Any], bytes]:
    validate_pack_mutation_locks(home, locks)
    _home, _skills, packs_root = _ensure_profile_roots(home)
    transaction_root = packs_root / "transactions" / transaction_id
    _create_directory(_home, transaction_root)
    stage_root = transaction_root / "stage"
    backup_root = transaction_root / "backup"
    _create_directory(_home, stage_root)
    _create_directory(_home, backup_root)

    old_state_raw = _state_raw(home)
    old_state_payload = old_state_raw if old_state_raw is not None else b""
    old_state_relative = f"transactions/{transaction_id}/old-state.json"
    new_state_relative = f"transactions/{transaction_id}/new-state.json"
    _atomic_write(transaction_root / "old-state.json", old_state_payload, root=_home)
    _new_state, new_state_raw = _build_new_state(
        home=home,
        catalog=catalog,
        plan=plan,
        transaction_id=transaction_id,
        now=now,
    )
    _atomic_write(transaction_root / "new-state.json", new_state_raw, root=_home)

    journal_operations: list[dict[str, Any]] = []
    for index, operation in enumerate(
        item for item in plan.operations if item.kind in {"promote", "remove"}
    ):
        validate_pack_mutation_locks(home, locks)
        if operation.destination_relative_path is None:
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "mutation operation is missing its destination",
            )
        backup_relative = f"transactions/{transaction_id}/backup/{index}"
        stage_relative: str | None = None
        if operation.kind == "promote":
            stage_relative = f"transactions/{transaction_id}/stage/{index}"
            source_root = _source_root(
                operation.source_kind,
                capability_packs_root=capability_packs_root,
                bundled_skills_root=bundled_skills_root,
                optional_skills_root=optional_skills_root,
            )
            try:
                source = resolve_relative_path(
                    source_root,
                    operation.source_relative_path,
                    must_exist=True,
                )
            except UnsafePathError as exc:
                raise _MutationFailure(
                    PackTransactionIssueCode.SOURCE_DIGEST_MISMATCH,
                    f"unsafe admitted source path: {operation.source_relative_path}",
                ) from exc
            assert operation.after_sha256 is not None
            _copy_verified_tree(
                source,
                stage_root / str(index),
                operation.after_sha256,
            )
        journal_operations.append({
            "after_sha256": operation.after_sha256,
            "backup_relative_path": backup_relative,
            "before_sha256": operation.before_sha256,
            "destination_relative_path": operation.destination_relative_path,
            "kind": operation.kind,
            "observed_phase": "planned",
            "operation_id": str(uuid.uuid4()),
            "stage_relative_path": stage_relative,
        })

    journal: dict[str, Any] = {
        "from_revision": plan.expected_revision,
        "new_config_relative_path": None,
        "new_config_sha256": None,
        "new_state_relative_path": new_state_relative,
        "new_state_sha256": _sha256_bytes(new_state_raw),
        "old_config_relative_path": None,
        "old_config_sha256": None,
        "old_state_present": old_state_raw is not None,
        "old_state_relative_path": old_state_relative,
        "old_state_sha256": _sha256_bytes(old_state_payload),
        "operation": plan.operation,
        "operations": journal_operations,
        "pack_id": plan.pack_id,
        "phase": "prepared",
        "schema_version": 1,
        "to_revision": plan.expected_revision + 1,
        "transaction_id": transaction_id,
    }
    validate_pack_mutation_locks(home, locks)
    _write_journal(transaction_root, journal)
    return transaction_root, journal, new_state_raw


def _safe_transaction_path(
    packs_root: Path,
    transaction_root: Path,
    relative: str,
    *,
    prefix: str,
) -> Path:
    canonical = normalize_relative_path(relative, field="journal path")
    transaction_id = transaction_root.name
    expected_prefix = f"transactions/{transaction_id}/{prefix}"
    if canonical != expected_prefix and not canonical.startswith(expected_prefix + "/"):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            f"journal path escapes its fixed {prefix} root",
        )
    try:
        path = resolve_relative_path(packs_root, canonical, must_exist=False)
    except UnsafePathError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            f"unsafe journal path: {relative}",
        ) from exc
    if path != transaction_root / Path(canonical).relative_to(
        f"transactions/{transaction_id}"
    ):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            f"journal path is not transaction-bound: {relative}",
        )
    return path


def _parse_uuid(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID, f"{field} must be a UUID"
        )
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID, f"{field} must be a UUID"
        ) from exc
    if str(parsed) != value:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID, f"{field} must be canonical"
        )
    return value


def _load_journal(transaction_root: Path, packs_root: Path) -> dict[str, Any]:
    raw = _read_regular_bytes(
        _journal_path(transaction_root),
        limit=MAX_JOURNAL_BYTES,
        label="capability-pack transaction journal",
    )
    if raw is None:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "transaction directory has no journal",
        )
    value = dict(_strict_json(raw, label="transaction journal"))
    required = {
        "from_revision",
        "new_config_relative_path",
        "new_config_sha256",
        "new_state_relative_path",
        "new_state_sha256",
        "old_config_relative_path",
        "old_config_sha256",
        "old_state_present",
        "old_state_relative_path",
        "old_state_sha256",
        "operation",
        "operations",
        "pack_id",
        "phase",
        "schema_version",
        "to_revision",
        "transaction_id",
    }
    if (
        set(value) != required
        or isinstance(value.get("schema_version"), bool)
        or value.get("schema_version") != 1
    ):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "transaction journal has missing, unknown, or unsupported fields",
        )
    transaction_id = _parse_uuid(value["transaction_id"], field="transaction_id")
    if transaction_id != transaction_root.name:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "journal transaction ID does not match its directory",
        )
    pack_id = value["pack_id"]
    if not isinstance(pack_id, str) or lifecycle._PACK_ID_RE.fullmatch(pack_id) is None:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "journal pack ID is invalid",
        )
    if value["operation"] not in {"apply", "update", "downgrade", "remove", "override"}:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "journal operation is invalid",
        )
    if value["phase"] not in {
        "prepared",
        "promoting",
        "state_written",
        "committed",
        "rolled_back",
        "manual_intervention",
    }:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID, "journal phase is invalid"
        )
    if (
        isinstance(value["from_revision"], bool)
        or not isinstance(value["from_revision"], int)
        or value["from_revision"] < 0
        or isinstance(value["to_revision"], bool)
        or not isinstance(value["to_revision"], int)
        or value["to_revision"] != value["from_revision"] + 1
    ):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "journal revision transition is invalid",
        )
    for field in ("old_state_sha256", "new_state_sha256"):
        if (
            not isinstance(value[field], str)
            or lifecycle._SHA256_RE.fullmatch(value[field]) is None
        ):
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                f"journal {field} is invalid",
            )
    if not isinstance(value["old_state_present"], bool):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "journal old_state_present must be boolean",
        )
    for field, prefix in (
        ("old_state_relative_path", "old-state.json"),
        ("new_state_relative_path", "new-state.json"),
    ):
        if not isinstance(value[field], str):
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                f"journal {field} is invalid",
            )
        expected = f"transactions/{transaction_id}/{prefix}"
        if (
            normalize_relative_path(value[field], field="journal state path")
            != expected
        ):
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                f"journal {field} must use its fixed transaction path",
            )
        _safe_transaction_path(
            packs_root, transaction_root, value[field], prefix=prefix
        )
    if any(
        value[field] is not None
        for field in (
            "old_config_sha256",
            "old_config_relative_path",
            "new_config_sha256",
            "new_config_relative_path",
        )
    ):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "apply recovery does not accept an unimplemented config mutation",
        )
    operations = value["operations"]
    if not isinstance(operations, list):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "journal operations must be a list",
        )
    destinations: set[str] = set()
    portable_destinations: set[str] = set()
    operation_ids: set[str] = set()
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping) or set(operation) != {
            "after_sha256",
            "backup_relative_path",
            "before_sha256",
            "destination_relative_path",
            "kind",
            "observed_phase",
            "operation_id",
            "stage_relative_path",
        }:
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "journal operation has missing or unknown fields",
            )
        operation_id = _parse_uuid(operation["operation_id"], field="operation_id")
        if operation_id in operation_ids:
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "journal operation IDs must be unique",
            )
        operation_ids.add(operation_id)
        if operation["kind"] not in {"promote", "remove"} or operation[
            "observed_phase"
        ] not in {"planned", "backup_present", "destination_present"}:
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "journal operation phase/kind is invalid",
            )
        destination = normalize_relative_path(
            operation["destination_relative_path"], field="journal destination"
        )
        portable_destination = destination.casefold()
        if portable_destination in portable_destinations or any(
            destination.startswith(existing + "/")
            or existing.startswith(destination + "/")
            for existing in destinations
        ):
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "journal destinations must be unique, portable, and non-overlapping",
            )
        destinations.add(destination)
        portable_destinations.add(portable_destination)
        for field in ("before_sha256", "after_sha256"):
            digest = operation[field]
            if digest is not None and (
                not isinstance(digest, str)
                or lifecycle._SHA256_RE.fullmatch(digest) is None
            ):
                raise _MutationFailure(
                    PackTransactionIssueCode.JOURNAL_INVALID,
                    f"journal operation {field} is invalid",
                )
        if operation["kind"] == "promote" and operation["after_sha256"] is None:
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "promote operation requires an after digest",
            )
        if operation["kind"] == "remove" and (
            operation["after_sha256"] is not None
            or operation["stage_relative_path"] is not None
        ):
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "remove operation cannot carry stage/post bytes",
            )
        expected_backup = f"transactions/{transaction_id}/backup/{index}"
        if operation["backup_relative_path"] != expected_backup:
            raise _MutationFailure(
                PackTransactionIssueCode.JOURNAL_INVALID,
                "journal backup path is not bound to its operation index",
            )
        _safe_transaction_path(
            packs_root,
            transaction_root,
            operation["backup_relative_path"],
            prefix="backup",
        )
        if operation["stage_relative_path"] is not None:
            expected_stage = f"transactions/{transaction_id}/stage/{index}"
            if operation["stage_relative_path"] != expected_stage:
                raise _MutationFailure(
                    PackTransactionIssueCode.JOURNAL_INVALID,
                    "journal stage path is not bound to its operation index",
                )
            _safe_transaction_path(
                packs_root,
                transaction_root,
                operation["stage_relative_path"],
                prefix="stage",
            )
    return value


def _journal_artifact_bytes(
    packs_root: Path,
    transaction_root: Path,
    journal: Mapping[str, Any],
    *,
    field: str,
    prefix: str,
) -> bytes:
    path = _safe_transaction_path(
        packs_root, transaction_root, journal[field], prefix=prefix
    )
    raw = _read_regular_bytes(path, limit=MAX_STATE_BYTES, label=prefix)
    digest_field = (
        "old_state_sha256" if prefix.startswith("old") else "new_state_sha256"
    )
    if raw is None or _sha256_bytes(raw) != journal[digest_field]:
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            f"journal {prefix} snapshot digest mismatch",
        )
    return raw


def _state_matches_new_transaction(raw: bytes, transaction_id: str) -> bool:
    try:
        value = _strict_json(raw, label="capability-pack state")
    except _MutationFailure:
        return False
    return value.get("last_transaction_id") == transaction_id


def _mark_commands_revision(home: Path, transaction_id: str) -> None:
    marker = Path(home) / "skills" / ".commands_revision"
    payload = f"{transaction_id}\n".encode("ascii")
    current = _read_regular_bytes(marker, limit=256, label="command revision marker")
    if current == payload:
        return
    _atomic_write(marker, payload, root=Path(home).resolve(strict=True))


def _remove_transaction_payload(transaction_root: Path, *, home: Path) -> None:
    with _pinned_directory(home, transaction_root) as pinned:
        for name in ("stage", "backup"):
            _validate_pinned_directory(pinned)
            path = pinned.path / name
            if pinned.fd is not None:
                try:
                    child = os.stat(name, dir_fd=pinned.fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(child.st_mode):
                    raise _MutationFailure(
                        PackTransactionIssueCode.JOURNAL_INVALID,
                        f"transaction {name} must be a directory",
                    )
                shutil.rmtree(name, dir_fd=pinned.fd)
                os.fsync(pinned.fd)
            else:  # pragma: no cover - Windows
                if not path.exists() and not path.is_symlink():
                    continue
                _safe_existing_directory(path, label=f"transaction {name}")
                shutil.rmtree(path)
            _validate_pinned_directory(pinned)


def _execute_transaction(
    *,
    home: Path,
    locks: PackMutationLocks,
    transaction_root: Path,
    journal: dict[str, Any],
    new_state_raw: bytes,
) -> None:
    validate_pack_mutation_locks(home, locks)
    _home, skills_root, packs_root = _ensure_profile_roots(home)
    _update_journal(transaction_root, journal, phase="promoting")
    for index, operation in enumerate(journal["operations"]):
        validate_pack_mutation_locks(home, locks)
        destination = _safe_mkdir_parents(
            skills_root, operation["destination_relative_path"]
        )
        actual = _tree_digest(destination)
        if actual != operation["before_sha256"]:
            raise _MutationFailure(
                PackTransactionIssueCode.USER_MODIFIED_CONFLICT,
                f"destination changed before promotion: {operation['destination_relative_path']}",
            )
        backup = _safe_transaction_path(
            packs_root,
            transaction_root,
            operation["backup_relative_path"],
            prefix="backup",
        )
        if operation["before_sha256"] is not None:
            if backup.exists() or backup.is_symlink():
                raise _MutationFailure(
                    PackTransactionIssueCode.JOURNAL_INVALID,
                    "transaction backup path was not empty",
                )
            _replace_path(destination, backup, root=_home)
            _update_journal(
                transaction_root,
                journal,
                operation_index=index,
                observed_phase="backup_present",
            )
        if operation["kind"] == "promote":
            stage = _safe_transaction_path(
                packs_root,
                transaction_root,
                operation["stage_relative_path"],
                prefix="stage",
            )
            if _tree_digest(stage) != operation["after_sha256"]:
                raise _MutationFailure(
                    PackTransactionIssueCode.SOURCE_DIGEST_MISMATCH,
                    "staged tree changed before promotion",
                )
            _replace_path(stage, destination, root=_home)
        if _tree_digest(destination) != operation["after_sha256"]:
            raise _MutationFailure(
                PackTransactionIssueCode.USER_MODIFIED_CONFLICT,
                "destination did not match the intended post-image",
            )
        _update_journal(
            transaction_root,
            journal,
            operation_index=index,
            observed_phase="destination_present",
        )

    # A non-pack writer may still ignore the shared lock during the migration
    # period. Re-hash the complete post-image immediately before committing
    # ownership state so an observed race fails closed instead of recording a
    # digest that was never actually installed.
    for operation in journal["operations"]:
        validate_pack_mutation_locks(home, locks)
        destination = resolve_relative_path(
            skills_root,
            operation["destination_relative_path"],
            must_exist=False,
        )
        if _tree_digest(destination) != operation["after_sha256"]:
            raise _MutationFailure(
                PackTransactionIssueCode.USER_MODIFIED_CONFLICT,
                "destination changed after promotion but before state commit",
            )

    current_state = _state_raw(home)
    if current_state is None:
        current_digest = _SHA256_EMPTY
    else:
        current_digest = _sha256_bytes(current_state)
    if current_digest != journal["old_state_sha256"]:
        raise _MutationFailure(
            PackTransactionIssueCode.USER_MODIFIED_CONFLICT,
            "capability-pack state changed during promotion",
        )
    validate_pack_mutation_locks(home, locks)
    _atomic_write(packs_root / "state.json", new_state_raw, root=_home)
    validate_pack_mutation_locks(home, locks)
    _update_journal(transaction_root, journal, phase="state_written")
    validate_pack_mutation_locks(home, locks)
    _mark_commands_revision(home, journal["transaction_id"])
    validate_pack_mutation_locks(home, locks)
    _remove_transaction_payload(transaction_root, home=home)
    validate_pack_mutation_locks(home, locks)
    _update_journal(transaction_root, journal, phase="committed")


def _restore_old_files(
    *,
    home: Path,
    locks: PackMutationLocks,
    skills_root: Path,
    packs_root: Path,
    transaction_root: Path,
    journal: dict[str, Any],
) -> None:
    for operation in reversed(journal["operations"]):
        validate_pack_mutation_locks(home, locks)
        destination = _safe_mkdir_parents(
            skills_root, operation["destination_relative_path"]
        )
        stage = None
        if operation["stage_relative_path"] is not None:
            stage = _safe_transaction_path(
                packs_root,
                transaction_root,
                operation["stage_relative_path"],
                prefix="stage",
            )
        backup = _safe_transaction_path(
            packs_root,
            transaction_root,
            operation["backup_relative_path"],
            prefix="backup",
        )
        destination_digest = _tree_digest(destination)
        backup_digest = _tree_digest(backup)
        stage_digest = _tree_digest(stage) if stage is not None else None
        before = operation["before_sha256"]
        after = operation["after_sha256"]

        if after is not None and destination_digest == after:
            if stage is None or stage_digest is not None:
                raise _MutationFailure(
                    PackTransactionIssueCode.ROLLBACK_FAILED,
                    "rollback found duplicate or missing stage identity",
                )
            _replace_path(destination, stage, root=skills_root.parent)
            destination_digest = None
            stage_digest = after
        elif destination_digest not in {before, None}:
            raise _MutationFailure(
                PackTransactionIssueCode.ROLLBACK_FAILED,
                "rollback found an unknown destination digest",
            )

        if before is None:
            if backup_digest is not None or destination_digest is not None:
                raise _MutationFailure(
                    PackTransactionIssueCode.ROLLBACK_FAILED,
                    "rollback could not prove the destination was originally absent",
                )
            continue
        if backup_digest is not None:
            if backup_digest != before or destination_digest is not None:
                raise _MutationFailure(
                    PackTransactionIssueCode.ROLLBACK_FAILED,
                    "rollback backup does not match the original destination",
                )
            _replace_path(backup, destination, root=skills_root.parent)
            destination_digest = before
        if destination_digest != before:
            raise _MutationFailure(
                PackTransactionIssueCode.ROLLBACK_FAILED,
                "rollback could not restore the original destination",
            )


def _recover_one_locked(
    *,
    home: Path,
    locks: PackMutationLocks,
    skills_root: Path,
    packs_root: Path,
    transaction_root: Path,
    journal: dict[str, Any],
) -> RecoveryDisposition:
    validate_pack_mutation_locks(home, locks)
    transaction_id = journal["transaction_id"]
    current_state = _state_raw(home)
    current_digest = (
        _sha256_bytes(current_state) if current_state is not None else _SHA256_EMPTY
    )
    old_state = _journal_artifact_bytes(
        packs_root,
        transaction_root,
        journal,
        field="old_state_relative_path",
        prefix="old-state.json",
    )
    new_state = _journal_artifact_bytes(
        packs_root,
        transaction_root,
        journal,
        field="new_state_relative_path",
        prefix="new-state.json",
    )
    if (
        _sha256_bytes(old_state) != journal["old_state_sha256"]
        or _sha256_bytes(new_state) != journal["new_state_sha256"]
    ):
        raise _MutationFailure(
            PackTransactionIssueCode.JOURNAL_INVALID,
            "transaction state snapshots do not match the journal",
        )

    if current_digest == journal["new_state_sha256"] and current_state is not None:
        if not _state_matches_new_transaction(current_state, transaction_id):
            raise _MutationFailure(
                PackTransactionIssueCode.RECOVERY_REQUIRED,
                "new state digest is not bound to the transaction ID",
            )
        for operation in journal["operations"]:
            validate_pack_mutation_locks(home, locks)
            destination = resolve_relative_path(
                skills_root,
                operation["destination_relative_path"],
                must_exist=False,
            )
            if _tree_digest(destination) != operation["after_sha256"]:
                raise _MutationFailure(
                    PackTransactionIssueCode.RECOVERY_REQUIRED,
                    "committed state does not match its installed skill trees",
                )
        validate_pack_mutation_locks(home, locks)
        _mark_commands_revision(home, transaction_id)
        validate_pack_mutation_locks(home, locks)
        _remove_transaction_payload(transaction_root, home=home)
        if journal["phase"] != "committed":
            _update_journal(transaction_root, journal, phase="committed")
        return RecoveryDisposition(transaction_id, "committed")

    old_matches = current_digest == journal["old_state_sha256"]
    if old_matches and (
        (journal["old_state_present"] and current_state is not None)
        or (not journal["old_state_present"] and current_state is None)
    ):
        _restore_old_files(
            home=home,
            locks=locks,
            skills_root=skills_root,
            packs_root=packs_root,
            transaction_root=transaction_root,
            journal=journal,
        )
        validate_pack_mutation_locks(home, locks)
        final_state = _state_raw(home)
        final_digest = (
            _sha256_bytes(final_state) if final_state is not None else _SHA256_EMPTY
        )
        if final_digest != journal["old_state_sha256"]:
            raise _MutationFailure(
                PackTransactionIssueCode.ROLLBACK_FAILED,
                "state changed while rolling back skill trees",
            )
        validate_pack_mutation_locks(home, locks)
        _remove_transaction_payload(transaction_root, home=home)
        if journal["phase"] != "rolled_back":
            _update_journal(transaction_root, journal, phase="rolled_back")
        return RecoveryDisposition(transaction_id, "rolled_back")

    raise _MutationFailure(
        PackTransactionIssueCode.RECOVERY_REQUIRED,
        "state digest matches neither the journal pre-image nor post-image",
    )


def _terminal_journal_matches_history(
    *,
    home: Path,
    packs_root: Path,
    transaction_root: Path,
    journal: Mapping[str, Any],
) -> bool:
    """Return whether a terminal phase is corroborated without using tree drift.

    Once a transaction is terminal, a user may legitimately modify or remove an
    installed skill and a later transaction may advance profile state.  Those
    are planner concerns, not reasons to replay old recovery.  A terminal claim
    is accepted only when its sealed snapshots exist, its payload was cleaned,
    and current state is either its exact terminal image or a later revision.
    """

    old_state = _journal_artifact_bytes(
        packs_root,
        transaction_root,
        journal,
        field="old_state_relative_path",
        prefix="old-state.json",
    )
    new_state = _journal_artifact_bytes(
        packs_root,
        transaction_root,
        journal,
        field="new_state_relative_path",
        prefix="new-state.json",
    )
    for name in ("stage", "backup"):
        path = transaction_root / name
        if path.exists() or path.is_symlink():
            return False
    current = _state_raw(home)
    current_digest = _sha256_bytes(current) if current is not None else _SHA256_EMPTY
    expected_digest = (
        journal["new_state_sha256"]
        if journal["phase"] == "committed"
        else journal["old_state_sha256"]
    )
    expected_present = (
        True if journal["phase"] == "committed" else journal["old_state_present"]
    )
    if current_digest == expected_digest and (
        (expected_present and current is not None)
        or (not expected_present and current is None)
    ):
        if journal["phase"] != "committed" or current is None:
            return True
        return _state_matches_new_transaction(current, journal["transaction_id"])
    if current is None:
        return False
    try:
        state = _strict_json(current, label="capability-pack state")
    except _MutationFailure:
        return False
    revision = state.get("revision")
    last_transaction_id = state.get("last_transaction_id")
    return (
        not isinstance(revision, bool)
        and isinstance(revision, int)
        and revision >= journal["to_revision"]
        and last_transaction_id != journal["transaction_id"]
        and _sha256_bytes(old_state) == journal["old_state_sha256"]
        and _sha256_bytes(new_state) == journal["new_state_sha256"]
    )


def _recover_transactions_locked(
    *, home: Path, locks: PackMutationLocks
) -> RecoveryResult:
    validate_pack_mutation_locks(home, locks)
    _home, skills_root, packs_root = _ensure_profile_roots(home)
    transactions_root = packs_root / "transactions"
    dispositions: list[RecoveryDisposition] = []
    manual: list[str] = []
    issues: list[PackMutationIssue] = []
    try:
        entries = sorted(transactions_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        return RecoveryResult(
            status=RecoveryStatus.MANUAL_INTERVENTION,
            manual_transactions=("<transactions-root>",),
            issues=(
                PackMutationIssue(
                    PackTransactionIssueCode.IO_UNAVAILABLE,
                    "could not enumerate capability-pack transactions",
                ),
            ),
        )
    for transaction_root in entries:
        transaction_id = transaction_root.name
        try:
            validate_pack_mutation_locks(home, locks)
            _parse_uuid(transaction_id, field="transaction directory")
            _safe_existing_directory(
                transaction_root, label=f"transaction {transaction_id}"
            )
            journal_path = _journal_path(transaction_root)
            if not journal_path.exists() and not journal_path.is_symlink():
                abandoned = _safe_mkdir_parents(
                    packs_root, f"abandoned/{transaction_id}"
                )
                if abandoned.exists() or abandoned.is_symlink():
                    raise _MutationFailure(
                        PackTransactionIssueCode.RECOVERY_REQUIRED,
                        "abandoned transaction quarantine already exists",
                    )
                validate_pack_mutation_locks(home, locks)
                _replace_path(transaction_root, abandoned, root=_home)
                dispositions.append(RecoveryDisposition(transaction_id, "rolled_back"))
                continue
            journal = _load_journal(transaction_root, packs_root)
            if journal["phase"] == "manual_intervention":
                raise _MutationFailure(
                    PackTransactionIssueCode.RECOVERY_REQUIRED,
                    "transaction was previously marked for manual intervention",
                )
            previous_phase = journal["phase"]
            if previous_phase in _TERMINAL_PHASES and _terminal_journal_matches_history(
                home=home,
                packs_root=packs_root,
                transaction_root=transaction_root,
                journal=journal,
            ):
                continue
            disposition = _recover_one_locked(
                home=home,
                locks=locks,
                skills_root=skills_root,
                packs_root=packs_root,
                transaction_root=transaction_root,
                journal=journal,
            )
            if (
                previous_phase not in _TERMINAL_PHASES
                or previous_phase != disposition.outcome
            ):
                dispositions.append(disposition)
        except SkillMutationLockError:
            raise
        except (OSError, RuntimeError, UnsafePathError, _MutationFailure) as exc:
            manual.append(transaction_id)
            code = (
                exc.code
                if isinstance(exc, _MutationFailure)
                else PackTransactionIssueCode.JOURNAL_INVALID
            )
            issues.append(PackMutationIssue(code, str(exc), transaction_id))
            # Mark only an already-validated journal.  An untrusted/tampered
            # journal is never rewritten and, crucially, never drives a move.
            if "journal" in locals() and isinstance(journal, dict):
                with contextlib.suppress(Exception):
                    _update_journal(
                        transaction_root, journal, phase="manual_intervention"
                    )
            continue
        finally:
            if "journal" in locals():
                del journal
    if manual:
        return RecoveryResult(
            RecoveryStatus.MANUAL_INTERVENTION,
            tuple(dispositions),
            tuple(manual),
            tuple(issues),
        )
    if dispositions:
        return RecoveryResult(
            RecoveryStatus.RECOVERED,
            tuple(dispositions),
            (),
            tuple(issues),
        )
    return RecoveryResult(RecoveryStatus.CLEAN)


def _recover_transactions(
    *, home: Path, timeout_seconds: float = 15.0
) -> RecoveryResult:
    """Recover every nonterminal transaction for one explicit profile."""

    try:
        with pack_mutation_locks(home, timeout_seconds=timeout_seconds) as locks:
            return _recover_transactions_locked(home=Path(home), locks=locks)
    except SkillMutationLockTimeout as exc:
        return RecoveryResult(
            RecoveryStatus.MANUAL_INTERVENTION,
            manual_transactions=("<lock>",),
            issues=(
                PackMutationIssue(PackTransactionIssueCode.LOCK_TIMEOUT, str(exc)),
            ),
        )
    except (SkillMutationLockError, OSError, RuntimeError) as exc:
        return RecoveryResult(
            RecoveryStatus.MANUAL_INTERVENTION,
            manual_transactions=("<profile>",),
            issues=(
                PackMutationIssue(PackTransactionIssueCode.IO_UNAVAILABLE, str(exc)),
            ),
        )


def _result_from_plan(plan: PackPlanResult) -> PackMutationResult:
    status = (
        PackMutationStatus.CONFLICT
        if plan.mutation_status == MutationPlanStatus.CONFLICT
        else PackMutationStatus.BLOCKED
    )
    return PackMutationResult(
        status=status,
        pack_id=plan.pack_id,
        version=plan.to_version,
        revision=plan.expected_revision,
        transaction_id=None,
        plan=plan,
    )


def _success_status(plan: PackPlanResult) -> PackMutationStatus:
    if plan.from_version is None:
        return PackMutationStatus.APPLIED
    if plan.from_version != plan.to_version:
        return PackMutationStatus.UPDATED
    return PackMutationStatus.REPAIRED


def _apply_validated_pack(
    pack_id: str,
    *,
    home: Path,
    catalog: Mapping[str, Any],
    capability_packs_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    target_version: str,
    host_os: Literal["linux", "macos", "windows"],
    session_platform: str | None,
    available_toolsets: frozenset[str],
    overrides: Mapping[str, str],
    external_skill_roots: Sequence[Path],
    expected_revision: int | None,
    expected_mutation_plan_digest: str | None,
    timeout_seconds: float = 15.0,
    now: Callable[[], datetime] | None = None,
) -> PackMutationResult:
    """Execute an already strictly loaded catalog (private testable core)."""

    clock = now or (lambda: datetime.now(timezone.utc))
    try:
        with pack_mutation_locks(home, timeout_seconds=timeout_seconds) as locks:
            recovery = _recover_transactions_locked(home=Path(home), locks=locks)
            if recovery.status == RecoveryStatus.MANUAL_INTERVENTION:
                return PackMutationResult(
                    PackMutationStatus.RECOVERY_REQUIRED,
                    pack_id,
                    target_version,
                    None,
                    None,
                    None,
                    recovery.issues,
                )

            def current_plan() -> PackPlanResult:
                return plan_pack(
                    pack_id,
                    home=home,
                    catalog=catalog,
                    operation="apply",
                    target_version=target_version,
                    host_os=host_os,
                    session_platform=session_platform,
                    available_toolsets=available_toolsets,
                    overrides=overrides,
                    external_skill_roots=external_skill_roots,
                )

            plan = current_plan()
            if (
                expected_revision is not None
                and expected_revision != plan.expected_revision
            ):
                return PackMutationResult(
                    PackMutationStatus.REVISION_CONFLICT,
                    pack_id,
                    target_version,
                    plan.expected_revision,
                    None,
                    plan,
                    (
                        PackMutationIssue(
                            PackTransactionIssueCode.REVISION_CONFLICT,
                            "expected revision does not match current profile state",
                        ),
                    ),
                )
            if (
                expected_mutation_plan_digest is not None
                and expected_mutation_plan_digest != plan.mutation_plan_digest
            ):
                return PackMutationResult(
                    PackMutationStatus.PLAN_CONFLICT,
                    pack_id,
                    target_version,
                    plan.expected_revision,
                    None,
                    plan,
                    (
                        PackMutationIssue(
                            PackTransactionIssueCode.PLAN_CONFLICT,
                            "mutation plan changed after it was displayed",
                        ),
                    ),
                )
            if plan.from_version is not None and plan.from_version != plan.to_version:
                return PackMutationResult(
                    PackMutationStatus.BLOCKED,
                    pack_id,
                    target_version,
                    plan.expected_revision,
                    None,
                    plan,
                    (
                        PackMutationIssue(
                            PackTransactionIssueCode.OPERATION_REQUIRED,
                            "apply cannot change an installed release; use an explicit update or downgrade operation",
                        ),
                    ),
                )
            if plan.mutation_status in {
                MutationPlanStatus.BLOCKED,
                MutationPlanStatus.CONFLICT,
            }:
                return _result_from_plan(plan)
            if plan.mutation_status == MutationPlanStatus.UNCHANGED:
                return PackMutationResult(
                    PackMutationStatus.UNCHANGED,
                    pack_id,
                    target_version,
                    plan.expected_revision,
                    None,
                    plan,
                )

            transaction_root: Path | None = None
            try:
                transaction_id = str(uuid.uuid4())
                transaction_root = (
                    Path(home).resolve(strict=False)
                    / "capability-packs"
                    / "transactions"
                    / transaction_id
                )
                transaction_root, journal, new_state_raw = _prepare_transaction(
                    home=home,
                    locks=locks,
                    transaction_id=transaction_id,
                    catalog=catalog,
                    plan=plan,
                    capability_packs_root=capability_packs_root,
                    bundled_skills_root=bundled_skills_root,
                    optional_skills_root=optional_skills_root,
                    now=clock(),
                )
                _execute_transaction(
                    home=home,
                    locks=locks,
                    transaction_root=transaction_root,
                    journal=journal,
                    new_state_raw=new_state_raw,
                )
                committed_plan = current_plan()
                return PackMutationResult(
                    _success_status(plan),
                    pack_id,
                    target_version,
                    plan.expected_revision + 1,
                    journal["transaction_id"],
                    committed_plan,
                )
            except Exception as raw_exc:
                exc = (
                    raw_exc
                    if isinstance(raw_exc, _MutationFailure)
                    else _MutationFailure(
                        PackTransactionIssueCode.IO_UNAVAILABLE,
                        "unexpected capability-pack transaction failure",
                    )
                )
                if (
                    transaction_root is None
                    or not _journal_path(transaction_root).exists()
                ):
                    # Never clean an unjournaled transaction by pathname. A
                    # concurrent replacement could turn recursive cleanup into
                    # deletion of an attacker-selected tree. UUID transaction
                    # leftovers are intentionally retained; the next locked
                    # recovery/apply pins and quarantines them under
                    # capability-packs/abandoned before retrying.
                    return PackMutationResult(
                        PackMutationStatus.BLOCKED,
                        pack_id,
                        target_version,
                        plan.expected_revision,
                        None,
                        plan,
                        (PackMutationIssue(exc.code, str(exc)),),
                    )
                recovery = _recover_transactions_locked(home=Path(home), locks=locks)
                matching = next(
                    (
                        item
                        for item in recovery.dispositions
                        if item.transaction_id == transaction_root.name
                    ),
                    None,
                )
                if (
                    recovery.status == RecoveryStatus.MANUAL_INTERVENTION
                    or matching is None
                ):
                    return PackMutationResult(
                        PackMutationStatus.RECOVERY_REQUIRED,
                        pack_id,
                        target_version,
                        None,
                        transaction_root.name,
                        plan,
                        (PackMutationIssue(exc.code, str(exc), transaction_root.name),)
                        + recovery.issues,
                    )
                if matching.outcome == "committed":
                    committed_plan = current_plan()
                    return PackMutationResult(
                        _success_status(plan),
                        pack_id,
                        target_version,
                        plan.expected_revision + 1,
                        transaction_root.name,
                        committed_plan,
                        (PackMutationIssue(exc.code, str(exc), transaction_root.name),),
                    )
                return PackMutationResult(
                    PackMutationStatus.ROLLED_BACK,
                    pack_id,
                    target_version,
                    plan.expected_revision,
                    transaction_root.name,
                    plan,
                    (PackMutationIssue(exc.code, str(exc), transaction_root.name),),
                )
    except SkillMutationLockTimeout as exc:
        return PackMutationResult(
            PackMutationStatus.CONFLICT,
            pack_id,
            target_version,
            None,
            None,
            None,
            (PackMutationIssue(PackTransactionIssueCode.LOCK_TIMEOUT, str(exc)),),
        )
    except (SkillMutationLockError, OSError, RuntimeError) as exc:
        return PackMutationResult(
            PackMutationStatus.RECOVERY_REQUIRED,
            pack_id,
            target_version,
            None,
            None,
            None,
            (PackMutationIssue(PackTransactionIssueCode.IO_UNAVAILABLE, str(exc)),),
        )


def _apply_pack_strict(
    pack_id: str,
    *,
    home: Path,
    catalog_path: Path,
    capability_packs_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    repository_root: Path,
    target_version: str,
    host_os: Literal["linux", "macos", "windows"],
    session_platform: str | None = None,
    available_toolsets: frozenset[str] = frozenset(),
    overrides: Mapping[str, str] | None = None,
    external_skill_roots: Sequence[Path] = (),
    expected_revision: int | None = None,
    expected_mutation_plan_digest: str | None = None,
    timeout_seconds: float = 15.0,
) -> PackMutationResult:
    """Strictly verify the packaged catalog, then exercise the apply engine.

    This foundation remains private and is intentionally not wired to CLI,
    REST, RPC, or UI while Hub/sync/editor/config writers can bypass the shared
    mutation locks.  Once every writer participates in the lock boundary, the
    public adapter can call this method without adding a provenance bypass.

    The method performs no network access and has no parameter that bypasses
    catalog provenance, license, source-tree, or platform-evidence validation.
    """

    catalog = load_compiled_catalog(
        catalog_path,
        capability_packs_root=capability_packs_root,
        bundled_skills_root=bundled_skills_root,
        optional_skills_root=optional_skills_root,
        repository_root=repository_root,
    )
    return _apply_validated_pack(
        pack_id,
        home=home,
        catalog=catalog,
        capability_packs_root=capability_packs_root,
        bundled_skills_root=bundled_skills_root,
        optional_skills_root=optional_skills_root,
        target_version=target_version,
        host_os=host_os,
        session_platform=session_platform,
        available_toolsets=available_toolsets,
        overrides=overrides or {},
        external_skill_roots=external_skill_roots,
        expected_revision=expected_revision,
        expected_mutation_plan_digest=expected_mutation_plan_digest,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "PackMutationIssue",
    "PackMutationResult",
    "PackMutationStatus",
    "PackTransactionIssueCode",
    "RecoveryDisposition",
    "RecoveryResult",
    "RecoveryStatus",
]
