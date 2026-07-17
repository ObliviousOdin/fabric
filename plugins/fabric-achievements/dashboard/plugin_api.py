"""Fabric Achievements dashboard plugin backend.

Mounted at /api/plugins/fabric-achievements/ by the Fabric dashboard.
"""
from __future__ import annotations

import base64
import functools
import ipaddress
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

try:
    from fabric_constants import get_fabric_home
except ImportError:
    def get_fabric_home() -> Path:  # type: ignore[misc]
        val = (os.environ.get("FABRIC_HOME") or "").strip()
        return Path(val) if val else Path.home() / ".fabric"

# Reuse Fabric's canonical Tailscale integration (the same code behind
# ``fabric setup tailscale``) instead of re-implementing binary discovery and
# status parsing. Imported optionally so the plugin still loads if the wider
# Fabric CLI isn't importable (e.g. a standalone plugin checkout); a local probe
# in ``detect_tailscale`` is the fallback.
try:  # pragma: no cover - trivially importable inside the dashboard process
    from fabric_cli.tailscale_setup import (
        find_tailscale_binary as _ts_find_binary,
        tailscale_status as _ts_status,
    )
except Exception:  # noqa: BLE001
    _ts_find_binary = None  # type: ignore[assignment]
    _ts_status = None  # type: ignore[assignment]

try:
    from fastapi import APIRouter, Request
except Exception:  # Allows local unit tests without dashboard dependencies.
    class APIRouter:  # type: ignore
        def get(self, *_args, **_kwargs):
            return lambda fn: fn
        def post(self, *_args, **_kwargs):
            return lambda fn: fn

    class Request:  # type: ignore
        """Minimal stand-in so signatures import without FastAPI installed."""

try:
    from fastapi.concurrency import run_in_threadpool
except Exception:  # pragma: no cover - exercised only without FastAPI
    run_in_threadpool = None  # type: ignore[assignment]

router = APIRouter()

SNAPSHOT_TTL_SECONDS = 120
_SCAN_LOCK = threading.Lock()
_SNAPSHOT_CACHE: Optional[Dict[str, Any]] = None
_SNAPSHOT_CACHE_AT = 0
_SCAN_STATUS: Dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "last_error": None,
    "last_duration_ms": None,
    "run_count": 0,
}

ERROR_RE = re.compile(r"\b(error|failed|failure|traceback|exception|permission denied|not found|eaddrinuse|already in use|timed out|blocked)\b", re.I)
PORT_RE = re.compile(r"\b(port\s+)?(3000|5173|8000|8080|9119)\b.*\b(in use|already|taken|eaddrinuse)\b|\beaddrinuse\b", re.I)
INSTALL_RE = re.compile(r"\b(npm|pnpm|yarn|pip|uv)\b.*\b(install|add)\b", re.I)
SUCCESS_RE = re.compile(r"\b(success|passed|built|compiled|done|exit_code[\"']?\s*[:=]\s*0|verified|ok)\b", re.I)
FILE_RE = re.compile(r"(?:/home/|~/?|\./|/mnt/)[\w./-]+\.(?:py|js|ts|tsx|jsx|css|html|md|json|yaml|yml|svg|sql|sh)")

TIER_NAMES = ["Copper", "Silver", "Gold", "Diamond", "Olympian"]


def tiers(values: List[int]) -> List[Dict[str, Any]]:
    return [{"name": name, "threshold": threshold} for name, threshold in zip(TIER_NAMES, values)]


def req(metric: str, gte: int) -> Dict[str, Any]:
    return {"metric": metric, "gte": gte}


ACHIEVEMENTS: List[Dict[str, Any]] = [
    # Agent Autonomy — mostly best-session feats
    {"id": "let_him_cook", "name": "Let Him Cook", "description": "Let Fabric run a serious autonomous tool chain in one session.", "category": "Agent Autonomy", "kind": "best_session", "icon": "flame", "threshold_metric": "max_tool_calls_in_session", "tiers": tiers([200, 500, 1200, 3000, 8000])},
    {"id": "autonomous_avalanche", "name": "Autonomous Avalanche", "description": "Accumulate a lifetime avalanche of Fabric tool calls across sessions.", "category": "Agent Autonomy", "kind": "lifetime", "icon": "avalanche", "threshold_metric": "total_tool_calls", "tiers": tiers([1000, 3000, 8000, 20000, 50000])},
    {"id": "toolchain_maxxer", "name": "Toolchain Maxxer", "description": "Use a wide spread of distinct Fabric tools in one session.", "category": "Agent Autonomy", "kind": "best_session", "icon": "nodes", "threshold_metric": "max_distinct_tools_in_session", "tiers": tiers([18, 28, 45, 70, 100])},
    {"id": "full_send", "name": "Full Send", "description": "Terminal, files, and web/browser all get involved in one real run.", "category": "Agent Autonomy", "kind": "multi_condition", "icon": "rocket", "requirements": [req("max_terminal_calls_in_session", 180), req("max_file_tool_calls_in_session", 120), req("max_web_browser_calls_in_session", 60)]},
    {"id": "subagent_commander", "name": "Subagent Commander", "description": "Coordinate delegated agent work.", "category": "Agent Autonomy", "kind": "lifetime", "icon": "branch", "threshold_metric": "total_delegate_calls", "tiers": tiers([5, 40, 100, 1000, 5000])},
    {"id": "background_process_enjoyer", "name": "Background Process Enjoyer", "description": "Start or control enough long-running processes to deserve the title.", "category": "Agent Autonomy", "kind": "lifetime", "icon": "daemon", "threshold_metric": "total_process_calls", "tiers": tiers([300, 800, 2000, 6000, 15000])},
    {"id": "cron_necromancer", "name": "Cron Necromancer", "description": "Raise scheduled autonomous jobs from the dead.", "category": "Agent Autonomy", "kind": "lifetime", "icon": "clock", "threshold_metric": "total_cron_calls", "tiers": tiers([1000, 3000, 8000, 20000, 50000])},

    # Debugging Chaos — higher thresholds + multi-condition events
    {"id": "red_text_connoisseur", "name": "Red Text Connoisseur", "description": "Encounter enough errors to develop a palate for red text.", "category": "Debugging Chaos", "kind": "lifetime", "icon": "warning", "threshold_metric": "total_errors", "tiers": tiers([1500, 4000, 10000, 25000, 75000])},
    {"id": "stack_trace_sommelier", "name": "Stack Trace Sommelier", "description": "Taste tracebacks by the flight, not by the sip.", "category": "Debugging Chaos", "kind": "lifetime", "icon": "wine", "threshold_metric": "traceback_events", "tiers": tiers([300, 1000, 3000, 8000, 20000])},
    {"id": "actually_read_the_logs", "name": "Actually Read The Logs", "description": "Inspect logs repeatedly instead of guessing.", "category": "Debugging Chaos", "kind": "lifetime", "icon": "scroll", "threshold_metric": "log_read_events", "tiers": tiers([1000, 3000, 8000, 20000, 50000])},
    {"id": "port_3000_taken", "name": "Port 3000 Is Taken", "description": "Discover dev-server port conflict patterns enough times to become numb.", "category": "Debugging Chaos", "kind": "lifetime", "icon": "plug", "secret": True, "threshold_metric": "port_conflict_events", "tiers": tiers([15, 40, 100, 300, 1000])},
    {"id": "permission_denied_any_percent", "name": "Permission Denied Any%", "description": "Speedrun into permission walls.", "category": "Debugging Chaos", "kind": "lifetime", "icon": "lock", "secret": True, "threshold_metric": "permission_denied_events", "tiers": tiers([25, 75, 200, 600, 1500])},
    {"id": "dependency_hell_tourist", "name": "Dependency Hell Tourist", "description": "Package installs fail, then somehow life continues.", "category": "Debugging Chaos", "kind": "multi_condition", "icon": "package_skull", "requirements": [req("install_error_events", 25), req("install_success_events", 10)]},
    {"id": "the_fix_was_restarting", "name": "The Fix Was Restarting It", "description": "Restart after enough error clusters to call it a technique.", "category": "Debugging Chaos", "kind": "multi_condition", "icon": "restart", "requirements": [req("restart_after_error_events", 50), req("total_errors", 4000)]},
    {"id": "forgot_the_env_var", "name": "Forgot The Env Var", "description": "Auth or configuration failed because an environment variable was missing.", "category": "Debugging Chaos", "kind": "lifetime", "icon": "key", "secret": True, "threshold_metric": "env_var_error_events", "tiers": tiers([5000, 15000, 40000, 100000, 250000])},
    {"id": "yaml_colon_incident", "name": "YAML Colon Incident", "description": "Configuration syntax bites back.", "category": "Debugging Chaos", "kind": "lifetime", "icon": "colon", "secret": True, "threshold_metric": "yaml_error_events", "tiers": tiers([1000, 3000, 8000, 20000, 50000])},
    {"id": "docker_name_collision", "name": "Docker Name Collision", "description": "A container name already exists. Of course it does.", "category": "Debugging Chaos", "kind": "lifetime", "icon": "container", "secret": True, "threshold_metric": "docker_conflict_events", "tiers": tiers([75, 200, 600, 1500, 4000])},

    # Vibe Coding
    {"id": "supposed_to_be_quick", "name": "This Was Supposed To Be Quick", "description": "A tiny ask becomes an entire expedition.", "category": "Vibe Coding", "kind": "best_session", "icon": "melting_clock", "threshold_metric": "max_messages_in_session", "tiers": tiers([300, 600, 1200, 2500, 6000])},
    {"id": "one_more_small_change", "name": "One More Small Change", "description": "Make enough file edits in one session to invalidate the phrase small change.", "category": "Vibe Coding", "kind": "best_session", "icon": "pencil", "threshold_metric": "max_file_tool_calls_in_session", "tiers": tiers([150, 400, 1000, 3000, 8000])},
    {"id": "vibe_architect", "name": "Vibe Architect", "description": "Touch a broad surface area in one project session.", "category": "Vibe Coding", "kind": "best_session", "icon": "blueprint", "threshold_metric": "max_files_touched_in_session", "tiers": tiers([300, 700, 1500, 4000, 10000])},
    {"id": "pixel_goblin", "name": "Pixel Goblin", "description": "Do sustained frontend, CSS, SVG, or visual tuning.", "category": "Vibe Coding", "kind": "lifetime", "icon": "pixel", "threshold_metric": "frontend_activity_events", "tiers": tiers([20000, 50000, 120000, 300000, 800000])},
    {"id": "ship_first_ask_later", "name": "Ship First, Ask Later", "description": "Git activity after a serious tool chain.", "category": "Vibe Coding", "kind": "multi_condition", "icon": "ship", "requirements": [req("git_events", 50), req("max_tool_calls_in_session", 500)]},
    {"id": "css_exorcist", "name": "CSS Exorcist", "description": "Cast repeated styling demons out of the interface.", "category": "Vibe Coding", "kind": "lifetime", "icon": "spark_cursor", "threshold_metric": "css_activity_events", "tiers": tiers([10000, 30000, 80000, 200000, 500000])},
    {"id": "one_character_fix", "name": "One Character Fix", "description": "A tiny edit after a pile of errors. Painful. Beautiful.", "category": "Vibe Coding", "kind": "multi_condition", "icon": "needle", "secret": True, "requirements": [req("tiny_patch_after_errors_events", 5), req("total_errors", 4000)]},

    # Fabric Native
    {"id": "skillsmith", "name": "Skillsmith", "description": "Work with Fabric skills enough to leave fingerprints.", "category": "Fabric Native", "kind": "lifetime", "icon": "hammer_scroll", "threshold_metric": "skill_events", "tiers": tiers([5000, 15000, 40000, 100000, 250000])},
    {"id": "skill_issue_skill_created", "name": "Skill Issue? Skill Created.", "description": "Create or patch durable procedures instead of repeating yourself.", "category": "Fabric Native", "kind": "lifetime", "icon": "anvil", "threshold_metric": "skill_manage_events", "tiers": tiers([25, 75, 200, 600, 1500])},
    {"id": "memory_keeper", "name": "Memory Keeper", "description": "Persist durable knowledge with memory or Mnemosyne.", "category": "Fabric Native", "kind": "lifetime", "icon": "crystal", "threshold_metric": "memory_events", "tiers": tiers([100, 300, 1000, 3000, 8000])},
    {"id": "memory_palace", "name": "Memory Palace", "description": "Build a serious durable-memory trail.", "category": "Fabric Native", "kind": "lifetime", "icon": "palace", "threshold_metric": "memory_write_events", "tiers": tiers([100, 300, 1000, 3000, 8000])},
    {"id": "context_dragon", "name": "Context Dragon", "description": "Brush against compression, huge context, or token pressure repeatedly.", "category": "Fabric Native", "kind": "lifetime", "icon": "dragon", "threshold_metric": "context_events", "tiers": tiers([5000, 15000, 40000, 100000, 250000])},
    {"id": "gateway_dweller", "name": "Gateway Dweller", "description": "Live through gateway-connected Fabric workflows.", "category": "Fabric Native", "kind": "lifetime", "icon": "antenna", "threshold_metric": "gateway_events", "tiers": tiers([5000, 15000, 40000, 100000, 250000])},
    {"id": "plugin_goblin", "name": "Plugin Goblin", "description": "Use or develop plugins enough that the dashboard notices.", "category": "Fabric Native", "kind": "lifetime", "icon": "puzzle", "threshold_metric": "plugin_events", "tiers": tiers([1000, 3000, 8000, 20000, 50000])},
    {"id": "rollback_wizard", "name": "Rollback Wizard", "description": "Invoke rollback/checkpoint recovery magic.", "category": "Fabric Native", "kind": "lifetime", "icon": "rewind", "secret": True, "threshold_metric": "rollback_events", "tiers": tiers([500, 1500, 4000, 10000, 25000])},

    # Research/Web
    {"id": "rabbit_hole_certified", "name": "Rabbit Hole Certified", "description": "Search or extract enough web content to qualify as a research spiral.", "category": "Research/Web", "kind": "lifetime", "icon": "spiral", "threshold_metric": "total_web_calls", "tiers": tiers([400, 1200, 3000, 8000, 20000])},
    {"id": "citation_goblin", "name": "Citation Goblin", "description": "Extract enough web pages to become a tiny librarian.", "category": "Research/Web", "kind": "lifetime", "icon": "quote", "threshold_metric": "total_web_extract_calls", "tiers": tiers([100, 300, 1000, 3000, 8000])},
    {"id": "docs_archaeologist", "name": "Docs Archaeologist", "description": "Dig through documentation sources over and over.", "category": "Research/Web", "kind": "lifetime", "icon": "compass", "threshold_metric": "docs_activity_events", "tiers": tiers([5000, 15000, 40000, 100000, 250000])},
    {"id": "browser_possession", "name": "Browser Possession", "description": "Possess a browser through automation repeatedly.", "category": "Research/Web", "kind": "lifetime", "icon": "browser", "threshold_metric": "browser_calls", "tiers": tiers([75, 200, 600, 1500, 4000])},

    # Tool Mastery
    {"id": "terminal_goblin", "name": "Terminal Goblin", "description": "Spend serious time in shell-land.", "category": "Tool Mastery", "kind": "lifetime", "icon": "terminal", "threshold_metric": "total_terminal_calls", "tiers": tiers([750, 2000, 6000, 15000, 50000])},
    {"id": "patch_wizard", "name": "Patch Wizard", "description": "Bend files to your will with targeted patches.", "category": "Tool Mastery", "kind": "lifetime", "icon": "wand", "threshold_metric": "total_patch_calls", "tiers": tiers([250, 750, 2000, 6000, 15000])},
    {"id": "file_archaeologist", "name": "File Archaeologist", "description": "Dig through the filesystem with reads and searches.", "category": "Tool Mastery", "kind": "lifetime", "icon": "folder", "threshold_metric": "total_file_reads_searches", "tiers": tiers([750, 2000, 6000, 15000, 50000])},
    {"id": "image_whisperer", "name": "Image Whisperer", "description": "Use image generation or vision tools enough for visual work.", "category": "Tool Mastery", "kind": "lifetime", "icon": "eye", "threshold_metric": "image_vision_calls", "tiers": tiers([100, 300, 1000, 3000, 8000])},
    {"id": "voice_of_the_machine", "name": "Voice Of The Machine", "description": "Use text-to-speech or voice tooling repeatedly.", "category": "Tool Mastery", "kind": "lifetime", "icon": "wave", "threshold_metric": "tts_calls", "tiers": tiers([10, 30, 100, 300, 800])},

    # Model Lore
    {"id": "model_hopper", "name": "Model Hopper", "description": "Switch or inspect providers/models enough to count as a habit.", "category": "Model Lore", "kind": "lifetime", "icon": "swap", "threshold_metric": "model_events", "tiers": tiers([10000, 30000, 80000, 200000, 500000])},
    {"id": "openrouter_enjoyer", "name": "OpenRouter Enjoyer", "description": "Route model work through OpenRouter repeatedly.", "category": "Model Lore", "kind": "lifetime", "icon": "router", "threshold_metric": "openrouter_events", "tiers": tiers([250, 750, 2000, 6000, 15000])},
    {"id": "codex_conjurer", "name": "Codex Conjurer", "description": "Summon Codex-flavored assistance often enough for a ritual.", "category": "Model Lore", "kind": "lifetime", "icon": "codex", "threshold_metric": "codex_events", "tiers": tiers([500, 1500, 4000, 10000, 25000])},
    {"id": "multi_model_mage", "name": "Multi-Model Mage", "description": "Use a real spread of distinct model names across Fabric history.", "category": "Model Lore", "kind": "lifetime", "icon": "prism", "threshold_metric": "distinct_model_count", "tiers": tiers([10, 20, 40, 80, 160])},
    {"id": "five_model_flight", "name": "Five-Model Flight", "description": "Try at least five distinct LLMs instead of marrying the first model that answers.", "category": "Model Lore", "kind": "lifetime", "icon": "prism", "threshold_metric": "distinct_model_count", "tiers": tiers([5, 10, 20, 40, 80])},
    {"id": "provider_polyglot", "name": "Provider Polyglot", "description": "Use models from multiple providers across Fabric history.", "category": "Model Lore", "kind": "lifetime", "icon": "swap", "threshold_metric": "distinct_provider_count", "tiers": tiers([2, 3, 5, 8, 12])},
    {"id": "model_sommelier", "name": "Model Sommelier", "description": "Taste enough model/provider conversations to develop preferences.", "category": "Model Lore", "kind": "lifetime", "icon": "wine", "threshold_metric": "model_events", "tiers": tiers([250, 750, 2000, 6000, 15000])},
    {"id": "claude_confidant", "name": "Claude Confidant", "description": "Bring Claude-flavored reasoning into the workflow repeatedly.", "category": "Model Lore", "kind": "lifetime", "icon": "quote", "threshold_metric": "claude_events", "tiers": tiers([50, 150, 500, 1500, 4000])},
    {"id": "gemini_cartographer", "name": "Gemini Cartographer", "description": "Map enough Gemini-related workflows to know the terrain.", "category": "Model Lore", "kind": "lifetime", "icon": "compass", "threshold_metric": "gemini_events", "tiers": tiers([50, 150, 500, 1500, 4000])},
    {"id": "open_weights_pilgrim", "name": "Open Weights Pilgrim", "description": "Actually chat with local/open-weight models through Fabric session metadata.", "category": "Model Lore", "kind": "lifetime", "icon": "terminal", "threshold_metric": "local_model_chat_sessions", "tiers": tiers([1, 3, 10, 30, 100])},

    # Workflow Intelligence
    {"id": "toolset_cartographer", "name": "Toolset Cartographer", "description": "Navigate Fabric toolsets deliberately instead of treating tools as a blur.", "category": "Fabric Native", "kind": "lifetime", "icon": "compass", "threshold_metric": "toolset_events", "tiers": tiers([20, 60, 200, 600, 1500])},
    {"id": "config_surgeon", "name": "Config Surgeon", "description": "Operate on real config files, manifests, env files, and dashboard settings without flinching.", "category": "Fabric Native", "kind": "lifetime", "icon": "key", "threshold_metric": "config_events", "tiers": tiers([100, 300, 1000, 3000, 10000])},
    {"id": "rebase_acrobat", "name": "Rebase Acrobat", "description": "Handle real git history surgery: rebase, conflict, merge, fetch, push.", "category": "Vibe Coding", "kind": "lifetime", "icon": "branch", "threshold_metric": "git_history_events", "tiers": tiers([10, 30, 100, 300, 800])},
    {"id": "test_suite_tamer", "name": "Test Suite Tamer", "description": "Run enough verification commands that green text becomes part of the ritual.", "category": "Tool Mastery", "kind": "lifetime", "icon": "daemon", "threshold_metric": "test_events", "tiers": tiers([100, 300, 800, 2400, 6000])},
    {"id": "screenshot_hunter", "name": "Screenshot Hunter", "description": "Capture, inspect, and polish visual proof instead of just claiming it works.", "category": "Tool Mastery", "kind": "lifetime", "icon": "eye", "threshold_metric": "screenshot_events", "tiers": tiers([50, 150, 500, 1500, 5000])},

    # Lifestyle
    {"id": "marathon_operator", "name": "Marathon Operator", "description": "Accumulate a serious number of Fabric sessions.", "category": "Lifestyle", "kind": "lifetime", "icon": "marathon", "threshold_metric": "session_count", "tiers": tiers([75, 200, 500, 1500, 5000])},
    {"id": "weekend_warrior", "name": "Weekend Warrior", "description": "Run Fabric on weekends enough times to make it a lifestyle.", "category": "Lifestyle", "kind": "lifetime", "icon": "calendar", "threshold_metric": "weekend_sessions", "tiers": tiers([25, 75, 200, 600, 1500])},
    {"id": "night_shift_operator", "name": "Night Shift Operator", "description": "Run sessions during gremlin hours repeatedly.", "category": "Lifestyle", "kind": "lifetime", "icon": "moon", "threshold_metric": "night_sessions", "tiers": tiers([25, 75, 200, 600, 1500])},
    {"id": "cache_hit_appreciator", "name": "Cache Hit Appreciator", "description": "Notice or benefit from prompt/cache behavior.", "category": "Lifestyle", "kind": "lifetime", "icon": "cache", "secret": True, "threshold_metric": "cache_events", "tiers": tiers([100, 300, 1000, 3000, 8000])},
]


