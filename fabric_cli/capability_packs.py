"""Deterministic, fail-closed capability-pack catalog compiler.

This module owns the distribution-time contract for capability packs.  It is
deliberately independent from the profile-scoped lifecycle implementation:
compiling and validating a catalog never installs a skill, changes config, or
contacts the network.

The authoring inputs are strict YAML.  The output is canonical JSON whose
referenced source trees, licenses, notices, nested assets, and host-evidence
records have all been hashed locally.  Runtime consumers can therefore reject
non-canonical or drifted distribution data instead of silently skipping a bad
entry.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from functools import total_ordering
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, Mapping, Sequence
from urllib.parse import urlsplit

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import YAMLError

from tools.skill_install import (
    is_path_redirect,
    iter_regular_files,
    normalize_relative_path,
    normalize_skill_install_path,
    resolve_relative_path,
    sha256_tree,
)


SCHEMA_VERSION = 1
CATALOG_SOURCE_NAME = "catalog.yaml"
CATALOG_OUTPUT_NAME = "catalog.json"
MAX_AUTHORING_BYTES = 2 * 1024 * 1024
MAX_COMPILED_BYTES = 32 * 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_TOOLSET_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_ISSUE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_HOST_OS = frozenset({"linux", "macos", "windows"})

PlatformEvidenceVerifier = Callable[[Path, bytes, Mapping[str, Any]], None]


class PackIssueCode(StrEnum):
    """Stable machine-readable validation issue codes."""

    CATALOG_NOT_CANONICAL = "CATALOG_NOT_CANONICAL"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    DUPLICATE_ID = "DUPLICATE_ID"
    DUPLICATE_INSTALL_PATH = "DUPLICATE_INSTALL_PATH"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    DUPLICATE_MEMBER = "DUPLICATE_MEMBER"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    LICENSE_EVIDENCE_MISSING = "LICENSE_EVIDENCE_MISSING"
    NESTED_ASSET_EVIDENCE_MISSING = "NESTED_ASSET_EVIDENCE_MISSING"
    NOTICE_EVIDENCE_MISSING = "NOTICE_EVIDENCE_MISSING"
    PATH_UNSAFE = "PATH_UNSAFE"
    PLATFORM_EVIDENCE_INVALID = "PLATFORM_EVIDENCE_INVALID"
    PLATFORM_EVIDENCE_MISSING = "PLATFORM_EVIDENCE_MISSING"
    PROVENANCE_EVIDENCE_MISSING = "PROVENANCE_EVIDENCE_MISSING"
    PROVENANCE_PIN_INVALID = "PROVENANCE_PIN_INVALID"
    PROVENANCE_REF_INVALID = "PROVENANCE_REF_INVALID"
    SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
    SOURCE_MISSING = "SOURCE_MISSING"
    SOURCE_NOT_REGULAR = "SOURCE_NOT_REGULAR"
    SPDX_INVALID = "SPDX_INVALID"
    SPECIFIER_INVALID = "SPECIFIER_INVALID"
    TYPE_INVALID = "TYPE_INVALID"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    VERSION_INVALID = "VERSION_INVALID"
    YAML_INVALID = "YAML_INVALID"


class CapabilityPackValidationError(ValueError):
    """A fail-closed catalog validation failure with a stable issue code."""

    def __init__(
        self,
        code: PackIssueCode,
        message: str,
        *,
        location: str | Path | None = None,
    ) -> None:
        self.code = code
        self.location = str(location) if location is not None else None
        prefix = f"{self.location}: " if self.location else ""
        super().__init__(f"{code.value}: {prefix}{message}")


@dataclass(frozen=True)
class NestedAssetRecord:
    path: PurePosixPath
    canonical_source_url: str
    pinned_revision: str
    source_path: PurePosixPath
    copyright_holders: tuple[str, ...]
    spdx_expression: str
    license_file: PurePosixPath
    license_source_path: PurePosixPath
    license_file_sha256: str
    sha256: str


@dataclass(frozen=True)
class EvidenceFileRecord:
    path: PurePosixPath
    sha256: str


@dataclass(frozen=True)
class SourceRepository:
    root: Path
    trusted_ref: str | None = None


@dataclass(frozen=True)
class PlatformEvidenceRecord:
    path: PurePosixPath
    sha256: str
    source_tree_sha256: str
    source_revisions: tuple[str, ...]
    verified_host_os: tuple[Literal["linux", "macos", "windows"], ...]
    check_evidence: tuple[EvidenceFileRecord, ...]


@dataclass(frozen=True)
class PackPermissions:
    required_toolsets: tuple[str, ...]
    optional_toolsets: tuple[str, ...]
    secrets: tuple[str, ...]
    network: Literal["inherited"]


@dataclass(frozen=True)
class PackProvenance:
    publisher: str
    source_repository: str
    adaptation_policy: Literal["original", "preserve-member-attribution"]


@dataclass(frozen=True)
class ProvenanceRecord:
    id: str
    canonical_source_url: str
    pinned_revision: str
    source_path: PurePosixPath
    source_tree_sha256: str
    copyright_holders: tuple[str, ...]
    spdx_expression: str
    license_file: PurePosixPath
    license_source_path: PurePosixPath
    license_file_sha256: str
    adaptation_type: Literal["original", "verified_adaptation", "verbatim"]
    changes: tuple[str, ...]
    nested_assets: tuple[NestedAssetRecord, ...]
    notice_output: PurePosixPath
    platform_evidence: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class AuthoringArtifact:
    name: str
    ownership: Literal["reference", "pack"]
    source_kind: Literal["bundled", "optional", "pack"]
    source_path: PurePosixPath
    install_path: PurePosixPath | None
    version: str
    author: str
    license: str
    provenance_ref: str
    host_os: tuple[Literal["linux", "macos", "windows"], ...]
    platform_evidence: tuple[str, ...]
    required_toolsets: tuple[str, ...]
    optional_toolsets: tuple[str, ...] = field(default_factory=tuple, kw_only=True)


@dataclass(frozen=True)
class AuthoringMember(AuthoringArtifact):
    role: Literal["required", "optional"]
    default: Literal["enabled", "disabled"]


@dataclass(frozen=True)
class ExcludedCandidate:
    name: str
    audited_source_path: PurePosixPath
    audited_tree_sha256: str
    disposition: Literal["quarantined", "reference_only"]
    gate_issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class AuthoringManifest:
    schema_version: int
    id: str
    name: str
    version: str
    fabric_requires: str
    summary: str
    router: AuthoringArtifact
    members: tuple[AuthoringMember, ...]
    excluded_candidates: tuple[ExcludedCandidate, ...]
    permissions: PackPermissions
    provenance: PackProvenance
    source_file: Path
    source_file_sha256: str


@dataclass(frozen=True)
class CompiledArtifact:
    authoring: AuthoringArtifact
    source_tree_sha256: str
    provenance: ProvenanceRecord
    provenance_file_sha256: str
    notice_file_sha256: str
    platform_evidence: tuple[PlatformEvidenceRecord, ...]


@dataclass(frozen=True)
class CompiledMember:
    authoring: AuthoringMember
    source_tree_sha256: str
    provenance: ProvenanceRecord
    provenance_file_sha256: str
    notice_file_sha256: str
    platform_evidence: tuple[PlatformEvidenceRecord, ...]


@dataclass(frozen=True)
class CompiledManifest:
    authoring: AuthoringManifest
    source_manifest_path: PurePosixPath
    router: CompiledArtifact
    members: tuple[CompiledMember, ...]
    excluded_candidates: tuple[ExcludedCandidate, ...]
    manifest_sha256: str
    notice_tree_sha256: str
    release_tree_sha256: str


@total_ordering
@dataclass(frozen=True, eq=False)
class _SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...]
    raw: str

    @property
    def precedence_key(self) -> tuple[int, int, int, tuple[str, ...]]:
        """Return SemVer precedence, which deliberately ignores build metadata."""

        return (self.major, self.minor, self.patch, self.prerelease)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, _SemVer):
            return NotImplemented
        left_core = (self.major, self.minor, self.patch)
        right_core = (other.major, other.minor, other.patch)
        if left_core != right_core:
            return left_core < right_core
        if not self.prerelease:
            return False if not other.prerelease else False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_numeric = left.isdigit()
            right_numeric = right.isdigit()
            if left_numeric and right_numeric:
                return int(left) < int(right)
            if left_numeric != right_numeric:
                return left_numeric
            return left < right
        return len(self.prerelease) < len(other.prerelease)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _SemVer):
            return False
        return self.precedence_key == other.precedence_key


def canonical_json_bytes(value: Any) -> bytes:
    """Return the one accepted JSON byte representation for a catalog."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _reject_json_constant(value: str) -> None:
    raise CapabilityPackValidationError(
        PackIssueCode.CATALOG_NOT_CANONICAL,
        f"non-finite JSON number is forbidden: {value}",
    )


def _sha256_pack_tree(path: Path) -> str:
    return sha256_tree(
        path,
        max_file_bytes=MAX_COMPILED_BYTES,
        max_total_bytes=4 * MAX_COMPILED_BYTES,
    )


def _sha256_evidence_file(path: Path) -> str:
    raw = _read_bytes_bounded(
        path,
        limit=MAX_COMPILED_BYTES,
        code=PackIssueCode.SOURCE_NOT_REGULAR,
        label="evidence file",
    )
    return hashlib.sha256(raw).hexdigest()


def _sha256_path_records(records: Sequence[tuple[PurePosixPath, str]]) -> str:
    digest = hashlib.sha256()
    for relative, file_digest in sorted(records, key=lambda item: item[0].as_posix()):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _read_bytes_bounded(
    path: Path,
    *,
    limit: int,
    code: PackIssueCode,
    label: str,
) -> bytes:
    try:
        if is_path_redirect(path):
            raise CapabilityPackValidationError(
                PackIssueCode.PATH_UNSAFE,
                f"{label} must not be a symlink or reparse point",
                location=path,
            )
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise CapabilityPackValidationError(
                PackIssueCode.SOURCE_NOT_REGULAR,
                f"{label} must be a regular file",
                location=path,
            )
        if before.st_size > limit:
            raise CapabilityPackValidationError(
                code,
                f"{label} exceeds {limit} bytes",
                location=path,
            )
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (
                before.st_dev,
                before.st_ino,
            ) != (opened.st_dev, opened.st_ino):
                raise CapabilityPackValidationError(
                    PackIssueCode.SOURCE_NOT_REGULAR,
                    f"{label} changed or is not a regular file",
                    location=path,
                )
            chunks: list[bytes] = []
            remaining = limit + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
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
                raise CapabilityPackValidationError(
                    PackIssueCode.PATH_UNSAFE,
                    f"{label} changed while being read",
                    location=path,
                )
        finally:
            os.close(descriptor)
        final = path.lstat()
        if (
            opened.st_dev,
            opened.st_ino,
            after.st_size,
            getattr(after, "st_mtime_ns", None),
            getattr(after, "st_ctime_ns", None),
        ) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            getattr(final, "st_mtime_ns", None),
            getattr(final, "st_ctime_ns", None),
        ):
            raise CapabilityPackValidationError(
                PackIssueCode.PATH_UNSAFE,
                f"{label} changed identity while being read",
                location=path,
            )
    except CapabilityPackValidationError:
        raise
    except OSError as exc:
        raise CapabilityPackValidationError(
            code,
            f"cannot read {label}: {exc}",
            location=path,
        ) from exc
    if len(raw) > limit:
        raise CapabilityPackValidationError(
            code,
            f"{label} exceeds {limit} bytes",
            location=path,
        )
    return raw


def _parse_yaml_mapping(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.YAML_INVALID,
            "YAML must be UTF-8",
            location=path,
        ) from exc
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    try:
        value = yaml.load(text)
    except DuplicateKeyError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.DUPLICATE_KEY,
            "duplicate YAML mapping key",
            location=path,
        ) from exc
    except YAMLError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.YAML_INVALID,
            f"invalid YAML: {exc}",
            location=path,
        ) from exc
    except (ValueError, RecursionError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.YAML_INVALID,
            f"invalid or oversized YAML scalar/structure: {exc}",
            location=path,
        ) from exc
    if not isinstance(value, dict):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            "top-level YAML value must be a mapping",
            location=path,
        )
    if not all(isinstance(key, str) for key in value):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            "all YAML mapping keys must be strings",
            location=path,
        )
    return value


def _load_yaml_mapping_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = _read_bytes_bounded(
        path,
        limit=MAX_AUTHORING_BYTES,
        code=PackIssueCode.YAML_INVALID,
        label="YAML",
    )
    return _parse_yaml_mapping(raw, path), hashlib.sha256(raw).hexdigest()


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    return _load_yaml_mapping_snapshot(path)[0]


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must be a string-keyed mapping",
        )
    return value


