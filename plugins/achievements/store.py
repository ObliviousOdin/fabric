"""Durable, profile-scoped state for the achievements plugin.

Earned milestones are an append-only event ledger.  Replacing the JSON file is
only the atomic persistence mechanism; existing events are never removed or
rewritten, so state-database pruning cannot relock a milestone later.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional

from fabric_constants import get_fabric_home

from .catalog import Milestone


SCHEMA_VERSION = 1
STATE_DIRNAME = "achievements-v1"
_MAX_STATE_BYTES = 1_048_576
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()

try:  # pragma: no cover - platform-specific import
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - platform-specific import
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]


class AchievementStateError(RuntimeError):
    """Raised when durable achievement state cannot be trusted."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


class AchievementStore:
    """Atomic state access rooted in one Fabric profile."""

    def __init__(
        self,
        fabric_home: Optional[Path] = None,
        *,
        read_only: bool = False,
    ) -> None:
        self.fabric_home = Path(fabric_home) if fabric_home is not None else get_fabric_home()
        self.root = self.fabric_home / STATE_DIRNAME
        self.read_only = read_only
        self.ledger_path = self.root / "ledger.json"
        self.leaderboard_path = self.root / "leaderboard.json"
        self._lock_path = self.root / ".state.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self.read_only:
            yield
            return
        lock_key = str(self.root.resolve())
        with _PROCESS_LOCKS_GUARD:
            process_lock = _PROCESS_LOCKS.setdefault(lock_key, threading.RLock())
        with process_lock:
            self.root.mkdir(parents=True, exist_ok=True)
            lock_file = open(self._lock_path, "a+b")
            try:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                elif msvcrt is not None:  # pragma: no cover - Windows
                    lock_file.seek(0, os.SEEK_END)
                    if lock_file.tell() == 0:
                        lock_file.write(b"\0")
                        lock_file.flush()
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                yield
            finally:
                if fcntl is not None:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
                elif msvcrt is not None:  # pragma: no cover - Windows
                    try:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                lock_file.close()

    @staticmethod
    def _read_json(path: Path) -> Optional[dict[str, Any]]:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise AchievementStateError("achievement state is unreadable") from exc
        if stat.st_size > _MAX_STATE_BYTES:
            raise AchievementStateError("achievement state exceeds its size limit")
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AchievementStateError("achievement state is malformed") from exc
        if not isinstance(data, dict):
            raise AchievementStateError("achievement state must be an object")
        return data

    @staticmethod
    def _atomic_write(path: Path, data: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > _MAX_STATE_BYTES:
            raise AchievementStateError("achievement state exceeds its size limit")
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            try:
                os.fchmod(fd, 0o600)
            except (AttributeError, OSError):  # pragma: no cover - Windows/filesystem
                pass
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def _new_ledger() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "profile_card_id": str(uuid.uuid4()),
            "created_at": utc_now(),
            "events": [],
        }

    @staticmethod
    def _validate_ledger(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("schema_version") != SCHEMA_VERSION:
            raise AchievementStateError("unsupported achievement ledger version")
        if not _is_uuid(data.get("profile_card_id")):
            raise AchievementStateError("achievement ledger card id is invalid")
        if not isinstance(data.get("created_at"), str):
            raise AchievementStateError("achievement ledger creation time is invalid")
        events = data.get("events")
        if not isinstance(events, list):
            raise AchievementStateError("achievement ledger events are invalid")
        seen: set[str] = set()
        for expected_sequence, event in enumerate(events, start=1):
            if not isinstance(event, dict):
                raise AchievementStateError("achievement ledger event is invalid")
            achievement_id = event.get("achievement_id")
            if not isinstance(achievement_id, str) or not achievement_id:
                raise AchievementStateError("achievement ledger event id is invalid")
            if achievement_id in seen:
                raise AchievementStateError("achievement ledger contains duplicate unlocks")
            seen.add(achievement_id)
            if event.get("sequence") != expected_sequence:
                raise AchievementStateError("achievement ledger sequence is invalid")
            if not isinstance(event.get("earned_at"), str):
                raise AchievementStateError("achievement ledger timestamp is invalid")
            for key in ("metric_value", "threshold", "points"):
                value = event.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise AchievementStateError("achievement ledger counter is invalid")
        return data

    def _load_ledger_unlocked(self, *, create: bool) -> Optional[dict[str, Any]]:
        data = self._read_json(self.ledger_path)
        if data is None:
            if not create:
                return None
            if self.read_only:
                raise AchievementStateError("cannot create achievement state read-only")
            data = self._new_ledger()
            self._atomic_write(self.ledger_path, data)
        return self._validate_ledger(data)

    def read_ledger(self, *, create: bool = True) -> Optional[dict[str, Any]]:
        """Return a validated copy of the ledger.

        Read-only stores default to ``create=False`` at call sites so profile
        enumeration never creates state in another profile.
        """
        with self._locked():
            data = self._load_ledger_unlocked(create=create)
            return json.loads(json.dumps(data)) if data is not None else None

    def card_id(self, *, create: bool = True) -> Optional[str]:
        ledger = self.read_ledger(create=create)
        if ledger is None:
            return None
        return str(ledger["profile_card_id"])

    def earned_records(self, *, create: bool = True) -> dict[str, dict[str, Any]]:
        ledger = self.read_ledger(create=create)
        if ledger is None:
            return {}
        return {
            str(event["achievement_id"]): dict(event)
            for event in ledger["events"]
        }

    def record_unlocks(
        self,
        milestones: Iterable[Milestone],
        metrics: Mapping[str, int],
    ) -> list[dict[str, Any]]:
        """Append each not-yet-recorded milestone exactly once."""
        if self.read_only:
            raise AchievementStateError("cannot append achievement state read-only")
        requested = list(milestones)
        if not requested:
            return []
        with self._locked():
            ledger = self._load_ledger_unlocked(create=True)
            assert ledger is not None
            seen = {str(event["achievement_id"]) for event in ledger["events"]}
            earned_at = utc_now()
            appended: list[dict[str, Any]] = []
            for milestone in requested:
                if milestone.id in seen:
                    continue
                raw_value = metrics.get(milestone.metric, 0)
                metric_value = (
                    raw_value
                    if isinstance(raw_value, int) and not isinstance(raw_value, bool)
                    else 0
                )
                event = {
                    "sequence": len(ledger["events"]) + 1,
                    "achievement_id": milestone.id,
                    "earned_at": earned_at,
                    "metric_value": max(0, metric_value),
                    "threshold": milestone.threshold,
                    "points": milestone.points,
                }
                ledger["events"].append(event)
                appended.append(dict(event))
                seen.add(milestone.id)
            if appended:
                self._atomic_write(self.ledger_path, ledger)
            return appended

    @staticmethod
    def _new_leaderboard() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "local_display_name": None,
            "imports": {},
        }

    @staticmethod
    def _validate_leaderboard(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("schema_version") != SCHEMA_VERSION:
            raise AchievementStateError("unsupported achievement leaderboard version")
        display_name = data.get("local_display_name")
        if display_name is not None and not isinstance(display_name, str):
            raise AchievementStateError("local leaderboard name is invalid")
        imports = data.get("imports")
        if not isinstance(imports, dict):
            raise AchievementStateError("achievement imports are invalid")
        for card_id, card in imports.items():
            if not _is_uuid(card_id) or not isinstance(card, dict):
                raise AchievementStateError("achievement import record is invalid")
            if card.get("card_id") != card_id:
                raise AchievementStateError("achievement import id mismatch")
        return data

    def _load_leaderboard_unlocked(self, *, create: bool) -> Optional[dict[str, Any]]:
        data = self._read_json(self.leaderboard_path)
        if data is None:
            if not create:
                return None
            if self.read_only:
                raise AchievementStateError("cannot create leaderboard state read-only")
            data = self._new_leaderboard()
            self._atomic_write(self.leaderboard_path, data)
        return self._validate_leaderboard(data)

    def local_display_name(self, default: str, *, create: bool = True) -> str:
        with self._locked():
            data = self._load_leaderboard_unlocked(create=create)
            if data is None or not data.get("local_display_name"):
                return default
            return str(data["local_display_name"])

    def set_local_display_name(self, display_name: str) -> None:
        if self.read_only:
            raise AchievementStateError("cannot update leaderboard state read-only")
        with self._locked():
            data = self._load_leaderboard_unlocked(create=True)
            assert data is not None
            if data.get("local_display_name") != display_name:
                data["local_display_name"] = display_name
                self._atomic_write(self.leaderboard_path, data)

    def list_imports(self, *, create: bool = True) -> list[dict[str, Any]]:
        with self._locked():
            data = self._load_leaderboard_unlocked(create=create)
            if data is None:
                return []
            return [dict(card) for card in data["imports"].values()]

    def upsert_import(self, card: Mapping[str, Any]) -> bool:
        """Insert or replace a self-reported card; return True when new."""
        if self.read_only:
            raise AchievementStateError("cannot update leaderboard state read-only")
        card_id = card.get("card_id")
        if not _is_uuid(card_id):
            raise AchievementStateError("achievement import card id is invalid")
        with self._locked():
            data = self._load_leaderboard_unlocked(create=True)
            assert data is not None
            created = card_id not in data["imports"]
            data["imports"][card_id] = dict(card)
            self._atomic_write(self.leaderboard_path, data)
            return created

    def delete_import(self, card_id: str) -> bool:
        if self.read_only:
            raise AchievementStateError("cannot update leaderboard state read-only")
        with self._locked():
            data = self._load_leaderboard_unlocked(create=True)
            assert data is not None
            if card_id not in data["imports"]:
                return False
            del data["imports"][card_id]
            self._atomic_write(self.leaderboard_path, data)
            return True

    def reset_imports(self) -> int:
        """Explicitly clear imported cards without touching progress."""
        if self.read_only:
            raise AchievementStateError("cannot update leaderboard state read-only")
        with self._locked():
            data = self._load_leaderboard_unlocked(create=True)
            assert data is not None
            removed = len(data["imports"])
            if removed:
                data["imports"] = {}
                self._atomic_write(self.leaderboard_path, data)
            return removed


__all__ = [
    "AchievementStateError",
    "AchievementStore",
    "SCHEMA_VERSION",
    "STATE_DIRNAME",
    "utc_now",
]