def state_path() -> Path:
    return get_fabric_home() / "plugins" / "fabric-achievements" / "state.json"


def snapshot_path() -> Path:
    return get_fabric_home() / "plugins" / "fabric-achievements" / "scan_snapshot.json"


def checkpoint_path() -> Path:
    return get_fabric_home() / "plugins" / "fabric-achievements" / "scan_checkpoint.json"


def load_state() -> Dict[str, Any]:
    path = state_path()
    if not path.exists():
        return {"unlocks": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"unlocks": {}}


def save_state(state: Dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, set):
        return sorted(_json_safe(v) for v in value)
    return value


def load_snapshot() -> Optional[Dict[str, Any]]:
    path = snapshot_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def save_snapshot(data: Dict[str, Any]) -> None:
    path = snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(data), indent=2, sort_keys=True))


def load_checkpoint() -> Dict[str, Any]:
    path = checkpoint_path()
    if not path.exists():
        return {"schema_version": 1, "generated_at": 0, "sessions": {}}
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            data.setdefault("schema_version", 1)
            data.setdefault("generated_at", 0)
            data.setdefault("sessions", {})
            if isinstance(data.get("sessions"), dict):
                return data
    except Exception:
        pass
    return {"schema_version": 1, "generated_at": 0, "sessions": {}}


def save_checkpoint(data: Dict[str, Any]) -> None:
    path = checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(data), indent=2, sort_keys=True))


def session_fingerprint(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "last_active": meta.get("last_active"),
        "started_at": meta.get("started_at"),
        "model": meta.get("model"),
        "title": meta.get("title") or meta.get("preview") or "Untitled",
    }


def _cache_is_fresh(now: int) -> bool:
    return _SNAPSHOT_CACHE is not None and (now - _SNAPSHOT_CACHE_AT) <= SNAPSHOT_TTL_SECONDS


def _is_snapshot_stale(snapshot: Optional[Dict[str, Any]], now: Optional[int] = None) -> bool:
    if not isinstance(snapshot, dict):
        return True
    ts = int(snapshot.get("generated_at") or 0)
    current = int(now or time.time())
    if ts <= 0:
        return True
    return (current - ts) > SNAPSHOT_TTL_SECONDS


def _scan_status_payload(now: Optional[int] = None) -> Dict[str, Any]:
    current = int(now or time.time())
    snap = _SNAPSHOT_CACHE if isinstance(_SNAPSHOT_CACHE, dict) else None
    generated_at = int((snap or {}).get("generated_at") or 0) if snap else 0
    return {
        "state": _SCAN_STATUS.get("state", "idle"),
        "started_at": _SCAN_STATUS.get("started_at"),
        "finished_at": _SCAN_STATUS.get("finished_at"),
        "last_error": _SCAN_STATUS.get("last_error"),
        "last_duration_ms": _SCAN_STATUS.get("last_duration_ms"),
        "run_count": _SCAN_STATUS.get("run_count", 0),
        "ttl_seconds": SNAPSHOT_TTL_SECONDS,
        "snapshot_generated_at": generated_at or None,
        "snapshot_age_seconds": (current - generated_at) if generated_at else None,
        "snapshot_stale": _is_snapshot_stale(snap, current),
    }


def _tool_name_from_call(call: Any) -> Optional[str]:
    if not isinstance(call, dict):
        return None
    fn = call.get("function") or {}
    return call.get("name") or fn.get("name")


def _content(msg: Dict[str, Any]) -> str:
    content = msg.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content)
    except Exception:
        return str(content)


def _count_tool(tool_names: List[str], *needles: str) -> int:
    lowered = [name.lower() for name in tool_names]
    return sum(1 for name in lowered if any(needle in name for needle in needles))


def model_provider(model_name: str) -> Optional[str]:
    name = (model_name or "").strip().lower()
    if not name or name == "none":
        return None
    if "/" in name:
        return name.split("/", 1)[0]
    for provider in ["openai", "anthropic", "google", "gemini", "mistral", "meta", "qwen", "deepseek", "xai", "nous", "ollama", "groq", "openrouter", "codex"]:
        if provider in name:
            return "google" if provider == "gemini" else provider
    return name.split(":", 1)[0].split("-", 1)[0]


def is_local_model_name(model_name: str) -> bool:
    name = (model_name or "").strip().lower()
    if not name or name == "none":
        return False
    local_markers = ["ollama", "llama.cpp", "localhost", "127.0.0.1", "local/", "local:", "gguf", "vllm-local"]
    return any(marker in name for marker in local_markers)


