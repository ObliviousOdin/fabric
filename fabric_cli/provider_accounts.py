"""Profile-scoped provider ownership and managed-access request state.

This module deliberately depends only on the Python standard library.  It owns
local account-intent metadata, request lifecycle state, and the durable OAuth
generation fence.  It does *not* read credentials, contact providers, or infer
which credential/model route is effective.

Every public operation accepts an explicit profile home.  The home is
canonicalized once, while symlink/junction/reparse redirects at the state and
lock *entries* fail closed.
"""

from __future__ import annotations

import contextlib
import errno
import json
import math
import os
import secrets
import stat
import sys
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

try:  # pragma: no cover - selected by platform
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - selected by platform
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
STATE_FILENAME = "provider-accounts.json"
LOCK_FILENAME = "provider-accounts.lock"
REPAIR_DIRNAME = ".provider-account-repair"
STATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
REPAIR_DIR_MODE = stat.S_IRWXU
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_POLL_SECONDS = 0.05
REQUEST_TTL = timedelta(days=7)
OAUTH_LEASE_TTL = timedelta(minutes=15)
MAX_TERMINAL_HISTORY = 50
MAX_DEVICE_LABEL_BYTES = 120
MAX_STATE_BYTES = 1024 * 1024
MAX_OAUTH_PROFILE_ENTRY_BYTES = 16 * 1024 * 1024
NOTIFICATION_POLICY_KEY = "fabric_default_approver_v1"

ALLOWED_PROVIDER_IDS = frozenset({"openai-codex", "xai-oauth"})
DESIRED_OWNERSHIP_STATES = frozenset({"unselected", "personal", "fabric_managed"})
ACTIVE_REQUEST_STATES = frozenset({"requested", "awaiting"})
HANDOFF_STATES = frozenset({"offered", "launch_attempted_unverified"})
TERMINAL_REQUEST_STATES = frozenset({"cancelled", "expired", "rejected"})
ALLOWED_TRANSITIONS = {
    "requested": frozenset({"awaiting", "cancelled", "expired", "rejected"}),
    "awaiting": frozenset({"cancelled", "expired", "rejected"}),
    "cancelled": frozenset(),
    "expired": frozenset(),
    "rejected": frozenset(),
}
OPERATOR_DECISION_SOURCES = frozenset({"local_operator", "fabric_control_plane"})
_ALL_DECISION_SOURCES = OPERATOR_DECISION_SOURCES | {
    "system_expiry",
    "verified_personal_oauth",
}

_STATE_KEYS = frozenset({"schema_version", "store_instance_id", "providers"})
_PROVIDER_KEYS = frozenset({
    "revision",
    "ownership_epoch",
    "oauth_generation",
    "oauth_lease",
    "oauth_completion",
    "desired_ownership",
    "active_request_id",
    "pruned_terminal_count",
    "requests",
})
_LEASE_KEYS = frozenset({
    "generation",
    "operation_id",
    "store_instance_id",
    "ownership_epoch",
    "active_request_id_at_start",
    "started_at",
    "expires_at",
})
_COMPLETION_KEYS = frozenset({
    "generation",
    "operation_id",
    "store_instance_id",
    "ownership_epoch",
    "active_request_id_at_start",
    "completed_at",
    "intent_matched",
    "superseded_request_id",
})
_REQUEST_BASE_KEYS = frozenset({
    "request_id",
    "provider_id",
    "status",
    "handoff_state",
    "device_label",
    "requested_at",
    "updated_at",
    "expires_at",
    "notification_policy_key",
})
_REQUEST_OPTIONAL_KEYS = frozenset({
    "notification_handoff_at",
    "decision_at",
    "decision_source",
    "decision_reason",
})
_BIDI_FORMATTING_CODEPOINTS = frozenset({
    "\u061c",  # ARABIC LETTER MARK
    "\u200e",  # LEFT-TO-RIGHT MARK
    "\u200f",  # RIGHT-TO-LEFT MARK
    "\u202a",  # LEFT-TO-RIGHT EMBEDDING
    "\u202b",  # RIGHT-TO-LEFT EMBEDDING
    "\u202c",  # POP DIRECTIONAL FORMATTING
    "\u202d",  # LEFT-TO-RIGHT OVERRIDE
    "\u202e",  # RIGHT-TO-LEFT OVERRIDE
    "\u2066",  # LEFT-TO-RIGHT ISOLATE
    "\u2067",  # RIGHT-TO-LEFT ISOLATE
    "\u2068",  # FIRST STRONG ISOLATE
    "\u2069",  # POP DIRECTIONAL ISOLATE
})


class ProviderAccountErrorCode(str, Enum):
    """Allowlisted public domain error codes."""

    INVALID_PROVIDER = "invalid_provider"
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    NOT_AUTHORIZED = "not_authorized"
    STALE_REVISION = "stale_revision"
    ILLEGAL_TRANSITION = "illegal_transition"
    OAUTH_IN_PROGRESS = "oauth_in_progress"
    INVALID_STATE = "invalid_state"
    NEWER_SCHEMA = "newer_schema"
    PATH_REDIRECT = "path_redirect"
    LOCK_TIMEOUT = "lock_timeout"
    IO_UNAVAILABLE = "io_unavailable"
    COMMIT_UNCERTAIN = "commit_uncertain"
    RUNTIME_MODE_UNAVAILABLE = "runtime_mode_unavailable"


_RETRYABLE_ERROR_CODES = frozenset({
    ProviderAccountErrorCode.STALE_REVISION,
    ProviderAccountErrorCode.ILLEGAL_TRANSITION,
    ProviderAccountErrorCode.OAUTH_IN_PROGRESS,
    ProviderAccountErrorCode.LOCK_TIMEOUT,
    ProviderAccountErrorCode.IO_UNAVAILABLE,
})


class ProviderAccountError(Exception):
    """Stable domain failure that never contains paths, state, or raw causes."""

    def __init__(
        self,
        code: ProviderAccountErrorCode | str,
        *,
        retryable: bool | None = None,
    ) -> None:
        try:
            parsed = ProviderAccountErrorCode(code)
        except (TypeError, ValueError) as exc:  # developer misuse, never user input
            raise ValueError("unknown provider-account error code") from exc
        self.code = parsed
        self.retryable = (
            parsed in _RETRYABLE_ERROR_CODES if retryable is None else retryable
        )
        super().__init__(parsed.value)


@dataclass(frozen=True)
class OAuthLease:
    generation: int
    operation_id: str = field(repr=False)
    store_instance_id: str = field(repr=False)
    ownership_epoch: int
    active_request_id_at_start: str | None
    started_at: str
    expires_at: str


@dataclass(frozen=True)
class OAuthCompletion:
    generation: int
    operation_id: str = field(repr=False)
    store_instance_id: str = field(repr=False)
    ownership_epoch: int
    active_request_id_at_start: str | None
    completed_at: str
    intent_matched: bool
    superseded_request_id: str | None


@dataclass(frozen=True)
class ManagedAccessRequest:
    request_id: str
    provider_id: str
    status: str
    handoff_state: str
    device_label: str
    requested_at: str
    updated_at: str
    expires_at: str
    notification_policy_key: str
    notification_handoff_at: str | None = None
    decision_at: str | None = None
    decision_source: str | None = None
    decision_reason: str | None = None


@dataclass(frozen=True)
class AccountSnapshot:
    provider_id: str
    revision: int
    ownership_epoch: int
    oauth_generation: int
    oauth_lease: OAuthLease | None
    oauth_completion: OAuthCompletion | None
    desired_ownership: str
    active_request_id: str | None
    active_request: ManagedAccessRequest | None
    pruned_terminal_count: int
    requests: tuple[ManagedAccessRequest, ...]


@dataclass(frozen=True)
class AccountMutationResult:
    snapshot: AccountSnapshot
    request: ManagedAccessRequest | None = None


@dataclass(frozen=True)
class ManagedRequestResult:
    snapshot: AccountSnapshot
    request: ManagedAccessRequest
    created: bool


@dataclass(frozen=True)
class ProviderAccountFlowOwner:
    """Server-side owner token.  Its canonical path is intentionally not repr'd."""

    canonical_home: Path = field(repr=False)
    home_identity: tuple[int, int] = field(repr=False)


@dataclass(frozen=True)
class PersonalOAuthIntent:
    flow_owner: ProviderAccountFlowOwner
    provider_id: str
    store_instance_id: str = field(repr=False)
    ownership_epoch: int
    active_request_id_at_start: str | None


@dataclass(frozen=True)
class PersonalOAuthStartResult:
    snapshot: AccountSnapshot
    intent: PersonalOAuthIntent

    @property
    def flow_owner(self) -> ProviderAccountFlowOwner:
        return self.intent.flow_owner

    @property
    def ownership_epoch(self) -> int:
        return self.intent.ownership_epoch

    @property
    def active_request_id_at_start(self) -> str | None:
        return self.intent.active_request_id_at_start


@dataclass(frozen=True)
class OAuthLeaseResult:
    snapshot: AccountSnapshot
    lease: OAuthLease
    takeover: bool

    @property
    def generation(self) -> int:
        return self.lease.generation


@dataclass(frozen=True)
class OAuthCompletionResult:
    snapshot: AccountSnapshot
    operation_id: str = field(repr=False)
    superseded_request_id: str | None
    intent_matched: bool
    replayed: bool


@dataclass(frozen=True)
class RepairResult:
    """Safe result for one confirmed, profile-scoped store reset.

    The backup path and prior bytes are deliberately absent.  A successful
    return means the replacement store is valid and contains no provider
    records; ``backup_created`` says only whether an existing state file was
    preserved first.
    """

    schema_version: int
    backup_created: bool


def _raise(
    code: ProviderAccountErrorCode, *, retryable: bool | None = None
) -> NoReturn:
    error = ProviderAccountError(code, retryable=retryable)
    try:
        raise error from None
    finally:
        # ``raise ... from None`` suppresses display of an active low-level
        # exception, but Python still assigns it to ``__context__``.  Clear it
        # during unwind so even programmatic traceback serialization cannot
        # recover raw JSON, paths, callback failures, or OS error text.
        error.__context__ = None


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _require_nonnegative_int(value: object) -> int:
    if not _is_nonnegative_int(value):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    return value


def _require_provider_id(provider_id: object) -> str:
    if not isinstance(provider_id, str) or provider_id not in ALLOWED_PROVIDER_IDS:
        _raise(ProviderAccountErrorCode.INVALID_PROVIDER)
    return provider_id


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _coerce_utc_now(value: datetime | None = None) -> datetime:
    current = _utc_now() if value is None else value
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    return current.astimezone(timezone.utc).replace(microsecond=0)


def _format_timestamp(value: datetime) -> str:
    return (
        value
        .astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    parsed = parsed.astimezone(timezone.utc)
    if _format_timestamp(parsed) != value:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    return parsed


def _is_redirect_stat(path: Path, result: os.stat_result) -> bool:
    if stat.S_ISLNK(result.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(result, "st_file_attributes", 0)
    if attributes & reparse_flag:
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            return bool(isjunction(path))
        except OSError:
            return True
    return False


@dataclass(frozen=True)
class _PinnedHome:
    canonical_home: Path
    identity: tuple[int, int]
    dir_fd: int | None = field(default=None, repr=False)
    windows_handles: tuple[int, ...] = field(default=(), repr=False)


_pinned_home_state = threading.local()


def _windows_close_handle(handle: int) -> None:  # pragma: no cover - Windows
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle(ctypes.c_void_p(handle))


def _windows_handle_identity(handle: int) -> tuple[int, int]:  # pragma: no cover
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
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if information.attributes & reparse_flag:
        _raise(ProviderAccountErrorCode.PATH_REDIRECT)
    file_index = (information.file_index_high << 32) | information.file_index_low
    return information.volume_serial, file_index


def _windows_pin_directory_tree(
    canonical_home: Path,
) -> tuple[tuple[int, ...], tuple[int, int]]:  # pragma: no cover - Windows
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

    handles: list[int] = []
    try:
        # FILE_SHARE_DELETE is intentionally omitted, pinning the canonical
        # profile directory against rename/delete for the full operation.
        raw_handle = kernel32.CreateFileW(
            os.fspath(canonical_home),
            file_read_attributes,
            file_share_read | file_share_write,
            None,
            open_existing,
            file_flag_backup_semantics | file_flag_open_reparse_point,
            None,
        )
        handle = ctypes.cast(raw_handle, ctypes.c_void_p).value
        if handle in (None, invalid_handle_value):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        handles.append(handle)
        _windows_handle_identity(handle)
        return tuple(handles), _windows_handle_identity(handles[-1])
    except BaseException:
        for handle in reversed(handles):
            _windows_close_handle(handle)
        raise


def _windows_private_dacl(
    handle: int,
    *,
    apply: bool,
) -> bool:  # pragma: no cover - Windows
    """Apply or validate one protected current-user-only file DACL."""

    import ctypes
    from ctypes import wintypes

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("user", SID_AND_ATTRIBUTES)]

    class ACL(ctypes.Structure):
        _fields_ = [
            ("revision", wintypes.BYTE),
            ("sbz1", wintypes.BYTE),
            ("size", wintypes.WORD),
            ("ace_count", wintypes.WORD),
            ("sbz2", wintypes.WORD),
        ]

    class ACE_HEADER(ctypes.Structure):
        _fields_ = [
            ("ace_type", wintypes.BYTE),
            ("ace_flags", wintypes.BYTE),
            ("ace_size", wintypes.WORD),
        ]

    class ACCESS_ALLOWED_ACE(ctypes.Structure):
        _fields_ = [
            ("header", ACE_HEADER),
            ("mask", wintypes.DWORD),
            ("sid_start", wintypes.DWORD),
        ]

    class ACL_SIZE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("ace_count", wintypes.DWORD),
            ("bytes_in_use", wintypes.DWORD),
            ("bytes_free", wintypes.DWORD),
        ]

    token_query = 0x0008
    token_user_class = 1
    error_insufficient_buffer = 122
    acl_revision = 2
    file_all_access = 0x001F01FF
    se_file_object = 1
    dacl_security_information = 0x00000004
    protected_dacl_security_information = 0x80000000
    se_dacl_protected = 0x1000
    acl_size_information_class = 2
    access_allowed_ace_type = 0

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    token = wintypes.HANDLE()
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.InitializeAcl.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.AddAccessAllowedAceEx.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    advapi32.AddAccessAllowedAceEx.restype = wintypes.BOOL
    advapi32.SetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    security_descriptor = ctypes.c_void_p()
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, token_user_class, None, 0, ctypes.byref(required)
        )
        if ctypes.get_last_error() != error_insufficient_buffer or required.value == 0:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        token_buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_class,
            ctypes.cast(token_buffer, ctypes.c_void_p),
            required.value,
            ctypes.byref(required),
        ):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        user_sid = ctypes.cast(
            token_buffer, ctypes.POINTER(TOKEN_USER)
        ).contents.user.sid
        sid_length = advapi32.GetLengthSid(user_sid)
        if sid_length == 0:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)

        if apply:
            acl_size = (
                ctypes.sizeof(ACL)
                + ctypes.sizeof(ACCESS_ALLOWED_ACE)
                - ctypes.sizeof(wintypes.DWORD)
                + sid_length
            )
            acl_buffer = ctypes.create_string_buffer(acl_size)
            acl_pointer = ctypes.cast(acl_buffer, ctypes.c_void_p)
            if not advapi32.InitializeAcl(acl_pointer, acl_size, acl_revision):
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            if not advapi32.AddAccessAllowedAceEx(
                acl_pointer,
                acl_revision,
                0,
                file_all_access,
                user_sid,
            ):
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            result = advapi32.SetSecurityInfo(
                wintypes.HANDLE(handle),
                se_file_object,
                dacl_security_information | protected_dacl_security_information,
                None,
                None,
                acl_pointer,
                None,
            )
            if result != 0:
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)

        dacl = ctypes.c_void_p()
        result = advapi32.GetSecurityInfo(
            wintypes.HANDLE(handle),
            se_file_object,
            dacl_security_information,
            None,
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(security_descriptor),
        )
        if result != 0 or not dacl.value or not security_descriptor.value:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(
            security_descriptor, ctypes.byref(control), ctypes.byref(revision)
        ):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if not control.value & se_dacl_protected:
            return False
        acl_information = ACL_SIZE_INFORMATION()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(acl_information),
            ctypes.sizeof(acl_information),
            acl_size_information_class,
        ):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if acl_information.ace_count != 1:
            return False
        ace_pointer = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace_pointer)):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(ACCESS_ALLOWED_ACE)).contents
        if (
            ace.header.ace_type != access_allowed_ace_type
            or ace.mask & file_all_access != file_all_access
        ):
            return False
        ace_sid = ctypes.c_void_p(
            ace_pointer.value + ACCESS_ALLOWED_ACE.sid_start.offset
        )
        return bool(advapi32.EqualSid(user_sid, ace_sid))
    finally:
        if security_descriptor.value:
            kernel32.LocalFree(security_descriptor)
        kernel32.CloseHandle(token)


