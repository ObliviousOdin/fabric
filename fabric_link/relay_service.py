"""Durable blind mailbox service shared by hosted and self-hosted Link relays.

Only routing metadata and opaque encrypted records cross this boundary. Fabric
methods, parameters, grants, responses, MLS state, pairing secrets, and machine
labels are neither parsed nor stored here.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from .protocol import normalize_relay_origin
from .relay_auth import (
    LinkRelayAuthenticationError,
    RelayAdmission,
    verify_controller_authentication,
    verify_host_authentication,
    verify_relay_revocation,
)
from .relay_contract import (
    RELAY_MAX_TTL_SECONDS,
    RELAY_NONCE_BYTES,
    RelayAcknowledgement,
    RelayAuthentication,
    RelayChallenge,
    RelayDelivery,
    RelayEnrollmentAcknowledgement,
    RelayEnrollmentDelivery,
    RelayEnrollmentMailbox,
    RelayEnrollmentPublish,
    RelayMailbox,
    RelayPublish,
    RelayRevocation,
)

_Kind: TypeAlias = Literal["application", "enrollment"]
_Recipient: TypeAlias = Literal["host", "controller"]
_APPLICATION_QUEUE_LIMIT = 512
_ENROLLMENT_QUEUE_LIMIT = 4
_RECEIPT_RETENTION_SECONDS = 24 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routes (
    route_id BLOB PRIMARY KEY,
    public_key BLOB NOT NULL,
    registered_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS revoked_serials (
    route_id BLOB NOT NULL,
    credential_serial BLOB NOT NULL,
    revoked_at INTEGER NOT NULL,
    PRIMARY KEY(route_id, credential_serial),
    FOREIGN KEY(route_id) REFERENCES routes(route_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mailbox_counters (
    kind TEXT NOT NULL,
    route_id BLOB NOT NULL,
    subject BLOB NOT NULL,
    recipient TEXT NOT NULL,
    next_sequence INTEGER NOT NULL,
    PRIMARY KEY(kind, route_id, subject, recipient)
);

CREATE TABLE IF NOT EXISTS records (
    kind TEXT NOT NULL,
    route_id BLOB NOT NULL,
    subject BLOB NOT NULL,
    recipient TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    message_id BLOB NOT NULL,
    expires_at INTEGER NOT NULL,
    opaque_record BLOB NOT NULL,
    record_digest BLOB NOT NULL,
    PRIMARY KEY(kind, route_id, subject, recipient, sequence),
    UNIQUE(kind, route_id, subject, recipient, message_id)
);

CREATE TABLE IF NOT EXISTS receipts (
    kind TEXT NOT NULL,
    route_id BLOB NOT NULL,
    subject BLOB NOT NULL,
    recipient TEXT NOT NULL,
    message_id BLOB NOT NULL,
    sequence INTEGER NOT NULL,
    record_digest BLOB NOT NULL,
    retain_until INTEGER NOT NULL,
    PRIMARY KEY(kind, route_id, subject, recipient, message_id)
);

CREATE INDEX IF NOT EXISTS idx_relay_records_expiry ON records(expires_at);
CREATE INDEX IF NOT EXISTS idx_relay_receipts_retention ON receipts(retain_until);
"""


