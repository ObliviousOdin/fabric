"""Fail-open consumer for Fabric's closed ``capability_event`` hook.

The default-on plugin deliberately does not subscribe to rich lifecycle hooks.
Core call sites first reduce those payloads to the small capability-event
contract; this module then converts raw identifiers to :class:`EventDraft`
objects and hands them to one bounded writer queue per profile.
"""

from __future__ import annotations

import atexit
import logging
import math
import queue
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fabric_constants import get_fabric_home

from .event_store import EventStore
from .events import (
    Capability,
    EventDraft,
    EventType,
    Outcome,
    normalize_provider,
    normalize_surface,
)


logger = logging.getLogger(__name__)
_WRITERS: dict[str, "_ObserverWriter"] = {}
_WRITERS_LOCK = threading.Lock()
_MAX_CACHED_PROFILES = 16
_QUEUE_CAPACITY = 2_048
_BATCH_SIZE = 64
_SHUTDOWN_FLUSH_SECONDS = 0.5
_SHUTDOWN_REGISTERED = False
_SHUTDOWN_REGISTER_LOCK = threading.Lock()


def _flush_at_shutdown() -> None:
    """Give the daemon writer a short, hard-bounded normal-exit drain window."""
    flush_observers(timeout=_SHUTDOWN_FLUSH_SECONDS)


def _register_shutdown_flush() -> None:
    global _SHUTDOWN_REGISTERED
    if _SHUTDOWN_REGISTERED:
        return
    with _SHUTDOWN_REGISTER_LOCK:
        if _SHUTDOWN_REGISTERED:
            return
        atexit.register(_flush_at_shutdown)
        _SHUTDOWN_REGISTERED = True


def _settings(home: Path) -> dict[str, Any]:
    """Read settings for the writer's profile, never the thread ContextVar."""
    try:
        from .journey_engine import read_journey_settings

        return read_journey_settings(home)
    except Exception:
        return {
            "tracking_enabled": False,
            "active_time_enabled": False,
            "raw_event_retention_days": 90,
        }