def analyze_messages(session_id: str, title: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    tool_names: Set[str] = set()
    tool_sequence: List[str] = []
    files_touched: Set[str] = set()
    full_text_parts: List[str] = []
    error_count = 0

    for msg in messages:
        text = _content(msg)
        full_text_parts.append(text)
        if msg.get("tool_name"):
            name = str(msg["tool_name"])
            tool_names.add(name)
            # Tool result rows name the tool that already appeared in the assistant tool_calls.
            # Keep it for distinct-tool detection, but do not double-count it as a new call.
            if msg.get("role") != "tool":
                tool_sequence.append(name)
        for call in msg.get("tool_calls") or []:
            name = _tool_name_from_call(call)
            if name:
                tool_names.add(name)
                tool_sequence.append(name)
        if ERROR_RE.search(text):
            error_count += 1
        blob = text
        if msg.get("tool_calls"):
            blob += " " + json.dumps(msg.get("tool_calls"), default=str)
        files_touched.update(FILE_RE.findall(blob))

    full_text = "\n".join(full_text_parts)
    lower = full_text.lower()
    terminal_calls = _count_tool(tool_sequence, "terminal")
    web_calls = _count_tool(tool_sequence, "web_search", "web_extract")
    web_extract_calls = _count_tool(tool_sequence, "web_extract")
    browser_calls = _count_tool(tool_sequence, "browser")
    web_browser_calls = web_calls + browser_calls
    patch_calls = _count_tool(tool_sequence, "patch")
    file_reads_searches = _count_tool(tool_sequence, "read_file", "search_files")
    file_tool_calls = _count_tool(tool_sequence, "read_file", "write_file", "patch", "search_files")
    delegate_calls = _count_tool(tool_sequence, "delegate_task")
    process_calls = _count_tool(tool_sequence, "process") + len(re.findall(r"background\s*=\s*true", full_text, re.I))
    cron_calls = _count_tool(tool_sequence, "cronjob")
    image_vision_calls = _count_tool(tool_sequence, "image", "vision")
    tts_calls = _count_tool(tool_sequence, "tts", "text_to_speech")
    skill_events = _count_tool(tool_sequence, "skill") + len(re.findall(r"\bskill", lower))
    skill_manage_events = _count_tool(tool_sequence, "skill_manage")
    memory_events = _count_tool(tool_sequence, "memory", "mnemosyne")
    memory_write_events = _count_tool(tool_sequence, "mnemosyne_remember", "memory")

    return {
        "session_id": session_id,
        "title": title or "Untitled session",
        "message_count": len(messages),
        "tool_call_count": len(tool_sequence),
        "tool_names": tool_names,
        "distinct_tool_count": len(tool_names),
        "error_count": error_count,
        "terminal_calls": terminal_calls,
        "web_calls": web_calls,
        "web_extract_calls": web_extract_calls,
        "browser_calls": browser_calls,
        "web_browser_calls": web_browser_calls,
        "patch_calls": patch_calls,
        "file_reads_searches": file_reads_searches,
        "file_tool_calls": file_tool_calls,
        "files_touched_count": len(files_touched),
        "delegate_calls": delegate_calls,
        "process_calls": process_calls,
        "cron_calls": cron_calls,
        "image_vision_calls": image_vision_calls,
        "tts_calls": tts_calls,
        "skill_events": skill_events,
        "skill_manage_events": skill_manage_events,
        "memory_events": memory_events,
        "memory_write_events": memory_write_events,
        "port_conflict": bool(PORT_RE.search(full_text)),
        "port_conflict_events": 1 if PORT_RE.search(full_text) else 0,
        "traceback_events": len(re.findall(r"traceback|exception", full_text, re.I)),
        "log_read_events": len(re.findall(r"gateway\.log|errors\.log|agent\.log|/api/logs|\blogs\b", full_text, re.I)),
        "permission_denied_events": len(re.findall(r"permission denied|eacces|operation not permitted", full_text, re.I)),
        "install_error_events": 1 if INSTALL_RE.search(full_text) and ERROR_RE.search(full_text) else 0,
        "install_success_events": 1 if INSTALL_RE.search(full_text) and SUCCESS_RE.search(full_text) else 0,
        "restart_after_error_events": 1 if error_count and re.search(r"\brestart|reload|kill|start\b", full_text, re.I) else 0,
        "env_var_error_events": len(re.findall(r"missing .*env|api key|environment variable|not configured|unauthorized|auth", full_text, re.I)),
        "yaml_error_events": len(re.findall(r"yaml|yml|colon|parse error", full_text, re.I)) if ERROR_RE.search(full_text) else 0,
        "docker_conflict_events": len(re.findall(r"docker.*(name|container).*already|container name conflict|Conflict\. The container", full_text, re.I)),
        "frontend_activity_events": len(re.findall(r"\.(css|svg|tsx|jsx)|frontend|tailwind|react", full_text, re.I)),
        "css_activity_events": len(re.findall(r"\.css|tailwind|style|className|visual", full_text, re.I)),
        "git_events": len(re.findall(r"\bgit\s+(commit|push|merge|rebase|status|diff)", full_text, re.I)),
        "tiny_patch_after_errors_events": 1 if error_count >= 5 and re.search(r"one character|single character|typo", full_text, re.I) else 0,
        "context_events": len(re.findall(r"compress|context window|token|cache", full_text, re.I)),
        "gateway_events": len(re.findall(r"gateway|discord|telegram|slack|api_server", full_text, re.I)),
        "plugin_events": len(re.findall(r"plugin|dashboard-plugins|manifest\.json", full_text, re.I)),
        "rollback_events": len(re.findall(r"rollback|checkpoint", full_text, re.I)),
        "docs_activity_events": len(re.findall(r"docs|documentation|docusaurus|README", full_text, re.I)),
        "model_events": len(re.findall(r"model|provider|openrouter|codex|gemini|claude|anthropic|openai|mistral|qwen|deepseek|llama|ollama|vllm|gguf", full_text, re.I)),
        "openrouter_events": len(re.findall(r"openrouter", full_text, re.I)),
        "codex_events": len(re.findall(r"codex", full_text, re.I)),
        "claude_events": len(re.findall(r"claude|anthropic", full_text, re.I)),
        "gemini_events": len(re.findall(r"gemini|google ai|google model", full_text, re.I)),
        "local_model_events": len(re.findall(r"ollama|llama\.cpp|gguf|vllm|local model|open[- ]weight|open weights", full_text, re.I)),
        "toolset_events": len(re.findall(r"toolset|enabled_toolsets|browser tool|terminal tool|file tool|web tool", full_text, re.I)),
        "config_events": len(re.findall(r"config\.ya?ml|\b[a-z0-9_-]+config\.(?:js|ts|json|ya?ml)|\.env(?:\b|\.)|manifest\.json|settings\.json|pyproject\.toml|package\.json", full_text, re.I)),
        "git_history_events": len(re.findall(r"\bgit\s+(rebase|merge|fetch|pull|push|tag|checkout)|merge conflict|conflict\s*\(|rebase --continue", full_text, re.I)),
        "test_events": len(re.findall(r"pytest|unittest|vitest|playwright|npm test|pnpm test|node --check|py_compile|tests? passed|\bOK\b", full_text, re.I)),
        "screenshot_events": len(re.findall(r"screenshot|playwright|vision_analyze|browser_vision|\.png|image data", full_text, re.I)),
        "release_events": len(re.findall(r"\bgit\s+tag|release|version bump|changelog|publish|pushed? tag", full_text, re.I)),
        "cache_events": len(re.findall(r"cache hit|prompt caching|cache_read", full_text, re.I)),
        "model_names": set(),
    }


def evaluate_tiered(definition: Dict[str, Any], aggregate: Dict[str, Any]) -> Dict[str, Any]:
    metric = definition["threshold_metric"]
    progress = int(aggregate.get(metric, 0) or 0)
    tiers_list = sorted(definition.get("tiers", []), key=lambda t: t["threshold"])
    achieved = [t for t in tiers_list if progress >= t["threshold"]]
    next_tiers = [t for t in tiers_list if progress < t["threshold"]]
    tier = achieved[-1]["name"] if achieved else None
    next_tier = next_tiers[0]["name"] if next_tiers else None
    next_threshold = next_tiers[0]["threshold"] if next_tiers else (tiers_list[-1]["threshold"] if tiers_list else 1)
    current_threshold = achieved[-1]["threshold"] if achieved else 0
    denom = max(1, next_threshold - current_threshold)
    pct = 100 if not next_tiers and achieved else max(0, min(99, math.floor(((progress - current_threshold) / denom) * 100)))
    unlocked = bool(achieved)
    discovered = bool(progress > 0)
    state = "unlocked" if unlocked else ("secret" if definition.get("secret") and not discovered else "discovered")
    return {"unlocked": unlocked, "discovered": discovered or not definition.get("secret"), "state": state, "tier": tier, "progress": progress, "next_tier": next_tier, "next_threshold": next_threshold, "progress_pct": pct}


def evaluate_requirements(definition: Dict[str, Any], aggregate: Dict[str, Any]) -> Dict[str, Any]:
    requirements = definition.get("requirements", [])
    if not requirements:
        return {"unlocked": False, "discovered": not definition.get("secret"), "state": "secret" if definition.get("secret") else "discovered", "tier": None, "progress": 0, "next_tier": None, "next_threshold": 1, "progress_pct": 0}
    parts = []
    any_progress = False
    complete = True
    for requirement in requirements:
        value = int(aggregate.get(requirement["metric"], 0) or 0)
        threshold = int(requirement.get("gte", 1))
        any_progress = any_progress or value > 0
        complete = complete and value >= threshold
        parts.append(min(1.0, value / max(1, threshold)))
    pct = math.floor((sum(parts) / len(parts)) * 100)
    state = "unlocked" if complete else ("secret" if definition.get("secret") and not any_progress else "discovered")
    return {"unlocked": complete, "discovered": any_progress or not definition.get("secret"), "state": state, "tier": None, "progress": pct, "next_tier": None, "next_threshold": 100, "progress_pct": 100 if complete else min(99, pct)}


def evaluate_boolean(definition: Dict[str, Any], aggregate: Dict[str, Any]) -> Dict[str, Any]:
    # Backward-compatible helper for old tests/definitions. New catalog avoids simple booleans.
    unlocked = bool(aggregate.get(definition["metric"]))
    return {"unlocked": unlocked, "discovered": True, "state": "unlocked" if unlocked else "discovered", "tier": None, "progress": 1 if unlocked else 0, "next_tier": None, "next_threshold": 1, "progress_pct": 100 if unlocked else 0}


METRIC_LABELS = {
    "max_tool_calls_in_session": "tool calls in one session",
    "max_distinct_tools_in_session": "distinct Fabric tools used in one session",
    "max_terminal_calls_in_session": "terminal calls in one session",
    "max_file_tool_calls_in_session": "file/search/patch calls in one session",
    "max_web_browser_calls_in_session": "web search/extract or browser calls in one session",
    "max_messages_in_session": "messages in one session",
    "max_files_touched_in_session": "files touched in one session",
    "total_delegate_calls": "lifetime delegate_task calls",
    "total_process_calls": "lifetime background process operations",
    "total_cron_calls": "lifetime scheduled-job operations",
    "total_errors": "error/failed/traceback messages observed",
    "traceback_events": "traceback or exception mentions",
    "log_read_events": "log inspections",
    "port_conflict_events": "dev-server port conflict detections",
    "permission_denied_events": "permission-denied errors",
    "install_error_events": "package-install failures",
    "install_success_events": "successful package installs after package work",
    "restart_after_error_events": "restart/reload actions after error clusters",
    "env_var_error_events": "missing auth/config/environment-variable events",
    "yaml_error_events": "YAML/config parse incidents",
    "docker_conflict_events": "Docker/container-name conflicts",
    "frontend_activity_events": "frontend/CSS/SVG/React activity mentions",
    "css_activity_events": "CSS, styling, Tailwind, or className activity",
    "git_events": "git workflow commands",
    "tiny_patch_after_errors_events": "tiny typo-style fixes after error clusters",
    "skill_events": "Fabric skill mentions or tool use",
    "skill_manage_events": "skill_manage create/patch/delete operations",
    "memory_events": "memory or Mnemosyne tool events",
    "memory_write_events": "durable memory writes",
    "context_events": "context, compression, token, or cache-pressure mentions",
    "gateway_events": "gateway/API/chat-platform activity",
    "plugin_events": "dashboard plugin development or usage signals",
    "rollback_events": "rollback/checkpoint recovery mentions",
    "docs_activity_events": "documentation/README/docs activity",
    "model_events": "model/provider-related activity",
    "openrouter_events": "OpenRouter mentions",
    "codex_events": "Codex mentions",
    "cache_events": "prompt-cache/cache-hit mentions",
    "total_web_calls": "lifetime web_search/web_extract calls",
    "total_web_extract_calls": "lifetime web_extract calls",
    "browser_calls": "lifetime browser automation calls",
    "total_tool_calls": "lifetime Fabric tool calls",
    "total_terminal_calls": "lifetime terminal calls",
    "total_patch_calls": "lifetime targeted patch edits",
    "total_file_reads_searches": "lifetime read_file/search_files calls",
    "image_vision_calls": "image generation or vision tool calls",
    "tts_calls": "text-to-speech or voice tool calls",
    "distinct_model_count": "distinct model names seen in session metadata",
    "distinct_provider_count": "distinct model providers inferred from session metadata",
    "claude_events": "Claude/Anthropic model mentions",
    "gemini_events": "Gemini/Google model mentions",
    "local_model_events": "local/open-weight model mentions",
    "local_model_chat_sessions": "Fabric sessions whose model metadata is local/open-weight",
    "toolset_events": "toolset or tool-family mentions",
    "config_events": "configuration/environment/manifest activity",
    "git_history_events": "git history operations such as rebase, merge, fetch, push, or tag",
    "test_events": "test/check/verification command mentions",
    "screenshot_events": "screenshot, Playwright, PNG, or vision-inspection activity",
    "release_events": "release, version, publish, or git tag events",
    "session_count": "Fabric sessions",
    "weekend_sessions": "sessions started on weekends",
    "night_sessions": "sessions started late night or before dawn",
}


def metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " "))


def criteria_for(definition: Dict[str, Any]) -> str:
    if definition.get("secret") and definition.get("state") == "secret":
        return "Secret: exact requirement hidden until Fabric sees the first matching signal. Keep using Fabric across debugging, tools, memory, skills, plugins, and model workflows to reveal it."
    secret_prefix = ""
    if "threshold_metric" in definition:
        tiers_list = sorted(definition.get("tiers", []), key=lambda t: t["threshold"])
        if not tiers_list:
            return secret_prefix + "Requirement: use Fabric in the matching workflow."
        metric = metric_label(definition["threshold_metric"])
        ladder = ", ".join(f"{t['name']} {t['threshold']}" for t in tiers_list)
        return secret_prefix + f"Requirement: {metric}. Tier ladder: {ladder}."
    requirements = definition.get("requirements") or []
    if requirements:
        parts = [f"{metric_label(r['metric'])} ≥ {int(r.get('gte', 1))}" for r in requirements]
        return secret_prefix + "Requirement: " + "; ".join(parts) + "."
    return secret_prefix + "Requirement: complete the matching Fabric behavior."


