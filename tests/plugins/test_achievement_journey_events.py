"""Privacy, concurrency, and retention contracts for Journey events."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from plugins.achievements import event_store as event_store_module
from plugins.achievements import observer as observer_module
from plugins.achievements.event_store import EventStore
from plugins.achievements.events import (
    Capability,
    EventDraft,
    EventSource,
    EventType,
    Outcome,
)
from plugins.achievements.journey_evidence import build_evidence
from plugins.achievements.observer import HOOKS, flush_observers, on_capability_event


def _draft(
    *,
    when: float,
    dedupe: str,
    capability: Capability = Capability.RESEARCH,
) -> EventDraft:
    return EventDraft(
        event_type=EventType.CAPABILITY_SUCCEEDED,
        capability=capability,
        outcome=Outcome.SUCCESS,
        occurred_at=when,
        raw_session_ref="session-secret",
        raw_turn_ref="turn-secret",
        raw_subject_ref="subject-secret",
        dedupe_key=dedupe,
    )


def test_event_store_hashes_refs_and_deduplicates(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    when = time.time()
    assert store.append(_draft(when=when, dedupe="same")) is True
    assert store.append(_draft(when=when, dedupe="same")) is False

    exported = store.export()
    assert len(exported["events"]) == 1
    encoded = json.dumps(exported, sort_keys=True)
    for secret in ("session-secret", "turn-secret", "subject-secret", "same"):
        assert secret not in encoded
    event = exported["events"][0]
    assert len(event["session_ref"]) == 64
    assert len(event["turn_ref"]) == 64
    assert len(event["subject_ref"]) == 64


def test_delete_floor_rejects_predelete_first_delivery(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    before_delete = time.time()
    removed = store.delete_activity()
    assert removed["generation"] == 2

    # A new store has no cached generation, so this specifically proves the
    # durable floor—not only an in-memory token—protects queued old work.
    fresh = EventStore(tmp_path)
    assert fresh.append(_draft(when=before_delete, dedupe="queued-old")) is False
    assert fresh.append(_draft(when=time.time(), dedupe="current-epoch")) is True
    with sqlite3.connect(fresh.db_path) as connection:
        stored_floor = connection.execute(
            "SELECT value FROM event_meta WHERE key = 'history_floor'"
        ).fetchone()[0]
    assert stored_floor == repr(float(stored_floor))
    assert len(fresh.export()["events"]) == 1


def test_delete_rotates_opaque_reference_epoch(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    first_when = time.time()
    assert store.append(_draft(when=first_when, dedupe="before-delete"))
    before = store.export()["events"][0]

    store.delete_activity()
    time.sleep(0.002)
    assert store.append(_draft(when=time.time(), dedupe="after-delete"))
    after = store.export()["events"][0]

    assert before["session_ref"] != after["session_ref"]
    assert before["turn_ref"] != after["turn_ref"]
    assert before["subject_ref"] != after["subject_ref"]


def test_export_enforces_retention_without_a_new_append(
    tmp_path: Path, monkeypatch
) -> None:
    base = time.time()
    monkeypatch.setattr(event_store_module.time, "time", lambda: base)
    store = EventStore(tmp_path)
    assert store.append(_draft(when=base, dedupe="ages-while-idle"))

    monkeypatch.setattr(event_store_module.time, "time", lambda: base + (2 * 86_400))
    exported = store.export(retention_days=1)

    assert exported["events"] == []
    assert sum(row["event_count"] for row in exported["rollups"]) == 1


def test_durable_pause_rejects_stale_writers_and_resume_erases_window(
    tmp_path: Path,
) -> None:
    store = EventStore(tmp_path)
    pause_at = time.time()
    assert store.append(_draft(when=pause_at - 1, dedupe="before-pause"))
    # Simulate a row committed by a writer that won the SQLite transaction
    # race immediately before the durable pause fence was installed.
    assert store.append(_draft(when=pause_at + 1, dedupe="stale-paused-window"))

    store.pause_collection(pause_at)
    assert store.collection_is_paused() is True
    assert (
        store.append(_draft(when=pause_at + 1.5, dedupe="stale-config-writer")) is False
    )

    store.resume_collection(pause_at + 2)
    assert store.collection_is_paused() is False
    exported = store.export()
    assert len(exported["events"]) == 1
    assert exported["events"][0]["occurred_at"] == pause_at - 1


def test_raw_rows_compact_at_a_hard_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(event_store_module, "MAX_RAW_EVENTS", 3)
    store = EventStore(tmp_path)
    now = time.time()

    assert store.append_many([
        _draft(when=now + index * 0.001, dedupe=f"raw-{index}") for index in range(4)
    ]) == [True, True, True, True]

    with sqlite3.connect(store.db_path) as connection:
        raw_count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    exported = store.export()
    assert raw_count <= 3
    assert sum(row["event_count"] for row in exported["rollups"]) == 2
    assert exported["truncated"] is True


def test_daily_rollups_compact_into_bounded_lifetime_totals(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(event_store_module, "MAX_DAILY_ROLLUPS", 2)
    store = EventStore(tmp_path)
    with store.connection() as connection:
        for index in range(4):
            connection.execute(
                """INSERT INTO event_rollups (
                       day, event_type, capability, outcome, surface, provider,
                       source, event_count, duration_ms, generation
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    f"2026-07-{index + 1:02d}",
                    EventType.CAPABILITY_SUCCEEDED.value,
                    Capability.RESEARCH.value,
                    Outcome.SUCCESS.value,
                    "cli",
                    "openai",
                    EventSource.OBSERVED_HOOK.value,
                    1,
                    0,
                ),
            )
        connection.commit()

    store.maintain(retention_days=365)

    with sqlite3.connect(store.db_path) as connection:
        daily_count = connection.execute(
            "SELECT COUNT(*) FROM event_rollups"
        ).fetchone()[0]
        lifetime_count = connection.execute(
            "SELECT COALESCE(SUM(event_count), 0) FROM event_totals"
        ).fetchone()[0]
    assert daily_count <= 2
    assert lifetime_count == 3
    assert sum(row["event_count"] for row in store.export()["rollups"]) == 4


