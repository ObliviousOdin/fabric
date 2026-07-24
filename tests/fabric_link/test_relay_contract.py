from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fabric_link.enrollment import _certificate
from fabric_link.protocol import canonical_dumps
from fabric_link.relay_auth import (
    LinkRelayAuthenticationError,
    create_controller_authentication,
    create_host_authentication,
    verify_controller_authentication,
    verify_host_authentication,
)
from fabric_link.relay_contract import (
    LinkRelayProtocolError,
    RelayAcknowledgement,
    RelayAuthentication,
    RelayChallenge,
    RelayDelivery,
    RelayMailbox,
    RelayPublish,
    relay_frame_from_cbor,
)
from fabric_link.store import LinkDeviceStore

NOW = 1_784_840_000
ORIGIN = "https://relay.example"


def make_store(tmp_path) -> LinkDeviceStore:
    root = tmp_path / "link"
    return LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    )


def challenge() -> RelayChallenge:
    return RelayChallenge(
        nonce=b"n" * 32,
        server_time=NOW,
        expires_at=NOW + 30,
        protocol_versions=(3, 2, 1),
    )


def test_relay_frames_are_strict_canonical_round_trips():
    mailbox = RelayMailbox(
        route_id=b"r" * 32,
        credential_serial=b"s" * 16,
        recipient="host",
    )
    frames = [
        challenge(),
        RelayAuthentication(
            route_id=mailbox.route_id,
            role="host",
            nonce=b"n" * 32,
            route_public_key=b"k" * 32,
            signature=b"g" * 64,
        ),
        RelayPublish(
            mailbox=mailbox,
            message_id=b"m" * 16,
            expires_at=NOW + 30,
            opaque_record=b"opaque MLS record",
        ),
        RelayDelivery(
            mailbox=mailbox,
            sequence=1,
            message_id=b"m" * 16,
            expires_at=NOW + 30,
            opaque_record=b"opaque MLS record",
        ),
        RelayAcknowledgement(
            mailbox=mailbox,
            sequence=1,
            message_id=b"m" * 16,
        ),
    ]

    for frame in frames:
        encoded = frame.to_cbor()
        assert relay_frame_from_cbor(encoded) == frame
        assert relay_frame_from_cbor(encoded).to_cbor() == encoded

    assert "opaque MLS record" not in repr(frames[2])
    assert "opaque MLS record" not in repr(frames[3])


def test_relay_contract_rejects_unknown_fields_and_invalid_direction():
    with pytest.raises(LinkRelayProtocolError, match="invalid_relay_recipient"):
        RelayMailbox(
            route_id=b"r" * 32,
            credential_serial=b"s" * 16,
            recipient="broadcast",  # type: ignore[arg-type]
        )

    encoded = canonical_dumps({
        "v": 1,
        "t": "ack",
        "mailbox": {
            "route": b"r" * 32,
            "credential_serial": b"s" * 16,
            "recipient": "host",
        },
        "sequence": 1,
        "message_id": b"m" * 16,
        "plaintext": "must never be accepted",
    })
    with pytest.raises(LinkRelayProtocolError, match="invalid_relay_frame"):
        relay_frame_from_cbor(encoded)


def test_host_challenge_authentication_binds_origin_nonce_and_route_key(tmp_path):
    with make_store(tmp_path) as store:
        identity = store.machine_identity()
        authentication = create_host_authentication(
            machine_identity=identity,
            challenge=challenge(),
            relay_origin=ORIGIN,
            now=NOW + 1,
        )

        admission = verify_host_authentication(
            authentication=authentication,
            challenge=challenge(),
            relay_origin=ORIGIN,
            now=NOW + 2,
        )
        assert admission.route_id == identity.route_id
        assert admission.public_key == identity.public_key
        assert admission.credential_serial is None

        with pytest.raises(
            LinkRelayAuthenticationError,
            match="relay_signature_invalid",
        ):
            verify_host_authentication(
                authentication=authentication,
                challenge=challenge(),
                relay_origin="https://other-relay.example",
                now=NOW + 2,
            )
        with pytest.raises(
            LinkRelayAuthenticationError,
            match="relay_challenge_mismatch",
        ):
            verify_host_authentication(
                authentication=authentication,
                challenge=replace(challenge(), nonce=b"x" * 32),
                relay_origin=ORIGIN,
                now=NOW + 2,
            )
        with pytest.raises(
            LinkRelayAuthenticationError,
            match="relay_route_key_mismatch",
        ):
            verify_host_authentication(
                authentication=authentication,
                challenge=challenge(),
                relay_origin=ORIGIN,
                now=NOW + 2,
                registered_route_public_key=b"x" * 32,
            )


def test_controller_authentication_requires_machine_certificate_and_key_proof(tmp_path):
    controller_key = Ed25519PrivateKey.generate()
    controller_public = controller_key.public_key().public_bytes_raw()
    credential_serial = b"s" * 16
    with make_store(tmp_path) as store:
        identity = store.machine_identity()
        certificate = _certificate(
            route_id=identity.route_id,
            relay_public_key=controller_public,
            credential_serial=credential_serial,
            not_before=NOW - 30,
            not_after=NOW + 3600,
            sign=identity.sign,
        )
        authentication = create_controller_authentication(
            route_id=identity.route_id,
            credential_serial=credential_serial,
            admission_certificate=certificate,
            controller_private_key=controller_key,
            challenge=challenge(),
            relay_origin=ORIGIN,
            now=NOW + 1,
        )

        admission = verify_controller_authentication(
            authentication=authentication,
            challenge=challenge(),
            relay_origin=ORIGIN,
            now=NOW + 2,
            registered_route_public_key=identity.public_key,
        )
        assert admission.role == "controller"
        assert admission.credential_serial == credential_serial
        assert admission.public_key == controller_public

        with pytest.raises(
            LinkRelayAuthenticationError,
            match="invalid_relay_admission_certificate",
        ):
            verify_controller_authentication(
                authentication=replace(
                    authentication,
                    controller_public_key=b"x" * 32,
                ),
                challenge=challenge(),
                relay_origin=ORIGIN,
                now=NOW + 2,
                registered_route_public_key=identity.public_key,
            )


def test_expired_challenge_never_authenticates(tmp_path):
    with make_store(tmp_path) as store:
        identity = store.machine_identity()
        with pytest.raises(
            LinkRelayAuthenticationError,
            match="relay_challenge_expired",
        ):
            create_host_authentication(
                machine_identity=identity,
                challenge=challenge(),
                relay_origin=ORIGIN,
                now=NOW + 31,
            )
