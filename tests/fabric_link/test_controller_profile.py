from __future__ import annotations

import pytest

from fabric_link.controller import LinkControllerError, PersistentLinkController
from fabric_link.controller_profile import (
    ControllerProfileStore,
    ControllerSecretBundle,
)
from fabric_link.core import ControllerDecryption, StateUpdate
from fabric_link.protocol import (
    LinkApplicationEnvelope,
    LinkRequest,
    LinkResponse,
    PairingPayload,
    canonical_dumps,
)

NOW = 1_784_840_000


class MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def load(self, controller_id: str) -> bytes | None:
        return self.values.get(controller_id)

    def store(self, controller_id: str, opaque_state: bytes) -> None:
        self.values[controller_id] = opaque_state

    def remove(self, controller_id: str) -> None:
        self.values.pop(controller_id, None)


class FakeCore:
    def controller_encrypt(
        self, *, opaque_state: bytes, plaintext: bytes
    ) -> StateUpdate:
        return StateUpdate(
            opaque_state=opaque_state + b"E",
            message=b"encrypted:" + plaintext,
        )

    def decrypt_controller(
        self,
        *,
        opaque_state: bytes,
        message: bytes,
    ) -> ControllerDecryption:
        if not message.startswith(b"encrypted:"):
            raise ValueError("invalid")
        return ControllerDecryption(
            opaque_state=opaque_state + b"D",
            plaintext=message.removeprefix(b"encrypted:"),
        )


def pairing_payload() -> PairingPayload:
    return PairingPayload(
        relay="https://relay.example",
        route=b"r" * 32,
        handle=b"h" * 32,
        secret=b"s" * 32,
        machine_key=b"m" * 32,
        expires_at=NOW + 300,
    )


def make_active_profile(tmp_path):
    vault = MemoryVault()
    profiles = ControllerProfileStore(
        vault=vault,
        db_path=tmp_path / "profiles" / "controllers.sqlite3",
    )
    payload = pairing_payload()
    pending = ControllerSecretBundle(
        opaque_state=b"state",
        relay_private_key=b"k" * 32,
        pairing_payload=payload.to_cbor(),
        enrollment_request=b"request",
    )
    profile = profiles.create_pending(
        label="My Mac",
        platform="desktop",
        payload=payload,
        secret_bundle=pending,
        now=NOW,
        controller_id="controller-test",
    )
    active = ControllerSecretBundle(
        opaque_state=b"state",
        relay_private_key=b"k" * 32,
        credential_serial=b"c" * 16,
        admission_certificate=b"signed-certificate",
        grants=("dispatch", "observe"),
    )
    profile = profiles.activate(
        profile.controller_id,
        credential_serial=b"c" * 16,
        admission_certificate=b"signed-certificate",
        grants=("dispatch", "observe"),
        active_bundle=active,
        now=NOW + 1,
    )
    return profiles, vault, profile


def request(
    request_id: bytes = b"q" * 16,
    *,
    issued_at: int = NOW + 2,
    expires_at: int = NOW + 60,
) -> LinkRequest:
    return LinkRequest(
        request_id=request_id,
        idempotency_key=b"i" * 16,
        issued_at=issued_at,
        expires_at=expires_at,
        method="job.create",
        params_cbor=canonical_dumps({"prompt": "ship it"}),
    )


def test_profile_database_contains_public_metadata_but_no_controller_secrets(tmp_path):
    profiles, _vault, profile = make_active_profile(tmp_path)
    try:
        stored = profiles.get(profile.controller_id)
        assert stored is not None
        assert stored.route_id == profile.route_id
        assert stored.admission_certificate == b"signed-certificate"
        database_files = [
            path.read_bytes()
            for path in profiles.path.parent.glob(f"{profiles.path.name}*")
        ]
        assert all(b"state" not in content for content in database_files)
        assert all(b"k" * 32 not in content for content in database_files)
    finally:
        profiles.close()


