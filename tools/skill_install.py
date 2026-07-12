"""Shared, side-effect-free path guards for skill installation.

The helpers in this module validate paths and inspect source trees; they do
not create, move, or delete files.  Callers performing a mutation must still
hold the profile's skill-mutation lock and revalidate immediately before the
filesystem operation.

The *root* passed to :func:`resolve_relative_path` is an explicit trust
boundary.  It may itself resolve through a symlink (for example, a profile
home mounted at another location), but redirects below that resolved root are
always rejected.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

_MAX_TREE_FILES = 10_000
_MAX_TREE_DIRECTORIES = 10_000
_MAX_TREE_ENTRIES = _MAX_TREE_FILES + _MAX_TREE_DIRECTORIES
_MAX_TREE_DEPTH = 64

# A security scan materializes captured bytes in memory so verdict and digest
# share one observation. Bound that allocation before the first read.
DEFAULT_SNAPSHOT_MAX_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_SNAPSHOT_MAX_TOTAL_BYTES = 32 * 1024 * 1024

_WINDOWS_INVALID_COMPONENT_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_COMPONENTS = frozenset({
    "AUX",
    "CLOCK$",
    "CON",
    "CONIN$",
    "CONOUT$",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
    *(f"COM{number}" for number in ("¹", "²", "³")),
    *(f"LPT{number}" for number in ("¹", "²", "³")),
})

TreeFile = tuple[PurePosixPath, Path]
FileState = tuple[int, int, int, int | None, int | None]
DirectoryState = tuple[int, int, int, int, int | None, int | None]


@dataclass(frozen=True)
class TreeSnapshotFile:
    """One immutable regular file captured through an attested descriptor."""

    relative_path: PurePosixPath
    content: bytes
    sha256: str
    state: FileState
    mode: int


@dataclass(frozen=True)
class TreeSnapshot:
    """A coherent regular-file tree captured from one opened root identity."""

    root_identity: tuple[int, int]
    files: tuple[TreeSnapshotFile, ...]
    tree_sha256: str
    content_sha256: str
    total_bytes: int
    # Windows cleanup carries the full volume + FILE_ID_128 identity because
    # Python 3.11's 64-bit ``st_ino`` cannot represent every ReFS identity.
    native_root_identity: tuple[int, bytes] | None = None


class UnsafePathError(ValueError):
    """A caller-controlled path or filesystem tree is unsafe to use."""


def _validate_portable_tree_paths(paths: tuple[PurePosixPath, ...]) -> None:
    # Validate the complete logical tree, not only complete file names.
    # Windows aliases every component case-insensitively, so ``Docs/a`` and
    # ``docs/b`` merge two source directories even though the full file paths
    # differ.  A file may also alias a directory (``tool`` + ``TOOL/run.py``),
    # which would make materialization order decide the resulting bytes.
    portable_nodes: dict[str, tuple[str, str]] = {}
    for relative in paths:
        components = relative.parts
        for index in range(1, len(components) + 1):
            source_node = "/".join(components[:index])
            node_kind = "file" if index == len(components) else "directory"
            portable_key = "/".join(
                unicodedata.normalize("NFC", component).casefold()
                for component in components[:index]
            )
            previous = portable_nodes.get(portable_key)
            if previous is None:
                portable_nodes[portable_key] = (source_node, node_kind)
                continue
            previous_source, previous_kind = previous
            if previous_source != source_node:
                raise _unsafe(
                    "tree",
                    f"cross-platform path collision: {source_node}",
                )
            if previous_kind != node_kind:
                raise _unsafe(
                    "tree",
                    f"cross-platform file/directory collision: {source_node}",
                )


def validate_portable_tree_paths(
    paths: tuple[str, ...],
    *,
    field: str = "tree path",
) -> tuple[str, ...]:
    """Validate a complete caller-supplied tree before any entry is written.

    The returned paths are canonical POSIX-relative names. Validation rejects
    Windows ADS/device/trailing-dot/control semantics and case/NFC collisions
    on every host, including before a case-insensitive filesystem can alias two
    bundle entries onto one destination.
    """

    canonical = tuple(
        normalize_relative_path(path, field=field) for path in paths
    )
    if len(set(canonical)) != len(canonical):
        raise _unsafe(field, "multiple entries normalize to the same path")
    try:
        _validate_portable_tree_paths(tuple(PurePosixPath(path) for path in canonical))
    except UnsafePathError as exc:
        reason = str(exc).partition(": ")[2] or str(exc)
        raise _unsafe(field, reason) from exc
    return canonical


def _unsafe(field: str, reason: str) -> UnsafePathError:
    return UnsafePathError(f"Unsafe {field}: {reason}")


def _file_state(value: os.stat_result) -> FileState:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        getattr(value, "st_mtime_ns", None),
        getattr(value, "st_ctime_ns", None),
    )


def _directory_state(value: os.stat_result) -> DirectoryState:
    return (
        value.st_dev,
        value.st_ino,
        value.st_nlink,
        value.st_size,
        getattr(value, "st_mtime_ns", None),
        getattr(value, "st_ctime_ns", None),
    )


def _validate_portable_component(component: str, *, field: str) -> None:
    if unicodedata.normalize("NFC", component) != component:
        raise _unsafe(field, "components must use NFC Unicode normalization")
    if component.endswith((" ", ".")):
        raise _unsafe(field, "components may not end with a space or period")
    if any(char in _WINDOWS_INVALID_COMPONENT_CHARS for char in component):
        raise _unsafe(field, "contains a character that is invalid on Windows")

    # Windows treats a reserved device basename as reserved even when it has
    # an extension (for example, ``NUL.txt``).  It also trims spaces and dots
    # from that basename during path interpretation.
    device_basename = component.split(".", 1)[0].rstrip(" .").upper()
    if device_basename in _WINDOWS_RESERVED_COMPONENTS:
        raise _unsafe(field, "contains a reserved Windows device name")


def normalize_relative_path(
    value: str,
    *,
    field: str = "relative path",
    allow_nested: bool = True,
) -> str:
    """Return a canonical POSIX relative path safe on supported hosts.

    Both slash styles are accepted as input and canonicalized to ``/``.
    Absolute, UNC, drive-qualified, traversal, control-character, and
    Windows-invalid paths are rejected even when running on POSIX.  ``.``
    components and repeated separators are normalized away.
    """

    if not isinstance(value, str):
        raise _unsafe(field, "expected a string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _unsafe(field, "must be valid UTF-8") from exc
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _unsafe(field, "control characters are not allowed")

    raw = value.strip()
    if not raw:
        raise _unsafe(field, "empty path")

    normalized = raw.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(raw)
    if (
        normalized.startswith("/")
        or posix_path.is_absolute()
        or bool(windows_path.drive)
        or bool(windows_path.root)
    ):
        raise _unsafe(field, "absolute, UNC, and drive-qualified paths are not allowed")

    parts = tuple(part for part in posix_path.parts if part not in {"", "."})
    if not parts:
        raise _unsafe(field, "empty path")
    if any(part == ".." for part in parts):
        raise _unsafe(field, "parent traversal is not allowed")
    if not allow_nested and len(parts) != 1:
        raise _unsafe(field, "nested paths are not allowed")

    for part in parts:
        _validate_portable_component(part, field=field)
    return "/".join(parts)


def validate_skill_name(name: str) -> str:
    """Normalize a skill name, which must be exactly one path component."""

    return normalize_relative_path(name, field="skill name", allow_nested=False)


def validate_install_parent_path(value: str) -> str:
    """Normalize an optional nested parent below a profile's skills root."""

    return normalize_relative_path(value, field="install parent path")


