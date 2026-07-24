from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import cbor2
import pytest

from fabric_link.protocol import (
    MAX_APPLICATION_CIPHERTEXT_BYTES,
    MAX_PARAMS_BYTES,
    LinkApplicationEnvelope,
    LinkProtocolError,
    LinkRequest,
    LinkResponse,
    PairingPayload,
    canonical_dumps,
    canonical_loads,
    normalize_relay_origin,
)

NOW = 1_784_840_000


def pairing_payload(**overrides) -> PairingPayload:
    values = {
        "relay": "https://relay.example",
        "route": b"r" * 32,
        "handle": b"h" * 32,
        "secret": b"s" * 32,
        "machine_key": b"m" * 32,
        "expires_at": NOW + 300,
    }
    values.update(overrides)
    return PairingPayload(**values)


def test_pairing_url_round_trip_keeps_credentials_out_of_http_request():
    payload = pairing_payload()
    pairing_url = payload.to_url()
    parsed = urlsplit(pairing_url)

    assert urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")) == (
        "https://relay.example/link/pair"
    )
    assert parsed.query == ""
    assert parsed.fragment.startswith("pair=")
    assert PairingPayload.from_url(pairing_url, now=NOW) == payload
    assert repr(payload).find(repr(payload.secret)) == -1


@pytest.mark.parametrize(
    ("value", "allow_loopback", "expected"),
    [
        ("https://relay.example/", False, "https://relay.example"),
        ("https://relay.example:443", False, "https://relay.example"),
        ("https://relay.example:9443", False, "https://relay.example:9443"),
        ("http://127.0.0.2:9000", True, "http://127.0.0.2:9000"),
        ("http://[::1]:9000", True, "http://[::1]:9000"),
    ],
)
def test_relay_origin_normalization(value, allow_loopback, expected):
    assert (
        normalize_relay_origin(value, allow_loopback_http=allow_loopback)
        == expected
    )


@pytest.mark.parametrize(
    "value",
    [
        "http://relay.example",
        "https://user:secret@relay.example",
        "https://relay.example/link",
        "https://relay.example?",
        "https://relay.example#",
        "https://relay.example?token=x",
        "https://relay.example/#pair=x",
        "https://relay.example\n.evil",
    ],
)
def test_relay_origin_rejects_unsafe_or_non_origin_values(value):
    with pytest.raises(LinkProtocolError):
        normalize_relay_origin(value)


def test_pairing_parser_rejects_unknown_duplicate_and_noncanonical_maps():
    raw = pairing_payload().to_cbor()
    decoded = cbor2.loads(raw)
    decoded["future"] = True
    with pytest.raises(LinkProtocolError, match="invalid_record_keys"):
        PairingPayload.from_cbor(canonical_dumps(decoded), now=NOW)

    assert raw[0] == 0xA7
    duplicate = bytes([0xA8]) + raw[1:] + canonical_dumps("v") + canonical_dumps(3)
    with pytest.raises(LinkProtocolError, match="non_canonical_cbor"):
        PairingPayload.from_cbor(duplicate, now=NOW)

    indefinite = b"\xbf" + raw[1:] + b"\xff"
    with pytest.raises(LinkProtocolError, match="non_canonical_cbor"):
        PairingPayload.from_cbor(indefinite, now=NOW)


def test_pairing_parser_rejects_expired_far_future_and_outer_relay_mismatch():
    with pytest.raises(LinkProtocolError, match="invalid_pairing_expiry"):
        PairingPayload.from_cbor(
            pairing_payload(expires_at=NOW).to_cbor(),
            now=NOW,
        )
    with pytest.raises(LinkProtocolError, match="invalid_pairing_expiry"):
        PairingPayload.from_cbor(
            pairing_payload(expires_at=NOW + 301).to_cbor(),
            now=NOW,
        )
    url = pairing_payload().to_url().replace(
        "https://relay.example/",
        "https://other.example/",
        1,
    )
    with pytest.raises(LinkProtocolError, match="pairing_relay_mismatch"):
        PairingPayload.from_url(url, now=NOW)


def test_link_request_round_trip_preserves_canonical_nested_params():
    request = LinkRequest(
        request_id=b"r" * 16,
        idempotency_key=b"i" * 16,
        issued_at=NOW,
        expires_at=NOW + 120,
        method="job.create",
        params_cbor=canonical_dumps({"prompt": "ship it", "priority": 2}),
    )

    decoded = LinkRequest.from_cbor(request.to_cbor())
    assert decoded == request
    assert canonical_loads(decoded.params_cbor, maximum=MAX_PARAMS_BYTES) == {
        "priority": 2,
        "prompt": "ship it",
    }
    assert repr(request).find("ship it") == -1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"method": "UPPER"},
        {"method": "x" * 97},
        {"expires_at": NOW + 301},
        {"params_cbor": b"\xbf\xff"},
        {"params_cbor": canonical_dumps(["not", "a", "map"])},
    ],
)
def test_link_request_rejects_invalid_envelopes(kwargs):
    values = {
        "request_id": b"r" * 16,
        "idempotency_key": b"i" * 16,
        "issued_at": NOW,
        "expires_at": NOW + 120,
        "method": "prompt.submit",
        "params_cbor": canonical_dumps({}),
    }
    values.update(kwargs)
    with pytest.raises(LinkProtocolError):
        LinkRequest(**values)


def test_link_response_requires_one_unambiguous_outcome():
    success = LinkResponse(
        request_id=b"r" * 16,
        completed_at=NOW,
        ok=True,
        result_cbor=canonical_dumps({"job_id": "job_1"}),
        error_code=None,
    )
    assert LinkResponse.from_cbor(success.to_cbor()) == success

    failure = LinkResponse(
        request_id=b"r" * 16,
        completed_at=NOW,
        ok=False,
        result_cbor=None,
        error_code="method_not_granted",
    )
    assert LinkResponse.from_cbor(failure.to_cbor()) == failure

    with pytest.raises(LinkProtocolError, match="invalid_response_outcome"):
        LinkResponse(
            request_id=b"r" * 16,
            completed_at=NOW,
            ok=True,
            result_cbor=canonical_dumps({}),
            error_code="unexpected",
        )


def test_application_envelope_keeps_request_data_opaque_and_canonical():
    envelope = LinkApplicationEnvelope(
        route_id=b"r" * 32,
        credential_serial=b"s" * 16,
        ciphertext=b"encrypted-mls-record",
    )

    encoded = envelope.to_cbor()
    assert LinkApplicationEnvelope.from_cbor(encoded) == envelope
    assert b"job.create" not in encoded
    assert repr(envelope).find("encrypted-mls-record") == -1

    with pytest.raises(LinkProtocolError, match="invalid_application_ciphertext"):
        LinkApplicationEnvelope(
            route_id=b"r" * 32,
            credential_serial=b"s" * 16,
            ciphertext=b"x" * (MAX_APPLICATION_CIPHERTEXT_BYTES + 1),
        )
