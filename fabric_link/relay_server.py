"""Reference WebSocket server for the Fabric Link blind relay contract."""

from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .relay_auth import RelayAdmission
from .relay_contract import (
    MAX_RELAY_FRAME_BYTES,
    LinkRelayProtocolError,
    RelayAcknowledgement,
    RelayAuthentication,
    RelayEnrollmentAcknowledgement,
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
from .relay_service import BlindRelayError, BlindRelayService

_SUBPROTOCOL = "fabric-link-relay-v1"
_MAX_CONNECTIONS = 1024


def create_relay_app(
    service: BlindRelayService,
    *,
    max_connections: int = _MAX_CONNECTIONS,
) -> FastAPI:
    """Create a relay ASGI app with no dashboard, identity provider, or cookies."""

    app = FastAPI(
        title="Fabric Link Blind Relay",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    connection_slots = asyncio.Semaphore(max_connections)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.websocket("/link")
    async def link_socket(websocket: WebSocket) -> None:
        requested = websocket.headers.get("sec-websocket-protocol", "")
        if _SUBPROTOCOL not in {
            item.strip() for item in requested.split(",") if item.strip()
        }:
            await websocket.close(code=1002)
            return
        if connection_slots.locked():
            await websocket.close(code=1013)
            return
        await connection_slots.acquire()
        admission: RelayAdmission | None = None
        try:
            await websocket.accept(subprotocol=_SUBPROTOCOL)
            now = _unix_time()
            challenge = service.issue_challenge(now=now)
            await websocket.send_bytes(challenge.to_cbor())
            while True:
                encoded = await websocket.receive_bytes()
                if len(encoded) > MAX_RELAY_FRAME_BYTES:
                    await _send_failure(websocket, "relay_frame_too_large")
                    await websocket.close(code=1009)
                    return
                correlation_id: bytes | None = None
                try:
                    frame = relay_frame_from_cbor(encoded)
                    correlation_id = _correlation_id(frame)
                    now = _unix_time()
                    if isinstance(frame, RelayAuthentication):
                        if admission is not None:
                            raise BlindRelayError("relay_already_authenticated")
                        admission = service.authenticate(frame, now=now)
                        await websocket.send_bytes(
                            RelayReady(role=admission.role).to_cbor()
                        )
                    elif isinstance(frame, RelayPublish):
                        identity = _require_admission(admission)
                        sequence = service.publish(identity, frame, now=now)
                        await websocket.send_bytes(
                            RelayReceipt(
                                message_id=frame.message_id,
                                sequence=sequence,
                            ).to_cbor()
                        )
                    elif isinstance(frame, RelayPoll):
                        identity = _require_admission(admission)
                        page = service.poll(
                            identity,
                            frame.mailbox,
                            after_sequence=frame.after_sequence,
                            limit=frame.limit,
                            now=now,
                        )
                        for delivery in page.deliveries:
                            await websocket.send_bytes(delivery.to_cbor())
                        await websocket.send_bytes(
                            RelaySync(
                                request_id=frame.request_id,
                                count=len(page.deliveries),
                                high_watermark=page.high_watermark,
                            ).to_cbor()
                        )
                    elif isinstance(frame, RelayAcknowledgement):
                        identity = _require_admission(admission)
                        sequence = service.acknowledge(identity, frame, now=now)
                        await websocket.send_bytes(
                            RelayReceipt(
                                message_id=frame.message_id,
                                sequence=sequence,
                            ).to_cbor()
                        )
                    elif isinstance(frame, RelayEnrollmentPublish):
                        host = _enrollment_host(admission)
                        sequence = service.publish_enrollment(
                            frame,
                            now=now,
                            host_admission=host,
                        )
                        await websocket.send_bytes(
                            RelayReceipt(
                                message_id=frame.message_id,
                                sequence=sequence,
                            ).to_cbor()
                        )
                    elif isinstance(frame, RelayEnrollmentPoll):
                        host = _enrollment_host(admission)
                        page = service.poll_enrollment(
                            frame.mailbox,
                            after_sequence=frame.after_sequence,
                            limit=frame.limit,
                            now=now,
                            host_admission=host,
                        )
                        for delivery in page.deliveries:
                            await websocket.send_bytes(delivery.to_cbor())
                        await websocket.send_bytes(
                            RelaySync(
                                request_id=frame.request_id,
                                count=len(page.deliveries),
                                high_watermark=page.high_watermark,
                            ).to_cbor()
                        )
                    elif isinstance(frame, RelayEnrollmentAcknowledgement):
                        host = _enrollment_host(admission)
                        sequence = service.acknowledge_enrollment(
                            frame,
                            now=now,
                            host_admission=host,
                        )
                        await websocket.send_bytes(
                            RelayReceipt(
                                message_id=frame.message_id,
                                sequence=sequence,
                            ).to_cbor()
                        )
                    elif isinstance(frame, RelayRevocation):
                        identity = _require_admission(admission)
                        service.revoke(identity, frame, now=now)
                        await websocket.send_bytes(
                            RelayReceipt(
                                message_id=frame.credential_serial,
                                sequence=1,
                            ).to_cbor()
                        )
                    else:
                        raise BlindRelayError("relay_frame_not_accepted")
                except (BlindRelayError, LinkRelayProtocolError) as exc:
                    await _send_failure(
                        websocket,
                        getattr(exc, "code", "invalid_relay_frame"),
                        correlation_id=correlation_id,
                    )
        except WebSocketDisconnect:
            return
        finally:
            connection_slots.release()

    return app


def run_reference_relay(
    *,
    relay_origin: str,
    db_path: Path,
    bind_host: str = "127.0.0.1",
    port: int = 8787,
    behind_tls_proxy: bool = False,
) -> None:
    """Run the self-hosted reference service.

    Non-loopback binds require an explicit acknowledgement that TLS terminates
    in a trusted reverse proxy. The relay never serves public plaintext HTTP.
    """

    if not 1 <= port <= 65535:
        raise BlindRelayError("invalid_relay_port")
    if not _is_loopback(bind_host) and not behind_tls_proxy:
        raise BlindRelayError("public_relay_requires_tls_proxy")
    import uvicorn

    service = BlindRelayService(relay_origin=relay_origin, db_path=db_path)
    app = create_relay_app(service)
    try:
        uvicorn.run(
            app,
            host=bind_host,
            port=port,
            access_log=False,
            server_header=False,
        )
    finally:
        service.close()


def _require_admission(admission: RelayAdmission | None) -> RelayAdmission:
    if admission is None:
        raise BlindRelayError("relay_authentication_required")
    return admission


def _enrollment_host(
    admission: RelayAdmission | None,
) -> RelayAdmission | None:
    if admission is not None and admission.role != "host":
        raise BlindRelayError("relay_enrollment_connection_forbidden")
    return admission


def _correlation_id(frame: Any) -> bytes | None:
    if isinstance(
        frame,
        (
            RelayPublish,
            RelayAcknowledgement,
            RelayEnrollmentPublish,
            RelayEnrollmentAcknowledgement,
        ),
    ):
        return frame.message_id
    if isinstance(frame, (RelayPoll, RelayEnrollmentPoll)):
        return frame.request_id
    if isinstance(frame, RelayRevocation):
        return frame.credential_serial
    return None


async def _send_failure(
    websocket: WebSocket,
    code: str,
    *,
    correlation_id: bytes | None = None,
) -> None:
    await websocket.send_bytes(
        RelayFailure(code=code, correlation_id=correlation_id).to_cbor()
    )


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _unix_time() -> int:
    import time

    return int(time.time())