def _windows_private_fd(fd: int, *, apply: bool) -> bool:  # pragma: no cover
    if msvcrt is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    try:
        handle = msvcrt.get_osfhandle(fd)
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    return _windows_private_dacl(handle, apply=apply)


@contextlib.contextmanager
def _windows_current_user_security_attributes():  # pragma: no cover - Windows
    """Build inheritable-ACL-free attributes for one private file creation.

    Applying a DACL after ``os.open`` leaves a small interval where another
    process can inherit the parent directory's broader permissions and retain
    an open handle.  CreateFileW accepts the final protected DACL as part of
    object creation, closing that gap.  The returned descriptor grants full
    access to exactly the current process token's user SID and is never
    inherited by child processes.
    """

    import ctypes
    from ctypes import wintypes

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("user", SID_AND_ATTRIBUTES)]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", wintypes.BOOL),
        ]

    token_query = 0x0008
    token_user_class = 1
    error_insufficient_buffer = 122
    sddl_revision_1 = 1

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
        wintypes.BOOL
    )

    token = wintypes.HANDLE()
    sid_string = wintypes.LPWSTR()
    security_descriptor = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, token_user_class, None, 0, ctypes.byref(required)
        )
        if ctypes.get_last_error() != error_insufficient_buffer or required.value == 0:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        token_buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_class,
            ctypes.cast(token_buffer, ctypes.c_void_p),
            required.value,
            ctypes.byref(required),
        ):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        user_sid = ctypes.cast(
            token_buffer, ctypes.POINTER(TOKEN_USER)
        ).contents.user.sid
        if not advapi32.ConvertSidToStringSidW(user_sid, ctypes.byref(sid_string)):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        # D:P = protected DACL. FA = FILE_ALL_ACCESS. Supplying this descriptor
        # to CreateFileW means no inherited ACE is ever observable on a newly
        # created credential/state/lock entry.
        sddl = f"D:P(A;;FA;;;{sid_string.value})"
        descriptor_size = wintypes.DWORD()
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl,
            sddl_revision_1,
            ctypes.byref(security_descriptor),
            ctypes.byref(descriptor_size),
        ):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        attributes = SECURITY_ATTRIBUTES(
            ctypes.sizeof(SECURITY_ATTRIBUTES),
            security_descriptor,
            False,
        )
        yield attributes
    finally:
        if security_descriptor.value:
            kernel32.LocalFree(security_descriptor)
        if sid_string:
            kernel32.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
        kernel32.CloseHandle(token)


def _windows_open_private_file(
    path: Path,
    *,
    create_new: bool,
    share_delete: bool = False,
    share_write: bool = True,
    open_existing: bool = False,
) -> int:  # pragma: no cover - Windows
    """Open/create a private regular file with all required native rights.

    The returned CRT descriptor owns the CreateFileW handle.  DELETE sharing is
    omitted by default so lock/state/auth entries cannot be swapped while the
    caller validates or writes them. Callers may also omit WRITE sharing to
    freeze exact delivery bytes while an SDK reopens the same path for reading.
    Backup publication may opt into DELETE sharing so its exact staged descriptor
    can remain open across a write-through MoveFileEx rename. Existing OPEN_ALWAYS
    lock entries are re-hardened through a handle that explicitly carries
    WRITE_DAC.
    """

    import ctypes
    from ctypes import wintypes

    if msvcrt is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    generic_read = 0x80000000
    generic_write = 0x40000000
    read_control = 0x00020000
    write_dac = 0x00040000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_share_delete = 0x00000004
    create_new_disposition = 1
    open_existing_disposition = 3
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
    handle: int | None = None
    with _windows_current_user_security_attributes() as attributes:
        raw_handle = kernel32.CreateFileW(
            os.fspath(path),
            generic_read | generic_write | read_control | write_dac,
            file_share_read
            | (file_share_write if share_write else 0)
            | (file_share_delete if share_delete else 0),
            ctypes.byref(attributes),
            (
                create_new_disposition
                if create_new
                else open_existing_disposition
                if open_existing
                else open_always
            ),
            file_attribute_normal | file_flag_open_reparse_point,
            None,
        )
        handle = ctypes.cast(raw_handle, ctypes.c_void_p).value
    if handle in (None, invalid_handle_value):
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    fd: int | None = None
    try:
        _windows_handle_identity(handle)
        if not _windows_private_dacl(handle, apply=True):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        try:
            fd = msvcrt.open_osfhandle(
                handle,
                os.O_RDWR | getattr(os, "O_BINARY", 0),
            )
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        # open_osfhandle transfers handle ownership to the CRT descriptor.
        handle = None
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or getattr(opened, "st_nlink", 1) != 1:
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        result = fd
        fd = None
        return result
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        if handle is not None:
            _windows_close_handle(handle)


def _windows_move_write_through(
    source: Path,
    target: Path,
    *,
    replace_existing: bool,
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
    flags = movefile_write_through
    if replace_existing:
        flags |= movefile_replace_existing
    if not kernel32.MoveFileExW(
        os.fspath(source),
        os.fspath(target),
        flags,
    ):
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)


def _windows_private_directory(
    path: Path,
    *,
    apply: bool,
) -> bool:  # pragma: no cover - Windows
    """Apply or validate the protected current-user DACL on one directory."""

    import ctypes
    from ctypes import wintypes

    file_read_attributes = 0x0080
    read_control = 0x00020000
    write_dac = 0x00040000
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
    desired_access = file_read_attributes | read_control
    if apply:
        desired_access |= write_dac
    raw_handle = kernel32.CreateFileW(
        os.fspath(path),
        desired_access,
        file_share_read | file_share_write,
        None,
        open_existing,
        file_flag_backup_semantics | file_flag_open_reparse_point,
        None,
    )
    handle = ctypes.cast(raw_handle, ctypes.c_void_p).value
    if handle in (None, invalid_handle_value):
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    try:
        _windows_handle_identity(handle)
        return _windows_private_dacl(handle, apply=apply)
    finally:
        _windows_close_handle(handle)


def _pinned_homes() -> dict[str, tuple[_PinnedHome, int]]:
    homes = getattr(_pinned_home_state, "homes", None)
    if homes is None:
        homes = {}
        _pinned_home_state.homes = homes
    return homes


def _canonical_key(path: Path) -> str:
    return os.path.normcase(os.fspath(path))


def _current_pinned_home(path: Path) -> _PinnedHome | None:
    entry = _pinned_homes().get(_canonical_key(path))
    return None if entry is None else entry[0]


def _pin_for_entry(path: Path) -> _PinnedHome | None:
    return _current_pinned_home(path.parent)


@contextlib.contextmanager
def _pin_canonical_home(canonical_home: Path) -> Iterator[_PinnedHome]:
    key = _canonical_key(canonical_home)
    homes = _pinned_homes()
    existing = homes.get(key)
    if existing is not None:
        pinned, depth = existing
        homes[key] = (pinned, depth + 1)
        try:
            yield pinned
        finally:
            homes[key] = (pinned, depth)
        return

    dir_fd: int | None = None
    windows_handles: tuple[int, ...] = ()
    try:
        if os.name == "nt":
            windows_handles, identity = _windows_pin_directory_tree(canonical_home)
            pinned = _PinnedHome(
                canonical_home=canonical_home,
                identity=identity,
                windows_handles=windows_handles,
            )
        else:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            dir_fd = os.open(canonical_home, flags)
            opened = os.fstat(dir_fd)
            current = os.stat(canonical_home, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or not stat.S_ISDIR(current.st_mode)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                _raise(ProviderAccountErrorCode.PATH_REDIRECT)
            _active_lock_fds.add(dir_fd)
            pinned = _PinnedHome(
                canonical_home=canonical_home,
                identity=(opened.st_dev, opened.st_ino),
                dir_fd=dir_fd,
            )
        homes[key] = (pinned, 1)
        try:
            yield pinned
        finally:
            homes.pop(key, None)
    except ProviderAccountError:
        raise
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    finally:
        if dir_fd is not None:
            _active_lock_fds.discard(dir_fd)
            with contextlib.suppress(OSError):
                os.close(dir_fd)
        for handle in reversed(windows_handles):
            _windows_close_handle(handle)


@contextlib.contextmanager
def _pin_child_directory(
    parent: _PinnedHome,
    child_path: Path,
) -> Iterator[_PinnedHome]:
    """Pin one direct child beneath an already pinned canonical directory.

    POSIX opens by ``dir_fd`` so renaming/replacing the profile pathname cannot
    redirect a nested repair backup into a different tree. Windows keeps the
    parent handle open without ``FILE_SHARE_DELETE`` and pins the child with a
    second non-delete-sharing handle before any backup entry is created.
    """

    if child_path.parent != parent.canonical_home:
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    key = _canonical_key(child_path)
    homes = _pinned_homes()
    existing = homes.get(key)
    if existing is not None:
        pinned, depth = existing
        homes[key] = (pinned, depth + 1)
        try:
            yield pinned
        finally:
            homes[key] = (pinned, depth)
        return

    dir_fd: int | None = None
    windows_handles: tuple[int, ...] = ()
    try:
        if os.name == "nt":
            if not parent.windows_handles:
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            windows_handles, identity = _windows_pin_directory_tree(child_path)
            pinned = _PinnedHome(
                canonical_home=child_path,
                identity=identity,
                windows_handles=windows_handles,
            )
        else:
            if parent.dir_fd is None:
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            dir_fd = os.open(child_path.name, flags, dir_fd=parent.dir_fd)
            opened = os.fstat(dir_fd)
            current = os.stat(
                child_path.name,
                dir_fd=parent.dir_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(opened.st_mode)
                or not stat.S_ISDIR(current.st_mode)
                or _is_redirect_stat(child_path, current)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                _raise(ProviderAccountErrorCode.PATH_REDIRECT)
            _active_lock_fds.add(dir_fd)
            pinned = _PinnedHome(
                canonical_home=child_path,
                identity=(opened.st_dev, opened.st_ino),
                dir_fd=dir_fd,
            )
        homes[key] = (pinned, 1)
        try:
            yield pinned
        finally:
            homes.pop(key, None)
    except ProviderAccountError:
        raise
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    finally:
        if dir_fd is not None:
            _active_lock_fds.discard(dir_fd)
            with contextlib.suppress(OSError):
                os.close(dir_fd)
        for handle in reversed(windows_handles):
            _windows_close_handle(handle)


def _entry_stat(path: Path) -> os.stat_result | None:
    try:
        pinned = _pin_for_entry(path)
        if pinned is not None and pinned.dir_fd is not None:
            return os.stat(path.name, dir_fd=pinned.dir_fd, follow_symlinks=False)
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)


def _assert_safe_entry(path: Path, *, allow_missing: bool = True) -> None:
    result = _entry_stat(path)
    if result is None:
        if allow_missing:
            return
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    if _is_redirect_stat(path, result):
        _raise(ProviderAccountErrorCode.PATH_REDIRECT)
    if not stat.S_ISREG(result.st_mode) or getattr(result, "st_nlink", 1) != 1:
        _raise(ProviderAccountErrorCode.PATH_REDIRECT)


def canonical_provider_account_home(home: Path) -> Path:
    """Return one real directory for an explicitly supplied profile home."""

    if not isinstance(home, Path):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    try:
        canonical = home.resolve(strict=True)
        if not canonical.is_dir():
            _raise(ProviderAccountErrorCode.INVALID_INPUT)
    except FileNotFoundError:
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    except ProviderAccountError:
        raise
    except (OSError, RuntimeError):
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    return canonical


def provider_account_state_path(home: Path) -> Path:
    return canonical_provider_account_home(home) / STATE_FILENAME


def provider_account_lock_path(home: Path) -> Path:
    return canonical_provider_account_home(home) / LOCK_FILENAME


def _normalize_device_label(device_label: object) -> str:
    if not isinstance(device_label, str):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    normalized = unicodedata.normalize("NFKC", device_label)
    if "\r" in normalized or "\n" in normalized:
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    pieces: list[str] = []
    pending_space = False
    for character in normalized:
        category = unicodedata.category(character)
        if category.startswith("C") or character in _BIDI_FORMATTING_CODEPOINTS:
            _raise(ProviderAccountErrorCode.INVALID_INPUT)
        if character.isspace():
            pending_space = bool(pieces)
            continue
        if pending_space:
            pieces.append(" ")
            pending_space = False
        pieces.append(character)
    result = "".join(pieces).strip()
    if not result or len(result.encode("utf-8")) > MAX_DEVICE_LABEL_BYTES:
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    return result


def normalize_device_label(device_label: str) -> str:
    """Normalize and validate a user-visible, non-hardware device label."""

    return _normalize_device_label(device_label)


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "store_instance_id": _new_store_instance_id(),
        "providers": {},
    }


