from __future__ import annotations

import secrets
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fabric_link.application import LinkApplicationController
from fabric_link.broker import (
    BrokerOutbox,
    BrokerOwnershipLease,
    FabricLinkBroker,
    LinkBrokerError,
)
from fabric_link.capabilities import LINK_REMOTE_METHODS
from fabric_link.core import OpenMLSCore
from fabric_link.enrollment import (
    EnrollmentManager,
    _certificate,
    build_enrollment_request,
    decrypt_enrollment_response,
)
from fabric_link.protocol import LinkRequest, canonical_dumps
from fabric_link.relay_auth import (
    create_controller_authentication,
    create_host_authentication,
)
from fabric_link.relay_client import LinkRelayClientError
from fabric_link.relay_contract import (
    RelayMailbox,
    RelayPoll,
    RelayPublish,
    RelayReady,
    RelaySync,
)
from fabric_link.relay_service import BlindRelayError, BlindRelayService
from fabric_link.store import LinkDeviceStore

generated_binding = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "fabric-link-core"
    / "target"
    / "generated-python"
)
if generated_binding.is_dir():
    sys.path.insert(0, str(generated_binding))

try:
    import fabric_link_core as link_core
except ImportError:
    link_core = None

NOW = 1_784_840_000
ORIGIN = "https://relay.example"


class FakeBridge:
    registered_methods = LINK_REMOTE_METHODS

    def __init__(self) -> None:
        self.calls = []
        self.revoked = []

    def dispatch(self, _device, request, params):
        self.calls.append((request.method, params))
        return {"machine": "host", "authenticated": True}

    def close(self) -> None:
        return None

    def revoke_device(self, device_id):
        self.revoked.append(device_id)


class ServiceClient:
    service: BlindRelayService
    fail_next_controller_publish = False

    def __init__(self, *, relay_origin, authentication_factory):
        assert relay_origin == ORIGIN
        self.authentication_factory = authentication_factory
        self.admission = None

    def connect(self):
        challenge = self.service.issue_challenge(now=NOW)
        self.admission = self.service.authenticate(
            self.authentication_factory(challenge),
            now=NOW,
        )
        return RelayReady(role=self.admission.role)

    def close(self):
        return None

    def poll(self, frame: RelayPoll):
        page = self.service.poll(
            self.admission,
            frame.mailbox,
            after_sequence=frame.after_sequence,
            limit=frame.limit,
            now=NOW,
        )
        return page.deliveries, RelaySync(
            request_id=frame.request_id,
            count=len(page.deliveries),
            high_watermark=page.high_watermark,
        )

    def publish(self, frame):
        if (
            frame.mailbox.recipient == "controller"
            and type(self).fail_next_controller_publish
        ):
            type(self).fail_next_controller_publish = False
            raise LinkRelayClientError("simulated_disconnect")
        sequence = self.service.publish(self.admission, frame, now=NOW)
        return type("Receipt", (), {"sequence": sequence})()

    def acknowledge(self, frame):
        sequence = self.service.acknowledge(self.admission, frame, now=NOW)
        return type("Receipt", (), {"sequence": sequence})()

    def revoke(self, frame):
        self.service.revoke(self.admission, frame, now=frame.issued_at)
        return type("Receipt", (), {"message_id": frame.credential_serial})()


def pair(tmp_path):
    root = tmp_path / "link"
    store = LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    )
    core = OpenMLSCore(link_core)
    bootstrap = core.create_controller(identity=b"broker-controller")
    relay_private_key = Ed25519PrivateKey.generate()
    relay_public_key = relay_private_key.public_key().public_bytes_raw()
    manager = EnrollmentManager(store=store, core=core)
    payload = manager.open_pairing(
        relay=ORIGIN,
        requested_grants=("observe",),
        now=NOW - 10,
    )
    request, encrypted_request = build_enrollment_request(
        payload=payload,
        controller_name="Broker test",
        platform="desktop",
        requested_grants=("observe",),
        relay_public_key=relay_public_key,
        key_package=bootstrap.key_package,
        now=NOW - 9,
    )
    manager.receive_request(encrypted_request, now=NOW - 8)
    encrypted_response = manager.approve(
        handle=payload.handle,
        approved_grants=("observe",),
        now=NOW - 7,
    )
    enrollment = decrypt_enrollment_response(
        payload=payload,
        request=request,
        encrypted_response=encrypted_response,
        now=NOW - 6,
    )
    controller = LinkApplicationController(
        core=core,
        route_id=payload.route,
        credential_serial=enrollment.credential_serial,
        opaque_state=core.join_controller(
            opaque_state=bootstrap.opaque_state,
            welcome=enrollment.welcome,
        ),
    )
    return (
        store,
        core,
        controller,
        request,
        enrollment,
        relay_private_key,
        payload,
    )


def authenticate_controller(
    service,
    *,
    enrollment,
    private_key,
    payload,
):
    challenge = service.issue_challenge(now=NOW)
    return service.authenticate(
        create_controller_authentication(
            route_id=payload.route,
            credential_serial=enrollment.credential_serial,
            admission_certificate=enrollment.admission_certificate,
            controller_private_key=private_key,
            challenge=challenge,
            relay_origin=ORIGIN,
            now=NOW,
        ),
        now=NOW,
    )


