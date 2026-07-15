"""Offline verification for signed Fabric skill releases.

This module implements a deliberately small, pure-data, TUF-style subset.  It
is not a claim of python-tuf or full TUF specification conformance.  The exact
chain is:

``trusted root -> timestamp -> snapshot -> (targets, revocations)``

The root assigns independent Ed25519 key thresholds to all five roles.  Root
rotation requires the next consecutive root to meet both the old and new root
thresholds.  Timestamp and snapshot metadata bind the exact canonical bytes,
lengths, and versions of their children.  Targets bind a skill name and exact
SemVer to its full tree, contract, and evaluation SHA-256 digests.  A dedicated
revocations role can revoke a name/version, a tree digest, or all versions
below a minimum safe SemVer.

Only deterministic UTF-8 canonical JSON is accepted: object keys are sorted,
there is no insignificant whitespace, strings and keys are NFC-normalized,
numbers are bounded integers, duplicate keys and floats are rejected, and all
schemas reject unknown fields.  Signatures cover the canonical ``signed``
object, while parent metadata hashes the complete canonical child envelope.

Limitations are intentional: there are no delegated targets, consistent
snapshot filenames, mirrors, network fetching, key storage, filesystem access,
or trust-on-first-use.  Callers must pin the first trusted root out of band,
atomically persist trusted metadata versions plus canonical envelope digests,
and decide when to fetch metadata.  Expired metadata never authorizes a new
install or update.  A caller may explicitly grant a bounded offline grace
period only with a verifier-issued HMAC proof and a fresh measurement of the
exact installed tree; the target must also remain non-revoked in the supplied
signed revocation metadata.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


SPEC_VERSION = "fabric-distribution-1"

_MAX_METADATA_BYTES = 2 * 1024 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 50_000
_MAX_MAPPING_KEYS = 10_000
_MAX_ARRAY_ITEMS = 10_000
_MAX_STRING_BYTES = 1024 * 1024
_MAX_SIGNATURES = 64
_MAX_KEYS = 64
_MAX_TARGETS = 10_000
_MAX_REVOCATIONS = 10_000
_MAX_REASON_BYTES = 512
_MAX_CLOCK_SKEW = timedelta(minutes=5)
_MAX_OFFLINE_GRACE = timedelta(days=30)
_INSTALL_PROOF_KEY_BYTES = 32
_INSTALL_PROOF_MAX_BYTES = 16 * 1024
_INSTALL_PROOF_VERSION = 1
_INSTALL_PROOF_DOMAIN = b"fabric.skill-install-proof.v1\0"

_ROLES = ("root", "timestamp", "snapshot", "targets", "revocations")
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._/-]{0,126}[a-z0-9])?$")
_CHANNEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)


class DistributionErrorCode(str, Enum):
    """Stable machine-readable failure codes for future install gates."""

    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    NON_CANONICAL_JSON = "non_canonical_json"
    METADATA_TOO_LARGE = "metadata_too_large"
    SCHEMA_ERROR = "schema_error"
    UNSUPPORTED_SPEC = "unsupported_spec"
    UNSUPPORTED_ALGORITHM = "unsupported_algorithm"
    MALFORMED_BASE64 = "malformed_base64"
    KEY_ID_MISMATCH = "key_id_mismatch"
    UNKNOWN_KEY = "unknown_key"
    UNAUTHORIZED_KEY = "unauthorized_key"
    INVALID_SIGNATURE = "invalid_signature"
    THRESHOLD_NOT_MET = "threshold_not_met"
    ROOT_ROLLBACK = "root_rollback"
    ROOT_VERSION_GAP = "root_version_gap"
    METADATA_ROLLBACK = "metadata_rollback"
    METADATA_EXPIRED = "metadata_expired"
    METADATA_FREEZE = "metadata_freeze"
    METADATA_HASH_MISMATCH = "metadata_hash_mismatch"
    METADATA_LENGTH_MISMATCH = "metadata_length_mismatch"
    METADATA_VERSION_MISMATCH = "metadata_version_mismatch"
    METADATA_EQUIVOCATION = "metadata_equivocation"
    ROOT_PIN_MISMATCH = "root_pin_mismatch"
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_REVOKED = "target_revoked"
    OFFLINE_GRACE_DENIED = "offline_grace_denied"
    INSTALL_PROOF_INVALID = "install_proof_invalid"
    ARTIFACT_MISMATCH = "artifact_mismatch"


class SkillDistributionError(ValueError):
    """Fail-closed verification error with a stable ``code`` and ``path``."""

    def __init__(
        self,
        code: DistributionErrorCode | str,
        message: str,
        *,
        path: str | None = None,
        revocation: RevocationDecision | None = None,
    ) -> None:
        self.code = code.value if isinstance(code, DistributionErrorCode) else code
        self.path = path
        self.revocation = revocation
        detail = f"{path}: {message}" if path else message
        super().__init__(f"{self.code}: {detail}")


@dataclass(frozen=True)
class TrustedVersions:
    """Highest trusted versions and their exact canonical envelope digests.

    A non-zero version always carries its SHA-256 digest.  Version-only state
    cannot distinguish a byte-identical cache hit from same-version metadata
    equivocation, so it is deliberately rejected.
    """

    root: int = 0
    timestamp: int = 0
    snapshot: int = 0
    targets: int = 0
    revocations: int = 0
    root_sha256: str | None = None
    timestamp_sha256: str | None = None
    snapshot_sha256: str | None = None
    targets_sha256: str | None = None
    revocations_sha256: str | None = None

    def __post_init__(self) -> None:
        for role in _ROLES:
            value = getattr(self, role)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _fail(
                    DistributionErrorCode.SCHEMA_ERROR,
                    "trusted version must be a non-negative integer",
                    path=f"prior_versions.{role}",
                )
            digest = getattr(self, f"{role}_sha256")
            if value == 0:
                if digest is not None:
                    _fail(
                        DistributionErrorCode.SCHEMA_ERROR,
                        "an untrusted role may not carry a digest",
                        path=f"prior_versions.{role}_sha256",
                    )
            elif not isinstance(digest, str) or not _HEX_SHA256_RE.fullmatch(digest):
                _fail(
                    DistributionErrorCode.SCHEMA_ERROR,
                    "a non-zero trusted version requires a lowercase SHA-256 digest",
                    path=f"prior_versions.{role}_sha256",
                )

    def without(self, roles: Sequence[str]) -> TrustedVersions:
        """Return state with *roles* reset after an authorized key rotation."""

        reset = set(roles)
        unknown = reset - set(_ROLES)
        if unknown:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                f"unknown trusted roles: {', '.join(sorted(unknown))}",
                path="roles",
            )
        values: dict[str, Any] = {}
        for role in _ROLES:
            if role in reset:
                values[role] = 0
                values[f"{role}_sha256"] = None
            else:
                values[role] = getattr(self, role)
                values[f"{role}_sha256"] = getattr(self, f"{role}_sha256")
        return TrustedVersions(**values)


@dataclass(frozen=True)
class OfflineGracePolicy:
    """Explicit upper bound for using stale metadata for an installed release."""

    max_staleness: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.max_staleness, timedelta):
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "max_staleness must be a timedelta",
                path="offline_grace.max_staleness",
            )
        if self.max_staleness <= timedelta(0):
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "max_staleness must be positive",
                path="offline_grace.max_staleness",
            )
        if self.max_staleness > _MAX_OFFLINE_GRACE:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "max_staleness may not exceed 30 days",
                path="offline_grace.max_staleness",
            )


@dataclass(frozen=True)
class RevocationDecision:
    """Result of evaluating every signed revocation rule for one target."""

    revoked: bool
    matched_by: str | None = None
    reason: str | None = None
    minimum_safe_version: str | None = None


@dataclass(frozen=True, init=False)
class VerifiedRelease:
    """A release whose complete signed metadata chain has been verified."""

    name: str
    version: str
    tree_sha256: str
    contract_sha256: str
    eval_sha256: str
    channel: str
    publisher: str
    root_version: int
    timestamp_version: int
    snapshot_version: int
    targets_version: int
    revocations_version: int
    verified_at: datetime
    revocation: RevocationDecision
    trusted_versions: TrustedVersions = field(repr=False)
    _verification_token: object = field(repr=False, compare=False)
    offline_grace_used: bool = False
    stale_roles: tuple[str, ...] = ()

    def __init__(self, *_: Any, **__: Any) -> None:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "VerifiedRelease values are verifier-issued and cannot be constructed",
            path="installed_release",
        )


@dataclass(frozen=True)
class _RoleDefinition:
    keyids: tuple[str, ...]
    threshold: int


@dataclass(frozen=True, init=False)
class TrustedRoot:
    """Validated root trust anchor. Bootstrap the first instance out of band."""

    version: int
    expires: datetime
    canonical_sha256: str
    _keys: Mapping[str, bytes] = field(repr=False, compare=False)
    _roles: Mapping[str, _RoleDefinition] = field(repr=False, compare=False)
    _invalidated_roles: tuple[str, ...] = field(repr=False, compare=False)
    _verification_token: object = field(repr=False, compare=False)

    def __init__(self, *_: Any, **__: Any) -> None:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "TrustedRoot values must come from pinned bootstrap or verified rotation",
            path="root",
        )


@dataclass(frozen=True)
class RootRotationResult:
    """A verified root and rollback state that callers persist atomically."""

    root: TrustedRoot
    trusted_versions: TrustedVersions


@dataclass(frozen=True)
class _Signature:
    keyid: str
    signature: bytes


@dataclass(frozen=True)
class _Envelope:
    raw: bytes
    signed: dict[str, Any]
    signatures: tuple[_Signature, ...]


@dataclass(frozen=True)
class _Reference:
    version: int
    length: int
    sha256: str


@dataclass(frozen=True)
class _Target:
    name: str
    version: str
    tree_sha256: str
    contract_sha256: str
    eval_sha256: str
    channel: str
    publisher: str


@dataclass(frozen=True)
class _Revocation:
    kind: str
    name: str | None
    version: str | None
    sha256: str | None
    reason: str | None


class _DuplicateKeyError(ValueError):
    pass


_TRUSTED_ROOT_TOKEN = object()
_VERIFIED_RELEASE_TOKEN = object()


def _fail(
    code: DistributionErrorCode,
    message: str,
    *,
    path: str | None = None,
    revocation: RevocationDecision | None = None,
) -> None:
    raise SkillDistributionError(code, message, path=path, revocation=revocation)


def _new_trusted_root(
    *,
    version: int,
    expires: datetime,
    canonical_sha256: str,
    keys: Mapping[str, bytes],
    roles: Mapping[str, _RoleDefinition],
    invalidated_roles: Sequence[str] = (),
) -> TrustedRoot:
    root = object.__new__(TrustedRoot)
    object.__setattr__(root, "version", version)
    object.__setattr__(root, "expires", expires)
    object.__setattr__(root, "canonical_sha256", canonical_sha256)
    object.__setattr__(root, "_keys", MappingProxyType(dict(keys)))
    object.__setattr__(root, "_roles", MappingProxyType(dict(roles)))
    object.__setattr__(
        root, "_invalidated_roles", tuple(dict.fromkeys(invalidated_roles))
    )
    object.__setattr__(root, "_verification_token", _TRUSTED_ROOT_TOKEN)
    return root


def _new_verified_release(**values: Any) -> VerifiedRelease:
    release = object.__new__(VerifiedRelease)
    for name, value in values.items():
        object.__setattr__(release, name, value)
    object.__setattr__(release, "_verification_token", _VERIFIED_RELEASE_TOKEN)
    return release


def _is_verifier_issued_release(value: Any) -> bool:
    return (
        type(value) is VerifiedRelease
        and getattr(value, "_verification_token", None) is _VERIFIED_RELEASE_TOKEN
    )


def _is_trusted_root(value: Any) -> bool:
    return (
        type(value) is TrustedRoot
        and getattr(value, "_verification_token", None) is _TRUSTED_ROOT_TOKEN
    )


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _reject_float(_: str) -> None:
    raise ValueError("floating-point values are not part of the canonical subset")


def _parse_int(value: str) -> int:
    if len(value.lstrip("-")) > 19:
        raise ValueError("integer exceeds the canonical 64-bit bound")
    parsed = int(value)
    if parsed < -(2**63) or parsed > 2**63 - 1:
        raise ValueError("integer exceeds the canonical 64-bit bound")
    return parsed


def _validate_json_value(value: Any, *, path: str = "$", depth: int = 0) -> int:
    if depth > _MAX_JSON_DEPTH:
        _fail(DistributionErrorCode.SCHEMA_ERROR, "JSON nesting is too deep", path=path)
    if value is None or isinstance(value, bool):
        return 1
    if isinstance(value, int):
        if value < -(2**63) or value > 2**63 - 1:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "integer exceeds the canonical 64-bit bound",
                path=path,
            )
        return 1
    if isinstance(value, float):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "floating-point values are not part of the canonical subset",
            path=path,
        )
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            _fail(
                DistributionErrorCode.NON_CANONICAL_JSON,
                "strings must use NFC Unicode normalization",
                path=path,
            )
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError:
            _fail(
                DistributionErrorCode.INVALID_JSON,
                "strings may not contain Unicode surrogate code points",
                path=path,
            )
        if len(encoded) > _MAX_STRING_BYTES:
            _fail(DistributionErrorCode.SCHEMA_ERROR, "string is too large", path=path)
        return 1
    if isinstance(value, Mapping):
        if len(value) > _MAX_MAPPING_KEYS:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "object has too many keys",
                path=path,
            )
        nodes = 1
        for key, child in value.items():
            if not isinstance(key, str):
                _fail(
                    DistributionErrorCode.SCHEMA_ERROR,
                    "object keys must be strings",
                    path=path,
                )
            if unicodedata.normalize("NFC", key) != key:
                _fail(
                    DistributionErrorCode.NON_CANONICAL_JSON,
                    "object keys must use NFC Unicode normalization",
                    path=path,
                )
            try:
                encoded_key = key.encode("utf-8")
            except UnicodeEncodeError:
                _fail(
                    DistributionErrorCode.INVALID_JSON,
                    "object keys may not contain Unicode surrogate code points",
                    path=path,
                )
            if len(encoded_key) > _MAX_STRING_BYTES:
                _fail(
                    DistributionErrorCode.SCHEMA_ERROR,
                    "object key is too large",
                    path=path,
                )
            if any(ord(char) < 0x20 or ord(char) == 0x7F for char in key):
                _fail(
                    DistributionErrorCode.SCHEMA_ERROR,
                    "control characters are forbidden in object keys",
                    path=path,
                )
            nodes += _validate_json_value(child, path=f"{path}.{key}", depth=depth + 1)
            if nodes > _MAX_JSON_NODES:
                _fail(
                    DistributionErrorCode.SCHEMA_ERROR,
                    "JSON has too many nodes",
                    path=path,
                )
        return nodes
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX_ARRAY_ITEMS:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "array has too many items",
                path=path,
            )
        nodes = 1
        for index, child in enumerate(value):
            nodes += _validate_json_value(
                child, path=f"{path}[{index}]", depth=depth + 1
            )
            if nodes > _MAX_JSON_NODES:
                _fail(
                    DistributionErrorCode.SCHEMA_ERROR,
                    "JSON has too many nodes",
                    path=path,
                )
        return nodes
    _fail(
        DistributionErrorCode.SCHEMA_ERROR,
        f"unsupported canonical JSON value {type(value).__name__}",
        path=path,
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return Fabric's deterministic canonical-JSON bytes for *value*."""

    _validate_json_value(value)
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return text.encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeEncodeError) as exc:
        _fail(DistributionErrorCode.SCHEMA_ERROR, f"cannot canonicalize JSON: {exc}")


