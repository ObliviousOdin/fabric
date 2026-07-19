"""Privacy-bounded metric collection and milestone evaluation."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

from fabric_constants import (
    get_fabric_home,
    reset_fabric_home_override,
    set_fabric_home_override,
)

from .catalog import MILESTONES, TOTAL_POINTS, TRACKS, Milestone
from .store import AchievementStore, utc_now


_MAX_COUNTER = (1 << 63) - 1

PRIVACY_METADATA: dict[str, Any] = {
    "data_scope": "local_profile_aggregates",
    "session_table_only": True,
    "session_content_accessed": False,
    "skill_usage_fields": ["use_count", "view_count", "patch_count"],
    "excluded_fields": [
        "prompt",
        "content",
        "reasoning",
        "tool_arguments",
        "title",
        "path",
        "user_id",
        "chat_id",
        "cost",
        "tokens",
    ],
    "network_access": False,
    "leaderboard": "local_manual_self_reported",
    "share_card_max_bytes": 16 * 1024,
}


_SESSION_AGGREGATE_SQL = """
SELECT
    COUNT(CASE WHEN COALESCE(message_count, 0) > 0 THEN 1 END) AS total_sessions,
    COALESCE(SUM(MAX(COALESCE(message_count, 0), 0)), 0) AS total_messages,
    COALESCE(SUM(MAX(COALESCE(tool_call_count, 0), 0)), 0) AS total_tool_calls,
    COALESCE(SUM(MAX(COALESCE(api_call_count, 0), 0)), 0) AS total_api_calls,
    COUNT(DISTINCT CASE
        WHEN COALESCE(message_count, 0) > 0
         AND TRIM(COALESCE(source, '')) <> ''
        THEN source END) AS distinct_sources,
    COUNT(DISTINCT CASE
        WHEN COALESCE(message_count, 0) > 0
         AND TRIM(COALESCE(model, '')) <> ''
        THEN model END) AS distinct_models,
    COALESCE(SUM(CASE
        WHEN COALESCE(message_count, 0) > 0
         AND LOWER(COALESCE(source, '')) = 'cron'
        THEN 1 ELSE 0 END), 0) AS cron_runs,
    COALESCE(SUM(CASE
        WHEN COALESCE(message_count, 0) > 0
         AND model_config IS NOT NULL
         AND json_type(
             CASE WHEN json_valid(model_config) THEN model_config ELSE '{}' END,
             '$._delegate_from'
         ) IS NOT NULL
        THEN 1 ELSE 0 END), 0) AS delegated_runs,
    COALESCE(SUM(CASE
        WHEN end_reason = 'compression' THEN 1 ELSE 0 END), 0)
        AS compressed_conversations,
    COALESCE(SUM(CASE WHEN COALESCE(archived, 0) <> 0 THEN 1 ELSE 0 END), 0)
        AS archived_sessions
FROM sessions
"""

_ACTIVE_DAYS_SQL = """
SELECT DISTINCT date(started_at, 'unixepoch') AS active_day
FROM sessions
WHERE COALESCE(message_count, 0) > 0
  AND date(started_at, 'unixepoch') IS NOT NULL
