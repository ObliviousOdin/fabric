"""Narrow Fabric Link bridge into the existing TUI gateway RPC registry."""

from __future__ import annotations

import copy
import secrets
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from .application import LinkApplicationDispatchRejected
from .capabilities import LINK_REMOTE_METHODS
from .protocol import LinkRequest
from .store import LinkDevice, MachineIdentity

_EVENT_QUEUE_CAPACITY = 2048
_RPC_TIMEOUT_SECONDS = 120.0
_INTERNAL_METHODS = frozenset({"session.create"})


class LinkGatewayBridgeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class _ResponseWaiter:
    event: threading.Event
    response: dict[str, Any] | None = None


class LinkGatewayTransport:
    """Persistent per-device transport for RPC replies and bounded live events."""

    def __init__(
        self,
        *,
        device: LinkDevice,
        machine_identity: MachineIdentity,
        capacity: int = _EVENT_QUEUE_CAPACITY,
    ) -> None:
        if capacity < 16 or capacity > 16_384:
            raise LinkGatewayBridgeError("invalid_link_event_capacity")
        self.device_id = device.device_id
        self.peer_host = "127.0.0.1"
        self._lock = threading.RLock()
        self._event_ready = threading.Condition(self._lock)
        self._waiters: dict[str, _ResponseWaiter] = {}
        self._events: deque[tuple[int, dict[str, Any]]] = deque(maxlen=capacity)
        self._next_event_seq = 1
        self._dropped_through = 0
        self._dispatch_session_id: str | None = None
        self._closed = False
        from tui_gateway.auth_context import make_authenticated_ws_context

        self._auth_context = make_authenticated_ws_context(
            auth_kind="device",
            gateway_identity=machine_identity.route_id.hex(),
            principal_identity=device.credential_hash.hex(),
            device_id=device.device_id,
        )

    def write(self, obj: dict) -> bool:
        with self._lock:
            if self._closed:
                return False
            request_id = obj.get("id")
            if request_id is not None:
                waiter = self._waiters.get(str(request_id))
                if waiter is not None:
                    waiter.response = copy.deepcopy(obj)
                    waiter.event.set()
                    return True
            if isinstance(obj.get("method"), str):
                if len(self._events) == self._events.maxlen and self._events:
                    self._dropped_through = self._events[0][0]
                sequence = self._next_event_seq
                self._next_event_seq += 1
                self._events.append((sequence, copy.deepcopy(obj)))
                self._event_ready.notify_all()
            return True

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._event_ready.notify_all()
            for waiter in self._waiters.values():
                waiter.event.set()
            self._waiters.clear()
            self._events.clear()

    def request(
        self,
        *,
        method: str,
        params: dict[str, Any],
        timeout_seconds: float = _RPC_TIMEOUT_SECONDS,
    ) -> Any:
        return self._request(
            method=method,
            params=params,
            timeout_seconds=timeout_seconds,
            internal=False,
        )

    def dispatch_session_id(self) -> str:
        """Create one hidden local session used only as the durable Work owner."""
        with self._lock:
            existing = self._dispatch_session_id
        if existing is not None:
            return existing
        result = self._request(
            method="session.create",
            params={
                "source": "link",
                "title": "Fabric Link Dispatch",
            },
            timeout_seconds=_RPC_TIMEOUT_SECONDS,
            internal=True,
        )
        if not isinstance(result, dict):
            raise LinkGatewayBridgeError("link_dispatch_session_invalid")
        session_id = str(result.get("session_id") or "").strip()
        if not session_id:
            raise LinkGatewayBridgeError("link_dispatch_session_invalid")
        with self._lock:
            if self._closed:
                raise LinkGatewayBridgeError("link_gateway_transport_closed")
            if self._dispatch_session_id is None:
                self._dispatch_session_id = session_id
            return self._dispatch_session_id

    def _request(
        self,
        *,
        method: str,
        params: dict[str, Any],
        timeout_seconds: float,
        internal: bool,
    ) -> Any:
        if internal:
            if method not in _INTERNAL_METHODS:
                raise LinkGatewayBridgeError("link_internal_method_not_reviewed")
        elif method not in LINK_REMOTE_METHODS:
            raise LinkGatewayBridgeError("link_method_not_reviewed")
        request_id = f"link_{secrets.token_hex(16)}"
        waiter = _ResponseWaiter(event=threading.Event())
        with self._lock:
            if self._closed:
                raise LinkGatewayBridgeError("link_gateway_transport_closed")
            self._waiters[request_id] = waiter
        try:
            from tui_gateway import server

            if method not in server._methods:
                raise LinkGatewayBridgeError("link_method_not_registered")
            response = server.dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                transport=self,
                auth_context=self._auth_context.for_request(),
            )
            if response is None:
                if not waiter.event.wait(timeout=timeout_seconds):
                    raise LinkGatewayBridgeError("link_gateway_rpc_timeout")
                response = waiter.response
            if not isinstance(response, dict):
                raise LinkGatewayBridgeError("link_gateway_rpc_invalid")
            if "error" in response:
                raise LinkApplicationDispatchRejected("rpc_rejected")
            if "result" not in response:
                raise LinkGatewayBridgeError("link_gateway_rpc_invalid")
            return response["result"]
        finally:
            with self._lock:
                self._waiters.pop(request_id, None)

    def poll_events(
        self,
        *,
        after_event_seq: int,
        limit: int,
        wait_ms: int = 0,
    ) -> dict[str, Any]:
        with self._event_ready:
            if self._closed:
                raise LinkGatewayBridgeError("link_gateway_transport_closed")
            if (
                wait_ms
                and self._next_event_seq - 1 <= after_event_seq
                and after_event_seq >= self._dropped_through
            ):
                self._event_ready.wait(timeout=wait_ms / 1000)
                if self._closed:
                    raise LinkGatewayBridgeError("link_gateway_transport_closed")
            snapshot_required = after_event_seq < self._dropped_through
            events = [
                {"event_seq": sequence, "frame": copy.deepcopy(frame)}
                for sequence, frame in self._events
                if sequence > after_event_seq
            ][:limit]
            return {
                "events": events,
                "high_watermark": self._next_event_seq - 1,
                "snapshot_required": snapshot_required,
            }