def _parse_canonical_json(data: bytes | str) -> tuple[bytes, Any]:
    if isinstance(data, str):
        try:
            raw = data.encode("utf-8")
        except UnicodeEncodeError as exc:
            _fail(DistributionErrorCode.INVALID_JSON, f"metadata is not UTF-8: {exc}")
    elif isinstance(data, bytes):
        raw = data
    else:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "metadata must be UTF-8 bytes or text",
        )
    if len(raw) > _MAX_METADATA_BYTES:
        _fail(DistributionErrorCode.METADATA_TOO_LARGE, "metadata exceeds 2 MiB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail(DistributionErrorCode.INVALID_JSON, f"metadata is not UTF-8: {exc}")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_json_pairs,
            parse_float=_reject_float,
            parse_int=_parse_int,
            parse_constant=_reject_float,
        )
    except _DuplicateKeyError:
        _fail(DistributionErrorCode.DUPLICATE_KEY, "duplicate object key")
    except (json.JSONDecodeError, RecursionError, UnicodeError, ValueError) as exc:
        _fail(DistributionErrorCode.INVALID_JSON, f"invalid canonical JSON: {exc}")
    _validate_json_value(value)
    if canonical_json_bytes(value) != raw:
        _fail(
            DistributionErrorCode.NON_CANONICAL_JSON,
            "metadata bytes are not in Fabric canonical form",
        )
    return raw, value


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(DistributionErrorCode.SCHEMA_ERROR, "must be an object", path=path)
    return value