def _sequence(value: Any, field_name: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must be a list",
        )
    return value


def _exact_fields(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    field_name: str,
) -> None:
    unknown = sorted(set(value) - required - optional)
    if unknown:
        raise CapabilityPackValidationError(
            PackIssueCode.UNKNOWN_FIELD,
            f"{field_name} has unknown field(s): {', '.join(unknown)}",
        )
    missing = sorted(required - set(value))
    if missing:
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} is missing field(s): {', '.join(missing)}",
        )


def _string(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must be a non-empty string",
        )
    if value != value.strip() or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} contains surrounding whitespace or control characters",
        )
    return value


def _frontmatter_text(value: Any, field_name: str) -> str:
    """Validate human-readable YAML text without rejecting block scalars."""

    if not isinstance(value, str) or not value.strip():
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must be non-empty text",
        )
    if any(
        (ord(char) < 32 and char not in {"\n", "\t"}) or ord(char) == 127
        for char in value
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} contains an unsafe control character",
        )
    return value


def _portable_path_parts(path: PurePosixPath) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in path.parts)


def _portable_paths_overlap(left: PurePosixPath, right: PurePosixPath) -> bool:
    left_parts = _portable_path_parts(left)
    right_parts = _portable_path_parts(right)
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def _resolved_paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _literal(value: Any, allowed: frozenset[str], field_name: str) -> str:
    result = _string(value, field_name)
    if result not in allowed:
        choices = ", ".join(sorted(allowed))
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must be one of: {choices}",
        )
    return result


def _string_tuple(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = True,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...]:
    result = tuple(
        _string(item, f"{field_name}[]") for item in _sequence(value, field_name)
    )
    if not allow_empty and not result:
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must not be empty",
        )
    if len({item.casefold() for item in result}) != len(result):
        raise CapabilityPackValidationError(
            PackIssueCode.DUPLICATE_ID,
            f"{field_name} contains duplicate values",
        )
    if pattern is not None:
        invalid = [item for item in result if pattern.fullmatch(item) is None]
        if invalid:
            raise CapabilityPackValidationError(
                PackIssueCode.TYPE_INVALID,
                f"{field_name} contains invalid value(s): {', '.join(invalid)}",
            )
    return result


def _path(value: Any, field_name: str) -> PurePosixPath:
    raw = _string(value, field_name)
    try:
        return PurePosixPath(normalize_relative_path(raw, field=field_name))
    except (OSError, ValueError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.PATH_UNSAFE,
            str(exc),
        ) from exc


def _path_tuple(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = True,
) -> tuple[PurePosixPath, ...]:
    result = tuple(
        _path(item, f"{field_name}[{index}]")
        for index, item in enumerate(_sequence(value, field_name))
    )
    if not allow_empty and not result:
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must not be empty",
        )
    identities = [item.as_posix().casefold() for item in result]
    if len(set(identities)) != len(identities):
        raise CapabilityPackValidationError(
            PackIssueCode.DUPLICATE_ID,
            f"{field_name} contains duplicate canonical paths",
        )
    return result


def _sha256(value: Any, field_name: str, *, allow_zero: bool = False) -> str:
    result = _string(value, field_name)
    if _SHA256_RE.fullmatch(result) is None or (
        not allow_zero and set(result) == {"0"}
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must be a non-zero lowercase SHA-256 digest",
        )
    return result


def _semver(value: Any, field_name: str) -> _SemVer:
    raw = _string(value, field_name)
    if len(raw) > 128:
        raise CapabilityPackValidationError(
            PackIssueCode.VERSION_INVALID,
            f"{field_name} exceeds the 128-character version limit",
        )
    match = _SEMVER_RE.fullmatch(raw)
    if match is None:
        raise CapabilityPackValidationError(
            PackIssueCode.VERSION_INVALID,
            f"{field_name} must be an exact SemVer 2.0.0 version",
        )
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
    try:
        return _SemVer(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            prerelease,
            raw,
        )
    except ValueError as exc:  # defensive for interpreter integer limits
        raise CapabilityPackValidationError(
            PackIssueCode.VERSION_INVALID,
            f"{field_name} contains an oversized numeric identifier",
        ) from exc


def _pack_id(value: Any, field_name: str) -> str:
    result = _string(value, field_name)
    segments = result.split(".")
    if len(segments) < 2 or any(
        _NAME_RE.fullmatch(segment) is None for segment in segments
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must contain two or more canonical dot-separated segments",
        )
    return result


def _specifier(value: Any, field_name: str) -> str:
    raw = _string(value, field_name)
    try:
        parsed = SpecifierSet(raw)
    except InvalidSpecifier as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.SPECIFIER_INVALID,
            f"{field_name} is not a valid version constraint",
        ) from exc
    if not str(parsed):
        raise CapabilityPackValidationError(
            PackIssueCode.SPECIFIER_INVALID,
            f"{field_name} must not be an unconstrained empty specifier",
        )
    return raw


def _spdx(value: Any, field_name: str) -> str:
    raw = _string(value, field_name)
    try:
        return str(canonicalize_license_expression(raw))
    except InvalidLicenseExpression as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.SPDX_INVALID,
            f"{field_name} is not a valid SPDX expression",
        ) from exc


def _immutable_pin(value: Any, field_name: str) -> str:
    raw = _string(value, field_name)
    git_pin = _GIT_REVISION_RE.fullmatch(raw) is not None and set(raw) != {"0"}
    release_digest = (
        raw.startswith("sha256:") and _SHA256_RE.fullmatch(raw[7:]) is not None
    )
    if release_digest and set(raw[7:]) == {"0"}:
        release_digest = False
    if not git_pin and not release_digest:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_PIN_INVALID,
            f"{field_name} must be an exact non-zero 40-hex Git revision or sha256:<digest>",
        )
    return raw


def _canonical_source_url(value: Any, field_name: str) -> str:
    raw = _string(value, field_name)
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"{field_name} is not a valid canonical HTTPS URL",
        ) from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"{field_name} must be a canonical HTTPS URL without credentials, query, or fragment",
        )
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"{field_name} contains an invalid hostname",
        ) from exc
    if ascii_host.endswith("."):
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"{field_name} hostname must not have a trailing dot",
        )

    if ":" in ascii_host:
        try:
            canonical_host = f"[{ipaddress.IPv6Address(ascii_host).compressed}]"
        except ipaddress.AddressValueError as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                f"{field_name} contains an invalid IPv6 hostname",
            ) from exc
    else:
        try:
            canonical_host = str(ipaddress.IPv4Address(ascii_host))
        except ipaddress.AddressValueError:
            host_component = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
            labels = ascii_host.split(".")
            if len(ascii_host) > 253 or any(
                host_component.fullmatch(label) is None for label in labels
            ):
                raise CapabilityPackValidationError(
                    PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                    f"{field_name} contains an invalid hostname",
                )
            canonical_host = ascii_host

    path = parsed.path
    if path in {"", "/"}:
        canonical_path = ""
    else:
        allowed_path = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@/-]+$")
        path_segments = path.split("/")[1:]
        if (
            not path.startswith("/")
            or path.endswith("/")
            or "//" in path
            or "\\" in path
            or "%" in path
            or unicodedata.normalize("NFC", path) != path
            or any(segment in {"", ".", ".."} for segment in path_segments)
            or allowed_path.fullmatch(path) is None
        ):
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                f"{field_name} path is not in canonical URL form",
            )
        canonical_path = path

    canonical_port = "" if port in {None, 443} else f":{port}"
    canonical = f"https://{canonical_host}{canonical_port}{canonical_path}"
    if raw != canonical:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"{field_name} must use the canonical spelling {canonical!r}",
        )
    return canonical


def _source_repository_slug(value: Any, field_name: str) -> str:
    raw = _string(value, field_name)
    parts = raw.split("/")
    component = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
    if len(parts) != 2 or any(component.fullmatch(part) is None for part in parts):
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} must be an owner/repository slug",
        )
    return raw


def _parse_artifact(value: Any, field_name: str, *, member: bool) -> AuthoringArtifact:
    data = _mapping(value, field_name)
    required = {
        "name",
        "version",
        "ownership",
        "source_kind",
        "source_path",
        "install_path",
        "author",
        "license",
        "provenance_ref",
        "host_os",
        "platform_evidence",
        "required_toolsets",
    }
    if member:
        required |= {"role", "default"}
    _exact_fields(
        data,
        required=frozenset(required),
        optional=frozenset({"optional_toolsets"}),
        field_name=field_name,
    )
    name = _string(data["name"], f"{field_name}.name")
    if _NAME_RE.fullmatch(name) is None:
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name}.name is not canonical",
        )
    version = _semver(data["version"], f"{field_name}.version").raw
    ownership = _literal(
        data["ownership"], frozenset({"reference", "pack"}), f"{field_name}.ownership"
    )
    source_kind = _literal(
        data["source_kind"],
        frozenset({"bundled", "optional", "pack"}),
        f"{field_name}.source_kind",
    )
    source_path = _path(data["source_path"], f"{field_name}.source_path")
    raw_install = data["install_path"]
    if raw_install is None:
        install_path = None
    else:
        raw_install_string = _string(raw_install, f"{field_name}.install_path")
        try:
            install_path = PurePosixPath(
                normalize_skill_install_path(raw_install_string, name)
            )
        except (OSError, ValueError) as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.PATH_UNSAFE,
                str(exc),
            ) from exc
    if ownership == "pack" and (source_kind != "pack" or install_path is None):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            f"{field_name}: pack-owned artifacts require source_kind=pack and an install_path",
        )
    if ownership == "reference" and (source_kind == "pack" or install_path is not None):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            f"{field_name}: references must use bundled/optional source and install_path=null",
        )
    host_os = _string_tuple(data["host_os"], f"{field_name}.host_os")
    invalid_hosts = sorted(set(host_os) - _HOST_OS)
    if invalid_hosts:
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name}.host_os contains unsupported values: {', '.join(invalid_hosts)}",
        )
    platform_evidence_paths = _path_tuple(
        data["platform_evidence"],
        f"{field_name}.platform_evidence",
    )
    platform_evidence = tuple(item.as_posix() for item in platform_evidence_paths)
    required_toolsets = _string_tuple(
        data["required_toolsets"],
        f"{field_name}.required_toolsets",
        pattern=_TOOLSET_RE,
    )
    optional_toolsets = _string_tuple(
        data.get("optional_toolsets", []),
        f"{field_name}.optional_toolsets",
        pattern=_TOOLSET_RE,
    )
    if set(required_toolsets) & set(optional_toolsets):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            f"{field_name} repeats a toolset as both required and optional",
        )
    common: dict[str, Any] = {
        "name": name,
        "ownership": ownership,
        "source_kind": source_kind,
        "source_path": source_path,
        "install_path": install_path,
        "version": version,
        "author": _string(data["author"], f"{field_name}.author"),
        "license": _spdx(data["license"], f"{field_name}.license"),
        "provenance_ref": _string(
            data["provenance_ref"], f"{field_name}.provenance_ref"
        ),
        "host_os": host_os,
        "platform_evidence": platform_evidence,
        "required_toolsets": required_toolsets,
        "optional_toolsets": optional_toolsets,
    }
    if not member:
        return AuthoringArtifact(**common)
    return AuthoringMember(
        **common,
        role=_literal(
            data["role"], frozenset({"required", "optional"}), f"{field_name}.role"
        ),
        default=_literal(
            data["default"], frozenset({"enabled", "disabled"}), f"{field_name}.default"
        ),
    )


def _parse_excluded_candidate(value: Any, field_name: str) -> ExcludedCandidate:
    data = _mapping(value, field_name)
    _exact_fields(
        data,
        required=frozenset({
            "name",
            "audited_source_path",
            "audited_tree_sha256",
            "disposition",
            "gate_issue_codes",
        }),
        field_name=field_name,
    )
    name = _string(data["name"], f"{field_name}.name")
    if _NAME_RE.fullmatch(name) is None:
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name}.name is not canonical",
        )
    return ExcludedCandidate(
        name=name,
        audited_source_path=_path(
            data["audited_source_path"], f"{field_name}.audited_source_path"
        ),
        audited_tree_sha256=_sha256(
            data["audited_tree_sha256"], f"{field_name}.audited_tree_sha256"
        ),
        disposition=_literal(
            data["disposition"],
            frozenset({"quarantined", "reference_only"}),
            f"{field_name}.disposition",
        ),
        gate_issue_codes=_string_tuple(
            data["gate_issue_codes"],
            f"{field_name}.gate_issue_codes",
            allow_empty=False,
            pattern=_ISSUE_CODE_RE,
        ),
    )


