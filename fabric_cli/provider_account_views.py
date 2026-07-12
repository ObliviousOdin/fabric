"""Safe public views for profile-scoped provider-account state.

The durable domain intentionally retains OAuth generation/lease details for
ceremony fencing.  CLI, REST, and JSON-RPC must never serialize those internal
fields independently, so every transport uses :func:`serialize_account_result`.

Managed-access requests are durable local intent only. The public distribution
does not route them to a hard-coded person or service, and no OAuth ceremony
data is serialized with the request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from fabric_cli import provider_accounts as accounts


_REQUEST_ID_RE = re.compile(r"^par_[0-9a-f]{24}$")
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PUBLIC_DECISION_SOURCES = frozenset({
    "local_operator",
    "fabric_control_plane",
    "system_expiry",
    "verified_personal_oauth",
})
_PUBLIC_DECISION_REASONS = frozenset({"superseded_by_verified_personal"})
_PUBLIC_DESIRED_OWNERSHIP = frozenset({"unselected", "personal", "fabric_managed"})
_OWNERSHIP_MISMATCH = "ownership_mismatch"


@dataclass(frozen=True)
class _ProviderMetadata:
    label: str
    fabric_docs_url: str


_PROVIDER_METADATA = MappingProxyType({
    "openai-codex": _ProviderMetadata(
        label="ChatGPT subscription (OpenAI Codex)",
        fabric_docs_url=(
            "https://obliviousodin.github.io/fabric/guides/chatgpt-codex-subscription"
        ),
    ),
    "xai-oauth": _ProviderMetadata(
        label="xAI Grok OAuth (SuperGrok / X Premium+)",
        fabric_docs_url="https://obliviousodin.github.io/fabric/guides/xai-grok-oauth",
    ),
})


@dataclass(frozen=True)
class ProviderAccountErrorTransport:
    """Transport metadata shared by CLI, REST, and JSON-RPC adapters."""

    http_status: int
    jsonrpc_code: int
    cli_exit_code: int
    retryable: bool
    client_meaning: str


def _transport(
    http_status: int,
    jsonrpc_code: int,
    cli_exit_code: int,
    retryable: bool,
    client_meaning: str,
) -> ProviderAccountErrorTransport:
    return ProviderAccountErrorTransport(
        http_status=http_status,
        jsonrpc_code=jsonrpc_code,
        cli_exit_code=cli_exit_code,
        retryable=retryable,
        client_meaning=client_meaning,
    )


PROVIDER_ACCOUNT_ERROR_TRANSPORTS = MappingProxyType({
    accounts.ProviderAccountErrorCode.INVALID_PROVIDER: _transport(
        400, -32602, 2, False, "Correct the allowlisted input."
    ),
    accounts.ProviderAccountErrorCode.INVALID_INPUT: _transport(
        400, -32602, 2, False, "Correct the allowlisted input."
    ),
    accounts.ProviderAccountErrorCode.NOT_FOUND: _transport(
        404, -32044, 4, False, "Resource unavailable to this owner."
    ),
    accounts.ProviderAccountErrorCode.NOT_AUTHORIZED: _transport(
        403,
        -32003,
        77,
        False,
        "Explicit admin policy does not permit mutation.",
    ),
    accounts.ProviderAccountErrorCode.STALE_REVISION: _transport(
        409, -32009, 3, True, "Refresh the snapshot; do not infer success."
    ),
    accounts.ProviderAccountErrorCode.ILLEGAL_TRANSITION: _transport(
        409, -32009, 3, True, "Refresh the snapshot; do not infer success."
    ),
    accounts.ProviderAccountErrorCode.OAUTH_IN_PROGRESS: _transport(
        409, -32009, 3, True, "Refresh the snapshot; do not infer success."
    ),
    accounts.ProviderAccountErrorCode.INVALID_STATE: _transport(
        409,
        -32010,
        5,
        False,
        "Local operator repair or upgrade is required.",
    ),
    accounts.ProviderAccountErrorCode.NEWER_SCHEMA: _transport(
        409,
        -32010,
        5,
        False,
        "Local operator repair or upgrade is required.",
    ),
    accounts.ProviderAccountErrorCode.PATH_REDIRECT: _transport(
        409,
        -32010,
        5,
        False,
        "Local operator repair or upgrade is required.",
    ),
    accounts.ProviderAccountErrorCode.LOCK_TIMEOUT: _transport(
        503, -32053, 75, True, "Preserve state and retry later."
    ),
    accounts.ProviderAccountErrorCode.IO_UNAVAILABLE: _transport(
        503, -32053, 75, True, "Preserve state and retry later."
    ),
    accounts.ProviderAccountErrorCode.COMMIT_UNCERTAIN: _transport(
        503,
        -32053,
        75,
        False,
        "Inspect current state before deciding whether to retry.",
    ),
    accounts.ProviderAccountErrorCode.RUNTIME_MODE_UNAVAILABLE: _transport(
        503,
        -32054,
        69,
        False,
        "This surface is unavailable in the current mode.",
    ),
})


def public_error_code(
    error: accounts.ProviderAccountError
    | accounts.ProviderAccountErrorCode
    | str
    | object,
) -> accounts.ProviderAccountErrorCode:
    """Normalize an internal failure without exposing mismatch or raw text."""

    if isinstance(error, accounts.ProviderAccountError):
        raw: object = error.code
    else:
        raw = error
    if raw == _OWNERSHIP_MISMATCH:
        return accounts.ProviderAccountErrorCode.NOT_FOUND
    try:
        return accounts.ProviderAccountErrorCode(raw)
    except (TypeError, ValueError):
        # An unexpected adapter failure is a corrupt/unavailable public view,
        # never a reason to serialize the exception text.
        return accounts.ProviderAccountErrorCode.INVALID_STATE


def error_transport(
    error: accounts.ProviderAccountError
    | accounts.ProviderAccountErrorCode
    | str
    | object,
) -> ProviderAccountErrorTransport:
    """Return the stable transport row for a domain failure."""

    return PROVIDER_ACCOUNT_ERROR_TRANSPORTS[public_error_code(error)]


def serialize_account_error(
    error: accounts.ProviderAccountError
    | accounts.ProviderAccountErrorCode
    | str
    | object,
) -> dict[str, dict[str, object]]:
    """Return the REST/JSON-CLI error body shared with JSON-RPC ``data``."""

    return {"error": serialize_account_rpc_error_data(error)}


def serialize_account_rpc_error_data(
    error: accounts.ProviderAccountError
    | accounts.ProviderAccountErrorCode
    | str
    | object,
) -> dict[str, object]:
    """Return direct JSON-RPC ``error.data`` without the REST wrapper."""

    code = public_error_code(error)
    metadata = PROVIDER_ACCOUNT_ERROR_TRANSPORTS[code]
    return {"code": code.value, "retryable": metadata.retryable}


def _invalid_state() -> None:
    raise accounts.ProviderAccountError(accounts.ProviderAccountErrorCode.INVALID_STATE)


def _is_public_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        _invalid_state()
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError):
        _invalid_state()
    normalized = parsed.astimezone(timezone.utc).replace(microsecond=0)
    if normalized.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        _invalid_state()
    return normalized


def _parse_optional_timestamp(value: object) -> datetime | None:
    return None if value is None else _parse_timestamp(value)


def _validate_request(request: accounts.ManagedAccessRequest) -> None:
    if not isinstance(request, accounts.ManagedAccessRequest):
        _invalid_state()
    if (
        not isinstance(request.provider_id, str)
        or request.provider_id not in _PROVIDER_METADATA
    ):
        _invalid_state()
    if (
        not isinstance(request.request_id, str)
        or _REQUEST_ID_RE.fullmatch(request.request_id) is None
    ):
        _invalid_state()
    if not isinstance(request.status, str) or request.status not in (
        accounts.ACTIVE_REQUEST_STATES | accounts.TERMINAL_REQUEST_STATES
    ):
        _invalid_state()
    if (
        not isinstance(request.handoff_state, str)
        or request.handoff_state not in accounts.HANDOFF_STATES
    ):
        _invalid_state()
    if not isinstance(request.device_label, str):
        _invalid_state()
    try:
        normalized_label = accounts.normalize_device_label(request.device_label)
    except accounts.ProviderAccountError:
        _invalid_state()
    if normalized_label != request.device_label:
        _invalid_state()
    if (
        not isinstance(request.notification_policy_key, str)
        or request.notification_policy_key != accounts.NOTIFICATION_POLICY_KEY
    ):
        _invalid_state()
    requested_at = _parse_timestamp(request.requested_at)
    updated_at = _parse_timestamp(request.updated_at)
    expires_at = _parse_timestamp(request.expires_at)
    if (
        updated_at < requested_at
        or expires_at <= requested_at
        or expires_at - requested_at != accounts.REQUEST_TTL
    ):
        _invalid_state()
    if request.status in accounts.ACTIVE_REQUEST_STATES and updated_at >= expires_at:
        _invalid_state()

    notification_at = _parse_optional_timestamp(request.notification_handoff_at)
    if request.handoff_state == "offered":
        if notification_at is not None:
            _invalid_state()
    elif (
        notification_at is None
        or notification_at < requested_at
        or notification_at > updated_at
    ):
        _invalid_state()

    if request.status == "requested":
        if any(
            value is not None
            for value in (
                request.decision_at,
                request.decision_source,
                request.decision_reason,
            )
        ):
            _invalid_state()
        return

    decision_at = _parse_timestamp(request.decision_at)
    if decision_at != updated_at or not requested_at <= decision_at <= updated_at:
        _invalid_state()
    if (
        not isinstance(request.decision_source, str)
        or request.decision_source not in _PUBLIC_DECISION_SOURCES
    ):
        _invalid_state()
    if request.status == "awaiting" and request.decision_source not in {
        "local_operator",
        "fabric_control_plane",
    }:
        _invalid_state()
    if request.status == "expired" and (
        request.decision_source != "system_expiry"
        or decision_at != expires_at
        or updated_at != expires_at
    ):
        _invalid_state()
    if request.status in {"awaiting", "cancelled", "rejected"} and (
        decision_at >= expires_at or updated_at >= expires_at
    ):
        _invalid_state()
    if request.status == "rejected" and request.decision_source not in {
        "local_operator",
        "fabric_control_plane",
    }:
        _invalid_state()
    if request.status == "cancelled" and request.decision_source not in {
        "local_operator",
        "fabric_control_plane",
        "verified_personal_oauth",
    }:
        _invalid_state()
    if request.decision_reason is not None and (
        not isinstance(request.decision_reason, str)
        or request.decision_reason not in _PUBLIC_DECISION_REASONS
        or request.status != "cancelled"
        or request.decision_source != "verified_personal_oauth"
    ):
        _invalid_state()
    if request.decision_source == "verified_personal_oauth" and (
        request.status != "cancelled"
        or request.decision_reason != "superseded_by_verified_personal"
    ):
        _invalid_state()


def _serialize_request(
    request: accounts.ManagedAccessRequest,
) -> dict[str, object]:
    _validate_request(request)
    return {
        "request_id": request.request_id,
        "provider_id": request.provider_id,
        "status": request.status,
        "handoff_state": request.handoff_state,
        "device_label": request.device_label,
        "requested_at": request.requested_at,
        "updated_at": request.updated_at,
        "expires_at": request.expires_at,
        "notification_handoff_at": request.notification_handoff_at,
        "decision_at": request.decision_at,
        "decision_source": request.decision_source,
        "decision_reason": request.decision_reason,
    }


def _derive_handoff(
    request: accounts.ManagedAccessRequest | None,
) -> dict[str, object] | None:
    """Return no remote handoff for the public, self-hosted distribution."""

    if request is None:
        return None
    _validate_request(request)
    if request.status not in accounts.ACTIVE_REQUEST_STATES:
        return None
    return None


def _validate_snapshot(snapshot: accounts.AccountSnapshot) -> None:
    if not isinstance(snapshot, accounts.AccountSnapshot):
        _invalid_state()
    if (
        not isinstance(snapshot.provider_id, str)
        or snapshot.provider_id not in _PROVIDER_METADATA
    ):
        _invalid_state()
    if (
        not isinstance(snapshot.desired_ownership, str)
        or snapshot.desired_ownership not in _PUBLIC_DESIRED_OWNERSHIP
    ):
        _invalid_state()
    if not all(
        _is_public_int(value)
        for value in (
            snapshot.revision,
            snapshot.ownership_epoch,
            snapshot.pruned_terminal_count,
        )
    ):
        _invalid_state()
    if not isinstance(snapshot.requests, tuple):
        _invalid_state()
    request_ids: set[str] = set()
    active_requests: list[accounts.ManagedAccessRequest] = []
    terminal_count = 0
    prior_requested_at: datetime | None = None
    for request in snapshot.requests:
        _validate_request(request)
        if request.provider_id != snapshot.provider_id:
            _invalid_state()
        if request.request_id in request_ids:
            _invalid_state()
        request_ids.add(request.request_id)
        requested_at = _parse_timestamp(request.requested_at)
        if prior_requested_at is not None and requested_at < prior_requested_at:
            _invalid_state()
        prior_requested_at = requested_at
        if request.status in accounts.ACTIVE_REQUEST_STATES:
            active_requests.append(request)
        else:
            terminal_count += 1
    if terminal_count > accounts.MAX_TERMINAL_HISTORY or len(active_requests) > 1:
        _invalid_state()

    if snapshot.active_request_id is not None and (
        not isinstance(snapshot.active_request_id, str)
        or _REQUEST_ID_RE.fullmatch(snapshot.active_request_id) is None
    ):
        _invalid_state()
    if snapshot.active_request is not None and not isinstance(
        snapshot.active_request, accounts.ManagedAccessRequest
    ):
        _invalid_state()
    expected_active = active_requests[0] if active_requests else None
    expected_active_id = (
        expected_active.request_id if expected_active is not None else None
    )
    if snapshot.active_request_id != expected_active_id:
        _invalid_state()
    if snapshot.active_request != expected_active:
        _invalid_state()
    if expected_active is not None and snapshot.desired_ownership == "unselected":
        _invalid_state()
    if snapshot.desired_ownership == "unselected" and (
        snapshot.ownership_epoch != 0 or snapshot.requests
    ):
        _invalid_state()
    if snapshot.desired_ownership != "unselected" and snapshot.ownership_epoch == 0:
        _invalid_state()


def _serialize_snapshot(snapshot: accounts.AccountSnapshot) -> dict[str, object]:
    _validate_snapshot(snapshot)
    active_request = (
        None
        if snapshot.active_request is None
        else _serialize_request(snapshot.active_request)
    )
    return {
        "provider_id": snapshot.provider_id,
        "revision": snapshot.revision,
        "ownership_epoch": snapshot.ownership_epoch,
        "desired_ownership": snapshot.desired_ownership,
        "active_request_id": snapshot.active_request_id,
        "active_request": active_request,
        "pruned_terminal_count": snapshot.pruned_terminal_count,
        "requests": [_serialize_request(request) for request in snapshot.requests],
        "handoff": _derive_handoff(snapshot.active_request),
    }


_SerializableAccountResult = (
    accounts.AccountSnapshot
    | accounts.AccountMutationResult
    | accounts.ManagedRequestResult
)


def serialize_account_result(
    value: _SerializableAccountResult,
) -> dict[str, object]:
    """Serialize every provider-account result into one transport-safe DTO.

    The returned shape is always ``{snapshot, request, created}``.  ``created``
    is populated only for :class:`ManagedRequestResult`; callers never need a
    transport-specific serializer.  Internal OAuth generation/lease state and
    any attributes added by orchestration layers are ignored by construction.
    """

    if isinstance(value, accounts.AccountSnapshot):
        snapshot = value
        request = None
        created = None
    elif isinstance(value, accounts.AccountMutationResult):
        snapshot = value.snapshot
        request = value.request
        created = None
    elif isinstance(value, accounts.ManagedRequestResult):
        snapshot = value.snapshot
        request = value.request
        created = value.created
    else:
        raise TypeError("unsupported provider-account result")

    _validate_snapshot(snapshot)
    serialized_request = None
    if request is not None:
        _validate_request(request)
        matches = [
            item for item in snapshot.requests if item.request_id == request.request_id
        ]
        if (
            request.provider_id != snapshot.provider_id
            or len(matches) != 1
            or request != matches[0]
        ):
            _invalid_state()
        serialized_request = _serialize_request(request)
    if created is not None and not isinstance(created, bool):
        _invalid_state()
    if isinstance(value, accounts.ManagedRequestResult) and request != (
        snapshot.active_request
    ):
        _invalid_state()
    return {
        "snapshot": _serialize_snapshot(snapshot),
        "request": serialized_request,
        "created": created,
    }


def serialize_account_repair_result(
    value: accounts.RepairResult,
) -> dict[str, object]:
    """Return the local-operator repair result without paths or prior state."""

    if (
        not isinstance(value, accounts.RepairResult)
        or value.schema_version != accounts.SCHEMA_VERSION
        or not isinstance(value.backup_created, bool)
    ):
        _invalid_state()
    return {
        "repair": {
            "backup_created": value.backup_created,
            "providers_reset": True,
            "schema_version": value.schema_version,
        }
    }


__all__ = [
    "PROVIDER_ACCOUNT_ERROR_TRANSPORTS",
    "ProviderAccountErrorTransport",
    "error_transport",
    "public_error_code",
    "serialize_account_error",
    "serialize_account_repair_result",
    "serialize_account_rpc_error_data",
    "serialize_account_result",
]