def _list(value: Any, path: str, *, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        _fail(DistributionErrorCode.SCHEMA_ERROR, "must be an array", path=path)
    if len(value) > maximum:
        _fail(DistributionErrorCode.SCHEMA_ERROR, "contains too many items", path=path)
    return value


def _exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    path: str,
) -> None:
    optional = optional or set()
    actual = set(value)
    missing = required - actual
    unknown = actual - required - optional
    if missing:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            f"missing fields: {', '.join(sorted(missing))}",
            path=path,
        )
    if unknown:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            f"unknown fields: {', '.join(sorted(unknown))}",
            path=path,
        )


def _string(value: Any, path: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR, "must be a non-empty string", path=path
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "must not contain Unicode surrogate code points",
            path=path,
        )
    if len(encoded) > maximum:
        _fail(DistributionErrorCode.SCHEMA_ERROR, "string is too long", path=path)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "control characters are forbidden",
            path=path,
        )
    return value


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR, "must be a positive integer", path=path
        )
    return value


def _sha256(value: Any, path: str) -> str:
    text = _string(value, path, maximum=64)
    if not _HEX_SHA256_RE.fullmatch(text):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "must be a lowercase 64-character SHA-256 hex digest",
            path=path,
        )
    return text


def _timestamp(value: Any, path: str) -> datetime:
    text = _string(value, path, maximum=20)
    if not _UTC_TIMESTAMP_RE.fullmatch(text):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "must be an RFC 3339 UTC timestamp with whole seconds",
            path=path,
        )
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR, f"invalid timestamp: {exc}", path=path
        )


def _utc_now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR, "now must be timezone-aware", path="now"
        )
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError) as exc:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            f"now cannot be converted to UTC: {exc}",
            path="now",
        )


def _version(value: Any, path: str) -> int:
    return _positive_int(value, path)


def _semver(value: Any, path: str) -> str:
    text = _string(value, path, maximum=128)
    if not _SEMVER_RE.fullmatch(text):
        _fail(DistributionErrorCode.SCHEMA_ERROR, "must be an exact SemVer", path=path)
    return text


def _name(value: Any, path: str) -> str:
    text = _string(value, path, maximum=128)
    if (
        not _NAME_RE.fullmatch(text)
        or "//" in text
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "must be a canonical skill name",
            path=path,
        )
    return text


def _b64(value: Any, path: str, *, length: int) -> bytes:
    text = _string(value, path, maximum=256)
    try:
        decoded = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        _fail(
            DistributionErrorCode.MALFORMED_BASE64, f"invalid Base64: {exc}", path=path
        )
    if len(decoded) != length or base64.b64encode(decoded).decode("ascii") != text:
        _fail(
            DistributionErrorCode.MALFORMED_BASE64,
            f"must be canonical Base64 for exactly {length} bytes",
            path=path,
        )
    return decoded


def _parse_envelope(data: bytes | str) -> _Envelope:
    raw, parsed = _parse_canonical_json(data)
    envelope = _mapping(parsed, "$")
    _exact_keys(envelope, required={"signed", "signatures"}, path="$")
    signed = _mapping(envelope["signed"], "$.signed")
    signatures_data = _list(
        envelope["signatures"], "$.signatures", maximum=_MAX_SIGNATURES
    )
    if not signatures_data:
        _fail(
            DistributionErrorCode.THRESHOLD_NOT_MET,
            "metadata has no signatures",
            path="$.signatures",
        )
    signatures: list[_Signature] = []
    seen: set[str] = set()
    for index, raw_signature in enumerate(signatures_data):
        path = f"$.signatures[{index}]"
        signature = _mapping(raw_signature, path)
        _exact_keys(signature, required={"keyid", "sig"}, path=path)
        keyid = _sha256(signature["keyid"], f"{path}.keyid")
        if keyid in seen:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "a key ID may sign an envelope only once",
                path=f"{path}.keyid",
            )
        seen.add(keyid)
        signatures.append(
            _Signature(
                keyid=keyid, signature=_b64(signature["sig"], f"{path}.sig", length=64)
            )
        )
    return _Envelope(raw=raw, signed=signed, signatures=tuple(signatures))


def _parse_common_signed(
    signed: Mapping[str, Any], role: str, *, extra_keys: set[str]
) -> tuple[int, datetime]:
    _exact_keys(
        signed,
        required={"_type", "spec_version", "version", "expires", *extra_keys},
        path="$.signed",
    )
    if signed["_type"] != role:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            f"expected _type {role!r}",
            path="$.signed._type",
        )
    if signed["spec_version"] != SPEC_VERSION:
        _fail(
            DistributionErrorCode.UNSUPPORTED_SPEC,
            f"only {SPEC_VERSION!r} is supported",
            path="$.signed.spec_version",
        )
    return (
        _version(signed["version"], "$.signed.version"),
        _timestamp(signed["expires"], "$.signed.expires"),
    )


