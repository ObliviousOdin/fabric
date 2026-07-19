"""Pinned privacy classification for provider-account and backup state.

Pathnames are only hints: another process can replace a path after validation.
This module opens one regular-file descriptor, classifies that exact object,
and exposes a small capability that consumers must keep through their read or
delivery snapshot.  Full backups are recognized independently by:

* structural placement under profile backup/snapshot trees;
* a protected inode registry written by the backup publisher;
* a bounded ZIP parser that recognizes the generated marker and sensitive or
  full-backup member structure, while treating malformed/ambiguous ZIPs as
  private.

The archive parser never inflates payloads and caps central-directory bytes and
entry counts.  Huge, sparse, ZIP64, multi-EOCD, or trailing-data candidates
therefore fail closed without unbounded reads.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import struct
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator


_STATE_FILENAME = "provider-accounts.json"
_LOCK_FILENAME = "provider-accounts.lock"
_REPAIR_DIRNAME = ".provider-account-repair"
_TEMP_PREFIX = ".provider-accounts.json.tmp."
_PRIVATE_STATE_DIRS = frozenset({"backups", "state-snapshots"})
_PRIVATE_BACKUP_STAGING_PREFIX = ".fabric-private-backup-"

PRIVATE_BACKUP_ZIP_COMMENT = b"fabric-private-full-backup-v1"
PRIVATE_BACKUP_ZIP_ENTRY = ".fabric-private-full-backup-v1"

_ZIP_LOCAL_SIGNATURE = b"PK\x03\x04"
_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_ZIP_LEADING_SIGNATURES = frozenset({
    _ZIP_LOCAL_SIGNATURE,
    _ZIP_EOCD_SIGNATURE,
    b"PK\x07\x08",  # spanned archive marker
})
_ZIP_EOCD_FIXED_SIZE = 22
_ZIP_MAX_COMMENT_SIZE = 65_535
_ZIP_MAX_EOCD_SIZE = _ZIP_EOCD_FIXED_SIZE + _ZIP_MAX_COMMENT_SIZE
_ZIP_MAX_CENTRAL_BYTES = 8 * 1024 * 1024
_ZIP_MAX_ENTRIES = 4_096
_ZIP_PREFIX_PROBE_BYTES = 64 * 1024
_ZIP16_SENTINEL = 0xFFFF
_ZIP32_SENTINEL = 0xFFFFFFFF

_REGISTRY_DIR = Path("backups") / ".private-archive-registry-v1"
_REGISTRY_RECORD_VERSION = 1
_REGISTRY_RECORD_MAX_BYTES = 4_096


class PinnedPathError(OSError):
    """A path could not be pinned or changed while its capability was used."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ArchiveDisposition(str, Enum):
    NOT_ARCHIVE = "not_archive"
    SAFE = "safe"
    PRIVATE = "private"
    AMBIGUOUS = "ambiguous"


def _stat_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _stat_content_fingerprint(metadata: os.stat_result) -> tuple[int, int, int]:
    return (
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", int(metadata.st_mtime * 1_000_000_000)),
        getattr(metadata, "st_ctime_ns", int(metadata.st_ctime * 1_000_000_000)),
    )