def load_authoring_manifest(path: Path) -> AuthoringManifest:
    """Parse one strict authoring manifest without resolving its sources."""

    data, source_file_sha256 = _load_yaml_mapping_snapshot(path)
    _exact_fields(
        data,
        required=frozenset({
            "schema_version",
            "id",
            "name",
            "version",
            "fabric_requires",
            "summary",
            "router",
            "members",
            "excluded_candidates",
            "permissions",
            "provenance",
        }),
        field_name="manifest",
    )
    if data["schema_version"] != SCHEMA_VERSION or isinstance(
        data["schema_version"], bool
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.SCHEMA_VERSION_UNSUPPORTED,
            f"manifest schema_version must be {SCHEMA_VERSION}",
            location=path,
        )
    pack_id = _pack_id(data["id"], "manifest.id")
    version = _semver(data["version"], "manifest.version").raw
    router = _parse_artifact(data["router"], "manifest.router", member=False)
    members = tuple(
        _parse_artifact(item, f"manifest.members[{index}]", member=True)
        for index, item in enumerate(_sequence(data["members"], "manifest.members"))
    )
    excluded = tuple(
        _parse_excluded_candidate(item, f"manifest.excluded_candidates[{index}]")
        for index, item in enumerate(
            _sequence(data["excluded_candidates"], "manifest.excluded_candidates")
        )
    )
    names = [
        router.name,
        *(member.name for member in members),
        *(item.name for item in excluded),
    ]
    if len({name.casefold() for name in names}) != len(names):
        raise CapabilityPackValidationError(
            PackIssueCode.DUPLICATE_MEMBER,
            "router, members, and excluded candidates must have distinct names",
            location=path,
        )
    install_paths = [
        (artifact.name, artifact.install_path)
        for artifact in (router, *members)
        if artifact.install_path is not None
    ]
    for (left_name, left), (right_name, right) in combinations(install_paths, 2):
        if _portable_paths_overlap(left, right):
            raise CapabilityPackValidationError(
                PackIssueCode.DUPLICATE_INSTALL_PATH,
                "pack-owned install paths must not overlap: "
                f"{left_name}={left} and {right_name}={right}",
                location=path,
            )
    if "skills" not in router.required_toolsets:
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            "router.required_toolsets must include skills",
            location=path,
        )
    for member in members:
        if member.role == "required" and member.default != "enabled":
            raise CapabilityPackValidationError(
                PackIssueCode.INVARIANT_VIOLATION,
                f"required member {member.name!r} must be enabled by default",
                location=path,
            )
    permissions_data = _mapping(data["permissions"], "manifest.permissions")
    _exact_fields(
        permissions_data,
        required=frozenset({
            "required_toolsets",
            "optional_toolsets",
            "secrets",
            "network",
        }),
        field_name="manifest.permissions",
    )
    permissions = PackPermissions(
        required_toolsets=_string_tuple(
            permissions_data["required_toolsets"],
            "manifest.permissions.required_toolsets",
            pattern=_TOOLSET_RE,
        ),
        optional_toolsets=_string_tuple(
            permissions_data["optional_toolsets"],
            "manifest.permissions.optional_toolsets",
            pattern=_TOOLSET_RE,
        ),
        secrets=_string_tuple(
            permissions_data["secrets"], "manifest.permissions.secrets"
        ),
        network=_literal(
            permissions_data["network"],
            frozenset({"inherited"}),
            "manifest.permissions.network",
        ),
    )
    required_members = tuple(member for member in members if member.role == "required")
    optional_members = tuple(member for member in members if member.role == "optional")
    all_required = set().union(
        *(set(item.required_toolsets) for item in (router, *required_members))
    )
    all_optional = (
        set().union(
            *(set(item.optional_toolsets) for item in (router, *members)),
            *(set(item.required_toolsets) for item in optional_members),
        )
        - all_required
    )
    if not all_required.issubset(set(permissions.required_toolsets)):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            "pack permissions omit an artifact's required toolset",
            location=path,
        )
    if not all_optional.issubset(set(permissions.optional_toolsets)):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            "pack permissions omit an artifact's optional toolset",
            location=path,
        )
    if set(permissions.required_toolsets) & set(permissions.optional_toolsets):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            "pack permissions repeat toolsets as required and optional",
            location=path,
        )
    provenance_data = _mapping(data["provenance"], "manifest.provenance")
    _exact_fields(
        provenance_data,
        required=frozenset({"publisher", "source_repository", "adaptation_policy"}),
        field_name="manifest.provenance",
    )
    provenance = PackProvenance(
        publisher=_string(
            provenance_data["publisher"], "manifest.provenance.publisher"
        ),
        source_repository=_string(
            _source_repository_slug(
                provenance_data["source_repository"],
                "manifest.provenance.source_repository",
            ),
            "manifest.provenance.source_repository",
        ),
        adaptation_policy=_literal(
            provenance_data["adaptation_policy"],
            frozenset({"original", "preserve-member-attribution"}),
            "manifest.provenance.adaptation_policy",
        ),
    )
    return AuthoringManifest(
        schema_version=SCHEMA_VERSION,
        id=pack_id,
        name=_string(data["name"], "manifest.name"),
        version=version,
        fabric_requires=_specifier(data["fabric_requires"], "manifest.fabric_requires"),
        summary=_string(data["summary"], "manifest.summary"),
        router=router,
        members=members,
        excluded_candidates=excluded,
        permissions=permissions,
        provenance=provenance,
        source_file=path,
        source_file_sha256=source_file_sha256,
    )


def _parse_nested_asset(value: Any, field_name: str) -> NestedAssetRecord:
    data = _mapping(value, field_name)
    _exact_fields(
        data,
        required=frozenset({
            "path",
            "canonical_source_url",
            "pinned_revision",
            "source_path",
            "copyright_holders",
            "spdx_expression",
            "license_file",
            "license_source_path",
            "license_file_sha256",
            "sha256",
        }),
        field_name=field_name,
    )
    return NestedAssetRecord(
        path=_path(data["path"], f"{field_name}.path"),
        canonical_source_url=_canonical_source_url(
            data["canonical_source_url"],
            f"{field_name}.canonical_source_url",
        ),
        pinned_revision=_immutable_pin(
            data["pinned_revision"], f"{field_name}.pinned_revision"
        ),
        source_path=_path(data["source_path"], f"{field_name}.source_path"),
        copyright_holders=_string_tuple(
            data["copyright_holders"],
            f"{field_name}.copyright_holders",
            allow_empty=False,
        ),
        spdx_expression=_spdx(data["spdx_expression"], f"{field_name}.spdx_expression"),
        license_file=_path(data["license_file"], f"{field_name}.license_file"),
        license_source_path=_path(
            data["license_source_path"], f"{field_name}.license_source_path"
        ),
        license_file_sha256=_sha256(
            data["license_file_sha256"], f"{field_name}.license_file_sha256"
        ),
        sha256=_sha256(data["sha256"], f"{field_name}.sha256"),
    )


def _parse_provenance_record(
    record_id: str, value: Any, field_name: str
) -> ProvenanceRecord:
    data = _mapping(value, field_name)
    _exact_fields(
        data,
        required=frozenset({
            "canonical_source_url",
            "pinned_revision",
            "source_path",
            "source_tree_sha256",
            "copyright_holders",
            "spdx_expression",
            "license_file",
            "license_source_path",
            "license_file_sha256",
            "adaptation_type",
            "changes",
            "nested_assets",
            "notice_output",
            "platform_evidence",
        }),
        field_name=field_name,
    )
    if _NAME_RE.fullmatch(record_id) is None:
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            f"{field_name} ID is not canonical",
        )
    adaptation_type = _literal(
        data["adaptation_type"],
        frozenset({"original", "verified_adaptation", "verbatim"}),
        f"{field_name}.adaptation_type",
    )
    changes = _string_tuple(data["changes"], f"{field_name}.changes")
    if adaptation_type != "original" and not changes:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"{field_name}.changes must describe every adaptation or verbatim import",
        )
    if adaptation_type == "original" and changes:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"{field_name}.changes must be empty when adaptation_type is original",
        )
    nested_assets = tuple(
        _parse_nested_asset(item, f"{field_name}.nested_assets[{index}]")
        for index, item in enumerate(
            _sequence(data["nested_assets"], f"{field_name}.nested_assets")
        )
    )
    if len({item.path.as_posix().casefold() for item in nested_assets}) != len(
        nested_assets
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.DUPLICATE_ID,
            f"{field_name}.nested_assets contains duplicate paths",
        )
    return ProvenanceRecord(
        id=record_id,
        canonical_source_url=_canonical_source_url(
            data["canonical_source_url"],
            f"{field_name}.canonical_source_url",
        ),
        pinned_revision=_immutable_pin(
            data["pinned_revision"], f"{field_name}.pinned_revision"
        ),
        source_path=_path(data["source_path"], f"{field_name}.source_path"),
        source_tree_sha256=_sha256(
            data["source_tree_sha256"], f"{field_name}.source_tree_sha256"
        ),
        copyright_holders=_string_tuple(
            data["copyright_holders"],
            f"{field_name}.copyright_holders",
            allow_empty=False,
        ),
        spdx_expression=_spdx(data["spdx_expression"], f"{field_name}.spdx_expression"),
        license_file=_path(data["license_file"], f"{field_name}.license_file"),
        license_source_path=_path(
            data["license_source_path"], f"{field_name}.license_source_path"
        ),
        license_file_sha256=_sha256(
            data["license_file_sha256"],
            f"{field_name}.license_file_sha256",
        ),
        adaptation_type=adaptation_type,
        changes=changes,
        nested_assets=nested_assets,
        notice_output=_path(data["notice_output"], f"{field_name}.notice_output"),
        platform_evidence=_path_tuple(
            data["platform_evidence"],
            f"{field_name}.platform_evidence",
        ),
    )


def _load_provenance_file(path: Path) -> tuple[dict[str, ProvenanceRecord], str]:
    data, file_sha256 = _load_yaml_mapping_snapshot(path)
    _exact_fields(
        data,
        required=frozenset({"schema_version", "records"}),
        field_name="provenance",
    )
    if data["schema_version"] != SCHEMA_VERSION or isinstance(
        data["schema_version"], bool
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.SCHEMA_VERSION_UNSUPPORTED,
            f"provenance schema_version must be {SCHEMA_VERSION}",
            location=path,
        )
    records_data = _mapping(data["records"], "provenance.records")
    result: dict[str, ProvenanceRecord] = {}
    for record_id in sorted(records_data):
        canonical_id = _string(record_id, "provenance.records key")
        if canonical_id.casefold() in {key.casefold() for key in result}:
            raise CapabilityPackValidationError(
                PackIssueCode.DUPLICATE_ID,
                f"duplicate provenance record ID: {canonical_id}",
                location=path,
            )
        result[canonical_id] = _parse_provenance_record(
            canonical_id,
            records_data[record_id],
            f"provenance.records.{canonical_id}",
        )
    return result, file_sha256


def _resolve_existing(
    root: Path,
    relative: PurePosixPath,
    *,
    directory: bool,
    missing_code: PackIssueCode = PackIssueCode.SOURCE_MISSING,
) -> Path:
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.lstat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise CapabilityPackValidationError(
            missing_code,
            "referenced path does not exist",
            location=candidate,
        ) from exc
    except OSError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.PATH_UNSAFE,
            f"cannot inspect referenced path: {exc}",
            location=candidate,
        ) from exc
    try:
        path = resolve_relative_path(root, relative.as_posix(), must_exist=True)
    except (OSError, ValueError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.PATH_UNSAFE,
            str(exc),
            location=root / Path(*relative.parts),
        ) from exc
    if directory and not path.is_dir():
        raise CapabilityPackValidationError(
            PackIssueCode.SOURCE_MISSING,
            "expected a directory",
            location=path,
        )
    if not directory and not path.is_file():
        raise CapabilityPackValidationError(
            PackIssueCode.SOURCE_NOT_REGULAR,
            "expected a regular file",
            location=path,
        )
    return path


def _resolve_provenance_ref(
    artifact: AuthoringArtifact,
    release_root: Path,
    cache: dict[Path, tuple[dict[str, ProvenanceRecord], str]],
) -> tuple[ProvenanceRecord, str]:
    if artifact.provenance_ref.count("#") != 1:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_REF_INVALID,
            f"{artifact.name}: provenance_ref must be relative/path.yaml#record-id",
        )
    raw_path, record_id = artifact.provenance_ref.split("#", 1)
    if not record_id or _NAME_RE.fullmatch(record_id) is None:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_REF_INVALID,
            f"{artifact.name}: provenance fragment is not canonical",
        )
    relative = _path(raw_path, f"{artifact.name}.provenance_ref")
    if relative.suffix not in {".yaml", ".yml"}:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_REF_INVALID,
            f"{artifact.name}: provenance_ref must name a YAML file",
        )
    path = _resolve_existing(
        release_root,
        relative,
        directory=False,
        missing_code=PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
    )
    snapshot = cache.get(path)
    if snapshot is None:
        snapshot = _load_provenance_file(path)
        cache[path] = snapshot
    records, file_sha256 = snapshot
    try:
        return records[record_id], file_sha256
    except KeyError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"{artifact.name}: provenance record {record_id!r} is missing",
            location=path,
        ) from exc