def _parse_root(envelope: _Envelope) -> TrustedRoot:
    signed = envelope.signed
    version, expires = _parse_common_signed(
        signed, "root", extra_keys={"keys", "roles"}
    )
    keys_data = _mapping(signed["keys"], "$.signed.keys")
    if not keys_data or len(keys_data) > _MAX_KEYS:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            f"root must contain between 1 and {_MAX_KEYS} keys",
            path="$.signed.keys",
        )
    keys: dict[str, bytes] = {}
    for raw_keyid, raw_key in keys_data.items():
        keyid = _sha256(raw_keyid, f"$.signed.keys.{raw_keyid}")
        key = _mapping(raw_key, f"$.signed.keys.{keyid}")
        _exact_keys(
            key,
            required={"keytype", "scheme", "keyval"},
            path=f"$.signed.keys.{keyid}",
        )
        if key["keytype"] != "ed25519" or key["scheme"] != "ed25519":
            _fail(
                DistributionErrorCode.UNSUPPORTED_ALGORITHM,
                "only raw Ed25519 keys are supported",
                path=f"$.signed.keys.{keyid}",
            )
        public_bytes = _b64(key["keyval"], f"$.signed.keys.{keyid}.keyval", length=32)
        expected_keyid = hashlib.sha256(canonical_json_bytes(key)).hexdigest()
        if keyid != expected_keyid:
            _fail(
                DistributionErrorCode.KEY_ID_MISMATCH,
                "key ID must equal SHA-256 of its canonical key object",
                path=f"$.signed.keys.{keyid}",
            )
        keys[keyid] = public_bytes

    roles_data = _mapping(signed["roles"], "$.signed.roles")
    _exact_keys(roles_data, required=set(_ROLES), path="$.signed.roles")
    roles: dict[str, _RoleDefinition] = {}
    for role in _ROLES:
        path = f"$.signed.roles.{role}"
        raw_role = _mapping(roles_data[role], path)
        _exact_keys(raw_role, required={"keyids", "threshold"}, path=path)
        raw_keyids = _list(raw_role["keyids"], f"{path}.keyids", maximum=_MAX_KEYS)
        if not raw_keyids:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "keyids may not be empty",
                path=f"{path}.keyids",
            )
        keyids = tuple(
            _sha256(keyid, f"{path}.keyids[{index}]")
            for index, keyid in enumerate(raw_keyids)
        )
        if len(set(keyids)) != len(keyids):
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "keyids must be distinct",
                path=f"{path}.keyids",
            )
        for keyid in keyids:
            if keyid not in keys:
                _fail(
                    DistributionErrorCode.UNKNOWN_KEY,
                    f"role references unknown key {keyid}",
                    path=f"{path}.keyids",
                )
        threshold = _positive_int(raw_role["threshold"], f"{path}.threshold")
        if threshold > len(keyids):
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "threshold exceeds the number of authorized keys",
                path=f"{path}.threshold",
            )
        roles[role] = _RoleDefinition(keyids=keyids, threshold=threshold)

    return _new_trusted_root(
        version=version,
        expires=expires,
        canonical_sha256=hashlib.sha256(envelope.raw).hexdigest(),
        keys=keys,
        roles=roles,
    )


def _verify_threshold(
    envelope: _Envelope,
    root: TrustedRoot,
    role_name: str,
    *,
    strict_signers: bool,
) -> None:
    role = root._roles[role_name]
    authorized = set(role.keyids)
    payload = canonical_json_bytes(envelope.signed)
    verified: set[str] = set()
    for signature in envelope.signatures:
        public_bytes = root._keys.get(signature.keyid)
        if public_bytes is None:
            if strict_signers:
                _fail(
                    DistributionErrorCode.UNKNOWN_KEY,
                    f"signature uses unknown key {signature.keyid}",
                    path="$.signatures",
                )
            continue
        if signature.keyid not in authorized:
            if strict_signers:
                _fail(
                    DistributionErrorCode.UNAUTHORIZED_KEY,
                    f"key {signature.keyid} is not authorized for role {role_name}",
                    path="$.signatures",
                )
            continue
        try:
            Ed25519PublicKey.from_public_bytes(public_bytes).verify(
                signature.signature, payload
            )
        except (InvalidSignature, ValueError):
            _fail(
                DistributionErrorCode.INVALID_SIGNATURE,
                f"invalid {role_name} signature from {signature.keyid}",
                path="$.signatures",
            )
        verified.add(signature.keyid)
    if len(verified) < role.threshold:
        _fail(
            DistributionErrorCode.THRESHOLD_NOT_MET,
            f"{role_name} needs {role.threshold} distinct valid signatures; got {len(verified)}",
            path="$.signatures",
        )


def load_trusted_root(
    metadata: bytes | str,
    *,
    now: datetime,
    trusted_sha256: str | None = None,
    minimum_version: int = 0,
) -> TrustedRoot:
    """Load a digest-pinned root supplied through an out-of-band channel.

    Expiration is intentionally not checked while loading a persisted trust
    anchor: an expired root must remain usable to authenticate consecutive
    intermediate rotations.  The final root is checked by :func:`verify_release`.
    """

    _utc_now(now)
    pinned_digest = _sha256(trusted_sha256, "trusted_sha256")
    if (
        isinstance(minimum_version, bool)
        or not isinstance(minimum_version, int)
        or minimum_version < 0
    ):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR, "minimum_version must be non-negative"
        )
    envelope = _parse_envelope(metadata)
    actual_digest = hashlib.sha256(envelope.raw).hexdigest()
    if not hmac.compare_digest(pinned_digest, actual_digest):
        _fail(
            DistributionErrorCode.ROOT_PIN_MISMATCH,
            "bootstrap root does not match its out-of-band SHA-256 pin",
            path="trusted_sha256",
        )
    root = _parse_root(envelope)
    if root.version < minimum_version:
        _fail(
            DistributionErrorCode.ROOT_ROLLBACK,
            f"root version {root.version} is below trusted version {minimum_version}",
        )
    # A root envelope retained after a verified key rotation may still carry
    # signatures from the *previous* root threshold. Those keys are
    # intentionally absent from the new root's key map, but the exact envelope
    # is already authenticated by the caller's out-of-band/local digest pin.
    # Ignore non-current signatures here and require the current root threshold;
    # rotation itself remains strict about the union of old/new authorized keys.
    _verify_threshold(envelope, root, "root", strict_signers=False)
    return root


