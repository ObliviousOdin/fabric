"""Fabric-owned achievement catalog.

The catalog is deliberately data-only.  Every track has the same three-tier
shape so scoring stays predictable while the underlying metrics can evolve
independently of the dashboard presentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable


@dataclass(frozen=True)
class Milestone:
    """One earnable tier within a metric track."""

    id: str
    track_id: str
    category: str
    metric: str
    tier: str
    title: str
    description: str
    threshold: int
    points: int


@dataclass(frozen=True)
class Track:
    """A metric and its ordered Thread, Weave, and Loom milestones."""

    id: str
    title: str
    category: str
    metric: str
    milestones: tuple[Milestone, ...]


_TIER_POINTS: Final[tuple[tuple[str, int], ...]] = (
    ("Thread", 10),
    ("Weave", 25),
    ("Loom", 50),
)


def _track(
    track_id: str,
    title: str,
    category: str,
    metric: str,
    unit: str,
    thresholds: tuple[int, int, int],
    titles: tuple[str, str, str],
) -> Track:
    milestones = tuple(
        Milestone(
            id=f"{track_id}.{tier.lower()}",
            track_id=track_id,
            category=category,
            metric=metric,
            tier=tier,
            title=milestone_title,
            description=f"Reach {threshold:,} {unit}.",
            threshold=threshold,
            points=points,
        )
        for (tier, points), threshold, milestone_title in zip(
            _TIER_POINTS, thresholds, titles
        )
    )
    return Track(
        id=track_id,
        title=title,
        category=category,
        metric=metric,
        milestones=milestones,
    )


TRACKS: Final[tuple[Track, ...]] = (
    _track(
        "session_horizons",
        "Session Horizons",
        "rhythm",
        "total_sessions",
        "sessions with activity",
        (1, 25, 100),
        ("First Tension", "Steady Shuttle", "Enduring Cloth"),
    ),
    _track(
        "active_calendar",
        "Active Calendar",
        "rhythm",
        "active_days_utc",
        "active UTC days",
        (1, 7, 30),
        ("Daymark", "Weekgrain", "Monthfield"),
    ),
    _track(
        "continuity_chain",
        "Continuity Chain",
        "rhythm",
        "longest_active_streak_utc",
        "consecutive active UTC days",
        (2, 7, 21),
        ("Linked Dawn", "Unbroken Span", "Seasoned Run"),
    ),
    _track(
        "dialogue_volume",
        "Dialogue Volume",
        "craft",
        "total_messages",
        "session messages",
        (10, 250, 1_000),
        ("Opening Exchange", "Running Dialogue", "Living Archive"),
    ),
    _track(
        "toolwork",
        "Toolwork",
        "craft",
        "total_tool_calls",
        "tool calls",
        (3, 100, 500),
        ("Hand Tool", "Full Bench", "Workshop Hum"),
    ),
    _track(
        "model_rounds",
        "Model Rounds",
        "craft",
        "total_api_calls",
        "model API calls",
        (5, 200, 1_000),
        ("First Turn", "Long Circuit", "Deep Current"),
    ),
    _track(
        "surface_range",
        "Surface Range",
        "range",
        "distinct_sources",
        "distinct conversation surfaces",
        (2, 4, 8),
        ("Side Door", "Many Rooms", "Whole House"),
    ),
    _track(
        "model_range",
        "Model Range",
        "range",
        "distinct_models",
        "distinct models",
        (2, 5, 12),
        ("New Lens", "Prism Rack", "Lens Library"),
    ),
    _track(
        "conversation_depth",
        "Conversation Depth",
        "range",
        "messages_per_session",
        "average messages per active session",
        (4, 12, 30),
        ("Thoughtful Thread", "Layered Exchange", "Deep Dialogue"),
    ),
    _track(
        "scheduled_work",
        "Scheduled Work",
        "automation",
        "cron_runs",
        "completed cron sessions",
        (1, 10, 50),
        ("Clock Set", "Reliable Cadence", "Quiet Machinery"),
    ),
    _track(
        "delegated_work",
        "Delegated Work",
        "automation",
        "delegated_runs",
        "delegated sessions",
        (1, 10, 50),
        ("Second Pair", "Small Crew", "Agent Ensemble"),
    ),
    _track(
        "automation_mix",
        "Automation Mix",
        "automation",
        "automation_runs",
        "scheduled or delegated runs",
        (3, 30, 150),
        ("Dual Motion", "Workflow Mesh", "Autonomous Fabric"),
    ),
    _track(
        "compression_care",
        "Compression Care",
        "stewardship",
        "compressed_conversations",
        "conversation compressions",
        (1, 5, 20),
        ("Folded Context", "Packed Continuity", "Long Memory"),
    ),
    _track(
        "archive_care",
        "Archive Care",
        "stewardship",
        "archived_sessions",
        "archived sessions",
        (1, 10, 50),
        ("Tidy Shelf", "Curated Cabinet", "Deep Archive"),
    ),
    _track(
        "daily_density",
        "Daily Density",
        "stewardship",
        "sessions_per_active_day",
        "average active sessions per active day",
        (2, 5, 12),
        ("Busy Day", "Focused Rhythm", "Session Storm"),
    ),
    _track(
        "skill_invocations",
        "Skill Invocations",
        "skills",
        "skill_use_count",
        "recorded skill uses",
        (1, 25, 100),
        ("Skill Spark", "Practice Loop", "Fluent Hands"),
    ),
    _track(
        "skill_breadth",
        "Skill Breadth",
        "skills",
        "distinct_skills_used",
        "skills used at least once",
        (1, 5, 15),
        ("First Technique", "Mixed Toolkit", "Capability Garden"),
    ),
    _track(
        "skill_care",
        "Skill Care",
        "skills",
        "skill_activity_total",
        "skill use, view, or patch events",
        (5, 75, 300),
        ("Studied Move", "Craft Notes", "Living Playbook"),
    ),
)


def iter_milestones() -> Iterable[Milestone]:
    for track in TRACKS:
        yield from track.milestones


MILESTONES: Final[tuple[Milestone, ...]] = tuple(iter_milestones())
MILESTONES_BY_ID: Final[dict[str, Milestone]] = {
    milestone.id: milestone for milestone in MILESTONES
}
CATEGORIES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(track.category for track in TRACKS)
)
TOTAL_POINTS: Final[int] = sum(milestone.points for milestone in MILESTONES)


def _validate_catalog() -> None:
    track_ids = [track.id for track in TRACKS]
    milestone_ids = [milestone.id for milestone in MILESTONES]
    if len(track_ids) != len(set(track_ids)):
        raise ValueError("achievement track ids must be unique")
    if len(milestone_ids) != len(set(milestone_ids)):
        raise ValueError("achievement milestone ids must be unique")
    for track in TRACKS:
        if tuple(m.tier for m in track.milestones) != tuple(
            tier for tier, _points in _TIER_POINTS
        ):
            raise ValueError(f"{track.id}: tiers must be Thread, Weave, Loom")
        if tuple(m.points for m in track.milestones) != tuple(
            points for _tier, points in _TIER_POINTS
        ):
            raise ValueError(f"{track.id}: tier points do not match the contract")
        thresholds = [m.threshold for m in track.milestones]
        if thresholds != sorted(thresholds) or len(set(thresholds)) != len(thresholds):
            raise ValueError(f"{track.id}: thresholds must increase strictly")
        if any(m.metric != track.metric for m in track.milestones):
            raise ValueError(f"{track.id}: milestone metric drift")


_validate_catalog()


__all__ = [
    "CATEGORIES",
    "MILESTONES",
    "MILESTONES_BY_ID",
    "TOTAL_POINTS",
    "TRACKS",
    "Milestone",
    "Track",
    "iter_milestones",
]
