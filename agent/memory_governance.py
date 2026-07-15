"""Local governance metadata for Fabric's built-in curated memory.

The durable memory text remains in ``MEMORY.md`` and ``USER.md``.  This
module stores only a bounded, profile-local provenance sidecar containing
opaque record ids, content digests, lifecycle timestamps, and pseudonymous
source correlations.  Prompts, responses, tool arguments, memory text, and
raw session/task identifiers have no field in the closed schema.

Governance is deliberately best-effort at runtime: a sidecar failure never
rolls back or blocks a memory write.  The deterministic audit then reports the
entry as untracked.  Expiry is evaluated once when a ``MemoryStore`` captures
its frozen session snapshot; live memory and the on-disk files are not
modified by expiry handling.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import stat
import tempfile
import threading
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fabric_constants import get_fabric_home


logger = logging.getLogger(__name__)

SCHEMA_ID = "fabric.memory-governance/v1"
AUDIT_SCHEMA_ID = "fabric.memory-governance-audit/v1"
STATE_FILENAME = "memory-governance.json"
KEY_FILENAME = "memory-governance.key"
EXPIRED_PLACEHOLDER = "[Unavailable: governed memory expired pending revalidation.]"

_MAX_STATE_BYTES = 2 * 1024 * 1024
_MAX_MEMORY_FILE_BYTES = 2 * 1024 * 1024
# A validated record is comfortably under 2 KiB; this count therefore stays
# below the 2 MiB encoded-state cap even at maximum lifecycle retention.
_MAX_RECORDS = 1024
_MAX_ENTRY_COUNT = 4096
_MAX_ENTRY_BYTES = 256 * 1024
_DEFAULT_REVIEW_DAYS = 180
_MAX_POLICY_DAYS = 3650
_PROCESS_LOCK = threading.RLock()
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_ID_RE = re.compile(r"^content_[0-9a-f]{24}$")
_RECORD_ID_RE = re.compile(r"^mem_[0-9a-f]{32}$")
_CONTEXT_REF_RE = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_STRUCTURED_FACT_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 _./-]{0,63})\s*[:=]\s*(\S(?:.*\S)?)\s*$"
)

_ORIGINS = frozenset(
    {
        "assistant_tool",
        "background_review",
        "curator",
        "approved_write",
        "manual",
        "other",
    }
)
_CONTEXTS = frozenset(
    {"foreground", "background", "background_review", "scheduled", "subagent", "other"}
)
_PLATFORMS = frozenset(
    {
        "cli",
        "tui",
        "desktop",
        "web",
        "dashboard",
        "local",
        "api",
        "api_server",
        "acp",
        "codex_app",
        "cron",
        "curator",
        "telegram",
        "discord",
        "slack",
        "whatsapp",
        "whatsapp_cloud",
        "signal",
        "matrix",
        "mattermost",
        "email",
        "sms",
        "dingtalk",
        "wecom",
        "wecom_callback",
        "weixin",
        "feishu",
        "qqbot",
        "bluebubbles",
        "yuanbao",
        "webhook",
        "msgraph_webhook",
        "homeassistant",
        "gateway",
        "oneshot",
        "subagent",
        "relay",
        "other",
    }
)
_CONFIDENCE = frozenset({"unspecified", "low", "medium", "high"})
_TARGETS = frozenset({"memory", "user"})
_STATUSES = frozenset({"active", "superseded", "removed"})

_STATE_KEYS = frozenset({"schema", "generation", "records"})
_RECORD_KEYS = frozenset(
    {
        "id",
        "target",
        "content_id",
        "content_sha256",
        "status",
        "source",
        "terminal_source",
        "confidence",
        "scope",
        "created_at",
        "last_validated_at",
        "review_after",
        "expires_at",
        "policy",
        "supersedes_content_id",
        "superseded_by",
        "removed_at",
        "relevance",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "origin",
        "context",
        "platform",
        "session_ref",
        "parent_session_ref",
        "task_ref",
        "tool_call_ref",
    }
)
_POLICY_KEYS = frozenset({"review_interval_days", "expiry_interval_days"})
_RELEVANCE_KEYS = frozenset({"relevant", "irrelevant"})


class MemoryGovernanceError(RuntimeError):
    """Governance state could not be accessed without risking data loss."""


def content_digest(entry: str) -> str:
    """Return the canonical SHA-256 digest for one parsed memory entry."""

    return hashlib.sha256(entry.strip().encode("utf-8")).hexdigest()


def content_id(entry_or_digest: str, *, is_digest: bool = False) -> str:
    """Return a stable opaque id derived from a content digest."""

    digest = entry_or_digest if is_digest else content_digest(entry_or_digest)
    if not _DIGEST_RE.fullmatch(digest):
        raise ValueError("content digest is invalid")
    return f"content_{digest[:24]}"


def record_committed_write(
    *,
    target: str,
    before_entries: Sequence[str],
    after_entries: Sequence[str],
    tool_args: Mapping[str, Any],
    tool_result: str | Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    home: Path | None = None,
    now: datetime | None = None,
) -> bool:
    """Record one successful committed built-in memory mutation.

    ``tool_args`` and entry text are used transiently to derive lifecycle
    relationships.  Neither is serialized.  Staged, failed, malformed, and
    idempotent no-op results are ignored.
    """

    if target not in _TARGETS:
        return False
    result = _parse_tool_result(tool_result)
    if not result or result.get("success") is not True or result.get("staged") is True:
        return False
    before = _bounded_entries(before_entries)
    after = _bounded_entries(after_entries)
    changes = _derive_committed_changes(before, after, tool_args, result)
    if not changes:
        return True

    profile_home = Path(home) if home is not None else get_fabric_home()
    current = _coerce_now(now)
    with _state_lock(profile_home, create=True) as governance:
        state, error = _load_state_locked(governance)
        if error:
            raise MemoryGovernanceError(error)
        key = _load_or_create_key_locked(governance)
        source = _build_source(metadata or {}, key)
        confidence = _confidence(metadata or {})
        review_days = _policy_days(metadata or {}, "review_interval_days", _DEFAULT_REVIEW_DAYS)
        expiry_days = _policy_days(metadata or {}, "expiry_interval_days", None)
        records = state["records"]

        for change in changes:
            old_digest = change.get("old_digest")
            new_digest = change.get("new_digest")
            new_record: dict[str, Any] | None = None

            if new_digest is not None:
                desired = Counter(content_digest(item) for item in after)[new_digest]
                active = _active_records(records, target, new_digest)
                if len(active) < desired:
                    new_record = _new_record(
                        target=target,
                        digest=new_digest,
                        source=source,
                        confidence=confidence,
                        current=current,
                        review_days=review_days,
                        expiry_days=expiry_days,
                        supersedes_content_id=(
                            content_id(old_digest, is_digest=True)
                            if old_digest is not None
                            else None
                        ),
                    )
                    records.append(new_record)
                elif old_digest is not None and active:
                    new_record = active[0]

            if old_digest is not None:
                old_active = _active_records(records, target, old_digest)
                # A same-content replacement has no lifecycle transition.
                if old_digest == new_digest:
                    continue
                if old_active:
                    old_record = old_active[0]
                else:
                    old_record = _new_record(
                        target=target,
                        digest=old_digest,
                        source=source,
                        confidence="unspecified",
                        current=current,
                        review_days=review_days,
                        expiry_days=None,
                        supersedes_content_id=None,
                    )
                    records.append(old_record)
                old_record["terminal_source"] = dict(source)
                if new_digest is not None:
                    old_record["status"] = "superseded"
                    old_record["superseded_by"] = (
                        new_record["id"] if new_record is not None else None
                    )
                else:
                    old_record["status"] = "removed"
                    old_record["removed_at"] = _format_time(current)

        state["generation"] += 1
        _compact_records(state)
        _write_state_locked(governance, state)
    return True


def record_committed_write_best_effort(**kwargs: Any) -> bool:
    """Runtime wrapper: provenance failure never blocks the committed write."""

    try:
        return record_committed_write(**kwargs)
    except Exception:
        logger.debug("Could not record built-in memory governance metadata", exc_info=True)
        return False


def audit_memory(
    *, home: Path | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Compare current memory files with provenance and return a private audit.

    The report contains digests and opaque ids only; it never echoes memory
    text.  Contradictions are conservative candidates, not truth judgments.
    """

    profile_home = Path(home) if home is not None else get_fabric_home()
    current = _coerce_now(now)
    state, governance_error = _read_state(profile_home)
    entries_by_target, memory_errors = _read_current_entries(profile_home)
    records = state["records"] if state is not None else []

    exact_duplicates: list[dict[str, Any]] = []
    untracked: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    digest_targets: dict[str, Counter[str]] = defaultdict(Counter)

    for target in sorted(_TARGETS):
        entries = entries_by_target.get(target, [])
        counts = Counter(content_digest(entry) for entry in entries)
        for digest, count in counts.items():
            digest_targets[digest][target] += count
        tracked_counts = Counter(
            record["content_sha256"]
            for record in records
            if record["target"] == target and record["status"] == "active"
        )
        for digest, count in sorted(counts.items()):
            if count > 1:
                exact_duplicates.append(
                    {
                        "target": target,
                        "content_id": content_id(digest, is_digest=True),
                        "content_sha256": digest,
                        "count": count,
                    }
                )
            if count > tracked_counts[digest]:
                untracked.append(
                    {
                        "target": target,
                        "content_id": content_id(digest, is_digest=True),
                        "content_sha256": digest,
                        "count": count - tracked_counts[digest],
                    }
                )
        for digest, count in sorted(tracked_counts.items()):
            missing = count - counts[digest]
            if missing <= 0:
                continue
            candidates = _active_records(records, target, digest)
            for record in candidates[-missing:]:
                orphaned.append(
                    {
                        "record_id": record["id"],
                        "target": target,
                        "content_id": record["content_id"],
                        "content_sha256": digest,
                    }
                )
        conflicts.extend(_candidate_contradictions(target, entries))

    for digest, targets in sorted(digest_targets.items()):
        if len(targets) <= 1:
            continue
        exact_duplicates.append(
            {
                "target": "cross_target",
                "targets": dict(sorted(targets.items())),
                "content_id": content_id(digest, is_digest=True),
                "content_sha256": digest,
                "count": sum(targets.values()),
            }
        )
    cross_conflicts = _candidate_contradictions(
        "cross_target", entries_by_target.get("memory", []) + entries_by_target.get("user", [])
    )
    for finding in cross_conflicts:
        involved = {
            target
            for digest in finding["content_sha256"]
            for target in digest_targets.get(digest, {})
        }
        if len(involved) > 1:
            finding["targets"] = sorted(involved)
            conflicts.append(finding)

    active_records = [record for record in records if record["status"] == "active"]
    review_due = [
        _record_deadline_view(record, "review_after")
        for record in active_records
        if _parse_time(record["review_after"]) <= current
    ]
    expired = [
        _record_deadline_view(record, "expires_at")
        for record in active_records
        if record["expires_at"] is not None
        and _parse_time(record["expires_at"]) <= current
    ]
    review_due.sort(key=lambda item: (item["deadline"], item["record_id"]))
    expired.sort(key=lambda item: (item["deadline"], item["record_id"]))

    relevant = sum(record["relevance"]["relevant"] for record in records)
    irrelevant = sum(record["relevance"]["irrelevant"] for record in records)
    labelled = relevant + irrelevant
    retrieval_precision = round(relevant / labelled, 6) if labelled else None

    errors = ([governance_error] if governance_error else []) + memory_errors
    findings = exact_duplicates or conflicts or untracked or orphaned or review_due or expired
    status = "degraded" if errors else ("attention" if findings else "ok")
    return {
        "schema": AUDIT_SCHEMA_ID,
        "generated_at": _format_time(current),
        "status": status,
        "errors": sorted(errors),
        "summary": {
            "current_entries": sum(len(items) for items in entries_by_target.values()),
            "governed_active_records": len(active_records),
            "untracked_entries": sum(item["count"] for item in untracked),
            "orphaned_records": len(orphaned),
            "exact_duplicate_groups": len(exact_duplicates),
            "candidate_contradictions": len(conflicts),
            "review_due_records": len(review_due),
            "expired_records": len(expired),
        },
        "retrieval_precision": retrieval_precision,
        "exact_duplicates": sorted(
            exact_duplicates, key=lambda item: (item["target"], item["content_sha256"])
        ),
        "candidate_contradictions": sorted(
            conflicts, key=lambda item: (item["target"], item["subject_sha256"])
        ),
        "untracked_entries": sorted(
            untracked, key=lambda item: (item["target"], item["content_sha256"])
        ),
        "orphaned_records": sorted(
            orphaned, key=lambda item: (item["target"], item["record_id"])
        ),
        "review_due_records": review_due,
        "expired_records": expired,
    }


