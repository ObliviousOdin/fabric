#!/usr/bin/env python3
"""
Skills Hub — Source adapters and hub state management for the Fabric Skills Hub.

This is a library module (not an agent tool). It provides:
  - GitHubAuth: Shared GitHub API authentication (PAT, gh CLI, GitHub App)
  - SkillSource ABC: Interface for all skill registry adapters
  - OptionalSkillSource: Official optional skills shipped with the repo (not activated by default)
  - GitHubSource: Fetch skills from any GitHub repo via the Contents API
  - HubLockFile: Track provenance of installed hub skills
  - Hub state directory management (quarantine, audit log, taps, index cache)

Used by fabric_cli/skills_hub.py for CLI commands and the /skills slash command.
"""

import copy
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import struct
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from fabric_constants import get_fabric_home
from fabric_cli._subprocess_compat import windows_hide_flags
from agent.skill_utils import extract_skill_metadata, is_excluded_skill_path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
import yaml

from tools.skills_guard import (
    ScanResult,
    content_hash,
    effective_skill_files,
    scan_skill,
    scan_skill_attested,
    scan_tree_snapshot,
    should_allow_install,
    TRUSTED_REPOS,
)
from tools.skill_install import (
    TreeSnapshot,
    UnsafePathError,
    capture_tree_snapshot,
    capture_tree_snapshot_fd,
    is_path_redirect,
    normalize_lock_install_path,
    normalize_relative_path,
    resolve_skill_install_path,
    sha256_tree,
    validate_install_parent_path,
    validate_portable_tree_paths,
    validate_skill_name,
)
from tools.skill_mutation import (
    MutationLockLease,
    duplicate_mutation_home_fd,
    duplicate_mutation_home_handle,
    skill_mutation_lock,
    validate_mutation_lock_lease,
)
from tools.url_safety import is_safe_url
from tools.website_policy import check_website_access

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Resolved per-call (not frozen at import) so the profile override is honored;
# import-time constants leaked across profiles in single-process multi-profile
# runtimes. Legacy names (SKILLS_DIR, ...) are re-exposed via __getattr__ below
# so external `from tools.skills_hub import SKILLS_DIR` callers still work.

INDEX_CACHE_TTL = 3600  # 1 hour
MAX_SKILL_HTTP_BYTES = 16 * 1024 * 1024
MAX_SKILL_FILE_BYTES = 8 * 1024 * 1024
MAX_SKILL_TOTAL_BYTES = 32 * 1024 * 1024
MAX_SKILL_ARCHIVE_FILES = 1_000
MAX_SKILL_METADATA_BYTES = 32 * 1024 * 1024
MAX_HUB_CATALOG_BYTES = 64 * 1024 * 1024
MAX_HUB_STATE_BYTES = 8 * 1024 * 1024
MAX_HUB_JSON_DEPTH = 64
MAX_HUB_JSON_ITEMS = 200_000
MAX_HUB_STRING_BYTES = 64 * 1024
MAX_HUB_DIRECTORY_ENTRIES = 10_000
# Shared TreeSnapshot admission permits up to 10k files plus 10k directories.
# Cleanup must be able to remove every tree that capture admitted.
MAX_HUB_CLEANUP_ENTRIES = 20_000
MAX_HUB_TRANSACTIONS = 1_024
MAX_HUB_GC_BATCH = 4_096


# _override lets a test-injected real module attribute (patch.object/monkeypatch
# on SKILLS_DIR etc.) win over dynamic resolution; None means resolve live.
def _override(name: str):
    return globals().get(name)


def _fabric_home() -> Path:
    active_state = globals().get("_ACTIVE_HUB_MUTATION")
    if active_state is not None:
        binding = active_state.get()
        if binding is not None:
            return binding.lexical_home
    return get_fabric_home()


def _skills_dir() -> Path:
    active_state = globals().get("_ACTIVE_HUB_MUTATION")
    if active_state is not None:
        binding = active_state.get()
        if binding is not None:
            return binding.skills_dir
    forced = _override("SKILLS_DIR")
    if forced is not None:
        return Path(forced)
    return _fabric_home() / "skills"


def _hub_dir() -> Path:
    active_state = globals().get("_ACTIVE_HUB_MUTATION")
    if active_state is not None:
        binding = active_state.get()
        if binding is not None:
            forced = _override("HUB_DIR") if binding.allow_path_overrides else None
            return Path(forced) if forced is not None else _skills_dir() / ".hub"
    forced = _override("HUB_DIR")
    return Path(forced) if forced is not None else _skills_dir() / ".hub"


def _lock_file() -> Path:
    active_state = globals().get("_ACTIVE_HUB_MUTATION")
    if active_state is not None:
        binding = active_state.get()
        if binding is not None:
            forced = _override("LOCK_FILE") if binding.allow_path_overrides else None
            return Path(forced) if forced is not None else _hub_dir() / "lock.json"
    forced = _override("LOCK_FILE")
    return Path(forced) if forced is not None else _hub_dir() / "lock.json"


def _quarantine_dir() -> Path:
    active_state = globals().get("_ACTIVE_HUB_MUTATION")
    if active_state is not None:
        binding = active_state.get()
        if binding is not None:
            forced = (
                _override("QUARANTINE_DIR") if binding.allow_path_overrides else None
            )
            return Path(forced) if forced is not None else _hub_dir() / "quarantine"
    forced = _override("QUARANTINE_DIR")
    return Path(forced) if forced is not None else _hub_dir() / "quarantine"


def _audit_log() -> Path:
    active_state = globals().get("_ACTIVE_HUB_MUTATION")
    if active_state is not None:
        binding = active_state.get()
        if binding is not None:
            forced = _override("AUDIT_LOG") if binding.allow_path_overrides else None
            return Path(forced) if forced is not None else _hub_dir() / "audit.log"
    forced = _override("AUDIT_LOG")
    return Path(forced) if forced is not None else _hub_dir() / "audit.log"


def _taps_file() -> Path:
    active_state = globals().get("_ACTIVE_HUB_MUTATION")
    if active_state is not None:
        binding = active_state.get()
        if binding is not None:
            forced = _override("TAPS_FILE") if binding.allow_path_overrides else None
            return Path(forced) if forced is not None else _hub_dir() / "taps.json"
    forced = _override("TAPS_FILE")
    return Path(forced) if forced is not None else _hub_dir() / "taps.json"


def _index_cache_dir() -> Path:
    active_state = globals().get("_ACTIVE_HUB_MUTATION")
    if active_state is not None:
        binding = active_state.get()
        if binding is not None:
            forced = (
                _override("INDEX_CACHE_DIR") if binding.allow_path_overrides else None
            )
            return Path(forced) if forced is not None else _hub_dir() / "index-cache"
    forced = _override("INDEX_CACHE_DIR")
    return Path(forced) if forced is not None else _hub_dir() / "index-cache"


_DYNAMIC_PATH_RESOLVERS = {
    "SKILLS_DIR": _skills_dir,
    "HUB_DIR": _hub_dir,
    "LOCK_FILE": _lock_file,
    "QUARANTINE_DIR": _quarantine_dir,
    "AUDIT_LOG": _audit_log,
    "TAPS_FILE": _taps_file,
    "INDEX_CACHE_DIR": _index_cache_dir,
}


def __getattr__(name: str):
    """Resolve test-overridable path constants against the active profile."""
    resolver = _DYNAMIC_PATH_RESOLVERS.get(name)
    if resolver is not None:
        return resolver()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass(frozen=True)
class _HubMutationBinding:
    home: Path
    lexical_home: Path
    skills_dir: Path
    allow_path_overrides: bool
    lease: MutationLockLease
    home_fd: int | None


_ACTIVE_HUB_MUTATION: ContextVar[_HubMutationBinding | None] = ContextVar(
    "_ACTIVE_HUB_MUTATION",
    default=None,
)


def _validate_hub_mutation_binding() -> None:
    """Fail before a pathname effect if the pinned profile generation moved."""

    binding = _ACTIVE_HUB_MUTATION.get()
    if binding is None:
        raise RuntimeError("active Hub mutation scope is required")
    validate_mutation_lock_lease(binding.home, binding.lease, kind="skills")


def _validate_hub_mutation_if_active() -> None:
    if _ACTIVE_HUB_MUTATION.get() is not None:
        _validate_hub_mutation_binding()


def _hub_relative_parts(path: Path) -> tuple[str, ...] | None:
    """Return lexical components below the bound profile, if applicable."""

    binding = _ACTIVE_HUB_MUTATION.get()
    if binding is None:
        return None
    candidate = Path(os.path.abspath(path))
    for root in (binding.lexical_home, binding.home):
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        return relative.parts
    return None


def _open_hub_directory(path: Path, *, create: bool = False) -> int:
    """Open a profile directory component-by-component without redirects."""

    _validate_hub_mutation_binding()
    if os.name == "nt":  # pragma: no cover - exercised by native Windows CI
        return _windows_open_hub_directory_fd(path, create=create)
    binding = _ACTIVE_HUB_MUTATION.get()
    assert binding is not None
    parts = _hub_relative_parts(path)
    if parts is None:
        raise RuntimeError("Hub path is outside the active profile")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = (
        os.dup(binding.home_fd)
        if binding.home_fd is not None
        else os.open(binding.home, flags)
    )
    try:
        for component in parts:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _validate_hub_mutation_binding()
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _hub_lstat(path: Path) -> os.stat_result:
    """Inspect a Hub/profile entry relative to the pinned generation."""

    _validate_hub_mutation_binding()
    if os.name == "nt":
        if _is_path_redirect(path):
            raise HubInstallError(f"Unsafe Hub redirect: {path}")
        return path.lstat()
    parts = _hub_relative_parts(path)
    if parts is None:
        raise HubInstallError("Hub path is outside the active profile")
    if not parts:
        binding = _ACTIVE_HUB_MUTATION.get()
        assert binding is not None and binding.home_fd is not None
        return os.fstat(binding.home_fd)
    parent_fd = _open_hub_directory(path.parent, create=False)
    try:
        return os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    finally:
        os.close(parent_fd)


