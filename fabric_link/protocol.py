"""Strict Fabric Link v3 wire records.

All security-sensitive records use deterministic CBOR. Decoders compare the
input against a canonical re-encoding, which rejects duplicate map keys,
indefinite-length values, non-minimal integers, trailing data, and alternate
encodings before any value is trusted.
"""

from __future__ import annotations

import base64
import ipaddress
import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

import cbor2

FABRIC_LINK_PROTOCOL_VERSION = 3
PAIRING_TTL_SECONDS = 300
REQUEST_TTL_SECONDS = 300
MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_APPLICATION_CIPHERTEXT_BYTES = MAX_RESPONSE_BYTES + 64 * 1024
MAX_APPLICATION_ENVELOPE_BYTES = MAX_APPLICATION_CIPHERTEXT_BYTES + 1024
MAX_PARAMS_BYTES = 240 * 1024
MAX_METHOD_BYTES = 96
REQUEST_ID_BYTES = 16
IDEMPOTENCY_KEY_BYTES = 16
PAIRING_FIELD_BYTES = 32

_PAIRING_KEYS = frozenset(
    {"v", "relay", "route", "handle", "secret", "machine_key", "expires_at"}
)
_REQUEST_KEYS = frozenset(
    {
        "v",
        "request_id",
        "idempotency_key",
        "issued_at",
        "expires_at",
        "method",
        "params",
    }
)
_RESPONSE_KEYS = frozenset(
    {
        "v",
        "request_id",
        "completed_at",
        "ok",
        "result",
        "error_code",
    }
)
_APPLICATION_ENVELOPE_KEYS = frozenset(
    {"v", "route", "credential_serial", "ciphertext"}
)
_METHOD_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class LinkProtocolError(ValueError):
    """A non-sensitive protocol rejection with a stable machine-readable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_dumps(value: Any) -> bytes:
    """Encode one supported protocol value using deterministic CBOR."""
    _validate_cbor_tree(value)
    try:
        return cbor2.dumps(value, canonical=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise LinkProtocolError("invalid_cbor_value") from exc


def canonical_loads(
    encoded: bytes,
    *,
    maximum: int,
    expected_type: type | tuple[type, ...] | None = None,
) -> Any:
    """Decode one exact canonical CBOR value within ``maximum`` bytes."""
    if not isinstance(encoded, bytes) or not encoded or len(encoded) > maximum:
        raise LinkProtocolError("invalid_cbor_size")
    try:
        value = cbor2.loads(encoded)
        canonical = cbor2.dumps(value, canonical=True)
    except (cbor2.CBORDecodeError, TypeError, ValueError, OverflowError) as exc:
        raise LinkProtocolError("invalid_cbor") from exc
    if canonical != encoded:
        raise LinkProtocolError("non_canonical_cbor")
    _validate_cbor_tree(value)
    if expected_type is not None and not isinstance(value, expected_type):
        raise LinkProtocolError("invalid_cbor_type")
    return value


def _validate_cbor_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 24:
        raise LinkProtocolError("cbor_too_deep")
    if value is None or isinstance(value, (bytes, str, bool)):
        return
    if isinstance(value, int):
        if isinstance(value, bool) or not (-(2**63) <= value < 2**64):
            raise LinkProtocolError("invalid_cbor_integer")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LinkProtocolError("invalid_cbor_float")
        return
    if isinstance(value, list):
        for item in value:
            _validate_cbor_tree(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise LinkProtocolError("invalid_cbor_map_key")
            _validate_cbor_tree(item, depth=depth + 1)
        return
    raise LinkProtocolError("unsupported_cbor_type")


def _require_exact_keys(value: Mapping[str, Any], keys: frozenset[str]) -> None:
    if frozenset(value) != keys:
        raise LinkProtocolError("invalid_record_keys")


def _require_int(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LinkProtocolError(code)
    return value


def _require_bytes(value: Any, length: int, code: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != length:
        raise LinkProtocolError(code)
    return value


def strict_base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def strict_base64url_decode(value: str, *, maximum: int) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or "=" in value
        or not _BASE64URL_RE.fullmatch(value)
    ):
        raise LinkProtocolError("invalid_base64url")
    try:
        decoded = base64.b64decode(
            value + ("=" * (-len(value) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, UnicodeEncodeError) as exc:
        raise LinkProtocolError("invalid_base64url") from exc
    if len(decoded) > maximum or strict_base64url_encode(decoded) != value:
        raise LinkProtocolError("invalid_base64url")
    return decoded


def normalize_relay_origin(value: str, *, allow_loopback_http: bool = False) -> str:
    """Validate and return one relay HTTPS origin without path/query/userinfo."""
    if (
        not isinstance(value, str)
        or not value
        or any(ch.isspace() for ch in value)
        or "?" in value
        or "#" in value
    ):
        raise LinkProtocolError("invalid_relay_origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise LinkProtocolError("invalid_relay_origin") from exc
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not parsed.hostname
    ):
        raise LinkProtocolError("invalid_relay_origin")
    hostname = parsed.hostname.lower()
    try:
        is_loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = hostname == "localhost"
    if parsed.scheme != "https" and not (
        allow_loopback_http and parsed.scheme == "http" and is_loopback
    ):
        raise LinkProtocolError("invalid_relay_origin")
    default_port = 443 if parsed.scheme == "https" else 80
    host = f"[{hostname}]" if ":" in hostname else hostname
    authority = host if port in {None, default_port} else f"{host}:{port}"
    return f"{parsed.scheme}://{authority}"


@dataclass(frozen=True)
class PairingPayload:
    relay: str
    route: bytes
    handle: bytes
    secret: bytes = field(repr=False)
    machine_key: bytes
    expires_at: int
    version: int = FABRIC_LINK_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        relay = normalize_relay_origin(self.relay, allow_loopback_http=True)
        if relay != self.relay:
            raise LinkProtocolError("non_canonical_relay_origin")
        _require_bytes(self.route, PAIRING_FIELD_BYTES, "invalid_pairing_route")
        _require_bytes(self.handle, PAIRING_FIELD_BYTES, "invalid_pairing_handle")
        _require_bytes(self.secret, PAIRING_FIELD_BYTES, "invalid_pairing_secret")
        _require_bytes(
            self.machine_key,
            PAIRING_FIELD_BYTES,
            "invalid_pairing_machine_key",
        )
        _require_int(self.expires_at, "invalid_pairing_expiry")
        if self.version != FABRIC_LINK_PROTOCOL_VERSION:
            raise LinkProtocolError("unsupported_pairing_version")

    def to_cbor(self) -> bytes:
        return canonical_dumps(
            {
                "v": self.version,
                "relay": self.relay,
                "route": self.route,
                "handle": self.handle,
                "secret": self.secret,
                "machine_key": self.machine_key,
                "expires_at": self.expires_at,
            }
        )

    def public_transcript_cbor(self) -> bytes:
        """Return the QR transcript with the one-time secret represented by a hash.

        Enrollment signatures bind the full QR separately. This helper is for
        diagnostic fingerprints that must never retain the raw secret.
        """
        import hashlib

        return canonical_dumps(
            {
                "v": self.version,
                "relay": self.relay,
                "route": self.route,
                "handle": self.handle,
                "secret_hash": hashlib.sha256(self.secret).digest(),
                "machine_key": self.machine_key,
                "expires_at": self.expires_at,
            }
        )

    def to_url(self) -> str:
        payload = strict_base64url_encode(self.to_cbor())
        return f"{self.relay}/link/pair#pair={payload}"

    @classmethod
    def from_cbor(
        cls,
        encoded: bytes,
        *,
        now: int,
        allow_loopback_http: bool = False,
    ) -> "PairingPayload":
        value = canonical_loads(encoded, maximum=4096, expected_type=dict)
        _require_exact_keys(value, _PAIRING_KEYS)
        version = _require_int(value["v"], "invalid_pairing_version")
        if version != FABRIC_LINK_PROTOCOL_VERSION:
            raise LinkProtocolError("unsupported_pairing_version")
        relay = normalize_relay_origin(
            value["relay"], allow_loopback_http=allow_loopback_http
        )
        if relay != value["relay"]:
            raise LinkProtocolError("non_canonical_relay_origin")
        expires_at = _require_int(value["expires_at"], "invalid_pairing_expiry")
        if expires_at <= now or expires_at > now + PAIRING_TTL_SECONDS:
            raise LinkProtocolError("invalid_pairing_expiry")
        return cls(
            relay=relay,
            route=_require_bytes(
                value["route"], PAIRING_FIELD_BYTES, "invalid_pairing_route"
            ),
            handle=_require_bytes(
                value["handle"], PAIRING_FIELD_BYTES, "invalid_pairing_handle"
            ),
            secret=_require_bytes(
                value["secret"], PAIRING_FIELD_BYTES, "invalid_pairing_secret"
            ),
            machine_key=_require_bytes(
                value["machine_key"],
                PAIRING_FIELD_BYTES,
                "invalid_pairing_machine_key",
            ),
            expires_at=expires_at,
            version=version,
        )

    @classmethod
    def from_url(
        cls,
        value: str,
        *,
        now: int,
        allow_loopback_http: bool = False,
    ) -> "PairingPayload":
        if not isinstance(value, str) or any(ch.isspace() for ch in value):
            raise LinkProtocolError("invalid_pairing_url")
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise LinkProtocolError("invalid_pairing_url") from exc
        if parsed.path != "/link/pair" or parsed.query or not parsed.fragment.startswith(
            "pair="
        ):
            raise LinkProtocolError("invalid_pairing_url")
        if parsed.fragment.count("=") != 1 or "&" in parsed.fragment or "%" in parsed.fragment:
            raise LinkProtocolError("invalid_pairing_url")
        encoded = strict_base64url_decode(
            parsed.fragment.removeprefix("pair="), maximum=4096
        )
        payload = cls.from_cbor(
            encoded,
            now=now,
            allow_loopback_http=allow_loopback_http,
        )
        outer_origin = normalize_relay_origin(
            f"{parsed.scheme}://{parsed.netloc}",
            allow_loopback_http=allow_loopback_http,
        )
        if outer_origin != payload.relay:
            raise LinkProtocolError("pairing_relay_mismatch")
        return payload


@dataclass(frozen=True)
class LinkRequest:
    request_id: bytes
    idempotency_key: bytes
    issued_at: int
    expires_at: int
    method: str
    params_cbor: bytes = field(repr=False)
    version: int = FABRIC_LINK_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_bytes(self.request_id, REQUEST_ID_BYTES, "invalid_request_id")
        _require_bytes(
            self.idempotency_key,
            IDEMPOTENCY_KEY_BYTES,
            "invalid_idempotency_key",
        )
        if self.version != FABRIC_LINK_PROTOCOL_VERSION:
            raise LinkProtocolError("unsupported_request_version")
        if not isinstance(self.method, str) or not _METHOD_RE.fullmatch(self.method):
            raise LinkProtocolError("invalid_method")
        issued_at = _require_int(self.issued_at, "invalid_request_time")
        expires_at = _require_int(self.expires_at, "invalid_request_time")
        if expires_at <= issued_at or expires_at - issued_at > REQUEST_TTL_SECONDS:
            raise LinkProtocolError("invalid_request_lifetime")
        params = canonical_loads(
            self.params_cbor,
            maximum=MAX_PARAMS_BYTES,
            expected_type=dict,
        )
        if not all(isinstance(key, str) for key in params):
            raise LinkProtocolError("invalid_params")

    def to_cbor(self) -> bytes:
        encoded = canonical_dumps(
            {
                "v": self.version,
                "request_id": self.request_id,
                "idempotency_key": self.idempotency_key,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "method": self.method,
                "params": self.params_cbor,
            }
        )
        if len(encoded) > MAX_REQUEST_BYTES:
            raise LinkProtocolError("request_too_large")
        return encoded

    @classmethod
    def from_cbor(cls, encoded: bytes) -> "LinkRequest":
        value = canonical_loads(
            encoded,
            maximum=MAX_REQUEST_BYTES,
            expected_type=dict,
        )
        _require_exact_keys(value, _REQUEST_KEYS)
        return cls(
            version=_require_int(value["v"], "invalid_request_version"),
            request_id=_require_bytes(
                value["request_id"], REQUEST_ID_BYTES, "invalid_request_id"
            ),
            idempotency_key=_require_bytes(
                value["idempotency_key"],
                IDEMPOTENCY_KEY_BYTES,
                "invalid_idempotency_key",
            ),
            issued_at=_require_int(value["issued_at"], "invalid_request_time"),
            expires_at=_require_int(value["expires_at"], "invalid_request_time"),
            method=value["method"],
            params_cbor=value["params"],
        )


@dataclass(frozen=True)
class LinkResponse:
    request_id: bytes
    completed_at: int
    ok: bool
    result_cbor: bytes | None = field(repr=False)
    error_code: str | None
    version: int = FABRIC_LINK_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_bytes(self.request_id, REQUEST_ID_BYTES, "invalid_request_id")
        _require_int(self.completed_at, "invalid_response_time")
        if self.version != FABRIC_LINK_PROTOCOL_VERSION:
            raise LinkProtocolError("unsupported_response_version")
        if not isinstance(self.ok, bool) or self.ok == (self.error_code is not None):
            raise LinkProtocolError("invalid_response_outcome")
        if self.ok:
            if self.result_cbor is None:
                raise LinkProtocolError("invalid_response_result")
            canonical_loads(self.result_cbor, maximum=MAX_RESPONSE_BYTES)
        elif self.result_cbor is not None:
            raise LinkProtocolError("invalid_response_result")
        if self.error_code is not None and (
            not isinstance(self.error_code, str)
            or not _METHOD_RE.fullmatch(self.error_code)
        ):
            raise LinkProtocolError("invalid_response_error")

    def to_cbor(self) -> bytes:
        encoded = canonical_dumps(
            {
                "v": self.version,
                "request_id": self.request_id,
                "completed_at": self.completed_at,
                "ok": self.ok,
                "result": self.result_cbor,
                "error_code": self.error_code,
            }
        )
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise LinkProtocolError("response_too_large")
        return encoded

    @classmethod
    def from_cbor(cls, encoded: bytes) -> "LinkResponse":
        value = canonical_loads(
            encoded,
            maximum=MAX_RESPONSE_BYTES,
            expected_type=dict,
        )
        _require_exact_keys(value, _RESPONSE_KEYS)
        return cls(
            version=_require_int(value["v"], "invalid_response_version"),
            request_id=_require_bytes(
                value["request_id"], REQUEST_ID_BYTES, "invalid_request_id"
            ),
            completed_at=_require_int(
                value["completed_at"], "invalid_response_time"
            ),
            ok=value["ok"],
            result_cbor=value["result"],
            error_code=value["error_code"],
        )


@dataclass(frozen=True)
class LinkApplicationEnvelope:
    """Opaque delivery metadata and one MLS application ciphertext.

    The route and signed admission serial let a blind relay deliver a record
    and let a host select the correct MLS group. Authorization remains inside
    the encrypted request and is evaluated only after MLS authentication.
    """

    route_id: bytes
    credential_serial: bytes
    ciphertext: bytes = field(repr=False)
    version: int = FABRIC_LINK_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_bytes(self.route_id, PAIRING_FIELD_BYTES, "invalid_application_route")
        _require_bytes(
            self.credential_serial,
            16,
            "invalid_application_credential_serial",
        )
        if self.version != FABRIC_LINK_PROTOCOL_VERSION:
            raise LinkProtocolError("unsupported_application_version")
        if (
            not isinstance(self.ciphertext, bytes)
            or not self.ciphertext
            or len(self.ciphertext) > MAX_APPLICATION_CIPHERTEXT_BYTES
        ):
            raise LinkProtocolError("invalid_application_ciphertext")

    def to_cbor(self) -> bytes:
        encoded = canonical_dumps(
            {
                "v": self.version,
                "route": self.route_id,
                "credential_serial": self.credential_serial,
                "ciphertext": self.ciphertext,
            }
        )
        if len(encoded) > MAX_APPLICATION_ENVELOPE_BYTES:
            raise LinkProtocolError("application_envelope_too_large")
        return encoded

    @classmethod
    def from_cbor(cls, encoded: bytes) -> "LinkApplicationEnvelope":
        value = canonical_loads(
            encoded,
            maximum=MAX_APPLICATION_ENVELOPE_BYTES,
            expected_type=dict,
        )
        _require_exact_keys(value, _APPLICATION_ENVELOPE_KEYS)
        return cls(
            version=_require_int(value["v"], "invalid_application_version"),
            route_id=_require_bytes(
                value["route"],
                PAIRING_FIELD_BYTES,
                "invalid_application_route",
            ),
            credential_serial=_require_bytes(
                value["credential_serial"],
                16,
                "invalid_application_credential_serial",
            ),
            ciphertext=value["ciphertext"],
        )
