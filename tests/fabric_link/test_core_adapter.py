from __future__ import annotations

from types import SimpleNamespace

import pytest

from fabric_link.core import LinkCoreUnavailable, OpenMLSCore


def binding(*, version=3, ciphersuite=None):
    expected = "MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519"
    return SimpleNamespace(
        fabric_link_protocol_version=lambda: version,
        fabric_link_ciphersuite=lambda: ciphersuite or expected,
    )


def test_native_adapter_requires_exact_protocol_and_ciphersuite():
    assert isinstance(OpenMLSCore(binding()), OpenMLSCore)

    with pytest.raises(LinkCoreUnavailable, match="protocol mismatch"):
        OpenMLSCore(binding(version=2))

    with pytest.raises(LinkCoreUnavailable, match="ciphersuite mismatch"):
        OpenMLSCore(binding(ciphersuite="unreviewed"))


def test_native_adapter_wraps_controller_state_transitions():
    native = binding()
    native.fabric_link_create_controller = lambda identity: SimpleNamespace(
        opaque_state=identity + b"-state",
        key_package=b"key-package",
    )
    native.fabric_link_controller_key_package = lambda state: state + b"-key"
    native.fabric_link_host_encrypt = lambda state, plaintext: SimpleNamespace(
        opaque_state=state + b"-host-encrypted",
        message=plaintext[::-1],
    )
    native.fabric_link_host_decrypt = lambda state, message: SimpleNamespace(
        opaque_state=state + b"-host-decrypted",
        plaintext=message[::-1],
    )
    native.fabric_link_controller_encrypt = lambda state, plaintext: SimpleNamespace(
        opaque_state=state + b"-controller-encrypted",
        message=plaintext[::-1],
    )
    native.fabric_link_controller_join = lambda state, welcome: state + welcome
    native.fabric_link_controller_decrypt = lambda state, message: SimpleNamespace(
        opaque_state=state + b"-updated",
        plaintext=message[::-1],
    )
    native.fabric_link_controller_apply_commit = lambda state, commit: SimpleNamespace(
        opaque_state=state + commit,
        active=False,
    )
    core = OpenMLSCore(native)

    bootstrap = core.create_controller(identity=b"controller")
    assert bootstrap.opaque_state == b"controller-state"
    assert bootstrap.key_package == b"key-package"
    assert core.controller_key_package(opaque_state=bootstrap.opaque_state) == (
        b"controller-state-key"
    )
    host_encrypted = core.host_encrypt(
        opaque_state=b"host-state",
        plaintext=b"host message",
    )
    assert host_encrypted.opaque_state == b"host-state-host-encrypted"
    assert host_encrypted.message == b"egassem tsoh"
    host_decrypted = core.host_decrypt(
        opaque_state=b"host-state",
        message=b"egassem rellortnoc",
    )
    assert host_decrypted.opaque_state == b"host-state-host-decrypted"
    assert host_decrypted.plaintext == b"controller message"
    controller_encrypted = core.controller_encrypt(
        opaque_state=bootstrap.opaque_state,
        plaintext=b"controller message",
    )
    assert controller_encrypted.opaque_state == b"controller-state-controller-encrypted"
    assert controller_encrypted.message == b"egassem rellortnoc"
    joined = core.join_controller(
        opaque_state=bootstrap.opaque_state,
        welcome=b"welcome",
    )
    assert joined == b"controller-statewelcome"
    decrypted = core.decrypt_controller(
        opaque_state=joined,
        message=b"secret message",
    )
    assert decrypted.opaque_state == b"controller-statewelcome-updated"
    assert decrypted.plaintext == b"egassem terces"
    membership = core.apply_controller_commit(
        opaque_state=decrypted.opaque_state,
        commit=b"remove",
    )
    assert membership.opaque_state == b"controller-statewelcome-updatedremove"
    assert membership.active is False