def test_export_response_has_hard_event_and_rollup_bounds(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(event_store_module, "MAX_EXPORT_EVENTS", 2)
    monkeypatch.setattr(event_store_module, "MAX_SNAPSHOT_ROLLUPS", 2)
    store = EventStore(tmp_path)
    now = time.time()
    store.append_many([
        _draft(when=now + index * 0.001, dedupe=f"export-{index}") for index in range(3)
    ])
    with store.connection() as connection:
        for index in range(3):
            connection.execute(
                """INSERT INTO event_rollups (
                       day, event_type, capability, outcome, surface, provider,
                       source, event_count, duration_ms, generation
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    f"2026-06-{index + 1:02d}",
                    EventType.CAPABILITY_SUCCEEDED.value,
                    Capability.RESEARCH.value,
                    Outcome.SUCCESS.value,
                    "cli",
                    "openai",
                    EventSource.OBSERVED_HOOK.value,
                    1,
                    0,
                ),
            )
        connection.commit()

    exported = store.export()
    assert len(exported["events"]) == 2
    assert len(exported["rollups"]) == 2
    assert exported["truncated"] is True


def test_shutdown_flush_registration_is_single_and_time_bounded(monkeypatch) -> None:
    callbacks: list[object] = []
    timeouts: list[float] = []
    monkeypatch.setattr(observer_module, "_SHUTDOWN_REGISTERED", False)
    monkeypatch.setattr(observer_module.atexit, "register", callbacks.append)
    monkeypatch.setattr(
        observer_module,
        "flush_observers",
        lambda timeout=5.0: timeouts.append(timeout) or True,
    )

    observer_module._register_shutdown_flush()
    observer_module._register_shutdown_flush()
    assert callbacks == [observer_module._flush_at_shutdown]

    callbacks[0]()
    assert timeouts == [observer_module._SHUTDOWN_FLUSH_SECONDS]
    assert 0 < timeouts[0] <= 1.0


def test_capability_idempotency_uses_source_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    occurred = time.time()
    payload = {
        "capability": "skill",
        "action": "used",
        "outcome": "success",
        "subject_id": "same-skill",
        "occurred_at": occurred,
    }
    on_capability_event(**payload)
    on_capability_event(**payload)
    on_capability_event(**{**payload, "occurred_at": occurred + 1})
    assert flush_observers()

    events = EventStore(tmp_path).export()["events"]
    assert len(events) == 2
    assert {event["capability"] for event in events} == {Capability.SKILL_USE.value}
    assert "same-skill" not in json.dumps(events)


def test_observer_subscribes_only_to_closed_hook_and_uses_event_id(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    assert set(HOOKS) == {"capability_event"}
    occurred = time.time()
    payload = {
        "capability": "tool",
        "action": "browser_navigate",
        "outcome": "success",
        "event_id": "replay-safe-id",
        "subject_id": "private-tool-call",
        "session_id": "private-session",
        "turn_id": "private-turn",
        "surface": "desktop",
        "occurred_at": occurred,
    }
    on_capability_event(**payload)
    on_capability_event(**{**payload, "occurred_at": occurred + 1})
    on_capability_event(
        capability="conversation",
        action="turn_completed",
        outcome="success",
        event_id="turn-complete",
        session_id="private-session",
        turn_id="private-turn",
        surface="desktop",
        occurred_at=occurred + 2,
    )
    assert flush_observers()
    exported = EventStore(tmp_path).export()
    assert len(exported["events"]) == 2
    assert {event["capability"] for event in exported["events"]} == {
        Capability.BROWSER_NAVIGATION.value,
        Capability.CONVERSATION.value,
    }
    encoded = json.dumps(exported)
    for secret in (
        "replay-safe-id",
        "private-tool-call",
        "private-session",
        "private-turn",
    ):
        assert secret not in encoded


def test_lifecycle_phases_and_repeated_tool_ids_survive_cross_turn_dedupe(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    occurred = time.time()
    lifecycle = [
        ("conversation", "turn_started", "turn-1", "turn-1", occurred),
        ("agent", "started", "agent-1", "turn-1", occurred + 1),
        ("agent", "stopped", "agent-1", "turn-1", occurred + 2),
        ("conversation", "turn_completed", "turn-1", "turn-1", occurred + 3),
        ("tool", "web_search", "provider-call-1", "turn-1", occurred + 4),
        ("tool", "web_search", "provider-call-1", "turn-2", occurred + 5),
    ]
    for family, action, event_id, turn_id, when in lifecycle:
        on_capability_event(
            capability=family,
            action=action,
            outcome="success",
            event_id=event_id,
            session_id="session-1",
            turn_id=turn_id,
            occurred_at=when,
        )
    # A transport replay in the same turn remains idempotent.
    on_capability_event(
        capability="tool",
        action="web_search",
        outcome="success",
        event_id="provider-call-1",
        session_id="session-1",
        turn_id="turn-2",
        occurred_at=occurred + 6,
    )
    assert flush_observers()

    events = EventStore(tmp_path).export()["events"]
    assert len(events) == len(lifecycle)
    assert [event["event_type"] for event in events].count(
        EventType.TOOL_SUCCEEDED.value
    ) == 2
    assert {
        EventType.TURN_STARTED.value,
        EventType.TURN_COMPLETED.value,
        EventType.SUBAGENT_STARTED.value,
        EventType.SUBAGENT_STOPPED.value,
    } <= {event["event_type"] for event in events}


def test_observer_rejects_missing_or_malformed_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    on_capability_event(capability="skill", action="used", outcome="success")
    on_capability_event(
        capability="skill",
        action="used",
        outcome="success",
        occurred_at="now",
    )
    assert flush_observers()
    assert EventStore(tmp_path).export()["events"] == []


def test_batch_persists_drop_diagnostics_and_private_modes(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    now = time.time()
    inserted = store.append_many(
        [
            _draft(when=now, dedupe="one"),
            _draft(when=now + 0.001, dedupe="two"),
        ],
        dropped_count=3,
    )
    assert inserted == [True, True]
    assert store.dropped_event_count() == 3
    if hasattr(Path, "chmod"):
        assert store.root.stat().st_mode & 0o777 == 0o700
        assert store.db_path.stat().st_mode & 0o777 == 0o600
        assert store.key_path.stat().st_mode & 0o777 == 0o600


def test_observed_rollups_count_for_mastery_but_inferred_do_not() -> None:
    observed = {
        "day": "2026-07-01",
        "event_type": EventType.PROVIDER_SUCCEEDED.value,
        "capability": Capability.MODEL_LAB.value,
        "outcome": Outcome.SUCCESS.value,
        "surface": "cli",
        "provider": "openai",
        "source": EventSource.OBSERVED_HOOK.value,
        "event_count": 4,
        "duration_ms": 0,
    }
    inferred = {
        **observed,
        "provider": "xai",
        "source": EventSource.HISTORICAL_INFERRED.value,
        "event_count": 9,
    }
    snapshot = build_evidence([], [observed, inferred])
    assert snapshot.facts["openai_provider_successes"] == 4
    assert snapshot.facts["xai_provider_successes"] == 0
    assert snapshot.facts["distinct_providers"] == 1
    assert snapshot.historical[f"{Capability.MODEL_LAB.value}.success"] == 9


def test_activity_delete_clears_mutable_journey_state_not_unlocks(
    tmp_path: Path,
) -> None:
    store = EventStore(tmp_path)
    with store.connection() as connection:
        connection.executescript(
            """
            CREATE TABLE journey_unlocks (achievement_id TEXT PRIMARY KEY);
            CREATE TABLE journey_snoozes (quest_id TEXT PRIMARY KEY, snoozed_until REAL);
            CREATE TABLE journey_attestations (achievement_id TEXT PRIMARY KEY);
            INSERT INTO journey_unlocks VALUES ('keep.me');
            INSERT INTO journey_snoozes VALUES ('drop.me', 9999999999);
            INSERT INTO journey_attestations VALUES ('drop.attestation');
            """
        )
        connection.commit()
    store.delete_activity()
    with sqlite3.connect(store.db_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM journey_unlocks").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM journey_snoozes").fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM journey_attestations").fetchone()[
                0
            ]
            == 0
        )
