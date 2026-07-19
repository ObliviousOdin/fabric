"""Convert safe Journey events into a closed fact snapshot."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from typing import Any, Iterable, Mapping, Optional

from .events import Capability, EventType, Outcome, Provider, Surface


@dataclass(frozen=True)
class EvidenceSnapshot:
    facts: dict[str, int]
    historical: dict[str, int]
    available_capabilities: frozenset[str]
    warnings: tuple[str, ...] = ()


def _event_count(row: Mapping[str, Any]) -> int:
    try:
        return max(1, int(row.get("count") or 1))
    except (TypeError, ValueError, OverflowError):
        return 1


def _timestamp(row: Mapping[str, Any]) -> Optional[float]:
    try:
        return float(row.get("occurred_at"))
    except (TypeError, ValueError, OverflowError):
        return None


def _union(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(item[0], item[1]) for item in merged]


def _max_concurrency(intervals: Iterable[tuple[float, float]]) -> int:
    points: list[tuple[float, int]] = []
    for start, end in intervals:
        if end <= start:
            continue
        points.append((start, 1))
        points.append((end, -1))
    active = 0
    peak = 0
    # Ends sort before starts at identical timestamps, avoiding false overlap.
    for _when, delta in sorted(points, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    return peak


def _local_day(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).date().isoformat()


def _local_week(timestamp: float) -> str:
    iso = datetime.fromtimestamp(timestamp).isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _max_consecutive_days(values: Iterable[str]) -> int:
    ordinals: list[int] = []
    for value in set(values):
        try:
            ordinals.append(date.fromisoformat(value).toordinal())
        except (TypeError, ValueError):
            continue
    best = current = 0
    previous: Optional[int] = None
    for ordinal in sorted(ordinals):
        current = current + 1 if previous is not None and ordinal == previous + 1 else 1
        best = max(best, current)
        previous = ordinal
    return best


def build_evidence(
    raw_events: Iterable[Mapping[str, Any]],
    rollups: Iterable[Mapping[str, Any]] = (),
    *,
    truncated: bool = False,
) -> EvidenceSnapshot:
    events = sorted(
        (dict(row) for row in raw_events if _timestamp(row) is not None),
        key=lambda row: float(row["occurred_at"]),
    )
    success = [row for row in events if row.get("outcome") == Outcome.SUCCESS.value]
    facts: Counter[str] = Counter()
    historical: Counter[str] = Counter()
    available = {str(row.get("capability")) for row in events if row.get("capability")}
    warnings: list[str] = ["event_window_truncated"] if truncated else []

    successful_turns = [
        row
        for row in success
        if row.get("event_type") == EventType.TURN_COMPLETED.value
    ]
    facts["successful_turns"] = sum(_event_count(row) for row in successful_turns)
    turns_by_session: Counter[str] = Counter(
        str(row.get("session_ref"))
        for row in successful_turns
        if row.get("session_ref")
    )
    facts["max_turns_per_session"] = max(turns_by_session.values(), default=0)
    observed_surfaces = {
        str(row.get("surface"))
        for row in successful_turns
        if row.get("surface") not in {None, "", Surface.UNKNOWN.value}
    }
    facts["distinct_surfaces"] = len(observed_surfaces)

    provider_events = [
        row
        for row in success
        if row.get("event_type") == EventType.PROVIDER_SUCCEEDED.value
    ]
    providers = {
        str(row.get("provider"))
        for row in provider_events
        if row.get("provider") not in {None, "", Provider.UNKNOWN.value}
    }
    facts["distinct_providers"] = len(providers)
    facts["openai_provider_successes"] = sum(
        _event_count(row)
        for row in provider_events
        if row.get("provider") == Provider.OPENAI.value
    )
    facts["xai_provider_successes"] = sum(
        _event_count(row)
        for row in provider_events
        if row.get("provider") == Provider.XAI.value
    )

    successful_tools = [
        row
        for row in success
        if row.get("event_type") == EventType.TOOL_SUCCEEDED.value
    ]
    facts["successful_tool_actions"] = sum(
        _event_count(row)
        for row in successful_tools
        if row.get("capability") != Capability.AGENT_CREW.value
    )
    facts["research_searches"] = sum(
        _event_count(row)
        for row in successful_tools
        if row.get("capability") == Capability.RESEARCH.value
    )
    facts["image_successes"] = sum(
        _event_count(row)
        for row in successful_tools
        if row.get("capability") == Capability.IMAGE.value
    )
    image_day_values = {
        _local_day(float(row["occurred_at"]))
        for row in successful_tools
        if row.get("capability") == Capability.IMAGE.value
    }
    facts["image_days"] = len(image_day_values)
    navigation_tools = [
        row
        for row in successful_tools
        if row.get("capability") == Capability.BROWSER_NAVIGATION.value
    ]
    browser_tools = [
        row
        for row in successful_tools
        if row.get("capability") == Capability.BROWSER.value
    ]
    cua_tools = [
        row
        for row in successful_tools
        if row.get("capability") == Capability.COMPUTER_USE.value
    ]
    facts["browser_navigations"] = sum(_event_count(row) for row in navigation_tools)
    facts["computer_use_successes"] = sum(_event_count(row) for row in cua_tools)

    completed_turn_refs = {
        str(row.get("turn_ref")) for row in successful_turns if row.get("turn_ref")
    }
    completed_turn_sessions = {
        str(row.get("turn_ref")): str(row.get("session_ref") or "")
        for row in successful_turns
        if row.get("turn_ref")
    }
    research_turn_refs = {
        str(row.get("turn_ref"))
        for row in successful_tools
        if row.get("capability") == Capability.RESEARCH.value and row.get("turn_ref")
    }
    facts["research_completed_turns"] = len(completed_turn_refs & research_turn_refs)
    browser_counts_by_turn: Counter[str] = Counter()
    navigation_counts_by_turn: Counter[str] = Counter()
    cua_counts_by_turn: Counter[str] = Counter()
    for row in navigation_tools:
        if row.get("turn_ref"):
            turn_ref = str(row["turn_ref"])
            navigation_counts_by_turn[turn_ref] += _event_count(row)
            browser_counts_by_turn[turn_ref] += _event_count(row)
    for row in browser_tools:
        if row.get("turn_ref"):
            browser_counts_by_turn[str(row["turn_ref"])] += _event_count(row)
    for row in cua_tools:
        if row.get("turn_ref"):
            cua_counts_by_turn[str(row["turn_ref"])] += _event_count(row)
    facts["browser_navigation_turns"] = sum(
        count >= 3
        and navigation_counts_by_turn[turn_ref] >= 1
        and turn_ref in completed_turn_refs
        for turn_ref, count in browser_counts_by_turn.items()
    )
    facts["computer_use_turns"] = sum(
        count >= 3 and turn_ref in completed_turn_refs
        for turn_ref, count in cua_counts_by_turn.items()
    )
    workflow_turns = {
        turn_ref
        for turn_ref in set(browser_counts_by_turn) | set(cua_counts_by_turn)
        if turn_ref in completed_turn_refs
    }
    facts["browser_workflows"] = len(workflow_turns)
    facts["browser_workflow_sessions"] = len({
        completed_turn_sessions[turn_ref]
        for turn_ref in workflow_turns
        if completed_turn_sessions.get(turn_ref)
    })

    capability_events = [
        row
        for row in events
        if row.get("event_type")
        in {
            EventType.CAPABILITY_SUCCEEDED.value,
            EventType.CAPABILITY_FAILED.value,
        }
    ]
    capability_successes = [
        row
        for row in success
        if row.get("event_type") == EventType.CAPABILITY_SUCCEEDED.value
    ]
    skill_uses = [
        row
        for row in capability_successes
        if row.get("capability") == Capability.SKILL_USE.value
    ]
    skill_authors = [
        row
        for row in capability_successes
        if row.get("capability") == Capability.SKILL_AUTHOR.value
    ]
    facts["skill_uses"] = sum(_event_count(row) for row in skill_uses)
    facts["distinct_skills"] = len({
        str(row.get("subject_ref")) for row in skill_uses if row.get("subject_ref")
    })
    facts["skills_authored"] = sum(_event_count(row) for row in skill_authors)

    authors_by_subject: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in skill_authors:
        if row.get("subject_ref"):
            authors_by_subject[str(row["subject_ref"])].append(row)
    reused = 0
    for row in skill_uses:
        subject = str(row.get("subject_ref") or "")
        if not subject:
            continue
        used_at = float(row["occurred_at"])
        if any(
            float(authored["occurred_at"]) < used_at
            for authored in authors_by_subject.get(subject, ())
        ):
            reused += 1
    facts["verified_skill_reuse"] = reused

    automation_schedules = [
        row
        for row in capability_successes
        if row.get("capability") == Capability.AUTOMATION_SCHEDULE.value
    ]
    automation_runs = [
        row
        for row in capability_successes
        if row.get("capability") == Capability.AUTOMATION_RUN.value
    ]
    automation_attempts = [
        row
        for row in capability_events
        if row.get("capability") == Capability.AUTOMATION_RUN.value
    ]
    automation_success_count = sum(_event_count(row) for row in automation_runs)
    recent_cutoff = time.time() - 90 * 86_400
    recent_automation_attempts = [
        row for row in automation_attempts if float(row["occurred_at"]) >= recent_cutoff
    ]
    recent_automation_successes = sum(
        _event_count(row)
        for row in recent_automation_attempts
        if row.get("outcome") == Outcome.SUCCESS.value
    )
    recent_automation_attempt_count = sum(
        _event_count(row) for row in recent_automation_attempts
    )
    facts["automation_schedules"] = sum(
        _event_count(row) for row in automation_schedules
    )
    facts["automation_runs"] = automation_success_count
    schedules_by_subject: dict[str, list[float]] = defaultdict(list)
    for row in automation_schedules:
        if row.get("subject_ref"):
            schedules_by_subject[str(row["subject_ref"])].append(
                float(row["occurred_at"])
            )
    facts["automation_schedule_run"] = int(
        any(
            row.get("subject_ref")
            and any(
                scheduled_at < float(row["occurred_at"])
                for scheduled_at in schedules_by_subject.get(
                    str(row["subject_ref"]), ()
                )
            )
            for row in automation_runs
        )
    )
    automation_day_values = {
        _local_day(float(row["occurred_at"])) for row in automation_runs
    }
    automation_week_values = {
        _local_week(float(row["occurred_at"])) for row in automation_runs
    }
    facts["automation_run_days"] = len(automation_day_values)
    facts["automation_run_weeks"] = len(automation_week_values)

    memory_store = [
        row
        for row in capability_successes
        if row.get("capability") == Capability.MEMORY_STORE.value
    ]
    memory_recall = [
        row
        for row in capability_successes
        if row.get("capability") == Capability.MEMORY_RECALL.value
    ]
    memory_sequence = False
    for stored in memory_store:
        stored_subject = stored.get("subject_ref")
        stored_at = float(stored["occurred_at"])
        if any(
            float(recalled["occurred_at"]) > stored_at
            and (
                not stored_subject
                or not recalled.get("subject_ref")
                or recalled.get("subject_ref") == stored_subject
            )
            for recalled in memory_recall
        ):
            memory_sequence = True
            break
    facts["memory_store_recall"] = int(memory_sequence)

    voice_stt = [
        row
        for row in capability_successes
        if row.get("capability") == Capability.VOICE_STT.value
    ]
    voice_tts = [
        row
        for row in success
        if row.get("capability") == Capability.VOICE_TTS.value
        and row.get("event_type")
        in {
            EventType.CAPABILITY_SUCCEEDED.value,
            EventType.TOOL_SUCCEEDED.value,
        }
    ]
    facts["voice_transcriptions"] = sum(_event_count(row) for row in voice_stt)
    stt_turns = {str(row.get("turn_ref")) for row in voice_stt if row.get("turn_ref")}
    tts_turns = {str(row.get("turn_ref")) for row in voice_tts if row.get("turn_ref")}
    facts["full_duplex_turns"] = len(stt_turns & tts_turns & completed_turn_refs)

    contribution_events = [
        row
        for row in capability_successes
        if row.get("capability") == Capability.CONTRIBUTION.value
    ]
    facts["verified_contributions"] = sum(
        _event_count(row) for row in contribution_events
    )
    facts["linkedin_launches"] = 0

    # Agent groups are bounded by one parent session + turn. A child stop event
    # carries authoritative status and duration; starts improve concurrency
    # reconstruction but are not themselves credited as success.
    starts: dict[tuple[str, str, str], float] = {}
    groups: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in events:
        group_key = (str(row.get("session_ref") or ""), str(row.get("turn_ref") or ""))
        if row.get("event_type") == EventType.SUBAGENT_STARTED.value and row.get(
            "subject_ref"
        ):
            starts.setdefault(
                (group_key[0], group_key[1], str(row["subject_ref"])),
                float(row["occurred_at"]),
            )
        elif row.get("event_type") == EventType.SUBAGENT_STOPPED.value and row.get(
            "subject_ref"
        ):
            subject = str(row["subject_ref"])
            previous = groups[group_key].get(subject)
            if previous is None or float(row["occurred_at"]) > float(
                previous["occurred_at"]
            ):
                groups[group_key][subject] = row
    successful_subagents = 0
    parallel_crew_runs = orchestra_runs = swarm_runs = 0
    for (_session_ref, turn_ref), rows_by_subject in groups.items():
        rows = list(rows_by_subject.values())
        total = len(rows)
        succeeded = sum(
            1 for row in rows if row.get("outcome") == Outcome.SUCCESS.value
        )
        successful_subagents += succeeded
        intervals: list[tuple[float, float]] = []
        for row in rows:
            end = float(row["occurred_at"])
            subject = str(row.get("subject_ref") or "")
            observed_start = (
                starts.get((_session_ref, turn_ref, subject)) if subject else None
            )
            if observed_start is not None and observed_start < end:
                intervals.append((observed_start, end))
            else:
                try:
                    duration = max(0.001, int(row.get("duration_ms") or 0) / 1_000)
                except (TypeError, ValueError, OverflowError):
                    duration = 0.001
                intervals.append((end - duration, end))
        peak = _max_concurrency(intervals)
        parent_completed = bool(turn_ref and turn_ref in completed_turn_refs)
        success_rate = succeeded / total if total else 0.0
        if parent_completed and total >= 3 and peak >= 3 and success_rate >= 0.8:
            parallel_crew_runs += 1
        if parent_completed and total >= 8 and peak >= 3 and success_rate >= 0.8:
            orchestra_runs += 1
        if parent_completed and total >= 20 and peak >= 3 and success_rate >= 0.8:
            swarm_runs += 1
    facts["successful_subagents"] = successful_subagents
    facts["parallel_crew_runs"] = parallel_crew_runs
    facts["orchestra_runs"] = orchestra_runs
    facts["swarm_runs"] = swarm_runs

    starts_by_turn: dict[str, float] = {}
    successful_end_by_turn: dict[str, Mapping[str, Any]] = {}
    for row in events:
        turn_ref = str(row.get("turn_ref") or "")
        if not turn_ref:
            continue
        if row.get("event_type") == EventType.TURN_STARTED.value:
            starts_by_turn.setdefault(turn_ref, float(row["occurred_at"]))
        elif (
            row.get("event_type") == EventType.TURN_COMPLETED.value
            and row.get("outcome") == Outcome.SUCCESS.value
        ):
            successful_end_by_turn[turn_ref] = row

    intervals_by_session: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for turn_ref, end_row in successful_end_by_turn.items():
        start = starts_by_turn.get(turn_ref)
        if start is None:
            continue
        end = float(end_row["occurred_at"])
        if end > start:
            session = str(end_row.get("session_ref") or "")
            if session:
                # A foreground interval contributes at most ten minutes. Long
                # API/tool waits remain useful evidence, but sleeping a request
                # cannot manufacture hours of active work.
                intervals_by_session[session].append((start, min(end, start + 600)))

    all_session_intervals: list[tuple[float, float, str]] = []
    meaningful_by_session: Counter[str] = Counter()
    for row in success:
        session = str(row.get("session_ref") or "")
        if not session:
            continue
        if row.get("event_type") in {
            EventType.TURN_COMPLETED.value,
            EventType.TOOL_SUCCEEDED.value,
            EventType.SUBAGENT_STOPPED.value,
            EventType.CAPABILITY_SUCCEEDED.value,
        }:
            meaningful_by_session[session] += 1

    focus = deep = long_haul = 0
    for session, intervals in intervals_by_session.items():
        merged = _union(intervals)
        all_session_intervals.extend((start, end, session) for start, end in merged)
        active = min(12 * 3_600, sum(end - start for start, end in merged))
        if active >= 30 * 60 and meaningful_by_session[session] >= 1:
            focus += 1
        if active >= 120 * 60 and meaningful_by_session[session] >= 1:
            deep += 1
        if merged:
            elapsed = merged[-1][1] - merged[0][0]
            max_gap = max(
                (
                    merged[index][0] - merged[index - 1][1]
                    for index in range(1, len(merged))
                ),
                default=0,
            )
            if (
                elapsed >= 5 * 3_600
                and active >= 300 * 60
                and max_gap <= 10 * 60
                and meaningful_by_session[session] >= 20
            ):
                long_haul += 1
    facts["focus_blocks"] = focus
    facts["deep_work_blocks"] = deep
    facts["long_haul_runs"] = long_haul

    parallel_sessions = 0
    for index, (start, end, session) in enumerate(all_session_intervals):
        if any(
            other_session != session
            and min(end, other_end) - max(start, other_start) >= 10 * 60
            for other_start, other_end, other_session in all_session_intervals[
                index + 1 :
            ]
        ):
            parallel_sessions = 1
            break
    facts["parallel_session_runs"] = parallel_sessions

    # Reflection metrics are deliberately separate from rank predicates. Merge
    # parallel sessions before reporting time so concurrent work is not counted
    # twice, split by the user's local calendar, and cap each day at 12 hours.
    global_active = _union(
        (start, end) for start, end, _session in all_session_intervals
    )
    local_today = datetime.now().date()
    active_days_7 = 0
    active_minutes_today = 0
    for offset in range(7):
        local_day = local_today - timedelta(days=offset)
        day_start = datetime.combine(local_day, datetime_time.min).timestamp()
        day_end = datetime.combine(
            local_day + timedelta(days=1), datetime_time.min
        ).timestamp()
        active_seconds = min(
            12 * 3_600,
            sum(
                max(0.0, min(end, day_end) - max(start, day_start))
                for start, end in global_active
            ),
        )
        if active_seconds > 0:
            active_days_7 += 1
        if offset == 0:
            active_minutes_today = int(active_seconds // 60)
    meaningful_types = {
        EventType.TURN_COMPLETED.value,
        EventType.TOOL_SUCCEEDED.value,
        EventType.SUBAGENT_STOPPED.value,
        EventType.CAPABILITY_SUCCEEDED.value,
    }
    seven_day_start = datetime.combine(
        local_today - timedelta(days=6), datetime_time.min
    ).timestamp()
    today_start = datetime.combine(local_today, datetime_time.min).timestamp()
    meaningful_rows = [
        row for row in success if row.get("event_type") in meaningful_types
    ]
    facts["active_minutes_today"] = active_minutes_today
    facts["active_days_7"] = active_days_7
    facts["meaningful_outcomes_today"] = sum(
        _event_count(row)
        for row in meaningful_rows
        if float(row["occurred_at"]) >= today_start
    )
    facts["meaningful_outcomes_7d"] = sum(
        _event_count(row)
        for row in meaningful_rows
        if float(row["occurred_at"]) >= seven_day_start
    )

    # Observed rollups remain rank-safe cumulative evidence. Only explicitly
    # inferred rows are reflection-only. Dimensions not preserved by the
    # rollup schema (subject/session/turn) never fabricate distinctness or
    # concurrency after raw retention.
    for row in rollups:
        try:
            count = max(0, int(row.get("event_count") or 0))
        except (TypeError, ValueError, OverflowError):
            count = 0
        source = str(row.get("source") or "")
        if source == "historical_inferred":
            historical[f"{row.get('capability')}.{row.get('outcome')}"] += count
            continue
        if source != "observed_hook":
            continue
        event_type = str(row.get("event_type") or "")
        capability = str(row.get("capability") or "")
        if (
            capability == Capability.AUTOMATION_RUN.value
            and event_type == EventType.CAPABILITY_SUCCEEDED.value
            and row.get("outcome") == Outcome.SUCCESS.value
        ):
            automation_success_count += count
        if row.get("outcome") != Outcome.SUCCESS.value:
            continue
        available.add(capability)
        if event_type == EventType.TURN_COMPLETED.value:
            facts["successful_turns"] += count
            surface = str(row.get("surface") or "")
            if surface and surface != Surface.UNKNOWN.value:
                observed_surfaces.add(surface)
        elif event_type == EventType.PROVIDER_SUCCEEDED.value:
            provider = str(row.get("provider") or "")
            if provider and provider != Provider.UNKNOWN.value:
                providers.add(provider)
            if provider == Provider.OPENAI.value:
                facts["openai_provider_successes"] += count
            elif provider == Provider.XAI.value:
                facts["xai_provider_successes"] += count
        elif event_type == EventType.TOOL_SUCCEEDED.value:
            if capability != Capability.AGENT_CREW.value:
                facts["successful_tool_actions"] += count
            if capability == Capability.RESEARCH.value:
                facts["research_searches"] += count
            elif capability == Capability.IMAGE.value:
                facts["image_successes"] += count
                if row.get("day"):
                    image_day_values.add(str(row["day"]))
            elif capability == Capability.BROWSER_NAVIGATION.value:
                facts["browser_navigations"] += count
            elif capability == Capability.COMPUTER_USE.value:
                facts["computer_use_successes"] += count
            elif capability == Capability.VOICE_TTS.value:
                # Count is useful for inspection, but no turn reference means
                # it cannot establish full duplex.
                pass
        elif event_type == EventType.SUBAGENT_STOPPED.value:
            facts["successful_subagents"] += count
        elif event_type == EventType.CAPABILITY_SUCCEEDED.value:
            if capability == Capability.SKILL_USE.value:
                facts["skill_uses"] += count
            elif capability == Capability.SKILL_AUTHOR.value:
                facts["skills_authored"] += count
            elif capability == Capability.AUTOMATION_SCHEDULE.value:
                facts["automation_schedules"] += count
            elif capability == Capability.AUTOMATION_RUN.value:
                facts["automation_runs"] += count
                if row.get("day"):
                    day_value = str(row["day"])
                    automation_day_values.add(day_value)
                    try:
                        iso = date.fromisoformat(day_value).isocalendar()
                        automation_week_values.add(f"{iso.year:04d}-W{iso.week:02d}")
                    except ValueError:
                        pass
            elif capability == Capability.VOICE_STT.value:
                facts["voice_transcriptions"] += count
            elif capability == Capability.CONTRIBUTION.value:
                facts["verified_contributions"] += count

    facts["distinct_surfaces"] = len(observed_surfaces)
    facts["distinct_providers"] = len(providers)
    facts["image_days"] = len(image_day_values)
    facts["automation_run_days"] = len(automation_day_values)
    facts["automation_run_weeks"] = len(automation_week_values)
    facts["automation_run_day_streak"] = _max_consecutive_days(automation_day_values)
    facts["automation_runs"] = automation_success_count
    facts["automation_reliability_percent"] = (
        int(100 * recent_automation_successes / recent_automation_attempt_count)
        if recent_automation_attempt_count
        else 0
    )

    return EvidenceSnapshot(
        facts=dict(facts),
        historical=dict(historical),
        available_capabilities=frozenset(available),
        warnings=tuple(warnings),
    )


__all__ = ["EvidenceSnapshot", "build_evidence"]
