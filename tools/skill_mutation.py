"""Cross-process serialization primitives for profile skill mutations.

Capability-pack transactions acquire these locks in the fixed order
``config -> skills -> pack``.  The individual config/skills contexts are
public so the existing Hub, sync, and editor writers can migrate to the same
serialization boundary without importing capability-pack code.

The lock files are advisory.  Correctness therefore requires every
cooperating writer to use the shared contexts; callers must still revalidate
the exact path/digest immediately before each filesystem mutation.
"""

from __future__ import annotations

import contextlib
import errno
import json
import math
import os
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from tools.skill_install import is_path_redirect

try:  # pragma: no cover - platform-specific import
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - platform-specific import
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]


LOCK_POLL_SECONDS = 0.05
MAX_LOCK_TIMEOUT_SECONDS = 3600.0
_OWNER_LIMIT = 16 * 1024
_LOCK_ORDER = {"config": 0, "skills": 1, "pack": 2}


class SkillMutationLockError(RuntimeError):
    """A profile mutation lock could not be used safely."""


class SkillMutationLockTimeout(SkillMutationLockError, TimeoutError):
    """A finite lock acquisition deadline expired."""

    def __init__(self, kind: str, owner: dict[str, object] | None) -> None:
        self.kind = kind
        self.owner = owner
        detail = ""
        if owner:
            detail = (
                f"; current owner pid={owner.get('pid')} token={owner.get('token')}"
            )
        super().__init__(f"timed out acquiring {kind} mutation lock{detail}")


@dataclass(frozen=True)
class MutationLockLease:
    """Opaque evidence that one lock is held by the current thread."""

    kind: str
    token: str
    pid: int
    thread_id: int
    acquired_at: str
    home: str
    lock_path: str


@dataclass(frozen=True)
class PackMutationLocks:
    """The three leases held for one profile transaction."""

    config: MutationLockLease
    skills: MutationLockLease
    pack: MutationLockLease


_thread_locks_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}
_thread_state = threading.local()


@dataclass(frozen=True)
class _ActiveLock:
    lease: MutationLockLease
    fd: int
    identity: tuple[int, int]
    parent: _PinnedLockParent


@dataclass(frozen=True)
class _PinnedLockParent:
    """An identity-pinned lock parent held for the complete lease lifetime."""

    home: Path
    path: Path
    identity: tuple[int, int]
    home_identity: tuple[int, int]
    home_fd: int | None = None
    parent_fd: int | None = None
    windows_handles: tuple[int, ...] = ()


_active_locks_guard = threading.Lock()
_active_locks: dict[str, _ActiveLock] = {}


def _reset_lock_state_after_fork() -> None:  # pragma: no cover - exercised by fork test
    """Drop inherited leases and descriptors in a forked child.

    Kernel locks and Python ``Lock`` objects are inherited across ``fork`` in
    states that are not safe to reuse.  Closing the child's duplicate file
    descriptors leaves the parent's locks intact, while rebuilding the local
    registries forces the child through an ordinary kernel acquisition.
    """

    global _active_locks_guard, _active_locks
    global _thread_locks_guard, _thread_locks, _thread_state

    closed_fds: set[int] = set()
    closed_handles: set[int] = set()
    for active in tuple(_active_locks.values()):
        with contextlib.suppress(OSError):
            os.close(active.fd)
        closed_fds.add(active.fd)
        for fd in (active.parent.parent_fd, active.parent.home_fd):
            if fd is None or fd in closed_fds:
                continue
            with contextlib.suppress(OSError):
                os.close(fd)
            closed_fds.add(fd)
        for handle in reversed(active.parent.windows_handles):
            if handle in closed_handles:
                continue
            _windows_close_handle(handle)
            closed_handles.add(handle)
    _active_locks_guard = threading.Lock()
    _active_locks = {}
    _thread_locks_guard = threading.Lock()
    _thread_locks = {}
    _thread_state = threading.local()


if hasattr(os, "register_at_fork"):  # pragma: no branch - platform capability
    os.register_at_fork(after_in_child=_reset_lock_state_after_fork)


def _holder_depths() -> dict[str, tuple[int, MutationLockLease]]:
    depths = getattr(_thread_state, "depths", None)
    if depths is None:
        depths = {}
        _thread_state.depths = depths
    return depths


