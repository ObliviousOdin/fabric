"""Closed, privacy-safe event vocabulary for Fabric Journey V2.

Only values declared in this module may reach the local event ledger.  Hook
payloads are deliberately projected into :class:`EventDraft` without copying
free-form dictionaries, prompts, tool inputs/results, errors, paths, URLs, or
identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


EVENT_SCHEMA_VERSION = 1
MAX_EVENT_COUNT = 1_000
MAX_EVENT_DURATION_MS = 12 * 60 * 60 * 1_000


class EventType(str, Enum):
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    PROVIDER_SUCCEEDED = "provider_succeeded"
    TOOL_SUCCEEDED = "tool_succeeded"
    TOOL_FAILED = "tool_failed"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_STOPPED = "subagent_stopped"
    CAPABILITY_SUCCEEDED = "capability_succeeded"
    CAPABILITY_FAILED = "capability_failed"


class Capability(str, Enum):
    CONVERSATION = "conversation"
    TOOL = "tool"
    MODEL_LAB = "model_lab"
    RESEARCH = "research"
    IMAGE = "image"
    BROWSER_NAVIGATION = "browser_navigation"
    BROWSER = "browser"
    COMPUTER_USE = "computer_use"
    AGENT_CREW = "agent_crew"
    AUTOMATION_SCHEDULE = "automation_schedule"
    AUTOMATION_RUN = "automation_run"
    SKILL_USE = "skill_use"
    SKILL_AUTHOR = "skill_author"
    MEMORY_STORE = "memory_store"
    MEMORY_RECALL = "memory_recall"
    VOICE_STT = "voice_stt"
    VOICE_TTS = "voice_tts"
    CONTRIBUTION = "contribution"


class Outcome(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    HISTORICAL = "historical"


class EventSource(str, Enum):
    OBSERVED_HOOK = "observed_hook"
    HISTORICAL_INFERRED = "historical_inferred"
    SELF_ATTESTED = "self_attested"


class Surface(str, Enum):
    CLI = "cli"
    TUI = "tui"
    DESKTOP = "desktop"
    WEB = "web"
    DASHBOARD = "dashboard"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    GATEWAY = "gateway"
    CRON = "cron"
    API = "api"
    UNKNOWN = "unknown"


class Provider(str, Enum):
    OPENAI = "openai"
    XAI = "xai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    BEDROCK = "bedrock"
    AZURE = "azure"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EventDraft:
    """Ephemeral event before raw identifiers are converted to opaque refs."""

    event_type: EventType
    capability: Capability
    outcome: Outcome
    occurred_at: float
    surface: Surface = Surface.UNKNOWN
    provider: Provider = Provider.UNKNOWN
    duration_ms: Optional[int] = None
    count: int = 1
    source: EventSource = EventSource.OBSERVED_HOOK
    raw_session_ref: Optional[str] = None
    raw_turn_ref: Optional[str] = None
    raw_subject_ref: Optional[str] = None
    dedupe_key: Optional[str] = None

    def bounded_duration(self) -> Optional[int]:
        if self.duration_ms is None or isinstance(self.duration_ms, bool):
            return None
        try:
            value = int(self.duration_ms)
        except (TypeError, ValueError, OverflowError):
            return None
        return min(MAX_EVENT_DURATION_MS, max(0, value))

    def bounded_count(self) -> int:
        if isinstance(self.count, bool):
            return 1
        try:
            value = int(self.count)
        except (TypeError, ValueError, OverflowError):
            return 1
        return min(MAX_EVENT_COUNT, max(1, value))


def normalize_surface(value: object) -> Surface:
    raw = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "ink": Surface.TUI,
        "electron": Surface.DESKTOP,
        "browser": Surface.WEB,
        "whatsapp": Surface.GATEWAY,
        "signal": Surface.GATEWAY,
        "matrix": Surface.GATEWAY,
        "mattermost": Surface.GATEWAY,
    }
    if raw in aliases:
        return aliases[raw]
    try:
        return Surface(raw)
    except ValueError:
        return Surface.UNKNOWN


def normalize_provider(value: object) -> Provider:
    raw = str(value or "").strip().casefold().replace("-", "_")
    if raw in {"chatgpt", "codex", "openai_codex", "openai_compatible"}:
        return Provider.OPENAI
    if raw in {"grok", "x_ai", "xai_oauth"}:
        return Provider.XAI
    if raw in {"gemini", "vertex", "vertex_ai"}:
        return Provider.GOOGLE
    if raw in {"aws", "aws_bedrock"}:
        return Provider.BEDROCK
    if raw.startswith("azure"):
        return Provider.AZURE
    try:
        return Provider(raw)
    except ValueError:
        return Provider.UNKNOWN


__all__ = [
    "Capability",
    "EVENT_SCHEMA_VERSION",
    "EventDraft",
    "EventSource",
    "EventType",
    "Outcome",
    "Provider",
    "Surface",
    "normalize_provider",
    "normalize_surface",
]