def display_achievement(item: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(item)
    if clean.get("state") == "secret":
        return {**clean, "name": "???", "description": "Secret achievement: hidden until Fabric detects the first relevant behavior in your session history.", "criteria": criteria_for(clean), "icon": "secret"}
    clean["criteria"] = criteria_for(clean)
    return clean


def scan_sessions(
    limit: Optional[int] = None,
    progress_callback: Optional[Any] = None,
    progress_every: int = 250,
) -> Dict[str, Any]:
    """Scan Fabric sessions and build per-session achievement stats.

    ``limit=None`` (the default) scans the ENTIRE session history. Prior
    versions capped this at 200, which silently reduced achievement totals
    to ~2% of history on long-running installs and made lifetime badges
    unreachable. SQLite's ``LIMIT -1`` means "unlimited"; we map ``None``
    and non-positive values to ``-1`` so callers get the full catalog.

    Warm scans stay cheap: the checkpoint cache stores per-session stats
    keyed by ``(started_at, last_active)`` and only re-analyzes sessions
    whose fingerprint changed. Cold scans on large histories (thousands
    of sessions) take tens of seconds to several minutes; ``evaluate_all``
    runs them on a background thread so the dashboard UI never blocks on
    the first request.

    ``progress_callback(partial_sessions, scanned_so_far, total)`` — when
    provided, fires every ``progress_every`` sessions with the sessions
    analyzed so far and progress counters. Background scans use this to
    publish intermediate snapshots so a long cold scan surfaces badges
    incrementally on each dashboard refresh instead of going all-at-once
    at the end.
    """
    try:
        from fabric_state import SessionDB
    except Exception as exc:
        return {"sessions": [], "aggregate": {}, "error": f"Could not import SessionDB: {exc}", "scan_meta": {"mode": "failed", "sessions_total": 0, "sessions_rescanned": 0, "sessions_reused": 0}}

    checkpoint = load_checkpoint()
    previous_sessions = checkpoint.get("sessions") if isinstance(checkpoint.get("sessions"), dict) else {}
    reused = 0
    rescanned = 0

    # SQLite treats LIMIT -1 as "no limit". Map None / <=0 to -1 so the
    # full session history flows through unless the caller explicitly
    # requests a small sample (e.g. a smoke test).
    db_limit = -1 if (limit is None or limit <= 0) else int(limit)

    db = SessionDB()
    try:
        sessions_meta = db.list_sessions_rich(limit=db_limit, include_children=True, project_compression_tips=False)
        total_sessions = len(sessions_meta)
        sessions: List[Dict[str, Any]] = []
        checkpoint_sessions: Dict[str, Any] = {}
        for idx, meta in enumerate(sessions_meta, start=1):
            sid = meta.get("id")
            if not sid:
                continue
            fp = session_fingerprint(meta)
            cached = previous_sessions.get(sid) if isinstance(previous_sessions, dict) else None
            cached_stats = cached.get("stats") if isinstance(cached, dict) else None
            cached_fp = cached.get("fingerprint") if isinstance(cached, dict) else None

            if isinstance(cached_stats, dict) and cached_fp == fp:
                stats = dict(cached_stats)
                reused += 1
            else:
                messages = db.get_messages(sid)
                stats = analyze_messages(sid, meta.get("title") or meta.get("preview") or "Untitled", messages)
                rescanned += 1

            stats["session_id"] = sid
            stats["title"] = meta.get("title") or meta.get("preview") or stats.get("title") or "Untitled"
            stats["started_at"] = meta.get("started_at")
            stats["last_active"] = meta.get("last_active")
            stats["source"] = meta.get("source")
            if meta.get("model"):
                stats.setdefault("model_names", set())
                if isinstance(stats["model_names"], set):
                    stats["model_names"].add(str(meta.get("model")))
                elif isinstance(stats["model_names"], list):
                    if str(meta.get("model")) not in stats["model_names"]:
                        stats["model_names"].append(str(meta.get("model")))
                else:
                    stats["model_names"] = {str(meta.get("model"))}

            sessions.append(stats)
            checkpoint_sessions[sid] = {"fingerprint": fp, "stats": _json_safe(stats)}

            if progress_callback is not None and progress_every > 0 and (idx % progress_every == 0) and idx < total_sessions:
                try:
                    progress_callback(list(sessions), idx, total_sessions)
                except Exception:
                    # Progress callbacks are advisory — a broken publisher
                    # must never abort the scan itself.
                    pass

        save_checkpoint({
            "schema_version": 1,
            "generated_at": int(time.time()),
            "sessions": checkpoint_sessions,
        })
    finally:
        close = getattr(db, "close", None)
        if close:
            close()
    return {
        "sessions": sessions,
        "aggregate": aggregate_stats(sessions),
        "scan_meta": {
            "mode": "incremental" if reused > 0 else "full",
            "sessions_total": len(sessions),
            "sessions_rescanned": rescanned,
            "sessions_reused": reused,
            "sessions_scanned_so_far": len(sessions),
            "sessions_expected_total": total_sessions,
        },
    }


def aggregate_stats(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    agg: Dict[str, Any] = {
        "session_count": len(sessions),
        "max_tool_calls_in_session": 0,
        "max_distinct_tools_in_session": 0,
        "max_messages_in_session": 0,
        "max_terminal_calls_in_session": 0,
        "max_file_tool_calls_in_session": 0,
        "max_web_calls_in_session": 0,
        "max_web_browser_calls_in_session": 0,
        "max_files_touched_in_session": 0,
        "total_errors": 0,
        "total_tool_calls": 0,
        "total_terminal_calls": 0,
        "total_web_calls": 0,
        "total_web_extract_calls": 0,
        "total_patch_calls": 0,
        "total_file_reads_searches": 0,
        "total_delegate_calls": 0,
        "total_process_calls": 0,
        "total_cron_calls": 0,
        "browser_calls": 0,
        "image_vision_calls": 0,
        "tts_calls": 0,
        "distinct_model_count": 0,
        "distinct_provider_count": 0,
        "local_model_chat_sessions": 0,
        "weekend_sessions": 0,
        "night_sessions": 0,
    }
    sum_keys = [
        "traceback_events", "log_read_events", "port_conflict_events", "permission_denied_events", "install_error_events", "install_success_events", "restart_after_error_events", "env_var_error_events", "yaml_error_events", "docker_conflict_events", "frontend_activity_events", "css_activity_events", "git_events", "tiny_patch_after_errors_events", "skill_events", "skill_manage_events", "memory_events", "memory_write_events", "context_events", "gateway_events", "plugin_events", "rollback_events", "docs_activity_events", "model_events", "openrouter_events", "codex_events", "claude_events", "gemini_events", "local_model_events", "toolset_events", "config_events", "git_history_events", "test_events", "screenshot_events", "release_events", "cache_events",
    ]
    for key in sum_keys:
        agg[key] = 0

    model_names: Set[str] = set()
    provider_names: Set[str] = set()
    for s in sessions:
        agg["max_tool_calls_in_session"] = max(agg["max_tool_calls_in_session"], s.get("tool_call_count", 0))
        agg["max_distinct_tools_in_session"] = max(agg["max_distinct_tools_in_session"], s.get("distinct_tool_count", 0))
        agg["max_messages_in_session"] = max(agg["max_messages_in_session"], s.get("message_count", 0))
        agg["max_terminal_calls_in_session"] = max(agg["max_terminal_calls_in_session"], s.get("terminal_calls", 0))
        agg["max_file_tool_calls_in_session"] = max(agg["max_file_tool_calls_in_session"], s.get("file_tool_calls", 0))
        agg["max_web_calls_in_session"] = max(agg["max_web_calls_in_session"], s.get("web_calls", 0))
        agg["max_web_browser_calls_in_session"] = max(agg["max_web_browser_calls_in_session"], s.get("web_browser_calls", 0))
        agg["max_files_touched_in_session"] = max(agg["max_files_touched_in_session"], s.get("files_touched_count", 0))
        agg["total_errors"] += s.get("error_count", 0)
        agg["total_tool_calls"] += s.get("tool_call_count", 0)
        agg["total_terminal_calls"] += s.get("terminal_calls", 0)
        agg["total_web_calls"] += s.get("web_calls", 0)
        agg["total_web_extract_calls"] += s.get("web_extract_calls", 0)
        agg["total_patch_calls"] += s.get("patch_calls", 0)
        agg["total_file_reads_searches"] += s.get("file_reads_searches", 0)
        agg["total_delegate_calls"] += s.get("delegate_calls", 0)
        agg["total_process_calls"] += s.get("process_calls", 0)
        agg["total_cron_calls"] += s.get("cron_calls", 0)
        agg["browser_calls"] += s.get("browser_calls", 0)
        agg["image_vision_calls"] += s.get("image_vision_calls", 0)
        agg["tts_calls"] += s.get("tts_calls", 0)
        for key in sum_keys:
            agg[key] += s.get(key, 0)
        model_names.update(s.get("model_names") or set())
        session_models = s.get("model_names") or set()
        for model_name in session_models:
            provider = model_provider(str(model_name))
            if provider:
                provider_names.add(provider)
        if any(is_local_model_name(str(model_name)) for model_name in session_models):
            agg["local_model_chat_sessions"] += 1
        if s.get("started_at"):
            try:
                lt = time.localtime(float(s.get("started_at")))
                if lt.tm_wday >= 5:
                    agg["weekend_sessions"] += 1
                if lt.tm_hour < 6 or lt.tm_hour >= 23:
                    agg["night_sessions"] += 1
            except Exception:
                pass
    agg["distinct_model_count"] = len({m for m in model_names if m and m != "None"})
    agg["distinct_provider_count"] = len(provider_names)
    return agg


def evaluate_definition(definition: Dict[str, Any], aggregate: Dict[str, Any]) -> Dict[str, Any]:
    if "threshold_metric" in definition:
        return evaluate_tiered(definition, aggregate)
    if "requirements" in definition:
        return evaluate_requirements(definition, aggregate)
    return evaluate_boolean(definition, aggregate)


def evidence_for(definition: Dict[str, Any], sessions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not sessions:
        return None
    metric = definition.get("threshold_metric")
    metric_to_session_key = {
        "max_tool_calls_in_session": "tool_call_count",
        "max_distinct_tools_in_session": "distinct_tool_count",
        "max_messages_in_session": "message_count",
        "max_terminal_calls_in_session": "terminal_calls",
        "max_file_tool_calls_in_session": "file_tool_calls",
        "max_web_calls_in_session": "web_calls",
        "max_web_browser_calls_in_session": "web_browser_calls",
        "max_files_touched_in_session": "files_touched_count",
    }
    if metric in metric_to_session_key:
        key = metric_to_session_key[metric]
        s = max(sessions, key=lambda x: x.get(key, 0))
        return {"session_id": s.get("session_id"), "title": s.get("title"), "value": s.get(key, 0)}
    return None


def _compute_from_scan(scan: Dict[str, Any], *, is_partial: bool = False) -> Dict[str, Any]:
    """Evaluate every achievement definition against a scan result.

    Used by ``compute_all`` for finished scans AND by the background
    progress callback for partial, in-flight snapshots. ``is_partial=True``
    skips persisting ``state.json`` unlocks — we don't want to record an
    "unlock time" based on half a scan that a later session might shift.
    """
    aggregate = scan.get("aggregate", {})
    state = load_state() if not is_partial else {"unlocks": {}}
    unlocks = state.setdefault("unlocks", {})
    now = int(time.time())
    evaluated = []
    for definition in ACHIEVEMENTS:
        result = evaluate_definition(definition, aggregate)
        unlock_id = definition["id"]
        if not is_partial and result["unlocked"] and unlock_id not in unlocks:
            unlocks[unlock_id] = {"unlocked_at": now, "first_tier": result.get("tier"), "evidence": evidence_for(definition, scan.get("sessions", []))}
        item = {**definition, **result}
        if result["unlocked"]:
            item["unlocked_at"] = unlocks.get(unlock_id, {}).get("unlocked_at")
            item["evidence"] = unlocks.get(unlock_id, {}).get("evidence") or evidence_for(definition, scan.get("sessions", []))
        evaluated.append(display_achievement(item))
    if not is_partial:
        save_state(state)
    unlocked = [a for a in evaluated if a["unlocked"]]
    discovered = [a for a in evaluated if a.get("state") == "discovered"]
    secret = [a for a in evaluated if a.get("state") == "secret"]
    return {
        "achievements": evaluated,
        "sessions": scan.get("sessions", []),
        "aggregate": aggregate,
        "scan_meta": scan.get("scan_meta", {}),
        "error": scan.get("error"),
        "unlocked_count": len(unlocked),
        "discovered_count": len(discovered),
        "secret_count": len(secret),
        "total_count": len(evaluated),
        "generated_at": now,
    }


def compute_all(progress_callback: Optional[Any] = None, progress_every: int = 250) -> Dict[str, Any]:
    scan = scan_sessions(progress_callback=progress_callback, progress_every=progress_every)
    return _compute_from_scan(scan, is_partial=False)


_BACKGROUND_SCAN_THREAD: Optional[threading.Thread] = None
_BACKGROUND_SCAN_LOCK = threading.Lock()


def _build_pending_snapshot(now: int) -> Dict[str, Any]:
    """Placeholder payload used while the first-ever scan is still running.

    Returns a structurally-complete response so the dashboard UI can render
    an empty achievement list + spinner without special-casing "no data yet".
    """
    evaluated = [display_achievement({**d, **{"unlocked": False, "discovered": False, "state": "secret" if d.get("secret") else "discovered", "progress": 0, "progress_pct": 0, "next_tier": (d.get("tiers") or [{}])[0].get("name"), "next_threshold": (d.get("tiers") or [{}])[0].get("threshold", 1), "tier": None}}) for d in ACHIEVEMENTS]
    return {
        "achievements": evaluated,
        "sessions": [],
        "aggregate": {},
        "scan_meta": {"mode": "pending", "sessions_total": 0, "sessions_rescanned": 0, "sessions_reused": 0},
        "error": None,
        "unlocked_count": 0,
        "discovered_count": sum(1 for a in evaluated if a.get("state") == "discovered"),
        "secret_count": sum(1 for a in evaluated if a.get("state") == "secret"),
        "total_count": len(evaluated),
        "generated_at": now,
    }


def _run_scan_and_update_cache(publish_partial_snapshots: bool = True) -> None:
    """Execute a scan + snapshot update. Called synchronously or from a thread.

    When ``publish_partial_snapshots=True`` (the default for background
    scans), the scanner periodically publishes an in-progress snapshot to
    ``_SNAPSHOT_CACHE`` so each dashboard refresh during a long cold scan
    shows more progress — badges unlock incrementally as sessions stream
    in, instead of staying at zero for minutes and then jumping to the
    final state. Synchronous /rescan callers pass ``False`` because they
    block on the full result anyway.
    """
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    with _SCAN_LOCK:
        started = int(time.time())
        _SCAN_STATUS["state"] = "running"
        _SCAN_STATUS["started_at"] = started
        _SCAN_STATUS["last_error"] = None

        def _publish_partial(partial_sessions, scanned_so_far, total):
            global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
            try:
                partial_scan = {
                    "sessions": partial_sessions,
                    "aggregate": aggregate_stats(partial_sessions),
                    "scan_meta": {
                        "mode": "in_progress",
                        "sessions_total": scanned_so_far,
                        "sessions_rescanned": 0,
                        "sessions_reused": 0,
                        "sessions_scanned_so_far": scanned_so_far,
                        "sessions_expected_total": total,
                    },
                }
                partial = _compute_from_scan(partial_scan, is_partial=True)
                # Keep the cache in the 'stale' TTL regime by NOT bumping
                # _SNAPSHOT_CACHE_AT to "now". The UI treats partial
                # results as stale so it keeps polling /scan-status and
                # sees the final snapshot when the scan finishes. In-flight
                # partials are visible but are never mistaken for finished.
                _SNAPSHOT_CACHE = _json_safe(partial)
                _SNAPSHOT_CACHE_AT = 0
            except Exception:
                # Intermediate publication is best-effort; don't kill the scan.
                pass

        callback = _publish_partial if publish_partial_snapshots else None
        try:
            computed = compute_all(progress_callback=callback)
            _SNAPSHOT_CACHE = _json_safe(computed)
            _SNAPSHOT_CACHE_AT = int(_SNAPSHOT_CACHE.get("generated_at") or int(time.time()))
            save_snapshot(_SNAPSHOT_CACHE)
            _SCAN_STATUS["state"] = "idle"
        except Exception as exc:
            _SCAN_STATUS["state"] = "failed"
            _SCAN_STATUS["last_error"] = str(exc)
        finally:
            _SCAN_STATUS["finished_at"] = int(time.time())
            _SCAN_STATUS["last_duration_ms"] = int((_SCAN_STATUS["finished_at"] - started) * 1000)
            _SCAN_STATUS["run_count"] = int(_SCAN_STATUS.get("run_count", 0)) + 1


def _start_background_scan() -> None:
    """Kick off a scan in a daemon thread if one isn't already running.

    Idempotent: concurrent callers see the in-flight thread and return
    immediately. The thread updates ``_SNAPSHOT_CACHE`` on completion so
    subsequent ``/achievements`` requests see fresh data. While running,
    it also publishes partial snapshots every ~250 sessions so the UI
    reflects incremental progress on long cold scans.
    """
    global _BACKGROUND_SCAN_THREAD
    with _BACKGROUND_SCAN_LOCK:
        existing = _BACKGROUND_SCAN_THREAD
        if existing is not None and existing.is_alive():
            return
        thread = threading.Thread(
            target=_run_scan_and_update_cache,
            kwargs={"publish_partial_snapshots": True},
            name="fabric-achievements-scan",
            daemon=True,
        )
        _BACKGROUND_SCAN_THREAD = thread
        thread.start()


def evaluate_all(force: bool = False) -> Dict[str, Any]:
    """Return the current achievements payload.

    Behavior matrix:

    * Fresh in-memory cache → return it instantly.
    * Stale on-disk snapshot → load it, kick a background rescan, return
      the stale data (UI decorates it with ``is_stale=True``).
    * No snapshot yet (first-ever run) → kick a background scan, return
      an empty-but-valid "pending" payload so the UI can render a spinner
      without blocking.
    * ``force=True`` (manual /rescan) → run synchronously, block the
      caller, replace the cache.

    Warm scans stay cheap (the checkpoint cache reuses per-session stats).
    Cold scans on 8000+ session databases take minutes; the background
    thread prevents that from ever blocking the dashboard request path.
    """
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    now = int(time.time())

    if not force and _cache_is_fresh(now):
        return _SNAPSHOT_CACHE or {}

    # Lazy-load persisted snapshot from disk so fresh process starts
    # don't have to wait for a scan to serve cached data.
    if _SNAPSHOT_CACHE is None:
        persisted = load_snapshot()
        if isinstance(persisted, dict):
            generated_at = int(persisted.get("generated_at") or 0)
            _SNAPSHOT_CACHE = persisted
            _SNAPSHOT_CACHE_AT = generated_at or now

    if force:
        # Manual /rescan — block the caller, synchronous scan path.
        # No partial publishing: the caller is waiting for the final result.
        _run_scan_and_update_cache(publish_partial_snapshots=False)
        if _SNAPSHOT_CACHE is not None:
            return _SNAPSHOT_CACHE
        # Scan failed with no prior cache — surface empty payload.
        return _build_pending_snapshot(now)

    # Non-force path: serve whatever we have and refresh in background.
    if _SNAPSHOT_CACHE is not None:
        if not _cache_is_fresh(now):
            _start_background_scan()
        return _SNAPSHOT_CACHE

    # First-ever run on this machine — no snapshot yet. Kick off a scan
    # and return a pending placeholder. The UI polls /scan-status and
    # re-fetches /achievements when the scan completes.
    _start_background_scan()
    return _build_pending_snapshot(now)


@router.get("/achievements")
async def achievements():
    data = evaluate_all()
    payload = {k: data[k] for k in ["achievements", "unlocked_count", "discovered_count", "secret_count", "total_count", "error", "generated_at"] if k in data}
    payload["is_stale"] = _is_snapshot_stale(data)
    payload["scan_meta"] = {
        **(data.get("scan_meta") or {}),
        "status": _scan_status_payload(),
    }
    return payload


@router.get("/scan-status")
async def scan_status():
    return _scan_status_payload()


@router.get("/recent-unlocks")
async def recent_unlocks():
    data = evaluate_all()
    return sorted([a for a in data["achievements"] if a["unlocked"]], key=lambda a: a.get("unlocked_at") or 0, reverse=True)[:20]


@router.get("/sessions/{session_id}/badges")
async def session_badges(session_id: str):
    data = evaluate_all()
    session = next((s for s in data["sessions"] if s["session_id"] == session_id), None)
    if not session:
        return {"session_id": session_id, "badges": []}
    aggregate = aggregate_stats([session])
    badges = []
    for definition in ACHIEVEMENTS:
        result = evaluate_definition(definition, aggregate)
        if result["unlocked"]:
            badges.append(display_achievement({**definition, **result}))
    return {"session_id": session_id, "badges": badges}


@router.post("/rescan")
async def rescan():
    return {"ok": True, **evaluate_all(force=True)}


@router.post("/reset-state")
async def reset_state():
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    save_state({"unlocks": {}})
    _SNAPSHOT_CACHE = None
    _SNAPSHOT_CACHE_AT = 0
    _SCAN_STATUS["state"] = "idle"
    _SCAN_STATUS["started_at"] = None
    _SCAN_STATUS["finished_at"] = None
    _SCAN_STATUS["last_error"] = None
    _SCAN_STATUS["last_duration_ms"] = None
    try:
        snapshot_path().unlink(missing_ok=True)
    except Exception:
        pass
    try:
        checkpoint_path().unlink(missing_ok=True)
    except Exception:
        pass
    return {"ok": True}


# =====================================================================
# Team leaderboard — opt-in, aggregate-only, cross-user sharing
# =====================================================================
#
# The achievements engine above is strictly local: it reads your session
# history and never phones home (see the plugin README). A leaderboard needs
# to compare people, which means *something* has to leave each machine. The
# design keeps that surface as small and as consent-driven as possible:
#
#   * Nothing is sent unless you explicitly create or join a team and leave
#     the "share my stats" toggle on. There is no background sync tied to the
#     scan.
#   * Only an AGGREGATE PROFILE leaves the machine — a score, unlock/tier
#     tallies, per-category counts, and up to five unlocked-badge names from
#     the static public catalogue, plus a display name you choose. Session
#     ids, titles, transcripts, file paths, and raw metrics never do (see
#     ``build_leaderboard_profile``).
#   * Members talk to a "relay" (see ../relay/) — a small self-hostable
#     service, not a Fabric cloud. You point at one via an invite link. The
#     browser never talks to the relay directly; these backend routes proxy,
#     so the relay only ever sees server-to-server calls.
#
# Trust note: joining a team means trusting whoever gave you the invite about
# which relay URL you contact — the request originates from your machine. Only
# join teams from people you trust, exactly as you would with any webhook URL.

INVITE_PREFIX = "fbl1_"  # fabric-leaderboard v1

# Points model. Each unlocked tier is worth progressively more; a
# multi-condition ("full send") unlock has no tier and is scored as a
# Gold-equivalent feat. Summing these across unlocked achievements yields a
# single comparable "Fabric Score" (gamerscore-style magnitudes).
TIER_POINTS = {"Copper": 10, "Silver": 25, "Gold": 60, "Diamond": 150, "Olympian": 400}
POINTS_PER_UNLOCK_NO_TIER = 60

TEAM_HTTP_TIMEOUT = 10

# Serializes the load-mutate-save sequence in the team_* helpers. They run in
# a threadpool (see _run), so concurrent dashboard requests could otherwise
# interleave a read-modify-write on team.json and lose a member_token. RLock
# is reentrant so helpers that call each other (e.g. team_kick -> team_leaderboard
# -> _publish_now) don't deadlock.
_TEAM_CONFIG_LOCK = threading.RLock()


def _synchronized(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _TEAM_CONFIG_LOCK:
            return fn(*args, **kwargs)
    return wrapper


class RelayClientError(Exception):
    """Raised when a relay call fails. ``status`` is the HTTP code (0 if the
    relay was unreachable)."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def team_config_path() -> Path:
    return get_fabric_home() / "plugins" / "fabric-achievements" / "team.json"


def _default_team_config() -> Dict[str, Any]:
    return {
        "membership": None,
        "publish_opt_in": False,
        "pending_unpublish": False,
        "pending_leaves": [],
        "pending_leave_error": None,
        "publish_error": None,
        "last_published_at": None,
        "last_error": None,
    }


def _pending_leave_record(membership: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Retain only the credentials required to retry a remote leave."""
    keys = ("relay_url", "team_id", "member_id", "member_token")
    if not all(isinstance(membership.get(key), str) and membership[key] for key in keys):
        return None
    return {key: membership[key] for key in keys}


def load_team_config() -> Dict[str, Any]:
    path = team_config_path()
    config = _default_team_config()
    if not path.exists():
        return config
    try:
        data = json.loads(path.read_text())
    except Exception:
        return config
    migrated = False
    if isinstance(data, dict):
        for key in config:
            if key in data:
                config[key] = data[key]
        # Older builds represented a failed opt-out as opt-in=false while
        # leaving last_published_at set. Preserve that cleanup obligation.
        if (
            "pending_unpublish" not in data
            and isinstance(config.get("membership"), dict)
            and not config.get("publish_opt_in")
            and config.get("last_published_at") is not None
        ):
            config["pending_unpublish"] = True
            migrated = True
        pending = config.get("pending_leaves")
        if isinstance(pending, list):
            minimal = []
            for item in pending:
                if isinstance(item, dict):
                    record = _pending_leave_record(item)
                    if record is not None:
                        minimal.append(record)
            if minimal != pending:
                config["pending_leaves"] = minimal
                migrated = True
    if migrated:
        save_team_config(config)
    return config


def save_team_config(config: Dict[str, Any]) -> None:
    path = team_config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    # Write-then-rename so an interrupted or concurrent write can never leave a
    # half-written team.json (which would orphan the member: member_token is
    # only stored here and is unrecoverable if lost).
    tmp: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp = Path(handle.name)
            os.chmod(tmp, 0o600)
            json.dump(config, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def _validate_relay_url(url: Any) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Relay URL is required.")
    cleaned = url.strip()
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Relay URL must be an http(s) URL, e.g. http://host:9137.")
    return cleaned.rstrip("/")


def encode_invite(relay_url: str, team_id: str, team_name: str, join_secret: str) -> str:
    payload = {"v": 1, "relay": relay_url, "team_id": team_id, "team_name": team_name, "secret": join_secret}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return INVITE_PREFIX + token


def decode_invite(code: Any) -> Dict[str, Any]:
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Invite code is required.")
    text = code.strip().strip('"').strip("'")
    if INVITE_PREFIX not in text:
        raise ValueError("That does not look like a Fabric leaderboard invite.")
    token = text[text.index(INVITE_PREFIX) + len(INVITE_PREFIX):].strip()
    # Tolerate anything appended after the token (a trailing URL fragment, a
    # stray word) by keeping only the first whitespace-delimited chunk.
    token = token.split()[0] if token.split() else ""
    if not token:
        raise ValueError("Invite code is empty.")
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(token + padding)
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Malformed invite code: {exc}")
    if not isinstance(payload, dict):
        raise ValueError("Invite code payload is invalid.")
    if not payload.get("team_id") or not payload.get("relay") or not payload.get("secret"):
        raise ValueError("Invite code is missing required fields.")
    return {
        "relay_url": _validate_relay_url(payload.get("relay")),
        "team_id": str(payload.get("team_id")),
        "team_name": str(payload.get("team_name") or "Team"),
        "join_secret": str(payload.get("secret")),
    }


def score_for_achievement(achievement: Dict[str, Any]) -> int:
    if not achievement.get("unlocked"):
        return 0
    tier = achievement.get("tier")
    if tier in TIER_POINTS:
        return TIER_POINTS[tier]
    return POINTS_PER_UNLOCK_NO_TIER


def _tier_rank(tier: Any) -> int:
    try:
        return TIER_NAMES.index(tier)
    except (ValueError, TypeError):
        return -1


def build_leaderboard_profile(achievements: List[Dict[str, Any]], display_name: str) -> Dict[str, Any]:
    """Derive the aggregate, privacy-safe profile that gets published.

    Deliberately excludes evidence, session ids/titles, ``unlocked_at``, and
    raw metric values — only counts, tallies, and static catalogue metadata
    for unlocked badges leave the machine.
    """
    unlocked = [a for a in achievements if a.get("unlocked")]
    score = sum(score_for_achievement(a) for a in achievements)
    tier_counts = {tier: 0 for tier in TIER_NAMES}
    category_counts: Dict[str, int] = {}
    for a in unlocked:
        tier = a.get("tier")
        if tier in tier_counts:
            tier_counts[tier] += 1
        category = a.get("category")
        if category:
            category_counts[category] = category_counts.get(category, 0) + 1
    highest = None
    for tier in reversed(TIER_NAMES):
        if tier_counts.get(tier):
            highest = tier
            break
    top_sorted = sorted(unlocked, key=lambda a: (-_tier_rank(a.get("tier")), str(a.get("name") or "")))
    top = [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "tier": a.get("tier"),
            "category": a.get("category"),
            "icon": a.get("icon"),
        }
        for a in top_sorted[:5]
    ]
    discovered = sum(1 for a in achievements if a.get("state") == "discovered")
    secret = sum(1 for a in achievements if a.get("state") == "secret")
    return {
        "display_name": display_name,
        "score": score,
        "unlocked_count": len(unlocked),
        "discovered_count": discovered,
        "secret_count": secret,
        "total_count": len(achievements),
        "tier_counts": tier_counts,
        "highest_tier": highest,
        "category_counts": category_counts,
        "top_achievements": top,
        "generated_at": int(time.time()),
    }


# Transport is injectable so tests can bind the client to an in-process relay
# store without a socket. Shape: (method, url, headers, body_bytes|None) ->
# (status_code, parsed_json_dict).
Transport = Callable[[str, str, Dict[str, str], Optional[bytes]], Tuple[int, Dict[str, Any]]]


def _default_transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes]) -> Tuple[int, Dict[str, Any]]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TEAM_HTTP_TIMEOUT) as response:
            status = response.getcode()
            raw = response.read()
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a JSON body
        status = exc.code
        try:
            raw = exc.read()
        except Exception:
            raw = b""
    except urllib.error.URLError as exc:
        raise RelayClientError(f"Could not reach the relay: {exc.reason}", status=0)
    except Exception as exc:  # noqa: BLE001
        raise RelayClientError(f"Relay request failed: {exc}", status=0)
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        data = {}
    return status, data if isinstance(data, dict) else {}


class RelayClient:
    def __init__(self, base_url: str, transport: Optional[Transport] = None) -> None:
        self.base_url = _validate_relay_url(base_url)
        self._transport = transport or _default_transport

    def _call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        url = self.base_url + path
        request_headers = {"Accept": "application/json"}
        data: Optional[bytes] = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        status, payload = self._transport(method, url, request_headers, data)
        if status < 200 or status >= 300:
            message = payload.get("error") if isinstance(payload, dict) else None
            raise RelayClientError(message or f"Relay returned HTTP {status}.", status=status)
        return payload if isinstance(payload, dict) else {}

    def _mutate(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        result = self._call("POST", path, body)
        if result.get("ok") is not True:
            raise RelayClientError(
                "Relay did not confirm the requested change. Is that URL a Fabric leaderboard relay?",
                status=502,
            )
        return result

    def create_team(self, name: str, display_name: str) -> Dict[str, Any]:
        return self._call("POST", "/api/teams", {"name": name, "display_name": display_name})

    def join_team(self, team_id: str, join_secret: str, display_name: str) -> Dict[str, Any]:
        return self._call("POST", f"/api/teams/{urllib.parse.quote(team_id)}/join",
                          {"join_secret": join_secret, "display_name": display_name})

    def publish(self, team_id: str, member_id: str, member_token: str, profile: Dict[str, Any], display_name: Optional[str] = None) -> Dict[str, Any]:
        body = {"member_id": member_id, "member_token": member_token, "profile": profile}
        if display_name is not None:
            body["display_name"] = display_name
        return self._mutate(f"/api/teams/{urllib.parse.quote(team_id)}/publish", body)

    def leave(self, team_id: str, member_id: str, member_token: str) -> Dict[str, Any]:
        return self._mutate(f"/api/teams/{urllib.parse.quote(team_id)}/leave",
                            {"member_id": member_id, "member_token": member_token})

    def rotate(self, team_id: str, member_id: str, member_token: str) -> Dict[str, Any]:
        return self._mutate(f"/api/teams/{urllib.parse.quote(team_id)}/rotate",
                            {"member_id": member_id, "member_token": member_token})

    def kick(self, team_id: str, member_id: str, member_token: str, target_member_id: str) -> Dict[str, Any]:
        return self._mutate(f"/api/teams/{urllib.parse.quote(team_id)}/kick",
                            {"member_id": member_id, "member_token": member_token, "target_member_id": target_member_id})

    def unpublish(self, team_id: str, member_id: str, member_token: str) -> Dict[str, Any]:
        return self._mutate(f"/api/teams/{urllib.parse.quote(team_id)}/unpublish",
                            {"member_id": member_id, "member_token": member_token})

    def leaderboard(self, team_id: str, join_secret: Optional[str] = None, member_id: Optional[str] = None, member_token: Optional[str] = None) -> Dict[str, Any]:
        headers: Dict[str, str] = {}
        if join_secret:
            headers["X-Join-Secret"] = join_secret
        if member_id and member_token:
            headers["X-Member-Id"] = member_id
            headers["X-Member-Token"] = member_token
        return self._call("GET", f"/api/teams/{urllib.parse.quote(team_id)}/leaderboard", None, headers)


def _require_fields(result: Dict[str, Any], keys: Tuple[str, ...]) -> None:
    """Guard against a 2xx response from a URL that isn't actually a relay.

    ``_validate_relay_url`` only checks scheme/netloc, so a typo'd homepage or
    an incompatible build can return HTTP 200 with a body that parses to ``{}``.
    Turn the resulting missing-key case into a RelayClientError so the routes'
    ``{ok: false}`` contract holds instead of a bare KeyError -> HTTP 500.
    """
    missing = [k for k in keys if not (isinstance(result, dict) and result.get(k))]
    if missing:
        raise RelayClientError(
            "Relay returned an unexpected response (missing: " + ", ".join(missing) + "). "
            "Is that URL a Fabric leaderboard relay?",
            status=502,
        )


# ---------------------------------------------------------------------------
# Hosting helpers (detect + start/stop the relay)
# ---------------------------------------------------------------------------
# Being the *host* of a leaderboard means running the relay (see relay/README.md)
# and giving teammates its URL. Two frictions: (1) the URL — on a laptop behind
# NAT, "http://<what?>:9137" is not something a user can guess, and 127.0.0.1
# only works on the one machine; and (2) actually starting the relay, previously
# a copy-paste terminal command. These helpers solve both:
#   * detect_tailscale()/host_status() read a running relay + this machine's
#     Tailscale identity and pre-fill a URL that actually works, and
#   * start_local_relay()/stop_local_relay() let the dashboard host the relay
#     with one click, tracked in a small state file so it survives a dashboard
#     restart.
# Tailscale reads reuse ``fabric_cli.tailscale_setup`` (the same code behind
# ``fabric setup tailscale``); only this node's own name/IPs are read — never
# peer or tailnet data. Connecting Tailscale (the interactive QR login) stays
# the CLI's job: the UI hands the user ``fabric setup tailscale`` rather than
# duplicating that ceremony without a terminal.

DEFAULT_RELAY_PORT = 9137
TAILSCALE_TIMEOUT = 5

# The command that runs Fabric's built-in Tailscale enrollment (QR login). The
# UI surfaces this verbatim; it needs an interactive terminal, so the dashboard
# can't run it headless — it reuses, not reimplements, that flow.
TAILSCALE_SETUP_COMMAND = "fabric setup tailscale"


def _tailscale_exe() -> Optional[str]:
    """Path to the ``tailscale`` CLI, or ``None`` if it isn't installed.

    Fallback binary discovery used only when ``fabric_cli.tailscale_setup`` is
    unavailable; otherwise ``find_tailscale_binary`` (which also handles WSL and
    the macOS app bundle) is reused.
    """
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for cand in (
        "/usr/bin/tailscale",
        "/usr/local/bin/tailscale",
        "/opt/homebrew/bin/tailscale",
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    ):
        if Path(cand).exists():
            return cand
    return None


def _run_tailscale(args: List[str], timeout: int = TAILSCALE_TIMEOUT) -> Tuple[int, str]:
    """Run ``tailscale <args>``; return ``(returncode, stdout)``. Fallback path.

    Returns ``(-1, "")`` if the CLI is absent or the call fails/ times out, so
    callers can treat "no Tailscale" and "Tailscale error" the same way.
    """
    exe = _tailscale_exe()
    if not exe:
        return -1, ""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - detection must never raise
        return -1, ""
    return proc.returncode, proc.stdout or ""


def _reused_tailscale_identity() -> Optional[Dict[str, Any]]:
    """Read Tailscale identity via ``fabric_cli.tailscale_setup`` (reuse).

    Returns a normalized dict (``installed``/``running``/``backend_state``/
    ``magicdns``/``ip``), or ``None`` when the reused module isn't importable so
    ``detect_tailscale`` knows to fall back to a direct probe. Never raises.
    """
    if _ts_find_binary is None or _ts_status is None:
        return None
    try:
        binary = _ts_find_binary()
    except Exception:  # noqa: BLE001
        binary = None
    if not binary:
        return {"installed": False, "running": False, "backend_state": None, "magicdns": None, "ip": None}
    try:
        status = _ts_status(binary)
    except Exception:  # noqa: BLE001
        status = None
    if status is None:
        return {"installed": True, "running": False, "backend_state": None, "magicdns": None, "ip": None}
    return {
        "installed": True,
        "running": bool(status.is_running),
        "backend_state": status.backend_state,
        "magicdns": status.dns_name,
        "ip": status.ip,
    }


def detect_tailscale() -> Dict[str, Any]:
    """Best-effort snapshot of this machine's own Tailscale identity.

    Never raises. Prefers Fabric's canonical ``fabric_cli.tailscale_setup``
    helpers; falls back to a direct ``tailscale status --json`` probe when that
    module isn't importable. A machine without Tailscale reports
    ``installed: False``; an installed-but-logged-out node reports
    ``running: False`` with no usable address. Only ``Self`` is read.
    """
    reused = _reused_tailscale_identity()
    if reused is not None:
        if not reused.get("installed"):
            return {
                "installed": False,
                "running": False,
                "magicdns": None,
                "ipv4": None,
                "ipv6": None,
                "ips": [],
            }
        raw_ip = reused.get("ip")
        try:
            parsed_ip = ipaddress.ip_address(str(raw_ip)) if raw_ip else None
        except ValueError:
            parsed_ip = None
        ipv4 = str(parsed_ip) if parsed_ip and parsed_ip.version == 4 else None
        ipv6 = str(parsed_ip) if parsed_ip and parsed_ip.version == 6 else None
        return {
            "installed": True,
            "running": bool(reused.get("running")),
            "backend_state": reused.get("backend_state"),
            "magicdns": reused.get("magicdns"),
            "ipv4": ipv4,
            "ipv6": ipv6,
            "ips": [str(parsed_ip)] if parsed_ip else [],
        }
    # Fallback: fabric_cli.tailscale_setup unavailable — probe the CLI directly.
    if _tailscale_exe() is None:
        return {
            "installed": False,
            "running": False,
            "magicdns": None,
            "ipv4": None,
            "ipv6": None,
            "ips": [],
        }
    code, out = _run_tailscale(["status", "--json"])
    if code != 0 or not out.strip():
        return {
            "installed": True,
            "running": False,
            "magicdns": None,
            "ipv4": None,
            "ipv6": None,
            "ips": [],
        }
    try:
        data = json.loads(out)
    except Exception:  # noqa: BLE001
        return {
            "installed": True,
            "running": False,
            "magicdns": None,
            "ipv4": None,
            "ipv6": None,
            "ips": [],
        }
    self_node = data.get("Self") if isinstance(data, dict) else None
    self_node = self_node if isinstance(self_node, dict) else {}
    ips = [ip for ip in (self_node.get("TailscaleIPs") or []) if isinstance(ip, str)]
    ipv4 = next((ip for ip in ips if ":" not in ip), None)
    ipv6 = next((ip for ip in ips if ":" in ip), None)
    magicdns = (self_node.get("DNSName") or "").rstrip(".") or None
    backend = data.get("BackendState") if isinstance(data, dict) else None
    # Case-insensitive to match the reused path's TailscaleStatus.is_running.
    running = isinstance(backend, str) and backend.casefold() == "running" and bool(ips)
    return {
        "installed": True,
        "running": running,
        "backend_state": backend,
        "magicdns": magicdns,
        "ipv4": ipv4,
        "ipv6": ipv6,
        "ips": ips,
    }


def _probe_relay_health(relay_url: Any, transport: Optional[Transport] = None) -> Dict[str, Any]:
    """GET ``<relay_url>/health`` and confirm the responder is a Fabric relay.

    Returns ``{"ok": True, "url", "schema_version", "teams", "members"}`` when a
    relay answers, else ``{"ok": False, "error": ...}``. Never raises — detection
    must degrade to "not found", not surface a 500. The ``/health`` payload is
    the store's own ``stats()`` output, so the ``schema_version`` key is what
    distinguishes a real relay from an unrelated server that happens to reply.
    """
    try:
        base = _validate_relay_url(relay_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    call = transport or _default_transport
    try:
        status, payload = call("GET", base + "/health", {"Accept": "application/json"}, None)
    except RelayClientError as exc:
        return {"ok": False, "error": exc.message}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not reach {base}: {exc}"}
    if status < 200 or status >= 300:
        return {"ok": False, "error": f"Relay returned HTTP {status}."}
    if not isinstance(payload, dict) or "schema_version" not in payload:
        return {"ok": False, "error": "That address answered, but it is not a Fabric leaderboard relay."}
    return {
        "ok": True,
        "url": base,
        "schema_version": payload.get("schema_version"),
        "teams": payload.get("teams"),
        "members": payload.get("members"),
    }


def _coerce_port(port: Any) -> int:
    try:
        port = int(port)
    except (TypeError, ValueError):
        return DEFAULT_RELAY_PORT
    if port < 1 or port > 65535:
        return DEFAULT_RELAY_PORT
    return port


def _relay_url(host: Any, port: Any) -> str:
    """Build an HTTP relay URL, bracketing IPv6 authorities correctly."""
    text = str(host or "").strip()
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        authority = text
    else:
        authority = f"[{parsed}]" if parsed.version == 6 else str(parsed)
    return f"http://{authority}:{_coerce_port(port)}"


def _relay_probe_url(host: Any, port: Any) -> str:
    """Return the reachable local health URL for a persisted bind address."""
    text = str(host or "").strip()
    if text in {"", "0.0.0.0"}:
        text = "127.0.0.1"
    elif text == "::":
        text = "::1"
    return _relay_url(text, port)


# --- Relay process management (host the relay from the dashboard) -----------
# There is no generic plugin process supervisor to reuse, so this mirrors the
# dashboard's own detached-spawn idiom (web_server._spawn_hermes_action and the
# WhatsApp pairing supervisor): a detached child, a small JSON state file next
# to team.json, and cross-platform detach + terminate reused from the shared
# helpers (fabric_cli._subprocess_compat, gateway.status, utils.atomic_json_write).
# It stays behind the dashboard auth gate like the rest of /team/*.

_RELAY_LOCK = threading.Lock()

# Module-level timing seams keep real process supervision bounded and let tests
# replace delays without sleeping.
RELAY_START_HEALTH_ATTEMPTS = 15
RELAY_START_HEALTH_DELAY = 0.3
RELAY_FINGERPRINT_ATTEMPTS = 20
RELAY_FINGERPRINT_DELAY = 0.025
RELAY_PROCESS_LOCK_TIMEOUT = 5.0
RELAY_PROCESS_LOCK_POLL_DELAY = 0.05
RELAY_STARTUP_OWNERSHIP_GRACE = 10.0
RELAY_STOP_TIMEOUT = 3.0
RELAY_FORCE_TIMEOUT = 2.0
RELAY_STOP_POLL_DELAY = 0.05

# Spawner is injectable. The production spawner returns ``(pid, start_time)``;
# tests may return a PID and use the fingerprint seam above.
Spawner = Callable[[List[str], Path, Path], Any]


def relay_state_path() -> Path:
    return get_fabric_home() / "plugins" / "fabric-achievements" / "relay.json"


def relay_lock_path() -> Path:
    return relay_state_path().with_suffix(".lock")


def relay_roster_path() -> Path:
    return get_fabric_home() / "plugins" / "fabric-achievements" / "roster.json"


def relay_log_path() -> Path:
    return get_fabric_home() / "logs" / "fabric-achievements-relay.log"


def _relay_plugin_dir() -> Path:
    # plugins/fabric-achievements — the directory ``python -m relay`` resolves
    # its package from (this file is dashboard/plugin_api.py -> parents[1]).
    return Path(__file__).resolve().parents[1]


def load_relay_state() -> Dict[str, Any]:
    path = relay_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def save_relay_state(state: Dict[str, Any]) -> None:
    path = relay_state_path()
    try:
        from utils import atomic_json_write  # reuse the shared atomic writer
        atomic_json_write(path, state)
        return
    except Exception:  # noqa: BLE001 - fall back to write-then-rename
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


def clear_relay_state() -> None:
    try:
        relay_state_path().unlink()
    except FileNotFoundError:
        return
    except Exception:  # noqa: BLE001
        save_relay_state({})


def _process_start_time(pid: int) -> Optional[int]:
    try:
        from gateway.status import get_process_start_time
        value = get_process_start_time(pid)
        return int(value) if value is not None else None
    except Exception:  # noqa: BLE001
        return None


def _pid_exists(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        import psutil
        try:
            if psutil.Process(value).status() == psutil.STATUS_ZOMBIE:
                return False
        except psutil.NoSuchProcess:
            return False
        except Exception:  # noqa: BLE001
            pass
        return bool(psutil.pid_exists(value))
    except ImportError:
        if os.name == "nt":
            # CPython maps os.kill(pid, 0) to CTRL_C_EVENT on Windows. Never
            # turn a liveness check into a signal when psutil is unavailable.
            return False
    try:
        os.kill(value, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _relay_process_identity(pid: Any, start_time: Any) -> str:
    """Return ``same``, ``gone``, ``other``, or ``unknown`` for a PID record."""
    if not _pid_exists(pid):
        return "gone"
    try:
        recorded = int(start_time)
    except (TypeError, ValueError):
        return "unknown"
    current = _process_start_time(int(pid))
    if current is None:
        return "unknown"
    return "same" if current == recorded else "other"


def _pid_is_alive(pid: Optional[int], start_time: Optional[int] = None) -> bool:
    """Return True only when PID liveness and its saved fingerprint both match."""
    return _relay_process_identity(pid, start_time) == "same"


def _relay_state_in_startup_grace(state: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Keep a freshly persisted spawn authoritative through process-table races."""
    if not state.get("pid") or state.get("start_time") is None:
        return False
    raw_started_at = state.get("started_at")
    if raw_started_at is None:
        return False
    try:
        started_at = float(raw_started_at)
    except (TypeError, ValueError):
        return False
    age = float(time.time() if now is None else now) - started_at
    return 0.0 <= age <= RELAY_STARTUP_OWNERSHIP_GRACE


def _relay_state_identity(state: Dict[str, Any]) -> str:
    identity = _relay_process_identity(state.get("pid"), state.get("start_time"))
    if identity == "gone" and _relay_state_in_startup_grace(state):
        return "starting"
    return identity


def _capture_process_start_time(pid: int) -> Optional[int]:
    for attempt in range(RELAY_FINGERPRINT_ATTEMPTS + 1):
        value = _process_start_time(pid)
        if value is not None:
            return value
        if not _pid_exists(pid):
            return None
        if attempt < RELAY_FINGERPRINT_ATTEMPTS:
            time.sleep(RELAY_FINGERPRINT_DELAY)
    return None


def _wait_original_process_gone(pid: int, start_time: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        identity = _relay_process_identity(pid, start_time)
        if identity in {"gone", "other"}:
            return True
        if identity == "unknown" or time.monotonic() >= deadline:
            return False
        time.sleep(RELAY_STOP_POLL_DELAY)


def _signal_relay_pid(pid: int, *, force: bool) -> bool:
    try:
        from gateway.status import terminate_pid
        terminate_pid(int(pid), force=force)
        return True
    except Exception:  # noqa: BLE001
        if os.name == "nt":
            return False
    try:
        import signal
        sig = getattr(signal, "SIGKILL", signal.SIGTERM) if force else signal.SIGTERM
        os.kill(int(pid), sig)
        return True
    except Exception:  # noqa: BLE001
        return False


def _terminate_relay_pid(pid: int, start_time: int) -> bool:
    """Terminate the exact recorded process and confirm it exited.

    Identity checks fail closed: an absent/unreadable fingerprint is never
    signalled. State remains on disk when exit cannot be confirmed so the
    dashboard does not forget a possibly-live relay.
    """
    if _relay_process_identity(pid, start_time) != "same":
        return False
    if not _signal_relay_pid(pid, force=False):
        return False
    if _wait_original_process_gone(pid, start_time, RELAY_STOP_TIMEOUT):
        return True
    if _relay_process_identity(pid, start_time) != "same":
        return False
    if not _signal_relay_pid(pid, force=True):
        return False
    return _wait_original_process_gone(pid, start_time, RELAY_FORCE_TIMEOUT)


def _acquire_relay_process_lock() -> Tuple[bool, Optional[Any]]:
    """Acquire an OS advisory lock for relay state mutations.

    ``gateway.status`` scoped locks intentionally reject live non-gateway
    owners, so they cannot serialize independent dashboard workers. This lock
    is kernel-owned and is released automatically if a process crashes.
    """
    path = relay_lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = open(path, "a+b")
    except OSError:
        return False, None

    try:
        if msvcrt is not None:
            lock_fh.seek(0, os.SEEK_END)
            if lock_fh.tell() == 0:
                lock_fh.write(b"\0")
                lock_fh.flush()
            lock_fh.seek(0)

        deadline = time.monotonic() + RELAY_PROCESS_LOCK_TIMEOUT
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:
                    getattr(msvcrt, "locking")(
                        lock_fh.fileno(), getattr(msvcrt, "LK_NBLCK"), 1
                    )
                return True, lock_fh
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    lock_fh.close()
                    return False, None
                time.sleep(RELAY_PROCESS_LOCK_POLL_DELAY)
    except Exception:  # noqa: BLE001
        lock_fh.close()
        return False, None


def _release_relay_process_lock(lock_fh: Optional[Any]) -> None:
    if lock_fh is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            lock_fh.seek(0)
            getattr(msvcrt, "locking")(
                lock_fh.fileno(), getattr(msvcrt, "LK_UNLCK"), 1
            )
    except (OSError, IOError):
        pass
    finally:
        lock_fh.close()


def _default_relay_spawner(argv: List[str], cwd: Path, log_path: Path) -> Tuple[int, int]:
    """Spawn detached and return a PID plus a verified start-time fingerprint."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    detach_kwargs: Dict[str, Any] = {}
    try:
        from fabric_cli._subprocess_compat import windows_detach_popen_kwargs
        detach_kwargs = windows_detach_popen_kwargs()
    except Exception:  # noqa: BLE001
        if os.name != "nt":
            detach_kwargs = {"start_new_session": True}
    popen_kwargs = {
        "cwd": str(cwd),
        "stdout": None,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
        **detach_kwargs,
    }
    log_fh = open(log_path, "ab")
    popen_kwargs["stdout"] = log_fh
    try:
        try:
            proc = subprocess.Popen(argv, **popen_kwargs)  # noqa: S603 - fixed argv, no shell
        except OSError:
            if "creationflags" not in detach_kwargs:
                raise
            # Windows job objects may deny CREATE_BREAKAWAY_FROM_JOB. Retry with
            # the canonical no-breakaway flags rather than failing hosting.
            from fabric_cli._subprocess_compat import windows_detach_flags_without_breakaway
            retry_kwargs = dict(popen_kwargs)
            retry_kwargs["creationflags"] = windows_detach_flags_without_breakaway()
            proc = subprocess.Popen(argv, **retry_kwargs)  # noqa: S603 - fixed argv, no shell
    finally:
        # The child inherited its own duplicate; the parent copy is done.
        log_fh.close()

    start_time = _capture_process_start_time(int(proc.pid))
    if start_time is None:
        # We still own the Popen handle, so cleanup is safe even without a PID
        # fingerprint. Never persist a killable record that cannot prove identity.
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
                proc.wait(timeout=1)
            except Exception:  # noqa: BLE001
                pass
        raise RuntimeError("Could not verify the relay process identity after spawn.")
    return int(proc.pid), int(start_time)


def relay_process_status(transport: Optional[Transport] = None) -> Dict[str, Any]:
    """Status of a *dashboard-managed* relay recorded in relay.json, if any.

    A record is managed only when both PID and start-time fingerprint match.
    Unknown ownership is surfaced separately and is never treated as killable.
    This read-only path does not delete state; start/stop own cleanup.
    """
    state = load_relay_state()
    pid = state.get("pid")
    port = state.get("port")
    host = state.get("host")
    log = state.get("log")
    if not pid:
        return {
            "managed": False,
            "running": False,
            "ownership_unknown": False,
            "pid": None,
            "port": None,
            "healthy": False,
            "log": log,
        }
    identity = _relay_state_identity(state)
    if identity not in {"same", "starting"}:
        return {
            "managed": False,
            "running": False,
            "ownership_unknown": identity == "unknown",
            "pid": int(pid) if identity == "unknown" else None,
            "port": _coerce_port(port) if identity == "unknown" and port else None,
            "healthy": False,
            "log": log,
        }
    healthy = bool(
        port and _probe_relay_health(_relay_probe_url(host, port), transport=transport).get("ok")
    )
    return {
        "managed": True,
        "running": True,
        "starting": identity == "starting",
        "ownership_unknown": False,
        "pid": int(pid),
        "port": _coerce_port(port) if port else None,
        "host": host,
        "started_at": state.get("started_at"),
        "healthy": healthy,
        "log": log,
    }


def _wait_relay_healthy(host: str, port: int, transport: Optional[Transport]) -> bool:
    health_url = _relay_probe_url(host, port)
    health = _probe_relay_health(health_url, transport=transport)
    attempts = 0
    while not health.get("ok") and attempts < RELAY_START_HEALTH_ATTEMPTS:
        time.sleep(RELAY_START_HEALTH_DELAY)
        health = _probe_relay_health(health_url, transport=transport)
        attempts += 1
    return bool(health.get("ok"))


def start_local_relay(
    port: int = DEFAULT_RELAY_PORT,
    host: Optional[str] = None,
    spawner: Optional[Spawner] = None,
    transport: Optional[Transport] = None,
) -> Dict[str, Any]:
    """Start one dashboard-managed relay without orphaning concurrent children.

    The default bind is the connected Tailscale IPv4 address, otherwise
    loopback. Mutation ownership is serialized across threads and dashboard
    processes; a live record is authoritative even before health starts
    answering. Every persisted PID has a verified start-time fingerprint.
    """
    port = _coerce_port(port)
    tailscale = detect_tailscale()
    default_host = tailscale.get("ipv4") if tailscale.get("running") else None
    host = str(host).strip() if host and str(host).strip() else str(default_host or "127.0.0.1")
    note: Optional[str] = None
    action_error: Optional[str] = None
    do_healthcheck = False

    with _RELAY_LOCK:
        acquired, process_lock = _acquire_relay_process_lock()
        if not acquired:
            note = "Another dashboard process is updating the relay; try again."
            action_error = note
        else:
            try:
                state = load_relay_state()
                managed_pid = state.get("pid")
                identity = _relay_state_identity(state) if managed_pid else "gone"
                if identity in {"same", "starting"}:
                    managed_port = _coerce_port(state.get("port"))
                    if managed_port != port:
                        note = (
                            f"The dashboard is already hosting a relay on port {managed_port}; "
                            "stop it before starting one on another port."
                        )
                        action_error = note
                    port = managed_port
                elif identity == "unknown":
                    note = "Relay ownership could not be verified; refusing to replace a possibly-live process."
                    action_error = note
                else:
                    probe_urls = [_relay_url("127.0.0.1", port)]
                    bind_probe = _relay_probe_url(host, port)
                    if bind_probe not in probe_urls:
                        probe_urls.append(bind_probe)
                    existing = next(
                        (
                            probe
                            for probe in (
                                _probe_relay_health(url, transport=transport)
                                for url in probe_urls
                            )
                            if probe.get("ok")
                        ),
                        None,
                    )
                    if existing:
                        note = "A relay is already running on this port (not started by the dashboard)."
                    else:
                        argv = [
                            sys.executable, "-m", "relay",
                            "--host", host, "--port", str(port),
                            "--state", str(relay_roster_path()),
                        ]
                        spawn = spawner or _default_relay_spawner
                        try:
                            spawned = spawn(argv, _relay_plugin_dir(), relay_log_path())
                            if isinstance(spawned, tuple):
                                if len(spawned) != 2:
                                    raise RuntimeError("Relay spawner returned an invalid process record.")
                                pid, start_time = int(spawned[0]), int(spawned[1])
                            else:
                                spawned_pid: Any = spawned
                                pid = int(spawned_pid)
                                captured = _capture_process_start_time(pid)
                                if captured is None:
                                    _signal_relay_pid(pid, force=True)
                                    raise RuntimeError("Could not verify the relay process identity after spawn.")
                                start_time = captured
                        except Exception as exc:  # noqa: BLE001
                            note = f"Could not start the relay: {exc}"
                            action_error = note
                        else:
                            try:
                                save_relay_state({
                                    "pid": pid,
                                    "port": port,
                                    "host": host,
                                    "started_at": int(time.time()),
                                    "start_time": start_time,
                                    "log": str(relay_log_path()),
                                })
                            except Exception as exc:  # noqa: BLE001
                                stopped = _terminate_relay_pid(pid, start_time)
                                suffix = "stopped it to avoid an orphan" if stopped else "manual cleanup may be required"
                                note = f"Started the relay but could not record it ({exc}); {suffix}."
                                action_error = note
                            else:
                                do_healthcheck = True
            finally:
                _release_relay_process_lock(process_lock)

    if do_healthcheck and not _wait_relay_healthy(host, port, transport):
        state = load_relay_state()
        raw_identity = _relay_process_identity(state.get("pid"), state.get("start_time"))
        owns_record = state.get("pid") == pid and state.get("start_time") == start_time
        if owns_record and raw_identity == "gone":
            clear_relay_state()
            note = "The relay process exited right after starting — see the relay log."
            action_error = note
        elif _relay_state_identity(state) in {"same", "starting"}:
            note = "Relay started but isn't answering yet — check the relay log if it doesn't come up."
        else:
            note = "The relay process could not be verified after starting — see the relay log."
            action_error = note
    return host_status(port, transport=transport, extra_note=note, action_error=action_error)


def stop_local_relay(transport: Optional[Transport] = None) -> Dict[str, Any]:
    """Stop only the exact dashboard-managed process and confirm its exit."""
    note: Optional[str] = None
    action_error: Optional[str] = None
    state: Dict[str, Any] = {}
    with _RELAY_LOCK:
        acquired, process_lock = _acquire_relay_process_lock()
        if not acquired:
            note = "Another dashboard process is updating the relay; try again."
            action_error = note
        else:
            try:
                state = load_relay_state()
                pid = state.get("pid")
                start_time = state.get("start_time")
                identity = _relay_state_identity(state) if pid else "gone"
                if identity == "same":
                    pid_value = int(pid or 0)
                    start_value = int(start_time or 0)
                    if _terminate_relay_pid(pid_value, start_value):
                        clear_relay_state()
                    else:
                        note = "Could not confirm the relay stopped — it may still be running; try again."
                        action_error = note
                elif identity == "starting":
                    note = "The relay is still starting; try Stop again in a moment."
                    action_error = note
                elif identity == "unknown":
                    note = "Relay ownership could not be verified, so it was not stopped."
                    action_error = note
                else:
                    if not pid:
                        note = "No dashboard-managed relay is running."
                    clear_relay_state()
            finally:
                _release_relay_process_lock(process_lock)
    port = _coerce_port(state.get("port") or DEFAULT_RELAY_PORT)
    return host_status(port, transport=transport, extra_note=note, action_error=action_error)


def host_status(
    port: int = DEFAULT_RELAY_PORT,
    transport: Optional[Transport] = None,
    extra_note: Optional[str] = None,
    action_error: Optional[str] = None,
) -> Dict[str, Any]:
    """Return local process health plus separately verified tailnet reachability."""
    port = _coerce_port(port)
    tailscale = detect_tailscale()
    managed = relay_process_status(transport=transport)
    if managed.get("running") and managed.get("port"):
        port = _coerce_port(managed["port"])
        local_url = _relay_probe_url(managed.get("host"), port)
    else:
        local_url = _relay_url("127.0.0.1", port)
    local_relay = _probe_relay_health(local_url, transport=transport)

    # Liveness keeps the UI in a truthful "starting" state, but only health can
    # establish reachability or make a suggested URL shareable.
    relay_live = bool(local_relay.get("ok")) or bool(managed.get("running"))
    shareable_host = (
        tailscale.get("magicdns") or tailscale.get("ipv4") or tailscale.get("ipv6")
    ) if tailscale.get("running") else None
    shareable_relay: Dict[str, Any] = {
        "ok": False,
        "error": "No connected Tailscale address is available.",
    }
    if shareable_host:
        suggested = _relay_url(shareable_host, port)
        # A manually hosted relay may bind only to its Tailscale address, so a
        # failed loopback probe must not suppress this independent check.
        shareable_relay = _probe_relay_health(suggested, transport=transport)
    elif relay_live:
        suggested = _relay_url("127.0.0.1", port)
    else:
        suggested = None
    shareable = bool(shareable_relay.get("ok"))
    relay_live = relay_live or shareable
    command_host = tailscale.get("ipv4") if tailscale.get("running") and tailscale.get("ipv4") else "127.0.0.1"

    result = {
        "ok": True,
        "default_port": port,
        "tailscale": tailscale,
        "local_relay": local_relay,
        "shareable_relay": shareable_relay,
        "managed_relay": managed,
        "relay_live": relay_live,
        "suggested_relay_url": suggested,
        "suggested_is_shareable": shareable,
        "tailscale_setup_command": TAILSCALE_SETUP_COMMAND,
        "tailscale_needs_setup": bool(tailscale.get("installed") and not tailscale.get("running")),
        "run_command": (
            "cd plugins/fabric-achievements && "
            f"python -m relay --host {command_host} --port {port} --state ./roster.json"
        ),
    }
    if extra_note:
        result["note"] = extra_note
    if action_error:
        result["action_ok"] = False
        result["error"] = action_error
    return result


def _current_achievements() -> List[Dict[str, Any]]:
    """The evaluated achievement list used to build a publish profile.

    Uses the same cached snapshot the dashboard shows, so a published profile
    matches what the user sees on the Achievements tab.
    """
    data = evaluate_all()
    if isinstance(data, dict):
        return data.get("achievements", []) or []
    return []


def _membership_summary(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    membership = config.get("membership")
    if not isinstance(membership, dict):
        return None
    summary = {
        "team_id": membership.get("team_id"),
        "team_name": membership.get("team_name"),
        "role": membership.get("role"),
        "display_name": membership.get("display_name"),
        "relay_url": membership.get("relay_url"),
        "member_id": membership.get("member_id"),
        "joined_at": membership.get("joined_at"),
    }
    # The invite code is safe to return to the plugin's own frontend (it runs
    # on the user's dashboard). Any member can re-share it.
    if membership.get("relay_url") and membership.get("team_id") and membership.get("join_secret"):
        try:
            summary["invite_code"] = encode_invite(
                membership["relay_url"], membership["team_id"],
                membership.get("team_name") or "Team", membership["join_secret"],
            )
        except Exception:
            summary["invite_code"] = None
    return summary


def _team_state_payload(config: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    pending_leaves = config.get("pending_leaves")
    payload = {
        "ok": True,
        "membership": _membership_summary(config),
        "publish_opt_in": bool(config.get("publish_opt_in")),
        "pending_unpublish": bool(config.get("pending_unpublish")),
        "pending_leave_count": len(pending_leaves) if isinstance(pending_leaves, list) else 0,
        "publish_error": config.get("publish_error"),
        "last_published_at": config.get("last_published_at"),
        "last_error": config.get("last_error"),
    }
    if extra:
        payload.update(extra)
    return payload


@_synchronized
def _publish_now(config: Dict[str, Any], transport: Optional[Transport] = None) -> Dict[str, Any]:
    membership = config.get("membership")
    if not isinstance(membership, dict):
        raise RelayClientError("You are not in a team.", status=0)
    profile = build_leaderboard_profile(_current_achievements(), membership.get("display_name") or "Member")
    client = RelayClient(membership["relay_url"], transport=transport)
    result = client.publish(
        membership["team_id"], membership["member_id"], membership["member_token"],
        profile, display_name=membership.get("display_name"),
    )
    config["last_published_at"] = int(time.time())
    config["pending_unpublish"] = False
    config["publish_error"] = None
    config["last_error"] = None
    save_team_config(config)
    return result


def _mark_unpublished(config: Dict[str, Any]) -> None:
    config["pending_unpublish"] = False
    config["publish_error"] = None
    config["last_published_at"] = None
    config["last_error"] = None
    save_team_config(config)


@_synchronized
def team_create(relay_url: str, team_name: str, display_name: str, publish_opt_in: bool = True, transport: Optional[Transport] = None) -> Dict[str, Any]:
    relay_url = _validate_relay_url(relay_url)
    display_name = (display_name or "").strip() or "Owner"
    config = load_team_config()
    if isinstance(config.get("membership"), dict):
        return _team_state_payload(config, {
            "ok": False,
            "error": "Leave your current leaderboard before creating another one.",
        })
    client = RelayClient(relay_url, transport=transport)
    result = client.create_team(team_name, display_name)
    _require_fields(result, ("team_id", "member_id", "member_token", "join_secret"))
    config["membership"] = {
        "team_id": result["team_id"],
        "team_name": result.get("team_name") or team_name or "Team",
        "relay_url": relay_url,
        "member_id": result["member_id"],
        "member_token": result["member_token"],
        "join_secret": result["join_secret"],
        "display_name": display_name,
        "role": result.get("role", "owner"),
        "joined_at": int(time.time()),
    }
    config["publish_opt_in"] = bool(publish_opt_in)
    config["pending_unpublish"] = False
    config["publish_error"] = None
    config["last_error"] = None
    save_team_config(config)
    publish_error: Optional[str] = None
    if config["publish_opt_in"]:
        try:
            _publish_now(config, transport=transport)
        except RelayClientError as exc:
            publish_error = exc.message
            config["publish_error"] = exc.message
            config["last_error"] = exc.message
            save_team_config(config)
    if publish_error:
        return _team_state_payload(config, {"ok": False, "error": publish_error})
    return _team_state_payload(config)


@_synchronized
def team_join(invite_code: str, display_name: str, publish_opt_in: bool = True, transport: Optional[Transport] = None) -> Dict[str, Any]:
    display_name = (display_name or "").strip() or "Member"
    config = load_team_config()
    if isinstance(config.get("membership"), dict):
        return _team_state_payload(config, {
            "ok": False,
            "error": "Leave your current leaderboard before joining another one.",
        })
    invite = decode_invite(invite_code)
    client = RelayClient(invite["relay_url"], transport=transport)
    result = client.join_team(invite["team_id"], invite["join_secret"], display_name)
    _require_fields(result, ("team_id", "member_id", "member_token"))
    config["membership"] = {
        "team_id": result["team_id"],
        "team_name": result.get("team_name") or invite["team_name"],
        "relay_url": invite["relay_url"],
        "member_id": result["member_id"],
        "member_token": result["member_token"],
        "join_secret": invite["join_secret"],
        "display_name": display_name,
        "role": result.get("role", "member"),
        "joined_at": int(time.time()),
    }
    config["publish_opt_in"] = bool(publish_opt_in)
    config["pending_unpublish"] = False
    config["publish_error"] = None
    config["last_error"] = None
    save_team_config(config)
    publish_error: Optional[str] = None
    if config["publish_opt_in"]:
        try:
            _publish_now(config, transport=transport)
        except RelayClientError as exc:
            publish_error = exc.message
            config["publish_error"] = exc.message
            config["last_error"] = exc.message
            save_team_config(config)
    if publish_error:
        return _team_state_payload(config, {"ok": False, "error": publish_error})
    return _team_state_payload(config)


def _retry_pending_leaves(config: Dict[str, Any], transport: Optional[Transport] = None) -> Optional[str]:
    """Retry remote removals retained after successful local leave actions."""
    pending = config.get("pending_leaves")
    if not isinstance(pending, list) or not pending:
        config["pending_leaves"] = []
        return None
    remaining = []
    errors = []
    for membership in pending:
        if not isinstance(membership, dict):
            continue
        try:
            client = RelayClient(membership["relay_url"], transport=transport)
            client.leave(membership["team_id"], membership["member_id"], membership["member_token"])
        except RelayClientError as exc:
            if exc.status == 404:
                continue
            remaining.append(membership)
            errors.append(exc.message)
        except Exception as exc:  # noqa: BLE001 - retain credentials for a later retry
            remaining.append(membership)
            errors.append(getattr(exc, "message", None) or str(exc))
    config["pending_leaves"] = remaining
    config["pending_leave_error"] = errors[0] if errors else None
    save_team_config(config)
    return errors[0] if errors else None


@_synchronized
def team_leave(transport: Optional[Transport] = None) -> Dict[str, Any]:
    config = load_team_config()
    previous_error = _retry_pending_leaves(config, transport=transport)
    membership = config.get("membership")
    leave_error: Optional[str] = None
    if isinstance(membership, dict):
        try:
            client = RelayClient(membership["relay_url"], transport=transport)
            client.leave(membership["team_id"], membership["member_id"], membership["member_token"])
        except RelayClientError as exc:
            if exc.status != 404:
                leave_error = exc.message
        except Exception as exc:  # noqa: BLE001 - local leave must still succeed
            leave_error = getattr(exc, "message", None) or str(exc)
        if leave_error:
            pending = config.get("pending_leaves")
            if not isinstance(pending, list):
                pending = []
            record = _pending_leave_record(membership)
            if record is not None:
                pending.append(record)
            config["pending_leaves"] = pending

    pending = config.get("pending_leaves") if isinstance(config.get("pending_leaves"), list) else []
    config = _default_team_config()
    config["pending_leaves"] = pending
    action_error = leave_error or previous_error
    if action_error:
        config["pending_leave_error"] = action_error
    save_team_config(config)
    if action_error:
        message = f"Left locally, but the remote row could not be removed: {action_error}. Fabric will retry."
        return _team_state_payload(config, {"ok": False, "error": message})
    return _team_state_payload(config)


@_synchronized
def team_settings(publish_opt_in: Optional[bool] = None, display_name: Optional[str] = None, transport: Optional[Transport] = None) -> Dict[str, Any]:
    config = load_team_config()
    membership = config.get("membership")
    was_opt_in = bool(config.get("publish_opt_in"))
    pending_unpublish = bool(config.get("pending_unpublish"))
    changed_name = False
    if display_name is not None:
        cleaned = display_name.strip()
        if cleaned and isinstance(membership, dict):
            membership["display_name"] = cleaned
            changed_name = True
    if publish_opt_in is not None:
        config["publish_opt_in"] = bool(publish_opt_in)
        if publish_opt_in:
            config["pending_unpublish"] = False
        else:
            config["publish_error"] = None
            if was_opt_in or pending_unpublish:
                # Persist the local opt-out before contacting the relay. If the
                # retraction fails, this marker drives truthful UI and retries.
                config["pending_unpublish"] = True
    save_team_config(config)
    now_opt_in = bool(config.get("publish_opt_in"))
    should_unpublish = publish_opt_in is False and bool(config.get("pending_unpublish"))
    action_error: Optional[str] = None

    if isinstance(membership, dict):
        if should_unpublish:
            try:
                client = RelayClient(membership["relay_url"], transport=transport)
                client.unpublish(membership["team_id"], membership["member_id"], membership["member_token"])
                _mark_unpublished(config)
            except RelayClientError as exc:
                if exc.status == 404:
                    _mark_unpublished(config)
                else:
                    action_error = exc.message
                    config["last_error"] = exc.message
                    save_team_config(config)
        elif now_opt_in and (changed_name or (publish_opt_in and not was_opt_in)):
            # Re-publish so a new name or newly-enabled sharing shows up now.
            try:
                _publish_now(config, transport=transport)
            except RelayClientError as exc:
                action_error = exc.message
                config["publish_error"] = exc.message
                config["last_error"] = exc.message
                save_team_config(config)
    if action_error:
        return _team_state_payload(config, {"ok": False, "error": action_error})
    return _team_state_payload(config)


@_synchronized
def team_publish(transport: Optional[Transport] = None) -> Dict[str, Any]:
    config = load_team_config()
    if not isinstance(config.get("membership"), dict):
        return _team_state_payload(config, {"ok": False, "error": "You are not in a team."})
    if not config.get("publish_opt_in") or config.get("pending_unpublish"):
        return _team_state_payload(config, {
            "ok": False,
            "error": "Sharing is disabled. Turn on sharing before publishing.",
        })
    try:
        _publish_now(config, transport=transport)
    except RelayClientError as exc:
        config["publish_error"] = exc.message
        config["last_error"] = exc.message
        save_team_config(config)
        return _team_state_payload(config, {"ok": False, "error": exc.message})
    return _team_state_payload(config)


@_synchronized
def team_leaderboard(
    transport: Optional[Transport] = None,
    refresh_profile: bool = True,
) -> Dict[str, Any]:
    config = load_team_config()
    pending_leave_error = _retry_pending_leaves(config, transport=transport)
    membership = config.get("membership")
    if not isinstance(membership, dict):
        extra = {"leaderboard": [], "member_count": 0}
        if pending_leave_error:
            extra.update({
                "ok": False,
                "error": f"A previous leaderboard row could not be removed: {pending_leave_error}. Fabric will retry.",
            })
        return _team_state_payload(config, extra)
    pending_error: Optional[str] = pending_leave_error
    if config.get("pending_unpublish"):
        try:
            client = RelayClient(membership["relay_url"], transport=transport)
            client.unpublish(membership["team_id"], membership["member_id"], membership["member_token"])
            _mark_unpublished(config)
        except RelayClientError as exc:
            if exc.status == 404:
                _mark_unpublished(config)
            else:
                pending_error = exc.message
                config["last_error"] = exc.message
                save_team_config(config)
    # On an initial load or explicit refresh, update our row before reading so
    # the board is current. Action follow-up reads pass ``refresh_profile=False``
    # because create/join/settings already applied their profile change.
    # A publish failure is non-fatal — we still show the roster.
    if refresh_profile and config.get("publish_opt_in"):
        try:
            _publish_now(config, transport=transport)
        except RelayClientError as exc:
            config["publish_error"] = exc.message
            config["last_error"] = exc.message
            save_team_config(config)
    try:
        client = RelayClient(membership["relay_url"], transport=transport)
        roster = client.leaderboard(
            membership["team_id"],
            join_secret=membership.get("join_secret"),
            member_id=membership.get("member_id"),
            member_token=membership.get("member_token"),
        )
    except RelayClientError as exc:
        config["last_error"] = exc.message
        save_team_config(config)
        return _team_state_payload(config, {"ok": False, "error": exc.message, "leaderboard": []})
    extra = {
        "team_name": roster.get("team_name"),
        "member_count": roster.get("member_count", 0),
        "my_member_id": membership.get("member_id"),
        "leaderboard": roster.get("leaderboard", []),
        "roster_generated_at": roster.get("generated_at"),
    }
    if pending_error:
        extra.update({"ok": False, "error": pending_error})
    return _team_state_payload(config, extra)


@_synchronized
def team_rotate(transport: Optional[Transport] = None) -> Dict[str, Any]:
    config = load_team_config()
    membership = config.get("membership")
    if not isinstance(membership, dict):
        return _team_state_payload(config, {"ok": False, "error": "You are not in a team."})
    try:
        client = RelayClient(membership["relay_url"], transport=transport)
        result = client.rotate(membership["team_id"], membership["member_id"], membership["member_token"])
    except RelayClientError as exc:
        return _team_state_payload(config, {"ok": False, "error": exc.message})
    new_secret = result.get("join_secret")
    if new_secret:
        membership["join_secret"] = new_secret
        config["last_error"] = None
        save_team_config(config)
    return _team_state_payload(config)


@_synchronized
def team_kick(target_member_id: str, transport: Optional[Transport] = None) -> Dict[str, Any]:
    config = load_team_config()
    membership = config.get("membership")
    if not isinstance(membership, dict):
        return _team_state_payload(config, {"ok": False, "error": "You are not in a team."})
    if not target_member_id:
        return _team_state_payload(config, {"ok": False, "error": "A member is required."})
    try:
        client = RelayClient(membership["relay_url"], transport=transport)
        client.kick(membership["team_id"], membership["member_id"], membership["member_token"], target_member_id)
    except RelayClientError as exc:
        return _team_state_payload(config, {"ok": False, "error": exc.message})
    # Re-read the board so the caller sees the roster without the kicked member.
    return team_leaderboard(transport=transport)


async def _json_body(request: Any) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a blocking helper off the event loop when FastAPI is available."""
    if run_in_threadpool is not None:
        return await run_in_threadpool(lambda: fn(*args, **kwargs))
    return fn(*args, **kwargs)


def _error_payload(exc: Exception) -> Dict[str, Any]:
    message = getattr(exc, "message", None) or str(exc)
    return {"ok": False, "error": message}


@router.get("/team")
async def get_team():
    return _team_state_payload(load_team_config())


@router.post("/team/create")
async def post_team_create(request: Request):
    body = await _json_body(request)
    try:
        return await _run(
            team_create,
            body.get("relay_url", ""),
            body.get("team_name", ""),
            body.get("display_name", ""),
            bool(body.get("publish_opt_in", True)),
        )
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/join")
async def post_team_join(request: Request):
    body = await _json_body(request)
    try:
        return await _run(
            team_join,
            body.get("invite_code", ""),
            body.get("display_name", ""),
            bool(body.get("publish_opt_in", True)),
        )
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/leave")
async def post_team_leave():
    try:
        return await _run(team_leave)
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/settings")
async def post_team_settings(request: Request):
    body = await _json_body(request)
    opt_in = body.get("publish_opt_in")
    name = body.get("display_name")
    try:
        return await _run(
            team_settings,
            None if opt_in is None else bool(opt_in),
            None if name is None else str(name),
        )
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/publish")
async def post_team_publish():
    try:
        return await _run(team_publish)
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.get("/team/leaderboard")
async def get_team_leaderboard(refresh: bool = True):
    try:
        return await _run(team_leaderboard, None, refresh)
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/rotate")
async def post_team_rotate():
    try:
        return await _run(team_rotate)
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/kick")
async def post_team_kick(request: Request):
    body = await _json_body(request)
    try:
        return await _run(team_kick, str(body.get("target_member_id", "")))
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.get("/team/host/status")
async def get_team_host_status(port: int = DEFAULT_RELAY_PORT):
    # Detection: probes a relay on this machine, reports any dashboard-managed
    # relay, and reads this node's own Tailscale identity so the frontend can
    # pre-fill a working relay URL. Runs the `tailscale` CLI and touches the
    # local network, so it stays behind the dashboard auth gate (not on the
    # public-paths allowlist), like the rest of /team/*.
    try:
        return await _run(host_status, port)
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/host/probe")
async def post_team_host_probe(request: Request):
    # Validate a candidate relay URL (typed or auto-filled) before Create/Join,
    # turning a bad address into a clear message instead of a mid-create failure.
    body = await _json_body(request)
    try:
        return await _run(_probe_relay_health, body.get("relay_url", ""))
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/host/start")
async def post_team_host_start(request: Request):
    # Start (host) a dashboard-managed relay on this machine. A deliberate,
    # user-initiated action that spawns a local listening server, so it stays
    # behind the dashboard auth gate like the rest of /team/*.
    body = await _json_body(request)
    # host is optional: when omitted, start_local_relay binds this node's
    # Tailscale IPv4 address when connected, otherwise loopback.
    host = body.get("host")
    try:
        return await _run(
            start_local_relay,
            body.get("port", DEFAULT_RELAY_PORT),
            str(host) if host else None,
        )
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)


@router.post("/team/host/stop")
async def post_team_host_stop():
    try:
        return await _run(stop_local_relay)
    except (RelayClientError, ValueError) as exc:
        return _error_payload(exc)