def rotate_trusted_root(
    current: TrustedRoot,
    metadata: bytes | str,
    *,
    now: datetime,
    prior_versions: TrustedVersions | None = None,
) -> RootRotationResult:
    """Verify one root rotation and return its atomic persistence unit.

    Callers persist the candidate root bytes/pin and ``trusted_versions`` from
    the result in one transaction.  This preserves key-rotation invalidations
    across crashes and makes fast-forward recovery durable.
    """

    _utc_now(now)
    if not _is_trusted_root(current):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "current must be a verifier-issued TrustedRoot",
            path="current",
        )
    if not isinstance(prior_versions, TrustedVersions):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "prior_versions must be TrustedVersions",
            path="prior_versions",
        )
    if prior_versions.root > current.version:
        _fail(
            DistributionErrorCode.ROOT_ROLLBACK,
            "current root is older than the persisted rollback state",
            path="current",
        )
    if (
        prior_versions.root == current.version
        and prior_versions.root > 0
        and not hmac.compare_digest(
            prior_versions.root_sha256 or "", current.canonical_sha256
        )
    ):
        _fail(
            DistributionErrorCode.METADATA_EQUIVOCATION,
            "current root changed canonical bytes at the trusted version",
            path="current",
        )
    envelope = _parse_envelope(metadata)
    candidate = _parse_root(envelope)
    if candidate.version <= current.version:
        _fail(
            DistributionErrorCode.ROOT_ROLLBACK,
            f"candidate root version {candidate.version} is not newer than {current.version}",
        )
    if candidate.version != current.version + 1:
        _fail(
            DistributionErrorCode.ROOT_VERSION_GAP,
            f"root rotation must be consecutive; expected {current.version + 1}",
        )

    old_authorized = set(current._roles["root"].keyids)
    new_authorized = set(candidate._roles["root"].keyids)
    all_known = set(current._keys) | set(candidate._keys)
    for signature in envelope.signatures:
        if signature.keyid not in all_known:
            _fail(
                DistributionErrorCode.UNKNOWN_KEY,
                f"root rotation contains unknown signer {signature.keyid}",
                path="$.signatures",
            )
        if signature.keyid not in old_authorized | new_authorized:
            _fail(
                DistributionErrorCode.UNAUTHORIZED_KEY,
                f"key {signature.keyid} is not an old or new root signer",
                path="$.signatures",
            )
    _verify_threshold(envelope, current, "root", strict_signers=False)
    _verify_threshold(envelope, candidate, "root", strict_signers=False)

    invalidated = set(current._invalidated_roles)
    if any(
        current._roles[role] != candidate._roles[role]
        for role in ("timestamp", "snapshot")
    ):
        # These roles bind every downstream metadata envelope.  Resetting the
        # whole non-root chain is what makes key-compromise recovery possible.
        invalidated.update(("timestamp", "snapshot", "targets", "revocations"))
    if current._roles["targets"] != candidate._roles["targets"]:
        invalidated.add("targets")
    if current._roles["revocations"] != candidate._roles["revocations"]:
        invalidated.add("revocations")
    rotated = _new_trusted_root(
        version=candidate.version,
        expires=candidate.expires,
        canonical_sha256=candidate.canonical_sha256,
        keys=candidate._keys,
        roles=candidate._roles,
        invalidated_roles=(role for role in _ROLES if role in invalidated),
    )
    reconciled = reconcile_trusted_versions(rotated, prior_versions)
    state_values: dict[str, Any] = {}
    for role in _ROLES:
        state_values[role] = getattr(reconciled, role)
        state_values[f"{role}_sha256"] = getattr(reconciled, f"{role}_sha256")
    state_values["root"] = rotated.version
    state_values["root_sha256"] = rotated.canonical_sha256
    return RootRotationResult(
        root=rotated,
        trusted_versions=TrustedVersions(**state_values),
    )


def reconcile_trusted_versions(
    root: TrustedRoot, prior: TrustedVersions
) -> TrustedVersions:
    """Apply metadata invalidations accumulated across verified root rotations."""

    if not _is_trusted_root(root):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "root must be a verifier-issued TrustedRoot",
            path="root",
        )
    if not isinstance(prior, TrustedVersions):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "prior must be TrustedVersions",
            path="prior",
        )
    if prior.root < root.version:
        return prior.without(root._invalidated_roles)
    return prior


def _parse_reference(value: Any, path: str) -> _Reference:
    reference = _mapping(value, path)
    _exact_keys(reference, required={"version", "length", "sha256"}, path=path)
    return _Reference(
        version=_version(reference["version"], f"{path}.version"),
        length=_positive_int(reference["length"], f"{path}.length"),
        sha256=_sha256(reference["sha256"], f"{path}.sha256"),
    )


def _parse_timestamp(envelope: _Envelope) -> tuple[int, datetime, _Reference]:
    version, expires = _parse_common_signed(
        envelope.signed, "timestamp", extra_keys={"snapshot"}
    )
    return (
        version,
        expires,
        _parse_reference(envelope.signed["snapshot"], "$.signed.snapshot"),
    )


def _parse_snapshot(
    envelope: _Envelope,
) -> tuple[int, datetime, dict[str, _Reference]]:
    version, expires = _parse_common_signed(
        envelope.signed, "snapshot", extra_keys={"meta"}
    )
    meta = _mapping(envelope.signed["meta"], "$.signed.meta")
    _exact_keys(meta, required={"targets", "revocations"}, path="$.signed.meta")
    return (
        version,
        expires,
        {
            role: _parse_reference(meta[role], f"$.signed.meta.{role}")
            for role in ("targets", "revocations")
        },
    )


def _parse_targets(envelope: _Envelope) -> tuple[int, datetime, dict[str, _Target]]:
    version, expires = _parse_common_signed(
        envelope.signed, "targets", extra_keys={"targets"}
    )
    targets_data = _mapping(envelope.signed["targets"], "$.signed.targets")
    if len(targets_data) > _MAX_TARGETS:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "too many targets",
            path="$.signed.targets",
        )
    targets: dict[str, _Target] = {}
    for target_key, raw_target in targets_data.items():
        path = f"$.signed.targets.{target_key}"
        target_data = _mapping(raw_target, path)
        _exact_keys(
            target_data,
            required={
                "name",
                "version",
                "tree_sha256",
                "contract_sha256",
                "eval_sha256",
                "channel",
                "publisher",
            },
            path=path,
        )
        name = _name(target_data["name"], f"{path}.name")
        target_version = _semver(target_data["version"], f"{path}.version")
        expected_key = f"{name}@{target_version}"
        if target_key != expected_key:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                f"target key must be {expected_key!r}",
                path=path,
            )
        channel = _string(target_data["channel"], f"{path}.channel", maximum=32)
        if not _CHANNEL_RE.fullmatch(channel):
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "invalid channel",
                path=f"{path}.channel",
            )
        publisher = _string(target_data["publisher"], f"{path}.publisher", maximum=128)
        targets[target_key] = _Target(
            name=name,
            version=target_version,
            tree_sha256=_sha256(target_data["tree_sha256"], f"{path}.tree_sha256"),
            contract_sha256=_sha256(
                target_data["contract_sha256"], f"{path}.contract_sha256"
            ),
            eval_sha256=_sha256(target_data["eval_sha256"], f"{path}.eval_sha256"),
            channel=channel,
            publisher=publisher,
        )
    return version, expires, targets


def _parse_revocations(
    envelope: _Envelope,
) -> tuple[int, datetime, tuple[_Revocation, ...]]:
    version, expires = _parse_common_signed(
        envelope.signed, "revocations", extra_keys={"revocations"}
    )
    records_data = _list(
        envelope.signed["revocations"],
        "$.signed.revocations",
        maximum=_MAX_REVOCATIONS,
    )
    records: list[_Revocation] = []
    for index, raw_record in enumerate(records_data):
        path = f"$.signed.revocations[{index}]"
        record = _mapping(raw_record, path)
        if "kind" not in record:
            _fail(DistributionErrorCode.SCHEMA_ERROR, "missing field: kind", path=path)
        kind = _string(record["kind"], f"{path}.kind", maximum=32)
        reason: str | None = None
        if "reason" in record:
            reason = _string(
                record["reason"], f"{path}.reason", maximum=_MAX_REASON_BYTES
            )
        if kind == "name_version":
            _exact_keys(
                record,
                required={"kind", "name", "version"},
                optional={"reason"},
                path=path,
            )
            records.append(
                _Revocation(
                    kind=kind,
                    name=_name(record["name"], f"{path}.name"),
                    version=_semver(record["version"], f"{path}.version"),
                    sha256=None,
                    reason=reason,
                )
            )
        elif kind == "digest":
            _exact_keys(
                record, required={"kind", "sha256"}, optional={"reason"}, path=path
            )
            records.append(
                _Revocation(
                    kind=kind,
                    name=None,
                    version=None,
                    sha256=_sha256(record["sha256"], f"{path}.sha256"),
                    reason=reason,
                )
            )
        elif kind == "minimum_safe_version":
            _exact_keys(
                record,
                required={"kind", "name", "version"},
                optional={"reason"},
                path=path,
            )
            records.append(
                _Revocation(
                    kind=kind,
                    name=_name(record["name"], f"{path}.name"),
                    version=_semver(record["version"], f"{path}.version"),
                    sha256=None,
                    reason=reason,
                )
            )
        else:
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                f"unknown revocation kind {kind!r}",
                path=f"{path}.kind",
            )
    return version, expires, tuple(records)