def normalize_skill_install_path(install_path: str, skill_name: str) -> str:
    """Normalize an install path and bind its final component to a skill."""

    safe_name = validate_skill_name(skill_name)
    normalized = normalize_relative_path(install_path, field="install path")
    if normalized.split("/")[-1] != safe_name:
        raise _unsafe("install path", "final component must match the skill name")
    return normalized


def normalize_lock_install_path(install_path: str, skill_name: str) -> str:
    """Compatibility spelling for lock-file install-path normalization."""

    return normalize_skill_install_path(install_path, skill_name)


def _is_windows() -> bool:
    return os.name == "nt"


def _get_windows_file_attributes(path: Path) -> int:
    """Read Win32 file attributes, including on Python 3.11.

    ``Path.is_junction`` was added in Python 3.12.  Calling the native API
    also catches other reparse-point redirects and keeps the guard identical
    across every supported Python version.
    """

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    get_attributes = kernel32.GetFileAttributesW
    get_attributes.argtypes = [ctypes.c_wchar_p]
    get_attributes.restype = ctypes.c_uint32
    ctypes.set_last_error(0)
    attributes = int(get_attributes(os.fspath(path)))
    if attributes == INVALID_FILE_ATTRIBUTES:
        error = ctypes.get_last_error()
        raise ctypes.WinError(error or 1)  # type: ignore[attr-defined]
    return attributes


