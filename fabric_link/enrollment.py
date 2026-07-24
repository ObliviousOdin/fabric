"""One-time, locally approved Fabric Link enrollment.

Possession of a QR secret permits sending an encrypted request, but it does not
authenticate the machine. The controller accepts a response only after an
Ed25519 signature verifies under the machine key pinned in that QR.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from .capabilities import normalize_grants
from .core import LinkCryptoCore
from .protocol import (
    FABRIC_LINK_PROTOCOL_VERSION,
    PAIRING_FIELD_BYTES,
    PAIRING_TTL_SECONDS,
    LinkProtocolError,
    PairingPayload,
    canonical_dumps,
    canonical_loads,
    normalize_relay_origin,
)
from .store import (
    LinkDevice,
    LinkDeviceStore,
    LinkStorageError,
    credential_fingerprint,
)

MAX_ENROLLMENT_RECORD_BYTES = 256 * 1024
MAX_KEY_PACKAGE_BYTES = 128 * 1024
ENROLLMENT_NONCE_BYTES = 12
CONTROLLER_NONCE_BYTES = 32
CONTROLLER_RELAY_KEY_BYTES = 32
CREDENTIAL_HASH_BYTES = 32
GROUP_ID_BYTES = 32
CREDENTIAL_SERIAL_BYTES = 16
ADMISSION_VALIDITY_SECONDS = 365 * 24 * 60 * 60

_REQUEST_KEYS = frozenset(
    {
        "v",
        "handle",
        "controller_nonce",
        "controller_name",
        "platform",
        "requested_grants",
        "relay_public_key",
        "key_package",
        "credential_hash",
        "issued_at",
        "expires_at",
    }
)
_ENVELOPE_KEYS = frozenset({"v", "handle", "nonce", "ciphertext"})
_CERTIFICATE_KEYS = frozenset(
    {
        "v",
        "route_id",
        "relay_public_key",
        "credential_serial",
        "not_before",
        "not_after",
    }
)
_SIGNED_CERTIFICATE_KEYS = frozenset({"certificate", "signature"})
_RESPONSE_CORE_KEYS = frozenset(
    {
        "v",
        "handle",
        "group_id",
        "welcome",
        "admission_certificate",
        "approved_grants",
        "request_hash",
        "issued_at",
        "expires_at",
    }
)
_RESPONSE_KEYS = _RESPONSE_CORE_KEYS | {"machine_signature"}
_PLATFORMS = frozenset({"ios", "android", "web", "desktop", "cli"})

_REQUEST_KEY_INFO = b"fabric-link-enrollment-request-key-v3"
_RESPONSE_KEY_INFO = b"fabric-link-enrollment-response-key-v3"
_REQUEST_AAD_DOMAIN = b"fabric-link-enrollment-request-aad-v3\x00"
_RESPONSE_AAD_DOMAIN = b"fabric-link-enrollment-response-aad-v3\x00"
_RESPONSE_SIGNATURE_DOMAIN = b"fabric-link-enrollment-response-signature-v3\x00"
_CERTIFICATE_SIGNATURE_DOMAIN = b"fabric-link-relay-admission-certificate-v1\x00"
_PENDING_MARKER_DOMAIN = b"fabric-link-pending-enrollment-v3\x00"


class LinkEnrollmentError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LinkRevocationIncomplete(RuntimeError):
    """Local access is denied, but MLS cleanup still needs reconciliation."""


def _exact_keys(value: dict[str, Any], keys: frozenset[str]) -> None:
    if frozenset(value) != keys:
        raise LinkEnrollmentError("invalid_enrollment_record")


def _require_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LinkEnrollmentError("invalid_enrollment_record")
    return value


def _require_bytes(value: Any, length: int | None = None) -> bytes:
    if not isinstance(value, bytes) or (length is not None and len(value) != length):
        raise LinkEnrollmentError("invalid_enrollment_record")
    return value


def _require_name(value: Any) -> str:
    if not isinstance(value, str):
        raise LinkEnrollmentError("invalid_controller_name")
    normalized = " ".join(value.split())
    if (
        not normalized
        or len(normalized.encode("utf-8")) > 96
        or any(ord(character) < 32 for character in normalized)
    ):
        raise LinkEnrollmentError("invalid_controller_name")
    return normalized


def _derive_key(payload: PairingPayload, *, response: bool) -> bytes:
    salt = hashlib.sha256(payload.route + payload.handle).digest()
    info = _RESPONSE_KEY_INFO if response else _REQUEST_KEY_INFO
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=info,
    ).derive(payload.secret)


def _aad(payload: PairingPayload, *, response: bool) -> bytes:
    domain = _RESPONSE_AAD_DOMAIN if response else _REQUEST_AAD_DOMAIN
    return domain + hashlib.sha256(payload.to_cbor()).digest()


def _pending_marker(payload: PairingPayload) -> bytes:
    return hmac.new(
        payload.secret,
        _PENDING_MARKER_DOMAIN + payload.handle,
        hashlib.sha256,
    ).digest()


@dataclass(frozen=True)
class EnrollmentRequest:
    handle: bytes
    controller_nonce: bytes
    controller_name: str
    platform: str
    requested_grants: tuple[str, ...]
    relay_public_key: bytes
    key_package: bytes = field(repr=False)
    credential_hash: bytes
    issued_at: int
    expires_at: int
    version: int = FABRIC_LINK_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_bytes(self.handle, PAIRING_FIELD_BYTES)
        _require_bytes(self.controller_nonce, CONTROLLER_NONCE_BYTES)
        if _require_name(self.controller_name) != self.controller_name:
            raise LinkEnrollmentError("invalid_controller_name")
        if not isinstance(self.platform, str) or self.platform not in _PLATFORMS:
            raise LinkEnrollmentError("invalid_controller_platform")
        if normalize_grants(self.requested_grants) != self.requested_grants:
            raise LinkEnrollmentError("non_canonical_grants")
        _require_bytes(self.relay_public_key, CONTROLLER_RELAY_KEY_BYTES)
        if not self.key_package or len(self.key_package) > MAX_KEY_PACKAGE_BYTES:
            raise LinkEnrollmentError("invalid_key_package")
        _require_bytes(self.credential_hash, CREDENTIAL_HASH_BYTES)
        if not hmac.compare_digest(
            self.credential_hash,
            hashlib.sha256(self.key_package).digest(),
        ):
            raise LinkEnrollmentError("credential_hash_mismatch")
        issued_at = _require_int(self.issued_at)
        expires_at = _require_int(self.expires_at)
        if expires_at <= issued_at or expires_at - issued_at > PAIRING_TTL_SECONDS:
            raise LinkEnrollmentError("invalid_enrollment_lifetime")
        if self.version != FABRIC_LINK_PROTOCOL_VERSION:
            raise LinkEnrollmentError("unsupported_enrollment_version")

    def to_cbor(self) -> bytes:
        return canonical_dumps(
            {
                "v": self.version,
                "handle": self.handle,
                "controller_nonce": self.controller_nonce,
                "controller_name": self.controller_name,
                "platform": self.platform,
                "requested_grants": list(self.requested_grants),
                "relay_public_key": self.relay_public_key,
                "key_package": self.key_package,
                "credential_hash": self.credential_hash,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
            }
        )

    @classmethod
    def from_cbor(cls, encoded: bytes) -> "EnrollmentRequest":
        try:
            value = canonical_loads(
                encoded,
                maximum=MAX_ENROLLMENT_RECORD_BYTES,
                expected_type=dict,
            )
            _exact_keys(value, _REQUEST_KEYS)
            grants = value["requested_grants"]
            if not isinstance(grants, list):
                raise LinkEnrollmentError("invalid_enrollment_record")
            return cls(
                version=_require_int(value["v"]),
                handle=_require_bytes(value["handle"], PAIRING_FIELD_BYTES),
                controller_nonce=_require_bytes(
                    value["controller_nonce"], CONTROLLER_NONCE_BYTES
                ),
                controller_name=_require_name(value["controller_name"]),
                platform=value["platform"],
                requested_grants=normalize_grants(grants),
                relay_public_key=_require_bytes(
                    value["relay_public_key"], CONTROLLER_RELAY_KEY_BYTES
                ),
                key_package=_require_bytes(value["key_package"]),
                credential_hash=_require_bytes(
                    value["credential_hash"], CREDENTIAL_HASH_BYTES
                ),
                issued_at=_require_int(value["issued_at"]),
                expires_at=_require_int(value["expires_at"]),
            )
        except LinkProtocolError as exc:
            raise LinkEnrollmentError("invalid_enrollment_record") from exc


@dataclass(frozen=True)
class EncryptedEnrollment:
    handle: bytes
    nonce: bytes
    ciphertext: bytes = field(repr=False)
    version: int = FABRIC_LINK_PROTOCOL_VERSION

    def to_cbor(self) -> bytes:
        encoded = canonical_dumps(
            {
                "v": self.version,
                "handle": self.handle,
                "nonce": self.nonce,
                "ciphertext": self.ciphertext,
            }
        )
        if len(encoded) > MAX_ENROLLMENT_RECORD_BYTES:
            raise LinkEnrollmentError("enrollment_record_too_large")
        return encoded

    @classmethod
    def from_cbor(cls, encoded: bytes) -> "EncryptedEnrollment":
        try:
            value = canonical_loads(
                encoded,
                maximum=MAX_ENROLLMENT_RECORD_BYTES,
                expected_type=dict,
            )
            _exact_keys(value, _ENVELOPE_KEYS)
            version = _require_int(value["v"])
            if version != FABRIC_LINK_PROTOCOL_VERSION:
                raise LinkEnrollmentError("unsupported_enrollment_version")
            ciphertext = _require_bytes(value["ciphertext"])
            if not ciphertext:
                raise LinkEnrollmentError("invalid_enrollment_record")
            return cls(
                version=version,
                handle=_require_bytes(value["handle"], PAIRING_FIELD_BYTES),
                nonce=_require_bytes(value["nonce"], ENROLLMENT_NONCE_BYTES),
                ciphertext=ciphertext,
            )
        except LinkProtocolError as exc:
            raise LinkEnrollmentError("invalid_enrollment_record") from exc


def build_enrollment_request(
    *,
    payload: PairingPayload,
    controller_name: str,
    platform: str,
    requested_grants: tuple[str, ...],
    relay_public_key: bytes,
    key_package: bytes,
    now: int,
) -> tuple[EnrollmentRequest, bytes]:
    """Create a controller request and its opaque relay envelope."""
    expires_at = min(payload.expires_at, now + PAIRING_TTL_SECONDS)
    request = EnrollmentRequest(
        handle=payload.handle,
        controller_nonce=secrets.token_bytes(CONTROLLER_NONCE_BYTES),
        controller_name=_require_name(controller_name),
        platform=platform,
        requested_grants=normalize_grants(requested_grants),
        relay_public_key=relay_public_key,
        key_package=key_package,
        credential_hash=hashlib.sha256(key_package).digest(),
        issued_at=now,
        expires_at=expires_at,
    )
    nonce = secrets.token_bytes(ENROLLMENT_NONCE_BYTES)
    ciphertext = AESGCM(_derive_key(payload, response=False)).encrypt(
        nonce,
        request.to_cbor(),
        _aad(payload, response=False),
    )
    return request, EncryptedEnrollment(
        handle=payload.handle,
        nonce=nonce,
        ciphertext=ciphertext,
    ).to_cbor()


@dataclass(frozen=True)
class PendingApproval:
    handle: bytes
    controller_name: str
    platform: str
    requested_grants: tuple[str, ...]
    device_fingerprint: str
    short_auth_string: str


@dataclass
class _Pending:
    payload: PairingPayload = field(repr=False)
    secret_marker: bytes = field(repr=False)
    allowed_grants: tuple[str, ...]
    request: EnrollmentRequest | None = field(default=None, repr=False)
    request_cbor: bytes | None = field(default=None, repr=False)
    request_envelope_hash: bytes | None = field(default=None, repr=False)
    approving: bool = False


@dataclass(frozen=True)
class EnrollmentResult:
    group_id: bytes
    welcome: bytes = field(repr=False)
    admission_certificate: bytes = field(repr=False)
    credential_serial: bytes = field(repr=False)
    approved_grants: tuple[str, ...]
    machine_signature: bytes


def _short_auth_string(payload: PairingPayload, request_cbor: bytes) -> str:
    transcript = hashlib.sha256(payload.to_cbor() + request_cbor).digest()
    number = int.from_bytes(transcript[:4], "big") % 1_000_000
    return f"{number:06d}"


def _certificate(
    *,
    route_id: bytes,
    relay_public_key: bytes,
    credential_serial: bytes,
    not_before: int,
    not_after: int,
    sign: Any,
) -> bytes:
    certificate = canonical_dumps(
        {
            "v": 1,
            "route_id": route_id,
            "relay_public_key": relay_public_key,
            "credential_serial": credential_serial,
            "not_before": not_before,
            "not_after": not_after,
        }
    )
    signature = sign(_CERTIFICATE_SIGNATURE_DOMAIN + certificate)
    return canonical_dumps({"certificate": certificate, "signature": signature})


def verify_admission_certificate(
    signed_certificate: bytes,
    *,
    machine_key: bytes,
    route_id: bytes,
    relay_public_key: bytes,
    now: int,
) -> dict[str, Any]:
    try:
        signed = canonical_loads(
            signed_certificate,
            maximum=16 * 1024,
            expected_type=dict,
        )
        _exact_keys(signed, _SIGNED_CERTIFICATE_KEYS)
        certificate_cbor = _require_bytes(signed["certificate"])
        signature = _require_bytes(signed["signature"], 64)
        certificate = canonical_loads(
            certificate_cbor,
            maximum=4096,
            expected_type=dict,
        )
        _exact_keys(certificate, _CERTIFICATE_KEYS)
        Ed25519PublicKey.from_public_bytes(machine_key).verify(
            signature,
            _CERTIFICATE_SIGNATURE_DOMAIN + certificate_cbor,
        )
    except (InvalidSignature, ValueError, LinkProtocolError) as exc:
        raise LinkEnrollmentError("invalid_admission_certificate") from exc
    if (
        _require_int(certificate["v"]) != 1
        or not hmac.compare_digest(
            _require_bytes(certificate["route_id"], 32),
            route_id,
        )
        or not hmac.compare_digest(
            _require_bytes(certificate["relay_public_key"], 32),
            relay_public_key,
        )
        or len(_require_bytes(certificate["credential_serial"])) != 16
        or _require_int(certificate["not_before"]) > now
        or _require_int(certificate["not_after"]) <= now
    ):
        raise LinkEnrollmentError("invalid_admission_certificate")
    return certificate


class EnrollmentManager:
    """In-memory one-time secrets backed by crash-cleanup markers in SQLite."""

    def __init__(self, *, store: LinkDeviceStore, core: LinkCryptoCore) -> None:
        self._store = store
        self._core = core
        self._lock = threading.RLock()
        self._pending: dict[bytes, _Pending] = {}

    def open_pairing(
        self,
        *,
        relay: str,
        requested_grants: tuple[str, ...],
        now: int,
        ttl_seconds: int = PAIRING_TTL_SECONDS,
        allow_loopback_http: bool = False,
    ) -> PairingPayload:
        if ttl_seconds <= 0 or ttl_seconds > PAIRING_TTL_SECONDS:
            raise LinkEnrollmentError("invalid_enrollment_ttl")
        identity = self._store.machine_identity()
        payload = PairingPayload(
            relay=normalize_relay_origin(
                relay,
                allow_loopback_http=allow_loopback_http,
            ),
            route=identity.route_id,
            handle=secrets.token_bytes(PAIRING_FIELD_BYTES),
            secret=secrets.token_bytes(PAIRING_FIELD_BYTES),
            machine_key=identity.public_key,
            expires_at=now + ttl_seconds,
        )
        marker = _pending_marker(payload)
        grants = normalize_grants(requested_grants)
        self._store.register_pending(
            handle=payload.handle,
            secret_marker=marker,
            requested_grants=grants,
            created_at=now,
            expires_at=payload.expires_at,
        )
        with self._lock:
            self._pending[payload.handle] = _Pending(
                payload=payload,
                secret_marker=marker,
                allowed_grants=grants,
            )
        return payload

    def receive_request(self, envelope_cbor: bytes, *, now: int) -> PendingApproval:
        envelope = EncryptedEnrollment.from_cbor(envelope_cbor)
        envelope_hash = hashlib.sha256(envelope_cbor).digest()
        with self._lock:
            pending = self._pending.get(envelope.handle)
            if pending is None or pending.payload.expires_at <= now:
                self._expire_locked(envelope.handle)
                raise LinkEnrollmentError("enrollment_expired")
            if pending.request is not None:
                if hmac.compare_digest(
                    pending.request_envelope_hash or b"",
                    envelope_hash,
                ):
                    return self._approval(pending)
                raise LinkEnrollmentError("enrollment_already_used")
            try:
                plaintext = AESGCM(
                    _derive_key(pending.payload, response=False)
                ).decrypt(
                    envelope.nonce,
                    envelope.ciphertext,
                    _aad(pending.payload, response=False),
                )
                request = EnrollmentRequest.from_cbor(plaintext)
            except Exception as exc:
                raise LinkEnrollmentError("invalid_enrollment_request") from exc
            if (
                not hmac.compare_digest(request.handle, envelope.handle)
                or request.expires_at > pending.payload.expires_at
                or request.expires_at <= now
                or request.issued_at > now + 30
                or request.issued_at < now - PAIRING_TTL_SECONDS
                or not set(request.requested_grants) <= set(pending.allowed_grants)
            ):
                raise LinkEnrollmentError("invalid_enrollment_request")
            pending.request = request
            pending.request_cbor = plaintext
            pending.request_envelope_hash = envelope_hash
            return self._approval(pending)

    def _approval(self, pending: _Pending) -> PendingApproval:
        if pending.request is None or pending.request_cbor is None:
            raise LinkEnrollmentError("enrollment_not_ready")
        return PendingApproval(
            handle=pending.payload.handle,
            controller_name=pending.request.controller_name,
            platform=pending.request.platform,
            requested_grants=pending.request.requested_grants,
            device_fingerprint=credential_fingerprint(
                pending.request.credential_hash
            ),
            short_auth_string=_short_auth_string(
                pending.payload,
                pending.request_cbor,
            ),
        )

    def approve(
        self,
        *,
        handle: bytes,
        approved_grants: tuple[str, ...],
        now: int,
    ) -> bytes:
        grants = normalize_grants(approved_grants)
        with self._lock:
            pending = self._pending.get(handle)
            if (
                pending is None
                or pending.request is None
                or pending.request_cbor is None
                or pending.payload.expires_at <= now
            ):
                self._expire_locked(handle)
                raise LinkEnrollmentError("enrollment_expired")
            if pending.approving:
                raise LinkEnrollmentError("enrollment_in_progress")
            if not set(grants) <= set(pending.request.requested_grants):
                raise LinkEnrollmentError("grant_not_requested")
            pending.approving = True
            try:
                return self._approve_locked(pending=pending, grants=grants, now=now)
            except Exception:
                pending.approving = False
                raise

    def _approve_locked(
        self,
        *,
        pending: _Pending,
        grants: tuple[str, ...],
        now: int,
    ) -> bytes:
        request = pending.request
        request_cbor = pending.request_cbor
        if request is None or request_cbor is None:
            raise LinkEnrollmentError("enrollment_not_ready")
        identity = self._store.machine_identity()
        if (
            not hmac.compare_digest(identity.route_id, pending.payload.route)
            or not hmac.compare_digest(identity.public_key, pending.payload.machine_key)
        ):
            raise LinkEnrollmentError("machine_identity_changed")
        group_id = secrets.token_bytes(GROUP_ID_BYTES)
        pair = self._core.create_pair(
            host_identity=b"fabric-machine:" + identity.public_key,
            group_id=group_id,
            controller_key_package=request.key_package,
        )
        credential_serial = secrets.token_bytes(CREDENTIAL_SERIAL_BYTES)
        signed_certificate = _certificate(
            route_id=identity.route_id,
            relay_public_key=request.relay_public_key,
            credential_serial=credential_serial,
            not_before=now - 30,
            not_after=now + ADMISSION_VALIDITY_SECONDS,
            sign=identity.sign,
        )
        response_core = {
            "v": FABRIC_LINK_PROTOCOL_VERSION,
            "handle": pending.payload.handle,
            "group_id": group_id,
            "welcome": pair.welcome,
            "admission_certificate": signed_certificate,
            "approved_grants": list(grants),
            "request_hash": hashlib.sha256(request_cbor).digest(),
            "issued_at": now,
            "expires_at": pending.payload.expires_at,
        }
        response_core_cbor = canonical_dumps(response_core)
        signature_input = (
            _RESPONSE_SIGNATURE_DOMAIN
            + hashlib.sha256(pending.payload.to_cbor()).digest()
            + hashlib.sha256(request_cbor).digest()
            + response_core_cbor
        )
        machine_signature = identity.sign(signature_input)
        response_cbor = canonical_dumps(
            {**response_core, "machine_signature": machine_signature}
        )
        nonce = secrets.token_bytes(ENROLLMENT_NONCE_BYTES)
        ciphertext = AESGCM(_derive_key(pending.payload, response=True)).encrypt(
            nonce,
            response_cbor,
            _aad(pending.payload, response=True),
        )
        encrypted_response = EncryptedEnrollment(
            handle=pending.payload.handle,
            nonce=nonce,
            ciphertext=ciphertext,
        ).to_cbor()
        created_device = LinkDevice(
            device_id=f"device_{secrets.token_hex(12)}",
            credential_hash=request.credential_hash,
            controller_name=request.controller_name,
            platform=request.platform,
            grants=grants,
            group_id=group_id,
            host_state=pair.host_state,
            relay_public_key=request.relay_public_key,
            credential_serial=credential_serial,
            admission_certificate=signed_certificate,
            status="active",
            created_at=now,
            updated_at=now,
            revoked_at=None,
            final_remove_commit=None,
        )
        self._store.consume_pending_and_add_device(
            handle=pending.payload.handle,
            secret_marker=pending.secret_marker,
            device=created_device,
            now=now,
        )
        self._pending.pop(pending.payload.handle, None)
        return encrypted_response

    def deny(self, *, handle: bytes) -> None:
        with self._lock:
            self._expire_locked(handle)

    def _expire_locked(self, handle: bytes) -> None:
        self._pending.pop(handle, None)
        self._store.cancel_pending(handle)


def decrypt_enrollment_response(
    *,
    payload: PairingPayload,
    request: EnrollmentRequest,
    encrypted_response: bytes,
    now: int,
) -> EnrollmentResult:
    envelope = EncryptedEnrollment.from_cbor(encrypted_response)
    if not hmac.compare_digest(envelope.handle, payload.handle):
        raise LinkEnrollmentError("enrollment_handle_mismatch")
    try:
        response_cbor = AESGCM(_derive_key(payload, response=True)).decrypt(
            envelope.nonce,
            envelope.ciphertext,
            _aad(payload, response=True),
        )
        response = canonical_loads(
            response_cbor,
            maximum=MAX_ENROLLMENT_RECORD_BYTES,
            expected_type=dict,
        )
        _exact_keys(response, _RESPONSE_KEYS)
    except Exception as exc:
        raise LinkEnrollmentError("invalid_enrollment_response") from exc
    signature = _require_bytes(response["machine_signature"], 64)
    response_core = {
        key: value for key, value in response.items() if key != "machine_signature"
    }
    response_core_cbor = canonical_dumps(response_core)
    signature_input = (
        _RESPONSE_SIGNATURE_DOMAIN
        + hashlib.sha256(payload.to_cbor()).digest()
        + hashlib.sha256(request.to_cbor()).digest()
        + response_core_cbor
    )
    try:
        Ed25519PublicKey.from_public_bytes(payload.machine_key).verify(
            signature,
            signature_input,
        )
    except (InvalidSignature, ValueError) as exc:
        raise LinkEnrollmentError("machine_signature_invalid") from exc
    grants_raw = response["approved_grants"]
    if not isinstance(grants_raw, list):
        raise LinkEnrollmentError("invalid_enrollment_response")
    grants = normalize_grants(grants_raw)
    if (
        _require_int(response["v"]) != FABRIC_LINK_PROTOCOL_VERSION
        or not hmac.compare_digest(
            _require_bytes(response["handle"], 32),
            payload.handle,
        )
        or not hmac.compare_digest(
            _require_bytes(response["request_hash"], 32),
            hashlib.sha256(request.to_cbor()).digest(),
        )
        or _require_int(response["issued_at"]) > now + 30
        or _require_int(response["expires_at"]) <= now
        or not set(grants) <= set(request.requested_grants)
    ):
        raise LinkEnrollmentError("invalid_enrollment_response")
    group_id = _require_bytes(response["group_id"], GROUP_ID_BYTES)
    welcome = _require_bytes(response["welcome"])
    if not welcome or len(welcome) > MAX_KEY_PACKAGE_BYTES:
        raise LinkEnrollmentError("invalid_enrollment_response")
    signed_certificate = _require_bytes(response["admission_certificate"])
    certificate = verify_admission_certificate(
        signed_certificate,
        machine_key=payload.machine_key,
        route_id=payload.route,
        relay_public_key=request.relay_public_key,
        now=now,
    )
    return EnrollmentResult(
        group_id=group_id,
        welcome=welcome,
        admission_certificate=signed_certificate,
        credential_serial=_require_bytes(certificate["credential_serial"], 16),
        approved_grants=grants,
        machine_signature=signature,
    )


def revoke_device(
    *,
    store: LinkDeviceStore,
    core: LinkCryptoCore,
    device_id: str,
    now: int,
) -> LinkDevice:
    """Deny locally first, then advance the MLS group and retain the Remove."""
    current = store.get_device(device_id)
    if current is None:
        raise LinkStorageError("device_not_found")
    if current.status == "active":
        denied = store.deny_device(device_id, now=now)
    elif current.status == "revoked" and current.final_remove_commit is None:
        denied = current
    elif current.status == "revoked":
        return current
    else:
        raise LinkStorageError("device_not_active")
    try:
        update = core.remove_controller(host_state=denied.host_state)
        store.finish_revocation(
            device_id,
            host_state=update.opaque_state,
            remove_commit=update.message,
            now=now,
        )
    except Exception as exc:
        raise LinkRevocationIncomplete(
            "device is locally denied; MLS removal must be reconciled"
        ) from exc
    current = store.get_device(device_id)
    if current is None:
        raise LinkStorageError("device_not_found")
    return current
