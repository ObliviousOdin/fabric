"""Loopback Remote Control host for the classic prompt-toolkit CLI.

The classic CLI remains the sole owner of its ``AIAgent`` and process loop.
This module only:

* publishes fenced snapshots and ordered events from that existing loop;
* serializes local and attached-controller turns through one input arbiter;
* exposes the narrow local Remote Control RPC subset on a random loopback port.

The listener is a Phase 1 development boundary, not the internet transport.
It rejects non-loopback peers and browser ``Origin`` headers, requires a
high-entropy per-publication token, and never dispatches arbitrary gateway RPCs.
Fabric Link replaces this token/listener boundary with device identity, grants,
MLS, and an outbound relay in later phases.
"""

from __future__ import annotations

import copy
import hmac
import ipaddress
import json
import logging
import queue
import secrets
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from fabric_cli.remote_control import publication_event
from tui_gateway.session_event_hub import (
    SessionEventHub,
    SessionNotPublishedError,
    SnapshotRequiredError,
    SubscriberAlreadyAttachedError,
    TransportAlreadyAttachedError,
)
from tui_gateway.session_input_arbiter import InputReceipt, SessionInputArbiter

logger = logging.getLogger(__name__)

_MAX_REQUEST_BYTES = 256 * 1024
_BASE_REMOTE_METHODS = frozenset({
    "session.attach",
    "session.detach",
    "session.input.submit",
    "session.remote_status",
})
@dataclass(frozen=True)
class ClassicArbitratedInput:
    """One accepted classic-CLI turn with immutable controller attribution."""

    controller_id: str
    request_id: str
    ordinal: int
    origin: str
    payload: Any


class ClassicRemoteInputQueue(queue.Queue):
    """Queue that sends user turns through Remote Control while it is published."""

    def __init__(self, cli: Any) -> None:
        super().__init__()
        self._cli = cli

    def put(self, item, block: bool = True, timeout: float | None = None) -> None:
        if isinstance(item, ClassicArbitratedInput):
            super().put(item, block=block, timeout=timeout)
            return
        host = getattr(self._cli, "_classic_remote_control", None)
        if host is not None and host.published and _is_user_turn(item):
            receipt = host.submit_owner(item)
            if receipt.state == "rejected":
                try:
                    self._cli._console_print(
                        f"  Remote Control input rejected: "
                        f"{receipt.reason or 'input rejected'}"
                    )
                except Exception:
                    pass
            return
        super().put(item, block=block, timeout=timeout)

    def put_accepted(self, item: ClassicArbitratedInput) -> None:
        """Insert an arbiter-owned item without submitting it a second time."""
        super().put(item)


def _is_user_turn(payload: Any) -> bool:
    if isinstance(payload, str):
        return bool(payload.strip()) and not payload.lstrip().startswith("/")
    if isinstance(payload, tuple) and len(payload) == 2:
        text, images = payload
        return bool(str(text or "").strip()) or bool(images)
    return False


def _payload_digest_bytes(payload: Any) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8", errors="surrogatepass")
    if isinstance(payload, tuple) and len(payload) == 2:
        text, images = payload
        normalized = {
            "images": [str(path) for path in (images or [])],
            "text": str(text or ""),
        }
        return json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="surrogatepass")
    raise ValueError("unsupported classic input payload")


def _receipt_payload(receipt: InputReceipt, *, origin: str) -> dict[str, Any]:
    return {
        "controller_id": receipt.controller_id,
        "ordinal": receipt.ordinal,
        "origin": origin,
        "original_state": receipt.original_state,
        "reason": receipt.reason,
        "request_id": receipt.request_id,
        "state": receipt.state,
    }


class _OwnerTransport:
    """The classic terminal renders through callbacks, not JSON frames."""

    def write(self, _obj: dict) -> bool:
        return True

    def close(self) -> None:
        return None


class _ConnectionTransport:
    """Thread-safe SessionEventHub transport over one sync WebSocket."""

    def __init__(self, connection) -> None:
        self._connection = connection
        self._lock = threading.Lock()
        self._closed = False

    def write(self, obj: dict) -> bool:
        with self._lock:
            if self._closed:
                return False
            try:
                self._connection.send(
                    json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
                )
                return True
            except Exception:
                self._closed = True
                return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._connection.close(code=1000, reason="publication ended")
            except Exception:
                pass