def test_broker_lease_is_exclusive_and_recoverable(tmp_path):
    first = BrokerOwnershipLease(tmp_path / "broker.lock")
    second = BrokerOwnershipLease(tmp_path / "broker.lock")
    first.acquire()
    with pytest.raises(LinkBrokerError, match="broker_already_running"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


@pytest.mark.skipif(
    link_core is None,
    reason="generated OpenMLS binding is built in the native verification gate",
)
def test_broker_carries_encrypted_rpc_and_recovers_outbox_after_disconnect(tmp_path):
    (
        store,
        core,
        controller,
        _enrollment_request,
        enrollment,
        controller_private_key,
        payload,
    ) = pair(tmp_path)
    service = BlindRelayService(relay_origin=ORIGIN)
    ServiceClient.service = service
    identity = store.machine_identity()
    challenge = service.issue_challenge(now=NOW)
    service.authenticate(
        create_host_authentication(
            machine_identity=identity,
            challenge=challenge,
            relay_origin=ORIGIN,
            now=NOW,
        ),
        now=NOW,
    )
    controller_admission = authenticate_controller(
        service,
        enrollment=enrollment,
        private_key=controller_private_key,
        payload=payload,
    )
    request = LinkRequest(
        request_id=b"q" * 16,
        idempotency_key=b"i" * 16,
        issued_at=NOW - 1,
        expires_at=NOW + 120,
        method="connection.context",
        params_cbor=canonical_dumps({}),
    )
    encrypted_request = controller.encrypt_request(request)
    request_mailbox = RelayMailbox(
        route_id=payload.route,
        credential_serial=enrollment.credential_serial,
        recipient="host",
    )
    service.publish(
        controller_admission,
        RelayPublish(
            mailbox=request_mailbox,
            message_id=b"m" * 16,
            expires_at=NOW + 120,
            opaque_record=encrypted_request,
        ),
        now=NOW,
    )
    outbox = BrokerOutbox(store)
    bridge = FakeBridge()
    broker = FabricLinkBroker(
        relay_origin=ORIGIN,
        store=store,
        core=core,
        outbox=outbox,
        bridge=bridge,  # type: ignore[arg-type]
        client_factory=ServiceClient,
    )
    ServiceClient.fail_next_controller_publish = True

    with pytest.raises(LinkBrokerError, match="simulated_disconnect"):
        broker.run_once(now=NOW)
    assert len(outbox.pending()) == 1
    assert service.snapshot(now=NOW).application_records == 1

    result = broker.run_once(now=NOW)

    assert result.responses_flushed == 1
    assert outbox.pending() == ()
    assert bridge.calls == [("connection.context", {})]
    controller_page = service.poll(
        controller_admission,
        RelayMailbox(
            route_id=payload.route,
            credential_serial=enrollment.credential_serial,
            recipient="controller",
        ),
        after_sequence=0,
        limit=10,
        now=NOW,
    )
    response = controller.decrypt_response(controller_page.deliveries[0].opaque_record)
    assert response.ok
    assert canonical_dumps({"machine": "host", "authenticated": True}) == (
        response.result_cbor
    )
    broker.close()
    store.close()
    service.close()


@pytest.mark.skipif(
    link_core is None,
    reason="generated OpenMLS binding is built in the native verification gate",
)
def test_broker_detaches_and_relay_revokes_a_locally_denied_controller(tmp_path):
    (
        store,
        core,
        _controller,
        _enrollment_request,
        enrollment,
        controller_private_key,
        payload,
    ) = pair(tmp_path)
    service = BlindRelayService(relay_origin=ORIGIN)
    ServiceClient.service = service
    identity = store.machine_identity()
    challenge = service.issue_challenge(now=NOW)
    service.authenticate(
        create_host_authentication(
            machine_identity=identity,
            challenge=challenge,
            relay_origin=ORIGIN,
            now=NOW,
        ),
        now=NOW,
    )
    controller_admission = authenticate_controller(
        service,
        enrollment=enrollment,
        private_key=controller_private_key,
        payload=payload,
    )
    bridge = FakeBridge()
    broker = FabricLinkBroker(
        relay_origin=ORIGIN,
        store=store,
        core=core,
        bridge=bridge,  # type: ignore[arg-type]
        client_factory=ServiceClient,
    )
    broker.run_once(now=NOW)
    device = store.list_devices()[0]
    store.deny_device(device.device_id, now=NOW + 1)

    broker.run_once(now=NOW + 2)

    assert bridge.revoked == [device.device_id]
    assert store.relay_revocation_delivered(
        credential_serial=device.credential_serial,
        relay_origin=ORIGIN,
    )
    with pytest.raises(BlindRelayError, match="relay_credential_revoked"):
        service.publish(
            controller_admission,
            RelayPublish(
                mailbox=RelayMailbox(
                    route_id=payload.route,
                    credential_serial=enrollment.credential_serial,
                    recipient="host",
                ),
                message_id=b"r" * 16,
                expires_at=NOW + 60,
                opaque_record=b"opaque",
            ),
            now=NOW + 3,
        )
    broker.close()
    store.close()
    service.close()