def _check_reference(
    reference: _Reference,
    envelope: _Envelope,
    actual_version: int,
    *,
    role: str,
) -> None:
    if reference.version != actual_version:
        _fail(
            DistributionErrorCode.METADATA_VERSION_MISMATCH,
            f"{role} reference version {reference.version} does not match {actual_version}",
            path=role,
        )
    if reference.length != len(envelope.raw):
        _fail(
            DistributionErrorCode.METADATA_LENGTH_MISMATCH,
            f"{role} reference length {reference.length} does not match {len(envelope.raw)}",
            path=role,
        )
    actual_digest = hashlib.sha256(envelope.raw).hexdigest()
    if reference.sha256 != actual_digest:
        _fail(
            DistributionErrorCode.METADATA_HASH_MISMATCH,
            f"{role} reference digest does not match its envelope",
            path=role,
        )


def _semver_parts(value: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = _SEMVER_RE.fullmatch(value)
    if match is None:  # all public callers validate before reaching this helper
        raise AssertionError(f"unvalidated SemVer {value!r}")
    core = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else None
    return core, prerelease


def _compare_semver(left: str, right: str) -> int:
    left_core, left_pre = _semver_parts(left)
    right_core, right_pre = _semver_parts(right)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if left_pre is None or right_pre is None:
        if left_pre is right_pre:
            return 0
        return 1 if left_pre is None else -1
    for left_item, right_item in zip(left_pre, right_pre, strict=False):
        if left_item == right_item:
            continue
        left_numeric = left_item.isdigit()
        right_numeric = right_item.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_item) < int(right_item) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_item < right_item else 1
    if len(left_pre) == len(right_pre):
        return 0
    return -1 if len(left_pre) < len(right_pre) else 1


def _revocation_decision(
    target: _Target, records: tuple[_Revocation, ...]
) -> RevocationDecision:
    minimum: _Revocation | None = None
    for record in records:
        if (
            record.kind == "name_version"
            and record.name == target.name
            and record.version == target.version
        ):
            return RevocationDecision(True, "name_version", record.reason)
        if record.kind == "digest" and record.sha256 == target.tree_sha256:
            return RevocationDecision(True, "digest", record.reason)
        if record.kind == "minimum_safe_version" and record.name == target.name:
            if (
                minimum is None
                or _compare_semver(record.version or "", minimum.version or "") > 0
            ):
                minimum = record
    if (
        minimum is not None
        and _compare_semver(target.version, minimum.version or "") < 0
    ):
        return RevocationDecision(
            True,
            "minimum_safe_version",
            minimum.reason,
            minimum_safe_version=minimum.version,
        )
    return RevocationDecision(
        False,
        minimum_safe_version=minimum.version if minimum is not None else None,
    )


def _check_rollbacks(actual: TrustedVersions, prior: TrustedVersions) -> None:
    for role in _ROLES:
        actual_value = getattr(actual, role)
        trusted_value = getattr(prior, role)
        if actual_value < trusted_value:
            code = (
                DistributionErrorCode.ROOT_ROLLBACK
                if role == "root"
                else DistributionErrorCode.METADATA_ROLLBACK
            )
            _fail(
                code,
                f"{role} version {actual_value} is below trusted version {trusted_value}",
                path=role,
            )
        if actual_value == trusted_value and trusted_value > 0:
            actual_digest = getattr(actual, f"{role}_sha256")
            trusted_digest = getattr(prior, f"{role}_sha256")
            if not hmac.compare_digest(actual_digest or "", trusted_digest or ""):
                _fail(
                    DistributionErrorCode.METADATA_EQUIVOCATION,
                    f"{role} version {actual_value} changed canonical bytes",
                    path=role,
                )


def _install_proof_key(value: Any, path: str = "receipt_key") -> bytes:
    if not isinstance(value, bytes) or len(value) != _INSTALL_PROOF_KEY_BYTES:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            f"must be exactly {_INSTALL_PROOF_KEY_BYTES} bytes",
            path=path,
        )
    return value


def _trusted_state_payload(state: TrustedVersions) -> dict[str, Any]:
    return {
        role: {
            "version": getattr(state, role),
            "sha256": getattr(state, f"{role}_sha256"),
        }
        for role in _ROLES
    }


def issue_installed_release_proof(
    release: VerifiedRelease,
    *,
    receipt_key: bytes,
    installed_tree_sha256: str,
) -> bytes:
    """Issue a durable local HMAC proof after measuring an installed tree.

    ``receipt_key`` must be generated and persisted by the trusted caller; it
    must never be stored beside the proof.  A proof is useful only together
    with a fresh measurement of the installed tree passed to
    :func:`verify_release`.
    """

    if not _is_verifier_issued_release(release):
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "release was not issued by this verifier",
            path="release",
        )
    key = _install_proof_key(receipt_key)
    measured_digest = _sha256(installed_tree_sha256, "installed_tree_sha256")
    if not hmac.compare_digest(measured_digest, release.tree_sha256):
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "installed tree does not match the verified release",
            path="installed_tree_sha256",
        )
    verified_at = _utc_now(release.verified_at)
    try:
        verified_at_epoch = int(verified_at.timestamp())
    except (OverflowError, OSError, ValueError) as exc:
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            f"verified_at cannot be represented: {exc}",
            path="release.verified_at",
        )
    if verified_at_epoch < 1:
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "verified_at must be after the Unix epoch",
            path="release.verified_at",
        )
    payload = {
        "proof_version": _INSTALL_PROOF_VERSION,
        "installed_tree_sha256": measured_digest,
        "release": {
            "name": release.name,
            "version": release.version,
            "tree_sha256": release.tree_sha256,
            "contract_sha256": release.contract_sha256,
            "eval_sha256": release.eval_sha256,
            "channel": release.channel,
            "publisher": release.publisher,
            "verified_at": verified_at_epoch,
            "trusted": _trusted_state_payload(release.trusted_versions),
        },
    }
    payload_bytes = canonical_json_bytes(payload)
    mac = hmac.new(
        key, _INSTALL_PROOF_DOMAIN + payload_bytes, hashlib.sha256
    ).hexdigest()
    return canonical_json_bytes({"hmac_sha256": mac, "payload": payload})


def bind_verified_release_to_trust_state(
    release: VerifiedRelease,
    *,
    trusted_versions: TrustedVersions,
) -> None:
    """Fail unless *release* belongs to one exact persisted trust state.

    A verifier-issued value is process-global evidence: by itself it does not
    prove that a particular profile-local state store accepted and durably
    advanced the metadata chain.  Proof issuers call this at the persistence
    boundary so a release from another root, profile, or rollback floor cannot
    be re-signed by an unrelated local receipt key.
    """

    if not _is_verifier_issued_release(release):
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "release was not issued by this verifier",
            path="release",
        )
    if type(trusted_versions) is not TrustedVersions:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "trusted_versions must be TrustedVersions",
            path="trusted_versions",
        )
    if release.trusted_versions != trusted_versions:
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "release does not match the exact persisted trust state",
            path="release.trusted_versions",
        )