class _ObserverWriter:
    """One lazy bounded queue and daemon writer per profile in this process."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.store = EventStore(home)
        self.queue: queue.Queue[EventDraft] = queue.Queue(maxsize=_QUEUE_CAPACITY)
        self._thread: Optional[threading.Thread] = None
        self._start_lock = threading.Lock()
        self._dropped_lock = threading.Lock()
        self._dropped_pending = 0

    def enqueue(self, draft: EventDraft) -> None:
        try:
            self.queue.put_nowait(draft)
        except queue.Full:
            with self._dropped_lock:
                self._dropped_pending += 1
            logger.debug("achievement event queue is full; dropping event")
            return
        if self._thread is None:
            with self._start_lock:
                if self._thread is None:
                    _register_shutdown_flush()
                    self._thread = threading.Thread(
                        target=self._run,
                        name="fabric-achievements-writer",
                        daemon=True,
                    )
                    self._thread.start()

    def _take_dropped(self) -> int:
        with self._dropped_lock:
            value = self._dropped_pending
            self._dropped_pending = 0
        return value

    def _restore_dropped(self, count: int) -> None:
        if count <= 0:
            return
        with self._dropped_lock:
            self._dropped_pending += count

    def _run(self) -> None:
        while True:
            first = self.queue.get()
            batch = [first]
            while len(batch) < _BATCH_SIZE:
                try:
                    batch.append(self.queue.get_nowait())
                except queue.Empty:
                    break
            dequeued_count = len(batch)
            dropped = self._take_dropped()
            try:
                settings = _settings(self.home)
                if settings.get("tracking_enabled") is not True:
                    continue
                if settings.get("active_time_enabled") is not True:
                    batch = [
                        draft
                        for draft in batch
                        if draft.event_type is not EventType.TURN_STARTED
                    ]
                self.store.append_many(
                    batch,
                    dropped_count=dropped,
                    retention_days=int(settings.get("raw_event_retention_days", 90)),
                )
            except Exception:
                self._restore_dropped(dropped)
                logger.debug("achievement event projection failed", exc_info=False)
            finally:
                # ``batch`` may be filtered above, so task accounting uses the
                # number dequeued rather than the number persisted.
                for _ in range(dequeued_count):
                    self.queue.task_done()


def _writer() -> Optional[_ObserverWriter]:
    home = Path(get_fabric_home())
    key = str(home.resolve())
    with _WRITERS_LOCK:
        writer = _WRITERS.get(key)
        if writer is None:
            if len(_WRITERS) >= _MAX_CACHED_PROFILES:
                logger.debug(
                    "achievement observer profile cache is full; dropping event"
                )
                return None
            writer = _ObserverWriter(home)
            _WRITERS[key] = writer
        return writer


def _safe_text(value: object, *, maximum: int = 1_024) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value if value and len(value) <= maximum else None


def _safe_label(value: object) -> Optional[str]:
    raw = _safe_text(value, maximum=128)
    if raw is None or not all(
        character.isascii() and (character.isalnum() or character in {"_", "-"})
        for character in raw
    ):
        return None
    return raw.casefold()


def _safe_duration(value: object) -> Optional[int]:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        return None
    return value


def _append(draft: EventDraft) -> None:
    try:
        writer = _writer()
        if writer is not None:
            writer.enqueue(draft)
    except Exception:
        logger.debug("achievement event enqueue failed", exc_info=False)


def flush_observers(timeout: float = 5.0) -> bool:
    """Test/shutdown helper; capability callbacks never call this path."""
    deadline = time.monotonic() + max(0.0, timeout)
    with _WRITERS_LOCK:
        writers = list(_WRITERS.values())
    while time.monotonic() < deadline:
        if all(writer.queue.unfinished_tasks == 0 for writer in writers):
            return True
        time.sleep(0.01)
    return all(writer.queue.unfinished_tasks == 0 for writer in writers)


def _tool_capability(tool_name: object) -> Capability:
    name = str(tool_name or "").strip().casefold()
    if name == "web_search":
        return Capability.RESEARCH
    if name == "image_generate":
        return Capability.IMAGE
    if name == "browser_navigate":
        return Capability.BROWSER_NAVIGATION
    if name == "computer_use":
        return Capability.COMPUTER_USE
    if name == "text_to_speech":
        return Capability.VOICE_TTS
    if name.startswith("browser_"):
        return Capability.BROWSER
    if name == "delegate_task":
        return Capability.AGENT_CREW
    return Capability.TOOL


_CAPABILITY_EVENTS: dict[tuple[str, str], Capability] = {
    ("skill", "used"): Capability.SKILL_USE,
    ("skills", "used"): Capability.SKILL_USE,
    ("skill", "authored"): Capability.SKILL_AUTHOR,
    ("skill", "created"): Capability.SKILL_AUTHOR,
    ("skills", "authored"): Capability.SKILL_AUTHOR,
    ("automation", "schedule_created"): Capability.AUTOMATION_SCHEDULE,
    ("cron", "schedule_created"): Capability.AUTOMATION_SCHEDULE,
    ("automation", "run_completed"): Capability.AUTOMATION_RUN,
    ("cron", "run_completed"): Capability.AUTOMATION_RUN,
    ("memory", "stored"): Capability.MEMORY_STORE,
    ("memory", "recalled"): Capability.MEMORY_RECALL,
    ("voice", "transcribed"): Capability.VOICE_STT,
    ("voice", "stt"): Capability.VOICE_STT,
    ("voice", "spoken"): Capability.VOICE_TTS,
    ("voice", "tts"): Capability.VOICE_TTS,
    ("contribution", "verified"): Capability.CONTRIBUTION,
}


def _closed_projection(
    family: str, action: str, outcome: Outcome
) -> Optional[tuple[EventType, Capability]]:
    if family == "conversation" and action == "turn_started":
        return EventType.TURN_STARTED, Capability.CONVERSATION
    if family == "conversation" and action == "turn_completed":
        return EventType.TURN_COMPLETED, Capability.CONVERSATION
    if family in {"provider", "model"} and action in {
        "request_succeeded",
        "request_completed",
    }:
        return (
            EventType.PROVIDER_SUCCEEDED
            if outcome is Outcome.SUCCESS
            else EventType.CAPABILITY_FAILED,
            Capability.MODEL_LAB,
        )
    if family == "tool":
        return (
            EventType.TOOL_SUCCEEDED
            if outcome is Outcome.SUCCESS
            else EventType.TOOL_FAILED,
            _tool_capability(action),
        )
    if family in {"agent", "agents"} and action == "started":
        return EventType.SUBAGENT_STARTED, Capability.AGENT_CREW
    if family in {"agent", "agents"} and action == "stopped":
        return EventType.SUBAGENT_STOPPED, Capability.AGENT_CREW
    capability = _CAPABILITY_EVENTS.get((family, action))
    if capability is None:
        return None
    return (
        EventType.CAPABILITY_SUCCEEDED
        if outcome is Outcome.SUCCESS
        else EventType.CAPABILITY_FAILED,
        capability,
    )


def on_capability_event(**kwargs: Any) -> None:
    """Project the safe generic event into enums; never retain free-form data."""
    family = _safe_label(kwargs.get("capability"))
    action = _safe_label(kwargs.get("action"))
    raw_outcome = _safe_label(kwargs.get("outcome"))
    if (
        family is None
        or action is None
        or raw_outcome
        not in {
            "success",
            "failed",
            "interrupted",
        }
    ):
        return None
    outcome = (
        Outcome.SUCCESS
        if raw_outcome == "success"
        else Outcome.INTERRUPTED
        if raw_outcome == "interrupted"
        else Outcome.FAILED
    )
    projection = _closed_projection(family, action, outcome)
    if projection is None:
        return None
    event_type, capability = projection

    raw_occurred_at = kwargs.get("occurred_at")
    try:
        if isinstance(raw_occurred_at, bool) or not isinstance(
            raw_occurred_at, (int, float)
        ):
            raise ValueError
        occurred_at = float(raw_occurred_at)
        if not math.isfinite(occurred_at) or not (0 < occurred_at <= time.time() + 300):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return None

    event_id = _safe_text(kwargs.get("event_id"), maximum=256)
    subject = _safe_text(kwargs.get("subject_id"), maximum=256)
    session = _safe_text(kwargs.get("session_id"), maximum=256)
    turn = _safe_text(kwargs.get("turn_id"), maximum=256)
    # The action participates only in the keyed dedupe input.  It is never a
    # stored column, so unknown plugin tool names cannot expand the vocabulary.
    dedupe = (
        "|".join((
            family,
            action,
            "event",
            event_id,
            "session",
            session or "",
            "turn",
            turn or "",
        ))
        if event_id
        else "|".join((family, action, "subject", subject or "", f"{occurred_at:.6f}"))
    )
    _append(
        EventDraft(
            event_type=event_type,
            capability=capability,
            outcome=outcome,
            occurred_at=occurred_at,
            duration_ms=_safe_duration(kwargs.get("duration_ms")),
            count=(
                kwargs.get("count")
                if type(kwargs.get("count")) is int and kwargs.get("count") > 0
                else 1
            ),
            surface=normalize_surface(_safe_label(kwargs.get("surface"))),
            provider=normalize_provider(_safe_label(kwargs.get("provider"))),
            raw_session_ref=session,
            raw_turn_ref=turn,
            raw_subject_ref=subject,
            dedupe_key=f"capability:{dedupe}",
        )
    )
    return None


HOOKS = {"capability_event": on_capability_event}


__all__ = ["HOOKS", "flush_observers", "on_capability_event"]