def _path_thread_lock(key: str) -> threading.Lock:
    with _thread_locks_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[key] = lock
        return lock


def _validated_timeout(timeout_seconds: float) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        raise SkillMutationLockError("lock timeout must be a finite positive number")
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_LOCK_TIMEOUT_SECONDS:
        raise SkillMutationLockError(
            f"lock timeout must be > 0 and <= {MAX_LOCK_TIMEOUT_SECONDS:g} seconds"
        )
    return timeout


def _lock_relative_parts(kind: str) -> tuple[str, str]:
    if kind == "pack":
        return "capability-packs", "lock"
    return ".locks", f"{kind}.lock"


def _lock_path(home: Path, *, kind: str) -> Path:
    parent_name, leaf_name = _lock_relative_parts(kind)
    return Path(home).resolve(strict=False) / parent_name / leaf_name


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _windows_close_handle(handle: int) -> None:  # pragma: no cover - Windows
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle(ctypes.c_void_p(handle))


def _windows_handle_information(
    handle: int,
) -> tuple[tuple[int, int], int, int]:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", FILETIME),
            ("last_access_time", FILETIME),
            ("last_write_time", FILETIME),
            ("volume_serial", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    information = BY_HANDLE_FILE_INFORMATION()
    if not kernel32.GetFileInformationByHandle(
        wintypes.HANDLE(handle), ctypes.byref(information)
    ):
        raise SkillMutationLockError("could not inspect Windows lock handle")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if information.attributes & reparse_flag:
        raise SkillMutationLockError("mutation lock path must not be a redirect")
    file_index = (information.file_index_high << 32) | information.file_index_low
    return (
        (information.volume_serial, file_index),
        information.number_of_links,
        information.attributes,
    )


def _windows_open_directory(
    path: Path,
) -> tuple[int, tuple[int, int]]:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    file_read_attributes = 0x0080
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    invalid_handle_value = ctypes.c_void_p(-1).value
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
    raw_handle = kernel32.CreateFileW(
        os.fspath(path),
        file_read_attributes,
        # FILE_SHARE_DELETE is deliberately absent. The directory cannot be
        # renamed out from under the subsequent native lock-file open.
        file_share_read | file_share_write,
        None,
        open_existing,
        file_flag_backup_semantics | file_flag_open_reparse_point,
        None,
    )
    handle = ctypes.cast(raw_handle, ctypes.c_void_p).value
    if handle in (None, invalid_handle_value):
        raise SkillMutationLockError("could not pin Windows lock directory")
    try:
        identity, _links, attributes = _windows_handle_information(handle)
        directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
        if not attributes & directory_flag:
            raise SkillMutationLockError("mutation-lock parent must be a directory")
        return handle, identity
    except BaseException:
        _windows_close_handle(handle)
        raise


def _validate_pinned_parent(parent: _PinnedLockParent) -> None:
    """Prove the expected profile pathname still names both pinned directories."""

    try:
        if os.name == "nt":  # pragma: no cover - Windows
            if len(parent.windows_handles) != 2:
                raise SkillMutationLockError(
                    "Windows mutation-lock parent is not pinned"
                )
            home_identity, _links, home_attributes = _windows_handle_information(
                parent.windows_handles[0]
            )
            identity, _links, attributes = _windows_handle_information(
                parent.windows_handles[1]
            )
            directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
            if (
                home_identity != parent.home_identity
                or identity != parent.identity
                or not home_attributes & directory_flag
                or not attributes & directory_flag
                or is_path_redirect(parent.home)
                or is_path_redirect(parent.path)
            ):
                raise SkillMutationLockError(
                    "mutation-lock parent pathname changed identity"
                )
            check_handle, check_identity = _windows_open_directory(parent.path)
            try:
                if check_identity != parent.identity:
                    raise SkillMutationLockError(
                        "mutation-lock parent pathname changed identity"
                    )
            finally:
                _windows_close_handle(check_handle)
            return

        if parent.home_fd is None or parent.parent_fd is None:
            raise SkillMutationLockError("mutation-lock parent is not pinned")
        opened_home = os.fstat(parent.home_fd)
        named_home = os.stat(parent.home, follow_symlinks=False)
        opened_parent = os.fstat(parent.parent_fd)
        named_parent = os.stat(
            parent.path.name,
            dir_fd=parent.home_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(opened_home.st_mode)
            or not stat.S_ISDIR(named_home.st_mode)
            or not stat.S_ISDIR(opened_parent.st_mode)
            or not stat.S_ISDIR(named_parent.st_mode)
            or _lock_file_identity(opened_home) != parent.home_identity
            or _lock_file_identity(named_home) != parent.home_identity
            or _lock_file_identity(opened_parent) != parent.identity
            or _lock_file_identity(named_parent) != parent.identity
        ):
            raise SkillMutationLockError(
                "mutation-lock parent pathname changed identity"
            )
    except SkillMutationLockError:
        raise
    except OSError as exc:
        raise SkillMutationLockError(
            "could not validate pinned mutation-lock parent"
        ) from exc


@contextmanager
def _pin_lock_parent(home: Path, *, kind: str) -> Iterator[_PinnedLockParent]:
    """Create and pin the expected profile-local parent without following it."""

    requested_home = Path(os.path.abspath(home))
    canonical_home = requested_home.resolve(strict=False)
    parent_name, _leaf_name = _lock_relative_parts(kind)
    parent_path = canonical_home / parent_name
    home_fd: int | None = None
    parent_fd: int | None = None
    windows_handles: list[int] = []
    try:
        if canonical_home.exists() and not canonical_home.is_dir():
            raise SkillMutationLockError("profile home must be a directory")
        if not canonical_home.exists():
            # Named profiles have an explicit lifecycle.  A process retaining
            # a stale HERMES_HOME after ``profile rename`` must not silently
            # recreate the old name and begin writing a replacement
            # generation.  Default/custom non-profile homes retain the
            # first-run create-on-lock behavior.
            if requested_home.parent.name == "profiles":
                raise SkillMutationLockError(
                    "named profile home no longer exists"
                )
            canonical_home.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":  # pragma: no cover - Windows
            home_handle, home_identity = _windows_open_directory(canonical_home)
            windows_handles.append(home_handle)
            try:
                parent_path.mkdir(mode=0o700)
            except FileExistsError:
                pass
            parent_handle, parent_identity = _windows_open_directory(parent_path)
            windows_handles.append(parent_handle)
            pinned = _PinnedLockParent(
                home=canonical_home,
                path=parent_path,
                identity=parent_identity,
                home_identity=home_identity,
                windows_handles=tuple(windows_handles),
            )
        else:
            home_fd = os.open(canonical_home, _directory_flags())
            opened_home = os.fstat(home_fd)
            named_home = os.stat(canonical_home, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened_home.st_mode)
                or not stat.S_ISDIR(named_home.st_mode)
                or _lock_file_identity(opened_home) != _lock_file_identity(named_home)
            ):
                raise SkillMutationLockError("profile home changed identity")
            try:
                os.mkdir(parent_name, 0o700, dir_fd=home_fd)
            except FileExistsError:
                pass
            parent_fd = os.open(parent_name, _directory_flags(), dir_fd=home_fd)
            opened_parent = os.fstat(parent_fd)
            named_parent = os.stat(
                parent_name,
                dir_fd=home_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(opened_parent.st_mode)
                or not stat.S_ISDIR(named_parent.st_mode)
                or _lock_file_identity(opened_parent)
                != _lock_file_identity(named_parent)
            ):
                raise SkillMutationLockError(
                    f"unsafe mutation-lock parent: {parent_name}"
                )
            pinned = _PinnedLockParent(
                home=canonical_home,
                path=parent_path,
                identity=_lock_file_identity(opened_parent),
                home_identity=_lock_file_identity(opened_home),
                home_fd=home_fd,
                parent_fd=parent_fd,
            )
        _validate_pinned_parent(pinned)
    except SkillMutationLockError:
        raise
    except OSError as exc:
        raise SkillMutationLockError(
            f"could not prepare mutation-lock parent {parent_name!r}"
        ) from exc

    try:
        # Deliberately keep the caller's body outside the preparation
        # exception handler. An OSError raised while the mutation is running
        # belongs to that mutation and must not be relabeled as lock setup.
        yield pinned
    finally:
        if parent_fd is not None:
            with contextlib.suppress(OSError):
                os.close(parent_fd)
        if home_fd is not None:
            with contextlib.suppress(OSError):
                os.close(home_fd)
        for handle in reversed(windows_handles):
            _windows_close_handle(handle)


