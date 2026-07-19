"""Behavior contracts for Journey catalog, evidence, ranks, and API."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.achievements.dashboard.plugin_api import router
from plugins.achievements.dashboard import plugin_api
from plugins.achievements.event_store import EventStore
from plugins.achievements.events import Capability, EventDraft, EventType, Outcome
from plugins.achievements.journey_catalog import (
    ACHIEVEMENTS,
    ACHIEVEMENTS_BY_ID,
    DAILY_TEMPLATES,
    RANKS,
)
from plugins.achievements.journey_engine import (
    JourneyEngine,
    JourneySettingsError,
    _periods,
    read_journey_settings,
)
from plugins.achievements.journey_evidence import build_evidence
from plugins.achievements.journey_store import JourneyStore


def _row(
    event_type: EventType,
    capability: Capability,
    when: float,
    *,
    outcome: Outcome = Outcome.SUCCESS,
    session: str = "s",
    turn: str = "t",
    subject: str | None = None,
    duration_ms: int | None = None,
) -> dict:
    return {
        "event_id": f"{event_type.value}-{when}-{subject or ''}",
        "event_type": event_type.value,
        "occurred_at": when,
        "duration_ms": duration_ms,
        "session_ref": session,
        "turn_ref": turn,
        "subject_ref": subject,
        "capability": capability.value,
        "outcome": outcome.value,
        "surface": "cli",
        "provider": "unknown",
        "count": 1,
        "source": "observed_hook",
    }


def test_catalog_can_reach_top_rank_without_preview_claims() -> None:
    launch = [item for item in ACHIEVEMENTS if item.launch and item.rank_eligible]
    assert sum(item.xp for item in launch) >= RANKS[-1].xp
    assert len(launch) >= RANKS[-1].achievements
    assert len({item.path_id for item in launch}) >= RANKS[-1].families
    previews = [item for item in ACHIEVEMENTS if not item.launch]
    assert previews
    assert all(item.xp == 0 and not item.rank_eligible for item in previews)
    browse_daily = next(item for item in DAILY_TEMPLATES if item.id == "daily.browse")
    assert browse_daily.fact_key == "browser_navigation_turns"


def test_memory_requires_recall_after_matching_store() -> None:
    now = time.time()
    recalled_first = _row(
        EventType.CAPABILITY_SUCCEEDED,
        Capability.MEMORY_RECALL,
        now,
        subject="memory-a",
    )
    stored_later = _row(
        EventType.CAPABILITY_SUCCEEDED,
        Capability.MEMORY_STORE,
        now + 1,
        subject="memory-a",
    )
    assert (
        build_evidence([recalled_first, stored_later]).facts["memory_store_recall"] == 0
    )
    recalled_later = {**recalled_first, "occurred_at": now + 2, "event_id": "later"}
    assert (
        build_evidence([stored_later, recalled_later]).facts["memory_store_recall"] == 1
    )


def test_skill_reuse_needs_later_use_not_session_identity() -> None:
    now = time.time()
    authored = _row(
        EventType.CAPABILITY_SUCCEEDED,
        Capability.SKILL_AUTHOR,
        now,
        session="",
        subject="skill-a",
    )
    used = _row(
        EventType.CAPABILITY_SUCCEEDED,
        Capability.SKILL_USE,
        now + 1,
        session="",
        subject="skill-a",
    )
    assert build_evidence([authored, used]).facts["verified_skill_reuse"] == 1


def test_active_turns_cap_at_ten_minutes_and_parallel_needs_ten_minutes() -> None:
    now = time.time()
    events = [
        _row(
            EventType.TURN_STARTED, Capability.CONVERSATION, now, session="a", turn="a1"
        ),
        _row(
            EventType.TURN_COMPLETED,
            Capability.CONVERSATION,
            now + 4 * 3600,
            session="a",
            turn="a1",
        ),
        _row(
            EventType.TURN_STARTED, Capability.CONVERSATION, now, session="b", turn="b1"
        ),
        _row(
            EventType.TURN_COMPLETED,
            Capability.CONVERSATION,
            now + 5 * 60,
            session="b",
            turn="b1",
        ),
    ]
    snapshot = build_evidence(events)
    assert snapshot.facts["focus_blocks"] == 0
    assert snapshot.facts["deep_work_blocks"] == 0
    assert snapshot.facts["parallel_session_runs"] == 0

    events[-1] = {
        **events[-1],
        "occurred_at": now + 20 * 60,
    }
    assert build_evidence(events).facts["parallel_session_runs"] == 1


def test_private_activity_reflection_unions_active_turns_without_rank_xp() -> None:
    now = time.time()
    events = []
    for index in range(3):
        start = now - 1_800 + index * 600
        turn = f"focus-{index}"
        events.extend([
            _row(
                EventType.TURN_STARTED,
                Capability.CONVERSATION,
                start,
                session="focus-session",
                turn=turn,
            ),
            _row(
                EventType.TURN_COMPLETED,
                Capability.CONVERSATION,
                start + 600,
                session="focus-session",
                turn=turn,
            ),
        ])
    facts = build_evidence(events).facts
    assert facts["active_minutes_today"] == 30
    assert facts["active_days_7"] == 1
    assert facts["focus_blocks"] == 1


def test_subagent_concurrency_prefers_matching_start_stop_intervals() -> None:
    now = time.time()
    events = [
        _row(
            EventType.TURN_COMPLETED, Capability.CONVERSATION, now + 20, turn="parent"
        ),
        _row(
            EventType.SUBAGENT_STARTED,
            Capability.AGENT_CREW,
            now,
            turn="parent",
            subject="one",
        ),
        _row(
            EventType.SUBAGENT_STARTED,
            Capability.AGENT_CREW,
            now + 1,
            turn="parent",
            subject="two",
        ),
        _row(
            EventType.SUBAGENT_STARTED,
            Capability.AGENT_CREW,
            now + 2,
            turn="parent",
            subject="three",
        ),
        _row(
            EventType.SUBAGENT_STOPPED,
            Capability.AGENT_CREW,
            now + 10,
            turn="parent",
            subject="one",
            duration_ms=1,
        ),
        _row(
            EventType.SUBAGENT_STOPPED,
            Capability.AGENT_CREW,
            now + 11,
            turn="parent",
            subject="two",
            duration_ms=1,
        ),
        _row(
            EventType.SUBAGENT_STOPPED,
            Capability.AGENT_CREW,
            now + 12,
            turn="parent",
            subject="three",
            duration_ms=1,
        ),
    ]
    assert build_evidence(events).facts["parallel_crew_runs"] == 1


def test_malformed_settings_fail_closed_and_empty_outcome_is_unset(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text("achievements: wrong\n", encoding="utf-8")
    settings = read_journey_settings(tmp_path)
    assert settings["invalid"] is True
    assert settings["tracking_enabled"] is False
    assert settings["active_time_enabled"] is False

    (tmp_path / "config.yaml").write_text(
        "achievements:\n  preferred_outcome: ''\n", encoding="utf-8"
    )
    settings = read_journey_settings(tmp_path)
    assert settings["invalid"] is False
    assert settings["preferred_outcome"] is None

    (tmp_path / "config.yaml").write_text(
        "achievements:\n  tracking_enabled: true\n  raw_event_retention_days: many\n",
        encoding="utf-8",
    )
    settings = read_journey_settings(tmp_path)
    assert settings["invalid"] is True
    assert settings["tracking_enabled"] is False


def test_browser_cua_and_research_require_completed_turn_contracts() -> None:
    now = time.time()
    events = [
        _row(
            EventType.TOOL_SUCCEEDED,
            Capability.BROWSER_NAVIGATION,
            now,
            session="browser-session",
            turn="browser-turn",
        ),
        _row(
            EventType.TOOL_SUCCEEDED,
            Capability.BROWSER,
            now + 1,
            session="browser-session",
            turn="browser-turn",
        ),
        _row(
            EventType.TOOL_SUCCEEDED,
            Capability.BROWSER,
            now + 2,
            session="browser-session",
            turn="browser-turn",
        ),
        _row(
            EventType.TOOL_SUCCEEDED,
            Capability.COMPUTER_USE,
            now + 3,
            session="cua-session",
            turn="cua-turn",
        ),
        _row(
            EventType.TOOL_SUCCEEDED,
            Capability.COMPUTER_USE,
            now + 4,
            session="cua-session",
            turn="cua-turn",
        ),
        _row(
            EventType.TOOL_SUCCEEDED,
            Capability.COMPUTER_USE,
            now + 5,
            session="cua-session",
            turn="cua-turn",
        ),
        _row(
            EventType.TOOL_SUCCEEDED,
            Capability.RESEARCH,
            now + 6,
            turn="research-turn",
        ),
    ]
    before_completion = build_evidence(events).facts
    assert before_completion["browser_navigation_turns"] == 0
    assert before_completion["computer_use_turns"] == 0
    assert before_completion["research_completed_turns"] == 0

    events.extend([
        _row(
            EventType.TURN_COMPLETED,
            Capability.CONVERSATION,
            now + 7,
            session="browser-session",
            turn="browser-turn",
        ),
        _row(
            EventType.TURN_COMPLETED,
            Capability.CONVERSATION,
            now + 8,
            session="cua-session",
            turn="cua-turn",
        ),
        _row(
            EventType.TURN_COMPLETED,
            Capability.CONVERSATION,
            now + 9,
            turn="research-turn",
        ),
    ])
    completed = build_evidence(events).facts
    assert completed["browser_navigation_turns"] == 1
    assert completed["computer_use_turns"] == 1
    assert completed["research_completed_turns"] == 1
    assert ACHIEVEMENTS_BY_ID["research.brief"].launch is False


def test_automation_sequence_streak_and_reliability() -> None:
    now = time.time() - 20 * 86_400
    events = [
        _row(
            EventType.CAPABILITY_SUCCEEDED,
            Capability.AUTOMATION_SCHEDULE,
            now,
            subject="job-a",
        )
    ]
    for day in range(14):
        for run in range(3 if day < 2 else 2):
            events.append(
                _row(
                    EventType.CAPABILITY_SUCCEEDED,
                    Capability.AUTOMATION_RUN,
                    now + (day + 1) * 86_400 + run,
                    subject="job-a",
                )
            )
    events.append(
        _row(
            EventType.CAPABILITY_FAILED,
            Capability.AUTOMATION_RUN,
            now + 15 * 86_400,
            outcome=Outcome.FAILED,
            subject="job-a",
        )
    )
    facts = build_evidence(events).facts
    assert facts["automation_schedule_run"] == 1
    assert facts["automation_run_day_streak"] == 14
    assert facts["automation_runs"] == 30
    assert facts["automation_reliability_percent"] >= 90

    old_success = {
        "day": "2025-01-01",
        "event_type": EventType.CAPABILITY_SUCCEEDED.value,
        "capability": Capability.AUTOMATION_RUN.value,
        "outcome": Outcome.SUCCESS.value,
        "surface": "cron",
        "provider": "unknown",
        "source": "observed_hook",
        "event_count": 100,
        "duration_ms": 0,
    }
    old_failure = {
        **old_success,
        "event_type": EventType.CAPABILITY_FAILED.value,
        "outcome": Outcome.FAILED.value,
        "event_count": 50,
    }
    old_only = build_evidence([], [old_success, old_failure]).facts
    assert old_only["automation_runs"] == 100
    assert old_only["automation_reliability_percent"] == 0


def test_resume_floor_rejects_a_draft_created_while_paused(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "achievements:\n  tracking_enabled: false\n",
        encoding="utf-8",
    )
    paused_draft = EventDraft(
        event_type=EventType.TURN_COMPLETED,
        capability=Capability.CONVERSATION,
        outcome=Outcome.SUCCESS,
        occurred_at=time.time(),
        dedupe_key="paused",
    )
    engine = JourneyEngine(tmp_path)
    assert engine.update_settings({"tracking_enabled": True})["tracking_enabled"]
    store = EventStore(tmp_path)
    assert store.append(paused_draft) is False
    time.sleep(0.001)
    resumed_draft = EventDraft(
        event_type=EventType.TURN_COMPLETED,
        capability=Capability.CONVERSATION,
        outcome=Outcome.SUCCESS,
        occurred_at=time.time(),
        dedupe_key="resumed",
    )
    assert store.append(resumed_draft) is True


def test_durable_pause_marker_overrides_a_stale_true_config(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "achievements:\n  tracking_enabled: true\n",
        encoding="utf-8",
    )
    store = EventStore(tmp_path)
    store.pause_collection()

    assert read_journey_settings(tmp_path)["tracking_enabled"] is False
    resumed = JourneyEngine(tmp_path).update_settings({"tracking_enabled": True})

    assert resumed["tracking_enabled"] is True
    assert store.collection_is_paused() is False


def test_explicit_pause_installs_durable_fence_when_config_is_already_false(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text(
        "achievements:\n  tracking_enabled: false\n",
        encoding="utf-8",
    )
    store = EventStore(tmp_path)
    assert store.collection_is_paused() is False

    paused = JourneyEngine(tmp_path).update_settings({"tracking_enabled": False})

    assert paused["tracking_enabled"] is False
    assert store.collection_is_paused() is True


def test_failed_resume_write_restores_durable_pause(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "config.yaml").write_text(
        "achievements:\n  tracking_enabled: false\n",
        encoding="utf-8",
    )
    engine = JourneyEngine(tmp_path)
    engine.update_settings({"tracking_enabled": False})

    def _fail_write(*_args, **_kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(
        "fabric_cli.config.atomic_config_write",
        _fail_write,
    )

    with pytest.raises(JourneySettingsError):
        engine.update_settings({"tracking_enabled": True})

    assert EventStore(tmp_path).collection_is_paused() is True
    assert read_journey_settings(tmp_path)["tracking_enabled"] is False


def test_paused_summary_still_enforces_raw_retention(
    tmp_path: Path, monkeypatch
) -> None:
    from plugins.achievements import event_store as event_store_module

    base = time.time()
    monkeypatch.setattr(event_store_module.time, "time", lambda: base)
    store = EventStore(tmp_path)
    assert store.append(
        EventDraft(
            event_type=EventType.TURN_COMPLETED,
            capability=Capability.CONVERSATION,
            outcome=Outcome.SUCCESS,
            occurred_at=base,
            dedupe_key="paused-retention",
        )
    )
    (tmp_path / "config.yaml").write_text(
        "achievements:\n"
        "  tracking_enabled: false\n"
        "  active_time_enabled: true\n"
        "  raw_event_retention_days: 1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(event_store_module.time, "time", lambda: base + (2 * 86_400))
    result = JourneyEngine(tmp_path, profile_name="test").summary()

    assert result["tracking"]["state"] == "paused"
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COALESCE(SUM(event_count), 0) FROM event_rollups"
            ).fetchone()[0]
            == 1
        )


def test_journey_first_run_has_no_optional_distractions(tmp_path: Path) -> None:
    result = JourneyEngine(tmp_path, profile_name="test").summary()
    assert result["onboarding"]["is_first_run"] is True
    assert result["today"]["primary"]["id"] == "starter.fabric_basics"
    assert result["starter"]["step_index"] == 0
    assert [step["status"] for step in result["starter"]["steps"]] == [
        "active",
        "unavailable",
        "unavailable",
    ]
    assert result["today"]["optional"] == []
    assert result["today"]["weekly"] is None
    assert len(result["collection"]["active"]) <= 3
    assert len(result["collection"]["discover"]) <= 3


def test_outcomes_project_canonical_paths_and_previews_do_not_block_paths(
    tmp_path: Path,
) -> None:
    engine = JourneyEngine(tmp_path, profile_name="test")
    eligible = [
        item
        for item in ACHIEVEMENTS
        if item.path_id in {"create", "contributor"}
        and item.launch
        and item.rank_eligible
    ]
    engine.store.record_unlocks(eligible, {})

    result = engine.summary()
    outcomes = {
        item["id"]: item["preferred_paths"] for item in result["onboarding"]["outcomes"]
    }
    assert outcomes == {
        "finish_faster": ["conversation", "computer_use", "deep_work"],
        "build_agents": ["agent_crew", "anywhere", "deep_work"],
        "create_content": ["create", "skills", "conversation"],
        "automate_work": ["automate", "skills", "agent_crew"],
    }

    paths = {item["id"]: item for item in result["paths"]}
    for path_id in ("create", "contributor"):
        path = paths[path_id]
        eligible_count = sum(1 for step in path["steps"] if step["rank_eligible"])
        assert any(step["status"] == "preview" for step in path["steps"])
        assert path["progress"] == {
            "current": eligible_count,
            "target": eligible_count,
            "label": f"{eligible_count} of {eligible_count}",
        }
        assert path["status"] == "completed"
        assert path["next_achievement_id"] is None


def test_daily_assignment_uses_baseline_and_is_persisted(tmp_path: Path) -> None:
    engine = JourneyEngine(tmp_path, profile_name="alpha")
    now = time.time()
    event_store = EventStore(tmp_path)
    for index, (event_type, capability) in enumerate((
        (EventType.TURN_COMPLETED, Capability.CONVERSATION),
        (EventType.TOOL_SUCCEEDED, Capability.TOOL),
        (EventType.SUBAGENT_STOPPED, Capability.AGENT_CREW),
    )):
        event_store.append(
            EventDraft(
                event_type=event_type,
                capability=capability,
                outcome=Outcome.SUCCESS,
                occurred_at=now + index * 0.01,
                duration_ms=10_000
                if event_type is EventType.SUBAGENT_STOPPED
                else None,
                raw_session_ref="parent",
                raw_turn_ref="turn",
                raw_subject_ref=f"subject-{index}",
                dedupe_key=f"event-{index}",
            )
        )
    # Parent completion after subagent stop makes the delegate authoritative.
    event_store.append(
        EventDraft(
            event_type=EventType.TURN_COMPLETED,
            capability=Capability.CONVERSATION,
            outcome=Outcome.SUCCESS,
            occurred_at=now + 1,
            raw_session_ref="parent",
            raw_turn_ref="turn",
            dedupe_key="parent-complete",
        )
    )
    first = engine.summary()
    assert first["starter"]["status"] == "completed"
    daily = first["today"]["primary"]
    assert daily["progress"]["current"] == 0
    assert daily["momentum"] == 10
    assert daily["snoozeable"] is True
    assert daily["reroll_available"] is True
    second = engine.summary()
    assert second["today"]["primary"]["id"] == daily["id"]
    assert second["today"]["primary"]["progress"]["current"] == 0

    rerolled = engine.reroll("daily")
    rerolled_daily = rerolled["today"]["primary"]
    assert rerolled_daily["id"] != daily["id"]
    assert rerolled_daily["reroll_available"] is False

    after_snooze = engine.snooze(rerolled_daily["id"], 7)
    assert after_snooze["today"]["primary"]["id"] != rerolled_daily["id"]
    assert after_snooze["snooze"]["quest_id"] == rerolled_daily["id"]
    assert after_snooze["schema_version"] == 2
    assert (
        engine.store.assignment("daily", time.strftime("%Y-%m-%d", time.localtime()))[
            "status"
        ]
        == "active"
    )


def test_weekly_reroll_requires_a_genuinely_different_capability_pair(
    tmp_path: Path, monkeypatch
) -> None:
    engine = JourneyEngine(tmp_path, profile_name="alpha")
    _daily_key, weekly_key, _season_id = _periods()
    engine.store.create_assignment(
        kind="weekly",
        period_key=weekly_key,
        template_id="weekly.cross_capability",
        path_id="anywhere",
        capability="agent_crew",
        secondary_capability="conversation",
        baseline_count=0,
        target_delta=3,
    )
    monkeypatch.setattr(
        engine,
        "_availability",
        lambda _evidence: frozenset({"agent_crew", "conversation"}),
    )

    with pytest.raises(ValueError, match="no alternative weekly challenge"):
        engine.reroll("weekly")

    unchanged = engine.store.assignment("weekly", weekly_key)
    assert unchanged is not None
    assert unchanged["reroll_count"] == 0

    monkeypatch.setattr(
        engine,
        "_availability",
        lambda _evidence: frozenset({"agent_crew", "conversation", "skills"}),
    )
    engine.reroll("weekly")
    changed = engine.store.assignment("weekly", weekly_key)
    assert changed is not None
    assert changed["reroll_count"] == 1
    assert frozenset({
        changed["capability"],
        changed["secondary_capability"],
    }) != frozenset({"agent_crew", "conversation"})


def test_cross_profile_leaderboard_ignores_unknown_unlock_xp(
    tmp_path: Path, monkeypatch
) -> None:
    current_home = tmp_path / "current"
    other_home = tmp_path / "other"
    JourneyStore(other_home).record_marker("starter.tool_assist", 1)
    with EventStore(other_home).connection() as connection:
        connection.execute(
            """INSERT INTO journey_unlocks (
                   achievement_id, earned_at, xp, confidence, evidence_kind,
                   evidence_count, evaluator_version
               ) VALUES ('conversation.first_thread', ?, 50, 'observed', 'turn', 1, 1)""",
            (time.time(),),
        )
        connection.execute(
            """INSERT INTO journey_unlocks (
                   achievement_id, earned_at, xp, confidence, evidence_kind,
                   evidence_count, evaluator_version
               ) VALUES ('unknown.corrupt', ?, 9999, 'observed', 'unknown', 1, 1)""",
            (time.time(),),
        )
        connection.executemany(
            """INSERT INTO journey_unlocks (
                   achievement_id, earned_at, xp, confidence, evidence_kind,
                   evidence_count, evaluator_version
               ) VALUES (?, ?, 9999, 'observed', 'unknown', 1, 1)""",
            [(f"unknown.corrupt.{index}", time.time()) for index in range(500)],
        )
        connection.commit()
    monkeypatch.setattr(
        plugin_api,
        "_profile_candidates",
        lambda _name, _home: [
            ("current", current_home, True),
            ("other", other_home, False),
        ],
    )
    board = plugin_api._journey_leaderboard(
        "current",
        current_home,
        {
            "mastery": {},
            "today": {"momentum": {"points": 0, "season_id": "S0"}},
        },
    )
    assert board["profiles"][0]["xp"] == 50


def test_profile_candidates_are_hard_bounded(tmp_path: Path, monkeypatch) -> None:
    requested: list[int | None] = []

    def _many_profiles(*, multiplex: bool, max_profiles: int | None = None):
        assert multiplex is True
        requested.append(max_profiles)
        return [
            (f"profile-{index}", tmp_path / f"profile-{index}") for index in range(500)
        ]

    monkeypatch.setattr(plugin_api, "profiles_to_serve", _many_profiles)
    candidates = plugin_api._profile_candidates("current", tmp_path / "current")

    assert requested == [plugin_api.MAX_LOCAL_LEADERBOARD_PROFILES]
    assert len(candidates) == plugin_api.MAX_LOCAL_LEADERBOARD_PROFILES


def test_api_settings_attestation_export_and_confirmed_delete(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    EventStore(tmp_path).append(
        EventDraft(
            event_type=EventType.TURN_COMPLETED,
            capability=Capability.CONVERSATION,
            outcome=Outcome.SUCCESS,
            occurred_at=time.time(),
            raw_session_ref="api-session",
            raw_turn_ref="api-turn",
            dedupe_key="api-first-turn",
        )
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/plugins/achievements")
    client = TestClient(app)

    journey = client.get("/api/plugins/achievements/journey")
    assert journey.status_code == 200
    assert set(journey.json()["leaderboard"]) >= {"you", "profiles", "friendly"}
    assert [item["id"] for item in journey.json()["newly_earned"]] == [
        "conversation.first_thread"
    ]

    bad = client.patch("/api/plugins/achievements/settings", json={"unknown": True})
    assert bad.status_code == 422
    changed = client.patch(
        "/api/plugins/achievements/settings",
        json={"preferred_outcome": "build_agents", "celebration_mode": "quiet"},
    )
    assert changed.status_code == 200
    assert changed.json()["settings"]["preferred_outcome"] == "build_agents"

    attested = client.post(
        "/api/plugins/achievements/quests/content.linkedin_launch/attest"
    )
    assert attested.status_code == 200
    assert attested.json()["confidence"] == "self_attested"
    assert attested.json()["xp"] == 0
    assert (
        client.post(
            "/api/plugins/achievements/quests/contribution.fabric_contributor/attest"
        ).status_code
        == 400
    )

    exported = client.get("/api/plugins/achievements/activity/export")
    assert exported.status_code == 200
    assert "events" in exported.json()
    assert (
        client.request(
            "DELETE", "/api/plugins/achievements/activity", json={"confirm": False}
        ).status_code
        == 400
    )
    deleted = client.request(
        "DELETE", "/api/plugins/achievements/activity", json={"confirm": True}
    )
    assert deleted.status_code == 200
    assert deleted.json()["unlocks_preserved"] is True
