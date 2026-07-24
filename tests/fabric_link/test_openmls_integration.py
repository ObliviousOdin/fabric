from __future__ import annotations

import secrets
import sys
from pathlib import Path

import pytest

from fabric_link.core import OpenMLSCore
from fabric_link.enrollment import (
    EnrollmentManager,
    build_enrollment_request,
    decrypt_enrollment_response,
    revoke_device,
)
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


def test_real_openmls_two_controller_enrollment_isolation_and_removal(tmp_path):
    root = tmp_path / "link"
    core = OpenMLSCore(link_core)
    with LinkDeviceStore(
        db_path=root / "state.sqlite3",
        key_path=root / "route.key",
    ) as store:
        manager = EnrollmentManager(store=store, core=core)
        controllers = []
        paired_devices = []
        expected_grants = [
            ("observe",),
            ("chat", "dispatch", "observe"),
        ]

        for index, grants in enumerate(expected_grants):
            bootstrap = link_core.fabric_link_create_controller(
                f"controller-{index}".encode()
            )
            payload = manager.open_pairing(
                relay="https://relay.example",
                requested_grants=grants,
                now=NOW,
            )
            request, envelope = build_enrollment_request(
                payload=payload,
                controller_name=f"Controller {index}",
                platform="desktop",
                requested_grants=grants,
                relay_public_key=secrets.token_bytes(32),
                key_package=bootstrap.key_package,
                now=NOW + 1,
            )
            manager.receive_request(envelope, now=NOW + 2)
            encrypted_response = manager.approve(
                handle=payload.handle,
                approved_grants=grants,
                now=NOW + 3,
            )
            response = decrypt_enrollment_response(
                payload=payload,
                request=request,
                encrypted_response=encrypted_response,
                now=NOW + 4,
            )
            controller_state = link_core.fabric_link_controller_join(
                bootstrap.opaque_state,
                response.welcome,
            )
            controllers.append(controller_state)
            device = store.get_device_by_credential(request.credential_hash)
            assert device is not None
            paired_devices.append(device)

        devices = store.list_devices()
        assert paired_devices[0].group_id != paired_devices[1].group_id
        assert [device.grants for device in paired_devices] == expected_grants
        assert len(devices) == 2

        encrypted = link_core.fabric_link_host_encrypt(
            paired_devices[0].host_state,
            b"controller zero only",
        )
        decrypted = link_core.fabric_link_controller_decrypt(
            controllers[0],
            encrypted.message,
        )
        assert decrypted.plaintext == b"controller zero only"
        with pytest.raises(link_core.FabricLinkCoreError):
            link_core.fabric_link_controller_decrypt(
                controllers[1],
                encrypted.message,
            )

        revoked = revoke_device(
            store=store,
            core=core,
            device_id=paired_devices[0].device_id,
            now=NOW + 5,
        )
        assert revoked.status == "revoked"
        assert revoked.final_remove_commit
        removed = link_core.fabric_link_controller_apply_commit(
            decrypted.opaque_state,
            revoked.final_remove_commit,
        )
        assert removed.active is False
        with pytest.raises(Exception, match="device_not_active"):
            store.require_active(paired_devices[0].credential_hash)
