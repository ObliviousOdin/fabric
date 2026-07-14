"""Crash-safe local trust state for signed skill distribution.

``agent.skill_distribution`` is intentionally pure: it verifies bytes but does
not own files, clocks, or locks.  This module is the narrow persistence adapter
used by install surfaces.  It stores the pinned root envelope and every
rollback/equivocation counter in one atomic document so a crash cannot advance
one without the other.

The store never fetches metadata and never activates a skill.  Callers still
have to compare a freshly measured candidate tree with the returned
``VerifiedRelease.tree_sha256`` before publishing it.  Installed-release HMAC
proofs use a separate 32-byte, mode-0600 key; the key is never embedded in the
state document or proof.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import stat
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from agent.skill_distribution import (
    OfflineGracePolicy,
    SkillDistributionError,
    TrustedRoot,
    TrustedVersions,
    VerifiedRelease,
    bind_verified_release_to_trust_state,
    canonical_json_bytes,
    issue_installed_release_proof,
    load_trusted_root,
    rotate_trusted_root,
    verify_release,
)
from fabric_constants import get_fabric_home


_SCHEMA_VERSION = 1
_MAX_STATE_BYTES = 4 * 1024 * 1024
_RECEIPT_KEY_BYTES = 32
_PROCESS_LOCK = threading.RLock()


class SkillDistributionStateError(RuntimeError):
    """Local state could not be read or durably advanced."""


@dataclass(frozen=True)
class DistributionTrustState:
    """Verifier-ready snapshot loaded under the store lock."""

    root: TrustedRoot
    trusted_versions: TrustedVersions
    root_envelope: bytes


def _default_state_dir() -> Path:
    return get_fabric_home() / "skills" / ".hub" / "trust"


def _versions_to_dict(value: TrustedVersions) -> dict[str, Any]:
    return {
        field: getattr(value, field)
        for role in ("root", "timestamp", "snapshot", "targets", "revocations")
        for field in (role, f"{role}_sha256")
    }


def _versions_from_dict(value: object) -> TrustedVersions:
    roles = ("root", "timestamp", "snapshot", "targets", "revocations")
    expected = {field for role in roles for field in (role, f"{role}_sha256")}
    if type(value) is not dict or set(value) != expected:
        raise SkillDistributionStateError("signed-skill rollback state is invalid")
    try:
        return TrustedVersions(**value)
    except (TypeError, SkillDistributionError) as exc:
        raise SkillDistributionStateError(
            "signed-skill rollback state is invalid"
        ) from exc


def _bounded_root_envelope(value: bytes | str) -> bytes:
    if isinstance(value, str):
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise SkillDistributionStateError("root metadata is not UTF-8") from exc
    elif isinstance(value, bytes):
        encoded = value
    else:
        raise SkillDistributionStateError("root metadata must be bytes or text")
    if not encoded or len(encoded) > _MAX_STATE_BYTES:
        raise SkillDistributionStateError("root metadata is empty or too large")
    return encoded


class SkillDistributionStateStore:
    """Profile-local atomic trust, rollback, and offline-proof state."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (
            Path(directory) if directory is not None else _default_state_dir()
        )
        self.state_path = self.directory / "state.json"
        self.key_path = self.directory / "receipt.key"
        self.lock_path = self.directory / "state.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize bootstrap, rotation, verification, and proof issuance."""

        with _PROCESS_LOCK:
            self._ensure_directory()
            descriptor = self._open_lock_file()
            try:
                try:
                    import fcntl
                except ImportError:  # pragma: no cover - native Windows
                    fcntl = None
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                if "fcntl" in locals() and fcntl is not None:
                    with contextlib.suppress(OSError):
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def exists(self) -> bool:
        with self.locked():
            descriptor = self._safe_regular_file(self.state_path, allow_missing=True)
            if descriptor is None:
                return False
            os.close(descriptor)
            return True

    def bootstrap(
        self,
        root_metadata: bytes | str,
        *,
        trusted_sha256: str,
        now: datetime,
    ) -> DistributionTrustState:
        """Create the first trust state from an out-of-band SHA-256 pin."""

        raw = _bounded_root_envelope(root_metadata)
        with self.locked():
            existing = self._safe_regular_file(self.state_path, allow_missing=True)
            if existing is not None:
                os.close(existing)
                raise SkillDistributionStateError(
                    "signed-skill trust is already initialized"
                )
            root = load_trusted_root(
                raw,
                trusted_sha256=trusted_sha256,
                minimum_version=0,
                now=now,
            )
            versions = TrustedVersions(
                root=root.version,
                root_sha256=root.canonical_sha256,
            )
            self._save_state(raw, versions)
            return DistributionTrustState(root, versions, raw)

    def load(self, *, now: datetime) -> DistributionTrustState:
        """Load and authenticate the locally pinned root and rollback state."""

        with self.locked():
            return self._load_locked(now=now)

    def rotate(
        self,
        root_metadata: bytes | str,
        *,
        now: datetime,
    ) -> DistributionTrustState:
        """Verify one consecutive root rotation and atomically persist its pair."""

        raw = _bounded_root_envelope(root_metadata)
        with self.locked():
            current = self._load_locked(now=now)
            rotated = rotate_trusted_root(
                current.root,
                raw,
                now=now,
                prior_versions=current.trusted_versions,
            )
            self._save_state(raw, rotated.trusted_versions)
            return DistributionTrustState(
                rotated.root,
                rotated.trusted_versions,
                raw,
            )

    def verify_and_advance(
        self,
        *,
        timestamp: bytes | str,
        snapshot: bytes | str,
        targets: bytes | str,
        revocations: bytes | str,
        name: str,
        version: str,
        now: datetime,
        installed_proof: bytes | str | None = None,
        installed_tree_sha256: str | None = None,
        offline_grace: OfflineGracePolicy | None = None,
    ) -> VerifiedRelease:
        """Verify a release and durably advance rollback state before returning.

        A successful return is safe for a caller to use as an install
        precondition.  If the atomic state write fails, no release is returned.
        """

        with self.locked():
            current = self._load_locked(now=now)
            receipt_key: bytes | None = None
            if installed_proof is not None or installed_tree_sha256 is not None:
                if installed_proof is None or installed_tree_sha256 is None:
                    raise SkillDistributionStateError(
                        "installed proof and tree digest must be supplied together"
                    )
                receipt_key = self._load_receipt_key(create=False)
            release = verify_release(
                root=current.root,
                timestamp=timestamp,
                snapshot=snapshot,
                targets=targets,
                revocations=revocations,
                name=name,
                version=version,
                now=now,
                prior_versions=current.trusted_versions,
                installed_proof=installed_proof,
                receipt_key=receipt_key,
                installed_tree_sha256=installed_tree_sha256,
                offline_grace=offline_grace,
            )
            self._save_state(current.root_envelope, release.trusted_versions)
            return release

    def issue_installed_proof(
        self,
        release: VerifiedRelease,
        *,
        installed_tree_sha256: str,
        now: datetime,
    ) -> bytes:
        """Authenticate a release accepted by this exact persisted trust state."""

        with self.locked():
            current = self._load_locked(now=now)
            try:
                bind_verified_release_to_trust_state(
                    release,
                    trusted_versions=current.trusted_versions,
                )
            except SkillDistributionError as exc:
                raise SkillDistributionStateError(
                    "verified release does not match the current signed-skill trust state"
                ) from exc
            key = self._load_receipt_key(create=True)
            return issue_installed_release_proof(
                release,
                receipt_key=key,
                installed_tree_sha256=installed_tree_sha256,
            )

    def _load_locked(self, *, now: datetime) -> DistributionTrustState:
        raw = self._read_state_document()
        if set(raw) != {"schema_version", "root_envelope_b64", "trusted_versions"}:
            raise SkillDistributionStateError("signed-skill trust state is invalid")
        if raw.get("schema_version") != _SCHEMA_VERSION:
            raise SkillDistributionStateError(
                "signed-skill trust state schema is unsupported"
            )
        encoded = raw.get("root_envelope_b64")
        if not isinstance(encoded, str) or len(encoded) > _MAX_STATE_BYTES * 2:
            raise SkillDistributionStateError("pinned root envelope is invalid")
        try:
            envelope = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise SkillDistributionStateError(
                "pinned root envelope is invalid"
            ) from exc
        if base64.b64encode(envelope).decode("ascii") != encoded:
            raise SkillDistributionStateError("pinned root envelope is not canonical")
        versions = _versions_from_dict(raw.get("trusted_versions"))
        if versions.root < 1 or versions.root_sha256 is None:
            raise SkillDistributionStateError("pinned root rollback state is missing")
        root = load_trusted_root(
            envelope,
            trusted_sha256=versions.root_sha256,
            minimum_version=versions.root,
            now=now,
        )
        if root.version != versions.root:
            raise SkillDistributionStateError("pinned root and rollback state disagree")
        return DistributionTrustState(root, versions, envelope)

    def _save_state(self, root_envelope: bytes, versions: TrustedVersions) -> None:
        document = {
            "schema_version": _SCHEMA_VERSION,
            "root_envelope_b64": base64.b64encode(root_envelope).decode("ascii"),
            "trusted_versions": _versions_to_dict(versions),
        }
        payload = canonical_json_bytes(document)
        if len(payload) > _MAX_STATE_BYTES:
            raise SkillDistributionStateError("signed-skill trust state is too large")
        self._atomic_write(self.state_path, payload, mode=0o600)

    def _read_state_document(self) -> dict[str, Any]:
        descriptor = self._safe_regular_file(self.state_path, allow_missing=False)
        assert descriptor is not None
        try:
            inspected = os.fstat(descriptor)
            if inspected.st_size > _MAX_STATE_BYTES:
                raise SkillDistributionStateError(
                    "signed-skill trust state is too large"
                )
            chunks: list[bytes] = []
            remaining = _MAX_STATE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > _MAX_STATE_BYTES:
                raise SkillDistributionStateError(
                    "signed-skill trust state is too large"
                )
        finally:
            os.close(descriptor)
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SkillDistributionStateError(
                "signed-skill trust state is unreadable"
            ) from exc
        if type(value) is not dict or canonical_json_bytes(value) != payload:
            raise SkillDistributionStateError(
                "signed-skill trust state is not canonical"
            )
        return value

    def _load_receipt_key(self, *, create: bool) -> bytes:
        descriptor = self._safe_regular_file(self.key_path, allow_missing=True)
        if descriptor is None:
            if not create:
                raise SkillDistributionStateError(
                    "installed-release proof key is unavailable"
                )
            key = os.urandom(_RECEIPT_KEY_BYTES)
            try:
                self._atomic_write(self.key_path, key, mode=0o600, replace=False)
            except FileExistsError:
                pass
            descriptor = self._safe_regular_file(self.key_path, allow_missing=False)
            assert descriptor is not None
        try:
            key = os.read(descriptor, _RECEIPT_KEY_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(key) != _RECEIPT_KEY_BYTES:
            raise SkillDistributionStateError("installed-release proof key is invalid")
        return key

    def _ensure_directory(self) -> None:
        missing: list[Path] = []
        current = self.directory
        while not current.exists():
            missing.append(current)
            if current == current.parent:
                break
            current = current.parent
        if current.exists() and (current.is_symlink() or not current.is_dir()):
            raise SkillDistributionStateError("trust state parent is unsafe")
        self.directory.mkdir(parents=True, exist_ok=True)
        for created in reversed(missing):
            with contextlib.suppress(OSError):
                os.chmod(created, 0o700)
            self._fsync_dir(created.parent)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise SkillDistributionStateError("trust state directory is unsafe")

    def _open_lock_file(self) -> int:
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(self.lock_path, flags, 0o600)
        inspected = os.fstat(descriptor)
        if not stat.S_ISREG(inspected.st_mode) or inspected.st_nlink != 1:
            os.close(descriptor)
            raise SkillDistributionStateError("trust state lock is unsafe")
        with contextlib.suppress(OSError):
            os.fchmod(descriptor, 0o600)
        return descriptor

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        if os.name == "nt" or not path.exists():
            return
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _safe_regular_file(path: Path, *, allow_missing: bool) -> int | None:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            before = path.lstat()
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            if allow_missing:
                return None
            raise SkillDistributionStateError(
                f"required trust state is missing: {path.name}"
            ) from None
        except OSError as exc:
            raise SkillDistributionStateError(
                f"trust state could not be opened: {path.name}"
            ) from exc
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or before.st_nlink != 1
            or opened.st_nlink != 1
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or (os.name != "nt" and (stat.S_IMODE(opened.st_mode) & 0o077) != 0)
        ):
            os.close(descriptor)
            raise SkillDistributionStateError(f"trust state is unsafe: {path.name}")
        return descriptor

    def _atomic_write(
        self,
        path: Path,
        payload: bytes,
        *,
        mode: int,
        replace: bool = True,
    ) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(self.directory), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            os.fchmod(descriptor, mode)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if not replace and (path.exists() or path.is_symlink()):
                raise FileExistsError(path)
            if replace and path.exists():
                existing = self._safe_regular_file(path, allow_missing=False)
                assert existing is not None
                os.close(existing)
            os.replace(temporary_name, path)
            self._fsync_dir(self.directory)
            temporary_name = ""
            with contextlib.suppress(OSError):
                os.chmod(path, mode)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_name:
                with contextlib.suppress(OSError):
                    os.unlink(temporary_name)


__all__ = [
    "DistributionTrustState",
    "SkillDistributionStateError",
    "SkillDistributionStateStore",
]
