"""Fabric Journey V2 evaluator and bounded dashboard projection."""

from __future__ import annotations

import hashlib
import itertools
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from fabric_constants import get_fabric_home
from utils import fast_safe_load

from .catalog import MILESTONES_BY_ID
from .event_store import EventStore
from .events import Capability, EventType, Outcome
from .journey_catalog import (
    ACHIEVEMENTS,
    ACHIEVEMENTS_BY_ID,
    DAILY_TEMPLATES,
    OUTCOMES,
    OUTCOMES_BY_ID,
    PATHS,
    RANKS,
    AchievementDefinition,
    DailyTemplate,
)
from .journey_evidence import EvidenceSnapshot, build_evidence
from .journey_store import JourneyStore
from .store import AchievementStateError, AchievementStore


JOURNEY_SCHEMA_VERSION = 2
_CONFIG_LOCKS: dict[str, threading.RLock] = {}
_CONFIG_LOCKS_GUARD = threading.Lock()
_CELEBRATION_MODES = frozenset({"standard", "quiet", "off"})

DEFAULT_SETTINGS: dict[str, Any] = {
    "tracking_enabled": True,
    "active_time_enabled": True,
    "celebration_mode": "standard",
    "raw_event_retention_days": 90,
    "preferred_outcome": None,
}


class JourneySettingsError(RuntimeError):
    pass


def _config_path(home: Path) -> Path:
    return home / "config.yaml"


def _read_raw_config(home: Path) -> dict[str, Any]:
    path = _config_path(home)
    if not path.exists():
        return {}
    try:
        value = fast_safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise JourneySettingsError("Fabric config is unavailable") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise JourneySettingsError("Fabric config must be a mapping")
    return value


def read_journey_settings(home: Path) -> dict[str, Any]:
    try:
        config = _read_raw_config(home)
    except JourneySettingsError:
        # Malformed explicit config fails closed for collection.
        return {
            "tracking_enabled": False,
            "active_time_enabled": False,
            "celebration_mode": "off",
            "raw_event_retention_days": 90,
            "preferred_outcome": None,
            "invalid": True,
        }
    raw_section = config.get("achievements")
    section_invalid = raw_section is not None and not isinstance(raw_section, dict)
    if section_invalid:
        return {
            "tracking_enabled": False,
            "active_time_enabled": False,
            "celebration_mode": "off",
            "raw_event_retention_days": 90,
            "preferred_outcome": None,
            "invalid": True,
        }
    section = raw_section if isinstance(raw_section, dict) else {}
    tracking_raw = section.get("tracking_enabled", True)
    active_raw = section.get("active_time_enabled", True)
    celebration_raw = section.get("celebration_mode", "standard")
    retention_raw = section.get("raw_event_retention_days", 90)
    outcome_raw = section.get("preferred_outcome")
    outcome_valid = (
        outcome_raw is None
        or outcome_raw == ""
        or (isinstance(outcome_raw, str) and outcome_raw in OUTCOMES_BY_ID)
    )
    retention_valid = type(retention_raw) is int and 1 <= retention_raw <= 365
    invalid = any((
        not isinstance(tracking_raw, bool),
        not isinstance(active_raw, bool),
        not (
            isinstance(celebration_raw, str) and celebration_raw in _CELEBRATION_MODES
        ),
        not retention_valid,
        not outcome_valid,
    ))
    if invalid:
        return {
            "tracking_enabled": False,
            "active_time_enabled": False,
            "celebration_mode": "off",
            "raw_event_retention_days": 90,
            "preferred_outcome": None,
            "invalid": True,
        }
    # The SQLite pause marker is the fail-closed authority for stale config
    # writers in other processes. A later unrelated full-config rewrite cannot
    # silently restart collection; only the explicit resume transition clears
    # this marker.
    try:
        durably_paused = EventStore(home).collection_is_paused()
    except Exception:
        durably_paused = True
    return {
        "tracking_enabled": tracking_raw and not durably_paused,
        "active_time_enabled": active_raw,
        "celebration_mode": celebration_raw,
        "raw_event_retention_days": retention_raw,
        "preferred_outcome": outcome_raw or None,
        "invalid": False,
    }


