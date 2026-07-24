from __future__ import annotations

import os
import stat
import sys

import pytest

from fabric_link.authorization import (
    LinkAuthorizationError,
    authorize_link_request,
)
from fabric_link.capabilities import LINK_GRANT_METHODS, LINK_REMOTE_METHODS
from fabric_link.protocol import LinkRequest, canonical_dumps
from fabric_link.store import (
    LinkDevice,
    LinkDeviceStore,
    LinkReplayError,
    LinkStorageError,
)

NOW = 1_784_840_000


def test_reviewed_remote_projection_never_grants_privileged_input_surfaces():
    forbidden = {
        "shell.exec",
        "cli.exec",
        "sudo.respond",
        "secret.respond",
        "process.kill",
        "computer.screenshot",
        "cron.manage",
    }
    granted = frozenset().union(*LINK_GRANT_METHODS.values())
    assert granted <= LINK_REMOTE_METHODS
    assert forbidden.isdisjoint(LINK_REMOTE_METHODS)


def make_store(tmp_path) -> LinkDeviceStore:
    root = tmp_path / "link"
    return LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    )


def add_device(
    store: LinkDeviceStore,
    *,
    marker: int = 1,
    grants: tuple[str, ...] = ("chat", "dispatch", "observe"),
) -> LinkDevice:
    byte = bytes([marker])
    handle = byte * 32
    secret_marker = bytes([marker + 20]) * 32
    store.register_pending(
        handle=handle,
        secret_marker=secret_marker,
        requested_grants=grants,
        created_at=NOW,
        expires_at=NOW + 300,
    )
    device = LinkDevice(
        device_id=f"device_{marker:024x}",
        credential_hash=byte * 32,
        controller_name=f"Controller {marker}",
        platform="ios",
        grants=tuple(sorted(grants)),
        group_id=bytes([marker + 1]) * 32,
        host_state=b"opaque-state-" + byte,
        relay_public_key=bytes([marker + 2]) * 32,
        credential_serial=bytes([marker + 3]) * 16,
        admission_certificate=b"signed-certificate-" + byte,
        status="active",
        created_at=NOW,
        updated_at=NOW,
        revoked_at=None,
        final_remove_commit=None,
    )
    store.consume_pending_and_add_device(
        handle=handle,
        secret_marker=secret_marker,
        device=device,
        now=NOW + 1,
    )
    return device


def request(
    *,
    method: str = "job.create",
    request_id: bytes = b"q" * 16,
    issued_at: int = NOW,
    expires_at: int = NOW + 120,
) -> LinkRequest:
    return LinkRequest(
        request_id=request_id,
        idempotency_key=b"i" * 16,
        issued_at=issued_at,
        expires_at=expires_at,
        method=method,
        params_cbor=canonical_dumps({"prompt": "bounded"}),
    )


def test_machine_identity_is_stable_and_owner_only(tmp_path):
    with make_store(tmp_path) as store:
        first = store.machine_identity()
        second = store.machine_identity()

        assert first.route_id == second.route_id
        assert first.public_key == second.public_key
        assert len(first.route_id) == 32
        assert len(first.public_key) == 32
        assert first.sign(b"proof") == second.sign(b"proof")

        if sys.platform != "win32":
            assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
            assert stat.S_IMODE(store.key_path.stat().st_mode) == 0o600


def test_route_key_rejects_symlink_and_malformed_state(tmp_path):
    if sys.platform == "win32":
        pytest.skip("symlink creation requires Windows developer mode")
    root = tmp_path / "link"
    root.mkdir()
    target = tmp_path / "target"
    target.write_bytes(os.urandom(32))
    (root / "route.key").symlink_to(target)

    with LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    ) as store:
        with pytest.raises(LinkStorageError, match="storage_path_not_regular"):
            store.machine_identity()


def test_device_grants_replay_scope_and_local_first_revocation(tmp_path):
    with make_store(tmp_path) as store:
        first = add_device(store, marker=1)
        second = add_device(store, marker=2)

        assert store.require_active(first.credential_hash).device_id == first.device_id
        assert (
            store.require_active_by_credential_serial(first.credential_serial).device_id
            == first.device_id
        )
        changed = store.set_grants(first.device_id, ("observe",), now=NOW + 2)
        assert changed.grants == ("observe",)
        assert "job.create" not in changed.allowed_methods

        advanced = store.update_active_host_state(
            first.device_id,
            b"evolved-host-state",
            now=NOW + 2,
        )
        assert advanced.host_state == b"evolved-host-state"

        store.claim_request_id(
            device_id=first.device_id,
            request_id=b"x" * 16,
            request_expires_at=NOW + 300,
            now=NOW,
        )
        with pytest.raises(LinkReplayError, match="request_replayed"):
            store.claim_request_id(
                device_id=first.device_id,
                request_id=b"x" * 16,
                request_expires_at=NOW + 300,
                now=NOW,
            )
        store.claim_request_id(
            device_id=second.device_id,
            request_id=b"x" * 16,
            request_expires_at=NOW + 300,
            now=NOW,
        )

        denied = store.deny_device(first.device_id, now=NOW + 3)
        assert denied.status == "revoked"
        with pytest.raises(LinkStorageError, match="device_not_active"):
            store.require_active(first.credential_hash)
        with pytest.raises(LinkStorageError, match="device_not_active"):
            store.require_active_by_credential_serial(first.credential_serial)
        with pytest.raises(LinkStorageError, match="device_not_active"):
            store.update_active_host_state(
                first.device_id,
                b"must-not-revive",
                now=NOW + 3,
            )
        store.finish_revocation(
            first.device_id,
            host_state=b"removed-state",
            remove_commit=b"remove-commit",
            now=NOW + 4,
        )
        finished = store.get_device(first.device_id)
        assert finished is not None
        assert finished.final_remove_commit == b"remove-commit"