def is_path_redirect(path: Path) -> bool:
    """Return whether *path* is a symlink, junction, or reparse point.

    Missing paths are not redirects.  Other inspection failures propagate so
    security-sensitive callers fail closed instead of treating an unreadable
    entry as a regular path.
    """

    candidate = Path(path)
    try:
        mode = candidate.lstat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        return False
    if stat.S_ISLNK(mode):
        return True
    if not _is_windows():
        return False
    return bool(_get_windows_file_attributes(candidate) & FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_relative_path(
    root: Path,
    relative: str,
    *,
    must_exist: bool = True,
) -> Path:
    """Resolve a strict child of *root* without following child redirects.

    Existing components are inspected one at a time before final resolution.
    The resolved result may never equal or escape the resolved root.  Set
    ``must_exist=False`` only when validating a destination that has not yet
    been created.
    """

    normalized = normalize_relative_path(relative)
    root_path = Path(root)
    try:
        # A valid redirected root is an explicit caller-owned trust boundary,
        # but a broken redirected root has no stable boundary to contain the
        # destination.  Resolve that case strictly even for a new target.
        root_is_redirect = is_path_redirect(root_path)
        root_resolved = root_path.resolve(strict=must_exist or root_is_redirect)
    except (OSError, RuntimeError) as exc:
        raise _unsafe("root", "cannot be resolved") from exc

    if root_resolved.exists() and not root_resolved.is_dir():
        raise _unsafe("root", "must be a directory")

    candidate = root_resolved
    parts = normalized.split("/")
    for index, part in enumerate(parts):
        candidate = candidate / part
        try:
            redirect = is_path_redirect(candidate)
        except OSError as exc:
            raise _unsafe(
                "relative path", "could not inspect a path component"
            ) from exc
        if redirect:
            raise _unsafe(
                "relative path", "symlink and reparse-point components are not allowed"
            )
        if index < len(parts) - 1 and candidate.exists() and not candidate.is_dir():
            raise _unsafe(
                "relative path", "an intermediate component is not a directory"
            )

    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        requirement = "does not exist" if must_exist else "cannot be resolved"
        raise _unsafe("relative path", requirement) from exc

    if resolved == root_resolved or not resolved.is_relative_to(root_resolved):
        raise _unsafe("relative path", "resolved path escapes its root")
    return resolved


def resolve_skill_install_path(
    skills_root: Path,
    install_path: str,
    skill_name: str,
    *,
    must_exist: bool = False,
) -> Path:
    """Normalize and safely resolve a skill's bound install destination."""

    normalized = normalize_skill_install_path(install_path, skill_name)
    return resolve_relative_path(skills_root, normalized, must_exist=must_exist)


def _canonical_tree_relative(root: Path, path: Path) -> PurePosixPath:
    relative = PurePosixPath(path.relative_to(root).as_posix())
    canonical = normalize_relative_path(relative.as_posix(), field="tree path")
    if canonical != relative.as_posix():
        raise _unsafe("tree path", "entry name is not in canonical portable form")
    return relative


def iter_regular_files(root: Path) -> tuple[TreeFile, ...]:
    """Enumerate a non-empty regular-file tree without following redirects.

    Results are immutable ``(relative_posix_path, absolute_path)`` pairs,
    ordered by the UTF-8 bytes of the complete relative POSIX path.  Empty
    directories are ignored; an entirely empty tree is invalid.
    """

    root_path = Path(root)
    try:
        if is_path_redirect(root_path):
            raise _unsafe(
                "tree root", "symlink and reparse-point roots are not allowed"
            )
        root_mode = root_path.lstat().st_mode
    except UnsafePathError:
        raise
    except (OSError, RuntimeError) as exc:
        raise _unsafe("tree root", "must be an existing readable directory") from exc
    if not stat.S_ISDIR(root_mode):
        raise _unsafe("tree root", "must be a directory")

    try:
        root_resolved = root_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _unsafe("tree root", "cannot be resolved") from exc

    files: list[TreeFile] = []
    directory_count = 0
    entry_count = 0

    def visit(directory: Path, *, depth: int) -> None:
        nonlocal directory_count, entry_count
        if depth > _MAX_TREE_DEPTH:
            raise _unsafe("tree", f"directory nesting exceeds {_MAX_TREE_DEPTH} levels")
        directory_count += 1
        if directory_count > _MAX_TREE_DIRECTORIES:
            raise _unsafe(
                "tree", f"contains more than {_MAX_TREE_DIRECTORIES} directories"
            )
        try:
            with os.scandir(directory) as entries:
                children = []
                for entry in entries:
                    if entry_count + len(children) >= _MAX_TREE_ENTRIES:
                        raise _unsafe(
                            "tree",
                            f"contains more than {_MAX_TREE_ENTRIES} entries",
                        )
                    children.append(entry)
        except OSError as exc:
            raise _unsafe("tree", "could not enumerate a directory") from exc
        children.sort(key=lambda entry: entry.name)

        for entry in children:
            entry_count += 1
            if entry_count > _MAX_TREE_ENTRIES:
                raise _unsafe("tree", f"contains more than {_MAX_TREE_ENTRIES} entries")
            path = directory / entry.name
            relative = _canonical_tree_relative(root_resolved, path)
            try:
                if is_path_redirect(path):
                    raise _unsafe(
                        "tree",
                        f"redirects are not allowed: {relative.as_posix()}",
                    )
                mode = entry.stat(follow_symlinks=False).st_mode
            except UnsafePathError:
                raise
            except OSError as exc:
                raise _unsafe(
                    "tree", f"could not inspect {relative.as_posix()}"
                ) from exc

            if stat.S_ISDIR(mode):
                visit(path, depth=depth + 1)
            elif stat.S_ISREG(mode):
                files.append((relative, path))
                if len(files) > _MAX_TREE_FILES:
                    raise _unsafe("tree", f"contains more than {_MAX_TREE_FILES} files")
            else:
                raise _unsafe(
                    "tree",
                    f"unsupported filesystem entry: {relative.as_posix()}",
                )

    try:
        visit(root_resolved, depth=0)
    except RecursionError as exc:
        raise _unsafe(
            "tree", "directory nesting exceeds the safe recursion limit"
        ) from exc
    if not files:
        raise _unsafe("tree", "must contain at least one regular file")

    _validate_portable_tree_paths(tuple(relative for relative, _path in files))

    try:
        files.sort(key=lambda item: item[0].as_posix().encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise _unsafe("tree path", "must be valid UTF-8") from exc
    return tuple(files)


def _sha256_regular_file(
    path: Path, *, max_file_bytes: int | None = None
) -> tuple[bytes, int]:
    """Hash one stable regular file without following a POSIX symlink."""

    if is_path_redirect(path):
        raise _unsafe("tree", f"redirects are not allowed: {path}")
    try:
        before = path.lstat()
    except OSError as exc:
        raise _unsafe("tree", f"could not inspect file: {path}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise _unsafe("tree", f"entry is not a regular file: {path}")
    if max_file_bytes is not None and before.st_size > max_file_bytes:
        raise _unsafe("tree", f"file exceeds {max_file_bytes} bytes: {path}")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _unsafe("tree", f"could not safely open file: {path}") from exc

    digest = hashlib.sha256()
    bytes_read = 0
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise _unsafe("tree", f"entry changed type while hashing: {path}")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise _unsafe("tree", f"entry changed while hashing: {path}")

        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            if max_file_bytes is not None and bytes_read > max_file_bytes:
                raise _unsafe(
                    "tree", f"file grew beyond {max_file_bytes} bytes: {path}"
                )
            digest.update(chunk)

        after = os.fstat(descriptor)
        before_state = _file_state(opened)
        after_state = _file_state(after)
        if before_state != after_state:
            raise _unsafe("tree", f"entry changed while hashing: {path}")
        if bytes_read != after.st_size:
            raise _unsafe("tree", f"file byte count differs from metadata: {path}")
    finally:
        os.close(descriptor)

    if is_path_redirect(path):
        raise _unsafe("tree", f"entry changed into a redirect while hashing: {path}")
    try:
        final = path.lstat()
    except OSError as exc:
        raise _unsafe("tree", f"entry disappeared while hashing: {path}") from exc
    if (opened.st_dev, opened.st_ino) != (final.st_dev, final.st_ino):
        raise _unsafe("tree", f"entry changed while hashing: {path}")
    final_state = _file_state(final)
    if after_state != final_state:
        raise _unsafe("tree", f"entry changed while hashing: {path}")
    return digest.digest(), bytes_read


def _sha256_open_file(
    descriptor: int,
    *,
    label: str,
    max_file_bytes: int | None,
) -> tuple[str, int]:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        raise _unsafe("tree", f"entry is not a regular file: {label}")
    if max_file_bytes is not None and opened.st_size > max_file_bytes:
        raise _unsafe("tree", f"file exceeds {max_file_bytes} bytes: {label}")
    before_state = (
        opened.st_size,
        getattr(opened, "st_mtime_ns", None),
        getattr(opened, "st_ctime_ns", None),
    )
    digest = hashlib.sha256()
    bytes_read = 0
    while True:
        read_size = 1024 * 1024
        if max_file_bytes is not None:
            # Never ask the kernel for a full chunk once only a small budget
            # remains. The single sentinel byte detects growth past the cap.
            read_size = min(read_size, max(1, max_file_bytes - bytes_read + 1))
        chunk = os.read(descriptor, read_size)
        if not chunk:
            break
        bytes_read += len(chunk)
        if max_file_bytes is not None and bytes_read > max_file_bytes:
            raise _unsafe("tree", f"file grew beyond {max_file_bytes} bytes: {label}")
        digest.update(chunk)
    after = os.fstat(descriptor)
    after_state = (
        after.st_size,
        getattr(after, "st_mtime_ns", None),
        getattr(after, "st_ctime_ns", None),
    )
    if (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
        raise _unsafe("tree", f"entry changed identity while hashing: {label}")
    if before_state != after_state:
        raise _unsafe("tree", f"entry changed while hashing: {label}")
    if bytes_read != after.st_size:
        raise _unsafe("tree", f"file byte count differs from metadata: {label}")
    return digest.hexdigest(), bytes_read


def _read_open_snapshot_file(
    descriptor: int,
    *,
    label: str,
    max_file_bytes: int | None,
) -> tuple[bytes, str, FileState, int]:
    """Read and hash exactly the bytes behind one already-open descriptor."""

    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        raise _unsafe("tree", f"entry is not a regular file: {label}")
    if max_file_bytes is not None and opened.st_size > max_file_bytes:
        raise _unsafe("tree", f"file exceeds {max_file_bytes} bytes: {label}")
    opened_state = _file_state(opened)
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    bytes_read = 0
    while True:
        read_size = 1024 * 1024
        if max_file_bytes is not None:
            read_size = min(
                read_size,
                max(1, max_file_bytes - bytes_read + 1),
            )
        chunk = os.read(descriptor, read_size)
        if not chunk:
            break
        bytes_read += len(chunk)
        if max_file_bytes is not None and bytes_read > max_file_bytes:
            raise _unsafe("tree", f"file grew beyond {max_file_bytes} bytes: {label}")
        chunks.append(chunk)
        digest.update(chunk)
    after = os.fstat(descriptor)
    after_state = _file_state(after)
    if opened_state != after_state or bytes_read != after.st_size:
        raise _unsafe("tree", f"entry changed while capturing: {label}")
    return b"".join(chunks), digest.hexdigest(), after_state, after.st_mode


def _build_tree_snapshot(
    root_identity: tuple[int, int],
    files: list[TreeSnapshotFile],
) -> TreeSnapshot:
    if not files:
        raise _unsafe("tree", "must contain at least one regular file")
    _validate_portable_tree_paths(tuple(item.relative_path for item in files))
    files.sort(
        key=lambda item: item.relative_path.as_posix().encode("utf-8", errors="strict")
    )
    tree_digest = hashlib.sha256()
    content_digest = hashlib.sha256()
    total_bytes = 0
    for item in files:
        encoded_path = item.relative_path.as_posix().encode("utf-8")
        tree_digest.update(encoded_path)
        tree_digest.update(b"\0")
        tree_digest.update(item.sha256.encode("ascii"))
        tree_digest.update(b"\0")
        content_digest.update(encoded_path)
        content_digest.update(b"\0")
        content_digest.update(item.content)
        total_bytes += len(item.content)
    return TreeSnapshot(
        root_identity=root_identity,
        files=tuple(files),
        tree_sha256=tree_digest.hexdigest(),
        content_sha256=content_digest.hexdigest(),
        total_bytes=total_bytes,
    )


def _capture_tree_snapshot_descriptor_relative(
    root: Path | None,
    *,
    max_file_bytes: int | None,
    max_total_bytes: int | None,
    max_files: int,
    root_descriptor: int | None = None,
) -> TreeSnapshot:
    """Capture one POSIX tree through a stable hierarchy of open descriptors."""

    root_path = Path(root) if root is not None else None
    if root_descriptor is not None:
        try:
            root_before = os.fstat(root_descriptor)
        except OSError as exc:
            raise _unsafe("tree root", "descriptor is not readable") from exc
    else:
        assert root_path is not None
        try:
            if is_path_redirect(root_path):
                raise _unsafe("tree root", "redirect roots are not allowed")
            root_before = root_path.lstat()
        except UnsafePathError:
            raise
        except OSError as exc:
            raise _unsafe(
                "tree root", "must be an existing readable directory"
            ) from exc
    if not stat.S_ISDIR(root_before.st_mode):
        raise _unsafe("tree root", "must be a directory")

    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        root_fd = (
            os.dup(root_descriptor)
            if root_descriptor is not None
            else os.open(root_path, directory_flags)
        )
    except OSError as exc:
        raise _unsafe(
            "tree root", "could not be opened without following redirects"
        ) from exc

    records: list[TreeSnapshotFile] = []
    directory_records: list[
        tuple[PurePosixPath | None, DirectoryState, tuple[str, ...]]
    ] = []
    total_bytes = 0
    directory_count = 0
    entry_count = 0

    def visit(
        directory_fd: int,
        prefix: PurePosixPath | None = None,
        *,
        depth: int,
    ) -> None:
        nonlocal total_bytes, directory_count, entry_count
        if depth > _MAX_TREE_DEPTH:
            raise _unsafe("tree", f"directory nesting exceeds {_MAX_TREE_DEPTH} levels")
        directory_count += 1
        if directory_count > _MAX_TREE_DIRECTORIES:
            raise _unsafe(
                "tree", f"contains more than {_MAX_TREE_DIRECTORIES} directories"
            )
        before_directory = os.fstat(directory_fd)
        before_directory_state = _directory_state(before_directory)
        try:
            initial_names = []
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if entry_count + len(initial_names) >= _MAX_TREE_ENTRIES:
                        raise _unsafe(
                            "tree",
                            f"contains more than {_MAX_TREE_ENTRIES} entries",
                        )
                    initial_names.append(entry.name)
            initial_names.sort(key=lambda name: name.encode("utf-8", errors="strict"))
        except (OSError, UnicodeEncodeError) as exc:
            raise _unsafe("tree", "could not enumerate a directory") from exc

        for name in initial_names:
            entry_count += 1
            if entry_count > _MAX_TREE_ENTRIES:
                raise _unsafe("tree", f"contains more than {_MAX_TREE_ENTRIES} entries")
            relative_raw = name if prefix is None else f"{prefix.as_posix()}/{name}"
            canonical = normalize_relative_path(relative_raw, field="tree path")
            if canonical != relative_raw:
                raise _unsafe("tree path", f"entry is not canonical: {relative_raw}")
            relative = PurePosixPath(canonical)
            try:
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise _unsafe("tree", f"could not inspect {relative}") from exc

            if stat.S_ISDIR(before.st_mode):
                try:
                    child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
                except OSError as exc:
                    raise _unsafe(
                        "tree", f"could not safely open directory {relative}"
                    ) from exc
                try:
                    opened = os.fstat(child_fd)
                    if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        raise _unsafe(
                            "tree", f"directory changed before open: {relative}"
                        )
                    visit(child_fd, relative, depth=depth + 1)
                finally:
                    os.close(child_fd)
                try:
                    final = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError as exc:
                    raise _unsafe("tree", f"directory disappeared: {relative}") from exc
                if _directory_state(before) != _directory_state(final):
                    raise _unsafe(
                        "tree", f"directory changed while capturing: {relative}"
                    )
                continue

            if stat.S_ISLNK(before.st_mode):
                raise _unsafe("tree", f"symlink redirects are not allowed: {relative}")
            if not stat.S_ISREG(before.st_mode):
                raise _unsafe("tree", f"unsupported filesystem entry: {relative}")
            if len(records) >= max_files:
                raise _unsafe("tree", f"contains more than {max_files} files")
            try:
                file_fd = os.open(name, file_flags, dir_fd=directory_fd)
            except OSError as exc:
                raise _unsafe("tree", f"could not safely open file {relative}") from exc
            try:
                opened = os.fstat(file_fd)
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise _unsafe("tree", f"file changed before open: {relative}")
                dynamic_limit = max_file_bytes
                if max_total_bytes is not None:
                    remaining = max_total_bytes - total_bytes
                    if remaining < 0:
                        raise _unsafe(
                            "tree", f"tree exceeds {max_total_bytes} total bytes"
                        )
                    dynamic_limit = (
                        remaining
                        if dynamic_limit is None
                        else min(dynamic_limit, remaining)
                    )
                content, file_digest, captured_state, mode = _read_open_snapshot_file(
                    file_fd,
                    label=relative.as_posix(),
                    max_file_bytes=dynamic_limit,
                )
            finally:
                os.close(file_fd)
            try:
                final = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise _unsafe("tree", f"file disappeared: {relative}") from exc
            if _file_state(final) != captured_state:
                raise _unsafe("tree", f"file changed while capturing: {relative}")
            total_bytes += len(content)
            records.append(
                TreeSnapshotFile(relative, content, file_digest, captured_state, mode)
            )

        try:
            final_names = []
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if len(final_names) >= len(initial_names):
                        raise _unsafe("tree", "directory entries changed while capturing")
                    final_names.append(entry.name)
            final_names.sort(key=lambda name: name.encode("utf-8", errors="strict"))
        except (OSError, UnicodeEncodeError) as exc:
            raise _unsafe("tree", "could not re-enumerate a directory") from exc
        if initial_names != final_names:
            raise _unsafe("tree", "directory entries changed while capturing")
        after_directory_state = _directory_state(os.fstat(directory_fd))
        if before_directory_state != after_directory_state:
            raise _unsafe("tree", "directory metadata changed while capturing")
        directory_records.append((prefix, after_directory_state, tuple(initial_names)))

    try:
        root_opened = os.fstat(root_fd)
        if _directory_state(root_before) != _directory_state(root_opened):
            raise _unsafe("tree root", "changed before open")
        try:
            visit(root_fd, depth=0)
        except RecursionError as exc:
            raise _unsafe(
                "tree", "directory nesting exceeds the safe recursion limit"
            ) from exc

        # Re-open every captured node relative to the still-open root. This
        # catches an early file changing while a later sibling was read.
        for record in records:
            parent_fd = root_fd
            opened_directories: list[int] = []
            file_fd: int | None = None
            try:
                for component in record.relative_path.parts[:-1]:
                    child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
                    opened_directories.append(child_fd)
                    parent_fd = child_fd
                file_fd = os.open(
                    record.relative_path.parts[-1], file_flags, dir_fd=parent_fd
                )
                current = os.fstat(file_fd)
                if (
                    not stat.S_ISREG(current.st_mode)
                    or _file_state(current) != record.state
                ):
                    raise _unsafe(
                        "tree", f"file changed after capture: {record.relative_path}"
                    )
            except OSError as exc:
                raise _unsafe(
                    "tree",
                    f"could not revalidate captured file: {record.relative_path}",
                ) from exc
            finally:
                if file_fd is not None:
                    os.close(file_fd)
                for opened_directory in reversed(opened_directories):
                    os.close(opened_directory)

        for relative, expected_state, expected_names in directory_records:
            directory_fd = root_fd
            opened_directories = []
            try:
                if relative is not None:
                    for component in relative.parts:
                        child_fd = os.open(
                            component, directory_flags, dir_fd=directory_fd
                        )
                        opened_directories.append(child_fd)
                        directory_fd = child_fd
                current_names = []
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        if len(current_names) >= len(expected_names):
                            raise _unsafe(
                                "tree", f"directory changed after capture: {relative}"
                            )
                        current_names.append(entry.name)
                current_names.sort(
                    key=lambda name: name.encode("utf-8", errors="strict")
                )
                if (
                    _directory_state(os.fstat(directory_fd)) != expected_state
                    or tuple(current_names) != expected_names
                ):
                    label = relative.as_posix() if relative is not None else "."
                    raise _unsafe("tree", f"directory changed after capture: {label}")
            except OSError as exc:
                label = relative.as_posix() if relative is not None else "."
                raise _unsafe(
                    "tree", f"could not revalidate captured directory: {label}"
                ) from exc
            finally:
                for opened_directory in reversed(opened_directories):
                    os.close(opened_directory)
        root_final = os.fstat(root_fd)
    finally:
        os.close(root_fd)

    if root_descriptor is None:
        assert root_path is not None
        try:
            root_final = root_path.lstat()
        except OSError as exc:
            raise _unsafe("tree root", "disappeared while capturing") from exc
    if _directory_state(root_before) != _directory_state(root_final):
        raise _unsafe("tree root", "changed while capturing")
    return _build_tree_snapshot(
        (root_before.st_dev, root_before.st_ino),
        records,
    )


def _capture_tree_snapshot_portable(
    root: Path,
    *,
    max_file_bytes: int | None,
    max_total_bytes: int | None,
    max_files: int,
) -> TreeSnapshot:
    """Capture fallback for platforms without descriptor-relative traversal."""

    root_path = Path(root)
    root_before = root_path.lstat()
    records: list[TreeSnapshotFile] = []
    total_bytes = 0
    for relative, path in iter_regular_files(root_path):
        if len(records) >= max_files:
            raise _unsafe("tree", f"contains more than {max_files} files")
        if is_path_redirect(path):
            raise _unsafe("tree", f"redirects are not allowed: {relative}")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise _unsafe("tree", f"entry is not a regular file: {relative}")
        dynamic_limit = max_file_bytes
        if max_total_bytes is not None:
            remaining = max_total_bytes - total_bytes
            if remaining < 0:
                raise _unsafe("tree", f"tree exceeds {max_total_bytes} total bytes")
            dynamic_limit = (
                remaining if dynamic_limit is None else min(dynamic_limit, remaining)
            )
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise _unsafe("tree", f"could not safely open file: {relative}") from exc
        try:
            opened = os.fstat(descriptor)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise _unsafe("tree", f"entry changed before capture: {relative}")
            content, file_digest, captured_state, mode = _read_open_snapshot_file(
                descriptor,
                label=relative.as_posix(),
                max_file_bytes=dynamic_limit,
            )
        finally:
            os.close(descriptor)
        final = path.lstat()
        if is_path_redirect(path) or _file_state(final) != captured_state:
            raise _unsafe("tree", f"entry changed while capturing: {relative}")
        total_bytes += len(content)
        records.append(
            TreeSnapshotFile(relative, content, file_digest, captured_state, mode)
        )

    final_files = iter_regular_files(root_path)
    if tuple(item.relative_path for item in records) != tuple(
        relative for relative, _path in final_files
    ):
        raise _unsafe("tree", "entries changed after capture")
    for record, (_relative, path) in zip(records, final_files):
        if _file_state(path.lstat()) != record.state:
            raise _unsafe("tree", f"file changed after capture: {record.relative_path}")
    root_final = root_path.lstat()
    if _directory_state(root_before) != _directory_state(root_final):
        raise _unsafe("tree root", "changed while capturing")
    return _build_tree_snapshot(
        (root_before.st_dev, root_before.st_ino),
        records,
    )


def capture_tree_snapshot(
    root: Path,
    *,
    max_file_bytes: int | None = DEFAULT_SNAPSHOT_MAX_FILE_BYTES,
    max_total_bytes: int | None = DEFAULT_SNAPSHOT_MAX_TOTAL_BYTES,
    max_files: int = _MAX_TREE_FILES,
) -> TreeSnapshot:
    """Capture one coherent tree whose digest and bytes share an identity.

    On POSIX, every byte is read through a descriptor opened relative to the
    already-open parent directory with ``O_NOFOLLOW``. The returned digest is
    computed from those exact bytes, allowing scanners and promotion code to
    bind policy and provenance to the same immutable observation.
    """

    if max_files < 1 or max_files > _MAX_TREE_FILES:
        raise ValueError(f"max_files must be between 1 and {_MAX_TREE_FILES}")
    if os.name != "nt" and all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")
    ):
        return _capture_tree_snapshot_descriptor_relative(
            root,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
            max_files=max_files,
        )
    return _capture_tree_snapshot_portable(
        root,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        max_files=max_files,
    )


def capture_tree_snapshot_fd(
    descriptor: int,
    *,
    max_file_bytes: int | None = DEFAULT_SNAPSHOT_MAX_FILE_BYTES,
    max_total_bytes: int | None = DEFAULT_SNAPSHOT_MAX_TOTAL_BYTES,
    max_files: int = _MAX_TREE_FILES,
) -> TreeSnapshot:
    """Capture a POSIX tree from an already-open directory capability.

    Unlike :func:`capture_tree_snapshot`, this never consults a pathname for
    the root generation. It is intended for recovery code that must keep
    operating on a profile directory after its lexical name is replaced.
    """

    if os.name == "nt" or not all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")
    ):
        raise NotImplementedError(
            "descriptor-root tree capture is only available on POSIX"
        )
    if max_files < 1 or max_files > _MAX_TREE_FILES:
        raise ValueError(f"max_files must be between 1 and {_MAX_TREE_FILES}")
    return _capture_tree_snapshot_descriptor_relative(
        None,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        max_files=max_files,
        root_descriptor=descriptor,
    )


def _sha256_tree_descriptor_relative(
    root: Path,
    *,
    max_file_bytes: int | None,
    max_total_bytes: int | None,
) -> str:
    """Hash a POSIX tree through stable directory descriptors.

    Every child is opened relative to its already-open parent with
    ``O_NOFOLLOW`` and its identity is compared before and after traversal.
    A concurrent rename/symlink swap therefore fails instead of escaping the
    checked root.
    """

    root_path = Path(root)
    try:
        if is_path_redirect(root_path):
            raise _unsafe("tree root", "redirect roots are not allowed")
        root_before = root_path.lstat()
    except UnsafePathError:
        raise
    except OSError as exc:
        raise _unsafe("tree root", "must be an existing readable directory") from exc
    if not stat.S_ISDIR(root_before.st_mode):
        raise _unsafe("tree root", "must be a directory")

    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        root_fd = os.open(root_path, directory_flags)
    except OSError as exc:
        raise _unsafe(
            "tree root", "could not be opened without following redirects"
        ) from exc

    records: list[tuple[PurePosixPath, str, FileState]] = []
    directory_records: list[
        tuple[PurePosixPath | None, DirectoryState, tuple[str, ...]]
    ] = []
    total_bytes = 0
    directory_count = 0
    entry_count = 0

    def visit(
        directory_fd: int,
        prefix: PurePosixPath | None = None,
        *,
        depth: int,
    ) -> None:
        nonlocal directory_count, entry_count, total_bytes
        if depth > _MAX_TREE_DEPTH:
            raise _unsafe("tree", f"directory nesting exceeds {_MAX_TREE_DEPTH} levels")
        directory_count += 1
        if directory_count > _MAX_TREE_DIRECTORIES:
            raise _unsafe(
                "tree", f"contains more than {_MAX_TREE_DIRECTORIES} directories"
            )
        directory_before = os.fstat(directory_fd)
        directory_state_before = _directory_state(directory_before)
        try:
            initial_names = os.listdir(directory_fd)
        except OSError as exc:
            raise _unsafe("tree", "could not enumerate a directory") from exc
        initial_names.sort(key=lambda name: name.encode("utf-8", errors="strict"))
        for name in initial_names:
            entry_count += 1
            if entry_count > _MAX_TREE_ENTRIES:
                raise _unsafe("tree", f"contains more than {_MAX_TREE_ENTRIES} entries")
            relative_raw = name if prefix is None else f"{prefix.as_posix()}/{name}"
            canonical = normalize_relative_path(relative_raw, field="tree path")
            if canonical != relative_raw:
                raise _unsafe("tree path", f"entry is not canonical: {relative_raw}")
            relative = PurePosixPath(canonical)
            try:
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise _unsafe("tree", f"could not inspect {relative}") from exc
            if stat.S_ISDIR(before.st_mode):
                try:
                    child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
                except OSError as exc:
                    raise _unsafe(
                        "tree", f"could not safely open directory {relative}"
                    ) from exc
                try:
                    opened = os.fstat(child_fd)
                    if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        raise _unsafe(
                            "tree", f"directory changed before open: {relative}"
                        )
                    visit(child_fd, relative, depth=depth + 1)
                finally:
                    os.close(child_fd)
                try:
                    final = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError as exc:
                    raise _unsafe("tree", f"directory disappeared: {relative}") from exc
                if _directory_state(before) != _directory_state(final):
                    raise _unsafe(
                        "tree", f"directory changed while hashing: {relative}"
                    )
                continue
            if not stat.S_ISREG(before.st_mode):
                raise _unsafe("tree", f"unsupported filesystem entry: {relative}")
            try:
                file_fd = os.open(name, file_flags, dir_fd=directory_fd)
            except OSError as exc:
                raise _unsafe("tree", f"could not safely open file {relative}") from exc
            try:
                opened = os.fstat(file_fd)
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise _unsafe("tree", f"file changed before open: {relative}")
                if (
                    max_total_bytes is not None
                    and total_bytes + opened.st_size > max_total_bytes
                ):
                    raise _unsafe("tree", f"tree exceeds {max_total_bytes} total bytes")
                dynamic_file_limit = max_file_bytes
                if max_total_bytes is not None:
                    remaining_total = max_total_bytes - total_bytes
                    dynamic_file_limit = (
                        remaining_total
                        if dynamic_file_limit is None
                        else min(dynamic_file_limit, remaining_total)
                    )
                file_digest, bytes_read = _sha256_open_file(
                    file_fd,
                    label=relative.as_posix(),
                    max_file_bytes=dynamic_file_limit,
                )
                hashed = os.fstat(file_fd)
                opened_state = _file_state(opened)
                hashed_state = _file_state(hashed)
                if opened_state != hashed_state:
                    raise _unsafe("tree", f"file changed while hashing: {relative}")
                total_bytes += bytes_read
            finally:
                os.close(file_fd)
            try:
                final = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise _unsafe("tree", f"file disappeared: {relative}") from exc
            final_state = _file_state(final)
            if hashed_state != final_state:
                raise _unsafe("tree", f"file changed while hashing: {relative}")
            records.append((relative, file_digest, final_state))
            if len(records) > _MAX_TREE_FILES:
                raise _unsafe("tree", f"contains more than {_MAX_TREE_FILES} files")
        try:
            final_names = os.listdir(directory_fd)
        except OSError as exc:
            raise _unsafe("tree", "could not re-enumerate a directory") from exc
        if set(initial_names) != set(final_names):
            raise _unsafe("tree", "directory entries changed while hashing")
        directory_after = os.fstat(directory_fd)
        directory_state_after = _directory_state(directory_after)
        if directory_state_before != directory_state_after:
            raise _unsafe("tree", "directory metadata changed while hashing")
        directory_records.append((prefix, directory_state_after, tuple(initial_names)))

    try:
        root_opened = os.fstat(root_fd)
        if _directory_state(root_before) != _directory_state(root_opened):
            raise _unsafe("tree root", "changed before open")
        try:
            visit(root_fd, depth=0)
        except RecursionError as exc:
            raise _unsafe(
                "tree", "directory nesting exceeds the safe recursion limit"
            ) from exc

        # A file hashed early can change while a later sibling is read without
        # altering directory metadata. Re-open every recorded path relative to
        # the still-open root and compare its complete observable state.
        for relative, _file_digest, expected_state in records:
            parent_fd = root_fd
            opened_directories: list[int] = []
            file_fd: int | None = None
            try:
                for component in relative.parts[:-1]:
                    child_fd = os.open(
                        component,
                        directory_flags,
                        dir_fd=parent_fd,
                    )
                    opened_directories.append(child_fd)
                    parent_fd = child_fd
                file_fd = os.open(
                    relative.parts[-1],
                    file_flags,
                    dir_fd=parent_fd,
                )
                current = os.fstat(file_fd)
                if (
                    not stat.S_ISREG(current.st_mode)
                    or _file_state(current) != expected_state
                ):
                    raise _unsafe("tree", f"file changed after hashing: {relative}")
            except OSError as exc:
                raise _unsafe(
                    "tree", f"could not revalidate hashed file: {relative}"
                ) from exc
            finally:
                if file_fd is not None:
                    os.close(file_fd)
                for opened_directory in reversed(opened_directories):
                    os.close(opened_directory)

        for relative, expected_state, expected_names in directory_records:
            directory_fd = root_fd
            opened_directories = []
            try:
                if relative is not None:
                    for component in relative.parts:
                        child_fd = os.open(
                            component,
                            directory_flags,
                            dir_fd=directory_fd,
                        )
                        opened_directories.append(child_fd)
                        directory_fd = child_fd
                current_state = _directory_state(os.fstat(directory_fd))
                current_names = os.listdir(directory_fd)
                current_names.sort(
                    key=lambda name: name.encode("utf-8", errors="strict")
                )
                if (
                    current_state != expected_state
                    or tuple(current_names) != expected_names
                ):
                    label = relative.as_posix() if relative is not None else "."
                    raise _unsafe("tree", f"directory changed after hashing: {label}")
            except OSError as exc:
                label = relative.as_posix() if relative is not None else "."
                raise _unsafe(
                    "tree", f"could not revalidate hashed directory: {label}"
                ) from exc
            finally:
                for opened_directory in reversed(opened_directories):
                    os.close(opened_directory)
    finally:
        os.close(root_fd)
    try:
        root_final = root_path.lstat()
    except OSError as exc:
        raise _unsafe("tree root", "disappeared while hashing") from exc
    if _directory_state(root_before) != _directory_state(root_final):
        raise _unsafe("tree root", "changed while hashing")
    if not records:
        raise _unsafe("tree", "must contain at least one regular file")
    _validate_portable_tree_paths(
        tuple(relative for relative, _digest, _state in records)
    )
    records.sort(key=lambda item: item[0].as_posix().encode("utf-8"))
    digest = hashlib.sha256()
    for relative, file_digest, _state in records:
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def sha256_tree(
    root: Path,
    *,
    max_file_bytes: int | None = None,
    max_total_bytes: int | None = None,
) -> str:
    """Return the deterministic SHA-256 digest of a regular-file tree.

    For each file in sorted relative-path order, the framing is::

        relative POSIX path as UTF-8 + NUL
        lowercase ASCII-hex SHA-256 of file bytes + NUL

    Redirects, empty trees, and all non-regular filesystem entries are
    rejected by :func:`iter_regular_files`.
    """

    if os.name != "nt" and all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")
    ):
        return _sha256_tree_descriptor_relative(
            root,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )

    # Native Windows lacks Python's descriptor-relative openat API.  The
    # fallback still rejects reparse points before/after every file and is
    # appropriate for the documented single-trusted-operator boundary; a
    # hostile concurrent filesystem writer is not treated as an isolated
    # tenant until a Win32 handle-relative walker lands.
    digest = hashlib.sha256()
    total_bytes = 0
    observed_states: dict[PurePosixPath, FileState] = {}
    for relative, path in iter_regular_files(root):
        size = path.lstat().st_size
        if max_file_bytes is not None and size > max_file_bytes:
            raise _unsafe("tree", f"file exceeds {max_file_bytes} bytes: {relative}")
        if max_total_bytes is not None and total_bytes + size > max_total_bytes:
            raise _unsafe("tree", f"tree exceeds {max_total_bytes} total bytes")
        digest.update(relative.as_posix().encode("utf-8", errors="strict"))
        digest.update(b"\0")
        dynamic_file_limit = max_file_bytes
        if max_total_bytes is not None:
            remaining_total = max_total_bytes - total_bytes
            dynamic_file_limit = (
                remaining_total
                if dynamic_file_limit is None
                else min(dynamic_file_limit, remaining_total)
            )
        file_digest, bytes_read = _sha256_regular_file(
            path, max_file_bytes=dynamic_file_limit
        )
        digest.update(file_digest.hex().encode("ascii"))
        digest.update(b"\0")
        total_bytes += bytes_read
        observed_states[relative] = _file_state(path.lstat())
    final_files = iter_regular_files(root)
    if tuple(observed_states) != tuple(relative for relative, _path in final_files):
        raise _unsafe("tree", "entries changed after hashing")
    for relative, path in final_files:
        if _file_state(path.lstat()) != observed_states[relative]:
            raise _unsafe("tree", f"file changed after hashing: {relative}")
    return digest.hexdigest()