def _new_store_instance_id() -> str:
    return "pas_" + secrets.token_hex(16)


def _new_request_id() -> str:
    return "par_" + secrets.token_hex(12)


def _new_oauth_operation_id() -> str:
    return "pao_" + secrets.token_hex(16)


def new_oauth_operation_id() -> str:
    """Mint a caller-known idempotency fence for one OAuth acquisition.

    Trusted coordinators generate this before acquiring a lease so an
    uncertain durability result can be retried without adopting another
    worker's same-intent lease.  Public serializers must never expose it.
    """

    return _new_oauth_operation_id()


def _empty_provider_state() -> dict[str, Any]:
    return {
        "revision": 0,
        "ownership_epoch": 0,
        "oauth_generation": 0,
        "oauth_lease": None,
        "oauth_completion": None,
        "desired_ownership": "unselected",
        "active_request_id": None,
        "pruned_terminal_count": 0,
        "requests": [],
    }


def _provider_state(state: dict[str, Any], provider_id: str) -> dict[str, Any]:
    providers = state["providers"]
    provider = providers.get(provider_id)
    if provider is None:
        provider = _empty_provider_state()
        providers[provider_id] = provider
    return provider


def _existing_provider_state(state: dict[str, Any], provider_id: str) -> dict[str, Any]:
    provider = state["providers"].get(provider_id)
    return _empty_provider_state() if provider is None else provider


def _validate_lease(provider: dict[str, Any], store_instance_id: str) -> None:
    lease = provider["oauth_lease"]
    if lease is None:
        return
    if not isinstance(lease, dict) or frozenset(lease) != _LEASE_KEYS:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    generation = lease["generation"]
    if not _is_nonnegative_int(generation) or generation == 0:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if generation != provider["oauth_generation"]:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if not _is_operation_id(lease["operation_id"]):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if lease["store_instance_id"] != store_instance_id:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if (
        not _is_nonnegative_int(lease["ownership_epoch"])
        or lease["ownership_epoch"] == 0
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    active_request_id_at_start = lease["active_request_id_at_start"]
    if active_request_id_at_start is not None and not _is_request_id(
        active_request_id_at_start
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    started_at = _parse_timestamp(lease["started_at"])
    expires_at = _parse_timestamp(lease["expires_at"])
    if expires_at <= started_at or expires_at - started_at > OAUTH_LEASE_TTL:
        _raise(ProviderAccountErrorCode.INVALID_STATE)


def _is_operation_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 36
        and value.startswith("pao_")
        and all(character in "0123456789abcdef" for character in value[4:])
    )


def _is_request_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 28
        and value.startswith("par_")
        and all(character in "0123456789abcdef" for character in value[4:])
    )


def _is_store_instance_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 36
        and value.startswith("pas_")
        and all(character in "0123456789abcdef" for character in value[4:])
    )