def update_journey_settings(home: Path, updates: Mapping[str, Any]) -> dict[str, Any]:
    key = str(_config_path(home).resolve())
    with _CONFIG_LOCKS_GUARD:
        lock = _CONFIG_LOCKS.setdefault(key, threading.RLock())
    with lock:
        config = _read_raw_config(home)
        previous_settings = read_journey_settings(home)
        store = EventStore(home)
        section = config.get("achievements")
        if section is None:
            section = {}
        if not isinstance(section, dict):
            raise JourneySettingsError("achievements config must be a mapping")
        section = dict(section)
        for name, value in updates.items():
            if name in {"tracking_enabled", "active_time_enabled"}:
                if not isinstance(value, bool):
                    raise JourneySettingsError(f"{name} must be a boolean")
            elif name == "celebration_mode":
                if value not in _CELEBRATION_MODES:
                    raise JourneySettingsError("celebration_mode is invalid")
            elif name == "preferred_outcome":
                if value is not None and value not in OUTCOMES_BY_ID:
                    raise JourneySettingsError("preferred_outcome is invalid")
            else:
                raise JourneySettingsError(f"unknown achievement setting: {name}")
            section[name] = value
        enabling = (
            updates.get("tracking_enabled") is True
            and previous_settings.get("tracking_enabled") is not True
        )
        # Treat every explicit ``false`` as a pause transition, even when the
        # YAML already says false. Older/manual config edits may not have the
        # durable SQLite fence yet; making the operation idempotent closes that
        # upgrade window without changing the public setting semantics.
        disabling = updates.get("tracking_enabled") is False
        was_durably_paused = store.collection_is_paused() if disabling else False
        if enabling:
            # Establish the resume floor before enabling collection. Drafts
            # created while paused remain ineligible even if still queued, and
            # any stale-writer rows from the paused window are erased.
            store.resume_collection()
        elif disabling:
            # Install the durable DB fence before publishing the config change;
            # stale processes cannot append even if they read the old setting.
            store.pause_collection()
        config["achievements"] = section
        try:
            from fabric_cli.config import atomic_config_write

            atomic_config_write(_config_path(home), config, sort_keys=False)
        except Exception as exc:
            if enabling:
                try:
                    store.pause_collection()
                except Exception:
                    pass
            elif disabling and not was_durably_paused:
                try:
                    store.cancel_collection_pause()
                except Exception:
                    pass
            raise JourneySettingsError("Fabric config could not be updated") from exc
    return read_journey_settings(home)


def _iso(timestamp: Optional[float] = None) -> str:
    value = time.time() if timestamp is None else timestamp
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _periods(now: Optional[float] = None) -> tuple[str, str, str]:
    current = datetime.fromtimestamp(time.time() if now is None else now)
    daily = current.date().isoformat()
    iso = current.isocalendar()
    weekly = f"{iso.year:04d}-W{iso.week:02d}"
    anchor = date(2026, 1, 5).toordinal()
    season_number = (current.date().toordinal() - anchor) // 28
    return daily, weekly, f"S{season_number:+d}"


def _fact_progress(
    definition: AchievementDefinition,
    facts: Mapping[str, int],
) -> tuple[int, int, str, bool]:
    unmet = []
    for requirement in definition.requirements:
        current = max(0, int(facts.get(requirement.key, 0)))
        if current < requirement.target:
            unmet.append((current, requirement.target))
    if unmet:
        current, target = min(unmet, key=lambda item: item[0] / item[1])
        return current, target, f"{min(current, target)} of {target}", False
    if not definition.requirements:
        return 0, 1, "Not started", False
    target = definition.requirements[-1].target
    return target, target, f"{target} of {target}", True


