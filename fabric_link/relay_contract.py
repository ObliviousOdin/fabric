"""Strict opaque-wire contract for hosted and self-hosted Fabric Link relays.

The relay routes authenticated endpoint frames but never interprets the MLS
application record inside ``opaque_record``.  This module intentionally has no
WebSocket server: a hosted service and a self-hosted service must implement the
same exact, canonical-CBOR contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

from .protocol import (
    MAX_APPLICATION_ENVELOPE_BYTES,
    PAIRING_FIELD_BYTES,
    LinkProtocolError,
    canonical_dumps,
    canonical_loads,
)

RELAY_PROTOCOL_VERSION = 1
RELAY_NONCE_BYTES = 32
RELAY_MESSAGE_ID_BYTES = 16
RELAY_CREDENTIAL_SERIAL_BYTES = 16
RELAY_PUBLIC_KEY_BYTES = 32
RELAY_SIGNATURE_BYTES = 64
RELAY_MAX_TTL_SECONDS = 300
RELAY_MAX_ENROLLMENT_RECORD_BYTES = 256 * 1024
MAX_RELAY_FRAME_BYTES = MAX_APPLICATION_ENVELOPE_BYTES + 2048

RelayRole: TypeAlias = Literal["host", "controller"]
RelayRecipient: TypeAlias = Literal["host", "controller"]
_RELAY_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


class LinkRelayProtocolError(ValueError):
    """A relay frame was malformed, non-canonical, or outside its contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _exact_keys(value: dict[str, Any], keys: frozenset[str]) -> None:
    if frozenset(value) != keys:
        raise LinkRelayProtocolError("invalid_relay_frame")


