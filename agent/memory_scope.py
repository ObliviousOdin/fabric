"""Canonical, prompt-invisible identity for external-memory operations.

This module is deliberately dependency-light and side-effect free except for
reading the current OS security principal when a local caller does not inject
one. Raw OS/platform authority values are hashed immediately and are never
stored on the returned models or included in their repr.

Persistence, provider dispatch, and gateway wiring land in later R2-MEM-03
steps. Keeping the pure identity/transition contract here lets those paths
share one implementation without importing provider plugins or session state.
"""

from __future__ import annotations

import ctypes
import hashlib
import math
import os
import re
import sys
import uuid
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

_MEMORY_NAMESPACE: Final = uuid.UUID("3e6e50dc-df88-5a58-9f4d-c458f9c8b4af")
_MAX_AUTHORITY_CHARS: Final = 1024
_MAX_SESSION_ID_CHARS: Final = 1024
_MAX_OPERATION_ID_CHARS: Final = 256
_MAX_OPERATION_NONCE_CHARS: Final = 256
MAX_MEMORY_TIMESTAMP: Final = 253_402_300_799.0  # 9999-12-31T23:59:59Z
_LOCAL_SURFACES: Final = frozenset({"cli", "tui", "desktop", "dashboard", "cron"})
_PLATFORM_RE: Final = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_PROFILE_ID_RE: Final = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_OPAQUE_ID_RE: Final = re.compile(r"(?:ten|pro|pri|aud)_[0-9a-f]{32}\Z")
_PROVIDER_KEY_RE: Final = re.compile(r"mem_[0-9a-f]{32}\Z")
_TRANSITION_ID_RE: Final = re.compile(r"mtr_[0-9a-f]{32}\Z")
_OPERATION_ID_RE: Final = re.compile(r"(?:mop|mtr)_[0-9a-f]{32}\Z")
_ERROR_CODE_RE: Final = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_UUID5_RE: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)