class BlindRelayError(RuntimeError):
    """A stable rejection safe to return to an endpoint."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RelayApplicationPage:
    deliveries: tuple[RelayDelivery, ...]
    high_watermark: int


@dataclass(frozen=True)
class RelayEnrollmentPage:
    deliveries: tuple[RelayEnrollmentDelivery, ...]
    high_watermark: int


@dataclass(frozen=True)
class BlindRelaySnapshot:
    """Credential-free operator counters; never includes record bytes or IDs."""

    routes: int
    revoked_serials: int
    application_records: int
    enrollment_records: int
    expired_records_removed: int


class BlindRelayService:
    """Thread-safe SQLite implementation of the canonical blind relay contract."""

    def __init__(
        self,
        *,
        relay_origin: str,
        db_path: Path | str = ":memory:",
    ) -> None:
        try:
            self.origin = normalize_relay_origin(
                relay_origin,
                allow_loopback_http=True,
            )
        except Exception as exc:
            raise BlindRelayError("invalid_relay_origin") from exc
        self._lock = threading.RLock()
        self._challenges: dict[bytes, RelayChallenge] = {}
        self._expired_records_removed = 0
        try:
            self._conn = sqlite3.connect(
                str(db_path),
                isolation_level=None,
                check_same_thread=False,
                timeout=5,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA trusted_schema=OFF")
            self._conn.execute("PRAGMA secure_delete=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            if str(db_path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise BlindRelayError("relay_store_unavailable") from exc

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> "BlindRelayService":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def issue_challenge(
        self,
        *,
        now: int,
        ttl_seconds: int = 30,
        nonce: bytes | None = None,
    ) -> RelayChallenge:
        if not 1 <= ttl_seconds <= RELAY_MAX_TTL_SECONDS:
            raise BlindRelayError("invalid_relay_challenge_lifetime")
        challenge = RelayChallenge(
            nonce=secrets.token_bytes(RELAY_NONCE_BYTES) if nonce is None else nonce,
            server_time=now,
            expires_at=now + ttl_seconds,
            protocol_versions=(1,),
        )
        with self._lock:
            self._purge_challenges(now)
            if challenge.nonce in self._challenges:
                raise BlindRelayError("relay_challenge_collision")
            self._challenges[challenge.nonce] = challenge
        return challenge

    def authenticate(
        self,
        authentication: RelayAuthentication,
        *,
        now: int,
    ) -> RelayAdmission:
        """Consume one challenge and authenticate one endpoint connection."""

        with self._lock:
            challenge = self._challenges.pop(authentication.nonce, None)
            if challenge is None:
                raise BlindRelayError("relay_challenge_unknown")
            route_key = self._route_key(authentication.route_id)
            try:
                if authentication.role == "host":
                    admission = verify_host_authentication(
                        authentication=authentication,
                        challenge=challenge,
                        relay_origin=self.origin,
                        now=now,
                        registered_route_public_key=route_key,
                    )
                    self._register_route(admission, now=now)
                    return admission
                if route_key is None:
                    raise BlindRelayError("relay_route_unknown")
                if self._is_revoked(
                    authentication.route_id,
                    authentication.credential_serial,
                ):
                    raise BlindRelayError("relay_credential_revoked")
                return verify_controller_authentication(
                    authentication=authentication,
                    challenge=challenge,
                    relay_origin=self.origin,
                    now=now,
                    registered_route_public_key=route_key,
                )
            except LinkRelayAuthenticationError as exc:
                raise BlindRelayError(exc.code) from exc

    def publish(
        self,
        admission: RelayAdmission,
        frame: RelayPublish,
        *,
        now: int,
    ) -> int:
        self._authorize_application_sender(admission, frame.mailbox)
        self._require_live_serial(frame.mailbox)
        self._require_expiry(frame.expires_at, now=now)
        return self._append(
            kind="application",
            route_id=frame.mailbox.route_id,
            subject=frame.mailbox.credential_serial,
            recipient=frame.mailbox.recipient,
            message_id=frame.message_id,
            expires_at=frame.expires_at,
            opaque_record=frame.opaque_record,
            queue_limit=_APPLICATION_QUEUE_LIMIT,
            now=now,
        )

    def poll(
        self,
        admission: RelayAdmission,
        mailbox: RelayMailbox,
        *,
        after_sequence: int,
        limit: int,
        now: int,
    ) -> RelayApplicationPage:
        self._authorize_application_recipient(admission, mailbox)
        self._require_live_serial(mailbox)
        rows, high_watermark = self._read_page(
            kind="application",
            route_id=mailbox.route_id,
            subject=mailbox.credential_serial,
            recipient=mailbox.recipient,
            after_sequence=after_sequence,
            limit=limit,
            now=now,
        )
        return RelayApplicationPage(
            deliveries=tuple(
                RelayDelivery(
                    mailbox=mailbox,
                    sequence=int(row["sequence"]),
                    message_id=bytes(row["message_id"]),
                    expires_at=int(row["expires_at"]),
                    opaque_record=bytes(row["opaque_record"]),
                )
                for row in rows
            ),
            high_watermark=high_watermark,
        )

    def acknowledge(
        self,
        admission: RelayAdmission,
        frame: RelayAcknowledgement,
        *,
        now: int,
    ) -> int:
        self._authorize_application_recipient(admission, frame.mailbox)
        return self._ack(
            kind="application",
            route_id=frame.mailbox.route_id,
            subject=frame.mailbox.credential_serial,
            recipient=frame.mailbox.recipient,
            sequence=frame.sequence,
            message_id=frame.message_id,
            now=now,
        )

    def publish_enrollment(
        self,
        frame: RelayEnrollmentPublish,
        *,
        now: int,
        host_admission: RelayAdmission | None = None,
    ) -> int:
        """Append one encrypted pairing record.

        A controller request is authorized by possession of the unguessable QR
        route/handle and remains useless without the QR secret. A response
        requires an authenticated host connection for the exact route.
        """

        self._require_registered_route(frame.mailbox.route_id)
        if frame.mailbox.recipient == "controller":
            self._require_host(host_admission, frame.mailbox.route_id)
        elif host_admission is not None:
            raise BlindRelayError("invalid_relay_enrollment_direction")
        self._require_expiry(frame.expires_at, now=now)
        return self._append(
            kind="enrollment",
            route_id=frame.mailbox.route_id,
            subject=frame.mailbox.pairing_handle,
            recipient=frame.mailbox.recipient,
            message_id=frame.message_id,
            expires_at=frame.expires_at,
            opaque_record=frame.opaque_record,
            queue_limit=_ENROLLMENT_QUEUE_LIMIT,
            now=now,
        )

    def poll_enrollment(
        self,
        mailbox: RelayEnrollmentMailbox,
        *,
        after_sequence: int,
        limit: int,
        now: int,
        host_admission: RelayAdmission | None = None,
    ) -> RelayEnrollmentPage:
        self._require_registered_route(mailbox.route_id)
        if mailbox.recipient == "host":
            self._require_host(host_admission, mailbox.route_id)
        elif host_admission is not None:
            raise BlindRelayError("invalid_relay_enrollment_direction")
        rows, high_watermark = self._read_page(
            kind="enrollment",
            route_id=mailbox.route_id,
            subject=mailbox.pairing_handle,
            recipient=mailbox.recipient,
            after_sequence=after_sequence,
            limit=min(limit, _ENROLLMENT_QUEUE_LIMIT),
            now=now,
        )
        return RelayEnrollmentPage(
            deliveries=tuple(
                RelayEnrollmentDelivery(
                    mailbox=mailbox,
                    sequence=int(row["sequence"]),
                    message_id=bytes(row["message_id"]),
                    expires_at=int(row["expires_at"]),
                    opaque_record=bytes(row["opaque_record"]),
                )
                for row in rows
            ),
            high_watermark=high_watermark,
        )

    def acknowledge_enrollment(
        self,
        frame: RelayEnrollmentAcknowledgement,
        *,
        now: int,
        host_admission: RelayAdmission | None = None,
    ) -> int:
        self._require_registered_route(frame.mailbox.route_id)
        if frame.mailbox.recipient == "host":
            self._require_host(host_admission, frame.mailbox.route_id)
        elif host_admission is not None:
            raise BlindRelayError("invalid_relay_enrollment_direction")
        return self._ack(
            kind="enrollment",
            route_id=frame.mailbox.route_id,
            subject=frame.mailbox.pairing_handle,
            recipient=frame.mailbox.recipient,
            sequence=frame.sequence,
            message_id=frame.message_id,
            now=now,
        )

    def revoke(
        self,
        admission: RelayAdmission,
        revocation: RelayRevocation,
        *,
        now: int,
    ) -> None:
        self._require_host(admission, revocation.route_id)
        with self._lock:
            route_key = self._route_key(revocation.route_id)
            if route_key is None:
                raise BlindRelayError("relay_route_unknown")
            try:
                verify_relay_revocation(
                    revocation=revocation,
                    relay_origin=self.origin,
                    now=now,
                    registered_route_public_key=route_key,
                )
            except LinkRelayAuthenticationError as exc:
                raise BlindRelayError(exc.code) from exc
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT OR IGNORE INTO revoked_serials("
                    "route_id, credential_serial, revoked_at) VALUES(?, ?, ?)",
                    (
                        revocation.route_id,
                        revocation.credential_serial,
                        now,
                    ),
                )
                self._conn.execute(
                    "DELETE FROM records "
                    "WHERE kind='application' AND route_id=? AND subject=?",
                    (revocation.route_id, revocation.credential_serial),
                )
                self._conn.execute("COMMIT")
            except sqlite3.Error as exc:
                self._rollback()
                raise BlindRelayError("relay_store_unavailable") from exc

    def snapshot(self, *, now: int) -> BlindRelaySnapshot:
        with self._lock:
            self._purge(now)
            values = {
                "routes": self._count("routes"),
                "revoked_serials": self._count("revoked_serials"),
                "application_records": self._count("records", "kind='application'"),
                "enrollment_records": self._count("records", "kind='enrollment'"),
            }
            return BlindRelaySnapshot(
                **values,
                expired_records_removed=self._expired_records_removed,
            )

    def _register_route(self, admission: RelayAdmission, *, now: int) -> None:
        existing = self._route_key(admission.route_id)
        if existing is not None:
            if not secrets.compare_digest(existing, admission.public_key):
                raise BlindRelayError("relay_route_key_mismatch")
            return
        try:
            self._conn.execute(
                "INSERT INTO routes(route_id, public_key, registered_at) "
                "VALUES(?, ?, ?)",
                (admission.route_id, admission.public_key, now),
            )
        except sqlite3.IntegrityError:
            existing = self._route_key(admission.route_id)
            if existing is None or not secrets.compare_digest(
                existing,
                admission.public_key,
            ):
                raise BlindRelayError("relay_route_key_mismatch")
        except sqlite3.Error as exc:
            raise BlindRelayError("relay_store_unavailable") from exc

    def _route_key(self, route_id: bytes) -> bytes | None:
        row = self._conn.execute(
            "SELECT public_key FROM routes WHERE route_id=?",
            (route_id,),
        ).fetchone()
        return bytes(row["public_key"]) if row is not None else None

    def _require_registered_route(self, route_id: bytes) -> None:
        with self._lock:
            if self._route_key(route_id) is None:
                raise BlindRelayError("relay_route_unknown")

    def _is_revoked(
        self,
        route_id: bytes,
        credential_serial: bytes | None,
    ) -> bool:
        if credential_serial is None:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM revoked_serials WHERE route_id=? AND credential_serial=?",
            (route_id, credential_serial),
        ).fetchone()
        return row is not None

    def _require_live_serial(self, mailbox: RelayMailbox) -> None:
        with self._lock:
            if self._is_revoked(mailbox.route_id, mailbox.credential_serial):
                raise BlindRelayError("relay_credential_revoked")

    @staticmethod
    def _require_expiry(expires_at: int, *, now: int) -> None:
        if expires_at <= now or expires_at > now + RELAY_MAX_TTL_SECONDS:
            raise BlindRelayError("invalid_relay_record_lifetime")

    @staticmethod
    def _require_host(
        admission: RelayAdmission | None,
        route_id: bytes,
    ) -> None:
        if (
            admission is None
            or admission.role != "host"
            or not secrets.compare_digest(admission.route_id, route_id)
        ):
            raise BlindRelayError("relay_mailbox_forbidden")

    @staticmethod
    def _authorize_application_sender(
        admission: RelayAdmission,
        mailbox: RelayMailbox,
    ) -> None:
        if not secrets.compare_digest(admission.route_id, mailbox.route_id):
            raise BlindRelayError("relay_mailbox_forbidden")
        if admission.role == "host":
            if mailbox.recipient != "controller":
                raise BlindRelayError("relay_mailbox_forbidden")
            return
        if (
            mailbox.recipient != "host"
            or admission.credential_serial is None
            or not secrets.compare_digest(
                admission.credential_serial,
                mailbox.credential_serial,
            )
        ):
            raise BlindRelayError("relay_mailbox_forbidden")

    @staticmethod
    def _authorize_application_recipient(
        admission: RelayAdmission,
        mailbox: RelayMailbox,
    ) -> None:
        if (
            not secrets.compare_digest(admission.route_id, mailbox.route_id)
            or admission.role != mailbox.recipient
        ):
            raise BlindRelayError("relay_mailbox_forbidden")
        if admission.role == "controller" and (
            admission.credential_serial is None
            or not secrets.compare_digest(
                admission.credential_serial,
                mailbox.credential_serial,
            )
        ):
            raise BlindRelayError("relay_mailbox_forbidden")

    def _append(
        self,
        *,
        kind: _Kind,
        route_id: bytes,
        subject: bytes,
        recipient: _Recipient,
        message_id: bytes,
        expires_at: int,
        opaque_record: bytes,
        queue_limit: int,
        now: int,
    ) -> int:
        digest = hashlib.sha256(
            expires_at.to_bytes(8, "big", signed=False) + opaque_record
        ).digest()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._purge(now)
                receipt = self._conn.execute(
                    "SELECT sequence, record_digest FROM receipts "
                    "WHERE kind=? AND route_id=? AND subject=? "
                    "AND recipient=? AND message_id=?",
                    (kind, route_id, subject, recipient, message_id),
                ).fetchone()
                if receipt is not None:
                    if not secrets.compare_digest(
                        bytes(receipt["record_digest"]),
                        digest,
                    ):
                        raise BlindRelayError("relay_message_id_conflict")
                    self._conn.execute("COMMIT")
                    return int(receipt["sequence"])
                queued = self._conn.execute(
                    "SELECT COUNT(*) AS count FROM records "
                    "WHERE kind=? AND route_id=? AND subject=? AND recipient=?",
                    (kind, route_id, subject, recipient),
                ).fetchone()
                if int(queued["count"]) >= queue_limit:
                    raise BlindRelayError("relay_mailbox_full")
                counter = self._conn.execute(
                    "SELECT next_sequence FROM mailbox_counters "
                    "WHERE kind=? AND route_id=? AND subject=? AND recipient=?",
                    (kind, route_id, subject, recipient),
                ).fetchone()
                sequence = int(counter["next_sequence"]) if counter else 1
                if counter is None:
                    self._conn.execute(
                        "INSERT INTO mailbox_counters("
                        "kind, route_id, subject, recipient, next_sequence"
                        ") VALUES(?, ?, ?, ?, ?)",
                        (kind, route_id, subject, recipient, sequence + 1),
                    )
                else:
                    self._conn.execute(
                        "UPDATE mailbox_counters SET next_sequence=? "
                        "WHERE kind=? AND route_id=? AND subject=? AND recipient=?",
                        (
                            sequence + 1,
                            kind,
                            route_id,
                            subject,
                            recipient,
                        ),
                    )
                self._conn.execute(
                    "INSERT INTO records("
                    "kind, route_id, subject, recipient, sequence, message_id, "
                    "expires_at, opaque_record, record_digest"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        kind,
                        route_id,
                        subject,
                        recipient,
                        sequence,
                        message_id,
                        expires_at,
                        opaque_record,
                        digest,
                    ),
                )
                self._conn.execute(
                    "INSERT INTO receipts("
                    "kind, route_id, subject, recipient, message_id, sequence, "
                    "record_digest, retain_until"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        kind,
                        route_id,
                        subject,
                        recipient,
                        message_id,
                        sequence,
                        digest,
                        max(expires_at, now + _RECEIPT_RETENTION_SECONDS),
                    ),
                )
                self._conn.execute("COMMIT")
                return sequence
            except BlindRelayError:
                self._rollback()
                raise
            except sqlite3.Error as exc:
                self._rollback()
                raise BlindRelayError("relay_store_unavailable") from exc

    def _read_page(
        self,
        *,
        kind: _Kind,
        route_id: bytes,
        subject: bytes,
        recipient: _Recipient,
        after_sequence: int,
        limit: int,
        now: int,
    ) -> tuple[list[sqlite3.Row], int]:
        if after_sequence < 0 or not 1 <= limit <= 100:
            raise BlindRelayError("invalid_relay_poll")
        with self._lock:
            self._purge(now)
            rows = self._conn.execute(
                "SELECT sequence, message_id, expires_at, opaque_record "
                "FROM records WHERE kind=? AND route_id=? AND subject=? "
                "AND recipient=? AND sequence>? AND expires_at>? "
                "ORDER BY sequence LIMIT ?",
                (
                    kind,
                    route_id,
                    subject,
                    recipient,
                    after_sequence,
                    now,
                    limit,
                ),
            ).fetchall()
            counter = self._conn.execute(
                "SELECT next_sequence FROM mailbox_counters "
                "WHERE kind=? AND route_id=? AND subject=? AND recipient=?",
                (kind, route_id, subject, recipient),
            ).fetchone()
            high_watermark = int(counter["next_sequence"]) - 1 if counter else 0
            return list(rows), high_watermark

    def _ack(
        self,
        *,
        kind: _Kind,
        route_id: bytes,
        subject: bytes,
        recipient: _Recipient,
        sequence: int,
        message_id: bytes,
        now: int,
    ) -> int:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._purge(now)
                row = self._conn.execute(
                    "SELECT message_id FROM records "
                    "WHERE kind=? AND route_id=? AND subject=? "
                    "AND recipient=? AND sequence=?",
                    (kind, route_id, subject, recipient, sequence),
                ).fetchone()
                if row is None:
                    receipt = self._conn.execute(
                        "SELECT sequence FROM receipts "
                        "WHERE kind=? AND route_id=? AND subject=? "
                        "AND recipient=? AND message_id=?",
                        (kind, route_id, subject, recipient, message_id),
                    ).fetchone()
                    if receipt is None or int(receipt["sequence"]) != sequence:
                        raise BlindRelayError("relay_delivery_unknown")
                    self._conn.execute("COMMIT")
                    return sequence
                if not secrets.compare_digest(bytes(row["message_id"]), message_id):
                    raise BlindRelayError("relay_ack_mismatch")
                self._conn.execute(
                    "DELETE FROM records WHERE kind=? AND route_id=? "
                    "AND subject=? AND recipient=? AND sequence=?",
                    (kind, route_id, subject, recipient, sequence),
                )
                self._conn.execute("COMMIT")
                return sequence
            except BlindRelayError:
                self._rollback()
                raise
            except sqlite3.Error as exc:
                self._rollback()
                raise BlindRelayError("relay_store_unavailable") from exc

    def _purge(self, now: int) -> None:
        removed = self._conn.execute(
            "DELETE FROM records WHERE expires_at<=?",
            (now,),
        ).rowcount
        self._expired_records_removed += max(0, removed)
        self._conn.execute(
            "DELETE FROM receipts WHERE retain_until<=?",
            (now,),
        )

    def _purge_challenges(self, now: int) -> None:
        expired = [
            nonce
            for nonce, challenge in self._challenges.items()
            if challenge.expires_at < now
        ]
        for nonce in expired:
            self._challenges.pop(nonce, None)

    def _count(self, table: str, predicate: str = "1=1") -> int:
        allowed = {
            ("routes", "1=1"),
            ("revoked_serials", "1=1"),
            ("records", "kind='application'"),
            ("records", "kind='enrollment'"),
        }
        if (table, predicate) not in allowed:
            raise BlindRelayError("invalid_relay_metric")
        row = self._conn.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE {predicate}"
        ).fetchone()
        return int(row["count"])

    def _rollback(self) -> None:
        try:
            self._conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
