#!/usr/bin/env python3
"""Write-approval gate + pending store for memory and skill writes.

Background
----------
The agent writes to two persistent stores that survive across sessions:

  * **memory** — MEMORY.md / USER.md, small (~200 char) declarative entries
  * **skills** — SKILL.md + supporting files, potentially huge (10-100 KB)

The stores can be written from three relevant origins:

  * **foreground** — a normal agent turn (user is present / chatting)
  * **background_review** — the self-improvement review fork that runs after a
    turn and autonomously decides what to save (the source of the
    "wrong assumptions" users complained about)
  * **learn_request / learn_followup** — an explicit ``/learn`` turn and its
    immediate continuation, both authoring quarantined reusable-skill drafts

This module lets the user gate those writes per-subsystem with a boolean
``write_approval``:

  * ``false`` (default) — foreground writes freely (the pre-gate behaviour)
  * ``true``            — require approval: do not commit the write; either
    prompt inline (memory, interactive CLI only) or **stage** it to a pending
    store and surface it for the user to approve or reject out-of-band

The size asymmetry between memory and skills is real and unavoidable: a memory
entry can be reviewed inline in a chat bubble; a 100 KB SKILL.md cannot. So
the gate stages BOTH to disk, but review affordances differ by subsystem
(see ``fabric_cli`` slash handlers): memory shows full content, skills show
metadata + a one-line gist + a ``diff`` escape hatch (CLI/dashboard/file).

Staging is mandatory for background-review and ``/learn`` skill writes,
regardless of the legacy opt-in gate: these are authored candidates, not
active-library mutations. It is also mandatory for gated background memory
writes (a daemon thread cannot block on an interactive prompt) and for gated
gateway sessions (no inline prompt channel — review happens via
``/memory pending``). Foreground CLI memory writes prompt inline via the
dangerous-command approval callback; gated foreground skill writes always
stage (too big to eyeball mid-loop).

Pending records live under ``<FABRIC_HOME>/pending/{memory,skills}/<id>.json``
so they survive process restarts and can be reviewed from CLI, gateway, or the
web dashboard.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from fabric_constants import get_fabric_home

logger = logging.getLogger(__name__)

# Subsystem identifiers
MEMORY = "memory"
SKILLS = "skills"
_SUBSYSTEMS = (MEMORY, SKILLS)
_PENDING_ID_RE = re.compile(r"^(?:[0-9a-f]{8}|[0-9a-f]{32})$")
_PENDING_BATCH_ID_RE = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{64})$")
_MAX_PENDING_RECORD_BYTES = 2 * 1024 * 1024

# Config key (per subsystem). A single boolean: the optional approval gate is
# OFF by default for ordinary foreground writes, and ON means stage / prompt
# every write for the user's approval. Governed skill-authoring origins are
# quarantined independently of this preference. There is intentionally no
# third "block all writes" state — to disable a subsystem entirely use its own
# enable flag (e.g. ``memory.memory_enabled: false``).
CONFIG_KEY = "write_approval"


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def write_approval_enabled(subsystem: str) -> bool:
    """Return whether the approval gate is enabled for ``subsystem``.

    Reads ``<subsystem>.write_approval`` from config.yaml. Defaults to
    ``False`` (gate off — writes flow freely) for any unset / invalid value so
    existing installs keep their current behaviour until the user opts in.
    """
    if subsystem not in _SUBSYSTEMS:
        return False
    try:
        from fabric_cli.config import load_config, cfg_get
        cfg = load_config()
        raw = cfg_get(cfg, subsystem, CONFIG_KEY, default=False)
    except Exception:
        return False
    return _normalize_enabled(raw)


def _normalize_enabled(value: Any) -> bool:
    """Coerce a config value to a bool. Default (unknown) is False (gate off).

    Accepts real bools and the usual truthy/falsey strings. YAML 1.1 parses
    bare ``on``/``off``/``yes``/``no`` as bools already, so the string branch
    is mostly for hand-edited configs.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"on", "true", "yes", "1", "approve", "enabled"}
    return False


# ---------------------------------------------------------------------------
# Pending store (file-backed)
# ---------------------------------------------------------------------------

def _validate_subsystem(subsystem: str) -> str:
    """Return a canonical pending subsystem or raise ``ValueError``.

    Pending paths are an authority boundary: accepting an arbitrary directory
    component here turns every get/discard operation into a profile-relative
    file primitive.  Keep the accepted universe deliberately closed.
    """
    if subsystem not in _SUBSYSTEMS:
        raise ValueError(f"Unsupported pending subsystem: {subsystem!r}")
    return subsystem