def _artifact_source_root(
    artifact: AuthoringArtifact,
    *,
    release_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
) -> Path:
    base = {
        "pack": release_root,
        "bundled": bundled_skills_root,
        "optional": optional_skills_root,
    }[artifact.source_kind]
    path = _resolve_existing(base, artifact.source_path, directory=True)
    skill_file = _resolve_existing(path, PurePosixPath("SKILL.md"), directory=False)
    _validate_skill_identity(skill_file, artifact.name)
    return path


def _validate_skill_identity(skill_file: Path, artifact_name: str) -> None:
    """Bind catalog identity to the slash-command identity in ``SKILL.md``."""

    raw = _read_bytes_bounded(
        skill_file,
        limit=MAX_AUTHORING_BYTES,
        code=PackIssueCode.YAML_INVALID,
        label="SKILL.md",
    )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.YAML_INVALID,
            "SKILL.md must be UTF-8",
            location=skill_file,
        ) from exc
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            "SKILL.md must start with YAML frontmatter",
            location=skill_file,
        )
    closing = normalized.find("\n---\n", 4)
    if closing < 0:
        raise CapabilityPackValidationError(
            PackIssueCode.YAML_INVALID,
            "SKILL.md frontmatter is not terminated",
            location=skill_file,
        )
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    try:
        frontmatter = yaml.load(normalized[4:closing])
    except DuplicateKeyError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.DUPLICATE_KEY,
            "SKILL.md frontmatter contains a duplicate key",
            location=skill_file,
        ) from exc
    except YAMLError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.YAML_INVALID,
            f"invalid SKILL.md frontmatter: {exc}",
            location=skill_file,
        ) from exc
    frontmatter_mapping = _mapping(frontmatter, "SKILL.md frontmatter")
    actual_name = _string(frontmatter_mapping.get("name"), "SKILL.md frontmatter.name")
    _frontmatter_text(
        frontmatter_mapping.get("description"),
        "SKILL.md frontmatter.description",
    )
    if actual_name != artifact_name:
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            f"SKILL.md name {actual_name!r} does not match catalog artifact {artifact_name!r}",
            location=skill_file,
        )
    body = normalized[closing + len("\n---\n") :].strip()
    if not body:
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            "SKILL.md must contain a non-empty instructional body",
            location=skill_file,
        )


def _git_environment() -> dict[str, str]:
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
    }
    if system_root := os.environ.get("SystemRoot"):
        environment["SystemRoot"] = system_root
    return environment


def _run_git(
    repository: Path,
    *arguments: str,
    max_output: int = MAX_COMPILED_BYTES,
) -> bytes:
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            completed = subprocess.run(
                ["git", "-C", str(repository), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                timeout=30,
                env=_git_environment(),
            )
            stdout_size = stdout.tell()
            stderr_size = stderr.tell()
            if stdout_size > max_output:
                raise CapabilityPackValidationError(
                    PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                    f"Git evidence output exceeds {max_output} bytes",
                    location=repository,
                )
            stdout.seek(0)
            output = stdout.read(max_output + 1)
            stderr.seek(0)
            error_output = stderr.read(min(stderr_size, 64 * 1024))
    except (OSError, subprocess.SubprocessError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"could not inspect pinned source repository: {exc}",
            location=repository,
        ) from exc
    if completed.returncode != 0:
        detail = error_output.decode("utf-8", errors="replace").strip()
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"pinned source lookup failed: {detail or 'git returned a failure'}",
            location=repository,
        )
    return output


def _git_source_tree_sha256(repository: Path, record: ProvenanceRecord) -> str:
    commit_type = _run_git(repository, "cat-file", "-t", record.pinned_revision).strip()
    if commit_type != b"commit":
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_PIN_INVALID,
            "pinned_revision must identify a Git commit object",
            location=repository,
        )
    object_spec = f"{record.pinned_revision}:{record.source_path.as_posix()}"
    object_type = _run_git(repository, "cat-file", "-t", object_spec).strip()
    if object_type != b"tree":
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            "pinned provenance source_path must identify a Git tree",
            location=repository,
        )
    listing = _run_git(
        repository,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        record.pinned_revision,
        "--",
        record.source_path.as_posix(),
    )
    prefix = record.source_path.as_posix().rstrip("/") + "/"
    records: list[tuple[PurePosixPath, str]] = []
    portable_paths: set[str] = set()
    total_bytes = 0
    raw_entries = [entry for entry in listing.split(b"\0") if entry]
    if len(raw_entries) > 10_000:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            "pinned provenance tree exceeds 10,000 entries",
            location=repository,
        )
    for raw_entry in raw_entries:
        try:
            header, raw_path = raw_entry.split(b"\t", 1)
            mode, object_kind, object_id = header.split(b" ", 2)
            full_path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                "pinned Git tree contains an unsupported path or entry",
                location=repository,
            ) from exc
        if object_kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                f"pinned source contains a redirect/submodule/non-file entry: {full_path}",
                location=repository,
            )
        if not full_path.startswith(prefix):
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                "Git returned a path outside the pinned source tree",
                location=repository,
            )
        raw_relative = full_path[len(prefix) :]
        relative = _path(raw_relative, "pinned Git source path")
        if relative.as_posix() != raw_relative:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                f"pinned Git path is not canonical/portable: {raw_relative!r}",
                location=repository,
            )
        portable_key = unicodedata.normalize("NFC", raw_relative).casefold()
        if portable_key in portable_paths:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                f"pinned Git tree has a cross-platform path collision: {raw_relative!r}",
                location=repository,
            )
        portable_paths.add(portable_key)
        object_id_string = object_id.decode("ascii")
        try:
            blob_size = int(
                _run_git(
                    repository,
                    "cat-file",
                    "-s",
                    object_id_string,
                    max_output=128,
                )
            )
        except ValueError as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                "Git returned an invalid blob size",
                location=repository,
            ) from exc
        if (
            blob_size > MAX_COMPILED_BYTES
            or total_bytes + blob_size > 4 * MAX_COMPILED_BYTES
        ):
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                "pinned provenance tree exceeds the compiler evidence-size limit",
                location=repository,
            )
        payload = _run_git(
            repository,
            "cat-file",
            "blob",
            object_id_string,
            max_output=blob_size,
        )
        total_bytes += len(payload)
        records.append((relative, hashlib.sha256(payload).hexdigest()))
    if not records:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            "pinned provenance source tree is empty",
            location=repository,
        )
    return _sha256_path_records(records)


def _normalized_git_remote(value: str) -> str:
    return value.strip().removesuffix("/").removesuffix(".git")


def _git_origin_urls(
    repository: Path,
    *,
    issue_code: PackIssueCode,
    label: str,
) -> frozenset[str]:
    raw = _run_git(repository, "remote", "get-url", "--all", "origin")
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise CapabilityPackValidationError(
            issue_code,
            f"{label} Git origin is not UTF-8",
            location=repository,
        ) from exc
    return frozenset(_normalized_git_remote(item) for item in lines if item.strip())


def _source_repository_entry(
    canonical_source_url: str,
    source_repositories: Mapping[str, Path | SourceRepository],
    *,
    issue_code: PackIssueCode,
) -> SourceRepository:
    value = source_repositories.get(canonical_source_url)
    if value is None:
        raise CapabilityPackValidationError(
            issue_code,
            f"no offline source repository was supplied for {canonical_source_url}",
        )
    if isinstance(value, SourceRepository):
        return SourceRepository(Path(value.root), value.trusted_ref)
    return SourceRepository(Path(value))


def _trusted_git_ref(value: str | None, canonical_source_url: str) -> str:
    if not isinstance(value, str):
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"Git source {canonical_source_url} requires an explicit trusted remote ref",
        )
    if (
        not value.startswith("refs/remotes/origin/")
        or value == "refs/remotes/origin/HEAD"
        or value != value.strip()
        or ".." in value
        or "@{" in value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            f"Git source {canonical_source_url} has an invalid trusted remote ref",
        )
    return value


def _verify_git_pin_reachable_from_trusted_ref(
    repository: Path,
    pinned_revision: str,
    trusted_ref: str,
) -> None:
    _run_git(repository, "check-ref-format", trusted_ref)
    object_id = _run_git(
        repository,
        "show-ref",
        "--verify",
        "--hash",
        trusted_ref,
    ).strip()
    if _GIT_REVISION_RE.fullmatch(object_id.decode("ascii", errors="ignore")) is None:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            "trusted canonical source ref does not resolve to one exact Git object",
            location=repository,
        )
    object_type = _run_git(repository, "cat-file", "-t", object_id.decode()).strip()
    if object_type != b"commit":
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            "trusted canonical source ref must resolve to a commit",
            location=repository,
        )
    _run_git(
        repository,
        "merge-base",
        "--is-ancestor",
        pinned_revision,
        object_id.decode(),
    )


def _verify_pinned_source(
    provenance: ProvenanceRecord,
    *,
    local_source_tree_sha256: str,
    source_repositories: Mapping[str, Path | SourceRepository],
) -> None:
    source_repository = _source_repository_entry(
        provenance.canonical_source_url,
        source_repositories,
        issue_code=PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
    )
    repository = source_repository.root
    if _GIT_REVISION_RE.fullmatch(provenance.pinned_revision):
        remote_urls = _git_origin_urls(
            Path(repository),
            issue_code=PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
            label="provenance source",
        )
        if _normalized_git_remote(provenance.canonical_source_url) not in remote_urls:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                "supplied Git object database origin does not match canonical_source_url",
                location=repository,
            )
        trusted_ref = _trusted_git_ref(
            source_repository.trusted_ref,
            provenance.canonical_source_url,
        )
        _verify_git_pin_reachable_from_trusted_ref(
            Path(repository), provenance.pinned_revision, trusted_ref
        )
        source_digest = _git_source_tree_sha256(Path(repository), provenance)
    else:
        repository_root = Path(repository)
        try:
            release_digest = _sha256_pack_tree(repository_root)
        except (OSError, ValueError) as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                f"cannot hash immutable non-Git release root: {exc}",
                location=repository_root,
            ) from exc
        if provenance.pinned_revision != f"sha256:{release_digest}":
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_PIN_INVALID,
                "non-Git pinned_revision does not match the supplied release root",
                location=repository_root,
            )
        source_root = _resolve_existing(
            repository_root,
            provenance.source_path,
            directory=True,
            missing_code=PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
        )
        try:
            source_digest = _sha256_pack_tree(source_root)
        except (OSError, ValueError) as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_EVIDENCE_MISSING,
                f"cannot hash immutable non-Git source: {exc}",
                location=source_root,
            ) from exc
    if source_digest != provenance.source_tree_sha256:
        raise CapabilityPackValidationError(
            PackIssueCode.DIGEST_MISMATCH,
            "pinned provenance source-tree digest does not match its record",
            location=repository,
        )
    if (
        provenance.adaptation_type in {"original", "verbatim"}
        and source_digest != local_source_tree_sha256
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.DIGEST_MISMATCH,
            f"{provenance.adaptation_type} content differs from its pinned source tree",
        )
    _verify_pinned_blob(
        canonical_source_url=provenance.canonical_source_url,
        pinned_revision=provenance.pinned_revision,
        source_path=provenance.license_source_path,
        expected_sha256=provenance.license_file_sha256,
        source_repositories=source_repositories,
        issue_code=PackIssueCode.LICENSE_EVIDENCE_MISSING,
        label=f"provenance {provenance.id} license",
    )


