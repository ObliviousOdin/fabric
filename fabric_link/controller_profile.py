"""Crash-safe controller profiles with secrets isolated in a platform vault."""

from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .capabilities import normalize_grants
from .protocol import (
    MAX_APPLICATION_ENVELOPE_BYTES,
    MAX_REQUEST_BYTES,
    PAIRING_FIELD_BYTES,
    PairingPayload,
    canonical_dumps,
    canonical_loads,
    normalize_relay_origin,
)
from .store import (
    _ensure_private_directory,
    _harden_private_path,
    _open_or_create_db_file,
    link_home,
)

_SCHEMA_VERSION = 1
_SECRET_VERSION = 1
_MAX_SECRET_BUNDLE_BYTES = 18 * 1024 * 1024
_MAX_CERTIFICATE_BYTES = 16 * 1024
_MAX_LABEL_BYTES = 96

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS controller_profiles (
    controller_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    platform TEXT NOT NULL,
    relay_origin TEXT NOT NULL,
    route_id BLOB NOT NULL,
    machine_public_key BLOB NOT NULL,
    credential_serial BLOB,
    admission_certificate BLOB,
    grants BLOB,
    status TEXT NOT NULL CHECK(status IN ('pending', 'active')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controller_profiles_status
ON controller_profiles(status, updated_at);
"""


class ControllerProfileError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ControllerSecretVault(Protocol):
    def load(self, controller_id: str) -> bytes | None: ...

    def store(self, controller_id: str, opaque_state: bytes) -> None: ...

    def remove(self, controller_id: str) -> None: ...


@dataclass(frozen=True)
class ControllerPendingApplication:
    request_id: bytes
    message_id: bytes
    expires_at: int
    envelope: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, bytes)
            or len(self.request_id) != 16
            or not isinstance(self.message_id, bytes)
            or len(self.message_id) != 16
            or isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, int)
            or not isinstance(self.envelope, bytes)
            or not self.envelope
            or len(self.envelope) > MAX_APPLICATION_ENVELOPE_BYTES
        ):
            raise ControllerProfileError("invalid_controller_pending_application")


@dataclass(frozen=True)
class ControllerSecretBundle:
    """The one platform-vault record that advances atomically."""

    opaque_state: bytes = field(repr=False)
    relay_private_key: bytes = field(repr=False)
    pairing_payload: bytes | None = field(default=None, repr=False)
    enrollment_request: bytes | None = field(default=None, repr=False)
    credential_serial: bytes | None = field(default=None, repr=False)
    admission_certificate: bytes | None = field(default=None, repr=False)
    grants: tuple[str, ...] = ()
    pending_application: ControllerPendingApplication | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.opaque_state, bytes)
            or not self.opaque_state
            or not isinstance(self.relay_private_key, bytes)
            or len(self.relay_private_key) != 32
        ):
            raise ControllerProfileError("invalid_controller_secret_bundle")
        if (self.pairing_payload is None) != (self.enrollment_request is None):
            raise ControllerProfileError("invalid_controller_enrollment_state")
        active_fields = (
            self.credential_serial,
            self.admission_certificate,
        )
        if any(value is not None for value in active_fields):
            if (
                self.credential_serial is None
                or len(self.credential_serial) != 16
                or self.admission_certificate is None
                or not 1 <= len(self.admission_certificate) <= _MAX_CERTIFICATE_BYTES
                or not self.grants
            ):
                raise ControllerProfileError("invalid_controller_admission")
            normalize_grants(self.grants)
        elif self.grants:
            raise ControllerProfileError("invalid_controller_admission")
        if self.pairing_payload is not None and self.credential_serial is not None:
            raise ControllerProfileError("invalid_controller_secret_bundle")
        if self.pairing_payload is None and self.credential_serial is None:
            raise ControllerProfileError("invalid_controller_secret_bundle")
        if self.pairing_payload is not None:
            if (
                not isinstance(self.pairing_payload, bytes)
                or len(self.pairing_payload) > 4096
                or not isinstance(self.enrollment_request, bytes)
                or not self.enrollment_request
                or len(self.enrollment_request) > MAX_REQUEST_BYTES
            ):
                raise ControllerProfileError("invalid_controller_enrollment_state")

    @property
    def relay_private_key_object(self) -> Ed25519PrivateKey:
        try:
            return Ed25519PrivateKey.from_private_bytes(self.relay_private_key)
        except ValueError as exc:
            raise ControllerProfileError("invalid_controller_relay_key") from exc

    def to_cbor(self) -> bytes:
        pending = self.pending_application
        encoded = canonical_dumps({
            "v": _SECRET_VERSION,
            "opaque_state": self.opaque_state,
            "relay_private_key": self.relay_private_key,
            "pairing_payload": self.pairing_payload,
            "enrollment_request": self.enrollment_request,
            "credential_serial": self.credential_serial,
            "admission_certificate": self.admission_certificate,
            "grants": list(self.grants),
            "pending_application": (
                None
                if pending is None
                else {
                    "request_id": pending.request_id,
                    "message_id": pending.message_id,
                    "expires_at": pending.expires_at,
                    "envelope": pending.envelope,
                }
            ),
        })
        if len(encoded) > _MAX_SECRET_BUNDLE_BYTES:
            raise ControllerProfileError("controller_secret_bundle_too_large")
        return encoded

    @classmethod
    def from_cbor(cls, encoded: bytes) -> "ControllerSecretBundle":
        try:
            value = canonical_loads(
                encoded,
                maximum=_MAX_SECRET_BUNDLE_BYTES,
                expected_type=dict,
            )
            if frozenset(value) != frozenset({
                "v",
                "opaque_state",
                "relay_private_key",
                "pairing_payload",
                "enrollment_request",
                "credential_serial",
                "admission_certificate",
                "grants",
                "pending_application",
            }):
                raise ControllerProfileError("invalid_controller_secret_bundle")
            if value["v"] != _SECRET_VERSION:
                raise ControllerProfileError("unsupported_controller_secret_version")
            pending_value = value["pending_application"]
            pending = None
            if pending_value is not None:
                if not isinstance(pending_value, dict) or frozenset(
                    pending_value
                ) != frozenset({
                    "request_id",
                    "message_id",
                    "expires_at",
                    "envelope",
                }):
                    raise ControllerProfileError(
                        "invalid_controller_pending_application"
                    )
                pending = ControllerPendingApplication(
                    request_id=pending_value["request_id"],
                    message_id=pending_value["message_id"],
                    expires_at=pending_value["expires_at"],
                    envelope=pending_value["envelope"],
                )
            return cls(
                opaque_state=value["opaque_state"],
                relay_private_key=value["relay_private_key"],
                pairing_payload=value["pairing_payload"],
                enrollment_request=value["enrollment_request"],
                credential_serial=value["credential_serial"],
                admission_certificate=value["admission_certificate"],
                grants=normalize_grants(
                    value["grants"],
                    allow_empty=True,
                ),
                pending_application=pending,
            )
        except ControllerProfileError:
            raise
        except Exception as exc:
            raise ControllerProfileError("invalid_controller_secret_bundle") from exc


@dataclass(frozen=True)
class ControllerProfile:
    controller_id: str
    label: str
    platform: str
    relay_origin: str
    route_id: bytes
    machine_public_key: bytes
    credential_serial: bytes | None
    admission_certificate: bytes | None = field(repr=False)
    grants: tuple[str, ...]
    status: str
    created_at: int
    updated_at: int


class ControllerProfileStore:
    """Public profile index plus one fail-closed platform-vault record per profile."""

    def __init__(
        self,
        *,
        vault: ControllerSecretVault,
        db_path: Path | None = None,
    ) -> None:
        self.path = db_path or (link_home() / "controllers.sqlite3")
        _ensure_private_directory(self.path.parent)
        _open_or_create_db_file(self.path)
        self._vault = vault
        try:
            self._conn = sqlite3.connect(
                str(self.path),
                isolation_level=None,
                timeout=5,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA trusted_schema=OFF")
            self._conn.execute("PRAGMA secure_delete=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._initialize_version()
        except sqlite3.Error as exc:
            raise ControllerProfileError(
                "controller_profile_store_unavailable"
            ) from exc
        _harden_private_path(self.path, directory=False)

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "ControllerProfileStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def create_pending(
        self,
        *,
        label: str,
        platform: str,
        payload: PairingPayload,
        secret_bundle: ControllerSecretBundle,
        now: int | None = None,
        controller_id: str | None = None,
    ) -> ControllerProfile:
        changed_at = int(time.time()) if now is None else now
        identifier = controller_id or f"controller_{secrets.token_hex(12)}"
        label = _validate_label(label)
        if platform not in {"desktop", "cli", "ios", "android", "web"}:
            raise ControllerProfileError("invalid_controller_platform")
        if secret_bundle.pairing_payload != payload.to_cbor():
            raise ControllerProfileError("controller_pairing_payload_mismatch")
        self._vault.store(identifier, secret_bundle.to_cbor())
        try:
            self._conn.execute(
                "INSERT INTO controller_profiles("
                "controller_id, label, platform, relay_origin, route_id, "
                "machine_public_key, credential_serial, admission_certificate, "
                "grants, status, created_at, updated_at"
                ") VALUES(?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 'pending', ?, ?)",
                (
                    identifier,
                    label,
                    platform,
                    payload.relay,
                    payload.route,
                    payload.machine_key,
                    changed_at,
                    changed_at,
                ),
            )
        except sqlite3.Error as exc:
            try:
                self._vault.remove(identifier)
            except Exception:
                pass
            raise ControllerProfileError("controller_profile_create_failed") from exc
        profile = self.get(identifier)
        if profile is None:
            raise ControllerProfileError("controller_profile_create_failed")
        return profile

    def activate(
        self,
        controller_id: str,
        *,
        credential_serial: bytes,
        admission_certificate: bytes,
        grants: tuple[str, ...],
        active_bundle: ControllerSecretBundle,
        now: int | None = None,
    ) -> ControllerProfile:
        if len(credential_serial) != 16 or not (
            1 <= len(admission_certificate) <= _MAX_CERTIFICATE_BYTES
        ):
            raise ControllerProfileError("invalid_controller_admission")
        normalized_grants = normalize_grants(grants)
        if (
            active_bundle.pairing_payload is not None
            or active_bundle.enrollment_request is not None
            or active_bundle.credential_serial != credential_serial
            or active_bundle.admission_certificate != admission_certificate
            or active_bundle.grants != normalized_grants
        ):
            raise ControllerProfileError("invalid_active_controller_bundle")
        changed_at = int(time.time()) if now is None else now
        # The vault commits first. If the process dies before SQLite catches up,
        # reconcile_activation can recover metadata without rolling MLS state back.
        self._vault.store(controller_id, active_bundle.to_cbor())
        try:
            result = self._conn.execute(
                "UPDATE controller_profiles SET credential_serial=?, "
                "admission_certificate=?, grants=?, status='active', updated_at=? "
                "WHERE controller_id=?",
                (
                    credential_serial,
                    admission_certificate,
                    canonical_dumps(list(normalized_grants)),
                    changed_at,
                    controller_id,
                ),
            )
        except sqlite3.Error as exc:
            raise ControllerProfileError("controller_profile_activate_failed") from exc
        if result.rowcount != 1:
            raise ControllerProfileError("controller_profile_not_found")
        profile = self.get(controller_id)
        if profile is None:
            raise ControllerProfileError("controller_profile_activate_failed")
        return profile

    def load_secret(self, controller_id: str) -> ControllerSecretBundle:
        encoded = self._vault.load(controller_id)
        if encoded is None:
            raise ControllerProfileError("controller_secret_not_found")
        bundle = ControllerSecretBundle.from_cbor(encoded)
        profile = self.get(controller_id)
        if profile is None:
            raise ControllerProfileError("controller_profile_not_found")
        if profile.status == "pending" and bundle.credential_serial is not None:
            self._reconcile_activation(controller_id, bundle)
        elif profile.status == "active" and bundle.credential_serial is None:
            raise ControllerProfileError("controller_profile_state_mismatch")
        return bundle

    def store_secret(
        self,
        controller_id: str,
        bundle: ControllerSecretBundle,
    ) -> None:
        if self.get(controller_id) is None:
            raise ControllerProfileError("controller_profile_not_found")
        self._vault.store(controller_id, bundle.to_cbor())

    def clear_expired_pending_application(
        self,
        controller_id: str,
        *,
        now: int,
    ) -> bool:
        bundle = self.load_secret(controller_id)
        pending = bundle.pending_application
        if pending is None or pending.expires_at > now:
            return False
        self.store_secret(
            controller_id,
            replace(bundle, pending_application=None),
        )
        return True

    def get(self, controller_id: str) -> ControllerProfile | None:
        row = self._conn.execute(
            "SELECT * FROM controller_profiles WHERE controller_id=?",
            (controller_id,),
        ).fetchone()
        return self._row(row) if row is not None else None

    def list(self) -> list[ControllerProfile]:
        rows = self._conn.execute(
            "SELECT * FROM controller_profiles ORDER BY updated_at DESC, controller_id"
        ).fetchall()
        return [self._row(row) for row in rows]

    def remove(self, controller_id: str) -> None:
        # Removing the vault first ensures an interrupted forget cannot leave an
        # apparently usable profile whose secret authority still exists.
        self._vault.remove(controller_id)
        try:
            self._conn.execute(
                "DELETE FROM controller_profiles WHERE controller_id=?",
                (controller_id,),
            )
        except sqlite3.Error as exc:
            raise ControllerProfileError("controller_profile_remove_failed") from exc

    def _initialize_version(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(_SCHEMA_VERSION).encode("ascii"),),
            )
            return
        try:
            version = int(bytes(row["value"]).decode("ascii"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ControllerProfileError("invalid_controller_schema_version") from exc
        if version != _SCHEMA_VERSION:
            raise ControllerProfileError("unsupported_controller_schema_version")

    def _reconcile_activation(
        self,
        controller_id: str,
        bundle: ControllerSecretBundle,
    ) -> None:
        if (
            bundle.credential_serial is None
            or bundle.admission_certificate is None
            or not bundle.grants
        ):
            raise ControllerProfileError("controller_profile_state_mismatch")
        try:
            result = self._conn.execute(
                "UPDATE controller_profiles SET credential_serial=?, "
                "admission_certificate=?, grants=?, status='active', updated_at=? "
                "WHERE controller_id=? AND status='pending'",
                (
                    bundle.credential_serial,
                    bundle.admission_certificate,
                    canonical_dumps(list(bundle.grants)),
                    int(time.time()),
                    controller_id,
                ),
            )
        except sqlite3.Error as exc:
            raise ControllerProfileError("controller_profile_reconcile_failed") from exc
        if result.rowcount != 1:
            raise ControllerProfileError("controller_profile_state_mismatch")

    @staticmethod
    def _row(row: sqlite3.Row) -> ControllerProfile:
        grants_value = row["grants"]
        grants = (
            ()
            if grants_value is None
            else normalize_grants(
                canonical_loads(
                    bytes(grants_value),
                    maximum=4096,
                    expected_type=list,
                )
            )
        )
        return ControllerProfile(
            controller_id=str(row["controller_id"]),
            label=str(row["label"]),
            platform=str(row["platform"]),
            relay_origin=normalize_relay_origin(
                str(row["relay_origin"]),
                allow_loopback_http=True,
            ),
            route_id=_fixed_bytes(row["route_id"], PAIRING_FIELD_BYTES),
            machine_public_key=_fixed_bytes(
                row["machine_public_key"],
                PAIRING_FIELD_BYTES,
            ),
            credential_serial=(
                _fixed_bytes(row["credential_serial"], 16)
                if row["credential_serial"] is not None
                else None
            ),
            admission_certificate=(
                bytes(row["admission_certificate"])
                if row["admission_certificate"] is not None
                else None
            ),
            grants=grants,
            status=str(row["status"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )


def _validate_label(value: str) -> str:
    normalized = " ".join(str(value).split())
    if not normalized or len(normalized.encode("utf-8")) > _MAX_LABEL_BYTES:
        raise ControllerProfileError("invalid_controller_label")
    return normalized


def _fixed_bytes(value: object, length: int) -> bytes:
    encoded = bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else b""
    if len(encoded) != length:
        raise ControllerProfileError("invalid_controller_profile")
    return encoded
