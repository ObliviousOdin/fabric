from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import fabric_link_core as link


interop_path = Path(os.environ["FABRIC_LINK_INTEROP_FIXTURE"])
interop = json.loads(interop_path.read_text(encoding="utf-8"))
assert interop["protocol_version"] == link.fabric_link_protocol_version()
for value_key, digest_key in (
    ("pairing_cbor_hex", "pairing_cbor_sha256_hex"),
    ("link_request_cbor_hex", "link_request_sha256_hex"),
    ("enrollment_request_cbor_hex", "enrollment_request_sha256_hex"),
):
    assert (
        hashlib.sha256(bytes.fromhex(interop[value_key])).hexdigest()
        == interop[digest_key]
    )

controller = link.fabric_link_create_controller(b"python-controller")
assert (
    link.fabric_link_controller_key_package(controller.opaque_state)
    == controller.key_package
)
pair = link.fabric_link_create_pair(
    b"python-host",
    b"python-binding-pair",
    controller.key_package,
)
controller_state = link.fabric_link_controller_join(
    controller.opaque_state,
    pair.welcome,
)
encrypted = link.fabric_link_host_encrypt(pair.host_state, b"python fixture")
if fixture_path := os.environ.get("FABRIC_LINK_FIXTURE_DIR"):
    fixture_dir = Path(fixture_path)
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "controller-state.bin").write_bytes(controller_state)
    (fixture_dir / "message.bin").write_bytes(encrypted.message)
    (fixture_dir / "plaintext.bin").write_bytes(b"python fixture")
decrypted = link.fabric_link_controller_decrypt(
    controller_state,
    encrypted.message,
)
assert decrypted.plaintext == b"python fixture"

controller_encrypted = link.fabric_link_controller_encrypt(
    decrypted.opaque_state,
    b"python controller fixture",
)
host_decrypted = link.fabric_link_host_decrypt(
    encrypted.opaque_state,
    controller_encrypted.message,
)
assert host_decrypted.plaintext == b"python controller fixture"

removal = link.fabric_link_host_remove_controller(host_decrypted.opaque_state)
removed = link.fabric_link_controller_apply_commit(
    controller_encrypted.opaque_state,
    removal.message,
)
assert not removed.active
print("PASS Python UniFFI bidirectional pairing/restart/removal + v3 corpus")
