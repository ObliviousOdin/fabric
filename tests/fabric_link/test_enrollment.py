from __future__ import annotations

import hashlib
import secrets

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from fabric_link.core import PairBootstrap, StateUpdate
from fabric_link.enrollment import (
    ENROLLMENT_NONCE_BYTES,
    EncryptedEnrollment,
    EnrollmentManager,
    LinkEnrollmentError,
    LinkRevocationIncomplete,
    _aad,
    _derive_key,
    build_enrollment_request,
    decrypt_enrollment_response,
    revoke_device,
)
from fabric_link.protocol import canonical_dumps, canonical_loads
from fabric_link.store import LinkDeviceStore

NOW = 1_784_840_000


class FakeCore:
    def __init__(self, *, fail_remove: bool = False) -> None:
        self.fail_remove = fail_remove
        self.group_ids: list[bytes] = []

    def create_pair(
        self,
        *,
        host_identity: bytes,
        group_id: bytes,
        controller_key_package: bytes,
    ) -> PairBootstrap:
        assert host_identity.startswith(b"fabric-machine:")
        assert controller_key_package.startswith(b"key-package:")
        self.group_ids.append(group_id)
        return PairBootstrap(
            host_state=b"host-state:" + group_id,
            welcome=b"welcome:" + group_id,
        )

    def remove_controller(self, *, host_state: bytes) -> StateUpdate:
        if self.fail_remove:
            raise RuntimeError("simulated MLS failure")
        return StateUpdate(
            opaque_state=b"removed:" + host_state,
            message=b"remove-commit",
        )


def make_store(tmp_path) -> LinkDeviceStore:
    root = tmp_path / "link"
    return LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    )


def open_request(
    manager: EnrollmentManager,
    *,
    grants: tuple[str, ...] = ("observe", "chat", "dispatch"),
):
    payload = manager.open_pairing(
        relay="https://relay.example",
        requested_grants=grants,
        now=NOW,
    )
    request, envelope = build_enrollment_request(
        payload=payload,
        controller_name="Owner's iPhone",
        platform="ios",
        requested_grants=grants,
        relay_public_key=b"p" * 32,
        key_package=b"key-package:" + secrets.token_bytes(32),
        now=NOW + 1,
    )
    return payload, request, envelope


def test_pairing_requires_local_approval_and_persists_no_qr_secret(tmp_path):
    with make_store(tmp_path) as store:
        manager = EnrollmentManager(store=store, core=FakeCore())
        payload, request, envelope = open_request(manager)

        for path in store.path.parent.iterdir():
            if path.is_file():
                assert payload.secret not in path.read_bytes()
        assert repr(payload).find(repr(payload.secret)) == -1
        assert store.list_devices() == []

        approval = manager.receive_request(envelope, now=NOW + 2)
        assert approval.controller_name == "Owner's iPhone"
        assert approval.platform == "ios"
        assert len(approval.short_auth_string) == 6
        assert approval.short_auth_string.isdigit()
        assert store.list_devices() == []

        duplicate = manager.receive_request(envelope, now=NOW + 2)
        assert duplicate == approval

        encrypted_response = manager.approve(
            handle=payload.handle,
            approved_grants=("observe", "chat"),
            now=NOW + 3,
        )
        result = decrypt_enrollment_response(
            payload=payload,
            request=request,
            encrypted_response=encrypted_response,
            now=NOW + 4,
        )
        assert result.approved_grants == ("chat", "observe")
        assert len(result.credential_serial) == 16
        assert result.welcome.startswith(b"welcome:")

        devices = store.list_devices()
        assert len(devices) == 1
        assert devices[0].grants == ("chat", "observe")
        assert devices[0].credential_hash == hashlib.sha256(
            request.key_package
        ).digest()


def test_qr_capturing_attacker_cannot_forge_machine_response(tmp_path):
    with make_store(tmp_path) as store:
        manager = EnrollmentManager(store=store, core=FakeCore())
        payload, request, envelope = open_request(manager)
        manager.receive_request(envelope, now=NOW + 2)
        encrypted = manager.approve(
            handle=payload.handle,
            approved_grants=("observe",),
            now=NOW + 3,
        )

        original = EncryptedEnrollment.from_cbor(encrypted)
        plaintext = AESGCM(_derive_key(payload, response=True)).decrypt(
            original.nonce,
            original.ciphertext,
            _aad(payload, response=True),
        )
        forged = canonical_loads(plaintext, maximum=256 * 1024, expected_type=dict)
        forged["machine_signature"] = b"f" * 64
        nonce = secrets.token_bytes(ENROLLMENT_NONCE_BYTES)
        ciphertext = AESGCM(_derive_key(payload, response=True)).encrypt(
            nonce,
            canonical_dumps(forged),
            _aad(payload, response=True),
        )
        attacker_response = EncryptedEnrollment(
            handle=payload.handle,
            nonce=nonce,
            ciphertext=ciphertext,
        ).to_cbor()

        with pytest.raises(LinkEnrollmentError, match="machine_signature_invalid"):
            decrypt_enrollment_response(
                payload=payload,
                request=request,
                encrypted_response=attacker_response,
                now=NOW + 4,
            )