def is_valid_pending_id(pending_id: object) -> bool:
    """Whether *pending_id* is a current 128-bit id or legacy 8-hex id."""
    return isinstance(pending_id, str) and _PENDING_ID_RE.fullmatch(pending_id) is not None


def is_valid_pending_batch_id(batch_id: object) -> bool:
    """Whether *batch_id* is a supported UUID/hash batch identifier."""
    return (
        isinstance(batch_id, str)
        and _PENDING_BATCH_ID_RE.fullmatch(batch_id) is not None
    )


def _fsync_directory(path: Path) -> None:
    """Persist directory-entry changes where the platform exposes directory fsync."""
    if os.name == "nt":  # Windows does not support opening directories via os.open.
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _pending_dir(subsystem: str) -> Path:
    return get_fabric_home() / "pending" / _validate_subsystem(subsystem)


def _safe_pending_dir(subsystem: str, *, create: bool) -> Optional[Path]:
    """Return the canonical pending directory, refusing redirected components."""
    directory = _pending_dir(subsystem)
    home = get_fabric_home().resolve(strict=False)
    pending_root = home / "pending"
    try:
        if create:
            home_existed = home.exists()
            pending_root_existed = pending_root.exists()
            directory_existed = directory.exists()
            pending_root.mkdir(parents=True, exist_ok=True)
            directory.mkdir(parents=True, exist_ok=True)
            if not home_existed:
                _fsync_directory(home.parent)
            if not pending_root_existed:
                _fsync_directory(pending_root.parent)
            if not directory_existed:
                _fsync_directory(directory.parent)
        for component in (pending_root, directory):
            if component.exists():
                info = component.lstat()
                if not stat.S_ISDIR(info.st_mode) or component.is_symlink():
                    return None
        resolved = directory.resolve(strict=False)
    except OSError:
        return None
    if resolved != pending_root / subsystem:
        return None
    return directory


def _pending_path(subsystem: str, pending_id: object) -> Optional[Path]:
    """Resolve one pending JSON path without permitting traversal/redirects."""
    if not is_valid_pending_id(pending_id):
        return None
    directory = _safe_pending_dir(subsystem, create=False)
    if directory is None:
        return None
    try:
        resolved_dir = directory.resolve(strict=False)
        candidate = (directory / f"{pending_id}.json").resolve(strict=False)
    except OSError:
        return None
    if candidate.parent != resolved_dir:
        return None
    return candidate


@contextmanager
def _pending_operation(subsystem: str) -> Iterator[None]:
    """Serialize skill-draft operations and recover interrupted promotions.

    Memory approvals retain their existing lightweight store. Skill drafts,
    however, participate in the same writer lock as active skill mutations so
    membership cannot change between review, claim, approval, and rejection.
    The manager import is deliberately lazy to keep this low-level module free
    of an import cycle during process startup.
    """
    _validate_subsystem(subsystem)
    if subsystem != SKILLS:
        yield
        return

    from tools.skill_mutation import skill_mutation_lock
    from tools.skill_manager_tool import (
        _skills_dir,
        recover_skill_pending_transactions,
    )

    with skill_mutation_lock(_skills_dir().parent):
        if _safe_pending_dir(SKILLS, create=False) is None:
            # The raw CRUD helpers will fail closed without following the
            # redirected store. Recovery cannot safely inspect it either.
            yield
            return
        recover_skill_pending_transactions(_lock_held=True)
        yield


def _is_regular_pending_file(path: Path) -> bool:
    """Require an existing, non-symlink regular file for pending reads/deletes."""
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not path.is_symlink()


def _read_pending_record(
    path: Path,
    *,
    subsystem: str,
    pending_id: str,
) -> Optional[Dict[str, Any]]:
    try:
        before = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        return None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or opened.st_size > _MAX_PENDING_RECORD_BYTES
            ):
                return None
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                fd = -1
                record = json.load(handle)
        finally:
            if fd >= 0:
                os.close(fd)
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    if record.get("id") != pending_id or record.get("subsystem") != subsystem:
        return None
    return record