def format_audit_report(report: Mapping[str, Any]) -> str:
    """Render a concise text form of :func:`audit_memory`."""

    summary = report.get("summary") if isinstance(report, Mapping) else {}
    summary = summary if isinstance(summary, Mapping) else {}
    lines = [f"Built-in memory governance: {report.get('status', 'degraded')}"]
    lines.append(
        "  entries={current} governed={governed} untracked={untracked} orphaned={orphaned}".format(
            current=summary.get("current_entries", 0),
            governed=summary.get("governed_active_records", 0),
            untracked=summary.get("untracked_entries", 0),
            orphaned=summary.get("orphaned_records", 0),
        )
    )
    lines.append(
        "  duplicates={duplicates} conflict-candidates={conflicts} review-due={review} expired={expired}".format(
            duplicates=summary.get("exact_duplicate_groups", 0),
            conflicts=summary.get("candidate_contradictions", 0),
            review=summary.get("review_due_records", 0),
            expired=summary.get("expired_records", 0),
        )
    )
    precision = report.get("retrieval_precision")
    lines.append(
        "  retrieval-precision=" + ("not measured" if precision is None else str(precision))
    )
    for label, field in (
        ("expired", "expired_records"),
        ("review due", "review_due_records"),
        ("orphaned", "orphaned_records"),
    ):
        records = report.get(field, []) if isinstance(report, Mapping) else []
        records = records if isinstance(records, list) else []
        for record in records[:20]:
            if not isinstance(record, Mapping):
                continue
            lines.append(
                f"  {label}: {record.get('record_id', 'unknown')} "
                f"({record.get('target', 'unknown')}, {record.get('content_id', 'unknown')})"
            )
        if len(records) > 20:
            lines.append(f"  {label}: +{len(records) - 20} more (use --json)")
    for error in report.get("errors", []) if isinstance(report, Mapping) else []:
        lines.append(f"  warning: {error}")
    return "\n".join(lines)


