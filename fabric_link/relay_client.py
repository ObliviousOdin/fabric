"""Blocking outbound-only client for the Fabric Link relay WebSocket contract."""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self
from urllib.parse import urlsplit

from .protocol import normalize_relay_origin
from .relay_contract import (
    MAX_RELAY_FRAME_BYTES,
    RelayAcknowledgement,
    RelayAuthentication,
    RelayChallenge,
    RelayDelivery,
    RelayEnrollmentAcknowledgement,
    RelayEnrollmentDelivery,
    RelayEnrollmentPoll,
    RelayEnrollmentPublish,
    RelayFailure,
    RelayPoll,
    RelayPublish,
    RelayReady,
    RelayReceipt,
    RelayRevocation,
    RelaySync,
    relay_frame_from_cbor,
)

_SUBPROTOCOL = "fabric-link-relay-v1"


class LinkRelayClientError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _RelaySocket(Protocol):
    subprotocol: str | None

    def send(self, message: bytes) -> None: ...

    def recv(self, timeout: float | None = None) -> bytes | str: ...

    def close(self) -> None: ...


AuthenticationFactory = Callable[[RelayChallenge], RelayAuthentication]
SocketConnector = Callable[..., _RelaySocket]


class LinkRelayClient:
    """One serialized relay connection.

    The class deliberately exposes relay records rather than Fabric JSON-RPC.
    MLS encryption/decryption and authorization remain in the controller and
    host broker layers.
    """

    def __init__(
        self,
        *,
        relay_origin: str,
        authentication_factory: AuthenticationFactory | None,
        timeout_seconds: float = 15.0,
        connector: SocketConnector | None = None,
    ) -> None:
        try:
            self.origin = normalize_relay_origin(
                relay_origin,
                allow_loopback_http=True,
            )
        except Exception as exc:
            raise LinkRelayClientError("invalid_relay_origin") from exc
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise LinkRelayClientError("invalid_relay_timeout")
        self._url = _websocket_url(self.origin)
        self._authentication_factory = authentication_factory
        self._timeout_seconds = timeout_seconds
        self._connector = connector or _default_connector
        self._socket: _RelaySocket | None = None
        self._lock = threading.Lock()

    def connect(self) -> RelayReady | None:
        with self._lock:
            if self._socket is not None:
                raise LinkRelayClientError("relay_already_connected")
            try:
                socket = self._connector(
                    self._url,
                    subprotocols=[_SUBPROTOCOL],
                    compression=None,
                    max_size=MAX_RELAY_FRAME_BYTES,
                    open_timeout=self._timeout_seconds,
                    close_timeout=5,
                )
                if socket.subprotocol != _SUBPROTOCOL:
                    socket.close()
                    raise LinkRelayClientError("relay_subprotocol_mismatch")
                self._socket = socket
                challenge = self._receive()
                if not isinstance(challenge, RelayChallenge):
                    raise LinkRelayClientError("relay_challenge_missing")
                if self._authentication_factory is None:
                    return None
                authentication = self._authentication_factory(challenge)
                socket.send(authentication.to_cbor())
                ready = self._receive()
                if not isinstance(ready, RelayReady):
                    raise LinkRelayClientError("relay_authentication_incomplete")
                return ready
            except LinkRelayClientError:
                self._close_unlocked()
                raise
            except Exception as exc:
                self._close_unlocked()
                raise LinkRelayClientError("relay_connect_failed") from exc

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def publish(self, frame: RelayPublish) -> RelayReceipt:
        return self._receipt_request(frame.to_cbor(), frame.message_id)

    def acknowledge(self, frame: RelayAcknowledgement) -> RelayReceipt:
        return self._receipt_request(frame.to_cbor(), frame.message_id)

    def poll(self, frame: RelayPoll) -> tuple[tuple[RelayDelivery, ...], RelaySync]:
        with self._lock:
            self._send(frame.to_cbor())
            deliveries: list[RelayDelivery] = []
            while True:
                response = self._receive()
                if isinstance(response, RelayDelivery):
                    deliveries.append(response)
                    continue
                if isinstance(response, RelaySync):
                    if response.request_id != frame.request_id:
                        raise LinkRelayClientError("relay_sync_mismatch")
                    if response.count != len(deliveries):
                        raise LinkRelayClientError("relay_sync_count_mismatch")
                    return tuple(deliveries), response
                raise LinkRelayClientError("relay_poll_response_invalid")

    def publish_enrollment(
        self,
        frame: RelayEnrollmentPublish,
    ) -> RelayReceipt:
        return self._receipt_request(frame.to_cbor(), frame.message_id)

    def acknowledge_enrollment(
        self,
        frame: RelayEnrollmentAcknowledgement,
    ) -> RelayReceipt:
        return self._receipt_request(frame.to_cbor(), frame.message_id)

    def poll_enrollment(
        self,
        frame: RelayEnrollmentPoll,
    ) -> tuple[tuple[RelayEnrollmentDelivery, ...], RelaySync]:
        with self._lock:
            self._send(frame.to_cbor())
            deliveries: list[RelayEnrollmentDelivery] = []
            while True:
                response = self._receive()
                if isinstance(response, RelayEnrollmentDelivery):
                    deliveries.append(response)
                    continue
                if isinstance(response, RelaySync):
                    if response.request_id != frame.request_id:
                        raise LinkRelayClientError("relay_sync_mismatch")
                    if response.count != len(deliveries):
                        raise LinkRelayClientError("relay_sync_count_mismatch")
                    return tuple(deliveries), response
                raise LinkRelayClientError("relay_poll_response_invalid")

    def revoke(self, frame: RelayRevocation) -> RelayReceipt:
        return self._receipt_request(frame.to_cbor(), frame.credential_serial)

    def _receipt_request(
        self,
        encoded: bytes,
        expected_message_id: bytes,
    ) -> RelayReceipt:
        with self._lock:
            self._send(encoded)
            response = self._receive()
            if (
                not isinstance(response, RelayReceipt)
                or response.message_id != expected_message_id
            ):
                raise LinkRelayClientError("relay_receipt_mismatch")
            return response

    def _send(self, encoded: bytes) -> None:
        socket = self._socket
        if socket is None:
            raise LinkRelayClientError("relay_not_connected")
        try:
            socket.send(encoded)
        except Exception as exc:
            self._close_unlocked()
            raise LinkRelayClientError("relay_send_failed") from exc

    def _receive(self):
        socket = self._socket
        if socket is None:
            raise LinkRelayClientError("relay_not_connected")
        try:
            encoded = socket.recv(timeout=self._timeout_seconds)
            if not isinstance(encoded, bytes):
                raise LinkRelayClientError("relay_binary_frame_required")
            frame = relay_frame_from_cbor(encoded)
            if isinstance(frame, RelayFailure):
                raise LinkRelayClientError(frame.code)
            return frame
        except LinkRelayClientError:
            raise
        except Exception as exc:
            self._close_unlocked()
            raise LinkRelayClientError("relay_receive_failed") from exc

    def _close_unlocked(self) -> None:
        socket, self._socket = self._socket, None
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass


def _websocket_url(origin: str) -> str:
    parsed = urlsplit(origin)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/link"


def _default_connector(url: str, **kwargs):
    from websockets.sync.client import connect

    return connect(url, **kwargs)
