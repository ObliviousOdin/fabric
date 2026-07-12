"""Pure, profile-scoped capability-pack planning and status evaluation.

This module is deliberately read-only.  It consumes an already validated
compiled catalog and an explicit profile home, then describes what a future
transaction would need to do.  It never syncs skills, changes config, mutates
discovery caches, or inspects process/session environment variables.

The neutral mutation plan and contextual execution health are separate
contracts.  Session platform, disabled-skill policy, and available toolsets
can change ``context_health`` and ``context_digest`` without changing the
mutation status or optimistic-concurrency digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping, Sequence

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import YAMLError

from fabric_cli.capability_packs import canonical_json_bytes
from tools.skill_install import (
    UnsafePathError,
    is_path_redirect,
    normalize_relative_path,
    normalize_skill_install_path,
    resolve_relative_path,
    sha256_tree,
)


MAX_PROFILE_CONFIG_BYTES = 2 * 1024 * 1024
MAX_PACK_STATE_BYTES = 8 * 1024 * 1024
MAX_SKILL_SCAN_ENTRIES = 10_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PACK_ID_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$"
)
_SKIP_DIRECTORIES = frozenset({
    ".archive",
    ".git",
    ".github",
    ".hub",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "site-packages",
    "venv",
})
_SUPPORT_DIRECTORIES = frozenset({"assets", "references", "scripts", "templates"})


class PackLifecycleIssueCode(StrEnum):
    """Stable issue codes emitted by the read-only lifecycle foundation."""

    CATALOG_INVALID = "CATALOG_INVALID"
    EXTERNAL_SHADOW = "EXTERNAL_SHADOW"
    HOST_UNSUPPORTED = "HOST_UNSUPPORTED"
    OVERRIDE_INVALID = "OVERRIDE_INVALID"
    PACK_UNKNOWN = "PACK_UNKNOWN"
    PATH_UNSAFE = "PATH_UNSAFE"
    PROFILE_CONFIG_INVALID = "PROFILE_CONFIG_INVALID"
    SKILL_DISABLED = "SKILL_DISABLED"
    SKILL_MISSING = "SKILL_MISSING"
    STATE_INVALID = "STATE_INVALID"
    SYMLINK_REJECTED = "SYMLINK_REJECTED"
    TARGET_RELEASE_UNAVAILABLE = "TARGET_RELEASE_UNAVAILABLE"
    TOOLSET_UNAVAILABLE = "TOOLSET_UNAVAILABLE"
    USER_MODIFIED_CONFLICT = "USER_MODIFIED_CONFLICT"


class PackLifecycleValidationError(ValueError):
    """A deterministic validation failure before a plan can be constructed."""

    def __init__(self, code: PackLifecycleIssueCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


class MemberClassification(StrEnum):
    """Stable inventory/context classifications from the R2 pack contract."""

    READY = "ready"
    MISSING = "missing"
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE_TOOLSET = "unavailable_toolset"
    EXTERNAL_SHADOW = "external_shadow"
    USER_MODIFIED = "user_modified"
    PACK_OWNED = "pack_owned"


class MutationPlanStatus(StrEnum):
    READY = "ready"
    UNCHANGED = "unchanged"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    CONFLICT = "conflict"


class PackContextHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    DRIFTED = "drifted"


@dataclass(frozen=True)
class PackIssue:
    code: PackLifecycleIssueCode
    severity: Literal["info", "warning", "error"]
    member: str | None
    message: str


@dataclass(frozen=True)
class PackOperation:
    """One exact read-only description of a future filesystem operation."""

    kind: Literal["promote", "remove", "preserve"]
    artifact_kind: Literal["router", "member"]
    member: str
    ownership: Literal["pack", "reference"]
    source_kind: Literal["pack", "bundled", "optional"]
    source_relative_path: str
    destination_relative_path: str | None
    before_sha256: str | None
    after_sha256: str | None


@dataclass(frozen=True)
class MemberStatus:
    artifact_kind: Literal["router", "member"]
    name: str
    role: Literal["required", "optional"]
    ownership: Literal["pack", "reference"]
    state_owned: bool
    enabled: bool
    enablement_source: Literal["required", "default", "override"]
    inventory_status: MemberClassification
    status: MemberClassification
    effective_path: str | None
    current_sha256: str | None
    expected_sha256: str
    host_supported: bool
    missing_toolsets: tuple[str, ...]
    issues: tuple[PackIssue, ...]


@dataclass(frozen=True)
class PackPlanResult:
    """A neutral mutation plan plus health for one explicit execution context."""

    mutation_status: MutationPlanStatus
    context_health: PackContextHealth
    pack_id: str
    operation: Literal["apply", "update", "downgrade", "remove", "override"]
    from_version: str | None
    to_version: str
    expected_revision: int
    mutation_plan_digest: str
    context_digest: str
    host_os: Literal["linux", "macos", "windows"]
    session_platform: str | None
    operations: tuple[PackOperation, ...]
    members: tuple[MemberStatus, ...]
    issues: tuple[PackIssue, ...]

    @property
    def status(self) -> MutationPlanStatus:
        """Compatibility spelling: plan ``status`` is always mutation-neutral."""

        return self.mutation_status


@dataclass(frozen=True)
class _OwnedPath:
    kind: Literal["router", "member"]
    sha256: str


@dataclass(frozen=True)
class _InstalledMember:
    ownership: Literal["pack", "reference"]
    effective_path: str
    source_sha256: str
    installed_sha256: str | None


@dataclass(frozen=True)
class _InstalledPack:
    version: str
    manifest_sha256: str
    installed_at: str
    updated_at: str
    owned: Mapping[str, _OwnedPath]
    members: Mapping[str, _InstalledMember]


@dataclass(frozen=True)
class _PackState:
    revision: int
    installed: Mapping[str, _InstalledPack]


@dataclass(frozen=True)
class _Artifact:
    artifact_kind: Literal["router", "member"]
    name: str
    role: Literal["required", "optional"]
    default: Literal["enabled", "disabled"]
    ownership: Literal["pack", "reference"]
    source_kind: Literal["pack", "bundled", "optional"]
    source_path: str
    source_relative_path: str
    install_path: str | None
    source_tree_sha256: str
    host_os: tuple[str, ...]
    required_toolsets: tuple[str, ...]


@dataclass(frozen=True)
class _SkillCandidate:
    origin: Literal["profile", "external"]
    path: Path
    effective_path: str
    sha256: str | None


def _validation(
    code: PackLifecycleIssueCode, message: str
) -> PackLifecycleValidationError:
    return PackLifecycleValidationError(code, message)


def _profile_subroot(home: Path, name: str) -> Path:
    """Return one non-redirected directory directly below an explicit home."""

    path = Path(home) / name
    try:
        if is_path_redirect(path):
            raise _validation(
                PackLifecycleIssueCode.SYMLINK_REJECTED,
                f"profile subdirectory {name!r} must not be a redirect",
            )
        if path.exists() and not path.is_dir():
            raise _validation(
                PackLifecycleIssueCode.PATH_UNSAFE,
                f"profile subdirectory {name!r} must be a directory",
            )
    except PackLifecycleValidationError:
        raise
    except OSError as exc:
        raise _validation(
            PackLifecycleIssueCode.PATH_UNSAFE,
            f"could not inspect profile subdirectory {name!r}: {exc}",
        ) from exc
    return path


def _normalize_external_roots(home: Path, roots: Sequence[Path]) -> tuple[Path, ...]:
    if isinstance(roots, (str, bytes, bytearray)):
        raise _validation(
            PackLifecycleIssueCode.PATH_UNSAFE,
            "external_skill_roots must be a sequence of absolute paths",
        )
    profile_skills = _profile_subroot(home, "skills").resolve()
    normalized: dict[str, Path] = {}
    for value in roots:
        path = Path(value)
        if not path.is_absolute():
            raise _validation(
                PackLifecycleIssueCode.PATH_UNSAFE,
                f"external skill root must be absolute: {path}",
            )
        try:
            if is_path_redirect(path):
                raise _validation(
                    PackLifecycleIssueCode.SYMLINK_REJECTED,
                    f"external skill root must not be a redirect: {path}",
                )
            resolved = path.resolve(strict=True)
        except PackLifecycleValidationError:
            raise
        except (OSError, RuntimeError) as exc:
            raise _validation(
                PackLifecycleIssueCode.PATH_UNSAFE,
                f"external skill root cannot be resolved: {path}",
            ) from exc
        if not resolved.is_dir():
            raise _validation(
                PackLifecycleIssueCode.PATH_UNSAFE,
                f"external skill root must be a directory: {path}",
            )
        if resolved == profile_skills:
            continue
        normalized[str(resolved)] = resolved
    return tuple(normalized[key] for key in sorted(normalized))


def _read_regular_bytes(path: Path, *, limit: int, label: str) -> bytes | None:
    """Read one optional bounded regular file without following redirects."""

    try:
        if not path.exists() and not path.is_symlink():
            return None
        if is_path_redirect(path):
            raise _validation(
                PackLifecycleIssueCode.PROFILE_CONFIG_INVALID
                if label == "profile config"
                else PackLifecycleIssueCode.STATE_INVALID,
                f"{label} must not be a symlink or reparse point",
            )
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise OSError(f"{label} is not a regular file")
        if before.st_size > limit:
            raise OSError(f"{label} exceeds {limit} bytes")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError(f"{label} changed type while opening")
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise OSError(f"{label} changed identity while opening")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise OSError(f"{label} exceeds {limit} bytes")
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
    except PackLifecycleValidationError:
        raise
    except OSError as exc:
        code = (
            PackLifecycleIssueCode.PROFILE_CONFIG_INVALID
            if label == "profile config"
            else PackLifecycleIssueCode.STATE_INVALID
        )
        raise _validation(code, f"could not safely read {label}: {exc}") from exc


def _load_profile_config(home: Path) -> Mapping[str, Any]:
    raw = _read_regular_bytes(
        Path(home) / "config.yaml",
        limit=MAX_PROFILE_CONFIG_BYTES,
        label="profile config",
    )
    if raw is None:
        return {}
    parser = YAML(typ="safe")
    parser.allow_duplicate_keys = False
    try:
        parsed = parser.load(raw.decode("utf-8"))
    except (UnicodeDecodeError, DuplicateKeyError, YAMLError, ValueError) as exc:
        raise _validation(
            PackLifecycleIssueCode.PROFILE_CONFIG_INVALID,
            f"config.yaml is not strict UTF-8 YAML: {exc}",
        ) from exc
    if parsed is None:
        return {}
    if not isinstance(parsed, Mapping):
        raise _validation(
            PackLifecycleIssueCode.PROFILE_CONFIG_INVALID,
            "config.yaml must contain a mapping",
        )
    return parsed


def _normalize_string_set(value: Any, *, field: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, Sequence) or isinstance(values, (bytes, bytearray)):
        raise _validation(
            PackLifecycleIssueCode.PROFILE_CONFIG_INVALID,
            f"{field} must be a string or list of strings",
        )
    result: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            raise _validation(
                PackLifecycleIssueCode.PROFILE_CONFIG_INVALID,
                f"{field} must contain only strings",
            )
        normalized = item.strip()
        if normalized:
            result.add(normalized)
    return frozenset(result)


def load_effective_disabled_skills(
    home: Path, session_platform: str | None
) -> frozenset[str]:
    """Return global plus exactly one supplied platform's disabled skills.

    ``None`` is intentionally global-only.  Unlike the legacy runtime helper,
    this function never consults ``HERMES_PLATFORM``, gateway session context,
    or any other ambient process state.
    """

    config = _load_profile_config(Path(home))
    skills = config.get("skills")
    if skills is None:
        return frozenset()
    if not isinstance(skills, Mapping):
        raise _validation(
            PackLifecycleIssueCode.PROFILE_CONFIG_INVALID,
            "skills must be a mapping",
        )
    disabled = set(
        _normalize_string_set(skills.get("disabled"), field="skills.disabled")
    )
    if session_platform is None:
        return frozenset(disabled)
    if not isinstance(session_platform, str) or not session_platform.strip():
        raise _validation(
            PackLifecycleIssueCode.PROFILE_CONFIG_INVALID,
            "session_platform must be None or a non-empty string",
        )
    platform_disabled = skills.get("platform_disabled")
    if platform_disabled is None:
        return frozenset(disabled)
    if not isinstance(platform_disabled, Mapping):
        raise _validation(
            PackLifecycleIssueCode.PROFILE_CONFIG_INVALID,
            "skills.platform_disabled must be a mapping",
        )
    disabled.update(
        _normalize_string_set(
            platform_disabled.get(session_platform),
            field=f"skills.platform_disabled.{session_platform}",
        )
    )
    return frozenset(disabled)


def _load_pack_state(home: Path) -> _PackState:
    path = _profile_subroot(Path(home), "capability-packs") / "state.json"
    raw = _read_regular_bytes(path, limit=MAX_PACK_STATE_BYTES, label="pack state")
    if raw is None:
        return _PackState(revision=0, installed={})

    def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _validation(
            PackLifecycleIssueCode.STATE_INVALID,
            f"state.json is not valid UTF-8 JSON: {exc}",
        ) from exc
    if (
        not isinstance(data, Mapping)
        or isinstance(data.get("schema_version"), bool)
        or data.get("schema_version") != 1
    ):
        raise _validation(
            PackLifecycleIssueCode.STATE_INVALID,
            "state.json must be a schema_version 1 mapping",
        )
    if set(data) != {
        "schema_version",
        "revision",
        "last_transaction_id",
        "installed",
    }:
        raise _validation(
            PackLifecycleIssueCode.STATE_INVALID,
            "state.json has missing or unknown fields",
        )
    last_transaction_id = data.get("last_transaction_id")
    if last_transaction_id is not None:
        try:
            parsed_transaction_id = uuid.UUID(str(last_transaction_id))
        except (ValueError, AttributeError) as exc:
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                "last_transaction_id must be null or a canonical UUID",
            ) from exc
        if str(parsed_transaction_id) != last_transaction_id:
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                "last_transaction_id must be null or a canonical UUID",
            )
    revision = data.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise _validation(
            PackLifecycleIssueCode.STATE_INVALID,
            "state revision must be a non-negative integer",
        )
    installed_raw = data.get("installed")
    if not isinstance(installed_raw, Mapping):
        raise _validation(
            PackLifecycleIssueCode.STATE_INVALID,
            "state installed must be a mapping",
        )
    installed: dict[str, _InstalledPack] = {}
    for pack_id, raw_pack in installed_raw.items():
        if (
            not isinstance(pack_id, str)
            or not _PACK_ID_RE.fullmatch(pack_id)
            or not isinstance(raw_pack, Mapping)
        ):
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                "installed pack entries must be string-keyed mappings",
            )
        if set(raw_pack) != {
            "version",
            "manifest_sha256",
            "installed_at",
            "updated_at",
            "owned",
            "members",
        }:
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                f"installed pack {pack_id!r} has missing or unknown fields",
            )
        version = raw_pack.get("version")
        manifest_sha256 = raw_pack.get("manifest_sha256")
        installed_at = raw_pack.get("installed_at")
        updated_at = raw_pack.get("updated_at")
        owned_raw = raw_pack.get("owned", {})
        members_raw = raw_pack.get("members", {})
        if (
            not isinstance(version, str)
            or not isinstance(manifest_sha256, str)
            or not _SHA256_RE.fullmatch(manifest_sha256)
            or not isinstance(installed_at, str)
            or not isinstance(updated_at, str)
            or not isinstance(owned_raw, Mapping)
            or not isinstance(members_raw, Mapping)
        ):
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                f"installed pack {pack_id!r} has invalid fields",
            )
        for field, value in (
            ("installed_at", installed_at),
            ("updated_at", updated_at),
        ):
            try:
                timestamp = datetime.fromisoformat(value)
            except ValueError as exc:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed pack {pack_id!r} has invalid {field}",
                ) from exc
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed pack {pack_id!r} {field} must be timezone-aware",
                )
        owned: dict[str, _OwnedPath] = {}
        for relative, record in owned_raw.items():
            try:
                normalized = normalize_relative_path(str(relative), field="owned path")
            except UnsafePathError as exc:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID, str(exc)
                ) from exc
            if normalized != relative or not isinstance(record, Mapping):
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed pack {pack_id!r} has a noncanonical owned path",
                )
            if set(record) != {"kind", "sha256"}:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"owned path {relative!r} has missing or unknown fields",
                )
            kind = record.get("kind")
            digest = record.get("sha256")
            if kind not in {"router", "member"} or (
                not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)
            ):
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"owned path {relative!r} has an invalid digest",
                )
            owned[normalized] = _OwnedPath(kind=kind, sha256=digest)
        members: dict[str, _InstalledMember] = {}
        for member_name, record in members_raw.items():
            if not isinstance(member_name, str) or not isinstance(record, Mapping):
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed pack {pack_id!r} has invalid member state",
                )
            if set(record) != {
                "ownership",
                "effective_path",
                "source_sha256",
                "installed_sha256",
            }:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed member {member_name!r} has missing or unknown fields",
                )
            ownership = record.get("ownership")
            effective_path = record.get("effective_path")
            source_sha256 = record.get("source_sha256")
            installed_sha256 = record.get("installed_sha256")
            if ownership not in {"pack", "reference"}:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed member {member_name!r} has invalid ownership",
                )
            try:
                normalized_effective = normalize_relative_path(
                    str(effective_path), field="effective path"
                )
            except UnsafePathError as exc:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID, str(exc)
                ) from exc
            if normalized_effective != effective_path:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed member {member_name!r} has a noncanonical effective path",
                )
            if not isinstance(source_sha256, str) or not _SHA256_RE.fullmatch(
                source_sha256
            ):
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed member {member_name!r} has an invalid source digest",
                )
            if installed_sha256 is not None and (
                not isinstance(installed_sha256, str)
                or not _SHA256_RE.fullmatch(installed_sha256)
            ):
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed member {member_name!r} has an invalid installed digest",
                )
            if ownership == "reference" and installed_sha256 is not None:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"reference member {member_name!r} must not have an installed digest",
                )
            if ownership == "pack" and installed_sha256 is None:
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"pack-owned member {member_name!r} requires an installed digest",
                )
            members[member_name] = _InstalledMember(
                ownership=ownership,
                effective_path=normalized_effective,
                source_sha256=source_sha256,
                installed_sha256=installed_sha256,
            )
        installed[pack_id] = _InstalledPack(
            version=version,
            manifest_sha256=manifest_sha256,
            installed_at=installed_at,
            updated_at=updated_at,
            owned=owned,
            members=members,
        )
    return _PackState(revision=revision, installed=installed)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID, f"{field} must be a mapping"
        )
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID, f"{field} must be a list"
        )
    return value


def _artifact(
    raw: Any,
    *,
    artifact_kind: Literal["router", "member"],
    release_root: PurePosixPath,
) -> _Artifact:
    data = _mapping(raw, artifact_kind)
    try:
        name = str(data["name"])
        ownership = data["ownership"]
        source_kind = data["source_kind"]
        try:
            source_path = normalize_relative_path(
                str(data["source_path"]), field="source path"
            )
        except UnsafePathError as exc:
            raise _validation(PackLifecycleIssueCode.CATALOG_INVALID, str(exc)) from exc
        source_digest = str(data["source_tree_sha256"])
        host_os_raw = _sequence(
            data.get("effective_host_os", data.get("host_os")), "host_os"
        )
        required_toolsets_raw = _sequence(
            data.get("required_toolsets", []), "required_toolsets"
        )
    except KeyError as exc:
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID,
            f"{artifact_kind} is missing {exc.args[0]}",
        ) from exc
    if ownership not in {"pack", "reference"} or source_kind not in {
        "pack",
        "bundled",
        "optional",
    }:
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID,
            f"{name!r} has invalid ownership/source kind",
        )
    if not _SHA256_RE.fullmatch(source_digest):
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID,
            f"{name!r} has an invalid source digest",
        )
    host_os = tuple(str(value) for value in host_os_raw)
    if any(value not in {"linux", "macos", "windows"} for value in host_os):
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID,
            f"{name!r} has invalid host support",
        )
    required_toolsets = tuple(sorted({str(value) for value in required_toolsets_raw}))
    install_raw = data.get("install_path")
    if ownership == "pack":
        if not isinstance(install_raw, str):
            raise _validation(
                PackLifecycleIssueCode.CATALOG_INVALID,
                f"pack-owned {name!r} requires an install path",
            )
        try:
            install_path = normalize_skill_install_path(install_raw, name)
        except UnsafePathError as exc:
            raise _validation(PackLifecycleIssueCode.CATALOG_INVALID, str(exc)) from exc
    else:
        if install_raw is not None:
            raise _validation(
                PackLifecycleIssueCode.CATALOG_INVALID,
                f"reference {name!r} must not declare an install path",
            )
        install_path = None
    if artifact_kind == "router":
        role: Literal["required", "optional"] = "required"
        default: Literal["enabled", "disabled"] = "enabled"
    else:
        role = data.get("role")
        default = data.get("default")
        if role not in {"required", "optional"} or default not in {
            "enabled",
            "disabled",
        }:
            raise _validation(
                PackLifecycleIssueCode.CATALOG_INVALID,
                f"member {name!r} has an invalid role/default",
            )
    source_relative = (
        release_root / PurePosixPath(source_path)
        if source_kind == "pack"
        else PurePosixPath(source_path)
    ).as_posix()
    return _Artifact(
        artifact_kind=artifact_kind,
        name=name,
        role=role,
        default=default,
        ownership=ownership,
        source_kind=source_kind,
        source_path=source_path,
        source_relative_path=source_relative,
        install_path=install_path,
        source_tree_sha256=source_digest,
        host_os=host_os,
        required_toolsets=required_toolsets,
    )


def _select_release(
    catalog: Mapping[str, Any], pack_id: str, target_version: str
) -> tuple[Mapping[str, Any], tuple[_Artifact, ...]]:
    packs = _sequence(catalog.get("packs"), "catalog.packs")
    selected_pack: Mapping[str, Any] | None = None
    for raw_pack in packs:
        pack = _mapping(raw_pack, "catalog pack")
        if pack.get("id") == pack_id:
            if selected_pack is not None:
                raise _validation(
                    PackLifecycleIssueCode.CATALOG_INVALID,
                    f"duplicate pack ID {pack_id!r}",
                )
            selected_pack = pack
    if selected_pack is None:
        raise _validation(
            PackLifecycleIssueCode.PACK_UNKNOWN, f"unknown pack: {pack_id}"
        )
    release: Mapping[str, Any] | None = None
    for raw_release in _sequence(selected_pack.get("releases"), "pack.releases"):
        candidate = _mapping(raw_release, "pack release")
        if candidate.get("version") == target_version:
            if release is not None:
                raise _validation(
                    PackLifecycleIssueCode.CATALOG_INVALID,
                    f"duplicate release {pack_id}@{target_version}",
                )
            release = candidate
    if release is None:
        raise _validation(
            PackLifecycleIssueCode.TARGET_RELEASE_UNAVAILABLE,
            f"release not retained: {pack_id}@{target_version}",
        )
    manifest = _mapping(release.get("authoring_manifest"), "authoring_manifest")
    try:
        manifest_path = normalize_relative_path(
            str(manifest.get("path")), field="manifest path"
        )
    except UnsafePathError as exc:
        raise _validation(PackLifecycleIssueCode.CATALOG_INVALID, str(exc)) from exc
    release_root = PurePosixPath(manifest_path).parent
    artifacts = [
        _artifact(
            release.get("router"), artifact_kind="router", release_root=release_root
        )
    ]
    artifacts.extend(
        _artifact(value, artifact_kind="member", release_root=release_root)
        for value in _sequence(release.get("members"), "release.members")
    )
    names: set[str] = set()
    for artifact in artifacts:
        if artifact.name in names:
            raise _validation(
                PackLifecycleIssueCode.CATALOG_INVALID,
                f"duplicate artifact name {artifact.name!r}",
            )
        names.add(artifact.name)
    return release, tuple(artifacts)


def _validate_installed_pack_binding(
    catalog: Mapping[str, Any], pack_id: str, installed: _InstalledPack
) -> None:
    """Prove persisted ownership facts came from one retained catalog release."""

    release, artifacts = _select_release(catalog, pack_id, installed.version)
    manifest = _mapping(release.get("authoring_manifest"), "authoring_manifest")
    if installed.manifest_sha256 != manifest.get("sha256"):
        raise _validation(
            PackLifecycleIssueCode.STATE_INVALID,
            f"installed pack {pack_id!r} manifest digest is not catalog-bound",
        )
    router = artifacts[0]
    if router.artifact_kind != "router" or router.ownership != "pack":
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID,
            f"pack {pack_id!r} router must be pack-owned",
        )
    members = {
        artifact.name: artifact
        for artifact in artifacts
        if artifact.artifact_kind == "member"
    }
    unknown_members = set(installed.members) - set(members)
    missing_required = {
        name
        for name, artifact in members.items()
        if artifact.role == "required" and name not in installed.members
    }
    if unknown_members or missing_required:
        raise _validation(
            PackLifecycleIssueCode.STATE_INVALID,
            f"installed pack {pack_id!r} member set does not match its release",
        )

    expected_owned: dict[str, _OwnedPath] = {}
    assert router.install_path is not None
    expected_owned[router.install_path] = _OwnedPath(
        kind="router", sha256=router.source_tree_sha256
    )
    for name, state_member in installed.members.items():
        artifact = members[name]
        if state_member.ownership != artifact.ownership:
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                f"installed member {name!r} ownership is not catalog-bound",
            )
        if state_member.source_sha256 != artifact.source_tree_sha256:
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                f"installed member {name!r} source digest is not catalog-bound",
            )
        if artifact.ownership == "pack":
            assert artifact.install_path is not None
            if (
                state_member.effective_path != artifact.install_path
                or state_member.installed_sha256 != artifact.source_tree_sha256
            ):
                raise _validation(
                    PackLifecycleIssueCode.STATE_INVALID,
                    f"installed member {name!r} path/digest is not catalog-bound",
                )
            expected_owned[artifact.install_path] = _OwnedPath(
                kind="member", sha256=artifact.source_tree_sha256
            )
        elif state_member.installed_sha256 is not None:
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                f"reference member {name!r} cannot own installed bytes",
            )
    if installed.owned != expected_owned:
        raise _validation(
            PackLifecycleIssueCode.STATE_INVALID,
            f"installed pack {pack_id!r} owned paths are not catalog-bound",
        )


def _installed_identity(installed: _InstalledPack | None) -> Mapping[str, Any] | None:
    if installed is None:
        return None
    return {
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
        "version": installed.version,
    }


def _frontmatter_name(skill_file: Path) -> str | None:
    try:
        raw = _read_regular_bytes(skill_file, limit=64 * 1024, label="pack state")
    except PackLifecycleValidationError:
        return None
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    for line in text[3:end].splitlines():
        match = re.fullmatch(r"\s*name\s*:\s*([^#]+?)\s*", line)
        if match:
            return match.group(1).strip().strip("\"'") or None
    return None


def _skill_directories(root: Path, *, name: str, preferred: str) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    candidates: dict[str, Path] = {}
    direct_relatives = {preferred, name}
    for relative in sorted(direct_relatives):
        try:
            candidate = resolve_relative_path(root, relative, must_exist=False)
        except (OSError, UnsafePathError):
            continue
        if candidate.is_dir() and (candidate / "SKILL.md").is_file():
            candidates[str(candidate.resolve())] = candidate

    entry_count = 0
    for current, directories, files in os.walk(root, followlinks=False):
        entry_count += len(directories) + len(files)
        if entry_count > MAX_SKILL_SCAN_ENTRIES:
            raise _validation(
                PackLifecycleIssueCode.STATE_INVALID,
                f"skill inventory under {root} exceeds {MAX_SKILL_SCAN_ENTRIES} entries",
            )
        current_path = Path(current)
        has_skill = "SKILL.md" in files
        kept: list[str] = []
        for directory in directories:
            child = current_path / directory
            if directory in _SKIP_DIRECTORIES or (
                has_skill and directory in _SUPPORT_DIRECTORIES
            ):
                continue
            try:
                if is_path_redirect(child):
                    continue
            except OSError:
                continue
            kept.append(directory)
        directories[:] = kept
        if not has_skill:
            continue
        skill_file = current_path / "SKILL.md"
        if current_path.name == name or _frontmatter_name(skill_file) == name:
            candidates[str(current_path.resolve())] = current_path
    return tuple(candidates[key] for key in sorted(candidates))


def _candidate(
    path: Path,
    *,
    root: Path,
    origin: Literal["profile", "external"],
) -> _SkillCandidate:
    try:
        resolved_path = path.resolve(strict=True)
        relative = resolved_path.relative_to(root.resolve(strict=True)).as_posix()
        digest = sha256_tree(
            path, max_file_bytes=16 * 1024 * 1024, max_total_bytes=64 * 1024 * 1024
        )
    except (OSError, RuntimeError, UnsafePathError, ValueError):
        resolved_path = path
        relative = path.name
        digest = None
    effective = relative if origin == "profile" else str(resolved_path)
    return _SkillCandidate(
        origin=origin, path=path, effective_path=effective, sha256=digest
    )


def _inventory_candidates(
    artifact: _Artifact,
    *,
    home: Path,
    external_skill_roots: Sequence[Path],
    installed: _InstalledPack | None,
) -> tuple[_SkillCandidate, ...]:
    skills_root = _profile_subroot(home, "skills")
    preferred = artifact.source_path
    if installed is not None:
        member_state = installed.members.get(artifact.name)
        if member_state is not None:
            preferred = member_state.effective_path
    candidates = [
        _candidate(path, root=skills_root, origin="profile")
        for path in _skill_directories(
            skills_root, name=artifact.name, preferred=preferred
        )
    ]
    for root in external_skill_roots:
        explicit_root = Path(root)
        candidates.extend(
            _candidate(path, root=explicit_root, origin="external")
            for path in _skill_directories(
                explicit_root, name=artifact.name, preferred=artifact.source_path
            )
        )
    return tuple(candidates)


def _enabled(
    artifact: _Artifact, overrides: Mapping[str, str]
) -> tuple[bool, Literal["required", "default", "override"]]:
    if artifact.artifact_kind == "router":
        return True, "required"
    override = overrides.get(artifact.name, "inherit")
    if override == "enabled":
        return True, "override"
    if override == "disabled":
        return False, "override"
    return artifact.default == "enabled", "default"


def _member_issue(
    code: PackLifecycleIssueCode,
    *,
    artifact: _Artifact,
    severity: Literal["info", "warning", "error"],
    message: str,
) -> PackIssue:
    return PackIssue(
        code=code, severity=severity, member=artifact.name, message=message
    )


def _issue_severity(
    artifact: _Artifact, *, enabled: bool
) -> Literal["info", "warning", "error"]:
    if not enabled:
        return "info"
    return "error" if artifact.role == "required" else "warning"


def _neutral_inventory(
    artifact: _Artifact,
    *,
    enabled: bool,
    home: Path,
    external_skill_roots: Sequence[Path],
    installed: _InstalledPack | None,
) -> tuple[MemberClassification, str | None, str | None, tuple[PackIssue, ...]]:
    skills_root = _profile_subroot(home, "skills")
    if artifact.ownership == "pack":
        assert artifact.install_path is not None
        try:
            destination = resolve_relative_path(
                skills_root, artifact.install_path, must_exist=False
            )
        except UnsafePathError as exc:
            raise _validation(
                PackLifecycleIssueCode.SYMLINK_REJECTED,
                f"unsafe pack destination for {artifact.name}: {exc}",
            ) from exc
        candidates = _inventory_candidates(
            artifact,
            home=home,
            external_skill_roots=external_skill_roots,
            installed=installed,
        )
        collisions: list[_SkillCandidate] = []
        for candidate in candidates:
            try:
                is_destination = (
                    candidate.origin == "profile"
                    and candidate.path.resolve() == destination
                )
            except (OSError, RuntimeError):
                is_destination = False
            if not is_destination:
                collisions.append(candidate)
        owned_record = installed.owned.get(artifact.install_path) if installed else None
        owned_digest = owned_record.sha256 if owned_record is not None else None
        if destination.exists():
            try:
                digest = sha256_tree(
                    destination,
                    max_file_bytes=16 * 1024 * 1024,
                    max_total_bytes=64 * 1024 * 1024,
                )
            except (OSError, UnsafePathError, ValueError):
                digest = None
            if owned_digest is None or digest != owned_digest:
                issue = _member_issue(
                    PackLifecycleIssueCode.USER_MODIFIED_CONFLICT,
                    artifact=artifact,
                    severity="error",
                    message=f"{artifact.name} occupies an unowned or modified pack path",
                )
                return (
                    MemberClassification.USER_MODIFIED,
                    artifact.install_path,
                    digest,
                    (issue,),
                )
            if collisions:
                issue = _member_issue(
                    PackLifecycleIssueCode.EXTERNAL_SHADOW,
                    artifact=artifact,
                    severity=_issue_severity(artifact, enabled=enabled),
                    message=f"another local or external skill collides with pack-owned {artifact.name}",
                )
                return (
                    MemberClassification.EXTERNAL_SHADOW,
                    artifact.install_path,
                    digest,
                    (issue,),
                )
            return MemberClassification.PACK_OWNED, artifact.install_path, digest, ()
        if collisions:
            issue = _member_issue(
                PackLifecycleIssueCode.EXTERNAL_SHADOW,
                artifact=artifact,
                severity=_issue_severity(artifact, enabled=enabled),
                message=f"another local or external skill would collide with pack-owned {artifact.name}",
            )
            return (
                MemberClassification.EXTERNAL_SHADOW,
                collisions[0].effective_path,
                None,
                (issue,),
            )
        return MemberClassification.MISSING, artifact.install_path, None, ()

    candidates = _inventory_candidates(
        artifact,
        home=home,
        external_skill_roots=external_skill_roots,
        installed=installed,
    )
    profile_candidates = tuple(
        value for value in candidates if value.origin == "profile"
    )
    external_candidates = tuple(
        value for value in candidates if value.origin == "external"
    )
    if external_candidates or len(profile_candidates) > 1:
        selected = (
            external_candidates[0] if external_candidates else profile_candidates[0]
        )
        issue = _member_issue(
            PackLifecycleIssueCode.EXTERNAL_SHADOW,
            artifact=artifact,
            severity=_issue_severity(artifact, enabled=enabled),
            message=f"{artifact.name} resolves to an external or ambiguous skill",
        )
        return (
            MemberClassification.EXTERNAL_SHADOW,
            selected.effective_path,
            selected.sha256,
            (issue,),
        )
    if not profile_candidates:
        issue = _member_issue(
            PackLifecycleIssueCode.SKILL_MISSING,
            artifact=artifact,
            severity=_issue_severity(artifact, enabled=enabled),
            message=f"referenced skill {artifact.name} is not installed in the profile",
        )
        return MemberClassification.MISSING, artifact.source_path, None, (issue,)
    selected = profile_candidates[0]
    if selected.sha256 != artifact.source_tree_sha256:
        issue = _member_issue(
            PackLifecycleIssueCode.USER_MODIFIED_CONFLICT,
            artifact=artifact,
            severity=_issue_severity(artifact, enabled=enabled),
            message=f"referenced skill {artifact.name} does not match the admitted digest",
        )
        return (
            MemberClassification.USER_MODIFIED,
            selected.effective_path,
            selected.sha256,
            (issue,),
        )
    return MemberClassification.READY, selected.effective_path, selected.sha256, ()


def _operation_for_member(
    artifact: _Artifact,
    *,
    enabled: bool,
    state_owned: bool,
    owned_sha256: str | None,
    inventory_status: MemberClassification,
    effective_path: str | None,
    current_sha256: str | None,
) -> PackOperation:
    if (
        artifact.ownership == "pack"
        and enabled
        and inventory_status
        in {
            MemberClassification.MISSING,
            MemberClassification.PACK_OWNED,
        }
        and current_sha256 != artifact.source_tree_sha256
    ):
        kind: Literal["promote", "remove", "preserve"] = "promote"
    elif (
        artifact.ownership == "pack"
        and not enabled
        and state_owned
        and (current_sha256 is None or current_sha256 == owned_sha256)
    ):
        kind = "remove"
    else:
        kind = "preserve"
    destination = (
        artifact.install_path if artifact.ownership == "pack" else effective_path
    )
    return PackOperation(
        kind=kind,
        artifact_kind=artifact.artifact_kind,
        member=artifact.name,
        ownership=artifact.ownership,
        source_kind=artifact.source_kind,
        source_relative_path=artifact.source_relative_path,
        destination_relative_path=destination,
        before_sha256=current_sha256,
        after_sha256=(
            artifact.source_tree_sha256
            if kind == "promote"
            else None
            if kind == "remove"
            else current_sha256
        ),
    )


def _mutation_status(
    members: Sequence[MemberStatus], operations: Sequence[PackOperation]
) -> MutationPlanStatus:
    enabled = tuple(member for member in members if member.enabled)
    if any(member.role == "required" and not member.enabled for member in members):
        return MutationPlanStatus.BLOCKED
    if any(
        member.inventory_status == MemberClassification.USER_MODIFIED
        and member.ownership == "pack"
        for member in enabled
    ) or any(
        member.inventory_status == MemberClassification.EXTERNAL_SHADOW
        and member.role == "required"
        for member in enabled
    ):
        return MutationPlanStatus.CONFLICT
    if any(
        member.role == "required"
        and member.inventory_status
        in {
            MemberClassification.MISSING,
            MemberClassification.USER_MODIFIED,
        }
        and member.ownership == "reference"
        for member in enabled
    ) or any(
        member.role == "required" and not member.host_supported for member in enabled
    ):
        return MutationPlanStatus.BLOCKED
    if any(
        member.role == "optional"
        and (
            (
                member.ownership == "reference"
                and member.inventory_status == MemberClassification.MISSING
            )
            or member.inventory_status
            in {
                MemberClassification.EXTERNAL_SHADOW,
                MemberClassification.USER_MODIFIED,
            }
        )
        for member in enabled
    ) or any(
        member.role == "optional" and not member.host_supported for member in enabled
    ):
        return MutationPlanStatus.DEGRADED
    if any(
        member.ownership == "pack" and member.state_owned and not member.enabled
        for member in members
    ):
        return MutationPlanStatus.READY
    if any(operation.kind in {"promote", "remove"} for operation in operations):
        return MutationPlanStatus.READY
    return MutationPlanStatus.UNCHANGED


def _context_health(members: Sequence[MemberStatus]) -> PackContextHealth:
    enabled = tuple(member for member in members if member.enabled)
    if any(member.role == "required" and not member.enabled for member in members):
        return PackContextHealth.BLOCKED
    if any(
        member.inventory_status == MemberClassification.USER_MODIFIED
        for member in enabled
    ):
        return PackContextHealth.DRIFTED
    failures = {
        MemberClassification.MISSING,
        MemberClassification.DISABLED,
        MemberClassification.UNSUPPORTED,
        MemberClassification.UNAVAILABLE_TOOLSET,
        MemberClassification.EXTERNAL_SHADOW,
        MemberClassification.USER_MODIFIED,
    }
    if any(
        member.role == "required" and member.status in failures for member in enabled
    ):
        return PackContextHealth.BLOCKED
    if any(
        member.role == "optional" and member.status in failures for member in enabled
    ):
        return PackContextHealth.DEGRADED
    return PackContextHealth.HEALTHY


def plan_pack(
    pack_id: str,
    *,
    home: Path,
    catalog: Mapping[str, Any],
    operation: Literal["apply", "update", "downgrade", "remove", "override"],
    target_version: str,
    host_os: Literal["linux", "macos", "windows"],
    session_platform: str | None,
    available_toolsets: frozenset[str],
    overrides: Mapping[str, str],
    external_skill_roots: Sequence[Path],
) -> PackPlanResult:
    """Build a deterministic, side-effect-free plan for one explicit profile."""

    if operation not in {"apply", "update", "downgrade", "remove", "override"}:
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID,
            f"invalid capability-pack operation: {operation}",
        )
    if host_os not in {"linux", "macos", "windows"}:
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID, f"invalid host_os: {host_os}"
        )
    if not isinstance(available_toolsets, frozenset) or any(
        not isinstance(value, str) for value in available_toolsets
    ):
        raise _validation(
            PackLifecycleIssueCode.CATALOG_INVALID,
            "available_toolsets must be a frozenset of strings",
        )
    try:
        explicit_home = Path(home).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise _validation(
            PackLifecycleIssueCode.PATH_UNSAFE,
            f"profile home cannot be resolved: {home}",
        ) from exc
    if explicit_home.exists() and not explicit_home.is_dir():
        raise _validation(
            PackLifecycleIssueCode.PATH_UNSAFE,
            f"profile home must be a directory: {explicit_home}",
        )
    _profile_subroot(explicit_home, "skills")
    _profile_subroot(explicit_home, "capability-packs")
    normalized_external_roots = _normalize_external_roots(
        explicit_home, external_skill_roots
    )
    release, artifacts = _select_release(catalog, pack_id, target_version)
    member_names = {
        artifact.name for artifact in artifacts if artifact.artifact_kind == "member"
    }
    for name, value in overrides.items():
        if name not in member_names or value not in {"enabled", "disabled", "inherit"}:
            raise _validation(
                PackLifecycleIssueCode.OVERRIDE_INVALID,
                f"invalid override {name!r}={value!r}",
            )
    disabled = load_effective_disabled_skills(explicit_home, session_platform)
    state = _load_pack_state(explicit_home)
    installed = state.installed.get(pack_id)
    if installed is not None:
        _validate_installed_pack_binding(catalog, pack_id, installed)
    if (
        operation == "remove"
        and installed is not None
        and target_version != installed.version
    ):
        raise _validation(
            PackLifecycleIssueCode.TARGET_RELEASE_UNAVAILABLE,
            "remove planning must target the exact installed release",
        )
    operations: list[PackOperation] = []
    members: list[MemberStatus] = []
    all_issues: list[PackIssue] = []
    for artifact in artifacts:
        enabled, enablement_source = _enabled(artifact, overrides)
        state_owned = bool(
            installed is not None
            and artifact.install_path is not None
            and artifact.install_path in installed.owned
        )
        owned_record = (
            installed.owned.get(artifact.install_path)
            if installed is not None and artifact.install_path is not None
            else None
        )
        inventory_status, effective_path, current_digest, inventory_issues = (
            _neutral_inventory(
                artifact,
                enabled=enabled,
                home=explicit_home,
                external_skill_roots=normalized_external_roots,
                installed=installed,
            )
        )
        issues = list(inventory_issues)
        missing_toolsets = tuple(
            sorted(set(artifact.required_toolsets) - set(available_toolsets))
        )
        host_supported = host_os in artifact.host_os
        contextual_status = inventory_status
        if not enabled:
            contextual_status = MemberClassification.DISABLED
            if artifact.role == "required":
                issues.append(
                    _member_issue(
                        PackLifecycleIssueCode.SKILL_DISABLED,
                        artifact=artifact,
                        severity="error",
                        message=f"required member {artifact.name} is disabled by override",
                    )
                )
        elif artifact.name in disabled:
            contextual_status = MemberClassification.DISABLED
            issues.append(
                _member_issue(
                    PackLifecycleIssueCode.SKILL_DISABLED,
                    artifact=artifact,
                    severity=_issue_severity(artifact, enabled=True),
                    message=f"{artifact.name} is disabled for the supplied session context",
                )
            )
        elif not host_supported:
            contextual_status = MemberClassification.UNSUPPORTED
            issues.append(
                _member_issue(
                    PackLifecycleIssueCode.HOST_UNSUPPORTED,
                    artifact=artifact,
                    severity=_issue_severity(artifact, enabled=True),
                    message=f"{artifact.name} is not admitted on {host_os}",
                )
            )
        elif missing_toolsets:
            contextual_status = MemberClassification.UNAVAILABLE_TOOLSET
            issues.append(
                _member_issue(
                    PackLifecycleIssueCode.TOOLSET_UNAVAILABLE,
                    artifact=artifact,
                    severity=_issue_severity(artifact, enabled=True),
                    message=(
                        f"{artifact.name} requires unavailable toolsets: "
                        + ", ".join(missing_toolsets)
                    ),
                )
            )
        member_operation = _operation_for_member(
            artifact,
            enabled=enabled,
            state_owned=state_owned,
            owned_sha256=owned_record.sha256 if owned_record is not None else None,
            inventory_status=inventory_status,
            effective_path=effective_path,
            current_sha256=current_digest,
        )
        operations.append(member_operation)
        member = MemberStatus(
            artifact_kind=artifact.artifact_kind,
            name=artifact.name,
            role=artifact.role,
            ownership=artifact.ownership,
            state_owned=state_owned,
            enabled=enabled,
            enablement_source=enablement_source,
            inventory_status=inventory_status,
            status=contextual_status,
            effective_path=effective_path,
            current_sha256=current_digest,
            expected_sha256=artifact.source_tree_sha256,
            host_supported=host_supported,
            missing_toolsets=missing_toolsets,
            issues=tuple(issues),
        )
        members.append(member)
        all_issues.extend(issues)

    artifact_by_install_path = {
        artifact.install_path: artifact
        for artifact in artifacts
        if artifact.ownership == "pack" and artifact.install_path is not None
    }
    if operation == "remove":
        operations = [
            operation_record
            for operation_record, member in zip(operations, members, strict=True)
            if member.ownership == "reference" or not member.state_owned
        ]
        target_paths: set[str] = set()
    else:
        target_paths = set(artifact_by_install_path)
    if installed is not None:
        skills_root = _profile_subroot(explicit_home, "skills")
        for old_path, old_record in sorted(installed.owned.items()):
            old_digest = old_record.sha256
            if old_path in target_paths:
                continue
            unsafe_reason: str | None = None
            try:
                destination = resolve_relative_path(
                    skills_root, old_path, must_exist=False
                )
            except UnsafePathError as exc:
                destination = skills_root / PurePosixPath(old_path)
                unsafe_reason = str(exc)
            current_digest: str | None = None
            path_present = (
                False
                if unsafe_reason is not None
                else destination.exists() or destination.is_symlink()
            )
            hash_failed = False
            if path_present and unsafe_reason is None:
                try:
                    current_digest = sha256_tree(
                        destination,
                        max_file_bytes=16 * 1024 * 1024,
                        max_total_bytes=64 * 1024 * 1024,
                    )
                except (OSError, UnsafePathError, ValueError) as exc:
                    hash_failed = True
                    unsafe_reason = str(exc)
            if (
                unsafe_reason is not None
                or hash_failed
                or (current_digest is not None and current_digest != old_digest)
            ):
                all_issues.append(
                    PackIssue(
                        code=PackLifecycleIssueCode.USER_MODIFIED_CONFLICT,
                        severity="error",
                        member=None,
                        message=(
                            f"obsolete owned path {old_path} is unsafe or modified "
                            "and will be preserved"
                        ),
                    )
                )
                kind: Literal["remove", "preserve"] = "preserve"
            else:
                kind = "remove"
            operations.append(
                PackOperation(
                    kind=kind,
                    artifact_kind=(
                        artifact_by_install_path[old_path].artifact_kind
                        if old_path in artifact_by_install_path
                        else old_record.kind
                    ),
                    member=(
                        artifact_by_install_path[old_path].name
                        if old_path in artifact_by_install_path
                        else PurePosixPath(old_path).name
                    ),
                    ownership="pack",
                    source_kind="pack",
                    source_relative_path=(
                        artifact_by_install_path[old_path].source_relative_path
                        if old_path in artifact_by_install_path
                        else ""
                    ),
                    destination_relative_path=old_path,
                    before_sha256=current_digest,
                    after_sha256=None,
                )
            )

    if operation == "remove":
        neutral_status = (
            MutationPlanStatus.UNCHANGED
            if installed is None
            else MutationPlanStatus.READY
        )
    else:
        neutral_status = _mutation_status(members, operations)
    if any(
        issue.code == PackLifecycleIssueCode.USER_MODIFIED_CONFLICT
        and issue.member is None
        for issue in all_issues
    ):
        neutral_status = MutationPlanStatus.CONFLICT
    target_manifest_sha256 = _mapping(
        release.get("authoring_manifest"), "authoring_manifest"
    ).get("sha256")
    if (
        operation != "remove"
        and neutral_status == MutationPlanStatus.UNCHANGED
        and (
            installed is None
            or installed.version != target_version
            or installed.manifest_sha256 != target_manifest_sha256
        )
    ):
        neutral_status = MutationPlanStatus.READY
    mutation_inputs = {
        "host_os": host_os,
        "operation": operation,
        "inventory": [
            {
                "current_sha256": member.current_sha256,
                "effective_path": member.effective_path,
                "enabled": member.enabled,
                "inventory_status": member.inventory_status.value,
                "host_supported": member.host_supported,
                "name": member.name,
                "ownership": member.ownership,
                "state_owned": member.state_owned,
            }
            for member in members
        ],
        "installed_identity": _installed_identity(installed),
        "manifest_sha256": target_manifest_sha256,
        "operations": [
            {
                "after_sha256": operation.after_sha256,
                "before_sha256": operation.before_sha256,
                "destination_relative_path": operation.destination_relative_path,
                "kind": operation.kind,
                "member": operation.member,
                "source_relative_path": operation.source_relative_path,
            }
            for operation in operations
        ],
        "overrides": {name: overrides[name] for name in sorted(overrides)},
        "pack_id": pack_id,
        "release_tree_sha256": release.get("release_tree_sha256"),
        "revision": state.revision,
        "target_version": target_version,
    }
    mutation_digest = hashlib.sha256(canonical_json_bytes(mutation_inputs)).hexdigest()
    context_digest = hashlib.sha256(
        canonical_json_bytes({
            "available_toolsets": sorted(available_toolsets),
            "disabled_skills": sorted(disabled),
            "mutation_plan_digest": mutation_digest,
            "session_platform": session_platform,
        })
    ).hexdigest()
    return PackPlanResult(
        mutation_status=neutral_status,
        context_health=_context_health(members),
        pack_id=pack_id,
        operation=operation,
        from_version=installed.version if installed is not None else None,
        to_version=target_version,
        expected_revision=state.revision,
        mutation_plan_digest=mutation_digest,
        context_digest=context_digest,
        host_os=host_os,
        session_platform=session_platform,
        operations=tuple(operations),
        members=tuple(members),
        issues=tuple(all_issues),
    )


__all__ = [
    "MemberClassification",
    "MemberStatus",
    "MutationPlanStatus",
    "PackContextHealth",
    "PackIssue",
    "PackLifecycleIssueCode",
    "PackLifecycleValidationError",
    "PackOperation",
    "PackPlanResult",
    "load_effective_disabled_skills",
    "plan_pack",
]