def _require_int(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LinkRelayProtocolError(code)
    return value


def _require_bytes(value: Any, length: int | None, code: str) -> bytes:
    if not isinstance(value, bytes) or (length is not None and len(value) != length):
        raise LinkRelayProtocolError(code)
    return value


def _require_role(value: Any, code: str) -> RelayRole:
    if value not in {"host", "controller"}:
        raise LinkRelayProtocolError(code)
    return value


def _require_version(value: Any) -> int:
    version = _require_int(value, "invalid_relay_version")
    if version != RELAY_PROTOCOL_VERSION:
        raise LinkRelayProtocolError("unsupported_relay_version")
    return version


def _decode_frame(encoded: bytes) -> dict[str, Any]:
    try:
        return canonical_loads(
            encoded,
            maximum=MAX_RELAY_FRAME_BYTES,
            expected_type=dict,
        )
    except LinkProtocolError as exc:
        raise LinkRelayProtocolError("invalid_relay_frame") from exc


@dataclass(frozen=True)
class RelayMailbox:
    """One opaque queue direction for a route/controller pair."""

    route_id: bytes
    credential_serial: bytes
    recipient: RelayRecipient

    def __post_init__(self) -> None:
        _require_bytes(self.route_id, PAIRING_FIELD_BYTES, "invalid_relay_route")
        _require_bytes(
            self.credential_serial,
            RELAY_CREDENTIAL_SERIAL_BYTES,
            "invalid_relay_credential_serial",
        )
        _require_role(self.recipient, "invalid_relay_recipient")

    def to_value(self) -> dict[str, Any]:
        return {
            "route": self.route_id,
            "credential_serial": self.credential_serial,
            "recipient": self.recipient,
        }

    @classmethod
    def from_value(cls, value: Any) -> "RelayMailbox":
        if not isinstance(value, dict):
            raise LinkRelayProtocolError("invalid_relay_mailbox")
        _exact_keys(value, frozenset({"route", "credential_serial", "recipient"}))
        return cls(
            route_id=_require_bytes(
                value["route"], PAIRING_FIELD_BYTES, "invalid_relay_route"
            ),
            credential_serial=_require_bytes(
                value["credential_serial"],
                RELAY_CREDENTIAL_SERIAL_BYTES,
                "invalid_relay_credential_serial",
            ),
            recipient=_require_role(value["recipient"], "invalid_relay_recipient"),
        )


@dataclass(frozen=True)
class RelayEnrollmentMailbox:
    """One short-lived queue direction scoped to an exact pairing QR."""

    route_id: bytes
    pairing_handle: bytes = field(repr=False)
    recipient: RelayRecipient

    def __post_init__(self) -> None:
        _require_bytes(self.route_id, PAIRING_FIELD_BYTES, "invalid_relay_route")
        _require_bytes(
            self.pairing_handle,
            PAIRING_FIELD_BYTES,
            "invalid_relay_pairing_handle",
        )
        _require_role(self.recipient, "invalid_relay_recipient")

    def to_value(self) -> dict[str, Any]:
        return {
            "route": self.route_id,
            "pairing_handle": self.pairing_handle,
            "recipient": self.recipient,
        }

    @classmethod
    def from_value(cls, value: Any) -> "RelayEnrollmentMailbox":
        if not isinstance(value, dict):
            raise LinkRelayProtocolError("invalid_relay_enrollment_mailbox")
        _exact_keys(value, frozenset({"route", "pairing_handle", "recipient"}))
        return cls(
            route_id=_require_bytes(
                value["route"], PAIRING_FIELD_BYTES, "invalid_relay_route"
            ),
            pairing_handle=_require_bytes(
                value["pairing_handle"],
                PAIRING_FIELD_BYTES,
                "invalid_relay_pairing_handle",
            ),
            recipient=_require_role(value["recipient"], "invalid_relay_recipient"),
        )


@dataclass(frozen=True)
class RelayChallenge:
    """One relay-issued nonce bound to a short-lived connection attempt."""

    nonce: bytes = field(repr=False)
    server_time: int
    expires_at: int
    protocol_versions: tuple[int, ...] = (RELAY_PROTOCOL_VERSION,)

    def __post_init__(self) -> None:
        _require_bytes(self.nonce, RELAY_NONCE_BYTES, "invalid_relay_nonce")
        server_time = _require_int(self.server_time, "invalid_relay_time")
        expires_at = _require_int(self.expires_at, "invalid_relay_time")
        if (
            expires_at <= server_time
            or expires_at - server_time > RELAY_MAX_TTL_SECONDS
        ):
            raise LinkRelayProtocolError("invalid_relay_challenge_lifetime")
        if (
            not self.protocol_versions
            or any(
                isinstance(version, bool) or not isinstance(version, int)
                for version in self.protocol_versions
            )
            or tuple(sorted(set(self.protocol_versions), reverse=True))
            != self.protocol_versions
        ):
            raise LinkRelayProtocolError("invalid_relay_versions")

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "challenge",
            "nonce": self.nonce,
            "server_time": self.server_time,
            "expires_at": self.expires_at,
            "versions": list(self.protocol_versions),
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayChallenge":
        _exact_keys(
            value,
            frozenset({"v", "t", "nonce", "server_time", "expires_at", "versions"}),
        )
        _require_version(value["v"])
        if value["t"] != "challenge" or not isinstance(value["versions"], list):
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            nonce=_require_bytes(
                value["nonce"], RELAY_NONCE_BYTES, "invalid_relay_nonce"
            ),
            server_time=_require_int(value["server_time"], "invalid_relay_time"),
            expires_at=_require_int(value["expires_at"], "invalid_relay_time"),
            protocol_versions=tuple(value["versions"]),
        )