ORDER BY active_day
"""


@dataclass(frozen=True)
class MetricSnapshot:
    metrics: dict[str, int]
    warnings: tuple[str, ...] = ()


def _zero_metrics() -> dict[str, int]:
    return {
        "total_sessions": 0,
        "active_days_utc": 0,
        "longest_active_streak_utc": 0,
        "total_messages": 0,
        "total_tool_calls": 0,
        "total_api_calls": 0,
        "distinct_sources": 0,
        "distinct_models": 0,
        "cron_runs": 0,
        "delegated_runs": 0,
        "compressed_conversations": 0,
        "archived_sessions": 0,
        "skill_use_count": 0,
        "skill_view_count": 0,
        "skill_patch_count": 0,
        "distinct_skills_used": 0,
        "messages_per_session": 0,
        "sessions_per_active_day": 0,
        "automation_runs": 0,
        "skill_activity_total": 0,
    }


def _bounded_counter(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)  # current skill sidecar tolerates legacy string counters
    except (TypeError, ValueError, OverflowError):
        return 0
    return min(_MAX_COUNTER, max(0, parsed))


def _longest_streak(raw_days: list[object]) -> int:
    parsed: list[date] = []
    for raw in raw_days:
        if not isinstance(raw, str):
            continue
        try:
            parsed.append(date.fromisoformat(raw))
        except ValueError:
            continue
    longest = 0
    current = 0
    previous: Optional[date] = None
    for day in sorted(set(parsed)):
        if previous is not None and (day - previous).days == 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous = day
    return longest


@contextmanager
def _profile_scope(fabric_home: Path) -> Iterator[None]:
    if fabric_home.resolve() == get_fabric_home().resolve():
        yield
        return
    token = set_fabric_home_override(fabric_home)
    try:
        yield
    finally:
        reset_fabric_home_override(token)


def _default_skill_usage_loader(fabric_home: Path) -> Mapping[str, Mapping[str, Any]]:
    # ``load_usage`` is the current public sidecar reader.  We scope its
    # profile-aware path and then consume only its three aggregate counters.
    with _profile_scope(fabric_home):
        from tools.skill_usage import load_usage

        return load_usage()


def collect_metrics(
    fabric_home: Optional[Path] = None,
    *,
    skill_usage_loader: Optional[
        Callable[[Path], Mapping[str, Mapping[str, Any]]]
    ] = None,
) -> MetricSnapshot:
    """Collect aggregate-only metrics from one profile.

    This function never references the ``messages`` table.  The two SQL
    statements return aggregate counters and UTC dates only; source, model, and
    delegation marker values are counted inside SQLite and never returned.
    """
    home = Path(fabric_home) if fabric_home is not None else get_fabric_home()
    metrics = _zero_metrics()
    warnings: list[str] = []
    db_path = home / "state.db"

    if not db_path.is_file():
        warnings.append("session_store_unavailable")
    else:
        connection: Optional[sqlite3.Connection] = None
        try:
            uri = db_path.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=1.0)
            connection.row_factory = sqlite3.Row
            row = connection.execute(_SESSION_AGGREGATE_SQL).fetchone()
            if row is not None:
                for key in (
                    "total_sessions",
                    "total_messages",
                    "total_tool_calls",
                    "total_api_calls",
                    "distinct_sources",
                    "distinct_models",
                    "cron_runs",
                    "delegated_runs",
                    "compressed_conversations",
                    "archived_sessions",
                ):
                    metrics[key] = _bounded_counter(row[key])
            day_rows = connection.execute(_ACTIVE_DAYS_SQL).fetchall()
            days = [row["active_day"] for row in day_rows]
            metrics["active_days_utc"] = len(days)
            metrics["longest_active_streak_utc"] = _longest_streak(days)
        except (OSError, sqlite3.Error):
            warnings.append("session_store_unreadable")
        finally:
            if connection is not None:
                connection.close()

    loader = skill_usage_loader or _default_skill_usage_loader
    try:
        usage = loader(home)
        if not isinstance(usage, Mapping):
            raise TypeError("skill usage must be a mapping")
        for record in usage.values():
            if not isinstance(record, Mapping):
                continue
            use_count = _bounded_counter(record.get("use_count"))
            view_count = _bounded_counter(record.get("view_count"))
            patch_count = _bounded_counter(record.get("patch_count"))
            metrics["skill_use_count"] = min(
                _MAX_COUNTER, metrics["skill_use_count"] + use_count
            )
            metrics["skill_view_count"] = min(
                _MAX_COUNTER, metrics["skill_view_count"] + view_count
            )
            metrics["skill_patch_count"] = min(
                _MAX_COUNTER, metrics["skill_patch_count"] + patch_count
            )
            if use_count > 0:
                metrics["distinct_skills_used"] += 1
    except Exception:
        warnings.append("skill_usage_unavailable")

    sessions = metrics["total_sessions"]
    active_days = metrics["active_days_utc"]
    metrics["messages_per_session"] = (
        metrics["total_messages"] // sessions if sessions else 0
    )
    metrics["sessions_per_active_day"] = sessions // active_days if active_days else 0
    metrics["automation_runs"] = min(
        _MAX_COUNTER, metrics["cron_runs"] + metrics["delegated_runs"]
    )
    metrics["skill_activity_total"] = min(
        _MAX_COUNTER,
        metrics["skill_use_count"]
        + metrics["skill_view_count"]
        + metrics["skill_patch_count"],
    )
    return MetricSnapshot(metrics=metrics, warnings=tuple(dict.fromkeys(warnings)))


def qualifying_milestones(metrics: Mapping[str, int]) -> tuple[Milestone, ...]:
    return tuple(
        milestone
        for milestone in MILESTONES
        if _bounded_counter(metrics.get(milestone.metric, 0)) >= milestone.threshold
    )


def _milestone_dict(
    milestone: Milestone,
    *,
    value: int,
    earned_record: Optional[Mapping[str, Any]],
    transient_earned: bool = False,
) -> dict[str, Any]:
    earned = earned_record is not None or transient_earned
    progress = 1.0 if earned else min(1.0, value / milestone.threshold)
    return {
        "id": milestone.id,
        "title": milestone.title,
        "description": milestone.description,
        "tier": milestone.tier,
        "threshold": milestone.threshold,
        "points": milestone.points,
        "earned": earned,
        "earned_at": earned_record.get("earned_at") if earned_record else None,
        "progress": progress,
    }


def build_summary(
    snapshot: MetricSnapshot,
    earned_records: Mapping[str, Mapping[str, Any]],
    *,
    include_current_qualifiers: bool = False,
) -> dict[str, Any]:
    qualifying_ids = (
        {milestone.id for milestone in qualifying_milestones(snapshot.metrics)}
        if include_current_qualifiers
        else set()
    )
    tracks: list[dict[str, Any]] = []
    score = 0
    earned_count = 0
    for track in TRACKS:
        value = _bounded_counter(snapshot.metrics.get(track.metric, 0))
        milestones: list[dict[str, Any]] = []
        for milestone in track.milestones:
            record = earned_records.get(milestone.id)
            item = _milestone_dict(
                milestone,
                value=value,
                earned_record=record,
                transient_earned=milestone.id in qualifying_ids,
            )
            if item["earned"]:
                score += milestone.points
                earned_count += 1
            milestones.append(item)
        tracks.append(
            {
                "id": track.id,
                "title": track.title,
                "category": track.category,
                "metric": track.metric,
                "value": value,
                "milestones": milestones,
            }
        )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "score": score,
        "earned_count": earned_count,
        "total_points": TOTAL_POINTS,
        "metrics": dict(snapshot.metrics),
        "tracks": tracks,
        "warnings": list(snapshot.warnings),
        "privacy": dict(PRIVACY_METADATA),
    }


class AchievementEngine:
    """Orchestrate metrics, ledger persistence, and API-ready summaries."""

    def __init__(
        self,
        fabric_home: Optional[Path] = None,
        *,
        read_only: bool = False,
        skill_usage_loader: Optional[
            Callable[[Path], Mapping[str, Mapping[str, Any]]]
        ] = None,
    ) -> None:
        self.fabric_home = Path(fabric_home) if fabric_home is not None else get_fabric_home()
        self.read_only = read_only
        self.skill_usage_loader = skill_usage_loader
        self.store = AchievementStore(self.fabric_home, read_only=read_only)

    def snapshot(self) -> MetricSnapshot:
        return collect_metrics(
            self.fabric_home,
            skill_usage_loader=self.skill_usage_loader,
        )

    def summary(self, *, include_current_qualifiers: bool = False) -> dict[str, Any]:
        records = self.store.earned_records(create=not self.read_only)
        return build_summary(
            self.snapshot(),
            records,
            include_current_qualifiers=include_current_qualifiers,
        )

    def refresh(self) -> dict[str, Any]:
        if self.read_only:
            raise RuntimeError("cannot refresh achievements read-only")
        snapshot = self.snapshot()
        appended = self.store.record_unlocks(
            qualifying_milestones(snapshot.metrics), snapshot.metrics
        )
        records = self.store.earned_records()
        summary = build_summary(snapshot, records)
        appended_by_id = {event["achievement_id"]: event for event in appended}
        newly_earned: list[dict[str, Any]] = []
        for milestone in MILESTONES:
            event = appended_by_id.get(milestone.id)
            if event is None:
                continue
            newly_earned.append(
                _milestone_dict(
                    milestone,
                    value=_bounded_counter(snapshot.metrics.get(milestone.metric, 0)),
                    earned_record=event,
                )
            )
        summary["newly_earned"] = newly_earned
        return summary


__all__ = [
    "AchievementEngine",
    "MetricSnapshot",
    "PRIVACY_METADATA",
    "build_summary",
    "collect_metrics",
    "qualifying_milestones",
]
