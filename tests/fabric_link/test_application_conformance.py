from __future__ import annotations

import secrets
import sys
from pathlib import Path

import pytest

from fabric_link.application import (
    InMemoryLinkDeliveryService,
    LinkApplicationController,
    LinkApplicationError,
    LinkApplicationHost,
)
from fabric_link.core import OpenMLSCore
from fabric_link.enrollment import (
    EnrollmentManager,
    build_enrollment_request,
    decrypt_enrollment_response,
)
from fabric_link.protocol import LinkApplicationEnvelope, LinkRequest, canonical_dumps
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

link_core = pytest.importorskip(
    "fabric_link_core",
    reason="generated OpenMLS binding is built in the native verification gate",
)

NOW = 1_784_840_000


def paired_application(tmp_path, *, grants: tuple[str, ...] = ("dispatch",)):
    root = tmp_path / "link"
    store = LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    )
    core = OpenMLSCore(link_core)
    bootstrap = core.create_controller(identity=b"conformance-controller")
    manager = EnrollmentManager(store=store, core=core)
    payload = manager.open_pairing(
        relay="https://relay.example",
        requested_grants=grants,
        now=NOW,
    )
    request, encrypted_request = build_enrollment_request(
        payload=payload,
        controller_name="Conformance controller",
        platform="desktop",
        requested_grants=grants,
        relay_public_key=secrets.token_bytes(32),
        key_package=bootstrap.key_package,
        now=NOW + 1,
    )
    manager.receive_request(encrypted_request, now=NOW + 2)
    encrypted_response = manager.approve(
        handle=payload.handle,
        approved_grants=grants,
        now=NOW + 3,
    )
    enrollment = decrypt_enrollment_response(
        payload=payload,
        request=request,
        encrypted_response=encrypted_response,
        now=NOW + 4,
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
    device = store.get_device_by_credential(request.credential_hash)
    assert device is not None
    return store, core, controller, device


def link_request(*, request_id: bytes = b"r" * 16, method: str = "job.create") -> LinkRequest:
    return LinkRequest(
        request_id=request_id,
        idempotency_key=b"i" * 16,
        issued_at=NOW + 5,
        expires_at=NOW + 120,
        method=method,
        params_cbor=canonical_dumps({"prompt": "make a durable work item"}),
    )


def test_encrypted_request_response_authorizes_before_dispatch_and_advances_both_states(tmp_path):
    store, core, controller, device = paired_application(tmp_path)
    calls: list[tuple[str, dict[str, object]]] = []
    host = LinkApplicationHost(
        core=core,
        store=store,
        registered_methods={"job.create"},
        dispatch=lambda _device, request, params: calls.append((request.method, params))
        or {"job_id": "job_123"},
    )
    delivery = InMemoryLinkDeliveryService()
    initial_controller_state = controller.opaque_state
    initial_host_state = device.host_state

    response = delivery.invoke(
        controller=controller,
        host=host,
        request=link_request(),
        now=NOW + 6,
    )

    assert response.ok is True
    assert response.error_code is None
    assert calls == [("job.create", {"prompt": "make a durable work item"})]
    assert controller.opaque_state != initial_controller_state
    updated = store.get_device(device.device_id)
    assert updated is not None
    assert updated.host_state != initial_host_state
    assert [trace.direction for trace in delivery.traces] == [
        "controller_to_host",
        "host_to_controller",
    ]
    assert all(trace.byte_length > 0 for trace in delivery.traces)
    assert all("job.create" not in repr(trace) for trace in delivery.traces)
    assert store.audit_records()[-1]["decision"] == "allow"
    store.close()


def test_denied_grant_returns_encrypted_error_without_dispatch(tmp_path):
    store, core, controller, _device = paired_application(tmp_path, grants=("observe",))
    calls: list[str] = []
    host = LinkApplicationHost(
        core=core,
        store=store,
        registered_methods={"job.create"},
        dispatch=lambda _device, request, _params: calls.append(request.method),
    )

    response = InMemoryLinkDeliveryService().invoke(
        controller=controller,
        host=host,
        request=link_request(),
        now=NOW + 6,
    )

    assert response.ok is False
    assert response.error_code == "method_not_granted"
    assert calls == []
    assert store.audit_records()[-1]["decision"] == "deny"
    assert store.audit_records()[-1]["error_code"] == "method_not_granted"
    store.close()


def test_unrecognized_serial_and_tampered_ciphertext_never_reach_dispatch(tmp_path):
    store, core, controller, _device = paired_application(tmp_path)
    calls: list[str] = []
    host = LinkApplicationHost(
        core=core,
        store=store,
        registered_methods={"job.create"},
        dispatch=lambda _device, request, _params: calls.append(request.method),
    )
    delivery = controller.encrypt_request(link_request())
    envelope = LinkApplicationEnvelope.from_cbor(delivery)
    unknown_serial = LinkApplicationEnvelope(
        route_id=envelope.route_id,
        credential_serial=b"z" * 16,
        ciphertext=envelope.ciphertext,
    ).to_cbor()
    with pytest.raises(LinkApplicationError, match="device_not_active"):
        host.receive(unknown_serial, now=NOW + 6)

    tampered = LinkApplicationEnvelope(
        route_id=envelope.route_id,
        credential_serial=envelope.credential_serial,
        ciphertext=envelope.ciphertext[:-1] + bytes([envelope.ciphertext[-1] ^ 1]),
    ).to_cbor()
    with pytest.raises(LinkApplicationError, match="request_decrypt_failed"):
        host.receive(tampered, now=NOW + 6)
    assert calls == []
    store.close()


def test_replayed_delivery_cannot_dispatch_twice(tmp_path):
    store, core, controller, _device = paired_application(tmp_path)
    calls: list[str] = []
    host = LinkApplicationHost(
        core=core,
        store=store,
        registered_methods={"job.create"},
        dispatch=lambda _device, request, _params: calls.append(request.method)
        or {"job_id": "job_123"},
    )
    delivery = controller.encrypt_request(link_request())
    first_response = host.receive(delivery, now=NOW + 6)
    first = controller.decrypt_response(first_response)
    assert first.ok is True

    with pytest.raises(LinkApplicationError):
        host.receive(delivery, now=NOW + 7)
    assert calls == ["job.create"]
    store.close()
