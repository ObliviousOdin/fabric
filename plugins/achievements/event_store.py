"""Profile-local, privacy-bounded SQLite ledger for Journey V2."""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from fabric_constants import get_fabric_home

from .events import EVENT_SCHEMA_VERSION, EventDraft


STATE_DIRNAME = "achievements-v2"
DATABASE_FILENAME = "events.db"
RAW_RETENTION_DAYS = 90
MAX_RAW_EVENTS = 50_000
MAX_EXPORT_EVENTS = 10_000
MAX_DAILY_ROLLUPS = 4_000
MAX_SNAPSHOT_ROLLUPS = 10_000
_KEY_FILENAME = ".event-key"
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    event_type TEXT NOT NULL,
    occurred_at REAL NOT NULL,
    duration_ms INTEGER,
    session_ref TEXT,
    turn_ref TEXT,
    subject_ref TEXT,
    capability TEXT NOT NULL,
    outcome TEXT NOT NULL,
    surface TEXT NOT NULL,
    provider TEXT NOT NULL,
    count INTEGER NOT NULL CHECK (count > 0),
    source TEXT NOT NULL,
    generation INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_achievement_events_time
    ON events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_achievement_events_capability
    ON events(capability, outcome, occurred_at);
CREATE TABLE IF NOT EXISTS event_rollups (
    day TEXT NOT NULL,
    event_type TEXT NOT NULL,
    capability TEXT NOT NULL,
    outcome TEXT NOT NULL,
    surface TEXT NOT NULL,
    provider TEXT NOT NULL,
    source TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    PRIMARY KEY (
        day, event_type, capability, outcome, surface, provider, source,
        generation
    )
);
CREATE TABLE IF NOT EXISTS event_totals (
    event_type TEXT NOT NULL,
    capability TEXT NOT NULL,
    outcome TEXT NOT NULL,
    surface TEXT NOT NULL,
    provider TEXT NOT NULL,
    source TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    PRIMARY KEY (
        event_type, capability, outcome, surface, provider, source, generation
    )
);
"""


class EventStoreError(RuntimeError):
    """The local event ledger could not be used safely."""


class EventStore:
    """Short-transaction event writer.

    Construction performs no I/O.  This is important because the achievements
    plugin is default-enabled: merely loading Fabric must not create files or
    start background work.
    """

    def __init__(self, fabric_home: Optional[Path] = None) -> None:
        self.fabric_home = (
            Path(fabric_home) if fabric_home is not None else get_fabric_home()
        )
        self.root = self.fabric_home / STATE_DIRNAME
        self.db_path = self.root / DATABASE_FILENAME
        self.key_path = self.root / _KEY_FILENAME
        self._initialised = False

    @property
    def _process_lock(self) -> threading.RLock:
        key = str(self.root.resolve())
        with _PROCESS_LOCKS_GUARD:
            return _PROCESS_LOCKS.setdefault(key, threading.RLock())

    @staticmethod
    def _chmod_private(path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except (NotImplementedError, OSError):
            # Windows and some network filesystems do not expose POSIX modes.
            pass

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        self._chmod_private(self.root, 0o700)
        connection = sqlite3.connect(self.db_path, timeout=2.0)
        self._chmod_private(self.db_path, 0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 2000")
        connection.execute("PRAGMA foreign_keys = ON")
        if not self._initialised:
            try:
                connection.execute("PRAGMA journal_mode = WAL")
            except sqlite3.Error:
                try:
                    connection.execute("PRAGMA journal_mode = DELETE")
                except sqlite3.Error:
                    pass
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO event_meta(key, value) VALUES ('generation', '1')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO event_meta(key, value) VALUES ('history_floor', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO event_meta(key, value) VALUES ('dropped_events', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO event_meta(key, value) VALUES ('compacted_events', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO event_meta(key, value) VALUES ('compacted_rollups', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO event_meta(key, value) VALUES ('key_epoch_generation', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO event_meta(key, value) VALUES ('collection_paused', '0')"
            )
            connection.commit()
            self._initialised = True
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield an initialised connection for sibling Journey stores."""
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _load_key(self) -> bytes:
        try:
            raw = self.key_path.read_bytes()
            if len(raw) == 32:
                self._chmod_private(self.key_path, 0o600)
                return raw
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise EventStoreError("achievement event key is unreadable") from exc

        self.root.mkdir(parents=True, exist_ok=True)
        self._chmod_private(self.root, 0o700)
        candidate = os.urandom(32)
        try:
            fd = os.open(
                self.key_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            try:
                raw = self.key_path.read_bytes()
            except OSError as exc:
                raise EventStoreError("achievement event key is unreadable") from exc
            if len(raw) != 32:
                raise EventStoreError("achievement event key is malformed")
            return raw
        except OSError as exc:
            raise EventStoreError("achievement event key cannot be created") from exc
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(candidate)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                self.key_path.unlink()
            except OSError:
                pass
            raise
        self._chmod_private(self.key_path, 0o600)
        return candidate

    @staticmethod
    def _clean_raw_ref(value: object) -> Optional[str]:
        if value is None:
            return None
        raw = str(value)
        if not raw or len(raw) > 1_024:
            return None
        return raw

    def _opaque_ref(self, key: bytes, namespace: str, raw: object) -> Optional[str]:
        value = self._clean_raw_ref(raw)
        if value is None:
            return None
        digest = hmac.new(
            key,
            f"{namespace}\0{value}".encode("utf-8", "surrogatepass"),
            hashlib.sha256,
        ).hexdigest()
        return digest

    @staticmethod
    def _generation_key(master_key: bytes, generation: int) -> bytes:
        """Derive a deletion-epoch key so erased exports cannot link forward."""
        return hmac.new(
            master_key,
            f"generation\0{generation}".encode("ascii"),
            hashlib.sha256,
        ).digest()

    def _reference_key(
        self,
        connection: sqlite3.Connection,
        master_key: bytes,
        generation: int,
    ) -> bytes:
        """Use legacy refs until a deletion explicitly rotates the key epoch.

        Existing Journey databases predate generation-derived keys. Preserving
        their master-key refs avoids silently splitting skill/session evidence
        during upgrade; the first deletion after upgrade marks the new
        generation as derived and all subsequent activity is unlinkable from
        prior exports.
        """
        row = connection.execute(
            "SELECT value FROM event_meta WHERE key = 'key_epoch_generation'"
        ).fetchone()
        try:
            epoch_generation = int(row[0]) if row is not None else 0
        except (TypeError, ValueError, OverflowError):
            epoch_generation = 0
        if epoch_generation == generation and generation > 0:
            return self._generation_key(master_key, generation)
        return master_key

    @staticmethod
    def _generation(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM event_meta WHERE key = 'generation'"
        ).fetchone()
        try:
            return max(1, int(row[0])) if row is not None else 1
        except (TypeError, ValueError, OverflowError):
            raise EventStoreError("achievement event generation is invalid")

    def _project_row(
        self, draft: EventDraft, *, key: bytes, now: float
    ) -> tuple[float, tuple[Any, ...]]:
        try:
            occurred_at = float(draft.occurred_at)
        except (TypeError, ValueError, OverflowError) as exc:
            raise EventStoreError("achievement event timestamp is invalid") from exc
        if not (0 < occurred_at <= now + 300):
            raise EventStoreError("achievement event timestamp is out of bounds")

        session_ref = self._opaque_ref(key, "session", draft.raw_session_ref)
        turn_ref = self._opaque_ref(key, "turn", draft.raw_turn_ref)
        subject_ref = self._opaque_ref(key, "subject", draft.raw_subject_ref)
        raw_dedupe = self._clean_raw_ref(draft.dedupe_key)
        if raw_dedupe is None:
            raw_dedupe = "|".join((
                draft.event_type.value,
                f"{occurred_at:.6f}",
                session_ref or "",
                turn_ref or "",
                subject_ref or "",
            ))
        event_id = self._opaque_ref(key, "event", raw_dedupe)
        assert event_id is not None
        return occurred_at, (
            event_id,
            EVENT_SCHEMA_VERSION,
            draft.event_type.value,
            occurred_at,
            draft.bounded_duration(),
            session_ref,
            turn_ref,
            subject_ref,
            draft.capability.value,
            draft.outcome.value,
            draft.surface.value,
            draft.provider.value,
            draft.bounded_count(),
            draft.source.value,
        )

    def append(self, draft: EventDraft) -> bool:
        """Insert one projected event, returning False for duplicates/resets."""
        return self.append_many((draft,))[0]

    def append_many(
        self,
        drafts: Iterable[EventDraft],
        *,
        dropped_count: int = 0,
        retention_days: int = RAW_RETENTION_DAYS,
    ) -> list[bool]:
        """Insert a small queue batch in one short transaction."""
        pending = list(drafts)
        dropped = max(0, int(dropped_count))
        if not pending and not dropped:
            return []
        now = time.time()
        inserted = [False] * len(pending)

        with self._process_lock:
            with self.connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    generation = self._generation(connection)
                    # Load and derive the HMAC key only after SQLite has
                    # serialized us with deletion. A generation increment is
                    # therefore an atomic key-epoch rotation even across
                    # separate Fabric processes.
                    key = self._reference_key(connection, self._load_key(), generation)
                    rows = [
                        self._project_row(draft, key=key, now=now) for draft in pending
                    ]
                    floor_row = connection.execute(
                        "SELECT value FROM event_meta WHERE key = 'history_floor'"
                    ).fetchone()
                    paused_row = connection.execute(
                        "SELECT value FROM event_meta WHERE key = 'collection_paused'"
                    ).fetchone()
                    collection_paused = (
                        paused_row is not None and str(paused_row[0]) == "1"
                    )
                    try:
                        history_floor = (
                            float(floor_row[0]) if floor_row is not None else 0.0
                        )
                    except (TypeError, ValueError, OverflowError):
                        raise EventStoreError("achievement history floor is invalid")
                    if dropped:
                        connection.execute(
                            """INSERT INTO event_meta(key, value)
                               VALUES ('dropped_events', ?)
                               ON CONFLICT(key) DO UPDATE SET
                                   value = CAST(CAST(event_meta.value AS INTEGER) + ? AS TEXT)""",
                            (str(dropped), dropped),
                        )
                    for index, (occurred_at, row) in enumerate(rows):
                        # The durable floor is the queue-to-delete fence.  A
                        # callback projected before deletion can arrive late,
                        # but it can never recreate erased activity.
                        if collection_paused or occurred_at <= history_floor:
                            continue
                        cursor = connection.execute(
                            """INSERT OR IGNORE INTO events (
                                   event_id, schema_version, event_type, occurred_at,
                                   duration_ms, session_ref, turn_ref, subject_ref,
                                   capability, outcome, surface, provider, count,
                                   source, generation
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (*row, generation),
                        )
                        inserted[index] = cursor.rowcount == 1
                    self._prune_if_due(
                        connection,
                        generation,
                        now,
                        retention_days=retention_days,
                    )
                    self._enforce_raw_limit(connection, generation)
                    self._compact_daily_rollups(connection, generation)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        return inserted

    def dropped_event_count(self) -> int:
        if not self.db_path.is_file():
            return 0
        with self.connection() as connection:
            row = connection.execute(
                "SELECT value FROM event_meta WHERE key = 'dropped_events'"
            ).fetchone()
        try:
            return max(0, int(row[0])) if row is not None else 0
        except (TypeError, ValueError, OverflowError):
            return 0

    def advance_history_floor(self, occurred_at: Optional[float] = None) -> float:
        """Advance the durable collection floor without deleting prior rows."""
        floor = time.time() if occurred_at is None else float(occurred_at)
        if floor <= 0:
            raise EventStoreError("achievement history floor is invalid")
        with self._process_lock:
            with self.connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT value FROM event_meta WHERE key = 'history_floor'"
                    ).fetchone()
                    current = float(row[0]) if row is not None else 0.0
                    effective = max(current, floor)
                    connection.execute(
                        "INSERT OR REPLACE INTO event_meta(key, value) VALUES ('history_floor', ?)",
                        (repr(effective),),
                    )
                    connection.commit()
                    return effective
                except BaseException:
                    connection.rollback()
                    raise

    def pause_collection(self, occurred_at: Optional[float] = None) -> float:
        """Install a durable fail-closed pause fence before config changes."""
        paused_at = time.time() if occurred_at is None else float(occurred_at)
        if paused_at <= 0:
            raise EventStoreError("achievement pause timestamp is invalid")
        with self._process_lock:
            with self.connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    existing = connection.execute(
                        "SELECT value FROM event_meta WHERE key = 'pause_started'"
                    ).fetchone()
                    try:
                        effective = (
                            min(paused_at, float(existing[0]))
                            if existing is not None
                            else paused_at
                        )
                    except (TypeError, ValueError, OverflowError):
                        effective = paused_at
                    connection.execute(
                        """INSERT OR REPLACE INTO event_meta(key, value)
                           VALUES ('pause_started', ?)""",
                        (repr(effective),),
                    )
                    connection.execute(
                        """INSERT OR REPLACE INTO event_meta(key, value)
                           VALUES ('collection_paused', '1')"""
                    )
                    connection.commit()
                    return effective
                except BaseException:
                    connection.rollback()
                    raise

    def collection_is_paused(self) -> bool:
        if not self.db_path.is_file():
            return False
        # This is called once per observer batch while reading config. Keep it
        # strictly read-only and avoid schema/journal setup on the hot path.
        connection = sqlite3.connect(
            self.db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25
        )
        try:
            row = connection.execute(
                "SELECT value FROM event_meta WHERE key = 'collection_paused'"
            ).fetchone()
        finally:
            connection.close()
        return row is not None and str(row[0]) == "1"

    def cancel_collection_pause(self) -> None:
        """Roll back a newly installed pause when its config write fails."""
        if not self.db_path.is_file():
            return
        with self._process_lock:
            with self.connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """INSERT OR REPLACE INTO event_meta(key, value)
                           VALUES ('collection_paused', '0')"""
                    )
                    connection.execute(
                        "DELETE FROM event_meta WHERE key = 'pause_started'"
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    def resume_collection(self, occurred_at: Optional[float] = None) -> float:
        """Erase any paused-window rows, advance the queue fence, and resume."""
        resumed_at = time.time() if occurred_at is None else float(occurred_at)
        if resumed_at <= 0:
            raise EventStoreError("achievement resume timestamp is invalid")
        with self._process_lock:
            with self.connection() as connection:
                try:
                    connection.execute("PRAGMA secure_delete = ON")
                    connection.execute("BEGIN IMMEDIATE")
                    floor_row = connection.execute(
                        "SELECT value FROM event_meta WHERE key = 'history_floor'"
                    ).fetchone()
                    current_floor = (
                        float(floor_row[0]) if floor_row is not None else 0.0
                    )
                    pause_row = connection.execute(
                        "SELECT value FROM event_meta WHERE key = 'pause_started'"
                    ).fetchone()
                    if pause_row is not None:
                        try:
                            pause_started = float(pause_row[0])
                        except (TypeError, ValueError, OverflowError):
                            pause_started = resumed_at
                        connection.execute(
                            """DELETE FROM events
                               WHERE occurred_at >= ? AND occurred_at <= ?""",
                            (pause_started, resumed_at),
                        )
                    effective = max(current_floor, resumed_at)
                    connection.execute(
                        """INSERT OR REPLACE INTO event_meta(key, value)
                           VALUES ('history_floor', ?)""",
                        (repr(effective),),
                    )
                    connection.execute(
                        """INSERT OR REPLACE INTO event_meta(key, value)
                           VALUES ('collection_paused', '0')"""
                    )
                    connection.execute(
                        "DELETE FROM event_meta WHERE key = 'pause_started'"
                    )
                    connection.commit()
                    return effective
                except BaseException:
                    connection.rollback()
                    raise

    def _prune_if_due(
        self,
        connection: sqlite3.Connection,
        generation: int,
        now: float,
        *,
        retention_days: int = RAW_RETENTION_DAYS,
        force: bool = False,
    ) -> None:
        local_day = time.strftime("%Y-%m-%d", time.localtime(now))
        row = connection.execute(
            "SELECT value FROM event_meta WHERE key = 'last_prune_day'"
        ).fetchone()
        if not force and row is not None and row[0] == local_day:
            return
        try:
            bounded_days = int(retention_days)
        except (TypeError, ValueError, OverflowError):
            bounded_days = RAW_RETENTION_DAYS
        bounded_days = min(365, max(1, bounded_days))
        cutoff = now - bounded_days * 86_400
        connection.execute(
            """INSERT INTO event_rollups (
                   day, event_type, capability, outcome, surface, provider,
                   source, event_count, duration_ms, generation
               )
               SELECT date(occurred_at, 'unixepoch', 'localtime'), event_type, capability,
                      outcome, surface, provider, source, SUM(count),
                      SUM(COALESCE(duration_ms, 0)), generation
               FROM events
               WHERE occurred_at < ? AND generation = ?
               GROUP BY date(occurred_at, 'unixepoch', 'localtime'), event_type, capability,
                        outcome, surface, provider, source, generation
               ON CONFLICT (
                   day, event_type, capability, outcome, surface, provider,
                   source, generation
               ) DO UPDATE SET
                   event_count = event_count + excluded.event_count,
                   duration_ms = duration_ms + excluded.duration_ms""",
            (cutoff, generation),
        )
        connection.execute(
            "DELETE FROM events WHERE occurred_at < ? AND generation = ?",
            (cutoff, generation),
        )
        connection.execute(
            "INSERT OR REPLACE INTO event_meta(key, value) VALUES ('last_prune_day', ?)",
            (local_day,),
        )

    @staticmethod
    def _increment_meta(connection: sqlite3.Connection, key: str, amount: int) -> None:
        if amount <= 0:
            return
        connection.execute(
            """INSERT INTO event_meta(key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value = CAST(CAST(event_meta.value AS INTEGER) + ? AS TEXT)""",
            (key, str(amount), amount),
        )

    def _enforce_raw_limit(
        self, connection: sqlite3.Connection, generation: int
    ) -> None:
        """Roll up oldest raw rows before the fixed-size ledger can grow."""
        row = connection.execute(
            "SELECT COUNT(*) FROM events WHERE generation = ?", (generation,)
        ).fetchone()
        count = int(row[0]) if row is not None else 0
        if count <= MAX_RAW_EVENTS:
            return
        target = max(1, int(MAX_RAW_EVENTS * 0.9))
        compact_count = count - target
        connection.execute(
            """INSERT INTO event_rollups (
                   day, event_type, capability, outcome, surface, provider,
                   source, event_count, duration_ms, generation
               )
               SELECT date(occurred_at, 'unixepoch', 'localtime'), event_type,
                      capability, outcome, surface, provider, source, SUM(count),
                      SUM(COALESCE(duration_ms, 0)), generation
               FROM events
               WHERE event_id IN (
                   SELECT event_id FROM events WHERE generation = ?
                   ORDER BY occurred_at, event_id LIMIT ?
               )
               GROUP BY date(occurred_at, 'unixepoch', 'localtime'), event_type,
                        capability, outcome, surface, provider, source, generation
               ON CONFLICT (
                   day, event_type, capability, outcome, surface, provider,
                   source, generation
               ) DO UPDATE SET
                   event_count = event_rollups.event_count + excluded.event_count,
                   duration_ms = event_rollups.duration_ms + excluded.duration_ms""",
            (generation, compact_count),
        )
        connection.execute(
            """DELETE FROM events WHERE event_id IN (
                   SELECT event_id FROM events WHERE generation = ?
                   ORDER BY occurred_at, event_id LIMIT ?
               )""",
            (generation, compact_count),
        )
        self._increment_meta(connection, "compacted_events", compact_count)

    def _compact_daily_rollups(
        self, connection: sqlite3.Connection, generation: int
    ) -> None:
        """Collapse oldest day rows into finite lifetime dimension totals."""
        row = connection.execute(
            "SELECT COUNT(*) FROM event_rollups WHERE generation = ?", (generation,)
        ).fetchone()
        count = int(row[0]) if row is not None else 0
        if count <= MAX_DAILY_ROLLUPS:
            return
        target = max(1, int(MAX_DAILY_ROLLUPS * 0.9))
        compact_count = count - target
        connection.execute(
            """INSERT INTO event_totals (
                   event_type, capability, outcome, surface, provider, source,
                   event_count, duration_ms, generation
               )
               SELECT event_type, capability, outcome, surface, provider, source,
                      SUM(event_count), SUM(duration_ms), generation
               FROM event_rollups
               WHERE rowid IN (
                   SELECT rowid FROM event_rollups WHERE generation = ?
                   ORDER BY day, rowid LIMIT ?
               )
               GROUP BY event_type, capability, outcome, surface, provider,
                        source, generation
               ON CONFLICT (
                   event_type, capability, outcome, surface, provider, source,
                   generation
               ) DO UPDATE SET
                   event_count = event_totals.event_count + excluded.event_count,
                   duration_ms = event_totals.duration_ms + excluded.duration_ms""",
            (generation, compact_count),
        )
        connection.execute(
            """DELETE FROM event_rollups WHERE rowid IN (
                   SELECT rowid FROM event_rollups WHERE generation = ?
                   ORDER BY day, rowid LIMIT ?
               )""",
            (generation, compact_count),
        )
        self._increment_meta(connection, "compacted_rollups", compact_count)

    def maintain(self, *, retention_days: int = RAW_RETENTION_DAYS) -> None:
        """Apply retention and hard storage bounds even without new events."""
        if not self.db_path.is_file():
            return
        now = time.time()
        with self._process_lock:
            with self.connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    generation = self._generation(connection)
                    self._prune_if_due(
                        connection,
                        generation,
                        now,
                        retention_days=retention_days,
                        force=True,
                    )
                    self._enforce_raw_limit(connection, generation)
                    self._compact_daily_rollups(connection, generation)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    def read_snapshot(
        self,
        *,
        retention_days: int = RAW_RETENTION_DAYS,
        max_events: Optional[int] = None,
        max_rollups: Optional[int] = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        """Return bounded safe rows, rollups, and whether raw rows were truncated."""
        if not self.db_path.is_file():
            return [], [], False
        self.maintain(retention_days=retention_days)
        event_limit = max(1, min(MAX_RAW_EVENTS, int(max_events or MAX_RAW_EVENTS)))
        rollup_limit = max(
            1, min(MAX_SNAPSHOT_ROLLUPS, int(max_rollups or MAX_SNAPSHOT_ROLLUPS))
        )
        with self.connection() as connection:
            generation = self._generation(connection)
            raw_rows = connection.execute(
                """SELECT event_id, event_type, occurred_at, duration_ms,
                          session_ref, turn_ref, subject_ref, capability,
                          outcome, surface, provider, count, source
                   FROM events WHERE generation = ?
                   ORDER BY occurred_at DESC LIMIT ?""",
                (generation, event_limit + 1),
            ).fetchall()
            total_rows = connection.execute(
                """SELECT NULL AS day, event_type, capability, outcome, surface,
                          provider, source, event_count, duration_ms
                   FROM event_totals WHERE generation = ?
                   ORDER BY event_type, capability, outcome, surface, provider,
                            source LIMIT ?""",
                (generation, rollup_limit + 1),
            ).fetchall()
            remaining = max(0, rollup_limit + 1 - len(total_rows))
            daily_rows = (
                connection.execute(
                    """SELECT day, event_type, capability, outcome, surface,
                              provider, source, event_count, duration_ms
                       FROM event_rollups WHERE generation = ? ORDER BY day""",
                    (generation,),
                ).fetchmany(remaining)
                if remaining > 0
                else []
            )
            compacted_row = connection.execute(
                "SELECT value FROM event_meta WHERE key = 'compacted_events'"
            ).fetchone()
            compacted_rollups_row = connection.execute(
                "SELECT value FROM event_meta WHERE key = 'compacted_rollups'"
            ).fetchone()
        rollups = list(total_rows) + list(daily_rows)
        try:
            compacted = max(0, int(compacted_row[0])) if compacted_row else 0
        except (TypeError, ValueError, OverflowError):
            compacted = 0
        try:
            compacted_rollups = (
                max(0, int(compacted_rollups_row[0])) if compacted_rollups_row else 0
            )
        except (TypeError, ValueError, OverflowError):
            compacted_rollups = 0
        truncated = (
            len(raw_rows) > event_limit
            or len(rollups) > rollup_limit
            or compacted > 0
            or compacted_rollups > 0
        )
        return (
            [dict(row) for row in raw_rows[:event_limit]],
            [dict(row) for row in rollups[:rollup_limit]],
            truncated,
        )

    def export(self, *, retention_days: int = RAW_RETENTION_DAYS) -> dict[str, Any]:
        events, rollups, truncated = self.read_snapshot(
            retention_days=retention_days,
            max_events=MAX_EXPORT_EVENTS,
            max_rollups=MAX_SNAPSHOT_ROLLUPS,
        )
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "events": events,
            "rollups": rollups,
            "truncated": truncated,
        }

    def delete_activity(self) -> dict[str, int]:
        """Delete activity metadata while preserving immutable unlock history."""
        with self._process_lock:
            with self.connection() as connection:
                try:
                    connection.execute("PRAGMA secure_delete = ON")
                    connection.execute("BEGIN IMMEDIATE")
                    previous = self._generation(connection)
                    event_count = connection.execute(
                        "SELECT COUNT(*) FROM events WHERE generation = ?", (previous,)
                    ).fetchone()[0]
                    rollup_count = connection.execute(
                        "SELECT COUNT(*) FROM event_rollups WHERE generation = ?",
                        (previous,),
                    ).fetchone()[0]
                    total_count = connection.execute(
                        "SELECT COUNT(*) FROM event_totals WHERE generation = ?",
                        (previous,),
                    ).fetchone()[0]
                    new_generation = previous + 1
                    history_floor = time.time()
                    connection.execute("DELETE FROM events")
                    connection.execute("DELETE FROM event_rollups")
                    connection.execute("DELETE FROM event_totals")
                    for table in (
                        "journey_assignments",
                        "journey_momentum",
                        "journey_snoozes",
                        "journey_attestations",
                    ):
                        try:
                            connection.execute(f"DELETE FROM {table}")
                        except sqlite3.OperationalError:
                            pass
                    connection.execute(
                        "UPDATE event_meta SET value = ? WHERE key = 'generation'",
                        (str(new_generation),),
                    )
                    connection.execute(
                        """INSERT OR REPLACE INTO event_meta(key, value)
                           VALUES ('key_epoch_generation', ?)""",
                        (str(new_generation),),
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO event_meta(key, value) VALUES ('history_floor', ?)",
                        (repr(history_floor),),
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO event_meta(key, value) VALUES ('dropped_events', '0')"
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO event_meta(key, value) VALUES ('compacted_events', '0')"
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO event_meta(key, value) VALUES ('compacted_rollups', '0')"
                    )
                    connection.execute(
                        "DELETE FROM event_meta WHERE key = 'last_prune_day'"
                    )
                    connection.commit()
                    # ``secure_delete`` overwrites freed database cells; the
                    # checkpoint removes prior event pages from the WAL too.
                    checkpoint = connection.execute(
                        "PRAGMA wal_checkpoint(TRUNCATE)"
                    ).fetchone()
                    if checkpoint is not None and int(checkpoint[0]) != 0:
                        raise EventStoreError(
                            "achievement activity WAL could not be truncated"
                        )
                    return {
                        "events": int(event_count),
                        "rollups": int(rollup_count),
                        "totals": int(total_count),
                        "generation": new_generation,
                    }
                except BaseException:
                    connection.rollback()
                    raise


__all__ = [
    "DATABASE_FILENAME",
    "EventStore",
    "EventStoreError",
    "MAX_DAILY_ROLLUPS",
    "MAX_EXPORT_EVENTS",
    "MAX_RAW_EVENTS",
    "MAX_SNAPSHOT_ROLLUPS",
    "RAW_RETENTION_DAYS",
    "STATE_DIRNAME",
]