@dataclass(frozen=True)
class RelayAuthentication:
    """An endpoint's signed response to a relay challenge.

    Host authentication proves possession of the route signing key. Controller
    authentication proves possession of the relay key named by a machine-signed
    admission certificate. Neither form contains a Fabric grant or MLS state.
    """

    route_id: bytes
    role: RelayRole
    nonce: bytes = field(repr=False)
    signature: bytes = field(repr=False)
    credential_serial: bytes | None = None
    route_public_key: bytes | None = None
    controller_public_key: bytes | None = None
    admission_certificate: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_bytes(self.route_id, PAIRING_FIELD_BYTES, "invalid_relay_route")
        _require_role(self.role, "invalid_relay_role")
        _require_bytes(self.nonce, RELAY_NONCE_BYTES, "invalid_relay_nonce")
        _require_bytes(self.signature, RELAY_SIGNATURE_BYTES, "invalid_relay_signature")
        if self.role == "host":
            _require_bytes(
                self.route_public_key,
                RELAY_PUBLIC_KEY_BYTES,
                "invalid_relay_route_key",
            )
            if any(
                value is not None
                for value in (
                    self.credential_serial,
                    self.controller_public_key,
                    self.admission_certificate,
                )
            ):
                raise LinkRelayProtocolError("invalid_host_relay_authentication")
            return
        _require_bytes(
            self.credential_serial,
            RELAY_CREDENTIAL_SERIAL_BYTES,
            "invalid_relay_credential_serial",
        )
        _require_bytes(
            self.controller_public_key,
            RELAY_PUBLIC_KEY_BYTES,
            "invalid_relay_controller_key",
        )
        if (
            not isinstance(self.admission_certificate, bytes)
            or not self.admission_certificate
        ):
            raise LinkRelayProtocolError("invalid_relay_admission_certificate")
        if self.route_public_key is not None:
            raise LinkRelayProtocolError("invalid_controller_relay_authentication")

    def unsigned_value(self) -> dict[str, Any]:
        if self.role == "host":
            return {
                "v": RELAY_PROTOCOL_VERSION,
                "t": "auth",
                "route": self.route_id,
                "role": self.role,
                "nonce": self.nonce,
                "route_public_key": self.route_public_key,
            }
        return {
            "v": RELAY_PROTOCOL_VERSION,
            "t": "auth",
            "route": self.route_id,
            "role": self.role,
            "nonce": self.nonce,
            "credential_serial": self.credential_serial,
            "controller_public_key": self.controller_public_key,
            "admission_certificate": self.admission_certificate,
        }

    def to_cbor(self) -> bytes:
        return canonical_dumps({**self.unsigned_value(), "signature": self.signature})

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayAuthentication":
        _require_version(value.get("v"))
        role = _require_role(value.get("role"), "invalid_relay_role")
        if role == "host":
            _exact_keys(
                value,
                frozenset({
                    "v",
                    "t",
                    "route",
                    "role",
                    "nonce",
                    "route_public_key",
                    "signature",
                }),
            )
            if value["t"] != "auth":
                raise LinkRelayProtocolError("invalid_relay_frame")
            return cls(
                route_id=_require_bytes(
                    value["route"], PAIRING_FIELD_BYTES, "invalid_relay_route"
                ),
                role=role,
                nonce=_require_bytes(
                    value["nonce"], RELAY_NONCE_BYTES, "invalid_relay_nonce"
                ),
                route_public_key=_require_bytes(
                    value["route_public_key"],
                    RELAY_PUBLIC_KEY_BYTES,
                    "invalid_relay_route_key",
                ),
                signature=_require_bytes(
                    value["signature"], RELAY_SIGNATURE_BYTES, "invalid_relay_signature"
                ),
            )
        _exact_keys(
            value,
            frozenset({
                "v",
                "t",
                "route",
                "role",
                "nonce",
                "credential_serial",
                "controller_public_key",
                "admission_certificate",
                "signature",
            }),
        )
        if value["t"] != "auth":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            route_id=_require_bytes(
                value["route"], PAIRING_FIELD_BYTES, "invalid_relay_route"
            ),
            role=role,
            nonce=_require_bytes(
                value["nonce"], RELAY_NONCE_BYTES, "invalid_relay_nonce"
            ),
            credential_serial=_require_bytes(
                value["credential_serial"],
                RELAY_CREDENTIAL_SERIAL_BYTES,
                "invalid_relay_credential_serial",
            ),
            controller_public_key=_require_bytes(
                value["controller_public_key"],
                RELAY_PUBLIC_KEY_BYTES,
                "invalid_relay_controller_key",
            ),
            admission_certificate=_require_bytes(
                value["admission_certificate"],
                None,
                "invalid_relay_admission_certificate",
            ),
            signature=_require_bytes(
                value["signature"], RELAY_SIGNATURE_BYTES, "invalid_relay_signature"
            ),
        )


@dataclass(frozen=True)
class RelayPublish:
    """A client-to-relay opaque mailbox append."""

    mailbox: RelayMailbox
    message_id: bytes
    expires_at: int
    opaque_record: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _require_bytes(
            self.message_id, RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
        )
        _require_int(self.expires_at, "invalid_relay_time")
        if (
            not isinstance(self.opaque_record, bytes)
            or not self.opaque_record
            or len(self.opaque_record) > MAX_APPLICATION_ENVELOPE_BYTES
        ):
            raise LinkRelayProtocolError("invalid_relay_opaque_record")

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "publish",
            "mailbox": self.mailbox.to_value(),
            "message_id": self.message_id,
            "expires_at": self.expires_at,
            "opaque_record": self.opaque_record,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayPublish":
        _exact_keys(
            value,
            frozenset({
                "v",
                "t",
                "mailbox",
                "message_id",
                "expires_at",
                "opaque_record",
            }),
        )
        _require_version(value["v"])
        if value["t"] != "publish":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            mailbox=RelayMailbox.from_value(value["mailbox"]),
            message_id=_require_bytes(
                value["message_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
            ),
            expires_at=_require_int(value["expires_at"], "invalid_relay_time"),
            opaque_record=_require_bytes(
                value["opaque_record"], None, "invalid_relay_opaque_record"
            ),
        )


