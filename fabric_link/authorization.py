"""Host-side Fabric Link authorization before JSON-RPC dispatch."""

from __future__ import annotations

from collections.abc import Collection

from .capabilities import LINK_REMOTE_METHODS, grant_for_method
from .protocol import LinkRequest, REQUEST_TTL_SECONDS
from .store import LinkDevice, LinkDeviceStore, LinkReplayError, LinkStorageError


class LinkAuthorizationError(PermissionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def check_link_request(
    *,
    device: LinkDevice,
    method: str,
    now: int,
    request: LinkRequest,
    registered_methods: Collection[str],
) -> None:
    """Evaluate policy without mutating replay, audit, or MLS state."""
    if method != request.method:
        raise LinkAuthorizationError("method_envelope_mismatch")
    if device.status != "active":
        raise LinkAuthorizationError("device_not_active")
    if method not in device.allowed_methods:
        raise LinkAuthorizationError("method_not_granted")
    if method not in LINK_REMOTE_METHODS:
        raise LinkAuthorizationError("method_not_link_reviewed")
    if method not in registered_methods:
        raise LinkAuthorizationError("method_not_registered")
    if (
        request.expires_at < now
        or request.issued_at > now + 30
        or request.issued_at < now - REQUEST_TTL_SECONDS
    ):
        raise LinkAuthorizationError("request_not_fresh")


def authorize_link_request(
    *,
    sender_credential_hash: bytes,
    method: str,
    now: int,
    request: LinkRequest,
    registry: LinkDeviceStore,
    registered_methods: Collection[str],
) -> LinkDevice:
    """Authorize and replay-claim one request before the existing dispatcher."""
    device: LinkDevice | None = None
    error_code: str | None = None
    allowed = False
    try:
        if method != request.method:
            raise LinkAuthorizationError("method_envelope_mismatch")
        try:
            device = registry.require_active(sender_credential_hash)
        except LinkStorageError as exc:
            raise LinkAuthorizationError("device_not_active") from exc
        check_link_request(
            device=device,
            method=method,
            now=now,
            request=request,
            registered_methods=registered_methods,
        )
        try:
            registry.claim_request_id(
                device_id=device.device_id,
                request_id=request.request_id,
                request_expires_at=request.expires_at,
                now=now,
            )
        except LinkReplayError as exc:
            raise LinkAuthorizationError(exc.code) from exc
        allowed = True
    except LinkAuthorizationError as exc:
        error_code = exc.code
        raise
    finally:
        registry.record_audit(
            recorded_at=now,
            device_id=device.device_id if device is not None else None,
            credential_hash=sender_credential_hash,
            request_id=request.request_id,
            method_class=grant_for_method(method),
            decision="allow" if allowed else "deny",
            error_code=error_code,
        )
    return device
