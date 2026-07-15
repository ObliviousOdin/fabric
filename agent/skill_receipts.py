"""Privacy-safe local activation and outcome receipts for Fabric skills.

Receipts are operational metadata, never model context.  This module writes a
small, profile-scoped JSONL journal under ``skills/.governance`` and deliberately
rejects arbitrary fields so prompts, responses, tool arguments, file contents,
and error strings cannot accidentally become telemetry.

The journal is local only.  Nothing in this module sends data over the network,
registers a model tool, or mutates the system prompt/tool schema.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import stat
import threading
import time
import uuid
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric_constants import get_fabric_home


logger = logging.getLogger(__name__)

SCHEMA_ID = "fabric.skill-receipt/v1"
AGGREGATE_SCHEMA_ID = "fabric.skill-receipt-aggregate/v1"
JOURNAL_FILENAME = "skill-receipts.jsonl"

_DEFAULT_MAX_BYTES = 1024 * 1024
_DEFAULT_MAX_FILES = 4
_MIN_MAX_BYTES = 64 * 1024
_MAX_MAX_BYTES = 8 * 1024 * 1024
_MAX_MAX_FILES = 16
_MAX_RECORD_BYTES = 16 * 1024
_MAX_CONTEXT_VALUE_BYTES = 1024
_MAX_SKILL_FILE_BYTES = 64 * 1024 * 1024
_MAX_SKILL_TREE_BYTES = 256 * 1024 * 1024
_MAX_SKILL_TREE_FILES = 4096
_SKILL_IDENTITY_CACHE_SIZE = 256
_MAX_COUNTER = (1 << 63) - 1
_MAX_DURATION_MS = 7 * 24 * 60 * 60 * 1000
_MAX_CORRELATION_SCOPES = 256
_MAX_ACTIVATIONS_PER_TURN = 32
_CORRELATION_TTL_SECONDS = 4 * 60 * 60
_MAX_CORRELATION_ID_BYTES = 1024

_EVENT_ID_RE = re.compile(r"^(?:act|out)_[0-9a-f]{32}$")
_ARCHIVE_NAME_RE = re.compile(r"^skill-receipts\.([1-9][0-9]*)\.jsonl$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTEXT_REF_RE = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")

_ACTIVATION_TOP_LEVEL = frozenset({
    "schema",
    "event",
    "event_id",
    "timestamp",
    "profile",
    "session_ref",
    "task_ref",
    "turn_ref",
    "skill",
    "selection",
    "governance",
})
_OUTCOME_TOP_LEVEL = frozenset({
    "schema",
    "event",
    "event_id",
    "timestamp",
    "profile",
    "activation_ids",
    "status",
    "duration_ms",
    "counts",
    "outcome_key",
    "guardrails",
    "digests",
})
_SELECTION_SOURCES = frozenset({
    "explicit_slash",
    "stack",
    "bundle",
    "preload",
    "skill_view",
    "scheduled",
})
_SELECTION_REASONS = frozenset({
    "user_invoked",
    "stack_member",
    "bundle_member",
    "session_preload",
    "agent_selected",
    "declared_job",
})
_CONTRACT_STATUSES = frozenset({"verified", "legacy_unverified", "invalid"})
_GOVERNANCE_MODES = frozenset({"governed", "legacy", "invalid"})
_GOVERNANCE_LANES = frozenset({
    "standard",
    "elevated",
    "approval_required",
    "restricted",
    "unknown",
})
_OUTCOME_STATUSES = frozenset({"completed", "failed", "interrupted"})
_COUNT_KEYS = frozenset({
    "api_calls",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "approvals",
    "cost_microusd",
})
_AGENT_COUNTER_FIELDS = {
    "input_tokens": "session_input_tokens",
    "output_tokens": "session_output_tokens",
    "prompt_tokens": "session_prompt_tokens",
    "completion_tokens": "session_completion_tokens",
    "total_tokens": "session_total_tokens",
    "cache_read_tokens": "session_cache_read_tokens",
    "cache_write_tokens": "session_cache_write_tokens",
    "reasoning_tokens": "session_reasoning_tokens",
}
_PROCESS_LOCK = threading.RLock()
_SKILL_IDENTITY_CACHE_LOCK = threading.Lock()
_SKILL_IDENTITY_CACHE: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_CORRELATION_LOCK = threading.RLock()


@dataclass
class _ActivationCorrelations:
    """Bounded volatile activation IDs for one pending scope or active turn."""

    updated_at: float
    activation_ids: OrderedDict[str, None]


_PENDING_ACTIVATIONS: OrderedDict[tuple[str, str], _ActivationCorrelations] = (
    OrderedDict()
)
_TURN_ACTIVATIONS: OrderedDict[str, _ActivationCorrelations] = OrderedDict()


class ReceiptValidationError(ValueError):
    """A receipt contains data outside the closed privacy-safe schema."""


class ReceiptIOError(RuntimeError):
    """The local receipt journal cannot be accessed safely."""


@dataclass(frozen=True)
class ReceiptSettings:
    """Bounded local journal settings resolved from ``config.yaml``."""

    enabled: bool = True
    max_bytes: int = _DEFAULT_MAX_BYTES
    max_files: int = _DEFAULT_MAX_FILES


def load_receipt_settings(config: Mapping[str, Any] | None = None) -> ReceiptSettings:
    """Resolve receipt settings, clamping malformed values to safe defaults."""

    if config is None:
        try:
            from fabric_cli.config import load_config_readonly

            config = load_config_readonly()
        except Exception:
            config = {}
    skills = config.get("skills") if isinstance(config, Mapping) else None
    raw = skills.get("receipts") if isinstance(skills, Mapping) else None
    raw = raw if isinstance(raw, Mapping) else {}

    enabled = raw.get("enabled", True)
    if type(enabled) is not bool:
        enabled = True
    max_bytes = raw.get("max_bytes", _DEFAULT_MAX_BYTES)
    if type(max_bytes) is not int or not (
        _MIN_MAX_BYTES <= max_bytes <= _MAX_MAX_BYTES
    ):
        max_bytes = _DEFAULT_MAX_BYTES
    max_files = raw.get("max_files", _DEFAULT_MAX_FILES)
    if type(max_files) is not int or not (1 <= max_files <= _MAX_MAX_FILES):
        max_files = _DEFAULT_MAX_FILES
    return ReceiptSettings(enabled=enabled, max_bytes=max_bytes, max_files=max_files)


def validate_receipt(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a detached receipt with a closed v1 schema."""

    if not isinstance(record, Mapping):
        raise ReceiptValidationError("receipt must be a mapping")
    event = record.get("event")
    if event == "activation":
        _validate_activation(record)
    elif event == "outcome":
        _validate_outcome(record)
    else:
        raise ReceiptValidationError("event must be 'activation' or 'outcome'")
    try:
        encoded = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReceiptValidationError(f"receipt is not canonical JSON: {exc}") from exc
    if len(encoded) + 1 > _MAX_RECORD_BYTES:
        raise ReceiptValidationError(f"receipt exceeds {_MAX_RECORD_BYTES} bytes")
    return json.loads(encoded)


