"""Owner-only machine identity, device registry, replay journal, and audit store."""

from __future__ import annotations

import base64
import contextlib
import csv
import hashlib
import hmac
import io
import os
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from fabric_constants import get_fabric_home

from .capabilities import methods_for_grants, normalize_grants
from .protocol import (
    MAX_APPLICATION_ENVELOPE_BYTES,
    canonical_dumps,
    canonical_loads,
)

SCHEMA_VERSION = 1
REPLAY_RETENTION_SECONDS = 7 * 24 * 60 * 60
ROUTE_KEY_BYTES = 32
ROUTE_ID_BYTES = 32
CONTROLLER_CREDENTIAL_HASH_BYTES = 32
GROUP_ID_BYTES = 32
RELAY_PUBLIC_KEY_BYTES = 32
CREDENTIAL_SERIAL_BYTES = 16

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_enrollments (
    handle BLOB PRIMARY KEY,
    secret_marker BLOB NOT NULL,
    requested_grants BLOB NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    credential_hash BLOB NOT NULL UNIQUE,
    controller_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    grants BLOB NOT NULL,
    group_id BLOB NOT NULL UNIQUE,
    host_state BLOB NOT NULL,
    relay_public_key BLOB NOT NULL,
    credential_serial BLOB NOT NULL UNIQUE,
    admission_certificate BLOB NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active', 'revoked')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    revoked_at INTEGER,
    final_remove_commit BLOB
);

CREATE TABLE IF NOT EXISTS replay_journal (
    device_id TEXT NOT NULL,
    request_id BLOB NOT NULL,
    claimed_at INTEGER NOT NULL,
    retain_until INTEGER NOT NULL,
    PRIMARY KEY(device_id, request_id),
    FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at INTEGER NOT NULL,
    device_id TEXT,
    credential_fingerprint TEXT NOT NULL,
    request_id TEXT,
    method_class TEXT NOT NULL,
    decision TEXT NOT NULL,
    error_code TEXT,
    result_hash TEXT
);

CREATE TABLE IF NOT EXISTS response_outbox (
    credential_serial BLOB NOT NULL,
    source_sequence INTEGER NOT NULL,
    source_message_id BLOB NOT NULL,
    response_message_id BLOB NOT NULL,
    expires_at INTEGER NOT NULL,
    response_record BLOB NOT NULL,
    response_digest BLOB NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(credential_serial, source_sequence)
);

CREATE TABLE IF NOT EXISTS relay_revocation_receipts (
    credential_serial BLOB NOT NULL,
    relay_origin TEXT NOT NULL,
    delivered_at INTEGER NOT NULL,
    PRIMARY KEY(credential_serial, relay_origin)
);

CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);
CREATE INDEX IF NOT EXISTS idx_replay_retention ON replay_journal(retain_until);
CREATE INDEX IF NOT EXISTS idx_audit_recorded_at ON audit_records(recorded_at);
CREATE INDEX IF NOT EXISTS idx_response_outbox_created
ON response_outbox(created_at, credential_serial, source_sequence);
"""


class LinkStorageError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LinkReplayError(LinkStorageError):
    pass


@dataclass(frozen=True)
class MachineIdentity:
    route_id: bytes
    public_key: bytes
    fingerprint: str
    _private_key: Ed25519PrivateKey = field(repr=False, compare=False)

    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)

    def verify(self, signature: bytes, message: bytes) -> None:
        Ed25519PublicKey.from_public_bytes(self.public_key).verify(signature, message)


@dataclass(frozen=True)
class LinkDevice:
    device_id: str
    credential_hash: bytes
    controller_name: str
    platform: str
    grants: tuple[str, ...]
    group_id: bytes
    host_state: bytes = field(repr=False)
    relay_public_key: bytes
    credential_serial: bytes
    admission_certificate: bytes = field(repr=False)
    status: str
    created_at: int
    updated_at: int
    revoked_at: int | None
    final_remove_commit: bytes | None

    @property
    def allowed_methods(self) -> frozenset[str]:
        return methods_for_grants(self.grants)


def link_home() -> Path:
    return get_fabric_home() / "link"


def link_db_path() -> Path:
    return link_home() / "state.sqlite3"


def route_key_path() -> Path:
    return link_home() / "route.key"


def credential_fingerprint(value: bytes) -> str:
    digest = hashlib.sha256(value).digest()[:10]
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=")
    return "-".join(encoded[index : index + 4] for index in range(0, len(encoded), 4))


def _require_regular_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise LinkStorageError("storage_path_unavailable") from exc
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise LinkStorageError("storage_path_not_regular")


def _windows_current_sid() -> str:
    whoami = shutil.which("whoami")
    if whoami is None:
        raise LinkStorageError("windows_acl_tool_unavailable")
    try:
        completed = subprocess.run(
            [whoami, "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        row = next(csv.reader(io.StringIO(completed.stdout)))
    except (OSError, subprocess.SubprocessError, StopIteration, csv.Error) as exc:
        raise LinkStorageError("windows_sid_unavailable") from exc
    if len(row) < 2 or not row[1].startswith("S-1-"):
        raise LinkStorageError("windows_sid_unavailable")
    return row[1]


def _harden_windows_acl(path: Path, *, directory: bool) -> None:
    icacls = shutil.which("icacls")
    if icacls is None:
        raise LinkStorageError("windows_acl_tool_unavailable")
    sid = _windows_current_sid()
    permission = f"*{sid}:{'(OI)(CI)' if directory else ''}F"
    try:
        subprocess.run(
            [icacls, str(path), "/inheritance:r", "/grant:r", permission],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LinkStorageError("windows_acl_hardening_failed") from exc


def _harden_private_path(path: Path, *, directory: bool) -> None:
    if sys.platform == "win32":
        _harden_windows_acl(path, directory=directory)
        return
    try:
        os.chmod(path, 0o700 if directory else 0o600)
    except OSError as exc:
        raise LinkStorageError("storage_permissions_failed") from exc
    mode = stat.S_IMODE(path.stat().st_mode)
    expected = 0o700 if directory else 0o600
    if mode != expected:
        raise LinkStorageError("storage_permissions_failed")


def _ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError as exc:
        raise LinkStorageError("storage_directory_failed") from exc
    if path.is_symlink() or not path.is_dir():
        raise LinkStorageError("storage_directory_unsafe")
    _harden_private_path(path, directory=True)


def _secure_create_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise
    except OSError as exc:
        raise LinkStorageError("storage_file_create_failed") from exc
    try:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise LinkStorageError("storage_file_write_failed")
            view = view[written:]
        os.fsync(fd)
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    finally:
        os.close(fd)
    _harden_private_path(path, directory=False)


def _open_or_create_db_file(path: Path) -> None:
    if path.exists() or path.is_symlink():
        _require_regular_file(path)
    else:
        _secure_create_file(path, b"")
    _harden_private_path(path, directory=False)


class LinkDeviceStore:
    """Single-process owner for one profile's Fabric Link state."""

    def __init__(self, db_path: Path | None = None, key_path: Path | None = None) -> None:
        self.path = Path(db_path) if db_path is not None else link_db_path()
        self.key_path = Path(key_path) if key_path is not None else route_key_path()
        if self.path.parent != self.key_path.parent:
            raise LinkStorageError("storage_paths_mismatch")
        _ensure_private_directory(self.path.parent)
        _open_or_create_db_file(self.path)
        try:
            self._conn = sqlite3.connect(
                str(self.path),
                isolation_level=None,
                timeout=5,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA trusted_schema=OFF")
            self._conn.execute("PRAGMA secure_delete=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._initialize_schema_version()
        except sqlite3.Error as exc:
            raise LinkStorageError("database_open_failed") from exc
        _harden_private_path(self.path, directory=False)

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "LinkDeviceStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextlib.contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        else:
            self._conn.execute("COMMIT")

    def _initialize_schema_version(self) -> None:
        raw = self._conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        if raw is None:
            with self._write():
                self._conn.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION).encode("ascii"),),
                )
            return
        try:
            version = int(bytes(raw["value"]).decode("ascii"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise LinkStorageError("invalid_schema_version") from exc
        if version != SCHEMA_VERSION:
            raise LinkStorageError("unsupported_schema_version")

    def machine_identity(self) -> MachineIdentity:
        private_key = self._load_or_create_private_key()
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        route_row = self._conn.execute(
            "SELECT value FROM metadata WHERE key='route_id'"
        ).fetchone()
        if route_row is None:
            route_id = secrets.token_bytes(ROUTE_ID_BYTES)
            with self._write():
                self._conn.execute(
                    "INSERT OR IGNORE INTO metadata(key, value) VALUES('route_id', ?)",
                    (route_id,),
                )
                stored = self._conn.execute(
                    "SELECT value FROM metadata WHERE key='route_id'"
                ).fetchone()
            route_id = bytes(stored["value"])
        else:
            route_id = bytes(route_row["value"])
        if len(route_id) != ROUTE_ID_BYTES:
            raise LinkStorageError("invalid_route_id")
        return MachineIdentity(
            route_id=route_id,
            public_key=public_key,
            fingerprint=credential_fingerprint(public_key),
            _private_key=private_key,
        )

    def _load_or_create_private_key(self) -> Ed25519PrivateKey:
        if not self.key_path.exists() and not self.key_path.is_symlink():
            private_key = Ed25519PrivateKey.generate()
            encoded = private_key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            try:
                _secure_create_file(self.key_path, encoded)
            except FileExistsError:
                pass
        _require_regular_file(self.key_path)
        _harden_private_path(self.key_path, directory=False)
        try:
            encoded = self.key_path.read_bytes()
            if len(encoded) != ROUTE_KEY_BYTES:
                raise LinkStorageError("invalid_route_key")
            return Ed25519PrivateKey.from_private_bytes(encoded)
        except OSError as exc:
            raise LinkStorageError("route_key_unavailable") from exc
        except ValueError as exc:
            raise LinkStorageError("invalid_route_key") from exc

    def register_pending(
        self,
        *,
        handle: bytes,
        secret_marker: bytes,
        requested_grants: Sequence[str],
        created_at: int,
        expires_at: int,
    ) -> None:
        if len(handle) != 32 or len(secret_marker) != 32 or expires_at <= created_at:
            raise LinkStorageError("invalid_pending_enrollment")
        grants = canonical_dumps(list(normalize_grants(requested_grants)))
        with self._write():
            self._conn.execute(
                "DELETE FROM pending_enrollments WHERE expires_at <= ?",
                (created_at,),
            )
            self._conn.execute(
                "INSERT INTO pending_enrollments("
                "handle, secret_marker, requested_grants, created_at, expires_at"
                ") VALUES(?, ?, ?, ?, ?)",
                (handle, secret_marker, grants, created_at, expires_at),
            )

    def cancel_pending(self, handle: bytes) -> None:
        with self._write():
            self._conn.execute(
                "DELETE FROM pending_enrollments WHERE handle=?",
                (handle,),
            )

    def consume_pending_and_add_device(
        self,
        *,
        handle: bytes,
        secret_marker: bytes,
        device: LinkDevice,
        now: int,
    ) -> None:
        self._validate_device(device)
        grants = canonical_dumps(list(normalize_grants(device.grants)))
        with self._write():
            deleted = self._conn.execute(
                "DELETE FROM pending_enrollments "
                "WHERE handle=? AND secret_marker=? AND expires_at>?",
                (handle, secret_marker, now),
            )
            if deleted.rowcount != 1:
                raise LinkStorageError("pending_enrollment_expired")
            self._conn.execute(
                "INSERT INTO devices("
                "device_id, credential_hash, controller_name, platform, grants, "
                "group_id, host_state, relay_public_key, credential_serial, "
                "admission_certificate, status, created_at, updated_at, revoked_at, "
                "final_remove_commit"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    device.device_id,
                    device.credential_hash,
                    device.controller_name,
                    device.platform,
                    grants,
                    device.group_id,
                    device.host_state,
                    device.relay_public_key,
                    device.credential_serial,
                    device.admission_certificate,
                    device.status,
                    device.created_at,
                    device.updated_at,
                    device.revoked_at,
                    device.final_remove_commit,
                ),
            )

    def _validate_device(self, device: LinkDevice) -> None:
        if (
            not device.device_id.startswith("device_")
            or len(device.credential_hash) != CONTROLLER_CREDENTIAL_HASH_BYTES
            or not device.controller_name
            or len(device.controller_name.encode("utf-8")) > 96
            or not device.platform
            or len(device.group_id) != GROUP_ID_BYTES
            or not device.host_state
            or len(device.relay_public_key) != RELAY_PUBLIC_KEY_BYTES
            or len(device.credential_serial) != CREDENTIAL_SERIAL_BYTES
            or not device.admission_certificate
            or device.status not in {"active", "revoked"}
        ):
            raise LinkStorageError("invalid_device")
        normalize_grants(device.grants)

    @staticmethod
    def _row_to_device(row: sqlite3.Row) -> LinkDevice:
        grants_raw = canonical_loads(
            bytes(row["grants"]),
            maximum=4096,
            expected_type=list,
        )
        grants = normalize_grants(grants_raw)
        return LinkDevice(
            device_id=str(row["device_id"]),
            credential_hash=bytes(row["credential_hash"]),
            controller_name=str(row["controller_name"]),
            platform=str(row["platform"]),
            grants=grants,
            group_id=bytes(row["group_id"]),
            host_state=bytes(row["host_state"]),
            relay_public_key=bytes(row["relay_public_key"]),
            credential_serial=bytes(row["credential_serial"]),
            admission_certificate=bytes(row["admission_certificate"]),
            status=str(row["status"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            revoked_at=(
                int(row["revoked_at"]) if row["revoked_at"] is not None else None
            ),
            final_remove_commit=(
                bytes(row["final_remove_commit"])
                if row["final_remove_commit"] is not None
                else None
            ),
        )

    def get_device(self, device_id: str) -> LinkDevice | None:
        row = self._conn.execute(
            "SELECT * FROM devices WHERE device_id=?",
            (device_id,),
        ).fetchone()
        return self._row_to_device(row) if row is not None else None

    def get_device_by_credential(self, credential_hash: bytes) -> LinkDevice | None:
        row = self._conn.execute(
            "SELECT * FROM devices WHERE credential_hash=?",
            (credential_hash,),
        ).fetchone()
        return self._row_to_device(row) if row is not None else None

    def get_device_by_credential_serial(
        self, credential_serial: bytes
    ) -> LinkDevice | None:
        if len(credential_serial) != CREDENTIAL_SERIAL_BYTES:
            return None
        row = self._conn.execute(
            "SELECT * FROM devices WHERE credential_serial=?",
            (credential_serial,),
        ).fetchone()
        return self._row_to_device(row) if row is not None else None

    def require_active(self, credential_hash: bytes) -> LinkDevice:
        if len(credential_hash) != CONTROLLER_CREDENTIAL_HASH_BYTES:
            raise LinkStorageError("device_not_active")
        device = self.get_device_by_credential(credential_hash)
        if device is None or device.status != "active":
            raise LinkStorageError("device_not_active")
        return device

    def require_active_by_credential_serial(self, credential_serial: bytes) -> LinkDevice:
        device = self.get_device_by_credential_serial(credential_serial)
        if device is None or device.status != "active":
            raise LinkStorageError("device_not_active")
        return device

    def list_devices(self) -> list[LinkDevice]:
        rows = self._conn.execute(
            "SELECT * FROM devices ORDER BY created_at, device_id"
        ).fetchall()
        return [self._row_to_device(row) for row in rows]

    def set_grants(
        self,
        device_id: str,
        grants: Sequence[str],
        *,
        now: int | None = None,
    ) -> LinkDevice:
        encoded = canonical_dumps(list(normalize_grants(grants)))
        changed_at = int(time.time()) if now is None else now
        with self._write():
            result = self._conn.execute(
                "UPDATE devices SET grants=?, updated_at=? "
                "WHERE device_id=? AND status='active'",
                (encoded, changed_at, device_id),
            )
            if result.rowcount != 1:
                raise LinkStorageError("device_not_active")
        device = self.get_device(device_id)
        if device is None:
            raise LinkStorageError("device_not_found")
        return device

    def update_active_host_state(
        self,
        device_id: str,
        host_state: bytes,
        *,
        now: int | None = None,
    ) -> LinkDevice:
        """Persist an evolved host MLS state without reviving a revoked device."""
        if not isinstance(host_state, bytes) or not host_state:
            raise LinkStorageError("invalid_host_state")
        changed_at = int(time.time()) if now is None else now
        with self._write():
            result = self._conn.execute(
                "UPDATE devices SET host_state=?, updated_at=? "
                "WHERE device_id=? AND status='active'",
                (host_state, changed_at, device_id),
            )
            if result.rowcount != 1:
                raise LinkStorageError("device_not_active")
        device = self.get_device(device_id)
        if device is None:
            raise LinkStorageError("device_not_found")
        return device

    def commit_application_response(
        self,
        *,
        device: LinkDevice,
        expected_host_state: bytes,
        evolved_host_state: bytes,
        request_id: bytes,
        request_expires_at: int,
        method_class: str,
        decision: str,
        error_code: str | None,
        response_record: bytes,
        now: int,
        source_sequence: int | None = None,
        source_message_id: bytes | None = None,
        response_expires_at: int | None = None,
    ) -> None:
        """Atomically advance MLS, claim replay, audit, and optionally queue reply."""
        if (
            not expected_host_state
            or not evolved_host_state
            or len(request_id) != 16
            or decision not in {"allow", "deny"}
            or not response_record
            or len(response_record) > MAX_APPLICATION_ENVELOPE_BYTES
        ):
            raise LinkStorageError("invalid_application_commit")
        outbox_values = (
            source_sequence,
            source_message_id,
            response_expires_at,
        )
        if any(value is not None for value in outbox_values):
            if (
                isinstance(source_sequence, bool)
                or not isinstance(source_sequence, int)
                or source_sequence < 1
                or not isinstance(source_message_id, bytes)
                or len(source_message_id) != 16
                or isinstance(response_expires_at, bool)
                or not isinstance(response_expires_at, int)
                or response_expires_at <= now
            ):
                raise LinkStorageError("invalid_application_outbox")
        response_digest = hashlib.sha256(response_record).digest()
        with self._write():
            row = self._conn.execute(
                "SELECT status, credential_serial, host_state FROM devices "
                "WHERE device_id=?",
                (device.device_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "active"
                or not hmac.compare_digest(
                    bytes(row["credential_serial"]),
                    device.credential_serial,
                )
                or not hmac.compare_digest(
                    bytes(row["host_state"]),
                    expected_host_state,
                )
            ):
                raise LinkStorageError("application_state_conflict")
            self._claim_request_id_in_transaction(
                device_id=device.device_id,
                request_id=request_id,
                request_expires_at=request_expires_at,
                now=now,
            )
            updated = self._conn.execute(
                "UPDATE devices SET host_state=?, updated_at=? "
                "WHERE device_id=? AND status='active' AND host_state=?",
                (
                    evolved_host_state,
                    now,
                    device.device_id,
                    expected_host_state,
                ),
            )
            if updated.rowcount != 1:
                raise LinkStorageError("application_state_conflict")
            self._record_audit_in_transaction(
                recorded_at=now,
                device_id=device.device_id,
                credential_hash=device.credential_hash,
                request_id=request_id,
                method_class=method_class,
                decision=decision,
                error_code=error_code,
                result_hash=response_digest,
            )
            if source_sequence is not None:
                try:
                    self._conn.execute(
                        "INSERT INTO response_outbox("
                        "credential_serial, source_sequence, source_message_id, "
                        "response_message_id, expires_at, response_record, "
                        "response_digest, created_at"
                        ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            device.credential_serial,
                            source_sequence,
                            source_message_id,
                            source_message_id,
                            response_expires_at,
                            response_record,
                            response_digest,
                            now,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise LinkStorageError("application_outbox_conflict") from exc

    def response_outbox_get(
        self,
        *,
        credential_serial: bytes,
        source_sequence: int,
    ) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT credential_serial, source_sequence, source_message_id, "
            "response_message_id, expires_at, response_record "
            "FROM response_outbox WHERE credential_serial=? AND source_sequence=?",
            (credential_serial, source_sequence),
        ).fetchone()
        return self._response_outbox_row(row) if row is not None else None

    def response_outbox_pending(self) -> tuple[dict[str, object], ...]:
        rows = self._conn.execute(
            "SELECT credential_serial, source_sequence, source_message_id, "
            "response_message_id, expires_at, response_record "
            "FROM response_outbox "
            "ORDER BY created_at, credential_serial, source_sequence"
        ).fetchall()
        return tuple(self._response_outbox_row(row) for row in rows)

    def response_outbox_complete(
        self,
        *,
        credential_serial: bytes,
        source_sequence: int,
    ) -> None:
        with self._write():
            self._conn.execute(
                "DELETE FROM response_outbox "
                "WHERE credential_serial=? AND source_sequence=?",
                (credential_serial, source_sequence),
            )

    @staticmethod
    def _response_outbox_row(row: sqlite3.Row) -> dict[str, object]:
        return {
            "credential_serial": bytes(row["credential_serial"]),
            "source_sequence": int(row["source_sequence"]),
            "source_message_id": bytes(row["source_message_id"]),
            "response_message_id": bytes(row["response_message_id"]),
            "expires_at": int(row["expires_at"]),
            "response_record": bytes(row["response_record"]),
        }

    def deny_device(self, device_id: str, *, now: int | None = None) -> LinkDevice:
        """Make local denial authoritative before MLS or relay cleanup."""
        changed_at = int(time.time()) if now is None else now
        with self._write():
            result = self._conn.execute(
                "UPDATE devices SET status='revoked', revoked_at=?, updated_at=? "
                "WHERE device_id=? AND status='active'",
                (changed_at, changed_at, device_id),
            )
            if result.rowcount != 1:
                raise LinkStorageError("device_not_active")
            row = self._conn.execute(
                "SELECT credential_serial FROM devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
            if row is None:
                raise LinkStorageError("device_not_found")
            # A locally denied controller must not receive a response that was
            # encrypted before the denial but had not yet reached the relay.
            self._conn.execute(
                "DELETE FROM response_outbox WHERE credential_serial=?",
                (bytes(row["credential_serial"]),),
            )
        device = self.get_device(device_id)
        if device is None:
            raise LinkStorageError("device_not_found")
        return device

    def relay_revocation_delivered(
        self,
        *,
        credential_serial: bytes,
        relay_origin: str,
    ) -> bool:
        if len(credential_serial) != CREDENTIAL_SERIAL_BYTES or not relay_origin:
            raise LinkStorageError("invalid_relay_revocation_receipt")
        row = self._conn.execute(
            "SELECT 1 FROM relay_revocation_receipts "
            "WHERE credential_serial=? AND relay_origin=?",
            (credential_serial, relay_origin),
        ).fetchone()
        return row is not None

    def mark_relay_revocation_delivered(
        self,
        *,
        credential_serial: bytes,
        relay_origin: str,
        now: int | None = None,
    ) -> None:
        if len(credential_serial) != CREDENTIAL_SERIAL_BYTES or not relay_origin:
            raise LinkStorageError("invalid_relay_revocation_receipt")
        delivered_at = int(time.time()) if now is None else now
        with self._write():
            self._conn.execute(
                "INSERT INTO relay_revocation_receipts("
                "credential_serial, relay_origin, delivered_at"
                ") VALUES(?, ?, ?) "
                "ON CONFLICT(credential_serial, relay_origin) "
                "DO UPDATE SET delivered_at=excluded.delivered_at",
                (credential_serial, relay_origin, delivered_at),
            )

    def finish_revocation(
        self,
        device_id: str,
        *,
        host_state: bytes,
        remove_commit: bytes,
        now: int | None = None,
    ) -> None:
        if not host_state or not remove_commit:
            raise LinkStorageError("invalid_revocation_state")
        changed_at = int(time.time()) if now is None else now
        with self._write():
            result = self._conn.execute(
                "UPDATE devices SET host_state=?, final_remove_commit=?, updated_at=? "
                "WHERE device_id=? AND status='revoked'",
                (host_state, remove_commit, changed_at, device_id),
            )
            if result.rowcount != 1:
                raise LinkStorageError("device_not_revoked")

    def claim_request_id(
        self,
        *,
        device_id: str,
        request_id: bytes,
        request_expires_at: int,
        now: int,
    ) -> None:
        if len(request_id) != 16:
            raise LinkReplayError("invalid_request_id")
        with self._write():
            self._claim_request_id_in_transaction(
                device_id=device_id,
                request_id=request_id,
                request_expires_at=request_expires_at,
                now=now,
            )

    def request_id_claimed(self, *, device_id: str, request_id: bytes) -> bool:
        if len(request_id) != 16:
            raise LinkReplayError("invalid_request_id")
        row = self._conn.execute(
            "SELECT 1 FROM replay_journal WHERE device_id=? AND request_id=?",
            (device_id, request_id),
        ).fetchone()
        return row is not None

    def _claim_request_id_in_transaction(
        self,
        *,
        device_id: str,
        request_id: bytes,
        request_expires_at: int,
        now: int,
    ) -> None:
        retain_until = max(request_expires_at, now + REPLAY_RETENTION_SECONDS)
        self._conn.execute(
            "DELETE FROM replay_journal WHERE retain_until < ?",
            (now,),
        )
        try:
            self._conn.execute(
                "INSERT INTO replay_journal("
                "device_id, request_id, claimed_at, retain_until"
                ") VALUES(?, ?, ?, ?)",
                (device_id, request_id, now, retain_until),
            )
        except sqlite3.IntegrityError as exc:
            raise LinkReplayError("request_replayed") from exc

    def record_audit(
        self,
        *,
        recorded_at: int,
        device_id: str | None,
        credential_hash: bytes,
        request_id: bytes | None,
        method_class: str,
        decision: str,
        error_code: str | None = None,
        result_hash: bytes | None = None,
    ) -> None:
        with self._write():
            self._record_audit_in_transaction(
                recorded_at=recorded_at,
                device_id=device_id,
                credential_hash=credential_hash,
                request_id=request_id,
                method_class=method_class,
                decision=decision,
                error_code=error_code,
                result_hash=result_hash,
            )

    def _record_audit_in_transaction(
        self,
        *,
        recorded_at: int,
        device_id: str | None,
        credential_hash: bytes,
        request_id: bytes | None,
        method_class: str,
        decision: str,
        error_code: str | None,
        result_hash: bytes | None,
    ) -> None:
        fingerprint = credential_fingerprint(credential_hash)
        request_text = (
            base64.urlsafe_b64encode(request_id).rstrip(b"=").decode("ascii")
            if request_id is not None
            else None
        )
        result_text = result_hash.hex() if result_hash is not None else None
        self._conn.execute(
            "INSERT INTO audit_records("
            "recorded_at, device_id, credential_fingerprint, request_id, "
            "method_class, decision, error_code, result_hash"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                recorded_at,
                device_id,
                fingerprint,
                request_text,
                method_class,
                decision,
                error_code,
                result_text,
            ),
        )

    def audit_records(self) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT recorded_at, device_id, credential_fingerprint, request_id, "
            "method_class, decision, error_code, result_hash "
            "FROM audit_records ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]