def test_authorization_checks_identity_grant_registry_freshness_and_replay(tmp_path):
    with make_store(tmp_path) as store:
        device = add_device(store)
        registered = {"job.create", "job.list", "prompt.submit"}

        allowed = authorize_link_request(
            sender_credential_hash=device.credential_hash,
            method="job.create",
            now=NOW + 1,
            request=request(),
            registry=store,
            registered_methods=registered,
        )
        assert allowed.device_id == device.device_id

        with pytest.raises(LinkAuthorizationError, match="request_replayed"):
            authorize_link_request(
                sender_credential_hash=device.credential_hash,
                method="job.create",
                now=NOW + 1,
                request=request(),
                registry=store,
                registered_methods=registered,
            )

        with pytest.raises(LinkAuthorizationError, match="method_not_granted"):
            authorize_link_request(
                sender_credential_hash=device.credential_hash,
                method="approval.respond",
                now=NOW + 1,
                request=request(
                    method="approval.respond",
                    request_id=b"a" * 16,
                ),
                registry=store,
                registered_methods={"approval.respond"},
            )

        with pytest.raises(LinkAuthorizationError, match="method_not_registered"):
            authorize_link_request(
                sender_credential_hash=device.credential_hash,
                method="job.cancel",
                now=NOW + 1,
                request=request(method="job.cancel", request_id=b"c" * 16),
                registry=store,
                registered_methods=registered,
            )

        with pytest.raises(LinkAuthorizationError, match="request_not_fresh"):
            authorize_link_request(
                sender_credential_hash=device.credential_hash,
                method="job.create",
                now=NOW + 500,
                request=request(request_id=b"s" * 16),
                registry=store,
                registered_methods=registered,
            )

        with pytest.raises(LinkAuthorizationError, match="device_not_active"):
            authorize_link_request(
                sender_credential_hash=b"z" * 32,
                method="job.create",
                now=NOW,
                request=request(request_id=b"u" * 16),
                registry=store,
                registered_methods=registered,
            )

        records = store.audit_records()
        assert [record["decision"] for record in records] == [
            "allow",
            "deny",
            "deny",
            "deny",
            "deny",
            "deny",
        ]
        assert all("bounded" not in str(record) for record in records)


def test_revocation_blocks_authorization_before_remove_commit_exists(tmp_path):
    with make_store(tmp_path) as store:
        device = add_device(store)
        store.deny_device(device.device_id, now=NOW)

        with pytest.raises(LinkAuthorizationError, match="device_not_active"):
            authorize_link_request(
                sender_credential_hash=device.credential_hash,
                method="job.create",
                now=NOW,
                request=request(),
                registry=store,
                registered_methods={"job.create"},
            )


def test_application_state_replay_audit_and_outbox_commit_atomically(tmp_path):
    with make_store(tmp_path) as store:
        device = add_device(store)
        store._conn.execute(
            "CREATE TRIGGER fail_test_outbox BEFORE INSERT ON response_outbox "
            "BEGIN SELECT RAISE(ABORT, 'simulated outbox failure'); END"
        )

        with pytest.raises(LinkStorageError, match="application_outbox_conflict"):
            store.commit_application_response(
                device=device,
                expected_host_state=device.host_state,
                evolved_host_state=b"evolved-state",
                request_id=b"t" * 16,
                request_expires_at=NOW + 120,
                method_class="dispatch",
                decision="allow",
                error_code=None,
                response_record=b"opaque-response",
                now=NOW + 1,
                source_sequence=1,
                source_message_id=b"m" * 16,
                response_expires_at=NOW + 120,
            )

        unchanged = store.get_device(device.device_id)
        assert unchanged is not None
        assert unchanged.host_state == device.host_state
        assert not store.request_id_claimed(
            device_id=device.device_id,
            request_id=b"t" * 16,
        )
        assert store.audit_records() == []
        assert store.response_outbox_pending() == ()
