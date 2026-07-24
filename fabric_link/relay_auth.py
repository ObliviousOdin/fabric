"""Challenge-signature admission for the blind Fabric Link relay.

Relay authentication protects mailbox ownership and abuse controls. It is not
Fabric authorization: only the machine's encrypted application boundary grants
or dispatches a Fabric operation.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, replace

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .enrollment import LinkEnrollmentError, verify_admission_certificate
from .protocol import canonical_dumps, normalize_relay_origin
from .relay_contract import (
    RELAY_CREDENTIAL_SERIAL_BYTES,
    RELAY_PUBLIC_KEY_BYTES,
    RelayAuthentication,
    RelayChallenge,
    RelayRevocation,
)
from .store import MachineIdentity

_AUTH_DOMAIN = b"fabric-link-relay-auth-v1\x00"
_REVOCATION_DOMAIN = b"fabric-link-relay-revocation-v1\x00"
_REVOCATION_MAX_AGE_SECONDS = 24 * 60 * 60
_CLOCK_SKEW_SECONDS = 60


class LinkRelayAuthenticationError(PermissionError):
    """A relay endpoint did not prove the required route or controller key."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RelayAdmission:
    """Identity available only for relay mailbox ownership checks."""

    route_id: bytes
    role: str
    credential_serial: bytes | None
    public_key: bytes


def _normalized_origin(relay_origin: str) -> str:
    try:
        return normalize_relay_origin(relay_origin)
    except Exception as exc:
        raise LinkRelayAuthenticationError("invalid_relay_origin") from exc


def relay_authentication_input(
    *,
    relay_origin: str,
    authentication: RelayAuthentication,
) -> bytes:
    """Return the exact signed challenge response input.

    The origin prevents a valid response from being replayed against another
    relay. The ephemeral nonce binds it to one connection attempt.
    """

    origin = _normalized_origin(relay_origin)
    return _AUTH_DOMAIN + canonical_dumps({
        "relay": origin,
        "authentication": authentication.unsigned_value(),
    })


def relay_revocation_input(
    *,
    relay_origin: str,
    revocation: RelayRevocation,
) -> bytes:
    """Return the exact machine-signed relay revocation input."""

    origin = _normalized_origin(relay_origin)
    return _REVOCATION_DOMAIN + canonical_dumps({
        "relay": origin,
        "revocation": revocation.unsigned_value(),
    })


def _challenge_nonce(challenge: RelayChallenge, *, now: int) -> bytes:
    if now > challenge.expires_at:
        raise LinkRelayAuthenticationError("relay_challenge_expired")
    return challenge.nonce


def create_host_authentication(
    *,
    machine_identity: MachineIdentity,
    challenge: RelayChallenge,
    relay_origin: str,
    now: int,
) -> RelayAuthentication:
    """Prove possession of the machine route key for one challenge."""

    unsigned = RelayAuthentication(
        route_id=machine_identity.route_id,
        role="host",
        nonce=_challenge_nonce(challenge, now=now),
        route_public_key=machine_identity.public_key,
        signature=bytes(64),
    )
    return replace(
        unsigned,
        signature=machine_identity.sign(
            relay_authentication_input(
                relay_origin=relay_origin,
                authentication=unsigned,
            )
        ),
    )


def create_controller_authentication(
    *,
    route_id: bytes,
    credential_serial: bytes,
    admission_certificate: bytes,
    controller_private_key: Ed25519PrivateKey,
    challenge: RelayChallenge,
    relay_origin: str,
    now: int,
) -> RelayAuthentication:
    """Prove possession of an admission-certificate controller relay key."""

    controller_public_key = controller_private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    unsigned = RelayAuthentication(
        route_id=route_id,
        role="controller",
        nonce=_challenge_nonce(challenge, now=now),
        credential_serial=credential_serial,
        controller_public_key=controller_public_key,
        admission_certificate=admission_certificate,
        signature=bytes(64),
    )
    return replace(
        unsigned,
        signature=controller_private_key.sign(
            relay_authentication_input(
                relay_origin=relay_origin,
                authentication=unsigned,
            )
        ),
    )


def create_relay_revocation(
    *,
    machine_identity: MachineIdentity,
    credential_serial: bytes,
    relay_origin: str,
    now: int,
) -> RelayRevocation:
    """Sign one route-scoped serial revocation with the machine identity."""

    unsigned = RelayRevocation(
        route_id=machine_identity.route_id,
        credential_serial=credential_serial,
        issued_at=now,
        signature=bytes(64),
    )
    return replace(
        unsigned,
        signature=machine_identity.sign(
            relay_revocation_input(
                relay_origin=relay_origin,
                revocation=unsigned,
            )
        ),
    )