def _verify_pinned_blob(
    *,
    canonical_source_url: str,
    pinned_revision: str,
    source_path: PurePosixPath,
    expected_sha256: str,
    source_repositories: Mapping[str, Path | SourceRepository],
    issue_code: PackIssueCode,
    label: str,
) -> None:
    source_repository = _source_repository_entry(
        canonical_source_url,
        source_repositories,
        issue_code=issue_code,
    )
    repository = source_repository.root
    if _GIT_REVISION_RE.fullmatch(pinned_revision):
        remote_urls = _git_origin_urls(
            repository,
            issue_code=issue_code,
            label=label,
        )
        if _normalized_git_remote(canonical_source_url) not in remote_urls:
            raise CapabilityPackValidationError(
                issue_code,
                f"{label} Git origin does not match canonical_source_url",
                location=repository,
            )
        trusted_ref = _trusted_git_ref(
            source_repository.trusted_ref,
            canonical_source_url,
        )
        _verify_git_pin_reachable_from_trusted_ref(
            repository, pinned_revision, trusted_ref
        )
        if _run_git(repository, "cat-file", "-t", pinned_revision).strip() != b"commit":
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_PIN_INVALID,
                f"{label} pinned_revision must identify a Git commit",
                location=repository,
            )
        object_spec = f"{pinned_revision}:{source_path.as_posix()}"
        if _run_git(repository, "cat-file", "-t", object_spec).strip() != b"blob":
            raise CapabilityPackValidationError(
                issue_code,
                f"{label} source_path must identify a Git blob",
                location=repository,
            )
        listing = _run_git(
            repository,
            "ls-tree",
            "-z",
            pinned_revision,
            "--",
            source_path.as_posix(),
        )
        entries = [entry for entry in listing.split(b"\0") if entry]
        if len(entries) != 1:
            raise CapabilityPackValidationError(
                issue_code,
                f"{label} source_path did not resolve to exactly one Git entry",
                location=repository,
            )
        try:
            header, returned_path = entries[0].split(b"\t", 1)
            mode, object_kind, object_id = header.split(b" ", 2)
            returned_path_string = returned_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise CapabilityPackValidationError(
                issue_code,
                f"{label} Git entry is malformed",
                location=repository,
            ) from exc
        if (
            mode not in {b"100644", b"100755"}
            or object_kind != b"blob"
            or returned_path_string != source_path.as_posix()
        ):
            raise CapabilityPackValidationError(
                issue_code,
                f"{label} must be a regular Git file, not a symlink or submodule",
                location=repository,
            )
        try:
            object_id_string = object_id.decode("ascii")
            blob_size = int(
                _run_git(
                    repository,
                    "cat-file",
                    "-s",
                    object_id_string,
                    max_output=128,
                )
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise CapabilityPackValidationError(
                issue_code,
                f"{label} Git blob metadata is invalid",
                location=repository,
            ) from exc
        if blob_size > MAX_COMPILED_BYTES:
            raise CapabilityPackValidationError(
                issue_code,
                f"{label} source exceeds the evidence-size limit",
                location=repository,
            )
        payload = _run_git(
            repository,
            "cat-file",
            "blob",
            object_id_string,
            max_output=blob_size,
        )
        source_sha256 = hashlib.sha256(payload).hexdigest()
    else:
        try:
            release_digest = _sha256_pack_tree(repository)
        except (OSError, ValueError) as exc:
            raise CapabilityPackValidationError(
                issue_code,
                f"cannot hash immutable non-Git release root for {label}: {exc}",
                location=repository,
            ) from exc
        if pinned_revision != f"sha256:{release_digest}":
            raise CapabilityPackValidationError(
                PackIssueCode.PROVENANCE_PIN_INVALID,
                f"{label} non-Git pin does not match the supplied release root",
                location=repository,
            )
        source_file = _resolve_existing(
            repository,
            source_path,
            directory=False,
            missing_code=issue_code,
        )
        source_sha256 = _sha256_evidence_file(source_file)
    if source_sha256 != expected_sha256:
        raise CapabilityPackValidationError(
            PackIssueCode.DIGEST_MISMATCH,
            f"{label} differs from its pinned source",
            location=repository,
        )


def _verify_pinned_nested_asset(
    asset: NestedAssetRecord,
    *,
    source_repositories: Mapping[str, Path | SourceRepository],
) -> None:
    _verify_pinned_blob(
        canonical_source_url=asset.canonical_source_url,
        pinned_revision=asset.pinned_revision,
        source_path=asset.source_path,
        expected_sha256=asset.sha256,
        source_repositories=source_repositories,
        issue_code=PackIssueCode.NESTED_ASSET_EVIDENCE_MISSING,
        label=f"nested asset {asset.path}",
    )
    _verify_pinned_blob(
        canonical_source_url=asset.canonical_source_url,
        pinned_revision=asset.pinned_revision,
        source_path=asset.license_source_path,
        expected_sha256=asset.license_file_sha256,
        source_repositories=source_repositories,
        issue_code=PackIssueCode.LICENSE_EVIDENCE_MISSING,
        label=f"nested asset {asset.path} license",
    )


def _load_platform_evidence(
    path: Path,
    *,
    relative: PurePosixPath,
    artifact_name: str,
    release_root: Path,
    source_tree_sha256: str,
    provenance: ProvenanceRecord,
    trusted_verifier: PlatformEvidenceVerifier | None,
    require_trusted_verification: bool,
) -> PlatformEvidenceRecord:
    try:
        raw = _read_bytes_bounded(
            path,
            limit=MAX_AUTHORING_BYTES,
            code=PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            label="platform evidence",
        )
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_pairs,
            parse_constant=_reject_json_constant,
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
        CapabilityPackValidationError,
    ) as exc:
        if isinstance(exc, CapabilityPackValidationError):
            raise
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            f"invalid platform evidence JSON: {exc}",
            location=path,
        ) from exc
    evidence = _mapping(data, "platform evidence")
    _exact_fields(
        evidence,
        required=frozenset({
            "schema_version",
            "artifact",
            "source_tree_sha256",
            "results",
        }),
        field_name="platform evidence",
    )
    if evidence["schema_version"] != SCHEMA_VERSION or isinstance(
        evidence["schema_version"], bool
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            f"platform evidence schema_version must be {SCHEMA_VERSION}",
            location=path,
        )
    if _string(evidence["artifact"], "platform evidence.artifact") != artifact_name:
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            f"platform evidence is not bound to artifact {artifact_name!r}",
            location=path,
        )
    bound_source_digest = _sha256(
        evidence["source_tree_sha256"],
        "platform evidence.source_tree_sha256",
    )
    if bound_source_digest != source_tree_sha256:
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            "platform evidence is bound to a different source tree",
            location=path,
        )
    results = _sequence(evidence["results"], "platform evidence.results")
    if not results:
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            "platform evidence must contain at least one host result",
            location=path,
        )
    hosts: list[str] = []
    source_revisions: set[str] = set()
    check_evidence: dict[PurePosixPath, str] = {}
    for result_index, raw_result in enumerate(results):
        result = _mapping(raw_result, f"platform evidence.results[{result_index}]")
        _exact_fields(
            result,
            required=frozenset({
                "host_os",
                "runner",
                "source_revision",
                "run_url",
                "checks",
            }),
            field_name=f"platform evidence.results[{result_index}]",
        )
        host = _literal(
            result["host_os"],
            _HOST_OS,
            f"platform evidence.results[{result_index}].host_os",
        )
        if host in hosts:
            raise CapabilityPackValidationError(
                PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                f"duplicate platform host result: {host}",
                location=path,
            )
        hosts.append(host)
        revision = _immutable_pin(
            result["source_revision"],
            f"platform evidence.results[{result_index}].source_revision",
        )
        if revision != provenance.pinned_revision:
            raise CapabilityPackValidationError(
                PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                "platform result source_revision does not match original provenance pin",
                location=path,
            )
        source_revisions.add(revision)
        run_url = _canonical_source_url(
            result["run_url"],
            f"platform evidence.results[{result_index}].run_url",
        )
        expected_run_prefix = (
            _normalized_git_remote(provenance.canonical_source_url) + "/actions/runs/"
        )
        if not run_url.startswith(expected_run_prefix):
            raise CapabilityPackValidationError(
                PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                "platform result run_url is not an Actions run for the canonical source",
                location=path,
            )
        runner = _string(
            result["runner"],
            f"platform evidence.results[{result_index}].runner",
        )
        runner_prefix = {"linux": "ubuntu-", "macos": "macos-", "windows": "windows-"}[
            host
        ]
        if not runner.startswith(runner_prefix):
            raise CapabilityPackValidationError(
                PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                f"platform runner {runner!r} is not compatible with host_os={host}",
                location=path,
            )
        checks = _sequence(
            result["checks"],
            f"platform evidence.results[{result_index}].checks",
        )
        if not checks:
            raise CapabilityPackValidationError(
                PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                f"platform evidence for {host} must contain at least one passing check",
                location=path,
            )
        check_ids: set[str] = set()
        for check_index, raw_check in enumerate(checks):
            check_field = (
                f"platform evidence.results[{result_index}].checks[{check_index}]"
            )
            check = _mapping(raw_check, check_field)
            _exact_fields(
                check,
                required=frozenset({
                    "id",
                    "status",
                    "evidence_path",
                    "evidence_sha256",
                }),
                field_name=check_field,
            )
            check_id = _string(check["id"], f"{check_field}.id")
            if check_id.casefold() in check_ids:
                raise CapabilityPackValidationError(
                    PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                    f"duplicate platform check ID for {host}: {check_id}",
                    location=path,
                )
            check_ids.add(check_id.casefold())
            if check["status"] != "passed":
                raise CapabilityPackValidationError(
                    PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                    f"platform check {check_id!r} did not pass on {host}",
                    location=path,
                )
            evidence_relative = _path(
                check["evidence_path"], f"{check_field}.evidence_path"
            )
            evidence_file = _resolve_existing(
                release_root,
                evidence_relative,
                directory=False,
                missing_code=PackIssueCode.PLATFORM_EVIDENCE_MISSING,
            )
            expected_evidence_sha256 = _sha256(
                check["evidence_sha256"], f"{check_field}.evidence_sha256"
            )
            evidence_raw = _read_bytes_bounded(
                evidence_file,
                limit=MAX_COMPILED_BYTES,
                code=PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                label="platform check evidence",
            )
            if not evidence_raw:
                raise CapabilityPackValidationError(
                    PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                    f"platform check {check_id!r} has empty evidence",
                    location=evidence_file,
                )
            if hashlib.sha256(evidence_raw).hexdigest() != expected_evidence_sha256:
                raise CapabilityPackValidationError(
                    PackIssueCode.DIGEST_MISMATCH,
                    f"platform check {check_id!r} evidence digest drift",
                    location=evidence_file,
                )
            existing_evidence_digest = check_evidence.get(evidence_relative)
            if (
                existing_evidence_digest is not None
                and existing_evidence_digest != expected_evidence_sha256
            ):
                raise CapabilityPackValidationError(
                    PackIssueCode.DIGEST_MISMATCH,
                    "shared platform-check evidence path has contradictory digests",
                    location=evidence_file,
                )
            check_evidence[evidence_relative] = expected_evidence_sha256
    if require_trusted_verification:
        if trusted_verifier is None:
            raise CapabilityPackValidationError(
                PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                "platform evidence requires an explicit trusted attestation verifier",
                location=path,
            )
        try:
            trusted_verifier(path, raw, evidence)
        except CapabilityPackValidationError:
            raise
        except Exception as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                f"trusted platform attestation verification failed: {exc}",
                location=path,
            ) from exc
        verified_raw = _read_bytes_bounded(
            path,
            limit=MAX_AUTHORING_BYTES,
            code=PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            label="platform evidence after trusted verification",
        )
        if verified_raw != raw:
            raise CapabilityPackValidationError(
                PackIssueCode.PLATFORM_EVIDENCE_INVALID,
                "platform evidence changed during trusted verification",
                location=path,
            )
    return PlatformEvidenceRecord(
        path=relative,
        sha256=hashlib.sha256(raw).hexdigest(),
        source_tree_sha256=bound_source_digest,
        source_revisions=tuple(sorted(source_revisions)),
        verified_host_os=tuple(hosts),
        check_evidence=tuple(
            EvidenceFileRecord(path=evidence_path, sha256=evidence_sha256)
            for evidence_path, evidence_sha256 in sorted(
                check_evidence.items(), key=lambda item: item[0].as_posix()
            )
        ),
    )


