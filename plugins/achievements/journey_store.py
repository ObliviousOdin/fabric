"""Durable Journey unlock, challenge, Momentum, and attestation state."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from fabric_constants import get_fabric_home

from .event_store import EventStore
from .journey_catalog import AchievementDefinition


_SCHEMA = """
CREATE TABLE IF NOT EXISTS journey_unlocks (
    achievement_id TEXT PRIMARY KEY,
    earned_at REAL NOT NULL,
    xp INTEGER NOT NULL CHECK (xp >= 0),
    confidence TEXT NOT NULL CHECK (confidence IN ('observed', 'aggregate_observed')),
    evidence_kind TEXT NOT NULL,
    evidence_count INTEGER NOT NULL CHECK (evidence_count >= 0),
    evaluator_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS journey_assignments (
    kind TEXT NOT NULL CHECK (kind IN ('daily', 'weekly')),
    period_key TEXT NOT NULL,
    template_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    assigned_at REAL NOT NULL,
    baseline_count INTEGER NOT NULL CHECK (baseline_count >= 0),
    target_delta INTEGER NOT NULL CHECK (target_delta > 0),
    secondary_capability TEXT,
    reroll_count INTEGER NOT NULL DEFAULT 0 CHECK (reroll_count >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'expired')),
    completed_at REAL,
    PRIMARY KEY (kind, period_key)
);
CREATE TABLE IF NOT EXISTS journey_momentum (
    kind TEXT NOT NULL CHECK (kind IN ('daily', 'weekly')),
    period_key TEXT NOT NULL,
    season_id TEXT NOT NULL,
    points INTEGER NOT NULL CHECK (points > 0),
    awarded_at REAL NOT NULL,
    PRIMARY KEY (kind, period_key)
);
CREATE TABLE IF NOT EXISTS journey_snoozes (
    quest_id TEXT PRIMARY KEY,
    snoozed_until REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS journey_attestations (
    achievement_id TEXT PRIMARY KEY,
    attested_at REAL NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence = 'self_attested')
);
CREATE TABLE IF NOT EXISTS journey_markers (
    marker_id TEXT PRIMARY KEY,
    earned_at REAL NOT NULL,
    evidence_count INTEGER NOT NULL CHECK (evidence_count >= 0)
);
"""


class JourneyStore:
    def __init__(self, fabric_home: Optional[Path] = None) -> None:
        self.fabric_home = (
            Path(fabric_home) if fabric_home is not None else get_fabric_home()
        )
        self.events = EventStore(self.fabric_home)
        self._initialised = False

    def _ensure(self, connection: sqlite3.Connection) -> None:
        if not self._initialised:
            connection.executescript(_SCHEMA)
            connection.commit()
            self._initialised = True

    def unlock_records(self) -> dict[str, dict[str, Any]]:
        if not self.events.db_path.is_file():
            return {}
        with self.events.connection() as connection:
            self._ensure(connection)
            rows = connection.execute(
                "SELECT * FROM journey_unlocks ORDER BY earned_at, achievement_id"
            ).fetchall()
        return {str(row["achievement_id"]): dict(row) for row in rows}

    def record_unlocks(
        self,
        definitions: Iterable[AchievementDefinition],
        facts: Mapping[str, int],
    ) -> list[dict[str, Any]]:
        requested = [item for item in definitions if item.launch and item.rank_eligible]
        if not requested:
            return []
        now = time.time()
        appended: list[dict[str, Any]] = []
        with self.events.connection() as connection:
            self._ensure(connection)
            try:
                connection.execute("BEGIN IMMEDIATE")
                for item in requested:
                    evidence_count = min(
                        (
                            max(0, int(facts.get(requirement.key, 0)))
                            for requirement in item.requirements
                        ),
                        default=0,
                    )
                    cursor = connection.execute(
                        """INSERT OR IGNORE INTO journey_unlocks (
                               achievement_id, earned_at, xp, confidence,
                               evidence_kind, evidence_count, evaluator_version
                           ) VALUES (?, ?, ?, 'observed', ?, ?, 1)""",
                        (
                            item.id,
                            now,
                            item.xp,
                            "+".join(
                                requirement.key for requirement in item.requirements
                            ),
                            evidence_count,
                        ),
                    )
                    if cursor.rowcount == 1:
                        appended.append({
                            "achievement_id": item.id,
                            "earned_at": now,
                            "xp": item.xp,
                            "confidence": "observed",
                            "evidence_count": evidence_count,
                        })
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return appended

    def record_marker(self, marker_id: str, evidence_count: int) -> bool:
        with self.events.connection() as connection:
            self._ensure(connection)
            cursor = connection.execute(
                """INSERT OR IGNORE INTO journey_markers (
                       marker_id, earned_at, evidence_count
                   ) VALUES (?, ?, ?)""",
                (marker_id, time.time(), max(0, int(evidence_count))),
            )
            connection.commit()
        return cursor.rowcount == 1

    def markers(self) -> dict[str, dict[str, Any]]:
        if not self.events.db_path.is_file():
            return {}
        with self.events.connection() as connection:
            self._ensure(connection)
            rows = connection.execute("SELECT * FROM journey_markers").fetchall()
        return {str(row["marker_id"]): dict(row) for row in rows}

    def assignment(self, kind: str, period_key: str) -> Optional[dict[str, Any]]:
        if not self.events.db_path.is_file():
            return None
        with self.events.connection() as connection:
            self._ensure(connection)
            row = connection.execute(
                "SELECT * FROM journey_assignments WHERE kind = ? AND period_key = ?",
                (kind, period_key),
            ).fetchone()
        return dict(row) if row is not None else None

    def recent_daily_capabilities(self, limit: int = 2) -> tuple[str, ...]:
        if not self.events.db_path.is_file():
            return ()
        with self.events.connection() as connection:
            self._ensure(connection)
            rows = connection.execute(
                """SELECT capability FROM journey_assignments
                   WHERE kind = 'daily' ORDER BY assigned_at DESC LIMIT ?""",
                (max(1, min(14, int(limit))),),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def create_assignment(
        self,
        *,
        kind: str,
        period_key: str,
        template_id: str,
        path_id: str,
        capability: str,
        baseline_count: int,
        target_delta: int,
        secondary_capability: Optional[str] = None,
        reroll_count: int = 0,
    ) -> dict[str, Any]:
        with self.events.connection() as connection:
            self._ensure(connection)
            connection.execute(
                """INSERT OR REPLACE INTO journey_assignments (
                       kind, period_key, template_id, path_id, capability,
                       assigned_at, baseline_count, target_delta,
                       secondary_capability, reroll_count, status, completed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL)""",
                (
                    kind,
                    period_key,
                    template_id,
                    path_id,
                    capability,
                    time.time(),
                    max(0, int(baseline_count)),
                    max(1, int(target_delta)),
                    secondary_capability,
                    max(0, int(reroll_count)),
                ),
            )
            connection.commit()
        assignment = self.assignment(kind, period_key)
        assert assignment is not None
        return assignment

    def complete_assignment(
        self, kind: str, period_key: str, *, season_id: str, points: int
    ) -> bool:
        now = time.time()
        with self.events.connection() as connection:
            self._ensure(connection)
            try:
                connection.execute("BEGIN IMMEDIATE")
                assignment = connection.execute(
                    "SELECT status FROM journey_assignments WHERE kind = ? AND period_key = ?",
                    (kind, period_key),
                ).fetchone()
                if assignment is None or assignment["status"] == "completed":
                    connection.rollback()
                    return False
                connection.execute(
                    """UPDATE journey_assignments
                       SET status = 'completed', completed_at = ?
                       WHERE kind = ? AND period_key = ?""",
                    (now, kind, period_key),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO journey_momentum (
                           kind, period_key, season_id, points, awarded_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (kind, period_key, season_id, max(1, int(points)), now),
                )
                connection.commit()
                return True
            except BaseException:
                connection.rollback()
                raise

    def momentum(self, season_id: str) -> int:
        if not self.events.db_path.is_file():
            return 0
        with self.events.connection() as connection:
            self._ensure(connection)
            row = connection.execute(
                "SELECT COALESCE(SUM(points), 0) FROM journey_momentum WHERE season_id = ?",
                (season_id,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def snooze(self, quest_id: str, *, days: int) -> float:
        until = time.time() + max(1, min(30, int(days))) * 86_400
        with self.events.connection() as connection:
            self._ensure(connection)
            connection.execute(
                "INSERT OR REPLACE INTO journey_snoozes(quest_id, snoozed_until) VALUES (?, ?)",
                (quest_id, until),
            )
            connection.commit()
        return until

    def snoozed_ids(self, *, now: Optional[float] = None) -> frozenset[str]:
        if not self.events.db_path.is_file():
            return frozenset()
        current = time.time() if now is None else float(now)
        with self.events.connection() as connection:
            self._ensure(connection)
            connection.execute(
                "DELETE FROM journey_snoozes WHERE snoozed_until <= ?", (current,)
            )
            rows = connection.execute("SELECT quest_id FROM journey_snoozes").fetchall()
            connection.commit()
        return frozenset(str(row[0]) for row in rows)

    def attest(self, achievement_id: str) -> dict[str, Any]:
        now = time.time()
        with self.events.connection() as connection:
            self._ensure(connection)
            connection.execute(
                """INSERT OR IGNORE INTO journey_attestations (
                       achievement_id, attested_at, confidence
                   ) VALUES (?, ?, 'self_attested')""",
                (achievement_id, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM journey_attestations WHERE achievement_id = ?",
                (achievement_id,),
            ).fetchone()
        assert row is not None
        return dict(row)

    def attestations(self) -> dict[str, dict[str, Any]]:
        if not self.events.db_path.is_file():
            return {}
        with self.events.connection() as connection:
            self._ensure(connection)
            rows = connection.execute("SELECT * FROM journey_attestations").fetchall()
        return {str(row["achievement_id"]): dict(row) for row in rows}


__all__ = ["JourneyStore"]