def verify_host_authentication(
    *,
    authentication: RelayAuthentication,
    challenge: RelayChallenge,
    relay_origin: str,
    now: int,
    registered_route_public_key: bytes | None = None,
) -> RelayAdmission:
    """Verify host proof and keep an existing route bound to one key."""

    if authentication.role != "host":
        raise LinkRelayAuthenticationError("relay_role_not_host")
    _verify_challenge_binding(
        authentication=authentication,
        challenge=challenge,
        now=now,
    )
    public_key = authentication.route_public_key
    if public_key is None:
        raise LinkRelayAuthenticationError("invalid_relay_route_key")
    if registered_route_public_key is not None and not hmac.compare_digest(
        public_key,
        registered_route_public_key,
    ):
        raise LinkRelayAuthenticationError("relay_route_key_mismatch")
    _verify_signature(
        public_key=public_key,
        signature=authentication.signature,
        data=relay_authentication_input(
            relay_origin=relay_origin,
            authentication=authentication,
        ),
    )
    return RelayAdmission(
        route_id=authentication.route_id,
        role="host",
        credential_serial=None,
        public_key=public_key,
    )


def verify_controller_authentication(
    *,
    authentication: RelayAuthentication,
    challenge: RelayChallenge,
    relay_origin: str,
    now: int,
    registered_route_public_key: bytes,
) -> RelayAdmission:
    """Verify a machine-signed controller certificate and challenge proof."""

    if authentication.role != "controller":
        raise LinkRelayAuthenticationError("relay_role_not_controller")
    _verify_challenge_binding(
        authentication=authentication,
        challenge=challenge,
        now=now,
    )
    serial = authentication.credential_serial
    public_key = authentication.controller_public_key
    certificate = authentication.admission_certificate
    if (
        serial is None
        or len(serial) != RELAY_CREDENTIAL_SERIAL_BYTES
        or public_key is None
        or len(public_key) != RELAY_PUBLIC_KEY_BYTES
        or certificate is None
    ):
        raise LinkRelayAuthenticationError("invalid_relay_controller_identity")
    try:
        verified_certificate = verify_admission_certificate(
            certificate,
            machine_key=registered_route_public_key,
            route_id=authentication.route_id,
            relay_public_key=public_key,
            now=now,
        )
    except (LinkEnrollmentError, ValueError) as exc:
        raise LinkRelayAuthenticationError(
            "invalid_relay_admission_certificate"
        ) from exc
    certificate_serial = verified_certificate["credential_serial"]
    if not isinstance(certificate_serial, bytes) or not hmac.compare_digest(
        certificate_serial,
        serial,
    ):
        raise LinkRelayAuthenticationError("relay_certificate_serial_mismatch")
    _verify_signature(
        public_key=public_key,
        signature=authentication.signature,
        data=relay_authentication_input(
            relay_origin=relay_origin,
            authentication=authentication,
        ),
    )
    return RelayAdmission(
        route_id=authentication.route_id,
        role="controller",
        credential_serial=serial,
        public_key=public_key,
    )


def verify_relay_revocation(
    *,
    revocation: RelayRevocation,
    relay_origin: str,
    now: int,
    registered_route_public_key: bytes,
) -> None:
    """Verify freshness, route ownership, and signature of a revocation."""

    if revocation.issued_at > now + _CLOCK_SKEW_SECONDS:
        raise LinkRelayAuthenticationError("relay_revocation_from_future")
    if now - revocation.issued_at > _REVOCATION_MAX_AGE_SECONDS:
        raise LinkRelayAuthenticationError("relay_revocation_expired")
    _verify_signature(
        public_key=registered_route_public_key,
        signature=revocation.signature,
        data=relay_revocation_input(
            relay_origin=relay_origin,
            revocation=revocation,
        ),
    )


def _verify_challenge_binding(
    *,
    authentication: RelayAuthentication,
    challenge: RelayChallenge,
    now: int,
) -> None:
    expected_nonce = _challenge_nonce(challenge, now=now)
    if not hmac.compare_digest(authentication.nonce, expected_nonce):
        raise LinkRelayAuthenticationError("relay_challenge_mismatch")


def _verify_signature(*, public_key: bytes, signature: bytes, data: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
    except (InvalidSignature, ValueError) as exc:
        raise LinkRelayAuthenticationError("relay_signature_invalid") from exc