def _validate_artifact_evidence(
    artifact: AuthoringArtifact,
    provenance: ProvenanceRecord,
    *,
    source_root: Path,
    release_root: Path,
    source_tree_sha256: str,
    source_repositories: Mapping[str, Path | SourceRepository],
    verify_upstream_sources: bool,
    platform_evidence_verifier: PlatformEvidenceVerifier | None,
) -> tuple[tuple[PlatformEvidenceRecord, ...], str]:
    if (
        _spdx(artifact.license, f"{artifact.name}.license")
        != provenance.spdx_expression
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.SPDX_INVALID,
            f"{artifact.name}: manifest license does not match provenance SPDX expression",
        )
    if provenance.adaptation_type != "original":
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            f"{artifact.name}: adapted/verbatim host admission requires a signed local-revision attestation",
        )
    license_path = _resolve_existing(
        release_root,
        provenance.license_file,
        directory=False,
        missing_code=PackIssueCode.LICENSE_EVIDENCE_MISSING,
    )
    license_raw = _read_bytes_bounded(
        license_path,
        limit=MAX_AUTHORING_BYTES,
        code=PackIssueCode.LICENSE_EVIDENCE_MISSING,
        label="license file",
    )
    if not license_raw:
        raise CapabilityPackValidationError(
            PackIssueCode.LICENSE_EVIDENCE_MISSING,
            f"{artifact.name}: license file must not be empty",
            location=license_path,
        )
    if hashlib.sha256(license_raw).hexdigest() != provenance.license_file_sha256:
        raise CapabilityPackValidationError(
            PackIssueCode.DIGEST_MISMATCH,
            f"{artifact.name}: license-file digest drift",
            location=license_path,
        )
    notice_path = _resolve_existing(
        release_root,
        provenance.notice_output,
        directory=False,
        missing_code=PackIssueCode.NOTICE_EVIDENCE_MISSING,
    )
    try:
        notice_raw = _read_bytes_bounded(
            notice_path,
            limit=MAX_AUTHORING_BYTES,
            code=PackIssueCode.NOTICE_EVIDENCE_MISSING,
            label="NOTICE",
        )
        notice_text = notice_raw.decode("utf-8")
    except (CapabilityPackValidationError, UnicodeError) as exc:
        if isinstance(exc, CapabilityPackValidationError):
            raise
        raise CapabilityPackValidationError(
            PackIssueCode.NOTICE_EVIDENCE_MISSING,
            f"{artifact.name}: NOTICE must be readable UTF-8 text",
            location=notice_path,
        ) from exc
    if not notice_text.strip():
        raise CapabilityPackValidationError(
            PackIssueCode.NOTICE_EVIDENCE_MISSING,
            f"{artifact.name}: NOTICE must not be empty",
            location=notice_path,
        )
    notice_tokens = (
        provenance.canonical_source_url,
        provenance.pinned_revision,
        provenance.spdx_expression,
        *provenance.copyright_holders,
        *(
            token
            for nested in provenance.nested_assets
            for token in (
                nested.canonical_source_url,
                nested.pinned_revision,
                nested.spdx_expression,
                *nested.copyright_holders,
            )
        ),
    )
    missing_notice_tokens = [
        token for token in notice_tokens if token not in notice_text
    ]
    if missing_notice_tokens:
        raise CapabilityPackValidationError(
            PackIssueCode.NOTICE_EVIDENCE_MISSING,
            f"{artifact.name}: NOTICE omits provenance/license attribution fields",
            location=notice_path,
        )
    for nested in provenance.nested_assets:
        nested_license = _resolve_existing(
            release_root,
            nested.license_file,
            directory=False,
            missing_code=PackIssueCode.LICENSE_EVIDENCE_MISSING,
        )
        nested_license_raw = _read_bytes_bounded(
            nested_license,
            limit=MAX_AUTHORING_BYTES,
            code=PackIssueCode.LICENSE_EVIDENCE_MISSING,
            label="nested-asset license file",
        )
        if not nested_license_raw:
            raise CapabilityPackValidationError(
                PackIssueCode.LICENSE_EVIDENCE_MISSING,
                f"nested asset {nested.path} license file must not be empty",
                location=nested_license,
            )
        if hashlib.sha256(nested_license_raw).hexdigest() != nested.license_file_sha256:
            raise CapabilityPackValidationError(
                PackIssueCode.DIGEST_MISMATCH,
                f"nested asset {nested.path} license-file digest drift",
                location=nested_license,
            )
        nested_path = _resolve_existing(
            source_root,
            nested.path,
            directory=False,
            missing_code=PackIssueCode.NESTED_ASSET_EVIDENCE_MISSING,
        )
        if _sha256_evidence_file(nested_path) != nested.sha256:
            raise CapabilityPackValidationError(
                PackIssueCode.DIGEST_MISMATCH,
                f"{artifact.name}: nested asset digest drift for {nested.path}",
                location=nested_path,
            )
        if verify_upstream_sources:
            _verify_pinned_nested_asset(
                nested,
                source_repositories=source_repositories,
            )
    declared_paths = tuple(
        _path(item, f"{artifact.name}.platform_evidence")
        for item in artifact.platform_evidence
    )
    if declared_paths != provenance.platform_evidence:
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_INVALID,
            f"{artifact.name}: manifest and provenance platform-evidence paths differ",
        )
    if not artifact.host_os or not declared_paths:
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_MISSING,
            f"{artifact.name}: admitted artifacts require checked host evidence",
        )
    records: list[PlatformEvidenceRecord] = []
    verified_hosts: set[str] = set()
    for relative in declared_paths:
        evidence_path = _resolve_existing(
            release_root,
            relative,
            directory=False,
            missing_code=PackIssueCode.PLATFORM_EVIDENCE_MISSING,
        )
        record = _load_platform_evidence(
            evidence_path,
            relative=relative,
            artifact_name=artifact.name,
            release_root=release_root,
            source_tree_sha256=source_tree_sha256,
            provenance=provenance,
            trusted_verifier=platform_evidence_verifier,
            require_trusted_verification=verify_upstream_sources,
        )
        records.append(record)
        verified_hosts.update(record.verified_host_os)
    if set(artifact.host_os) != verified_hosts:
        missing_hosts = sorted(set(artifact.host_os) - verified_hosts)
        extra_hosts = sorted(verified_hosts - set(artifact.host_os))
        detail = []
        if missing_hosts:
            detail.append(f"missing: {', '.join(missing_hosts)}")
        if extra_hosts:
            detail.append(f"undeclared: {', '.join(extra_hosts)}")
        raise CapabilityPackValidationError(
            PackIssueCode.PLATFORM_EVIDENCE_MISSING,
            f"{artifact.name}: host evidence does not exactly match host_os ({'; '.join(detail)})",
        )
    return (
        tuple(sorted(records, key=lambda item: item.path.as_posix())),
        hashlib.sha256(notice_raw).hexdigest(),
    )


def _compile_artifact(
    artifact: AuthoringArtifact,
    *,
    release_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    source_repositories: Mapping[str, Path | SourceRepository],
    verify_upstream_sources: bool,
    platform_evidence_verifier: PlatformEvidenceVerifier | None,
    provenance_cache: dict[Path, tuple[dict[str, ProvenanceRecord], str]],
) -> CompiledArtifact:
    source_root = _artifact_source_root(
        artifact,
        release_root=release_root,
        bundled_skills_root=bundled_skills_root,
        optional_skills_root=optional_skills_root,
    )
    provenance, provenance_file_sha256 = _resolve_provenance_ref(
        artifact, release_root, provenance_cache
    )
    try:
        source_digest = _sha256_pack_tree(source_root)
    except (OSError, ValueError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.SOURCE_NOT_REGULAR,
            f"{artifact.name}: unsafe source tree: {exc}",
            location=source_root,
        ) from exc
    if verify_upstream_sources:
        _verify_pinned_source(
            provenance,
            local_source_tree_sha256=source_digest,
            source_repositories=source_repositories,
        )
    elif (
        provenance.adaptation_type in {"original", "verbatim"}
        and provenance.source_tree_sha256 != source_digest
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.DIGEST_MISMATCH,
            f"{provenance.adaptation_type} content differs from its sealed source-tree digest",
            location=source_root,
        )
    evidence, notice_file_sha256 = _validate_artifact_evidence(
        artifact,
        provenance,
        source_root=source_root,
        release_root=release_root,
        source_tree_sha256=source_digest,
        source_repositories=source_repositories,
        verify_upstream_sources=verify_upstream_sources,
        platform_evidence_verifier=platform_evidence_verifier,
    )
    return CompiledArtifact(
        authoring=artifact,
        source_tree_sha256=source_digest,
        provenance=provenance,
        provenance_file_sha256=provenance_file_sha256,
        notice_file_sha256=notice_file_sha256,
        platform_evidence=evidence,
    )


def _provenance_reference_path(artifact: AuthoringArtifact) -> PurePosixPath:
    raw_path, separator, _record_id = artifact.provenance_ref.partition("#")
    if not separator:
        raise CapabilityPackValidationError(
            PackIssueCode.PROVENANCE_REF_INVALID,
            f"{artifact.name}: provenance_ref is missing its record fragment",
        )
    return _path(raw_path, f"{artifact.name}.provenance_ref")


def _register_release_file_claim(
    claims: dict[str, tuple[PurePosixPath, str, str]],
    *,
    path: PurePosixPath,
    sha256: str,
    kind: str,
    release_root: Path,
) -> None:
    identity = unicodedata.normalize("NFC", path.as_posix()).casefold()
    existing = claims.get(identity)
    if existing is None:
        claims[identity] = (path, sha256, kind)
        return
    existing_path, existing_sha256, existing_kind = existing
    if existing_path != path:
        raise CapabilityPackValidationError(
            PackIssueCode.PATH_UNSAFE,
            f"release paths collide across supported filesystems: {existing_path} and {path}",
            location=release_root,
        )
    if existing_sha256 != sha256:
        raise CapabilityPackValidationError(
            PackIssueCode.DIGEST_MISMATCH,
            f"shared release path {path} has contradictory byte snapshots",
            location=release_root / path,
        )
    if existing_kind != kind:
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            f"release path {path} is reused as both {existing_kind} and {kind}",
            location=release_root / path,
        )


def _seal_release_tree(
    *,
    release_root: Path,
    manifest: AuthoringManifest,
    router: CompiledArtifact,
    members: Sequence[CompiledMember],
) -> str:
    """Reject undeclared release bytes and return a whole-release tree digest."""

    claims: dict[str, tuple[PurePosixPath, str, str]] = {}
    _register_release_file_claim(
        claims,
        path=PurePosixPath("pack.yaml"),
        sha256=manifest.source_file_sha256,
        kind="manifest",
        release_root=release_root,
    )
    source_roots: list[tuple[PurePosixPath, str, str]] = []
    for artifact in (router, *members):
        authoring = artifact.authoring
        if authoring.source_kind == "pack":
            source_roots.append((
                authoring.source_path,
                artifact.source_tree_sha256,
                authoring.name,
            ))
        _register_release_file_claim(
            claims,
            path=_provenance_reference_path(authoring),
            sha256=artifact.provenance_file_sha256,
            kind="provenance",
            release_root=release_root,
        )
        _register_release_file_claim(
            claims,
            path=artifact.provenance.license_file,
            sha256=artifact.provenance.license_file_sha256,
            kind="license",
            release_root=release_root,
        )
        _register_release_file_claim(
            claims,
            path=artifact.provenance.notice_output,
            sha256=artifact.notice_file_sha256,
            kind="notice",
            release_root=release_root,
        )
        for nested in artifact.provenance.nested_assets:
            _register_release_file_claim(
                claims,
                path=nested.license_file,
                sha256=nested.license_file_sha256,
                kind="license",
                release_root=release_root,
            )
        for platform in artifact.platform_evidence:
            _register_release_file_claim(
                claims,
                path=platform.path,
                sha256=platform.sha256,
                kind="platform-evidence",
                release_root=release_root,
            )
            for check in platform.check_evidence:
                _register_release_file_claim(
                    claims,
                    path=check.path,
                    sha256=check.sha256,
                    kind="platform-check-evidence",
                    release_root=release_root,
                )

    for source_root, _source_digest, source_name in source_roots:
        for claimed_path, _claimed_digest, claimed_kind in claims.values():
            if claimed_path == source_root or claimed_path.is_relative_to(source_root):
                raise CapabilityPackValidationError(
                    PackIssueCode.INVARIANT_VIOLATION,
                    f"{claimed_kind} path {claimed_path} overlaps pack source "
                    f"{source_name!r} at {source_root}",
                    location=release_root,
                )

    try:
        inventory = iter_regular_files(release_root)
    except (OSError, ValueError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.SOURCE_NOT_REGULAR,
            f"release tree contains an unsafe entry: {exc}",
            location=release_root,
        ) from exc
    inventory_paths = {relative for relative, _path_value in inventory}
    claims_by_path = {path: (digest, kind) for path, digest, kind in claims.values()}
    claim_paths = set(claims_by_path)
    source_root_parts = {tuple(root.parts) for root, _digest, _name in source_roots}
    missing_claims = sorted(
        claim_paths - inventory_paths,
        key=lambda value: value.as_posix().encode("utf-8"),
    )
    if missing_claims:
        raise CapabilityPackValidationError(
            PackIssueCode.SOURCE_MISSING,
            f"release inventory omits declared path {missing_claims[0]}",
            location=release_root,
        )

    for relative, file_path in inventory:
        claimed = claims_by_path.get(relative)
        if claimed is not None:
            expected_digest, _claimed_kind = claimed
            if _sha256_evidence_file(file_path) != expected_digest:
                raise CapabilityPackValidationError(
                    PackIssueCode.DIGEST_MISMATCH,
                    f"release file changed after validation: {relative}",
                    location=file_path,
                )
            continue
        relative_parts = tuple(relative.parts)
        if any(
            relative_parts[:length] in source_root_parts
            for length in range(1, len(relative_parts) + 1)
        ):
            continue
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            f"release contains undeclared file: {relative}",
            location=file_path,
        )

    for source_root, expected_digest, source_name in source_roots:
        source_path = _resolve_existing(release_root, source_root, directory=True)
        actual_relative = PurePosixPath(
            source_path.relative_to(release_root.resolve(strict=True)).as_posix()
        )
        if actual_relative != source_root:
            raise CapabilityPackValidationError(
                PackIssueCode.PATH_UNSAFE,
                f"pack source {source_name!r} is not referenced with its exact path spelling",
                location=source_path,
            )
        try:
            actual_digest = _sha256_pack_tree(source_path)
        except (OSError, ValueError) as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.SOURCE_NOT_REGULAR,
                f"pack source {source_name!r} changed during release sealing: {exc}",
                location=source_path,
            ) from exc
        if actual_digest != expected_digest:
            raise CapabilityPackValidationError(
                PackIssueCode.DIGEST_MISMATCH,
                f"pack source {source_name!r} changed during release sealing",
                location=source_path,
            )

    try:
        return _sha256_pack_tree(release_root)
    except (OSError, ValueError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.SOURCE_NOT_REGULAR,
            f"could not seal release tree: {exc}",
            location=release_root,
        ) from exc


