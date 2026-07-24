from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fabric_link.enrollment import _certificate
from fabric_link.relay_auth import (
    RelayAdmission,
    create_controller_authentication,
    create_host_authentication,
    create_relay_revocation,
)
from fabric_link.relay_contract import (
    RelayAcknowledgement,
    RelayEnrollmentAcknowledgement,
    RelayEnrollmentMailbox,
    RelayEnrollmentPublish,
    RelayMailbox,
    RelayPublish,
)
from fabric_link.relay_service import BlindRelayError, BlindRelayService
from fabric_link.store import LinkDeviceStore, MachineIdentity

NOW = 1_784_840_000
ORIGIN = "https://relay.example"


def make_identity(tmp_path) -> tuple[LinkDeviceStore, MachineIdentity]:
    root = tmp_path / "link"
    store = LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    )
    return store, store.machine_identity()


def authenticate_host(
    service: BlindRelayService,
    identity: MachineIdentity,
    *,
    now: int = NOW,
) -> RelayAdmission:
    challenge = service.issue_challenge(now=now, nonce=b"h" * 32)
    return service.authenticate(
        create_host_authentication(
            machine_identity=identity,
            challenge=challenge,
            relay_origin=ORIGIN,
            now=now + 1,
        ),
        now=now + 1,
    )


def authenticate_controller(
    service: BlindRelayService,
    identity: MachineIdentity,
    *,
    serial: bytes,
    private_key: Ed25519PrivateKey,
    now: int = NOW,
) -> tuple[RelayAdmission, bytes]:
    public_key = private_key.public_key().public_bytes_raw()
    certificate = _certificate(
        route_id=identity.route_id,
        relay_public_key=public_key,
        credential_serial=serial,
        not_before=now - 30,
        not_after=now + 3600,
        sign=identity.sign,
    )
    challenge = service.issue_challenge(now=now, nonce=b"c" * 32)
    admission = service.authenticate(
        create_controller_authentication(
            route_id=identity.route_id,
            credential_serial=serial,
            admission_certificate=certificate,
            controller_private_key=private_key,
            challenge=challenge,
            relay_origin=ORIGIN,
            now=now + 1,
        ),
        now=now + 1,
    )
    return admission, certificate


def test_application_mailboxes_are_owned_ordered_idempotent_and_acknowledged(tmp_path):
    service = BlindRelayService(relay_origin=ORIGIN)
    store, identity = make_identity(tmp_path)
    controller_key = Ed25519PrivateKey.generate()
    serial = b"s" * 16
    try:
        host = authenticate_host(service, identity)
        controller, _certificate_bytes = authenticate_controller(
            service,
            identity,
            serial=serial,
            private_key=controller_key,
        )
        to_host = RelayMailbox(
            route_id=identity.route_id,
            credential_serial=serial,
            recipient="host",
        )
        request = RelayPublish(
            mailbox=to_host,
            message_id=b"1" * 16,
            expires_at=NOW + 60,
            opaque_record=b"opaque-request",
        )

        assert service.publish(controller, request, now=NOW + 2) == 1
        assert service.publish(controller, request, now=NOW + 3) == 1
        with pytest.raises(BlindRelayError, match="relay_message_id_conflict"):
            service.publish(
                controller,
                replace(request, opaque_record=b"different-ciphertext"),
                now=NOW + 3,
            )
        with pytest.raises(BlindRelayError, match="relay_mailbox_forbidden"):
            service.publish(host, request, now=NOW + 3)
        with pytest.raises(BlindRelayError, match="relay_mailbox_forbidden"):
            service.poll(
                controller,
                to_host,
                after_sequence=0,
                limit=10,
                now=NOW + 3,
            )

        host_page = service.poll(
            host,
            to_host,
            after_sequence=0,
            limit=10,
            now=NOW + 3,
        )
        assert host_page.high_watermark == 1
        assert [item.opaque_record for item in host_page.deliveries] == [
            b"opaque-request"
        ]
        request_ack = RelayAcknowledgement(
            mailbox=to_host,
            sequence=1,
            message_id=b"1" * 16,
        )
        assert service.acknowledge(host, request_ack, now=NOW + 4) == 1
        assert service.acknowledge(host, request_ack, now=NOW + 5) == 1

        to_controller = RelayMailbox(
            route_id=identity.route_id,
            credential_serial=serial,
            recipient="controller",
        )
        response = RelayPublish(
            mailbox=to_controller,
            message_id=b"2" * 16,
            expires_at=NOW + 60,
            opaque_record=b"opaque-response",
        )
        assert service.publish(host, response, now=NOW + 5) == 1
        controller_page = service.poll(
            controller,
            to_controller,
            after_sequence=0,
            limit=10,
            now=NOW + 6,
        )
        assert controller_page.deliveries[0].opaque_record == b"opaque-response"
    finally:
        store.close()
        service.close()