@dataclass(frozen=True)
class RelayDelivery:
    """A relay-to-client opaque record with a mailbox-local sequence number."""

    mailbox: RelayMailbox
    sequence: int
    message_id: bytes
    expires_at: int
    opaque_record: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if _require_int(self.sequence, "invalid_relay_sequence") < 1:
            raise LinkRelayProtocolError("invalid_relay_sequence")
        RelayPublish(
            mailbox=self.mailbox,
            message_id=self.message_id,
            expires_at=self.expires_at,
            opaque_record=self.opaque_record,
        )

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "delivery",
            "mailbox": self.mailbox.to_value(),
            "sequence": self.sequence,
            "message_id": self.message_id,
            "expires_at": self.expires_at,
            "opaque_record": self.opaque_record,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayDelivery":
        _exact_keys(
            value,
            frozenset({
                "v",
                "t",
                "mailbox",
                "sequence",
                "message_id",
                "expires_at",
                "opaque_record",
            }),
        )
        _require_version(value["v"])
        if value["t"] != "delivery":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            mailbox=RelayMailbox.from_value(value["mailbox"]),
            sequence=_require_int(value["sequence"], "invalid_relay_sequence"),
            message_id=_require_bytes(
                value["message_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
            ),
            expires_at=_require_int(value["expires_at"], "invalid_relay_time"),
            opaque_record=_require_bytes(
                value["opaque_record"], None, "invalid_relay_opaque_record"
            ),
        )


@dataclass(frozen=True)
class RelayAcknowledgement:
    """A durable-consumer acknowledgement for one relay delivery."""

    mailbox: RelayMailbox
    sequence: int
    message_id: bytes

    def __post_init__(self) -> None:
        if _require_int(self.sequence, "invalid_relay_sequence") < 1:
            raise LinkRelayProtocolError("invalid_relay_sequence")
        _require_bytes(
            self.message_id, RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
        )

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "ack",
            "mailbox": self.mailbox.to_value(),
            "sequence": self.sequence,
            "message_id": self.message_id,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayAcknowledgement":
        _exact_keys(value, frozenset({"v", "t", "mailbox", "sequence", "message_id"}))
        _require_version(value["v"])
        if value["t"] != "ack":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            mailbox=RelayMailbox.from_value(value["mailbox"]),
            sequence=_require_int(value["sequence"], "invalid_relay_sequence"),
            message_id=_require_bytes(
                value["message_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
            ),
        )


@dataclass(frozen=True)
class RelayEnrollmentPublish:
    """An opaque request or response append for one short-lived pairing handle."""

    mailbox: RelayEnrollmentMailbox
    message_id: bytes
    expires_at: int
    opaque_record: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _require_bytes(
            self.message_id, RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
        )
        _require_int(self.expires_at, "invalid_relay_time")
        if (
            not isinstance(self.opaque_record, bytes)
            or not self.opaque_record
            or len(self.opaque_record) > RELAY_MAX_ENROLLMENT_RECORD_BYTES
        ):
            raise LinkRelayProtocolError("invalid_relay_enrollment_record")

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "enrollment_publish",
            "mailbox": self.mailbox.to_value(),
            "message_id": self.message_id,
            "expires_at": self.expires_at,
            "opaque_record": self.opaque_record,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayEnrollmentPublish":
        _exact_keys(
            value,
            frozenset({
                "v",
                "t",
                "mailbox",
                "message_id",
                "expires_at",
                "opaque_record",
            }),
        )
        _require_version(value["v"])
        if value["t"] != "enrollment_publish":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            mailbox=RelayEnrollmentMailbox.from_value(value["mailbox"]),
            message_id=_require_bytes(
                value["message_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
            ),
            expires_at=_require_int(value["expires_at"], "invalid_relay_time"),
            opaque_record=_require_bytes(
                value["opaque_record"], None, "invalid_relay_enrollment_record"
            ),
        )