def test_pending_enrollment_is_one_time_memory_state_and_has_grant_ceiling(tmp_path):
    with make_store(tmp_path) as store:
        manager = EnrollmentManager(store=store, core=FakeCore())
        payload = manager.open_pairing(
            relay="https://relay.example",
            requested_grants=("observe",),
            now=NOW,
        )
        _request, envelope = build_enrollment_request(
            payload=payload,
            controller_name="Desktop",
            platform="desktop",
            requested_grants=("dispatch",),
            relay_public_key=b"d" * 32,
            key_package=b"key-package:" + b"k" * 32,
            now=NOW + 1,
        )
        with pytest.raises(LinkEnrollmentError, match="invalid_enrollment_request"):
            manager.receive_request(envelope, now=NOW + 2)

        manager_after_restart = EnrollmentManager(store=store, core=FakeCore())
        with pytest.raises(LinkEnrollmentError, match="enrollment_expired"):
            manager_after_restart.receive_request(envelope, now=NOW + 2)


def test_different_request_cannot_replace_staged_controller(tmp_path):
    with make_store(tmp_path) as store:
        manager = EnrollmentManager(store=store, core=FakeCore())
        payload, _request, envelope = open_request(manager)
        manager.receive_request(envelope, now=NOW + 2)
        _other_request, other_envelope = build_enrollment_request(
            payload=payload,
            controller_name="Other phone",
            platform="android",
            requested_grants=("observe",),
            relay_public_key=b"a" * 32,
            key_package=b"key-package:" + b"o" * 32,
            now=NOW + 2,
        )
        with pytest.raises(LinkEnrollmentError, match="enrollment_already_used"):
            manager.receive_request(other_envelope, now=NOW + 2)


def test_approval_cannot_add_unrequested_grant(tmp_path):
    with make_store(tmp_path) as store:
        manager = EnrollmentManager(store=store, core=FakeCore())
        payload, _request, envelope = open_request(
            manager,
            grants=("observe",),
        )
        manager.receive_request(envelope, now=NOW + 2)
        with pytest.raises(LinkEnrollmentError, match="grant_not_requested"):
            manager.approve(
                handle=payload.handle,
                approved_grants=("observe", "approve"),
                now=NOW + 3,
            )
        assert store.list_devices() == []


def test_two_controllers_receive_independent_pair_groups(tmp_path):
    core = FakeCore()
    with make_store(tmp_path) as store:
        manager = EnrollmentManager(store=store, core=core)
        group_ids = []
        for index in range(2):
            payload, request, envelope = open_request(manager)
            manager.receive_request(envelope, now=NOW + 2)
            encrypted = manager.approve(
                handle=payload.handle,
                approved_grants=("observe",),
                now=NOW + 3,
            )
            result = decrypt_enrollment_response(
                payload=payload,
                request=request,
                encrypted_response=encrypted,
                now=NOW + 4,
            )
            group_ids.append(result.group_id)
        assert group_ids[0] != group_ids[1]
        assert len(store.list_devices()) == 2


def test_revocation_is_locally_authoritative_even_if_mls_cleanup_fails(tmp_path):
    with make_store(tmp_path) as store:
        manager = EnrollmentManager(store=store, core=FakeCore())
        payload, _request, envelope = open_request(manager)
        manager.receive_request(envelope, now=NOW + 2)
        manager.approve(
            handle=payload.handle,
            approved_grants=("observe",),
            now=NOW + 3,
        )
        device = store.list_devices()[0]

        with pytest.raises(LinkRevocationIncomplete):
            revoke_device(
                store=store,
                core=FakeCore(fail_remove=True),
                device_id=device.device_id,
                now=NOW + 4,
            )
        denied = store.get_device(device.device_id)
        assert denied is not None
        assert denied.status == "revoked"
        assert denied.final_remove_commit is None

        reconciled = revoke_device(
            store=store,
            core=FakeCore(),
            device_id=device.device_id,
            now=NOW + 5,
        )
        assert reconciled.status == "revoked"
        assert reconciled.final_remove_commit == b"remove-commit"

        idempotent = revoke_device(
            store=store,
            core=FakeCore(fail_remove=True),
            device_id=device.device_id,
            now=NOW + 6,
        )
        assert idempotent.final_remove_commit == b"remove-commit"