def _compile_manifest(
    manifest_path: Path,
    *,
    capability_packs_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    repository_root: Path,
    source_repositories: Mapping[str, Path | SourceRepository],
    verify_upstream_sources: bool = True,
    platform_evidence_verifier: PlatformEvidenceVerifier | None = None,
) -> CompiledManifest:
    """Compile one authoring manifest after validating every local gate."""

    manifest = load_authoring_manifest(manifest_path)
    try:
        source_manifest_path = PurePosixPath(
            manifest_path.relative_to(
                capability_packs_root.resolve(strict=True)
            ).as_posix()
        )
    except ValueError as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.PATH_UNSAFE,
            "manifest is outside the capability-pack root",
            location=manifest_path,
        ) from exc
    parts = source_manifest_path.parts
    if (
        len(parts) != 3
        or parts[-1] != "pack.yaml"
        or parts[-3] != manifest.id
        or parts[-2] != manifest.version
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            "manifest path must be <pack-id>/<version>/pack.yaml and match its identity",
            location=manifest_path,
        )
    release_root = manifest_path.parent
    provenance_cache: dict[Path, tuple[dict[str, ProvenanceRecord], str]] = {}
    router = _compile_artifact(
        manifest.router,
        release_root=release_root,
        bundled_skills_root=bundled_skills_root,
        optional_skills_root=optional_skills_root,
        source_repositories=source_repositories,
        verify_upstream_sources=verify_upstream_sources,
        platform_evidence_verifier=platform_evidence_verifier,
        provenance_cache=provenance_cache,
    )
    members: list[CompiledMember] = []
    for authoring_member in manifest.members:
        compiled = _compile_artifact(
            authoring_member,
            release_root=release_root,
            bundled_skills_root=bundled_skills_root,
            optional_skills_root=optional_skills_root,
            source_repositories=source_repositories,
            verify_upstream_sources=verify_upstream_sources,
            platform_evidence_verifier=platform_evidence_verifier,
            provenance_cache=provenance_cache,
        )
        members.append(
            CompiledMember(
                authoring=authoring_member,
                source_tree_sha256=compiled.source_tree_sha256,
                provenance=compiled.provenance,
                provenance_file_sha256=compiled.provenance_file_sha256,
                notice_file_sha256=compiled.notice_file_sha256,
                platform_evidence=compiled.platform_evidence,
            )
        )
    compiled_artifacts: tuple[CompiledArtifact | CompiledMember, ...] = (
        router,
        *members,
    )
    if manifest.provenance.adaptation_policy == "original" and any(
        item.provenance.adaptation_type != "original" for item in compiled_artifacts
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            "adaptation_policy=original cannot admit adapted or verbatim artifacts",
            location=manifest_path,
        )
    expected_pack_source = _normalized_git_remote(
        f"https://github.com/{manifest.provenance.source_repository}"
    )
    for item in compiled_artifacts:
        if item.authoring.ownership != "pack":
            continue
        if item.authoring.author != manifest.provenance.publisher:
            raise CapabilityPackValidationError(
                PackIssueCode.INVARIANT_VIOLATION,
                f"pack-owned artifact {item.authoring.name!r} author must match publisher",
                location=manifest_path,
            )
        if item.provenance.adaptation_type != "original":
            raise CapabilityPackValidationError(
                PackIssueCode.INVARIANT_VIOLATION,
                f"pack-owned artifact {item.authoring.name!r} must use original provenance",
                location=manifest_path,
            )
        if (
            _normalized_git_remote(item.provenance.canonical_source_url)
            != expected_pack_source
        ):
            raise CapabilityPackValidationError(
                PackIssueCode.INVARIANT_VIOLATION,
                f"pack-owned artifact {item.authoring.name!r} source URL does not match pack repository",
                location=manifest_path,
            )
    admitted_sources = [
        (
            item.authoring.name,
            _artifact_source_root(
                item.authoring,
                release_root=release_root,
                bundled_skills_root=bundled_skills_root,
                optional_skills_root=optional_skills_root,
            ).resolve(),
        )
        for item in compiled_artifacts
    ]
    for (left_name, left), (right_name, right) in combinations(admitted_sources, 2):
        if _resolved_paths_overlap(left, right):
            raise CapabilityPackValidationError(
                PackIssueCode.INVARIANT_VIOLATION,
                "admitted source roots must not overlap: "
                f"{left_name}={left} and {right_name}={right}",
                location=manifest_path,
            )
    excluded_source_paths: set[Path] = set()
    for excluded in manifest.excluded_candidates:
        source = _resolve_existing(
            repository_root, excluded.audited_source_path, directory=True
        )
        source_resolved = source.resolve()
        for admitted_name, admitted_source in admitted_sources:
            if _resolved_paths_overlap(source_resolved, admitted_source):
                raise CapabilityPackValidationError(
                    PackIssueCode.INVARIANT_VIOLATION,
                    f"excluded candidate {excluded.name!r} overlaps admitted source "
                    f"{admitted_name!r}",
                    location=source,
                )
        portable_source = Path(str(source_resolved).casefold())
        if portable_source in excluded_source_paths:
            raise CapabilityPackValidationError(
                PackIssueCode.DUPLICATE_ID,
                f"excluded candidates repeat audited source {excluded.audited_source_path}",
                location=source,
            )
        excluded_source_paths.add(portable_source)
        excluded_skill_file = _resolve_existing(
            source,
            PurePosixPath("SKILL.md"),
            directory=False,
            missing_code=PackIssueCode.SOURCE_MISSING,
        )
        _validate_skill_identity(excluded_skill_file, excluded.name)
        try:
            actual = _sha256_pack_tree(source)
        except (OSError, ValueError) as exc:
            raise CapabilityPackValidationError(
                PackIssueCode.SOURCE_NOT_REGULAR,
                f"excluded candidate source is unsafe: {exc}",
                location=source,
            ) from exc
        if actual != excluded.audited_tree_sha256:
            raise CapabilityPackValidationError(
                PackIssueCode.DIGEST_MISMATCH,
                f"excluded candidate {excluded.name!r} audited digest drift",
                location=source,
            )
    notice_records: dict[PurePosixPath, str] = {}
    for artifact in (router, *members):
        existing = notice_records.get(artifact.provenance.notice_output)
        if existing is not None and existing != artifact.notice_file_sha256:
            raise CapabilityPackValidationError(
                PackIssueCode.DIGEST_MISMATCH,
                "shared NOTICE path produced contradictory byte snapshots",
                location=release_root / artifact.provenance.notice_output,
            )
        notice_records[artifact.provenance.notice_output] = artifact.notice_file_sha256
    release_tree_sha256 = _seal_release_tree(
        release_root=release_root,
        manifest=manifest,
        router=router,
        members=members,
    )
    return CompiledManifest(
        authoring=manifest,
        source_manifest_path=source_manifest_path,
        router=router,
        members=tuple(members),
        excluded_candidates=manifest.excluded_candidates,
        manifest_sha256=manifest.source_file_sha256,
        notice_tree_sha256=_sha256_path_records(tuple(notice_records.items())),
        release_tree_sha256=release_tree_sha256,
    )


def compile_manifest(
    manifest_path: Path,
    *,
    capability_packs_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    repository_root: Path,
    source_repositories: Mapping[str, Path | SourceRepository],
    platform_evidence_verifier: PlatformEvidenceVerifier,
) -> CompiledManifest:
    """Source-backed admission compiler; upstream verification cannot be disabled."""

    return _compile_manifest(
        manifest_path,
        capability_packs_root=capability_packs_root,
        bundled_skills_root=bundled_skills_root,
        optional_skills_root=optional_skills_root,
        repository_root=repository_root,
        source_repositories=source_repositories,
        verify_upstream_sources=True,
        platform_evidence_verifier=platform_evidence_verifier,
    )


def _artifact_authoring_dict(artifact: AuthoringArtifact) -> dict[str, Any]:
    result: dict[str, Any] = {
        "author": artifact.author,
        "host_os": list(artifact.host_os),
        "install_path": artifact.install_path.as_posix()
        if artifact.install_path
        else None,
        "license": artifact.license,
        "name": artifact.name,
        "optional_toolsets": list(artifact.optional_toolsets),
        "ownership": artifact.ownership,
        "platform_evidence": list(artifact.platform_evidence),
        "provenance_ref": artifact.provenance_ref,
        "required_toolsets": list(artifact.required_toolsets),
        "source_kind": artifact.source_kind,
        "source_path": artifact.source_path.as_posix(),
        "version": artifact.version,
    }
    if isinstance(artifact, AuthoringMember):
        result["default"] = artifact.default
        result["role"] = artifact.role
    return result


def _provenance_dict(record: ProvenanceRecord) -> dict[str, Any]:
    return {
        "adaptation_type": record.adaptation_type,
        "canonical_source_url": record.canonical_source_url,
        "changes": list(record.changes),
        "copyright_holders": list(record.copyright_holders),
        "id": record.id,
        "license_file": record.license_file.as_posix(),
        "license_source_path": record.license_source_path.as_posix(),
        "license_file_sha256": record.license_file_sha256,
        "nested_assets": [
            {
                "canonical_source_url": item.canonical_source_url,
                "copyright_holders": list(item.copyright_holders),
                "license_file": item.license_file.as_posix(),
                "license_source_path": item.license_source_path.as_posix(),
                "license_file_sha256": item.license_file_sha256,
                "path": item.path.as_posix(),
                "pinned_revision": item.pinned_revision,
                "source_path": item.source_path.as_posix(),
                "sha256": item.sha256,
                "spdx_expression": item.spdx_expression,
            }
            for item in record.nested_assets
        ],
        "notice_output": record.notice_output.as_posix(),
        "pinned_revision": record.pinned_revision,
        "platform_evidence": [item.as_posix() for item in record.platform_evidence],
        "source_path": record.source_path.as_posix(),
        "source_tree_sha256": record.source_tree_sha256,
        "spdx_expression": record.spdx_expression,
    }


def _compiled_artifact_dict(
    artifact: CompiledArtifact | CompiledMember,
) -> dict[str, Any]:
    result = _artifact_authoring_dict(artifact.authoring)
    result.update({
        "effective_host_os": list(artifact.authoring.host_os),
        "notice_file_sha256": artifact.notice_file_sha256,
        "platform_evidence_records": [
            {
                "check_evidence": [
                    {
                        "path": check.path.as_posix(),
                        "sha256": check.sha256,
                    }
                    for check in item.check_evidence
                ],
                "path": item.path.as_posix(),
                "sha256": item.sha256,
                "source_revisions": list(item.source_revisions),
                "source_tree_sha256": item.source_tree_sha256,
                "verified_host_os": list(item.verified_host_os),
            }
            for item in artifact.platform_evidence
        ],
        "provenance": _provenance_dict(artifact.provenance),
        "provenance_file_sha256": artifact.provenance_file_sha256,
        "source_tree_sha256": artifact.source_tree_sha256,
    })
    return result