def test_vault_first_activation_reconciles_an_interrupted_metadata_commit(tmp_path):
    vault = MemoryVault()
    profiles = ControllerProfileStore(
        vault=vault,
        db_path=tmp_path / "profiles" / "controllers.sqlite3",
    )
    payload = pairing_payload()
    profile = profiles.create_pending(
        label="Phone",
        platform="ios",
        payload=payload,
        secret_bundle=ControllerSecretBundle(
            opaque_state=b"pending-state",
            relay_private_key=b"k" * 32,
            pairing_payload=payload.to_cbor(),
            enrollment_request=b"request",
        ),
        now=NOW,
        controller_id="controller-reconcile",
    )
    vault.store(
        profile.controller_id,
        ControllerSecretBundle(
            opaque_state=b"active-state",
            relay_private_key=b"k" * 32,
            credential_serial=b"c" * 16,
            admission_certificate=b"certificate",
            grants=("observe",),
        ).to_cbor(),
    )

    bundle = profiles.load_secret(profile.controller_id)

    assert bundle.opaque_state == b"active-state"
    reconciled = profiles.get(profile.controller_id)
    assert reconciled is not None
    assert reconciled.status == "active"
    assert reconciled.credential_serial == b"c" * 16
    profiles.close()


def test_persistent_controller_retries_one_ciphertext_and_commits_response_state(
    tmp_path,
):
    profiles, _vault, profile = make_active_profile(tmp_path)
    controller = PersistentLinkController(
        profiles=profiles,
        core=FakeCore(),  # type: ignore[arg-type]
        controller_id=profile.controller_id,
    )
    first = controller.encrypt_request(request(), now=NOW + 2)
    retried = controller.encrypt_request(request(), now=NOW + 2)

    assert retried == first
    assert profiles.load_secret(profile.controller_id).opaque_state == b"stateE"
    with pytest.raises(LinkControllerError, match="controller_request_in_flight"):
        controller.encrypt_request(request(b"x" * 16), now=NOW + 2)

    response = LinkResponse(
        request_id=b"q" * 16,
        completed_at=NOW + 3,
        ok=True,
        result_cbor=canonical_dumps({"job_id": "job-1"}),
        error_code=None,
    )
    delivery = LinkApplicationEnvelope(
        route_id=profile.route_id,
        credential_serial=b"c" * 16,
        ciphertext=b"encrypted:" + response.to_cbor(),
    ).to_cbor()

    result = controller.decrypt_response(delivery)

    assert result.ok
    bundle = profiles.load_secret(profile.controller_id)
    assert bundle.opaque_state == b"stateED"
    assert bundle.pending_application is None
    profiles.close()


def test_pending_request_can_only_be_abandoned_after_its_expiry(tmp_path):
    profiles, _vault, profile = make_active_profile(tmp_path)
    controller = PersistentLinkController(
        profiles=profiles,
        core=FakeCore(),  # type: ignore[arg-type]
        controller_id=profile.controller_id,
    )
    controller.encrypt_request(request(), now=NOW + 2)

    assert controller.abandon_expired_request(now=NOW + 59) is False
    assert controller.abandon_expired_request(now=NOW + 61) is True
    assert profiles.load_secret(profile.controller_id).pending_application is None
    profiles.close()


def test_expired_pending_request_is_cleared_before_a_fresh_retry(tmp_path):
    profiles, _vault, profile = make_active_profile(tmp_path)
    controller = PersistentLinkController(
        profiles=profiles,
        core=FakeCore(),  # type: ignore[arg-type]
        controller_id=profile.controller_id,
    )
    controller.encrypt_request(request(), now=NOW + 2)

    fresh = controller.encrypt_request(
        request(
            b"x" * 16,
            issued_at=NOW + 61,
            expires_at=NOW + 120,
        ),
        now=NOW + 61,
    )

    assert fresh.request_id == b"x" * 16
    bundle = profiles.load_secret(profile.controller_id)
    assert bundle.opaque_state == b"stateEE"
    assert bundle.pending_application is not None
    assert bundle.pending_application.request_id == b"x" * 16
    profiles.close()