@dataclass(frozen=True)
class RelayEnrollmentDelivery:
    """A mailbox-local sequence around one opaque enrollment record."""

    mailbox: RelayEnrollmentMailbox
    sequence: int
    message_id: bytes
    expires_at: int
    opaque_record: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if _require_int(self.sequence, "invalid_relay_sequence") < 1:
            raise LinkRelayProtocolError("invalid_relay_sequence")
        RelayEnrollmentPublish(
            mailbox=self.mailbox,
            message_id=self.message_id,
            expires_at=self.expires_at,
            opaque_record=self.opaque_record,
        )

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "enrollment_delivery",
            "mailbox": self.mailbox.to_value(),
            "sequence": self.sequence,
            "message_id": self.message_id,
            "expires_at": self.expires_at,
            "opaque_record": self.opaque_record,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayEnrollmentDelivery":
        _exact_keys(
            value,
            frozenset({
                "v",
                "t",
                "mailbox",
                "sequence",
                "message_id",
                "expires_at",
                "opaque_record",
            }),
        )
        _require_version(value["v"])
        if value["t"] != "enrollment_delivery":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            mailbox=RelayEnrollmentMailbox.from_value(value["mailbox"]),
            sequence=_require_int(value["sequence"], "invalid_relay_sequence"),
            message_id=_require_bytes(
                value["message_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
            ),
            expires_at=_require_int(value["expires_at"], "invalid_relay_time"),
            opaque_record=_require_bytes(
                value["opaque_record"], None, "invalid_relay_enrollment_record"
            ),
        )


@dataclass(frozen=True)
class RelayEnrollmentAcknowledgement:
    """A durable-consumer acknowledgement for one pairing delivery."""

    mailbox: RelayEnrollmentMailbox
    sequence: int
    message_id: bytes

    def __post_init__(self) -> None:
        if _require_int(self.sequence, "invalid_relay_sequence") < 1:
            raise LinkRelayProtocolError("invalid_relay_sequence")
        _require_bytes(
            self.message_id, RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
        )

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "enrollment_ack",
            "mailbox": self.mailbox.to_value(),
            "sequence": self.sequence,
            "message_id": self.message_id,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayEnrollmentAcknowledgement":
        _exact_keys(value, frozenset({"v", "t", "mailbox", "sequence", "message_id"}))
        _require_version(value["v"])
        if value["t"] != "enrollment_ack":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            mailbox=RelayEnrollmentMailbox.from_value(value["mailbox"]),
            sequence=_require_int(value["sequence"], "invalid_relay_sequence"),
            message_id=_require_bytes(
                value["message_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
            ),
        )


@dataclass(frozen=True)
class RelayPoll:
    """Request a bounded replay page from one authenticated application mailbox."""

    mailbox: RelayMailbox
    request_id: bytes
    after_sequence: int = 0
    limit: int = 50

    def __post_init__(self) -> None:
        _require_bytes(
            self.request_id, RELAY_MESSAGE_ID_BYTES, "invalid_relay_request_id"
        )
        if _require_int(self.after_sequence, "invalid_relay_sequence") < 0:
            raise LinkRelayProtocolError("invalid_relay_sequence")
        if not 1 <= _require_int(self.limit, "invalid_relay_limit") <= 100:
            raise LinkRelayProtocolError("invalid_relay_limit")

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "poll",
            "mailbox": self.mailbox.to_value(),
            "request_id": self.request_id,
            "after_sequence": self.after_sequence,
            "limit": self.limit,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayPoll":
        _exact_keys(
            value,
            frozenset({
                "v",
                "t",
                "mailbox",
                "request_id",
                "after_sequence",
                "limit",
            }),
        )
        _require_version(value["v"])
        if value["t"] != "poll":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            mailbox=RelayMailbox.from_value(value["mailbox"]),
            request_id=_require_bytes(
                value["request_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_request_id"
            ),
            after_sequence=_require_int(
                value["after_sequence"], "invalid_relay_sequence"
            ),
            limit=_require_int(value["limit"], "invalid_relay_limit"),
        )