def _validate_completion(provider: dict[str, Any], store_instance_id: str) -> None:
    completion = provider["oauth_completion"]
    if completion is None:
        return
    if not isinstance(completion, dict) or frozenset(completion) != _COMPLETION_KEYS:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    generation = completion["generation"]
    if (
        not _is_nonnegative_int(generation)
        or generation == 0
        or generation != provider["oauth_generation"]
        or not _is_operation_id(completion["operation_id"])
        or completion["store_instance_id"] != store_instance_id
        or not _is_nonnegative_int(completion["ownership_epoch"])
        or completion["ownership_epoch"] == 0
        or not isinstance(completion["intent_matched"], bool)
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    completed_at = _parse_timestamp(completion["completed_at"])
    superseded = completion["superseded_request_id"]
    if superseded is not None and not _is_request_id(superseded):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    active_request_id_at_start = completion["active_request_id_at_start"]
    if active_request_id_at_start is not None and not _is_request_id(
        active_request_id_at_start
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    intent_matched = completion["intent_matched"]
    if superseded is not None and (
        not intent_matched or superseded != active_request_id_at_start
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if (
        intent_matched
        and active_request_id_at_start is not None
        and (superseded != active_request_id_at_start)
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if provider["oauth_lease"] is not None:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if intent_matched and (
        provider["desired_ownership"] != "personal"
        or completion["ownership_epoch"] != provider["ownership_epoch"]
        or provider["active_request_id"] is not None
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if superseded is not None:
        matches = [
            request
            for request in provider["requests"]
            if request.get("request_id") == superseded
        ]
        if (
            len(matches) != 1
            or matches[0].get("status") != "cancelled"
            or matches[0].get("decision_source") != "verified_personal_oauth"
            or _parse_timestamp(matches[0].get("decision_at")) != completed_at
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)


def _validate_request(
    request: object,
    *,
    provider_id: str,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    keys = frozenset(request)
    if not _REQUEST_BASE_KEYS <= keys or not keys <= (
        _REQUEST_BASE_KEYS | _REQUEST_OPTIONAL_KEYS
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    request_id = request["request_id"]
    if not _is_request_id(request_id):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if request["provider_id"] != provider_id:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    status_value = request["status"]
    if not isinstance(status_value, str) or status_value not in (
        ACTIVE_REQUEST_STATES | TERMINAL_REQUEST_STATES
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    handoff_state = request["handoff_state"]
    if not isinstance(handoff_state, str) or handoff_state not in HANDOFF_STATES:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    try:
        normalized_label = _normalize_device_label(request["device_label"])
    except ProviderAccountError:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if normalized_label != request["device_label"]:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if request["notification_policy_key"] != NOTIFICATION_POLICY_KEY:
        _raise(ProviderAccountErrorCode.INVALID_STATE)

    requested_at = _parse_timestamp(request["requested_at"])
    updated_at = _parse_timestamp(request["updated_at"])
    expires_at = _parse_timestamp(request["expires_at"])
    if (
        updated_at < requested_at
        or expires_at <= requested_at
        or expires_at - requested_at != REQUEST_TTL
    ):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if status_value in ACTIVE_REQUEST_STATES and updated_at >= expires_at:
        _raise(ProviderAccountErrorCode.INVALID_STATE)

    notification_at = request.get("notification_handoff_at")
    parsed_notification_at: datetime | None = None
    if handoff_state == "offered":
        if notification_at is not None:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
    else:
        parsed_notification_at = _parse_timestamp(notification_at)
        if not requested_at <= parsed_notification_at <= updated_at:
            _raise(ProviderAccountErrorCode.INVALID_STATE)

    decision_at = request.get("decision_at")
    decision_source = request.get("decision_source")
    decision_reason = request.get("decision_reason")
    parsed_decision_at: datetime | None = None
    if status_value == "requested":
        if any(
            value is not None
            for value in (decision_at, decision_source, decision_reason)
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
    else:
        parsed_decision_at = _parse_timestamp(decision_at)
        if not requested_at <= parsed_decision_at <= updated_at:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if status_value in TERMINAL_REQUEST_STATES and parsed_decision_at != updated_at:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if (
            not isinstance(decision_source, str)
            or decision_source not in _ALL_DECISION_SOURCES
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if (
            status_value == "awaiting"
            and decision_source not in OPERATOR_DECISION_SOURCES
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if status_value == "expired" and decision_source != "system_expiry":
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if status_value == "expired" and (
            parsed_decision_at != expires_at or updated_at != expires_at
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if status_value in {"awaiting", "cancelled", "rejected"} and (
            parsed_decision_at >= expires_at or updated_at >= expires_at
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if (
            status_value == "rejected"
            and decision_source not in OPERATOR_DECISION_SOURCES
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if status_value == "cancelled" and decision_source not in (
            OPERATOR_DECISION_SOURCES | {"verified_personal_oauth"}
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if decision_reason is not None:
            if (
                status_value != "cancelled"
                or decision_source != "verified_personal_oauth"
                or decision_reason != "superseded_by_verified_personal"
            ):
                _raise(ProviderAccountErrorCode.INVALID_STATE)
        if decision_source == "verified_personal_oauth" and (
            status_value != "cancelled"
            or decision_reason != "superseded_by_verified_personal"
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
    recorded_event_times = [requested_at]
    if parsed_notification_at is not None:
        recorded_event_times.append(parsed_notification_at)
    if parsed_decision_at is not None:
        recorded_event_times.append(parsed_decision_at)
    if updated_at != max(recorded_event_times):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    return request


def _validate_state(state: object) -> dict[str, Any]:
    if not isinstance(state, dict):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    version = state.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if version > SCHEMA_VERSION:
        _raise(ProviderAccountErrorCode.NEWER_SCHEMA)
    if version != SCHEMA_VERSION:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if frozenset(state) != _STATE_KEYS:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    providers = state.get("providers")
    if not _is_store_instance_id(state.get("store_instance_id")):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if not isinstance(providers, dict):
        _raise(ProviderAccountErrorCode.INVALID_STATE)

    all_request_ids: set[str] = set()
    for provider_id, provider in providers.items():
        if provider_id not in ALLOWED_PROVIDER_IDS:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if not isinstance(provider, dict) or frozenset(provider) != _PROVIDER_KEYS:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if not _is_nonnegative_int(provider["revision"]) or provider["revision"] == 0:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if not _is_nonnegative_int(provider["ownership_epoch"]):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if not _is_nonnegative_int(provider["oauth_generation"]):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if provider["revision"] < max(
            provider["ownership_epoch"], provider["oauth_generation"]
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        desired_ownership = provider["desired_ownership"]
        if (
            not isinstance(desired_ownership, str)
            or desired_ownership not in DESIRED_OWNERSHIP_STATES
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if not _is_nonnegative_int(provider["pruned_terminal_count"]):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        _validate_lease(provider, state["store_instance_id"])
        requests = provider["requests"]
        if not isinstance(requests, list):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        active_requests: list[dict[str, Any]] = []
        prior_requested_at: datetime | None = None
        terminal_count = 0
        for raw_request in requests:
            request = _validate_request(raw_request, provider_id=provider_id)
            request_id = request["request_id"]
            if request_id in all_request_ids:
                _raise(ProviderAccountErrorCode.INVALID_STATE)
            all_request_ids.add(request_id)
            request_time = _parse_timestamp(request["requested_at"])
            if prior_requested_at is not None and request_time < prior_requested_at:
                _raise(ProviderAccountErrorCode.INVALID_STATE)
            prior_requested_at = request_time
            if request["status"] in ACTIVE_REQUEST_STATES:
                active_requests.append(request)
            else:
                terminal_count += 1
        if terminal_count > MAX_TERMINAL_HISTORY or len(active_requests) > 1:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        active_request_id = provider["active_request_id"]
        if active_request_id is not None and not isinstance(active_request_id, str):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        expected_active_id = (
            active_requests[0]["request_id"] if active_requests else None
        )
        if active_request_id != expected_active_id:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if (
            active_request_id is not None
            and provider["desired_ownership"] == "unselected"
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if desired_ownership == "unselected" and (
            provider["ownership_epoch"] != 0
            or requests
            or provider["oauth_lease"] is not None
            or provider["oauth_completion"] is not None
        ):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if desired_ownership != "unselected" and provider["ownership_epoch"] == 0:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        _validate_completion(provider, state["store_instance_id"])
    return state


def _same_opened_entry(path: Path, opened: os.stat_result) -> bool:
    current = _entry_stat(path)
    if current is None or _is_redirect_stat(path, current):
        return False
    return (
        stat.S_ISREG(current.st_mode)
        and getattr(current, "st_nlink", 1) == 1
        and getattr(opened, "st_nlink", 1) == 1
        and current.st_dev == opened.st_dev
        and current.st_ino == opened.st_ino
    )


def _decode_state_payload(raw: bytes) -> dict[str, Any]:
    """Decode the exact schema with duplicate-key rejection."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        decoded_object: dict[str, Any] = {}
        for key, value in pairs:
            if key in decoded_object:
                _raise(ProviderAccountErrorCode.INVALID_STATE)
            decoded_object[key] = value
        return decoded_object

    try:
        decoded = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except (ValueError, UnicodeError, RecursionError):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    return _validate_state(decoded)


def _read_state(canonical_home: Path) -> dict[str, Any]:
    state_path = canonical_home / STATE_FILENAME
    _assert_safe_entry(state_path)
    if _entry_stat(state_path) is None:
        return _empty_state()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd: int | None = None
    try:
        pinned = _pin_for_entry(state_path)
        if pinned is not None and pinned.dir_fd is not None:
            fd = os.open(state_path.name, flags, dir_fd=pinned.dir_fd)
        else:
            fd = os.open(state_path, flags)
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or getattr(opened, "st_nlink", 1) != 1
            or not _same_opened_entry(state_path, opened)
        ):
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        if os.name != "nt" and stat.S_IMODE(opened.st_mode) != STATE_FILE_MODE:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if os.name == "nt" and not _windows_private_fd(fd, apply=False):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        geteuid = getattr(os, "geteuid", None)
        if geteuid is not None and opened.st_uid != geteuid():
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        handle = os.fdopen(fd, "rb")
        fd = None
        with handle:
            raw = handle.read(MAX_STATE_BYTES + 1)
    except ProviderAccountError:
        raise
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
    if len(raw) > MAX_STATE_BYTES:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    return _decode_state_payload(raw)


def _serialize_state(state: dict[str, Any]) -> bytes:
    _validate_state(state)
    return (
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _fsync_directory(directory: Path) -> None:
    pinned = _current_pinned_home(directory)
    if pinned is not None and pinned.dir_fd is not None:
        try:
            os.fsync(pinned.dir_fd)
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        return
    if pinned is not None and pinned.windows_handles:
        # MoveFileExW(MOVEFILE_WRITE_THROUGH) is the Windows durability
        # boundary; directory handles cannot be fsynced like POSIX dirfds.
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        directory_fd = os.open(directory, flags)
    except OSError as exc:
        if os.name == "nt" and exc.errno in {
            errno.EACCES,
            errno.EINVAL,
            errno.EISDIR,
            errno.ENOTSUP,
        }:
            return
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        if os.name != "nt" or exc.errno not in {
            errno.EBADF,
            errno.EINVAL,
            errno.ENOTSUP,
        }:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    finally:
        os.close(directory_fd)


def _write_state(canonical_home: Path, state: dict[str, Any]) -> None:
    state_path = canonical_home / STATE_FILENAME
    _assert_safe_entry(state_path)
    payload = _serialize_state(state)
    temporary_path = canonical_home / (
        f".{STATE_FILENAME}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    fd: int | None = None
    pinned = _current_pinned_home(canonical_home)
    if pinned is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    temporary_identity: tuple[int, int] | None = None
    replace_attempted = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        if os.name == "nt":
            fd = _windows_open_private_file(temporary_path, create_new=True)
        elif pinned.dir_fd is not None:
            fd = os.open(
                temporary_path.name,
                flags,
                STATE_FILE_MODE,
                dir_fd=pinned.dir_fd,
            )
        else:
            fd = os.open(temporary_path, flags, STATE_FILE_MODE)
        opened = os.fstat(fd)
        temporary_identity = (opened.st_dev, opened.st_ino)
        if not stat.S_ISREG(opened.st_mode) or getattr(opened, "st_nlink", 1) != 1:
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        try:
            os.fchmod(fd, STATE_FILE_MODE)
        except AttributeError:  # pragma: no cover - legacy Windows Python
            pass
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if os.name != "nt" and stat.S_IMODE(os.fstat(fd).st_mode) != STATE_FILE_MODE:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if os.name == "nt" and not _windows_private_fd(fd, apply=False):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _assert_safe_entry(state_path)
        replace_attempted = True
        _atomic_replace_entry(
            temporary_path,
            state_path,
            source_parent=pinned,
            target_parent=pinned,
        )
        _fsync_directory(canonical_home)
        if (
            _entry_identity(state_path) != temporary_identity
            or _entry_identity(temporary_path) is not None
        ):
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        return
    except BaseException as failure:
        if replace_attempted and temporary_identity is not None:
            try:
                state_after = _entry_identity(state_path)
                temporary_after = _entry_identity(temporary_path)
            except BaseException:
                _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
            if state_after == temporary_identity and temporary_after is None:
                # The new state is visible even if the primitive, directory
                # flush, or signal delivery failed afterward. Never invite a
                # blind retry of a potentially non-idempotent mutation.
                with contextlib.suppress(BaseException):
                    _fsync_directory(canonical_home)
                _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
            if temporary_after != temporary_identity:
                _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
            # Definite no-effect replacement attempt. Clean only the exact
            # staged inode while still inside the pre-effect exception path;
            # successful/post-effect returns do no cleanup work at all.
            with contextlib.suppress(OSError, ProviderAccountError):
                _unlink_pinned_entry_if_identity(
                    temporary_path,
                    pinned,
                    temporary_identity,
                )
        if isinstance(failure, OSError):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if isinstance(failure, ProviderAccountError):
            raise
        raise
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        if temporary_identity is not None and not replace_attempted:
            with contextlib.suppress(OSError, ProviderAccountError):
                _unlink_pinned_entry_if_identity(
                    temporary_path,
                    pinned,
                    temporary_identity,
                )


def _read_repair_source_bytes(canonical_home: Path) -> bytes | None:
    """Read one existing private state file without accepting unsafe metadata.

    Repair intentionally refuses oversized input.  Without decoding the entire
    document, it cannot prove that an oversized file is not a valid newer
    schema, and newer schemas must never be overwritten.
    """

    state_path = canonical_home / STATE_FILENAME
    _assert_safe_entry(state_path)
    if _entry_stat(state_path) is None:
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd: int | None = None
    try:
        pinned = _pin_for_entry(state_path)
        if pinned is not None and pinned.dir_fd is not None:
            fd = os.open(state_path.name, flags, dir_fd=pinned.dir_fd)
        else:
            fd = os.open(state_path, flags)
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or getattr(opened, "st_nlink", 1) != 1
            or not _same_opened_entry(state_path, opened)
        ):
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        if os.name != "nt" and stat.S_IMODE(opened.st_mode) != STATE_FILE_MODE:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if os.name == "nt" and not _windows_private_fd(fd, apply=False):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        geteuid = getattr(os, "geteuid", None)
        if geteuid is not None and opened.st_uid != geteuid():
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if opened.st_size > MAX_STATE_BYTES:
            _raise(ProviderAccountErrorCode.INVALID_STATE)

        chunks: list[bytes] = []
        remaining = MAX_STATE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        if len(raw) > MAX_STATE_BYTES:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if (
            after.st_size != opened.st_size
            or getattr(after, "st_mtime_ns", after.st_mtime)
            != getattr(opened, "st_mtime_ns", opened.st_mtime)
            or getattr(after, "st_ctime_ns", after.st_ctime)
            != getattr(opened, "st_ctime_ns", opened.st_ctime)
            or not _same_opened_entry(state_path, opened)
        ):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        return raw
    except ProviderAccountError:
        raise
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)


def _validate_private_repair_directory(path: Path, *, created: bool) -> None:
    result = _entry_stat(path)
    if result is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    if _is_redirect_stat(path, result) or not stat.S_ISDIR(result.st_mode):
        _raise(ProviderAccountErrorCode.PATH_REDIRECT)
    if os.name != "nt" and stat.S_IMODE(result.st_mode) != REPAIR_DIR_MODE:
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and result.st_uid != geteuid():
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    if os.name == "nt" and not _windows_private_directory(path, apply=created):
        _raise(
            ProviderAccountErrorCode.IO_UNAVAILABLE
            if created
            else ProviderAccountErrorCode.INVALID_STATE
        )


@contextlib.contextmanager
def _private_repair_directory(
    canonical_home: Path,
) -> Iterator[tuple[Path, _PinnedHome]]:
    """Create, validate, and pin the private repair directory."""

    pinned_home = _current_pinned_home(canonical_home)
    if pinned_home is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    repair_path = canonical_home / REPAIR_DIRNAME
    created = False
    existing = _entry_stat(repair_path)
    if existing is None:
        try:
            if pinned_home.dir_fd is not None:
                os.mkdir(repair_path.name, REPAIR_DIR_MODE, dir_fd=pinned_home.dir_fd)
            else:
                os.mkdir(repair_path, REPAIR_DIR_MODE)
            created = True
        except FileExistsError:
            # A concurrent non-cooperating creator is accepted only after the
            # same strict private-directory validation below.
            created = False
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)

    if created and os.name != "nt":
        # Do not rely on the process umask to produce the exact private mode.
        try:
            if pinned_home.dir_fd is not None:
                directory_fd = os.open(
                    repair_path.name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=pinned_home.dir_fd,
                )
            else:
                directory_fd = os.open(
                    repair_path,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
            try:
                os.fchmod(directory_fd, REPAIR_DIR_MODE)
            finally:
                os.close(directory_fd)
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)

    _validate_private_repair_directory(repair_path, created=created)
    with _pin_child_directory(pinned_home, repair_path) as pinned_repair:
        _validate_private_repair_directory(repair_path, created=False)
        if created:
            _fsync_directory(repair_path)
            _fsync_directory(canonical_home)
        yield repair_path, pinned_repair


def _unlink_pinned_entry(path: Path, pinned_parent: _PinnedHome) -> None:
    if pinned_parent.dir_fd is not None:
        os.unlink(path.name, dir_fd=pinned_parent.dir_fd)
    else:
        path.unlink()


def _entry_identity(path: Path) -> tuple[int, int] | None:
    result = _entry_stat(path)
    if result is None:
        return None
    return (result.st_dev, result.st_ino)


def _unlink_pinned_entry_if_identity(
    path: Path,
    pinned_parent: _PinnedHome,
    expected_identity: tuple[int, int],
) -> bool:
    """Unlink only the exact entry previously opened by this transaction."""

    if _entry_identity(path) != expected_identity:
        return False
    _unlink_pinned_entry(path, pinned_parent)
    return True


def _posix_move_noreplace(
    source_name: str,
    target_name: str,
    *,
    source_dir_fd: int,
    target_dir_fd: int,
) -> None:
    """Atomically move one entry without replacing the destination.

    Python does not expose Darwin ``renameatx_np(RENAME_EXCL)`` or Linux
    ``renameat2(RENAME_NOREPLACE)``.  Call those native primitives directly and
    fail closed on other POSIX platforms; link-plus-unlink is not an acceptable
    fallback because an interrupted cleanup leaves security-invalid hardlinks.
    """

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source_name)
    target_bytes = os.fsencode(target_name)
    if sys.platform == "darwin":  # pragma: no branch - platform selected
        try:
            rename = libc.renameatx_np
        except AttributeError:
            raise OSError(errno.ENOTSUP, "atomic no-replace rename unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            source_dir_fd,
            source_bytes,
            target_dir_fd,
            target_bytes,
            0x00000004,  # RENAME_EXCL
        )
    elif sys.platform.startswith("linux"):
        try:
            rename = libc.renameat2
        except AttributeError:
            raise OSError(errno.ENOTSUP, "atomic no-replace rename unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            source_dir_fd,
            source_bytes,
            target_dir_fd,
            target_bytes,
            0x00000001,  # RENAME_NOREPLACE
        )
    else:  # pragma: no cover - unsupported POSIX fails closed
        raise OSError(errno.ENOTSUP, "atomic no-replace rename unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _atomic_move_noreplace(
    source: Path,
    target: Path,
    *,
    source_parent: _PinnedHome,
    target_parent: _PinnedHome,
) -> None:
    """Platform-native no-clobber move with no copy or hardlink fallback."""

    if os.name == "nt":
        _windows_move_write_through(source, target, replace_existing=False)
        return
    if source_parent.dir_fd is None or target_parent.dir_fd is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    _posix_move_noreplace(
        source.name,
        target.name,
        source_dir_fd=source_parent.dir_fd,
        target_dir_fd=target_parent.dir_fd,
    )


def _atomic_replace_entry(
    source: Path,
    target: Path,
    *,
    source_parent: _PinnedHome,
    target_parent: _PinnedHome,
) -> None:
    """Atomically replace a transaction-owned reservation with the source."""

    if os.name == "nt":
        _windows_move_write_through(source, target, replace_existing=True)
        return
    if source_parent.dir_fd is None or target_parent.dir_fd is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    os.replace(
        source.name,
        target.name,
        src_dir_fd=source_parent.dir_fd,
        dst_dir_fd=target_parent.dir_fd,
    )


@dataclass(frozen=True)
class OAuthProfileWriteCapability:
    """Directory-bound credential I/O for one fenced OAuth completion.

    This capability is available only while ``commit_current_oauth_generation``
    holds the provider-account lock.  On POSIX, every read/create/replace is
    relative to the *same already-open directory fd* used by account-state
    completion.  On Windows, ``_pin_canonical_home`` keeps the directory tree
    open without ``FILE_SHARE_DELETE`` for the capability's lifetime, so the
    pathname cannot be renamed or replaced underneath the operation.

    Consumers must use both ``read_bytes`` and ``atomic_write_bytes``.  Reading
    through a fresh pathname and writing through this capability would merely
    move the directory-replacement race from the write side to the read side.
    Only direct children are accepted; this is a profile-store capability, not
    a general filesystem primitive.
    """

    _pinned_home: _PinnedHome = field(repr=False)

    @property
    def canonical_home(self) -> Path:
        return self._pinned_home.canonical_home

    def owns(self, path: Path) -> bool:
        if not isinstance(path, Path):
            return False
        try:
            absolute = Path(os.path.abspath(os.fspath(path)))
        except (OSError, TypeError, ValueError):
            return False
        return (
            _canonical_key(absolute.parent) == _canonical_key(self.canonical_home)
            and absolute.name not in {"", ".", ".."}
            and os.sep not in absolute.name
            and (os.altsep is None or os.altsep not in absolute.name)
        )

    def _require_owned(self, path: Path) -> Path:
        if not self.owns(path):
            _raise(ProviderAccountErrorCode.INVALID_INPUT)
        return Path(os.path.abspath(os.fspath(path)))

    def lock_identity(self, path: Path) -> tuple[str, int, int, str]:
        """Stable reentrancy identity for a direct-child advisory lock."""

        entry = self._require_owned(path)
        return (
            "profile-entry",
            self._pinned_home.identity[0],
            self._pinned_home.identity[1],
            os.path.normcase(entry.name),
        )

    def open_lock_file(self, path: Path) -> int:
        """Open one advisory lock through the same pinned directory object."""

        return _open_lock_file(self._require_owned(path))

    def read_bytes(
        self,
        path: Path,
        *,
        max_bytes: int = MAX_OAUTH_PROFILE_ENTRY_BYTES,
    ) -> bytes | None:
        """Read one direct child through the pinned directory object."""

        entry = self._require_owned(path)
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes <= 0
            or max_bytes > MAX_OAUTH_PROFILE_ENTRY_BYTES
        ):
            _raise(ProviderAccountErrorCode.INVALID_INPUT)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        fd: int | None = None
        try:
            if self._pinned_home.dir_fd is not None:
                fd = os.open(entry.name, flags, dir_fd=self._pinned_home.dir_fd)
            else:
                # The pinned Windows directory handles deny rename/delete for
                # the full tree, making this pathname lookup object-stable.
                fd = os.open(entry, flags)
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or getattr(opened, "st_nlink", 1) != 1
            ):
                _raise(ProviderAccountErrorCode.PATH_REDIRECT)
            if self._pinned_home.dir_fd is None and not _same_opened_entry(
                entry, opened
            ):
                _raise(ProviderAccountErrorCode.PATH_REDIRECT)
            handle = os.fdopen(fd, "rb")
            fd = None
            with handle:
                payload = handle.read(max_bytes + 1)
        except FileNotFoundError:
            return None
        except ProviderAccountError:
            raise
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        finally:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        if len(payload) > max_bytes:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        return payload

    def atomic_write_bytes(
        self,
        path: Path,
        payload: bytes,
        *,
        mode: int = STATE_FILE_MODE,
    ) -> None:
        """Durably replace one direct child through the pinned directory."""

        entry = self._require_owned(path)
        if not isinstance(payload, bytes) or len(payload) > MAX_OAUTH_PROFILE_ENTRY_BYTES:
            _raise(ProviderAccountErrorCode.INVALID_INPUT)
        if not isinstance(mode, int) or isinstance(mode, bool) or mode != STATE_FILE_MODE:
            _raise(ProviderAccountErrorCode.INVALID_INPUT)
        temporary = self.canonical_home / (
            f".{entry.name}.oauth.{os.getpid()}.{uuid.uuid4().hex}"
        )
        fd: int | None = None
        published = False
        try:
            _assert_safe_entry(entry)
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            if os.name == "nt":
                fd = _windows_open_private_file(temporary, create_new=True)
            elif self._pinned_home.dir_fd is not None:
                fd = os.open(
                    temporary.name,
                    flags,
                    mode,
                    dir_fd=self._pinned_home.dir_fd,
                )
            else:
                fd = os.open(temporary, flags, mode)
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or getattr(opened, "st_nlink", 1) != 1
            ):
                _raise(ProviderAccountErrorCode.PATH_REDIRECT)
            try:
                os.fchmod(fd, mode)
            except AttributeError:  # pragma: no cover - legacy Windows Python
                pass
            if os.name == "nt" and not _windows_private_fd(fd, apply=True):
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            with os.fdopen(fd, "wb") as handle:
                fd = None
                if handle.write(payload) != len(payload):
                    _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
                handle.flush()
                os.fsync(handle.fileno())
            _atomic_replace_entry(
                temporary,
                entry,
                source_parent=self._pinned_home,
                target_parent=self._pinned_home,
            )
            published = True
            _fsync_directory(self.canonical_home)
        except ProviderAccountError:
            raise
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        finally:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
            if not published:
                try:
                    if self._pinned_home.dir_fd is not None:
                        os.unlink(temporary.name, dir_fd=self._pinned_home.dir_fd)
                    else:
                        temporary.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass


def _reserve_repair_backup(
    repair_path: Path,
    pinned_repair: _PinnedHome,
) -> tuple[Path, tuple[int, int]]:
    """Reserve one unpredictable private destination with O_EXCL."""

    timestamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    for _ in range(16):
        candidate = repair_path / (
            f"{STATE_FILENAME}.{timestamp}.{uuid.uuid4().hex}.bak"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd: int | None = None
        try:
            if pinned_repair.dir_fd is not None:
                fd = os.open(
                    candidate.name,
                    flags,
                    STATE_FILE_MODE,
                    dir_fd=pinned_repair.dir_fd,
                )
            else:
                fd = os.open(candidate, flags, STATE_FILE_MODE)
        except FileExistsError:
            continue
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        opened_identity: tuple[int, int] | None = None
        try:
            opened = os.fstat(fd)
            opened_identity = (opened.st_dev, opened.st_ino)
            if not stat.S_ISREG(opened.st_mode) or getattr(opened, "st_nlink", 1) != 1:
                _raise(ProviderAccountErrorCode.PATH_REDIRECT)
            try:
                os.fchmod(fd, STATE_FILE_MODE)
            except AttributeError:  # pragma: no cover - legacy Windows Python
                pass
            except OSError:
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            if (
                os.name != "nt"
                and stat.S_IMODE(os.fstat(fd).st_mode) != STATE_FILE_MODE
            ):
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            if os.name == "nt" and not _windows_private_fd(fd, apply=True):
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            if not _same_opened_entry(candidate, opened):
                _raise(ProviderAccountErrorCode.PATH_REDIRECT)
            return candidate, opened_identity
        except BaseException:
            if opened_identity is not None:
                with contextlib.suppress(OSError, ProviderAccountError):
                    _unlink_pinned_entry_if_identity(
                        candidate,
                        pinned_repair,
                        opened_identity,
                    )
            raise
        finally:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
    _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)


def _claim_repair_source(
    canonical_home: Path,
    repair_path: Path,
    pinned_repair: _PinnedHome,
) -> Path:
    """Atomically move the current state entry over an O_EXCL reservation."""

    state_path = canonical_home / STATE_FILENAME
    pinned_home = _current_pinned_home(canonical_home)
    if pinned_home is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    backup_path, reservation_identity = _reserve_repair_backup(
        repair_path,
        pinned_repair,
    )
    source_identity = _entry_identity(state_path)
    if source_identity is None:
        with contextlib.suppress(OSError, ProviderAccountError):
            _unlink_pinned_entry_if_identity(
                backup_path,
                pinned_repair,
                reservation_identity,
            )
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    try:
        _atomic_replace_entry(
            state_path,
            backup_path,
            source_parent=pinned_home,
            target_parent=pinned_repair,
        )
        # Make the claim metadata durable inside this helper. If signal delivery
        # occurs after return but before the caller stores ``backup_path``, the
        # original bytes still survive in the durable private backup.
        _fsync_directory(repair_path)
        _fsync_directory(canonical_home)
        backup_identity = _entry_identity(backup_path)
        if backup_identity is None or backup_identity == reservation_identity:
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        return backup_path
    except BaseException as failure:
        try:
            state_after = _entry_identity(state_path)
            backup_after = _entry_identity(backup_path)
        except BaseException:
            # Outcome observation itself failed after a possibly committing
            # primitive. Preserve every path and force manual read-before-decide.
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)

        if backup_after is not None and backup_after != reservation_identity:
            # The replace took effect, or an ambiguous non-reservation entry now
            # occupies the destination. Never delete it. Restore atomically when
            # the canonical state path remains empty; otherwise preserve both it
            # and the concurrent writer's state.
            if state_after is None:
                try:
                    restored = _restore_claimed_repair_source(
                        canonical_home,
                        backup_path,
                        pinned_repair,
                    )
                except BaseException:
                    _raise(
                        ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                        retryable=False,
                    )
                if not restored:
                    try:
                        state_still_missing = _entry_identity(state_path) is None
                    except BaseException:
                        _raise(
                            ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                            retryable=False,
                        )
                    if state_still_missing:
                        _raise(
                            ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                            retryable=False,
                        )
            else:
                try:
                    _fsync_directory(repair_path)
                    _fsync_directory(canonical_home)
                except ProviderAccountError:
                    _raise(
                        ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                        retryable=False,
                    )
        elif backup_after == reservation_identity:
            # Definite transaction-owned placeholder. It contains no source
            # bytes and is the only destination entry safe to remove.
            with contextlib.suppress(OSError, ProviderAccountError):
                _unlink_pinned_entry_if_identity(
                    backup_path,
                    pinned_repair,
                    reservation_identity,
                )
        elif state_after != source_identity:
            # Neither path now identifies the pre-call source. Do not guess at
            # cleanup or report a retryable pre-effect failure.
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)

        if isinstance(failure, OSError):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        raise


def _read_claimed_repair_bytes(
    backup_path: Path,
    pinned_repair: _PinnedHome,
) -> bytes:
    """Read and durably flush the exact entry claimed for reset."""

    _assert_safe_entry(backup_path, allow_missing=False)
    flags = (
        (os.O_RDWR if os.name == "nt" else os.O_RDONLY)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    fd: int | None = None
    try:
        if pinned_repair.dir_fd is not None:
            fd = os.open(backup_path.name, flags, dir_fd=pinned_repair.dir_fd)
        else:
            fd = os.open(backup_path, flags)
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or getattr(opened, "st_nlink", 1) != 1
            or not _same_opened_entry(backup_path, opened)
        ):
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        if os.name != "nt" and stat.S_IMODE(opened.st_mode) != STATE_FILE_MODE:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if os.name == "nt" and not _windows_private_fd(fd, apply=False):
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        geteuid = getattr(os, "geteuid", None)
        if geteuid is not None and opened.st_uid != geteuid():
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if opened.st_size > MAX_STATE_BYTES:
            _raise(ProviderAccountErrorCode.INVALID_STATE)

        chunks: list[bytes] = []
        remaining = MAX_STATE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        if len(raw) > MAX_STATE_BYTES:
            _raise(ProviderAccountErrorCode.INVALID_STATE)
        if (
            after.st_size != opened.st_size
            or getattr(after, "st_mtime_ns", after.st_mtime)
            != getattr(opened, "st_mtime_ns", opened.st_mtime)
            or getattr(after, "st_ctime_ns", after.st_ctime)
            != getattr(opened, "st_ctime_ns", opened.st_ctime)
            or not _same_opened_entry(backup_path, opened)
        ):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        os.fsync(fd)
        return raw
    except ProviderAccountError:
        raise
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)


def _restore_claimed_repair_source(
    canonical_home: Path,
    backup_path: Path,
    pinned_repair: _PinnedHome,
) -> bool:
    """Restore a claimed entry without overwriting a concurrent replacement."""

    state_path = canonical_home / STATE_FILENAME
    pinned_home = _current_pinned_home(canonical_home)
    if pinned_home is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    _assert_safe_entry(backup_path, allow_missing=False)
    backup_identity = _entry_identity(backup_path)
    if backup_identity is None:
        _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
    try:
        _atomic_move_noreplace(
            backup_path,
            state_path,
            source_parent=pinned_repair,
            target_parent=pinned_home,
        )
        _assert_safe_entry(state_path, allow_missing=False)
        _fsync_directory(canonical_home)
        _fsync_directory(backup_path.parent)
        if (
            _entry_identity(state_path) != backup_identity
            or _entry_identity(backup_path) is not None
        ):
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        return True
    except BaseException:
        try:
            state_after = _entry_identity(state_path)
            backup_after = _entry_identity(backup_path)
        except BaseException:
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        if state_after == backup_identity and backup_after is None:
            # The native move committed before reporting an error or delivering
            # an interrupt. Treat restoration as successful after making both
            # affected directories durable; the caller can re-raise its original
            # pre-publication failure with the source safely back in place.
            try:
                _assert_safe_entry(state_path, allow_missing=False)
                _fsync_directory(canonical_home)
                _fsync_directory(backup_path.parent)
            except ProviderAccountError:
                _raise(
                    ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                    retryable=False,
                )
            return True
        if backup_after == backup_identity:
            # Definite no-effect outcome. A concurrent state entry is preserved;
            # with an empty destination the caller escalates to commit_uncertain
            # while this durable backup remains the recovery source.
            return False
        _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)


def _stage_repair_replacement(
    canonical_home: Path,
    state: dict[str, Any],
) -> Path:
    """Create and fsync a private replacement without publishing it."""

    payload = _serialize_state(state)
    temporary_path = canonical_home / (
        f".{STATE_FILENAME}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    pinned_home = _current_pinned_home(canonical_home)
    if pinned_home is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    fd: int | None = None
    complete = False
    opened_identity: tuple[int, int] | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        if pinned_home.dir_fd is not None:
            fd = os.open(
                temporary_path.name,
                flags,
                STATE_FILE_MODE,
                dir_fd=pinned_home.dir_fd,
            )
        else:
            fd = os.open(temporary_path, flags, STATE_FILE_MODE)
        opened = os.fstat(fd)
        opened_identity = (opened.st_dev, opened.st_ino)
        if not stat.S_ISREG(opened.st_mode) or getattr(opened, "st_nlink", 1) != 1:
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        try:
            os.fchmod(fd, STATE_FILE_MODE)
        except AttributeError:  # pragma: no cover - legacy Windows Python
            pass
        except OSError:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if os.name != "nt" and stat.S_IMODE(os.fstat(fd).st_mode) != STATE_FILE_MODE:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if os.name == "nt" and not _windows_private_fd(fd, apply=True):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if not _same_opened_entry(temporary_path, opened):
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            if handle.write(payload) != len(payload):
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
            handle.flush()
            os.fsync(handle.fileno())
        complete = True
        return temporary_path
    except ProviderAccountError:
        raise
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        if not complete and opened_identity is not None:
            with contextlib.suppress(OSError, ProviderAccountError):
                _unlink_pinned_entry_if_identity(
                    temporary_path,
                    pinned_home,
                    opened_identity,
                )


def _publish_repair_replacement(
    canonical_home: Path,
    temporary_path: Path,
) -> None:
    """Publish a staged reset only if no concurrent state entry exists."""

    state_path = canonical_home / STATE_FILENAME
    pinned_home = _current_pinned_home(canonical_home)
    if pinned_home is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    _assert_safe_entry(temporary_path, allow_missing=False)
    temporary_identity = _entry_identity(temporary_path)
    if temporary_identity is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    try:
        _atomic_move_noreplace(
            temporary_path,
            state_path,
            source_parent=pinned_home,
            target_parent=pinned_home,
        )
        _assert_safe_entry(state_path, allow_missing=False)
        _fsync_directory(canonical_home)
        if (
            _entry_identity(state_path) != temporary_identity
            or _entry_identity(temporary_path) is not None
        ):
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        current = _entry_stat(state_path)
        if current is None or getattr(current, "st_nlink", 1) != 1:
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        if not stat.S_ISREG(current.st_mode):
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        if os.name != "nt" and stat.S_IMODE(current.st_mode) != STATE_FILE_MODE:
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        return
    except BaseException as failure:
        try:
            state_after = _entry_identity(state_path)
            temporary_after = _entry_identity(temporary_path)
        except BaseException:
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        if state_after == temporary_identity and temporary_after is None:
            # The reset became observable before the primitive reported failure
            # or delivered an interrupt. Never report a retryable pre-commit
            # error after that point.
            with contextlib.suppress(BaseException):
                _fsync_directory(canonical_home)
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)
        if temporary_after != temporary_identity:
            # The staged source disappeared or changed identity without a
            # verifiable publication outcome. Preserve every observed entry and
            # force read-before-decide recovery.
            _raise(ProviderAccountErrorCode.COMMIT_UNCERTAIN, retryable=False)

        # Definite no-effect outcome: the exact staged inode remains. Cleanup is
        # best-effort and identity-checked; failure can leak a private temp file
        # but can never make the canonical state unreadable.
        with contextlib.suppress(OSError, ProviderAccountError):
            _unlink_pinned_entry_if_identity(
                temporary_path,
                pinned_home,
                temporary_identity,
            )
        if isinstance(failure, OSError):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if isinstance(failure, ProviderAccountError):
            raise
        raise


_thread_lock_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}
_lock_holder = threading.local()
_active_lock_fds: set[int] = set()
_credential_writer_state = threading.local()
_repair_state = threading.local()


def current_oauth_profile_write_capability(
    path: Path | None = None,
) -> OAuthProfileWriteCapability | None:
    """Return the directory-bound capability active in an OAuth writer.

    The capability is deliberately thread-local and absent everywhere except
    the credential callback of a current durable OAuth generation.  Supplying
    ``path`` additionally proves that the requested entry is a direct child of
    that exact pinned profile directory.
    """

    capability = getattr(_credential_writer_state, "write_capability", None)
    if not isinstance(capability, OAuthProfileWriteCapability):
        return None
    if path is not None and not capability.owns(path):
        return None
    return capability


def _reject_credential_writer_reentry() -> None:
    if getattr(_credential_writer_state, "active", False):
        _raise(ProviderAccountErrorCode.OAUTH_IN_PROGRESS)


@contextlib.contextmanager
def _repair_operation_guard() -> Iterator[None]:
    if getattr(_repair_state, "active", False):
        _raise(ProviderAccountErrorCode.INVALID_STATE)
    _repair_state.active = True
    try:
        yield
    finally:
        _repair_state.active = False


def _reset_lock_state_after_fork() -> None:
    """Drop inherited process-local lock state and inherited lock descriptors."""

    global _thread_lock_guard, _thread_locks, _lock_holder, _active_lock_fds
    global _credential_writer_state, _repair_state
    global _pinned_home_state
    for fd in tuple(_active_lock_fds):
        with contextlib.suppress(OSError):
            os.close(fd)
    _thread_lock_guard = threading.Lock()
    _thread_locks = {}
    _lock_holder = threading.local()
    _active_lock_fds = set()
    _credential_writer_state = threading.local()
    _repair_state = threading.local()
    _pinned_home_state = threading.local()


if hasattr(os, "register_at_fork"):  # pragma: no branch - POSIX registration
    os.register_at_fork(after_in_child=_reset_lock_state_after_fork)


def _path_thread_lock(key: str) -> threading.Lock:
    with _thread_lock_guard:
        return _thread_locks.setdefault(key, threading.Lock())


def _holder_depths() -> dict[str, int]:
    depths = getattr(_lock_holder, "depths", None)
    if depths is None:
        depths = {}
        _lock_holder.depths = depths
    return depths


def _open_lock_file(lock_path: Path) -> int:
    _assert_safe_entry(lock_path)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd: int | None = None
    try:
        pinned = _pin_for_entry(lock_path)
        if os.name == "nt":
            fd = _windows_open_private_file(lock_path, create_new=False)
        elif pinned is not None and pinned.dir_fd is not None:
            fd = os.open(
                lock_path.name,
                flags,
                STATE_FILE_MODE,
                dir_fd=pinned.dir_fd,
            )
        else:
            fd = os.open(lock_path, flags, STATE_FILE_MODE)
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or getattr(opened, "st_nlink", 1) != 1
            or not _same_opened_entry(lock_path, opened)
        ):
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        try:
            os.fchmod(fd, STATE_FILE_MODE)
        except AttributeError:  # pragma: no cover - legacy Windows Python
            pass
        if os.name != "nt" and stat.S_IMODE(os.fstat(fd).st_mode) != STATE_FILE_MODE:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if os.name == "nt" and not _windows_private_fd(fd, apply=False):
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if not _same_opened_entry(lock_path, opened):
            _raise(ProviderAccountErrorCode.PATH_REDIRECT)
        if opened.st_size == 0:
            os.write(fd, b" ")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        result = fd
        fd = None
        return result
    except ProviderAccountError:
        raise
    except OSError:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)


def _acquire_kernel_lock(fd: int, deadline: float) -> None:
    if fcntl is None and msvcrt is None:
        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
    while True:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - Windows
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except (BlockingIOError, PermissionError):
            pass
        except OSError as exc:
            contention_errnos = {
                errno.EACCES,
                errno.EAGAIN,
                errno.EWOULDBLOCK,
                getattr(errno, "EDEADLK", errno.EACCES),
                getattr(errno, "EDEADLOCK", errno.EACCES),
            }
            contention_winerrors = {32, 33}  # sharing / lock violation
            if (
                exc.errno not in contention_errnos
                and getattr(exc, "winerror", None) not in contention_winerrors
            ):
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        if time.monotonic() >= deadline:
            _raise(ProviderAccountErrorCode.LOCK_TIMEOUT)
        time.sleep(LOCK_POLL_SECONDS)


def _release_kernel_lock(fd: int) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        # The protected write has already completed.  Closing the descriptor
        # releases the OS lock even if the explicit unlock reports a race.
        pass


@contextlib.contextmanager
def _provider_account_lock_pinned(
    canonical_home: Path,
    pinned_home: _PinnedHome,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    try:
        normalized_timeout = float(timeout_seconds)
    except (OverflowError, TypeError, ValueError):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    if (
        not math.isfinite(normalized_timeout)
        or normalized_timeout <= 0
        or normalized_timeout > threading.TIMEOUT_MAX
    ):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    lock_path = canonical_home / LOCK_FILENAME
    key = f"{pinned_home.identity[0]}:{pinned_home.identity[1]}:{LOCK_FILENAME}"
    depths = _holder_depths()
    if depths.get(key, 0) > 0:
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return

    deadline = time.monotonic() + normalized_timeout
    thread_lock = _path_thread_lock(key)
    remaining = max(0.0, deadline - time.monotonic())
    if not thread_lock.acquire(timeout=remaining):
        _raise(ProviderAccountErrorCode.LOCK_TIMEOUT)
    fd: int | None = None
    try:
        fd = _open_lock_file(lock_path)
        _active_lock_fds.add(fd)
        _acquire_kernel_lock(fd, deadline)
        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)
            _release_kernel_lock(fd)
    finally:
        if fd is not None:
            _active_lock_fds.discard(fd)
            with contextlib.suppress(OSError):
                os.close(fd)
        thread_lock.release()


@contextlib.contextmanager
def _provider_account_lock_canonical(
    canonical_home: Path,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    with _pin_canonical_home(canonical_home) as pinned_home:
        with _provider_account_lock_pinned(
            canonical_home,
            pinned_home,
            timeout_seconds=timeout_seconds,
        ):
            yield


@contextlib.contextmanager
def provider_account_lock(
    home: Path,
    *,
    timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire the bounded cross-thread/process lock for one profile store."""

    _reject_credential_writer_reentry()
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=timeout_seconds
    ):
        yield


def _active_request(provider: dict[str, Any]) -> dict[str, Any] | None:
    active_id = provider["active_request_id"]
    if active_id is None:
        return None
    for request in provider["requests"]:
        if request["request_id"] == active_id:
            return request
    _raise(ProviderAccountErrorCode.INVALID_STATE)


def _require_revision(provider: dict[str, Any], expected_revision: object) -> None:
    revision = _require_nonnegative_int(expected_revision)
    if provider["revision"] != revision:
        _raise(ProviderAccountErrorCode.STALE_REVISION)


def _set_desired_ownership(provider: dict[str, Any], desired: str) -> bool:
    if provider["desired_ownership"] == desired:
        return False
    provider["desired_ownership"] = desired
    provider["ownership_epoch"] += 1
    return True


def _prune_terminal_history(provider: dict[str, Any]) -> None:
    terminal = [
        request
        for request in provider["requests"]
        if request["status"] in TERMINAL_REQUEST_STATES
    ]
    remove_count = max(0, len(terminal) - MAX_TERMINAL_HISTORY)
    if remove_count == 0:
        return
    remove_ids = {request["request_id"] for request in terminal[:remove_count]}
    provider["requests"] = [
        request
        for request in provider["requests"]
        if request["request_id"] not in remove_ids
    ]
    provider["pruned_terminal_count"] += remove_count


def _terminalize_request(
    provider: dict[str, Any],
    request: dict[str, Any],
    *,
    target: str,
    source: str,
    when: datetime,
    reason: str | None = None,
) -> None:
    if target not in ALLOWED_TRANSITIONS.get(request["status"], frozenset()):
        _raise(ProviderAccountErrorCode.ILLEGAL_TRANSITION)
    request["status"] = target
    timestamp = _format_timestamp(when)
    request["updated_at"] = timestamp
    request["decision_at"] = timestamp
    request["decision_source"] = source
    if reason is not None:
        request["decision_reason"] = reason
    else:
        request.pop("decision_reason", None)
    if target in TERMINAL_REQUEST_STATES:
        provider["active_request_id"] = None
        _prune_terminal_history(provider)


def _apply_lazy_expiry(
    state: dict[str, Any],
    provider_id: str,
    *,
    now: datetime,
) -> bool:
    provider = state["providers"].get(provider_id)
    if provider is None:
        return False
    changed = False
    active = _active_request(provider)
    if active is not None and _parse_timestamp(active["expires_at"]) <= now:
        expiry_at = _parse_timestamp(active["expires_at"])
        _terminalize_request(
            provider,
            active,
            target="expired",
            source="system_expiry",
            when=expiry_at,
        )
        changed = True
    lease = provider["oauth_lease"]
    if lease is not None and _parse_timestamp(lease["expires_at"]) <= now:
        provider["oauth_lease"] = None
        changed = True
    return changed


def _commit_provider_mutation(
    canonical_home: Path,
    state: dict[str, Any],
    provider_id: str,
    *,
    preserve_oauth_completion: bool = False,
) -> None:
    provider = _provider_state(state, provider_id)
    if not preserve_oauth_completion:
        provider["oauth_completion"] = None
    provider["revision"] += 1
    _write_state(canonical_home, state)


def _load_with_lazy_expiry(
    canonical_home: Path,
    provider_id: str,
    *,
    now: datetime,
) -> tuple[dict[str, Any], bool]:
    state = _read_state(canonical_home)
    changed = _apply_lazy_expiry(state, provider_id, now=now)
    if changed:
        _commit_provider_mutation(canonical_home, state, provider_id)
    return state, changed


def _request_snapshot(request: dict[str, Any]) -> ManagedAccessRequest:
    return ManagedAccessRequest(
        request_id=request["request_id"],
        provider_id=request["provider_id"],
        status=request["status"],
        handoff_state=request["handoff_state"],
        device_label=request["device_label"],
        requested_at=request["requested_at"],
        updated_at=request["updated_at"],
        expires_at=request["expires_at"],
        notification_policy_key=request["notification_policy_key"],
        notification_handoff_at=request.get("notification_handoff_at"),
        decision_at=request.get("decision_at"),
        decision_source=request.get("decision_source"),
        decision_reason=request.get("decision_reason"),
    )


def _account_snapshot(state: dict[str, Any], provider_id: str) -> AccountSnapshot:
    provider = _existing_provider_state(state, provider_id)
    requests = tuple(_request_snapshot(request) for request in provider["requests"])
    active_request = next(
        (
            request
            for request in requests
            if request.request_id == provider["active_request_id"]
        ),
        None,
    )
    raw_lease = provider["oauth_lease"]
    lease = (
        None
        if raw_lease is None
        else OAuthLease(
            generation=raw_lease["generation"],
            operation_id=raw_lease["operation_id"],
            store_instance_id=raw_lease["store_instance_id"],
            ownership_epoch=raw_lease["ownership_epoch"],
            active_request_id_at_start=raw_lease["active_request_id_at_start"],
            started_at=raw_lease["started_at"],
            expires_at=raw_lease["expires_at"],
        )
    )
    raw_completion = provider["oauth_completion"]
    completion = (
        None
        if raw_completion is None
        else OAuthCompletion(
            generation=raw_completion["generation"],
            operation_id=raw_completion["operation_id"],
            store_instance_id=raw_completion["store_instance_id"],
            ownership_epoch=raw_completion["ownership_epoch"],
            active_request_id_at_start=raw_completion["active_request_id_at_start"],
            completed_at=raw_completion["completed_at"],
            intent_matched=raw_completion["intent_matched"],
            superseded_request_id=raw_completion["superseded_request_id"],
        )
    )
    return AccountSnapshot(
        provider_id=provider_id,
        revision=provider["revision"],
        ownership_epoch=provider["ownership_epoch"],
        oauth_generation=provider["oauth_generation"],
        oauth_lease=lease,
        oauth_completion=completion,
        desired_ownership=provider["desired_ownership"],
        active_request_id=provider["active_request_id"],
        active_request=active_request,
        pruned_terminal_count=provider["pruned_terminal_count"],
        requests=requests,
    )


def _find_active_request(
    provider: dict[str, Any], request_id: object
) -> dict[str, Any]:
    if not isinstance(request_id, str):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    active = _active_request(provider)
    if active is None or not secrets.compare_digest(active["request_id"], request_id):
        _raise(ProviderAccountErrorCode.NOT_FOUND)
    return active


def get_account_snapshot(
    *,
    home: Path,
    provider_id: str,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> AccountSnapshot:
    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        now = _coerce_utc_now()
        state, _ = _load_with_lazy_expiry(canonical_home, provider_id, now=now)
        return _account_snapshot(state, provider_id)


def get_captured_oauth_snapshot(
    *,
    home: Path,
    provider_id: str,
    captured_intent: PersonalOAuthIntent,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> AccountSnapshot:
    """Read OAuth state only from the directory/store captured by ``intent``."""

    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    canonical_home = canonical_provider_account_home(home)
    with _pin_canonical_home(canonical_home) as pinned_home:
        captured_intent = _validate_captured_intent(
            canonical_home,
            provider_id,
            captured_intent,
        )
        with _provider_account_lock_pinned(
            canonical_home,
            pinned_home,
            timeout_seconds=lock_timeout_seconds,
        ):
            now = _coerce_utc_now()
            state = _read_state(canonical_home)
            if state["store_instance_id"] != captured_intent.store_instance_id:
                _raise(ProviderAccountErrorCode.NOT_FOUND)
            if _apply_lazy_expiry(state, provider_id, now=now):
                _commit_provider_mutation(canonical_home, state, provider_id)
            return _account_snapshot(state, provider_id)


def select_personal(
    *,
    home: Path,
    provider_id: str,
    expected_revision: int,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> AccountMutationResult:
    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        now = _coerce_utc_now()
        state, _ = _load_with_lazy_expiry(canonical_home, provider_id, now=now)
        provider = _existing_provider_state(state, provider_id)
        _require_revision(provider, expected_revision)
        if provider["desired_ownership"] == "personal":
            return AccountMutationResult(snapshot=_account_snapshot(state, provider_id))
        provider = _provider_state(state, provider_id)
        _set_desired_ownership(provider, "personal")
        _commit_provider_mutation(canonical_home, state, provider_id)
        return AccountMutationResult(snapshot=_account_snapshot(state, provider_id))


def create_managed_request(
    *,
    home: Path,
    provider_id: str,
    device_label: str,
    expected_revision: int,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> ManagedRequestResult:
    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    normalized_label = _normalize_device_label(device_label)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        now = _coerce_utc_now()
        state, _ = _load_with_lazy_expiry(canonical_home, provider_id, now=now)
        provider = _existing_provider_state(state, provider_id)
        current = _active_request(provider)
        if current is not None and provider["desired_ownership"] == "fabric_managed":
            request = _request_snapshot(current)
            return ManagedRequestResult(
                snapshot=_account_snapshot(state, provider_id),
                request=request,
                created=False,
            )

        _require_revision(provider, expected_revision)
        provider = _provider_state(state, provider_id)
        if current is not None:
            _set_desired_ownership(provider, "fabric_managed")
            _commit_provider_mutation(canonical_home, state, provider_id)
            request = _request_snapshot(current)
            return ManagedRequestResult(
                snapshot=_account_snapshot(state, provider_id),
                request=request,
                created=False,
            )

        request_id = _new_request_id()
        existing_ids = {
            request["request_id"]
            for other_provider in state["providers"].values()
            for request in other_provider["requests"]
        }
        while request_id in existing_ids:
            request_id = _new_request_id()
        requested_at = _format_timestamp(now)
        request_dict: dict[str, Any] = {
            "request_id": request_id,
            "provider_id": provider_id,
            "status": "requested",
            "handoff_state": "offered",
            "device_label": normalized_label,
            "requested_at": requested_at,
            "updated_at": requested_at,
            "expires_at": _format_timestamp(now + REQUEST_TTL),
            "notification_policy_key": NOTIFICATION_POLICY_KEY,
        }
        _set_desired_ownership(provider, "fabric_managed")
        provider["requests"].append(request_dict)
        provider["active_request_id"] = request_id
        _prune_terminal_history(provider)
        _commit_provider_mutation(canonical_home, state, provider_id)
        request = _request_snapshot(request_dict)
        return ManagedRequestResult(
            snapshot=_account_snapshot(state, provider_id),
            request=request,
            created=True,
        )


def record_handoff_attempt(
    *,
    home: Path,
    provider_id: str,
    request_id: str,
    expected_revision: int,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> AccountMutationResult:
    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        now = _coerce_utc_now()
        state, _ = _load_with_lazy_expiry(canonical_home, provider_id, now=now)
        provider = _existing_provider_state(state, provider_id)
        request = _find_active_request(provider, request_id)
        _require_revision(provider, expected_revision)
        if request["handoff_state"] == "launch_attempted_unverified":
            return AccountMutationResult(
                snapshot=_account_snapshot(state, provider_id),
                request=_request_snapshot(request),
            )
        timestamp = _format_timestamp(now)
        request["handoff_state"] = "launch_attempted_unverified"
        request["notification_handoff_at"] = timestamp
        request["updated_at"] = timestamp
        _commit_provider_mutation(canonical_home, state, provider_id)
        return AccountMutationResult(
            snapshot=_account_snapshot(state, provider_id),
            request=_request_snapshot(request),
        )


def record_admin_acknowledgement(
    *,
    home: Path,
    provider_id: str,
    request_id: str,
    expected_revision: int,
    source: str,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> AccountMutationResult:
    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    if not isinstance(source, str) or source not in OPERATOR_DECISION_SOURCES:
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        now = _coerce_utc_now()
        state, _ = _load_with_lazy_expiry(canonical_home, provider_id, now=now)
        provider = _existing_provider_state(state, provider_id)
        request = _find_active_request(provider, request_id)
        _require_revision(provider, expected_revision)
        if request["status"] != "requested":
            _raise(ProviderAccountErrorCode.ILLEGAL_TRANSITION)
        _terminalize_request(
            provider,
            request,
            target="awaiting",
            source=source,
            when=now,
        )
        _commit_provider_mutation(canonical_home, state, provider_id)
        return AccountMutationResult(
            snapshot=_account_snapshot(state, provider_id),
            request=_request_snapshot(request),
        )


def transition_request(
    *,
    home: Path,
    provider_id: str,
    request_id: str,
    target: str,
    expected_revision: int,
    source: str,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> AccountMutationResult:
    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    if not isinstance(target, str) or target not in {"cancelled", "rejected"}:
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    if not isinstance(source, str) or source not in OPERATOR_DECISION_SOURCES:
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        now = _coerce_utc_now()
        state, _ = _load_with_lazy_expiry(canonical_home, provider_id, now=now)
        provider = _existing_provider_state(state, provider_id)
        request = _find_active_request(provider, request_id)
        _require_revision(provider, expected_revision)
        _terminalize_request(
            provider,
            request,
            target=target,
            source=source,
            when=now,
        )
        _commit_provider_mutation(canonical_home, state, provider_id)
        return AccountMutationResult(
            snapshot=_account_snapshot(state, provider_id),
            request=_request_snapshot(request),
        )


def capture_personal_oauth_start(
    *,
    home: Path,
    provider_id: str,
    expected_revision: int,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> PersonalOAuthStartResult:
    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        now = _coerce_utc_now()
        state, _ = _load_with_lazy_expiry(canonical_home, provider_id, now=now)
        provider = _existing_provider_state(state, provider_id)
        _require_revision(provider, expected_revision)
        if provider["desired_ownership"] != "personal":
            provider = _provider_state(state, provider_id)
            _set_desired_ownership(provider, "personal")
            _commit_provider_mutation(canonical_home, state, provider_id)
        snapshot = _account_snapshot(state, provider_id)
        pinned_home = _current_pinned_home(canonical_home)
        if pinned_home is None:  # defensive: capture always runs under the lock pin
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        return PersonalOAuthStartResult(
            snapshot=snapshot,
            intent=PersonalOAuthIntent(
                flow_owner=ProviderAccountFlowOwner(
                    canonical_home,
                    pinned_home.identity,
                ),
                provider_id=provider_id,
                store_instance_id=state["store_instance_id"],
                ownership_epoch=snapshot.ownership_epoch,
                active_request_id_at_start=snapshot.active_request_id,
            ),
        )


def acquire_oauth_lease(
    *,
    home: Path,
    provider_id: str,
    captured_intent: PersonalOAuthIntent,
    operation_id: str | None = None,
    takeover: bool = False,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> OAuthLeaseResult:
    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    if not isinstance(takeover, bool):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    if operation_id is not None and not _is_operation_id(operation_id):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        captured_intent = _validate_captured_intent(
            canonical_home, provider_id, captured_intent
        )
        now = _coerce_utc_now()
        state = _read_state(canonical_home)
        if state["store_instance_id"] != captured_intent.store_instance_id:
            _raise(ProviderAccountErrorCode.NOT_FOUND)
        expiry_changed = _apply_lazy_expiry(state, provider_id, now=now)
        provider = _existing_provider_state(state, provider_id)
        if not _intent_matches_provider_state(provider, captured_intent):
            if expiry_changed:
                _commit_provider_mutation(canonical_home, state, provider_id)
            _raise(ProviderAccountErrorCode.NOT_FOUND)
        active_lease = provider["oauth_lease"]
        if active_lease is not None:
            exact_replay = (
                operation_id is not None
                and active_lease["operation_id"] == operation_id
                and active_lease["store_instance_id"]
                == captured_intent.store_instance_id
                and active_lease["ownership_epoch"] == captured_intent.ownership_epoch
                and active_lease["active_request_id_at_start"]
                == captured_intent.active_request_id_at_start
            )
            if exact_replay and not takeover:
                return OAuthLeaseResult(
                    snapshot=_account_snapshot(state, provider_id),
                    lease=OAuthLease(**active_lease),
                    takeover=False,
                )
            if not takeover:
                _raise(ProviderAccountErrorCode.OAUTH_IN_PROGRESS)
            if exact_replay:
                # A takeover is a distinct worker generation and must never
                # reuse the active writer's operation/idempotency key.
                _raise(ProviderAccountErrorCode.INVALID_INPUT)
        provider = _provider_state(state, provider_id)
        provider["oauth_generation"] += 1
        reserved_operation_ids = {
            candidate["operation_id"]
            for candidate in (active_lease, provider["oauth_completion"])
            if candidate is not None
        }
        if operation_id is None:
            operation_id = _new_oauth_operation_id()
            while operation_id in reserved_operation_ids:
                operation_id = _new_oauth_operation_id()
        elif operation_id in reserved_operation_ids:
            _raise(ProviderAccountErrorCode.INVALID_INPUT)
        lease_dict = {
            "generation": provider["oauth_generation"],
            "operation_id": operation_id,
            "store_instance_id": state["store_instance_id"],
            "ownership_epoch": captured_intent.ownership_epoch,
            "active_request_id_at_start": captured_intent.active_request_id_at_start,
            "started_at": _format_timestamp(now),
            "expires_at": _format_timestamp(now + OAUTH_LEASE_TTL),
        }
        provider["oauth_lease"] = lease_dict
        provider["oauth_completion"] = None
        _commit_provider_mutation(canonical_home, state, provider_id)
        lease = OAuthLease(**lease_dict)
        return OAuthLeaseResult(
            snapshot=_account_snapshot(state, provider_id),
            lease=lease,
            takeover=active_lease is not None,
        )


def _owners_match(canonical_home: Path, flow_owner: ProviderAccountFlowOwner) -> bool:
    if not isinstance(flow_owner, ProviderAccountFlowOwner):
        return False
    pinned_home = _current_pinned_home(canonical_home)
    return (
        pinned_home is not None
        and _canonical_key(canonical_home) == _canonical_key(flow_owner.canonical_home)
        and pinned_home.identity == flow_owner.home_identity
    )


def _validate_captured_intent(
    canonical_home: Path,
    provider_id: str,
    captured_intent: object,
) -> PersonalOAuthIntent:
    if not isinstance(captured_intent, PersonalOAuthIntent):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    if (
        not _is_nonnegative_int(captured_intent.ownership_epoch)
        or not _is_store_instance_id(captured_intent.store_instance_id)
        or (
            captured_intent.active_request_id_at_start is not None
            and not isinstance(captured_intent.active_request_id_at_start, str)
        )
    ):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    if (
        not _owners_match(canonical_home, captured_intent.flow_owner)
        or not isinstance(captured_intent.provider_id, str)
        or captured_intent.provider_id != provider_id
    ):
        _raise(ProviderAccountErrorCode.NOT_FOUND)
    return captured_intent


def _intent_matches_provider_state(
    provider: dict[str, Any],
    intent: PersonalOAuthIntent,
) -> bool:
    return (
        provider["desired_ownership"] == "personal"
        and provider["ownership_epoch"] == intent.ownership_epoch
        and provider["active_request_id"] == intent.active_request_id_at_start
    )


def _conditionally_supersede_captured_request(
    provider: dict[str, Any],
    intent: PersonalOAuthIntent,
    *,
    now: datetime,
) -> str | None:
    if (
        provider["desired_ownership"] != "personal"
        or provider["ownership_epoch"] != intent.ownership_epoch
        or provider["active_request_id"] != intent.active_request_id_at_start
        or intent.active_request_id_at_start is None
    ):
        return None
    request = _active_request(provider)
    if request is None:
        return None
    request_id = request["request_id"]
    _terminalize_request(
        provider,
        request,
        target="cancelled",
        source="verified_personal_oauth",
        when=now,
        reason="superseded_by_verified_personal",
    )
    return request_id


def commit_current_oauth_generation(
    *,
    home: Path,
    provider_id: str,
    generation: int,
    operation_id: str,
    credential_writer: Callable[[str], None],
    captured_intent: PersonalOAuthIntent,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> OAuthCompletionResult:
    """Persist credentials only while the durable OAuth generation is current.

    The provider-account lock remains held through ``credential_writer`` and the
    account-state completion.  A stale or expired generation is rejected before
    the callback can run.
    """

    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    generation = _require_nonnegative_int(generation)
    if (
        generation == 0
        or not _is_operation_id(operation_id)
        or not callable(credential_writer)
    ):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        captured_intent = _validate_captured_intent(
            canonical_home, provider_id, captured_intent
        )
        now = _coerce_utc_now()
        state = _read_state(canonical_home)
        if state["store_instance_id"] != captured_intent.store_instance_id:
            _raise(ProviderAccountErrorCode.NOT_FOUND)
        provider = _existing_provider_state(state, provider_id)
        completion = provider["oauth_completion"]
        if completion is not None and (
            completion["generation"] == generation
            and completion["operation_id"] == operation_id
            and completion["ownership_epoch"] == captured_intent.ownership_epoch
            and completion["active_request_id_at_start"]
            == captured_intent.active_request_id_at_start
        ):
            return OAuthCompletionResult(
                snapshot=_account_snapshot(state, provider_id),
                operation_id=operation_id,
                superseded_request_id=completion["superseded_request_id"],
                intent_matched=completion["intent_matched"],
                replayed=True,
            )
        lease = provider["oauth_lease"]
        if lease is None:
            _raise(ProviderAccountErrorCode.NOT_FOUND)
        lease_expired = _parse_timestamp(lease["expires_at"]) <= now
        if lease_expired:
            provider = _provider_state(state, provider_id)
            provider["oauth_lease"] = None
            _commit_provider_mutation(canonical_home, state, provider_id)
            _raise(ProviderAccountErrorCode.NOT_FOUND)
        if (
            provider["oauth_generation"] != generation
            or lease["generation"] != generation
            or lease["operation_id"] != operation_id
            or lease["ownership_epoch"] != captured_intent.ownership_epoch
            or lease["active_request_id_at_start"]
            != captured_intent.active_request_id_at_start
        ):
            _raise(ProviderAccountErrorCode.NOT_FOUND)
        if _apply_lazy_expiry(state, provider_id, now=now):
            _commit_provider_mutation(canonical_home, state, provider_id)
        provider = _existing_provider_state(state, provider_id)
        pinned_home = _current_pinned_home(canonical_home)
        if pinned_home is None:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        capability = OAuthProfileWriteCapability(pinned_home)
        _credential_writer_state.active = True
        _credential_writer_state.write_capability = capability
        try:
            credential_writer(operation_id)
        except ProviderAccountError as exc:
            _raise(exc.code, retryable=exc.retryable)
        except Exception:
            _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
        finally:
            _credential_writer_state.write_capability = None
            _credential_writer_state.active = False

        provider["oauth_lease"] = None
        matched = _intent_matches_provider_state(provider, captured_intent)
        superseded = _conditionally_supersede_captured_request(
            provider, captured_intent, now=now
        )
        provider["oauth_completion"] = {
            "generation": generation,
            "operation_id": operation_id,
            "store_instance_id": state["store_instance_id"],
            "ownership_epoch": captured_intent.ownership_epoch,
            "active_request_id_at_start": captured_intent.active_request_id_at_start,
            "completed_at": _format_timestamp(now),
            "intent_matched": matched,
            "superseded_request_id": superseded,
        }
        _commit_provider_mutation(
            canonical_home,
            state,
            provider_id,
            preserve_oauth_completion=True,
        )
        return OAuthCompletionResult(
            snapshot=_account_snapshot(state, provider_id),
            operation_id=operation_id,
            superseded_request_id=superseded,
            intent_matched=matched,
            replayed=False,
        )


def persist_personal_oauth_completion(
    *,
    home: Path,
    provider_id: str,
    generation: int,
    operation_id: str,
    credential_writer: Callable[[str], None],
    captured_intent: PersonalOAuthIntent,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> OAuthCompletionResult:
    """Descriptive alias for :func:`commit_current_oauth_generation`."""

    _reject_credential_writer_reentry()
    return commit_current_oauth_generation(
        home=home,
        provider_id=provider_id,
        generation=generation,
        operation_id=operation_id,
        credential_writer=credential_writer,
        captured_intent=captured_intent,
        lock_timeout_seconds=lock_timeout_seconds,
    )


def release_oauth_lease(
    *,
    home: Path,
    provider_id: str,
    generation: int,
    operation_id: str,
    store_instance_id: str,
    captured_intent: PersonalOAuthIntent,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> AccountMutationResult:
    """Clear only the caller's still-current OAuth lease (cancel/error cleanup).

    Cleanup is bound to the profile-directory identity captured before the
    provider ceremony.  A profile path can be renamed and replaced while a
    worker is running; lease keys and copied state bytes alone are therefore
    insufficient authority to mutate whatever directory later occupies that
    pathname.  Once the captured owner and store instance are proven, absence
    of this exact lease is an idempotent success.
    """

    _reject_credential_writer_reentry()
    provider_id = _require_provider_id(provider_id)
    generation = _require_nonnegative_int(generation)
    if (
        generation == 0
        or not _is_operation_id(operation_id)
        or not _is_store_instance_id(store_instance_id)
    ):
        _raise(ProviderAccountErrorCode.INVALID_INPUT)
    canonical_home = canonical_provider_account_home(home)
    # Validate the captured directory owner against a descriptor/handle pin
    # *before* opening the lock entry.  If the profile path was replaced, even
    # creating a lock file in the successor directory would be an unauthorized
    # mutation.  Once pinned, all lock/state operations remain descriptor-
    # relative to the captured directory if its pathname changes again.
    with _pin_canonical_home(canonical_home) as pinned_home:
        captured_intent = _validate_captured_intent(
            canonical_home, provider_id, captured_intent
        )
        with _provider_account_lock_pinned(
            canonical_home,
            pinned_home,
            timeout_seconds=lock_timeout_seconds,
        ):
            now = _coerce_utc_now()
            state = _read_state(canonical_home)
            if (
                state["store_instance_id"] != captured_intent.store_instance_id
                or store_instance_id != captured_intent.store_instance_id
            ):
                _raise(ProviderAccountErrorCode.NOT_FOUND)
            provider = _existing_provider_state(state, provider_id)
            lease = provider["oauth_lease"]
            if lease is None or _parse_timestamp(lease["expires_at"]) <= now:
                if lease is not None:
                    provider = _provider_state(state, provider_id)
                    provider["oauth_lease"] = None
                    _commit_provider_mutation(canonical_home, state, provider_id)
                return AccountMutationResult(
                    snapshot=_account_snapshot(state, provider_id)
                )
            if (
                provider["oauth_generation"] != generation
                or lease["generation"] != generation
                or lease["operation_id"] != operation_id
                or lease["store_instance_id"] != store_instance_id
            ):
                return AccountMutationResult(
                    snapshot=_account_snapshot(state, provider_id)
                )
            _apply_lazy_expiry(state, provider_id, now=now)
            provider = _existing_provider_state(state, provider_id)
            provider["oauth_lease"] = None
            _commit_provider_mutation(canonical_home, state, provider_id)
            return AccountMutationResult(snapshot=_account_snapshot(state, provider_id))


def repair_account_store(
    *,
    home: Path,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> RepairResult:
    """Reset one confirmed profile store after preserving its exact bytes.

    Confirmation belongs to the local CLI adapter.  This domain operation is
    deliberately not exposed by REST or JSON-RPC.  An existing safe state file
    is atomically claimed into the private repair directory before the empty
    schema-v1 replacement is published with no-clobber semantics. A decodable
    newer schema, redirected or hard-linked entries, unsafe permissions, and
    oversized input all fail closed without replacing the store.
    """

    _reject_credential_writer_reentry()
    canonical_home = canonical_provider_account_home(home)
    with _repair_operation_guard():
        with _provider_account_lock_canonical(
            canonical_home, timeout_seconds=lock_timeout_seconds
        ):
            raw = _read_repair_source_bytes(canonical_home)
            prior_instance_id: str | None = None
            if raw is not None:
                try:
                    decoded = _decode_state_payload(raw)
                except ProviderAccountError as exc:
                    if exc.code is ProviderAccountErrorCode.NEWER_SCHEMA:
                        raise
                    if exc.code is not ProviderAccountErrorCode.INVALID_STATE:
                        raise
                else:
                    prior_instance_id = decoded["store_instance_id"]
            elif _entry_stat(canonical_home / STATE_FILENAME) is not None:
                _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)

            replacement = _empty_state()
            while replacement["store_instance_id"] == prior_instance_id:
                replacement = _empty_state()

            if raw is None:
                temporary_path = _stage_repair_replacement(
                    canonical_home,
                    replacement,
                )
                _publish_repair_replacement(canonical_home, temporary_path)
                return RepairResult(
                    schema_version=SCHEMA_VERSION,
                    backup_created=False,
                )

            with _private_repair_directory(canonical_home) as (
                repair_path,
                pinned_repair,
            ):
                backup_path = _claim_repair_source(
                    canonical_home,
                    repair_path,
                    pinned_repair,
                )
                temporary_path: Path | None = None
                temporary_identity: tuple[int, int] | None = None
                publish_attempted = False
                try:
                    # Validate the bytes actually claimed, not merely the
                    # earlier observation. A non-cooperating process may have
                    # replaced the entry before the atomic move; those exact
                    # bytes become the backup and control newer-schema policy.
                    claimed_raw = _read_claimed_repair_bytes(
                        backup_path,
                        pinned_repair,
                    )
                    claimed_instance_id: str | None = None
                    try:
                        claimed = _decode_state_payload(claimed_raw)
                    except ProviderAccountError as exc:
                        if exc.code is ProviderAccountErrorCode.NEWER_SCHEMA:
                            raise
                        if exc.code is not ProviderAccountErrorCode.INVALID_STATE:
                            raise
                    else:
                        claimed_instance_id = claimed["store_instance_id"]

                    while replacement["store_instance_id"] == claimed_instance_id:
                        replacement = _empty_state()
                    temporary_path = _stage_repair_replacement(
                        canonical_home,
                        replacement,
                    )
                    temporary_identity = _entry_identity(temporary_path)
                    if temporary_identity is None:
                        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)

                    # The claim rename and exact bytes must be durable before
                    # a reset can become visible. There is deliberately no copy
                    # or cross-filesystem fallback.
                    _fsync_directory(repair_path)
                    _fsync_directory(canonical_home)
                    publish_attempted = True
                    _publish_repair_replacement(canonical_home, temporary_path)
                    temporary_path = None
                except BaseException:
                    state_path = canonical_home / STATE_FILENAME
                    try:
                        state_missing = _entry_identity(state_path) is None
                    except BaseException:
                        _raise(
                            ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                            retryable=False,
                        )
                    if state_missing:
                        restored = _restore_claimed_repair_source(
                            canonical_home,
                            backup_path,
                            pinned_repair,
                        )
                        if not restored:
                            try:
                                state_still_missing = (
                                    _entry_identity(state_path) is None
                                )
                            except BaseException:
                                _raise(
                                    ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                                    retryable=False,
                                )
                            if state_still_missing:
                                _raise(
                                    ProviderAccountErrorCode.COMMIT_UNCERTAIN,
                                    retryable=False,
                                )
                    raise
                finally:
                    if temporary_path is not None and not publish_attempted:
                        pinned_home = _current_pinned_home(canonical_home)
                        if pinned_home is not None and temporary_identity is not None:
                            with contextlib.suppress(
                                OSError,
                                ProviderAccountError,
                            ):
                                _unlink_pinned_entry_if_identity(
                                    temporary_path,
                                    pinned_home,
                                    temporary_identity,
                                )
            return RepairResult(
                schema_version=SCHEMA_VERSION,
                backup_created=True,
            )


def rebind_restored_account_store(
    *,
    home: Path,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> None:
    """Fence restored/migrated state from pre-restore OAuth workers.

    Request history and desired ownership are preserved.  The store instance is
    rotated, all live OAuth leases/completion tombstones are cleared, and each
    persisted provider revision advances once.  Callers must invoke this after
    placing restored bytes and before exposing the profile to any runtime.
    """

    _reject_credential_writer_reentry()
    canonical_home = canonical_provider_account_home(home)
    with _provider_account_lock_canonical(
        canonical_home, timeout_seconds=lock_timeout_seconds
    ):
        if os.name == "nt":
            state_path = canonical_home / STATE_FILENAME
            _assert_safe_entry(state_path)
            if _entry_stat(state_path) is not None:
                fd: int | None = None
                try:
                    fd = os.open(state_path, os.O_RDWR | getattr(os, "O_BINARY", 0))
                    opened = os.fstat(fd)
                    if not _same_opened_entry(state_path, opened):
                        _raise(ProviderAccountErrorCode.PATH_REDIRECT)
                    if not _windows_private_fd(fd, apply=True):
                        _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
                except ProviderAccountError:
                    raise
                except OSError:
                    _raise(ProviderAccountErrorCode.IO_UNAVAILABLE)
                finally:
                    if fd is not None:
                        with contextlib.suppress(OSError):
                            os.close(fd)
        state = _read_state(canonical_home)
        prior_instance_id = state["store_instance_id"]
        new_instance_id = _new_store_instance_id()
        while new_instance_id == prior_instance_id:
            new_instance_id = _new_store_instance_id()
        state["store_instance_id"] = new_instance_id
        for provider in state["providers"].values():
            provider["oauth_lease"] = None
            provider["oauth_completion"] = None
            provider["revision"] += 1
        _write_state(canonical_home, state)


__all__ = [
    "ACTIVE_REQUEST_STATES",
    "ALLOWED_PROVIDER_IDS",
    "ALLOWED_TRANSITIONS",
    "HANDOFF_STATES",
    "TERMINAL_REQUEST_STATES",
    "AccountMutationResult",
    "AccountSnapshot",
    "ManagedAccessRequest",
    "ManagedRequestResult",
    "OAuthCompletionResult",
    "OAuthLease",
    "OAuthLeaseResult",
    "PersonalOAuthIntent",
    "PersonalOAuthStartResult",
    "ProviderAccountError",
    "ProviderAccountErrorCode",
    "ProviderAccountFlowOwner",
    "RepairResult",
    "acquire_oauth_lease",
    "canonical_provider_account_home",
    "capture_personal_oauth_start",
    "commit_current_oauth_generation",
    "create_managed_request",
    "get_account_snapshot",
    "normalize_device_label",
    "new_oauth_operation_id",
    "persist_personal_oauth_completion",
    "provider_account_lock",
    "provider_account_lock_path",
    "provider_account_state_path",
    "record_admin_acknowledgement",
    "record_handoff_attempt",
    "repair_account_store",
    "rebind_restored_account_store",
    "release_oauth_lease",
    "select_personal",
    "transition_request",
]
