"""Behavior and privacy contracts for the Fabric achievements backend."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.achievements.catalog import (
    MILESTONES,
    MILESTONES_BY_ID,
    TRACKS,
)
from plugins.achievements.dashboard.plugin_api import router
from plugins.achievements.engine import (
    AchievementEngine,
    MetricSnapshot,
    build_summary,
    collect_metrics,
)
from plugins.achievements.share_cards import (
    MAX_SHARE_CARD_BYTES,
    ShareCardValidationError,
    create_share_card,
    parse_share_card,
    sanitize_display_name,
    serialize_share_card,
    validate_share_card,
)
from plugins.achievements.store import (
    AchievementStateError,
    AchievementStore,
    STATE_DIRNAME,
)


_SESSION_SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    model TEXT,
    model_config TEXT,
    started_at REAL NOT NULL,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    api_call_count INTEGER DEFAULT 0,
    end_reason TEXT,
    archived INTEGER DEFAULT 0,
    title TEXT,
    user_id TEXT,
    chat_id TEXT,
    estimated_cost_usd REAL,
    input_tokens INTEGER
)
"""


def _epoch(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()


def _create_state_db(home: Path, rows: list[dict] | None = None) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    db_path = home / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(_SESSION_SCHEMA)
        for index, row in enumerate(rows or []):
            values = {
                "id": f"session-{index}",
                "source": "cli",
                "model": None,
                "model_config": None,
                "started_at": _epoch(2026, 1, 1),
                "message_count": 0,
                "tool_call_count": 0,
                "api_call_count": 0,
                "end_reason": None,
                "archived": 0,
                "title": "private title",
                "user_id": "private user",
                "chat_id": "private chat",
                "estimated_cost_usd": 999.0,
                "input_tokens": 999_999,
            }
            values.update(row)
            connection.execute(
                """INSERT INTO sessions (
                    id, source, model, model_config, started_at,
                    message_count, tool_call_count, api_call_count,
                    end_reason, archived, title, user_id, chat_id,
                    estimated_cost_usd, input_tokens
                ) VALUES (
                    :id, :source, :model, :model_config, :started_at,
                    :message_count, :tool_call_count, :api_call_count,
                    :end_reason, :archived, :title, :user_id, :chat_id,
                    :estimated_cost_usd, :input_tokens
                )""",
                values,
            )
    return db_path


@pytest.fixture
def fabric_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".fabric"
    home.mkdir()
    monkeypatch.setenv("FABRIC_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return home


@pytest.fixture
def populated_home(fabric_home: Path) -> Path:
    _create_state_db(
        fabric_home,
        [
            {
                "source": "cli",
                "model": "model-a",
                "started_at": _epoch(2026, 1, 1),
                "message_count": 10,
                "tool_call_count": 2,
                "api_call_count": 3,
            },
            {
                "source": "cron",
                "model": "model-b",
                "started_at": _epoch(2026, 1, 2),
                "message_count": 4,
                "tool_call_count": 1,
                "api_call_count": 2,
                "end_reason": "compression",
            },
            {
                "source": "telegram",
                "model": "model-a",
                "model_config": json.dumps(
                    {"_delegate_from": "secret-parent-value", "private": "ignore me"}
                ),
                "started_at": _epoch(2026, 1, 4),
                "message_count": 6,
                "api_call_count": 1,
                "archived": 1,
            },
            {
                "source": "cron",
                "model": "model-c",
                "model_config": "not valid json",
                "started_at": _epoch(2026, 1, 5),
                "message_count": 0,
                "archived": 1,
            },
        ],
    )
    return fabric_home


@pytest.fixture
def api_client(populated_home: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/plugins/achievements")
    return TestClient(app)


def _empty_card(**updates) -> dict:
    card = {
        "schema_version": 1,
        "card_id": str(uuid.uuid4()),
        "display_name": "Local Weaver",
        "generated_at": "2026-07-19T12:00:00Z",
        "score": 0,
        "earned_count": 0,
        "category_totals": {},
    }
    card.update(updates)
    return card


# ---------------------------------------------------------------------------
# Catalog and engine contracts
# ---------------------------------------------------------------------------


def test_catalog_is_three_ordered_tiers_with_deterministic_points() -> None:
    assert TRACKS
    assert len({track.id for track in TRACKS}) == len(TRACKS)
    assert len({track.metric for track in TRACKS}) == len(TRACKS)
    assert len(MILESTONES_BY_ID) == len(MILESTONES)
    for track in TRACKS:
        assert [item.tier for item in track.milestones] == ["Thread", "Weave", "Loom"]
        assert [item.points for item in track.milestones] == [10, 25, 50]
        thresholds = [item.threshold for item in track.milestones]
        assert thresholds == sorted(set(thresholds))
        assert all(item.metric == track.metric for item in track.milestones)
        assert all(item.title and item.description for item in track.milestones)


def test_collect_metrics_uses_session_aggregates_and_safe_skill_counts(
    populated_home: Path,
) -> None:
    usage = {
        "one": {"use_count": 3, "view_count": 4, "patch_count": 1, "last_used_at": "private"},
        "two": {"use_count": 2, "view_count": 0, "patch_count": 2},
        "bad": {"use_count": -100, "view_count": math.inf, "patch_count": "bad"},
    }
    snapshot = collect_metrics(populated_home, skill_usage_loader=lambda _home: usage)
    assert snapshot.warnings == ()
    assert snapshot.metrics == {
        "total_sessions": 3,
        "active_days_utc": 3,
        "longest_active_streak_utc": 2,
        "total_messages": 20,
        "total_tool_calls": 3,
        "total_api_calls": 6,
        "distinct_sources": 3,
        "distinct_models": 2,
        "cron_runs": 1,
        "delegated_runs": 1,
        "compressed_conversations": 1,
        "archived_sessions": 2,
        "skill_use_count": 5,
        "skill_view_count": 4,
        "skill_patch_count": 3,
        "distinct_skills_used": 2,
        "messages_per_session": 6,
        "sessions_per_active_day": 1,
        "automation_runs": 2,
        "skill_activity_total": 12,
    }


def test_active_days_are_bucketed_in_utc(fabric_home: Path) -> None:
    _create_state_db(
        fabric_home,
        [
            {"started_at": _epoch(2026, 2, 1, 23), "message_count": 1},
            {"started_at": _epoch(2026, 2, 2, 0), "message_count": 1},
            {"started_at": _epoch(2026, 2, 4, 0), "message_count": 1},
        ],
    )
    metrics = collect_metrics(fabric_home, skill_usage_loader=lambda _home: {}).metrics
    assert metrics["active_days_utc"] == 3
    assert metrics["longest_active_streak_utc"] == 2


def test_collect_metrics_tolerates_unreconciled_legacy_session_columns(
    fabric_home: Path,
) -> None:
    db_path = fabric_home / "state.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                source TEXT,
                started_at REAL,
                message_count INTEGER DEFAULT 0
            )"""
        )
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?)",
            ("legacy-session", "cli", _epoch(2025, 12, 31), 7),
        )

    snapshot = collect_metrics(fabric_home, skill_usage_loader=lambda _home: {})

    assert "session_store_unreadable" not in snapshot.warnings
    assert snapshot.metrics["total_sessions"] == 1
    assert snapshot.metrics["total_messages"] == 7
    assert snapshot.metrics["active_days_utc"] == 1
    assert snapshot.metrics["distinct_sources"] == 1
    assert snapshot.metrics["total_tool_calls"] == 0
    assert snapshot.metrics["total_api_calls"] == 0
    assert snapshot.metrics["delegated_runs"] == 0
    assert snapshot.metrics["compressed_conversations"] == 0
    assert snapshot.metrics["archived_sessions"] == 0


def test_missing_state_db_degrades_to_zero_metrics(fabric_home: Path) -> None:
    snapshot = collect_metrics(fabric_home, skill_usage_loader=lambda _home: {})
    assert snapshot.metrics["total_sessions"] == 0
    assert snapshot.warnings == ("session_store_unavailable",)


def test_refresh_unlocks_once_and_history_pruning_does_not_relock(
    populated_home: Path,
) -> None:
    engine = AchievementEngine(populated_home, skill_usage_loader=lambda _home: {})
    first = engine.refresh()
    assert first["newly_earned"]
    earned_ids = {
        milestone["id"]
        for track in first["tracks"]
        for milestone in track["milestones"]
        if milestone["earned"]
    }
    second = engine.refresh()
    assert second["newly_earned"] == []

    with sqlite3.connect(populated_home / "state.db") as connection:
        connection.execute("DELETE FROM sessions")
    after_prune = engine.refresh()
    still_earned = {
        milestone["id"]
        for track in after_prune["tracks"]
        for milestone in track["milestones"]
        if milestone["earned"]
    }
    assert still_earned == earned_ids
    assert after_prune["score"] == first["score"]


def test_build_summary_can_evaluate_current_qualifiers_without_persistence() -> None:
    metrics = {track.metric: track.milestones[-1].threshold for track in TRACKS}
    summary = build_summary(
        MetricSnapshot(metrics=metrics), {}, include_current_qualifiers=True
    )
    assert summary["earned_count"] == len(MILESTONES)
    assert all(
        milestone["earned"]
        for track in summary["tracks"]
        for milestone in track["milestones"]
    )


# ---------------------------------------------------------------------------
# Ledger and leaderboard store contracts
# ---------------------------------------------------------------------------


def test_card_id_is_stable_across_store_instances(fabric_home: Path) -> None:
    first = AchievementStore(fabric_home).card_id()
    second = AchievementStore(fabric_home).card_id()
    assert first == second
    assert str(uuid.UUID(str(first))) == first


def test_concurrent_unlock_recording_is_deduplicated(fabric_home: Path) -> None:
    milestones = list(MILESTONES[:6])
    metrics = {milestone.metric: milestone.threshold for milestone in milestones}
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            AchievementStore(fabric_home).record_unlocks(milestones, metrics)
        except BaseException as exc:  # pragma: no cover - assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    ledger = AchievementStore(fabric_home).read_ledger()
    assert ledger is not None
    assert [event["achievement_id"] for event in ledger["events"]] == [
        milestone.id for milestone in milestones
    ]


def test_atomic_write_failure_preserves_previous_ledger(
    fabric_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AchievementStore(fabric_home)
    store.card_id()
    before = store.ledger_path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        store.record_unlocks([MILESTONES[0]], {MILESTONES[0].metric: 999})
    assert store.ledger_path.read_bytes() == before


def test_unknown_ledger_version_fails_closed(fabric_home: Path) -> None:
    store = AchievementStore(fabric_home)
    store.root.mkdir(parents=True)
    store.ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "profile_card_id": str(uuid.uuid4()),
                "created_at": "2026-01-01T00:00:00Z",
                "events": [],
            }
        )
    )
    with pytest.raises(AchievementStateError):
        store.read_ledger()


def test_read_only_store_never_creates_state(fabric_home: Path) -> None:
    store = AchievementStore(fabric_home, read_only=True)
    assert store.read_ledger(create=False) is None
    assert not (fabric_home / STATE_DIRNAME).exists()


def test_import_reset_preserves_ledger_bytes(fabric_home: Path) -> None:
    store = AchievementStore(fabric_home)
    store.record_unlocks([MILESTONES[0]], {MILESTONES[0].metric: 999})
    ledger_before = store.ledger_path.read_bytes()
    store.upsert_import(_empty_card())
    assert store.reset_imports() == 1
    assert store.list_imports() == []
    assert store.ledger_path.read_bytes() == ledger_before


# ---------------------------------------------------------------------------
# Share-card schema and privacy contracts
# ---------------------------------------------------------------------------


def test_display_name_sanitization_is_bounded_and_control_free() -> None:
    assert sanitize_display_name("  Alice\n\tWeaver  ") == "Alice Weaver"
    with pytest.raises(ShareCardValidationError):
        sanitize_display_name(" ")
    with pytest.raises(ShareCardValidationError):
        sanitize_display_name("x" * 41)


def test_share_card_round_trip_is_canonical_and_within_limit() -> None:
    card = validate_share_card(_empty_card(display_name="  Local\nWeaver "))
    assert card["display_name"] == "Local Weaver"
    serialized = serialize_share_card(card)
    assert len(serialized.encode("utf-8")) <= MAX_SHARE_CARD_BYTES
    assert parse_share_card(serialized) == card


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": True},
        {"schema_version": 2},
        {"score": math.nan},
        {"score": math.inf},
        {"earned_count": -1},
        {"category_totals": {"not-a-category": 0}},
        {"generated_at": "not-a-date"},
        {"card_id": "not-a-uuid"},
    ],
)
def test_share_card_rejects_unknown_types_and_bounds(mutation: dict) -> None:
    with pytest.raises(ShareCardValidationError):
        validate_share_card(_empty_card(**mutation))


def test_share_card_rejects_duplicate_json_keys_and_oversized_payload() -> None:
    raw = serialize_share_card(_empty_card())
    duplicate = raw[:-1] + ',"score":0}'
    with pytest.raises(ShareCardValidationError, match="duplicate key"):
        parse_share_card(duplicate)
    with pytest.raises(ShareCardValidationError, match="16 KiB"):
        parse_share_card(b"{" + b" " * MAX_SHARE_CARD_BYTES + b"}")


def test_share_card_validates_catalog_highlights_and_category_sum() -> None:
    milestone = MILESTONES[0]
    card = _empty_card(
        score=milestone.points,
        earned_count=1,
        category_totals={milestone.category: milestone.points},
        achievement_ids=[milestone.id],
    )
    assert validate_share_card(card)["achievement_ids"] == [milestone.id]
    with pytest.raises(ShareCardValidationError):
        validate_share_card({**card, "achievement_ids": ["missing.id"]})
    with pytest.raises(ShareCardValidationError):
        validate_share_card({**card, "achievement_ids": [[milestone.id]]})
    with pytest.raises(ShareCardValidationError):
        validate_share_card({**card, "category_totals": {milestone.category: 0}})


def test_create_share_card_only_accepts_earned_highlights() -> None:
    milestone = MILESTONES[0]
    summary = build_summary(
        MetricSnapshot(metrics={milestone.metric: milestone.threshold}),
        {},
        include_current_qualifiers=True,
    )
    card = create_share_card(
        summary,
        card_id=str(uuid.uuid4()),
        display_name="Tester",
        achievement_ids=[milestone.id],
    )
    assert card["achievement_ids"] == [milestone.id]
    unearned = next(item.id for item in MILESTONES if item.id != milestone.id)
    with pytest.raises(ShareCardValidationError, match="already be earned"):
        create_share_card(
            summary,
            card_id=str(uuid.uuid4()),
            display_name="Tester",
            achievement_ids=[unearned],
        )


def test_metric_reader_has_no_messages_table_or_private_column_dependency(
    populated_home: Path,
) -> None:
    # The fixture intentionally has no messages table.  Private session fields
    # contain values that must not influence or appear in the result.
    snapshot = collect_metrics(populated_home, skill_usage_loader=lambda _home: {})
    encoded = json.dumps(snapshot.metrics, sort_keys=True)
    for private_value in (
        "private title",
        "private user",
        "private chat",
        "secret-parent-value",
        "999999",
    ):
        assert private_value not in encoded


def test_summary_publishes_explicit_privacy_metadata(populated_home: Path) -> None:
    summary = AchievementEngine(
        populated_home, skill_usage_loader=lambda _home: {}
    ).summary()
    privacy = summary["privacy"]
    assert privacy["session_table_only"] is True
    assert privacy["session_content_accessed"] is False
    assert privacy["network_access"] is False
    assert set(privacy["skill_usage_fields"]) == {
        "use_count",
        "view_count",
        "patch_count",
    }
    assert {"content", "reasoning", "tool_arguments", "cost", "tokens"} <= set(
        privacy["excluded_fields"]
    )


# ---------------------------------------------------------------------------
# Dashboard API contracts
# ---------------------------------------------------------------------------


def test_summary_and_refresh_api_are_idempotent(api_client: TestClient) -> None:
    before = api_client.get("/api/plugins/achievements/summary")
    assert before.status_code == 200
    assert before.json()["privacy"]["network_access"] is False
    assert before.json()["score"] > 0
    records_after_first_load = AchievementStore().earned_records()
    again = api_client.get("/api/plugins/achievements/summary")
    assert again.status_code == 200
    assert again.json()["score"] == before.json()["score"]
    assert AchievementStore().earned_records() == records_after_first_load
    first = api_client.post("/api/plugins/achievements/refresh")
    second = api_client.post("/api/plugins/achievements/refresh")
    assert first.status_code == second.status_code == 200
    assert first.json()["newly_earned"] == []
    assert second.json()["newly_earned"] == []
    assert second.json()["score"] == first.json()["score"]


def test_dashboard_api_scopes_progress_and_imports_to_requested_profile(
    api_client: TestClient, populated_home: Path
) -> None:
    research_home = populated_home / "profiles" / "research"
    _create_state_db(
        research_home,
        [{"message_count": 42, "tool_call_count": 9, "api_call_count": 5}],
    )
    default_store = AchievementStore(populated_home)
    research_store = AchievementStore(research_home)
    assert not default_store.ledger_path.exists()
    assert not research_store.ledger_path.exists()

    summary = api_client.get(
        "/api/plugins/achievements/summary?profile=research"
    )
    assert summary.status_code == 200
    assert summary.json()["metrics"]["total_sessions"] == 1
    assert summary.json()["metrics"]["total_messages"] == 42
    assert research_store.ledger_path.is_file()
    assert not default_store.ledger_path.exists()

    shared = api_client.post(
        "/api/plugins/achievements/share-card?profile=research",
        json={"display_name": "Research Weaver"},
    )
    assert shared.status_code == 200
    assert research_store.local_display_name("fallback", create=False) == "Research Weaver"

    card = _empty_card(display_name="Research Peer")
    imported = api_client.post(
        "/api/plugins/achievements/leaderboard/import?profile=research",
        json=card,
    )
    assert imported.status_code == 200
    assert research_store.list_imports() == [card]
    assert default_store.list_imports(create=False) == []
    research_board = api_client.get(
        "/api/plugins/achievements/leaderboard?profile=research"
    ).json()
    default_board = api_client.get(
        "/api/plugins/achievements/leaderboard?profile=default"
    ).json()
    assert any(
        entry["card"]["card_id"] == card["card_id"]
        for entry in research_board["entries"]
    )
    assert all(
        entry["card"]["card_id"] != card["card_id"]
        for entry in default_board["entries"]
    )

    deleted = api_client.delete(
        f"/api/plugins/achievements/leaderboard/{card['card_id']}?profile=research"
    )
    assert deleted.json() == {"ok": True, "deleted": True}
    assert research_store.list_imports() == []

    missing = api_client.get(
        "/api/plugins/achievements/summary?profile=does-not-exist"
    )
    assert missing.status_code == 404


def test_share_card_api_reuses_profile_card_id(api_client: TestClient) -> None:
    first = api_client.post(
        "/api/plugins/achievements/share-card", json={"display_name": "Alice"}
    )
    second = api_client.post(
        "/api/plugins/achievements/share-card", json={"display_name": "Alice 2"}
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["card"]["score"] > 0
    assert first.json()["card"]["card_id"] == second.json()["card"]["card_id"]
    assert second.json()["card"]["display_name"] == "Alice 2"
    assert AchievementStore().earned_records()


def test_leaderboard_import_upserts_and_delete_removes(api_client: TestClient) -> None:
    card = _empty_card(display_name="Peer")
    first = api_client.post("/api/plugins/achievements/leaderboard/import", json=card)
    assert first.status_code == 200
    assert first.json()["created"] is True
    updated = {**card, "display_name": "Peer Updated"}
    second = api_client.post("/api/plugins/achievements/leaderboard/import", json=updated)
    assert second.status_code == 200
    assert second.json()["created"] is False
    board = api_client.get("/api/plugins/achievements/leaderboard").json()
    imported = [entry for entry in board["entries"] if entry["origin"] == "self_reported_import"]
    assert len(imported) == 1
    assert imported[0]["card"]["display_name"] == "Peer Updated"
    deleted = api_client.delete(
        f"/api/plugins/achievements/leaderboard/{card['card_id']}"
    )
    assert deleted.json() == {"ok": True, "deleted": True}


def test_import_api_enforces_payload_cap(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/plugins/achievements/leaderboard/import",
        content=b"{" + b" " * MAX_SHARE_CARD_BYTES + b"}",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_import_api_bounds_chunked_body_without_content_length(
    api_client: TestClient,
) -> None:
    def chunks():
        yield b"{"
        yield b" " * MAX_SHARE_CARD_BYTES
        yield b"}"

    response = api_client.post(
        "/api/plugins/achievements/leaderboard/import",
        content=chunks(),
        headers={"content-type": "application/json", "transfer-encoding": "chunked"},
    )
    assert response.status_code == 413


def test_reset_is_confirmed_import_only_and_preserves_progress(
    api_client: TestClient, populated_home: Path
) -> None:
    api_client.post("/api/plugins/achievements/refresh")
    ledger_path = AchievementStore(populated_home).ledger_path
    ledger_before = ledger_path.read_bytes()
    api_client.post("/api/plugins/achievements/leaderboard/import", json=_empty_card())
    unconfirmed = api_client.post(
        "/api/plugins/achievements/reset",
        json={"scope": "imported_leaderboard", "confirm": False},
    )
    assert unconfirmed.status_code == 400
    reset = api_client.post(
        "/api/plugins/achievements/reset",
        json={"scope": "imported_leaderboard", "confirm": True},
    )
    assert reset.status_code == 200
    assert reset.json() == {
        "ok": True,
        "scope": "imported_leaderboard",
        "removed": 1,
        "progress_preserved": True,
    }
    assert ledger_path.read_bytes() == ledger_before
    assert api_client.get("/api/plugins/achievements/summary").json()["score"] > 0


def test_leaderboard_includes_other_profiles_without_writing_them(
    api_client: TestClient, populated_home: Path
) -> None:
    other_home = populated_home / "profiles" / "research"
    _create_state_db(
        other_home,
        [{"message_count": 20, "tool_call_count": 5, "api_call_count": 5}],
    )
    other_engine = AchievementEngine(other_home, skill_usage_loader=lambda _home: {})
    other_engine.refresh()
    ledger_before = other_engine.store.ledger_path.read_bytes()
    assert not other_engine.store.leaderboard_path.exists()

    board = api_client.get("/api/plugins/achievements/leaderboard")
    assert board.status_code == 200
    local_entries = [
        entry for entry in board.json()["entries"] if entry["origin"] == "local_profile"
    ]
    assert len(local_entries) >= 2
    assert any(entry["is_current_profile"] is False for entry in local_entries)
    assert other_engine.store.ledger_path.read_bytes() == ledger_before
    assert not other_engine.store.leaderboard_path.exists()


def test_leaderboard_skips_uninitialized_profile_without_exposing_paths(
    api_client: TestClient, populated_home: Path
) -> None:
    profile = populated_home / "profiles" / "empty"
    profile.mkdir(parents=True)
    response = api_client.get("/api/plugins/achievements/leaderboard")
    assert response.status_code == 200
    data = response.json()
    assert data["skipped_local_profiles"] >= 1
    assert str(profile) not in json.dumps(data)
    assert not (profile / STATE_DIRNAME).exists()


def test_dashboard_manifest_declares_standard_backend_route() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "achievements"
        / "dashboard"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == "achievements"
    assert manifest["api"] == "plugin_api.py"
    assert manifest["tab"]["path"].startswith("/")
