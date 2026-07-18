"""Secure, profile-scoped storage for imported design-system ZIP archives.

The library is intentionally independent of FastAPI.  Its public functions
return JSON-serializable dictionaries and resolve :func:`get_fabric_home` at
call time, so CLI, gateway, and per-request profile contexts share the same
implementation without sharing state across profiles.

Archives are copied into a staging directory, validated, and extracted member
by member.  A complete revision is published atomically under its SHA-256
name; published revisions are never overwritten.  Library records are stable
IDs whose current revision pointer can be replaced without mutating an older
revision.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import unicodedata
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from fabric_constants import get_fabric_home


LIBRARY_DIRECTORY = "design-system-library"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2_000
MAX_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_ENTRY_BYTES = 25 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_PATH_DEPTH = 32
MAX_PATH_LENGTH = 512
MAX_PATH_SEGMENT_LENGTH = 255
MAX_INSPECTION_FILES = 200
MAX_INSPECTION_ENTRYPOINTS_PER_KIND = 40
MAX_DESIGN_MD_PREVIEW_BYTES = 16 * 1024

# Readable aliases for callers that want to advertise the limits.
MAX_ARCHIVE_SIZE = MAX_ARCHIVE_BYTES
MAX_ENTRIES = MAX_ARCHIVE_ENTRIES
MAX_TOTAL_UNCOMPRESSED_BYTES = MAX_EXPANDED_BYTES
MAX_ENTRY_UNCOMPRESSED_BYTES = MAX_ENTRY_BYTES
MAX_SEGMENT_LENGTH = MAX_PATH_SEGMENT_LENGTH

_METADATA_VERSION = 1
_METADATA_MAX_BYTES = 1024 * 1024
_ID_RE = re.compile(r"^ds_[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_WINDOWS_DEVICE_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_PROHIBITED_DIRECTORY_NAMES = {".git", ".ssh", "node_modules"}
_PRIVATE_KEY_NAMES = {
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "identity",
}
_PRIVATE_KEY_SUFFIXES = (".key", ".p12", ".pem", ".pfx", ".pkcs8")
_BUFFER_SIZE = 1024 * 1024
_PROCESS_LOCK = threading.RLock()


class DesignSystemLibraryError(Exception):
    """Base class for library failures suitable for API error mapping."""


class ArchiveValidationError(DesignSystemLibraryError, ValueError):
    """The archive is malformed, unsafe, or exceeds an import limit."""


class DesignSystemNotFoundError(DesignSystemLibraryError, LookupError):
    """The requested stable library ID does not exist in this profile."""


class DesignSystemConflictError(DesignSystemLibraryError):
    """The record changed after a caller read its generation."""


class DesignSystemStorageError(DesignSystemLibraryError, RuntimeError):
    """Profile-local library state is corrupt or cannot be accessed safely."""


@dataclass(frozen=True)
class _ValidatedMember:
    info: zipfile.ZipInfo
    parts: tuple[str, ...]
    is_directory: bool
    ignored: bool


@dataclass(frozen=True)
class _RevisionResult:
    sha256: str
    archive_size: int
    expanded_size: int
    file_count: int


class DesignSystemLibrary:
    """Synchronous design-system library service for one dynamic profile.

    ``home=None`` is deliberate: the active profile home is resolved for every
    operation.  Passing a home is useful for an explicitly scoped service
    instance, but module-level helpers should normally leave it unset.
    """

    def __init__(self, home: str | os.PathLike[str] | None = None) -> None:
        self._home = Path(home) if home is not None else None

    @property
    def home(self) -> Path:
        return self._home if self._home is not None else get_fabric_home()

    @property
    def root(self) -> Path:
        return self.home / LIBRARY_DIRECTORY

    def list(self) -> list[dict[str, Any]]:
        """Return all records, newest first, from only this profile."""

        records_dir = self._existing_records_directory()
        if records_dir is None:
            return []
        records: list[dict[str, Any]] = []
        try:
            candidates = tuple(records_dir.iterdir())
        except OSError as exc:
            raise DesignSystemStorageError("could not list design-system records") from exc
        for path in candidates:
            if path.suffix != ".json" or not _ID_RE.fullmatch(path.stem):
                continue
            record = self._read_record(path.stem)
            if record is not None:
                records.append(self._public_record(record))
        records.sort(key=lambda item: (-float(item["updated_at"]), str(item["id"])))
        return records

    def get(self, design_system_id: str) -> dict[str, Any] | None:
        """Return one record, or ``None`` for a missing/invalid ID."""

        if not isinstance(design_system_id, str) or not _ID_RE.fullmatch(
            design_system_id
        ):
            return None
        if self._existing_records_directory() is None:
            return None
        record = self._read_record(design_system_id)
        return self._public_record(record) if record is not None else None

    def inspect(self, design_system_id: str) -> dict[str, Any] | None:
        """Return a bounded inspection of the current immutable revision.

        Metadata comes from the published revision manifest and a carefully
        opened ``DESIGN.md`` preview under the verified current revision root.
        This never re-extracts the archive and never follows symlinks.
        """

        if not isinstance(design_system_id, str) or not _ID_RE.fullmatch(
            design_system_id
        ):
            return None
        if self._existing_records_directory() is None:
            return None
        record = self._read_record(design_system_id)
        if record is None:
            return None
        public = self._public_record(record)
        revision_sha = str(public["sha256"])
        revision_root = self.root / "revisions" / revision_sha
        files_root = revision_root / "files"
        _require_directory(revision_root, "design-system revision")
        _require_directory(files_root, "design-system revision files")
        manifest = _read_json_regular(revision_root / "revision.json")
        if not isinstance(manifest, dict):
            raise DesignSystemStorageError(
                "design-system revision manifest is invalid"
            )
        if (
            manifest.get("version") != _METADATA_VERSION
            or manifest.get("sha256") != revision_sha
            or manifest.get("archive_size") != public["archive_size"]
            or manifest.get("expanded_size") != public["expanded_size"]
            or manifest.get("file_count") != public["file_count"]
            or not isinstance(manifest.get("files"), list)
        ):
            raise DesignSystemStorageError(
                "design-system revision manifest does not match the current revision"
            )

        file_rows: list[dict[str, Any]] = []
        for raw_row in manifest["files"]:
            if not isinstance(raw_row, dict):
                raise DesignSystemStorageError(
                    "design-system revision manifest file list is invalid"
                )
            path_value = raw_row.get("path")
            size_value = raw_row.get("size")
            if not isinstance(path_value, str) or not path_value:
                raise DesignSystemStorageError(
                    "design-system revision manifest path is invalid"
                )
            if (
                isinstance(size_value, bool)
                or not isinstance(size_value, int)
                or size_value < 0
            ):
                raise DesignSystemStorageError(
                    "design-system revision manifest size is invalid"
                )
            file_rows.append({"path": path_value, "size": size_value})

        if (
            len(file_rows) != int(public["file_count"])
            or sum(int(row["size"]) for row in file_rows)
            != int(public["expanded_size"])
        ):
            raise DesignSystemStorageError(
                "design-system revision manifest inventory does not match the current revision"
            )

        file_rows.sort(key=lambda row: str(row["path"]).casefold())
        entrypoints, omitted_entrypoint_count = _detect_entrypoints(file_rows)
        inventory = file_rows[:MAX_INSPECTION_FILES]
        omitted = max(0, len(file_rows) - len(inventory))
        design_md_preview = None
        design_md_path = entrypoints.get("designMd")
        if isinstance(design_md_path, str) and design_md_path:
            design_md_preview = _read_design_md_preview(files_root, design_md_path)

        return {
            "designSystemId": public["id"],
            "revisionSha256": revision_sha,
            "fileCount": int(public["file_count"]),
            "expandedBytes": int(public["expanded_size"]),
            "entrypoints": entrypoints,
            "files": inventory,
            "omittedFileCount": omitted,
            "omittedEntrypointCount": omitted_entrypoint_count,
            "designMdPreview": design_md_preview,
        }

    def import_archive(
        self,
        archive_path: str | os.PathLike[str],
        *,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Validate and import an archive as a new stable library record."""

        source = Path(archive_path)
        display_name = _validated_display_name(name) if name is not None else _source_name(source)
        source_filename = _safe_source_filename(source)
        with _PROCESS_LOCK, self._exclusive_library_lock():
            result = self._publish_archive(source)
            now = time.time()
            design_system_id = f"ds_{uuid.uuid4().hex}"
            revision = _revision_descriptor(result, source_filename, now)
            record: dict[str, Any] = {
                "version": _METADATA_VERSION,
                "id": design_system_id,
                "kind": "archive",
                "name": display_name,
                "created_at": now,
                "updated_at": now,
                "current_revision": result.sha256,
                "revisions": [revision],
            }
            self._write_record(record)
            return self._public_record(record)

    def replace(
        self,
        design_system_id: str,
        archive_path: str | os.PathLike[str],
        *,
        expected_generation: int | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Point a stable record at a newly published immutable revision."""

        if not isinstance(design_system_id, str) or not _ID_RE.fullmatch(
            design_system_id
        ):
            raise DesignSystemNotFoundError("design system not found")
        source = Path(archive_path)
        source_filename = _safe_source_filename(source)
        replacement_name = _validated_display_name(name) if name is not None else None
        with _PROCESS_LOCK, self._exclusive_library_lock():
            record = self._read_record(design_system_id)
            if record is None:
                raise DesignSystemNotFoundError("design system not found")
            if expected_generation is not None and expected_generation != len(
                record["revisions"]
            ):
                raise DesignSystemConflictError(
                    "design system changed; refresh and try again"
                )
            result = self._publish_archive(source)
            now = time.time()
            revisions = list(record["revisions"])
            descriptor = _revision_descriptor(result, source_filename, now)
            # Re-importing byte-identical data reuses the same content-addressed
            # revision while refreshing its import provenance rather than
            # growing duplicate history rows.
            revisions = [row for row in revisions if row["sha256"] != result.sha256]
            revisions.append(descriptor)
            updated = {
                **record,
                "name": replacement_name if replacement_name is not None else record["name"],
                "updated_at": now,
                "current_revision": result.sha256,
                "revisions": revisions,
            }
            self._write_record(updated)
            return self._public_record(updated)

    def delete(
        self,
        design_system_id: str,
        *,
        expected_generation: int | None = None,
    ) -> bool:
        """Forget a record without mutating or following revision paths."""

        if not isinstance(design_system_id, str) or not _ID_RE.fullmatch(
            design_system_id
        ):
            return False
        with _PROCESS_LOCK, self._exclusive_library_lock(create=False) as locked:
            if not locked:
                return False
            record = self._read_record(design_system_id)
            if record is None:
                return False
            if expected_generation is not None and expected_generation != len(
                record["revisions"]
            ):
                raise DesignSystemConflictError(
                    "design system changed; refresh and try again"
                )
            path = self.root / "records" / f"{design_system_id}.json"
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise DesignSystemStorageError("could not inspect design-system record") from exc
            if not stat.S_ISREG(metadata.st_mode):
                raise DesignSystemStorageError("design-system record is not a regular file")
            try:
                path.unlink()
                _fsync_directory(path.parent)
            except OSError as exc:
                raise DesignSystemStorageError("could not delete design-system record") from exc
            return True

    @contextmanager
    def _exclusive_library_lock(self, *, create: bool = True) -> Iterator[bool]:
        if create:
            self._ensure_layout()
        else:
            if self._existing_records_directory() is None:
                yield False
                return
        lock_path = self.root / ".lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise DesignSystemStorageError("could not open design-system library lock") from exc
        try:
            try:
                path_metadata = lock_path.lstat()
                descriptor_metadata = os.fstat(descriptor)
            except OSError as exc:
                raise DesignSystemStorageError(
                    "could not verify design-system library lock"
                ) from exc
            if not stat.S_ISREG(path_metadata.st_mode) or not stat.S_ISREG(
                descriptor_metadata.st_mode
            ):
                raise DesignSystemStorageError(
                    "design-system library lock is not a regular file"
                )
            if (path_metadata.st_dev, path_metadata.st_ino) != (
                descriptor_metadata.st_dev,
                descriptor_metadata.st_ino,
            ):
                raise DesignSystemStorageError(
                    "design-system library lock changed while opening"
                )
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            else:  # pragma: no cover - native Windows lacks descriptor chmod
                os.chmod(lock_path, 0o600)
            _lock_descriptor(descriptor)
            yield True
        finally:
            _unlock_descriptor(descriptor)
            os.close(descriptor)

    def _ensure_layout(self) -> None:
        home = self.home
        try:
            home.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise DesignSystemStorageError("could not create the active profile home") from exc
        _ensure_private_directory(self.root)
        _ensure_private_directory(self.root / "records")
        _ensure_private_directory(self.root / "revisions")
        _ensure_private_directory(self.root / "staging")

    def _existing_records_directory(self) -> Path | None:
        try:
            root_metadata = self.root.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DesignSystemStorageError(
                "could not inspect design-system library directory"
            ) from exc
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise DesignSystemStorageError(
                "design-system library directory is not a regular directory"
            )
        records_dir = self.root / "records"
        try:
            records_metadata = records_dir.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DesignSystemStorageError(
                "could not inspect design-system records directory"
            ) from exc
        if not stat.S_ISDIR(records_metadata.st_mode):
            raise DesignSystemStorageError(
                "design-system records directory is not a regular directory"
            )
        return records_dir

    def _publish_archive(self, source: Path) -> _RevisionResult:
        staging_root = self.root / "staging"
        self._cleanup_staging(staging_root)
        operation = Path(tempfile.mkdtemp(prefix="stage-", dir=staging_root))
        revision_stage = operation / "revision"
        files_stage = revision_stage / "files"
        try:
            revision_stage.mkdir(mode=0o700)
            files_stage.mkdir(mode=0o700)
            staged_archive = revision_stage / "archive.zip"
            sha256, archive_size = _copy_and_hash_archive(source, staged_archive)
            extracted_size, file_count, file_manifest = _validate_and_extract(
                staged_archive, files_stage
            )
            manifest = {
                "version": _METADATA_VERSION,
                "sha256": sha256,
                "archive_size": archive_size,
                "expanded_size": extracted_size,
                "file_count": file_count,
                "files": file_manifest,
            }
            _write_new_json(revision_stage / "revision.json", manifest)
            result = _RevisionResult(
                sha256=sha256,
                archive_size=archive_size,
                expanded_size=extracted_size,
                file_count=file_count,
            )
            final = self.root / "revisions" / sha256
            if final.exists() or final.is_symlink():
                _verify_existing_revision(final, result)
                return result
            _freeze_revision(revision_stage)
            # macOS requires the source directory itself to remain writable
            # for this cross-parent rename.  Its descendants are already
            # frozen; tighten the published root immediately after the atomic
            # namespace operation.
            revision_stage.chmod(0o700)
            try:
                os.rename(revision_stage, final)
            except FileExistsError:
                _verify_existing_revision(final, result)
            except OSError as exc:
                # Another process may have won publication between exists() and
                # rename().  Reuse only a complete, matching revision.
                if final.exists() or final.is_symlink():
                    _verify_existing_revision(final, result)
                else:
                    raise DesignSystemStorageError(
                        "could not atomically publish design-system revision"
                    ) from exc
            try:
                final.chmod(0o500)
            except OSError as exc:
                raise DesignSystemStorageError(
                    "could not secure published design-system revision"
                ) from exc
            _fsync_directory(final.parent)
            return result
        finally:
            _remove_path(operation)
            self._cleanup_staging(staging_root)

    def _cleanup_staging(self, staging_root: Path) -> None:
        try:
            children = tuple(staging_root.iterdir())
        except FileNotFoundError:
            return
        except OSError as exc:
            raise DesignSystemStorageError("could not inspect design-system staging") from exc
        for child in children:
            if child.name.startswith("stage-"):
                _remove_path(child)

    def _record_path(self, design_system_id: str) -> Path:
        return self.root / "records" / f"{design_system_id}.json"

    def _read_record(self, design_system_id: str) -> dict[str, Any] | None:
        path = self._record_path(design_system_id)
        try:
            raw = _read_json_regular(path)
        except FileNotFoundError:
            return None
        record = _validate_record(raw, expected_id=design_system_id)
        return record

    def _write_record(self, record: dict[str, Any]) -> None:
        validated = _validate_record(record, expected_id=str(record.get("id", "")))
        path = self._record_path(validated["id"])
        _atomic_json_write(path, validated)

    def _public_record(self, record: dict[str, Any]) -> dict[str, Any]:
        revisions = [self._public_revision(row) for row in record["revisions"]]
        current_sha = record["current_revision"]
        current = next(row for row in reversed(revisions) if row["sha256"] == current_sha)
        return {
            "id": record["id"],
            "kind": "archive",
            "name": record["name"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "revision": current_sha,
            "sha256": current_sha,
            "source_filename": current["source_filename"],
            "archive_size": current["archive_size"],
            "expanded_size": current["expanded_size"],
            "file_count": current["file_count"],
            "archive_path": current["archive_path"],
            "files_path": current["files_path"],
            "path": current["files_path"],
            "revisions": revisions,
        }

    def _public_revision(self, revision: dict[str, Any]) -> dict[str, Any]:
        revision_root = self.root / "revisions" / revision["sha256"]
        return {
            **revision,
            "archive_path": str(revision_root / "archive.zip"),
            "files_path": str(revision_root / "files"),
            "path": str(revision_root / "files"),
        }


# Module-level API: compact and directly usable by FastAPI route handlers.
def list_design_systems() -> list[dict[str, Any]]:
    return DesignSystemLibrary().list()


def get_design_system(design_system_id: str) -> dict[str, Any] | None:
    return DesignSystemLibrary().get(design_system_id)


def import_design_system(
    archive_path: str | os.PathLike[str], *, name: str | None = None
) -> dict[str, Any]:
    return DesignSystemLibrary().import_archive(archive_path, name=name)


def replace_design_system(
    design_system_id: str,
    archive_path: str | os.PathLike[str],
    *,
    expected_generation: int | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    return DesignSystemLibrary().replace(
        design_system_id,
        archive_path,
        expected_generation=expected_generation,
        name=name,
    )


def delete_design_system(
    design_system_id: str, *, expected_generation: int | None = None
) -> bool:
    return DesignSystemLibrary().delete(
        design_system_id, expected_generation=expected_generation
    )


def inspect_design_system(design_system_id: str) -> dict[str, Any] | None:
    return DesignSystemLibrary().inspect(design_system_id)


# Short aliases are convenient for dependency-injected service users.
list_library_entries = list_design_systems
get_library_entry = get_design_system
import_archive = import_design_system
replace_library_entry = replace_design_system
delete_library_entry = delete_design_system
inspect_library_entry = inspect_design_system


def _validated_display_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("design-system name must be a string")
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        raise ValueError("design-system name must not be empty")
    if len(cleaned) > 120:
        raise ValueError("design-system name exceeds 120 characters")
    if any(unicodedata.category(char).startswith("C") for char in cleaned):
        raise ValueError("design-system name contains control characters")
    return cleaned


def _safe_source_filename(source: Path) -> str:
    value = source.name or "design-system.zip"
    value = "".join(
        "_" if unicodedata.category(char).startswith("C") else char for char in value
    )
    value = value.strip() or "design-system.zip"
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_PATH_SEGMENT_LENGTH:
        return value
    while len(value.encode("utf-8")) > MAX_PATH_SEGMENT_LENGTH:
        value = value[:-1]
    return value or "design-system.zip"


def _source_name(source: Path) -> str:
    filename = _safe_source_filename(source)
    stem = filename[:-4] if filename.casefold().endswith(".zip") else filename
    stem = re.sub(r"[-_]+", " ", stem)
    return _validated_display_name(stem[:120].strip() or "Imported design system")


def _revision_descriptor(
    result: _RevisionResult, source_filename: str, imported_at: float
) -> dict[str, Any]:
    return {
        "sha256": result.sha256,
        "imported_at": imported_at,
        "source_filename": source_filename,
        "archive_size": result.archive_size,
        "expanded_size": result.expanded_size,
        "file_count": result.file_count,
    }


def _detect_entrypoints(file_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    design_md: str | None = None
    package_json: str | None = None
    html: list[str] = []
    token_files: list[str] = []

    def priority(path: str) -> tuple[int, str]:
        return path.count("/"), path.casefold()

    for row in file_rows:
        relative = str(row["path"])
        basename = Path(relative).name.casefold()
        folded = relative.casefold()
        suffix = Path(relative).suffix.casefold()
        if basename == "design.md" and (
            design_md is None or priority(relative) < priority(design_md)
        ):
            design_md = relative
        if basename == "package.json" and (
            package_json is None or priority(relative) < priority(package_json)
        ):
            package_json = relative
        if suffix in {".htm", ".html"}:
            html.append(relative)
        if "token" in folded and suffix in {".css", ".json", ".toml", ".yaml", ".yml"}:
            token_files.append(relative)

    result: dict[str, Any] = {}
    if design_md is not None:
        result["designMd"] = design_md
    if package_json is not None:
        result["packageJson"] = package_json
    sorted_html = sorted(html)
    sorted_token_files = sorted(token_files)
    omitted = max(0, len(sorted_html) - MAX_INSPECTION_ENTRYPOINTS_PER_KIND)
    omitted += max(0, len(sorted_token_files) - MAX_INSPECTION_ENTRYPOINTS_PER_KIND)
    if sorted_html:
        result["html"] = sorted_html[:MAX_INSPECTION_ENTRYPOINTS_PER_KIND]
    if sorted_token_files:
        result["tokenFiles"] = sorted_token_files[:MAX_INSPECTION_ENTRYPOINTS_PER_KIND]
    return result, omitted


def _read_design_md_preview(files_root: Path, relative_path: str) -> dict[str, Any] | None:
    parts = tuple(relative_path.split("/"))
    if (
        not parts
        or relative_path.startswith("/")
        or "\\" in relative_path
        or ":" in relative_path
        or len(relative_path) > MAX_PATH_LENGTH
        or len(relative_path.encode("utf-8")) > MAX_PATH_LENGTH
        or any(unicodedata.category(char).startswith("C") for char in relative_path)
        or any(
            not segment
            or segment in {".", ".."}
            or len(segment) > MAX_PATH_SEGMENT_LENGTH
            or len(segment.encode("utf-8")) > MAX_PATH_SEGMENT_LENGTH
            for segment in parts
        )
        or len(parts) > MAX_PATH_DEPTH
    ):
        raise DesignSystemStorageError("design-system DESIGN.md path is invalid")

    try:
        with _open_regular_beneath(files_root, parts) as handle:
            raw = handle.read(MAX_DESIGN_MD_PREVIEW_BYTES + 1)
    except FileNotFoundError:
        return None

    truncated = len(raw) > MAX_DESIGN_MD_PREVIEW_BYTES
    payload = raw[:MAX_DESIGN_MD_PREVIEW_BYTES]
    if b"\x00" in payload:
        return None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    try:
        # ``final=False`` permits only an incomplete trailing code point caused
        # by the hard byte cap; invalid UTF-8 anywhere else still suppresses
        # the preview rather than silently rewriting archive content.
        text = decoder.decode(payload, final=not truncated)
    except UnicodeDecodeError:
        return None
    return {
        "path": relative_path,
        "text": text,
        "truncated": truncated,
    }


@contextmanager
def _open_regular_beneath(root: Path, parts: tuple[str, ...]) -> Iterator[BinaryIO]:
    """Open a regular file without following any archive-controlled symlink.

    POSIX platforms use descriptor-relative ``openat`` traversal so an attacker
    cannot swap an intermediate directory between a path check and the final
    open. Platforms without that support use a component-by-component fallback
    that still rejects every visible symlink and verifies the resolved target.
    """

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if nofollow and directory_flag and os.open in os.supports_dir_fd:
        directory_descriptors: list[int] = []
        file_descriptor: int | None = None
        directory_flags = (
            os.O_RDONLY
            | directory_flag
            | nofollow
            | getattr(os, "O_CLOEXEC", 0)
        )
        file_flags = (
            os.O_RDONLY
            | nofollow
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            directory_descriptors.append(os.open(root, directory_flags))
            for segment in parts[:-1]:
                directory_descriptors.append(
                    os.open(
                        segment,
                        directory_flags,
                        dir_fd=directory_descriptors[-1],
                    )
                )
            file_descriptor = os.open(
                parts[-1],
                file_flags,
                dir_fd=directory_descriptors[-1],
            )
            opened = os.fstat(file_descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise DesignSystemStorageError(
                    "DESIGN.md preview target is not a regular file"
                )
            with os.fdopen(file_descriptor, "rb", closefd=False) as handle:
                yield handle
        except FileNotFoundError:
            raise
        except DesignSystemStorageError:
            raise
        except OSError as exc:
            raise DesignSystemStorageError(
                "could not open DESIGN.md preview safely"
            ) from exc
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            for descriptor in reversed(directory_descriptors):
                os.close(descriptor)
        return

    target = root
    try:
        root_metadata = root.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise DesignSystemStorageError(
                "design-system revision files is not a regular directory"
            )
        resolved_root = root.resolve(strict=True)
        for segment in parts[:-1]:
            target = target / segment
            metadata = target.lstat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise DesignSystemStorageError(
                    "DESIGN.md preview parent is not a regular directory"
                )
        target = target / parts[-1]
        metadata = target.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise DesignSystemStorageError(
                "DESIGN.md preview target is not a regular file"
            )
        try:
            target.resolve(strict=True).relative_to(resolved_root)
        except ValueError as exc:
            raise DesignSystemStorageError(
                "design-system DESIGN.md path escaped revision root"
            ) from exc
        with _open_regular_binary(target) as handle:
            yield handle
    except FileNotFoundError:
        raise
    except DesignSystemStorageError:
        raise
    except OSError as exc:
        raise DesignSystemStorageError(
            "could not open DESIGN.md preview safely"
        ) from exc


def _copy_and_hash_archive(source: Path, destination: Path) -> tuple[str, int]:
    source_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    source_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        before = source.lstat()
    except OSError as exc:
        raise ArchiveValidationError("archive could not be inspected") from exc
    if not stat.S_ISREG(before.st_mode):
        raise ArchiveValidationError("archive must be a regular, non-symlink file")
    try:
        source_fd = os.open(source, source_flags)
    except OSError as exc:
        raise ArchiveValidationError("archive could not be opened safely") from exc
    destination_fd: int | None = None
    try:
        opened = os.fstat(source_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ArchiveValidationError("archive must be a regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ArchiveValidationError("archive changed while it was opened")
        if opened.st_size > MAX_ARCHIVE_BYTES:
            raise ArchiveValidationError("archive exceeds the 50 MiB limit")
        destination_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        destination_fd = os.open(destination, destination_flags, 0o600)
        digest = hashlib.sha256()
        copied = 0
        with os.fdopen(source_fd, "rb", closefd=False) as input_file, os.fdopen(
            destination_fd, "wb", closefd=False
        ) as output_file:
            while True:
                chunk = input_file.read(_BUFFER_SIZE)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > MAX_ARCHIVE_BYTES:
                    raise ArchiveValidationError("archive exceeds the 50 MiB limit")
                digest.update(chunk)
                output_file.write(chunk)
            output_file.flush()
            os.fsync(output_file.fileno())
        if copied != opened.st_size:
            raise ArchiveValidationError("archive changed while it was copied")
        os.chmod(destination, 0o600)
        return digest.hexdigest(), copied
    finally:
        os.close(source_fd)
        if destination_fd is not None:
            os.close(destination_fd)


def _validate_and_extract(
    archive_path: Path, destination: Path
) -> tuple[int, int, list[dict[str, Any]]]:
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = _validate_members(archive.infolist())
            total = 0
            file_count = 0
            file_manifest: list[dict[str, Any]] = []
            for member in members:
                if member.ignored:
                    continue
                target = destination.joinpath(*member.parts)
                if member.is_directory:
                    _mkdir_extracted(target)
                    continue
                _mkdir_extracted(target.parent)
                size, digest = _extract_regular_file(archive, member.info, target, total)
                total += size
                if total > MAX_EXPANDED_BYTES:
                    raise ArchiveValidationError("archive exceeds the 250 MiB expanded limit")
                file_count += 1
                file_manifest.append(
                    {
                        "path": "/".join(member.parts),
                        "size": size,
                        "sha256": digest,
                    }
                )
            return total, file_count, file_manifest
    except ArchiveValidationError:
        raise
    except (NotImplementedError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ArchiveValidationError("archive is not a supported, valid ZIP file") from exc
    except OSError as exc:
        raise DesignSystemStorageError("could not extract design-system archive") from exc


def _validate_members(infos: list[zipfile.ZipInfo]) -> list[_ValidatedMember]:
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ArchiveValidationError("archive exceeds the 2000-entry limit")
    validated: list[_ValidatedMember] = []
    seen: dict[tuple[str, ...], str] = {}
    files: set[tuple[str, ...]] = set()
    directories: set[tuple[str, ...]] = set()
    declared_total = 0
    for info in infos:
        if info.flag_bits & (0x1 | 0x40):
            raise ArchiveValidationError("encrypted ZIP entries are not allowed")
        parts, is_directory = _validated_member_path(info)
        canonical = tuple(_canonical_segment(part) for part in parts)
        previous = seen.get(canonical)
        if previous is not None:
            raise ArchiveValidationError(
                f"Unicode/case path collision: {previous!r} and {info.filename!r}"
            )
        seen[canonical] = info.filename
        for depth in range(1, len(canonical)):
            prefix = canonical[:depth]
            if prefix in files:
                raise ArchiveValidationError("file/directory prefix collision in archive")
            directories.add(prefix)
        if is_directory:
            if canonical in files:
                raise ArchiveValidationError("file/directory path collision in archive")
            directories.add(canonical)
        else:
            if canonical in directories:
                raise ArchiveValidationError("file/directory path collision in archive")
            files.add(canonical)

        _validate_member_type(info, is_directory)
        if info.file_size < 0 or info.compress_size < 0:
            raise ArchiveValidationError("ZIP entry has an invalid size")
        if is_directory and info.file_size:
            raise ArchiveValidationError("ZIP directory entry contains file data")
        if info.file_size > MAX_ENTRY_BYTES:
            raise ArchiveValidationError("ZIP entry exceeds the 25 MiB limit")
        declared_total += info.file_size
        if declared_total > MAX_EXPANDED_BYTES:
            raise ArchiveValidationError("archive exceeds the 250 MiB expanded limit")
        if info.file_size and (
            info.compress_size == 0
            or info.file_size > info.compress_size * MAX_COMPRESSION_RATIO
        ):
            raise ArchiveValidationError("ZIP entry exceeds the 100:1 compression ratio")

        ignored = _is_ignored_path(parts)
        if not ignored:
            _reject_prohibited_path(parts)
        validated.append(
            _ValidatedMember(
                info=info,
                parts=parts,
                is_directory=is_directory,
                ignored=ignored,
            )
        )
    return validated


def _validated_member_path(info: zipfile.ZipInfo) -> tuple[tuple[str, ...], bool]:
    raw = getattr(info, "orig_filename", info.filename)
    if not isinstance(raw, str) or not raw:
        raise ArchiveValidationError("ZIP entry has an empty path")
    if any(unicodedata.category(char).startswith("C") for char in raw):
        raise ArchiveValidationError("ZIP entry path contains control characters")
    if "\\" in raw:
        raise ArchiveValidationError("Windows-style ZIP entry paths are not allowed")
    if raw.startswith("/") or raw.startswith("//") or _DRIVE_RE.match(raw):
        raise ArchiveValidationError("absolute ZIP entry paths are not allowed")
    if ":" in raw:
        raise ArchiveValidationError("Windows drive/ADS ZIP entry paths are not allowed")

    is_directory = info.is_dir()
    path_value = raw[:-1] if is_directory and raw.endswith("/") else raw
    if not path_value or path_value.endswith("/"):
        raise ArchiveValidationError("ZIP entry path contains an empty segment")
    if len(path_value) > MAX_PATH_LENGTH or len(path_value.encode("utf-8")) > MAX_PATH_LENGTH:
        raise ArchiveValidationError("ZIP entry path exceeds 512 characters/bytes")
    parts = tuple(path_value.split("/"))
    if len(parts) > MAX_PATH_DEPTH:
        raise ArchiveValidationError("ZIP entry path exceeds depth 32")
    for part in parts:
        if not part or part in {".", ".."}:
            raise ArchiveValidationError("ZIP entry path contains traversal or empty segments")
        if len(part) > MAX_PATH_SEGMENT_LENGTH or len(part.encode("utf-8")) > MAX_PATH_SEGMENT_LENGTH:
            raise ArchiveValidationError("ZIP entry path segment exceeds 255 characters/bytes")
        if part.endswith((" ", ".")):
            raise ArchiveValidationError("Windows-ambiguous ZIP entry paths are not allowed")
        windows_base = part.split(".", 1)[0].casefold()
        if windows_base in _WINDOWS_DEVICE_NAMES:
            raise ArchiveValidationError("Windows device ZIP entry paths are not allowed")
    return parts, is_directory


def _validate_member_type(info: zipfile.ZipInfo, is_directory: bool) -> None:
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ArchiveValidationError("symlink and special ZIP entries are not allowed")
    if file_type == stat.S_IFDIR and not is_directory:
        raise ArchiveValidationError("ZIP directory mode does not match its path")
    if file_type == stat.S_IFREG and is_directory:
        raise ArchiveValidationError("ZIP file mode does not match its path")
    dos_directory = bool(info.external_attr & 0x10)
    if dos_directory and not is_directory:
        raise ArchiveValidationError("ZIP directory attribute does not match its path")


def _canonical_segment(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _is_ignored_path(parts: tuple[str, ...]) -> bool:
    canonical = tuple(_canonical_segment(part) for part in parts)
    return canonical[0] == "__macosx" or canonical[-1] == ".ds_store"


def _reject_prohibited_path(parts: tuple[str, ...]) -> None:
    canonical = tuple(_canonical_segment(part) for part in parts)
    if any(part in _PROHIBITED_DIRECTORY_NAMES for part in canonical):
        raise ArchiveValidationError("archive contains a prohibited private/build directory")
    filename = canonical[-1]
    if filename == ".env" or filename.startswith(".env."):
        raise ArchiveValidationError("archive contains a prohibited environment file")
    if filename in _PRIVATE_KEY_NAMES or filename.endswith(_PRIVATE_KEY_SUFFIXES):
        raise ArchiveValidationError("archive contains a prohibited private key file")


def _mkdir_extracted(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
    except OSError as exc:
        raise DesignSystemStorageError("could not create extraction directory") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise ArchiveValidationError("file/directory path collision in archive")
    os.chmod(path, 0o700)


def _extract_regular_file(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    target: Path,
    expanded_before: int,
) -> tuple[int, str]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError as exc:
        raise ArchiveValidationError("duplicate or colliding ZIP entry path") from exc
    except OSError as exc:
        raise DesignSystemStorageError("could not create extracted file") from exc
    size = 0
    digest = hashlib.sha256()
    try:
        with archive.open(info, "r") as source, os.fdopen(
            descriptor, "wb", closefd=False
        ) as output:
            while True:
                chunk = source.read(min(_BUFFER_SIZE, MAX_ENTRY_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ENTRY_BYTES:
                    raise ArchiveValidationError("ZIP entry exceeds the 25 MiB limit")
                if expanded_before + size > MAX_EXPANDED_BYTES:
                    raise ArchiveValidationError("archive exceeds the 250 MiB expanded limit")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != info.file_size:
            raise ArchiveValidationError("ZIP entry size does not match its metadata")
        os.chmod(target, 0o600)
        return size, digest.hexdigest()
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    finally:
        os.close(descriptor)


def _validate_record(raw: Any, *, expected_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DesignSystemStorageError("design-system record is not an object")
    required = {
        "version",
        "id",
        "kind",
        "name",
        "created_at",
        "updated_at",
        "current_revision",
        "revisions",
    }
    if set(raw) != required:
        raise DesignSystemStorageError("design-system record has an invalid schema")
    if raw["version"] != _METADATA_VERSION or raw["kind"] != "archive":
        raise DesignSystemStorageError("design-system record has an unsupported version")
    if raw["id"] != expected_id or not _ID_RE.fullmatch(str(raw["id"])):
        raise DesignSystemStorageError("design-system record ID is invalid")
    try:
        name = _validated_display_name(raw["name"])
    except ValueError as exc:
        raise DesignSystemStorageError("design-system record name is invalid") from exc
    created = _validated_number(raw["created_at"], "created_at")
    updated = _validated_number(raw["updated_at"], "updated_at")
    if updated < created:
        raise DesignSystemStorageError("design-system record timestamps are invalid")
    current = raw["current_revision"]
    if not isinstance(current, str) or not _SHA256_RE.fullmatch(current):
        raise DesignSystemStorageError("design-system current revision is invalid")
    rows = raw["revisions"]
    if not isinstance(rows, list) or not rows:
        raise DesignSystemStorageError("design-system revision history is invalid")
    revisions = [_validate_revision_descriptor(row) for row in rows]
    if current not in {row["sha256"] for row in revisions}:
        raise DesignSystemStorageError("design-system current revision is missing")
    return {
        "version": _METADATA_VERSION,
        "id": raw["id"],
        "kind": "archive",
        "name": name,
        "created_at": created,
        "updated_at": updated,
        "current_revision": current,
        "revisions": revisions,
    }


def _validate_revision_descriptor(raw: Any) -> dict[str, Any]:
    required = {
        "sha256",
        "imported_at",
        "source_filename",
        "archive_size",
        "expanded_size",
        "file_count",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise DesignSystemStorageError("design-system revision metadata is invalid")
    sha256 = raw["sha256"]
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise DesignSystemStorageError("design-system revision hash is invalid")
    imported_at = _validated_number(raw["imported_at"], "imported_at")
    source_filename = raw["source_filename"]
    if (
        not isinstance(source_filename, str)
        or not source_filename
        or "/" in source_filename
        or "\\" in source_filename
        or len(source_filename.encode("utf-8")) > MAX_PATH_SEGMENT_LENGTH
        or any(
            unicodedata.category(char).startswith("C") for char in source_filename
        )
    ):
        raise DesignSystemStorageError("design-system revision source name is invalid")
    archive_size = _validated_bounded_int(raw["archive_size"], MAX_ARCHIVE_BYTES)
    expanded_size = _validated_bounded_int(raw["expanded_size"], MAX_EXPANDED_BYTES)
    file_count = _validated_bounded_int(raw["file_count"], MAX_ARCHIVE_ENTRIES)
    return {
        "sha256": sha256,
        "imported_at": imported_at,
        "source_filename": source_filename,
        "archive_size": archive_size,
        "expanded_size": expanded_size,
        "file_count": file_count,
    }


def _validated_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesignSystemStorageError(f"design-system {field} is invalid")
    numeric = float(value)
    if not (0 <= numeric < float("inf")):
        raise DesignSystemStorageError(f"design-system {field} is invalid")
    return numeric


def _validated_bounded_int(value: Any, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise DesignSystemStorageError("design-system revision count/size is invalid")
    return value


def _read_json_regular(path: Path) -> Any:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        before = path.lstat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise DesignSystemStorageError("could not inspect design-system metadata") from exc
    if not stat.S_ISREG(before.st_mode):
        raise DesignSystemStorageError("design-system metadata is not a regular file")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DesignSystemStorageError("could not open design-system metadata safely") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > _METADATA_MAX_BYTES:
            raise DesignSystemStorageError("design-system metadata is invalid or too large")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise DesignSystemStorageError("design-system metadata changed while opening")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as file:
            try:
                return json.load(file)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DesignSystemStorageError("design-system metadata is corrupt") from exc
    finally:
        os.close(descriptor)


def _atomic_json_write(path: Path, value: Any) -> None:
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        _write_new_json(temporary, value)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise DesignSystemStorageError("could not atomically write design-system metadata") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _write_new_json(path: Path, value: Any) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as file:
            json.dump(value, file, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(path, 0o600)
    finally:
        os.close(descriptor)


def _verify_existing_revision(path: Path, expected: _RevisionResult) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DesignSystemStorageError("could not inspect existing design-system revision") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise DesignSystemStorageError("existing design-system revision is not a directory")
    manifest = _read_json_regular(path / "revision.json")
    if not isinstance(manifest, dict):
        raise DesignSystemStorageError("existing design-system revision manifest is invalid")
    summary = {
        "version": manifest.get("version"),
        "sha256": manifest.get("sha256"),
        "archive_size": manifest.get("archive_size"),
        "expanded_size": manifest.get("expanded_size"),
        "file_count": manifest.get("file_count"),
    }
    expected_summary = {
        "version": _METADATA_VERSION,
        "sha256": expected.sha256,
        "archive_size": expected.archive_size,
        "expanded_size": expected.expanded_size,
        "file_count": expected.file_count,
    }
    if summary != expected_summary or not isinstance(manifest.get("files"), list):
        raise DesignSystemStorageError("existing design-system revision does not match its hash")
    archive_path = path / "archive.zip"
    digest = hashlib.sha256()
    size = 0
    try:
        with _open_regular_binary(archive_path) as archive_file:
            for chunk in iter(lambda: archive_file.read(_BUFFER_SIZE), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise DesignSystemStorageError("could not verify existing design-system revision") from exc
    if size != expected.archive_size or digest.hexdigest() != expected.sha256:
        raise DesignSystemStorageError("existing design-system archive was modified")
    _require_directory(path / "files", "revision files directory")


@contextmanager
def _open_regular_binary(path: Path) -> Iterator[BinaryIO]:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise DesignSystemStorageError("revision file is not regular")
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DesignSystemStorageError("revision file is not regular")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise DesignSystemStorageError("revision file changed while opening")
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            yield file
    finally:
        os.close(descriptor)


def _freeze_revision(path: Path) -> None:
    try:
        for root, directories, filenames in os.walk(path, topdown=False, followlinks=False):
            root_path = Path(root)
            for filename in filenames:
                child = root_path / filename
                if child.is_symlink() or not stat.S_ISREG(child.lstat().st_mode):
                    raise DesignSystemStorageError("staged revision contains a special file")
                child.chmod(0o400)
            for directory in directories:
                child = root_path / directory
                if child.is_symlink() or not stat.S_ISDIR(child.lstat().st_mode):
                    raise DesignSystemStorageError("staged revision contains a special directory")
                child.chmod(0o500)
        path.chmod(0o500)
    except OSError as exc:
        raise DesignSystemStorageError("could not make design-system revision immutable") from exc


def _ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise DesignSystemStorageError(f"{path.name} is not a directory")
        path.chmod(0o700)
    except DesignSystemStorageError:
        raise
    except OSError as exc:
        raise DesignSystemStorageError(f"could not create secure {path.name} directory") from exc


def _require_directory(path: Path, description: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DesignSystemStorageError(f"could not inspect {description}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise DesignSystemStorageError(f"{description} is not a regular directory")


def _remove_path(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DesignSystemStorageError("could not inspect design-system staging path") from exc
    try:
        if stat.S_ISDIR(metadata.st_mode):
            # A failed publication can leave a frozen (0500) staged tree.
            # Restore directory write permission top-down before unlinking
            # children; changing a file's own mode does not grant permission
            # to remove it from a read-only parent directory.
            for root, directories, _filenames in os.walk(
                path, topdown=True, followlinks=False
            ):
                root_path = Path(root)
                root_path.chmod(0o700)
                for directory in directories:
                    child = root_path / directory
                    if not child.is_symlink():
                        child.chmod(0o700)
            for root, directories, filenames in os.walk(path, topdown=False, followlinks=False):
                root_path = Path(root)
                for filename in filenames:
                    child = root_path / filename
                    if child.is_symlink():
                        child.unlink()
                    else:
                        child.chmod(0o600)
                        child.unlink()
                for directory in directories:
                    child = root_path / directory
                    if child.is_symlink():
                        child.unlink()
                    else:
                        child.chmod(0o700)
                        child.rmdir()
            path.chmod(0o700)
            path.rmdir()
        else:
            path.unlink()
    except OSError as exc:
        raise DesignSystemStorageError("could not clean design-system staging") from exc


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass


__all__ = [
    "ArchiveValidationError",
    "DesignSystemConflictError",
    "DesignSystemLibrary",
    "DesignSystemLibraryError",
    "DesignSystemNotFoundError",
    "DesignSystemStorageError",
    "LIBRARY_DIRECTORY",
    "MAX_ARCHIVE_BYTES",
    "MAX_ARCHIVE_ENTRIES",
    "MAX_COMPRESSION_RATIO",
    "MAX_DESIGN_MD_PREVIEW_BYTES",
    "MAX_ENTRY_BYTES",
    "MAX_EXPANDED_BYTES",
    "MAX_INSPECTION_FILES",
    "MAX_PATH_DEPTH",
    "MAX_PATH_LENGTH",
    "MAX_PATH_SEGMENT_LENGTH",
    "delete_design_system",
    "get_design_system",
    "import_design_system",
    "inspect_design_system",
    "list_design_systems",
    "replace_design_system",
]