def _lock_file_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _validate_open_lock_identity(
    parent: _PinnedLockParent,
    leaf_name: str,
    fd: int,
    *,
    expected: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Prove one lock descriptor is still the unique named lock file."""

    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise SkillMutationLockError(
                "mutation lock must be a uniquely linked regular file"
            )
        identity = _lock_file_identity(opened)
        if expected is not None and identity != expected:
            raise SkillMutationLockError("mutation lock descriptor changed identity")
        _validate_pinned_parent(parent)
        path = parent.path / leaf_name
        if is_path_redirect(path):
            raise SkillMutationLockError("mutation lock must not be a redirect")
        if os.name == "nt":  # pragma: no cover - Windows
            named = path.lstat()
        else:
            if parent.parent_fd is None:
                raise SkillMutationLockError("mutation-lock parent is not pinned")
            named = os.stat(
                leaf_name,
                dir_fd=parent.parent_fd,
                follow_symlinks=False,
            )
        if (
            not stat.S_ISREG(named.st_mode)
            or named.st_nlink != 1
            or _lock_file_identity(named) != identity
        ):
            raise SkillMutationLockError(
                "mutation lock pathname no longer names the held file"
            )
        return identity
    except SkillMutationLockError:
        raise
    except OSError as exc:
        raise SkillMutationLockError(
            "could not validate mutation lock identity"
        ) from exc


def _windows_open_lock_file(path: Path) -> int:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    if msvcrt is None:
        raise SkillMutationLockError("Windows lock runtime is unavailable")
    generic_read = 0x80000000
    generic_write = 0x40000000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_always = 4
    file_attribute_normal = 0x00000080
    file_flag_open_reparse_point = 0x00200000
    invalid_handle_value = ctypes.c_void_p(-1).value
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
    raw_handle = kernel32.CreateFileW(
        os.fspath(path),
        generic_read | generic_write,
        # Keep the lock pathname non-replaceable for the complete lease.
        file_share_read | file_share_write,
        None,
        open_always,
        file_attribute_normal | file_flag_open_reparse_point,
        None,
    )
    handle = ctypes.cast(raw_handle, ctypes.c_void_p).value
    if handle in (None, invalid_handle_value):
        raise SkillMutationLockError("could not safely open Windows mutation lock")
    try:
        _identity, links, attributes = _windows_handle_information(handle)
        directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
        if links != 1 or attributes & directory_flag:
            raise SkillMutationLockError(
                "mutation lock must be a uniquely linked regular file"
            )
        fd = msvcrt.open_osfhandle(
            handle,
            os.O_RDWR | getattr(os, "O_BINARY", 0),
        )
        handle = None
        return fd
    finally:
        if handle is not None:
            _windows_close_handle(handle)


def _open_lock_file(
    parent: _PinnedLockParent,
    leaf_name: str,
) -> tuple[int, tuple[int, int]]:
    try:
        _validate_pinned_parent(parent)
        path = parent.path / leaf_name
        if is_path_redirect(path):
            raise SkillMutationLockError("mutation lock must not be a redirect")
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if os.name == "nt":  # pragma: no cover - Windows
            fd = _windows_open_lock_file(path)
        else:
            if parent.parent_fd is None:
                raise SkillMutationLockError("mutation-lock parent is not pinned")
            for attempt in range(3):
                try:
                    fd = os.open(
                        leaf_name,
                        flags,
                        0o600,
                        dir_fd=parent.parent_fd,
                    )
                    break
                except FileNotFoundError:
                    # On macOS, concurrent first creation with O_NOFOLLOW can
                    # transiently report ENOENT. Re-prove the pinned parent
                    # before retrying; a genuinely replaced/removed parent
                    # still fails closed in validation.
                    _validate_pinned_parent(parent)
                    if attempt == 2:
                        raise
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise SkillMutationLockError(
                "mutation lock must be a uniquely linked regular file"
            )
        identity = _validate_open_lock_identity(parent, leaf_name, fd)
        if opened.st_size == 0:
            os.write(fd, b" ")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        _validate_open_lock_identity(parent, leaf_name, fd, expected=identity)
        return fd, identity
    except SkillMutationLockError:
        if "fd" in locals():
            with contextlib.suppress(OSError):
                os.close(fd)
        raise
    except OSError as exc:
        raise SkillMutationLockError("could not safely open mutation lock") from exc


def _acquire_kernel_lock(fd: int, deadline: float) -> bool:
    if fcntl is None and msvcrt is None:
        raise SkillMutationLockError("no supported kernel file-lock API is available")
    while True:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - Windows
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except (BlockingIOError, PermissionError):
            pass
        except OSError as exc:
            contention = {
                errno.EACCES,
                errno.EAGAIN,
                errno.EWOULDBLOCK,
                getattr(errno, "EDEADLK", errno.EACCES),
                getattr(errno, "EDEADLOCK", errno.EACCES),
            }
            if exc.errno not in contention and getattr(exc, "winerror", None) not in {
                32,
                33,
            }:
                raise SkillMutationLockError("kernel mutation lock failed") from exc
        if time.monotonic() >= deadline:
            return False
        time.sleep(LOCK_POLL_SECONDS)


def _release_kernel_lock(fd: int) -> None:
    with contextlib.suppress(OSError):
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _owner_payload(lease: MutationLockLease) -> bytes:
    return json.dumps(
        {
            "acquired_at": lease.acquired_at,
            "kind": lease.kind,
            "pid": lease.pid,
            "thread_id": lease.thread_id,
            "token": lease.token,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _write_owner(fd: int, lease: MutationLockLease) -> None:
    payload = _owner_payload(lease)
    if len(payload) > _OWNER_LIMIT:
        raise SkillMutationLockError("mutation-lock owner payload is too large")
    opened = os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
        raise SkillMutationLockError(
            "mutation lock must remain a uniquely linked regular file"
        )
    os.ftruncate(fd, 1)
    os.lseek(fd, 1, os.SEEK_SET)
    os.write(fd, payload)
    os.fsync(fd)


def _read_owner(fd: int) -> dict[str, object] | None:
    try:
        inspected = os.fstat(fd)
        if not stat.S_ISREG(inspected.st_mode) or inspected.st_nlink != 1:
            return None
        os.lseek(fd, 1, os.SEEK_SET)
        raw = os.read(fd, _OWNER_LIMIT + 1)
        if not raw or len(raw) > _OWNER_LIMIT:
            return None
        parsed = json.loads(raw.decode("ascii"))
        if not isinstance(parsed, dict):
            return None
        return parsed
    except (OSError, UnicodeError, ValueError):
        return None


def validate_mutation_lock_lease(
    home: Path,
    lease: MutationLockLease,
    *,
    kind: str,
) -> None:
    """Reject forged, inherited, released, wrong-home, or replaced leases."""

    if not isinstance(lease, MutationLockLease) or lease.kind != kind:
        raise SkillMutationLockError(f"active {kind} mutation lock is required")
    if lease.pid != os.getpid() or lease.thread_id != threading.get_ident():
        raise SkillMutationLockError(
            f"{kind} mutation lock belongs to another process or thread"
        )
    canonical_home = str(Path(home).resolve(strict=False))
    if lease.home != canonical_home:
        raise SkillMutationLockError(f"{kind} mutation lock belongs to another profile")
    with _active_locks_guard:
        active = _active_locks.get(lease.token)
    if active is None or active.lease != lease:
        raise SkillMutationLockError(f"{kind} mutation lock is not active")
    relative_path = (
        Path("capability-packs") / "lock"
        if kind == "pack"
        else Path(".locks") / f"{kind}.lock"
    )
    expected_path = os.fspath(Path(canonical_home) / relative_path)
    if lease.lock_path != expected_path:
        raise SkillMutationLockError(
            f"{kind} mutation lock path does not match profile"
        )
    _parent_name, leaf_name = _lock_relative_parts(kind)
    _validate_open_lock_identity(
        active.parent,
        leaf_name,
        active.fd,
        expected=active.identity,
    )


def duplicate_mutation_home_fd(
    home: Path,
    lease: MutationLockLease,
    *,
    kind: str,
) -> int | None:
    """Duplicate the POSIX profile-directory capability pinned by a lease.

    The returned descriptor remains valid if the profile pathname is renamed.
    Windows uses native directory handles that deny rename for the lease
    lifetime, so callers receive ``None`` and keep their native path flow.
    """

    validate_mutation_lock_lease(home, lease, kind=kind)
    if os.name == "nt":  # pragma: no cover - Windows uses pinned HANDLEs
        return None
    with _active_locks_guard:
        active = _active_locks.get(lease.token)
        if active is None or active.lease != lease:
            raise SkillMutationLockError(f"{kind} mutation lock is not active")
        home_fd = active.parent.home_fd
        expected_identity = active.parent.home_identity
        if home_fd is None:
            raise SkillMutationLockError("mutation profile directory is not pinned")
        duplicate = os.dup(home_fd)
    try:
        opened = os.fstat(duplicate)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != expected_identity
        ):
            raise SkillMutationLockError(
                "duplicated mutation profile capability changed identity"
            )
        return duplicate
    except BaseException:
        os.close(duplicate)
        raise


def duplicate_mutation_home_handle(
    home: Path,
    lease: MutationLockLease,
    *,
    kind: str,
) -> int | None:
    """Duplicate the native Windows profile-directory capability for a lease.

    Cleanup and recovery code can use this as the root for handle-relative
    native opens without reopening a replaceable profile pathname. POSIX
    callers keep using :func:`duplicate_mutation_home_fd` and receive ``None``.
    The caller owns the returned HANDLE and must close it.
    """

    validate_mutation_lock_lease(home, lease, kind=kind)
    if os.name != "nt":
        return None

    import ctypes  # pragma: no cover - Windows
    from ctypes import wintypes  # pragma: no cover - Windows

    duplicate_same_access = 0x00000002
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.DuplicateHandle.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.DuplicateHandle.restype = wintypes.BOOL

    with _active_locks_guard:
        active = _active_locks.get(lease.token)
        if active is None or active.lease != lease:
            raise SkillMutationLockError(f"{kind} mutation lock is not active")
        handles = active.parent.windows_handles
        if not handles:
            raise SkillMutationLockError("Windows mutation profile is not pinned")
        source = handles[0]
        expected_identity = active.parent.home_identity
        process = kernel32.GetCurrentProcess()
        duplicated = wintypes.HANDLE()
        if not kernel32.DuplicateHandle(
            process,
            wintypes.HANDLE(source),
            process,
            ctypes.byref(duplicated),
            0,
            False,
            duplicate_same_access,
        ):
            raise SkillMutationLockError(
                "could not duplicate Windows mutation profile handle"
            )

    duplicate_value = ctypes.cast(duplicated, ctypes.c_void_p).value
    if duplicate_value is None:
        raise SkillMutationLockError(
            "Windows mutation profile handle duplication returned no handle"
        )
    try:
        identity, _links, attributes = _windows_handle_information(duplicate_value)
        directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
        if identity != expected_identity or not attributes & directory_flag:
            raise SkillMutationLockError(
                "duplicated Windows mutation profile capability changed identity"
            )
        return duplicate_value
    except BaseException:
        _windows_close_handle(duplicate_value)
        raise


def validate_pack_mutation_locks(home: Path, locks: PackMutationLocks) -> None:
    """Prove the current thread actively holds all locks for one profile."""

    if not isinstance(locks, PackMutationLocks):
        raise SkillMutationLockError("recovery requires all three mutation locks")
    validate_mutation_lock_lease(home, locks.config, kind="config")
    validate_mutation_lock_lease(home, locks.skills, kind="skills")
    validate_mutation_lock_lease(home, locks.pack, kind="pack")


@contextmanager
def mutation_file_lock(
    home: Path,
    *,
    kind: str,
    timeout_seconds: float = 15.0,
) -> Iterator[MutationLockLease]:
    """Acquire one finite, reentrant, cross-process profile lock."""

    if kind not in {"config", "skills", "pack"}:
        raise SkillMutationLockError(f"unsupported mutation lock kind: {kind}")
    timeout = _validated_timeout(timeout_seconds)
    canonical_home_path = Path(home).resolve(strict=False)
    parent_name, leaf_name = _lock_relative_parts(kind)
    path = canonical_home_path / parent_name / leaf_name
    key = os.path.normcase(os.fspath(path))
    held = _holder_depths()
    existing = held.get(key)
    if existing is not None:
        depth, lease = existing
        validate_mutation_lock_lease(home, lease, kind=kind)
        held[key] = (depth + 1, lease)
        try:
            yield lease
        finally:
            current_depth, current_lease = held[key]
            if current_depth == 1:
                held.pop(key, None)
            else:
                held[key] = (current_depth - 1, current_lease)
        return

    canonical_home = str(Path(home).resolve(strict=False))
    for _depth, active_lease in held.values():
        if (
            active_lease.home == canonical_home
            and _LOCK_ORDER[kind] < _LOCK_ORDER[active_lease.kind]
        ):
            raise SkillMutationLockError(
                "mutation locks must be acquired in config -> skills -> pack order"
            )

    deadline = time.monotonic() + timeout
    thread_lock = _path_thread_lock(key)
    if not thread_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise SkillMutationLockTimeout(kind, None)
    fd: int | None = None
    kernel_locked = False
    identity: tuple[int, int] | None = None
    lease: MutationLockLease | None = None
    try:
        with _pin_lock_parent(canonical_home_path, kind=kind) as parent:
            fd, identity = _open_lock_file(parent, leaf_name)
            kernel_locked = _acquire_kernel_lock(fd, deadline)
            if not kernel_locked:
                raise SkillMutationLockTimeout(kind, _read_owner(fd))
            _validate_open_lock_identity(parent, leaf_name, fd, expected=identity)
            lease = MutationLockLease(
                kind=kind,
                token=str(uuid.uuid4()),
                pid=os.getpid(),
                thread_id=threading.get_ident(),
                acquired_at=datetime.now(timezone.utc).isoformat(),
                home=canonical_home,
                lock_path=os.fspath(path),
            )
            _write_owner(fd, lease)
            _validate_open_lock_identity(parent, leaf_name, fd, expected=identity)
            with _active_locks_guard:
                _active_locks[lease.token] = _ActiveLock(
                    lease=lease,
                    fd=fd,
                    identity=identity,
                    parent=parent,
                )
            validate_mutation_lock_lease(home, lease, kind=kind)
            held[key] = (1, lease)
            try:
                yield lease
            finally:
                held.pop(key, None)
                with _active_locks_guard:
                    _active_locks.pop(lease.token, None)
    finally:
        if lease is not None:
            with _active_locks_guard:
                _active_locks.pop(lease.token, None)
        if fd is not None:
            if kernel_locked:
                _release_kernel_lock(fd)
            with contextlib.suppress(OSError):
                os.close(fd)
        thread_lock.release()


def config_mutation_lock(
    home: Path, *, timeout_seconds: float = 15.0
) -> contextlib.AbstractContextManager[MutationLockLease]:
    return mutation_file_lock(home, kind="config", timeout_seconds=timeout_seconds)


def skill_mutation_lock(
    home: Path, *, timeout_seconds: float = 15.0
) -> contextlib.AbstractContextManager[MutationLockLease]:
    return mutation_file_lock(home, kind="skills", timeout_seconds=timeout_seconds)


def pack_profile_lock(
    home: Path, *, timeout_seconds: float = 15.0
) -> contextlib.AbstractContextManager[MutationLockLease]:
    return mutation_file_lock(home, kind="pack", timeout_seconds=timeout_seconds)


@contextmanager
def pack_mutation_locks(
    home: Path, *, timeout_seconds: float = 15.0
) -> Iterator[PackMutationLocks]:
    """Acquire the only supported lock order for pack mutation/recovery."""

    with config_mutation_lock(home, timeout_seconds=timeout_seconds) as config:
        with skill_mutation_lock(home, timeout_seconds=timeout_seconds) as skills:
            with pack_profile_lock(home, timeout_seconds=timeout_seconds) as pack:
                yield PackMutationLocks(config=config, skills=skills, pack=pack)


__all__ = [
    "MutationLockLease",
    "PackMutationLocks",
    "SkillMutationLockError",
    "SkillMutationLockTimeout",
    "config_mutation_lock",
    "duplicate_mutation_home_handle",
    "mutation_file_lock",
    "pack_mutation_locks",
    "pack_profile_lock",
    "skill_mutation_lock",
    "validate_mutation_lock_lease",
    "validate_pack_mutation_locks",
]