def _stage_write_unlocked(subsystem: str, payload: Dict[str, Any],
                          *, summary: str, origin: str,
                          batch_id: Optional[str] = None,
                          ordinal: Optional[int] = None,
                          precondition: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Persist a pending write and return a short record describing it.

    Args:
        subsystem: ``memory`` or ``skills``.
        payload: the exact kwargs needed to replay the write when approved
            (e.g. ``{"action": "add", "target": "user", "content": "..."}``
            for memory, or the full ``skill_manage`` kwargs for skills).
        summary: a one-line human-readable description shown in pending lists.
            For skills this is the LLM/heuristic gist; for memory it can be the
            entry text itself.
        origin: ``foreground``, ``background_review``, ``learn_request``, or
            ``learn_followup`` — recorded for audit.

    Returns a dict with ``id`` and metadata plus the internal ``_persisted``
    result flag. On disk failure it logs and returns ``_persisted=False`` so a
    governed caller can fail closed; nothing is silently committed.
    """
    _validate_subsystem(subsystem)
    if not isinstance(payload, dict):
        raise ValueError("Pending payload must be a mapping")
    if subsystem == SKILLS and batch_id is not None and not is_valid_pending_batch_id(batch_id):
        raise ValueError("Invalid pending skill batch id")
    pid = uuid.uuid4().hex
    record = {
        "id": pid,
        "subsystem": subsystem,
        "action": payload.get("action", ""),
        "summary": (summary or "").strip(),
        "origin": origin or "foreground",
        "created_at": time.time(),
        "payload": payload,
    }
    if subsystem == SKILLS:
        # Pending skill records are the on-disk quarantine. They deliberately
        # live outside ``skills/`` so discovery and the cached skill index can
        # never treat an unapproved candidate as active guidance.
        record["lifecycle"] = "draft"
        if batch_id:
            record["batch_id"] = batch_id
        if ordinal is not None:
            record["ordinal"] = ordinal
        if precondition is not None:
            record["precondition"] = precondition
    tmp: Optional[Path] = None
    linked_path: Optional[Path] = None
    try:
        d = _safe_pending_dir(subsystem, create=True)
        if d is None:
            raise OSError("pending directory is redirected or unsafe")
        serialized = json.dumps(record, ensure_ascii=False, indent=2)
        # Creation is exclusive: even a forced RNG collision can never
        # overwrite another pending decision or its audit context. Readers
        # continue to accept the historical 8-hex ids.
        for _attempt in range(32):
            path = d / f"{pid}.json"
            if path.exists() or path.is_symlink():
                pid = uuid.uuid4().hex
                record["id"] = pid
                serialized = json.dumps(record, ensure_ascii=False, indent=2)
                continue
            tmp = d / f".{pid}.{uuid.uuid4().hex}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(tmp, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            publish_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                publish_fd = os.open(path, publish_flags, 0o600)
            except FileExistsError:
                tmp.unlink(missing_ok=True)
                pid = uuid.uuid4().hex
                record["id"] = pid
                serialized = json.dumps(record, ensure_ascii=False, indent=2)
                continue
            else:
                os.close(publish_fd)
            linked_path = path
            # The O_EXCL reservation is the collision-safe publish claim;
            # replace atomically swaps the complete temp record into that
            # uniquely owned name on filesystems without hard-link support.
            os.replace(tmp, path)
            _fsync_directory(d)
            tmp.unlink(missing_ok=True)
            linked_path = None
            break
        else:  # pragma: no cover - requires a broken/colliding RNG
            raise OSError("could not allocate a unique pending id")
        record["_persisted"] = True
    except Exception as e:  # pragma: no cover - disk failure path
        logger.error("Failed to stage pending %s write: %s", subsystem, e, exc_info=True)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        if linked_path is not None:
            try:
                linked_path.unlink(missing_ok=True)
            except OSError:
                pass
        record["_persisted"] = False
        record["_persistence_error"] = str(e)
    return record


def stage_write(subsystem: str, payload: Dict[str, Any],
                *, summary: str, origin: str,
                batch_id: Optional[str] = None,
                ordinal: Optional[int] = None,
                precondition: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Persist a pending write under the subsystem's serialization boundary."""
    with _pending_operation(subsystem):
        record = _stage_write_unlocked(
            subsystem,
            payload,
            summary=summary,
            origin=origin,
            batch_id=batch_id,
            ordinal=ordinal,
            precondition=precondition,
        )
        if (
            subsystem == SKILLS
            and record.get("_persisted") is True
            and isinstance(batch_id, str)
        ):
            try:
                from tools.skill_manager_tool import _invalidate_skill_batch_review

                _invalidate_skill_batch_review(batch_id)
            except Exception as exc:
                # A newly appended action must never leave an older review
                # attestation valid. If invalidation cannot be made durable,
                # retract the append and fail closed.
                _discard_pending_unlocked(subsystem, str(record["id"]))
                record["_persisted"] = False
                record["_persistence_error"] = (
                    f"could not invalidate prior batch review: {exc}"
                )
        return record


def _list_pending_unlocked(subsystem: str) -> List[Dict[str, Any]]:
    """Return all pending records for ``subsystem``, oldest first."""
    d = _safe_pending_dir(subsystem, create=False)
    if d is None or not d.exists():
        return []
    records: List[Dict[str, Any]] = []
    for p in d.glob("*.json"):
        pending_id = p.stem
        if not is_valid_pending_id(pending_id):
            logger.warning("Skipping invalid pending filename: %s", p)
            continue
        record = _read_pending_record(
            p,
            subsystem=subsystem,
            pending_id=pending_id,
        )
        if record is None:
            logger.warning("Skipping unsafe or unreadable pending record: %s", p)
            continue
        records.append(record)
    records.sort(key=lambda r: r.get("created_at", 0))
    return records


def list_pending(subsystem: str) -> List[Dict[str, Any]]:
    """Return pending records after recovering any interrupted skill promotion."""
    with _pending_operation(subsystem):
        return _list_pending_unlocked(subsystem)


def _get_pending_unlocked(subsystem: str, pending_id: str) -> Optional[Dict[str, Any]]:
    """Return a single pending record by id, or None."""
    path = _pending_path(subsystem, pending_id)
    if path is None:
        return None
    return _read_pending_record(path, subsystem=subsystem, pending_id=pending_id)


def get_pending(subsystem: str, pending_id: str) -> Optional[Dict[str, Any]]:
    """Return one pending record after interrupted skill work is recovered."""
    with _pending_operation(subsystem):
        return _get_pending_unlocked(subsystem, pending_id)


def _discard_pending_unlocked(subsystem: str, pending_id: str) -> bool:
    """Delete a pending record. Returns True if it existed."""
    path = _pending_path(subsystem, pending_id)
    if path is None or not _is_regular_pending_file(path):
        return False
    try:
        path.unlink()
        _fsync_directory(path.parent)
        return True
    except Exception as e:  # pragma: no cover
        logger.error("Failed to discard pending %s/%s: %s", subsystem, pending_id, e)
    return False


def discard_pending(subsystem: str, pending_id: str) -> bool:
    """Delete one pending record under the subsystem serialization boundary."""
    with _pending_operation(subsystem):
        record = _get_pending_unlocked(subsystem, pending_id)
        removed = _discard_pending_unlocked(subsystem, pending_id)
        if removed and subsystem == SKILLS and record is not None:
            batch_id = record.get("batch_id")
            if is_valid_pending_batch_id(batch_id):
                from tools.skill_manager_tool import _invalidate_skill_batch_review

                _invalidate_skill_batch_review(batch_id)
        return removed


def pending_count(subsystem: str) -> int:
    """Cheap count of pending records (for notification badges)."""
    return len(list_pending(subsystem))


# ---------------------------------------------------------------------------
# Write origin
# ---------------------------------------------------------------------------

def current_origin(*, fail_closed: bool = False) -> str:
    """Return the active provenance label for the current write.

    Reuses the skill-provenance ContextVar. Autonomous review/curation and
    explicit ``/learn`` turns set governed origins there; ordinary agent turns
    leave it at the default ``foreground``.
    """
    try:
        from tools.skill_provenance import get_current_write_origin
        return get_current_write_origin()
    except Exception:
        # Most legacy memory callers retain the historical foreground fallback.
        # Skill mutation passes ``fail_closed=True`` because provenance is an
        # authority boundary: a partial install must never downgrade a
        # quarantined /learn or background-review write to foreground.
        return "__provenance_unavailable__" if fail_closed else "foreground"


def is_background() -> bool:
    return current_origin() == "background_review"


# ---------------------------------------------------------------------------
# Gate decision
# ---------------------------------------------------------------------------

class GateDecision:
    """Result of evaluating the write gate for a single write attempt.

    Exactly one of the boolean flags is True:
      * ``allow``  — proceed with the real write (gate off, or an inline
        approval was granted).
      * ``blocked`` — refuse the write (the user denied an inline approval
        prompt). ``message`` explains why; surface it to the agent.
      * ``stage``  — do not write; the caller should stage the payload via
        ``stage_write`` (a governed skill-authoring origin, or the gate is on
        and no inline prompt is available). ``message`` is the user-facing
        "staged for approval" note.
    """

    __slots__ = ("allow", "blocked", "stage", "message")

    def __init__(self, *, allow=False, blocked=False, stage=False, message=""):
        self.allow = allow
        self.blocked = blocked
        self.stage = stage
        self.message = message


def evaluate_gate(subsystem: str, *, inline_summary: str = "",
                  inline_detail: str = "") -> GateDecision:
    """Decide what to do with a pending write for ``subsystem``.

    Args:
        subsystem: ``memory`` or ``skills``.
        inline_summary: short description used as the inline approval prompt
            header (memory foreground path only).
        inline_detail: full content shown in the inline prompt (memory entries
            are small; skills never take the inline path).

    Decision matrix:
        background-review or /learn skill     → stage (gate-independent)
        gate off, other origin (default)      → allow (writes flow freely)
        gate on, memory + interactive CLI     → inline approve/deny prompt
        gate on, memory + gateway/script/bg   → stage
        gate on, skills (any origin)          → stage (too big to review inline)

    Note: there is no config-driven "blocked" outcome — the gate only ever
    delays a write for approval, never silently refuses it. ``blocked`` is
    still produced when the user *actively denies* an inline prompt.
    """
    origin = current_origin()

    # Autonomous reviews and explicit /learn turns always author quarantined
    # candidates. This safety boundary is independent of the legacy
    # ``skills.write_approval`` opt-in so neither path can mutate the active
    # tree before a user reviews and promotes the draft.
    if subsystem == SKILLS:
        try:
            from tools.skill_provenance import is_quarantined_skill_origin

            quarantined = is_quarantined_skill_origin(origin)
        except Exception:
            # Provenance is an authority boundary. A partial install/upgrade
            # must stage, not silently grant active-library mutation.
            quarantined = True
        if quarantined:
            return GateDecision(
                stage=True,
                message=(
                    "Saved as a quarantined skill draft. The active skill "
                    "library was not changed — review with /skills diff <id>, "
                    "then promote with /skills approve <id> or reject with "
                    "/skills reject <id>."
                ),
            )

    if not write_approval_enabled(subsystem):
        return GateDecision(allow=True)

    background = origin == "background_review"

    # Skills always stage — a SKILL.md is too large to review inline, and a
    # background skill write happens in a daemon thread with no user present.
    if subsystem == SKILLS or background:
        where = "/skills pending" if subsystem == SKILLS else "/memory pending"
        return GateDecision(
            stage=True,
            message=(
                f"Staged for approval ({subsystem}.write_approval is on). "
                f"Not yet saved — review with {where}."
            ),
        )

    # Memory + foreground: if an interactive approval channel exists (a CLI
    # approval callback registered on this thread), prompt inline — entries
    # are small enough to show in full. Otherwise (gateway, script, batch,
    # no listener) stage instead of forcing a blind deny.
    if _interactive_approval_available():
        granted = _prompt_inline_memory_approval(inline_summary, inline_detail)
        if granted is True:
            return GateDecision(allow=True)
        if granted is False:
            return GateDecision(
                blocked=True,
                message="Memory write denied by user. The change was not saved.",
            )
        # granted is None → prompt failed; fall through to staging.

    return GateDecision(
        stage=True,
        message=(
            "Staged for approval (memory.write_approval is on). "
            "Not yet saved — review with /memory pending."
        ),
    )


def _interactive_approval_available() -> bool:
    """True when a foreground memory write can be approved inline.

    Inline prompting requires a per-thread approval callback registered by the
    interactive CLI (``tools.terminal_tool.set_approval_callback``). Every
    other surface stages instead:

    * **Gateway/API sessions** — the dangerous-command ``/approve`` round-trip
      lives in the pending-approval queue (``submit_pending`` +
      ``_await_gateway_decision``), which ``prompt_dangerous_approval`` never
      reaches; trying to prompt from a gateway session would hit the
      ``input()`` fallback and silently deny. Staging gives the user a real
      review affordance (``/memory pending``) instead.
    * Scripts, cron, and background threads — no user present.
    """
    try:
        from tools.terminal_tool import _get_approval_callback
        return _get_approval_callback() is not None
    except Exception:
        return False


def _prompt_inline_memory_approval(summary: str, detail: str) -> Optional[bool]:
    """Prompt the user inline to approve a memory write.

    Returns True (approved), False (denied), or None (no interactive prompt
    available / prompt failed → caller should stage instead).

    Reuses the per-thread CLI approval callback registered for dangerous
    commands (``tools.terminal_tool.set_approval_callback``). The callback is
    invoked directly — NOT via ``prompt_dangerous_approval`` — because that
    wrapper falls back to ``input()`` (deadlock-prone under prompt_toolkit,
    see #15216) and converts callback errors into a silent deny; here a
    failed prompt must stage the write instead.
    """
    try:
        from tools.terminal_tool import _get_approval_callback
    except Exception:
        return None

    callback = _get_approval_callback()
    if callback is None:
        # No interactive channel on this thread — stage rather than risk the
        # input() fallback (deadlock under prompt_toolkit, EOF-deny in tests).
        return None

    header = summary.strip() or "Save to memory?"
    body = detail.strip()
    description = f"Save to memory: {header}"
    command = body if body else header
    # Invoke the callback directly instead of via prompt_dangerous_approval:
    # that wrapper swallows callback exceptions into "deny", which would
    # silently refuse the write. Direct invocation lets a crashed prompt fall
    # back to staging (the gate only ever delays a write, never drops it).
    try:
        choice = callback(command, description, allow_permanent=False)
    except Exception as e:
        logger.error("Inline memory approval prompt failed: %s", e)
        return None

    if choice in {"once", "session"}:
        return True
    if choice == "deny":
        return False
    # Any other outcome (e.g. timeout that returns "deny" already handled) →
    # treat unknown as no-decision so we stage rather than silently drop.
    return None


# ---------------------------------------------------------------------------
# Skill-specific helpers (gist + diff for the review affordances)
# ---------------------------------------------------------------------------

def skill_gist(action: str, name: str, *, content: str = "",
               file_path: str = "", old_string: str = "",
               new_string: str = "") -> str:
    """Build a one-line human gist for a pending skill write.

    Heuristic, no model call — the gist surfaces enough to decide approve/reject
    in a chat bubble, while the full diff stays behind /skills diff (CLI/
    dashboard/file). For create/edit it pulls the frontmatter ``description:``;
    for patch/write_file it describes the size of the change.
    """
    if action in {"create", "edit"} and content:
        desc = _frontmatter_description(content)
        size = f"{len(content) // 1024 + 1} KB" if len(content) >= 1024 else f"{len(content)} chars"
        verb = "create" if action == "create" else "rewrite"
        if desc:
            return f"{verb} '{name}' — {desc} ({size})"
        return f"{verb} '{name}' ({size})"
    if action == "patch":
        target = file_path or "SKILL.md"
        removed = old_string.count("\n") + 1 if old_string else 0
        added = new_string.count("\n") + 1 if new_string else 0
        return f"patch '{name}' {target} (+{added}/-{removed} lines)"
    if action == "write_file":
        return f"write {file_path} in '{name}'"
    if action == "remove_file":
        return f"remove {file_path} from '{name}'"
    if action == "delete":
        return f"delete skill '{name}'"
    return f"{action} '{name}'"


def _frontmatter_description(content: str) -> str:
    """Extract the ``description:`` value from SKILL.md YAML frontmatter."""
    import re
    m = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
    if not m:
        return ""
    desc = m.group(1).strip().strip("'\"")
    return desc[:140]


def skill_pending_diff(record: Dict[str, Any]) -> str:
    """Build a full unified diff (or full content) for a staged skill write.

    Used by /skills diff <id> on a surface that can render it (CLI pager, web
    dashboard, or by opening the pending JSON file). For create this is the new
    file content; for edit/patch it is a unified diff against the current
    on-disk skill.
    """
    from tools.skill_manager_tool import preview_skill_pending_record

    batch_id = record.get("batch_id")
    if batch_id:
        related = [
            candidate
            for candidate in list_pending(SKILLS)
            if candidate.get("batch_id") == batch_id
        ]
    else:
        related = [record]
    return preview_skill_pending_record(record, related)