@dataclass(frozen=True)
class RelayEnrollmentPoll:
    """Request a bounded replay page for one short-lived enrollment mailbox."""

    mailbox: RelayEnrollmentMailbox
    request_id: bytes
    after_sequence: int = 0
    limit: int = 4

    def __post_init__(self) -> None:
        _require_bytes(
            self.request_id, RELAY_MESSAGE_ID_BYTES, "invalid_relay_request_id"
        )
        if _require_int(self.after_sequence, "invalid_relay_sequence") < 0:
            raise LinkRelayProtocolError("invalid_relay_sequence")
        if not 1 <= _require_int(self.limit, "invalid_relay_limit") <= 4:
            raise LinkRelayProtocolError("invalid_relay_limit")

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "enrollment_poll",
            "mailbox": self.mailbox.to_value(),
            "request_id": self.request_id,
            "after_sequence": self.after_sequence,
            "limit": self.limit,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayEnrollmentPoll":
        _exact_keys(
            value,
            frozenset({
                "v",
                "t",
                "mailbox",
                "request_id",
                "after_sequence",
                "limit",
            }),
        )
        _require_version(value["v"])
        if value["t"] != "enrollment_poll":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            mailbox=RelayEnrollmentMailbox.from_value(value["mailbox"]),
            request_id=_require_bytes(
                value["request_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_request_id"
            ),
            after_sequence=_require_int(
                value["after_sequence"], "invalid_relay_sequence"
            ),
            limit=_require_int(value["limit"], "invalid_relay_limit"),
        )


@dataclass(frozen=True)
class RelaySync:
    """Marks the end of one poll page without exposing queue contents."""

    request_id: bytes
    count: int
    high_watermark: int

    def __post_init__(self) -> None:
        _require_bytes(
            self.request_id, RELAY_MESSAGE_ID_BYTES, "invalid_relay_request_id"
        )
        if _require_int(self.count, "invalid_relay_count") < 0:
            raise LinkRelayProtocolError("invalid_relay_count")
        if _require_int(self.high_watermark, "invalid_relay_sequence") < 0:
            raise LinkRelayProtocolError("invalid_relay_sequence")

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "sync",
            "request_id": self.request_id,
            "count": self.count,
            "high_watermark": self.high_watermark,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelaySync":
        _exact_keys(
            value,
            frozenset({"v", "t", "request_id", "count", "high_watermark"}),
        )
        _require_version(value["v"])
        if value["t"] != "sync":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            request_id=_require_bytes(
                value["request_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_request_id"
            ),
            count=_require_int(value["count"], "invalid_relay_count"),
            high_watermark=_require_int(
                value["high_watermark"], "invalid_relay_sequence"
            ),
        )


@dataclass(frozen=True)
class RelayReceipt:
    """Confirms a publish or acknowledgement without echoing opaque bytes."""

    message_id: bytes
    sequence: int

    def __post_init__(self) -> None:
        _require_bytes(
            self.message_id, RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
        )
        if _require_int(self.sequence, "invalid_relay_sequence") < 1:
            raise LinkRelayProtocolError("invalid_relay_sequence")

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "receipt",
            "message_id": self.message_id,
            "sequence": self.sequence,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayReceipt":
        _exact_keys(value, frozenset({"v", "t", "message_id", "sequence"}))
        _require_version(value["v"])
        if value["t"] != "receipt":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            message_id=_require_bytes(
                value["message_id"], RELAY_MESSAGE_ID_BYTES, "invalid_relay_message_id"
            ),
            sequence=_require_int(value["sequence"], "invalid_relay_sequence"),
        )


@dataclass(frozen=True)
class RelayReady:
    """Confirms that challenge authentication completed on this connection."""

    role: RelayRole

    def __post_init__(self) -> None:
        _require_role(self.role, "invalid_relay_role")

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "ready",
            "role": self.role,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayReady":
        _exact_keys(value, frozenset({"v", "t", "role"}))
        _require_version(value["v"])
        if value["t"] != "ready":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(role=_require_role(value["role"], "invalid_relay_role"))


@dataclass(frozen=True)
class RelayFailure:
    """A stable relay rejection with optional request correlation."""

    code: str
    correlation_id: bytes | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not _RELAY_ERROR_RE.fullmatch(self.code):
            raise LinkRelayProtocolError("invalid_relay_error")
        if self.correlation_id is not None:
            _require_bytes(
                self.correlation_id,
                RELAY_MESSAGE_ID_BYTES,
                "invalid_relay_request_id",
            )

    def to_cbor(self) -> bytes:
        return canonical_dumps({
            "v": RELAY_PROTOCOL_VERSION,
            "t": "failure",
            "code": self.code,
            "correlation_id": self.correlation_id,
        })

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayFailure":
        _exact_keys(value, frozenset({"v", "t", "code", "correlation_id"}))
        _require_version(value["v"])
        if value["t"] != "failure":
            raise LinkRelayProtocolError("invalid_relay_frame")
        correlation_id = value["correlation_id"]
        if correlation_id is not None:
            correlation_id = _require_bytes(
                correlation_id,
                RELAY_MESSAGE_ID_BYTES,
                "invalid_relay_request_id",
            )
        return cls(code=value["code"], correlation_id=correlation_id)