def append_receipt(
    record: Mapping[str, Any],
    *,
    home: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> bool:
    """Append one validated receipt; return ``False`` when locally disabled."""

    validated = validate_receipt(record)
    settings = load_receipt_settings(config)
    if not settings.enabled:
        return False
    line = (
        json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    if len(line) > settings.max_bytes:
        raise ReceiptValidationError("one receipt exceeds configured journal max_bytes")

    governance = _ensure_governance_dir(
        Path(home) if home is not None else get_fabric_home()
    )
    with _journal_lock(governance):
        _prune_archives_locked(governance, settings)
        current = governance / JOURNAL_FILENAME
        current_size = _safe_file_size(current)
        if current_size and current_size + len(line) > settings.max_bytes:
            _rotate_locked(
                governance,
                settings.max_files,
                archive_current=current_size <= settings.max_bytes,
            )
        _append_line_locked(current, line)
    return True


def record_activation(
    *,
    skill_dir: Path,
    source: str,
    reason: str,
    canonical_name: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    turn_id: str | None = None,
    home: Path | None = None,
    config: Mapping[str, Any] | None = None,
    timestamp: datetime | None = None,
    event_id: str | None = None,
) -> str | None:
    """Record one strict activation and return its id, or ``None`` if disabled.

    Context identifiers are never stored verbatim.  They are HMAC-bound to a
    random, profile-local key and persisted as pseudonymous references.
    """

    settings = load_receipt_settings(config)
    if not settings.enabled:
        return None
    if source not in _SELECTION_SOURCES:
        raise ReceiptValidationError("selection source is invalid")
    if reason not in _SELECTION_REASONS:
        raise ReceiptValidationError("selection reason is invalid")
    profile_home = Path(home) if home is not None else get_fabric_home()
    governance = _ensure_governance_dir(profile_home)
    context_key = _load_or_create_context_key(governance)
    identity = _inspect_skill(Path(skill_dir), canonical_name)
    record: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "event": "activation",
        "event_id": event_id or f"act_{uuid.uuid4().hex}",
        "timestamp": _format_timestamp(timestamp),
        "profile": _profile_name(profile_home),
        "skill": identity["skill"],
        "selection": {"source": source, "reason": reason},
        "governance": identity["governance"],
    }
    for field, value in (
        ("session_ref", session_id),
        ("task_ref", task_id),
        ("turn_ref", turn_id),
    ):
        if value:
            record[field] = _context_ref(context_key, value)
    if not append_receipt(record, home=profile_home, config=config):
        return None
    activation_id = str(record["event_id"])
    _correlate_activation(
        activation_id,
        source=source,
        session_id=session_id,
        task_id=task_id,
        turn_id=turn_id,
    )
    return activation_id


def record_activation_best_effort(**kwargs: Any) -> str | None:
    """Runtime integration wrapper: receipt failure never blocks skill use."""

    try:
        return record_activation(**kwargs)
    except Exception:
        logger.debug("Could not record skill activation", exc_info=True)
        return None


def bind_pending_activation_receipts(
    *,
    turn_id: str,
    task_id: str | None = None,
    session_id: str | None = None,
) -> int:
    """Bind exact pre-turn activation IDs to one concrete turn.

    Slash, stack, bundle, and scheduled skill expansion can occur before the
    turn prologue allocates a turn ID. Their already-written activation IDs are
    staged only in this bounded process-local registry, then consumed here.
    Session preloads intentionally stay session-scoped: one preload activation
    must not be falsely finalized as the outcome of an arbitrary first turn.
    """

    normalized_turn = _bounded_correlation_id(turn_id)
    if normalized_turn is None:
        return 0
    now = time.monotonic()
    with _CORRELATION_LOCK:
        _cleanup_correlations_locked(now)
        collected: OrderedDict[str, None] = OrderedDict()
        for key in _pending_scope_keys(task_id=task_id, session_id=session_id):
            pending = _PENDING_ACTIVATIONS.pop(key, None)
            if pending is None:
                continue
            for activation_id in pending.activation_ids:
                collected.setdefault(activation_id, None)
        if not collected:
            return 0
        turn = _TURN_ACTIVATIONS.get(normalized_turn)
        if turn is None:
            turn = _ActivationCorrelations(now, OrderedDict())
            _TURN_ACTIVATIONS[normalized_turn] = turn
        for activation_id in collected:
            if len(turn.activation_ids) >= _MAX_ACTIVATIONS_PER_TURN:
                break
            turn.activation_ids.setdefault(activation_id, None)
        turn.updated_at = now
        _TURN_ACTIVATIONS.move_to_end(normalized_turn)
        _bound_correlations_locked(_TURN_ACTIVATIONS)
        return len(turn.activation_ids)


def record_turn_outcome_best_effort(
    *,
    turn_id: str,
    status: str,
    duration_ms: int,
    counts: Mapping[str, int] | None = None,
    home: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """Close every activation bound to one turn with structured metrics.

    This deliberately records only runtime completion and efficiency. It does
    not infer a skill's declared business outcome or guardrail truth from model
    prose; callers that possess those facts continue to use :func:`record_outcome`
    explicitly with ``outcome_key`` and structured guardrail results.
    """

    activation_ids = _take_turn_activation_ids(turn_id)
    if not activation_ids:
        return None
    try:
        return record_outcome(
            activation_ids=activation_ids,
            status=status,
            duration_ms=duration_ms,
            counts=counts,
            home=home,
            config=config,
        )
    except Exception:
        # No exception detail is logged. Although the API has a closed schema,
        # this keeps future validation changes from surfacing context values.
        logger.debug("Could not record skill turn outcome")
        return None


def finalize_agent_turn_receipts_best_effort(
    *,
    agent: Any,
    result: Mapping[str, Any] | None,
    baseline: Mapping[str, Any],
    turn_id: str | None = None,
    raised: bool = False,
) -> str | None:
    """Finalize correlated activations from an ``AIAgent`` turn result.

    ``baseline`` is a volatile counter snapshot captured by the narrow
    ``AIAgent.run_conversation`` forwarder. Only non-negative numeric deltas
    and a structural tool-call count are retained. Message content is never
    copied into a receipt, and no business outcome is inferred from it.
    """

    try:
        previous_turn = baseline.get("previous_turn_id")
        turn_id = turn_id or getattr(agent, "_current_turn_id", None)
        if not isinstance(turn_id, str) or not turn_id or turn_id == previous_turn:
            return None
        activation_ids = _take_turn_activation_ids(turn_id)
        if not activation_ids:
            return None

        status = "failed"
        if not raised and isinstance(result, Mapping):
            if result.get("interrupted") is True:
                status = "interrupted"
            elif result.get("completed") is True and result.get("failed") is not True:
                status = "completed"

        started_at = baseline.get("started_at")
        if not isinstance(started_at, (int, float)) or isinstance(started_at, bool):
            duration_ms = 0
        else:
            duration_ms = max(0, int((time.monotonic() - started_at) * 1000))
        duration_ms = min(duration_ms, _MAX_DURATION_MS)

        counts: dict[str, int] = {}
        if isinstance(result, Mapping):
            api_calls = result.get("api_calls")
            if type(api_calls) is int and 0 <= api_calls <= _MAX_COUNTER:
                counts["api_calls"] = api_calls
            tool_calls = _count_last_turn_tool_calls(result.get("messages"))
            if tool_calls:
                counts["tool_calls"] = tool_calls

        for receipt_key, attribute in _AGENT_COUNTER_FIELDS.items():
            before = baseline.get(attribute)
            after = getattr(agent, attribute, None)
            delta = _non_negative_counter_delta(before, after)
            if delta is not None:
                counts[receipt_key] = delta

        before_cost = baseline.get("session_estimated_cost_usd")
        after_cost = getattr(agent, "session_estimated_cost_usd", None)
        cost_delta = _non_negative_float_delta(before_cost, after_cost)
        if cost_delta is not None:
            counts["cost_microusd"] = min(
                _MAX_COUNTER, max(0, round(cost_delta * 1_000_000))
            )

        return record_outcome(
            activation_ids=activation_ids,
            status=status,
            duration_ms=duration_ms,
            counts=counts,
        )
    except Exception:
        logger.debug("Could not finalize skill turn receipts")
        return None


def record_outcome(
    *,
    activation_ids: Iterable[str],
    status: str,
    duration_ms: int,
    counts: Mapping[str, int] | None = None,
    outcome_key: str | None = None,
    guardrails: Iterable[Mapping[str, Any]] = (),
    active_digest: str | None = None,
    prior_digest: str | None = None,
    rollback_digest: str | None = None,
    home: Path | None = None,
    config: Mapping[str, Any] | None = None,
    timestamp: datetime | None = None,
    event_id: str | None = None,
) -> str | None:
    """Append a strict terminal outcome correlated to one or more activations.

    Callers must supply structured values only.  Error messages, model text,
    prompts, responses, tool arguments, and arbitrary metadata have no field in
    this API and are rejected by :func:`validate_receipt`.
    """

    settings = load_receipt_settings(config)
    if not settings.enabled:
        return None
    profile_home = Path(home) if home is not None else get_fabric_home()
    record = {
        "schema": SCHEMA_ID,
        "event": "outcome",
        "event_id": event_id or f"out_{uuid.uuid4().hex}",
        "timestamp": _format_timestamp(timestamp),
        "profile": _profile_name(profile_home),
        "activation_ids": list(activation_ids),
        "status": status,
        "duration_ms": duration_ms,
        "counts": dict(counts or {}),
        "outcome_key": outcome_key,
        "guardrails": [dict(item) for item in guardrails],
        "digests": {
            "active": active_digest,
            "prior": prior_digest,
            "rollback": rollback_digest,
        },
    }
    if not append_receipt(record, home=profile_home, config=config):
        return None
    return str(record["event_id"])


def read_receipts(
    *,
    home: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read valid local receipts oldest-first, skipping corrupt lines."""

    settings = load_receipt_settings(config)
    if not settings.enabled:
        return []
    profile_home = Path(home) if home is not None else get_fabric_home()
    governance = _governance_path(profile_home)
    if not governance.exists():
        return []
    _assert_safe_directory(governance, "governance directory")
    paths = [
        governance / f"skill-receipts.{index}.jsonl"
        for index in range(settings.max_files - 1, 0, -1)
    ] + [governance / JOURNAL_FILENAME]
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists() and not path.is_symlink():
            continue
        try:
            raw = _read_regular_file(path, _MAX_MAX_BYTES + _MAX_RECORD_BYTES)
        except ReceiptIOError:
            logger.debug("Skipping unsafe skill receipt file %s", path, exc_info=True)
            continue
        for line in raw.splitlines():
            if not line or len(line) > _MAX_RECORD_BYTES:
                continue
            try:
                parsed = json.loads(line)
                records.append(validate_receipt(parsed))
            except (json.JSONDecodeError, ReceiptValidationError, UnicodeError):
                continue
    return records


def aggregate_receipts(
    records: Iterable[Mapping[str, Any]] | None = None,
    *,
    home: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic privacy-safe metrics by canonical skill/version.

    Completion coverage is ``completed activations / activations``; completion
    and failure rates use finalized activations as their denominator. Routing
    precision is emitted only when an outcome carries the explicit boolean
    guardrail label ``routing_relevant``. Multi-skill outcomes are fully
    attributed to each correlated activation, so per-skill budget totals are
    attribution metrics rather than a billing ledger.
    """

    source = read_receipts(home=home, config=config) if records is None else records
    candidates: list[dict[str, Any]] = []
    for raw in source:
        try:
            item = validate_receipt(raw)
        except ReceiptValidationError:
            continue
        candidates.append(item)
    candidates.sort(
        key=lambda item: (
            item["timestamp"],
            item["event_id"],
            json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    )
    valid: list[dict[str, Any]] = []
    seen_events: set[str] = set()
    for item in candidates:
        if item["event_id"] in seen_events:
            continue
        seen_events.add(item["event_id"])
        valid.append(item)

    activations = {
        item["event_id"]: item for item in valid if item["event"] == "activation"
    }
    terminal: dict[str, dict[str, Any]] = {}
    outcome_events = 0
    for item in valid:
        if item["event"] != "outcome":
            continue
        outcome_events += 1
        for activation_id in item["activation_ids"]:
            if (
                activation_id in activations
                and activations[activation_id]["profile"] == item["profile"]
                and activation_id not in terminal
            ):
                terminal[activation_id] = item

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for activation_id, activation in activations.items():
        skill = activation["skill"]
        key = (skill["name"], skill["version"])
        bucket = buckets.setdefault(key, _empty_bucket(*key))
        bucket["activations"] += 1
        outcome = terminal.get(activation_id)
        if outcome is None:
            continue
        bucket["finalized"] += 1
        bucket[outcome["status"]] += 1
        bucket["durations"].append(outcome["duration_ms"])
        for count_key, value in outcome["counts"].items():
            bucket["counts"][count_key] += value
        if outcome.get("outcome_key"):
            bucket["outcomes"][outcome["outcome_key"]] += 1
        for guardrail in outcome["guardrails"]:
            key_name = guardrail["key"]
            bucket["guardrails"][key_name]["checked"] += 1
            if guardrail["passed"]:
                bucket["guardrails"][key_name]["passed"] += 1
        if outcome["digests"]["rollback"] is not None:
            bucket["rollback_count"] += 1

    skills = [_finalize_bucket(buckets[key]) for key in sorted(buckets)]
    totals = {
        "activations": len(activations),
        "finalized_activations": len(terminal),
        "completed": sum(
            1 for item in terminal.values() if item["status"] == "completed"
        ),
        "failed": sum(1 for item in terminal.values() if item["status"] == "failed"),
        "interrupted": sum(
            1 for item in terminal.values() if item["status"] == "interrupted"
        ),
        "outcome_events": outcome_events,
        "rollback_count": sum(
            1 for item in terminal.values() if item["digests"]["rollback"] is not None
        ),
    }
    totals["completion_coverage"] = _rate(totals["completed"], totals["activations"])
    totals["completion_rate"] = _rate(
        totals["completed"], totals["finalized_activations"]
    )
    totals["failure_rate"] = _rate(totals["failed"], totals["finalized_activations"])
    relevance_labels = [
        guardrail["passed"]
        for item in terminal.values()
        for guardrail in item["guardrails"]
        if guardrail["key"] == "routing_relevant"
    ]
    totals["routing_precision"] = (
        _rate(sum(relevance_labels), len(relevance_labels))
        if relevance_labels
        else None
    )
    return {
        "schema": AGGREGATE_SCHEMA_ID,
        "attribution": "full_per_correlated_activation",
        "totals": totals,
        "skills": skills,
    }


def _validate_activation(record: Mapping[str, Any]) -> None:
    _validate_common(record, _ACTIVATION_TOP_LEVEL, "activation")
    for optional in ("session_ref", "task_ref", "turn_ref"):
        value = record.get(optional)
        if value is not None and (
            not isinstance(value, str) or not _CONTEXT_REF_RE.fullmatch(value)
        ):
            raise ReceiptValidationError(
                f"{optional} must be a pseudonymous context reference"
            )
    skill = _mapping_with_keys(
        record.get("skill"),
        {"name", "version", "tree_sha256", "contract_sha256", "contract_status"},
        "skill",
    )
    _safe_string(skill.get("name"), _SAFE_NAME_RE, "skill.name")
    _safe_string(skill.get("version"), _SAFE_VERSION_RE, "skill.version")
    _digest(skill.get("tree_sha256"), "skill.tree_sha256", optional=False)
    _digest(skill.get("contract_sha256"), "skill.contract_sha256", optional=True)
    if skill.get("contract_status") not in _CONTRACT_STATUSES:
        raise ReceiptValidationError("skill.contract_status is invalid")
    selection = _mapping_with_keys(
        record.get("selection"), {"source", "reason"}, "selection"
    )
    if selection.get("source") not in _SELECTION_SOURCES:
        raise ReceiptValidationError("selection.source is invalid")
    if selection.get("reason") not in _SELECTION_REASONS:
        raise ReceiptValidationError("selection.reason is invalid")
    governance = _mapping_with_keys(
        record.get("governance"), {"mode", "lane"}, "governance"
    )
    if governance.get("mode") not in _GOVERNANCE_MODES:
        raise ReceiptValidationError("governance.mode is invalid")
    if governance.get("lane") not in _GOVERNANCE_LANES:
        raise ReceiptValidationError("governance.lane is invalid")


def _validate_outcome(record: Mapping[str, Any]) -> None:
    _validate_common(record, _OUTCOME_TOP_LEVEL, "outcome")
    activation_ids = record.get("activation_ids")
    if not isinstance(activation_ids, list) or not (1 <= len(activation_ids) <= 32):
        raise ReceiptValidationError("activation_ids must contain 1..32 ids")
    if len(set(activation_ids)) != len(activation_ids):
        raise ReceiptValidationError("activation_ids must be unique")
    for activation_id in activation_ids:
        if (
            not isinstance(activation_id, str)
            or not activation_id.startswith("act_")
            or not _EVENT_ID_RE.fullmatch(activation_id)
        ):
            raise ReceiptValidationError(
                "activation_ids contains an invalid activation id"
            )
    if record.get("status") not in _OUTCOME_STATUSES:
        raise ReceiptValidationError("status must be completed, failed, or interrupted")
    _counter(record.get("duration_ms"), "duration_ms")
    if record["duration_ms"] > _MAX_DURATION_MS:
        raise ReceiptValidationError("duration_ms exceeds the seven-day bound")
    counts = record.get("counts")
    if not isinstance(counts, Mapping):
        raise ReceiptValidationError("counts must be a mapping")
    unknown_counts = set(counts) - _COUNT_KEYS
    if unknown_counts:
        raise ReceiptValidationError(
            f"unknown counts fields: {', '.join(sorted(unknown_counts))}"
        )
    for key, value in counts.items():
        _counter(value, f"counts.{key}")
    outcome_key = record.get("outcome_key")
    if outcome_key is not None:
        _safe_string(outcome_key, _SAFE_KEY_RE, "outcome_key")
    guardrails = record.get("guardrails")
    if not isinstance(guardrails, list) or len(guardrails) > 32:
        raise ReceiptValidationError(
            "guardrails must be a list with at most 32 results"
        )
    seen_guardrails: set[str] = set()
    for index, item in enumerate(guardrails):
        guardrail = _mapping_with_keys(item, {"key", "passed"}, f"guardrails[{index}]")
        key = _safe_string(
            guardrail.get("key"), _SAFE_KEY_RE, f"guardrails[{index}].key"
        )
        if key in seen_guardrails:
            raise ReceiptValidationError("guardrail keys must be unique")
        seen_guardrails.add(key)
        if type(guardrail.get("passed")) is not bool:
            raise ReceiptValidationError(f"guardrails[{index}].passed must be boolean")
    digests = _mapping_with_keys(
        record.get("digests"), {"active", "prior", "rollback"}, "digests"
    )
    for key in ("active", "prior", "rollback"):
        _digest(digests.get(key), f"digests.{key}", optional=True)


def _validate_common(
    record: Mapping[str, Any], allowed: frozenset[str], event: str
) -> None:
    unknown = set(record) - allowed
    if unknown:
        raise ReceiptValidationError(
            f"unknown receipt fields: {', '.join(sorted(unknown))}"
        )
    required = allowed - {"session_ref", "task_ref", "turn_ref"}
    missing = required - set(record)
    if missing:
        raise ReceiptValidationError(
            f"missing receipt fields: {', '.join(sorted(missing))}"
        )
    if record.get("schema") != SCHEMA_ID or record.get("event") != event:
        raise ReceiptValidationError("schema/event mismatch")
    event_id = record.get("event_id")
    if not isinstance(event_id, str) or not _EVENT_ID_RE.fullmatch(event_id):
        raise ReceiptValidationError("event_id is invalid")
    expected_prefix = "act_" if event == "activation" else "out_"
    if not event_id.startswith(expected_prefix):
        raise ReceiptValidationError("event_id prefix does not match event")
    _validate_timestamp(record.get("timestamp"))
    _safe_string(record.get("profile"), _SAFE_NAME_RE, "profile")


def _mapping_with_keys(value: Any, keys: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptValidationError(f"{field} must be a mapping")
    if set(value) != keys:
        raise ReceiptValidationError(
            f"{field} must contain exactly: {', '.join(sorted(keys))}"
        )
    return value


def _safe_string(value: Any, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ReceiptValidationError(f"{field} is not a safe bounded identifier")
    return value


def _counter(value: Any, field: str) -> None:
    if type(value) is not int or not (0 <= value <= _MAX_COUNTER):
        raise ReceiptValidationError(f"{field} must be a non-negative integer")


def _digest(value: Any, field: str, *, optional: bool) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReceiptValidationError(f"{field} must be a lowercase SHA-256 digest")


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str) or len(value) > 32 or not value.endswith("Z"):
        raise ReceiptValidationError("timestamp must be a bounded UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReceiptValidationError("timestamp is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise ReceiptValidationError("timestamp must use UTC")


def _format_timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ReceiptValidationError("timestamp must be timezone-aware")
    current = current.astimezone(timezone.utc)
    return current.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_skill_name(value: str) -> str:
    candidate = value.strip().replace("_", "-").replace(" ", "-")
    candidate = re.sub(r"[^A-Za-z0-9_.:-]+", "-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-.")
    if not candidate or not _SAFE_NAME_RE.fullmatch(candidate):
        raise ReceiptValidationError("skill name cannot be represented safely")
    return candidate


def _inspect_skill(skill_dir: Path, canonical_name: str | None) -> dict[str, Any]:
    from agent.skill_contract import CONTRACT_FILENAME, validate_skill_directory
    from agent.skill_utils import parse_frontmatter
    from tools.skill_install import sha256_tree

    _assert_safe_directory(skill_dir, "skill directory")
    signature_before = _skill_tree_metadata_signature(skill_dir)
    cache_key = (str(skill_dir.resolve()), signature_before)
    with _SKILL_IDENTITY_CACHE_LOCK:
        cached = _SKILL_IDENTITY_CACHE.get(cache_key)
        if cached is not None:
            _SKILL_IDENTITY_CACHE.move_to_end(cache_key)
            # The cached object never escapes without a JSON roundtrip below;
            # copy nested dicts here so callers cannot mutate cache state.
            return {
                "skill": dict(cached["skill"]),
                "governance": dict(cached["governance"]),
            }
    skill_md = skill_dir / "SKILL.md"
    raw = _read_regular_file(skill_md, 2 * 1024 * 1024).decode("utf-8")
    frontmatter, _ = parse_frontmatter(raw)
    validation = validate_skill_directory(skill_dir)
    contract = validation.contract if isinstance(validation.contract, Mapping) else {}
    identity = contract.get("identity") if validation.status == "verified" else None
    identity = identity if isinstance(identity, Mapping) else {}
    raw_name = (
        identity.get("name")
        or frontmatter.get("name")
        or canonical_name
        or skill_dir.name
    )
    raw_version = identity.get("version") or frontmatter.get("version") or "unversioned"
    name = _canonical_skill_name(str(raw_name))
    version = str(raw_version).strip() or "unversioned"
    if not _SAFE_VERSION_RE.fullmatch(version):
        version = "unversioned"

    contract_digest = validation.digest
    contract_path = skill_dir / CONTRACT_FILENAME
    if contract_digest is None and (
        contract_path.exists() or contract_path.is_symlink()
    ):
        try:
            contract_digest = hashlib.sha256(
                _read_regular_file(contract_path, 512 * 1024)
            ).hexdigest()
        except ReceiptIOError:
            contract_digest = None
    tree_digest = sha256_tree(
        skill_dir,
        max_file_bytes=_MAX_SKILL_FILE_BYTES,
        max_total_bytes=_MAX_SKILL_TREE_BYTES,
    )
    signature_after = _skill_tree_metadata_signature(skill_dir)
    if signature_before != signature_after:
        raise ReceiptIOError("skill tree changed while building its activation receipt")
    result = {
        "skill": {
            "name": name,
            "version": version,
            "tree_sha256": tree_digest,
            "contract_sha256": contract_digest,
            "contract_status": validation.status,
        },
        "governance": {
            "mode": {
                "verified": "governed",
                "legacy_unverified": "legacy",
                "invalid": "invalid",
            }[validation.status],
            "lane": _governance_lane(validation.contract, validation.status),
        },
    }
    with _SKILL_IDENTITY_CACHE_LOCK:
        # Drop stale generations for this path, then retain only a bounded LRU.
        resolved = cache_key[0]
        for old_key in tuple(_SKILL_IDENTITY_CACHE):
            if old_key[0] == resolved and old_key != cache_key:
                _SKILL_IDENTITY_CACHE.pop(old_key, None)
        _SKILL_IDENTITY_CACHE[cache_key] = {
            "skill": dict(result["skill"]),
            "governance": dict(result["governance"]),
        }
        _SKILL_IDENTITY_CACHE.move_to_end(cache_key)
        while len(_SKILL_IDENTITY_CACHE) > _SKILL_IDENTITY_CACHE_SIZE:
            _SKILL_IDENTITY_CACHE.popitem(last=False)
    return result


def _skill_tree_metadata_signature(skill_dir: Path) -> str:
    """Cheap cache key that invalidates on path/content metadata changes.

    This is a performance cache only, not a security attestation: a miss still
    uses the existing descriptor-safe ``sha256_tree`` implementation, and the
    signature is checked again after hashing so a concurrent mutation fails.
    """

    digest = hashlib.sha256()
    total_bytes = 0
    file_count = 0
    try:
        paths = sorted(
            skill_dir.rglob("*"),
            key=lambda item: item.relative_to(skill_dir).as_posix().encode("utf-8"),
        )
    except (OSError, UnicodeError) as exc:
        raise ReceiptIOError("could not enumerate skill tree") from exc
    for path in paths:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ReceiptIOError("could not inspect skill tree") from exc
        relative = path.relative_to(skill_dir).as_posix()
        if stat.S_ISDIR(info.st_mode):
            if path.is_symlink():
                raise ReceiptIOError("skill tree contains a redirect directory")
            continue
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise ReceiptIOError("skill tree contains a non-regular entry")
        file_count += 1
        total_bytes += info.st_size
        if file_count > _MAX_SKILL_TREE_FILES or total_bytes > _MAX_SKILL_TREE_BYTES:
            raise ReceiptIOError("skill tree exceeds receipt digest limits")
        payload = (
            relative,
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            getattr(info, "st_ctime_ns", 0),
        )
        digest.update(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\0")
    if file_count == 0:
        raise ReceiptIOError("skill tree contains no regular files")
    return digest.hexdigest()


def _clear_skill_identity_cache() -> None:
    """Test hook for deterministic cache behavior checks."""

    with _SKILL_IDENTITY_CACHE_LOCK:
        _SKILL_IDENTITY_CACHE.clear()


def _governance_lane(contract: Mapping[str, Any] | None, status: str) -> str:
    # Import lazily so receipt-only consumers do not pay the permission registry
    # startup cost, while both surfaces still use one risk classification contract.
    from agent.skill_permissions import derive_skill_risk_lane

    return derive_skill_risk_lane(contract, status)


def _profile_name(home: Path) -> str:
    if home.parent.name == "profiles":
        return _canonical_skill_name(home.name)
    if home == get_fabric_home():
        try:
            from fabric_cli.profiles import get_active_profile_name

            return _canonical_skill_name(get_active_profile_name())
        except Exception:
            pass
    return "default"


def _context_ref(key: bytes, value: Any) -> str:
    encoded = str(value).encode("utf-8", errors="strict")
    if not encoded or len(encoded) > _MAX_CONTEXT_VALUE_BYTES:
        raise ReceiptValidationError("context identifier is empty or too large")
    return "hmac-sha256:" + hmac.new(key, encoded, hashlib.sha256).hexdigest()


def _governance_path(home: Path) -> Path:
    return home / "skills" / ".governance"


def _ensure_governance_dir(home: Path) -> Path:
    try:
        if not home.exists():
            home.mkdir(parents=True, mode=0o700, exist_ok=True)
        _assert_safe_directory(home, "profile home")
        skills = home / "skills"
        if not skills.exists():
            skills.mkdir(mode=0o700, exist_ok=True)
        _assert_safe_directory(skills, "skills directory")
        governance = _governance_path(home)
        if not governance.exists():
            governance.mkdir(mode=0o700, exist_ok=True)
        _assert_safe_directory(governance, "governance directory")
        try:
            governance.resolve().relative_to(home.resolve())
        except ValueError as exc:
            raise ReceiptIOError("governance directory escapes the profile") from exc
        os.chmod(governance, 0o700)
        return governance
    except ReceiptIOError:
        raise
    except OSError as exc:
        raise ReceiptIOError(f"could not prepare receipt directory: {exc}") from exc


def _assert_safe_directory(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ReceiptIOError(f"{label} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISDIR(mode):
        raise ReceiptIOError(f"{label} must be a regular non-symlink directory")


def _assert_safe_regular_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ReceiptIOError(f"could not inspect receipt file {path}") from exc
    if path.is_symlink() or not stat.S_ISREG(mode):
        raise ReceiptIOError(f"receipt file must be regular and non-symlink: {path}")


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    _assert_safe_regular_file(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ReceiptIOError(f"could not safely open {path}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > max_bytes:
            raise ReceiptIOError(f"unsafe or oversized receipt file: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ReceiptIOError(f"receipt file grew beyond limit: {path}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _load_or_create_context_key(governance: Path) -> bytes:
    path = governance / "skill-receipts.key"
    try:
        key = (
            _read_regular_file(path, 32)
            if path.exists() or path.is_symlink()
            else _create_key(path)
        )
    except FileExistsError:
        key = _read_regular_file(path, 32)
    if len(key) != 32:
        raise ReceiptIOError("skill receipt context key must be exactly 32 bytes")
    try:
        if os.name != "nt" and stat.S_IMODE(path.lstat().st_mode) != 0o600:
            raise ReceiptIOError("skill receipt context key must have mode 0600")
    except OSError as exc:
        raise ReceiptIOError("could not verify skill receipt context key mode") from exc
    return key


def _create_key(path: Path) -> bytes:
    key = secrets.token_bytes(32)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = os.open(path, flags, 0o600)
    try:
        _set_private_file_mode(fd, path)
        os.write(fd, key)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)
    return key


@contextmanager
def _journal_lock(governance: Path):
    path = governance / "skill-receipts.lock"
    _assert_safe_regular_file(path)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, 0o600)
        _set_private_file_mode(fd, path)
    except OSError as exc:
        raise ReceiptIOError("could not open skill receipt lock safely") from exc
    with _PROCESS_LOCK:
        try:
            if os.name == "nt":  # pragma: no cover - exercised on Windows CI
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        except ReceiptIOError:
            raise
        except Exception as exc:
            raise ReceiptIOError("skill receipt journal lock failed") from exc
        finally:
            try:
                if os.name == "nt":  # pragma: no cover
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(fd)


def _safe_file_size(path: Path) -> int:
    _assert_safe_regular_file(path)
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise ReceiptIOError(f"could not inspect {path}") from exc


def _prune_archives_locked(governance: Path, settings: ReceiptSettings) -> None:
    """Enforce reduced retention settings before the next append."""

    changed = False
    try:
        entries = tuple(governance.iterdir())
    except OSError as exc:
        raise ReceiptIOError("could not inspect skill receipt retention") from exc
    for path in entries:
        match = _ARCHIVE_NAME_RE.fullmatch(path.name)
        if match is None:
            continue
        _assert_safe_regular_file(path)
        index = int(match.group(1))
        if index >= settings.max_files or _safe_file_size(path) > settings.max_bytes:
            path.unlink()
            changed = True
    if changed:
        _fsync_directory(governance)


def _rotate_locked(
    governance: Path,
    max_files: int,
    *,
    archive_current: bool,
) -> None:
    current = governance / JOURNAL_FILENAME
    _assert_safe_regular_file(current)
    if max_files == 1:
        if current.exists():
            current.unlink()
            _fsync_directory(governance)
        return
    oldest = governance / f"skill-receipts.{max_files - 1}.jsonl"
    _assert_safe_regular_file(oldest)
    if oldest.exists():
        oldest.unlink()
    for index in range(max_files - 2, 0, -1):
        source = governance / f"skill-receipts.{index}.jsonl"
        target = governance / f"skill-receipts.{index + 1}.jsonl"
        _assert_safe_regular_file(source)
        _assert_safe_regular_file(target)
        if source.exists():
            os.replace(source, target)
    if current.exists() and archive_current:
        os.replace(current, governance / "skill-receipts.1.jsonl")
    elif current.exists():
        current.unlink()
    _fsync_directory(governance)


def _append_line_locked(path: Path, line: bytes) -> None:
    _assert_safe_regular_file(path)
    existed = path.exists()
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_APPEND
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, 0o600)
        _set_private_file_mode(fd, path)
        written = os.write(fd, line)
        if written != len(line):
            raise ReceiptIOError("short write to skill receipt journal")
        os.fsync(fd)
    except ReceiptIOError:
        raise
    except OSError as exc:
        raise ReceiptIOError("could not append skill receipt") from exc
    finally:
        if "fd" in locals():
            os.close(fd)
    if not existed:
        _fsync_directory(path.parent)


def _set_private_file_mode(descriptor: int, path: Path) -> None:
    """Apply owner-only mode where the platform exposes POSIX mode bits."""

    if hasattr(os, "fchmod"):
        os.fchmod(descriptor, 0o600)
    else:  # pragma: no cover - native Windows
        os.chmod(path, 0o600)


def _fsync_directory(path: Path) -> None:
    """Durably publish rotated/new journal names where supported."""

    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        return
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError as exc:
        raise ReceiptIOError("could not durably publish skill receipt journal") from exc
    finally:
        if "descriptor" in locals():
            os.close(descriptor)


def _empty_bucket(name: str, version: str) -> dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "activations": 0,
        "finalized": 0,
        "completed": 0,
        "failed": 0,
        "interrupted": 0,
        "durations": [],
        "counts": Counter(),
        "outcomes": Counter(),
        "guardrails": defaultdict(Counter),
        "rollback_count": 0,
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    durations = sorted(bucket["durations"])
    counts = {key: bucket["counts"].get(key, 0) for key in sorted(_COUNT_KEYS)}
    guardrails = {
        key: {
            "checked": value["checked"],
            "passed": value["passed"],
            "pass_rate": _rate(value["passed"], value["checked"]),
        }
        for key, value in sorted(bucket["guardrails"].items())
    }
    relevance = guardrails.get("routing_relevant")
    return {
        "name": bucket["name"],
        "version": bucket["version"],
        "activations": bucket["activations"],
        "finalized_activations": bucket["finalized"],
        "completed": bucket["completed"],
        "failed": bucket["failed"],
        "interrupted": bucket["interrupted"],
        "completion_coverage": _rate(bucket["completed"], bucket["activations"]),
        "completion_rate": _rate(bucket["completed"], bucket["finalized"]),
        "failure_rate": _rate(bucket["failed"], bucket["finalized"]),
        "routing_precision": relevance["pass_rate"] if relevance else None,
        "latency_ms": {
            "average": round(sum(durations) / len(durations), 3) if durations else 0.0,
            "p50": _percentile(durations, 0.50),
            "p95": _percentile(durations, 0.95),
        },
        "budget_totals": counts,
        "approvals": counts["approvals"],
        "rollback_count": bucket["rollback_count"],
        "outcomes": dict(sorted(bucket["outcomes"].items())),
        "guardrails": guardrails,
    }


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, int((len(values) * quantile) + 0.999999) - 1))
    return values[index]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _correlate_activation(
    activation_id: str,
    *,
    source: str,
    session_id: str | None,
    task_id: str | None,
    turn_id: str | None,
) -> None:
    """Place one receipt ID in the bounded volatile correlation registry."""

    if not _EVENT_ID_RE.fullmatch(activation_id) or not activation_id.startswith(
        "act_"
    ):
        return
    now = time.monotonic()
    normalized_turn = _bounded_correlation_id(turn_id)
    with _CORRELATION_LOCK:
        _cleanup_correlations_locked(now)
        if normalized_turn is not None:
            bucket = _TURN_ACTIVATIONS.get(normalized_turn)
            if bucket is None:
                bucket = _ActivationCorrelations(now, OrderedDict())
                _TURN_ACTIVATIONS[normalized_turn] = bucket
            if len(bucket.activation_ids) < _MAX_ACTIVATIONS_PER_TURN:
                bucket.activation_ids.setdefault(activation_id, None)
            bucket.updated_at = now
            _TURN_ACTIVATIONS.move_to_end(normalized_turn)
            _bound_correlations_locked(_TURN_ACTIVATIONS)
            return

        # A preload activation describes a session-level instruction. Reusing
        # its one ID for multiple turn outcomes would make aggregation choose
        # an arbitrary first terminal event, so automatic correlation is
        # intentionally disabled for this source.
        if source == "preload":
            return
        keys = _pending_scope_keys(task_id=task_id, session_id=session_id)
        if not keys:
            return
        key = keys[0]
        bucket = _PENDING_ACTIVATIONS.get(key)
        if bucket is None:
            bucket = _ActivationCorrelations(now, OrderedDict())
            _PENDING_ACTIVATIONS[key] = bucket
        if len(bucket.activation_ids) < _MAX_ACTIVATIONS_PER_TURN:
            bucket.activation_ids.setdefault(activation_id, None)
        bucket.updated_at = now
        _PENDING_ACTIVATIONS.move_to_end(key)
        _bound_correlations_locked(_PENDING_ACTIVATIONS)


def _count_last_turn_tool_calls(messages: Any) -> int:
    if not isinstance(messages, list):
        return 0
    boundary = -1
    for index in range(len(messages) - 1, -1, -1):
        item = messages[index]
        if isinstance(item, Mapping) and item.get("role") == "user":
            boundary = index
            break
    count = 0
    for item in messages[boundary + 1 :]:
        if not isinstance(item, Mapping) or item.get("role") != "assistant":
            continue
        calls = item.get("tool_calls")
        if isinstance(calls, list):
            count += len(calls)
    return min(count, _MAX_COUNTER)


def _non_negative_counter_delta(before: Any, after: Any) -> int | None:
    if (
        type(before) is not int
        or type(after) is not int
        or before < 0
        or after < before
    ):
        return None
    return min(after - before, _MAX_COUNTER)


def _non_negative_float_delta(before: Any, after: Any) -> float | None:
    if (
        isinstance(before, bool)
        or isinstance(after, bool)
        or not isinstance(before, (int, float))
        or not isinstance(after, (int, float))
    ):
        return None
    left = float(before)
    right = float(after)
    if not math.isfinite(left) or not math.isfinite(right) or left < 0 or right < left:
        return None
    return right - left


def _take_turn_activation_ids(turn_id: str) -> tuple[str, ...]:
    normalized = _bounded_correlation_id(turn_id)
    if normalized is None:
        return ()
    with _CORRELATION_LOCK:
        _cleanup_correlations_locked(time.monotonic())
        bucket = _TURN_ACTIVATIONS.pop(normalized, None)
        return tuple(bucket.activation_ids) if bucket is not None else ()


def _pending_scope_keys(
    *, task_id: str | None, session_id: str | None
) -> tuple[tuple[str, str], ...]:
    keys: list[tuple[str, str]] = []
    task = _bounded_correlation_id(task_id)
    session = _bounded_correlation_id(session_id)
    if task is not None:
        keys.append(("task", task))
    if session is not None:
        key = ("session", session)
        if key not in keys:
            keys.append(key)
    return tuple(keys)


def _bounded_correlation_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return None
    if len(encoded) > _MAX_CORRELATION_ID_BYTES:
        return None
    return value


def _cleanup_correlations_locked(now: float) -> None:
    for registry in (_PENDING_ACTIVATIONS, _TURN_ACTIVATIONS):
        expired = [
            key
            for key, bucket in registry.items()
            if now - bucket.updated_at > _CORRELATION_TTL_SECONDS
        ]
        for key in expired:
            registry.pop(key, None)
        _bound_correlations_locked(registry)


def _bound_correlations_locked(registry: OrderedDict[Any, Any]) -> None:
    while len(registry) > _MAX_CORRELATION_SCOPES:
        registry.popitem(last=False)


def _clear_receipt_correlations_for_tests() -> None:
    with _CORRELATION_LOCK:
        _PENDING_ACTIVATIONS.clear()
        _TURN_ACTIVATIONS.clear()


__all__ = [
    "AGGREGATE_SCHEMA_ID",
    "JOURNAL_FILENAME",
    "ReceiptIOError",
    "ReceiptSettings",
    "ReceiptValidationError",
    "SCHEMA_ID",
    "aggregate_receipts",
    "append_receipt",
    "bind_pending_activation_receipts",
    "finalize_agent_turn_receipts_best_effort",
    "load_receipt_settings",
    "read_receipts",
    "record_activation",
    "record_activation_best_effort",
    "record_outcome",
    "record_turn_outcome_best_effort",
    "validate_receipt",
]