def _compiled_manifest_dict(compiled: CompiledManifest) -> dict[str, Any]:
    manifest = compiled.authoring
    return {
        "authoring_manifest": {
            "path": compiled.source_manifest_path.as_posix(),
            "sha256": compiled.manifest_sha256,
        },
        "excluded_candidates": [
            {
                "audited_source_path": item.audited_source_path.as_posix(),
                "audited_tree_sha256": item.audited_tree_sha256,
                "disposition": item.disposition,
                "gate_issue_codes": list(item.gate_issue_codes),
                "name": item.name,
            }
            for item in compiled.excluded_candidates
        ],
        "fabric_requires": manifest.fabric_requires,
        "id": manifest.id,
        "members": [_compiled_artifact_dict(item) for item in compiled.members],
        "name": manifest.name,
        "notice_tree_sha256": compiled.notice_tree_sha256,
        "release_tree_sha256": compiled.release_tree_sha256,
        "permissions": {
            "network": manifest.permissions.network,
            "optional_toolsets": list(manifest.permissions.optional_toolsets),
            "required_toolsets": list(manifest.permissions.required_toolsets),
            "secrets": list(manifest.permissions.secrets),
        },
        "provenance": {
            "adaptation_policy": manifest.provenance.adaptation_policy,
            "publisher": manifest.provenance.publisher,
            "source_repository": manifest.provenance.source_repository,
        },
        "router": _compiled_artifact_dict(compiled.router),
        "schema_version": manifest.schema_version,
        "summary": manifest.summary,
        "version": manifest.version,
    }


def _load_source_catalog(path: Path) -> tuple[list[tuple[str, PurePosixPath]], str]:
    data, source_file_sha256 = _load_yaml_mapping_snapshot(path)
    _exact_fields(
        data,
        required=frozenset({"schema_version", "packs"}),
        field_name="catalog",
    )
    if data["schema_version"] != SCHEMA_VERSION or isinstance(
        data["schema_version"], bool
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.SCHEMA_VERSION_UNSUPPORTED,
            f"catalog schema_version must be {SCHEMA_VERSION}",
            location=path,
        )
    result: list[tuple[str, PurePosixPath]] = []
    pack_ids: set[str] = set()
    manifest_paths: set[str] = set()
    raw_packs = _sequence(data["packs"], "catalog.packs")
    if not raw_packs:
        raise CapabilityPackValidationError(
            PackIssueCode.TYPE_INVALID,
            "catalog.packs must contain at least one approved release",
            location=path,
        )
    for pack_index, raw_pack in enumerate(raw_packs):
        pack = _mapping(raw_pack, f"catalog.packs[{pack_index}]")
        _exact_fields(
            pack,
            required=frozenset({"id", "releases"}),
            field_name=f"catalog.packs[{pack_index}]",
        )
        pack_id = _pack_id(pack["id"], f"catalog.packs[{pack_index}].id")
        if pack_id.casefold() in pack_ids:
            raise CapabilityPackValidationError(
                PackIssueCode.DUPLICATE_ID,
                f"duplicate catalog pack ID: {pack_id}",
            )
        pack_ids.add(pack_id.casefold())
        releases = _sequence(pack["releases"], f"catalog.packs[{pack_index}].releases")
        if not releases:
            raise CapabilityPackValidationError(
                PackIssueCode.TYPE_INVALID,
                f"catalog pack {pack_id!r} must declare at least one release",
            )
        for release_index, raw_release in enumerate(releases):
            release = _mapping(
                raw_release,
                f"catalog.packs[{pack_index}].releases[{release_index}]",
            )
            _exact_fields(
                release,
                required=frozenset({"manifest"}),
                field_name=f"catalog.packs[{pack_index}].releases[{release_index}]",
            )
            manifest = _path(
                release["manifest"],
                f"catalog.packs[{pack_index}].releases[{release_index}].manifest",
            )
            folded = manifest.as_posix().casefold()
            if folded in manifest_paths:
                raise CapabilityPackValidationError(
                    PackIssueCode.DUPLICATE_ID,
                    f"duplicate catalog manifest path: {manifest}",
                )
            manifest_paths.add(folded)
            result.append((pack_id, manifest))
    return result, source_file_sha256


def _validate_catalog_root_inventory(
    capability_packs_root: Path,
    *,
    source_catalog: PurePosixPath,
    declarations: Sequence[tuple[str, PurePosixPath]],
) -> None:
    """Reject files that packaging would ship outside a declared release."""

    release_roots = {manifest.parent for _pack_id, manifest in declarations}
    generated_catalog = PurePosixPath(CATALOG_OUTPUT_NAME)
    try:
        inventory = iter_regular_files(capability_packs_root)
    except (OSError, ValueError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.SOURCE_NOT_REGULAR,
            f"capability-pack root contains an unsafe entry: {exc}",
            location=capability_packs_root,
        ) from exc
    for relative, file_path in inventory:
        if relative in {source_catalog, generated_catalog}:
            continue
        if any(relative.is_relative_to(root) for root in release_roots):
            continue
        raise CapabilityPackValidationError(
            PackIssueCode.INVARIANT_VIOLATION,
            f"capability-pack root contains a file outside declared releases: {relative}",
            location=file_path,
        )


def _compile_catalog(
    capability_packs_root: Path,
    *,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    repository_root: Path,
    source_repositories: Mapping[str, Path | SourceRepository],
    source_name: str = CATALOG_SOURCE_NAME,
    verify_upstream_sources: bool = True,
    platform_evidence_verifier: PlatformEvidenceVerifier | None = None,
) -> dict[str, Any]:
    """Compile a source catalog into deterministic JSON-compatible data."""

    source_relative = _path(source_name, "source_name")
    source_path = _resolve_existing(
        capability_packs_root, source_relative, directory=False
    )
    declarations, source_catalog_sha256 = _load_source_catalog(source_path)
    grouped: dict[str, list[CompiledManifest]] = {}
    versions: dict[str, dict[tuple[int, int, int, tuple[str, ...]], str]] = {}
    for declared_id, manifest_relative in declarations:
        manifest_path = _resolve_existing(
            capability_packs_root, manifest_relative, directory=False
        )
        compiled = _compile_manifest(
            manifest_path,
            capability_packs_root=capability_packs_root,
            bundled_skills_root=bundled_skills_root,
            optional_skills_root=optional_skills_root,
            repository_root=repository_root,
            source_repositories=source_repositories,
            verify_upstream_sources=verify_upstream_sources,
            platform_evidence_verifier=platform_evidence_verifier,
        )
        if compiled.authoring.id != declared_id:
            raise CapabilityPackValidationError(
                PackIssueCode.INVARIANT_VIOLATION,
                f"catalog ID {declared_id!r} does not match manifest ID {compiled.authoring.id!r}",
                location=manifest_path,
            )
        parsed_version = _semver(compiled.authoring.version, "manifest.version")
        seen = versions.setdefault(declared_id, {})
        if parsed_version.precedence_key in seen:
            raise CapabilityPackValidationError(
                PackIssueCode.DUPLICATE_ID,
                "release versions with equal SemVer precedence are ambiguous: "
                f"{declared_id}@{seen[parsed_version.precedence_key]} and "
                f"{compiled.authoring.version}",
            )
        seen[parsed_version.precedence_key] = compiled.authoring.version
        grouped.setdefault(declared_id, []).append(compiled)
    _validate_catalog_root_inventory(
        capability_packs_root,
        source_catalog=source_relative,
        declarations=declarations,
    )
    packs = []
    for pack_id in sorted(grouped):
        releases = sorted(
            grouped[pack_id],
            key=lambda item: (
                _semver(item.authoring.version, "version"),
                item.authoring.version,
            ),
        )
        packs.append({
            "id": pack_id,
            "releases": [_compiled_manifest_dict(item) for item in releases],
        })
    return {
        "packs": packs,
        "schema_version": SCHEMA_VERSION,
        "source_catalog": {
            "path": source_relative.as_posix(),
            "sha256": source_catalog_sha256,
        },
    }


def compile_catalog(
    capability_packs_root: Path,
    *,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    repository_root: Path,
    source_repositories: Mapping[str, Path | SourceRepository],
    platform_evidence_verifier: PlatformEvidenceVerifier,
    source_name: str = CATALOG_SOURCE_NAME,
) -> dict[str, Any]:
    """Source-backed admission compiler; upstream verification cannot be disabled."""

    return _compile_catalog(
        capability_packs_root,
        bundled_skills_root=bundled_skills_root,
        optional_skills_root=optional_skills_root,
        repository_root=repository_root,
        source_repositories=source_repositories,
        source_name=source_name,
        verify_upstream_sources=True,
        platform_evidence_verifier=platform_evidence_verifier,
    )


def build_catalog_bytes(
    capability_packs_root: Path,
    *,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    repository_root: Path,
    source_repositories: Mapping[str, Path | SourceRepository],
    platform_evidence_verifier: PlatformEvidenceVerifier,
    source_name: str = CATALOG_SOURCE_NAME,
) -> bytes:
    """Compile and serialize one catalog without changing the filesystem."""

    payload = canonical_json_bytes(
        compile_catalog(
            capability_packs_root,
            bundled_skills_root=bundled_skills_root,
            optional_skills_root=optional_skills_root,
            repository_root=repository_root,
            source_repositories=source_repositories,
            platform_evidence_verifier=platform_evidence_verifier,
            source_name=source_name,
        )
    )
    if len(payload) > MAX_COMPILED_BYTES:
        raise CapabilityPackValidationError(
            PackIssueCode.CATALOG_NOT_CANONICAL,
            f"compiled catalog exceeds {MAX_COMPILED_BYTES} bytes",
        )
    return payload


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CapabilityPackValidationError(
                PackIssueCode.DUPLICATE_KEY,
                f"duplicate JSON key: {key}",
            )
        result[key] = value
    return result


def _compiled_source_name(data: Mapping[str, Any]) -> str:
    _exact_fields(
        data,
        required=frozenset({"schema_version", "packs", "source_catalog"}),
        field_name="compiled catalog",
    )
    if data["schema_version"] != SCHEMA_VERSION or isinstance(
        data["schema_version"], bool
    ):
        raise CapabilityPackValidationError(
            PackIssueCode.SCHEMA_VERSION_UNSUPPORTED,
            f"compiled catalog schema_version must be {SCHEMA_VERSION}",
        )
    source_catalog = _mapping(data["source_catalog"], "compiled catalog.source_catalog")
    _exact_fields(
        source_catalog,
        required=frozenset({"path", "sha256"}),
        field_name="compiled catalog.source_catalog",
    )
    _sha256(source_catalog["sha256"], "compiled catalog.source_catalog.sha256")
    return _path(
        source_catalog["path"], "compiled catalog.source_catalog.path"
    ).as_posix()


def load_compiled_catalog(
    path: Path,
    *,
    capability_packs_root: Path,
    bundled_skills_root: Path,
    optional_skills_root: Path,
    repository_root: Path,
) -> dict[str, Any]:
    """Load a compiled catalog and prove it matches current authoring/source data.

    This strict loader intentionally rebuilds from the shipped authoring input.
    Distribution packaging must therefore include all build evidence referenced
    by a release; a runtime never downgrades a bad release to a partial catalog.
    """

    raw = _read_bytes_bounded(
        path,
        limit=MAX_COMPILED_BYTES,
        code=PackIssueCode.CATALOG_NOT_CANONICAL,
        label="compiled catalog",
    )
    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_pairs,
            parse_constant=_reject_json_constant,
        )
    except CapabilityPackValidationError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.CATALOG_NOT_CANONICAL,
            f"compiled catalog is not valid UTF-8 JSON: {exc}",
            location=path,
        ) from exc
    try:
        canonical = canonical_json_bytes(data)
    except (TypeError, ValueError, RecursionError) as exc:
        raise CapabilityPackValidationError(
            PackIssueCode.CATALOG_NOT_CANONICAL,
            f"compiled catalog cannot be canonicalized: {exc}",
            location=path,
        ) from exc
    if not isinstance(data, dict) or canonical != raw:
        raise CapabilityPackValidationError(
            PackIssueCode.CATALOG_NOT_CANONICAL,
            "compiled catalog bytes are not canonical JSON",
            location=path,
        )
    expected = _compile_catalog(
        capability_packs_root,
        bundled_skills_root=bundled_skills_root,
        optional_skills_root=optional_skills_root,
        repository_root=repository_root,
        source_repositories={},
        source_name=_compiled_source_name(data),
        verify_upstream_sources=False,
        platform_evidence_verifier=None,
    )
    if data != expected:
        raise CapabilityPackValidationError(
            PackIssueCode.DIGEST_MISMATCH,
            "compiled catalog does not match current authoring/source evidence",
            location=path,
        )
    return data


__all__ = [
    "AuthoringArtifact",
    "AuthoringManifest",
    "AuthoringMember",
    "CapabilityPackValidationError",
    "CompiledArtifact",
    "CompiledManifest",
    "CompiledMember",
    "EvidenceFileRecord",
    "ExcludedCandidate",
    "NestedAssetRecord",
    "PackIssueCode",
    "PackPermissions",
    "PackProvenance",
    "PlatformEvidenceRecord",
    "ProvenanceRecord",
    "SourceRepository",
    "build_catalog_bytes",
    "canonical_json_bytes",
    "compile_catalog",
    "compile_manifest",
    "load_authoring_manifest",
    "load_compiled_catalog",
]
