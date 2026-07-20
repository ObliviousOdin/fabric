"""Immutable, server-derived authentication context for gateway RPCs.

The WebSocket upgrade boundary is the first point at which Fabric knows how a
remote peer authenticated.  Historically that fact was reduced to a boolean
before ``tui_gateway.dispatch`` ran, which made later mobile audit and trust
features unable to distinguish a provider-backed connection from a legacy
session-token connection.

This module intentionally contains no registry, credential, or client input
parsing.  It receives only identity facts already verified by the dashboard
server, turns the human/provider subject into a process-opaque identifier, and
propagates a fresh correlation identifier for each accepted RPC.  A durable
device registry will replace the process-opaque subjects for ``device``
connections in FMB-003A's later enrollment slice.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import hmac
import secrets
from typing import Literal


AuthKind = Literal["device", "internal", "legacy_token", "provider_cookie"]

_AUTH_KINDS = frozenset({"device", "internal", "legacy_token", "provider_cookie"})
_OPAQUE_ID_KEY = secrets.token_bytes(32)


def _opaque_id(prefix: str, value: str) -> str:
    """Return a non-reversible, process-scoped identifier for *value*.

    The key is deliberately process-local.  These identifiers describe a
    currently accepted transport connection; they are not a replacement for
    the durable principal/device IDs that enrollment will issue later.  HMAC
    instead of a plain digest prevents a client that knows a provider's user-ID
    format from checking guesses against a projection.
    """
    digest = hmac.new(
        _OPAQUE_ID_KEY,
        f"{prefix}\0{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _new_correlation_id() -> str:
    return f"cor_{secrets.token_hex(16)}"


@dataclass(frozen=True, slots=True)
class WSAuthContext:
    """Authentication facts that only a verified server boundary may create.

    ``principal_id`` and ``gateway_scope`` are opaque projections; neither
    stores the credential, provider user ID, URL, profile path, or any
    client-selected value.  ``device_id`` remains ``None`` until the durable
    enrollment registry is in place.  ``correlation_id`` is refreshed once per
    dispatched request so subsequent action receipts can identify an exact
    accepted mutation without trusting a client-supplied correlation field.
    """

    auth_kind: AuthKind
    principal_id: str | None
    device_id: str | None
    gateway_scope: str
    correlation_id: str

    def for_request(self) -> "WSAuthContext":
        """Return the same verified identity with a fresh request correlation."""
        return replace(self, correlation_id=_new_correlation_id())

    def public_projection(self) -> dict[str, str | bool | None]:
        """Return the small, credential-free shape safe for an RPC response."""
        return {
            "authenticated": True,
            "auth_kind": self.auth_kind,
            "principal_id": self.principal_id,
            "device_id": self.device_id,
            "gateway_scope": self.gateway_scope,
            "correlation_id": self.correlation_id,
            "credential_state": "active",
        }


def make_authenticated_ws_context(
    *,
    auth_kind: AuthKind,
    gateway_identity: str,
    principal_identity: str | None = None,
    device_id: str | None = None,
) -> WSAuthContext:
    """Create a context from facts verified at the WebSocket boundary.

    ``principal_identity`` is intentionally accepted only by this server-side
    constructor.  It is immediately HMAC-projected and is never retained on
    the returned object.  Callers must reject client JSON/header fields rather
    than forwarding them here.
    """
    if auth_kind not in _AUTH_KINDS:
        raise ValueError(f"unsupported WebSocket auth kind: {auth_kind}")
    if not gateway_identity:
        raise ValueError("gateway identity is required")
    if device_id is not None and not device_id:
        raise ValueError("device_id must be non-empty when provided")

    return WSAuthContext(
        auth_kind=auth_kind,
        principal_id=(
            _opaque_id("pri", principal_identity) if principal_identity else None
        ),
        device_id=device_id,
        gateway_scope=_opaque_id("gwy", gateway_identity),
        correlation_id=_new_correlation_id(),
    )
