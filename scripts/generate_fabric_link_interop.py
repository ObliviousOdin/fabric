#!/usr/bin/env python3
"""Generate the deterministic Fabric Link v3 interoperability corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fabric_link.enrollment import (
    EncryptedEnrollment,
    EnrollmentRequest,
    _aad,
    _derive_key,
)
from fabric_link.protocol import LinkRequest, PairingPayload, canonical_dumps

OUTPUT = ROOT / "fabric_link" / "fixtures" / "v3-interoperability.json"


def _sequence(start: int, length: int) -> bytes:
    return bytes(range(start, start + length))


def _sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_corpus() -> dict[str, int | str]:
    now = 1_784_840_000
    payload = PairingPayload(
        relay="https://relay.example",
        route=_sequence(0x00, 32),
        handle=_sequence(0x20, 32),
        secret=_sequence(0x40, 32),
        machine_key=_sequence(0x60, 32),
        expires_at=now + 300,
    )
    params_cbor = canonical_dumps(
        {
            "prompt": "fixture",
            "workspace": "/workspace",
        }
    )
    request = LinkRequest(
        request_id=_sequence(0x00, 16),
        idempotency_key=_sequence(0x10, 16),
        issued_at=now,
        expires_at=now + 120,
        method="job.create",
        params_cbor=params_cbor,
    )
    key_package = b"fixture-key-package"
    enrollment_request = EnrollmentRequest(
        handle=payload.handle,
        controller_nonce=_sequence(0xA0, 32),
        controller_name="Fixture Controller",
        platform="desktop",
        requested_grants=("dispatch", "observe"),
        relay_public_key=_sequence(0x80, 32),
        key_package=key_package,
        credential_hash=hashlib.sha256(key_package).digest(),
        issued_at=now,
        expires_at=now + 300,
    )

    pairing_cbor = payload.to_cbor()
    request_cbor = request.to_cbor()
    enrollment_request_cbor = enrollment_request.to_cbor()
    request_key = _derive_key(payload, response=False)
    response_key = _derive_key(payload, response=True)
    request_aad = _aad(payload, response=False)
    response_aad = _aad(payload, response=True)
    request_nonce = _sequence(0xC0, 12)
    request_ciphertext = AESGCM(request_key).encrypt(
        request_nonce,
        enrollment_request_cbor,
        request_aad,
    )
    request_envelope = EncryptedEnrollment(
        handle=payload.handle,
        nonce=request_nonce,
        ciphertext=request_ciphertext,
    ).to_cbor()
    response_plaintext = canonical_dumps(
        {
            "fixture": "response",
            "ok": True,
        }
    )
    response_nonce = _sequence(0xD0, 12)
    response_ciphertext = AESGCM(response_key).encrypt(
        response_nonce,
        response_plaintext,
        response_aad,
    )

    return {
        "schema_version": 1,
        "protocol_version": 3,
        "vector_purpose": "public deterministic test-only data; never use as credentials",
        "pairing_now": now,
        "relay_origin": payload.relay,
        "pairing_route_hex": payload.route.hex(),
        "pairing_handle_hex": payload.handle.hex(),
        "pairing_secret_hex": payload.secret.hex(),
        "pairing_machine_key_hex": payload.machine_key.hex(),
        "pairing_expires_at": payload.expires_at,
        "pairing_cbor_hex": pairing_cbor.hex(),
        "pairing_cbor_sha256_hex": _sha256_hex(pairing_cbor),
        "pairing_public_transcript_cbor_hex": payload.public_transcript_cbor().hex(),
        "pairing_url": payload.to_url(),
        "link_params_cbor_hex": params_cbor.hex(),
        "link_request_cbor_hex": request_cbor.hex(),
        "link_request_sha256_hex": _sha256_hex(request_cbor),
        "enrollment_request_cbor_hex": enrollment_request_cbor.hex(),
        "enrollment_request_sha256_hex": _sha256_hex(enrollment_request_cbor),
        "enrollment_request_key_hex": request_key.hex(),
        "enrollment_response_key_hex": response_key.hex(),
        "enrollment_request_aad_hex": request_aad.hex(),
        "enrollment_response_aad_hex": response_aad.hex(),
        "enrollment_request_nonce_hex": request_nonce.hex(),
        "enrollment_request_ciphertext_hex": request_ciphertext.hex(),
        "enrollment_request_envelope_cbor_hex": request_envelope.hex(),
        "enrollment_response_plaintext_cbor_hex": response_plaintext.hex(),
        "enrollment_response_nonce_hex": response_nonce.hex(),
        "enrollment_response_ciphertext_hex": response_ciphertext.hex(),
    }


def _render() -> str:
    return json.dumps(build_corpus(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the checked-in corpus differs from current protocol code",
    )
    args = parser.parse_args()
    rendered = _render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                "Fabric Link interoperability corpus is stale; run "
                "scripts/generate_fabric_link_interop.py"
            )
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(OUTPUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