class ClassicRemoteControlHost:
    """Own one classic CLI publication without owning or creating its agent."""

    def __init__(
        self,
        *,
        session_id: str,
        snapshot_builder: Callable[[], dict[str, Any]],
        accepted_input: Callable[[ClassicArbitratedInput], None],
        approval_responder: Callable[[str, str], dict[str, Any]] | None = None,
        clarify_responder: Callable[[str, str], dict[str, Any]] | None = None,
        fence_lock: threading.RLock | None = None,
    ) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        self.session_id = session_id
        self._snapshot_builder = snapshot_builder
        self._accepted_input = accepted_input
        self._approval_responder = approval_responder
        self._clarify_responder = clarify_responder
        self._remote_methods = set(_BASE_REMOTE_METHODS)
        if approval_responder is not None:
            self._remote_methods.add("approval.respond")
        if clarify_responder is not None:
            self._remote_methods.add("clarify.respond")
        self._fence_lock = fence_lock or threading.RLock()
        self._hub = SessionEventHub(
            session_id,
            _OwnerTransport(),
            fence_lock=self._fence_lock,
        )
        self._arbiter = SessionInputArbiter()
        self._entries: dict[tuple[str, str], ClassicArbitratedInput] = {}
        self._entry_origins: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()
        self._server = None
        self._server_thread: threading.Thread | None = None
        self._token: str | None = None
        self._port: int | None = None
        self._inflight: ClassicArbitratedInput | None = None
        self._link_status: dict[str, Any] = {}

    @property
    def published(self) -> bool:
        return self._hub.published

    @property
    def endpoint(self) -> str | None:
        with self._lock:
            if not self._token or not self._port:
                return None
            return f"ws://127.0.0.1:{self._port}/remote?token={self._token}"

    @property
    def inflight(self) -> ClassicArbitratedInput | None:
        with self._lock:
            return self._inflight

    def start(self) -> dict[str, Any]:
        """Publish and start the loopback listener, idempotently."""
        with self._lock:
            if self._server is not None and self._hub.published:
                return self.status(owner=True)
            self._token = secrets.token_urlsafe(32)
            try:
                from websockets.sync.server import serve

                server = serve(
                    self._handle_connection,
                    "127.0.0.1",
                    0,
                    compression=None,
                    max_size=_MAX_REQUEST_BYTES,
                    max_queue=16,
                    open_timeout=5,
                )
            except Exception:
                self._token = None
                raise
            self._server = server
            self._port = int(server.socket.getsockname()[1])
            self._hub.enable_remote()
            thread = threading.Thread(
                target=server.serve_forever,
                name="fabric-classic-remote-control",
                daemon=True,
            )
            self._server_thread = thread
            thread.start()
        return self.status(owner=True)

    def stop(self, *, require_idle: bool = True) -> dict[str, Any]:
        """Withdraw publication and stop the loopback listener."""
        with self._lock:
            if require_idle and (
                self._arbiter.active is not None or self._arbiter.queued
            ):
                raise RuntimeError(
                    "session busy — unpublish after queued input finishes"
                )
            detached = self._hub.disable_remote()
            server = self._server
            thread = self._server_thread
            self._server = None
            self._server_thread = None
            self._port = None
            self._token = None
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                logger.debug("classic Remote Control shutdown failed", exc_info=True)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        status = self.status(owner=True)
        status["detached_controllers"] = list(detached)
        return status

    def status(
        self,
        *,
        owner: bool = False,
        transport: _ConnectionTransport | None = None,
    ) -> dict[str, Any]:
        subscriber_id = (
            self._hub.subscriber_for_transport(transport)
            if transport is not None
            else None
        )
        return {
            "attached_controllers": sorted(self._hub.subscriber_ids),
            "endpoint": self.endpoint if owner else None,
            "event_seq": self._hub.sequence,
            "generation": self._hub.generation,
            "owner": owner,
            "published": self._hub.published,
            "session_id": self.session_id,
            "subscriber_id": subscriber_id,
            "link": dict(self._link_status),
        }

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._snapshot_builder())

    def set_link_status(self, status: dict[str, Any] | None) -> None:
        with self._lock:
            self._link_status = dict(status or {})

    def submit_owner(self, payload: Any) -> InputReceipt:
        return self._submit(
            controller_id="owner",
            request_id=f"owner-{uuid.uuid4().hex}",
            payload=payload,
            origin="owner",
        )

    def submit_remote(
        self,
        *,
        transport: _ConnectionTransport,
        controller_id: str | None,
        request_id: str,
        text: Any,
    ) -> InputReceipt:
        attached_id = self._hub.subscriber_for_transport(transport)
        if attached_id is None:
            raise PermissionError("transport is not attached to this live session")
        if controller_id and controller_id != attached_id:
            raise PermissionError("controller identity does not match transport")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text is required")
        return self._submit(
            controller_id=attached_id,
            request_id=_identifier(request_id, field="request_id"),
            payload=text,
            origin="remote",
        )

    def _submit(
        self,
        *,
        controller_id: str,
        request_id: str,
        payload: Any,
        origin: str,
    ) -> InputReceipt:
        if not self._hub.published:
            raise RuntimeError("session is not published")
        digest_payload = _payload_digest_bytes(payload)
        receipt = self._arbiter.submit(
            controller_id=controller_id,
            request_id=request_id,
            payload=digest_payload,
        )
        key = (controller_id, request_id)
        if receipt.state in {"accepted", "queued"}:
            entry = ClassicArbitratedInput(
                controller_id=controller_id,
                request_id=request_id,
                ordinal=int(receipt.ordinal or 0),
                origin=origin,
                payload=payload,
            )
            with self._lock:
                self._entries[key] = entry
                self._entry_origins[key] = origin
        self.emit(
            "input.receipt",
            _receipt_payload(receipt, origin=origin),
        )
        if receipt.state == "accepted":
            self._accepted_input(self._entries[key])
        return receipt

    def begin_turn(
        self,
        entry: ClassicArbitratedInput,
        *,
        text: Any,
        mutation: Callable[[], None],
    ) -> None:
        with self._lock:
            self._inflight = entry
        self.mutate_and_emit(
            "message.start",
            {
                "input": {
                    "controller_id": entry.controller_id,
                    "ordinal": entry.ordinal,
                    "origin": entry.origin,
                    "request_id": entry.request_id,
                },
                "text": text if isinstance(text, str) else "[multimodal input]",
            },
            mutation,
        )

    def complete_turn(
        self,
        entry: ClassicArbitratedInput,
        *,
        response: str,
        mutation: Callable[[], None],
        failed: bool = False,
    ) -> None:
        def finish_snapshot_state() -> None:
            mutation()
            with self._lock:
                self._inflight = None

        self.mutate_and_emit(
            "message.complete",
            {
                "failed": bool(failed),
                "input": {
                    "controller_id": entry.controller_id,
                    "ordinal": entry.ordinal,
                    "origin": entry.origin,
                    "request_id": entry.request_id,
                },
                "text": response,
            },
            finish_snapshot_state,
        )

    def release_turn(self, entry: ClassicArbitratedInput) -> None:
        """Complete one arbiter slot and enqueue its deterministic successor."""
        key = (entry.controller_id, entry.request_id)
        try:
            promoted = self._arbiter.complete(
                controller_id=entry.controller_id,
                request_id=entry.request_id,
            )
        except ValueError:
            logger.error("classic Remote Control lost active input %s", key)
            return
        with self._lock:
            self._entries.pop(key, None)
            completed_origin = self._entry_origins.pop(key, entry.origin)
            if self._inflight == entry:
                self._inflight = None
        completed = self._arbiter.receipt(
            controller_id=entry.controller_id,
            request_id=entry.request_id,
        )
        if completed is not None:
            self.emit(
                "input.receipt",
                _receipt_payload(completed, origin=completed_origin),
            )
        if promoted is None:
            return
        promoted_key = (promoted.controller_id, promoted.request_id)
        with self._lock:
            promoted_entry = self._entries[promoted_key]
            promoted_origin = self._entry_origins[promoted_key]
        self.emit(
            "input.receipt",
            _receipt_payload(promoted, origin=promoted_origin),
        )
        self._accepted_input(promoted_entry)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> bool:
        if not self._hub.published:
            return False
        return self._hub.emit(
            publication_event(event_type, self.session_id, payload)
        )

    def mutate_and_emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        mutation: Callable[[], None],
    ) -> bool:
        if not self._hub.published:
            mutation()
            return False
        return self._hub.mutate_and_emit(
            lambda: (
                mutation(),
                publication_event(event_type, self.session_id, payload),
            )[1]
        )

    def mutate_and_emit_if(
        self,
        predicate: Callable[[], bool],
        event_type: str,
        payload: dict[str, Any],
        mutation: Callable[[], None],
    ) -> bool:
        """Apply and publish one state transition only while it is still current."""
        with self._fence_lock:
            if not predicate():
                return False
            mutation()
            if not self._hub.published:
                return False
            return self._hub.emit(
                publication_event(event_type, self.session_id, payload)
            )

    def _handle_connection(self, connection) -> None:
        transport = _ConnectionTransport(connection)
        if not self._authorize_connection(connection):
            try:
                connection.close(code=1008, reason="unauthorized")
            except Exception:
                pass
            return
        transport.write(
            publication_event(
                "gateway.ready",
                self.session_id,
                {
                    "methods": sorted(self._remote_methods),
                    "surface": "classic_remote_control",
                },
            )
        )
        try:
            for raw in connection:
                response = self._dispatch_wire(raw, transport)
                if response is not None and not transport.write(response):
                    return
        except Exception:
            logger.debug("classic Remote Control connection ended", exc_info=True)
        finally:
            self._hub.detach_transport(transport)

    def dispatch_authenticated(
        self,
        request: dict[str, Any],
        *,
        transport: Any,
    ) -> dict[str, Any]:
        """Dispatch one request already authenticated and authorized by Link.

        This bypasses only the loopback bearer-token handshake. The caller is
        the Fabric Link broker after MLS sender verification, local grant
        authorization, replay rejection, and method allow-listing.
        """
        method = request.get("method")
        if not isinstance(method, str) or method not in self._remote_methods:
            return _error(request.get("id"), -32601, "method not available")
        response = self._dispatch_wire(
            json.dumps(request, separators=(",", ":")),
            transport,
        )
        if response is None:
            return _error(request.get("id"), -32000, "request produced no response")
        return response

    def _authorize_connection(self, connection) -> bool:
        remote = getattr(connection, "remote_address", None)
        peer_host = remote[0] if isinstance(remote, tuple) and remote else ""
        try:
            if not ipaddress.ip_address(str(peer_host)).is_loopback:
                return False
        except ValueError:
            return False
        request = getattr(connection, "request", None)
        headers = getattr(request, "headers", None)
        if headers is not None and headers.get("Origin"):
            return False
        path = str(getattr(request, "path", "") or "")
        parsed = urlsplit(path)
        if parsed.path != "/remote":
            return False
        supplied_tokens = parse_qs(parsed.query).get("token") or []
        if len(supplied_tokens) != 1:
            return False
        supplied = supplied_tokens[0]
        with self._lock:
            expected = self._token or ""
        return bool(expected) and hmac.compare_digest(supplied, expected)

    def _dispatch_wire(
        self,
        raw: str | bytes,
        transport: _ConnectionTransport,
    ) -> dict[str, Any] | None:
        if isinstance(raw, bytes):
            return _error(None, -32600, "binary requests are not supported")
        if len(raw.encode("utf-8", errors="ignore")) > _MAX_REQUEST_BYTES:
            return _error(None, -32600, "request exceeds size limit")
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            return _error(None, -32700, "invalid JSON")
        if not isinstance(request, dict):
            return _error(None, -32600, "request must be an object")
        rid = request.get("id")
        if request.get("jsonrpc") != "2.0" or "id" not in request:
            return _error(rid, -32600, "JSON-RPC 2.0 request id is required")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str) or method not in self._remote_methods:
            return _error(rid, -32601, "method not available")
        if not isinstance(params, dict):
            return _error(rid, -32602, "params must be an object")
        try:
            if str(params.get("session_id") or "") != self.session_id:
                raise LookupError("session not found")
            if method == "session.attach":
                controller_id = _identifier(
                    params.get("controller_id"),
                    field="controller_id",
                )
                generation = str(params.get("generation") or "").strip() or None
                raw_after = params.get("after_event_seq")
                after_event_seq = (
                    int(raw_after) if raw_after is not None else None
                )
                result = self._hub.attach(
                    controller_id,
                    transport,
                    self._snapshot_builder,
                    generation=generation,
                    after_event_seq=after_event_seq,
                )
                return _ok(
                    rid,
                    {
                        "generation": result.generation,
                        "resumed": result.resumed,
                        "session_id": self.session_id,
                        "snapshot": result.snapshot,
                        "snapshot_seq": result.snapshot_seq,
                    },
                )
            if method == "session.detach":
                subscriber_id = self._hub.subscriber_for_transport(transport)
                if subscriber_id is None:
                    raise PermissionError(
                        "transport is not attached to this live session"
                    )
                supplied_id = str(params.get("controller_id") or "").strip()
                if supplied_id and supplied_id != subscriber_id:
                    raise PermissionError(
                        "controller identity does not match transport"
                    )
                return _ok(
                    rid,
                    {
                        "controller_id": subscriber_id,
                        "detached": self._hub.detach(subscriber_id),
                        "session_id": self.session_id,
                    },
                )
            if method == "session.remote_status":
                if self._hub.subscriber_for_transport(transport) is None:
                    raise PermissionError(
                        "transport is not attached to this live session"
                    )
                return _ok(rid, self.status(transport=transport))
            if method == "approval.respond":
                if self._hub.subscriber_for_transport(transport) is None:
                    raise PermissionError(
                        "transport is not attached to this live session"
                    )
                if self._approval_responder is None:
                    raise RuntimeError("approval responses are unavailable")
                request_id = _identifier(
                    params.get("request_id"),
                    field="request_id",
                )
                choice = str(params.get("choice") or "").strip().lower()
                try:
                    result = self._approval_responder(request_id, choice)
                except LookupError as exc:
                    return _error(rid, 4009, str(exc))
                return _ok(
                    rid,
                    result,
                )
            if method == "clarify.respond":
                if self._hub.subscriber_for_transport(transport) is None:
                    raise PermissionError(
                        "transport is not attached to this live session"
                    )
                if self._clarify_responder is None:
                    raise RuntimeError("clarification responses are unavailable")
                request_id = _identifier(
                    params.get("request_id"),
                    field="request_id",
                )
                answer = params.get("answer")
                if not isinstance(answer, str):
                    raise ValueError("answer must be a string")
                if len(answer) > 16 * 1024:
                    raise ValueError("answer is too long")
                try:
                    result = self._clarify_responder(request_id, answer)
                except LookupError as exc:
                    return _error(rid, 4009, str(exc))
                return _ok(
                    rid,
                    result,
                )
            receipt = self.submit_remote(
                transport=transport,
                controller_id=str(params.get("controller_id") or "").strip()
                or None,
                request_id=str(params.get("request_id") or ""),
                text=params.get("text"),
            )
            if receipt.state == "rejected":
                return _error(
                    rid,
                    4093,
                    receipt.reason or "input rejected",
                    {"receipt": _receipt_payload(receipt, origin="remote")},
                )
            return _ok(
                rid,
                {
                    "receipt": _receipt_payload(receipt, origin="remote"),
                    "status": (
                        "streaming"
                        if receipt.state == "accepted"
                        else receipt.original_state or receipt.state
                    ),
                },
            )
        except LookupError as exc:
            return _error(rid, 4040, str(exc))
        except PermissionError as exc:
            return _error(rid, 4030, str(exc))
        except ValueError as exc:
            return _error(rid, 4002, str(exc))
        except (
            SessionNotPublishedError,
            SnapshotRequiredError,
            SubscriberAlreadyAttachedError,
            TransportAlreadyAttachedError,
            RuntimeError,
        ) as exc:
            return _error(rid, 4091, str(exc))


def _identifier(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > 128:
        raise ValueError(f"{field} is too long")
    if not all(char.isalnum() or char in "._:-" for char in normalized):
        raise ValueError(f"{field} contains unsupported characters")
    return normalized


def _ok(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"id": rid, "jsonrpc": "2.0", "result": result}


def _error(
    rid: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"error": error, "id": rid, "jsonrpc": "2.0"}


def snapshot_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the bounded display transcript used by classic attach snapshots."""
    messages: list[dict[str, Any]] = []
    for message in history:
        role = str(message.get("role") or "")
        if role not in {"user", "assistant", "tool"}:
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            text = str(content or "")
        messages.append({"role": role, "text": text})
    return copy.deepcopy(messages[-500:])