class JourneyEngine:
    def __init__(
        self, fabric_home: Optional[Path] = None, *, profile_name: str = "current"
    ) -> None:
        self.fabric_home = (
            Path(fabric_home) if fabric_home is not None else get_fabric_home()
        )
        self.profile_name = profile_name
        self.events = EventStore(self.fabric_home)
        self.store = JourneyStore(self.fabric_home)

    def settings(self) -> dict[str, Any]:
        return read_journey_settings(self.fabric_home)

    def update_settings(self, updates: Mapping[str, Any]) -> dict[str, Any]:
        return update_journey_settings(self.fabric_home, updates)

    def _legacy(self) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        try:
            ledger = AchievementStore(self.fabric_home, read_only=True).read_ledger(
                create=False
            )
        except AchievementStateError:
            return [], ["legacy_state_unavailable"]
        if ledger is None:
            return [], warnings
        rows: list[dict[str, Any]] = []
        for event in ledger.get("events", []):
            if not isinstance(event, dict):
                continue
            achievement_id = str(event.get("achievement_id") or "")
            definition = MILESTONES_BY_ID.get(achievement_id)
            rows.append({
                "id": achievement_id,
                "title": definition.title if definition else achievement_id,
                "description": (
                    definition.description
                    if definition
                    else "Legacy Fabric achievement"
                ),
                "tier": definition.tier if definition else "Legacy",
                "points": max(0, int(event.get("points") or 0)),
                "earned": True,
                "earned_at": event.get("earned_at"),
                "confidence": "legacy",
            })
        return rows, warnings

    def _availability(self, evidence: EvidenceSnapshot) -> frozenset[str]:
        available = {"conversation"}
        raw = evidence.available_capabilities
        if Capability.RESEARCH.value in raw:
            available.add("research")
        if (
            Capability.BROWSER_NAVIGATION.value in raw
            or Capability.BROWSER.value in raw
            or Capability.COMPUTER_USE.value in raw
        ):
            available.add("computer_use")
        if Capability.AGENT_CREW.value in raw:
            available.add("agent_crew")
        if Capability.SKILL_USE.value in raw or (self.fabric_home / "skills").is_dir():
            available.add("skills")
        # Registry checks improve first-use discovery without importing tool
        # modules or assuming an unconfigured service exists.
        try:
            from tools.registry import registry

            checks = {
                "research": "web_search",
                "computer_use": "browser_navigate",
                "agent_crew": "delegate_task",
            }
            for capability, tool_name in checks.items():
                entry = registry.get_entry(tool_name)
                if entry is None:
                    continue
                if entry.check_fn is None or bool(entry.check_fn()):
                    available.add(capability)
        except Exception:
            pass
        return frozenset(available)

    @staticmethod
    def _qualifying(
        facts: Mapping[str, int], records: Mapping[str, Mapping[str, Any]]
    ) -> list[AchievementDefinition]:
        return [
            item
            for item in ACHIEVEMENTS
            if item.launch
            and item.rank_eligible
            and item.id not in records
            and all(
                max(0, int(facts.get(requirement.key, 0))) >= requirement.target
                for requirement in item.requirements
            )
        ]

    def _achievement_item(
        self,
        definition: AchievementDefinition,
        *,
        facts: Mapping[str, int],
        historical: Mapping[str, int],
        record: Optional[Mapping[str, Any]],
        attestation: Optional[Mapping[str, Any]],
        snoozed: bool,
    ) -> dict[str, Any]:
        current, target, label, qualifies = _fact_progress(definition, facts)
        historical_current, _historical_target, _label, _ = _fact_progress(
            definition, historical
        )
        earned = record is not None or attestation is not None
        if record is not None:
            confidence = str(record.get("confidence") or "observed")
            status = "earned"
            earned_at = _iso(float(record["earned_at"]))
            evidence_source = "observed_hook"
            evidence_count = int(record.get("evidence_count") or 0)
        elif attestation is not None:
            confidence = "self_attested"
            status = "earned"
            earned_at = _iso(float(attestation["attested_at"]))
            evidence_source = "self_attested"
            evidence_count = 1
        elif not definition.launch:
            confidence = (
                "self_attested"
                if definition.id == "content.linkedin_launch"
                else "unavailable"
            )
            status = "preview"
            earned_at = None
            evidence_source = confidence
            evidence_count = 0
        elif snoozed:
            confidence = "observed"
            status = "snoozed"
            earned_at = None
            evidence_source = "observed_hook"
            evidence_count = current
        else:
            confidence = (
                "observed"
                if current
                else "historical_inferred"
                if historical_current
                else "observed"
            )
            status = "active" if current or qualifies else "available"
            earned_at = None
            evidence_source = (
                "historical_inferred"
                if not current and historical_current
                else "observed_hook"
            )
            evidence_count = current
        action = {
            "kind": definition.action.kind,
            "label": definition.action.label,
        }
        if definition.action.route:
            action["route"] = definition.action.route
        if definition.action.draft:
            action["draft"] = definition.action.draft
        return {
            "id": definition.id,
            "path_id": definition.path_id,
            "capability": definition.capability,
            "title": definition.title,
            "description": definition.description,
            "xp": definition.xp,
            "estimate_minutes": definition.estimate_minutes,
            "status": status,
            "earned": earned,
            "earned_at": earned_at,
            "hidden": definition.hidden,
            "rank_eligible": definition.rank_eligible,
            "confidence": confidence,
            "progress": {"current": current, "target": target, "label": label},
            "historical_progress": {
                "current": historical_current,
                "target": target,
                "label": f"{min(historical_current, target)} of {target} previously seen",
            },
            "evidence": {
                "confidence": confidence,
                "source": evidence_source,
                "count": evidence_count,
            },
            "action": action,
            "unavailable_reason": definition.preview_reason,
        }

    @staticmethod
    def _rank(
        records: Mapping[str, Mapping[str, Any]], starter_complete: bool
    ) -> tuple[dict[str, str], Optional[dict[str, Any]], int, int, int]:
        definitions = [
            ACHIEVEMENTS_BY_ID[item_id]
            for item_id in records
            if item_id in ACHIEVEMENTS_BY_ID
            and ACHIEVEMENTS_BY_ID[item_id].rank_eligible
        ]
        xp = sum(int(records[item.id].get("xp") or item.xp) for item in definitions)
        count = len(definitions)
        breadth = len({item.path_id for item in definitions})
        earned_ids = {item.id for item in definitions}
        multi_step = any(item.multi_step for item in definitions)

        def special(rank_id: str) -> bool:
            if rank_id == "operator":
                return starter_complete
            if rank_id == "orchestrator":
                return multi_step
            if rank_id == "weaver":
                return "agents.parallel_crew" in earned_ids and (
                    "automation.reliable_loop" in earned_ids
                    or "sessions.parallel_pilot" in earned_ids
                )
            if rank_id == "patternmaker":
                return bool(
                    {
                        "skills.skillsmith",
                        "contribution.verified_builder",
                        "contribution.fabric_contributor",
                    }
                    & earned_ids
                )
            return True

        current = RANKS[0]
        for rank in RANKS[1:]:
            if (
                xp >= rank.xp
                and count >= rank.achievements
                and breadth >= rank.families
                and special(rank.id)
            ):
                current = rank
            else:
                break
        next_rank = next((rank for rank in RANKS if rank.xp > current.xp), None)
        projection = None
        if next_rank is not None:
            requirements = [
                {
                    "id": "xp",
                    "label": "Mastery XP",
                    "current": xp,
                    "target": next_rank.xp,
                    "met": xp >= next_rank.xp,
                },
                {
                    "id": "achievements",
                    "label": "Achievements",
                    "current": count,
                    "target": next_rank.achievements,
                    "met": count >= next_rank.achievements,
                },
                {
                    "id": "families",
                    "label": "Capability paths",
                    "current": breadth,
                    "target": next_rank.families,
                    "met": breadth >= next_rank.families,
                },
            ]
            if next_rank.id == "operator":
                requirements.append({
                    "id": "starter",
                    "label": "Starter journey",
                    "current": int(starter_complete),
                    "target": 1,
                    "met": starter_complete,
                })
            elif next_rank.id == "orchestrator":
                requirements.append({
                    "id": "multi_step",
                    "label": "Multi-step quest",
                    "current": int(multi_step),
                    "target": 1,
                    "met": multi_step,
                })
            elif next_rank.id == "weaver":
                parallel = "agents.parallel_crew" in earned_ids
                reliable = bool(
                    {"automation.reliable_loop", "sessions.parallel_pilot"} & earned_ids
                )
                requirements.extend([
                    {
                        "id": "parallel_crew",
                        "label": "Successful parallel agents",
                        "current": int(parallel),
                        "target": 1,
                        "met": parallel,
                    },
                    {
                        "id": "reliable_work",
                        "label": "Reliable automation or parallel sessions",
                        "current": int(reliable),
                        "target": 1,
                        "met": reliable,
                    },
                ])
            elif next_rank.id == "patternmaker":
                builder = bool(
                    {
                        "skills.skillsmith",
                        "contribution.verified_builder",
                        "contribution.fabric_contributor",
                    }
                    & earned_ids
                )
                requirements.append({
                    "id": "builder",
                    "label": "Authored/reused skill or verified contribution",
                    "current": int(builder),
                    "target": 1,
                    "met": builder,
                })
            projection = {
                "id": next_rank.id,
                "label": next_rank.label,
                "xp_required": next_rank.xp,
                "requirements": requirements,
            }
        return (
            {"id": current.id, "label": current.label},
            projection,
            xp,
            count,
            breadth,
        )

    @staticmethod
    def _family_for_event(row: Mapping[str, Any]) -> Optional[str]:
        capability = str(row.get("capability") or "")
        return {
            Capability.CONVERSATION.value: "conversation",
            Capability.RESEARCH.value: "research",
            Capability.IMAGE.value: "create",
            Capability.BROWSER_NAVIGATION.value: "computer_use",
            Capability.BROWSER.value: "computer_use",
            Capability.COMPUTER_USE.value: "computer_use",
            Capability.AGENT_CREW.value: "agent_crew",
            Capability.AUTOMATION_SCHEDULE.value: "automate",
            Capability.AUTOMATION_RUN.value: "automate",
            Capability.SKILL_USE.value: "skills",
            Capability.SKILL_AUTHOR.value: "skills",
            Capability.MODEL_LAB.value: "model_lab",
            Capability.MEMORY_STORE.value: "memory",
            Capability.MEMORY_RECALL.value: "memory",
            Capability.VOICE_STT.value: "voice",
            Capability.VOICE_TTS.value: "voice",
        }.get(capability)

    def _weekly_progress(
        self, raw_events: list[dict[str, Any]], assignment: Mapping[str, Any]
    ) -> tuple[int, int]:
        assigned_at = float(assignment["assigned_at"])
        assigned_families = {
            str(assignment.get("capability") or ""),
            str(assignment.get("secondary_capability") or ""),
        }
        assigned_families.discard("")
        outcomes: set[tuple[str, str]] = set()
        families: set[str] = set()
        for row in raw_events:
            if float(row.get("occurred_at") or 0) <= assigned_at:
                continue
            if row.get("outcome") != Outcome.SUCCESS.value:
                continue
            if row.get("event_type") not in {
                EventType.TURN_COMPLETED.value,
                EventType.TOOL_SUCCEEDED.value,
                EventType.SUBAGENT_STOPPED.value,
                EventType.CAPABILITY_SUCCEEDED.value,
            }:
                continue
            family = self._family_for_event(row)
            if not family or family not in assigned_families:
                continue
            identity = str(row.get("turn_ref") or row.get("event_id") or "")
            if not identity:
                continue
            outcomes.add((identity, family))
            families.add(family)
        return len(outcomes), len(families)

    def _daily_candidates(
        self,
        evidence: EvidenceSnapshot,
        preferred_outcome: Optional[str],
        *,
        exclude_id: Optional[str] = None,
    ) -> list[DailyTemplate]:
        available = self._availability(evidence)
        candidates = [
            item
            for item in DAILY_TEMPLATES
            if item.capability in available and item.id != exclude_id
        ]
        if not candidates:
            fallback = DAILY_TEMPLATES[0]
            return [] if fallback.id == exclude_id else [fallback]
        preferred_paths = (
            OUTCOMES_BY_ID[preferred_outcome].preferred_paths
            if preferred_outcome in OUTCOMES_BY_ID
            else ()
        )
        recent = set(self.store.recent_daily_capabilities())
        return sorted(
            candidates,
            key=lambda item: (
                item.path_id not in preferred_paths,
                item.capability in recent,
                item.id,
            ),
        )

    def _choose_daily(
        self,
        period_key: str,
        evidence: EvidenceSnapshot,
        preferred_outcome: Optional[str],
        *,
        reroll: int = 0,
        exclude_id: Optional[str] = None,
    ) -> DailyTemplate:
        candidates = self._daily_candidates(
            evidence, preferred_outcome, exclude_id=exclude_id
        )
        if not candidates:
            raise ValueError("no alternative daily challenge is available")
        digest = hashlib.sha256(
            f"{self._stable_identity()}|{period_key}|{reroll}".encode("utf-8")
        ).digest()
        return candidates[int.from_bytes(digest[:8], "big") % len(candidates)]

    def _weekly_pairs(
        self,
        evidence: EvidenceSnapshot,
        *,
        exclude: Optional[tuple[str, str]] = None,
    ) -> list[tuple[str, str]]:
        excluded = frozenset(exclude or ())
        return [
            pair
            for pair in itertools.combinations(sorted(self._availability(evidence)), 2)
            if not excluded or frozenset(pair) != excluded
        ]

    def _choose_weekly(
        self,
        period_key: str,
        evidence: EvidenceSnapshot,
        *,
        reroll: int = 0,
        exclude: Optional[tuple[str, str]] = None,
    ) -> tuple[str, str]:
        pairs = self._weekly_pairs(evidence, exclude=exclude)
        if not pairs:
            raise ValueError("no alternative weekly challenge is available")
        digest = hashlib.sha256(
            f"{self._stable_identity()}|weekly|{period_key}|{reroll}".encode("utf-8")
        ).digest()
        return pairs[int.from_bytes(digest[:8], "big") % len(pairs)]

    def _stable_identity(self) -> str:
        try:
            card_id = AchievementStore(self.fabric_home, read_only=True).card_id(
                create=False
            )
            if card_id:
                return card_id
        except AchievementStateError:
            pass
        return hashlib.sha256(
            str(self.fabric_home.resolve()).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _daily_projection(
        assignment: Mapping[str, Any], template: DailyTemplate, current: int
    ) -> dict[str, Any]:
        baseline = int(assignment["baseline_count"])
        target_delta = int(assignment["target_delta"])
        delta = max(0, current - baseline)
        action = {"kind": template.action.kind, "label": template.action.label}
        if template.action.route:
            action["route"] = template.action.route
        if template.action.draft:
            action["draft"] = template.action.draft
        return {
            "id": template.id,
            "path_id": template.path_id,
            "capability": template.capability,
            "title": template.title,
            "description": template.description,
            "why": template.why,
            "xp": 0,
            "momentum": 10,
            "snoozeable": assignment["status"] == "active",
            "reroll_available": (
                assignment["status"] == "active" and int(assignment["reroll_count"]) < 1
            ),
            "estimate_minutes": template.estimate_minutes,
            "status": assignment["status"],
            "confidence": "observed",
            "progress": {
                "current": min(delta, target_delta),
                "target": target_delta,
                "label": f"{min(delta, target_delta)} of {target_delta}",
            },
            "action": action,
        }

    def _starter(
        self,
        records: Mapping[str, Mapping[str, Any]],
        markers: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        steps = [
            (
                "conversation.first_thread",
                "Start one useful chat",
                "Complete a real Fabric chat turn.",
                "conversation.first_thread" in records,
            ),
            (
                "starter.tool_assist",
                "Use a tool successfully",
                "Let Fabric complete one tool-assisted action.",
                "starter.tool_assist" in markers,
            ),
            (
                "agents.first_delegate",
                "Delegate one bounded task",
                "Receive one successful subagent result.",
                "agents.first_delegate" in records,
            ),
        ]
        first_incomplete = next(
            (index for index, step in enumerate(steps) if not step[3]), len(steps)
        )
        projected = [
            {
                "id": item_id,
                "title": title,
                "description": description,
                "status": (
                    "completed"
                    if completed
                    else "active"
                    if index == first_incomplete
                    else "unavailable"
                ),
                "progress": {
                    "current": 1 if completed else 0,
                    "target": 1,
                    "label": "1 of 1" if completed else "0 of 1",
                },
            }
            for index, (item_id, title, description, completed) in enumerate(steps)
        ]
        complete = all(step[3] for step in steps)
        return {
            "id": "starter.fabric_basics",
            "status": "completed" if complete else "active",
            "step_index": sum(1 for step in steps if step[3]),
            "total_steps": len(steps),
            "steps": projected,
            "action": {
                "kind": "chat",
                "label": "Start in Chat",
                "route": "/workspace/chat",
                "draft": "Help me complete one useful task, use a tool when it helps, and delegate one bounded subtask.",
            },
        }

    def summary(self, *, include_new: bool = False) -> dict[str, Any]:
        settings = self.settings()
        tracking = bool(settings["tracking_enabled"])
        raw_events: list[dict[str, Any]] = []
        rollups: list[dict[str, Any]] = []
        event_truncated = False
        evidence = EvidenceSnapshot({}, {}, frozenset())
        historical: dict[str, int] = {}
        warnings: list[str] = []
        retention_days = int(settings.get("raw_event_retention_days", 90))
        if tracking:
            raw_events, rollups, event_truncated = self.events.read_snapshot(
                retention_days=retention_days
            )
            evidence = build_evidence(raw_events, rollups, truncated=event_truncated)
            warnings.extend(evidence.warnings)
        else:
            # Pausing collection must not pause the privacy retention clock.
            self.events.maintain(retention_days=retention_days)
            if settings.get("invalid"):
                warnings.append("tracking_config_invalid")

        records = self.store.unlock_records()
        markers = self.store.markers()
        newly_earned: list[dict[str, Any]] = []
        if tracking:
            if evidence.facts.get("successful_tool_actions", 0) >= 1:
                self.store.record_marker(
                    "starter.tool_assist", evidence.facts["successful_tool_actions"]
                )
                markers = self.store.markers()
            appended = self.store.record_unlocks(
                self._qualifying(evidence.facts, records), evidence.facts
            )
            records = self.store.unlock_records()
            newly_earned = appended

        attestations = self.store.attestations()
        snoozed = self.store.snoozed_ids()
        starter = self._starter(records, markers)
        level, next_level, xp, earned_count, breadth = self._rank(
            records, starter["status"] == "completed"
        )

        items = [
            self._achievement_item(
                definition,
                facts=evidence.facts,
                historical=historical,
                record=records.get(definition.id),
                attestation=attestations.get(definition.id),
                snoozed=definition.id in snoozed,
            )
            for definition in ACHIEVEMENTS
        ]
        item_by_id = {item["id"]: item for item in items}
        path_items: list[dict[str, Any]] = []
        for path in PATHS:
            steps = [
                item
                for item in items
                if item["path_id"] == path.id and not item["hidden"]
            ]
            eligible_steps = [item for item in steps if item["rank_eligible"]]
            completed = sum(1 for item in eligible_steps if item["earned"])
            next_item = next(
                (item for item in eligible_steps if not item["earned"]), None
            )
            path_items.append({
                "id": path.id,
                "title": path.title,
                "description": path.description,
                "status": "completed"
                if eligible_steps and completed == len(eligible_steps)
                else "active"
                if completed
                else "available",
                "progress": {
                    "current": completed,
                    "target": len(eligible_steps),
                    "label": f"{completed} of {len(eligible_steps)}",
                },
                "steps": steps,
                "next_achievement_id": next_item["id"] if next_item else None,
            })

        daily_key, weekly_key, season_id = _periods()
        daily_projection = None
        weekly_projection = None
        if tracking and starter["status"] == "completed":
            daily_is_snoozed = False
            assignment = self.store.assignment("daily", daily_key)
            if assignment is None:
                chosen = self._choose_daily(
                    daily_key, evidence, settings.get("preferred_outcome")
                )
                assignment = self.store.create_assignment(
                    kind="daily",
                    period_key=daily_key,
                    template_id=chosen.id,
                    path_id=chosen.path_id,
                    capability=chosen.capability,
                    baseline_count=int(evidence.facts.get(chosen.fact_key, 0)),
                    target_delta=chosen.target_delta,
                )
            elif str(assignment["template_id"]) in snoozed:
                alternatives = self._daily_candidates(
                    evidence,
                    settings.get("preferred_outcome"),
                    exclude_id=str(assignment["template_id"]),
                )
                if alternatives:
                    replacement = self._choose_daily(
                        daily_key,
                        evidence,
                        settings.get("preferred_outcome"),
                        reroll=int(assignment["reroll_count"]) + 1,
                        exclude_id=str(assignment["template_id"]),
                    )
                    assignment = self.store.create_assignment(
                        kind="daily",
                        period_key=daily_key,
                        template_id=replacement.id,
                        path_id=replacement.path_id,
                        capability=replacement.capability,
                        baseline_count=int(evidence.facts.get(replacement.fact_key, 0)),
                        target_delta=replacement.target_delta,
                        reroll_count=int(assignment["reroll_count"]),
                    )
                else:
                    daily_is_snoozed = True
            if not daily_is_snoozed:
                template = next(
                    (
                        item
                        for item in DAILY_TEMPLATES
                        if item.id == assignment["template_id"]
                    ),
                    DAILY_TEMPLATES[0],
                )
                current = int(evidence.facts.get(template.fact_key, 0))
                if assignment["status"] == "active" and current - int(
                    assignment["baseline_count"]
                ) >= int(assignment["target_delta"]):
                    self.store.complete_assignment(
                        "daily", daily_key, season_id=season_id, points=10
                    )
                    assignment = self.store.assignment("daily", daily_key) or assignment
                daily_projection = self._daily_projection(assignment, template, current)

            if earned_count >= 3:
                weekly = self.store.assignment("weekly", weekly_key)
                if weekly is None:
                    try:
                        first, second = self._choose_weekly(weekly_key, evidence)
                    except ValueError:
                        weekly = None
                    else:
                        weekly = self.store.create_assignment(
                            kind="weekly",
                            period_key=weekly_key,
                            template_id="weekly.cross_capability",
                            path_id="anywhere",
                            capability=first,
                            secondary_capability=second,
                            baseline_count=0,
                            target_delta=3,
                        )
                if weekly is not None:
                    weekly_count, weekly_families = self._weekly_progress(
                        raw_events, weekly
                    )
                    if (
                        weekly["status"] == "active"
                        and weekly_count >= 3
                        and weekly_families >= 2
                    ):
                        self.store.complete_assignment(
                            "weekly", weekly_key, season_id=season_id, points=60
                        )
                        weekly = self.store.assignment("weekly", weekly_key) or weekly
                    weekly_projection = {
                        "id": "weekly.cross_capability",
                        "path_id": "anywhere",
                        "capability": "anywhere",
                        "title": "Cross two capability paths",
                        "description": (
                            "Complete three meaningful outcomes across "
                            f"{weekly['capability']} and {weekly['secondary_capability']}."
                        ),
                        "why": "Breadth turns isolated features into a Fabric workflow.",
                        "xp": 0,
                        "momentum": 60,
                        "reroll_available": (
                            weekly["status"] == "active"
                            and int(weekly["reroll_count"]) < 1
                            and bool(
                                self._weekly_pairs(
                                    evidence,
                                    exclude=(
                                        str(weekly["capability"]),
                                        str(weekly["secondary_capability"] or ""),
                                    ),
                                )
                            )
                        ),
                        "estimate_minutes": 60,
                        "status": weekly["status"],
                        "confidence": "observed",
                        "progress": {
                            "current": min(weekly_count, 3),
                            "target": 3,
                            "label": f"{min(weekly_count, 3)} of 3 across {weekly_families} families",
                        },
                        "action": {
                            "kind": "chat",
                            "label": "Start in Chat",
                            "route": "/workspace/chat",
                            "draft": "Help me complete a useful workflow that combines at least two Fabric capabilities.",
                        },
                    }

        earned_items = [item for item in items if item["earned"]]
        earned_items.sort(key=lambda item: item["earned_at"] or "", reverse=True)
        active_items = [
            item
            for item in items
            if not item["earned"] and item["status"] == "active" and not item["hidden"]
        ]
        discover_items = [
            item
            for item in items
            if not item["earned"]
            and item["status"] in {"available", "preview"}
            and not item["hidden"]
        ]
        optional = (
            [
                item
                for item in active_items + discover_items
                if item["status"] != "preview"
                and ACHIEVEMENTS_BY_ID[item["id"]].recommendable
                and item["id"] not in snoozed
            ][:2]
            if starter["status"] == "completed"
            else []
        )
        legacy, legacy_warnings = self._legacy()
        warnings.extend(legacy_warnings)

        momentum = self.store.momentum(season_id)
        next_checkpoint = next(
            (value for value in (100, 250, 400) if momentum < value), None
        )
        primary = None
        if starter["status"] != "completed":
            primary = {
                "id": starter["id"],
                "path_id": "conversation",
                "capability": "conversation",
                "title": "Learn Fabric by doing",
                "description": "Complete chat, tool, and delegation outcomes.",
                "why": "These three steps unlock the rest of the Journey.",
                "xp": 0,
                "estimate_minutes": 15,
                "status": starter["status"],
                "confidence": "observed",
                "progress": {
                    "current": sum(
                        1 for step in starter["steps"] if step["status"] == "completed"
                    ),
                    "target": starter["total_steps"],
                    "label": f"Step {starter['step_index']} of {starter['total_steps']}",
                },
                "action": starter["action"],
            }
        elif daily_projection is not None:
            primary = daily_projection

        sources = {
            "observed": len(raw_events),
            "historical": sum(evidence.historical.values()),
            "self_attested": len(attestations),
        }
        dropped_events = self.events.dropped_event_count()
        if dropped_events:
            warnings.append("observer_events_dropped")
        result = {
            "schema_version": JOURNEY_SCHEMA_VERSION,
            "generated_at": _iso(),
            "profile": self.profile_name,
            "onboarding": {
                "is_first_run": settings.get("preferred_outcome") is None,
                "selected_outcome": settings.get("preferred_outcome"),
                "outcomes": [
                    {
                        "id": item.id,
                        "label": item.label,
                        "description": item.description,
                        "preferred_paths": list(item.preferred_paths),
                    }
                    for item in OUTCOMES
                ],
            },
            "mastery": {
                "xp": xp,
                "level": level,
                "next_level": next_level,
                "breadth": {
                    "current": breadth,
                    "target": next_level["requirements"][2]["target"]
                    if next_level
                    else breadth,
                },
                "earned_count": earned_count,
            },
            "starter": starter,
            "today": {
                "primary": primary,
                "optional": optional,
                "weekly": weekly_projection,
                "reflection": {
                    "active_minutes": int(
                        evidence.facts.get("active_minutes_today", 0)
                    ),
                    "active_hours": round(
                        evidence.facts.get("active_minutes_today", 0) / 60, 1
                    ),
                    "meaningful_outcomes": int(
                        evidence.facts.get("meaningful_outcomes_today", 0)
                    ),
                    "active_days_7": int(evidence.facts.get("active_days_7", 0)),
                    "meaningful_outcomes_7": int(
                        evidence.facts.get("meaningful_outcomes_7d", 0)
                    ),
                    "rank_eligible": False,
                },
                "momentum": {
                    "points": momentum,
                    "season_id": season_id,
                    "next_checkpoint": next_checkpoint,
                },
                "recent_wins": earned_items[:3],
                "active_paths": [
                    path for path in path_items if path["status"] == "active"
                ][:2],
            },
            "paths": path_items,
            "collection": {
                "earned": earned_items,
                "active": active_items[:3],
                "discover": discover_items[:3],
                "legacy": legacy,
            },
            "tracking": {
                "enabled": tracking,
                "active_time_enabled": bool(settings["active_time_enabled"]),
                "celebration_mode": settings["celebration_mode"],
                "raw_event_retention_days": int(
                    settings.get("raw_event_retention_days", 90)
                ),
                "settings_invalid": bool(settings.get("invalid")),
                "state": "active" if tracking else "paused",
                "sources": sources,
                "dropped_events": dropped_events,
                "allowed_fields": [
                    "event_type",
                    "occurred_at",
                    "duration_ms",
                    "opaque_refs",
                    "capability",
                    "outcome",
                    "surface",
                    "provider",
                    "count",
                    "source",
                ],
                "excluded_fields": [
                    "prompt",
                    "response",
                    "conversation_history",
                    "tool_arguments",
                    "tool_results",
                    "errors",
                    "paths",
                    "urls",
                    "identities",
                    "tokens",
                    "cost",
                ],
            },
            "warnings": list(dict.fromkeys(warnings)),
        }
        if include_new:
            result["newly_earned"] = [
                item_by_id[event["achievement_id"]]
                for event in newly_earned
                if event["achievement_id"] in item_by_id
            ]
        return result

    def reroll(self, kind: str) -> dict[str, Any]:
        if kind not in {"daily", "weekly"}:
            raise ValueError("challenge kind must be daily or weekly")
        settings = self.settings()
        if not settings["tracking_enabled"]:
            raise ValueError("tracking is paused")
        raw, rollups, truncated = self.events.read_snapshot(
            retention_days=int(settings.get("raw_event_retention_days", 90))
        )
        evidence = build_evidence(raw, rollups, truncated=truncated)
        daily_key, weekly_key, _season_id = _periods()
        period = daily_key if kind == "daily" else weekly_key
        current = self.store.assignment(kind, period)
        pending_unlocks: list[dict[str, Any]] = []
        if current is None:
            initial = self.summary(include_new=True)
            pending_unlocks = list(initial.get("newly_earned") or [])
            current = self.store.assignment(kind, period)
        if current is None:
            raise ValueError("challenge is not available")
        if int(current["reroll_count"]) >= 1:
            raise ValueError("free reroll already used")
        if kind == "weekly":
            first, second = self._choose_weekly(
                period,
                evidence,
                reroll=1,
                exclude=(
                    str(current["capability"]),
                    str(current["secondary_capability"] or ""),
                ),
            )
            self.store.create_assignment(
                kind="weekly",
                period_key=period,
                template_id="weekly.cross_capability",
                path_id="anywhere",
                capability=first,
                secondary_capability=second,
                baseline_count=0,
                target_delta=3,
                reroll_count=1,
            )
        else:
            chosen = self._choose_daily(
                period,
                evidence,
                settings.get("preferred_outcome"),
                reroll=1,
                exclude_id=str(current["template_id"]),
            )
            self.store.create_assignment(
                kind="daily",
                period_key=period,
                template_id=chosen.id,
                path_id=chosen.path_id,
                capability=chosen.capability,
                baseline_count=int(evidence.facts.get(chosen.fact_key, 0)),
                target_delta=chosen.target_delta,
                reroll_count=1,
            )
        result = self.summary(include_new=True)
        if pending_unlocks and not result.get("newly_earned"):
            result["newly_earned"] = pending_unlocks
        return result

    def snooze(self, quest_id: str, days: int) -> dict[str, Any]:
        valid = quest_id in ACHIEVEMENTS_BY_ID or any(
            item.id == quest_id for item in DAILY_TEMPLATES
        )
        if not valid:
            raise ValueError("unknown quest id")
        until = self.store.snooze(quest_id, days=days)
        result = self.summary(include_new=True)
        result["snooze"] = {
            "quest_id": quest_id,
            "snoozed_until": _iso(until),
        }
        return result

    def attest(self, achievement_id: str) -> dict[str, Any]:
        definition = ACHIEVEMENTS_BY_ID.get(achievement_id)
        if definition is None or achievement_id != "content.linkedin_launch":
            raise ValueError("achievement is not self-attestable")
        record = self.store.attest(achievement_id)
        return {
            "ok": True,
            "achievement_id": achievement_id,
            "confidence": "self_attested",
            "xp": 0,
            "attested_at": _iso(float(record["attested_at"])),
        }


__all__ = [
    "DEFAULT_SETTINGS",
    "JOURNEY_SCHEMA_VERSION",
    "JourneyEngine",
    "JourneySettingsError",
    "read_journey_settings",
    "update_journey_settings",
]