def test_pairing_mailboxes_require_host_for_request_read_and_response_write(tmp_path):
    service = BlindRelayService(relay_origin=ORIGIN)
    store, identity = make_identity(tmp_path)
    try:
        host = authenticate_host(service, identity)
        handle = b"p" * 32
        to_host = RelayEnrollmentMailbox(
            route_id=identity.route_id,
            pairing_handle=handle,
            recipient="host",
        )
        request = RelayEnrollmentPublish(
            mailbox=to_host,
            message_id=b"q" * 16,
            expires_at=NOW + 60,
            opaque_record=b"encrypted-enrollment-request",
        )
        assert service.publish_enrollment(request, now=NOW + 2) == 1
        with pytest.raises(BlindRelayError, match="relay_mailbox_forbidden"):
            service.poll_enrollment(
                to_host,
                after_sequence=0,
                limit=4,
                now=NOW + 2,
            )
        page = service.poll_enrollment(
            to_host,
            after_sequence=0,
            limit=4,
            now=NOW + 2,
            host_admission=host,
        )
        assert page.deliveries[0].opaque_record == b"encrypted-enrollment-request"
        service.acknowledge_enrollment(
            RelayEnrollmentAcknowledgement(
                mailbox=to_host,
                sequence=1,
                message_id=b"q" * 16,
            ),
            now=NOW + 3,
            host_admission=host,
        )

        to_controller = RelayEnrollmentMailbox(
            route_id=identity.route_id,
            pairing_handle=handle,
            recipient="controller",
        )
        response = RelayEnrollmentPublish(
            mailbox=to_controller,
            message_id=b"a" * 16,
            expires_at=NOW + 60,
            opaque_record=b"encrypted-enrollment-response",
        )
        with pytest.raises(
            BlindRelayError,
            match="relay_mailbox_forbidden",
        ):
            service.publish_enrollment(response, now=NOW + 3)
        service.publish_enrollment(
            response,
            now=NOW + 3,
            host_admission=host,
        )
        controller_page = service.poll_enrollment(
            to_controller,
            after_sequence=0,
            limit=4,
            now=NOW + 4,
        )
        assert controller_page.deliveries[0].opaque_record == (
            b"encrypted-enrollment-response"
        )
    finally:
        store.close()
        service.close()


def test_machine_signed_revocation_evicts_queues_and_blocks_reauthentication(tmp_path):
    service = BlindRelayService(relay_origin=ORIGIN)
    store, identity = make_identity(tmp_path)
    controller_key = Ed25519PrivateKey.generate()
    serial = b"z" * 16
    try:
        host = authenticate_host(service, identity)
        controller, certificate = authenticate_controller(
            service,
            identity,
            serial=serial,
            private_key=controller_key,
        )
        mailbox = RelayMailbox(
            route_id=identity.route_id,
            credential_serial=serial,
            recipient="host",
        )
        service.publish(
            controller,
            RelayPublish(
                mailbox=mailbox,
                message_id=b"m" * 16,
                expires_at=NOW + 60,
                opaque_record=b"opaque",
            ),
            now=NOW + 2,
        )
        service.revoke(
            host,
            create_relay_revocation(
                machine_identity=identity,
                credential_serial=serial,
                relay_origin=ORIGIN,
                now=NOW + 3,
            ),
            now=NOW + 3,
        )
        assert service.snapshot(now=NOW + 4).application_records == 0
        with pytest.raises(BlindRelayError, match="relay_credential_revoked"):
            service.publish(
                controller,
                RelayPublish(
                    mailbox=mailbox,
                    message_id=b"n" * 16,
                    expires_at=NOW + 60,
                    opaque_record=b"opaque",
                ),
                now=NOW + 4,
            )

        challenge = service.issue_challenge(now=NOW + 4, nonce=b"r" * 32)
        with pytest.raises(BlindRelayError, match="relay_credential_revoked"):
            service.authenticate(
                create_controller_authentication(
                    route_id=identity.route_id,
                    credential_serial=serial,
                    admission_certificate=certificate,
                    controller_private_key=controller_key,
                    challenge=challenge,
                    relay_origin=ORIGIN,
                    now=NOW + 5,
                ),
                now=NOW + 5,
            )
    finally:
        store.close()
        service.close()


def test_durable_relay_keeps_opaque_records_and_route_binding_across_restart(tmp_path):
    relay_path = tmp_path / "relay.sqlite3"
    store, identity = make_identity(tmp_path)
    controller_key = Ed25519PrivateKey.generate()
    serial = b"d" * 16
    first = BlindRelayService(relay_origin=ORIGIN, db_path=relay_path)
    try:
        host = authenticate_host(first, identity)
        controller, _certificate_bytes = authenticate_controller(
            first,
            identity,
            serial=serial,
            private_key=controller_key,
        )
        mailbox = RelayMailbox(
            route_id=identity.route_id,
            credential_serial=serial,
            recipient="host",
        )
        first.publish(
            controller,
            RelayPublish(
                mailbox=mailbox,
                message_id=b"d" * 16,
                expires_at=NOW + 60,
                opaque_record=b"opaque-after-restart",
            ),
            now=NOW + 2,
        )
    finally:
        first.close()

    second = BlindRelayService(relay_origin=ORIGIN, db_path=relay_path)
    try:
        host = authenticate_host(second, identity, now=NOW + 3)
        page = second.poll(
            host,
            mailbox,
            after_sequence=0,
            limit=10,
            now=NOW + 4,
        )
        assert page.deliveries[0].opaque_record == b"opaque-after-restart"
        assert b"opaque-after-restart" in relay_path.read_bytes()
        # Relay persistence is allowed to contain only this already-encrypted
        # application record; no test plaintext method or parameter is present.
        assert b"prompt.submit" not in relay_path.read_bytes()
    finally:
        store.close()
        second.close()