def bind_verified_release_to_artifact(
    release: VerifiedRelease,
    *,
    name: str,
    tree_sha256: str,
    contract_sha256: str,
    eval_sha256: str,
) -> None:
    """Fail unless local candidate measurements match a verifier-issued release.

    Install surfaces call this after their authoritative, descriptor-safe tree
    scan and contract/eval parsing, immediately before starting a filesystem
    transaction.  Keeping the comparison here prevents a caller from treating
    a merely well-shaped ``VerifiedRelease`` lookalike as trust evidence.
    """

    if not _is_verifier_issued_release(release):
        _fail(
            DistributionErrorCode.ARTIFACT_MISMATCH,
            "release was not issued by this verifier",
            path="release",
        )
    measured_name = _name(name, "name")
    measured_tree = _sha256(tree_sha256, "tree_sha256")
    measured_contract = _sha256(contract_sha256, "contract_sha256")
    measured_eval = _sha256(eval_sha256, "eval_sha256")
    if measured_name != release.name:
        _fail(
            DistributionErrorCode.ARTIFACT_MISMATCH,
            "candidate name does not match the signed release",
            path="name",
        )
    for field, measured, expected in (
        ("tree_sha256", measured_tree, release.tree_sha256),
        ("contract_sha256", measured_contract, release.contract_sha256),
        ("eval_sha256", measured_eval, release.eval_sha256),
    ):
        if not hmac.compare_digest(measured, expected):
            _fail(
                DistributionErrorCode.ARTIFACT_MISMATCH,
                f"candidate {field} does not match the signed release",
                path=field,
            )


def _parse_proof_trusted_state(value: Any, path: str) -> TrustedVersions:
    trusted = _mapping(value, path)
    _exact_keys(trusted, required=set(_ROLES), path=path)
    values: dict[str, Any] = {}
    for role in _ROLES:
        role_path = f"{path}.{role}"
        record = _mapping(trusted[role], role_path)
        _exact_keys(record, required={"version", "sha256"}, path=role_path)
        values[role] = _version(record["version"], f"{role_path}.version")
        values[f"{role}_sha256"] = _sha256(record["sha256"], f"{role_path}.sha256")
    return TrustedVersions(**values)