def _hub_exists(path: Path) -> bool:
    try:
        _hub_lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def _hub_is_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(_hub_lstat(path).st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


def _hub_list_directory(
    path: Path,
    *,
    max_entries: int = MAX_HUB_DIRECTORY_ENTRIES,
    expected_identity: tuple[int, int] | None = None,
) -> tuple[Path, ...]:
    """Enumerate one directory through its opened capability."""

    if (
        isinstance(max_entries, bool)
        or not isinstance(max_entries, int)
        or max_entries < 1
    ):
        raise HubInstallError("Hub directory entry limit is invalid")
    descriptor: int | None = None
    if os.name == "nt":
        if _is_path_redirect(path):
            raise HubInstallError(f"Unsafe Hub redirect: {path}")
        scan_target: Path | int = path
    else:
        descriptor = _open_hub_directory(path, create=False)
        scan_target = descriptor
    try:
        if descriptor is not None and expected_identity is not None:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != expected_identity:
                raise HubInstallError("Hub directory changed identity")
        elif os.name == "nt" and expected_identity is not None:
            opened = path.lstat()
            if (opened.st_dev, opened.st_ino) != expected_identity:
                raise HubInstallError("Hub directory changed identity")
        names: list[str] = []
        with os.scandir(scan_target) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > max_entries:
                    raise HubInstallError(
                        f"Hub directory contains more than {max_entries} entries"
                    )
        names.sort(key=lambda name: name.encode("utf-8", errors="strict"))
        return tuple(path / name for name in names)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _hub_list_directory_batch(
    path: Path,
    *,
    max_entries: int,
) -> tuple[tuple[Path, ...], bool]:
    """Return one bounded directory batch without wedging cleanup on overflow.

    Ordinary mutation/recovery enumeration is deliberately fail-closed when a
    directory exceeds its bound.  Explicit GC is the escape hatch for an old
    or manually-created over-cap transaction directory, so it must make
    bounded progress instead: collect at most ``max_entries`` names and report
    whether another entry remains.
    """

    if (
        isinstance(max_entries, bool)
        or not isinstance(max_entries, int)
        or max_entries < 1
    ):
        raise HubInstallError("Hub GC batch limit is invalid")
    descriptor: int | None = None
    if os.name == "nt":
        if _is_path_redirect(path):
            raise HubInstallError(f"Unsafe Hub redirect: {path}")
        scan_target: Path | int = path
    else:
        descriptor = _open_hub_directory(path, create=False)
        scan_target = descriptor
    try:
        names: list[str] = []
        truncated = False
        with os.scandir(scan_target) as entries:
            for entry in entries:
                if len(names) == max_entries:
                    truncated = True
                    break
                names.append(entry.name)
        names.sort(key=lambda name: name.encode("utf-8", errors="strict"))
        return tuple(path / name for name in names), truncated
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _capture_hub_tree(path: Path) -> TreeSnapshot:
    """Snapshot a tree without reopening its replaceable profile pathname."""

    _validate_hub_mutation_binding()
    if os.name == "nt":
        with _windows_pin_hub_snapshot_root(path) as (
            canonical_path,
            python_identity,
            native_identity,
        ):
            snapshot = capture_tree_snapshot(canonical_path)
            if snapshot.root_identity != python_identity:
                raise HubInstallError("Hub snapshot root changed identity")
            snapshot = replace(
                snapshot,
                native_root_identity=native_identity,
            )
    else:
        descriptor = _open_hub_directory(path, create=False)
        try:
            snapshot = capture_tree_snapshot_fd(descriptor)
        finally:
            os.close(descriptor)
    _validate_hub_mutation_binding()
    return snapshot


def _hub_remove_empty_directory(path: Path) -> None:
    _validate_hub_mutation_binding()
    if os.name == "nt":
        _hub_remove_tree(
            path,
            max_entries=0,
        )
    else:
        parent_fd = _open_hub_directory(path.parent, create=False)
        try:
            os.rmdir(path.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    _validate_hub_mutation_binding()


def _hub_write_regular_file_atomic(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
) -> None:
    """Publish bytes below the pinned profile without following redirects.

    Existing targets must remain the same uniquely linked regular file from
    admission through replacement. This prevents a symlink, hardlink, or
    pathname swap from redirecting a manifest/lock publication.
    """

    _validate_hub_mutation_binding()
    if not isinstance(payload, bytes):
        raise TypeError("atomic profile payload must be bytes")
    temporary_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_fd: int | None = None
    descriptor: int | None = None
    temporary = path.parent / temporary_name
    admitted_identity: tuple[int, int] | None = None
    try:
        if os.name == "nt":  # pragma: no cover - exercised by native Windows CI
            path.parent.mkdir(parents=True, exist_ok=True)
            if _is_path_redirect(path.parent):
                raise HubInstallError("Atomic profile parent must not be redirected")
            try:
                admitted = path.lstat()
            except FileNotFoundError:
                admitted = None
            if admitted is not None:
                if (
                    not stat.S_ISREG(admitted.st_mode)
                    or admitted.st_nlink != 1
                    or _is_path_redirect(path)
                ):
                    raise HubInstallError(
                        "Atomic profile target must be a uniquely linked regular file"
                    )
                admitted_identity = (admitted.st_dev, admitted.st_ino)
            descriptor = os.open(temporary, flags, mode)
        else:
            parent_fd = _open_hub_directory(path.parent, create=True)
            try:
                admitted = os.stat(
                    path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                admitted = None
            if admitted is not None:
                if not stat.S_ISREG(admitted.st_mode) or admitted.st_nlink != 1:
                    raise HubInstallError(
                        "Atomic profile target must be a uniquely linked regular file"
                    )
                admitted_identity = (admitted.st_dev, admitted.st_ino)
            descriptor = os.open(
                temporary_name,
                flags,
                mode,
                dir_fd=parent_fd,
            )
        temporary_state = os.fstat(descriptor)
        if not stat.S_ISREG(temporary_state.st_mode) or temporary_state.st_nlink != 1:
            raise HubInstallError(
                "Atomic profile temporary must be a uniquely linked regular file"
            )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short atomic profile write")
            view = view[written:]
        os.fsync(descriptor)
        _validate_hub_mutation_binding()

        if os.name == "nt":  # pragma: no cover - exercised by native Windows CI
            named_temporary = temporary.lstat()
        else:
            assert parent_fd is not None
            named_temporary = os.stat(
                temporary_name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        if (
            not stat.S_ISREG(named_temporary.st_mode)
            or named_temporary.st_nlink != 1
            or (named_temporary.st_dev, named_temporary.st_ino)
            != (temporary_state.st_dev, temporary_state.st_ino)
            or os.fstat(descriptor).st_nlink != 1
        ):
            raise HubInstallError("Atomic profile temporary changed before publish")

        if os.name == "nt":  # pragma: no cover - exercised by native Windows CI
            try:
                current = path.lstat()
            except FileNotFoundError:
                current_identity = None
            else:
                if (
                    not stat.S_ISREG(current.st_mode)
                    or current.st_nlink != 1
                    or _is_path_redirect(path)
                ):
                    raise HubInstallError("Atomic profile target changed type")
                current_identity = (current.st_dev, current.st_ino)
            if current_identity != admitted_identity:
                raise HubInstallError("Atomic profile target changed before publish")
            os.replace(temporary, path)
            published = path.lstat()
        else:
            assert parent_fd is not None
            try:
                current = os.stat(
                    path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                current_identity = None
            else:
                if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                    raise HubInstallError("Atomic profile target changed type")
                current_identity = (current.st_dev, current.st_ino)
            if current_identity != admitted_identity:
                raise HubInstallError("Atomic profile target changed before publish")
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
            published = os.stat(
                path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        opened_after_publish = os.fstat(descriptor)
        if (
            not stat.S_ISREG(published.st_mode)
            or published.st_nlink != 1
            or (published.st_dev, published.st_ino)
            != (temporary_state.st_dev, temporary_state.st_ino)
            or (opened_after_publish.st_dev, opened_after_publish.st_ino)
            != (temporary_state.st_dev, temporary_state.st_ino)
            or opened_after_publish.st_nlink != 1
        ):
            # The source name can still be exchanged by an uncooperative
            # process inside the final rename syscall boundary.  Never leave
            # that unverified object installed as authoritative state.  Only
            # unlink the exact post-image we just inspected; if its name has
            # changed yet again, retain it for manual inspection rather than
            # deleting an unknown replacement.
            try:
                if os.name == "nt":  # pragma: no cover - native Windows CI
                    current_postimage = path.lstat()
                    if (
                        current_postimage.st_dev,
                        current_postimage.st_ino,
                    ) != (published.st_dev, published.st_ino):
                        raise HubInstallError(
                            "Atomic profile invalid post-image changed again"
                        )
                    path.unlink()
                else:
                    assert parent_fd is not None
                    current_postimage = os.stat(
                        path.name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    if (
                        current_postimage.st_dev,
                        current_postimage.st_ino,
                    ) != (published.st_dev, published.st_ino):
                        raise HubInstallError(
                            "Atomic profile invalid post-image changed again"
                        )
                    os.unlink(path.name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except FileNotFoundError:
                pass
            except HubInstallError:
                raise
            except OSError as exc:
                raise HubInstallError(
                    "Atomic profile invalid post-image could not be removed"
                ) from exc
            raise HubInstallError("Atomic profile post-image changed identity")
        os.close(descriptor)
        descriptor = None
        _validate_hub_mutation_binding()
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_fd is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_fd)
            os.close(parent_fd)
        else:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()


def _hub_unlink_regular_file(path: Path) -> None:
    """Unlink one uniquely linked regular file below the pinned profile."""

    _validate_hub_mutation_binding()
    if os.name == "nt":  # pragma: no cover - exercised by native Windows CI
        inspected = path.lstat()
        if (
            not stat.S_ISREG(inspected.st_mode)
            or inspected.st_nlink != 1
            or _is_path_redirect(path)
        ):
            raise HubInstallError("Profile unlink target is unsafe")
        path.unlink()
    else:
        parent_fd = _open_hub_directory(path.parent, create=False)
        try:
            inspected = os.stat(
                path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            if not stat.S_ISREG(inspected.st_mode) or inspected.st_nlink != 1:
                raise HubInstallError("Profile unlink target is unsafe")
            os.unlink(path.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    _validate_hub_mutation_binding()


@dataclass(frozen=True)
class _WindowsCleanupEntry:
    name: str
    file_id: bytes
    attributes: int


def _windows_close_cleanup_handle(handle: int) -> None:  # pragma: no cover - Windows
    from tools.skill_mutation import _windows_close_handle

    _windows_close_handle(handle)


def _windows_cleanup_handle_information(
    handle: int,
) -> tuple[tuple[int, int], int, int]:  # pragma: no cover - Windows
    from tools.skill_mutation import SkillMutationLockError, _windows_handle_information

    try:
        return _windows_handle_information(handle)
    except SkillMutationLockError as exc:
        if "redirect" in str(exc):
            raise HubInstallError("Unsafe Windows Hub cleanup reparse point") from exc
        raise HubInstallError("Unsafe Windows Hub cleanup handle") from exc


def _windows_cleanup_extended_identity(
    handle: int,
) -> tuple[int, bytes]:  # pragma: no cover - Windows
    """Return the volume plus 128-bit ID used by extended enumeration."""

    import ctypes
    from ctypes import wintypes

    class FILE_ID_INFO(ctypes.Structure):
        _fields_ = [
            ("VolumeSerialNumber", ctypes.c_ulonglong),
            ("FileId", ctypes.c_ubyte * 16),
        ]

    file_id_info = 18
    identity = FILE_ID_INFO()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    if not kernel32.GetFileInformationByHandleEx(
        wintypes.HANDLE(handle),
        file_id_info,
        ctypes.byref(identity),
        ctypes.sizeof(identity),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, "could not query extended Windows cleanup identity")
    file_id = bytes(identity.FileId)
    if not any(file_id):
        raise HubInstallError(
            "Windows cleanup filesystem has no stable extended file identity"
        )
    return int(identity.VolumeSerialNumber), file_id


def _windows_reopen_cleanup_home(
    anchor_handle: int,
    *,
    add_directory_access: bool = False,
    share_write: bool = False,
) -> tuple[int, tuple[int, int]]:  # pragma: no cover - Windows
    """Reopen the exact lease-pinned home with cleanup-exclusive sharing."""

    import ctypes
    from ctypes import wintypes

    file_list_directory = 0x0001
    file_add_subdirectory = 0x0004
    file_traverse = 0x0020
    file_read_attributes = 0x0080
    synchronize = 0x00100000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    invalid_handle_value = ctypes.c_void_p(-1).value
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReOpenFile.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.ReOpenFile.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    desired_access = (
        file_list_directory | file_traverse | file_read_attributes | synchronize
    )
    if add_directory_access:
        desired_access |= file_add_subdirectory
    raw_handle = kernel32.ReOpenFile(
        wintypes.HANDLE(anchor_handle),
        desired_access,
        # Cleanup permits concurrent readers only. A rename destination also
        # shares writes because the I/O manager performs its own relative
        # FILE_WRITE_DATA open, while still denying delete/rename of the
        # pinned parent itself.
        file_share_read | (file_share_write if share_write else 0),
        file_flag_backup_semantics | file_flag_open_reparse_point,
    )
    handle = ctypes.cast(raw_handle, ctypes.c_void_p).value
    if handle in (None, invalid_handle_value):
        error = ctypes.get_last_error()
        raise OSError(error, "could not reopen Windows cleanup profile root")
    try:
        identity, _links, attributes = _windows_cleanup_handle_information(handle)
        directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if not attributes & directory_flag or attributes & reparse_flag:
            raise HubInstallError("Windows cleanup profile root is unsafe")
        return handle, identity
    except BaseException:
        _windows_close_cleanup_handle(handle)
        raise


def _windows_open_cleanup_relative(
    parent_handle: int,
    name: str,
    *,
    directory: bool,
    delete_access: bool,
    add_directory_access: bool = False,
    share_write: bool = False,
    create: bool = False,
    create_exclusive: bool = False,
) -> tuple[int, tuple[int, int], int, int]:  # pragma: no cover - Windows
    """Open one exact child below a pinned HANDLE without parsing a path."""

    import ctypes
    from ctypes import wintypes

    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "\x00" in name
        or "/" in name
        or "\\" in name
    ):
        raise HubInstallError("Invalid Windows Hub cleanup path component")

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class OBJECT_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UNICODE_STRING)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", ctypes.c_void_p),
            ("SecurityQualityOfService", ctypes.c_void_p),
        ]

    class STATUS_OR_POINTER(ctypes.Union):
        _fields_ = [("Status", wintypes.LONG), ("Pointer", ctypes.c_void_p)]

    class IO_STATUS_BLOCK(ctypes.Structure):
        _anonymous_ = ("result",)
        _fields_ = [("result", STATUS_OR_POINTER), ("Information", ctypes.c_size_t)]

    delete = 0x00010000
    synchronize = 0x00100000
    file_list_directory = 0x0001
    file_add_subdirectory = 0x0004
    file_traverse = 0x0020
    file_read_attributes = 0x0080
    file_write_attributes = 0x0100
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_open = 0x00000001
    file_create = 0x00000002
    file_open_if = 0x00000003
    file_directory_file = 0x00000001
    file_synchronous_io_nonalert = 0x00000020
    file_open_reparse_point = 0x00200000

    desired_access = file_read_attributes | synchronize
    create_options = file_open_reparse_point | file_synchronous_io_nonalert
    if directory:
        desired_access |= file_list_directory | file_traverse
        if add_directory_access:
            desired_access |= file_add_subdirectory
    elif add_directory_access:
        raise HubInstallError("Cannot add children through a non-directory handle")
    if delete_access:
        desired_access |= delete | file_write_attributes
    if create:
        if not directory:
            raise HubInstallError("Windows Hub creation target must be a directory")
        create_options |= file_directory_file
    elif create_exclusive:
        raise HubInstallError("Exclusive Windows Hub creation requires create mode")

    encoded_length = len(name.encode("utf-16-le"))
    name_buffer = ctypes.create_unicode_buffer(name)
    unicode_name = UNICODE_STRING(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    object_attributes = OBJECT_ATTRIBUTES(
        ctypes.sizeof(OBJECT_ATTRIBUTES),
        wintypes.HANDLE(parent_handle),
        ctypes.pointer(unicode_name),
        # Preserve the exact enumerated/profile component spelling. On a
        # case-sensitive Windows directory, case-insensitive lookup could open
        # a sibling with a different identity.
        0,
        None,
        None,
    )
    io_status = IO_STATUS_BLOCK()
    opened_handle = wintypes.HANDLE()
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(OBJECT_ATTRIBUTES),
        ctypes.POINTER(IO_STATUS_BLOCK),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    ntdll.NtCreateFile.restype = wintypes.LONG
    status = int(
        ntdll.NtCreateFile(
            ctypes.byref(opened_handle),
            desired_access,
            ctypes.byref(object_attributes),
            ctypes.byref(io_status),
            None,
            0,
            file_share_read | (file_share_write if share_write else 0),
            file_create
            if create_exclusive
            else (file_open_if if create else file_open),
            create_options,
            None,
            0,
        )
    )
    if status < 0:
        ntdll.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
        ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
        error = int(ntdll.RtlNtStatusToDosError(status))
        raise OSError(error, f"could not pin Windows cleanup entry {name!r}")
    handle = ctypes.cast(opened_handle, ctypes.c_void_p).value
    if handle is None:
        raise HubInstallError("Windows cleanup entry returned no handle")
    try:
        identity, links, attributes = _windows_cleanup_handle_information(handle)
        directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            bool(attributes & directory_flag) is not directory
            or attributes & reparse_flag
        ):
            raise HubInstallError("Windows cleanup entry changed type")
        return handle, identity, links, attributes
    except BaseException:
        _windows_close_cleanup_handle(handle)
        raise


def _windows_open_hub_directory_fd(
    path: Path,
    *,
    create: bool,
    exclusive_final: bool = False,
) -> int:  # pragma: no cover - Windows
    """Open/create a Hub directory from the lease root and return a CRT fd."""

    import msvcrt

    binding = _ACTIVE_HUB_MUTATION.get()
    if binding is None:
        raise RuntimeError("active Hub mutation scope is required")
    parts = _hub_relative_parts(path)
    if parts is None:
        raise HubInstallError("Hub directory path is outside the active profile")

    anchor_handle: int | None = None
    home_handle: int | None = None
    component_handles: list[int] = []
    final_handle: int | None = None
    descriptor: int | None = None
    try:
        anchor_handle = duplicate_mutation_home_handle(
            binding.home,
            binding.lease,
            kind="skills",
        )
        if anchor_handle is None:
            raise HubInstallError("Windows Hub profile capability is unavailable")
        anchor_identity, _links, _attributes = _windows_cleanup_handle_information(
            anchor_handle
        )
        home_handle, home_identity = _windows_reopen_cleanup_home(
            anchor_handle,
            add_directory_access=create,
        )
        if home_identity != anchor_identity:
            raise HubInstallError("Windows Hub profile generation changed")

        parent_handle = home_handle
        for index, component in enumerate(parts):
            handle, _identity, _links, _attributes = _windows_open_cleanup_relative(
                parent_handle,
                component,
                directory=True,
                delete_access=False,
                add_directory_access=create,
                create=create,
                create_exclusive=exclusive_final and index == len(parts) - 1,
            )
            component_handles.append(handle)
            parent_handle = handle

        if component_handles:
            final_handle = component_handles.pop()
        else:
            final_handle = home_handle
            home_handle = None
        descriptor = msvcrt.open_osfhandle(
            final_handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        final_handle = None  # The CRT descriptor now owns the native HANDLE.
        _validate_hub_mutation_binding()
        result = descriptor
        descriptor = None
        return result
    except HubInstallError:
        raise
    except OSError as exc:
        raise HubInstallError("Could not safely open Windows Hub directory") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if final_handle is not None:
            _windows_close_cleanup_handle(final_handle)
        for handle in reversed(component_handles):
            _windows_close_cleanup_handle(handle)
        if home_handle is not None:
            _windows_close_cleanup_handle(home_handle)
        if anchor_handle is not None:
            _windows_close_cleanup_handle(anchor_handle)


@contextmanager
def _windows_pin_hub_snapshot_root(
    path: Path,
) -> Iterator[
    tuple[Path, tuple[int, int], tuple[int, bytes]]
]:  # pragma: no cover - Windows
    """Pin one exact profile-relative root while portable capture reads it."""

    binding = _ACTIVE_HUB_MUTATION.get()
    if binding is None:
        raise RuntimeError("active Hub mutation scope is required")
    parts = _hub_relative_parts(path)
    if parts is None or not parts:
        raise HubInstallError("Hub snapshot path must be below the active profile")

    anchor_handle: int | None = None
    home_handle: int | None = None
    component_handles: list[int] = []
    try:
        anchor_handle = duplicate_mutation_home_handle(
            binding.home,
            binding.lease,
            kind="skills",
        )
        if anchor_handle is None:
            raise HubInstallError("Windows snapshot profile capability is unavailable")
        anchor_identity, _links, _attributes = _windows_cleanup_handle_information(
            anchor_handle
        )
        home_handle, home_identity = _windows_reopen_cleanup_home(anchor_handle)
        if home_identity != anchor_identity:
            raise HubInstallError("Windows snapshot profile generation changed")

        parent_handle = home_handle
        for component in parts:
            handle, _identity, _links, _attributes = _windows_open_cleanup_relative(
                parent_handle,
                component,
                directory=True,
                delete_access=False,
            )
            component_handles.append(handle)
            parent_handle = handle

        canonical_target = binding.home.joinpath(*parts)
        named = canonical_target.lstat()
        if not stat.S_ISDIR(named.st_mode):
            raise HubInstallError("Hub snapshot root is not a directory")
        python_identity = (named.st_dev, named.st_ino)
        native_identity = _windows_cleanup_extended_identity(component_handles[-1])
        yield canonical_target, python_identity, native_identity
    except HubInstallError:
        raise
    except (OSError, UnicodeError) as exc:
        raise HubInstallError("Could not safely pin Windows Hub snapshot") from exc
    finally:
        for handle in reversed(component_handles):
            _windows_close_cleanup_handle(handle)
        if home_handle is not None:
            _windows_close_cleanup_handle(home_handle)
        if anchor_handle is not None:
            _windows_close_cleanup_handle(anchor_handle)


def _windows_cleanup_directory_entries(
    directory_handle: int,
    *,
    max_entries: int,
) -> tuple[_WindowsCleanupEntry, ...]:  # pragma: no cover - Windows
    """Enumerate one pinned directory without consulting its pathname."""

    import ctypes
    from ctypes import wintypes

    class FILE_ID_EXTD_DIR_INFO(ctypes.Structure):
        _fields_ = [
            ("NextEntryOffset", wintypes.DWORD),
            ("FileIndex", wintypes.DWORD),
            ("CreationTime", ctypes.c_longlong),
            ("LastAccessTime", ctypes.c_longlong),
            ("LastWriteTime", ctypes.c_longlong),
            ("ChangeTime", ctypes.c_longlong),
            ("EndOfFile", ctypes.c_longlong),
            ("AllocationSize", ctypes.c_longlong),
            ("FileAttributes", wintypes.DWORD),
            ("FileNameLength", wintypes.DWORD),
            ("EaSize", wintypes.DWORD),
            ("ReparsePointTag", wintypes.DWORD),
            ("FileId", ctypes.c_ubyte * 16),
            ("FileName", wintypes.WCHAR * 1),
        ]

    if max_entries < 0:
        raise HubInstallError("Hub cleanup tree exceeds the entry limit")
    file_id_extd_directory_info = 19
    file_id_extd_directory_restart_info = 20
    error_no_more_files = 18
    buffer_size = 64 * 1024
    buffer = ctypes.create_string_buffer(buffer_size)
    if (
        ctypes.addressof(buffer) % 8
        or FILE_ID_EXTD_DIR_INFO.FileId.offset % 8
        or FILE_ID_EXTD_DIR_INFO.FileName.offset
        != FILE_ID_EXTD_DIR_INFO.FileId.offset + 16
    ):
        raise HubInstallError("Windows cleanup enumeration layout is unsupported")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    results: list[_WindowsCleanupEntry] = []
    casefolded_names: set[str] = set()
    first_query = True
    while True:
        ctypes.set_last_error(0)
        if not kernel32.GetFileInformationByHandleEx(
            wintypes.HANDLE(directory_handle),
            (
                file_id_extd_directory_restart_info
                if first_query
                else file_id_extd_directory_info
            ),
            buffer,
            buffer_size,
        ):
            error = ctypes.get_last_error()
            if error == error_no_more_files:
                break
            raise OSError(error, "could not enumerate Windows cleanup directory")
        first_query = False
        offset = 0
        while True:
            if offset + FILE_ID_EXTD_DIR_INFO.FileName.offset > buffer_size:
                raise HubInstallError("Windows cleanup enumeration is malformed")
            record = FILE_ID_EXTD_DIR_INFO.from_buffer(buffer, offset)
            name_length = int(record.FileNameLength)
            name_offset = offset + FILE_ID_EXTD_DIR_INFO.FileName.offset
            next_offset = int(record.NextEntryOffset)
            if next_offset != 0 and (
                next_offset % 8
                or next_offset < FILE_ID_EXTD_DIR_INFO.FileName.offset
                or offset + next_offset >= buffer_size
            ):
                raise HubInstallError("Windows cleanup enumeration offset is malformed")
            record_end = offset + next_offset if next_offset else buffer_size
            if (
                name_length % 2
                or name_length <= 0
                or name_offset + name_length > record_end
            ):
                raise HubInstallError("Windows cleanup entry name is malformed")
            name = ctypes.string_at(
                ctypes.addressof(buffer) + name_offset,
                name_length,
            ).decode("utf-16-le", errors="strict")
            if name not in {".", ".."}:
                if "\x00" in name or "/" in name or "\\" in name:
                    raise HubInstallError("Windows cleanup entry name is unsafe")
                folded = name.casefold()
                if folded in casefolded_names:
                    raise HubInstallError(
                        "Windows cleanup directory contains ambiguous names"
                    )
                casefolded_names.add(folded)
                if len(results) >= max_entries:
                    raise HubInstallError("Hub cleanup tree exceeds the entry limit")
                file_id = bytes(record.FileId)
                if not any(file_id):
                    raise HubInstallError(
                        "Windows cleanup entry has no stable identity"
                    )
                results.append(
                    _WindowsCleanupEntry(
                        name=name,
                        file_id=file_id,
                        attributes=int(record.FileAttributes),
                    )
                )
            if next_offset == 0:
                break
            offset += next_offset
    return tuple(results)


def _windows_mark_cleanup_deleted(handle: int) -> None:  # pragma: no cover - Windows
    """Mark the exact opened entry for deletion; never reopen its pathname."""

    import ctypes
    from ctypes import wintypes

    class FILE_DISPOSITION_INFO(ctypes.Structure):
        # Win32 BOOLEAN is one byte (unlike BOOL).
        _fields_ = [("DeleteFile", ctypes.c_ubyte)]

    class FILE_DISPOSITION_INFO_EX(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD)]

    class FILE_BASIC_INFO(ctypes.Structure):
        _fields_ = [
            ("CreationTime", ctypes.c_longlong),
            ("LastAccessTime", ctypes.c_longlong),
            ("LastWriteTime", ctypes.c_longlong),
            ("ChangeTime", ctypes.c_longlong),
            ("FileAttributes", wintypes.DWORD),
        ]

    file_basic_info = 0
    file_disposition_info = 4
    file_disposition_info_ex = 21
    file_disposition_flag_delete = 0x00000001
    file_disposition_flag_ignore_readonly_attribute = 0x00000010
    file_attribute_readonly = 0x00000001
    file_attribute_normal = 0x00000080
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL

    # Modern Windows can ignore READONLY atomically on this exact handle.
    # Fall back to exact-handle FileBasicInfo + legacy disposition for older
    # filesystems that reject FileDispositionInfoEx.
    extended = FILE_DISPOSITION_INFO_EX(
        file_disposition_flag_delete | file_disposition_flag_ignore_readonly_attribute
    )
    ctypes.set_last_error(0)
    if kernel32.SetFileInformationByHandle(
        wintypes.HANDLE(handle),
        file_disposition_info_ex,
        ctypes.byref(extended),
        ctypes.sizeof(extended),
    ):
        return
    extended_error = ctypes.get_last_error()
    unsupported_errors = {1, 50, 87, 120, 124}
    if extended_error not in unsupported_errors:
        raise OSError(
            extended_error,
            "could not delete exact Windows cleanup entry",
        )

    basic = FILE_BASIC_INFO()
    ctypes.set_last_error(0)
    if not kernel32.GetFileInformationByHandleEx(
        wintypes.HANDLE(handle),
        file_basic_info,
        ctypes.byref(basic),
        ctypes.sizeof(basic),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, "could not inspect exact Windows cleanup entry")
    original_attributes: int | None = None
    if basic.FileAttributes & file_attribute_readonly:
        original_attributes = int(basic.FileAttributes)
        attributes = int(basic.FileAttributes) & ~file_attribute_readonly
        if attributes == 0:
            attributes = file_attribute_normal
        update = FILE_BASIC_INFO(0, 0, 0, 0, attributes)
        ctypes.set_last_error(0)
        if not kernel32.SetFileInformationByHandle(
            wintypes.HANDLE(handle),
            file_basic_info,
            ctypes.byref(update),
            ctypes.sizeof(update),
        ):
            error = ctypes.get_last_error()
            raise OSError(error, "could not clear exact Windows cleanup readonly flag")

    disposition = FILE_DISPOSITION_INFO(1)
    ctypes.set_last_error(0)
    if not kernel32.SetFileInformationByHandle(
        wintypes.HANDLE(handle),
        file_disposition_info,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        error = ctypes.get_last_error()
        if original_attributes is not None:
            restore = FILE_BASIC_INFO(0, 0, 0, 0, original_attributes)
            ctypes.set_last_error(0)
            if not kernel32.SetFileInformationByHandle(
                wintypes.HANDLE(handle),
                file_basic_info,
                ctypes.byref(restore),
                ctypes.sizeof(restore),
            ):
                restore_error = ctypes.get_last_error()
                raise OSError(
                    restore_error,
                    "could not restore exact Windows cleanup readonly flag",
                )
        raise OSError(error, "could not delete exact Windows cleanup entry")


def _windows_remove_hub_tree(
    path: Path,
    *,
    expected_identity: tuple[int, int] | None,
    expected_native_identity: tuple[int, bytes] | None,
    max_entries: int,
) -> None:  # pragma: no cover - Windows
    """Delete a profile-relative tree using only pinned native capabilities."""

    if (
        isinstance(max_entries, bool)
        or not isinstance(max_entries, int)
        or max_entries < 0
    ):
        raise HubInstallError("Hub cleanup entry limit is invalid")
    binding = _ACTIVE_HUB_MUTATION.get()
    if binding is None:
        raise RuntimeError("active Hub mutation scope is required")
    parts = _hub_relative_parts(path)
    if parts is None or not parts:
        raise HubInstallError("Hub cleanup path must be below the active profile")

    anchor_handle: int | None = None
    home_handle: int | None = None
    component_handles: list[int] = []
    try:
        anchor_handle = duplicate_mutation_home_handle(
            binding.home,
            binding.lease,
            kind="skills",
        )
        if anchor_handle is None:
            raise HubInstallError("Windows cleanup profile capability is unavailable")
        anchor_identity, _links, _attributes = _windows_cleanup_handle_information(
            anchor_handle
        )
        home_handle, home_identity = _windows_reopen_cleanup_home(anchor_handle)
        if home_identity != anchor_identity:
            raise HubInstallError("Windows cleanup profile generation changed")

        parent_handle = home_handle
        for index, component in enumerate(parts):
            is_root = index == len(parts) - 1
            handle, _identity, _links, _attributes = _windows_open_cleanup_relative(
                parent_handle,
                component,
                directory=True,
                delete_access=is_root,
            )
            component_handles.append(handle)
            parent_handle = handle

        canonical_target = binding.home.joinpath(*parts)
        named = canonical_target.lstat()
        if not stat.S_ISDIR(named.st_mode):
            raise HubInstallError("Hub cleanup target is not a directory")
        if (
            expected_identity is not None
            and (
                named.st_dev,
                named.st_ino,
            )
            != expected_identity
        ):
            raise HubInstallError("Hub cleanup target changed identity")

        root_handle = component_handles[-1]
        root_extended_identity = _windows_cleanup_extended_identity(root_handle)
        if (
            expected_native_identity is not None
            and root_extended_identity != expected_native_identity
        ):
            raise HubInstallError("Hub cleanup target changed native identity")
        seen = 0

        def remove_contents(
            directory_handle: int,
            directory_identity: tuple[int, bytes],
        ) -> None:
            nonlocal seen
            entries = _windows_cleanup_directory_entries(
                directory_handle,
                max_entries=max_entries - seen,
            )
            seen += len(entries)
            directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            for entry in entries:
                if entry.attributes & reparse_flag:
                    raise HubInstallError("Unsafe Hub cleanup reparse point")
                is_directory = bool(entry.attributes & directory_flag)
                child_handle: int | None = None
                try:
                    child_handle, _child_identity, links, opened_attributes = (
                        _windows_open_cleanup_relative(
                            directory_handle,
                            entry.name,
                            directory=is_directory,
                            delete_access=True,
                        )
                    )
                    child_extended_identity = _windows_cleanup_extended_identity(
                        child_handle
                    )
                    if (
                        child_extended_identity[0] != directory_identity[0]
                        or child_extended_identity[1] != entry.file_id
                        or bool(opened_attributes & directory_flag) is not is_directory
                    ):
                        raise HubInstallError(
                            "Windows cleanup entry changed after enumeration"
                        )
                    if is_directory:
                        remove_contents(child_handle, child_extended_identity)
                    elif links != 1:
                        raise HubInstallError(
                            "Windows cleanup file must be uniquely linked"
                        )
                    _windows_mark_cleanup_deleted(child_handle)
                finally:
                    if child_handle is not None:
                        _windows_close_cleanup_handle(child_handle)

        remove_contents(root_handle, root_extended_identity)
        _validate_hub_mutation_binding()
        # FileDispositionInfo binds deletion to this exact open directory. A
        # replacement created later is never revisited or removed.
        _windows_mark_cleanup_deleted(root_handle)
        _windows_close_cleanup_handle(root_handle)
        component_handles.pop()
        # Keep every ancestor capability pinned while confirming that closing
        # our exact root handle removed its entry from the pinned parent. A
        # foreign reader may otherwise leave the directory delete-pending.
        root_parent_handle = component_handles[-1] if component_handles else home_handle
        if root_parent_handle is None:
            raise HubInstallError("Windows cleanup root parent is unavailable")
        parent_entries = _windows_cleanup_directory_entries(
            root_parent_handle,
            max_entries=MAX_HUB_DIRECTORY_ENTRIES,
        )
        root_name = parts[-1].casefold()
        if any(entry.name.casefold() == root_name for entry in parent_entries):
            raise HubInstallError("Windows Hub cleanup deletion is still pending")
    except HubInstallError:
        raise
    except (OSError, UnicodeError) as exc:
        raise HubInstallError("Could not safely remove Windows Hub tree") from exc
    finally:
        for handle in reversed(component_handles):
            _windows_close_cleanup_handle(handle)
        if home_handle is not None:
            _windows_close_cleanup_handle(home_handle)
        if anchor_handle is not None:
            _windows_close_cleanup_handle(anchor_handle)


def _hub_remove_tree(
    path: Path,
    *,
    expected_identity: tuple[int, int] | None = None,
    expected_native_identity: tuple[int, bytes] | None = None,
    max_entries: int = MAX_HUB_CLEANUP_ENTRIES,
) -> None:
    """Remove one descriptor-contained directory tree under a strict bound."""

    _validate_hub_mutation_binding()
    if os.name == "nt":  # pragma: no cover - exercised by native Windows CI
        _windows_remove_hub_tree(
            path,
            expected_identity=expected_identity,
            expected_native_identity=expected_native_identity,
            max_entries=max_entries,
        )
        _validate_hub_mutation_binding()
        return

    inspected = _hub_lstat(path)
    if not stat.S_ISDIR(inspected.st_mode):
        raise HubInstallError("Hub cleanup target is not a directory")
    if (
        expected_identity is not None
        and (inspected.st_dev, inspected.st_ino) != expected_identity
    ):
        raise HubInstallError("Hub cleanup target changed identity")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_fd = _open_hub_directory(path.parent, create=False)
    root_fd: int | None = None
    seen = 0

    def remove_contents(directory_fd: int) -> None:
        nonlocal seen
        if hasattr(os, "fchmod"):
            current_mode = stat.S_IMODE(os.fstat(directory_fd).st_mode)
            os.fchmod(directory_fd, current_mode | stat.S_IRWXU)
        names: list[str] = []
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                seen += 1
                if seen > max_entries:
                    raise HubInstallError("Hub cleanup tree exceeds the entry limit")
                names.append(entry.name)
        for name in names:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(current.st_mode):
                child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
                try:
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino) != (
                        current.st_dev,
                        current.st_ino,
                    ):
                        raise HubInstallError("Hub cleanup directory changed identity")
                    remove_contents(child_fd)
                finally:
                    os.close(child_fd)
                os.rmdir(name, dir_fd=directory_fd)
            elif stat.S_ISREG(current.st_mode):
                os.unlink(name, dir_fd=directory_fd)
            else:
                raise HubInstallError("Unsafe Hub cleanup entry")
        os.fsync(directory_fd)

    try:
        root_fd = os.open(path.name, directory_flags, dir_fd=parent_fd)
        opened = os.fstat(root_fd)
        if (
            expected_identity is not None
            and (opened.st_dev, opened.st_ino) != expected_identity
        ):
            raise HubInstallError("Hub cleanup target changed identity")
        remove_contents(root_fd)
        os.close(root_fd)
        root_fd = None
        os.rmdir(path.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)
    _validate_hub_mutation_binding()


def _create_hub_directory(path: Path, *, mode: int = 0o700) -> None:
    """Create exactly one directory below a descriptor-bound Hub parent."""

    _validate_hub_mutation_binding()
    if os.name == "nt":
        del mode
        descriptor = _windows_open_hub_directory_fd(
            path,
            create=True,
            exclusive_final=True,
        )
        os.close(descriptor)
        _validate_hub_mutation_binding()
        return
    parent_fd = _open_hub_directory(path.parent, create=True)
    try:
        os.mkdir(path.name, mode=mode, dir_fd=parent_fd)
        child_fd = _open_hub_directory(path, create=False)
        try:
            os.fsync(child_fd)
        finally:
            os.close(child_fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    _validate_hub_mutation_binding()


@contextmanager
def hub_mutation_scope(
    home: Path,
    *,
    skills_dir: Path | None = None,
) -> Iterator[MutationLockLease]:
    """Serialize Hub mutations and bind them to one profile generation.

    Windows directory handles held by the underlying lease deny rename. POSIX
    validates the still-open home/lock parent identity immediately around every
    shared Hub effect. All cooperative profile movers use this same lock.
    """

    lexical_home = Path(os.path.abspath(home))
    if _is_path_redirect(lexical_home):
        raise RuntimeError("Hub mutation profile home must not be redirected")
    lexical_skills = Path(
        os.path.abspath(
            skills_dir if skills_dir is not None else lexical_home / "skills"
        )
    )
    try:
        relative_skills = lexical_skills.relative_to(lexical_home)
    except ValueError as exc:
        raise RuntimeError("Hub skills directory must belong to its profile") from exc
    if not relative_skills.parts:
        raise RuntimeError("Hub skills directory must be below its profile")
    canonical_home = Path(home).resolve(strict=False)
    active = _ACTIVE_HUB_MUTATION.get()
    if active is not None:
        if active.home != canonical_home or (
            skills_dir is not None and active.skills_dir != lexical_skills
        ):
            raise RuntimeError("nested Hub mutation targets another profile")
        _validate_hub_mutation_binding()
        yield active.lease
        return

    with skill_mutation_lock(canonical_home) as lease:
        home_fd = duplicate_mutation_home_fd(
            canonical_home,
            lease,
            kind="skills",
        )
        binding = _HubMutationBinding(
            canonical_home,
            lexical_home,
            lexical_skills,
            skills_dir is None,
            lease,
            home_fd,
        )
        token = _ACTIVE_HUB_MUTATION.set(binding)
        try:
            _validate_hub_mutation_binding()
            yield lease
        finally:
            _ACTIVE_HUB_MUTATION.reset(token)
            if home_fd is not None:
                os.close(home_fd)


_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_MAX_SKILL_FETCH_REDIRECTS = 5


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SkillMeta:
    """Minimal metadata returned by search results."""

    name: str
    description: str
    source: str  # "official", "github", "clawhub", "claude-marketplace", "lobehub"
    identifier: str  # source-specific ID (e.g. "openai/skills/skill-creator")
    trust_level: str  # "builtin" | "trusted" | "community"
    repo: Optional[str] = None
    path: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillBundle:
    """A downloaded skill ready for quarantine/scanning/installation."""

    name: str
    files: Dict[str, Union[str, bytes]]  # relative_path -> file content
    source: str
    identifier: str
    trust_level: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class HubSourceKind(str, Enum):
    """Authenticated adapter identity, never derived from a package slug."""

    OFFICIAL_OPTIONAL = "official"
    FABRIC_INDEX = "fabric-index"
    SKILLS_SH = "skills-sh"
    WELL_KNOWN = "well-known"
    URL = "url"
    GITHUB = "github"
    CLAWHUB = "clawhub"
    CLAUDE_MARKETPLACE = "claude-marketplace"
    LOBEHUB = "lobehub"
    BROWSE_SH = "browse-sh"
    UNVERIFIED = "unverified"


_AUTHORITY_TRUST_LEVELS = frozenset({"builtin", "trusted", "community"})
_AUTHORITY_BUNDLE_SOURCES = {
    HubSourceKind.OFFICIAL_OPTIONAL: "official",
    HubSourceKind.FABRIC_INDEX: "fabric-index",
    HubSourceKind.SKILLS_SH: "skills.sh",
    HubSourceKind.WELL_KNOWN: "well-known",
    HubSourceKind.URL: "url",
    HubSourceKind.GITHUB: "github",
    HubSourceKind.CLAWHUB: "clawhub",
    HubSourceKind.CLAUDE_MARKETPLACE: "claude-marketplace",
    HubSourceKind.LOBEHUB: "lobehub",
    HubSourceKind.BROWSE_SH: "browse-sh",
}
_AUTHORITY_REPO_ADAPTERS = frozenset({
    HubSourceKind.GITHUB,
    HubSourceKind.SKILLS_SH,
    HubSourceKind.CLAUDE_MARKETPLACE,
})


def _authority_repository(
    adapter: HubSourceKind,
    identifier: str,
) -> str:
    canonical = identifier
    if adapter is HubSourceKind.SKILLS_SH:
        if not identifier.startswith("skills-sh/"):
            return ""
        canonical = identifier.removeprefix("skills-sh/")
    parts = canonical.split("/", 2)
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ""


@dataclass(frozen=True)
class HubSourceAuthority:
    """Adapter-attested provenance used by scanning, journals, and lock state."""

    adapter: HubSourceKind
    remote_identifier: str
    bundle_source: str
    trust_level: str

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, HubSourceKind):
            raise HubInstallError("Hub source authority adapter is invalid")
        if not isinstance(self.remote_identifier, str) or not self.remote_identifier:
            raise HubInstallError("Hub source authority identifier is invalid")
        if not isinstance(self.bundle_source, str) or not self.bundle_source:
            raise HubInstallError("Hub source authority bundle source is invalid")
        if self.trust_level not in _AUTHORITY_TRUST_LEVELS:
            raise HubInstallError("Hub source authority trust level is invalid")
        expected_source = _AUTHORITY_BUNDLE_SOURCES.get(self.adapter)
        if self.adapter is not HubSourceKind.UNVERIFIED and (
            expected_source is None or self.bundle_source != expected_source
        ):
            raise HubInstallError("Hub source authority adapter/source disagree")
        if self.adapter is HubSourceKind.OFFICIAL_OPTIONAL:
            prefix = "official/"
            try:
                official_path = normalize_relative_path(
                    self.remote_identifier.removeprefix(prefix),
                    field="official Hub identifier",
                )
            except (UnsafePathError, ValueError) as exc:
                raise HubInstallError("Official Hub authority is invalid") from exc
            if (
                self.trust_level != "builtin"
                or not self.remote_identifier.startswith(prefix)
                or self.remote_identifier != f"{prefix}{official_path}"
            ):
                raise HubInstallError("Official Hub authority is invalid")
        elif self.trust_level == "builtin":
            raise HubInstallError(
                "Only the local official adapter can grant builtin trust"
            )
        if self.adapter is HubSourceKind.UNVERIFIED and self.trust_level != "community":
            raise HubInstallError("Unverified Hub authority must be community trust")
        if self.trust_level == "trusted":
            repository = _authority_repository(self.adapter, self.remote_identifier)
            if (
                self.adapter not in _AUTHORITY_REPO_ADAPTERS
                or repository.casefold()
                not in {repo.casefold() for repo in TRUSTED_REPOS}
            ):
                raise HubInstallError(
                    "Trusted Hub authority must name a code-allowlisted repository"
                )
        elif (
            self.adapter not in _AUTHORITY_REPO_ADAPTERS
            and self.adapter
            not in {
                HubSourceKind.OFFICIAL_OPTIONAL,
                HubSourceKind.UNVERIFIED,
            }
            and self.trust_level != "community"
        ):
            raise HubInstallError("Hub adapter cannot grant elevated trust")

    @property
    def scan_source(self) -> str:
        return f"hub-adapter:{self.adapter.value}:{self.remote_identifier}"

    def as_dict(self) -> dict[str, str]:
        return {
            "adapter": self.adapter.value,
            "remote_identifier": self.remote_identifier,
            "bundle_source": self.bundle_source,
            "trust_level": self.trust_level,
        }

    @classmethod
    def from_dict(cls, value: object) -> "HubSourceAuthority":
        if not isinstance(value, dict) or set(value) != {
            "adapter",
            "remote_identifier",
            "bundle_source",
            "trust_level",
        }:
            raise HubInstallError("Hub source authority record is invalid")
        try:
            adapter = HubSourceKind(value["adapter"])
        except (TypeError, ValueError) as exc:
            raise HubInstallError("Hub source authority adapter is invalid") from exc
        return cls(
            adapter=adapter,
            remote_identifier=value["remote_identifier"],
            bundle_source=value["bundle_source"],
            trust_level=value["trust_level"],
        )

    def validate_bundle(self, bundle: SkillBundle) -> None:
        if (
            bundle.identifier != self.remote_identifier
            or bundle.source != self.bundle_source
        ):
            raise HubInstallError("Hub bundle provenance changed after adapter fetch")


def _legacy_unverified_authority(
    bundle: SkillBundle,
    scan_result: ScanResult,
) -> HubSourceAuthority:
    """Compatibility for direct library callers; it can never elevate trust."""

    if scan_result.trust_level != "community":
        raise HubInstallError(
            "Direct Hub installs require typed adapter provenance for elevated trust"
        )
    return HubSourceAuthority(
        adapter=HubSourceKind.UNVERIFIED,
        remote_identifier=bundle.identifier,
        bundle_source=bundle.source,
        trust_level="community",
    )


def _concrete_adapter_identity(
    adapter: "SkillSource",
) -> tuple[HubSourceKind, str]:
    """Return code-owned identity for an exact built-in adapter class."""

    identity = {
        OptionalSkillSource: (HubSourceKind.OFFICIAL_OPTIONAL, "official"),
        FabricIndexSource: (HubSourceKind.FABRIC_INDEX, "fabric-index"),
        SkillsShSource: (HubSourceKind.SKILLS_SH, "skills.sh"),
        WellKnownSkillSource: (HubSourceKind.WELL_KNOWN, "well-known"),
        UrlSource: (HubSourceKind.URL, "url"),
        GitHubSource: (HubSourceKind.GITHUB, "github"),
        ClawHubSource: (HubSourceKind.CLAWHUB, "clawhub"),
        ClaudeMarketplaceSource: (
            HubSourceKind.CLAUDE_MARKETPLACE,
            "claude-marketplace",
        ),
        LobeHubSource: (HubSourceKind.LOBEHUB, "lobehub"),
        BrowseShSource: (HubSourceKind.BROWSE_SH, "browse-sh"),
    }.get(type(adapter))
    if identity is None:
        raise HubInstallError("Unknown or virtual Skills Hub source adapter")
    return identity


def source_authority_for_adapter(
    adapter: "SkillSource",
    bundle: SkillBundle,
) -> HubSourceAuthority:
    """Bind a fetched bundle to the concrete adapter that returned it."""

    try:
        kind, expected_bundle_source = _concrete_adapter_identity(adapter)
    except HubInstallError:
        # Adapter authority is code-owned.  A plugin, mock, proxy, or subclass
        # may expose ``source_id() == 'github'`` (or even ``'official'``), but
        # that display claim must never be persisted as a built-in adapter
        # identity.  Unknown implementations remain installable only through
        # the generic community boundary.
        authority = HubSourceAuthority(
            adapter=HubSourceKind.UNVERIFIED,
            remote_identifier=bundle.identifier,
            bundle_source=bundle.source,
            trust_level="community",
        )
        authority.validate_bundle(bundle)
        return authority
    if bundle.source != expected_bundle_source:
        raise HubInstallError("Hub adapter returned mismatched source identity")

    # Trust is an immutable property of the concrete adapter plus Fabric's
    # code-owned repository allowlist. Remote index/catalog fields are only
    # discovery hints and can never promote themselves to trusted/official.
    trust_level = "community"
    if kind is HubSourceKind.OFFICIAL_OPTIONAL:
        if bundle.source != "official" or not bundle.identifier.startswith("official/"):
            raise HubInstallError("Official adapter returned mismatched provenance")
        trust_level = "builtin"
    elif kind in _AUTHORITY_REPO_ADAPTERS:
        repo = _authority_repository(kind, bundle.identifier)
        trust_level = (
            "trusted"
            if repo.casefold() in {item.casefold() for item in TRUSTED_REPOS}
            else "community"
        )

    authority = HubSourceAuthority(
        adapter=kind,
        remote_identifier=bundle.identifier,
        bundle_source=bundle.source,
        trust_level=trust_level,
    )
    authority.validate_bundle(bundle)
    return authority


def _bind_scan_to_authority(
    result: ScanResult,
    authority: HubSourceAuthority,
) -> ScanResult:
    result.source = authority.scan_source
    result.trust_level = authority.trust_level
    return result


def scan_skill_with_authority(
    skill_path: Path,
    authority: HubSourceAuthority,
) -> ScanResult:
    """Scan for UI/confirmation using the same typed authority as commit."""

    from tools import skills_guard

    result = skills_guard.scan_skill_attested(
        skill_path,
        source=authority.scan_source,
        max_files=MAX_SKILL_ARCHIVE_FILES,
    ).result
    return _bind_scan_to_authority(result, authority)


def _authority_for_installed_entry(entry: Mapping[str, Any]) -> HubSourceAuthority:
    recorded = entry.get("source_authority")
    if recorded is not None:
        authority = HubSourceAuthority.from_dict(recorded)
        if (
            authority.remote_identifier != entry.get("identifier")
            or authority.bundle_source != entry.get("source")
            or authority.trust_level != entry.get("trust_level")
        ):
            raise HubInstallError("Hub lock provenance fields disagree")
        return authority
    identifier = entry.get("identifier")
    source = entry.get("source")
    if not isinstance(identifier, str) or not identifier:
        raise HubInstallError("Legacy Hub lock identifier is invalid")
    if not isinstance(source, str) or not source:
        raise HubInstallError("Legacy Hub lock source is invalid")
    return HubSourceAuthority(
        adapter=HubSourceKind.UNVERIFIED,
        remote_identifier=identifier,
        bundle_source=source,
        trust_level="community",
    )


def bundle_source_revision(bundle: SkillBundle) -> str:
    """Return the adapter-bound revision token persisted for exact replay."""

    metadata = bundle.metadata if isinstance(bundle.metadata, dict) else {}
    for field in (
        "source_revision",
        "version",
        "latest_version",
        "commit_sha",
        "etag",
    ):
        value = metadata.get(field)
        if isinstance(value, str) and value:
            return value
    return bundle.identifier


def fetch_snapshot_bundle(
    adapter: "SkillSource",
    authority: HubSourceAuthority,
    source_revision: str,
) -> Optional[SkillBundle]:
    """Fetch one snapshot identity without catalog/name re-resolution."""

    try:
        adapter_kind, adapter_bundle_source = _concrete_adapter_identity(adapter)
    except HubInstallError as exc:
        raise HubInstallError("Snapshot adapter authority is not code-owned") from exc
    if (
        adapter_kind is not authority.adapter
        or adapter_bundle_source != authority.bundle_source
    ):
        raise HubInstallError("Snapshot adapter authority changed")
    if not isinstance(source_revision, str) or not source_revision:
        raise HubInstallError("Snapshot source revision is invalid")

    if authority.adapter is HubSourceKind.FABRIC_INDEX:
        if source_revision == authority.remote_identifier:
            raise HubInstallError(
                "Legacy centralized-index snapshot has no exact resolved source"
            )
        bundle = adapter._get_github().fetch(source_revision)  # type: ignore[attr-defined]
        if bundle is None:
            return None
        bundle.source = "fabric-index"
        bundle.identifier = authority.remote_identifier
        bundle.trust_level = "community"
        bundle.metadata["source_revision"] = source_revision
        bundle.metadata["source_name"] = bundle.name
        return bundle

    if authority.adapter is HubSourceKind.SKILLS_SH:
        bundle = adapter.github.fetch(source_revision)  # type: ignore[attr-defined]
        if bundle is None:
            return None
        bundle.source = "skills.sh"
        bundle.identifier = authority.remote_identifier
        bundle.metadata["source_revision"] = source_revision
        bundle.metadata["source_name"] = bundle.name
        return bundle

    if authority.adapter is HubSourceKind.CLAWHUB:
        slug = authority.remote_identifier.split("/")[-1]
        files = adapter._download_zip(slug, source_revision)  # type: ignore[attr-defined]
        if "SKILL.md" not in files:
            version_data = adapter._get_json(  # type: ignore[attr-defined]
                f"{adapter.BASE_URL}/skills/{slug}/versions/{source_revision}"  # type: ignore[attr-defined]
            )
            if isinstance(version_data, dict):
                files = adapter._extract_files(version_data)  # type: ignore[attr-defined]
                nested = version_data.get("version")
                if "SKILL.md" not in files and isinstance(nested, dict):
                    files = adapter._extract_files(nested)  # type: ignore[attr-defined]
        if "SKILL.md" not in files:
            return None
        return SkillBundle(
            name=slug,
            files=files,
            source="clawhub",
            identifier=authority.remote_identifier,
            trust_level="community",
            metadata={
                "source_revision": source_revision,
                "source_name": slug,
            },
        )

    if authority.adapter is HubSourceKind.OFFICIAL_OPTIONAL:
        rel = authority.remote_identifier.removeprefix("official/")
        exact = adapter._optional_dir.joinpath(*rel.split("/"))  # type: ignore[attr-defined]
        if not exact.is_dir():
            return None

    bundle = adapter.fetch(authority.remote_identifier)
    if bundle is None or bundle.identifier != authority.remote_identifier:
        return None
    if bundle_source_revision(bundle) != source_revision:
        return None
    return bundle


class _BoundedBundleBuilder:
    """Admit each bundle file before retaining it in memory."""

    def __init__(self) -> None:
        self.files: Dict[str, Union[str, bytes]] = {}
        self.total_bytes = 0

    def add(self, path: str, value: Union[str, bytes]) -> None:
        safe_path = _validate_bundle_rel_path(path)
        encoded = value if isinstance(value, bytes) else value.encode("utf-8")
        if len(self.files) >= MAX_SKILL_ARCHIVE_FILES and safe_path not in self.files:
            raise SkillPayloadTooLarge("skill bundle contains too many files")
        if len(encoded) > MAX_SKILL_FILE_BYTES:
            raise SkillPayloadTooLarge(
                f"skill file {safe_path!r} exceeds {MAX_SKILL_FILE_BYTES} bytes"
            )
        previous = self.files.get(safe_path)
        previous_size = 0
        if previous is not None:
            previous_size = len(
                previous if isinstance(previous, bytes) else previous.encode("utf-8")
            )
        prospective = self.total_bytes - previous_size + len(encoded)
        if prospective > MAX_SKILL_TOTAL_BYTES:
            raise SkillPayloadTooLarge(
                f"skill tree exceeds {MAX_SKILL_TOTAL_BYTES} bytes"
            )
        self.files[safe_path] = value
        self.total_bytes = prospective

    def text_files(self) -> Dict[str, str]:
        return {
            path: value for path, value in self.files.items() if isinstance(value, str)
        }


def _normalize_bundle_path(
    path_value: str, *, field_name: str, allow_nested: bool
) -> str:
    """Normalize and validate bundle-controlled paths before touching disk."""
    return normalize_relative_path(
        path_value,
        field=field_name,
        allow_nested=allow_nested,
    )


def _validate_skill_name(name: str) -> str:
    return validate_skill_name(name)


def _validate_install_parent_path(category: str) -> str:
    return validate_install_parent_path(category)


def _normalize_lock_install_path(install_path: str, skill_name: str) -> str:
    """Validate a skill install path before it touches the lock file or disk.

    Lock-file ``install_path`` entries are the source-of-truth for where
    ``uninstall_skill`` will call ``shutil.rmtree``. A poisoned or buggy
    entry — empty string, ``"."``, an absolute path, ``../..`` traversal,
    or anything whose final component doesn't match the skill name — would
    let ``rmtree`` wipe either the entire ``skills/`` tree or content
    outside it.

    Enforce that ``install_path`` ends with ``<skill_name>``. Nested
    official optional skills may legitimately install below paths such as
    ``mlops/training/<skill_name>``; traversal, absolute paths, empty paths,
    and mismatched final components are still rejected.
    """
    return normalize_lock_install_path(install_path, skill_name)


def _is_path_redirect(path: Path) -> bool:
    """True when ``path`` is a symlink or (on Windows) a directory junction.

    Either form lets an attacker who can write into the ``skills/`` tree
    redirect a subsequent ``rmtree`` to content outside it. ``is_junction``
    only exists on Python 3.12+ Windows; gate with ``hasattr``.
    """
    return is_path_redirect(path)


def _resolve_lock_install_path(install_path: str, skill_name: str) -> Path:
    """Resolve a lock-file install path without allowing escapes from ``SKILLS_DIR``.

    Two layers of defence on top of the existing ``is_relative_to`` check
    that's been on main:

    1. Walk the path component-by-component and refuse if any intermediate
       component is a symlink/junction (a path resolution that follows a
       symlink to outside skills/ would otherwise be hidden by Path.resolve).
    2. After resolve(), reject not just escape-out but also ``resolved == SKILLS_DIR``
       — an empty/``"."``/``""`` install_path resolves to the skills root itself,
       and ``rmtree(SKILLS_DIR)`` would wipe every installed skill.
    """
    return resolve_skill_install_path(
        _skills_dir(),
        install_path,
        skill_name,
        must_exist=False,
    )


def _bound_install_path(install_path: str, skill_name: str) -> Path:
    """Build a lexical install path for descriptor-bound transaction access."""

    normalized = _normalize_lock_install_path(install_path, skill_name)
    return _skills_dir().joinpath(*normalized.split("/"))


class SkillPayloadTooLarge(ValueError):
    """A remote or expanded skill payload exceeded an admission bound."""


@dataclass(frozen=True)
class _BoundedHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> Any:
        _preflight_json_bytes(self.content)
        try:
            parsed = json.loads(self.content)
        except RecursionError as exc:
            raise SkillPayloadTooLarge(
                "JSON payload exceeds the nesting limit"
            ) from exc
        return _validate_bounded_json_graph(parsed)


def _bounded_response_text(response: _BoundedHttpResponse) -> Optional[str]:
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _read_bounded_regular_file(
    path: Path,
    *,
    max_bytes: int,
    require_unique: bool = False,
) -> tuple[bytes, os.stat_result]:
    """Read one non-redirect regular file with a remaining+sentinel budget."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    parent_fd: int | None = None
    if (
        os.name != "nt"
        and _ACTIVE_HUB_MUTATION.get() is not None
        and _hub_relative_parts(path.parent) is not None
    ):
        parent_fd = _open_hub_directory(path.parent, create=False)
        descriptor = os.open(path.name, flags, dir_fd=parent_fd)
    else:
        descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"not a regular file: {path}")
        if require_unique and opened.st_nlink != 1:
            raise ValueError(f"file must be uniquely linked: {path}")
        if opened.st_size > max_bytes:
            raise SkillPayloadTooLarge(f"file exceeds {max_bytes} bytes: {path}")
        chunks: list[bytes] = []
        received = 0
        while True:
            read_size = min(64 * 1024, max(1, max_bytes - received + 1))
            chunk = os.read(descriptor, read_size)
            if not chunk:
                break
            received += len(chunk)
            if received > max_bytes:
                raise SkillPayloadTooLarge(f"file exceeds {max_bytes} bytes: {path}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if require_unique and after.st_nlink != 1:
            raise ValueError(f"file link count changed while reading: {path}")
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            getattr(opened, "st_mtime_ns", None),
            getattr(opened, "st_ctime_ns", None),
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            getattr(after, "st_mtime_ns", None),
            getattr(after, "st_ctime_ns", None),
        ):
            raise ValueError(f"file changed while reading: {path}")
        if parent_fd is not None:
            named = os.stat(
                path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(named.st_mode)
                or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)
                or (require_unique and named.st_nlink != 1)
            ):
                raise ValueError(f"file pathname changed while reading: {path}")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)
        if parent_fd is not None:
            os.close(parent_fd)


def _bounded_http_get(
    url: str,
    *,
    timeout: int,
    max_bytes: int,
    follow_redirects: bool,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    max_wire_bytes: int | None = None,
) -> _BoundedHttpResponse:
    """Stream an identity response with separate wire/decoded admission caps.

    ``httpx.iter_bytes()`` may inflate a tiny gzip body into one enormous
    allocation before yielding it. Request identity, reject an encoded response,
    and read raw chunks bounded by the remaining budget instead.
    """

    wire_limit = max_bytes if max_wire_bytes is None else max_wire_bytes
    request_headers = dict(headers or {})
    request_headers["Accept-Encoding"] = "identity"

    with httpx.stream(
        "GET",
        url,
        timeout=timeout,
        follow_redirects=follow_redirects,
        params=params,
        headers=request_headers,
    ) as response:
        content_encoding = response.headers.get("content-encoding", "identity")
        if content_encoding.strip().lower() not in {"", "identity"}:
            raise SkillPayloadTooLarge(
                "encoded HTTP payloads are not accepted by the bounded reader"
            )
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = -1
            if declared > wire_limit:
                raise SkillPayloadTooLarge(
                    f"remote wire payload exceeds {wire_limit} bytes"
                )
        chunks: List[bytes] = []
        received = 0
        raw_iterator = getattr(response, "iter_raw", None)
        if raw_iterator is None:
            iterator = response.iter_bytes()
        else:
            iterator = raw_iterator(chunk_size=64 * 1024)
        for chunk in iterator:
            received += len(chunk)
            if received > wire_limit:
                raise SkillPayloadTooLarge(
                    f"remote wire payload exceeds {wire_limit} bytes"
                )
            if received > max_bytes:
                raise SkillPayloadTooLarge(f"remote payload exceeds {max_bytes} bytes")
            chunks.append(chunk)
        return _BoundedHttpResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=b"".join(chunks),
        )


def _validate_bounded_json_graph(
    value: Any,
    *,
    max_depth: int = MAX_HUB_JSON_DEPTH,
    max_items: int = MAX_HUB_JSON_ITEMS,
    max_string_bytes: int = MAX_HUB_STRING_BYTES,
) -> Any:
    """Bound decoded JSON structure before adapters retain or traverse it."""

    remaining = max_items
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            raise SkillPayloadTooLarge("JSON payload exceeds the nesting limit")
        remaining -= 1
        if remaining < 0:
            raise SkillPayloadTooLarge("JSON payload contains too many values")
        if isinstance(current, str):
            if len(current.encode("utf-8")) > max_string_bytes:
                raise SkillPayloadTooLarge("JSON string exceeds the byte limit")
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object key must be a string")
                if len(key.encode("utf-8")) > max_string_bytes:
                    raise SkillPayloadTooLarge("JSON key exceeds the byte limit")
                stack.append((item, depth + 1))
    return value


def _preflight_json_bytes(payload: bytes) -> None:
    """Reject pathological JSON shape before the decoder allocates objects.

    This intentionally performs only admission accounting, leaving syntax to
    ``json.loads``. Raw string/scalar spans, nesting, and value/key count are
    bounded in one pass with constant auxiliary memory.
    """

    depth = 0
    items = 0
    in_string = False
    escaped = False
    string_bytes = 0
    in_scalar = False
    scalar_bytes = 0

    for byte in payload:
        if in_string:
            string_bytes += 1
            if string_bytes > MAX_HUB_STRING_BYTES * 6:
                # A Unicode escape may use six raw bytes for one character;
                # anything beyond this cannot decode within the string cap.
                raise SkillPayloadTooLarge("JSON string exceeds the byte limit")
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
                items += 1
                if items > MAX_HUB_JSON_ITEMS:
                    raise SkillPayloadTooLarge("JSON payload contains too many values")
            continue

        if byte == 0x22:
            in_string = True
            escaped = False
            string_bytes = 0
            in_scalar = False
            continue
        if byte in (0x7B, 0x5B):  # { [
            depth += 1
            if depth > MAX_HUB_JSON_DEPTH:
                raise SkillPayloadTooLarge("JSON payload exceeds the nesting limit")
            items += 1
            if items > MAX_HUB_JSON_ITEMS:
                raise SkillPayloadTooLarge("JSON payload contains too many values")
            in_scalar = False
            continue
        if byte in (0x7D, 0x5D):  # } ]
            depth -= 1
            if depth < 0:
                break  # syntax error is reported by json.loads
            in_scalar = False
            continue
        if byte in (0x2C, 0x3A, 0x20, 0x09, 0x0A, 0x0D):
            in_scalar = False
            continue
        if not in_scalar:
            in_scalar = True
            scalar_bytes = 0
            items += 1
            if items > MAX_HUB_JSON_ITEMS:
                raise SkillPayloadTooLarge("JSON payload contains too many values")
        scalar_bytes += 1
        if scalar_bytes > MAX_HUB_STRING_BYTES:
            raise SkillPayloadTooLarge("JSON scalar exceeds the byte limit")


def _bounded_json(response: _BoundedHttpResponse) -> Any:
    _preflight_json_bytes(response.content)
    try:
        parsed = json.loads(response.content)
    except RecursionError as exc:
        raise SkillPayloadTooLarge("JSON payload exceeds the nesting limit") from exc
    return _validate_bounded_json_graph(parsed)


def _read_bounded_json_file(
    path: Path,
    *,
    max_bytes: int = MAX_HUB_CATALOG_BYTES,
    require_unique: bool = False,
) -> tuple[Any, os.stat_result]:
    payload, state = _read_bounded_regular_file(
        path,
        max_bytes=max_bytes,
        require_unique=require_unique,
    )
    _preflight_json_bytes(payload)
    try:
        parsed = json.loads(payload)
    except RecursionError as exc:
        raise SkillPayloadTooLarge("JSON payload exceeds the nesting limit") from exc
    return _validate_bounded_json_graph(parsed), state


def _preflight_zip_directory(payload: bytes) -> int:
    """Validate the complete central directory before ``ZipFile`` allocates.

    The final EOCD is not trusted as a count oracle: every central-directory
    header is walked under the 1,000-entry cap, and competing EOCD/Zip64
    structures are rejected as ambiguous.
    """

    eocd_signature = b"PK\x05\x06"
    search_start = max(0, len(payload) - (65_535 + 22))
    offsets: list[int] = []
    cursor = search_start
    while True:
        cursor = payload.find(eocd_signature, cursor)
        if cursor < 0:
            break
        offsets.append(cursor)
        cursor += 1

    terminal: list[int] = []
    for offset in offsets:
        if offset + 22 > len(payload):
            continue
        comment_size = struct.unpack_from("<H", payload, offset + 20)[0]
        if offset + 22 + comment_size == len(payload):
            terminal.append(offset)
    if len(terminal) != 1:
        raise ValueError("ZIP end-of-central-directory structure is ambiguous")
    eocd_offset = terminal[0]
    (
        _signature,
        disk_number,
        directory_disk,
        entries_on_disk,
        entries_total,
        directory_size,
        directory_offset,
        comment_size,
    ) = struct.unpack_from("<4s4H2LH", payload, eocd_offset)
    if disk_number != 0 or directory_disk != 0 or entries_on_disk != entries_total:
        raise ValueError("multi-disk ZIP archives are not supported")

    central_end = eocd_offset
    if (
        entries_on_disk == 0xFFFF
        or entries_total == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        locator_offset = eocd_offset - 20
        if (
            locator_offset < 0
            or payload[locator_offset : locator_offset + 4] != b"PK\x06\x07"
        ):
            raise ValueError("ZIP64 locator is missing")
        _locator, zip64_disk, zip64_offset, disk_count = struct.unpack_from(
            "<4sLQL",
            payload,
            locator_offset,
        )
        if zip64_disk != 0 or disk_count != 1 or zip64_offset + 56 > len(payload):
            raise ValueError("ZIP64 locator is invalid")
        if payload[zip64_offset : zip64_offset + 4] != b"PK\x06\x06":
            raise ValueError("ZIP64 end-of-central-directory record is missing")
        record_size = struct.unpack_from("<Q", payload, zip64_offset + 4)[0]
        if record_size < 44 or zip64_offset + 12 + record_size != locator_offset:
            raise ValueError("ZIP64 end-of-central-directory bounds are invalid")
        if payload.count(b"PK\x06\x07", search_start, eocd_offset) != 1:
            raise ValueError("ZIP64 locator structure is ambiguous")
        if payload.count(b"PK\x06\x06", search_start, locator_offset) != 1:
            raise ValueError("ZIP64 end-of-central-directory structure is ambiguous")
        entries_on_disk = struct.unpack_from("<Q", payload, zip64_offset + 24)[0]
        entries_total = struct.unpack_from("<Q", payload, zip64_offset + 32)[0]
        directory_size = struct.unpack_from("<Q", payload, zip64_offset + 40)[0]
        directory_offset = struct.unpack_from("<Q", payload, zip64_offset + 48)[0]
        if entries_on_disk != entries_total:
            raise ValueError("multi-disk ZIP64 archives are not supported")
        central_end = zip64_offset

    if entries_total > MAX_SKILL_ARCHIVE_FILES:
        raise SkillPayloadTooLarge("skill archive contains too many files")
    if directory_size > MAX_SKILL_HTTP_BYTES:
        raise SkillPayloadTooLarge("ZIP central directory exceeds the byte cap")
    if directory_offset + directory_size != central_end:
        raise ValueError("ZIP central directory bounds are invalid")

    # A second structurally plausible EOCD is ambiguous even when later bytes
    # make it non-terminal (the forged-last-EOCD attack).
    for offset in offsets:
        if offset == eocd_offset or offset + 22 > len(payload):
            continue
        try:
            fields = struct.unpack_from("<4s4H2LH", payload, offset)
        except struct.error:
            continue
        prior_entries = fields[4]
        prior_size = fields[5]
        prior_offset = fields[6]
        prior_comment = fields[7]
        if (
            fields[1] == 0
            and fields[2] == 0
            and fields[3] == prior_entries
            and offset + 22 + prior_comment <= len(payload)
            and prior_offset + prior_size <= offset
        ):
            raise ValueError("ZIP contains multiple plausible EOCD records")

    actual_entries = 0
    cursor = int(directory_offset)
    directory_limit = int(directory_offset + directory_size)
    while cursor < directory_limit:
        if cursor + 46 > directory_limit:
            raise ValueError("ZIP central directory entry is truncated")
        if payload[cursor : cursor + 4] != b"PK\x01\x02":
            raise ValueError("ZIP central directory signature is invalid")
        name_size, extra_size, member_comment_size, start_disk = struct.unpack_from(
            "<4H",
            payload,
            cursor + 28,
        )
        if start_disk != 0:
            raise ValueError("multi-disk ZIP entries are not supported")
        entry_size = 46 + name_size + extra_size + member_comment_size
        if entry_size < 46 or cursor + entry_size > directory_limit:
            raise ValueError("ZIP central directory entry bounds are invalid")
        actual_entries += 1
        if actual_entries > MAX_SKILL_ARCHIVE_FILES:
            raise SkillPayloadTooLarge("skill archive contains too many files")
        cursor += entry_size
    if cursor != directory_limit or actual_entries != entries_total:
        raise ValueError("ZIP entry count disagrees with its central directory")
    return int(entries_total)


def _guarded_http_get(
    url: str,
    *,
    timeout: int = 20,
    max_bytes: int = MAX_SKILL_HTTP_BYTES,
) -> Optional[_BoundedHttpResponse]:
    """Fetch a URL with SSRF and redirect-target validation."""
    current_url = url

    for _ in range(_MAX_SKILL_FETCH_REDIRECTS + 1):
        if not is_safe_url(current_url):
            logger.warning("Blocked unsafe Skills Hub URL: %s", current_url)
            return None

        blocked = check_website_access(current_url)
        if blocked:
            logger.info(
                "Blocked Skills Hub fetch for %s by rule %s",
                blocked["host"],
                blocked["rule"],
            )
            return None

        try:
            resp = _bounded_http_get(
                current_url,
                timeout=timeout,
                max_bytes=max_bytes,
                follow_redirects=False,
            )
        except (httpx.HTTPError, SkillPayloadTooLarge) as exc:
            logger.debug("Skills Hub fetch failed for %s: %s", current_url, exc)
            return None

        if resp.status_code in _REDIRECT_STATUS_CODES:
            location = getattr(resp, "headers", {}).get("location")
            if not location:
                return None
            current_url = urljoin(current_url, location)
            continue

        return resp

    logger.warning("Skills Hub fetch exceeded redirect limit for %s", url)
    return None


def _validate_bundle_rel_path(rel_path: str) -> str:
    return _normalize_bundle_path(
        rel_path, field_name="bundle file path", allow_nested=True
    )


def _validated_effective_bundle_files(
    bundle: SkillBundle,
) -> Dict[str, Union[str, bytes]]:
    """Normalize once, then apply the scanner's shared effective-tree policy."""

    raw_paths = tuple(bundle.files)
    if any(path != path.strip() for path in raw_paths):
        raise UnsafePathError(
            "Unsafe bundle file path: outer whitespace is not allowed"
        )
    portable_paths = validate_portable_tree_paths(
        raw_paths,
        field="bundle file path",
    )
    validated: Dict[str, Union[str, bytes]] = {}
    for raw_path, safe_rel_path in zip(raw_paths, portable_paths):
        validated[safe_rel_path] = bundle.files[raw_path]
    effective = effective_skill_files(validated)
    if len(effective) > MAX_SKILL_ARCHIVE_FILES:
        raise SkillPayloadTooLarge("skill bundle contains too many files")
    total_bytes = 0
    for path, value in effective.items():
        encoded = value if isinstance(value, bytes) else value.encode("utf-8")
        if len(encoded) > MAX_SKILL_FILE_BYTES:
            raise SkillPayloadTooLarge(
                f"skill file {path!r} exceeds {MAX_SKILL_FILE_BYTES} bytes"
            )
        total_bytes += len(encoded)
        if total_bytes > MAX_SKILL_TOTAL_BYTES:
            raise SkillPayloadTooLarge(
                f"skill tree exceeds {MAX_SKILL_TOTAL_BYTES} bytes"
            )
    return effective


# ---------------------------------------------------------------------------
# GitHub Authentication
# ---------------------------------------------------------------------------


class GitHubAuth:
    """
    GitHub API authentication. Tries methods in priority order:
      1. GITHUB_TOKEN / GH_TOKEN env var (PAT — the default)
      2. `gh auth token` subprocess (if gh CLI is installed)
      3. GitHub App JWT + installation token (if app credentials configured)
      4. Unauthenticated (60 req/hr, public repos only)
    """

    def __init__(self):
        self._cached_token: Optional[str] = None
        self._cached_method: Optional[str] = None
        self._app_token_expiry: float = 0

    def get_headers(self) -> Dict[str, str]:
        """Return authorization headers for GitHub API requests."""
        token = self._resolve_token()
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    def is_authenticated(self) -> bool:
        return self._resolve_token() is not None

    def auth_method(self) -> str:
        """Return which auth method is active: 'pat', 'gh-cli', 'github-app', or 'anonymous'."""
        self._resolve_token()
        return self._cached_method or "anonymous"

    def _resolve_token(self) -> Optional[str]:
        # Return cached token if still valid
        if self._cached_token:
            if (
                self._cached_method != "github-app"
                or time.time() < self._app_token_expiry
            ):
                return self._cached_token

        # 1. Environment variable
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            self._cached_token = token
            self._cached_method = "pat"
            return token

        # 2. gh CLI
        token = self._try_gh_cli()
        if token:
            self._cached_token = token
            self._cached_method = "gh-cli"
            return token

        # 3. GitHub App
        token = self._try_github_app()
        if token:
            self._cached_token = token
            self._cached_method = "github-app"
            self._app_token_expiry = time.time() + 3500  # ~58 min (tokens last 1 hour)
            return token

        self._cached_method = "anonymous"
        return None

    def _try_gh_cli(self) -> Optional[str]:
        """Try to get a token from the gh CLI."""
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5,
                stdin=subprocess.DEVNULL,
                creationflags=windows_hide_flags(),
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.debug("gh CLI token lookup failed: %s", e)
        return None

    def _try_github_app(self) -> Optional[str]:
        """Try GitHub App JWT authentication if credentials are configured."""
        app_id = os.environ.get("GITHUB_APP_ID")
        key_path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
        installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")

        if not all([app_id, key_path, installation_id]):
            return None

        try:
            import jwt  # PyJWT
        except ImportError:
            logger.debug("PyJWT not installed, skipping GitHub App auth")
            return None

        try:
            key_file = Path(key_path)
            if not key_file.exists():
                return None
            private_key = key_file.read_text(encoding="utf-8")

            now = int(time.time())
            payload = {
                "iat": now - 60,
                "exp": now + (10 * 60),
                "iss": app_id,
            }
            encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

            resp = httpx.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {encoded_jwt}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=10,
            )
            if resp.status_code == 201:
                return resp.json().get("token")
        except Exception as e:
            logger.debug(f"GitHub App auth failed: {e}")

        return None


# ---------------------------------------------------------------------------
# Source adapter interface
# ---------------------------------------------------------------------------


class SkillSource(ABC):
    """Abstract base for all skill registry adapters."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        """Search for skills matching a query string."""
        ...

    @abstractmethod
    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        """Download a skill bundle by identifier."""
        ...

    @abstractmethod
    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        """Fetch metadata for a skill without downloading all files."""
        ...

    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this source (e.g. 'github', 'clawhub')."""
        ...

    def trust_level_for(self, identifier: str) -> str:
        """Determine trust level for a skill from this source."""
        return "community"


# ---------------------------------------------------------------------------
# GitHub source adapter
# ---------------------------------------------------------------------------

# Map a GitHub tap repo (owner/repo) to the human-facing provider label used
# in the docs-site catalog (website/scripts/extract-skills.py::GITHUB_TAP_LABELS).
# The runtime index collapses every GitHub tap into source="github"; stamping
# this provider label onto each skill's ``extra`` keeps the per-tap identity
# (NVIDIA / OpenAI / Anthropic / HuggingFace / gstack / ...) searchable and
# filterable at the CLI without disturbing the source="github" dedup / floor /
# index-skip logic that keys off the bare source id.
GITHUB_TAP_PROVIDERS = {
    "openai/skills": "OpenAI",
    "anthropics/skills": "Anthropic",
    "huggingface/skills": "HuggingFace",
    "nvidia/skills": "NVIDIA",
    "voltagent/awesome-agent-skills": "VoltAgent",
    "garrytan/gstack": "gstack",
    "minimax-ai/cli": "MiniMax",
    "obra/superpowers": "Superpowers",
    "everyinc/compound-engineering-plugin": "Every",
    "coreyhaines31/marketingskills": "MarketingSkills",
    "shawnpang/startup-founder-skills": "FounderSkills",
    "phuryn/pm-skills": "PMSkills",
    "leonxlnx/taste-skill": "Taste",
    "pbakaus/impeccable": "Impeccable",
    "multica-ai/andrej-karpathy-skills": "Karpathy",
    "addyosmani/agent-skills": "AddyOsmani",
}


def github_provider_for(repo: str) -> Optional[str]:
    """Return the provider label for a GitHub tap repo, or None.

    ``repo`` is ``owner/repo``; matched case-insensitively so ``NVIDIA/skills``
    and ``nvidia/skills`` both resolve to ``"NVIDIA"``.
    """
    if not repo:
        return None
    return GITHUB_TAP_PROVIDERS.get(repo.strip().lower())


# Lowercased set of accepted ``--source`` provider filters. These are not real
# source ids — they narrow the merged results to GitHub-tap skills carrying the
# matching ``extra.provider`` label (see ``_filter_results_by_provider``).
_PROVIDER_FILTER_VALUES = frozenset(v.lower() for v in GITHUB_TAP_PROVIDERS.values())


def _filter_results_by_provider(
    results: List["SkillMeta"], provider: str
) -> List["SkillMeta"]:
    """Keep only results whose ``extra.provider`` matches ``provider``.

    An explicit provider filter (e.g. ``--source nvidia``) means "show me that
    provider's skills" — so it narrows to exactly those, without injecting the
    official catalog the unfiltered browse/search would lead with.
    """
    want = provider.strip().lower()
    return [
        r for r in results if str((r.extra or {}).get("provider", "")).lower() == want
    ]


class GitHubSource(SkillSource):
    """Fetch skills from GitHub repos via the Contents API."""

    DEFAULT_TAPS = [
        # NOTE: openai/skills moved its content into skills/.curated/ (and
        # skills/.system/ for system-level skills). _list_skills_in_repo
        # skips directories starting with "." or "_", so we point both
        # entries at the inner paths directly.
        {"repo": "openai/skills", "path": "skills/.curated/"},
        {"repo": "openai/skills", "path": "skills/.system/"},
        {"repo": "anthropics/skills", "path": "skills/"},
        {"repo": "huggingface/skills", "path": "skills/"},
        # NVIDIA/skills: NVIDIA-verified skills for CUDA-X, AIQ, cuOpt,
        # cuPyNumeric, DeepStream, NeMo, NemoClaw, etc. Each skill ships
        # alongside a signed `skill.oms.sig`, an OMS-signed `skill-card.md`
        # (governance card), and an `evals/` directory — synced daily from
        # the NVIDIA product repos. Treated as `trusted` (see
        # `tools/skills_guard.py::TRUSTED_REPOS`). Sample layout:
        # https://github.com/NVIDIA/skills/tree/main/skills
        {"repo": "NVIDIA/skills", "path": "skills/"},
        {"repo": "garrytan/gstack", "path": ""},
        # Curated community skill packs from the Skills Ecosystem Directory
        # (website/docs/reference/skills-ecosystem-directory.md). All are
        # community trust level — installs still pass the skills guard scan
        # and quarantine. Paths verified against each repo's live tree; the
        # full (much larger) curated catalog is crawled at index-build time
        # by scripts/build_skills_index.py CURATED_TAPS instead of here, so
        # runtime searches stay cheap.
        {"repo": "obra/superpowers", "path": "skills/"},
        {"repo": "EveryInc/compound-engineering-plugin", "path": "skills/"},
        {"repo": "coreyhaines31/marketingskills", "path": "skills/"},
        {"repo": "shawnpang/startup-founder-skills", "path": "skills/"},
        {"repo": "phuryn/pm-skills", "path": "pm-product-discovery/skills/"},
        {"repo": "phuryn/pm-skills", "path": "pm-execution/skills/"},
        {"repo": "leonxlnx/taste-skill", "path": "skills/"},
        {"repo": "pbakaus/impeccable", "path": ".claude/skills/"},
        {"repo": "multica-ai/andrej-karpathy-skills", "path": "skills/"},
        {"repo": "addyosmani/agent-skills", "path": "skills/"},
    ]

    def __init__(self, auth: GitHubAuth, extra_taps: Optional[List[Dict]] = None):
        self.auth = auth
        self.taps = list(self.DEFAULT_TAPS)
        if extra_taps:
            self.taps.extend(extra_taps)
        # Per-instance cache: repo -> (default_branch, tree_entries)
        # Survives within a single search/install flow, avoiding redundant API calls.
        self._tree_cache: Dict[str, Tuple[str, List[dict]]] = {}
        # Per-repo cache of the optional skills.sh.json grouping sidecar,
        # mapping skill_name -> human-readable grouping title. ``None`` means
        # "fetched, no sidecar"; a missing key means "not fetched yet".
        self._skillsh_groupings: Dict[str, Optional[Dict[str, str]]] = {}
        # Set when GitHub returns 403 with rate limit exhausted
        self._rate_limited: bool = False

    def source_id(self) -> str:
        return "github"

    @property
    def is_rate_limited(self) -> bool:
        """Whether GitHub API rate limit was hit during operations."""
        return self._rate_limited

    def trust_level_for(self, identifier: str) -> str:
        # identifier format: "owner/repo/path/to/skill"
        parts = identifier.split("/", 2)
        if len(parts) >= 2:
            repo = f"{parts[0]}/{parts[1]}"
            if repo in TRUSTED_REPOS:
                return "trusted"
        return "community"

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        """Search all taps for skills matching the query."""
        results: List[SkillMeta] = []
        query_lower = query.lower()

        for tap in self.taps:
            try:
                skills = self._list_skills_in_repo(tap["repo"], tap.get("path", ""))
                for skill in skills:
                    searchable = f"{skill.name} {skill.description} {' '.join(skill.tags)}".lower()
                    if query_lower in searchable:
                        results.append(skill)
            except Exception as e:
                logger.debug(f"Failed to search {tap['repo']}: {e}")
                continue

        # Deduplicate by identifier, preferring higher trust levels.
        # identifier is unique per skill; name is not (two configured taps can
        # publish skills with the same name but different identifiers).
        _trust_rank = {"builtin": 2, "trusted": 1, "community": 0}
        seen = {}
        for r in results:
            if r.identifier not in seen:
                seen[r.identifier] = r
            elif _trust_rank.get(r.trust_level, 0) > _trust_rank.get(
                seen[r.identifier].trust_level, 0
            ):
                seen[r.identifier] = r
        results = list(seen.values())

        return results[:limit]

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        """
        Download a skill from GitHub.
        identifier format: "owner/repo/path/to/skill-dir"
        """
        parts = identifier.split("/", 2)
        if len(parts) < 3:
            return None

        repo = f"{parts[0]}/{parts[1]}"
        skill_path = parts[2]

        files = self._download_directory(repo, skill_path)
        if not files or "SKILL.md" not in files:
            return None

        skill_name = skill_path.rstrip("/").split("/")[-1]
        trust = self.trust_level_for(identifier)

        return SkillBundle(
            name=skill_name,
            files=files,
            source="github",
            identifier=identifier,
            trust_level=trust,
        )

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        """Fetch just the SKILL.md metadata for preview."""
        parts = identifier.split("/", 2)
        if len(parts) < 3:
            return None

        repo = f"{parts[0]}/{parts[1]}"
        skill_path = parts[2].rstrip("/")
        skill_md_path = f"{skill_path}/SKILL.md"

        content = self._fetch_file_content(repo, skill_md_path)
        if not content:
            return None

        fm = self._parse_frontmatter_quick(content)
        skill_name = fm.get("name", skill_path.split("/")[-1])
        description = fm.get("description", "")

        tags = extract_skill_metadata(fm).get("tags", [])
        if not tags:
            raw_tags = fm.get("tags", [])
            tags = raw_tags if isinstance(raw_tags, list) else []

        provider = github_provider_for(repo)
        extra: Dict[str, Any] = {}
        if provider:
            extra["provider"] = provider

        return SkillMeta(
            name=skill_name,
            description=str(description),
            source="github",
            identifier=identifier,
            trust_level=self.trust_level_for(identifier),
            repo=repo,
            path=skill_path,
            tags=[str(t) for t in tags],
            extra=extra,
        )

    # -- Internal helpers --

    def _list_skills_in_repo(self, repo: str, path: str) -> List[SkillMeta]:
        """List skill directories in a GitHub repo path, using cached index."""
        cache_key = f"{repo}_{path}".replace("/", "_").replace(" ", "_")
        cached = self._read_cache(cache_key)
        if cached is not None:
            return [SkillMeta(**s) for s in cached]

        url = f"https://api.github.com/repos/{repo}/contents/{path.rstrip('/')}"
        resp = self._github_get(url)
        if resp is None or resp.status_code != 200:
            return []

        try:
            entries = _bounded_json(resp)
        except (json.JSONDecodeError, SkillPayloadTooLarge, ValueError):
            return []
        if not isinstance(entries, list):
            return []

        skills: List[SkillMeta] = []
        groupings = self._get_skillsh_groupings(repo)
        for entry in entries:
            if entry.get("type") != "dir":
                continue

            dir_name = entry["name"]
            if dir_name.startswith((".", "_")):
                continue

            prefix = path.rstrip("/")
            skill_identifier = (
                f"{repo}/{prefix}/{dir_name}" if prefix else f"{repo}/{dir_name}"
            )
            meta = self.inspect(skill_identifier)
            if meta:
                if groupings:
                    category = groupings.get(meta.name) or groupings.get(dir_name)
                    if category:
                        meta.extra["category"] = category
                skills.append(meta)

        # Cache the results
        self._write_cache(cache_key, [self._meta_to_dict(s) for s in skills])
        return skills

    # -- Repo tree cache (avoids redundant API calls) --

    def _get_repo_tree(self, repo: str) -> Optional[Tuple[str, List[dict]]]:
        """Get cached or fresh repo tree.

        Returns ``(default_branch, tree_entries)`` or ``None``.
        A single install can call ``_download_directory_via_tree`` and
        ``_find_skill_in_repo_tree`` multiple times for the same repo — this
        cache eliminates the redundant ``GET /repos/{repo}`` +
        ``GET /repos/{repo}/git/trees/{branch}`` round-trips (previously up to
        6 duplicated pairs per install, consuming ~12 of the 60/hr
        unauthenticated rate limit for nothing).
        """
        if repo in self._tree_cache:
            return self._tree_cache[repo]

        headers = self.auth.get_headers()

        # Resolve default branch
        try:
            resp = self._github_get(
                f"https://api.github.com/repos/{repo}",
                headers=headers,
                timeout=15,
            )
            if resp is None or resp.status_code != 200:
                if resp is None:
                    return None
                self._check_rate_limit_response(resp)
                return None
            repo_data = _bounded_json(resp)
            if not isinstance(repo_data, dict):
                return None
            default_branch = repo_data.get("default_branch", "main")
            if not isinstance(default_branch, str) or not default_branch:
                return None
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            return None

        # Fetch recursive tree
        try:
            resp = self._github_get(
                f"https://api.github.com/repos/{repo}/git/trees/{default_branch}",
                params={"recursive": "1"},
                headers=headers,
                timeout=30,
            )
            if resp is None or resp.status_code != 200:
                if resp is None:
                    return None
                self._check_rate_limit_response(resp)
                return None
            tree_data = _bounded_json(resp)
            if not isinstance(tree_data, dict):
                return None
            if tree_data.get("truncated"):
                logger.debug("Git tree truncated for %s, cannot cache", repo)
                return None
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            return None

        entries = tree_data.get("tree", [])
        if not isinstance(entries, list):
            return None
        self._tree_cache[repo] = (default_branch, entries)
        return (default_branch, entries)

    def _check_rate_limit_response(self, resp: "httpx.Response") -> None:
        """Flag the instance as rate-limited when GitHub returns 403 + exhausted quota."""
        if resp.status_code in (403, 429):
            remaining = resp.headers.get("X-RateLimit-Remaining", "")
            if remaining == "0" or resp.status_code == 429:
                self._rate_limited = True
                logger.warning(
                    "GitHub API rate limit exhausted (unauthenticated: 60 req/hr). "
                    "Set GITHUB_TOKEN or install the gh CLI to raise the limit to 5,000/hr."
                )

    def _github_get(
        self,
        url: str,
        *,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> Optional[_BoundedHttpResponse]:
        """GET against the GitHub API with retry/backoff on transient failures.

        Returns the final ``httpx.Response`` (caller inspects status) or
        ``None`` when every attempt raised a transport error.

        Retries on:
          - 403/429 with ``X-RateLimit-Remaining: 0`` — waits until the
            reset time (capped) when the header is present, else exponential
            backoff. This is the all-GitHub-tap-collapse case: a single
            shared rate limit zeroes github + claude-marketplace + well-known
            at once during the index build.
          - 5xx and connection/timeout errors — exponential backoff.

        On terminal rate-limit exhaustion the instance is flagged via
        ``_check_rate_limit_response`` so the build can fail loud instead of
        silently shipping an index with the GitHub sources dropped to zero.
        """
        hdrs = headers if headers is not None else self.auth.get_headers()
        backoff = 1.0
        last_resp: Optional[_BoundedHttpResponse] = None
        for attempt in range(max_retries):
            try:
                resp = _bounded_http_get(
                    url,
                    params=params,
                    headers=hdrs,
                    timeout=timeout,
                    max_bytes=MAX_SKILL_METADATA_BYTES,
                    follow_redirects=True,
                )
            except (httpx.HTTPError, SkillPayloadTooLarge) as e:
                logger.debug(
                    "GitHub GET %s failed (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                return None

            last_resp = resp
            if resp.status_code == 200:
                return resp

            # Rate-limited: honor the reset header when present, else back off.
            if resp.status_code in (403, 429):
                remaining = resp.headers.get("X-RateLimit-Remaining", "")
                is_rl = remaining == "0" or resp.status_code == 429
                if is_rl and attempt < max_retries - 1:
                    wait = backoff
                    reset = resp.headers.get("X-RateLimit-Reset", "")
                    retry_after = resp.headers.get("Retry-After", "")
                    if retry_after.isdigit():
                        wait = min(float(retry_after), 60.0)
                    elif reset.isdigit():
                        delta = float(reset) - time.time()
                        if 0 < delta <= 60.0:
                            wait = delta
                    logger.debug(
                        "GitHub rate limited on %s, waiting %.1fs (attempt %d/%d)",
                        url,
                        wait,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(wait)
                    backoff = min(backoff * 2, 30.0)
                    continue
                # Out of retries (or not a rate-limit 403) — flag and return.
                self._check_rate_limit_response(resp)
                return resp

            # 5xx — retry; 4xx (other than rate limit) — return immediately.
            if 500 <= resp.status_code < 600 and attempt < max_retries - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            return resp

        return last_resp

    def _download_directory(self, repo: str, path: str) -> Dict[str, str]:
        """Recursively download all text files from a GitHub directory.

        Uses the Git Trees API first (single call for the entire tree) to
        avoid per-directory rate limiting that causes silent subdirectory
        loss.  Falls back to the recursive Contents API when the tree
        endpoint is unavailable or the response is truncated.
        """
        files = self._download_directory_via_tree(repo, path)
        if files is not None:
            return files
        logger.debug(
            "Tree API unavailable for %s/%s, falling back to Contents API", repo, path
        )
        return self._download_directory_recursive(repo, path)

    def _download_directory_via_tree(
        self, repo: str, path: str
    ) -> Optional[Dict[str, str]]:
        """Download an entire directory using the Git Trees API (single request).

        Returns:
            dict of files if the path exists and has content,
            empty dict ``{}`` if the tree is cached but the path doesn't exist
            (prevents unnecessary Contents API fallback),
            ``None`` if the tree couldn't be fetched (triggers Contents API fallback).
        """
        path = path.rstrip("/")

        cached = self._get_repo_tree(repo)
        if cached is None:
            return None
        _default_branch, tree_entries = cached

        # Check if ANY entry lives under the target path
        prefix = f"{path}/"
        has_entries = any(
            item.get("path", "").startswith(prefix) for item in tree_entries
        )
        if not has_entries:
            # Path definitively doesn't exist in the repo — return empty
            # instead of None to skip the Contents API fallback.
            return {}

        # Admit metadata for the complete candidate set before fetching any
        # blob, so a huge tree cannot allocate file bodies ahead of the cap.
        scoped_entries = [
            item
            for item in tree_entries
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and item["path"].startswith(prefix)
        ]
        unknown_entries = [
            item for item in scoped_entries if item.get("type") not in {"blob", "tree"}
        ]
        if unknown_entries:
            raise HubInstallError("GitHub bundle contains an unsupported tree entry")
        blobs = [item for item in scoped_entries if item.get("type") == "blob"]
        if len(blobs) > MAX_SKILL_ARCHIVE_FILES:
            raise SkillPayloadTooLarge("skill bundle contains too many files")
        declared_total = 0
        relative_paths: list[str] = []
        for item in blobs:
            rel_path = _validate_bundle_rel_path(item["path"][len(prefix) :])
            declared_size = item.get("size")
            if isinstance(declared_size, int):
                if declared_size < 0 or declared_size > MAX_SKILL_FILE_BYTES:
                    raise SkillPayloadTooLarge(
                        f"skill file {rel_path!r} exceeds the file cap"
                    )
                declared_total += declared_size
                if declared_total > MAX_SKILL_TOTAL_BYTES:
                    raise SkillPayloadTooLarge("skill tree exceeds the total byte cap")
            relative_paths.append(rel_path)
        validate_portable_tree_paths(tuple(relative_paths), field="bundle file path")

        builder = _BoundedBundleBuilder()
        for item, rel_path in zip(blobs, relative_paths):
            item_path = item["path"]
            content = self._fetch_file_content(repo, item_path)
            if content is None:
                raise HubInstallError(
                    f"GitHub bundle is incomplete; could not fetch {repo}/{item_path}"
                )
            builder.add(rel_path, content)

        files = builder.text_files()
        return files if files else None

    def _download_directory_recursive(
        self,
        repo: str,
        path: str,
        *,
        _builder: _BoundedBundleBuilder | None = None,
        _relative_prefix: str = "",
        _depth: int = 0,
    ) -> Dict[str, str]:
        """Recursively download via Contents API (fallback)."""
        if _depth > 64:
            raise SkillPayloadTooLarge("skill bundle directory nesting is too deep")
        builder = _builder or _BoundedBundleBuilder()
        url = f"https://api.github.com/repos/{repo}/contents/{path.rstrip('/')}"
        # Route through _github_get so directory listing gets the same
        # 429/403-rate-limit retry + backoff as file fetches (#3033).
        resp = self._github_get(url)
        if resp is None:
            if _depth:
                raise HubInstallError(
                    f"GitHub bundle is incomplete below {repo}/{path}"
                )
            return {}
        if resp.status_code != 200:
            logger.debug(
                "Contents API returned %d for %s/%s", resp.status_code, repo, path
            )
            if _depth:
                raise HubInstallError(
                    f"GitHub bundle is incomplete below {repo}/{path}"
                )
            return {}

        try:
            entries = _bounded_json(resp)
        except (json.JSONDecodeError, SkillPayloadTooLarge, ValueError):
            if _depth:
                raise HubInstallError(
                    f"GitHub bundle metadata is invalid below {repo}/{path}"
                )
            return {}
        if not isinstance(entries, list):
            if _depth:
                raise HubInstallError(
                    f"GitHub bundle metadata is invalid below {repo}/{path}"
                )
            return {}

        for entry in entries:
            name = entry.get("name", "")
            entry_type = entry.get("type", "")

            if entry_type == "file":
                rel_path = f"{_relative_prefix}/{name}".lstrip("/")
                if len(builder.files) >= MAX_SKILL_ARCHIVE_FILES:
                    raise SkillPayloadTooLarge("skill bundle contains too many files")
                declared_size = entry.get("size")
                if isinstance(declared_size, int) and (
                    declared_size < 0 or declared_size > MAX_SKILL_FILE_BYTES
                ):
                    raise SkillPayloadTooLarge(
                        f"skill file {rel_path!r} exceeds the file cap"
                    )
                if (
                    isinstance(declared_size, int)
                    and builder.total_bytes + declared_size > MAX_SKILL_TOTAL_BYTES
                ):
                    raise SkillPayloadTooLarge("skill tree exceeds the total byte cap")
                content = self._fetch_file_content(repo, entry.get("path", ""))
                if content is None:
                    raise HubInstallError(
                        f"GitHub bundle is incomplete; could not fetch {repo}/"
                        f"{entry.get('path', '')}"
                    )
                builder.add(rel_path, content)
            elif entry_type == "dir":
                prefix = f"{_relative_prefix}/{name}".lstrip("/")
                self._download_directory_recursive(
                    repo,
                    entry.get("path", ""),
                    _builder=builder,
                    _relative_prefix=prefix,
                    _depth=_depth + 1,
                )

        return builder.text_files()

    def _find_skill_in_repo_tree(self, repo: str, skill_name: str) -> Optional[str]:
        """Use the GitHub Trees API to find a skill directory anywhere in the repo.

        Returns the full identifier (``repo/path/to/skill``) or ``None``.
        This is a single API call regardless of repo depth, so it efficiently
        handles deeply nested directory structures like
        ``cli-tool/components/skills/development/<skill>/SKILL.md``.
        """
        cached = self._get_repo_tree(repo)
        if cached is None:
            return None
        _default_branch, tree_entries = cached

        # Look for SKILL.md files inside directories named <skill_name>
        skill_md_suffix = f"/{skill_name}/SKILL.md"
        for entry in tree_entries:
            if entry.get("type") != "blob":
                continue
            path = entry.get("path", "")
            if path.endswith(skill_md_suffix) or path == f"{skill_name}/SKILL.md":
                # Strip /SKILL.md to get the skill directory path
                skill_dir = path[: -len("/SKILL.md")]
                return f"{repo}/{skill_dir}"

        return None

    def _fetch_file_content(self, repo: str, path: str) -> Optional[str]:
        """Fetch a single file's content from GitHub."""
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        try:
            resp = _bounded_http_get(
                url,
                timeout=20,
                max_bytes=MAX_SKILL_FILE_BYTES,
                follow_redirects=True,
                headers={
                    **self.auth.get_headers(),
                    "Accept": "application/vnd.github.v3.raw",
                },
            )
        except (httpx.HTTPError, SkillPayloadTooLarge):
            return None
        if resp.status_code == 200:
            try:
                return resp.content.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return None

    def _get_skillsh_groupings(self, repo: str) -> Optional[Dict[str, str]]:
        """Fetch and parse the repo-root ``skills.sh.json`` grouping sidecar.

        ``skills.sh.json`` is a published cross-ecosystem standard
        (``$schema: https://skills.sh/schemas/skills.sh.schema.json``) that
        lets a tap declare human-readable category groupings for its skills:

            {"groupings": [{"title": "Inference AI", "skills": ["dynamo-..."]}]}

        We flatten it into ``{skill_name: grouping_title}`` so the Skills Hub
        UI can show a real category pill instead of a tag-derived guess. Any
        tap that ships this file gets categorization for free — this is not
        NVIDIA-specific.

        Returns the map (possibly empty) on success, or ``None`` when the repo
        has no sidecar / it couldn't be parsed. Cached per-repo on the instance.
        """
        if repo in self._skillsh_groupings:
            return self._skillsh_groupings[repo]

        content = self._fetch_file_content(repo, "skills.sh.json")
        groupings = self._parse_skillsh_groupings(content) if content else None
        self._skillsh_groupings[repo] = groupings
        return groupings

    @staticmethod
    def _parse_skillsh_groupings(content: str) -> Optional[Dict[str, str]]:
        """Flatten a ``skills.sh.json`` document into ``{skill_name: title}``.

        Returns ``None`` when the content isn't a usable grouping document.
        """
        try:
            if not isinstance(content, str):
                return None
            payload = content.encode("utf-8")
            if len(payload) > MAX_SKILL_FILE_BYTES:
                return None
            _preflight_json_bytes(payload)
            data = _validate_bounded_json_graph(json.loads(payload))
        except (
            json.JSONDecodeError,
            RecursionError,
            SkillPayloadTooLarge,
            TypeError,
            UnicodeError,
            ValueError,
        ):
            return None
        if not isinstance(data, dict):
            return None
        groupings = data.get("groupings")
        if not isinstance(groupings, list):
            return None

        mapping: Dict[str, str] = {}
        for group in groupings:
            if not isinstance(group, dict):
                continue
            title = group.get("title")
            members = group.get("skills")
            if not isinstance(title, str) or not isinstance(members, list):
                continue
            for member in members:
                if isinstance(member, str) and member:
                    # First grouping wins if a skill is listed twice.
                    mapping.setdefault(member, title)
        return mapping

    def _read_cache(self, key: str) -> Optional[list]:
        """Read cached index if not expired."""
        cached = _read_index_cache(key)
        return cached if isinstance(cached, list) else None

    def _write_cache(self, key: str, data: list) -> None:
        """Write index data to cache."""
        _write_index_cache(key, data)

    @staticmethod
    def _meta_to_dict(meta: SkillMeta) -> dict:
        return {
            "name": meta.name,
            "description": meta.description,
            "source": meta.source,
            "identifier": meta.identifier,
            "trust_level": meta.trust_level,
            "repo": meta.repo,
            "path": meta.path,
            "tags": meta.tags,
            "extra": meta.extra,
        }

    @staticmethod
    def _parse_frontmatter_quick(content: str) -> dict:
        """Parse YAML frontmatter from SKILL.md content."""
        if not content.startswith("---"):
            return {}
        match = re.search(r"\n---\s*\n", content[3:])
        if not match:
            return {}
        yaml_text = content[3 : match.start() + 3]
        try:
            parsed = yaml.safe_load(yaml_text)
            return parsed if isinstance(parsed, dict) else {}
        except yaml.YAMLError:
            return {}


# ---------------------------------------------------------------------------
# Well-known Agent Skills endpoint source adapter
# ---------------------------------------------------------------------------


class WellKnownSkillSource(SkillSource):
    """Read skills from a domain exposing /.well-known/skills/index.json."""

    BASE_PATH = "/.well-known/skills"

    def source_id(self) -> str:
        return "well-known"

    def trust_level_for(self, identifier: str) -> str:
        return "community"

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        index_url = self._query_to_index_url(query)
        if not index_url:
            return []

        parsed = self._parse_index(index_url)
        if not parsed:
            return []

        results: List[SkillMeta] = []
        for entry in parsed["skills"][:limit]:
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            description = entry.get("description", "")
            files = entry.get("files", ["SKILL.md"])
            results.append(
                SkillMeta(
                    name=name,
                    description=str(description),
                    source="well-known",
                    identifier=self._wrap_identifier(parsed["base_url"], name),
                    trust_level="community",
                    path=name,
                    extra={
                        "index_url": parsed["index_url"],
                        "base_url": parsed["base_url"],
                        "files": files if isinstance(files, list) else ["SKILL.md"],
                    },
                )
            )
        return results

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        parsed = self._parse_identifier(identifier)
        if not parsed:
            return None

        entry = self._index_entry(parsed["index_url"], parsed["skill_name"])
        if not entry:
            return None

        skill_md = self._fetch_text(f"{parsed['skill_url']}/SKILL.md")
        if skill_md is None:
            return None

        fm = GitHubSource._parse_frontmatter_quick(skill_md)
        description = str(fm.get("description") or entry.get("description") or "")
        name = str(fm.get("name") or parsed["skill_name"])
        return SkillMeta(
            name=name,
            description=description,
            source="well-known",
            identifier=self._wrap_identifier(parsed["base_url"], parsed["skill_name"]),
            trust_level="community",
            path=parsed["skill_name"],
            extra={
                "index_url": parsed["index_url"],
                "base_url": parsed["base_url"],
                "files": entry.get("files", ["SKILL.md"]),
                "endpoint": parsed["skill_url"],
            },
        )

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        parsed = self._parse_identifier(identifier)
        if not parsed:
            return None

        try:
            skill_name = _validate_skill_name(parsed["skill_name"])
        except ValueError:
            logger.warning(
                "Well-known skill identifier contained unsafe skill name: %s",
                identifier,
            )
            return None

        entry = self._index_entry(parsed["index_url"], parsed["skill_name"])
        if not entry:
            return None

        files = entry.get("files", ["SKILL.md"])
        if not isinstance(files, list) or not files:
            files = ["SKILL.md"]

        downloaded: Dict[str, str] = {}
        for rel_path in files:
            if not isinstance(rel_path, str) or not rel_path:
                continue
            try:
                safe_rel_path = _validate_bundle_rel_path(rel_path)
            except ValueError:
                logger.warning(
                    "Well-known skill %s advertised unsafe file path: %r",
                    identifier,
                    rel_path,
                )
                return None
            text = self._fetch_text(f"{parsed['skill_url']}/{safe_rel_path}")
            if text is None:
                return None
            downloaded[safe_rel_path] = text

        if "SKILL.md" not in downloaded:
            return None

        return SkillBundle(
            name=skill_name,
            files=downloaded,
            source="well-known",
            identifier=self._wrap_identifier(parsed["base_url"], skill_name),
            trust_level="community",
            metadata={
                "index_url": parsed["index_url"],
                "base_url": parsed["base_url"],
                "endpoint": parsed["skill_url"],
                "files": files,
            },
        )

    def _query_to_index_url(self, query: str) -> Optional[str]:
        query = query.strip()
        if not query.startswith(("http://", "https://")):
            return None
        if query.endswith("/index.json"):
            return query
        if f"{self.BASE_PATH}/" in query:
            base_url = query.split(f"{self.BASE_PATH}/", 1)[0] + self.BASE_PATH
            return f"{base_url}/index.json"
        return query.rstrip("/") + f"{self.BASE_PATH}/index.json"

    def _parse_identifier(self, identifier: str) -> Optional[dict]:
        raw = (
            identifier[len("well-known:") :]
            if identifier.startswith("well-known:")
            else identifier
        )
        if not raw.startswith(("http://", "https://")):
            return None

        parsed_url = urlparse(raw)
        clean_url = urlunparse(parsed_url._replace(fragment=""))
        fragment = parsed_url.fragment

        if clean_url.endswith("/index.json"):
            if not fragment:
                return None
            base_url = clean_url[: -len("/index.json")]
            skill_name = fragment
            skill_url = f"{base_url}/{skill_name}"
            return {
                "index_url": clean_url,
                "base_url": base_url,
                "skill_name": skill_name,
                "skill_url": skill_url,
            }

        if clean_url.endswith("/SKILL.md"):
            skill_url = clean_url[: -len("/SKILL.md")]
        else:
            skill_url = clean_url.rstrip("/")

        if f"{self.BASE_PATH}/" not in skill_url:
            return None

        base_url, skill_name = skill_url.rsplit("/", 1)
        return {
            "index_url": f"{base_url}/index.json",
            "base_url": base_url,
            "skill_name": skill_name,
            "skill_url": skill_url,
        }

    def _parse_index(self, index_url: str) -> Optional[dict]:
        cache_key = f"well_known_index_{hashlib.md5(index_url.encode()).hexdigest()}"
        cached = _read_index_cache(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("skills"), list):
            return cached

        resp = _guarded_http_get(index_url, timeout=20)
        if resp is None or resp.status_code != 200:
            return None
        try:
            data = _bounded_json(resp)
        except (json.JSONDecodeError, SkillPayloadTooLarge, ValueError):
            return None

        skills = data.get("skills", []) if isinstance(data, dict) else []
        if not isinstance(skills, list):
            return None

        parsed = {
            "index_url": index_url,
            "base_url": index_url[: -len("/index.json")],
            "skills": skills,
        }
        _write_index_cache(cache_key, parsed)
        return parsed

    def _index_entry(self, index_url: str, skill_name: str) -> Optional[dict]:
        parsed = self._parse_index(index_url)
        if not parsed:
            return None
        for entry in parsed["skills"]:
            if isinstance(entry, dict) and entry.get("name") == skill_name:
                return entry
        return None

    @staticmethod
    def _fetch_text(url: str) -> Optional[str]:
        resp = _guarded_http_get(url, timeout=20, max_bytes=MAX_SKILL_FILE_BYTES)
        if resp is not None and resp.status_code == 200:
            return _bounded_response_text(resp)
        return None

    @staticmethod
    def _wrap_identifier(base_url: str, skill_name: str) -> str:
        return f"well-known:{base_url.rstrip('/')}/{skill_name}"


# ---------------------------------------------------------------------------
# Direct URL source adapter
# ---------------------------------------------------------------------------


class UrlSource(SkillSource):
    """Fetch a single-file SKILL.md skill directly from an HTTP(S) URL.

    The identifier IS the URL (e.g. ``https://example.com/path/SKILL.md``).
    Only single-file skills are supported — multi-file skills with
    ``references/`` or ``scripts/`` subfolders need a manifest we can't
    discover from a bare URL.

    The skill name is read from the ``name:`` field in the SKILL.md YAML
    frontmatter (with a URL-slug fallback). Trust level is always
    ``community`` and the same security scan runs as for every other source.
    """

    def source_id(self) -> str:
        return "url"

    def trust_level_for(self, identifier: str) -> str:
        return "community"

    # Search is meaningless for a direct URL — skip (return empty).
    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        return []

    def _matches(self, identifier: str) -> bool:
        """Return True iff this source should handle ``identifier``.

        We claim bare HTTP(S) URLs that end in ``.md`` (typically
        ``.../SKILL.md``). Wrapped identifiers (``github:``,
        ``well-known:``, etc.) and ``/.well-known/skills/`` URLs are
        left for their respective adapters.
        """
        if not isinstance(identifier, str):
            return False
        ident = identifier.strip()
        if not ident.lower().startswith(("http://", "https://")):
            return False
        # Don't steal well-known URLs.
        if "/.well-known/skills/" in ident or ident.rstrip("/").endswith("/index.json"):
            return False
        # Only claim URLs that look like a markdown file.
        try:
            path = urlparse(ident).path
        except ValueError:
            return False
        return path.lower().endswith(".md")

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        if not self._matches(identifier):
            return None
        url = identifier.strip()
        text = self._fetch_text(url)
        if text is None:
            return None
        fm = GitHubSource._parse_frontmatter_quick(text)
        name = self._resolve_skill_name(fm, url)
        description = str(fm.get("description") or "")
        raw_tags = extract_skill_metadata(fm).get("tags", [])
        tags: List[str] = (
            [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
        )
        return SkillMeta(
            name=name or "",
            description=description,
            source="url",
            identifier=url,
            trust_level="community",
            path=name or "",
            tags=tags,
            extra={"url": url, "awaiting_name": name is None},
        )

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        if not self._matches(identifier):
            return None
        url = identifier.strip()
        text = self._fetch_text(url)
        if text is None:
            return None

        fm = GitHubSource._parse_frontmatter_quick(text)
        name = self._resolve_skill_name(fm, url)

        # When auto-resolution fails, return a bundle with an empty name and
        # ``awaiting_name=True`` in metadata. The install flow (``do_install``)
        # either prompts the user on a TTY or refuses with an actionable error
        # on non-interactive surfaces. Keep the expensive HTTP fetch's result
        # so the caller doesn't have to re-download after picking a name.
        skill_name = ""
        if name is not None:
            try:
                skill_name = _validate_skill_name(name)
            except ValueError:
                logger.warning("URL skill %s produced unsafe skill name: %r", url, name)
                return None

        return SkillBundle(
            name=skill_name,
            files={"SKILL.md": text},
            source="url",
            identifier=url,
            trust_level="community",
            metadata={"url": url, "awaiting_name": not skill_name},
        )

    @staticmethod
    def _fetch_text(url: str) -> Optional[str]:
        resp = _guarded_http_get(url, timeout=20, max_bytes=MAX_SKILL_FILE_BYTES)
        if resp is not None and resp.status_code == 200:
            return _bounded_response_text(resp)
        return None

    # Skill names must look like identifiers: lowercase letters/digits with
    # optional hyphens/underscores. Blocks dangerous (``../evil``) AND useless
    # (``SKILL``, ``README``, empty) candidates before they hit the disk.
    _VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

    @classmethod
    def _is_valid_skill_name(cls, name: Optional[str]) -> bool:
        if not isinstance(name, str):
            return False
        candidate = name.strip().lower()
        if not candidate or candidate in {"skill", "readme", "index", "unnamed-skill"}:
            return False
        return bool(cls._VALID_NAME_RE.match(candidate))

    @classmethod
    def _resolve_skill_name(cls, fm: dict, url: str) -> Optional[str]:
        """Pick a skill name from frontmatter or URL.

        Returns ``None`` when neither source produces a valid identifier;
        callers (CLI ``do_install``) then prompt the user or refuse. Preferring
        a clean failure over a useless auto-name like ``SKILL`` or ``unnamed-skill``.
        """
        # 1. Frontmatter ``name:`` is authoritative when present and valid.
        fm_name = fm.get("name") if isinstance(fm, dict) else None
        if isinstance(fm_name, str) and cls._is_valid_skill_name(fm_name):
            return fm_name.strip()

        # 2. URL-slug heuristic: ``.../<name>/SKILL.md`` → ``<name>``;
        #    ``.../<name>.md`` → ``<name>``. Validate each candidate.
        try:
            path = urlparse(url).path
        except ValueError:
            return None
        parts = [p for p in path.split("/") if p]
        if parts and parts[-1].lower() == "skill.md" and len(parts) >= 2:
            candidate = parts[-2]
            if cls._is_valid_skill_name(candidate):
                return candidate
        if parts:
            candidate = re.sub(r"\.md$", "", parts[-1], flags=re.IGNORECASE)
            if cls._is_valid_skill_name(candidate):
                return candidate

        # Nothing usable — let the caller handle it.
        return None


# ---------------------------------------------------------------------------
# skills.sh source adapter
# ---------------------------------------------------------------------------


class SkillsShSource(SkillSource):
    """Discover skills via skills.sh and fetch content from the underlying GitHub repo."""

    BASE_URL = "https://skills.sh"
    SEARCH_URL = f"{BASE_URL}/api/search"
    # Sitemap index — the real catalog source. The homepage scrape only
    # exposes a curated featured strip (~200 entries); the sitemap covers
    # the full ~20k+ catalog. https://www.skills.sh/sitemap.xml points at
    # sitemap-skills-1.xml + sitemap-skills-2.xml, each up to 10k URLs.
    SITEMAP_INDEX_URL = "https://www.skills.sh/sitemap.xml"
    _SITEMAP_LOC_RE = re.compile(r"<loc>([^<]+)</loc>", re.IGNORECASE)
    _SITEMAP_SKILL_RE = re.compile(
        r"^https?://(?:www\.)?skills\.sh/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<skill>[^/]+)/?$",
        re.IGNORECASE,
    )
    _SKILL_LINK_RE = re.compile(
        r'href=["\']/(?P<id>(?!agents/|_next/|api/)[^"\'/]+/[^"\'/]+/[^"\'/]+)["\']'
    )
    _INSTALL_CMD_RE = re.compile(
        r"npx\s+skills\s+add\s+(?P<repo>https?://github\.com/[^\s<]+|[^\s<]+)"
        r"(?:\s+--skill\s+(?P<skill>[^\s<]+))?",
        re.IGNORECASE,
    )
    _PAGE_H1_RE = re.compile(r"<h1[^>]*>(?P<title>.*?)</h1>", re.IGNORECASE | re.DOTALL)
    _PROSE_H1_RE = re.compile(
        r'<div[^>]*class=["\'][^"\']*prose[^"\']*["\'][^>]*>.*?<h1[^>]*>(?P<title>.*?)</h1>',
        re.IGNORECASE | re.DOTALL,
    )
    _PROSE_P_RE = re.compile(
        r'<div[^>]*class=["\'][^"\']*prose[^"\']*["\'][^>]*>.*?<p[^>]*>(?P<body>.*?)</p>',
        re.IGNORECASE | re.DOTALL,
    )
    _WEEKLY_INSTALLS_RE = re.compile(
        r'Weekly Installs.*?children\\":\\"(?P<count>[0-9.,Kk]+)\\"', re.DOTALL
    )

    def __init__(self, auth: GitHubAuth):
        self.auth = auth
        self.github = GitHubSource(auth=auth)

    def source_id(self) -> str:
        return "skills-sh"

    def trust_level_for(self, identifier: str) -> str:
        return self.github.trust_level_for(self._normalize_identifier(identifier))

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        if not query.strip():
            # Empty query = bulk catalog dump (what build_skills_index.py
            # calls with). The homepage scrape only sees ~200 featured
            # entries; the sitemap walks the full ~20k+ catalog.
            return self._sitemap_catalog(limit)

        cache_key = (
            f"skills_sh_search_{hashlib.md5(f'{query}|{limit}'.encode()).hexdigest()}"
        )
        cached = _read_index_cache(cache_key)
        if cached is not None:
            return [SkillMeta(**item) for item in cached][:limit]

        try:
            resp = _bounded_http_get(
                self.SEARCH_URL,
                params={"q": query, "limit": limit},
                timeout=20,
                max_bytes=MAX_SKILL_METADATA_BYTES,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return []
            data = _bounded_json(resp)
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            return []

        items = data.get("skills", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            return []

        results: List[SkillMeta] = []
        for item in items[:limit]:
            meta = self._meta_from_search_item(item)
            if meta:
                results.append(meta)

        _write_index_cache(cache_key, [_skill_meta_to_dict(item) for item in results])
        return results

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        canonical = self._normalize_identifier(identifier)
        detail = self._fetch_detail_page(canonical)
        for candidate in self._candidate_identifiers(canonical):
            bundle = self.github.fetch(candidate)
            if bundle:
                bundle.source = "skills.sh"
                bundle.identifier = self._wrap_identifier(canonical)
                bundle.metadata.update(self._detail_to_metadata(canonical, detail))
                bundle.metadata["source_revision"] = candidate
                bundle.metadata["source_name"] = bundle.name
                return bundle

        resolved = self._discover_identifier(canonical, detail=detail)
        if resolved:
            bundle = self.github.fetch(resolved)
            if bundle:
                bundle.source = "skills.sh"
                bundle.identifier = self._wrap_identifier(canonical)
                bundle.metadata.update(self._detail_to_metadata(canonical, detail))
                bundle.metadata["source_revision"] = resolved
                bundle.metadata["source_name"] = bundle.name
                return bundle
        return None

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        canonical = self._normalize_identifier(identifier)
        detail = self._fetch_detail_page(canonical)
        meta = self._resolve_github_meta(canonical, detail=detail)
        if meta:
            return self._finalize_inspect_meta(meta, canonical, detail)
        return None

    def _sitemap_catalog(self, limit: int) -> List[SkillMeta]:
        """Walk the skills.sh sitemap to enumerate the full catalog.

        Cached for the standard index TTL so we don't refetch ~2 MB of
        sitemap XML per build. Falls back to ``_featured_skills`` if the
        sitemap is unreachable or empty (network failure, hostname
        change, etc.).
        """
        cache_key = "skills_sh_sitemap_v1"
        cached = _read_index_cache(cache_key)
        if cached is not None:
            metas = [SkillMeta(**item) for item in cached]
            return metas[:limit] if limit > 0 else metas

        # skills.sh serves the per-skill sitemaps brotli-compressed, and
        # httpx's optional brotlicffi backend has a streaming-decode bug
        # that fails on these specific payloads. Excluding "br" from
        # Accept-Encoding makes the server fall back to gzip (or
        # identity), which works on every httpx install.
        sitemap_headers = {"Accept-Encoding": "identity"}

        # Step 1: fetch the sitemap index → list of skill-sitemap URLs.
        skill_sitemap_urls: List[str] = []
        try:
            resp = _bounded_http_get(
                self.SITEMAP_INDEX_URL,
                timeout=20,
                max_bytes=MAX_HUB_CATALOG_BYTES,
                follow_redirects=True,
                headers=sitemap_headers,
            )
            if resp.status_code != 200:
                return self._featured_skills(limit)
            for match in self._SITEMAP_LOC_RE.finditer(resp.text):
                loc = match.group(1).strip()
                # Sitemap index entries that point at the per-skill maps.
                if "sitemap-skills" in loc:
                    skill_sitemap_urls.append(loc)
        except (httpx.HTTPError, SkillPayloadTooLarge):
            return self._featured_skills(limit)

        if not skill_sitemap_urls:
            return self._featured_skills(limit)

        # Step 2: fetch each skill sitemap and collect canonical "owner/repo/skill" IDs.
        seen: set[str] = set()
        results: List[SkillMeta] = []
        for sitemap_url in skill_sitemap_urls:
            try:
                resp = _bounded_http_get(
                    sitemap_url,
                    timeout=30,
                    max_bytes=MAX_HUB_CATALOG_BYTES,
                    follow_redirects=True,
                    headers=sitemap_headers,
                )
                if resp.status_code != 200:
                    continue
            except (httpx.HTTPError, SkillPayloadTooLarge):
                continue
            for loc_match in self._SITEMAP_LOC_RE.finditer(resp.text):
                url = loc_match.group(1).strip()
                m = self._SITEMAP_SKILL_RE.match(url)
                if not m:
                    continue
                owner = m.group("owner")
                repo_name = m.group("repo")
                skill_name = m.group("skill")
                canonical = f"{owner}/{repo_name}/{skill_name}"
                if canonical in seen:
                    continue
                seen.add(canonical)
                repo = f"{owner}/{repo_name}"
                results.append(
                    SkillMeta(
                        name=skill_name,
                        description=f"Indexed by skills.sh from {repo}",
                        source="skills.sh",
                        identifier=self._wrap_identifier(canonical),
                        trust_level=self.github.trust_level_for(canonical),
                        repo=repo,
                        path=skill_name,
                        extra={
                            "detail_url": f"{self.BASE_URL}/{canonical}",
                            "repo_url": f"https://github.com/{repo}",
                        },
                    )
                )

        if not results:
            return self._featured_skills(limit)

        _write_index_cache(cache_key, [_skill_meta_to_dict(item) for item in results])
        return results[:limit] if limit > 0 else results

    def _featured_skills(self, limit: int) -> List[SkillMeta]:
        cache_key = "skills_sh_featured"
        cached = _read_index_cache(cache_key)
        if cached is not None:
            return [SkillMeta(**item) for item in cached][:limit]

        try:
            resp = _bounded_http_get(
                self.BASE_URL,
                timeout=20,
                max_bytes=MAX_SKILL_METADATA_BYTES,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return []
        except (httpx.HTTPError, SkillPayloadTooLarge):
            return []

        seen: set[str] = set()
        results: List[SkillMeta] = []
        for match in self._SKILL_LINK_RE.finditer(resp.text):
            canonical = match.group("id")
            if canonical in seen:
                continue
            seen.add(canonical)
            parts = canonical.split("/", 2)
            if len(parts) < 3:
                continue
            repo = f"{parts[0]}/{parts[1]}"
            skill_path = parts[2]
            results.append(
                SkillMeta(
                    name=skill_path.split("/")[-1],
                    description=f"Featured on skills.sh from {repo}",
                    source="skills.sh",
                    identifier=self._wrap_identifier(canonical),
                    trust_level=self.github.trust_level_for(canonical),
                    repo=repo,
                    path=skill_path,
                )
            )
            if len(results) >= limit:
                break

        _write_index_cache(cache_key, [_skill_meta_to_dict(item) for item in results])
        return results

    def _meta_from_search_item(self, item: dict) -> Optional[SkillMeta]:
        if not isinstance(item, dict):
            return None

        canonical = item.get("id")
        repo = item.get("source")
        skill_path = item.get("skillId")
        if not isinstance(canonical, str) or canonical.count("/") < 2:
            if not (isinstance(repo, str) and isinstance(skill_path, str)):
                return None
            canonical = f"{repo}/{skill_path}"

        parts = canonical.split("/", 2)
        if len(parts) < 3:
            return None

        repo = f"{parts[0]}/{parts[1]}"
        skill_path = parts[2]
        installs = item.get("installs")
        installs_label = (
            f" · {int(installs):,} installs" if isinstance(installs, int) else ""
        )

        return SkillMeta(
            name=str(item.get("name") or skill_path.split("/")[-1]),
            description=f"Indexed by skills.sh from {repo}{installs_label}",
            source="skills.sh",
            identifier=self._wrap_identifier(canonical),
            trust_level=self.github.trust_level_for(canonical),
            repo=repo,
            path=skill_path,
            extra={
                "installs": installs,
                "detail_url": f"{self.BASE_URL}/{canonical}",
                "repo_url": f"https://github.com/{repo}",
            },
        )

    def _fetch_detail_page(self, identifier: str) -> Optional[dict]:
        cache_key = f"skills_sh_detail_{hashlib.md5(identifier.encode()).hexdigest()}"
        cached = _read_index_cache(cache_key)
        if isinstance(cached, dict):
            return cached

        try:
            resp = _bounded_http_get(
                f"{self.BASE_URL}/{identifier}",
                timeout=20,
                max_bytes=MAX_SKILL_METADATA_BYTES,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
        except (httpx.HTTPError, SkillPayloadTooLarge):
            return None

        detail = self._parse_detail_page(identifier, resp.text)
        if detail:
            _write_index_cache(cache_key, detail)
        return detail

    def _parse_detail_page(self, identifier: str, html: str) -> Optional[dict]:
        parts = identifier.split("/", 2)
        if len(parts) < 3:
            return None

        default_repo = f"{parts[0]}/{parts[1]}"
        skill_token = parts[2]
        repo = default_repo
        install_skill = skill_token

        install_command = None
        install_match = self._INSTALL_CMD_RE.search(html)
        if install_match:
            install_command = install_match.group(0).strip()
            repo_value = (install_match.group("repo") or "").strip()
            install_skill = (install_match.group("skill") or install_skill).strip()
            repo = self._extract_repo_slug(repo_value) or repo

        page_title = self._extract_first_match(self._PAGE_H1_RE, html)
        body_title = self._extract_first_match(self._PROSE_H1_RE, html)
        body_summary = self._extract_first_match(self._PROSE_P_RE, html)
        weekly_installs = self._extract_weekly_installs(html)
        security_audits = self._extract_security_audits(html, identifier)

        return {
            "repo": repo,
            "install_skill": install_skill,
            "page_title": page_title,
            "body_title": body_title,
            "body_summary": body_summary,
            "weekly_installs": weekly_installs,
            "install_command": install_command,
            "repo_url": f"https://github.com/{repo}",
            "detail_url": f"{self.BASE_URL}/{identifier}",
            "security_audits": security_audits,
        }

    def _discover_identifier(
        self, identifier: str, detail: Optional[dict] = None
    ) -> Optional[str]:
        parts = identifier.split("/", 2)
        if len(parts) < 3:
            return None

        default_repo = f"{parts[0]}/{parts[1]}"
        repo = (
            detail.get("repo", default_repo)
            if isinstance(detail, dict)
            else default_repo
        )
        skill_token = parts[2].split("/")[-1]
        tokens = [skill_token]
        if isinstance(detail, dict):
            tokens.extend([
                detail.get("install_skill", ""),
                detail.get("page_title", ""),
                detail.get("body_title", ""),
            ])

        # Standard skill paths
        base_paths = ["skills/", ".agents/skills/", ".claude/skills/"]

        for base_path in base_paths:
            try:
                skills = self.github._list_skills_in_repo(repo, base_path)
            except Exception:
                continue
            for meta in skills:
                if self._matches_skill_tokens(meta, tokens):
                    return meta.identifier

        # Prefer a single recursive tree lookup before brute-forcing every
        # top-level directory. This avoids large request bursts on categorized
        # repos like borghei/claude-skills.
        tree_result = self.github._find_skill_in_repo_tree(repo, skill_token)
        if tree_result:
            return tree_result

        # Fallback: scan repo root for directories that might contain skills
        try:
            root_url = f"https://api.github.com/repos/{repo}/contents/"
            resp = self.github._github_get(
                root_url,
                headers=self.github.auth.get_headers(),
                timeout=15,
            )
            if resp is not None and resp.status_code == 200:
                entries = _bounded_json(resp)
                if isinstance(entries, list):
                    for entry in entries:
                        if entry.get("type") != "dir":
                            continue
                        dir_name = entry["name"]
                        if dir_name.startswith((".", "_")):
                            continue
                        if dir_name in {"skills", ".agents", ".claude"}:
                            continue  # already tried
                        # Try direct: repo/dir/skill_token
                        direct_id = f"{repo}/{dir_name}/{skill_token}"
                        meta = self.github.inspect(direct_id)
                        if meta:
                            return meta.identifier
                        # Try listing skills in this directory
                        try:
                            skills = self.github._list_skills_in_repo(
                                repo, dir_name + "/"
                            )
                        except Exception:
                            continue
                        for meta in skills:
                            if self._matches_skill_tokens(meta, tokens):
                                return meta.identifier
        except Exception:
            pass

        return None

    def _resolve_github_meta(
        self, identifier: str, detail: Optional[dict] = None
    ) -> Optional[SkillMeta]:
        for candidate in self._candidate_identifiers(identifier):
            meta = self.github.inspect(candidate)
            if meta:
                return meta

        resolved = self._discover_identifier(identifier, detail=detail)
        if resolved:
            return self.github.inspect(resolved)
        return None

    def _finalize_inspect_meta(
        self, meta: SkillMeta, canonical: str, detail: Optional[dict]
    ) -> SkillMeta:
        meta.source = "skills.sh"
        meta.identifier = self._wrap_identifier(canonical)
        meta.trust_level = self.trust_level_for(canonical)
        merged_extra = dict(meta.extra)
        merged_extra.update(self._detail_to_metadata(canonical, detail))
        meta.extra = merged_extra

        if isinstance(detail, dict):
            body_summary = detail.get("body_summary")
            weekly_installs = detail.get("weekly_installs")
            if body_summary:
                meta.description = body_summary
            elif meta.description and weekly_installs:
                meta.description = f"{meta.description} · {weekly_installs} weekly installs on skills.sh"
        return meta

    @classmethod
    def _matches_skill_tokens(cls, meta: SkillMeta, skill_tokens: List[str]) -> bool:
        candidates = set()
        candidates.update(cls._token_variants(meta.name))
        candidates.update(cls._token_variants(meta.path))
        candidates.update(
            cls._token_variants(
                meta.identifier.split("/", 2)[-1] if meta.identifier else None
            )
        )

        for token in skill_tokens:
            variants = cls._token_variants(token)
            if variants & candidates:
                return True
        return False

    @staticmethod
    def _token_variants(value: Optional[str]) -> set[str]:
        if not value:
            return set()

        plain = SkillsShSource._strip_html(str(value)).strip().strip("/").lower()
        if not plain:
            return set()

        base = plain.split("/")[-1]
        sanitized = re.sub(r"[^a-z0-9/_-]+", "-", plain).strip("-")
        sanitized_base = sanitized.split("/")[-1] if sanitized else ""
        slash_tail = plain.split("/")[-1]
        slash_tail_clean = slash_tail.lstrip("@")
        slash_tail_clean = slash_tail_clean.split("/")[-1]

        variants = {
            plain,
            plain.replace("_", "-"),
            plain.replace("/", "-"),
            base,
            base.replace("_", "-"),
            base.replace("/", "-"),
            sanitized,
            sanitized.replace("/", "-") if sanitized else "",
            sanitized_base,
            slash_tail_clean,
            slash_tail_clean.replace("_", "-"),
        }
        return {v for v in variants if v}

    @staticmethod
    def _extract_repo_slug(repo_value: str) -> Optional[str]:
        repo_value = repo_value.strip()
        if repo_value.startswith("https://github.com/"):
            repo_value = repo_value[len("https://github.com/") :]
        repo_value = repo_value.strip("/")
        parts = repo_value.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return None

    @staticmethod
    def _extract_first_match(pattern: re.Pattern, text: str) -> Optional[str]:
        match = pattern.search(text)
        if not match:
            return None
        value = next((group for group in match.groups() if group), None)
        if value is None:
            return None
        return SkillsShSource._strip_html(value).strip() or None

    def _detail_to_metadata(
        self, canonical: str, detail: Optional[dict]
    ) -> Dict[str, Any]:
        parts = canonical.split("/", 2)
        repo = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ""
        metadata = {
            "detail_url": f"{self.BASE_URL}/{canonical}",
        }
        if repo:
            metadata["repo_url"] = f"https://github.com/{repo}"
        if isinstance(detail, dict):
            for key in (
                "weekly_installs",
                "install_command",
                "repo_url",
                "detail_url",
                "security_audits",
            ):
                value = detail.get(key)
                if value:
                    metadata[key] = value
        return metadata

    @staticmethod
    def _extract_weekly_installs(html: str) -> Optional[str]:
        match = SkillsShSource._WEEKLY_INSTALLS_RE.search(html)
        if not match:
            return None
        return match.group("count")

    @staticmethod
    def _extract_security_audits(html: str, identifier: str) -> Dict[str, str]:
        audits: Dict[str, str] = {}
        for audit in ("agent-trust-hub", "socket", "snyk"):
            idx = html.find(f"/security/{audit}")
            if idx == -1:
                continue
            window = html[idx : idx + 500]
            match = re.search(r"(Pass|Warn|Fail)", window, re.IGNORECASE)
            if match:
                audits[audit] = match.group(1).title()
        return audits

    @staticmethod
    def _strip_html(value: str) -> str:
        return re.sub(r"<[^>]+>", "", value)

    @staticmethod
    def _normalize_identifier(identifier: str) -> str:
        prefix_aliases = (
            "skills-sh/",
            "skills.sh/",
            "skils-sh/",
            "skils.sh/",
        )
        for prefix in prefix_aliases:
            if identifier.startswith(prefix):
                return identifier[len(prefix) :]
        return identifier

    @staticmethod
    def _candidate_identifiers(identifier: str) -> List[str]:
        parts = identifier.split("/", 2)
        if len(parts) < 3:
            return [identifier]

        repo = f"{parts[0]}/{parts[1]}"
        skill_path = parts[2].lstrip("/")
        candidates = [
            f"{repo}/{skill_path}",
            f"{repo}/skills/{skill_path}",
            f"{repo}/.agents/skills/{skill_path}",
            f"{repo}/.claude/skills/{skill_path}",
        ]

        seen = set()
        deduped: List[str] = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped

    @staticmethod
    def _wrap_identifier(identifier: str) -> str:
        return f"skills-sh/{identifier}"


# ---------------------------------------------------------------------------
# ClawHub source adapter
# ---------------------------------------------------------------------------


class ClawHubSource(SkillSource):
    """
    Fetch skills from ClawHub (clawhub.ai) via their HTTP API.
    All skills are treated as community trust — ClawHavoc incident showed
    their vetting is insufficient (341 malicious skills found Feb 2026).
    """

    BASE_URL = "https://clawhub.ai/api/v1"

    # Wall-clock budget for a full catalog walk. ClawHub has 50k+ skills and
    # the walk is sequential (~250 requests, each under per-request
    # timeout=30 so nothing errors), so an unbounded walk can block for
    # minutes. Bound it so a slow/large catalog cannot hang the caller.
    CATALOG_WALK_BUDGET_SECONDS = 12

    def source_id(self) -> str:
        return "clawhub"

    def trust_level_for(self, identifier: str) -> str:
        return "community"

    @staticmethod
    def _normalize_tags(tags: Any) -> List[str]:
        if isinstance(tags, list):
            return [str(t) for t in tags]
        if isinstance(tags, dict):
            return [str(k) for k in tags if str(k) != "latest"]
        return []

    @staticmethod
    def _coerce_skill_payload(data: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(data, dict):
            return None
        nested = data.get("skill")
        if isinstance(nested, dict):
            merged = dict(nested)
            latest_version = data.get("latestVersion")
            if latest_version is not None and "latestVersion" not in merged:
                merged["latestVersion"] = latest_version
            return merged
        return data

    @staticmethod
    def _query_terms(query: str) -> List[str]:
        return [term for term in re.split(r"[^a-z0-9]+", query.lower()) if term]

    @classmethod
    def _search_score(cls, query: str, meta: SkillMeta) -> int:
        query_norm = query.strip().lower()
        if not query_norm:
            return 1

        identifier = (meta.identifier or "").lower()
        name = (meta.name or "").lower()
        description = (meta.description or "").lower()
        normalized_identifier = " ".join(cls._query_terms(identifier))
        normalized_name = " ".join(cls._query_terms(name))
        query_terms = cls._query_terms(query_norm)
        identifier_terms = cls._query_terms(identifier)
        name_terms = cls._query_terms(name)
        score = 0

        if query_norm == identifier:
            score += 140
        if query_norm == name:
            score += 130
        if normalized_identifier == query_norm:
            score += 125
        if normalized_name == query_norm:
            score += 120
        if normalized_identifier.startswith(query_norm):
            score += 95
        if normalized_name.startswith(query_norm):
            score += 90
        if query_terms and identifier_terms[: len(query_terms)] == query_terms:
            score += 70
        if query_terms and name_terms[: len(query_terms)] == query_terms:
            score += 65
        if query_norm in identifier:
            score += 40
        if query_norm in name:
            score += 35
        if query_norm in description:
            score += 10

        for term in query_terms:
            if term in identifier_terms:
                score += 15
            if term in name_terms:
                score += 12
            if term in description:
                score += 3

        return score

    @staticmethod
    def _dedupe_results(results: List[SkillMeta]) -> List[SkillMeta]:
        seen: set[str] = set()
        deduped: List[SkillMeta] = []
        for result in results:
            key = (result.identifier or result.name).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        return deduped

    def _exact_slug_meta(self, query: str) -> Optional[SkillMeta]:
        slug = query.strip().split("/")[-1]
        query_terms = self._query_terms(query)
        candidates: List[str] = []

        if slug and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
            candidates.append(slug)

        if query_terms:
            base_slug = "-".join(query_terms)
            if len(query_terms) >= 2:
                candidates.extend([
                    f"{base_slug}-agent",
                    f"{base_slug}-skill",
                    f"{base_slug}-tool",
                    f"{base_slug}-assistant",
                    f"{base_slug}-playbook",
                    base_slug,
                ])
            else:
                candidates.append(base_slug)

        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            meta = self.inspect(candidate)
            if meta:
                return meta

        return None

    def _finalize_search_results(
        self, query: str, results: List[SkillMeta], limit: int
    ) -> List[SkillMeta]:
        query_norm = query.strip()
        if not query_norm:
            return self._dedupe_results(results)[:limit]

        filtered = [
            meta for meta in results if self._search_score(query_norm, meta) > 0
        ]
        filtered.sort(
            key=lambda meta: (
                -self._search_score(query_norm, meta),
                meta.name.lower(),
                meta.identifier.lower(),
            )
        )
        filtered = self._dedupe_results(filtered)

        exact = self._exact_slug_meta(query_norm)
        if exact:
            filtered = [
                meta for meta in filtered if self._search_score(query_norm, meta) >= 20
            ]
            filtered = self._dedupe_results([exact] + filtered)

        if filtered:
            return filtered[:limit]

        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", query_norm):
            return []

        return self._dedupe_results(results)[:limit]

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        query = query.strip()

        if query:
            query_terms = self._query_terms(query)
            if len(query_terms) >= 2:
                direct = self._exact_slug_meta(query)
                if direct:
                    return [direct]

            results = self._search_catalog(query, limit=limit)
            if results:
                return results
        else:
            # Empty query: route through the paginating catalog walker. When
            # the full catalog is already disk-cached this returns it whole and
            # the caller paginates client-side. On a cold cache, bound the walk
            # to `limit` so a browse command renders its first page without
            # walking the entire 50k+ catalog (max_items=0 → unbounded, used
            # only by the offline index builder via search("", limit=0)).
            catalog = self._load_catalog_index(max_items=limit if limit > 0 else 0)
            if catalog:
                return (
                    self._dedupe_results(catalog)[:limit]
                    if limit > 0
                    else self._dedupe_results(catalog)
                )

        # Non-empty query catalog miss, or catalog walker failure: fall back to
        # the lightweight listing API for a best-effort response.
        cache_key = f"clawhub_search_listing_v1_{hashlib.md5(query.encode()).hexdigest()}_{limit}"
        cached = _read_index_cache(cache_key)
        if cached is not None:
            return self._finalize_search_results(
                query,
                [SkillMeta(**s) for s in cached],
                limit,
            )

        try:
            resp = _bounded_http_get(
                f"{self.BASE_URL}/skills",
                params={"search": query, "limit": limit},
                timeout=15,
                max_bytes=MAX_SKILL_METADATA_BYTES,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return []
            data = _bounded_json(resp)
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            return []

        skills_data = data.get("items", data) if isinstance(data, dict) else data
        if not isinstance(skills_data, list):
            return []

        results = []
        for item in skills_data[:limit]:
            slug = item.get("slug")
            if not slug:
                continue
            display_name = item.get("displayName") or item.get("name") or slug
            summary = item.get("summary") or item.get("description") or ""
            tags = self._normalize_tags(item.get("tags", []))
            results.append(
                SkillMeta(
                    name=display_name,
                    description=summary,
                    source="clawhub",
                    identifier=slug,
                    trust_level="community",
                    tags=tags,
                )
            )

        final_results = self._finalize_search_results(query, results, limit)
        _write_index_cache(cache_key, [_skill_meta_to_dict(s) for s in final_results])
        return final_results

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        slug = identifier.split("/")[-1]

        skill_data = self._get_json(f"{self.BASE_URL}/skills/{slug}")
        if not isinstance(skill_data, dict):
            return None

        latest_version = self._resolve_latest_version(slug, skill_data)
        if not latest_version:
            logger.warning(
                "ClawHub fetch failed for %s: could not resolve latest version", slug
            )
            return None

        # Primary method: download the skill as a ZIP bundle from /download
        files = self._download_zip(slug, latest_version)

        # Fallback: try the version metadata endpoint for inline/raw content
        if "SKILL.md" not in files:
            version_data = self._get_json(
                f"{self.BASE_URL}/skills/{slug}/versions/{latest_version}"
            )
            if isinstance(version_data, dict):
                # Files may be nested under version_data["version"]["files"]
                files = self._extract_files(version_data) or files
                if "SKILL.md" not in files:
                    nested = version_data.get("version", {})
                    if isinstance(nested, dict):
                        files = self._extract_files(nested) or files

        if "SKILL.md" not in files:
            logger.warning(
                "ClawHub fetch for %s resolved version %s but could not retrieve file content",
                slug,
                latest_version,
            )
            return None

        return SkillBundle(
            name=slug,
            files=files,
            source="clawhub",
            identifier=slug,
            trust_level="community",
            metadata={
                "source_revision": latest_version,
                "source_name": slug,
            },
        )

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        slug = identifier.split("/")[-1]
        data = self._coerce_skill_payload(
            self._get_json(f"{self.BASE_URL}/skills/{slug}")
        )
        if not isinstance(data, dict):
            return None

        tags = self._normalize_tags(data.get("tags", []))

        return SkillMeta(
            name=data.get("displayName")
            or data.get("name")
            or data.get("slug")
            or slug,
            description=data.get("summary") or data.get("description") or "",
            source="clawhub",
            identifier=data.get("slug") or slug,
            trust_level="community",
            tags=tags,
        )

    def _search_catalog(self, query: str, limit: int = 10) -> List[SkillMeta]:
        cache_key = f"clawhub_search_catalog_v1_{hashlib.md5(f'{query}|{limit}'.encode()).hexdigest()}"
        cached = _read_index_cache(cache_key)
        if cached is not None:
            return [SkillMeta(**s) for s in cached][:limit]

        catalog = self._load_catalog_index()
        if not catalog:
            return []

        results = self._finalize_search_results(query, catalog, limit)
        _write_index_cache(cache_key, [_skill_meta_to_dict(s) for s in results])
        return results

    def _load_catalog_index(self, max_items: int = 0) -> List[SkillMeta]:
        """Walk the ClawHub catalog via cursor pagination.

        ``max_items`` bounds the walk: once at least that many distinct skills
        have been gathered the walk stops early. This is what browse's
        cold-start fallback wants — it only renders one page, so walking the
        entire 50k+ catalog just to slice off the first N is pure waste.
        ``max_items=0`` (the default, used by the offline index builder) means
        walk to exhaustion.

        Caching: only a *complete* catalog (cursor exhausted or page cap) is
        written to the shared ``clawhub_catalog_v1`` cache. A walk truncated by
        ``max_items`` OR the wall-clock budget is partial, so caching it would
        poison the full-catalog cache with an incomplete slice.
        """
        cache_key = "clawhub_catalog_v1"
        cached = _read_index_cache(cache_key)
        if cached is not None:
            return [SkillMeta(**s) for s in cached]

        cursor: Optional[str] = None
        results: List[SkillMeta] = []
        seen: set[str] = set()
        # ClawHub has 50k+ skills as of May 2026 (live E2E walked 49,698 with
        # an active cursor still pending); 750 pages * 200/page = 150k ceiling
        # leaves room for catalog growth. Walk-to-exhaustion typically
        # terminates well before this on `nextCursor` going None — the cap is
        # a safety rail against an infinite-cursor loop.
        max_pages = 750
        # Wall-clock budget is for interactive browse (max_items > 0) only.
        # The offline index builder passes max_items=0 and must walk the full
        # catalog — a 12s cap there ships ~3k skills and trips the deploy
        # health floor (20k).
        deadline = (
            time.monotonic() + self.CATALOG_WALK_BUDGET_SECONDS
            if max_items > 0
            else None
        )
        hit_deadline = False
        hit_max_items = False

        for _ in range(max_pages):
            if deadline is not None and time.monotonic() > deadline:
                hit_deadline = True
                break
            params: Dict[str, Any] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor

            try:
                resp = _bounded_http_get(
                    f"{self.BASE_URL}/skills",
                    params=params,
                    timeout=30,
                    max_bytes=MAX_SKILL_METADATA_BYTES,
                    follow_redirects=True,
                )
                if resp.status_code != 200:
                    break
                data = _bounded_json(resp)
            except (
                httpx.HTTPError,
                json.JSONDecodeError,
                SkillPayloadTooLarge,
                ValueError,
            ):
                break

            items = data.get("items", []) if isinstance(data, dict) else []
            if not isinstance(items, list) or not items:
                break

            for item in items:
                slug = item.get("slug")
                if not isinstance(slug, str) or not slug or slug in seen:
                    continue
                seen.add(slug)
                display_name = item.get("displayName") or item.get("name") or slug
                summary = item.get("summary") or item.get("description") or ""
                tags = self._normalize_tags(item.get("tags", []))
                results.append(
                    SkillMeta(
                        name=display_name,
                        description=summary,
                        source="clawhub",
                        identifier=slug,
                        trust_level="community",
                        tags=tags,
                    )
                )

            cursor = data.get("nextCursor") if isinstance(data, dict) else None
            if not isinstance(cursor, str) or not cursor:
                break

            # Browse's cold-start fallback only renders one page, so stop as
            # soon as we have enough to satisfy the caller's bound. The index
            # builder passes max_items=0 (unbounded) and walks to exhaustion.
            if max_items > 0 and len(results) >= max_items:
                hit_max_items = True
                break

        # Only cache a walk that reached a natural stop (cursor exhausted or
        # page cap). A walk truncated by the wall-clock budget OR by max_items
        # is partial, so writing it would poison the shared full-catalog cache
        # with incomplete data.
        if not hit_deadline and not hit_max_items:
            _write_index_cache(cache_key, [_skill_meta_to_dict(s) for s in results])
        return results

    def _get_json(self, url: str, timeout: int = 20) -> Optional[Any]:
        try:
            # Version metadata may contain inline skill files, so this is a
            # bundle-bearing response rather than harmless catalog metadata.
            # Stream it through the same hard cap used for archive downloads
            # before asking the JSON decoder to allocate object graphs.
            resp = _bounded_http_get(
                url,
                timeout=timeout,
                max_bytes=MAX_SKILL_HTTP_BYTES,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            return _bounded_json(resp)
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            return None

    def _resolve_latest_version(
        self, slug: str, skill_data: Dict[str, Any]
    ) -> Optional[str]:
        latest = skill_data.get("latestVersion")
        if isinstance(latest, dict):
            version = latest.get("version")
            if isinstance(version, str) and version:
                return version

        tags = skill_data.get("tags")
        if isinstance(tags, dict):
            latest_tag = tags.get("latest")
            if isinstance(latest_tag, str) and latest_tag:
                return latest_tag

        versions_data = self._get_json(f"{self.BASE_URL}/skills/{slug}/versions")
        if isinstance(versions_data, list) and versions_data:
            first = versions_data[0]
            if isinstance(first, dict):
                version = first.get("version")
                if isinstance(version, str) and version:
                    return version
        return None

    def _extract_files(self, version_data: Dict[str, Any]) -> Dict[str, str]:
        builder = _BoundedBundleBuilder()
        file_list = version_data.get("files")

        if isinstance(file_list, dict):
            if len(file_list) > MAX_SKILL_ARCHIVE_FILES:
                raise SkillPayloadTooLarge("skill bundle contains too many files")
            for path, value in file_list.items():
                if isinstance(path, str) and isinstance(value, str):
                    builder.add(path, value)
            return builder.text_files()

        if not isinstance(file_list, list):
            return {}
        if len(file_list) > MAX_SKILL_ARCHIVE_FILES:
            raise SkillPayloadTooLarge("skill bundle contains too many files")

        for file_meta in file_list:
            if not isinstance(file_meta, dict):
                continue

            fname = file_meta.get("path") or file_meta.get("name")
            if not fname or not isinstance(fname, str):
                continue

            inline_content = file_meta.get("content")
            if isinstance(inline_content, str):
                builder.add(fname, inline_content)
                continue

            raw_url = (
                file_meta.get("rawUrl")
                or file_meta.get("downloadUrl")
                or file_meta.get("url")
            )
            if isinstance(raw_url, str) and raw_url.startswith("http"):
                content = self._fetch_text(raw_url)
                if content is not None:
                    builder.add(fname, content)

        return builder.text_files()

    def _download_zip(self, slug: str, version: str) -> Dict[str, str]:
        """Download skill as a ZIP bundle from the /download endpoint and extract text files."""
        import io
        import zipfile

        files: Dict[str, str] = {}
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = _bounded_http_get(
                    f"{self.BASE_URL}/download",
                    max_bytes=MAX_SKILL_HTTP_BYTES,
                    params={"slug": slug, "version": version},
                    timeout=30,
                    follow_redirects=True,
                )
                if resp.status_code == 429:
                    try:
                        retry_after = int(resp.headers.get("retry-after", "5"))
                    except (ValueError, TypeError):
                        retry_after = 5
                    retry_after = min(retry_after, 15)  # Cap wait time
                    logger.debug(
                        "ClawHub download rate-limited for %s, retrying in %ds (attempt %d/%d)",
                        slug,
                        retry_after,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(retry_after)
                    continue
                if resp.status_code != 200:
                    logger.debug(
                        "ClawHub ZIP download for %s v%s returned %s",
                        slug,
                        version,
                        resp.status_code,
                    )
                    return files

                expected_entries = _preflight_zip_directory(resp.content)
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    members = [info for info in zf.infolist() if not info.is_dir()]
                    if len(zf.infolist()) != expected_entries:
                        raise ValueError("ZIP entry count disagrees with its directory")
                    if len(members) > MAX_SKILL_ARCHIVE_FILES:
                        raise SkillPayloadTooLarge(
                            "skill archive contains too many files"
                        )
                    declared_total = 0
                    member_names: List[str] = []
                    for info in members:
                        name = _validate_bundle_rel_path(info.filename)
                        if info.file_size > MAX_SKILL_FILE_BYTES:
                            raise SkillPayloadTooLarge(
                                f"archive member {name!r} exceeds the file cap"
                            )
                        declared_total += info.file_size
                        if declared_total > MAX_SKILL_TOTAL_BYTES:
                            raise SkillPayloadTooLarge(
                                "expanded skill archive exceeds the total byte cap"
                            )
                        member_names.append(name)
                    validate_portable_tree_paths(
                        tuple(member_names), field="archive member path"
                    )

                    actual_total = 0
                    for info, name in zip(members, member_names):
                        chunks: List[bytes] = []
                        member_bytes = 0
                        with zf.open(info, "r") as member:
                            while True:
                                remaining_file = MAX_SKILL_FILE_BYTES - member_bytes
                                remaining_total = MAX_SKILL_TOTAL_BYTES - actual_total
                                read_size = min(
                                    64 * 1024,
                                    remaining_file + 1,
                                    remaining_total + 1,
                                )
                                chunk = member.read(max(1, read_size))
                                if not chunk:
                                    break
                                member_bytes += len(chunk)
                                actual_total += len(chunk)
                                if member_bytes > MAX_SKILL_FILE_BYTES:
                                    raise SkillPayloadTooLarge(
                                        f"archive member {name!r} exceeds the file cap"
                                    )
                                if actual_total > MAX_SKILL_TOTAL_BYTES:
                                    raise SkillPayloadTooLarge(
                                        "expanded skill archive exceeds the total byte cap"
                                    )
                                chunks.append(chunk)
                        try:
                            files[name] = b"".join(chunks).decode("utf-8")
                        except UnicodeDecodeError:
                            logger.debug("Skipping non-text file in ZIP: %s", name)

                return files

            except zipfile.BadZipFile:
                logger.warning("ClawHub returned invalid ZIP for %s v%s", slug, version)
                return files
            except (SkillPayloadTooLarge, UnsafePathError, ValueError) as exc:
                logger.warning(
                    "ClawHub ZIP for %s v%s was rejected: %s",
                    slug,
                    version,
                    exc,
                )
                return {}
            except httpx.HTTPError as exc:
                logger.debug(
                    "ClawHub ZIP download failed for %s v%s: %s", slug, version, exc
                )
                return files

        logger.debug("ClawHub ZIP download exhausted retries for %s v%s", slug, version)
        return files

    def _fetch_text(self, url: str) -> Optional[str]:
        resp = _guarded_http_get(url, timeout=20, max_bytes=MAX_SKILL_FILE_BYTES)
        if resp is not None and resp.status_code == 200:
            return _bounded_response_text(resp)
        return None


# ---------------------------------------------------------------------------
# Claude Code marketplace source adapter
# ---------------------------------------------------------------------------


class ClaudeMarketplaceSource(SkillSource):
    """
    Discover skills from Claude Code marketplace repos.
    Marketplace repos contain .claude-plugin/marketplace.json with plugin listings.
    """

    KNOWN_MARKETPLACES = [
        "anthropics/skills",
        "aiskillstore/marketplace",
    ]

    def __init__(self, auth: GitHubAuth):
        self.auth = auth
        # Persistent GitHubSource so rate-limit state survives across the
        # marketplace-index fetch + per-skill inspect calls and can be
        # surfaced to the index builder (see is_rate_limited).
        self.github = GitHubSource(auth=auth)

    def source_id(self) -> str:
        return "claude-marketplace"

    @property
    def is_rate_limited(self) -> bool:
        """Whether the underlying GitHub API hit a rate limit during the crawl."""
        return self.github.is_rate_limited

    def trust_level_for(self, identifier: str) -> str:
        parts = identifier.split("/", 2)
        if len(parts) >= 2:
            repo = f"{parts[0]}/{parts[1]}"
            if repo in TRUSTED_REPOS:
                return "trusted"
        return "community"

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        results: List[SkillMeta] = []
        query_lower = query.lower()

        for marketplace_repo in self.KNOWN_MARKETPLACES:
            plugins = self._fetch_marketplace_index(marketplace_repo)
            for plugin in plugins:
                searchable = (
                    f"{plugin.get('name', '')} {plugin.get('description', '')}".lower()
                )
                if query_lower in searchable:
                    source_path = plugin.get("source", "")
                    if source_path.startswith("./"):
                        identifier = f"{marketplace_repo}/{source_path[2:]}"
                    elif "/" in source_path:
                        identifier = source_path
                    else:
                        identifier = f"{marketplace_repo}/{source_path}"

                    results.append(
                        SkillMeta(
                            name=plugin.get("name", ""),
                            description=plugin.get("description", ""),
                            source="claude-marketplace",
                            identifier=identifier,
                            trust_level=self.trust_level_for(identifier),
                            repo=marketplace_repo,
                        )
                    )

        return results[:limit]

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        # Delegate to GitHub Contents API since marketplace skills live in GitHub repos
        bundle = self.github.fetch(identifier)
        if bundle:
            bundle.source = "claude-marketplace"
        return bundle

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        meta = self.github.inspect(identifier)
        if meta:
            meta.source = "claude-marketplace"
            meta.trust_level = self.trust_level_for(identifier)
        return meta

    def _fetch_marketplace_index(self, repo: str) -> List[dict]:
        """Fetch and parse .claude-plugin/marketplace.json from a repo."""
        cache_key = f"claude_marketplace_{repo.replace('/', '_')}"
        cached = _read_index_cache(cache_key)
        if cached is not None:
            if isinstance(cached, list) and all(
                isinstance(plugin, dict) for plugin in cached
            ):
                return cached
            return []

        url = f"https://api.github.com/repos/{repo}/contents/.claude-plugin/marketplace.json"
        resp = self.github._github_get(
            url,
            headers={
                **self.auth.get_headers(),
                "Accept": "application/vnd.github.v3.raw",
            },
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = _bounded_json(resp)
        except (
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            UnicodeError,
            ValueError,
        ):
            return []
        if not isinstance(data, dict):
            return []
        plugins = data.get("plugins", [])
        if not isinstance(plugins, list) or not all(
            isinstance(plugin, dict) for plugin in plugins
        ):
            return []
        _write_index_cache(cache_key, plugins)
        return plugins


# ---------------------------------------------------------------------------
# LobeHub source adapter
# ---------------------------------------------------------------------------


class LobeHubSource(SkillSource):
    """
    Fetch skills from LobeHub's agent marketplace (14,500+ agents).
    LobeHub agents are system prompt templates — we convert them to SKILL.md on fetch.
    Data lives in GitHub: lobehub/lobe-chat-agents.
    """

    INDEX_URL = "https://chat-agents.lobehub.com/index.json"

    def source_id(self) -> str:
        return "lobehub"

    def trust_level_for(self, identifier: str) -> str:
        return "community"

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        index = self._fetch_index()
        if not index:
            return []

        query_lower = query.lower()
        results: List[SkillMeta] = []

        agents = index.get("agents", index) if isinstance(index, dict) else index
        if not isinstance(agents, list):
            return []

        for agent in agents:
            meta = agent.get("meta", agent)
            title = meta.get("title", agent.get("identifier", ""))
            desc = meta.get("description", "")
            tags = meta.get("tags", [])

            searchable = f"{title} {desc} {' '.join(tags) if isinstance(tags, list) else ''}".lower()
            if query_lower in searchable:
                identifier = agent.get("identifier", title.lower().replace(" ", "-"))
                results.append(
                    SkillMeta(
                        name=identifier,
                        description=desc[:200],
                        source="lobehub",
                        identifier=f"lobehub/{identifier}",
                        trust_level="community",
                        tags=tags if isinstance(tags, list) else [],
                    )
                )

            if len(results) >= limit:
                break

        return results

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        # Strip "lobehub/" prefix if present
        agent_id = (
            identifier.split("/", 1)[-1]
            if identifier.startswith("lobehub/")
            else identifier
        )

        agent_data = self._fetch_agent(agent_id)
        if not agent_data:
            return None

        skill_md = self._convert_to_skill_md(agent_data)
        return SkillBundle(
            name=agent_id,
            files={"SKILL.md": skill_md},
            source="lobehub",
            identifier=f"lobehub/{agent_id}",
            trust_level="community",
        )

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        agent_id = (
            identifier.split("/", 1)[-1]
            if identifier.startswith("lobehub/")
            else identifier
        )
        index = self._fetch_index()
        if not index:
            return None

        agents = index.get("agents", index) if isinstance(index, dict) else index
        if not isinstance(agents, list):
            return None

        for agent in agents:
            if agent.get("identifier") == agent_id:
                meta = agent.get("meta", agent)
                return SkillMeta(
                    name=agent_id,
                    description=meta.get("description", ""),
                    source="lobehub",
                    identifier=f"lobehub/{agent_id}",
                    trust_level="community",
                    tags=meta.get("tags", [])
                    if isinstance(meta.get("tags"), list)
                    else [],
                )
        return None

    def _fetch_index(self) -> Optional[Any]:
        """Fetch the LobeHub agent index (cached for 1 hour)."""
        cache_key = "lobehub_index"
        cached = _read_index_cache(cache_key)
        if cached is not None:
            return cached

        try:
            resp = _bounded_http_get(
                self.INDEX_URL,
                timeout=30,
                max_bytes=MAX_HUB_CATALOG_BYTES,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            data = _bounded_json(resp)
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            return None

        _write_index_cache(cache_key, data)
        return data

    def _fetch_agent(self, agent_id: str) -> Optional[dict]:
        """Fetch a single agent's JSON file."""
        url = f"https://chat-agents.lobehub.com/{agent_id}.json"
        try:
            # This response becomes SKILL.md directly. Bound it while
            # streaming so a hostile Content-Length or chunked body cannot be
            # fully allocated before the common bundle validator runs.
            resp = _bounded_http_get(
                url,
                timeout=15,
                max_bytes=MAX_SKILL_FILE_BYTES,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                parsed = _bounded_json(resp)
                return parsed if isinstance(parsed, dict) else None
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
        ) as e:
            logger.debug("LobeHub agent fetch failed: %s", e)
        return None

    @staticmethod
    def _convert_to_skill_md(agent_data: dict) -> str:
        """Convert a LobeHub agent JSON into SKILL.md format."""
        meta = agent_data.get("meta", agent_data)
        identifier = agent_data.get("identifier", "lobehub-agent")
        title = meta.get("title", identifier)
        description = meta.get("description", "")
        tags = meta.get("tags", [])
        system_role = agent_data.get("config", {}).get("systemRole", "")

        tag_list = tags if isinstance(tags, list) else []
        fm_lines = [
            "---",
            f"name: {identifier}",
            f"description: {description[:500]}",
            "metadata:",
            "  fabric:",
            f"    tags: [{', '.join(str(t) for t in tag_list)}]",
            "  lobehub:",
            "    source: lobehub",
            "---",
        ]

        body_lines = [
            f"# {title}",
            "",
            description,
            "",
            "## Instructions",
            "",
            system_role if system_role else "(No system role defined)",
        ]

        return "\n".join(fm_lines) + "\n\n" + "\n".join(body_lines) + "\n"


# ---------------------------------------------------------------------------
# browse.sh source adapter
# ---------------------------------------------------------------------------


class BrowseShSource(SkillSource):
    """Discover and install site-specific browser automation skills from browse.sh.

    browse.sh (https://browse.sh) is Browserbase's catalog of 200+ SKILL.md files
    that describe how to automate specific websites (Airbnb, Amazon, arXiv, etc.).
    The catalog lives at ``/api/skills`` and each skill's actual SKILL.md content
    is fetched via ``/api/skills/{slug}`` which returns a ``skillMdUrl`` field
    pointing at a CDN-hosted blob — the catalog's ``sourceUrl`` field is a GitHub
    HTML URL whose underlying repository is not always public, so it cannot be
    relied on for content fetch.
    """

    CATALOG_URL = "https://browse.sh/api/skills"
    SKILL_DETAIL_URL = "https://browse.sh/api/skills/{slug}"
    _CACHE_KEY = "browse_sh_catalog"

    def source_id(self) -> str:
        return "browse-sh"

    def trust_level_for(self, identifier: str) -> str:
        return "community"

    def _fetch_catalog(self) -> List[Dict]:
        cached = _read_index_cache(self._CACHE_KEY)
        if cached is not None:
            return cached
        try:
            resp = _bounded_http_get(
                self.CATALOG_URL,
                timeout=20,
                max_bytes=MAX_HUB_CATALOG_BYTES,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return []
            data = _bounded_json(resp)
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            return []
        skills = data.get("skills", []) if isinstance(data, dict) else []
        if isinstance(skills, list):
            _write_index_cache(self._CACHE_KEY, skills)
        return skills if isinstance(skills, list) else []

    def _item_to_meta(self, item: Dict) -> Optional[SkillMeta]:
        slug = item.get("slug", "")
        name = item.get("name", "")
        title = item.get("title", name)
        description = item.get("description", title)
        if not slug or not name:
            return None
        if len(description) > 1024:
            description = description[:1021] + "..."
        return SkillMeta(
            name=name,
            description=description,
            source="browse-sh",
            identifier=f"browse-sh/{slug}",
            trust_level="community",
            tags=item.get("tags", []),
            extra={
                "slug": slug,
                "hostname": item.get("hostname", ""),
                "category": item.get("category", ""),
                "source_url": item.get("sourceUrl", ""),
                "recommended_method": item.get("recommendedMethod", ""),
                "proxies": item.get("proxies", False),
                "install_count": item.get("installCount", 0),
            },
        )

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        catalog = self._fetch_catalog()
        query_lower = query.lower()
        results = []
        for item in catalog:
            text = " ".join([
                item.get("name", ""),
                item.get("title", ""),
                item.get("description", ""),
                item.get("hostname", ""),
                item.get("category", ""),
                " ".join(item.get("tags", [])),
            ]).lower()
            if not query_lower or query_lower in text:
                meta = self._item_to_meta(item)
                if meta:
                    results.append(meta)
            if len(results) >= limit:
                break
        return results

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        slug = self._slug_from_identifier(identifier)
        if not slug:
            return None
        catalog = self._fetch_catalog()
        for item in catalog:
            if item.get("slug") == slug:
                return self._item_to_meta(item)
        return None

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        slug = self._slug_from_identifier(identifier)
        if not slug:
            return None
        catalog = self._fetch_catalog()
        item = next((i for i in catalog if i.get("slug") == slug), None)
        if not item:
            return None

        # Resolve the actual SKILL.md content URL via the per-skill detail
        # endpoint, which returns a ``skillMdUrl`` (CDN blob). The catalog's
        # ``sourceUrl`` is a GitHub HTML link whose underlying repo is not
        # reliably public, so we don't use it for content.
        md_url = self._resolve_skill_md_url(slug, item)
        if not md_url:
            return None
        resp = _guarded_http_get(
            md_url,
            timeout=20,
            max_bytes=MAX_SKILL_FILE_BYTES,
        )
        if resp is None or resp.status_code != 200:
            return None
        try:
            content = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            return None

        meta = self._item_to_meta(item)
        name = meta.name if meta else slug.split("/")[-1]
        return SkillBundle(
            name=name,
            files={"SKILL.md": content},
            source="browse-sh",
            identifier=identifier,
            trust_level="community",
            metadata={
                "slug": slug,
                "hostname": item.get("hostname", ""),
                "source_url": item.get("sourceUrl", ""),
                "skill_md_url": md_url,
            },
        )

    def _resolve_skill_md_url(self, slug: str, item: Dict) -> Optional[str]:
        """Resolve the SKILL.md content URL for a slug.

        Primary path: hit ``/api/skills/{slug}`` and read ``skillMdUrl``.
        Fallback: if the catalog item already has a ``raw.githubusercontent.com``
        ``sourceUrl`` (some entries may), use it directly.
        """
        try:
            detail = _bounded_http_get(
                self.SKILL_DETAIL_URL.format(slug=slug),
                timeout=20,
                max_bytes=MAX_SKILL_METADATA_BYTES,
                follow_redirects=True,
            )
            if detail.status_code == 200:
                data = _bounded_json(detail)
                if isinstance(data, dict):
                    md_url = data.get("skillMdUrl")
                    if isinstance(md_url, str) and md_url.startswith("http"):
                        return md_url
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            pass

        source_url = item.get("sourceUrl", "") if isinstance(item, dict) else ""
        if source_url and "raw.githubusercontent.com" in source_url:
            return source_url
        return None

    def _slug_from_identifier(self, identifier: str) -> str:
        """Extract slug from identifier like 'browse-sh/airbnb.com/search-listings-abc'."""
        if identifier.startswith("browse-sh/"):
            return identifier[len("browse-sh/") :]
        return identifier


# ---------------------------------------------------------------------------
# Official optional skills source adapter
# ---------------------------------------------------------------------------


class OptionalSkillSource(SkillSource):
    """
    Fetch skills from the optional-skills/ directory shipped with the repo.

    These skills are official (maintained by Fabric contributors) but not activated
    by default — they don't appear in the system prompt and aren't copied to
    ~/.fabric/skills/ during setup.  They are discoverable via the Skills Hub
    (search / install / inspect) and labelled "official" with "builtin" trust.
    """

    OFFICIAL_REPO = "ObliviousOdin/fabric"

    def __init__(self):
        from fabric_constants import get_optional_skills_dir

        self._optional_dir = get_optional_skills_dir(
            Path(__file__).parent.parent / "optional-skills"
        )

    def source_id(self) -> str:
        return "official"

    def trust_level_for(self, identifier: str) -> str:
        return "builtin"

    # -- search -----------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        results: List[SkillMeta] = []
        query_lower = query.lower()

        for meta in self._scan_all():
            searchable = f"{meta.name} {meta.description} {' '.join(meta.tags)}".lower()
            if query_lower in searchable:
                results.append(meta)
            if len(results) >= limit:
                break

        return results

    # -- fetch ------------------------------------------------------------

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        # identifier format: "official/category/skill" or "official/skill"
        rel = (
            identifier.split("/", 1)[-1]
            if identifier.startswith("official/")
            else identifier
        )
        skill_dir = self._optional_dir / rel

        # Guard against path traversal (e.g. "official/../../etc")
        try:
            resolved = skill_dir.resolve()
            optional_root = self._optional_dir.resolve()
            if not resolved.is_relative_to(optional_root):
                return None
        except (OSError, ValueError):
            return None

        if not resolved.is_dir():
            # Try searching by skill name only (last segment)
            skill_name = rel.rsplit("/", 1)[-1]
            skill_dir = self._find_skill_dir(skill_name)
            if not skill_dir:
                return None
        else:
            skill_dir = resolved

        files: Dict[str, Union[str, bytes]] = {}
        try:
            snapshot = capture_tree_snapshot(
                skill_dir,
                max_file_bytes=MAX_SKILL_FILE_BYTES,
                max_total_bytes=MAX_SKILL_TOTAL_BYTES,
                max_files=MAX_SKILL_ARCHIVE_FILES,
            )
        except (OSError, UnsafePathError, ValueError):
            return None
        builder = _BoundedBundleBuilder()
        for record in snapshot.files:
            parts = record.relative_path.parts
            if (
                any(part.startswith(".") for part in parts)
                or "__pycache__" in parts
                or record.relative_path.suffix == ".pyc"
            ):
                continue
            builder.add(record.relative_path.as_posix(), record.content)
        files.update(builder.files)

        if not files:
            return None

        # Determine category from directory structure
        name = skill_dir.name

        return SkillBundle(
            name=name,
            files=files,
            source="official",
            identifier=f"official/{skill_dir.relative_to(self._optional_dir)}",
            trust_level="builtin",
        )

    # -- inspect ----------------------------------------------------------

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        rel = (
            identifier.split("/", 1)[-1]
            if identifier.startswith("official/")
            else identifier
        )
        skill_name = rel.rsplit("/", 1)[-1]

        for meta in self._scan_all():
            if meta.name == skill_name:
                return meta
        return None

    # -- internal helpers -------------------------------------------------

    def _find_skill_dir(self, name: str) -> Optional[Path]:
        """Find a skill directory by name anywhere in optional-skills/."""
        if not self._optional_dir.is_dir():
            return None
        for skill_md in self._optional_dir.rglob("SKILL.md"):
            if is_excluded_skill_path(skill_md):
                continue
            if skill_md.parent.name == name:
                return skill_md.parent
        return None

    def _scan_all(self) -> List[SkillMeta]:
        """Enumerate all optional skills with metadata."""
        if not self._optional_dir.is_dir():
            return []

        results: List[SkillMeta] = []
        for skill_md in sorted(self._optional_dir.rglob("SKILL.md")):
            if is_excluded_skill_path(skill_md):
                continue
            parent = skill_md.parent

            try:
                payload, _state = _read_bounded_regular_file(
                    skill_md,
                    max_bytes=MAX_SKILL_FILE_BYTES,
                )
                content = payload.decode("utf-8")
            except (
                OSError,
                SkillPayloadTooLarge,
                UnicodeDecodeError,
                ValueError,
            ):
                continue

            fm = self._parse_frontmatter(content)
            name = fm.get("name", parent.name)
            desc = fm.get("description", "")
            tags = extract_skill_metadata(fm).get("tags", [])

            rel_path = parent.relative_to(self._optional_dir).as_posix()

            results.append(
                SkillMeta(
                    name=name,
                    description=desc[:200],
                    source="official",
                    identifier=f"official/{rel_path}",
                    trust_level="builtin",
                    repo=self.OFFICIAL_REPO,
                    # The centralized skills index consumes repo-root-relative paths.
                    path=f"optional-skills/{rel_path}",
                    tags=tags if isinstance(tags, list) else [],
                )
            )

        return results

    @staticmethod
    def _parse_frontmatter(content: str) -> dict:
        """Parse YAML frontmatter from SKILL.md content."""
        if not content.startswith("---"):
            return {}
        match = re.search(r"\n---\s*\n", content[3:])
        if not match:
            return {}
        yaml_text = content[3 : match.start() + 3]
        try:
            parsed = yaml.safe_load(yaml_text)
            return parsed if isinstance(parsed, dict) else {}
        except yaml.YAMLError:
            return {}


# ---------------------------------------------------------------------------
# Shared cache helpers (used by multiple adapters)
# ---------------------------------------------------------------------------


def _read_index_cache(key: str) -> Optional[Any]:
    """Read cached data if not expired."""
    cache_file = _index_cache_dir() / f"{key}.json"
    if not cache_file.exists():
        return None
    try:
        with hub_mutation_scope(_skills_dir().parent):
            data, state = _read_bounded_json_file(cache_file)
            _validate_hub_mutation_binding()
        if time.time() - state.st_mtime > INDEX_CACHE_TTL:
            return None
        return data
    except (
        OSError,
        RuntimeError,
        json.JSONDecodeError,
        SkillPayloadTooLarge,
        ValueError,
    ):
        return None


def _write_index_cache(key: str, data: Any) -> None:
    """Write data to cache."""
    try:
        normalized = json.loads(json.dumps(data, ensure_ascii=False, default=str))
        _validate_bounded_json_graph(normalized)
        if (
            len(json.dumps(normalized, ensure_ascii=False).encode("utf-8"))
            > MAX_HUB_CATALOG_BYTES
        ):
            raise SkillPayloadTooLarge("Hub cache payload exceeds the byte cap")
        with hub_mutation_scope(_skills_dir().parent):
            index_cache_dir = _index_cache_dir()
            if os.name == "nt":
                index_cache_dir.mkdir(parents=True, exist_ok=True)
            else:
                index_fd = _open_hub_directory(index_cache_dir, create=True)
                os.close(index_fd)
            _validate_hub_mutation_binding()
            # Cache entries contain untrusted catalog text. Keep Hub internals
            # out of repository/text searches without a pathname-following
            # writer that could escape during a profile rename.
            ignore_file = _hub_dir() / ".ignore"
            ignore_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            ignore_parent_fd: int | None = None
            ignore_fd: int | None = None
            try:
                try:
                    if os.name == "nt":
                        ignore_fd = os.open(ignore_file, ignore_flags, 0o600)
                    else:
                        ignore_parent_fd = _open_hub_directory(
                            ignore_file.parent,
                            create=True,
                        )
                        ignore_fd = os.open(
                            ignore_file.name,
                            ignore_flags,
                            0o600,
                            dir_fd=ignore_parent_fd,
                        )
                except FileExistsError:
                    pass
                if ignore_fd is not None:
                    payload = b"# Exclude hub internals from search tools\n*\n"
                    view = memoryview(payload)
                    while view:
                        written = os.write(ignore_fd, view)
                        if written <= 0:
                            raise OSError("short Hub ignore-file write")
                        view = view[written:]
                    os.fsync(ignore_fd)
                    if ignore_parent_fd is not None:
                        os.fsync(ignore_parent_fd)
            finally:
                if ignore_fd is not None:
                    os.close(ignore_fd)
                if ignore_parent_fd is not None:
                    os.close(ignore_parent_fd)
            cache_file = index_cache_dir / f"{key}.json"
            HubLockFile(path=cache_file)._save_atomic(normalized)
    except (OSError, RuntimeError, SkillPayloadTooLarge, ValueError) as e:
        logger.debug("Could not write cache: %s", e)


def _skill_meta_to_dict(meta: SkillMeta) -> dict:
    """Convert a SkillMeta to a dict for caching."""
    return {
        "name": meta.name,
        "description": meta.description,
        "source": meta.source,
        "identifier": meta.identifier,
        "trust_level": meta.trust_level,
        "repo": meta.repo,
        "path": meta.path,
        "tags": meta.tags,
        "extra": meta.extra,
    }


# ---------------------------------------------------------------------------
# Lock file management
# ---------------------------------------------------------------------------


class HubDurabilityUncertainError(OSError):
    """A metadata replace happened but parent-directory durability is unknown."""


def _fsync_parent_directory(path: Path, *, attempts: int = 3) -> None:
    """Repair/confirm rename durability before a transaction can commit."""

    _validate_hub_mutation_if_active()
    if os.name == "nt":
        return
    if _hub_relative_parts(path.parent) is not None:
        parent_fd = _open_hub_directory(path.parent, create=False)
    else:
        parent_fd = os.open(
            path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    try:
        last_error: OSError | None = None
        for _attempt in range(attempts):
            try:
                os.fsync(parent_fd)
                _validate_hub_mutation_if_active()
                return
            except OSError as exc:
                last_error = exc
        raise HubDurabilityUncertainError(
            f"Could not confirm parent-directory durability for {path}"
        ) from last_error
    finally:
        os.close(parent_fd)


def _validate_hub_lock_data(data: object) -> dict:
    """Validate the complete pure JSON schema used by Hub lock snapshots."""

    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("installed"), dict)
    ):
        raise ValueError("invalid Hub lock-file schema")
    last_transaction_id = data.get("last_transaction_id")
    if last_transaction_id is not None and not isinstance(last_transaction_id, str):
        raise ValueError("invalid Hub lock transaction marker")
    installed = data["installed"]
    if not all(
        isinstance(name, str) and isinstance(entry, dict)
        for name, entry in installed.items()
    ):
        raise ValueError("invalid Hub installed-entry schema")
    for entry in installed.values():
        files = entry.get("files", [])
        metadata = entry.get("metadata", {})
        authority = entry.get("source_authority")
        if (
            not isinstance(files, list)
            or not all(isinstance(item, str) for item in files)
            or not isinstance(metadata, dict)
            or (authority is not None and not isinstance(authority, dict))
        ):
            raise ValueError("invalid Hub installed-entry schema")
        if authority is not None:
            HubSourceAuthority.from_dict(authority)
    return data


def _canonical_json_sha256(value: object) -> str:
    """Digest one JSON value with an unambiguous, deterministic encoding."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class HubLockFile:
    """Manages skills/.hub/lock.json — tracks provenance of installed hub skills."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path if path is not None else _lock_file()
        self._uses_profile_path = path is None

    def _mutation_home(self) -> Path:
        if self._uses_profile_path:
            return _skills_dir().parent
        return self.path.parent

    def load(self, *, strict: bool = False) -> dict:
        if _ACTIVE_HUB_MUTATION.get() is None:
            with hub_mutation_scope(self._mutation_home()):
                return self.load(strict=strict)
        _validate_hub_mutation_binding()
        if not _hub_exists(self.path):
            return {"version": 1, "installed": {}}
        try:
            data, _state = _read_bounded_json_file(
                self.path,
                max_bytes=MAX_HUB_STATE_BYTES,
                require_unique=True,
            )
            _validate_hub_mutation_binding()
            if isinstance(data, dict) and "version" not in data:
                data["version"] = 1
            return _validate_hub_lock_data(data)
        except (
            json.JSONDecodeError,
            OSError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            if strict:
                raise ValueError("Hub lock file is unreadable or invalid")
            return {"version": 1, "installed": {}}

    def _save_atomic(self, data: dict) -> None:
        _validate_hub_mutation_if_active()
        payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        if _ACTIVE_HUB_MUTATION.get() is None:
            raise RuntimeError("active Hub mutation scope is required")
        if _hub_relative_parts(self.path) is None:
            raise HubInstallError("Hub state path is outside the active profile")
        _hub_write_regular_file_atomic(self.path, payload)
        _fsync_parent_directory(self.path)

    def save(self, data: dict) -> None:
        with hub_mutation_scope(self._mutation_home()):
            self._save_atomic(data)

    def ensure_parent_durable(self) -> None:
        _fsync_parent_directory(self.path)

    @staticmethod
    def _install_entry(
        *,
        source: str,
        identifier: str,
        trust_level: str,
        scan_verdict: str,
        skill_hash: str,
        install_path: str,
        files: List[str],
        metadata: Optional[Dict[str, Any]],
        transaction_id: str | None,
        installed_at: str | None,
        attested_tree_sha256: str | None = None,
        source_authority: HubSourceAuthority | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "source": source,
            "identifier": identifier,
            "trust_level": trust_level,
            "scan_verdict": scan_verdict,
            "content_hash": skill_hash,
            "install_path": install_path,
            "files": files,
            "metadata": metadata or {},
            "installed_at": installed_at or now,
            "updated_at": now,
        }
        if transaction_id is not None:
            entry["transaction_id"] = transaction_id
        if attested_tree_sha256 is not None:
            entry["attested_tree_sha256"] = attested_tree_sha256
        if source_authority is not None:
            entry["source_authority"] = source_authority.as_dict()
        return entry

    def record_install(
        self,
        name: str,
        source: str,
        identifier: str,
        trust_level: str,
        scan_verdict: str,
        skill_hash: str,
        install_path: str,
        files: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        transaction_id: str | None = None,
    ) -> None:
        # Validate both the skill name and the install path SHAPE before
        # writing into lock.json. A poisoned lock entry is the precondition
        # for the uninstall_skill rmtree-escape; reject malformed input at
        # write time so the file never carries the bad state.
        safe_name = _validate_skill_name(name)
        safe_install_path = _normalize_lock_install_path(install_path, safe_name)
        with hub_mutation_scope(self._mutation_home()):
            data = self.load(strict=True)
            previous = data["installed"].get(safe_name)
            installed_at = (
                previous.get("installed_at") if isinstance(previous, dict) else None
            )
            data["installed"][safe_name] = self._install_entry(
                source=source,
                identifier=identifier,
                trust_level=trust_level,
                scan_verdict=scan_verdict,
                skill_hash=skill_hash,
                install_path=safe_install_path,
                files=files,
                metadata=metadata,
                transaction_id=transaction_id,
                installed_at=installed_at,
            )
            self._save_atomic(data)

    def record_uninstall(self, name: str) -> None:
        safe_name = _validate_skill_name(name)
        with hub_mutation_scope(self._mutation_home()):
            data = self.load(strict=True)
            data["installed"].pop(safe_name, None)
            self._save_atomic(data)

    def get_installed(self, name: str) -> Optional[dict]:
        data = self.load()
        return data["installed"].get(name)

    def list_installed(self) -> List[dict]:
        data = self.load()
        result = []
        for name, entry in data["installed"].items():
            result.append({"name": name, **entry})
        return result


# ---------------------------------------------------------------------------
# Taps management
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HubMetadataMutationOutcome:
    status: str
    message: str
    changed: bool = False

    @property
    def committed(self) -> bool:
        return self.status == "committed"

    def __bool__(self) -> bool:
        return self.committed and self.changed


class TapsManager:
    """Manages the taps.json file — custom GitHub repo sources."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path if path is not None else _taps_file()
        self._uses_profile_path = path is None

    def _mutation_home(self) -> Path:
        if self._uses_profile_path:
            return _skills_dir().parent
        return self.path.parent

    def load(self, *, strict: bool = False) -> List[dict]:
        if _ACTIVE_HUB_MUTATION.get() is None:
            with hub_mutation_scope(self._mutation_home()):
                return self.load(strict=strict)
        _validate_hub_mutation_binding()
        if not _hub_exists(self.path):
            return []
        try:
            data, _state = _read_bounded_json_file(
                self.path,
                max_bytes=MAX_HUB_STATE_BYTES,
            )
            _validate_hub_mutation_binding()
            taps = data.get("taps") if isinstance(data, dict) else None
            if not isinstance(taps, list) or not all(
                isinstance(tap, dict) for tap in taps
            ):
                raise ValueError("invalid taps schema")
            return taps
        except (
            json.JSONDecodeError,
            OSError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            if strict:
                raise ValueError("Hub taps file is unreadable or invalid")
            return []

    def _publish_locked(
        self,
        *,
        previous: List[dict],
        desired: List[dict],
        message: str,
    ) -> HubMetadataMutationOutcome:
        metadata_file = HubLockFile(path=self.path)
        try:
            metadata_file._save_atomic({"taps": desired})
        except BaseException as exc:
            # os.replace may already have published the desired bytes before a
            # parent fsync error. Inspect and repair durability before deciding
            # whether the typed result is committed, rolled back, or pending.
            try:
                observed = self.load(strict=True)
                metadata_file.ensure_parent_durable()
            except BaseException as reconcile_exc:
                return HubMetadataMutationOutcome(
                    status="recovery_pending",
                    message=f"{message}; metadata recovery pending: {reconcile_exc}",
                )
            if observed == desired:
                return HubMetadataMutationOutcome(
                    status="committed",
                    message=message,
                    changed=desired != previous,
                )
            if observed == previous:
                return HubMetadataMutationOutcome(
                    status="rolled_back",
                    message=f"{message}; publication rolled back: {exc}",
                )
            return HubMetadataMutationOutcome(
                status="recovery_pending",
                message=f"{message}; published taps have an unknown post-image",
            )
        return HubMetadataMutationOutcome(
            status="committed",
            message=message,
            changed=desired != previous,
        )

    def save(self, taps: List[dict]) -> HubMetadataMutationOutcome:
        with hub_mutation_scope(self._mutation_home()):
            previous = self.load(strict=True)
            return self._publish_locked(
                previous=previous,
                desired=taps,
                message="Saved Hub taps",
            )

    def add(self, repo: str, path: str = "skills/") -> HubMetadataMutationOutcome:
        """Add a tap. Returns False if already exists."""
        with hub_mutation_scope(self._mutation_home()):
            taps = self.load(strict=True)
            if any(t.get("repo") == repo for t in taps if isinstance(t, dict)):
                return HubMetadataMutationOutcome(
                    status="committed",
                    message=f"Tap already configured: {repo}",
                )
            desired = [*taps, {"repo": repo, "path": path}]
            return self._publish_locked(
                previous=taps,
                desired=desired,
                message=f"Added tap: {repo}",
            )

    def remove(self, repo: str) -> HubMetadataMutationOutcome:
        """Remove a tap by repo name. Returns False if not found."""
        with hub_mutation_scope(self._mutation_home()):
            taps = self.load(strict=True)
            new_taps = [
                tap
                for tap in taps
                if not isinstance(tap, dict) or tap.get("repo") != repo
            ]
            if len(new_taps) == len(taps):
                return HubMetadataMutationOutcome(
                    status="committed",
                    message=f"Tap not configured: {repo}",
                )
            return self._publish_locked(
                previous=taps,
                desired=new_taps,
                message=f"Removed tap: {repo}",
            )

    def list_taps(self) -> List[dict]:
        return self.load()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def append_audit_log(
    action: str,
    skill_name: str,
    source: str,
    trust_level: str,
    verdict: str,
    extra: str = "",
) -> None:
    """Append a line to the audit log."""
    if _ACTIVE_HUB_MUTATION.get() is None:
        audit_path = _audit_log()
        profile_home = Path(os.path.abspath(_skills_dir().parent))
        try:
            Path(os.path.abspath(audit_path)).relative_to(profile_home)
            mutation_home = profile_home
        except ValueError:
            mutation_home = audit_path.parent
        with hub_mutation_scope(mutation_home):
            append_audit_log(
                action,
                skill_name,
                source,
                trust_level,
                verdict,
                extra,
            )
        return
    audit_log = _audit_log()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [timestamp, action, skill_name, f"{source}:{trust_level}", verdict]
    if extra:
        parts.append(extra)
    line = (
        " ".join(str(part).replace("\r", "\\r").replace("\n", "\\n") for part in parts)
        + "\n"
    )
    try:
        _validate_hub_mutation_binding()
        flags = (
            os.O_WRONLY
            | os.O_APPEND
            | os.O_CREAT
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        parent_fd: int | None = None
        if os.name == "nt":
            audit_log.parent.mkdir(parents=True, exist_ok=True)
            _validate_hub_mutation_binding()
            descriptor = os.open(audit_log, flags, 0o600)
        else:
            parent_fd = _open_hub_directory(
                audit_log.parent,
                create=True,
            )
            _validate_hub_mutation_binding()
            descriptor = os.open(
                audit_log.name,
                flags,
                0o600,
                dir_fd=parent_fd,
            )
        try:
            view = memoryview(line.encode("utf-8"))
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short Hub audit write")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            if parent_fd is not None:
                os.close(parent_fd)
        _validate_hub_mutation_binding()
    except (OSError, RuntimeError) as e:
        logger.debug("Could not write audit log: %s", e)


def _append_audit_log_best_effort(*args: Any, **kwargs: Any) -> None:
    """A non-authoritative audit append cannot replace a terminal outcome."""

    try:
        append_audit_log(*args, **kwargs)
    except BaseException as exc:
        logger.warning("Skills Hub audit append failed after mutation: %s", exc)


# ---------------------------------------------------------------------------
# Hub operations (high-level)
# ---------------------------------------------------------------------------


def ensure_hub_dirs() -> None:
    """Create the .hub directory structure if it doesn't exist."""
    with hub_mutation_scope(_skills_dir().parent):
        hub_dir = _hub_dir()
        lock_file = _lock_file()
        audit_log = _audit_log()
        taps_file = _taps_file()
        _validate_hub_mutation_binding()
        if os.name == "nt":
            hub_dir.mkdir(parents=True, exist_ok=True)
            _quarantine_dir().mkdir(exist_ok=True)
            _index_cache_dir().mkdir(exist_ok=True)
        else:
            for directory in (hub_dir, _quarantine_dir(), _index_cache_dir()):
                directory_fd = _open_hub_directory(directory, create=True)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        _validate_hub_mutation_binding()
        for path, payload in (
            (lock_file, b'{"version": 1, "installed": {}}\n'),
            (audit_log, b""),
            (taps_file, b'{"taps": []}\n'),
        ):
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            parent_fd: int | None = None
            try:
                if os.name == "nt" or _hub_relative_parts(path.parent) is None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fd = os.open(path, flags, 0o600)
                else:
                    parent_fd = _open_hub_directory(path.parent, create=True)
                    fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
            except FileExistsError:
                if parent_fd is not None:
                    os.close(parent_fd)
                continue
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short Hub metadata initialization write")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
                if parent_fd is not None:
                    os.fsync(parent_fd)
                    os.close(parent_fd)


_HUB_TRANSACTION_SCHEMA_VERSION = 3
_HUB_LEGACY_TRANSACTION_SCHEMA_VERSION = 2
_HUB_PREPARATION_SCHEMA_VERSION = 1
_HUB_PREPARATION_FILE = "preparation.json"


class HubInstallError(ValueError):
    """A Hub installation could not commit without risking user data."""


@dataclass(frozen=True)
class HubMutationOutcome:
    """Typed terminal/recovery state for one public Hub mutation."""

    status: str
    message: str
    transaction_id: str | None = None
    install_path: Path | None = None
    cleanup_pending: Tuple[str, ...] = ()

    @property
    def committed(self) -> bool:
        return self.status == "committed"

    def __iter__(self):
        """Compatibility for legacy ``ok, message = uninstall_skill(...)``."""

        yield self.committed
        yield self.message


def _materialize_snapshot_candidate(
    snapshot: TreeSnapshot,
    destination: Path,
) -> TreeSnapshot:
    """Rebuild a private candidate solely from one attested byte snapshot."""

    _validate_hub_mutation_binding()
    try:
        if os.name == "nt":
            destination.mkdir(mode=0o700, parents=False, exist_ok=False)
            directories = {destination}
            for item in snapshot.files:
                _validate_hub_mutation_binding()
                target = destination.joinpath(*item.relative_path.parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                directories.update((target.parent, *target.parent.parents))
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                descriptor = os.open(target, flags, item.mode & 0o777)
                try:
                    view = memoryview(item.content)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise OSError("short snapshot candidate write")
                        view = view[written:]
                    if hasattr(os, "fchmod"):
                        os.fchmod(descriptor, item.mode & 0o777)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        else:
            directory_flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            file_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            parent_fd = _open_hub_directory(destination.parent, create=False)
            try:
                os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
                destination_fd = os.open(
                    destination.name,
                    directory_flags,
                    dir_fd=parent_fd,
                )
                try:
                    for item in snapshot.files:
                        directory_fd = os.dup(destination_fd)
                        try:
                            for component in item.relative_path.parts[:-1]:
                                try:
                                    child_fd = os.open(
                                        component,
                                        directory_flags,
                                        dir_fd=directory_fd,
                                    )
                                except FileNotFoundError:
                                    os.mkdir(
                                        component,
                                        mode=0o700,
                                        dir_fd=directory_fd,
                                    )
                                    child_fd = os.open(
                                        component,
                                        directory_flags,
                                        dir_fd=directory_fd,
                                    )
                                os.close(directory_fd)
                                directory_fd = child_fd
                            file_fd = os.open(
                                item.relative_path.parts[-1],
                                file_flags,
                                item.mode & 0o777,
                                dir_fd=directory_fd,
                            )
                            try:
                                view = memoryview(item.content)
                                while view:
                                    written = os.write(file_fd, view)
                                    if written <= 0:
                                        raise OSError("short snapshot candidate write")
                                    view = view[written:]
                                os.fchmod(file_fd, item.mode & 0o777)
                                os.fsync(file_fd)
                            finally:
                                os.close(file_fd)
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                    os.fsync(destination_fd)
                finally:
                    os.close(destination_fd)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            _validate_hub_mutation_binding()
        rebuilt = _capture_hub_tree(destination)
        _validate_hub_mutation_binding()
        if (
            rebuilt.tree_sha256 != snapshot.tree_sha256
            or rebuilt.content_sha256 != snapshot.content_sha256
        ):
            raise HubInstallError("Private candidate differs from scanned snapshot")
        return rebuilt
    except BaseException:
        # No journal or external effect exists yet. The UUID transaction root
        # remains for abandoned-preparation quarantine; never recurse through
        # a caller-controlled path here.
        raise


def _directory_identity(path: Path) -> tuple[int, int]:
    try:
        inspected = _hub_lstat(path)
    except HubInstallError:
        raise
    except OSError as exc:
        raise HubInstallError(f"Could not inspect directory: {path}") from exc
    if not stat.S_ISDIR(inspected.st_mode):
        raise HubInstallError(f"Expected a directory: {path}")
    return inspected.st_dev, inspected.st_ino


def _windows_atomic_move_directory(
    source: Path,
    destination: Path,
    *,
    expected_identity: tuple[int, int],
    expected_native_identity: tuple[int, bytes] | None,
) -> tuple[int, int]:  # pragma: no cover - Windows
    """Rename one exact opened directory between two pinned Hub parents."""

    import ctypes
    from ctypes import wintypes

    if expected_native_identity is None:
        raise HubInstallError(
            "Windows transaction move requires a full native source identity"
        )

    source_parts = _hub_relative_parts(source)
    destination_parts = _hub_relative_parts(destination)
    if (
        source_parts is None
        or destination_parts is None
        or not source_parts
        or not destination_parts
    ):
        raise HubInstallError("Windows transaction move must stay below the profile")
    destination_parent_parts = destination_parts[:-1]
    if tuple(destination_parent_parts[: len(source_parts)]) == tuple(source_parts):
        raise HubInstallError("Windows transaction destination is inside its source")

    anchor_handle: int | None = None
    home_handle: int | None = None
    source_parent_handles: list[int] = []
    destination_parent_handles: list[int] = []
    source_handle: int | None = None
    try:
        binding = _ACTIVE_HUB_MUTATION.get()
        if binding is None:
            raise RuntimeError("active Hub mutation scope is required")
        anchor_handle = duplicate_mutation_home_handle(
            binding.home,
            binding.lease,
            kind="skills",
        )
        if anchor_handle is None:
            raise HubInstallError("Windows move profile capability is unavailable")
        anchor_identity, _links, _attributes = _windows_cleanup_handle_information(
            anchor_handle
        )
        home_handle, home_identity = _windows_reopen_cleanup_home(
            anchor_handle,
            share_write=not destination_parent_parts,
        )
        if home_identity != anchor_identity:
            raise HubInstallError("Windows move profile generation changed")

        source_parent_handle = home_handle
        source_parent_by_parts: dict[tuple[str, ...], int] = {(): home_handle}
        for index, component in enumerate(source_parts[:-1]):
            prefix = tuple(source_parts[: index + 1])
            handle, _identity, _links, _attributes = _windows_open_cleanup_relative(
                source_parent_handle,
                component,
                directory=True,
                delete_access=False,
                share_write=prefix == tuple(destination_parent_parts),
            )
            source_parent_handles.append(handle)
            source_parent_handle = handle
            source_parent_by_parts[prefix] = handle
        source_handle, _source_identity, _links, source_attributes = (
            _windows_open_cleanup_relative(
                source_parent_handle,
                source_parts[-1],
                directory=True,
                delete_access=True,
            )
        )
        source_native_identity = _windows_cleanup_extended_identity(source_handle)
        if source_native_identity != expected_native_identity:
            raise HubInstallError("Transaction source changed native identity")
        canonical_source = binding.home.joinpath(*source_parts)
        named_source = canonical_source.lstat()
        if (
            not stat.S_ISDIR(named_source.st_mode)
            or (named_source.st_dev, named_source.st_ino) != expected_identity
        ):
            raise HubInstallError("Transaction source changed identity")

        destination_parent_key = tuple(destination_parent_parts)
        destination_parent_handle = source_parent_by_parts.get(destination_parent_key)
        if destination_parent_handle is None:
            destination_parent_handle = home_handle
            for index, component in enumerate(destination_parent_parts):
                handle, _identity, _links, _attributes = _windows_open_cleanup_relative(
                    destination_parent_handle,
                    component,
                    directory=True,
                    delete_access=False,
                    share_write=index == len(destination_parent_parts) - 1,
                )
                destination_parent_handles.append(handle)
                destination_parent_handle = handle

        source_parent_native = _windows_cleanup_extended_identity(source_parent_handle)
        destination_parent_native = _windows_cleanup_extended_identity(
            destination_parent_handle
        )
        if source_parent_native[0] != source_native_identity[0] or (
            destination_parent_native[0] != source_native_identity[0]
        ):
            raise HubInstallError("Windows transaction move crosses volumes")

        source_entries = _windows_cleanup_directory_entries(
            source_parent_handle,
            max_entries=MAX_HUB_DIRECTORY_ENTRIES,
        )
        source_name = source_parts[-1].casefold()
        source_matches = [
            entry for entry in source_entries if entry.name.casefold() == source_name
        ]
        if (
            len(source_matches) != 1
            or source_matches[0].file_id != source_native_identity[1]
        ):
            raise HubInstallError("Transaction source namespace changed identity")

        destination_entries = _windows_cleanup_directory_entries(
            destination_parent_handle,
            max_entries=MAX_HUB_DIRECTORY_ENTRIES,
        )
        destination_name = destination_parts[-1]
        destination_folded = destination_name.casefold()
        if any(
            entry.name.casefold() == destination_folded for entry in destination_entries
        ):
            raise HubInstallError("Transaction destination appeared concurrently")

        class FILE_RENAME_INFO_HEADER(ctypes.Structure):
            _fields_ = [
                ("ReplaceIfExists", ctypes.c_ubyte),
                ("RootDirectory", wintypes.HANDLE),
                ("FileNameLength", wintypes.DWORD),
                ("FileName", wintypes.WCHAR * 1),
            ]

        encoded_name = destination_name.encode("utf-16-le")
        # The native contract requires at least sizeof(FILE_RENAME_INFORMATION)
        # plus the variable name bytes. Keep an additional zero WCHAR so the
        # same buffer is also safely terminated for filesystem filters that
        # inspect it as a string.
        rename_size = ctypes.sizeof(FILE_RENAME_INFO_HEADER) + len(encoded_name) + 2
        rename_buffer = ctypes.create_string_buffer(rename_size)
        rename_info = FILE_RENAME_INFO_HEADER.from_buffer(rename_buffer)
        rename_info.ReplaceIfExists = 0
        rename_info.RootDirectory = wintypes.HANDLE(destination_parent_handle)
        rename_info.FileNameLength = len(encoded_name)
        ctypes.memmove(
            ctypes.addressof(rename_buffer) + FILE_RENAME_INFO_HEADER.FileName.offset,
            encoded_name,
            len(encoded_name),
        )

        class STATUS_OR_POINTER(ctypes.Union):
            _fields_ = [("Status", wintypes.LONG), ("Pointer", ctypes.c_void_p)]

        class IO_STATUS_BLOCK(ctypes.Structure):
            _anonymous_ = ("result",)
            _fields_ = [
                ("result", STATUS_OR_POINTER),
                ("Information", ctypes.c_size_t),
            ]

        file_rename_information = 10
        io_status = IO_STATUS_BLOCK()
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        ntdll.NtSetInformationFile.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(IO_STATUS_BLOCK),
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.c_int,
        ]
        ntdll.NtSetInformationFile.restype = wintypes.LONG
        status = int(
            ntdll.NtSetInformationFile(
                wintypes.HANDLE(source_handle),
                ctypes.byref(io_status),
                rename_buffer,
                rename_size,
                file_rename_information,
            )
        )
        if status < 0:
            ntdll.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
            ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
            error = int(ntdll.RtlNtStatusToDosError(status))
            raise OSError(error, "could not rename exact Windows transaction source")

        source_after = _windows_cleanup_directory_entries(
            source_parent_handle,
            max_entries=MAX_HUB_DIRECTORY_ENTRIES,
        )
        if any(entry.name.casefold() == source_name for entry in source_after):
            raise HubInstallError("Transaction source name remains after rename")
        destination_after = _windows_cleanup_directory_entries(
            destination_parent_handle,
            max_entries=MAX_HUB_DIRECTORY_ENTRIES,
        )
        destination_matches = [
            entry
            for entry in destination_after
            if entry.name.casefold() == destination_folded
        ]
        directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            len(destination_matches) != 1
            or destination_matches[0].file_id != source_native_identity[1]
            or not destination_matches[0].attributes & directory_flag
            or destination_matches[0].attributes & reparse_flag
            or not source_attributes & directory_flag
        ):
            raise HubInstallError("Transaction destination post-image is invalid")
        _validate_hub_mutation_binding()
        return expected_identity
    except HubInstallError:
        raise
    except (OSError, UnicodeError) as exc:
        raise HubInstallError("Could not safely rename Windows Hub directory") from exc
    finally:
        if source_handle is not None:
            _windows_close_cleanup_handle(source_handle)
        for handle in reversed(destination_parent_handles):
            _windows_close_cleanup_handle(handle)
        for handle in reversed(source_parent_handles):
            _windows_close_cleanup_handle(handle)
        if home_handle is not None:
            _windows_close_cleanup_handle(home_handle)
        if anchor_handle is not None:
            _windows_close_cleanup_handle(anchor_handle)


def _atomic_move_directory(
    source: Path,
    destination: Path,
    *,
    expected_identity: tuple[int, int],
    expected_native_identity: tuple[int, bytes] | None = None,
) -> tuple[int, int]:
    """Rename one identity-attested directory without a copy/delete fallback."""

    _validate_hub_mutation_binding()
    if _hub_exists(destination):
        raise HubInstallError(f"Transaction destination already exists: {destination}")

    if os.name == "nt":  # pragma: no cover - exercised by native Windows CI
        return _windows_atomic_move_directory(
            source,
            destination,
            expected_identity=expected_identity,
            expected_native_identity=expected_native_identity,
        )

    if all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")):
        directory_flags = (
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        )
        source_parent_fd = _open_hub_directory(source.parent, create=False)
        destination_parent_fd = _open_hub_directory(
            destination.parent,
            create=True,
        )
        source_fd: int | None = None
        try:
            source_fd = os.open(
                source.name,
                directory_flags,
                dir_fd=source_parent_fd,
            )
            opened = os.fstat(source_fd)
            named = os.stat(
                source.name,
                dir_fd=source_parent_fd,
                follow_symlinks=False,
            )
            opened_identity = (opened.st_dev, opened.st_ino)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or not stat.S_ISDIR(named.st_mode)
                or opened_identity != expected_identity
                or (named.st_dev, named.st_ino) != expected_identity
            ):
                raise HubInstallError("Transaction source changed identity")
            try:
                os.stat(
                    destination.name,
                    dir_fd=destination_parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise HubInstallError("Transaction destination appeared concurrently")
            os.replace(
                source.name,
                destination.name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=destination_parent_fd,
            )
            _validate_hub_mutation_binding()
            promoted = os.stat(
                destination.name,
                dir_fd=destination_parent_fd,
                follow_symlinks=False,
            )
            if (promoted.st_dev, promoted.st_ino) != expected_identity:
                raise HubInstallError("Promoted directory changed identity")
            os.fsync(source_parent_fd)
            if destination_parent_fd != source_parent_fd:
                os.fsync(destination_parent_fd)
            return expected_identity
        finally:
            if source_fd is not None:
                os.close(source_fd)
            os.close(destination_parent_fd)
            os.close(source_parent_fd)

    raise HubInstallError("Descriptor-relative Hub rename is unavailable")


def _write_hub_journal(transaction_root: Path, journal: dict) -> None:
    _validate_hub_mutation_binding()
    HubLockFile(path=transaction_root / "journal.json")._save_atomic(journal)


def _write_hub_preparation(
    transaction_root: Path,
    *,
    state: str,
    old_lock_sha256: str | None = None,
    new_lock_sha256: str | None = None,
) -> None:
    """Durably classify a transaction before any externally visible move."""

    if state not in {"private_only", "effects_may_start"}:
        raise HubInstallError("Hub transaction preparation state is invalid")
    record = {
        "schema_version": _HUB_PREPARATION_SCHEMA_VERSION,
        "transaction_id": transaction_root.name,
        "state": state,
    }
    if state == "effects_may_start":
        for label, digest in (
            ("old_lock_sha256", old_lock_sha256),
            ("new_lock_sha256", new_lock_sha256),
        ):
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise HubInstallError("Hub transaction preparation proof is invalid")
            record[label] = digest
    HubLockFile(path=transaction_root / _HUB_PREPARATION_FILE)._save_atomic(record)


def _load_hub_preparation(transaction_root: Path) -> dict | None:
    path = transaction_root / _HUB_PREPARATION_FILE
    if not _hub_exists(path):
        return None
    try:
        record, _state = _read_bounded_json_file(
            path,
            max_bytes=16 * 1024,
            require_unique=True,
        )
    except (OSError, ValueError, SkillPayloadTooLarge) as exc:
        raise HubInstallError("Hub transaction preparation is unreadable") from exc
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != _HUB_PREPARATION_SCHEMA_VERSION
        or record.get("transaction_id") != transaction_root.name
        or record.get("state") not in {"private_only", "effects_may_start"}
    ):
        raise HubInstallError("Hub transaction preparation is invalid")
    if record["state"] == "effects_may_start" and (
        re.fullmatch(r"[0-9a-f]{64}", record.get("old_lock_sha256", "")) is None
        or re.fullmatch(r"[0-9a-f]{64}", record.get("new_lock_sha256", "")) is None
    ):
        raise HubInstallError("Hub transaction preparation proof is invalid")
    return record


def _journal_less_transaction_is_private(transaction_root: Path) -> bool:
    """Return true only when a missing journal cannot hide a live-tree move."""

    preparation = _load_hub_preparation(transaction_root)
    if preparation is not None:
        if preparation["state"] != "private_only":
            return False
        children = _hub_list_directory(
            transaction_root,
            max_entries=MAX_HUB_DIRECTORY_ENTRIES,
        )
        names = tuple(child.name for child in children)
        return names in {
            (_HUB_PREPARATION_FILE,),
            ("candidate", _HUB_PREPARATION_FILE),
        }
    # Legacy v2 created its private candidate before attempting the journal.
    # A still-present candidate proves promotion never occurred. Empty roots,
    # backups, and unknown shapes are ambiguous and must remain blocking.
    children = _hub_list_directory(
        transaction_root,
        max_entries=MAX_HUB_DIRECTORY_ENTRIES,
    )
    return tuple(child.name for child in children) == ("candidate",)


def _load_hub_journal(transaction_root: Path) -> dict:
    _validate_hub_mutation_binding()
    try:
        journal, _state = _read_bounded_json_file(
            transaction_root / "journal.json",
            max_bytes=MAX_HUB_STATE_BYTES,
            require_unique=True,
        )
        _validate_hub_mutation_binding()
    except (
        OSError,
        json.JSONDecodeError,
        SkillPayloadTooLarge,
        ValueError,
    ) as exc:
        raise HubInstallError("Hub transaction journal is unreadable") from exc
    if (
        not isinstance(journal, dict)
        or journal.get("schema_version")
        not in {
            _HUB_LEGACY_TRANSACTION_SCHEMA_VERSION,
            _HUB_TRANSACTION_SCHEMA_VERSION,
        }
        or journal.get("transaction_id") != transaction_root.name
    ):
        raise HubInstallError("Hub transaction journal is invalid")
    return journal


def _update_hub_journal(
    transaction_root: Path,
    journal: dict,
    *,
    phase: str,
) -> None:
    journal["phase"] = phase
    _write_hub_journal(transaction_root, journal)


def _recover_hub_transaction_locked(
    transaction_root: Path,
    *,
    lock: HubLockFile,
) -> HubMutationOutcome:
    journal = _load_hub_journal(transaction_root)
    preparation = _load_hub_preparation(transaction_root)
    journal_file = HubLockFile(path=transaction_root / "journal.json")
    # A previous atomic replace may have reached the namespace before its
    # parent fsync failed. Repair that durability uncertainty before trusting
    # any phase, including an already-visible ``committed`` phase.
    journal_file.ensure_parent_durable()
    operation = journal.get("operation", "install")
    if operation not in {"install", "uninstall"}:
        raise HubInstallError("Hub transaction operation is invalid")
    skill_name = _validate_skill_name(journal.get("skill_name", ""))
    install_rel = _normalize_lock_install_path(
        journal.get("install_path", ""),
        skill_name,
    )
    quarantine_name = normalize_relative_path(
        journal.get("quarantine_name", ""),
        field="quarantine name",
        allow_nested=False,
    )
    install_dir = _bound_install_path(install_rel, skill_name)
    quarantine_path = _quarantine_dir() / quarantine_name
    raw_candidate_name = journal.get("candidate_name")
    if raw_candidate_name is None:
        # Compatibility with the first journal schema, which promoted the
        # quarantine directory itself.
        candidate_path = quarantine_path
    else:
        candidate_name = normalize_relative_path(
            raw_candidate_name,
            field="candidate name",
            allow_nested=False,
        )
        candidate_path = transaction_root / candidate_name
    backup_path = transaction_root / "backup"
    source_sha256 = journal.get("source_sha256")
    old_tree_sha256 = journal.get("old_tree_sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise HubInstallError("Hub transaction source digest is invalid")
    raw_source_identity = journal.get("source_identity")
    source_identity = (
        tuple(raw_source_identity)
        if (
            isinstance(raw_source_identity, list)
            and len(raw_source_identity) == 2
            and all(isinstance(value, int) for value in raw_source_identity)
        )
        else None
    )
    if operation == "install" and source_identity is None:
        raise HubInstallError("Hub transaction source identity is invalid")
    source_authority = HubSourceAuthority.from_dict(journal.get("source_authority"))
    source_content_sha256 = journal.get("source_content_sha256")
    if operation == "install" and (
        not isinstance(source_content_sha256, str) or len(source_content_sha256) != 64
    ):
        raise HubInstallError("Hub transaction content digest is invalid")
    old_lock_data = journal.get("old_lock_data")
    try:
        old_lock_data = _validate_hub_lock_data(old_lock_data)
    except ValueError as exc:
        raise HubInstallError("Hub transaction lock snapshot is invalid") from exc
    schema_version = journal.get("schema_version")
    if schema_version == _HUB_TRANSACTION_SCHEMA_VERSION:
        if preparation is None:
            raise HubInstallError("Hub transaction preparation proof is missing")
        old_lock_sha256 = journal.get("old_lock_sha256")
        if (
            not isinstance(old_lock_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", old_lock_sha256) is None
            or old_lock_sha256 != _canonical_json_sha256(old_lock_data)
        ):
            raise HubInstallError("Hub transaction lock snapshot proof is invalid")
        if (
            preparation["state"] == "effects_may_start"
            and preparation["old_lock_sha256"] != old_lock_sha256
        ):
            raise HubInstallError("Hub transaction preparation proof disagrees")
    phase = journal.get("phase")
    new_entry = journal.get("new_entry")
    if operation == "install":
        if not isinstance(new_entry, dict):
            raise HubInstallError("Hub transaction lock post-image is invalid")
        source_files = journal.get("source_files")
        if source_files is None:
            # Compatibility with journals created before source_files became
            # an independent recovery proof. New journals always carry it.
            source_files = new_entry.get("files")
        if not isinstance(source_files, list) or not all(
            isinstance(item, str) for item in source_files
        ):
            raise HubInstallError("Hub transaction source file list is invalid")
        expected_content_hash = f"sha256:{source_content_sha256[:16]}"
        immutable_postimage_is_consistent = not (
            _normalize_lock_install_path(
                new_entry.get("install_path", ""),
                skill_name,
            )
            != install_rel
            or new_entry.get("attested_tree_sha256") != source_sha256
            or new_entry.get("transaction_id") != transaction_root.name
            or new_entry.get("source_authority") != source_authority.as_dict()
            or new_entry.get("identifier") != source_authority.remote_identifier
            or new_entry.get("source") != source_authority.bundle_source
            or new_entry.get("trust_level") != source_authority.trust_level
        )
        terminal_postimage_is_consistent = (
            immutable_postimage_is_consistent
            and new_entry.get("files") == source_files
            and new_entry.get("content_hash") == expected_content_hash
        )
        if schema_version == _HUB_TRANSACTION_SCHEMA_VERSION and phase == "committed":
            new_entry_sha256 = journal.get("new_entry_sha256")
            if (
                not isinstance(new_entry_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", new_entry_sha256) is None
                or new_entry_sha256 != _canonical_json_sha256(new_entry)
            ):
                raise HubInstallError(
                    "Hub transaction lock post-image proof is invalid"
                )
        if not immutable_postimage_is_consistent or (
            phase == "committed" and not terminal_postimage_is_consistent
        ):
            raise HubInstallError("Hub transaction lock post-image is inconsistent")
    raw_cleanup_pending = journal.get("cleanup_pending", [])
    if not isinstance(raw_cleanup_pending, list) or not all(
        isinstance(item, str) for item in raw_cleanup_pending
    ):
        raise HubInstallError("Hub transaction cleanup state is invalid")

    current_lock = lock.load(strict=True)
    expected_new_lock = copy.deepcopy(old_lock_data)
    if operation == "install":
        expected_new_lock["installed"][skill_name] = new_entry
    else:
        expected_new_lock["installed"].pop(skill_name, None)
        expected_new_lock["last_transaction_id"] = transaction_root.name
    try:
        _validate_hub_lock_data(expected_new_lock)
    except ValueError as exc:
        raise HubInstallError("Hub transaction lock post-image is invalid") from exc
    postimage_proof_matches = True
    if (
        schema_version == _HUB_TRANSACTION_SCHEMA_VERSION
        and preparation is not None
        and preparation["state"] == "effects_may_start"
        and preparation["new_lock_sha256"] != _canonical_json_sha256(expected_new_lock)
    ):
        if phase == "committed":
            raise HubInstallError("Hub transaction preparation proof disagrees")
        postimage_proof_matches = False
    if (
        schema_version == _HUB_LEGACY_TRANSACTION_SCHEMA_VERSION
        and phase == "committed"
        and operation == "install"
    ):
        legacy_terminal_entry = current_lock["installed"].get(skill_name)
        if (
            isinstance(legacy_terminal_entry, dict)
            and legacy_terminal_entry.get("transaction_id") == transaction_root.name
            and legacy_terminal_entry != new_entry
        ):
            raise HubInstallError(
                "Legacy committed Hub transaction disagrees with its lock post-image"
            )

    if phase == "rolled_back" and not _hub_exists(backup_path):
        old_skill_entry = old_lock_data["installed"].get(skill_name)
        current_skill_entry = current_lock["installed"].get(skill_name)
        later_owner_superseded = isinstance(
            current_skill_entry, dict
        ) and current_skill_entry.get("transaction_id") not in {
            None,
            transaction_root.name,
        }
        later_removal_superseded = (
            old_skill_entry is not None
            and current_skill_entry is None
            and current_lock.get("last_transaction_id")
            not in {
                None,
                old_lock_data.get("last_transaction_id"),
                transaction_root.name,
            }
        )
        transaction_ownership_is_rolled_back_or_superseded = (
            current_skill_entry == old_skill_entry
            or later_owner_superseded
            or later_removal_superseded
        )
        install_exists = _hub_exists(install_dir)
        missing_owned_preimage = old_tree_sha256 is not None and not install_exists
        later_external_removal = (
            missing_owned_preimage and current_skill_entry == old_skill_entry
        )
        if operation == "install":
            active_is_promoted_candidate = (
                install_exists and _directory_identity(install_dir) == source_identity
            )
            rolled_back_state_is_terminal = (
                transaction_ownership_is_rolled_back_or_superseded
                and not active_is_promoted_candidate
                and (
                    not missing_owned_preimage
                    or later_removal_superseded
                    or later_external_removal
                )
            )
        else:
            rolled_back_state_is_terminal = (
                transaction_ownership_is_rolled_back_or_superseded
                and (
                    install_exists or later_removal_superseded or later_external_removal
                )
            )
        if rolled_back_state_is_terminal:
            lock.ensure_parent_durable()
            journal_file.ensure_parent_durable()
            message = f"Hub {operation} was rolled back"
            if later_external_removal:
                message += "; installed tree was later removed externally"
            return HubMutationOutcome(
                status="rolled_back",
                message=message,
                transaction_id=transaction_root.name,
                install_path=install_dir if install_exists else None,
                cleanup_pending=tuple(raw_cleanup_pending),
            )

    install_snapshot_error: UnsafePathError | None = None
    backup_snapshot_error: UnsafePathError | None = None
    try:
        install_snapshot = (
            _capture_hub_tree(install_dir) if _hub_exists(install_dir) else None
        )
    except UnsafePathError as exc:
        install_snapshot = None
        install_snapshot_error = exc
    try:
        backup_snapshot = (
            _capture_hub_tree(backup_path) if _hub_exists(backup_path) else None
        )
    except UnsafePathError as exc:
        backup_snapshot = None
        backup_snapshot_error = exc
    backup_matches_preimage = (
        backup_snapshot is None
        if old_tree_sha256 is None
        else (
            backup_snapshot is not None
            and backup_snapshot.tree_sha256 == old_tree_sha256
        )
    )

    if phase == "committed" and current_lock == expected_new_lock:
        if operation == "install":
            terminal_state_is_exact = (
                install_snapshot_error is None
                and backup_snapshot_error is None
                and install_snapshot is not None
                and install_snapshot.root_identity == source_identity
                and install_snapshot.tree_sha256 == source_sha256
                and install_snapshot.content_sha256 == source_content_sha256
                and backup_matches_preimage
            )
        else:
            terminal_state_is_exact = (
                install_snapshot_error is None
                and backup_snapshot_error is None
                and install_snapshot is None
                and backup_matches_preimage
            )
        if not terminal_state_is_exact:
            # The transaction was committed, but the active tree changed
            # afterward (for example, a user edit). Preserve every private
            # recovery artifact instead of rolling that later state back or
            # allowing GC to erase the backup.
            safe_cleanup_pending = [
                marker
                for marker in raw_cleanup_pending
                if marker.startswith("quarantine:")
            ]
            if safe_cleanup_pending != raw_cleanup_pending:
                journal["cleanup_pending"] = safe_cleanup_pending
                _update_hub_journal(
                    transaction_root,
                    journal,
                    phase="committed",
                )
            lock.ensure_parent_durable()
            journal_file.ensure_parent_durable()
            return HubMutationOutcome(
                status="committed",
                message=f"Hub {operation} commit has later tree changes",
                transaction_id=transaction_root.name,
                install_path=None,
                cleanup_pending=tuple(safe_cleanup_pending),
            )
        lock.ensure_parent_durable()
        journal_file.ensure_parent_durable()
        return HubMutationOutcome(
            status="committed",
            message=f"Hub {operation} committed",
            transaction_id=transaction_root.name,
            install_path=install_dir if operation == "install" else None,
            cleanup_pending=tuple(raw_cleanup_pending),
        )

    if phase == "committed" and current_lock != old_lock_data:
        # A later lock mutation superseded this already-durable terminal
        # record. Do not reinterpret that newer state, but also do not let GC
        # discard this transaction's private recovery material automatically.
        safe_cleanup_pending = [
            marker for marker in raw_cleanup_pending if marker.startswith("quarantine:")
        ]
        if safe_cleanup_pending != raw_cleanup_pending:
            journal["cleanup_pending"] = safe_cleanup_pending
            _update_hub_journal(transaction_root, journal, phase="committed")
        lock.ensure_parent_durable()
        journal_file.ensure_parent_durable()
        return HubMutationOutcome(
            status="committed",
            message=f"Hub {operation} commit was superseded",
            transaction_id=transaction_root.name,
            install_path=None,
            cleanup_pending=tuple(safe_cleanup_pending),
        )

    current_without_skill = copy.deepcopy(current_lock)
    old_without_skill = copy.deepcopy(old_lock_data)
    current_without_skill["installed"].pop(skill_name, None)
    old_without_skill["installed"].pop(skill_name, None)
    recoverable_unproven_install_postimage = (
        operation == "install"
        and not postimage_proof_matches
        and current_without_skill == old_without_skill
    )
    if current_lock not in (old_lock_data, expected_new_lock) and not (
        recoverable_unproven_install_postimage
    ):
        raise HubInstallError("Hub lock changed outside the transaction pre/post-image")
    if install_snapshot_error is not None or backup_snapshot_error is not None:
        raise HubInstallError(
            "Hub transaction tree exceeds safe recovery bounds"
        ) from (install_snapshot_error or backup_snapshot_error)

    if operation == "install":
        assert isinstance(source_content_sha256, str)
        expected_files = (
            [item.relative_path.as_posix() for item in install_snapshot.files]
            if install_snapshot is not None
            else None
        )
        lock_entry_matches_tree = (
            new_entry.get("files") == expected_files
            and new_entry.get("content_hash") == expected_content_hash
        )
        destination_is_candidate = (
            install_snapshot is not None
            and install_snapshot.root_identity == source_identity
        )
        destination_is_new = (
            destination_is_candidate
            and install_snapshot.tree_sha256 == source_sha256
            and install_snapshot.content_sha256 == source_content_sha256
        )
        lock_is_new = (
            postimage_proof_matches
            and current_lock == expected_new_lock
            and lock_entry_matches_tree
        )
        committed_postimage = (
            destination_is_new and lock_is_new and backup_matches_preimage
        )
    else:
        destination_is_new = False
        lock_is_new = current_lock == expected_new_lock
        committed_postimage = (
            install_snapshot is None and lock_is_new and backup_matches_preimage
        )

    if committed_postimage:
        lock.ensure_parent_durable()
        cleanup_pending = list(raw_cleanup_pending)
        if _hub_exists(backup_path) and "backup" not in cleanup_pending:
            cleanup_pending.append("backup")
        quarantine_marker = f"quarantine:{quarantine_name}"
        if _hub_exists(quarantine_path) and quarantine_marker not in cleanup_pending:
            cleanup_pending.append(quarantine_marker)
        journal["cleanup_pending"] = cleanup_pending
        if phase != "committed" or cleanup_pending != raw_cleanup_pending:
            _update_hub_journal(transaction_root, journal, phase="committed")
        journal_file.ensure_parent_durable()
        return HubMutationOutcome(
            status="committed",
            message=f"Hub {operation} committed",
            transaction_id=transaction_root.name,
            install_path=install_dir if operation == "install" else None,
            cleanup_pending=tuple(cleanup_pending),
        )

    if operation == "install":
        # Preserve the promoted candidate back inside its private transaction
        # tree. It was rebuilt solely from snapshot bytes and is never confused
        # with the mutable download quarantine.
        if destination_is_candidate:
            if _hub_exists(candidate_path):
                raise HubInstallError("Cannot preserve promoted tree during rollback")
            assert install_snapshot is not None
            _atomic_move_directory(
                install_dir,
                candidate_path,
                expected_identity=install_snapshot.root_identity,
                expected_native_identity=install_snapshot.native_root_identity,
            )
        elif install_snapshot is not None:
            if (
                old_tree_sha256 is None
                or install_snapshot.tree_sha256 != old_tree_sha256
            ):
                raise HubInstallError("Hub transaction destination has unknown bytes")

    if _hub_exists(backup_path):
        if _hub_exists(install_dir):
            raise HubInstallError("Cannot restore Hub backup over an existing tree")
        if backup_snapshot is None:
            raise HubInstallError("Cannot restore an unverified Hub backup")
        _atomic_move_directory(
            backup_path,
            install_dir,
            expected_identity=backup_snapshot.root_identity,
            expected_native_identity=backup_snapshot.native_root_identity,
        )
    elif old_tree_sha256 is not None and not _hub_exists(install_dir):
        raise HubInstallError("Hub transaction backup is missing")

    lock._save_atomic(old_lock_data)
    cleanup_pending = list(raw_cleanup_pending)
    if _hub_exists(candidate_path) and "candidate" not in cleanup_pending:
        cleanup_pending.append("candidate")
    quarantine_marker = f"quarantine:{quarantine_name}"
    if _hub_exists(quarantine_path) and quarantine_marker not in cleanup_pending:
        cleanup_pending.append(quarantine_marker)
    journal["cleanup_pending"] = cleanup_pending
    _update_hub_journal(transaction_root, journal, phase="rolled_back")
    lock.ensure_parent_durable()
    journal_file.ensure_parent_durable()
    return HubMutationOutcome(
        status="rolled_back",
        message=f"Hub {operation} failed and was rolled back",
        transaction_id=transaction_root.name,
        install_path=install_dir if _hub_exists(install_dir) else None,
        cleanup_pending=tuple(cleanup_pending),
    )


def _recover_hub_transactions_locked(
    *, lock: HubLockFile
) -> Tuple[HubMutationOutcome, ...]:
    transactions_root = _hub_dir() / "transactions"
    transactions_fd = _open_hub_directory(transactions_root, create=True)
    os.close(transactions_fd)
    outcomes: List[HubMutationOutcome] = []
    for transaction_root in _hub_list_directory(
        transactions_root,
        max_entries=MAX_HUB_TRANSACTIONS,
    ):
        if len(transaction_root.name) != 36:
            raise HubInstallError("Invalid Hub transaction identifier")
        if not _hub_is_directory(transaction_root):
            raise HubInstallError("Unsafe Hub transaction entry")
        try:
            uuid.UUID(transaction_root.name)
        except ValueError as exc:
            raise HubInstallError("Invalid Hub transaction identifier") from exc
        if not _hub_exists(transaction_root / "journal.json"):
            if not _journal_less_transaction_is_private(transaction_root):
                raise HubInstallError(
                    "Journal-less Hub transaction may contain external effects"
                )
            abandoned_root = _hub_dir() / "abandoned"
            abandoned_fd = _open_hub_directory(abandoned_root, create=True)
            os.close(abandoned_fd)
            abandoned = abandoned_root / transaction_root.name
            if _hub_exists(abandoned):
                raise HubInstallError("Hub abandoned-transaction path already exists")
            abandoned_identity = _directory_identity(transaction_root)
            abandoned_native_identity: tuple[int, bytes] | None = None
            if os.name == "nt":
                with _windows_pin_hub_snapshot_root(transaction_root) as (
                    _canonical_transaction,
                    pinned_identity,
                    abandoned_native_identity,
                ):
                    if pinned_identity != abandoned_identity:
                        raise HubInstallError(
                            "Hub transaction changed before abandonment"
                        )
            _atomic_move_directory(
                transaction_root,
                abandoned,
                expected_identity=abandoned_identity,
                expected_native_identity=abandoned_native_identity,
            )
            continue
        outcomes.append(_recover_hub_transaction_locked(transaction_root, lock=lock))
    return tuple(outcomes)


def _ensure_hub_transaction_capacity() -> None:
    """Refuse to create a transaction that would exceed the recovery bound."""

    transactions_root = _hub_dir() / "transactions"
    transactions_fd = _open_hub_directory(transactions_root, create=True)
    os.close(transactions_fd)
    try:
        existing = _hub_list_directory(
            transactions_root,
            max_entries=MAX_HUB_TRANSACTIONS,
        )
    except HubInstallError as exc:
        raise HubInstallError(
            "Hub transaction capacity is exceeded; run `fabric skills gc` "
            "before retrying"
        ) from exc
    if len(existing) >= MAX_HUB_TRANSACTIONS:
        raise HubInstallError(
            "Hub transaction capacity is full; run `fabric skills gc` before retrying"
        )


def _retain_hub_transaction_for_inspection(
    transaction_root: Path,
    *,
    expected_identity: tuple[int, int],
    expected_native_identity: tuple[int, bytes] | None,
) -> Path:
    """Move one terminal-but-unprunable record out of the active queue."""

    retained_root = _hub_dir() / "retained-transactions"
    retained_fd = _open_hub_directory(retained_root, create=True)
    os.close(retained_fd)
    destination = retained_root / transaction_root.name
    if _hub_exists(destination):
        raise HubInstallError("Retained Hub transaction path already exists")
    _atomic_move_directory(
        transaction_root,
        destination,
        expected_identity=expected_identity,
        expected_native_identity=expected_native_identity,
    )
    return destination


def gc_hub_transaction_artifacts() -> dict[str, int]:
    """Recover and prune a bounded batch of attested Hub transactions.

    Unlike the ordinary recovery path this explicit escape hatch can make
    progress when a legacy transaction directory already exceeds the normal
    cap.  Payload artifacts are deleted only when their journal digest
    matches; a terminal record directory is pruned only after it contains its
    journal and nothing else.
    """

    removed = 0
    retained = 0
    transactions_removed = 0
    transactions_retained = 0
    with hub_mutation_scope(_skills_dir().parent):
        lock = HubLockFile()
        transactions_root = _hub_dir() / "transactions"
        transactions_fd = _open_hub_directory(transactions_root, create=True)
        os.close(transactions_fd)
        transaction_roots, truncated = _hub_list_directory_batch(
            transactions_root,
            max_entries=MAX_HUB_GC_BATCH,
        )
        for transaction_root in transaction_roots:
            if len(transaction_root.name) != 36 or not _hub_is_directory(
                transaction_root
            ):
                raise HubInstallError("Invalid Hub transaction entry during GC")
            try:
                uuid.UUID(transaction_root.name)
            except ValueError as exc:
                raise HubInstallError("Invalid Hub transaction identifier") from exc
            transaction_identity = _directory_identity(transaction_root)
            transaction_native_identity: tuple[int, bytes] | None = None
            if os.name == "nt":
                with _windows_pin_hub_snapshot_root(transaction_root) as (
                    _canonical_transaction,
                    pinned_identity,
                    transaction_native_identity,
                ):
                    if pinned_identity != transaction_identity:
                        raise HubInstallError(
                            "Hub transaction changed during GC admission"
                        )
            if not _hub_exists(transaction_root / "journal.json"):
                if not _journal_less_transaction_is_private(transaction_root):
                    raise HubInstallError(
                        "Journal-less Hub transaction may contain external effects"
                    )
                abandoned_root = _hub_dir() / "abandoned"
                abandoned_fd = _open_hub_directory(abandoned_root, create=True)
                os.close(abandoned_fd)
                abandoned = abandoned_root / transaction_root.name
                if _hub_exists(abandoned):
                    raise HubInstallError(
                        "Hub abandoned-transaction path already exists"
                    )
                _atomic_move_directory(
                    transaction_root,
                    abandoned,
                    expected_identity=transaction_identity,
                    expected_native_identity=transaction_native_identity,
                )
                transactions_removed += 1
                continue
            journal = _load_hub_journal(transaction_root)
            _recover_hub_transaction_locked(transaction_root, lock=lock)
            journal = _load_hub_journal(transaction_root)
            if journal.get("phase") not in {"committed", "rolled_back"}:
                retained += len(journal.get("cleanup_pending", []))
                continue
            pending = journal.get("cleanup_pending", [])
            if not isinstance(pending, list) or not all(
                isinstance(item, str) for item in pending
            ):
                raise HubInstallError("Hub transaction cleanup state is invalid")
            source_sha256 = journal.get("source_sha256")
            old_tree_sha256 = journal.get("old_tree_sha256")
            quarantine_name = normalize_relative_path(
                journal.get("quarantine_name", ""),
                field="quarantine name",
                allow_nested=False,
            )
            remaining: list[str] = []
            for marker in pending:
                if marker == "backup":
                    artifact = transaction_root / "backup"
                    expected_digest = old_tree_sha256
                elif marker == "candidate":
                    candidate_name = normalize_relative_path(
                        journal.get("candidate_name", "candidate"),
                        field="candidate name",
                        allow_nested=False,
                    )
                    artifact = transaction_root / candidate_name
                    expected_digest = source_sha256
                elif marker.startswith("quarantine:"):
                    marker_name = normalize_relative_path(
                        marker.partition(":")[2],
                        field="quarantine marker",
                        allow_nested=False,
                    )
                    if marker_name != quarantine_name:
                        raise HubInstallError("Hub quarantine cleanup marker disagrees")
                    artifact = _quarantine_dir() / marker_name
                    expected_digest = source_sha256
                else:
                    raise HubInstallError("Unknown Hub cleanup artifact")

                if not _hub_exists(artifact):
                    continue
                if not isinstance(expected_digest, str) or len(expected_digest) != 64:
                    remaining.append(marker)
                    retained += 1
                    continue
                try:
                    snapshot = _capture_hub_tree(artifact)
                except UnsafePathError:
                    remaining.append(marker)
                    retained += 1
                    continue
                if snapshot.tree_sha256 != expected_digest:
                    remaining.append(marker)
                    retained += 1
                    continue
                _hub_remove_tree(
                    artifact,
                    expected_identity=snapshot.root_identity,
                    expected_native_identity=snapshot.native_root_identity,
                )
                removed += 1
            if remaining:
                if remaining != pending:
                    journal["cleanup_pending"] = remaining
                    _write_hub_journal(transaction_root, journal)
                _retain_hub_transaction_for_inspection(
                    transaction_root,
                    expected_identity=transaction_identity,
                    expected_native_identity=transaction_native_identity,
                )
                transactions_retained += 1
                continue

            # Every named artifact is now absent.  Do not recursively erase
            # unknown transaction content: only a journal-only terminal root
            # is an attested record eligible for pruning.
            try:
                children = _hub_list_directory(
                    transaction_root,
                    max_entries=MAX_HUB_DIRECTORY_ENTRIES,
                    expected_identity=transaction_identity,
                )
            except HubInstallError as exc:
                if not str(exc).startswith("Hub directory contains more than"):
                    raise
                retained += 1
                _retain_hub_transaction_for_inspection(
                    transaction_root,
                    expected_identity=transaction_identity,
                    expected_native_identity=transaction_native_identity,
                )
                transactions_retained += 1
                continue
            allowed_record_files = {"journal.json"}
            if _hub_exists(transaction_root / _HUB_PREPARATION_FILE):
                allowed_record_files.add(_HUB_PREPARATION_FILE)
            unknown_children = [
                child for child in children if child.name not in allowed_record_files
            ]
            if unknown_children:
                retained += len(unknown_children)
                _retain_hub_transaction_for_inspection(
                    transaction_root,
                    expected_identity=transaction_identity,
                    expected_native_identity=transaction_native_identity,
                )
                transactions_retained += 1
                continue
            _hub_remove_tree(
                transaction_root,
                expected_identity=transaction_identity,
                expected_native_identity=transaction_native_identity,
            )
            transactions_removed += 1
    return {
        "removed": removed,
        "retained": retained,
        "transactions_removed": transactions_removed,
        "transactions_retained": transactions_retained,
        "truncated": int(truncated),
    }


def quarantine_bundle(bundle: SkillBundle) -> Path:
    """Write the exact effective skill tree to quarantine for scanning.

    `.skillignore` / `.clawhubignore` are consumed here through the same
    matcher as the scanner. Neither the ignore files nor ignored payloads are
    written, so a later scan and install necessarily see the same tree.
    """
    ensure_hub_dirs()
    skill_name = _validate_skill_name(bundle.name)
    effective_files = _validated_effective_bundle_files(bundle)

    with hub_mutation_scope(_skills_dir().parent):
        dest = _quarantine_dir() / f"{skill_name}-{uuid.uuid4().hex}"
        _validate_hub_mutation_binding()
        try:
            if os.name == "nt":
                dest.mkdir(parents=True, exist_ok=False)
                for rel_path, file_content in effective_files.items():
                    _validate_hub_mutation_binding()
                    file_dest = dest.joinpath(*rel_path.split("/"))
                    file_dest.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(file_content, bytes):
                        file_dest.write_bytes(file_content)
                    else:
                        file_dest.write_text(file_content, encoding="utf-8")
            else:
                directory_flags = (
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                file_flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                quarantine_fd = _open_hub_directory(
                    _quarantine_dir(),
                    create=True,
                )
                try:
                    os.mkdir(dest.name, mode=0o700, dir_fd=quarantine_fd)
                    dest_fd = os.open(
                        dest.name,
                        directory_flags,
                        dir_fd=quarantine_fd,
                    )
                    try:
                        for rel_path, file_content in effective_files.items():
                            parts = tuple(rel_path.split("/"))
                            parent_fd = os.dup(dest_fd)
                            try:
                                for component in parts[:-1]:
                                    try:
                                        child_fd = os.open(
                                            component,
                                            directory_flags,
                                            dir_fd=parent_fd,
                                        )
                                    except FileNotFoundError:
                                        os.mkdir(
                                            component,
                                            mode=0o700,
                                            dir_fd=parent_fd,
                                        )
                                        child_fd = os.open(
                                            component,
                                            directory_flags,
                                            dir_fd=parent_fd,
                                        )
                                    os.close(parent_fd)
                                    parent_fd = child_fd
                                file_fd = os.open(
                                    parts[-1],
                                    file_flags,
                                    0o600,
                                    dir_fd=parent_fd,
                                )
                                try:
                                    payload = (
                                        file_content
                                        if isinstance(file_content, bytes)
                                        else file_content.encode("utf-8")
                                    )
                                    view = memoryview(payload)
                                    while view:
                                        written = os.write(file_fd, view)
                                        if written <= 0:
                                            raise OSError("short quarantine write")
                                        view = view[written:]
                                    os.fsync(file_fd)
                                finally:
                                    os.close(file_fd)
                                os.fsync(parent_fd)
                            finally:
                                os.close(parent_fd)
                        os.fsync(dest_fd)
                    finally:
                        os.close(dest_fd)
                    os.fsync(quarantine_fd)
                finally:
                    os.close(quarantine_fd)
                _validate_hub_mutation_binding()
            # Fail before returning a quarantine handle if the materialized tree
            # aliases on Windows or is not a stable regular-file snapshot.
            _capture_hub_tree(dest)
            _validate_hub_mutation_binding()
        except BaseException:
            logger.warning(
                "Incomplete Hub quarantine retained for recovery: %s",
                dest,
            )
            raise

    return dest


def install_from_quarantine(
    quarantine_path: Path,
    skill_name: str,
    category: str,
    bundle: SkillBundle,
    scan_result: ScanResult,
    *,
    source_authority: HubSourceAuthority | None = None,
    expected_installed_entry: Mapping[str, Any] | None = None,
    force: bool = False,
    adopt_identical_untracked: bool = False,
    verified_release: Any | None = None,
    distribution_name: str | None = None,
    distribution_store: Any | None = None,
) -> HubMutationOutcome:
    """Commit only a private candidate rebuilt from authoritative scan bytes."""
    if not isinstance(adopt_identical_untracked, bool):
        raise HubInstallError("Hub adoption flag must be boolean")
    legacy_unverified = source_authority is None
    authority = source_authority or _legacy_unverified_authority(
        bundle,
        scan_result,
    )
    authority.validate_bundle(bundle)
    from agent.skill_distribution_policy import load_distribution_policy

    distribution_policy = load_distribution_policy()
    if (
        distribution_policy.requires_signed_release(provenance="hub")
        and verified_release is None
    ):
        raise HubInstallError(
            "Signed-skill distribution enforcement blocked an unsigned Hub install"
        )
    if verified_release is not None and not distribution_name:
        raise HubInstallError(
            "A verified Hub release requires its canonical distribution name"
        )
    if verified_release is not None:
        from agent.skill_distribution_state import SkillDistributionStateStore

        if not isinstance(distribution_store, SkillDistributionStateStore):
            raise HubInstallError(
                "A verified Hub release requires its trust-state store"
            )
    safe_skill_name = _validate_skill_name(skill_name)
    safe_category = _validate_install_parent_path(category) if category else ""
    quarantine_name = normalize_relative_path(
        quarantine_path.name,
        field="quarantine name",
        allow_nested=False,
    )
    quarantine_resolved = _quarantine_dir() / quarantine_name
    if Path(os.path.abspath(quarantine_path)) != Path(
        os.path.abspath(quarantine_resolved)
    ):
        raise HubInstallError(f"Unsafe quarantine path: {quarantine_path}")

    if safe_category:
        install_rel_path = f"{safe_category}/{safe_skill_name}"
    else:
        install_rel_path = safe_skill_name

    # Resolve via the same lock-path validator the uninstaller uses. Catches
    # symlink-in-skills-tree redirects at install time so the lock entry's
    # path can never refer to a redirected target.
    install_dir = _bound_install_path(install_rel_path, safe_skill_name)

    # Warn (but don't block) if SKILL.md is very large.
    transaction_root: Path | None = None
    journal: dict | None = None
    authoritative_scan: ScanResult | None = None
    outcome: HubMutationOutcome | None = None
    lock = HubLockFile()
    with hub_mutation_scope(_skills_dir().parent):
        _recover_hub_transactions_locked(lock=lock)
        skill_md = quarantine_resolved / "SKILL.md"
        if _hub_exists(skill_md):
            skill_size = _hub_lstat(skill_md).st_size
            if skill_size > 100_000:
                logger.warning(
                    "Skill '%s' has a large SKILL.md (%s chars). "
                    "Large skills consume significant context when loaded. "
                    "Consider asking the author to split it into smaller files.",
                    safe_skill_name,
                    f"{skill_size:,}",
                )
        scanned_snapshot = _capture_hub_tree(quarantine_resolved)
        authoritative_result = scan_tree_snapshot(
            scanned_snapshot,
            skill_name=safe_skill_name,
            source="community",
            respect_skillignore=False,
        )
        authoritative_scan = _bind_scan_to_authority(
            authoritative_result,
            authority,
        )
        expected_scan_source = authority.scan_source
        if legacy_unverified:
            expected_scan_source = scan_result.source
            authoritative_scan.source = expected_scan_source
        source_sha256 = authoritative_scan.attested_tree_sha256
        if (
            authoritative_scan.attested_root_identity is None
            or len(source_sha256) != 64
        ):
            raise HubInstallError("Security scan did not return an attested snapshot")
        promoted_files = authoritative_scan.scanned_files
        promoted_hash = authoritative_scan.scanned_content_hash
        if (
            not scan_result.scanned_content_hash
            or scan_result.scanned_content_hash != promoted_hash
            or scan_result.scanned_files != promoted_files
            or scan_result.attested_tree_sha256 != source_sha256
            or scan_result.source != expected_scan_source
            or scan_result.trust_level != authority.trust_level
            or authoritative_scan.scanned_content_hash != promoted_hash
            or authoritative_scan.scanned_files != promoted_files
        ):
            raise HubInstallError(
                "Quarantined skill tree does not match its security scan"
            )
        allowed, reason = should_allow_install(authoritative_scan, force=force)
        if allowed is not True:
            raise HubInstallError(
                f"Authoritative security scan blocked install: {reason}"
            )

        signed_release_metadata: dict[str, Any] | None = None
        if verified_release is not None:
            from agent.skill_contract import (
                source_freshness_blockers,
                validate_skill_directory,
            )
            from agent.skill_distribution import (
                SkillDistributionError,
                bind_verified_release_to_artifact,
            )
            from agent.skill_evals import validate_eval_manifest

            contract_validation = validate_skill_directory(
                quarantine_resolved,
                require_contract=True,
            )
            if (
                not contract_validation.ok
                or contract_validation.status != "verified"
                or contract_validation.contract is None
                or contract_validation.digest is None
            ):
                codes = ", ".join(
                    sorted({issue.code for issue in contract_validation.errors})
                )
                raise HubInstallError(
                    "Signed skill has no valid contract"
                    + (f" ({codes})" if codes else "")
                )
            freshness = source_freshness_blockers(contract_validation)
            if freshness:
                raise HubInstallError(
                    "Signed skill contract sources require refresh before install"
                )
            suite = contract_validation.contract.get("evals", {}).get("suite")
            eval_validation = validate_eval_manifest(
                quarantine_resolved,
                suite,
            )
            if (
                not eval_validation.ok
                or eval_validation.digest is None
                or eval_validation.manifest is None
            ):
                codes = ", ".join(
                    sorted({issue.code for issue in eval_validation.errors})
                )
                raise HubInstallError(
                    "Signed skill has no valid evaluation manifest"
                    + (f" ({codes})" if codes else "")
                )
            try:
                bind_verified_release_to_artifact(
                    verified_release,
                    name=str(distribution_name),
                    tree_sha256=source_sha256,
                    contract_sha256=contract_validation.digest,
                    eval_sha256=eval_validation.digest,
                )
            except SkillDistributionError as exc:
                raise HubInstallError(
                    f"Signed skill artifact verification failed: {exc.code}"
                ) from exc
            try:
                installed_proof = distribution_store.issue_installed_proof(
                    verified_release,
                    installed_tree_sha256=source_sha256,
                    now=verified_release.verified_at,
                )
            except Exception as exc:
                raise HubInstallError(
                    "Could not issue the authenticated installed-release proof"
                ) from exc
            signed_release_metadata = {
                "spec_version": "fabric-distribution-1",
                "name": verified_release.name,
                "version": verified_release.version,
                "tree_sha256": verified_release.tree_sha256,
                "contract_sha256": verified_release.contract_sha256,
                "eval_sha256": verified_release.eval_sha256,
                "channel": verified_release.channel,
                "publisher": verified_release.publisher,
                "root_version": verified_release.root_version,
                "timestamp_version": verified_release.timestamp_version,
                "snapshot_version": verified_release.snapshot_version,
                "targets_version": verified_release.targets_version,
                "revocations_version": verified_release.revocations_version,
                "verified_at": verified_release.verified_at.isoformat(),
                "offline_grace_used": verified_release.offline_grace_used,
                "installed_proof": installed_proof.decode("utf-8"),
            }

        old_lock_data = lock.load(strict=True)
        old_entry = old_lock_data["installed"].get(safe_skill_name)
        if expected_installed_entry is not None and old_entry != dict(
            expected_installed_entry
        ):
            raise HubInstallError("Installed Hub state changed after the update check")
        if old_entry is not None:
            if not isinstance(old_entry, dict):
                raise HubInstallError("Existing Hub ownership record is invalid")
            recorded_path = _normalize_lock_install_path(
                old_entry.get("install_path", ""),
                safe_skill_name,
            )
            if recorded_path != install_rel_path:
                raise HubInstallError(
                    "Existing Hub ownership record names a different destination"
                )
            if not force:
                raise HubInstallError(
                    f"Skill '{safe_skill_name}' is already Hub-installed; use --force"
                )
        elif _hub_exists(install_dir) and not (
            adopt_identical_untracked
            and authority.adapter is HubSourceKind.OFFICIAL_OPTIONAL
        ):
            raise HubInstallError(
                "Refusing to replace an untracked or locally owned skill directory"
            )

        old_tree_sha256: str | None = None
        old_identity: tuple[int, int] | None = None
        old_snapshot: TreeSnapshot | None = None
        if _hub_exists(install_dir):
            old_snapshot = _capture_hub_tree(install_dir)
            old_identity = old_snapshot.root_identity
            old_tree_sha256 = old_snapshot.tree_sha256
            recorded_tree_sha256 = (
                old_entry.get("attested_tree_sha256")
                if isinstance(old_entry, dict)
                else None
            )
            if old_entry is None:
                ownership_matches = (
                    adopt_identical_untracked
                    and authority.adapter is HubSourceKind.OFFICIAL_OPTIONAL
                    and old_snapshot.tree_sha256 == scanned_snapshot.tree_sha256
                    and old_snapshot.content_sha256 == scanned_snapshot.content_sha256
                    and tuple(
                        item.relative_path.as_posix() for item in old_snapshot.files
                    )
                    == tuple(promoted_files)
                    and tuple(
                        (item.relative_path.as_posix(), item.mode & 0o777)
                        for item in old_snapshot.files
                    )
                    == tuple(
                        (item.relative_path.as_posix(), item.mode & 0o777)
                        for item in scanned_snapshot.files
                    )
                )
            elif recorded_tree_sha256:
                ownership_matches = recorded_tree_sha256 == old_tree_sha256
            else:
                ownership_matches = (
                    f"sha256:{old_snapshot.content_sha256[:16]}"
                    == old_entry.get("content_hash")
                )
            if not ownership_matches:
                if old_entry is None:
                    raise HubInstallError(
                        "Untracked destination changed after official adoption check"
                    )
                raise HubInstallError(
                    "Existing destination no longer matches its Hub ownership digest"
                )

        _ensure_hub_transaction_capacity()
        transaction_id = str(uuid.uuid4())
        transaction_root = _hub_dir() / "transactions" / transaction_id
        try:
            _create_hub_directory(transaction_root)
        except OSError as exc:
            raise HubInstallError("Could not create Hub install transaction") from exc
        try:
            _write_hub_preparation(transaction_root, state="private_only")
        except BaseException as exc:
            with contextlib.suppress(OSError, HubInstallError):
                _hub_remove_empty_directory(transaction_root)
            raise HubInstallError("Could not prepare Hub install transaction") from exc
        candidate_path = transaction_root / "candidate"
        try:
            candidate_snapshot = _materialize_snapshot_candidate(
                scanned_snapshot,
                candidate_path,
            )
        except BaseException as exc:
            raise HubInstallError(
                "Could not materialize the scanned Hub candidate"
            ) from exc
        source_identity = candidate_snapshot.root_identity
        backup_path = transaction_root / "backup"
        new_lock_data = copy.deepcopy(old_lock_data)
        installed_at = (
            old_entry.get("installed_at") if isinstance(old_entry, dict) else None
        )
        install_metadata = dict(bundle.metadata)
        install_metadata["source_name"] = bundle.name
        install_metadata["source_revision"] = bundle_source_revision(bundle)
        if signed_release_metadata is not None:
            install_metadata["signed_release"] = signed_release_metadata
        new_entry = lock._install_entry(
            source=bundle.source,
            identifier=bundle.identifier,
            trust_level=authority.trust_level,
            scan_verdict=authoritative_scan.verdict,
            skill_hash=(
                f"sha256:{authoritative_scan.scanned_content_hash.removeprefix('sha256:')[:16]}"
            ),
            install_path=install_rel_path,
            files=list(promoted_files),
            metadata=install_metadata,
            transaction_id=transaction_id,
            installed_at=installed_at,
            attested_tree_sha256=source_sha256,
            source_authority=authority,
        )
        new_lock_data["installed"][safe_skill_name] = new_entry
        journal = {
            "schema_version": _HUB_TRANSACTION_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "operation": "install",
            "phase": "prepared",
            "skill_name": safe_skill_name,
            "install_path": install_rel_path,
            "quarantine_name": quarantine_resolved.name,
            "candidate_name": candidate_path.name,
            "source_sha256": source_sha256,
            "source_content_sha256": scanned_snapshot.content_sha256,
            "source_files": list(promoted_files),
            "source_identity": list(source_identity),
            "source_authority": authority.as_dict(),
            "old_tree_sha256": old_tree_sha256,
            "old_lock_data": old_lock_data,
            "old_lock_sha256": _canonical_json_sha256(old_lock_data),
            "new_entry": new_entry,
            "new_entry_sha256": _canonical_json_sha256(new_entry),
            "cleanup_pending": [f"quarantine:{quarantine_resolved.name}"],
        }
        try:
            _write_hub_journal(transaction_root, journal)
        except BaseException as exc:
            try:
                _hub_remove_empty_directory(transaction_root)
            except (OSError, HubInstallError):
                logger.warning(
                    "Pre-journal Hub transaction retained at %s",
                    transaction_root,
                )
            if isinstance(exc, (HubInstallError, UnsafePathError)):
                raise
            raise HubInstallError("Could not prepare Hub install journal") from exc

        try:
            _write_hub_preparation(
                transaction_root,
                state="effects_may_start",
                old_lock_sha256=_canonical_json_sha256(old_lock_data),
                new_lock_sha256=_canonical_json_sha256(new_lock_data),
            )
            if old_identity is not None:
                assert old_snapshot is not None
                _atomic_move_directory(
                    install_dir,
                    backup_path,
                    expected_identity=old_identity,
                    expected_native_identity=old_snapshot.native_root_identity,
                )
                _update_hub_journal(transaction_root, journal, phase="backed_up")
                backed_up_snapshot = _capture_hub_tree(backup_path)
                if (
                    backed_up_snapshot.root_identity != old_identity
                    or backed_up_snapshot.tree_sha256 != old_tree_sha256
                ):
                    raise HubInstallError(
                        "Existing destination changed before transactional backup"
                    )
            _atomic_move_directory(
                candidate_path,
                install_dir,
                expected_identity=source_identity,
                expected_native_identity=candidate_snapshot.native_root_identity,
            )
            promoted_snapshot = _capture_hub_tree(install_dir)
            if (
                promoted_snapshot.root_identity != source_identity
                or promoted_snapshot.tree_sha256 != source_sha256
            ):
                raise HubInstallError("Promoted skill does not match attested source")
            _update_hub_journal(transaction_root, journal, phase="promoted")
            lock._save_atomic(new_lock_data)
            # Metadata publication is not the linearization point by itself.
            # Re-prove the installed bytes and the exact lock post-image after
            # publication so a mutation immediately before the replace rolls
            # back rather than committing safe provenance for different bytes.
            committed_snapshot = _capture_hub_tree(install_dir)
            if (
                committed_snapshot.root_identity != source_identity
                or committed_snapshot.tree_sha256 != source_sha256
                or committed_snapshot.content_sha256 != scanned_snapshot.content_sha256
            ):
                raise HubInstallError(
                    "Installed bytes changed before Hub commit linearization"
                )
            published_lock = lock.load(strict=True)
            published_entry = published_lock["installed"].get(safe_skill_name)
            if not isinstance(published_entry, dict) or published_entry != new_entry:
                raise HubInstallError("Hub provenance post-image is invalid")
            if old_tree_sha256 is not None:
                precommit_backup = _capture_hub_tree(backup_path)
                if precommit_backup.tree_sha256 != old_tree_sha256:
                    raise HubInstallError(
                        "Existing destination changed before Hub commit"
                    )
                if "backup" not in journal["cleanup_pending"]:
                    journal["cleanup_pending"].append("backup")
            _update_hub_journal(transaction_root, journal, phase="committed")
            outcome = HubMutationOutcome(
                status="committed",
                message=f"Installed '{safe_skill_name}'",
                transaction_id=transaction_id,
                install_path=install_dir,
                cleanup_pending=tuple(journal["cleanup_pending"]),
            )
        except BaseException as exc:
            try:
                outcome = _recover_hub_transaction_locked(
                    transaction_root,
                    lock=lock,
                )
            except BaseException as recovery_exc:
                outcome = HubMutationOutcome(
                    status="recovery_pending",
                    message=(
                        f"Install of '{safe_skill_name}' requires recovery: "
                        f"{recovery_exc}"
                    ),
                    transaction_id=transaction_id,
                    # Do not probe a replacement profile generation merely to
                    # decorate an uncertain result.
                    install_path=None,
                    cleanup_pending=tuple(journal.get("cleanup_pending", [])),
                )
            else:
                if outcome.status == "rolled_back":
                    outcome = HubMutationOutcome(
                        status="rolled_back",
                        message=(
                            f"Install of '{safe_skill_name}' failed and was "
                            f"rolled back: {exc}"
                        ),
                        transaction_id=outcome.transaction_id,
                        install_path=outcome.install_path,
                        cleanup_pending=outcome.cleanup_pending,
                    )
                elif outcome.status == "committed":
                    outcome = HubMutationOutcome(
                        status="committed",
                        message=f"Installed '{safe_skill_name}'",
                        transaction_id=outcome.transaction_id,
                        install_path=install_dir,
                        cleanup_pending=outcome.cleanup_pending,
                    )

        if outcome is not None and outcome.committed:
            _append_audit_log_best_effort(
                "INSTALL",
                safe_skill_name,
                authority.adapter.value,
                authority.trust_level,
                authoritative_scan.verdict,
                authoritative_scan.scanned_content_hash,
            )

    assert outcome is not None
    if not outcome.committed:
        logger.warning(
            "Hub install transaction %s ended %s: %s",
            outcome.transaction_id,
            outcome.status,
            outcome.message,
        )
    return outcome


def uninstall_skill(skill_name: str) -> HubMutationOutcome:
    """Transactionally remove only the exact Hub-owned tree."""

    ensure_hub_dirs()
    try:
        safe_skill_name = _validate_skill_name(skill_name)
    except ValueError as exc:
        return HubMutationOutcome(
            status="rolled_back",
            message=f"Refusing to uninstall '{skill_name}': {exc}",
        )

    lock = HubLockFile()
    entry: dict | None = None
    install_rel = ""
    transaction_root: Path | None = None
    journal: dict | None = None
    old_tree_sha256 = ""
    outcome: HubMutationOutcome | None = None
    with hub_mutation_scope(_skills_dir().parent):
        try:
            _recover_hub_transactions_locked(lock=lock)
            old_lock_data = lock.load(strict=True)
            raw_entry = old_lock_data["installed"].get(safe_skill_name)
            if not isinstance(raw_entry, dict):
                return HubMutationOutcome(
                    status="rolled_back",
                    message=(
                        f"'{safe_skill_name}' is not a hub-installed skill "
                        "(may be a builtin)"
                    ),
                )
            entry = raw_entry
            source_authority = _authority_for_installed_entry(entry)
            install_rel = _normalize_lock_install_path(
                entry.get("install_path", ""), safe_skill_name
            )
            install_path = _bound_install_path(install_rel, safe_skill_name)
            if not _hub_exists(install_path):
                return HubMutationOutcome(
                    status="rolled_back",
                    message=(
                        f"Refusing to uninstall '{safe_skill_name}': "
                        "the Hub-owned tree is missing"
                    ),
                )

            old_snapshot = _capture_hub_tree(install_path)
            old_tree_sha256 = old_snapshot.tree_sha256
            recorded_tree_sha256 = entry.get("attested_tree_sha256")
            if recorded_tree_sha256:
                ownership_matches = recorded_tree_sha256 == old_tree_sha256
            else:
                ownership_matches = (
                    f"sha256:{old_snapshot.content_sha256[:16]}"
                    == entry.get("content_hash")
                )
            if not ownership_matches:
                return HubMutationOutcome(
                    status="rolled_back",
                    message=(
                        f"Refusing to uninstall '{safe_skill_name}': "
                        "the installed tree was modified locally"
                    ),
                )

            _ensure_hub_transaction_capacity()
            transaction_id = str(uuid.uuid4())
            transaction_root = _hub_dir() / "transactions" / transaction_id
            _create_hub_directory(transaction_root)
            try:
                _write_hub_preparation(transaction_root, state="private_only")
            except BaseException as exc:
                with contextlib.suppress(OSError, HubInstallError):
                    _hub_remove_empty_directory(transaction_root)
                raise HubInstallError(
                    "Could not prepare Hub uninstall transaction"
                ) from exc
            backup_path = transaction_root / "backup"
            new_lock_data = copy.deepcopy(old_lock_data)
            new_lock_data["installed"].pop(safe_skill_name, None)
            new_lock_data["last_transaction_id"] = transaction_id
            journal = {
                "schema_version": _HUB_TRANSACTION_SCHEMA_VERSION,
                "transaction_id": transaction_id,
                "operation": "uninstall",
                "phase": "prepared",
                "skill_name": safe_skill_name,
                "install_path": install_rel,
                "quarantine_name": f"uninstall-{transaction_id}",
                "source_sha256": old_tree_sha256,
                "source_authority": source_authority.as_dict(),
                "old_tree_sha256": old_tree_sha256,
                "old_lock_data": old_lock_data,
                "old_lock_sha256": _canonical_json_sha256(old_lock_data),
                "cleanup_pending": ["backup"],
            }
            _write_hub_journal(transaction_root, journal)

            try:
                _write_hub_preparation(
                    transaction_root,
                    state="effects_may_start",
                    old_lock_sha256=_canonical_json_sha256(old_lock_data),
                    new_lock_sha256=_canonical_json_sha256(new_lock_data),
                )
                _atomic_move_directory(
                    install_path,
                    backup_path,
                    expected_identity=old_snapshot.root_identity,
                    expected_native_identity=old_snapshot.native_root_identity,
                )
                _update_hub_journal(transaction_root, journal, phase="backed_up")
                backup_snapshot = _capture_hub_tree(backup_path)
                if (
                    backup_snapshot.root_identity != old_snapshot.root_identity
                    or backup_snapshot.tree_sha256 != old_tree_sha256
                ):
                    raise HubInstallError(
                        "Hub-owned tree changed before uninstall backup"
                    )
                lock._save_atomic(new_lock_data)
                precommit_backup = _capture_hub_tree(backup_path)
                if precommit_backup.tree_sha256 != old_tree_sha256:
                    raise HubInstallError(
                        "Hub-owned tree changed before uninstall commit"
                    )
                published_lock = lock.load(strict=True)
                if (
                    safe_skill_name in published_lock["installed"]
                    or published_lock.get("last_transaction_id") != transaction_id
                ):
                    raise HubInstallError(
                        "Hub uninstall provenance post-image is invalid"
                    )
                _update_hub_journal(transaction_root, journal, phase="committed")
                outcome = HubMutationOutcome(
                    status="committed",
                    message=f"Uninstalled '{safe_skill_name}' from {install_rel}",
                    transaction_id=transaction_id,
                    cleanup_pending=("backup",),
                )
            except BaseException as exc:
                try:
                    outcome = _recover_hub_transaction_locked(
                        transaction_root,
                        lock=lock,
                    )
                except BaseException as recovery_exc:
                    outcome = HubMutationOutcome(
                        status="recovery_pending",
                        message=(
                            f"Uninstall of '{safe_skill_name}' is pending recovery: "
                            f"{recovery_exc}"
                        ),
                        transaction_id=transaction_id,
                        cleanup_pending=tuple(journal.get("cleanup_pending", [])),
                    )
                else:
                    if outcome.status == "rolled_back":
                        outcome = HubMutationOutcome(
                            status="rolled_back",
                            message=(
                                f"Uninstall of '{safe_skill_name}' failed and was "
                                f"rolled back: {exc}"
                            ),
                            transaction_id=outcome.transaction_id,
                            install_path=outcome.install_path,
                            cleanup_pending=outcome.cleanup_pending,
                        )
                    elif outcome.status == "committed":
                        outcome = HubMutationOutcome(
                            status="committed",
                            message=(
                                f"Uninstalled '{safe_skill_name}' from {install_rel}"
                            ),
                            transaction_id=outcome.transaction_id,
                            cleanup_pending=outcome.cleanup_pending,
                        )
        except (OSError, ValueError, UnsafePathError) as exc:
            return HubMutationOutcome(
                status="rolled_back",
                message=f"Refusing to uninstall '{safe_skill_name}': {exc}",
                transaction_id=(
                    transaction_root.name if transaction_root is not None else None
                ),
            )

        if outcome is not None and outcome.committed and entry is not None:
            _append_audit_log_best_effort(
                "UNINSTALL",
                safe_skill_name,
                source_authority.adapter.value,
                source_authority.trust_level,
                "n/a",
                "user_request",
            )

    assert entry is not None
    assert outcome is not None
    return outcome


def bundle_content_hash(bundle: SkillBundle) -> str:
    """Hash the same effective tree that quarantine/install will promote."""
    h = hashlib.sha256()
    effective_files = _validated_effective_bundle_files(bundle)
    for rel_path in sorted(effective_files):
        # Include the path so swapping file contents between two paths
        # changes the hash (avoids filename-swap evading update detection).
        h.update(rel_path.encode("utf-8"))
        h.update(b"\x00")
        content = effective_files[rel_path]
        if isinstance(content, bytes):
            h.update(content)
        else:
            h.update(content.encode("utf-8"))
    return f"sha256:{h.hexdigest()[:16]}"


def bundle_snapshot_identity(bundle: SkillBundle) -> dict[str, object]:
    """Return full digests for the exact effective tree carried by a bundle."""

    tree_digest = hashlib.sha256()
    content_digest = hashlib.sha256()
    effective_files = _validated_effective_bundle_files(bundle)
    ordered_paths = sorted(effective_files)
    for rel_path in ordered_paths:
        content = effective_files[rel_path]
        payload = content if isinstance(content, bytes) else content.encode("utf-8")
        encoded_path = rel_path.encode("utf-8")
        file_digest = hashlib.sha256(payload).hexdigest()
        tree_digest.update(encoded_path)
        tree_digest.update(b"\0")
        tree_digest.update(file_digest.encode("ascii"))
        tree_digest.update(b"\0")
        content_digest.update(encoded_path)
        content_digest.update(b"\0")
        content_digest.update(payload)
    return {
        "tree_sha256": tree_digest.hexdigest(),
        "content_sha256": content_digest.hexdigest(),
        "files": ordered_paths,
    }


def _source_matches(source: SkillSource, source_name: str) -> bool:
    """Match only an exact built-in adapter to persisted display provenance."""

    try:
        kind, bundle_source = _concrete_adapter_identity(source)
    except HubInstallError:
        return False
    return source_name in {kind.value, bundle_source}


def check_for_skill_updates(
    name: Optional[str] = None,
    *,
    lock: Optional[HubLockFile] = None,
    sources: Optional[List[SkillSource]] = None,
    auth: Optional[GitHubAuth] = None,
) -> List[dict]:
    """Check installed hub skills for upstream changes."""
    lock = lock or HubLockFile()
    installed = lock.list_installed()
    if name:
        installed = [entry for entry in installed if entry.get("name") == name]

    if sources is None:
        sources = create_source_router(auth=auth)

    results: List[dict] = []
    for entry in installed:
        identifier = entry.get("identifier", "")
        source_name = entry.get("source", "")
        try:
            recorded_authority = _authority_for_installed_entry(entry)
        except HubInstallError:
            results.append({
                "name": entry.get("name", ""),
                "identifier": identifier,
                "source": source_name,
                "status": "invalid_provenance",
            })
            continue
        if recorded_authority.adapter is HubSourceKind.UNVERIFIED:
            legacy_kind = {
                "skills.sh": HubSourceKind.SKILLS_SH,
                "well-known": HubSourceKind.WELL_KNOWN,
                "url": HubSourceKind.URL,
                "github": HubSourceKind.GITHUB,
                "clawhub": HubSourceKind.CLAWHUB,
                "claude-marketplace": HubSourceKind.CLAUDE_MARKETPLACE,
                "lobehub": HubSourceKind.LOBEHUB,
                "browse-sh": HubSourceKind.BROWSE_SH,
            }.get(source_name)
            if legacy_kind is None:
                results.append({
                    "name": entry.get("name", ""),
                    "identifier": identifier,
                    "source": source_name,
                    "status": "unavailable",
                })
                continue
            recorded_authority = HubSourceAuthority(
                adapter=legacy_kind,
                remote_identifier=identifier,
                bundle_source=source_name,
                trust_level="community",
            )

        candidate_sources: list[SkillSource] = []
        for source in sources:
            try:
                kind, _bundle_source = _concrete_adapter_identity(source)
            except HubInstallError:
                # Update continuity is bound to the concrete code-owned
                # adapter, not to a virtual object's self-asserted source_id.
                continue
            if kind is recorded_authority.adapter:
                candidate_sources.append(source)

        bundle = None
        candidate_authority: HubSourceAuthority | None = None
        for src in candidate_sources:
            try:
                fetched = src.fetch(recorded_authority.remote_identifier)
            except Exception:
                fetched = None
            if fetched is None:
                continue
            try:
                fetched_authority = source_authority_for_adapter(src, fetched)
            except HubInstallError:
                continue
            if fetched_authority != recorded_authority:
                continue
            bundle = fetched
            candidate_authority = fetched_authority
            if bundle:
                break

        if not bundle or candidate_authority is None:
            results.append({
                "name": entry.get("name", ""),
                "identifier": identifier,
                "source": source_name,
                "status": "unavailable",
            })
            continue

        current_hash = entry.get("content_hash", "")
        latest_hash = bundle_content_hash(bundle)
        snapshot_identity = bundle_snapshot_identity(bundle)
        status = "up_to_date" if current_hash == latest_hash else "update_available"
        checked_bundle = copy.deepcopy(bundle)
        results.append({
            "name": entry.get("name", ""),
            "identifier": identifier,
            "source": source_name,
            "status": status,
            "current_hash": current_hash,
            "latest_hash": latest_hash,
            "bundle": checked_bundle,
            "checked_candidate": {
                "authority": candidate_authority.as_dict(),
                "bundle": checked_bundle,
                "installed_entry": copy.deepcopy(entry),
                "latest_hash": latest_hash,
                "snapshot_identity": snapshot_identity,
                "source_name": checked_bundle.name,
                "source_revision": bundle_source_revision(checked_bundle),
            },
        })

    return results


# ---------------------------------------------------------------------------
# Fabric centralized index source
# ---------------------------------------------------------------------------

FABRIC_INDEX_URL = "https://obliviousodin.github.io/fabric/api/skills-index.json"
FABRIC_INDEX_TTL = 6 * 3600  # 6 hours


def _fabric_index_cache_file() -> Path:
    return _index_cache_dir() / "fabric-index.json"


def _load_fabric_index() -> Optional[dict]:
    """Fetch the centralized skills index, with local cache.

    The index is a JSON file hosted on the docs site, rebuilt daily by CI.
    We cache it locally for FABRIC_INDEX_TTL seconds to avoid repeated
    downloads within a session.
    """
    # Check local cache
    fabric_index_cache_file = _fabric_index_cache_file()
    if fabric_index_cache_file.exists():
        try:
            with hub_mutation_scope(_skills_dir().parent):
                cached, state = _read_bounded_json_file(
                    fabric_index_cache_file,
                )
                _validate_hub_mutation_binding()
            age = time.time() - state.st_mtime
            if age < FABRIC_INDEX_TTL:
                return cached if isinstance(cached, dict) else None
        except (
            OSError,
            RuntimeError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            pass

    # Fetch from docs site.
    #
    # Identity transfer plus a raw streaming ceiling prevents compressed or
    # chunked responses from allocating beyond the catalog budget.
    try:
        resp = _bounded_http_get(
            FABRIC_INDEX_URL,
            timeout=15,
            max_bytes=MAX_HUB_CATALOG_BYTES,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.debug("Fabric index fetch returned %d", resp.status_code)
            return _load_stale_index_cache()
        data = _bounded_json(resp)
    except (
        httpx.HTTPError,
        json.JSONDecodeError,
        SkillPayloadTooLarge,
        ValueError,
    ) as e:
        logger.debug("Fabric index fetch failed: %s", e)
        return _load_stale_index_cache()

    # Validate structure
    if not isinstance(data, dict) or "skills" not in data:
        return _load_stale_index_cache()

    # Cache locally
    try:
        _write_index_cache("fabric-index", data)
    except (OSError, RuntimeError, ValueError):
        pass

    return data


def _load_stale_index_cache() -> Optional[dict]:
    """Fall back to stale cache when the network fetch fails."""
    fabric_index_cache_file = _fabric_index_cache_file()
    if fabric_index_cache_file.exists():
        try:
            with hub_mutation_scope(_skills_dir().parent):
                cached, _state = _read_bounded_json_file(
                    fabric_index_cache_file,
                )
                _validate_hub_mutation_binding()
            return cached if isinstance(cached, dict) else None
        except (
            OSError,
            RuntimeError,
            json.JSONDecodeError,
            SkillPayloadTooLarge,
            ValueError,
        ):
            pass
    return None


class FabricIndexSource(SkillSource):
    """Skill source backed by the centralized Fabric Skills Index.

    The index is a JSON catalog published to the docs site and rebuilt
    daily by CI.  It contains metadata + resolved GitHub paths for every
    skill, eliminating the need for users to hit the GitHub API for
    search or path discovery.

    When the index is unavailable, all methods return empty / None so
    downstream sources take over transparently.
    """

    def __init__(self, auth: GitHubAuth):
        self._index: Optional[dict] = None
        self._loaded = False
        self.auth = auth
        # Lazily create GitHubSource for fetch — only used when actually
        # downloading files, which requires real GitHub API calls.
        self._github: Optional[GitHubSource] = None

    def _ensure_loaded(self) -> dict:
        if not self._loaded:
            self._index = _load_fabric_index()
            self._loaded = True
        return self._index or {}

    def _get_github(self) -> GitHubSource:
        if self._github is None:
            self._github = GitHubSource(auth=self.auth)
        return self._github

    def source_id(self) -> str:
        return "fabric-index"

    @property
    def is_available(self) -> bool:
        """Whether the index is loaded and has skills."""
        index = self._ensure_loaded()
        return bool(index.get("skills"))

    def trust_level_for(self, identifier: str) -> str:
        # The index is an unauthenticated aggregate. Its trust/source fields
        # are display metadata, not adapter authority.
        return "community"

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        """Search the cached index.  Zero API calls.

        Matches against name, description, tags, identifier, and the per-tap
        ``extra.provider`` label (so a query like ``nvidia`` surfaces the
        ``NVIDIA/skills/...`` entries even though their ``source`` is the bare
        ``github``).  Results are scored and ranked (exact name > name prefix >
        whole-word > substring) rather than returned in raw index order and
        truncated at the first ``limit`` hits — that earlier break-at-limit
        behaviour returned an arbitrary file-order slice and buried the most
        relevant skills.
        """
        index = self._ensure_loaded()
        skills = index.get("skills", [])
        if not skills:
            return []

        if not query.strip():
            # No query — return featured/popular (index order)
            return [self._to_meta(s) for s in skills[:limit]]

        query_lower = query.lower()
        scored: List[Tuple[int, int, dict]] = []
        for i, s in enumerate(skills):
            name = str(s.get("name", "")).lower()
            provider = str((s.get("extra") or {}).get("provider", "")).lower()
            haystack = " ".join([
                name,
                str(s.get("description", "")).lower(),
                " ".join(str(t).lower() for t in s.get("tags", [])),
                str(s.get("identifier", "")).lower(),
                provider,
            ])
            if query_lower not in haystack:
                continue
            # Lower score sorts first.
            if name == query_lower:
                score = 0
            elif name.startswith(query_lower):
                score = 1
            elif provider == query_lower:
                score = 2
            elif query_lower in name.split() or query_lower in provider.split():
                score = 3
            elif query_lower in name:
                score = 4
            else:
                score = 5
            # i (original index order) is the stable tiebreaker.
            scored.append((score, i, s))

        scored.sort(key=lambda x: (x[0], x[1]))
        return [self._to_meta(s) for _, _, s in scored[:limit]]

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        """Fetch a skill using the resolved path from the index.

        If the index has a ``resolved_github_id`` for this skill, we skip
        the entire candidate/discovery chain and go directly to GitHub
        with the exact path.  This reduces install from ~31 API calls to
        just the file content downloads (~5-22 depending on skill size).
        """
        index = self._ensure_loaded()
        entry = self._find_entry(identifier, index)
        if not entry:
            return None

        # Use resolved path if available
        resolved = entry.get("resolved_github_id")
        if resolved:
            bundle = self._get_github().fetch(resolved)
            if bundle:
                bundle.source = "fabric-index"
                bundle.identifier = identifier
                bundle.trust_level = "community"
                bundle.metadata["source_revision"] = resolved
                bundle.metadata["source_name"] = bundle.name
                return bundle

        # Fall back to identifier-based fetch via repo/path
        repo = entry.get("repo", "")
        path = entry.get("path", "")
        if repo and path:
            github_id = f"{repo}/{path}"
            bundle = self._get_github().fetch(github_id)
            if bundle:
                bundle.source = "fabric-index"
                bundle.identifier = identifier
                bundle.trust_level = "community"
                bundle.metadata["source_revision"] = github_id
                bundle.metadata["source_name"] = bundle.name
                return bundle

        return None

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        """Return metadata from the index.  Zero API calls."""
        index = self._ensure_loaded()
        entry = self._find_entry(identifier, index)
        if entry:
            return self._to_meta(entry)
        return None

    def _find_entry(self, identifier: str, index: dict) -> Optional[dict]:
        """Look up a skill in the index by identifier or name."""
        skills = index.get("skills", [])

        # Exact identifier match
        for s in skills:
            if s.get("identifier") == identifier:
                return s

        # Try without source prefix (e.g. "skills-sh/" stripped)
        normalized = identifier
        for prefix in ("skills-sh/", "skills.sh/", "official/", "github/", "clawhub/"):
            if identifier.startswith(prefix):
                normalized = identifier[len(prefix) :]
                break

        # Match on normalized identifier or name
        for s in skills:
            sid = s.get("identifier", "")
            # Strip prefix from stored identifier too
            stored_normalized = sid
            for prefix in (
                "skills-sh/",
                "skills.sh/",
                "official/",
                "github/",
                "clawhub/",
            ):
                if sid.startswith(prefix):
                    stored_normalized = sid[len(prefix) :]
                    break
            if stored_normalized == normalized:
                return s

        return None

    @staticmethod
    def _to_meta(entry: dict) -> SkillMeta:
        return SkillMeta(
            name=entry.get("name", ""),
            description=entry.get("description", ""),
            source="fabric-index",
            identifier=entry.get("identifier", ""),
            trust_level="community",
            repo=entry.get("repo"),
            path=entry.get("path"),
            tags=entry.get("tags", []),
            extra=entry.get("extra", {}),
        )


def create_source_router(auth: Optional[GitHubAuth] = None) -> List[SkillSource]:
    """
    Create all configured source adapters.
    Returns a list of active sources for search/fetch operations.
    """
    if auth is None:
        auth = GitHubAuth()

    taps_mgr = TapsManager()
    extra_taps = taps_mgr.list_taps()

    sources: List[SkillSource] = [
        OptionalSkillSource(),  # Official optional skills (highest priority)
        FabricIndexSource(
            auth=auth
        ),  # Centralized index (search + resolved install paths)
        SkillsShSource(auth=auth),
        WellKnownSkillSource(),
        UrlSource(),  # Direct HTTP(S) URL to a SKILL.md file
        GitHubSource(auth=auth, extra_taps=extra_taps),
        ClawHubSource(),
        ClaudeMarketplaceSource(auth=auth),
        LobeHubSource(),
        BrowseShSource(),  # browse.sh: 169+ site-specific browser automation skills
    ]

    return sources


def _search_one_source(
    src: SkillSource, query: str, limit: int
) -> Tuple[str, List[SkillMeta]]:
    """Search a single source.  Runs in a thread for parallelism."""
    try:
        return src.source_id(), src.search(query, limit=limit)
    except Exception as e:
        logger.debug("Search failed for %s: %s", src.source_id(), e)
        return src.source_id(), []


def parallel_search_sources(
    sources: List[SkillSource],
    query: str = "",
    per_source_limits: Optional[Dict[str, int]] = None,
    source_filter: str = "all",
    overall_timeout: float = 30,
    on_source_done: Optional[Any] = None,
) -> Tuple[List[SkillMeta], Dict[str, int], List[str]]:
    """Search all sources in parallel with per-source timeout.

    Returns ``(all_results, source_counts, timed_out_ids)``.

    *on_source_done* is an optional callback ``(source_id, count) -> None``
    invoked as each source completes — useful for progress indicators.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    per_source_limits = per_source_limits or {}

    # A provider filter (e.g. "nvidia", "openai") targets GitHub-tap skills
    # that the runtime index stores under source="github" with an
    # ``extra.provider`` label. It is NOT a real source id, so source-level
    # selection must treat it like "all" (the index / github source carries
    # the data); the per-provider narrowing happens downstream on the merged
    # results (see ``_filter_results_by_provider``).
    _provider_filter = source_filter.strip().lower() in _PROVIDER_FILTER_VALUES
    _effective_filter = "all" if _provider_filter else source_filter

    active: List[SkillSource] = []
    # When the centralized index is available and the user hasn't filtered
    # to a specific source, skip external API sources (github, skills-sh,
    # clawhub, etc.) — the index already has their data.  This avoids
    # ~70 GitHub API calls per search for unauthenticated users.
    _index_available = False
    _api_source_ids = frozenset({
        "github",
        "skills-sh",
        "clawhub",
        "claude-marketplace",
        "lobehub",
        "well-known",
    })
    if _effective_filter == "all":
        for src in sources:
            if src.source_id() == "fabric-index" and getattr(
                src, "is_available", False
            ):
                _index_available = True
                break

    for src in sources:
        sid = src.source_id()
        if (
            _effective_filter != "all"
            and sid != _effective_filter
            and sid != "official"
        ):
            continue
        # Skip external API sources when the index covers them
        if _index_available and sid in _api_source_ids:
            continue
        active.append(src)

    all_results: List[SkillMeta] = []
    source_counts: Dict[str, int] = {}
    timed_out_ids: List[str] = []

    if not active:
        return all_results, source_counts, timed_out_ids

    # NOTE: a `with ThreadPoolExecutor(...) as pool` block calls
    # ``shutdown(wait=True)`` on exit, which blocks until every submitted
    # worker finishes — so a single slow source (e.g. ClawHub) keeps the
    # caller blocked for minutes and renders ``overall_timeout`` a no-op.
    # Manage the executor manually and shut it down with ``wait=False`` so
    # the timeout is actually honoured.  Daemon workers (tools.daemon_pool):
    # an abandoned slow source must not block interpreter exit either —
    # stdlib workers are joined unconditionally by the atexit hook.
    from tools.daemon_pool import DaemonThreadPoolExecutor

    pool = DaemonThreadPoolExecutor(max_workers=min(len(active), 8))
    futures = {}
    for src in active:
        lim = per_source_limits.get(src.source_id(), 50)
        fut = pool.submit(_search_one_source, src, query, lim)
        futures[fut] = src.source_id()

    try:
        try:
            for fut in as_completed(futures, timeout=overall_timeout):
                try:
                    sid, results = fut.result(timeout=0)
                    source_counts[sid] = len(results)
                    all_results.extend(results)
                    if on_source_done:
                        on_source_done(sid, len(results))
                except Exception:
                    pass
        except TimeoutError:
            timed_out_ids = [futures[f] for f in futures if not f.done()]
            if timed_out_ids:
                logger.debug(
                    "Skills browse timed out waiting for: %s",
                    ", ".join(timed_out_ids),
                )
    finally:
        # wait=False so a slow source cannot block the caller's return;
        # cancel_futures drops not-yet-started work.
        pool.shutdown(wait=False, cancel_futures=True)

    return all_results, source_counts, timed_out_ids


def unified_search(
    query: str, sources: List[SkillSource], source_filter: str = "all", limit: int = 10
) -> List[SkillMeta]:
    """Search all sources (in parallel) and merge results."""
    all_results, _, _ = parallel_search_sources(
        sources,
        query=query,
        source_filter=source_filter,
        overall_timeout=30,
    )

    # A provider filter (nvidia/openai/...) is applied here, on the merged set,
    # because it targets the per-tap ``extra.provider`` label rather than a real
    # source id (the runtime index stores every GitHub tap as source="github").
    if source_filter.strip().lower() in _PROVIDER_FILTER_VALUES:
        all_results = _filter_results_by_provider(all_results, source_filter)

    # Deduplicate by identifier, preferring higher trust levels.
    # identifier is always unique per skill (e.g. "browse-sh/airbnb.com/search-listings-ddgioa").
    # Using name would incorrectly collapse browse-sh skills from different sites that share
    # the same task name (e.g. "search-listings" from Airbnb and Booking.com).
    _TRUST_RANK = {"builtin": 2, "trusted": 1, "community": 0}
    seen: Dict[str, SkillMeta] = {}
    for r in all_results:
        if r.identifier not in seen:
            seen[r.identifier] = r
        elif _TRUST_RANK.get(r.trust_level, 0) > _TRUST_RANK.get(
            seen[r.identifier].trust_level, 0
        ):
            seen[r.identifier] = r
    deduped = list(seen.values())

    return deduped[:limit]