class MemoryScopeUnavailable(RuntimeError):
    """Fail-closed scope error carrying only a stable, non-sensitive code."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if isinstance(code, str) and _ERROR_CODE_RE.fullmatch(code)
            else "memory_scope_unavailable"
        )
        super().__init__(self.code)

    def __repr__(self) -> str:
        return f"MemoryScopeUnavailable(code={self.code!r})"


class MemoryScopeConflict(RuntimeError):
    """A durable scope transition lost a compare-and-swap race."""

    __slots__ = ("code",)

    def __init__(self, code: str = "memory_scope_conflict") -> None:
        self.code = (
            code
            if isinstance(code, str) and _ERROR_CODE_RE.fullmatch(code)
            else "memory_scope_conflict"
        )
        super().__init__(self.code)

    def __repr__(self) -> str:
        return f"MemoryScopeConflict(code={self.code!r})"


class MemoryScopeTransition(str, Enum):
    NEW_SESSION = "new_session"
    RESET = "reset"
    RESUME = "resume"
    BRANCH = "branch"
    REWIND = "rewind"
    COMPRESSION = "compression"
    DELEGATION = "delegation"
    PROFILE_CHANGE = "profile_change"


class MemoryScopeEffectState(str, Enum):
    PREPARED = "prepared"
    RUNNING = "running"
    APPLIED = "applied"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizedGatewaySource:
    """Post-authorization gateway identity inputs.

    Construction does not itself authorize a sender. Gateway code may create
    this value only after its existing authorization gate succeeds. Keeping a
    separate type prevents the memory builder from accepting display-oriented
    ``SessionSource`` objects accidentally.
    """

    platform: str
    user_id: str | None
    user_id_alt: str | None
    chat_type: str
    scope_id: str | None
    chat_id: str
    thread_id: str | None
    shared_multi_user_session: bool

    def __repr__(self) -> str:
        return "AuthorizedGatewaySource(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class MemoryIdentityAuthority:
    """Opaque authority fields from which a conversation scope is derived."""

    tenant_id: str
    profile_id: str
    principal_id: str
    audience_id: str
    surface: str

    def __post_init__(self) -> None:
        for value, prefix in (
            (self.tenant_id, "ten_"),
            (self.profile_id, "pro_"),
            (self.principal_id, "pri_"),
            (self.audience_id, "aud_"),
        ):
            if (
                not isinstance(value, str)
                or not _OPAQUE_ID_RE.fullmatch(value)
                or not value.startswith(prefix)
            ):
                raise MemoryScopeUnavailable("canonical_identity_invalid")
        if _validate_surface(self.surface) != self.surface:
            raise MemoryScopeUnavailable("surface_unsupported")

    def __repr__(self) -> str:
        return "MemoryIdentityAuthority(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class MemoryScopeV1:
    tenant_id: str
    profile_id: str
    principal_id: str
    audience_id: str
    conversation_id: str
    branch_id: str | None
    parent_conversation_id: str | None
    surface: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        MemoryIdentityAuthority(
            tenant_id=self.tenant_id,
            profile_id=self.profile_id,
            principal_id=self.principal_id,
            audience_id=self.audience_id,
            surface=self.surface,
        )
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise MemoryScopeUnavailable("scope_version_unsupported")
        _validate_uuid5(self.conversation_id, "conversation_identity_invalid")
        if self.branch_id is not None:
            _validate_uuid5(self.branch_id, "branch_identity_invalid")
        if self.parent_conversation_id is not None:
            _validate_uuid5(
                self.parent_conversation_id,
                "parent_conversation_identity_invalid",
            )

    def __repr__(self) -> str:
        return "MemoryScopeV1(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class MemoryScopeBinding:
    session_id: str
    scope: MemoryScopeV1
    revision: int
    updated_at: float

    def __post_init__(self) -> None:
        _validate_session_id(self.session_id)
        if not isinstance(self.scope, MemoryScopeV1):
            raise MemoryScopeUnavailable("canonical_scope_invalid")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision <= 0
        ):
            raise MemoryScopeUnavailable("scope_revision_unavailable")
        _validate_timestamp(self.updated_at)

    def __repr__(self) -> str:
        return "MemoryScopeBinding(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class MemoryScopeTransitionResult:
    transition_id: str
    source_session_id: str
    source_revision: int
    target: MemoryScopeBinding
    reason: MemoryScopeTransition
    effect_state: MemoryScopeEffectState
    effect_error_code: str | None
    created_at: float
    updated_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.transition_id, str) or not _TRANSITION_ID_RE.fullmatch(
            self.transition_id
        ):
            raise MemoryScopeUnavailable("scope_transition_id_invalid")
        _validate_session_id(self.source_session_id)
        if (
            not isinstance(self.source_revision, int)
            or isinstance(self.source_revision, bool)
            or self.source_revision <= 0
        ):
            raise MemoryScopeUnavailable("scope_revision_unavailable")
        if not isinstance(self.target, MemoryScopeBinding):
            raise MemoryScopeUnavailable("canonical_scope_invalid")
        if not isinstance(self.reason, MemoryScopeTransition):
            raise MemoryScopeUnavailable("scope_transition_unsupported")
        if not isinstance(self.effect_state, MemoryScopeEffectState):
            raise MemoryScopeUnavailable("scope_effect_state_invalid")
        if self.effect_error_code is not None and (
            not isinstance(self.effect_error_code, str)
            or not _ERROR_CODE_RE.fullmatch(self.effect_error_code)
        ):
            raise MemoryScopeUnavailable("scope_effect_error_invalid")
        if self.effect_state in {
            MemoryScopeEffectState.PREPARED,
            MemoryScopeEffectState.RUNNING,
            MemoryScopeEffectState.APPLIED,
        }:
            if self.effect_error_code is not None:
                raise MemoryScopeUnavailable("scope_effect_error_invalid")
        elif self.effect_error_code is None:
            raise MemoryScopeUnavailable("scope_effect_error_invalid")
        for timestamp in (self.created_at, self.updated_at):
            _validate_timestamp(timestamp)
        if (
            self.target.updated_at > self.created_at
            or self.updated_at < self.created_at
        ):
            raise MemoryScopeUnavailable("scope_timestamp_invalid")

    def __repr__(self) -> str:
        return "MemoryScopeTransitionResult(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class MemoryInvocationContext:
    scope: MemoryScopeV1
    principal_key: str
    conversation_key: str
    parent_conversation_key: str | None
    operation_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, MemoryScopeV1):
            raise MemoryScopeUnavailable("canonical_scope_invalid")
        for value in (self.principal_key, self.conversation_key):
            if not isinstance(value, str) or not _PROVIDER_KEY_RE.fullmatch(value):
                raise MemoryScopeUnavailable("provider_key_invalid")
        if self.parent_conversation_key is not None and (
            not isinstance(self.parent_conversation_key, str)
            or not _PROVIDER_KEY_RE.fullmatch(self.parent_conversation_key)
        ):
            raise MemoryScopeUnavailable("provider_key_invalid")
        if (
            self.principal_key,
            self.conversation_key,
            self.parent_conversation_key,
        ) != _provider_keys_for_scope(self.scope):
            raise MemoryScopeUnavailable("provider_key_invalid")
        _validate_operation_id(self.operation_id)

    def __repr__(self) -> str:
        return "MemoryInvocationContext(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class MemoryScopeTransitionCommit:
    """Durable transition outcome, including an explicit no-op variant."""

    target: MemoryScopeBinding
    transition: MemoryScopeTransitionResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.target, MemoryScopeBinding):
            raise MemoryScopeUnavailable("canonical_scope_invalid")
        if self.transition is not None:
            if (
                not isinstance(self.transition, MemoryScopeTransitionResult)
                or self.transition.target != self.target
            ):
                raise MemoryScopeUnavailable("scope_transition_result_invalid")

    @property
    def changed(self) -> bool:
        return self.transition is not None

    def __bool__(self) -> bool:
        raise TypeError("MemoryScopeTransitionCommit has no truth value; use .changed")

    def __repr__(self) -> str:
        return "MemoryScopeTransitionCommit(<redacted>)"


def _has_forbidden_control(value: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)


def _validate_timestamp(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 <= value <= MAX_MEMORY_TIMESTAMP
    ):
        raise MemoryScopeUnavailable("scope_timestamp_invalid")
    return float(value)


def _bounded_authority(value: object, *, code: str) -> str:
    if not isinstance(value, str):
        raise MemoryScopeUnavailable(code)
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _MAX_AUTHORITY_CHARS
        or _has_forbidden_control(normalized)
    ):
        raise MemoryScopeUnavailable(code)
    return normalized


def _canonical_profile_name(value: object) -> str:
    raw = _bounded_authority(value, code="profile_identity_unavailable")
    # Keep this contract aligned with fabric_cli.profiles._PROFILE_ID_RE after
    # its ingress normalization. Reject Unicode before lowercasing so aliases
    # such as Kelvin-sign "K" cannot collapse into an ASCII profile id.
    if not raw.isascii():
        raise MemoryScopeUnavailable("profile_identity_unavailable")
    normalized = raw.lower()
    if not _PROFILE_ID_RE.fullmatch(normalized):
        raise MemoryScopeUnavailable("profile_identity_unavailable")
    return normalized


def _has_directory_access(path: Path, *, writable: bool) -> bool:
    mode = os.R_OK | os.X_OK | (os.W_OK if writable else 0)
    try:
        return os.access(path, mode, effective_ids=True)
    except (NotImplementedError, TypeError):
        return os.access(path, mode)


def _darwin_canonical_spelling(path: Path) -> Path:
    """Recover directory-entry spelling without folding case-sensitive paths.

    ``Path.resolve()`` preserves caller spelling on a case-insensitive APFS/HFS
    volume. Walking each already-resolved component and matching its filesystem
    identity yields the directory entry's canonical spelling. On a case-
    sensitive volume each differently-cased path has a different identity, so
    the paths remain distinct.
    """

    if sys.platform != "darwin":
        return path
    anchor = path.anchor
    if not anchor:
        raise OSError("directory path has no anchor")
    current = Path(anchor)
    for part in path.parts[1:]:
        candidate = current / part
        target_stat = candidate.stat()
        match: str | None = None
        with os.scandir(current) as entries:
            for entry in entries:
                try:
                    if os.path.samestat(entry.stat(follow_symlinks=True), target_stat):
                        match = entry.name
                        if entry.name == part:
                            break
                except OSError:
                    continue
        if match is None:
            raise OSError("directory spelling could not be resolved")
        current /= match
    return current


def _canonical_existing_directory(
    value: str | os.PathLike[str], *, writable: bool = False
) -> str:
    try:
        resolved = Path(value).resolve(strict=True)
        if not resolved.is_dir() or not _has_directory_access(
            resolved, writable=writable
        ):
            raise OSError("not a directory")
        resolved = _darwin_canonical_spelling(resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise MemoryScopeUnavailable("profile_unresolved") from None
    return os.path.normcase(os.path.normpath(str(resolved)))


def _hash_parts(prefix: str, domain: str, *parts: str) -> str:
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(b"\0")
    for part in parts:
        encoded = part.encode("utf-8", errors="surrogatepass")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return f"{prefix}{digest.hexdigest()[:32]}"


def _uuid5_parts(domain: str, *parts: str) -> str:
    encoded = "\0".join((domain, *parts))
    return str(uuid.uuid5(_MEMORY_NAMESPACE, encoded))


def _validate_uuid5(value: object, code: str) -> str:
    if not isinstance(value, str) or not _UUID5_RE.fullmatch(value):
        raise MemoryScopeUnavailable(code)
    return value


def _validate_surface(surface: object) -> str:
    if not isinstance(surface, str):
        raise MemoryScopeUnavailable("surface_unsupported")
    normalized = surface.strip().lower()
    if normalized in _LOCAL_SURFACES:
        return normalized
    if normalized.startswith("gateway:") and _PLATFORM_RE.fullmatch(
        normalized.removeprefix("gateway:")
    ):
        return normalized
    raise MemoryScopeUnavailable("surface_unsupported")


def _validate_session_id(session_id: object) -> str:
    if not isinstance(session_id, str):
        raise MemoryScopeUnavailable("conversation_id_unavailable")
    value = session_id.strip()
    if (
        not value
        or value != session_id
        or len(value) > _MAX_SESSION_ID_CHARS
        or _has_forbidden_control(value)
    ):
        raise MemoryScopeUnavailable("conversation_id_unavailable")
    return value


def _validate_operation_id(operation_id: object) -> str:
    if not isinstance(operation_id, str):
        raise MemoryScopeUnavailable("memory_operation_id_unavailable")
    value = operation_id.strip()
    if (
        not value
        or value != operation_id
        or len(value) > _MAX_OPERATION_ID_CHARS
        or _has_forbidden_control(value)
        or not _OPERATION_ID_RE.fullmatch(value)
    ):
        raise MemoryScopeUnavailable("memory_operation_id_unavailable")
    return value


def _windows_process_sid() -> str:
    """Return the current Windows process-token SID without shelling out."""

    token_query = 0x0008
    token_user_class = 1
    error_insufficient_buffer = 122

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HANDLE,)
    kernel32.LocalFree.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    class SidAndAttributes(ctypes.Structure):
        _fields_ = (("sid", wintypes.LPVOID), ("attributes", wintypes.DWORD))

    class TokenUser(ctypes.Structure):
        _fields_ = (("user", SidAndAttributes),)

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        raise MemoryScopeUnavailable("local_principal_unavailable")

    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token,
            token_user_class,
            None,
            0,
            ctypes.byref(required),
        )
        if ctypes.get_last_error() != error_insufficient_buffer or required.value <= 0:
            raise MemoryScopeUnavailable("local_principal_unavailable")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_class,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise MemoryScopeUnavailable("local_principal_unavailable")
        token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        sid_text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            token_user.user.sid, ctypes.byref(sid_text)
        ):
            raise MemoryScopeUnavailable("local_principal_unavailable")
        try:
            value = sid_text.value or ""
        finally:
            if sid_text:
                kernel32.LocalFree(sid_text)
        return _bounded_authority(
            f"windows-sid:{value}", code="local_principal_unavailable"
        )
    finally:
        kernel32.CloseHandle(token)


def _current_os_principal() -> str:
    if sys.platform == "win32":
        return _windows_process_sid()
    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        try:
            uid = int(getuid())
        except (OSError, TypeError, ValueError):
            raise MemoryScopeUnavailable("local_principal_unavailable") from None
        if uid < 0:
            raise MemoryScopeUnavailable("local_principal_unavailable")
        return f"posix-uid:{uid}"
    raise MemoryScopeUnavailable("local_principal_unavailable")


def _identity_from_authorities(
    *,
    deployment_root: str | os.PathLike[str],
    profile_home: str | os.PathLike[str],
    profile_name: str,
    surface: str,
    tenant_authority: str,
    principal_kind: str,
    principal_authority: str,
    audience_authority: str,
) -> MemoryIdentityAuthority:
    canonical_root = _canonical_existing_directory(deployment_root)
    canonical_home = _canonical_existing_directory(profile_home, writable=True)
    canonical_profile = _canonical_profile_name(profile_name)
    canonical_surface = _validate_surface(surface)
    tenant_raw = _bounded_authority(
        tenant_authority, code="tenant_authority_unavailable"
    )
    principal_raw = _bounded_authority(
        principal_authority, code="principal_authority_unavailable"
    )
    audience_raw = _bounded_authority(audience_authority, code="audience_unavailable")
    kind = _bounded_authority(principal_kind, code="principal_authority_unavailable")

    tenant_id = _hash_parts(
        "ten_",
        "fabric.memory.tenant.v1",
        canonical_root,
        tenant_raw,
    )
    return MemoryIdentityAuthority(
        tenant_id=tenant_id,
        profile_id=_hash_parts(
            "pro_",
            "fabric.memory.profile.v1",
            tenant_id,
            canonical_home,
            canonical_profile,
        ),
        principal_id=_hash_parts(
            "pri_",
            "fabric.memory.principal.v1",
            tenant_id,
            kind,
            principal_raw,
        ),
        audience_id=_hash_parts(
            "aud_",
            "fabric.memory.audience.v1",
            tenant_id,
            audience_raw,
        ),
        surface=canonical_surface,
    )


def build_local_memory_identity(
    *,
    deployment_root: str | os.PathLike[str],
    profile_home: str | os.PathLike[str],
    profile_name: str,
    surface: str,
    os_principal: str | None = None,
) -> MemoryIdentityAuthority:
    """Build local single-operator identity from an OS security principal."""

    principal = _current_os_principal() if os_principal is None else os_principal
    try:
        principal = _bounded_authority(principal, code="local_principal_unavailable")
    except MemoryScopeUnavailable:
        raise MemoryScopeUnavailable("local_principal_unavailable") from None
    if _validate_surface(surface) not in _LOCAL_SURFACES:
        raise MemoryScopeUnavailable("surface_unsupported")
    return _identity_from_authorities(
        deployment_root=deployment_root,
        profile_home=profile_home,
        profile_name=profile_name,
        surface=surface,
        tenant_authority=f"local-owner:{principal}",
        principal_kind="local_os",
        principal_authority=principal,
        audience_authority="personal",
    )


def build_gateway_memory_identity(
    *,
    deployment_root: str | os.PathLike[str],
    profile_home: str | os.PathLike[str],
    profile_name: str,
    tenant_authority: str,
    source: AuthorizedGatewaySource,
) -> MemoryIdentityAuthority:
    """Build identity for a gateway source already accepted by authz."""

    if not isinstance(source, AuthorizedGatewaySource):
        raise MemoryScopeUnavailable("gateway_authority_unavailable")
    tenant = _bounded_authority(tenant_authority, code="tenant_authority_unavailable")
    try:
        platform = _bounded_authority(
            source.platform, code="surface_unsupported"
        ).lower()
    except MemoryScopeUnavailable:
        raise MemoryScopeUnavailable("surface_unsupported") from None
    if not _PLATFORM_RE.fullmatch(platform):
        raise MemoryScopeUnavailable("surface_unsupported")
    if not isinstance(source.shared_multi_user_session, bool):
        raise MemoryScopeUnavailable("gateway_authority_unavailable")
    if source.shared_multi_user_session:
        raise MemoryScopeUnavailable("shared_memory_scope_unsupported")

    principal_value = (
        source.user_id_alt if source.user_id_alt not in (None, "") else source.user_id
    )
    if principal_value is None:
        raise MemoryScopeUnavailable("ambiguous_gateway_principal")
    try:
        principal_raw = _bounded_authority(
            principal_value, code="ambiguous_gateway_principal"
        )
    except MemoryScopeUnavailable:
        raise MemoryScopeUnavailable("ambiguous_gateway_principal") from None
    scope_raw = ""
    if source.scope_id not in (None, ""):
        scope_raw = _bounded_authority(source.scope_id, code="audience_unavailable")

    chat_type = _bounded_authority(
        source.chat_type, code="audience_unavailable"
    ).lower()
    if chat_type in {"dm", "private"}:
        audience_raw = f"personal:{platform}:{scope_raw}:{principal_raw}"
    elif chat_type in {"group", "forum", "channel", "thread"}:
        chat_raw = _bounded_authority(source.chat_id, code="audience_unavailable")
        thread_raw = ""
        if source.thread_id not in (None, ""):
            thread_raw = _bounded_authority(
                source.thread_id, code="audience_unavailable"
            )
        audience_raw = f"shared:{platform}:{scope_raw}:{chat_raw}:{thread_raw or '-'}"
    else:
        raise MemoryScopeUnavailable("audience_unavailable")

    return _identity_from_authorities(
        deployment_root=deployment_root,
        profile_home=profile_home,
        profile_name=profile_name,
        surface=f"gateway:{platform}",
        tenant_authority=tenant,
        principal_kind=f"gateway:{platform}:{scope_raw or '-'}",
        principal_authority=principal_raw,
        audience_authority=audience_raw,
    )


def derive_memory_scope(
    identity: MemoryIdentityAuthority,
    *,
    session_id: str,
    branch_id: str | None = None,
    parent_conversation_id: str | None = None,
) -> MemoryScopeV1:
    if not isinstance(identity, MemoryIdentityAuthority):
        raise MemoryScopeUnavailable("canonical_identity_invalid")
    session = _validate_session_id(session_id)
    if branch_id is not None:
        _validate_uuid5(branch_id, "branch_identity_invalid")
    if parent_conversation_id is not None:
        _validate_uuid5(
            parent_conversation_id,
            "parent_conversation_identity_invalid",
        )
    conversation_id = _uuid5_parts(
        "fabric.memory.conversation.v1",
        identity.tenant_id,
        identity.profile_id,
        identity.principal_id,
        identity.audience_id,
        session,
    )
    return MemoryScopeV1(
        tenant_id=identity.tenant_id,
        profile_id=identity.profile_id,
        principal_id=identity.principal_id,
        audience_id=identity.audience_id,
        conversation_id=conversation_id,
        branch_id=branch_id,
        parent_conversation_id=parent_conversation_id,
        surface=identity.surface,
    )


def _identity_from_scope(scope: MemoryScopeV1) -> MemoryIdentityAuthority:
    if not isinstance(scope, MemoryScopeV1):
        raise MemoryScopeUnavailable("canonical_scope_invalid")
    return MemoryIdentityAuthority(
        tenant_id=scope.tenant_id,
        profile_id=scope.profile_id,
        principal_id=scope.principal_id,
        audience_id=scope.audience_id,
        surface=scope.surface,
    )


def _transition_resume(
    current: MemoryScopeV1,
    identity: MemoryIdentityAuthority,
    session: str,
    durable_revision: int | None,
) -> MemoryScopeV1:
    del current, identity, session, durable_revision
    raise MemoryScopeUnavailable("scope_transition_requires_binding")


def _transition_profile_change(
    current: MemoryScopeV1,
    identity: MemoryIdentityAuthority,
    session: str,
    durable_revision: int | None,
) -> MemoryScopeV1:
    del current, identity, session, durable_revision
    raise MemoryScopeUnavailable("scope_profile_rebuild_required")


def _transition_new(
    current: MemoryScopeV1,
    identity: MemoryIdentityAuthority,
    session: str,
    durable_revision: int | None,
) -> MemoryScopeV1:
    del current, durable_revision
    return derive_memory_scope(identity, session_id=session)


def _transition_branch(
    current: MemoryScopeV1,
    identity: MemoryIdentityAuthority,
    session: str,
    durable_revision: int | None,
) -> MemoryScopeV1:
    del durable_revision
    child = derive_memory_scope(
        identity,
        session_id=session,
        parent_conversation_id=current.conversation_id,
    )
    return MemoryScopeV1(
        tenant_id=child.tenant_id,
        profile_id=child.profile_id,
        principal_id=child.principal_id,
        audience_id=child.audience_id,
        conversation_id=child.conversation_id,
        branch_id=_uuid5_parts(
            "fabric.memory.branch.v1",
            child.conversation_id,
            session,
        ),
        parent_conversation_id=current.conversation_id,
        surface=child.surface,
    )


def _transition_rewind(
    current: MemoryScopeV1,
    identity: MemoryIdentityAuthority,
    session: str,
    durable_revision: int | None,
) -> MemoryScopeV1:
    del identity, session
    if (
        not isinstance(durable_revision, int)
        or isinstance(durable_revision, bool)
        or durable_revision <= 0
    ):
        raise MemoryScopeUnavailable("rewind_revision_unavailable")
    return MemoryScopeV1(
        tenant_id=current.tenant_id,
        profile_id=current.profile_id,
        principal_id=current.principal_id,
        audience_id=current.audience_id,
        conversation_id=current.conversation_id,
        branch_id=_uuid5_parts(
            "fabric.memory.rewind.v1",
            current.conversation_id,
            str(durable_revision),
        ),
        parent_conversation_id=current.parent_conversation_id,
        surface=current.surface,
    )


def _transition_compression(
    current: MemoryScopeV1,
    identity: MemoryIdentityAuthority,
    session: str,
    durable_revision: int | None,
) -> MemoryScopeV1:
    del identity, session, durable_revision
    return MemoryScopeV1(
        tenant_id=current.tenant_id,
        profile_id=current.profile_id,
        principal_id=current.principal_id,
        audience_id=current.audience_id,
        conversation_id=current.conversation_id,
        branch_id=current.branch_id,
        parent_conversation_id=current.parent_conversation_id,
        surface=current.surface,
    )


def _transition_delegation(
    current: MemoryScopeV1,
    identity: MemoryIdentityAuthority,
    session: str,
    durable_revision: int | None,
) -> MemoryScopeV1:
    del durable_revision
    return derive_memory_scope(
        identity,
        session_id=session,
        parent_conversation_id=current.conversation_id,
    )


_TransitionHandler = Callable[
    [MemoryScopeV1, MemoryIdentityAuthority, str, int | None], MemoryScopeV1
]
_TRANSITIONS: Final[dict[MemoryScopeTransition, _TransitionHandler]] = {
    MemoryScopeTransition.NEW_SESSION: _transition_new,
    MemoryScopeTransition.RESET: _transition_new,
    MemoryScopeTransition.RESUME: _transition_resume,
    MemoryScopeTransition.BRANCH: _transition_branch,
    MemoryScopeTransition.REWIND: _transition_rewind,
    MemoryScopeTransition.COMPRESSION: _transition_compression,
    MemoryScopeTransition.DELEGATION: _transition_delegation,
    MemoryScopeTransition.PROFILE_CHANGE: _transition_profile_change,
}


def transition_scope(
    current: MemoryScopeV1,
    *,
    reason: MemoryScopeTransition | str,
    new_session_id: str,
    durable_revision: int | None = None,
) -> MemoryScopeV1:
    identity = _identity_from_scope(current)
    session = _validate_session_id(new_session_id)
    try:
        transition = MemoryScopeTransition(reason)
    except (TypeError, ValueError):
        raise MemoryScopeUnavailable("scope_transition_unsupported") from None
    handler = _TRANSITIONS.get(transition)
    if handler is None:
        raise MemoryScopeUnavailable("scope_transition_unsupported")
    if transition is not MemoryScopeTransition.REWIND and durable_revision is not None:
        raise MemoryScopeUnavailable("scope_transition_input_invalid")
    return handler(current, identity, session, durable_revision)


def validate_scope_transition_target(
    source: MemoryScopeV1,
    target: MemoryScopeV1,
    reason: MemoryScopeTransition | str,
    *,
    source_session_id: str,
    target_session_id: str,
    durable_revision: int | None = None,
) -> bool:
    """Validate the lifecycle matrix and return whether it is an explicit no-op."""

    _identity_from_scope(source)
    _identity_from_scope(target)
    if (
        source.tenant_id,
        source.profile_id,
        source.principal_id,
        source.audience_id,
        source.surface,
    ) != (
        target.tenant_id,
        target.profile_id,
        target.principal_id,
        target.audience_id,
        target.surface,
    ):
        raise MemoryScopeUnavailable("scope_authority_mismatch")
    source_session = _validate_session_id(source_session_id)
    target_session = _validate_session_id(target_session_id)
    try:
        transition = MemoryScopeTransition(reason)
    except (TypeError, ValueError):
        raise MemoryScopeUnavailable("scope_transition_unsupported") from None
    if transition in {
        MemoryScopeTransition.RESUME,
        MemoryScopeTransition.PROFILE_CHANGE,
    }:
        raise MemoryScopeUnavailable("scope_transition_unsupported")
    if transition is MemoryScopeTransition.REWIND:
        if source_session != target_session:
            raise MemoryScopeUnavailable("scope_transition_target_invalid")
    else:
        if durable_revision is not None:
            raise MemoryScopeUnavailable("scope_transition_input_invalid")
        if (
            transition
            in {
                MemoryScopeTransition.NEW_SESSION,
                MemoryScopeTransition.RESET,
                MemoryScopeTransition.BRANCH,
                MemoryScopeTransition.DELEGATION,
            }
            and source_session == target_session
        ):
            raise MemoryScopeUnavailable("scope_transition_target_invalid")

    expected = transition_scope(
        source,
        reason=transition,
        new_session_id=target_session,
        durable_revision=durable_revision,
    )
    if target != expected:
        raise MemoryScopeUnavailable("scope_transition_target_invalid")
    return (
        transition is MemoryScopeTransition.COMPRESSION
        and source_session == target_session
    )


def _provider_key(domain: str, *parts: str) -> str:
    return _hash_parts("mem_", f"fabric.memory.provider.{domain}.v1", *parts)


def _provider_keys_for_scope(scope: MemoryScopeV1) -> tuple[str, str, str | None]:
    _identity_from_scope(scope)
    active_branch = scope.branch_id or "root"
    return (
        _provider_key(
            "principal",
            scope.profile_id,
            scope.principal_id,
            scope.audience_id,
        ),
        _provider_key(
            "conversation",
            scope.conversation_id,
            active_branch,
        ),
        (
            _provider_key("parent", scope.parent_conversation_id)
            if scope.parent_conversation_id
            else None
        ),
    )


def memory_operation_id(
    scope: MemoryScopeV1,
    *,
    operation: str,
    nonce: str,
) -> str:
    """Generate an opaque provider idempotency ID from host-owned inputs."""

    _identity_from_scope(scope)
    if not isinstance(operation, str) or not _ERROR_CODE_RE.fullmatch(operation):
        raise MemoryScopeUnavailable("memory_operation_kind_invalid")
    if (
        not isinstance(nonce, str)
        or not nonce
        or nonce != nonce.strip()
        or len(nonce) > _MAX_OPERATION_NONCE_CHARS
        or _has_forbidden_control(nonce)
    ):
        raise MemoryScopeUnavailable("memory_operation_nonce_unavailable")
    return _hash_parts(
        "mop_",
        "fabric.memory.operation.v1",
        str(scope.schema_version),
        scope.tenant_id,
        scope.profile_id,
        scope.principal_id,
        scope.audience_id,
        scope.conversation_id,
        scope.branch_id or "root",
        scope.parent_conversation_id or "root",
        scope.surface,
        operation,
        nonce,
    )


def invocation_context(
    scope: MemoryScopeV1,
    operation_id: str,
) -> MemoryInvocationContext:
    _identity_from_scope(scope)
    operation = _validate_operation_id(operation_id)
    principal_key, conversation_key, parent_key = _provider_keys_for_scope(scope)
    return MemoryInvocationContext(
        scope=scope,
        principal_key=principal_key,
        conversation_key=conversation_key,
        parent_conversation_key=parent_key,
        operation_id=operation,
    )


def transition_operation_id(
    source: MemoryScopeV1,
    target: MemoryScopeV1,
    reason: MemoryScopeTransition | str,
    *,
    source_session_id: str,
    target_session_id: str,
    source_revision: int,
    durable_revision: int | None = None,
) -> str:
    is_noop = validate_scope_transition_target(
        source,
        target,
        reason,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        durable_revision=durable_revision,
    )
    if is_noop:
        raise MemoryScopeUnavailable("scope_transition_noop")
    transition = MemoryScopeTransition(reason)
    if (
        not isinstance(source_revision, int)
        or isinstance(source_revision, bool)
        or source_revision <= 0
    ):
        raise MemoryScopeUnavailable("scope_revision_unavailable")
    source_session = _validate_session_id(source_session_id)
    target_session = _validate_session_id(target_session_id)
    return _hash_parts(
        "mtr_",
        "fabric.memory.transition.v1",
        source_session,
        source.tenant_id,
        source.profile_id,
        source.principal_id,
        source.audience_id,
        source.surface,
        source.conversation_id,
        source.branch_id or "root",
        source.parent_conversation_id or "root",
        str(source_revision),
        target_session,
        target.conversation_id,
        target.branch_id or "root",
        target.parent_conversation_id or "root",
        transition.value,
        str(durable_revision) if durable_revision is not None else "-",
    )


__all__ = [
    "AuthorizedGatewaySource",
    "MAX_MEMORY_TIMESTAMP",
    "MemoryIdentityAuthority",
    "MemoryInvocationContext",
    "MemoryScopeBinding",
    "MemoryScopeConflict",
    "MemoryScopeEffectState",
    "MemoryScopeTransition",
    "MemoryScopeTransitionCommit",
    "MemoryScopeTransitionResult",
    "MemoryScopeUnavailable",
    "MemoryScopeV1",
    "build_gateway_memory_identity",
    "build_local_memory_identity",
    "derive_memory_scope",
    "invocation_context",
    "memory_operation_id",
    "transition_operation_id",
    "transition_scope",
    "validate_scope_transition_target",
]