def _verify_installed_release_proof(
    proof: bytes | str,
    *,
    receipt_key: bytes,
    installed_tree_sha256: str,
    target: _Target,
    trusted_versions: TrustedVersions,
    now: datetime,
) -> None:
    key = _install_proof_key(receipt_key)
    if isinstance(proof, str):
        try:
            proof_size = len(proof.encode("utf-8"))
        except UnicodeEncodeError:
            _fail(
                DistributionErrorCode.INSTALL_PROOF_INVALID,
                "proof is not valid UTF-8 text",
                path="installed_proof",
            )
    elif isinstance(proof, bytes):
        proof_size = len(proof)
    else:
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "must be canonical JSON bytes or text",
            path="installed_proof",
        )
    if proof_size > _INSTALL_PROOF_MAX_BYTES:
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "proof exceeds 16 KiB",
            path="installed_proof",
        )
    _, parsed = _parse_canonical_json(proof)
    envelope = _mapping(parsed, "installed_proof")
    _exact_keys(
        envelope,
        required={"hmac_sha256", "payload"},
        path="installed_proof",
    )
    supplied_mac = _sha256(envelope["hmac_sha256"], "installed_proof.hmac_sha256")
    payload = _mapping(envelope["payload"], "installed_proof.payload")
    expected_mac = hmac.new(
        key,
        _INSTALL_PROOF_DOMAIN + canonical_json_bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied_mac, expected_mac):
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "proof authentication failed",
            path="installed_proof.hmac_sha256",
        )

    _exact_keys(
        payload,
        required={"proof_version", "installed_tree_sha256", "release"},
        path="installed_proof.payload",
    )
    proof_version = _positive_int(
        payload["proof_version"], "installed_proof.payload.proof_version"
    )
    if proof_version != _INSTALL_PROOF_VERSION:
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "unsupported proof version",
            path="installed_proof.payload.proof_version",
        )
    measured_digest = _sha256(installed_tree_sha256, "installed_tree_sha256")
    proof_tree_digest = _sha256(
        payload["installed_tree_sha256"],
        "installed_proof.payload.installed_tree_sha256",
    )
    release = _mapping(payload["release"], "installed_proof.payload.release")
    _exact_keys(
        release,
        required={
            "name",
            "version",
            "tree_sha256",
            "contract_sha256",
            "eval_sha256",
            "channel",
            "publisher",
            "verified_at",
            "trusted",
        },
        path="installed_proof.payload.release",
    )
    proof_name = _name(release["name"], "installed_proof.payload.release.name")
    proof_version = _semver(
        release["version"], "installed_proof.payload.release.version"
    )
    proof_tree = _sha256(
        release["tree_sha256"], "installed_proof.payload.release.tree_sha256"
    )
    proof_contract = _sha256(
        release["contract_sha256"],
        "installed_proof.payload.release.contract_sha256",
    )
    proof_eval = _sha256(
        release["eval_sha256"], "installed_proof.payload.release.eval_sha256"
    )
    proof_channel = _string(
        release["channel"], "installed_proof.payload.release.channel", maximum=32
    )
    if not _CHANNEL_RE.fullmatch(proof_channel):
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            "invalid channel",
            path="installed_proof.payload.release.channel",
        )
    proof_publisher = _string(
        release["publisher"],
        "installed_proof.payload.release.publisher",
        maximum=128,
    )
    verified_at_epoch = _positive_int(
        release["verified_at"], "installed_proof.payload.release.verified_at"
    )
    try:
        verified_at = datetime.fromtimestamp(verified_at_epoch, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        _fail(
            DistributionErrorCode.INSTALL_PROOF_INVALID,
            f"verified_at is invalid: {exc}",
            path="installed_proof.payload.release.verified_at",
        )
    proof_trusted_versions = _parse_proof_trusted_state(
        release["trusted"], "installed_proof.payload.release.trusted"
    )
    if proof_trusted_versions != trusted_versions:
        _fail(
            DistributionErrorCode.OFFLINE_GRACE_DENIED,
            "proof does not match the exact signed metadata trust state",
            path="installed_proof.payload.release.trusted",
        )

    exact_identity = (
        proof_name == target.name
        and proof_version == target.version
        and proof_tree == target.tree_sha256
        and proof_contract == target.contract_sha256
        and proof_eval == target.eval_sha256
        and proof_channel == target.channel
        and proof_publisher == target.publisher
    )
    if not exact_identity:
        _fail(
            DistributionErrorCode.OFFLINE_GRACE_DENIED,
            "proof does not describe the exact signed target",
            path="installed_proof.payload.release",
        )
    if not (
        hmac.compare_digest(measured_digest, proof_tree_digest)
        and hmac.compare_digest(measured_digest, target.tree_sha256)
    ):
        _fail(
            DistributionErrorCode.OFFLINE_GRACE_DENIED,
            "current installed-tree measurement does not match the proof and target",
            path="installed_tree_sha256",
        )
    if verified_at > now + _MAX_CLOCK_SKEW:
        _fail(
            DistributionErrorCode.OFFLINE_GRACE_DENIED,
            "proof verification time is implausibly in the future",
            path="installed_proof.payload.release.verified_at",
        )


def verify_release(
    *,
    root: TrustedRoot,
    timestamp: bytes | str,
    snapshot: bytes | str,
    targets: bytes | str,
    revocations: bytes | str,
    name: str,
    version: str,
    now: datetime,
    prior_versions: TrustedVersions | None = None,
    installed_proof: bytes | str | None = None,
    receipt_key: bytes | None = None,
    installed_tree_sha256: str | None = None,
    offline_grace: OfflineGracePolicy | None = None,
) -> VerifiedRelease:
    """Verify and resolve one exact signed release from an offline metadata set.

    ``prior_versions`` is caller-persisted rollback state.  If any supplied
    metadata is expired, verification fails unless ``offline_grace`` is
    explicit and an authenticated ``installed_proof`` exactly matches both the
    signed target and the caller's fresh ``installed_tree_sha256`` measurement.
    Grace never bypasses signatures, hash/version bindings, rollback checks,
    target lookup, or revocation rules.
    """

    if not _is_trusted_root(root):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "root must be a TrustedRoot",
            path="root",
        )
    if not isinstance(prior_versions, TrustedVersions):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "prior_versions must be TrustedVersions",
            path="prior_versions",
        )
    if offline_grace is not None and not isinstance(offline_grace, OfflineGracePolicy):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "offline_grace must be OfflineGracePolicy",
            path="offline_grace",
        )
    proof_values = (installed_proof, receipt_key, installed_tree_sha256)
    if any(value is not None for value in proof_values) and not all(
        value is not None for value in proof_values
    ):
        _fail(
            DistributionErrorCode.SCHEMA_ERROR,
            "installed_proof, receipt_key, and installed_tree_sha256 must be supplied together",
            path="installed_proof",
        )
    now_utc = _utc_now(now)
    requested_name = _name(name, "name")
    requested_version = _semver(version, "version")
    prior = reconcile_trusted_versions(root, prior_versions)

    timestamp_envelope = _parse_envelope(timestamp)
    snapshot_envelope = _parse_envelope(snapshot)
    targets_envelope = _parse_envelope(targets)
    revocations_envelope = _parse_envelope(revocations)

    timestamp_version, timestamp_expires, snapshot_reference = _parse_timestamp(
        timestamp_envelope
    )
    snapshot_version, snapshot_expires, snapshot_meta = _parse_snapshot(
        snapshot_envelope
    )
    targets_version, targets_expires, target_records = _parse_targets(targets_envelope)
    revocations_version, revocations_expires, revocation_records = _parse_revocations(
        revocations_envelope
    )

    _verify_threshold(timestamp_envelope, root, "timestamp", strict_signers=True)
    _verify_threshold(snapshot_envelope, root, "snapshot", strict_signers=True)
    _verify_threshold(targets_envelope, root, "targets", strict_signers=True)
    _verify_threshold(revocations_envelope, root, "revocations", strict_signers=True)

    _check_reference(
        snapshot_reference, snapshot_envelope, snapshot_version, role="snapshot"
    )
    _check_reference(
        snapshot_meta["targets"], targets_envelope, targets_version, role="targets"
    )
    _check_reference(
        snapshot_meta["revocations"],
        revocations_envelope,
        revocations_version,
        role="revocations",
    )

    current_versions = TrustedVersions(
        root=root.version,
        timestamp=timestamp_version,
        snapshot=snapshot_version,
        targets=targets_version,
        revocations=revocations_version,
        root_sha256=root.canonical_sha256,
        timestamp_sha256=hashlib.sha256(timestamp_envelope.raw).hexdigest(),
        snapshot_sha256=hashlib.sha256(snapshot_envelope.raw).hexdigest(),
        targets_sha256=hashlib.sha256(targets_envelope.raw).hexdigest(),
        revocations_sha256=hashlib.sha256(revocations_envelope.raw).hexdigest(),
    )
    _check_rollbacks(current_versions, prior)

    target_key = f"{requested_name}@{requested_version}"
    target = target_records.get(target_key)
    if target is None:
        _fail(
            DistributionErrorCode.TARGET_NOT_FOUND,
            f"signed targets do not contain {target_key}",
            path="targets",
        )
    decision = _revocation_decision(target, revocation_records)
    if decision.revoked:
        _fail(
            DistributionErrorCode.TARGET_REVOKED,
            f"{target_key} is revoked by {decision.matched_by}",
            path="revocations",
            revocation=decision,
        )

    proof_verified = False
    if installed_proof is not None:
        if receipt_key is None or installed_tree_sha256 is None:  # defensive narrowing
            _fail(
                DistributionErrorCode.SCHEMA_ERROR,
                "installed proof inputs are incomplete",
                path="installed_proof",
            )
        _verify_installed_release_proof(
            installed_proof,
            receipt_key=receipt_key,
            installed_tree_sha256=installed_tree_sha256,
            target=target,
            trusted_versions=current_versions,
            now=now_utc,
        )
        proof_verified = True

    expirations = {
        "root": root.expires,
        "timestamp": timestamp_expires,
        "snapshot": snapshot_expires,
        "targets": targets_expires,
        "revocations": revocations_expires,
    }
    stale_roles = tuple(role for role in _ROLES if now_utc >= expirations[role])
    grace_used = False
    if stale_roles:
        if offline_grace is None:
            code = (
                DistributionErrorCode.METADATA_FREEZE
                if "timestamp" in stale_roles
                else DistributionErrorCode.METADATA_EXPIRED
            )
            _fail(
                code,
                f"expired metadata blocks installs and updates: {', '.join(stale_roles)}",
                path="expires",
            )
        if not proof_verified:
            _fail(
                DistributionErrorCode.OFFLINE_GRACE_DENIED,
                "offline grace requires an authenticated installed-release proof",
                path="installed_proof",
            )
        maximum_staleness = max(now_utc - expirations[role] for role in stale_roles)
        if maximum_staleness > offline_grace.max_staleness:
            _fail(
                DistributionErrorCode.OFFLINE_GRACE_DENIED,
                "metadata exceeds the caller's offline grace window",
                path="expires",
            )
        grace_used = True

    return _new_verified_release(
        name=target.name,
        version=target.version,
        tree_sha256=target.tree_sha256,
        contract_sha256=target.contract_sha256,
        eval_sha256=target.eval_sha256,
        channel=target.channel,
        publisher=target.publisher,
        root_version=root.version,
        timestamp_version=timestamp_version,
        snapshot_version=snapshot_version,
        targets_version=targets_version,
        revocations_version=revocations_version,
        verified_at=now_utc,
        revocation=decision,
        trusted_versions=current_versions,
        offline_grace_used=grace_used,
        stale_roles=stale_roles,
    )


__all__ = [
    "DistributionErrorCode",
    "OfflineGracePolicy",
    "RevocationDecision",
    "RootRotationResult",
    "SPEC_VERSION",
    "SkillDistributionError",
    "TrustedRoot",
    "TrustedVersions",
    "VerifiedRelease",
    "bind_verified_release_to_artifact",
    "bind_verified_release_to_trust_state",
    "canonical_json_bytes",
    "issue_installed_release_proof",
    "load_trusted_root",
    "reconcile_trusted_versions",
    "rotate_trusted_root",
    "verify_release",
]