def revalidate_record(
    record_id: str, *, home: Path | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Revalidate one current governed record and refresh its policy clocks."""

    if not isinstance(record_id, str) or not _RECORD_ID_RE.fullmatch(record_id):
        return {"success": False, "error": "invalid_record_id"}
    profile_home = Path(home) if home is not None else get_fabric_home()
    current = _coerce_now(now)
    try:
        return _revalidate_record_locked(record_id, profile_home, current)
    except (MemoryGovernanceError, OSError, ValueError):
        return {"success": False, "error": "governance_state_unsafe"}


def _revalidate_record_locked(
    record_id: str, profile_home: Path, current: datetime
) -> dict[str, Any]:
    with _state_lock(profile_home, create=False) as governance:
        if governance is None:
            return {"success": False, "error": "governance_state_missing"}
        state, error = _load_state_locked(governance)
        if error:
            return {"success": False, "error": "governance_state_corrupt"}
        record = next((item for item in state["records"] if item["id"] == record_id), None)
        if record is None:
            return {"success": False, "error": "record_not_found"}
        if record["status"] != "active":
            return {"success": False, "error": "record_not_active"}
        entries_by_target, errors = _read_current_entries(profile_home)
        if errors:
            return {"success": False, "error": "memory_store_unavailable"}
        current_digests = {
            content_digest(entry) for entry in entries_by_target[record["target"]]
        }
        if record["content_sha256"] not in current_digests:
            return {"success": False, "error": "record_orphaned"}
        # Exact duplicates are occurrence-governed.  Match the same oldest-
        # first records that ``audit_memory`` keeps non-orphaned so a removed
        # duplicate cannot be revalidated merely because one identical entry
        # still exists on disk.
        occurrence_count = sum(
            content_digest(entry) == record["content_sha256"]
            for entry in entries_by_target[record["target"]]
        )
        current_records = _active_records(
            state["records"], record["target"], record["content_sha256"]
        )[:occurrence_count]
        if record["id"] not in {item["id"] for item in current_records}:
            return {"success": False, "error": "record_orphaned"}

        policy = record["policy"]
        record["last_validated_at"] = _format_time(current)
        record["review_after"] = _format_time(
            current + timedelta(days=policy["review_interval_days"])
        )
        expiry_days = policy["expiry_interval_days"]
        record["expires_at"] = (
            _format_time(current + timedelta(days=expiry_days))
            if expiry_days is not None
            else None
        )
        state["generation"] += 1
        _write_state_locked(governance, state)
        return {
            "success": True,
            "record_id": record_id,
            "last_validated_at": record["last_validated_at"],
            "review_after": record["review_after"],
            "expires_at": record["expires_at"],
        }


def record_relevance_label(
    record_id: str,
    *,
    relevant: bool,
    home: Path | None = None,
) -> bool:
    """Record an explicit retrieval-relevance label for precision metrics."""

    if type(relevant) is not bool or not _RECORD_ID_RE.fullmatch(record_id or ""):
        return False
    profile_home = Path(home) if home is not None else get_fabric_home()
    try:
        return _record_relevance_label_locked(record_id, relevant, profile_home)
    except (MemoryGovernanceError, OSError, ValueError):
        return False


def _record_relevance_label_locked(
    record_id: str, relevant: bool, profile_home: Path
) -> bool:
    with _state_lock(profile_home, create=False) as governance:
        if governance is None:
            return False
        state, error = _load_state_locked(governance)
        if error:
            return False
        record = next((item for item in state["records"] if item["id"] == record_id), None)
        if record is None:
            return False
        field = "relevant" if relevant else "irrelevant"
        record["relevance"][field] += 1
        state["generation"] += 1
        _write_state_locked(governance, state)
        return True


def capture_expiry_decisions(
    entries_by_target: Mapping[str, Sequence[str]],
    *,
    home: Path | None = None,
    now: datetime | None = None,
) -> dict[str, dict[str, int]]:
    """Capture expired occurrence counts for one frozen session snapshot.

    Corrupt or unavailable governance fails open: legacy and untracked memory
    remains usable, while ``fabric memory audit`` reports the sidecar problem.
    """

    profile_home = Path(home) if home is not None else get_fabric_home()
    state, error = _read_state(profile_home)
    if state is None or error:
        if error:
            logger.debug("Memory governance expiry unavailable: %s", error)
        return {"memory": {}, "user": {}}
    current = _coerce_now(now)
    decisions: dict[str, dict[str, int]] = {"memory": {}, "user": {}}
    for target in _TARGETS:
        available = Counter(
            content_digest(entry) for entry in entries_by_target.get(target, [])
        )
        expired_counts: Counter[str] = Counter()
        for digest, count in sorted(available.items()):
            # Audit maps current duplicate occurrences to the oldest active
            # records and reports later records as orphaned.  Apply expiry to
            # that identical deterministic subset; an expired orphan must not
            # hide a surviving unexpired occurrence.
            current_records = _active_records(state["records"], target, digest)[:count]
            expired_counts[digest] = sum(
                record["expires_at"] is not None
                and _parse_time(record["expires_at"]) <= current
                for record in current_records
            )
        decisions[target] = {
            digest: min(count, available[digest])
            for digest, count in sorted(expired_counts.items())
            if count > 0 and available[digest] > 0
        }
    return decisions


def apply_expiry_decisions(
    target: str,
    entries: Sequence[str],
    decisions: Mapping[str, Mapping[str, int]],
) -> list[str]:
    """Apply a previously frozen expiry decision without reading live state."""

    remaining = Counter(decisions.get(target, {})) if target in _TARGETS else Counter()
    sanitized: list[str] = []
    for entry in entries:
        digest = content_digest(entry)
        if remaining[digest] > 0:
            sanitized.append(EXPIRED_PLACEHOLDER)
            remaining[digest] -= 1
        else:
            sanitized.append(entry)
    return sanitized


def has_governance_state(target: str = "all", *, home: Path | None = None) -> bool:
    """Return whether reset has governance state to remove for ``target``."""

    if target not in {"all", *_TARGETS}:
        return False
    profile_home = Path(home) if home is not None else get_fabric_home()
    governance = _governance_path(profile_home)
    path = governance / STATE_FILENAME
    key_path = governance / KEY_FILENAME
    if (
        not path.exists()
        and not path.is_symlink()
        and (target != "all" or (not key_path.exists() and not key_path.is_symlink()))
    ):
        return False
    if (
        target == "all"
        and not path.exists()
        and not path.is_symlink()
        and (key_path.exists() or key_path.is_symlink())
    ):
        return True
    state, error = _read_state(profile_home)
    if error or state is None:
        return True
    return bool(state["records"]) if target == "all" else any(
        record["target"] == target for record in state["records"]
    )


def reset_governance(target: str = "all", *, home: Path | None = None) -> bool:
    """Remove all governance state or safely prune records for one target."""

    if target not in {"all", *_TARGETS}:
        return False
    profile_home = Path(home) if home is not None else get_fabric_home()
    try:
        return _reset_governance_locked(target, profile_home)
    except (MemoryGovernanceError, OSError, ValueError):
        return False


def _reset_governance_locked(target: str, profile_home: Path) -> bool:
    with _state_lock(profile_home, create=False) as governance:
        if governance is None:
            return True
        state_path = governance / STATE_FILENAME
        if target == "all":
            paths: list[Path] = []
            for path in (state_path, governance / KEY_FILENAME):
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                # Unlinking a symlink removes the link itself and never
                # follows it.  Directories/devices are not governance files
                # and are left untouched.
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                    return False
                paths.append(path)
            for path in paths:
                path.unlink()
            _fsync_dir(governance)
            return True
        state, error = _load_state_locked(governance)
        if error:
            return False
        kept = [record for record in state["records"] if record["target"] != target]
        if len(kept) == len(state["records"]):
            return True
        state["records"] = kept
        state["generation"] += 1
        _write_state_locked(governance, state)
        return True


def _derive_committed_changes(
    before: list[str],
    after: list[str],
    tool_args: Mapping[str, Any],
    result: Mapping[str, Any],
) -> list[dict[str, str | None]]:
    if (
        tool_args.get("action") == "add"
        and isinstance(result.get("message"), str)
        and "already exists" in result["message"].lower()
    ):
        return []
    operations = tool_args.get("operations")
    if not isinstance(operations, list) or not operations:
        operations = [
            {
                "action": tool_args.get("action"),
                "content": tool_args.get("content"),
                "old_text": tool_args.get("old_text"),
            }
        ]
    if len(operations) > _MAX_ENTRY_COUNT:
        raise MemoryGovernanceError("memory operation collection is out of bounds")
    # Track occurrence lineage through the whole atomic batch.  This collapses
    # chains such as A -> B -> C into one A -> C supersession, treats
    # add-then-remove as a net no-op, and preserves replace-then-remove as a
    # removal of the original record.
    working = [
        {"content": entry, "origin_digest": content_digest(entry)} for entry in before
    ]
    removed_origins: list[str] = []
    for raw in operations:
        if not isinstance(raw, Mapping):
            continue
        action = raw.get("action")
        content = raw.get("content")
        old_text = raw.get("old_text")
        content = content.strip() if isinstance(content, str) else ""
        old_text = old_text.strip() if isinstance(old_text, str) else ""
        if action == "add" and content:
            if content not in [token["content"] for token in working]:
                working.append({"content": content, "origin_digest": None})
        elif action in {"replace", "remove"} and old_text:
            matches = [
                index
                for index, token in enumerate(working)
                if old_text in token["content"]
            ]
            if not matches:
                continue
            index = matches[0]
            if action == "replace" and content:
                working[index]["content"] = content
            elif action == "remove":
                removed = working.pop(index)
                if removed["origin_digest"] is not None:
                    removed_origins.append(removed["origin_digest"])

    planned: list[dict[str, str | None]] = [
        {"old_digest": digest, "new_digest": None} for digest in removed_origins
    ]
    for token in working:
        new_digest = content_digest(token["content"])
        old_digest = token["origin_digest"]
        if old_digest != new_digest:
            planned.append({"old_digest": old_digest, "new_digest": new_digest})

    # The normal path is exact: MemoryStore committed the same simulated list
    # we observed around the call.  When a sister session changed the store in
    # the capture window, fall back to conservative net-diff validation so we
    # never attribute unrelated content to this tool call.
    if [token["content"] for token in working] == after:
        return planned

    added = Counter(content_digest(entry) for entry in after)
    added.subtract(content_digest(entry) for entry in before)
    removed = Counter(content_digest(entry) for entry in before)
    removed.subtract(content_digest(entry) for entry in after)
    committed: list[dict[str, str | None]] = []
    for change in planned:
        old_digest = change["old_digest"]
        new_digest = change["new_digest"]
        if old_digest == new_digest:
            continue
        if old_digest is not None and removed[old_digest] <= 0:
            continue
        if new_digest is not None and added[new_digest] <= 0:
            continue
        if old_digest is not None:
            removed[old_digest] -= 1
        if new_digest is not None:
            added[new_digest] -= 1
        committed.append(change)
    return committed


def _new_record(
    *,
    target: str,
    digest: str,
    source: Mapping[str, Any],
    confidence: str,
    current: datetime,
    review_days: int,
    expiry_days: int | None,
    supersedes_content_id: str | None,
) -> dict[str, Any]:
    created = _format_time(current)
    return {
        "id": f"mem_{uuid.uuid4().hex}",
        "target": target,
        "content_id": content_id(digest, is_digest=True),
        "content_sha256": digest,
        "status": "active",
        "source": dict(source),
        "terminal_source": None,
        "confidence": confidence,
        "scope": "profile",
        "created_at": created,
        "last_validated_at": created,
        "review_after": _format_time(current + timedelta(days=review_days)),
        "expires_at": (
            _format_time(current + timedelta(days=expiry_days))
            if expiry_days is not None
            else None
        ),
        "policy": {
            "review_interval_days": review_days,
            "expiry_interval_days": expiry_days,
        },
        "supersedes_content_id": supersedes_content_id,
        "superseded_by": None,
        "removed_at": None,
        "relevance": {"relevant": 0, "irrelevant": 0},
    }


def _build_source(metadata: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    source = {
        "origin": _enum_value(metadata.get("write_origin"), _ORIGINS, "other"),
        "context": _enum_value(metadata.get("execution_context"), _CONTEXTS, "other"),
        "platform": _enum_value(metadata.get("platform"), _PLATFORMS, "other"),
        "session_ref": None,
        "parent_session_ref": None,
        "task_ref": None,
        "tool_call_ref": None,
    }
    for source_key, metadata_key in (
        ("session_ref", "session_id"),
        ("parent_session_ref", "parent_session_id"),
        ("task_ref", "task_id"),
        ("tool_call_ref", "tool_call_id"),
    ):
        raw = metadata.get(metadata_key)
        if isinstance(raw, str) and 0 < len(raw.encode("utf-8")) <= 4096:
            digest = hmac.new(
                key,
                f"fabric-memory-governance/v1:{source_key}:{raw}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            source[source_key] = f"hmac-sha256:{digest}"
    return source


def _confidence(metadata: Mapping[str, Any]) -> str:
    return _enum_value(metadata.get("confidence"), _CONFIDENCE, "unspecified")


def _policy_days(
    metadata: Mapping[str, Any], field: str, default: int | None
) -> int | None:
    value = metadata.get(field, default)
    if value is None:
        return None
    if type(value) is not int or not (1 <= value <= _MAX_POLICY_DAYS):
        return default
    return value


def _enum_value(value: Any, allowed: frozenset[str], default: str) -> str:
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower()
    return normalized if normalized in allowed else default


def _active_records(
    records: Sequence[dict[str, Any]], target: str, digest: str
) -> list[dict[str, Any]]:
    return sorted(
        (
            record
            for record in records
            if record["target"] == target
            and record["content_sha256"] == digest
            and record["status"] == "active"
        ),
        key=lambda record: (record["created_at"], record["id"]),
    )


def _candidate_contradictions(target: str, entries: Sequence[str]) -> list[dict[str, Any]]:
    by_subject: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for entry in entries:
        match = _STRUCTURED_FACT_RE.fullmatch(entry)
        if not match:
            continue
        subject = " ".join(match.group(1).casefold().split())
        value = " ".join(match.group(2).casefold().split())
        by_subject[subject][value].add(content_digest(entry))
    findings: list[dict[str, Any]] = []
    for subject, values in sorted(by_subject.items()):
        if len(values) <= 1:
            continue
        digests = sorted({digest for group in values.values() for digest in group})
        findings.append(
            {
                "classification": "candidate_contradiction",
                "confidence": "candidate",
                "rule": "structured_key_value_mismatch",
                "target": target,
                "subject_sha256": hashlib.sha256(
                    f"structured-subject:{subject}".encode("utf-8")
                ).hexdigest(),
                "content_ids": [content_id(digest, is_digest=True) for digest in digests],
                "content_sha256": digests,
            }
        )
    return findings


def _record_deadline_view(record: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {
        "record_id": record["id"],
        "target": record["target"],
        "content_id": record["content_id"],
        "content_sha256": record["content_sha256"],
        "deadline": record[field],
    }


def _read_current_entries(home: Path) -> tuple[dict[str, list[str]], list[str]]:
    result = {"memory": [], "user": []}
    errors: list[str] = []
    for target, filename in (("memory", "MEMORY.md"), ("user", "USER.md")):
        path = Path(home) / "memories" / filename
        if not path.exists() and not path.is_symlink():
            continue
        try:
            raw = _read_regular_file(path, _MAX_MEMORY_FILE_BYTES).decode("utf-8")
            parts = raw.split("\n§\n")
            if len(parts) > _MAX_ENTRY_COUNT:
                raise MemoryGovernanceError("memory entry collection is out of bounds")
            result[target] = [entry.strip() for entry in parts if entry.strip()]
        except (MemoryGovernanceError, UnicodeError):
            errors.append(f"{filename}: unavailable_or_unsafe")
    return result, errors


def _bounded_entries(entries: Sequence[str]) -> list[str]:
    if isinstance(entries, (str, bytes)) or len(entries) > _MAX_ENTRY_COUNT:
        raise MemoryGovernanceError("memory entry collection is out of bounds")
    result: list[str] = []
    for entry in entries:
        if not isinstance(entry, str) or len(entry.encode("utf-8")) > _MAX_ENTRY_BYTES:
            raise MemoryGovernanceError("memory entry is out of bounds")
        normalized = entry.strip()
        if normalized:
            result.append(normalized)
    return result


def _parse_tool_result(value: str | Mapping[str, Any]) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str) or len(value.encode("utf-8")) > 64 * 1024:
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, UnicodeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _read_state(home: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with _state_lock(home, create=False) as governance:
            if governance is None:
                return _empty_state(), None
            return _load_state_locked(governance)
    except (MemoryGovernanceError, OSError) as exc:
        return None, str(exc)


def _load_state_locked(governance: Path) -> tuple[dict[str, Any], str | None]:
    path = governance / STATE_FILENAME
    if not path.exists() and not path.is_symlink():
        return _empty_state(), None
    try:
        _assert_single_link_regular(path, "memory governance state")
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        raw = _read_regular_file(path, _MAX_STATE_BYTES)
        parsed = json.loads(raw.decode("utf-8"))
        return _validate_state(parsed), None
    except (MemoryGovernanceError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return _empty_state(), f"memory governance sidecar is corrupt or unsafe: {type(exc).__name__}"


def _validate_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _STATE_KEYS:
        raise ValueError("state must use the closed v1 schema")
    if value.get("schema") != SCHEMA_ID:
        raise ValueError("unsupported memory governance schema")
    generation = value.get("generation")
    records = value.get("records")
    if type(generation) is not int or generation < 0:
        raise ValueError("generation must be non-negative")
    if not isinstance(records, list) or len(records) > _MAX_RECORDS:
        raise ValueError("records collection is out of bounds")
    validated = [_validate_record(record) for record in records]
    ids = [record["id"] for record in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("record ids must be unique")
    return {"schema": SCHEMA_ID, "generation": generation, "records": validated}


def _validate_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _RECORD_KEYS:
        raise ValueError("record must use the closed v1 schema")
    record = dict(value)
    if not isinstance(record["id"], str) or not _RECORD_ID_RE.fullmatch(record["id"]):
        raise ValueError("invalid record id")
    if record["target"] not in _TARGETS or record["status"] not in _STATUSES:
        raise ValueError("invalid record target or status")
    if not isinstance(record["content_id"], str) or not _CONTENT_ID_RE.fullmatch(record["content_id"]):
        raise ValueError("invalid content id")
    if not isinstance(record["content_sha256"], str) or not _DIGEST_RE.fullmatch(record["content_sha256"]):
        raise ValueError("invalid content digest")
    if record["content_id"] != content_id(record["content_sha256"], is_digest=True):
        raise ValueError("content id/digest mismatch")
    record["source"] = _validate_source(record["source"])
    if record["terminal_source"] is not None:
        record["terminal_source"] = _validate_source(record["terminal_source"])
    if record["confidence"] not in _CONFIDENCE or record["scope"] != "profile":
        raise ValueError("invalid confidence or scope")
    for field in ("created_at", "last_validated_at", "review_after"):
        _parse_time(record[field])
    for field in ("expires_at", "removed_at"):
        if record[field] is not None:
            _parse_time(record[field])
    policy = record["policy"]
    if not isinstance(policy, Mapping) or set(policy) != _POLICY_KEYS:
        raise ValueError("invalid policy")
    review_days = policy["review_interval_days"]
    expiry_days = policy["expiry_interval_days"]
    if type(review_days) is not int or not (1 <= review_days <= _MAX_POLICY_DAYS):
        raise ValueError("invalid review interval")
    if expiry_days is not None and (
        type(expiry_days) is not int or not (1 <= expiry_days <= _MAX_POLICY_DAYS)
    ):
        raise ValueError("invalid expiry interval")
    if (expiry_days is None) != (record["expires_at"] is None):
        raise ValueError("expiry policy/deadline mismatch")
    for field in ("supersedes_content_id",):
        if record[field] is not None and (
            not isinstance(record[field], str) or not _CONTENT_ID_RE.fullmatch(record[field])
        ):
            raise ValueError("invalid supersession content id")
    if record["superseded_by"] is not None and (
        not isinstance(record["superseded_by"], str)
        or not _RECORD_ID_RE.fullmatch(record["superseded_by"])
    ):
        raise ValueError("invalid superseded_by")
    if record["status"] == "active" and (
        record["terminal_source"] is not None
        or record["superseded_by"] is not None
        or record["removed_at"] is not None
    ):
        raise ValueError("active record has terminal fields")
    if record["status"] == "superseded" and (
        record["terminal_source"] is None
        or record["superseded_by"] is None
        or record["removed_at"] is not None
    ):
        raise ValueError("superseded record lacks terminal provenance")
    if record["status"] == "removed" and (
        record["terminal_source"] is None
        or record["removed_at"] is None
        or record["superseded_by"] is not None
    ):
        raise ValueError("removed record lacks terminal provenance")
    relevance = record["relevance"]
    if not isinstance(relevance, Mapping) or set(relevance) != _RELEVANCE_KEYS:
        raise ValueError("invalid relevance counters")
    for count in relevance.values():
        if type(count) is not int or not (0 <= count <= (1 << 63) - 1):
            raise ValueError("invalid relevance counter")
    record["policy"] = dict(policy)
    record["relevance"] = dict(relevance)
    return record


def _validate_source(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_KEYS:
        raise ValueError("source must use the closed v1 schema")
    source = dict(value)
    if source["origin"] not in _ORIGINS:
        raise ValueError("invalid source origin")
    if source["context"] not in _CONTEXTS:
        raise ValueError("invalid source context")
    if source["platform"] not in _PLATFORMS:
        raise ValueError("invalid source platform")
    for field in ("session_ref", "parent_session_ref", "task_ref", "tool_call_ref"):
        item = source[field]
        if item is not None and (
            not isinstance(item, str) or not _CONTEXT_REF_RE.fullmatch(item)
        ):
            raise ValueError("raw source correlation is forbidden")
    return source


def _empty_state() -> dict[str, Any]:
    return {"schema": SCHEMA_ID, "generation": 0, "records": []}


def _compact_records(state: dict[str, Any]) -> None:
    records = state["records"]
    if len(records) <= _MAX_RECORDS:
        return
    active = [record for record in records if record["status"] == "active"]
    if len(active) > _MAX_RECORDS:
        raise MemoryGovernanceError("active governance records exceed the safe bound")
    terminal = sorted(
        (record for record in records if record["status"] != "active"),
        key=lambda record: (record["removed_at"] or record["created_at"], record["id"]),
        reverse=True,
    )
    state["records"] = active + terminal[: _MAX_RECORDS - len(active)]


def _write_state_locked(governance: Path, state: Mapping[str, Any]) -> None:
    validated = _validate_state(state)
    encoded = json.dumps(
        validated,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_STATE_BYTES:
        raise MemoryGovernanceError("memory governance sidecar exceeds its size bound")
    path = governance / STATE_FILENAME
    _assert_not_symlink(path, "memory governance state")
    fd, tmp_name = tempfile.mkstemp(prefix=".memory-governance.", suffix=".tmp", dir=governance)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        _fsync_dir(governance)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _load_or_create_key_locked(governance: Path) -> bytes:
    path = governance / KEY_FILENAME
    if path.exists() or path.is_symlink():
        _assert_single_link_regular(path, "memory governance key")
        key = _read_regular_file(path, 32)
        if len(key) != 32:
            raise MemoryGovernanceError("memory governance key is corrupt")
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return key
    key = secrets.token_bytes(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    created: os.stat_result | None = None
    try:
        created = os.fstat(fd)
        _write_all(fd, key)
        os.fsync(fd)
    except BaseException:
        # A short write or interrupted fsync must not leave a permanently
        # corrupt key that prevents all future provenance writes.  Remove only
        # the exact inode this call created; never follow or unlink a swapped
        # path.
        try:
            linked = path.lstat()
            if (
                created is not None
                and stat.S_ISREG(linked.st_mode)
                and (linked.st_dev, linked.st_ino) == (created.st_dev, created.st_ino)
            ):
                path.unlink()
                _fsync_dir(governance)
        except OSError:
            pass
        raise
    finally:
        os.close(fd)
    _fsync_dir(governance)
    return key


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return b""
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise MemoryGovernanceError(f"unsafe file type: {path.name}")
    if info.st_size > max_bytes:
        raise MemoryGovernanceError(f"file exceeds safe bound: {path.name}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        current = os.fstat(fd)
        if not stat.S_ISREG(current.st_mode) or current.st_size > max_bytes:
            raise MemoryGovernanceError(f"unsafe file changed while opening: {path.name}")
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise MemoryGovernanceError(f"file changed while opening: {path.name}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise MemoryGovernanceError(f"file exceeds safe bound: {path.name}")
        try:
            after = path.lstat()
        except FileNotFoundError as exc:
            raise MemoryGovernanceError(f"file changed while reading: {path.name}") from exc
        if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
            raise MemoryGovernanceError(f"file changed while reading: {path.name}")
        return data
    finally:
        os.close(fd)


def _governance_path(home: Path) -> Path:
    return Path(home) / "memories" / ".governance"


@contextmanager
def _state_lock(home: Path, *, create: bool):
    governance = _governance_path(home)
    memories = governance.parent
    with _PROCESS_LOCK:
        if create:
            _ensure_safe_directory(memories, mode=0o700)
            _ensure_safe_directory(governance, mode=0o700)
        elif not governance.exists() and not governance.is_symlink():
            yield None
            return
        else:
            _assert_safe_directory(memories, "memory directory")
            _assert_safe_directory(governance, "memory governance directory")
            try:
                governance.chmod(0o700)
            except OSError:
                pass

        lock_path = governance / ".lock"
        before = None
        try:
            before = lock_path.lstat()
        except FileNotFoundError:
            pass
        if before is not None and (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            raise MemoryGovernanceError("memory governance lock is unsafe")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            fd = os.open(lock_path, flags, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            raise MemoryGovernanceError("cannot open memory governance lock safely") from exc
        try:
            opened = os.fstat(fd)
            try:
                linked = lock_path.lstat()
            except FileNotFoundError as exc:
                raise MemoryGovernanceError("memory governance lock changed while opening") from exc
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or stat.S_ISLNK(linked.st_mode)
                or not stat.S_ISREG(linked.st_mode)
                or linked.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
                or (
                    before is not None
                    and (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                )
            ):
                raise MemoryGovernanceError("memory governance lock changed while opening")
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            if opened.st_size == 0:
                _write_all(fd, b"\0")
                os.fsync(fd)
                os.lseek(fd, 0, os.SEEK_SET)
            _lock_fd(fd)
            # Locking the wrong, just-replaced inode would provide no mutual
            # exclusion for path-based state updates.  Recheck after flock.
            linked_after_lock = lock_path.lstat()
            if (opened.st_dev, opened.st_ino) != (
                linked_after_lock.st_dev,
                linked_after_lock.st_ino,
            ):
                raise MemoryGovernanceError("memory governance lock changed while locking")
            yield governance
        finally:
            _unlock_fd(fd)
            os.close(fd)


def _ensure_safe_directory(path: Path, *, mode: int) -> None:
    if path.exists() or path.is_symlink():
        _assert_safe_directory(path, path.name or "directory")
    else:
        try:
            path.mkdir(parents=True, mode=mode, exist_ok=False)
        except FileExistsError:
            _assert_safe_directory(path, path.name or "directory")
    try:
        path.chmod(mode)
    except OSError:
        pass


def _assert_safe_directory(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise MemoryGovernanceError(f"{label} is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise MemoryGovernanceError(f"{label} is unsafe")


def _assert_not_symlink(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise MemoryGovernanceError(f"{label} is unsafe")


def _assert_single_link_regular(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise MemoryGovernanceError(f"{label} is missing") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
    ):
        raise MemoryGovernanceError(f"{label} is unsafe")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = os.write(fd, view[written:])
        if count <= 0:
            raise MemoryGovernanceError("short write while creating governance key")
        written += count


def _lock_fd(fd: int) -> None:
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    except ImportError:
        pass
    try:
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    except ImportError:
        pass


def _unlock_fd(fd: int) -> None:
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    except (ImportError, OSError):
        pass
    try:
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError):
        pass


def _fsync_dir(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _coerce_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("governance timestamps must be timezone-aware")
    return current.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return _coerce_now(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 32 or not value.endswith("Z"):
        raise ValueError("invalid governance timestamp")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("governance timestamp is not UTC")
    return parsed


__all__ = [
    "AUDIT_SCHEMA_ID",
    "EXPIRED_PLACEHOLDER",
    "SCHEMA_ID",
    "MemoryGovernanceError",
    "apply_expiry_decisions",
    "audit_memory",
    "capture_expiry_decisions",
    "content_digest",
    "content_id",
    "format_audit_report",
    "has_governance_state",
    "record_committed_write",
    "record_committed_write_best_effort",
    "record_relevance_label",
    "reset_governance",
    "revalidate_record",
]