def _is_redirect_stat(path: Path, metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(metadata, "st_file_attributes", 0) & reparse_flag:
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            return bool(isjunction(path))
        except OSError:
            return True
    return False


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


@dataclass
class PinnedFileCapability:
    """An exact regular-file descriptor plus pathname stability proof."""

    requested_path: Path
    resolved_path: Path
    fd: int = field(repr=False)
    identity: tuple[int, int]
    initial_fingerprint: tuple[int, int, int]
    _closed: bool = field(default=False, init=False, repr=False)
    _io_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str] | Path,
        *,
        stable_for_external_read: bool = False,
    ) -> PinnedFileCapability:
        requested = _absolute_lexical(Path(path))
        try:
            resolved = requested.resolve(strict=True)
        except FileNotFoundError as exc:
            raise PinnedPathError("not_found") from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise PinnedPathError("path_unavailable") from exc

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0)
        try:
            if os.name == "nt" and stable_for_external_read:  # pragma: no cover
                from fabric_cli.provider_accounts import _windows_open_private_file

                fd = _windows_open_private_file(
                    resolved,
                    create_new=False,
                    share_write=False,
                    open_existing=True,
                )
            else:
                fd = os.open(resolved, flags)
        except OSError as exc:
            raise PinnedPathError("path_unavailable") from exc
        try:
            opened = os.fstat(fd)
            current = os.stat(resolved, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or _is_redirect_stat(resolved, current)
                or _stat_identity(opened) != _stat_identity(current)
            ):
                raise PinnedPathError("path_changed")
            capability = cls(
                requested_path=requested,
                resolved_path=resolved,
                fd=fd,
                identity=_stat_identity(opened),
                initial_fingerprint=_stat_content_fingerprint(opened),
            )
            fd = -1
            capability.assert_unchanged()
            return capability
        finally:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)

    @property
    def size(self) -> int:
        return self.initial_fingerprint[0]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(OSError):
            os.close(self.fd)

    def __enter__(self) -> PinnedFileCapability:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def assert_unchanged(self) -> None:
        """Reject path replacement or in-place mutation since pinning."""
        if self._closed:
            raise PinnedPathError("capability_closed")
        try:
            opened = os.fstat(self.fd)
            resolved_now = self.requested_path.resolve(strict=True)
            current = os.stat(resolved_now, follow_symlinks=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PinnedPathError("path_changed") from exc
        if (
            resolved_now != self.resolved_path
            or _is_redirect_stat(resolved_now, current)
            or _stat_identity(opened) != self.identity
            or _stat_identity(current) != self.identity
            or _stat_content_fingerprint(opened) != self.initial_fingerprint
        ):
            raise PinnedPathError("path_changed")

    def read_at(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError("offset and size must be nonnegative")
        with self._io_lock:
            self.assert_unchanged()
            if hasattr(os, "pread"):
                payload = os.pread(self.fd, size, offset)
            else:  # pragma: no cover - Windows
                prior = os.lseek(self.fd, 0, os.SEEK_CUR)
                try:
                    os.lseek(self.fd, offset, os.SEEK_SET)
                    payload = os.read(self.fd, size)
                finally:
                    os.lseek(self.fd, prior, os.SEEK_SET)
            self.assert_unchanged()
            return payload

    @contextlib.contextmanager
    def open_reader(self) -> Iterator[BinaryIO]:
        """Yield a duplicate descriptor and verify before and after its read."""
        with self._io_lock:
            self.assert_unchanged()
            duplicate = os.dup(self.fd)
            try:
                os.lseek(duplicate, 0, os.SEEK_SET)
                with os.fdopen(duplicate, "rb", closefd=True) as reader:
                    duplicate = -1
                    yield reader
            finally:
                if duplicate >= 0:
                    with contextlib.suppress(OSError):
                        os.close(duplicate)
            self.assert_unchanged()

    def read_bytes(self, *, max_bytes: int | None = None) -> bytes:
        if max_bytes is not None and self.size > max_bytes:
            raise PinnedPathError("file_too_large")
        with self.open_reader() as reader:
            return reader.read()

    def copy_to_private_directory(self, directory: Path) -> Path:
        """Materialize this exact descriptor in a private, basename-stable dir."""
        root = directory.expanduser().resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        snapshot_name = f"validated-{uuid.uuid4().hex}"
        snapshot_dir = root / snapshot_name
        name = self.requested_path.name or "attachment"
        target = snapshot_dir / name
        fd: int | None = None
        root_fd: int | None = None
        snapshot_fd: int | None = None
        windows_root_handles: list[int] = []
        windows_snapshot_handles: list[int] = []
        opened_target: os.stat_result | None = None
        snapshot_created = False
        completed = False
        try:
            if os.name == "nt":  # pragma: no cover - Windows CI
                from fabric_cli.provider_accounts import (
                    _windows_open_private_file,
                    _windows_pin_directory_tree,
                    _windows_private_directory,
                )

                try:
                    if not _windows_private_directory(root, apply=True):
                        raise PinnedPathError("private_directory_unavailable")
                    root_handles, _root_identity = _windows_pin_directory_tree(root)
                    windows_root_handles.extend(root_handles)
                    snapshot_dir.mkdir(mode=0o700)
                    snapshot_created = True
                    if not _windows_private_directory(snapshot_dir, apply=True):
                        raise PinnedPathError("private_directory_unavailable")
                    snapshot_handles, _snapshot_identity = _windows_pin_directory_tree(
                        snapshot_dir
                    )
                    windows_snapshot_handles.extend(snapshot_handles)
                    fd = _windows_open_private_file(target, create_new=True)
                    opened_target = os.fstat(fd)
                except PinnedPathError:
                    raise
                except Exception as exc:
                    raise PinnedPathError("private_file_unavailable") from exc
            else:
                root.chmod(0o700)
                directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                directory_flags |= getattr(os, "O_CLOEXEC", 0)
                directory_flags |= getattr(os, "O_NOFOLLOW", 0)
                root_fd = os.open(root, directory_flags)
                os.fchmod(root_fd, 0o700)
                opened_root = os.fstat(root_fd)
                current_root = os.stat(root, follow_symlinks=False)
                if (
                    not stat.S_ISDIR(opened_root.st_mode)
                    or _is_redirect_stat(root, current_root)
                    or _stat_identity(opened_root) != _stat_identity(current_root)
                    or stat.S_IMODE(opened_root.st_mode) != 0o700
                ):
                    raise PinnedPathError("private_directory_unavailable")
                os.mkdir(snapshot_name, 0o700, dir_fd=root_fd)
                snapshot_created = True
                snapshot_fd = os.open(
                    snapshot_name,
                    directory_flags,
                    dir_fd=root_fd,
                )
                os.fchmod(snapshot_fd, 0o700)
                opened_snapshot = os.fstat(snapshot_fd)
                current_snapshot = os.stat(
                    snapshot_name,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISDIR(opened_snapshot.st_mode)
                    or _stat_identity(opened_snapshot)
                    != _stat_identity(current_snapshot)
                    or stat.S_IMODE(opened_snapshot.st_mode) != 0o700
                ):
                    raise PinnedPathError("private_directory_unavailable")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(name, flags, 0o600, dir_fd=snapshot_fd)
                os.fchmod(fd, 0o600)
                opened_target = os.fstat(fd)
                if (
                    not stat.S_ISREG(opened_target.st_mode)
                    or opened_target.st_nlink != 1
                    or stat.S_IMODE(opened_target.st_mode) != 0o600
                ):
                    raise PinnedPathError("private_file_unavailable")

            with self.open_reader() as source, os.fdopen(fd, "wb") as destination:
                fd = None
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            self.assert_unchanged()
            if os.name == "nt":  # pragma: no cover - Windows CI
                current_target = target.stat(follow_symlinks=False)
                if (
                    opened_target is None
                    or _is_redirect_stat(target, current_target)
                    or _stat_identity(opened_target) != _stat_identity(current_target)
                ):
                    raise PinnedPathError("snapshot_changed")
            else:
                if root_fd is None or snapshot_fd is None:
                    raise PinnedPathError("private_directory_unavailable")
                current_root = os.stat(root, follow_symlinks=False)
                current_snapshot = os.stat(
                    snapshot_name,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
                current_target = os.stat(
                    name,
                    dir_fd=snapshot_fd,
                    follow_symlinks=False,
                )
                if (
                    _stat_identity(os.fstat(root_fd)) != _stat_identity(current_root)
                    or _stat_identity(os.fstat(snapshot_fd))
                    != _stat_identity(current_snapshot)
                    or opened_target is None
                    or _stat_identity(opened_target) != _stat_identity(current_target)
                    or stat.S_IMODE(current_target.st_mode) != 0o600
                ):
                    raise PinnedPathError("snapshot_changed")
                os.fsync(snapshot_fd)
                os.fsync(root_fd)
            completed = True
            return target
        except BaseException:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
            raise
        finally:
            if not completed and snapshot_created:
                if snapshot_fd is not None:
                    with contextlib.suppress(OSError):
                        os.unlink(name, dir_fd=snapshot_fd)
                else:
                    with contextlib.suppress(OSError):
                        target.unlink(missing_ok=True)
            if snapshot_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(snapshot_fd)
            if os.name == "nt":  # pragma: no cover - Windows CI
                from fabric_cli.provider_accounts import _windows_close_handle

                for handle in reversed(windows_snapshot_handles):
                    with contextlib.suppress(Exception):
                        _windows_close_handle(handle)
            if not completed and snapshot_created:
                if root_fd is not None:
                    with contextlib.suppress(OSError):
                        os.rmdir(snapshot_name, dir_fd=root_fd)
                else:
                    with contextlib.suppress(OSError):
                        snapshot_dir.rmdir()
            if root_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(root_fd)
            if os.name == "nt":  # pragma: no cover - Windows CI
                from fabric_cli.provider_accounts import _windows_close_handle

                for handle in reversed(windows_root_handles):
                    with contextlib.suppress(Exception):
                        _windows_close_handle(handle)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _path_forms(path: Path) -> tuple[Path, ...]:
    forms: list[Path] = []
    try:
        forms.append(_absolute_lexical(path))
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    try:
        resolved = path.expanduser().resolve(strict=False)
        if resolved not in forms:
            forms.append(resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return tuple(forms)


def _profile_relative(relative: Path) -> Path | None:
    parts = relative.parts
    if not parts:
        return None
    if parts[0] != "profiles":
        return relative
    if len(parts) < 3:
        return None
    return Path(*parts[2:])


def _is_private_profile_relative(relative: Path) -> bool:
    profile_relative = _profile_relative(relative)
    if profile_relative is None or not profile_relative.parts:
        return False
    parts = profile_relative.parts
    if parts[0] in _PRIVATE_STATE_DIRS or parts[0] == _REPAIR_DIRNAME:
        return True
    if len(parts) != 1:
        return False
    name = parts[0]
    return name in {_STATE_FILENAME, _LOCK_FILENAME} or name.startswith(_TEMP_PREFIX)


def _is_private_structural_path(
    path: Path,
    *,
    active_home: Path,
    fabric_root: Path,
) -> bool:
    path_forms = _path_forms(path)
    if any(
        candidate.name.lower().startswith(_PRIVATE_BACKUP_STAGING_PREFIX)
        and candidate.suffix.lower() == ".zip"
        for candidate in path_forms
    ):
        return True
    roots: list[Path] = []
    for root in (active_home, fabric_root):
        for form in _path_forms(root):
            if form not in roots:
                roots.append(form)
    for candidate in path_forms:
        for root in roots:
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                continue
            if _is_private_profile_relative(relative):
                return True
    return False


def _is_stable_ordinary_directory(path: Path) -> bool:
    """Prove that *path* is one ordinary directory, not a redirect.

    Boolean compatibility callers use the privacy classifier for directory
    search roots as well as files.  ``PinnedFileCapability`` intentionally
    rejects non-files; treating that rejection as private made every ordinary
    project directory unreadable.  This narrow directory proof preserves
    fail-closed behavior for symlinks, junctions, replacements, and errors.
    """
    requested = _absolute_lexical(path)
    descriptor: int | None = None
    try:
        before = os.stat(requested, follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode) or _is_redirect_stat(requested, before):
            return False
        if os.name == "nt":  # pragma: no cover - native Windows CI
            resolved = requested.resolve(strict=True)
            after = os.stat(requested, follow_symlinks=False)
            resolved_metadata = os.stat(resolved, follow_symlinks=False)
            return (
                stat.S_ISDIR(after.st_mode)
                and stat.S_ISDIR(resolved_metadata.st_mode)
                and not _is_redirect_stat(requested, after)
                and not _is_redirect_stat(resolved, resolved_metadata)
                and _stat_identity(before) == _stat_identity(after)
                and _stat_identity(before) == _stat_identity(resolved_metadata)
            )
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(requested, flags)
        opened = os.fstat(descriptor)
        after = os.stat(requested, follow_symlinks=False)
        return (
            stat.S_ISDIR(opened.st_mode)
            and stat.S_ISDIR(after.st_mode)
            and not _is_redirect_stat(requested, after)
            and _stat_identity(before)
            == _stat_identity(opened)
            == _stat_identity(after)
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _registry_record_path(root: Path, identity: tuple[int, int]) -> Path:
    device, inode = identity
    return root / _REGISTRY_DIR / f"{device:x}-{inode:x}.json"


def _registry_matches(
    capability: PinnedFileCapability,
    roots: tuple[Path, ...],
) -> bool:
    for root in roots:
        record: Path | None = None
        try:
            record = _registry_record_path(
                root.resolve(strict=False), capability.identity
            )
            if (
                not record.is_file()
                or record.stat().st_size > _REGISTRY_RECORD_MAX_BYTES
            ):
                continue
            payload = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, RuntimeError, UnicodeError, ValueError, json.JSONDecodeError):
            # An exact identity record exists but is unreadable/malformed: fail
            # closed rather than allowing registry corruption to declassify it.
            if record is not None and record.exists():
                return True
            continue
        if (
            payload.get("version") == _REGISTRY_RECORD_VERSION
            and payload.get("device") == capability.identity[0]
            and payload.get("inode") == capability.identity[1]
        ):
            return True
    return False


def _normalized_member(name_bytes: bytes, flags: int) -> tuple[str, ...] | None:
    encoding = "utf-8" if flags & 0x800 else "cp437"
    try:
        raw = name_bytes.decode(encoding)
    except UnicodeDecodeError:
        return None
    # ``zipfile.ZipInfo`` (and therefore every stdlib extraction/listing path)
    # treats the first NUL as the end of the member name.  Classifying the raw
    # suffix would let ``auth.json\0harmless.txt`` appear harmless here while
    # consumers see ``auth.json``.
    raw = raw.split("\0", 1)[0].replace("\\", "/")
    if not raw:
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    parts = tuple(part for part in path.parts if part)
    if parts and parts[0] == ".fabric":
        parts = parts[1:]
    return parts


def _member_is_private(parts: tuple[str, ...]) -> bool:
    if not parts:
        return False
    lowered = tuple(part.lower() for part in parts)
    if lowered[-1] in {
        ".env",
        "auth.json",
        ".anthropic_oauth.json",
        "google_token.json",
        "google_oauth_pending.json",
        "provider-accounts.json",
        "webhook_subscriptions.json",
        "bws_cache.json",
    }:
        return True
    private_parts = {
        _REPAIR_DIRNAME,
        "_external",
        "mcp-tokens",
        "credentials",
        "pairing",
        "state-snapshots",
    }
    return any(part in private_parts for part in lowered)


def _member_indicator(parts: tuple[str, ...]) -> str | None:
    if not parts:
        return None
    if parts == (PRIVATE_BACKUP_ZIP_ENTRY,):
        return "marker"
    first = parts[0].lower()
    if first in {"sessions", "memories", "profiles", "skills", "plugins"}:
        return first
    joined = "/".join(part.lower() for part in parts)
    if joined in {
        "config.yaml",
        "state.db",
        "memory_store.db",
        "cron/jobs.json",
    }:
        return joined
    return None


@dataclass(frozen=True)
class _CentralEntry:
    name: bytes
    flags: int
    compression_method: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    local_offset: int


def _zip_archive_disposition(capability: PinnedFileCapability) -> ArchiveDisposition:
    size = capability.size
    if size < _ZIP_EOCD_FIXED_SIZE:
        leading = capability.read_at(0, min(size, 4))
        if leading.startswith(b"PK"):
            return ArchiveDisposition.AMBIGUOUS
        return ArchiveDisposition.NOT_ARCHIVE
    leading = capability.read_at(0, 4)
    tail_size = min(size, _ZIP_MAX_EOCD_SIZE)
    tail_offset = size - tail_size
    tail = capability.read_at(tail_offset, tail_size)
    records: list[tuple[int, int, int, int, int, int, int, int]] = []
    search_at = 0
    while True:
        relative = tail.find(_ZIP_EOCD_SIGNATURE, search_at)
        if relative < 0:
            break
        search_at = relative + 1
        if relative + _ZIP_EOCD_FIXED_SIZE > len(tail):
            continue
        absolute = tail_offset + relative
        (
            disk_number,
            central_disk,
            disk_entries,
            total_entries,
            central_size,
            central_offset,
            comment_size,
        ) = struct.unpack_from("<4H2LH", tail, relative + 4)
        record_end = absolute + _ZIP_EOCD_FIXED_SIZE + comment_size
        if record_end > size:
            continue
        comment_start = relative + _ZIP_EOCD_FIXED_SIZE
        comment_end = comment_start + comment_size
        if (
            comment_end <= len(tail)
            and tail[comment_start:comment_end] == PRIVATE_BACKUP_ZIP_COMMENT
        ):
            return ArchiveDisposition.PRIVATE
        records.append((
            absolute,
            record_end,
            disk_number,
            central_disk,
            disk_entries,
            total_entries,
            central_size,
            central_offset,
        ))

    if not records:
        if (
            leading in _ZIP_LEADING_SIGNATURES
            or capability.requested_path.suffix.lower() == ".zip"
        ):
            return ArchiveDisposition.AMBIGUOUS
        prefix = capability.read_at(0, min(size, _ZIP_PREFIX_PROBE_BYTES))
        if any(
            signature in prefix
            for signature in (_ZIP_LOCAL_SIGNATURE, _ZIP_CENTRAL_SIGNATURE)
        ):
            return ArchiveDisposition.AMBIGUOUS
        return ArchiveDisposition.NOT_ARCHIVE
    if len(records) != 1:
        return ArchiveDisposition.AMBIGUOUS
    (
        eocd_offset,
        record_end,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
    ) = records[0]
    archive_base = eocd_offset - central_size - central_offset
    if (
        record_end != size
        or disk_number != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries == _ZIP16_SENTINEL
        or central_size == _ZIP32_SENTINEL
        or central_offset == _ZIP32_SENTINEL
        or archive_base < 0
        or total_entries > _ZIP_MAX_ENTRIES
        or central_size > _ZIP_MAX_CENTRAL_BYTES
    ):
        return ArchiveDisposition.AMBIGUOUS

    actual_central_offset = archive_base + central_offset
    central = capability.read_at(actual_central_offset, central_size)
    if len(central) != central_size:
        return ArchiveDisposition.AMBIGUOUS
    entries: list[_CentralEntry] = []
    normalized_entries: list[tuple[tuple[str, ...], bool]] = []
    position = 0
    for _ in range(total_entries):
        if (
            position + 46 > len(central)
            or central[position : position + 4] != _ZIP_CENTRAL_SIGNATURE
        ):
            return ArchiveDisposition.AMBIGUOUS
        flags = int.from_bytes(central[position + 8 : position + 10], "little")
        compression_method = int.from_bytes(
            central[position + 10 : position + 12], "little"
        )
        crc32 = int.from_bytes(central[position + 16 : position + 20], "little")
        compressed_size = int.from_bytes(
            central[position + 20 : position + 24], "little"
        )
        uncompressed_size = int.from_bytes(
            central[position + 24 : position + 28], "little"
        )
        name_size = int.from_bytes(central[position + 28 : position + 30], "little")
        extra_size = int.from_bytes(central[position + 30 : position + 32], "little")
        comment_size = int.from_bytes(central[position + 32 : position + 34], "little")
        local_offset = int.from_bytes(central[position + 42 : position + 46], "little")
        if (
            compressed_size == _ZIP32_SENTINEL
            or uncompressed_size == _ZIP32_SENTINEL
            or local_offset == _ZIP32_SENTINEL
        ):
            return ArchiveDisposition.AMBIGUOUS
        end = position + 46 + name_size + extra_size + comment_size
        if end > len(central):
            return ArchiveDisposition.AMBIGUOUS
        name = central[position + 46 : position + 46 + name_size]
        parts = _normalized_member(name, flags)
        if parts is None:
            return ArchiveDisposition.AMBIGUOUS
        if _member_is_private(parts):
            return ArchiveDisposition.PRIVATE
        indicator = _member_indicator(parts)
        if indicator == "marker":
            return ArchiveDisposition.PRIVATE
        normalized_entries.append((parts, name.endswith((b"/", b"\\"))))
        entries.append(
            _CentralEntry(
                name,
                flags,
                compression_method,
                crc32,
                compressed_size,
                uncompressed_size,
                local_offset,
            )
        )
        position = end
    if position != len(central):
        return ArchiveDisposition.AMBIGUOUS

    # A forged alternate central directory can omit original private members.
    # Generated archives start with a local header, so prove the selected
    # central directory describes one contiguous local-record region from byte
    # zero through the central directory.  Unreferenced prefix/trailing records,
    # data descriptors, overlaps, and gaps are ambiguous and therefore private.
    archive_leading = capability.read_at(archive_base, 4)
    if archive_leading == _ZIP_LOCAL_SIGNATURE:
        spans: list[tuple[int, int]] = []
        local_probe_bytes = 0
        for entry in entries:
            if entry.flags & 0x08:
                return ArchiveDisposition.AMBIGUOUS
            actual_local_offset = archive_base + entry.local_offset
            header = capability.read_at(actual_local_offset, 30)
            if len(header) != 30 or header[:4] != _ZIP_LOCAL_SIGNATURE:
                return ArchiveDisposition.AMBIGUOUS
            local_flags = int.from_bytes(header[6:8], "little")
            local_method = int.from_bytes(header[8:10], "little")
            local_crc32 = int.from_bytes(header[14:18], "little")
            local_compressed_size = int.from_bytes(header[18:22], "little")
            local_uncompressed_size = int.from_bytes(header[22:26], "little")
            name_size = int.from_bytes(header[26:28], "little")
            extra_size = int.from_bytes(header[28:30], "little")
            local_probe_bytes += 30 + name_size
            if local_probe_bytes > _ZIP_MAX_CENTRAL_BYTES:
                return ArchiveDisposition.AMBIGUOUS
            local_name = capability.read_at(actual_local_offset + 30, name_size)
            if (
                local_flags != entry.flags
                or local_method != entry.compression_method
                or local_crc32 != entry.crc32
                or local_compressed_size != entry.compressed_size
                or local_uncompressed_size != entry.uncompressed_size
                or local_name != entry.name
            ):
                return ArchiveDisposition.AMBIGUOUS
            end = (
                actual_local_offset
                + 30
                + name_size
                + extra_size
                + entry.compressed_size
            )
            if end > actual_central_offset:
                return ArchiveDisposition.AMBIGUOUS
            spans.append((actual_local_offset, end))
        cursor = archive_base
        for start, end in sorted(spans):
            if start != cursor or end < start:
                return ArchiveDisposition.AMBIGUOUS
            cursor = end
        if cursor != actual_central_offset:
            return ArchiveDisposition.AMBIGUOUS
    elif total_entries:
        # A populated ZIP whose selected directory does not describe local
        # records starting at byte zero may contain an unreferenced private
        # prefix.  We cannot prove complete coverage, so fail closed.
        return ArchiveDisposition.AMBIGUOUS

    # Import accepts one common wrapper directory around a home backup.  Apply
    # the same shape to privacy classification, including arbitrary wrapper
    # names, but only when every file member shares exactly that first part.
    file_parts = [parts for parts, is_directory in normalized_entries if not is_directory]
    common_wrapper: str | None = None
    if (
        file_parts
        and all(len(parts) >= 2 for parts in file_parts)
        and len({parts[0] for parts in file_parts}) == 1
    ):
        common_wrapper = file_parts[0][0]

    indicators: set[str] = set()
    for parts, _is_directory in normalized_entries:
        views = [parts]
        if common_wrapper is not None and parts and parts[0] == common_wrapper:
            views.append(parts[1:])
        for view in views:
            if _member_is_private(view):
                return ArchiveDisposition.PRIVATE
            indicator = _member_indicator(view)
            if indicator == "marker":
                return ArchiveDisposition.PRIVATE
            if indicator:
                indicators.add(indicator)
    if len(indicators) >= 2:
        return ArchiveDisposition.PRIVATE
    if archive_base:
        # A concatenated prefix is valid stdlib ZIP syntax, but proving that an
        # arbitrarily large prefix does not itself hide another archive would
        # require unbounded scanning.  A structurally safe suffix therefore
        # remains ambiguous (and private to callers).
        return ArchiveDisposition.AMBIGUOUS
    return ArchiveDisposition.SAFE


def classify_pinned_provider_account_path(
    capability: PinnedFileCapability,
    *,
    active_home: Path,
    fabric_root: Path,
) -> bool:
    """Classify the exact pinned object; ambiguous archives fail closed."""
    capability.assert_unchanged()
    if _is_private_structural_path(
        capability.requested_path,
        active_home=active_home,
        fabric_root=fabric_root,
    ) or _is_private_structural_path(
        capability.resolved_path,
        active_home=active_home,
        fabric_root=fabric_root,
    ):
        return True
    roots = tuple(dict.fromkeys((active_home, fabric_root)))
    if _registry_matches(capability, roots):
        return True
    disposition = _zip_archive_disposition(capability)
    return disposition in {ArchiveDisposition.PRIVATE, ArchiveDisposition.AMBIGUOUS}


def classify_pinned_backup_archive(
    capability: PinnedFileCapability,
    *,
    active_home: Path,
    fabric_root: Path,
) -> bool:
    """Classify only archive bytes/registry, not their source location.

    A full backup intentionally contains private profile state.  Inclusion
    filtering must therefore reject *nested private archives* without rejecting
    ordinary secret-bearing files merely because they live in the profile.
    """
    capability.assert_unchanged()
    roots = tuple(dict.fromkeys((active_home, fabric_root)))
    if _registry_matches(capability, roots):
        return True
    disposition = _zip_archive_disposition(capability)
    return disposition in {ArchiveDisposition.PRIVATE, ArchiveDisposition.AMBIGUOUS}


def is_private_backup_archive(
    path: Path,
    *,
    active_home: Path,
    fabric_root: Path,
) -> bool:
    """Return whether one existing file is a private/ambiguous backup archive."""
    if _is_stable_ordinary_directory(path):
        return False
    try:
        with PinnedFileCapability.open(path) as capability:
            roots = tuple(dict.fromkeys((active_home, fabric_root)))
            if _registry_matches(capability, roots):
                return True
            disposition = _zip_archive_disposition(capability)
            return disposition in {
                ArchiveDisposition.PRIVATE,
                ArchiveDisposition.AMBIGUOUS,
            }
    except PinnedPathError as exc:
        return exc.code != "not_found"


def is_private_provider_account_path(
    path: Path,
    *,
    active_home: Path,
    fabric_root: Path,
) -> bool:
    """Compatibility boolean; descriptor consumers should pin directly."""
    if _is_private_structural_path(
        path,
        active_home=active_home,
        fabric_root=fabric_root,
    ):
        return True
    if _is_stable_ordinary_directory(path):
        return False
    try:
        with PinnedFileCapability.open(path) as capability:
            return classify_pinned_provider_account_path(
                capability,
                active_home=active_home,
                fabric_root=fabric_root,
            )
    except PinnedPathError as exc:
        return exc.code != "not_found"


def _write_private_record(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":  # pragma: no cover - Windows CI
        from fabric_cli.provider_accounts import (
            _windows_move_write_through,
            _windows_open_private_file,
            _windows_private_directory,
        )

        if not _windows_private_directory(path.parent, apply=True):
            raise PinnedPathError("registry_permissions")
    else:
        path.parent.chmod(0o700)
        if stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
            raise PinnedPathError("registry_permissions")

    temporary = path.with_name(f".{path.name}.tmp.{uuid.uuid4().hex}")
    fd: int | None = None
    try:
        if os.name == "nt":  # pragma: no cover - Windows CI
            fd = _windows_open_private_file(temporary, create_new=True)
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(temporary, flags, 0o600)
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "nt":  # pragma: no cover - Windows CI
            _windows_move_write_through(
                temporary,
                path,
                replace_existing=path.exists(),
            )
        else:
            os.replace(temporary, path)
            _fsync_directory(path.parent)
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def register_private_backup(path: Path, *, fabric_root: Path) -> Path:
    """Register one published archive identity in a protected root registry."""
    with PinnedFileCapability.open(path) as capability:
        record = _registry_record_path(
            fabric_root.resolve(strict=False), capability.identity
        )
        payload = json.dumps(
            {
                "version": _REGISTRY_RECORD_VERSION,
                "device": capability.identity[0],
                "inode": capability.identity[1],
                "size": capability.size,
                "fingerprint": hashlib.sha256(
                    capability.read_at(0, min(capability.size, 4096))
                ).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        _write_private_record(record, payload)
        return record


__all__ = [
    "ArchiveDisposition",
    "PRIVATE_BACKUP_ZIP_COMMENT",
    "PRIVATE_BACKUP_ZIP_ENTRY",
    "PinnedFileCapability",
    "PinnedPathError",
    "classify_pinned_backup_archive",
    "classify_pinned_provider_account_path",
    "is_private_backup_archive",
    "is_private_provider_account_path",
    "register_private_backup",
]
