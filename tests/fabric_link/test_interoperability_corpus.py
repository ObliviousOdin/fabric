from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from fabric_link.enrollment import (
    EncryptedEnrollment,
    EnrollmentRequest,
    _aad,
    _derive_key,
)
from fabric_link.protocol import LinkRequest, PairingPayload

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "fabric_link" / "fixtures" / "v3-interoperability.json"


def _bytes(corpus: dict[str, object], key: str) -> bytes:
    value = corpus[key]
    assert isinstance(value, str)
    return bytes.fromhex(value)


def test_v3_interoperability_corpus_matches_protocol_implementation():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    pairing_cbor = _bytes(corpus, "pairing_cbor_hex")
    payload = PairingPayload.from_cbor(
        pairing_cbor,
        now=int(corpus["pairing_now"]),
    )

    assert corpus["schema_version"] == 1
    assert corpus["protocol_version"] == 3
    assert payload.to_url() == corpus["pairing_url"]
    assert payload.public_transcript_cbor() == _bytes(
        corpus,
        "pairing_public_transcript_cbor_hex",
    )
    assert hashlib.sha256(pairing_cbor).hexdigest() == corpus[
        "pairing_cbor_sha256_hex"
    ]

    link_request_cbor = _bytes(corpus, "link_request_cbor_hex")
    link_request = LinkRequest.from_cbor(link_request_cbor)
    assert link_request.to_cbor() == link_request_cbor
    assert link_request.params_cbor == _bytes(corpus, "link_params_cbor_hex")
    assert hashlib.sha256(link_request_cbor).hexdigest() == corpus[
        "link_request_sha256_hex"
    ]

    enrollment_request_cbor = _bytes(corpus, "enrollment_request_cbor_hex")
    assert EnrollmentRequest.from_cbor(
        enrollment_request_cbor
    ).to_cbor() == enrollment_request_cbor
    assert hashlib.sha256(enrollment_request_cbor).hexdigest() == corpus[
        "enrollment_request_sha256_hex"
    ]

    request_key = _derive_key(payload, response=False)
    response_key = _derive_key(payload, response=True)
    assert request_key == _bytes(corpus, "enrollment_request_key_hex")
    assert response_key == _bytes(corpus, "enrollment_response_key_hex")
    assert _aad(payload, response=False) == _bytes(
        corpus,
        "enrollment_request_aad_hex",
    )
    assert _aad(payload, response=True) == _bytes(
        corpus,
        "enrollment_response_aad_hex",
    )
    assert AESGCM(request_key).decrypt(
        _bytes(corpus, "enrollment_request_nonce_hex"),
        _bytes(corpus, "enrollment_request_ciphertext_hex"),
        _bytes(corpus, "enrollment_request_aad_hex"),
    ) == enrollment_request_cbor
    assert AESGCM(response_key).decrypt(
        _bytes(corpus, "enrollment_response_nonce_hex"),
        _bytes(corpus, "enrollment_response_ciphertext_hex"),
        _bytes(corpus, "enrollment_response_aad_hex"),
    ) == _bytes(corpus, "enrollment_response_plaintext_cbor_hex")

    envelope = EncryptedEnrollment.from_cbor(
        _bytes(corpus, "enrollment_request_envelope_cbor_hex")
    )
    assert envelope.handle == payload.handle
    assert envelope.nonce == _bytes(corpus, "enrollment_request_nonce_hex")
    assert envelope.ciphertext == _bytes(
        corpus,
        "enrollment_request_ciphertext_hex",
    )