@dataclass(frozen=True)
class RelayRevocation:
    """A machine-signed request to permanently reject one admission serial."""

    route_id: bytes
    credential_serial: bytes
    issued_at: int
    signature: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _require_bytes(self.route_id, PAIRING_FIELD_BYTES, "invalid_relay_route")
        _require_bytes(
            self.credential_serial,
            RELAY_CREDENTIAL_SERIAL_BYTES,
            "invalid_relay_credential_serial",
        )
        _require_int(self.issued_at, "invalid_relay_time")
        _require_bytes(self.signature, RELAY_SIGNATURE_BYTES, "invalid_relay_signature")

    def unsigned_value(self) -> dict[str, Any]:
        return {
            "v": RELAY_PROTOCOL_VERSION,
            "t": "revoke",
            "route": self.route_id,
            "credential_serial": self.credential_serial,
            "issued_at": self.issued_at,
        }

    def to_cbor(self) -> bytes:
        return canonical_dumps({**self.unsigned_value(), "signature": self.signature})

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "RelayRevocation":
        _exact_keys(
            value,
            frozenset({
                "v",
                "t",
                "route",
                "credential_serial",
                "issued_at",
                "signature",
            }),
        )
        _require_version(value["v"])
        if value["t"] != "revoke":
            raise LinkRelayProtocolError("invalid_relay_frame")
        return cls(
            route_id=_require_bytes(
                value["route"], PAIRING_FIELD_BYTES, "invalid_relay_route"
            ),
            credential_serial=_require_bytes(
                value["credential_serial"],
                RELAY_CREDENTIAL_SERIAL_BYTES,
                "invalid_relay_credential_serial",
            ),
            issued_at=_require_int(value["issued_at"], "invalid_relay_time"),
            signature=_require_bytes(
                value["signature"], RELAY_SIGNATURE_BYTES, "invalid_relay_signature"
            ),
        )


RelayFrame: TypeAlias = (
    RelayChallenge
    | RelayAuthentication
    | RelayPublish
    | RelayDelivery
    | RelayAcknowledgement
    | RelayEnrollmentPublish
    | RelayEnrollmentDelivery
    | RelayEnrollmentAcknowledgement
    | RelayPoll
    | RelayEnrollmentPoll
    | RelaySync
    | RelayReceipt
    | RelayReady
    | RelayFailure
    | RelayRevocation
)


def relay_frame_from_cbor(encoded: bytes) -> RelayFrame:
    """Decode exactly one canonical relay frame without examining its payload."""

    value = _decode_frame(encoded)
    frame_type = value.get("t")
    if frame_type == "challenge":
        return RelayChallenge.from_value(value)
    if frame_type == "auth":
        return RelayAuthentication.from_value(value)
    if frame_type == "publish":
        return RelayPublish.from_value(value)
    if frame_type == "delivery":
        return RelayDelivery.from_value(value)
    if frame_type == "ack":
        return RelayAcknowledgement.from_value(value)
    if frame_type == "enrollment_publish":
        return RelayEnrollmentPublish.from_value(value)
    if frame_type == "enrollment_delivery":
        return RelayEnrollmentDelivery.from_value(value)
    if frame_type == "enrollment_ack":
        return RelayEnrollmentAcknowledgement.from_value(value)
    if frame_type == "poll":
        return RelayPoll.from_value(value)
    if frame_type == "enrollment_poll":
        return RelayEnrollmentPoll.from_value(value)
    if frame_type == "sync":
        return RelaySync.from_value(value)
    if frame_type == "receipt":
        return RelayReceipt.from_value(value)
    if frame_type == "ready":
        return RelayReady.from_value(value)
    if frame_type == "failure":
        return RelayFailure.from_value(value)
    if frame_type == "revoke":
        return RelayRevocation.from_value(value)
    raise LinkRelayProtocolError("unsupported_relay_frame")