class LinkGatewayBridge:
    """One persistent local gateway transport per active Link device."""

    def __init__(self, *, machine_identity: MachineIdentity) -> None:
        self._machine_identity = machine_identity
        self._lock = threading.RLock()
        self._transports: dict[str, LinkGatewayTransport] = {}

    @property
    def registered_methods(self) -> frozenset[str]:
        from tui_gateway import server

        return frozenset(server._methods)

    def dispatch(
        self,
        device: LinkDevice,
        request: LinkRequest,
        params: dict[str, Any],
    ) -> Any:
        transport = self._transport(device)
        if request.method == "job.create" and "session_id" not in params:
            params = dict(params)
            params["session_id"] = transport.dispatch_session_id()
        return transport.request(method=request.method, params=params)

    def close(self) -> None:
        with self._lock:
            transports = tuple(self._transports.values())
            self._transports.clear()
        try:
            from tui_gateway import server

            for transport in transports:
                try:
                    server._close_sessions_for_transport(transport)
                except Exception:
                    pass
                transport.close()
        except Exception:
            for transport in transports:
                transport.close()

    def transport_for_device(self, device: LinkDevice) -> LinkGatewayTransport:
        """Return the verified per-device transport for reviewed local adapters."""
        return self._transport(device)

    def revoke_device(self, device_id: str) -> None:
        with self._lock:
            transport = self._transports.pop(device_id, None)
        if transport is None:
            return
        try:
            from tui_gateway import server

            server._close_sessions_for_transport(transport)
        finally:
            transport.close()

    def _transport(self, device: LinkDevice) -> LinkGatewayTransport:
        with self._lock:
            transport = self._transports.get(device.device_id)
            if transport is None:
                transport = LinkGatewayTransport(
                    device=device,
                    machine_identity=self._machine_identity,
                )
                self._transports[device.device_id] = transport
            return transport
