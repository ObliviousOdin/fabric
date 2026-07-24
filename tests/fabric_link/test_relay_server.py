from __future__ import annotations

from fastapi.testclient import TestClient

from fabric_link.relay_auth import create_host_authentication
from fabric_link.relay_contract import (
    RelayChallenge,
    RelayEnrollmentMailbox,
    RelayEnrollmentPoll,
    RelayEnrollmentPublish,
    RelayFailure,
    RelayReady,
    RelayReceipt,
    RelaySync,
    relay_frame_from_cbor,
)
from fabric_link.relay_server import create_relay_app, run_reference_relay
from fabric_link.relay_service import BlindRelayError, BlindRelayService
from fabric_link.store import LinkDeviceStore

NOW = 1_784_840_000
ORIGIN = "https://relay.example"
SUBPROTOCOL = "fabric-link-relay-v1"


def make_store(tmp_path) -> LinkDeviceStore:
    root = tmp_path / "link"
    return LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    )


def test_websocket_challenge_auth_and_enrollment_poll_contract(tmp_path, monkeypatch):
    monkeypatch.setattr("fabric_link.relay_server._unix_time", lambda: NOW)
    service = BlindRelayService(relay_origin=ORIGIN)
    with make_store(tmp_path) as store:
        identity = store.machine_identity()
        client = TestClient(create_relay_app(service))

        with client.websocket_connect(
            "/link",
            subprotocols=[SUBPROTOCOL],
        ) as socket:
            challenge = relay_frame_from_cbor(socket.receive_bytes())
            assert isinstance(challenge, RelayChallenge)
            socket.send_bytes(
                create_host_authentication(
                    machine_identity=identity,
                    challenge=challenge,
                    relay_origin=ORIGIN,
                    now=NOW,
                ).to_cbor()
            )
            ready = relay_frame_from_cbor(socket.receive_bytes())
            assert ready == RelayReady(role="host")

        mailbox = RelayEnrollmentMailbox(
            route_id=identity.route_id,
            pairing_handle=b"p" * 32,
            recipient="host",
        )
        with client.websocket_connect(
            "/link",
            subprotocols=[SUBPROTOCOL],
        ) as guest:
            assert isinstance(
                relay_frame_from_cbor(guest.receive_bytes()),
                RelayChallenge,
            )
            guest.send_bytes(
                RelayEnrollmentPublish(
                    mailbox=mailbox,
                    message_id=b"m" * 16,
                    expires_at=NOW + 60,
                    opaque_record=b"opaque-enrollment",
                ).to_cbor()
            )
            receipt = relay_frame_from_cbor(guest.receive_bytes())
            assert receipt == RelayReceipt(message_id=b"m" * 16, sequence=1)

        with client.websocket_connect(
            "/link",
            subprotocols=[SUBPROTOCOL],
        ) as host:
            challenge = relay_frame_from_cbor(host.receive_bytes())
            assert isinstance(challenge, RelayChallenge)
            host.send_bytes(
                create_host_authentication(
                    machine_identity=identity,
                    challenge=challenge,
                    relay_origin=ORIGIN,
                    now=NOW,
                ).to_cbor()
            )
            assert relay_frame_from_cbor(host.receive_bytes()) == RelayReady(
                role="host"
            )
            host.send_bytes(
                RelayEnrollmentPoll(
                    mailbox=mailbox,
                    request_id=b"r" * 16,
                ).to_cbor()
            )
            delivery = relay_frame_from_cbor(host.receive_bytes())
            assert delivery.opaque_record == b"opaque-enrollment"
            sync = relay_frame_from_cbor(host.receive_bytes())
            assert sync == RelaySync(
                request_id=b"r" * 16,
                count=1,
                high_watermark=1,
            )
    service.close()


def test_websocket_rejects_application_frames_before_authentication(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("fabric_link.relay_server._unix_time", lambda: NOW)
    service = BlindRelayService(relay_origin=ORIGIN)
    with make_store(tmp_path) as store:
        identity = store.machine_identity()
        host = service.authenticate(
            create_host_authentication(
                machine_identity=identity,
                challenge=service.issue_challenge(now=NOW, nonce=b"h" * 32),
                relay_origin=ORIGIN,
                now=NOW,
            ),
            now=NOW,
        )
        assert host.role == "host"
        client = TestClient(create_relay_app(service))
        with client.websocket_connect(
            "/link",
            subprotocols=[SUBPROTOCOL],
        ) as guest:
            assert isinstance(
                relay_frame_from_cbor(guest.receive_bytes()),
                RelayChallenge,
            )
            guest.send_bytes(
                RelayEnrollmentPoll(
                    mailbox=RelayEnrollmentMailbox(
                        route_id=identity.route_id,
                        pairing_handle=b"p" * 32,
                        recipient="host",
                    ),
                    request_id=b"r" * 16,
                ).to_cbor()
            )
            failure = relay_frame_from_cbor(guest.receive_bytes())
            assert failure == RelayFailure(
                code="relay_mailbox_forbidden",
                correlation_id=b"r" * 16,
            )
    service.close()


def test_reference_relay_refuses_public_plaintext_bind(tmp_path):
    try:
        run_reference_relay(
            relay_origin=ORIGIN,
            db_path=tmp_path / "relay.sqlite3",
            bind_host="0.0.0.0",
            port=8787,
        )
    except BlindRelayError as exc:
        assert exc.code == "public_relay_requires_tls_proxy"
    else:
        raise AssertionError("public bind must require an explicit TLS proxy")
