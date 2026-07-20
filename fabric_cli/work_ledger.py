"""Durable, profile-scoped Job and Attention state for Fabric's edge clients.

``work.db`` is deliberately independent from ``state.db`` and ``kanban.db``:
its event-heavy workload must not extend the session store's FTS write locks,
and its rows are profile-private history rather than a cross-profile queue.

Only bounded, already-redacted public data belongs here.  In particular, this
module never accepts a background prompt or a clarify/sudo/secret response.
Those values remain in the creator process and session transcript.  The two
request-hash helpers below accept only the reviewed non-sensitive envelopes,
which makes that privacy rule structural rather than caller convention.

Job transitions (``JOB_TRANSITIONS`` is the executable authority)::

    queued -> claimed -> running <-> waiting_attention -> succeeded | failed
       |         |          |              |
       +---------+----------+--------------+--> cancel_requested -> cancelled
       +---------+----------+--------------+--> interrupted

``claimed -> failed`` is the one explicit operational edge not shown by the
compact diagram: it records a scheduler/runner start failure after admission.

Attention transitions (``ATTENTION_TRANSITIONS`` is the authority)::

    pending -> resolving -> resolved | denied
       |            `----> orphaned (delivery outcome unknown)
       +----> expired | cancelled | orphaned

No transition leaves a terminal state.  Every subject version change and its
self-contained public after-state (or tombstone) event commit in the same
``BEGIN IMMEDIATE`` transaction.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import math
import os
import random
import re
import sqlite3
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar


# ``FWK1`` in big-endian ASCII.  Keep stable forever: backup/doctor/import use
# it to distinguish this ledger from another valid SQLite database.
WORK_APPLICATION_ID = 0x46574B31
# Schema v2 adds a deterministic expression index used exclusively by bounded
# retention.  v1 stores migrate in-place during first open; no public row or
# event shape changes.
WORK_SCHEMA_VERSION = 2
_WORK_SCHEMA_V1 = 1
WORK_DB_FILENAME = "work.db"

PUBLIC_JSON_MAX_BYTES = 32 * 1024
DETAIL_JSON_MAX_BYTES = 256 * 1024
SYNC_MAX_BYTES = 1024 * 1024
JOB_RESULT_PREVIEW_MAX_BYTES = 4 * 1024
JOB_ERROR_PREVIEW_MAX_BYTES = 8 * 1024
DEFAULT_RETENTION_SECONDS = 30 * 24 * 60 * 60
DEFAULT_RETENTION_SUBJECT_BATCH_SIZE = 100
DEFAULT_BUSY_TIMEOUT_MS = 100
DEFAULT_WRITE_DEADLINE_SECONDS = 5.0
DEFAULT_INIT_DEADLINE_SECONDS = 10.0
_RETRY_MIN_SECONDS = 0.020
_RETRY_MAX_SECONDS = 0.150

_SQLITE_HEADER = b"SQLite format 3\x00"
_ID_RE = re.compile(r"^(?P<prefix>job|run|attn|mut|ledger)_[0-9a-f]{32}$")
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,511}$")

JOB_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
JOB_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "queued": frozenset({"claimed", "cancel_requested", "interrupted"}),
    "claimed": frozenset({"running", "failed", "cancel_requested", "interrupted"}),
    "running": frozenset(
        {"waiting_attention", "succeeded", "failed", "cancel_requested", "interrupted"}
    ),
    "waiting_attention": frozenset(
        {"running", "succeeded", "failed", "cancel_requested", "interrupted"}
    ),
    "cancel_requested": frozenset({"cancelled", "interrupted"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "interrupted": frozenset(),
}

ATTENTION_TERMINAL_STATES = frozenset(
    {"resolved", "denied", "expired", "cancelled", "orphaned"}
)
ATTENTION_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "pending": frozenset({"resolving", "expired", "cancelled", "orphaned"}),
    "resolving": frozenset({"resolved", "denied", "orphaned"}),
    "resolved": frozenset(),
    "denied": frozenset(),
    "expired": frozenset(),
    "cancelled": frozenset(),
    "orphaned": frozenset(),
}

# This is the single executable authority for response actions.  The value is
# the successful terminal state that a claimed action is allowed to produce;
# ``orphaned`` remains the action-independent fail-closed outcome when waiter
# delivery cannot be proved.  Keep create validation, public allowed-actions,
# request hashing, and resolution finalization derived from this table.
ATTENTION_ACTION_OUTCOMES: Mapping[str, Mapping[str, str]] = {
    "approval": {
        "once": "resolved",
        "session": "resolved",
        "always": "resolved",
        "deny": "denied",
    },
    "clarify": {"submit": "resolved", "cancel": "denied"},
    "sudo": {"submit": "resolved", "cancel": "denied"},
    "secret": {"submit": "resolved", "cancel": "denied"},
}

IDEMPOTENCY_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "reserved": frozenset({"delivering", "finalized", "failed", "uncertain"}),
    "delivering": frozenset({"finalized", "failed", "uncertain"}),
    "finalized": frozenset(),
    "failed": frozenset(),
    "uncertain": frozenset(),
}


SCHEMA_TABLE_SQL: Mapping[str, str] = {
    "work_meta": """
        CREATE TABLE work_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """,
    "jobs": """
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            source TEXT NOT NULL,
            source_session_key TEXT,
            runtime_session_id TEXT,
            prompt_preview TEXT,
            current_run_id TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            runtime_summary_json TEXT NOT NULL,
            result_json TEXT,
            result_omitted_reason TEXT,
            error_json TEXT,
            open_attention_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            started_at REAL,
            updated_at REAL NOT NULL,
            finished_at REAL,
            cancel_requested_at REAL
        )
    """,
    "job_runs": """
        CREATE TABLE job_runs (
            run_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL,
            runtime_json TEXT NOT NULL,
            owner_boot_token TEXT NOT NULL,
            owner_pid INTEGER NOT NULL,
            owner_start_token TEXT NOT NULL,
            owner_generation TEXT NOT NULL,
            claim_token TEXT,
            claimed_at REAL,
            started_at REAL,
            updated_at REAL NOT NULL,
            finished_at REAL,
            result_json TEXT,
            error_json TEXT,
            UNIQUE(job_id, attempt)
        )
    """,
    "attention_items": """
        CREATE TABLE attention_items (
            attention_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            job_id TEXT,
            run_id TEXT,
            source_session_key TEXT NOT NULL,
            runtime_session_id TEXT,
            request_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            blocking INTEGER NOT NULL,
            sensitive INTEGER NOT NULL,
            title TEXT NOT NULL,
            public_payload_json TEXT NOT NULL,
            owner_boot_token TEXT NOT NULL,
            owner_pid INTEGER NOT NULL,
            owner_start_token TEXT NOT NULL,
            owner_generation TEXT NOT NULL,
            waiter_generation TEXT NOT NULL,
            resolution_token TEXT,
            terminal_reason TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            expires_at REAL,
            resolved_at REAL,
            UNIQUE(source_session_key, request_id)
        )
    """,
    "work_events": """
        CREATE TABLE work_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            job_id TEXT,
            run_id TEXT,
            subject_version INTEGER NOT NULL,
            subject_json TEXT,
            tombstone INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        )
    """,
    "idempotency_keys": """
        CREATE TABLE idempotency_keys (
            operation TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            subject_id TEXT,
            binding_json TEXT,
            response_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY(operation, idempotency_key)
        )
    """,
}

SCHEMA_V1_INDEX_SQL: Mapping[str, str] = {
    "idx_jobs_status_updated":
        "CREATE INDEX idx_jobs_status_updated ON jobs(status, updated_at DESC, job_id DESC)",
    "idx_jobs_session_updated":
        "CREATE INDEX idx_jobs_session_updated ON jobs(source_session_key, updated_at DESC, job_id DESC)",
    "idx_jobs_terminal_finished":
        "CREATE INDEX idx_jobs_terminal_finished ON jobs(status, finished_at, job_id)",
    "idx_job_runs_job_attempt":
        "CREATE INDEX idx_job_runs_job_attempt ON job_runs(job_id, attempt DESC)",
    "idx_job_runs_owner_status":
        "CREATE INDEX idx_job_runs_owner_status ON job_runs(owner_boot_token, owner_pid, owner_generation, status)",
    "idx_job_runs_status_updated":
        "CREATE INDEX idx_job_runs_status_updated ON job_runs(status, updated_at, run_id)",
    "idx_attention_state_created":
        "CREATE INDEX idx_attention_state_created ON attention_items(state, created_at DESC, attention_id DESC)",
    "idx_attention_job_state":
        "CREATE INDEX idx_attention_job_state ON attention_items(job_id, state)",
    "idx_attention_session_state":
        "CREATE INDEX idx_attention_session_state ON attention_items(runtime_session_id, state, attention_id)",
    "idx_attention_owner_state":
        "CREATE INDEX idx_attention_owner_state ON attention_items(owner_boot_token, owner_pid, owner_generation, state)",
    "idx_work_events_job_cursor":
        "CREATE INDEX idx_work_events_job_cursor ON work_events(job_id, event_id)",
    "idx_work_events_created_cursor":
        "CREATE INDEX idx_work_events_created_cursor ON work_events(created_at, event_id)",
    "idx_work_events_subject_cursor":
        "CREATE INDEX idx_work_events_subject_cursor "
        "ON work_events(subject_type, subject_id, event_id)",
    "idx_idempotency_state_updated":
        "CREATE INDEX idx_idempotency_state_updated ON idempotency_keys(state, updated_at, idempotency_key)",
}

# Terminal Attention retention orders by its final timestamp, not creation
# time.  The expression keeps a long-lived pending item that only recently
# reached a terminal state from forcing an unbounded scan of old rows.  The
# leading state is deliberately queried one terminal state at a time, so this
# index supplies both the cutoff and deterministic keyset order.
SCHEMA_INDEX_SQL: Mapping[str, str] = {
    **SCHEMA_V1_INDEX_SQL,
    "idx_attention_state_terminal_time":
        "CREATE INDEX idx_attention_state_terminal_time ON attention_items("
        "state, COALESCE(resolved_at, updated_at), attention_id)",
}
_SCHEMA_V2_ADDITIVE_INDEXES = ("idx_attention_state_terminal_time",)

EXPECTED_TABLE_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "work_meta": ("key", "value"),
    "jobs": (
        "job_id", "version", "kind", "status", "title", "summary", "source",
        "source_session_key", "runtime_session_id", "prompt_preview", "current_run_id",
        "attempt_count", "runtime_summary_json", "result_json", "result_omitted_reason",
        "error_json", "open_attention_count", "created_at", "started_at", "updated_at",
        "finished_at", "cancel_requested_at",
    ),
    "job_runs": (
        "run_id", "job_id", "attempt", "version", "status", "runtime_json",
        "owner_boot_token", "owner_pid", "owner_start_token", "owner_generation",
        "claim_token", "claimed_at", "started_at", "updated_at", "finished_at",
        "result_json", "error_json",
    ),
    "attention_items": (
        "attention_id", "version", "job_id", "run_id", "source_session_key",
        "runtime_session_id", "request_id", "kind", "state", "blocking", "sensitive",
        "title", "public_payload_json", "owner_boot_token", "owner_pid",
        "owner_start_token", "owner_generation", "waiter_generation", "resolution_token",
        "terminal_reason", "created_at", "updated_at", "expires_at", "resolved_at",
    ),
    "work_events": (
        "event_id", "event_type", "subject_type", "subject_id", "job_id", "run_id",
        "subject_version", "subject_json", "tombstone", "created_at",
    ),
    "idempotency_keys": (
        "operation", "idempotency_key", "request_hash", "state", "subject_id",
        "binding_json", "response_json", "created_at", "updated_at",
    ),
}

SCHEMA_V1_EXPECTED_INDEX_COLUMNS: Mapping[str, tuple[str | None, ...]] = {
    "idx_jobs_status_updated": ("status", "updated_at", "job_id"),
    "idx_jobs_session_updated": ("source_session_key", "updated_at", "job_id"),
    "idx_jobs_terminal_finished": ("status", "finished_at", "job_id"),
    "idx_job_runs_job_attempt": ("job_id", "attempt"),
    "idx_job_runs_owner_status": ("owner_boot_token", "owner_pid", "owner_generation", "status"),
    "idx_job_runs_status_updated": ("status", "updated_at", "run_id"),
    "idx_attention_state_created": ("state", "created_at", "attention_id"),
    "idx_attention_job_state": ("job_id", "state"),
    "idx_attention_session_state": ("runtime_session_id", "state", "attention_id"),
    "idx_attention_owner_state": ("owner_boot_token", "owner_pid", "owner_generation", "state"),
    "idx_work_events_job_cursor": ("job_id", "event_id"),
    "idx_work_events_created_cursor": ("created_at", "event_id"),
    "idx_work_events_subject_cursor": ("subject_type", "subject_id", "event_id"),
    "idx_idempotency_state_updated": ("state", "updated_at", "idempotency_key"),
}

EXPECTED_INDEX_COLUMNS: Mapping[str, tuple[str | None, ...]] = {
    **SCHEMA_V1_EXPECTED_INDEX_COLUMNS,
    # SQLite reports an expression key as ``None`` through ``index_info``.
    "idx_attention_state_terminal_time": ("state", None, "attention_id"),
}


class WorkLedgerError(RuntimeError):
    """Base for stable, caller-classifiable work-store failures."""

    code = "work_store_unavailable"
    retryable = False

    def __init__(self, message: str, *, data: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.data = dict(data or {})


class WorkStoreUnavailable(WorkLedgerError):
    pass


class WorkStoreBusy(WorkStoreUnavailable):
    retryable = True


class WorkStoreSignatureError(WorkStoreUnavailable):
    pass


class WorkStoreFutureSchemaError(WorkStoreUnavailable):
    def __init__(self, found: int):
        super().__init__(
            f"work.db schema {found} is newer than supported schema {WORK_SCHEMA_VERSION}",
            data={"found": found, "supported": WORK_SCHEMA_VERSION},
        )


class WorkStoreSchemaError(WorkStoreUnavailable):
    pass


class WorkStoreCorruptError(WorkStoreUnavailable):
    pass


class WorkStoreReplacedError(WorkStoreUnavailable):
    code = "cursor_expired"


class InvalidWorkIdentifier(WorkLedgerError, ValueError):
    code = "invalid_params"


class InvalidPublicData(WorkLedgerError, ValueError):
    code = "invalid_params"


class WorkNotFound(WorkLedgerError):
    code = "not_found"


class VersionConflict(WorkLedgerError):
    code = "version_conflict"


class InvalidTransition(WorkLedgerError):
    code = "invalid_transition"


class IdempotencyConflict(WorkLedgerError):
    code = "idempotency_conflict"


class WorkOperationInProgress(WorkLedgerError):
    code = "work_operation_in_progress"
    retryable = True


class RuntimeOwnerMismatch(WorkLedgerError):
    code = "runtime_owner_mismatch"


class AttentionNotActionable(WorkLedgerError):
    code = "attention_not_actionable"


class CursorExpired(WorkLedgerError):
    code = "cursor_expired"


@dataclass(frozen=True)
class RuntimeOwner:
    boot_token: str
    pid: int
    start_token: str
    generation: str

    def validated(self) -> "RuntimeOwner":
        if not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid <= 0:
            raise InvalidPublicData("owner pid must be a positive integer")
        for name, value in (
            ("boot_token", self.boot_token),
            ("start_token", self.start_token),
            ("generation", self.generation),
        ):
            _bounded_text(value, name, 512)
        return self


@dataclass(frozen=True)
class WorkStoreOwnerSummary:
    """One bounded, nonterminal owner group reported by read-only diagnostics."""

    owner: RuntimeOwner
    run_count: int
    attention_count: int


@dataclass(frozen=True)
class WorkStoreInspection:
    """A non-mutating health snapshot of one profile's durable Work store.

    This intentionally does not instantiate :class:`WorkLedger`: construction
    is an initialization/migration path, while doctor and restore preflight
    need to inspect a missing, legacy, or corrupt store without changing it.
    ``status`` is a stable, redacted diagnostic code rather than a SQLite
    exception string, which could contain an arbitrary filesystem path.
    """

    path: Path
    status: str
    size_bytes: int = 0
    wal_size_bytes: int = 0
    rollback_journal_size_bytes: int = 0
    application_id: int | None = None
    schema_version: int | None = None
    integrity_ok: bool | None = None
    ledger_id: str | None = None
    event_floor: int | None = None
    last_maintenance_at: float | None = None
    owner_summaries: tuple[WorkStoreOwnerSummary, ...] = ()
    owners_truncated: bool = False
    schema_mismatches: tuple[str, ...] = ()

    @property
    def readable(self) -> bool:
        return self.status in {"healthy", "legacy_schema"}


@dataclass(frozen=True)
class AttentionResolutionClaim:
    attention_id: str
    attention_version: int
    operation: str
    idempotency_key: str
    request_hash: str
    resolution_token: str | None
    replayed: bool
    receipt: Mapping[str, Any] | None = None


def new_work_id(prefix: str) -> str:
    if prefix not in {"job", "run", "attn", "mut", "ledger"}:
        raise InvalidWorkIdentifier(f"unsupported work id prefix: {prefix}")
    return f"{prefix}_{uuid.uuid4().hex}"


def validate_work_id(value: object, prefix: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value) or not value.startswith(prefix + "_"):
        raise InvalidWorkIdentifier(f"expected {prefix}_ followed by 32 lowercase hex characters")
    return value


def canonical_public_json(
    value: Any,
    *,
    max_bytes: int = PUBLIC_JSON_MAX_BYTES,
    field: str = "public JSON",
) -> str:
    """Return deterministic bounded JSON, rejecting NaN and non-JSON values."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 2:
        raise ValueError("max_bytes must be an integer >= 2")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidPublicData(f"{field} must be finite JSON data") from exc
    size = len(encoded.encode("utf-8"))
    if size > max_bytes:
        raise InvalidPublicData(f"{field} exceeds {max_bytes} UTF-8 bytes")
    return encoded


def _canonical_hash(value: Any) -> str:
    encoded = canonical_public_json(value, max_bytes=PUBLIC_JSON_MAX_BYTES, field="request envelope")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def hash_job_create_envelope(*, kind: str, title: str) -> str:
    """Hash only the non-sensitive create envelope; raw prompt is impossible here."""
    return _canonical_hash({"kind": _bounded_text(kind, "kind", 64), "title": _normalize_title(title)})


def hash_job_cancel_envelope(*, job_id: str, expected_version: int) -> str:
    """Hash the exact, non-sensitive cancellation CAS envelope."""

    return _canonical_hash(
        {
            "expected_version": _positive_int(expected_version, "expected_version"),
            "job_id": validate_work_id(job_id, "job"),
        }
    )


def hash_attention_response_envelope(
    *, attention_id: str, expected_version: int, kind: str, action: str
) -> str:
    """Hash response routing/action only; no value, reason, answer, or secret."""
    kind = _bounded_text(kind, "kind", 32).strip().lower()
    action = _bounded_text(action, "action", 64).strip().lower()
    _attention_outcome(kind, action)
    return _canonical_hash(
        {
            "action": action,
            "attention_id": validate_work_id(attention_id, "attn"),
            "expected_version": _positive_int(expected_version, "expected_version"),
            "kind": kind,
        }
    )


def _bounded_text(
    value: object,
    field: str,
    max_chars: int,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise InvalidPublicData(f"{field} must be a string")
    if len(value) > max_chars:
        raise InvalidPublicData(f"{field} exceeds {max_chars} characters")
    if not allow_empty and not value.strip():
        raise InvalidPublicData(f"{field} must not be empty")
    return value


def _attention_outcome(kind: str, action: str) -> str:
    """Return the only successful terminal state for a kind/action pair."""
    actions = ATTENTION_ACTION_OUTCOMES.get(kind)
    if actions is None:
        raise InvalidPublicData("unsupported Attention kind")
    outcome = actions.get(action)
    if outcome is None:
        raise InvalidPublicData(f"unsupported action for {kind} Attention")
    return outcome


def _optional_text(value: object | None, field: str, max_chars: int) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field, max_chars, allow_empty=True)


def _normalize_title(value: object) -> str:
    return _bounded_text(value, "title", 200).strip()


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise InvalidPublicData(f"{field} must be a positive integer")
    return value


def _bounded_limit(value: object, *, maximum: int, field: str = "limit") -> int:
    parsed = _positive_int(value, field)
    if parsed > maximum:
        raise InvalidPublicData(f"{field} must be <= {maximum}")
    return parsed


def _validate_idempotency_key(value: object) -> str:
    if not isinstance(value, str) or not _IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise InvalidPublicData("idempotency_key must be 16..128 safe characters")
    return value


def _validate_operation(value: object) -> str:
    text = _bounded_text(value, "operation", 128)
    if not re.fullmatch(r"[a-z][a-z0-9_.-]*", text):
        raise InvalidPublicData("operation has an invalid format")
    return text


def _now_seconds(value: float | None = None) -> float:
    result = time.time() if value is None else value
    if isinstance(result, bool) or not isinstance(result, (int, float)) or not math.isfinite(result):
        raise InvalidPublicData("timestamp must be finite")
    return float(result)


def _ms(value: object | None) -> int | None:
    return None if value is None else int(float(value) * 1000)


def _json_load(raw: object | None, *, default: Any = None) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise WorkStoreSchemaError("work.db contains malformed JSON") from exc


def _preview_json(raw: object | None, max_bytes: int) -> Any:
    if raw is None:
        return None
    text = str(raw)
    if len(text.encode("utf-8")) <= max_bytes:
        return _json_load(text)
    data = text.encode("utf-8")[: max(0, max_bytes - 32)]
    preview = data.decode("utf-8", errors="ignore")
    return {"truncated": True, "preview": preview}


def _normalize_schema_sql(value: object | None) -> str:
    """Normalize SQLite's formatting while preserving declaration semantics."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


T = TypeVar("T")


def _is_busy_error(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    code = getattr(exc, "sqlite_errorcode", None)
    if code in {getattr(sqlite3, "SQLITE_BUSY", 5), getattr(sqlite3, "SQLITE_LOCKED", 6)}:
        return True
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message


_PROCESS_INIT_LOCK = threading.RLock()


@contextlib.contextmanager
def _cross_process_init_lock(path: Path, *, deadline: float):
    """Acquire a bounded host-local first-open lock; never proceed unguarded."""
    lock_path = path.with_name(path.name + ".init.lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise WorkStoreUnavailable(f"cannot open work-store init lock: {exc}") from exc
    handle = os.fdopen(fd, "r+b", closefd=True)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            while time.monotonic() < deadline:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.025)
        else:
            import fcntl

            while time.monotonic() < deadline:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except (BlockingIOError, OSError):
                    time.sleep(0.025)
        if not acquired:
            raise WorkStoreBusy("work-store initialization lock deadline exhausted")
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class WorkLedger:
    """A short-connection, multi-process-safe view of one profile's ledger."""

    def __init__(
        self,
        profile_home: str | os.PathLike[str],
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        write_deadline_seconds: float = DEFAULT_WRITE_DEADLINE_SECONDS,
        init_deadline_seconds: float = DEFAULT_INIT_DEADLINE_SECONDS,
        clock: Callable[[], float] = time.time,
    ):
        home = Path(profile_home).expanduser()
        if str(home) in {"", "."}:
            raise WorkStoreUnavailable("profile_home must be explicit")
        try:
            self.profile_home = home.resolve(strict=False)
        except OSError as exc:
            raise WorkStoreUnavailable(f"cannot resolve profile home: {exc}") from exc
        self.path = self.profile_home / WORK_DB_FILENAME
        if not isinstance(busy_timeout_ms, int) or isinstance(busy_timeout_ms, bool) or busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be a positive integer")
        if write_deadline_seconds <= 0 or init_deadline_seconds <= 0:
            raise ValueError("transaction deadlines must be positive")
        self.busy_timeout_ms = busy_timeout_ms
        self.write_deadline_seconds = float(write_deadline_seconds)
        self.init_deadline_seconds = float(init_deadline_seconds)
        self._clock = clock
        self._ledger_id = self._initialize()

    @property
    def ledger_id(self) -> str:
        return self._ledger_id

    def assert_store_identity(self) -> str:
        """Prove the on-disk ledger still matches this cached service instance."""
        conn = self._connect(for_write=False)
        conn.close()
        return self._ledger_id

    def close(self) -> None:
        """Compatibility hook for WorkService; operations own short connections."""
        return None

    def _ensure_profile_directory(self) -> None:
        try:
            self.profile_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkStoreUnavailable(f"cannot create profile directory: {exc}") from exc
        try:
            mode = self.profile_home.lstat().st_mode
        except OSError as exc:
            raise WorkStoreUnavailable(f"cannot inspect profile directory: {exc}") from exc
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise WorkStoreUnavailable("profile_home must be a real directory, not a symlink")

    def _secure_create_if_missing(self) -> bool:
        """Create a real 0600 file without following a final-component symlink."""
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError:
            created = False
        except OSError as exc:
            raise WorkStoreUnavailable(f"cannot create work.db: {exc}") from exc
        else:
            os.close(fd)
            created = True
        try:
            mode = self.path.lstat().st_mode
        except OSError as exc:
            raise WorkStoreUnavailable(f"cannot inspect work.db: {exc}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise WorkStoreUnavailable("work.db must be a regular file, not a symlink")
        return created

    def _validate_header(self) -> None:
        try:
            size = self.path.stat().st_size
            if size == 0:
                return
            with self.path.open("rb") as handle:
                header = handle.read(len(_SQLITE_HEADER))
        except OSError as exc:
            raise WorkStoreUnavailable(f"cannot inspect work.db header: {exc}") from exc
        if header != _SQLITE_HEADER:
            raise WorkStoreSignatureError("work.db has an invalid SQLite header")

    def _raw_connect(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = None
        try:
            # ``mode=rw`` is load-bearing even after the lstat/header checks:
            # another process can unlink the path between those checks and
            # sqlite3.connect().  SQLite's default mode would silently create
            # a new zero-byte database in that window.
            conn = sqlite3.connect(
                f"{self.path.as_uri()}?mode=rw",
                uri=True,
                isolation_level=None,
                timeout=self.busy_timeout_ms / 1000.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.execute("PRAGMA secure_delete=ON")
            conn.execute("PRAGMA cell_size_check=ON")
            return conn
        except sqlite3.OperationalError as exc:
            if conn is not None:
                conn.close()
            if _is_busy_error(exc):
                raise WorkStoreBusy(f"work.db is busy while opening: {exc}") from exc
            raise WorkStoreUnavailable(f"cannot open work.db: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()
            raise WorkStoreCorruptError(f"work.db is not a valid SQLite database: {exc}") from exc
        except OSError as exc:
            if conn is not None:
                conn.close()
            raise WorkStoreUnavailable(f"cannot open work.db: {exc}") from exc

    def _initialize(self) -> str:
        self._ensure_profile_directory()
        deadline = time.monotonic() + self.init_deadline_seconds
        with _PROCESS_INIT_LOCK, _cross_process_init_lock(self.path, deadline=deadline):
            created = self._secure_create_if_missing()
            self._validate_header()
            conn = self._raw_connect()
            try:
                self._preflight_signature(conn, created=created)
                from fabric_state import apply_wal_with_fallback

                apply_wal_with_fallback(conn, db_label=f"work.db ({self.profile_home})")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("PRAGMA wal_autocheckpoint=100")
                self._begin(conn, deadline=deadline)
                try:
                    ledger_id = self._initialize_or_validate_in_txn(conn)
                    self._commit(conn, deadline=deadline)
                except Exception:
                    self._rollback(conn)
                    raise
                check = conn.execute("PRAGMA quick_check").fetchone()
                if not check or str(check[0]).lower() != "ok":
                    raise WorkStoreCorruptError(
                        f"work.db quick_check failed: {check[0] if check else '<no result>'}"
                    )
            except sqlite3.DatabaseError as exc:
                if isinstance(exc, sqlite3.OperationalError) and _is_busy_error(exc):
                    raise WorkStoreBusy("work.db initialization lock deadline exhausted") from exc
                raise WorkStoreCorruptError(f"work.db is not readable: {exc}") from exc
            finally:
                conn.close()
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                if os.name != "nt":
                    raise WorkStoreUnavailable("cannot restrict work.db permissions")
            return ledger_id

    def _preflight_signature(self, conn: sqlite3.Connection, *, created: bool) -> None:
        try:
            app_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.DatabaseError as exc:
            raise WorkStoreCorruptError(f"cannot read work.db signature: {exc}") from exc
        if version > WORK_SCHEMA_VERSION:
            raise WorkStoreFutureSchemaError(version)
        if app_id not in {0, WORK_APPLICATION_ID}:
            raise WorkStoreSignatureError(
                f"SQLite application_id {app_id} does not identify a Fabric work ledger"
            )
        if created:
            return
        check = conn.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise WorkStoreCorruptError(
                f"work.db quick_check failed: {check[0] if check else '<no result>'}"
            )
        tables = self._user_tables(conn)
        if tables:
            mismatches = self._schema_mismatches_for_version(conn, version)
            if mismatches and not self._known_tables_are_empty(conn):
                raise WorkStoreSchemaError(
                    "populated work.db schema mismatch: " + "; ".join(mismatches)
                )
            recognized_version = (
                app_id == WORK_APPLICATION_ID
                and version in {_WORK_SCHEMA_V1, WORK_SCHEMA_VERSION}
            )
            if not recognized_version:
                if not self._known_tables_are_empty(conn):
                    raise WorkStoreSchemaError(
                        "populated prerelease work.db cannot be adopted"
                    )
            elif not mismatches:
                meta = {
                    str(row[0]): str(row[1])
                    for row in conn.execute("SELECT key, value FROM work_meta")
                }
                required = {
                    "ledger_id",
                    "event_floor",
                    "created_at",
                    "last_maintenance_at",
                }
                if set(meta) != required and not self._known_tables_are_empty(conn):
                    raise WorkStoreSchemaError(
                        "populated work.db metadata signature is incomplete"
                    )

    @staticmethod
    def _user_tables(conn: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    @staticmethod
    def _schema_mismatches(
        conn: sqlite3.Connection,
        *,
        expected_index_columns: Mapping[str, tuple[str | None, ...]] = EXPECTED_INDEX_COLUMNS,
        expected_index_sql: Mapping[str, str] = SCHEMA_INDEX_SQL,
    ) -> list[str]:
        mismatches: list[str] = []
        tables = WorkLedger._user_tables(conn)
        expected_tables = set(EXPECTED_TABLE_COLUMNS)
        if tables != expected_tables:
            mismatches.append(
                f"tables expected={sorted(expected_tables)} found={sorted(tables)}"
            )
        for table, expected in EXPECTED_TABLE_COLUMNS.items():
            if table not in tables:
                continue
            found = tuple(str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")'))
            if found != expected:
                mismatches.append(f"columns for {table} differ")
            sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if sql_row is None or _normalize_schema_sql(sql_row[0]) != _normalize_schema_sql(
                SCHEMA_TABLE_SQL[table]
            ):
                mismatches.append(f"declaration for table {table} differs")
        indexes = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        expected_indexes = set(expected_index_columns)
        if indexes != expected_indexes:
            mismatches.append(
                f"indexes expected={sorted(expected_indexes)} found={sorted(indexes)}"
            )
        for index, expected in expected_index_columns.items():
            if index not in indexes:
                continue
            found = tuple(row[2] for row in conn.execute(f'PRAGMA index_info("{index}")'))
            if found != expected:
                mismatches.append(f"columns for index {index} differ")
            sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index,)
            ).fetchone()
            if sql_row is None or _normalize_schema_sql(sql_row[0]) != _normalize_schema_sql(
                expected_index_sql[index]
            ):
                mismatches.append(f"declaration for index {index} differs")
        return mismatches

    @staticmethod
    def _schema_mismatches_for_version(
        conn: sqlite3.Connection, version: int
    ) -> list[str]:
        """Validate the exact known shape for one on-disk schema version."""

        if version == _WORK_SCHEMA_V1:
            # v1/v2 share table declarations.  Freeze separate table maps
            # before introducing any future table migration.
            return WorkLedger._schema_mismatches(
                conn,
                expected_index_columns=SCHEMA_V1_EXPECTED_INDEX_COLUMNS,
                expected_index_sql=SCHEMA_V1_INDEX_SQL,
            )
        return WorkLedger._schema_mismatches(conn)

    @staticmethod
    def _known_tables_are_empty(conn: sqlite3.Connection) -> bool:
        tables = WorkLedger._user_tables(conn)
        if not tables.issubset(SCHEMA_TABLE_SQL):
            return False
        for table in tables:
            try:
                if conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() is not None:
                    return False
            except sqlite3.DatabaseError:
                return False
        return True

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        for sql in SCHEMA_TABLE_SQL.values():
            conn.execute(sql)
        for sql in SCHEMA_INDEX_SQL.values():
            conn.execute(sql)

    @staticmethod
    def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
        """Apply the v1->v2 retention migration inside the open write txn."""

        # v1 allowed wall-clock rollback to put an Attention's terminal time
        # before an earlier open/response/event timestamp. Normalize to the
        # highest retained lifecycle evidence before adding the final-time
        # index; otherwise a v2 retention pass could erase live history early.
        conn.execute(
            "WITH receipt_bounds AS ("
            "SELECT subject_id AS attention_id, "
            "MAX(CASE WHEN created_at>updated_at THEN created_at ELSE updated_at END) AS bound_at "
            "FROM idempotency_keys WHERE operation='attention.respond' AND subject_id IS NOT NULL "
            "GROUP BY subject_id"
            "), event_bounds AS ("
            "SELECT subject_id AS attention_id, MAX(created_at) AS bound_at "
            "FROM work_events WHERE subject_type='attention' GROUP BY subject_id"
            ") UPDATE attention_items SET "
            "updated_at=MAX(created_at, updated_at, COALESCE(resolved_at, updated_at), "
            "COALESCE((SELECT bound_at FROM receipt_bounds "
            "WHERE attention_id=attention_items.attention_id), created_at), "
            "COALESCE((SELECT bound_at FROM event_bounds "
            "WHERE attention_id=attention_items.attention_id), created_at)), "
            "resolved_at=CASE WHEN resolved_at IS NULL THEN NULL ELSE "
            "MAX(created_at, updated_at, resolved_at, "
            "COALESCE((SELECT bound_at FROM receipt_bounds "
            "WHERE attention_id=attention_items.attention_id), created_at), "
            "COALESCE((SELECT bound_at FROM event_bounds "
            "WHERE attention_id=attention_items.attention_id), created_at)) END"
        )
        conn.execute(
            "UPDATE idempotency_keys SET "
            "created_at=MAX(created_at, (SELECT a.created_at FROM attention_items a "
            "WHERE a.attention_id=idempotency_keys.subject_id)), "
            "updated_at=MAX(updated_at, (SELECT COALESCE(a.resolved_at, a.updated_at) "
            "FROM attention_items a WHERE a.attention_id=idempotency_keys.subject_id)) "
            "WHERE operation='attention.respond' AND EXISTS (SELECT 1 FROM attention_items a "
            "WHERE a.attention_id=idempotency_keys.subject_id)"
        )
        for index in _SCHEMA_V2_ADDITIVE_INDEXES:
            conn.execute(SCHEMA_INDEX_SQL[index])

    @staticmethod
    def _drop_known_schema(conn: sqlite3.Connection) -> None:
        for index in SCHEMA_INDEX_SQL:
            conn.execute(f'DROP INDEX IF EXISTS "{index}"')
        for table in reversed(tuple(SCHEMA_TABLE_SQL)):
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')

    def _initialize_or_validate_in_txn(self, conn: sqlite3.Connection) -> str:
        app_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version > WORK_SCHEMA_VERSION:
            raise WorkStoreFutureSchemaError(version)
        if app_id not in {0, WORK_APPLICATION_ID}:
            raise WorkStoreSignatureError("work.db application signature changed during open")

        fresh = app_id == 0 and version == 0 and not self._user_tables(conn)
        current = app_id == WORK_APPLICATION_ID and version == WORK_SCHEMA_VERSION
        initialized_empty_schema = False
        if fresh:
            self._create_schema(conn)
            initialized_empty_schema = True
        elif app_id == WORK_APPLICATION_ID and version == _WORK_SCHEMA_V1:
            legacy_mismatches = self._schema_mismatches_for_version(conn, version)
            if legacy_mismatches:
                # An empty, recognisably prerelease schema is safe to rebuild.
                # A populated v1-shaped database is evidence and must not be
                # "migrated" through a mismatched declaration.
                if not self._known_tables_are_empty(conn):
                    raise WorkStoreSchemaError(
                        "work.db schema mismatch: " + "; ".join(legacy_mismatches)
                    )
                self._drop_known_schema(conn)
                self._create_schema(conn)
                initialized_empty_schema = True
            else:
                self._migrate_v1_to_v2(conn)
                migrated_mismatches = self._schema_mismatches(conn)
                if migrated_mismatches:
                    raise WorkStoreSchemaError(
                        "work.db schema migration mismatch: "
                        + "; ".join(migrated_mismatches)
                    )
        elif self._schema_mismatches(conn):
            # An empty, recognisably prerelease schema is safe to rebuild.  Any
            # populated or foreign shape is evidence, so fail without mutation.
            if not self._known_tables_are_empty(conn):
                raise WorkStoreSchemaError(
                    "work.db schema mismatch: "
                    + "; ".join(self._schema_mismatches(conn))
                )
            self._drop_known_schema(conn)
            self._create_schema(conn)
            initialized_empty_schema = True
        elif not current:
            # Even an exact-looking populated prerelease database is not adopted:
            # without both signature fields its ownership/version is ambiguous.
            if not self._known_tables_are_empty(conn):
                raise WorkStoreSchemaError("populated prerelease work.db cannot be adopted")
            # Exact-but-unversioned empty prerelease schema: rebuild so its
            # declaration and metadata are both unquestionably v1.
            self._drop_known_schema(conn)
            self._create_schema(conn)
            initialized_empty_schema = True

        conn.execute(f"PRAGMA application_id={WORK_APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version={WORK_SCHEMA_VERSION}")
        now = self._clock()
        existing_meta = {
            str(row[0]): str(row[1])
            for row in conn.execute("SELECT key, value FROM work_meta")
        }
        if not existing_meta:
            if not initialized_empty_schema:
                if not self._known_tables_are_empty(conn):
                    raise WorkStoreSchemaError(
                        "populated work.db is missing its ledger metadata"
                    )
                self._drop_known_schema(conn)
                self._create_schema(conn)
            ledger_id = new_work_id("ledger")
            conn.executemany(
                "INSERT INTO work_meta(key, value) VALUES (?, ?)",
                (
                    ("ledger_id", ledger_id),
                    ("event_floor", "1"),
                    ("created_at", repr(float(now))),
                    ("last_maintenance_at", repr(float(now))),
                ),
            )
            return ledger_id
        required = {"ledger_id", "event_floor", "created_at", "last_maintenance_at"}
        if set(existing_meta) != required:
            raise WorkStoreSchemaError("work.db metadata signature is incomplete")
        ledger_id = validate_work_id(existing_meta["ledger_id"], "ledger")
        try:
            floor = int(existing_meta["event_floor"])
            float(existing_meta["created_at"])
            float(existing_meta["last_maintenance_at"])
        except ValueError as exc:
            raise WorkStoreSchemaError("work.db metadata contains invalid values") from exc
        if floor < 1:
            raise WorkStoreSchemaError("work.db event_floor must be >= 1")
        return ledger_id

    def _connect(self, *, for_write: bool = False) -> sqlite3.Connection:
        # Never recreate a missing/replaced file from a stale service instance.
        try:
            mode = self.path.lstat().st_mode
        except OSError as exc:
            raise WorkStoreReplacedError("work.db disappeared; reopen the profile service") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise WorkStoreReplacedError("work.db path was replaced")
        self._validate_header()
        conn = self._raw_connect()
        try:
            app_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if app_id != WORK_APPLICATION_ID:
                raise WorkStoreSignatureError("work.db application signature changed")
            if version > WORK_SCHEMA_VERSION:
                raise WorkStoreFutureSchemaError(version)
            if version != WORK_SCHEMA_VERSION:
                raise WorkStoreSchemaError("work.db schema version changed")
            row = conn.execute(
                "SELECT value FROM work_meta WHERE key='ledger_id'"
            ).fetchone()
            if row is None or str(row[0]) != self._ledger_id:
                raise WorkStoreReplacedError("work.db ledger_id changed; bootstrap a new service")
            if for_write:
                from fabric_state import apply_wal_with_fallback

                apply_wal_with_fallback(conn, db_label=f"work.db ({self.profile_home})")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("PRAGMA wal_autocheckpoint=100")
            return conn
        except Exception:
            conn.close()
            raise

    def _begin(self, conn: sqlite3.Connection, *, deadline: float) -> None:
        self._boundary(conn, "BEGIN IMMEDIATE", deadline=deadline)

    def _commit(self, conn: sqlite3.Connection, *, deadline: float) -> None:
        self._boundary(conn, "COMMIT", deadline=deadline)

    @staticmethod
    def _rollback(conn: sqlite3.Connection) -> None:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass

    @staticmethod
    def _boundary(conn: sqlite3.Connection, sql: str, *, deadline: float) -> None:
        while True:
            try:
                conn.execute(sql)
                return
            except sqlite3.OperationalError as exc:
                if not _is_busy_error(exc):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkStoreBusy(
                        f"work.db {sql.split()[0].lower()} deadline exhausted"
                    ) from exc
                time.sleep(min(remaining, random.uniform(_RETRY_MIN_SECONDS, _RETRY_MAX_SECONDS)))

    def _write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``fn`` exactly once; retry only stable BEGIN/COMMIT boundaries."""
        conn = self._connect(for_write=True)
        deadline = time.monotonic() + self.write_deadline_seconds
        try:
            self._begin(conn, deadline=deadline)
            try:
                # Fence a restore/replacement that raced connection creation.
                row = conn.execute(
                    "SELECT value FROM work_meta WHERE key='ledger_id'"
                ).fetchone()
                if row is None or str(row[0]) != self._ledger_id:
                    raise WorkStoreReplacedError("work.db ledger changed during mutation")
                result = fn(conn)
            except Exception:
                self._rollback(conn)
                raise
            try:
                self._commit(conn, deadline=deadline)
            except Exception:
                self._rollback(conn)
                raise
            return result
        finally:
            conn.close()

    @contextlib.contextmanager
    def _read(self):
        conn = self._connect(for_write=False)
        try:
            conn.execute("BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            self._rollback(conn)
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public row projections and event append
    # ------------------------------------------------------------------

    @staticmethod
    def _load_run_row(
        conn: sqlite3.Connection, run_id: object | None
    ) -> sqlite3.Row | None:
        if run_id is None:
            return None
        return conn.execute(
            "SELECT * FROM job_runs WHERE run_id=?", (str(run_id),)
        ).fetchone()

    @staticmethod
    def _run_public(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        runtime = _json_load(row["runtime_json"], default={})
        if not isinstance(runtime, dict):
            raise WorkStoreSchemaError("job_runs.runtime_json must be an object")
        return {
            "run_id": str(row["run_id"]),
            "attempt": int(row["attempt"]),
            "version": int(row["version"]),
            "status": str(row["status"]),
            "runtime_kind": str(runtime.get("kind") or "in_process_agent"),
            "owner_state": str(runtime.get("owner_state") or "creator_bound"),
            "restart_behavior": "interrupt",
            "claimed_at": _ms(row["claimed_at"]),
            "started_at": _ms(row["started_at"]),
            "updated_at": _ms(row["updated_at"]),
            "finished_at": _ms(row["finished_at"]),
        }

    @classmethod
    def _job_public(
        cls,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        detail: bool = False,
    ) -> dict[str, Any]:
        return cls._job_public_with_run(
            row,
            cls._load_run_row(conn, row["current_run_id"]),
            detail=detail,
        )

    @classmethod
    def _job_public_with_run(
        cls,
        row: sqlite3.Row,
        run_row: sqlite3.Row | None,
        *,
        detail: bool = False,
    ) -> dict[str, Any]:
        runtime = _json_load(row["runtime_summary_json"], default={})
        if not isinstance(runtime, dict):
            raise WorkStoreSchemaError("jobs.runtime_summary_json must be an object")
        result_preview = None
        if row["result_omitted_reason"] is None:
            result_preview = _preview_json(row["result_json"], JOB_RESULT_PREVIEW_MAX_BYTES)
        error_preview = _preview_json(row["error_json"], JOB_ERROR_PREVIEW_MAX_BYTES)
        result_ref = runtime.get("result_ref")
        result: dict[str, Any] = {
            "job_id": str(row["job_id"]),
            "version": int(row["version"]),
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "title": str(row["title"]),
            "summary": row["summary"],
            "source": str(row["source"]),
            "source_session_key": row["source_session_key"],
            "runtime_session_id": row["runtime_session_id"],
            "attempt_count": int(row["attempt_count"]),
            "open_attention_count": int(row["open_attention_count"]),
            "created_at": _ms(row["created_at"]),
            "started_at": _ms(row["started_at"]),
            "updated_at": _ms(row["updated_at"]),
            "finished_at": _ms(row["finished_at"]),
            "cancel_requested_at": _ms(row["cancel_requested_at"]),
            "runtime": runtime,
            "current_run": cls._run_public(run_row),
            "result_preview": result_preview,
            "result_ref": result_ref,
            "result_omitted_reason": row["result_omitted_reason"],
            "error": error_preview,
        }
        if detail:
            result["prompt_preview"] = row["prompt_preview"]
            result["result"] = (
                None
                if row["result_omitted_reason"] is not None
                else _json_load(row["result_json"])
            )
            result["error_detail"] = _json_load(row["error_json"])
        return result

    @staticmethod
    def _attention_allowed_actions(kind: str, state: str) -> list[str]:
        if state != "pending":
            return []
        return list(ATTENTION_ACTION_OUTCOMES.get(kind, ()))

    @classmethod
    def _attention_public(cls, row: sqlite3.Row) -> dict[str, Any]:
        payload = _json_load(row["public_payload_json"], default={})
        if not isinstance(payload, dict):
            raise WorkStoreSchemaError("attention public payload must be an object")
        kind = str(row["kind"])
        state = str(row["state"])
        return {
            "attention_id": str(row["attention_id"]),
            "version": int(row["version"]),
            "job_id": row["job_id"],
            "run_id": row["run_id"],
            "source_session_key": row["source_session_key"],
            "runtime_session_id": row["runtime_session_id"],
            "request_id": str(row["request_id"]),
            "kind": kind,
            "state": state,
            "blocking": bool(row["blocking"]),
            "sensitive": bool(row["sensitive"]),
            "title": str(row["title"]),
            "public_payload": payload,
            "allowed_actions": cls._attention_allowed_actions(kind, state),
            "created_at": _ms(row["created_at"]),
            "updated_at": _ms(row["updated_at"]),
            "expires_at": _ms(row["expires_at"]),
            "resolved_at": _ms(row["resolved_at"]),
            "terminal_reason": row["terminal_reason"],
        }

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        event_type: str,
        subject_type: str,
        subject_id: str,
        subject_version: int,
        subject: Mapping[str, Any] | None,
        job_id: str | None,
        run_id: str | None,
        tombstone: bool,
        created_at: float,
    ) -> int:
        event_type = _bounded_text(event_type, "event_type", 128)
        if subject_type not in {"job", "attention"}:
            raise InvalidPublicData("subject_type must be job or attention")
        subject_json = None
        if not tombstone:
            if subject is None:
                raise InvalidPublicData("non-tombstone event requires a subject")
            subject_json = canonical_public_json(subject, field="event subject")
        elif subject is not None:
            raise InvalidPublicData("tombstone event subject must be null")
        cursor = conn.execute(
            "INSERT INTO work_events("
            "event_type, subject_type, subject_id, job_id, run_id, subject_version, "
            "subject_json, tombstone, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_type,
                subject_type,
                subject_id,
                job_id,
                run_id,
                subject_version,
                subject_json,
                int(tombstone),
                created_at,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _event_public(row: sqlite3.Row) -> dict[str, Any]:
        subject = _json_load(row["subject_json"])
        return {
            "event_id": int(row["event_id"]),
            "event_type": str(row["event_type"]),
            "subject_type": str(row["subject_type"]),
            "subject_id": str(row["subject_id"]),
            "job_id": row["job_id"],
            "run_id": row["run_id"],
            "subject_version": int(row["subject_version"]),
            "subject": subject,
            "tombstone": bool(row["tombstone"]),
            "created_at": _ms(row["created_at"]),
        }

    # ------------------------------------------------------------------
    # Idempotency state
    # ------------------------------------------------------------------

    @staticmethod
    def _idempotency_row(
        conn: sqlite3.Connection, operation: str, idempotency_key: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM idempotency_keys WHERE operation=? AND idempotency_key=?",
            (operation, idempotency_key),
        ).fetchone()

    @staticmethod
    def _attention_resolution_binding(row: sqlite3.Row) -> dict[str, Any]:
        """Validate a durable action binding against its SHA-256 envelope."""
        if str(row["operation"]) != "attention.respond":
            raise WorkStoreSchemaError("Attention reservation has the wrong operation")
        binding = _json_load(row["binding_json"])
        if not isinstance(binding, dict) or set(binding) != {
            "kind",
            "action",
            "expected_version",
            "terminal_state",
        }:
            raise WorkStoreSchemaError("Attention reservation binding is malformed")
        try:
            attention_id = validate_work_id(row["subject_id"], "attn")
            kind = _bounded_text(binding["kind"], "kind", 32).strip().lower()
            action = _bounded_text(binding["action"], "action", 64).strip().lower()
            expected_version = _positive_int(
                binding["expected_version"], "expected_version"
            )
            terminal_state = _bounded_text(
                binding["terminal_state"], "terminal_state", 32
            ).strip().lower()
            allowed_terminal_state = _attention_outcome(kind, action)
        except (InvalidPublicData, InvalidWorkIdentifier) as exc:
            raise WorkStoreSchemaError(
                "Attention reservation binding contains invalid values"
            ) from exc
        if terminal_state != allowed_terminal_state:
            raise WorkStoreSchemaError(
                "Attention reservation action and terminal state diverged"
            )
        expected_hash = hash_attention_response_envelope(
            attention_id=attention_id,
            expected_version=expected_version,
            kind=kind,
            action=action,
        )
        request_hash = str(row["request_hash"])
        if not hmac.compare_digest(request_hash, expected_hash):
            raise WorkStoreSchemaError(
                "Attention reservation binding does not match its request hash"
            )
        return {
            "attention_id": attention_id,
            "kind": kind,
            "action": action,
            "expected_version": expected_version,
            "terminal_state": terminal_state,
        }

    @staticmethod
    def _check_existing_idempotency(
        row: sqlite3.Row | None,
        *,
        request_hash: str,
    ) -> Mapping[str, Any] | None:
        if row is None:
            return None
        if str(row["request_hash"]) != request_hash:
            raise IdempotencyConflict("idempotency key was reused for a different public envelope")
        state = str(row["state"])
        if state == "finalized" and row["response_json"] is not None:
            response = _json_load(row["response_json"])
            if not isinstance(response, dict):
                raise WorkStoreSchemaError("finalized idempotency receipt must be an object")
            return response
        if state in {"reserved", "delivering"}:
            raise WorkOperationInProgress(
                f"identical {row['operation']} mutation is {state}", data={"state": state}
            )
        raise AttentionNotActionable(
            f"idempotent mutation is terminal without a replayable receipt: {state}",
            data={"state": state},
        )

    def get_idempotency(
        self, *, operation: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        operation = _validate_operation(operation)
        idempotency_key = _validate_idempotency_key(idempotency_key)
        with self._read() as conn:
            row = self._idempotency_row(conn, operation, idempotency_key)
            if row is None:
                return None
            return {
                "operation": str(row["operation"]),
                "idempotency_key": str(row["idempotency_key"]),
                "request_hash": str(row["request_hash"]),
                "state": str(row["state"]),
                "subject_id": row["subject_id"],
                "response": _json_load(row["response_json"]),
                "created_at": _ms(row["created_at"]),
                "updated_at": _ms(row["updated_at"]),
            }

    def reserve_idempotency(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        subject_id: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Reserve a non-sensitive envelope for a later claim/deliver flow.

        This low-level helper intentionally accepts a precomputed hash, never a
        request object.  Prefer the two public hash helpers above.
        """
        operation = _validate_operation(operation)
        idempotency_key = _validate_idempotency_key(idempotency_key)
        if not isinstance(request_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", request_hash):
            raise InvalidPublicData("request_hash must be a lowercase SHA-256 digest")
        if subject_id is not None:
            _bounded_text(subject_id, "subject_id", 128)
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            row = self._idempotency_row(conn, operation, idempotency_key)
            replay = self._check_existing_idempotency(row, request_hash=request_hash)
            if replay is not None:
                return {"replayed": True, "receipt": dict(replay)}
            conn.execute(
                "INSERT INTO idempotency_keys("
                "operation, idempotency_key, request_hash, state, subject_id, response_json, "
                "created_at, updated_at) VALUES (?, ?, ?, 'reserved', ?, NULL, ?, ?)",
                (operation, idempotency_key, request_hash, subject_id, timestamp, timestamp),
            )
            return {"replayed": False, "state": "reserved", "subject_id": subject_id}

        return self._write(mutate)

    def transition_idempotency(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        next_state: str,
        response: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        operation = _validate_operation(operation)
        idempotency_key = _validate_idempotency_key(idempotency_key)
        if not isinstance(request_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", request_hash):
            raise InvalidPublicData("request_hash must be a lowercase SHA-256 digest")
        next_state = _bounded_text(next_state, "next_state", 32)
        if next_state not in IDEMPOTENCY_TRANSITIONS:
            raise InvalidTransition(f"unknown idempotency state: {next_state}")
        if (next_state == "finalized") != (response is not None):
            raise InvalidPublicData("only finalized idempotency state stores a response")
        response_json = (
            canonical_public_json(response, field="idempotency receipt")
            if response is not None
            else None
        )
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            row = self._idempotency_row(conn, operation, idempotency_key)
            if row is None:
                raise WorkNotFound("idempotency reservation not found")
            if str(row["request_hash"]) != request_hash:
                raise IdempotencyConflict("idempotency request hash changed")
            current = str(row["state"])
            if next_state not in IDEMPOTENCY_TRANSITIONS.get(current, frozenset()):
                raise InvalidTransition(f"idempotency cannot transition {current} -> {next_state}")
            conn.execute(
                "UPDATE idempotency_keys SET state=?, response_json=?, updated_at=? "
                "WHERE operation=? AND idempotency_key=?",
                (next_state, response_json, timestamp, operation, idempotency_key),
            )
            return {
                "operation": operation,
                "idempotency_key": idempotency_key,
                "state": next_state,
                "response": dict(response) if response is not None else None,
            }

        return self._write(mutate)

    # ------------------------------------------------------------------
    # Jobs and execution attempts
    # ------------------------------------------------------------------

    def create_job(
        self,
        *,
        kind: str,
        title: str,
        source: str,
        owner: RuntimeOwner,
        idempotency_key: str,
        runtime_summary: Mapping[str, Any],
        run_runtime: Mapping[str, Any],
        source_session_key: str | None = None,
        runtime_session_id: str | None = None,
        summary: str | None = None,
        prompt_preview: str | None = None,
        job_id: str | None = None,
        run_id: str | None = None,
        mutation_id: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Create one creator-bound Job/Run and finalize its create receipt.

        ``prompt_preview`` must already be redacted and length-limited.  It is
        deliberately excluded from the request hash, along with all raw prompt
        text (which this API does not accept at all).  Retrying the same key
        with a changed preview therefore replays the first receipt and creates
        no second Job or Run.
        """
        kind = _bounded_text(kind, "kind", 64).strip().lower()
        title = _normalize_title(title)
        source = _bounded_text(source, "source", 64).strip().lower()
        owner = owner.validated()
        idempotency_key = _validate_idempotency_key(idempotency_key)
        source_session_key = _optional_text(
            source_session_key, "source_session_key", 512
        )
        runtime_session_id = _optional_text(
            runtime_session_id, "runtime_session_id", 512
        )
        summary = _optional_text(summary, "summary", 4_000)
        prompt_preview = _optional_text(prompt_preview, "prompt_preview", 1_000)
        runtime_summary_json = canonical_public_json(
            runtime_summary, max_bytes=16 * 1024, field="runtime summary"
        )
        run_runtime_json = canonical_public_json(
            run_runtime, max_bytes=16 * 1024, field="run runtime"
        )
        job_id = validate_work_id(job_id or new_work_id("job"), "job")
        run_id = validate_work_id(run_id or new_work_id("run"), "run")
        mutation_id = validate_work_id(mutation_id or new_work_id("mut"), "mut")
        timestamp = _now_seconds(now if now is not None else self._clock())
        request_hash = hash_job_create_envelope(kind=kind, title=title)

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            existing = self._idempotency_row(conn, "job.create", idempotency_key)
            replay = self._check_existing_idempotency(
                existing, request_hash=request_hash
            )
            if replay is not None:
                result = dict(replay)
                result["replayed"] = True
                return result

            conn.execute(
                "INSERT INTO idempotency_keys("
                "operation, idempotency_key, request_hash, state, subject_id, response_json, "
                "created_at, updated_at) VALUES ('job.create', ?, ?, 'reserved', ?, NULL, ?, ?)",
                (idempotency_key, request_hash, job_id, timestamp, timestamp),
            )
            try:
                conn.execute(
                    "INSERT INTO jobs("
                    "job_id, version, kind, status, title, summary, source, source_session_key, "
                    "runtime_session_id, prompt_preview, current_run_id, attempt_count, "
                    "runtime_summary_json, result_json, result_omitted_reason, error_json, "
                    "open_attention_count, created_at, started_at, updated_at, finished_at, "
                    "cancel_requested_at"
                    ") VALUES (?, 1, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, 1, ?, NULL, NULL, "
                    "NULL, 0, ?, NULL, ?, NULL, NULL)",
                    (
                        job_id,
                        kind,
                        title,
                        summary,
                        source,
                        source_session_key,
                        runtime_session_id,
                        prompt_preview,
                        run_id,
                        runtime_summary_json,
                        timestamp,
                        timestamp,
                    ),
                )
                conn.execute(
                    "INSERT INTO job_runs("
                    "run_id, job_id, attempt, version, status, runtime_json, owner_boot_token, "
                    "owner_pid, owner_start_token, owner_generation, claim_token, claimed_at, "
                    "started_at, updated_at, finished_at, result_json, error_json"
                    ") VALUES (?, ?, 1, 1, 'queued', ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, "
                    "NULL, NULL, NULL)",
                    (
                        run_id,
                        job_id,
                        run_runtime_json,
                        owner.boot_token,
                        owner.pid,
                        owner.start_token,
                        owner.generation,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkStoreSchemaError("generated Job or Run identity collided") from exc
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            assert row is not None
            public_job = self._job_public(conn, row)
            self._append_event(
                conn,
                event_type="job.created",
                subject_type="job",
                subject_id=job_id,
                subject_version=1,
                subject=public_job,
                job_id=job_id,
                run_id=run_id,
                tombstone=False,
                created_at=timestamp,
            )
            receipt: dict[str, Any] = {
                "mutation_id": mutation_id,
                "replayed": False,
                "job": public_job,
                "runtime_started": False,
            }
            response_json = canonical_public_json(
                receipt, field="job mutation receipt"
            )
            conn.execute(
                "UPDATE idempotency_keys SET state='finalized', response_json=?, updated_at=? "
                "WHERE operation='job.create' AND idempotency_key=?",
                (response_json, timestamp, idempotency_key),
            )
            return receipt

        return self._write(mutate)

    def get_job(self, job_id: str, *, detail: bool = True) -> dict[str, Any]:
        job_id = validate_work_id(job_id, "job")
        with self._read() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise WorkNotFound(f"Job {job_id} not found")
            return self._job_public(conn, row, detail=detail)

    def list_jobs(
        self,
        *,
        statuses: Sequence[str] | None = None,
        kinds: Sequence[str] | None = None,
        source_session_key: str | None = None,
        limit: int = 100,
        before: tuple[float, str] | None = None,
        _include_cursor: bool = False,
    ) -> (
        list[dict[str, Any]]
        | tuple[list[dict[str, Any]], tuple[float, str] | None]
    ):
        limit = _bounded_limit(limit, maximum=100)
        clauses: list[str] = []
        params: list[Any] = []
        if statuses is not None:
            normalized = tuple(_bounded_text(v, "status", 32) for v in statuses)
            if not normalized:
                return ([], None) if _include_cursor else []
            unknown = set(normalized) - set(JOB_TRANSITIONS)
            if unknown:
                raise InvalidPublicData(f"unknown Job status: {sorted(unknown)[0]}")
            clauses.append("status IN (%s)" % ",".join("?" for _ in normalized))
            params.extend(normalized)
        if kinds is not None:
            normalized_kinds = tuple(_bounded_text(v, "kind", 64) for v in kinds)
            if not normalized_kinds:
                return ([], None) if _include_cursor else []
            clauses.append("kind IN (%s)" % ",".join("?" for _ in normalized_kinds))
            params.extend(normalized_kinds)
        if source_session_key is not None:
            clauses.append("source_session_key=?")
            params.append(_bounded_text(source_session_key, "source_session_key", 512))
        if before is not None:
            before_time, before_id = before
            before_time = _now_seconds(before_time)
            before_id = validate_work_id(before_id, "job")
            clauses.append("(updated_at < ? OR (updated_at = ? AND job_id < ?))")
            params.extend((before_time, before_time, before_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT * FROM jobs" + where + " ORDER BY updated_at DESC, job_id DESC LIMIT ?"
        )
        params.append(limit)
        with self._read() as conn:
            rows = list(conn.execute(sql, params))
            items = [self._job_public(conn, row) for row in rows]
            if not _include_cursor:
                return items
            cursor = (
                (float(rows[-1]["updated_at"]), str(rows[-1]["job_id"]))
                if rows
                else None
            )
            return items, cursor

    def transition_job(
        self,
        job_id: str,
        *,
        expected_version: int,
        next_status: str,
        event_type: str = "job.status_changed",
        summary: str | None | object = None,
        result: Any = None,
        error: Any = None,
        result_omitted_reason: str | None = None,
        claim_token: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """CAS the current Job and Run, then append one self-contained event."""
        job_id = validate_work_id(job_id, "job")
        expected_version = _positive_int(expected_version, "expected_version")
        next_status = _bounded_text(next_status, "next_status", 32)
        if next_status not in JOB_TRANSITIONS:
            raise InvalidTransition(f"unknown Job status: {next_status}")
        event_type = _bounded_text(event_type, "event_type", 128)
        if summary is not None:
            summary = _optional_text(summary, "summary", 4_000)
        result_json = (
            canonical_public_json(result, max_bytes=DETAIL_JSON_MAX_BYTES, field="Job result")
            if result is not None
            else None
        )
        error_json = (
            canonical_public_json(error, max_bytes=DETAIL_JSON_MAX_BYTES, field="Job error")
            if error is not None
            else None
        )
        result_omitted_reason = _optional_text(
            result_omitted_reason, "result_omitted_reason", 128
        )
        if result_json is not None and result_omitted_reason is not None:
            raise InvalidPublicData("Job result must be omitted when an omission reason is set")
        if (
            result_json is not None
            or error_json is not None
            or result_omitted_reason is not None
        ) and next_status not in JOB_TERMINAL_STATES:
            raise InvalidPublicData("durable result/error fields require a terminal Job state")
        claim_token = _optional_text(claim_token, "claim_token", 512)
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            job = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if job is None:
                raise WorkNotFound(f"Job {job_id} not found")
            if int(job["version"]) != expected_version:
                raise VersionConflict(
                    f"Job {job_id} is version {job['version']}, expected {expected_version}"
                )
            current = str(job["status"])
            if next_status not in JOB_TRANSITIONS[current]:
                raise InvalidTransition(f"Job cannot transition {current} -> {next_status}")
            run_id = job["current_run_id"]
            run = self._load_run_row(conn, run_id)
            if run is None:
                raise WorkStoreSchemaError("Job has no current Run")
            if str(run["status"]) != current:
                raise WorkStoreSchemaError("Job and current Run status diverged")

            started_at = timestamp if next_status == "running" and job["started_at"] is None else job["started_at"]
            finished_at = timestamp if next_status in JOB_TERMINAL_STATES else job["finished_at"]
            cancel_requested_at = (
                timestamp if next_status == "cancel_requested" else job["cancel_requested_at"]
            )
            claimed_at = (
                timestamp if next_status == "claimed" and run["claimed_at"] is None else run["claimed_at"]
            )
            run_started_at = (
                timestamp if next_status == "running" and run["started_at"] is None else run["started_at"]
            )
            run_finished_at = timestamp if next_status in JOB_TERMINAL_STATES else run["finished_at"]

            updated = conn.execute(
                "UPDATE jobs SET status=?, version=version+1, summary=COALESCE(?, summary), "
                "result_json=CASE WHEN ? THEN NULL ELSE COALESCE(?, result_json) END, "
                "result_omitted_reason=COALESCE(?, result_omitted_reason), "
                "error_json=COALESCE(?, error_json), started_at=?, updated_at=?, finished_at=?, "
                "cancel_requested_at=? WHERE job_id=? AND version=? AND status=?",
                (
                    next_status,
                    summary,
                    int(result_omitted_reason is not None),
                    result_json,
                    result_omitted_reason,
                    error_json,
                    started_at,
                    timestamp,
                    finished_at,
                    cancel_requested_at,
                    job_id,
                    expected_version,
                    current,
                ),
            )
            if updated.rowcount != 1:
                raise VersionConflict(f"Job {job_id} changed during transition")
            run_updated = conn.execute(
                "UPDATE job_runs SET status=?, version=version+1, claim_token=COALESCE(?, claim_token), "
                "claimed_at=?, started_at=?, updated_at=?, finished_at=?, "
                "result_json=CASE WHEN ? THEN NULL ELSE COALESCE(?, result_json) END, "
                "error_json=COALESCE(?, error_json) "
                "WHERE run_id=? AND version=? AND status=?",
                (
                    next_status,
                    claim_token,
                    claimed_at,
                    run_started_at,
                    timestamp,
                    run_finished_at,
                    int(result_omitted_reason is not None),
                    result_json,
                    error_json,
                    run_id,
                    int(run["version"]),
                    current,
                ),
            )
            if run_updated.rowcount != 1:
                raise VersionConflict(f"Run {run_id} changed during transition")
            new_row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            assert new_row is not None
            public = self._job_public(conn, new_row)
            self._append_event(
                conn,
                event_type=event_type,
                subject_type="job",
                subject_id=job_id,
                subject_version=int(new_row["version"]),
                subject=public,
                job_id=job_id,
                run_id=str(run_id),
                tombstone=False,
                created_at=timestamp,
            )
            return public

        return self._write(mutate)

    def cancel_job(
        self,
        job_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        owner: RuntimeOwner,
        mutation_id: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Atomically CAS creator-owned cancellation and finalize its receipt."""

        job_id = validate_work_id(job_id, "job")
        expected_version = _positive_int(expected_version, "expected_version")
        idempotency_key = _validate_idempotency_key(idempotency_key)
        owner = owner.validated()
        mutation_id = validate_work_id(mutation_id or new_work_id("mut"), "mut")
        timestamp = _now_seconds(now if now is not None else self._clock())
        request_hash = hash_job_cancel_envelope(
            job_id=job_id,
            expected_version=expected_version,
        )

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            existing = self._idempotency_row(conn, "job.cancel", idempotency_key)
            replay = self._check_existing_idempotency(
                existing,
                request_hash=request_hash,
            )
            if replay is not None:
                receipt = dict(replay)
                receipt["replayed"] = True
                return receipt

            job = conn.execute(
                "SELECT * FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if job is None:
                raise WorkNotFound(f"Job {job_id} not found")
            current = str(job["status"])
            run = self._load_run_row(conn, job["current_run_id"])
            if run is None:
                raise WorkStoreSchemaError("Job has no current Run")
            if str(run["status"]) != current:
                raise WorkStoreSchemaError("Job and current Run status diverged")
            if (
                str(run["owner_boot_token"]) != owner.boot_token
                or int(run["owner_pid"]) != owner.pid
                or str(run["owner_start_token"]) != owner.start_token
                or str(run["owner_generation"]) != owner.generation
            ):
                raise RuntimeOwnerMismatch(
                    "Job belongs to a different runtime owner"
                )

            current_version = int(job["version"])
            if current in JOB_TERMINAL_STATES:
                if current_version not in {expected_version, expected_version + 1}:
                    raise VersionConflict(
                        f"Job {job_id} is version {current_version}, "
                        f"expected {expected_version}"
                    )
                conn.execute(
                    "INSERT INTO idempotency_keys("
                    "operation, idempotency_key, request_hash, state, subject_id, "
                    "response_json, created_at, updated_at) "
                    "VALUES ('job.cancel', ?, ?, 'reserved', ?, NULL, ?, ?)",
                    (idempotency_key, request_hash, job_id, timestamp, timestamp),
                )
                receipt = {
                    "mutation_id": mutation_id,
                    "replayed": False,
                    "job": self._job_public(conn, job),
                    "runtime_started": False,
                    "newly_cancelled": False,
                }
                response_json = canonical_public_json(
                    receipt,
                    field="Job cancellation receipt",
                )
                conn.execute(
                    "UPDATE idempotency_keys SET state='finalized', response_json=?, "
                    "updated_at=? WHERE operation='job.cancel' AND idempotency_key=? "
                    "AND state='reserved'",
                    (response_json, timestamp, idempotency_key),
                )
                return receipt

            if current_version != expected_version:
                raise VersionConflict(
                    f"Job {job_id} is version {current_version}, expected {expected_version}"
                )
            if "cancel_requested" not in JOB_TRANSITIONS[current]:
                raise InvalidTransition(f"Job cannot transition {current} -> cancel_requested")

            conn.execute(
                "INSERT INTO idempotency_keys("
                "operation, idempotency_key, request_hash, state, subject_id, response_json, "
                "created_at, updated_at) VALUES ('job.cancel', ?, ?, 'reserved', ?, NULL, ?, ?)",
                (idempotency_key, request_hash, job_id, timestamp, timestamp),
            )
            updated = conn.execute(
                "UPDATE jobs SET status='cancel_requested', version=version+1, "
                "updated_at=?, cancel_requested_at=? "
                "WHERE job_id=? AND version=? AND status=?",
                (timestamp, timestamp, job_id, expected_version, current),
            )
            run_updated = conn.execute(
                "UPDATE job_runs SET status='cancel_requested', version=version+1, updated_at=? "
                "WHERE run_id=? AND version=? AND status=?",
                (timestamp, str(run["run_id"]), int(run["version"]), current),
            )
            if updated.rowcount != 1 or run_updated.rowcount != 1:
                raise VersionConflict("Job changed during cancellation")
            new_row = conn.execute(
                "SELECT * FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            assert new_row is not None
            public = self._job_public(conn, new_row)
            self._append_event(
                conn,
                event_type="job.cancel_requested",
                subject_type="job",
                subject_id=job_id,
                subject_version=int(new_row["version"]),
                subject=public,
                job_id=job_id,
                run_id=str(run["run_id"]),
                tombstone=False,
                created_at=timestamp,
            )
            receipt: dict[str, Any] = {
                "mutation_id": mutation_id,
                "replayed": False,
                "job": public,
                "runtime_started": False,
                "newly_cancelled": True,
            }
            response_json = canonical_public_json(
                receipt,
                field="Job cancellation receipt",
            )
            conn.execute(
                "UPDATE idempotency_keys SET state='finalized', response_json=?, updated_at=? "
                "WHERE operation='job.cancel' AND idempotency_key=? AND state='reserved'",
                (response_json, timestamp, idempotency_key),
            )
            return receipt

        return self._write(mutate)

    # ------------------------------------------------------------------
    # Exact-addressed Attention
    # ------------------------------------------------------------------

    def create_attention(
        self,
        *,
        source_session_key: str,
        request_id: str,
        kind: str,
        title: str,
        public_payload: Mapping[str, Any],
        owner: RuntimeOwner,
        waiter_generation: str,
        blocking: bool = True,
        sensitive: bool = False,
        runtime_session_id: str | None = None,
        job_id: str | None = None,
        run_id: str | None = None,
        expires_at: float | None = None,
        attention_id: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        attention_id = validate_work_id(
            attention_id or new_work_id("attn"), "attn"
        )
        source_session_key = _bounded_text(
            source_session_key, "source_session_key", 512
        )
        request_id = _bounded_text(request_id, "request_id", 128)
        if not _SAFE_TOKEN_RE.fullmatch(request_id):
            raise InvalidPublicData("request_id has an invalid format")
        kind = _bounded_text(kind, "kind", 32).strip().lower()
        if kind not in ATTENTION_ACTION_OUTCOMES:
            raise InvalidPublicData("unsupported Attention kind")
        title = _normalize_title(title)
        if not isinstance(blocking, bool) or not isinstance(sensitive, bool):
            raise InvalidPublicData("blocking and sensitive must be booleans")
        payload_json = canonical_public_json(
            public_payload, max_bytes=24 * 1024, field="Attention public payload"
        )
        owner = owner.validated()
        waiter_generation = _bounded_text(
            waiter_generation, "waiter_generation", 512
        )
        runtime_session_id = _optional_text(
            runtime_session_id, "runtime_session_id", 512
        )
        if job_id is not None:
            job_id = validate_work_id(job_id, "job")
        if run_id is not None:
            run_id = validate_work_id(run_id, "run")
        if run_id is not None and job_id is None:
            raise InvalidPublicData("run_id requires job_id")
        timestamp = _now_seconds(now if now is not None else self._clock())
        if expires_at is not None:
            expires_at = _now_seconds(expires_at)
            if expires_at <= timestamp:
                raise InvalidPublicData("expires_at must be later than created_at")

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            job: sqlite3.Row | None = None
            if job_id is not None:
                job = conn.execute(
                    "SELECT * FROM jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                if job is None:
                    raise WorkNotFound(f"Job {job_id} not found")
                if str(job["status"]) in JOB_TERMINAL_STATES:
                    raise InvalidTransition("cannot open Attention for a terminal Job")
                if run_id is not None and str(job["current_run_id"]) != run_id:
                    raise InvalidTransition("Attention Run is not the Job's current Run")
            try:
                conn.execute(
                    "INSERT INTO attention_items("
                    "attention_id, version, job_id, run_id, source_session_key, runtime_session_id, "
                    "request_id, kind, state, blocking, sensitive, title, public_payload_json, "
                    "owner_boot_token, owner_pid, owner_start_token, owner_generation, "
                    "waiter_generation, resolution_token, terminal_reason, created_at, updated_at, "
                    "expires_at, resolved_at"
                    ") VALUES (?, 1, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "NULL, NULL, ?, ?, ?, NULL)",
                    (
                        attention_id,
                        job_id,
                        run_id,
                        source_session_key,
                        runtime_session_id,
                        request_id,
                        kind,
                        int(blocking),
                        int(sensitive),
                        title,
                        payload_json,
                        owner.boot_token,
                        owner.pid,
                        owner.start_token,
                        owner.generation,
                        waiter_generation,
                        timestamp,
                        timestamp,
                        expires_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidTransition(
                    "Attention identity or session request_id already exists"
                ) from exc
            row = conn.execute(
                "SELECT * FROM attention_items WHERE attention_id=?", (attention_id,)
            ).fetchone()
            assert row is not None
            public = self._attention_public(row)
            self._append_event(
                conn,
                event_type="attention.opened",
                subject_type="attention",
                subject_id=attention_id,
                subject_version=1,
                subject=public,
                job_id=job_id,
                run_id=run_id,
                tombstone=False,
                created_at=timestamp,
            )
            if job is not None:
                conn.execute(
                    "UPDATE jobs SET open_attention_count=open_attention_count+1, "
                    "version=version+1, updated_at=? WHERE job_id=? AND version=?",
                    (timestamp, job_id, int(job["version"])),
                )
                updated_job = conn.execute(
                    "SELECT * FROM jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                assert updated_job is not None
                self._append_event(
                    conn,
                    event_type="job.attention_changed",
                    subject_type="job",
                    subject_id=str(job_id),
                    subject_version=int(updated_job["version"]),
                    subject=self._job_public(conn, updated_job),
                    job_id=job_id,
                    run_id=run_id,
                    tombstone=False,
                    created_at=timestamp,
                )
            return public

        return self._write(mutate)

    def get_attention(self, attention_id: str) -> dict[str, Any]:
        attention_id = validate_work_id(attention_id, "attn")
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM attention_items WHERE attention_id=?", (attention_id,)
            ).fetchone()
            if row is None:
                raise WorkNotFound(f"Attention {attention_id} not found")
            return self._attention_public(row)

    def list_attention(
        self,
        *,
        states: Sequence[str] | None = None,
        kinds: Sequence[str] | None = None,
        job_id: str | None = None,
        runtime_session_id: str | None = None,
        limit: int = 100,
        before: tuple[float, str] | None = None,
        _include_cursor: bool = False,
    ) -> (
        list[dict[str, Any]]
        | tuple[list[dict[str, Any]], tuple[float, str] | None]
    ):
        limit = _bounded_limit(limit, maximum=100)
        clauses: list[str] = []
        params: list[Any] = []
        if states is not None:
            normalized = tuple(_bounded_text(v, "state", 32) for v in states)
            if not normalized:
                return ([], None) if _include_cursor else []
            unknown = set(normalized) - set(ATTENTION_TRANSITIONS)
            if unknown:
                raise InvalidPublicData(f"unknown Attention state: {sorted(unknown)[0]}")
            clauses.append("state IN (%s)" % ",".join("?" for _ in normalized))
            params.extend(normalized)
        if kinds is not None:
            normalized_kinds = tuple(_bounded_text(v, "kind", 32) for v in kinds)
            if not normalized_kinds:
                return ([], None) if _include_cursor else []
            clauses.append("kind IN (%s)" % ",".join("?" for _ in normalized_kinds))
            params.extend(normalized_kinds)
        if job_id is not None:
            clauses.append("job_id=?")
            params.append(validate_work_id(job_id, "job"))
        if runtime_session_id is not None:
            clauses.append("runtime_session_id=?")
            params.append(_bounded_text(runtime_session_id, "runtime_session_id", 512))
        if before is not None:
            before_time, before_id = before
            before_time = _now_seconds(before_time)
            before_id = validate_work_id(before_id, "attn")
            clauses.append("(created_at < ? OR (created_at = ? AND attention_id < ?))")
            params.extend((before_time, before_time, before_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT * FROM attention_items" + where
            + " ORDER BY created_at DESC, attention_id DESC LIMIT ?"
        )
        params.append(limit)
        with self._read() as conn:
            rows = list(conn.execute(sql, params))
            items = [self._attention_public(row) for row in rows]
            if not _include_cursor:
                return items
            cursor = (
                (float(rows[-1]["created_at"]), str(rows[-1]["attention_id"]))
                if rows
                else None
            )
            return items, cursor

    def transition_attention(
        self,
        attention_id: str,
        *,
        expected_version: int,
        next_state: str,
        event_type: str = "attention.state_changed",
        terminal_reason: str | None = None,
        resolution_token: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        attention_id = validate_work_id(attention_id, "attn")
        expected_version = _positive_int(expected_version, "expected_version")
        next_state = _bounded_text(next_state, "next_state", 32)
        if next_state not in ATTENTION_TRANSITIONS:
            raise InvalidTransition(f"unknown Attention state: {next_state}")
        event_type = _bounded_text(event_type, "event_type", 128)
        terminal_reason = _optional_text(terminal_reason, "terminal_reason", 256)
        resolution_token = _optional_text(resolution_token, "resolution_token", 512)
        if next_state == "resolving" and resolution_token is None:
            raise InvalidPublicData("resolving Attention requires a resolution_token")
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            return self._transition_attention_in_txn(
                conn,
                attention_id=attention_id,
                expected_version=expected_version,
                next_state=next_state,
                event_type=event_type,
                terminal_reason=terminal_reason,
                resolution_token=resolution_token,
                timestamp=timestamp,
            )

        return self._write(mutate)

    def assert_attention_owner(
        self,
        attention_id: str,
        *,
        owner: RuntimeOwner,
    ) -> str:
        """Return the private waiter generation only for the exact owner."""

        attention_id = validate_work_id(attention_id, "attn")
        owner = owner.validated()
        with self._read() as conn:
            row = conn.execute(
                "SELECT owner_boot_token, owner_pid, owner_start_token, "
                "owner_generation, waiter_generation FROM attention_items "
                "WHERE attention_id=?",
                (attention_id,),
            ).fetchone()
            if row is None:
                raise WorkNotFound(f"Attention {attention_id} not found")
            if (
                str(row["owner_boot_token"]) != owner.boot_token
                or int(row["owner_pid"]) != owner.pid
                or str(row["owner_start_token"]) != owner.start_token
                or str(row["owner_generation"]) != owner.generation
            ):
                raise RuntimeOwnerMismatch(
                    "Attention belongs to a different runtime waiter"
                )
            return str(row["waiter_generation"])

    def terminate_attention_waiter(
        self,
        attention_id: str,
        *,
        expected_version: int,
        owner: RuntimeOwner,
        waiter_generation: str,
        terminal_reason: str,
        pending_state: str = "cancelled",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Close one exact local waiter and make an in-flight receipt uncertain.

        A resolving Attention and its ``attention.respond`` reservation are one
        crash-consistency unit.  Teardown must never commit ``orphaned`` while
        leaving the corresponding receipt ``delivering``.  A waiter that was
        never delivered may close as either ``cancelled`` (lifecycle teardown)
        or ``expired`` (its own response deadline elapsed).
        """

        attention_id = validate_work_id(attention_id, "attn")
        expected_version = _positive_int(expected_version, "expected_version")
        owner = owner.validated()
        waiter_generation = _bounded_text(
            waiter_generation, "waiter_generation", 512
        )
        terminal_reason = _bounded_text(
            terminal_reason, "terminal_reason", 256
        )
        pending_state = _bounded_text(pending_state, "pending_state", 32)
        if pending_state not in {"cancelled", "expired"}:
            raise ValueError("pending_state must be cancelled or expired")
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            row = conn.execute(
                "SELECT * FROM attention_items WHERE attention_id=?",
                (attention_id,),
            ).fetchone()
            if row is None:
                raise WorkNotFound(f"Attention {attention_id} not found")
            if int(row["version"]) != expected_version:
                raise VersionConflict(
                    f"Attention {attention_id} is version {row['version']}, "
                    f"expected {expected_version}"
                )
            if (
                str(row["owner_boot_token"]) != owner.boot_token
                or int(row["owner_pid"]) != owner.pid
                or str(row["owner_start_token"]) != owner.start_token
                or str(row["owner_generation"]) != owner.generation
                or str(row["waiter_generation"]) != waiter_generation
            ):
                raise RuntimeOwnerMismatch(
                    "Attention belongs to a different runtime waiter"
                )
            state = str(row["state"])
            if state not in {"pending", "resolving"}:
                raise AttentionNotActionable(
                    f"Attention is {state}, not pending or resolving"
                )
            lifecycle_timestamp = self._attention_lifecycle_timestamp(row, timestamp)
            next_state = pending_state if state == "pending" else "orphaned"
            public = self._transition_attention_in_txn(
                conn,
                attention_id=attention_id,
                expected_version=expected_version,
                next_state=next_state,
                event_type=f"attention.{next_state}",
                terminal_reason=terminal_reason,
                resolution_token=None,
                timestamp=lifecycle_timestamp,
            )
            if state == "resolving":
                updated = conn.execute(
                    "UPDATE idempotency_keys SET state='uncertain', "
                    "response_json=NULL, updated_at=? "
                    "WHERE operation='attention.respond' AND subject_id=? "
                    "AND state IN ('reserved','delivering')",
                    (lifecycle_timestamp, attention_id),
                )
                if updated.rowcount != 1:
                    raise WorkStoreSchemaError(
                        "resolving Attention must have one nonfinal response receipt"
                    )
            return public

        return self._write(mutate)

    @staticmethod
    def _attention_lifecycle_timestamp(row: sqlite3.Row, timestamp: float) -> float:
        """Keep one Attention's public lifecycle time nondecreasing."""

        try:
            created_at = _now_seconds(float(row["created_at"]))
            updated_at = _now_seconds(float(row["updated_at"]))
        except (TypeError, ValueError) as exc:
            raise WorkStoreSchemaError("Attention lifecycle timestamps are invalid") from exc
        return max(timestamp, created_at, updated_at)

    def _transition_attention_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        attention_id: str,
        expected_version: int,
        next_state: str,
        event_type: str,
        terminal_reason: str | None,
        resolution_token: str | None,
        timestamp: float,
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM attention_items WHERE attention_id=?", (attention_id,)
        ).fetchone()
        if row is None:
            raise WorkNotFound(f"Attention {attention_id} not found")
        if int(row["version"]) != expected_version:
            raise VersionConflict(
                f"Attention {attention_id} is version {row['version']}, expected {expected_version}"
            )
        current = str(row["state"])
        if next_state not in ATTENTION_TRANSITIONS[current]:
            raise InvalidTransition(f"Attention cannot transition {current} -> {next_state}")
        # The wall clock can move backwards between opening an Attention and
        # resolving it. Keep lifecycle time monotonic at the row boundary so
        # terminal retention can use one indexed final-time predicate without
        # deleting a newly opened item or scanning an unbounded residual set.
        timestamp = self._attention_lifecycle_timestamp(row, timestamp)
        terminal = next_state in ATTENTION_TERMINAL_STATES
        token = resolution_token if next_state == "resolving" else row["resolution_token"]
        updated = conn.execute(
            "UPDATE attention_items SET state=?, version=version+1, resolution_token=?, "
            "terminal_reason=?, updated_at=?, resolved_at=? "
            "WHERE attention_id=? AND version=? AND state=?",
            (
                next_state,
                token,
                terminal_reason,
                timestamp,
                timestamp if terminal else None,
                attention_id,
                expected_version,
                current,
            ),
        )
        if updated.rowcount != 1:
            raise VersionConflict(f"Attention {attention_id} changed during transition")
        new_row = conn.execute(
            "SELECT * FROM attention_items WHERE attention_id=?", (attention_id,)
        ).fetchone()
        assert new_row is not None
        public = self._attention_public(new_row)
        self._append_event(
            conn,
            event_type=event_type,
            subject_type="attention",
            subject_id=attention_id,
            subject_version=int(new_row["version"]),
            subject=public,
            job_id=new_row["job_id"],
            run_id=new_row["run_id"],
            tombstone=False,
            created_at=timestamp,
        )
        if terminal and new_row["job_id"] is not None:
            job = conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (new_row["job_id"],)
            ).fetchone()
            if job is not None:
                if int(job["open_attention_count"]) < 1:
                    raise WorkStoreSchemaError("Job open_attention_count underflow")
                conn.execute(
                    "UPDATE jobs SET open_attention_count=open_attention_count-1, "
                    "version=version+1, updated_at=? WHERE job_id=? AND version=?",
                    (timestamp, new_row["job_id"], int(job["version"])),
                )
                updated_job = conn.execute(
                    "SELECT * FROM jobs WHERE job_id=?", (new_row["job_id"],)
                ).fetchone()
                assert updated_job is not None
                self._append_event(
                    conn,
                    event_type="job.attention_changed",
                    subject_type="job",
                    subject_id=str(new_row["job_id"]),
                    subject_version=int(updated_job["version"]),
                    subject=self._job_public(conn, updated_job),
                    job_id=str(new_row["job_id"]),
                    run_id=new_row["run_id"],
                    tombstone=False,
                    created_at=timestamp,
                )
        return public

    def begin_attention_resolution(
        self,
        attention_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        kind: str,
        action: str,
        owner: RuntimeOwner,
        waiter_generation: str,
        resolution_token: str | None = None,
        now: float | None = None,
    ) -> AttentionResolutionClaim:
        """Atomically reserve a sanitized response and CAS pending -> resolving."""
        attention_id = validate_work_id(attention_id, "attn")
        expected_version = _positive_int(expected_version, "expected_version")
        idempotency_key = _validate_idempotency_key(idempotency_key)
        kind = _bounded_text(kind, "kind", 32).strip().lower()
        action = _bounded_text(action, "action", 64).strip().lower()
        terminal_state = _attention_outcome(kind, action)
        owner = owner.validated()
        waiter_generation = _bounded_text(
            waiter_generation, "waiter_generation", 512
        )
        resolution_token = _bounded_text(
            resolution_token or uuid.uuid4().hex, "resolution_token", 512
        )
        request_hash = hash_attention_response_envelope(
            attention_id=attention_id,
            expected_version=expected_version,
            kind=kind,
            action=action,
        )
        binding_json = canonical_public_json(
            {
                "action": action,
                "expected_version": expected_version,
                "kind": kind,
                "terminal_state": terminal_state,
            },
            field="Attention resolution binding",
        )
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> AttentionResolutionClaim:
            existing = self._idempotency_row(
                conn, "attention.respond", idempotency_key
            )
            if existing is not None:
                if str(existing["request_hash"]) != request_hash:
                    raise IdempotencyConflict(
                        "idempotency key was reused for a different public envelope"
                    )
                binding = self._attention_resolution_binding(existing)
                if str(binding["attention_id"]) != attention_id:
                    raise IdempotencyConflict(
                        "idempotency key belongs to a different Attention"
                    )
                existing_state = str(existing["state"])
                if existing_state == "finalized":
                    replay = _json_load(existing["response_json"])
                    if not isinstance(replay, dict):
                        raise WorkStoreSchemaError(
                            "finalized Attention receipt must be an object"
                        )
                    if replay.get("state") != binding["terminal_state"]:
                        raise WorkStoreSchemaError(
                            "finalized Attention receipt violates its action binding"
                        )
                    replay = dict(replay)
                    replay["replayed"] = True
                    return AttentionResolutionClaim(
                        attention_id=attention_id,
                        attention_version=int(replay["attention_version"]),
                        operation="attention.respond",
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        resolution_token=None,
                        replayed=True,
                        receipt=replay,
                    )
                if existing_state not in {"reserved", "delivering"}:
                    raise AttentionNotActionable(
                        f"Attention response is {existing_state} and cannot be replayed"
                    )
            row = conn.execute(
                "SELECT * FROM attention_items WHERE attention_id=?", (attention_id,)
            ).fetchone()
            if row is None:
                raise WorkNotFound(f"Attention {attention_id} not found")
            if str(row["kind"]) != kind:
                raise AttentionNotActionable("Attention kind does not match response")
            if (
                str(row["owner_boot_token"]) != owner.boot_token
                or int(row["owner_pid"]) != owner.pid
                or str(row["owner_start_token"]) != owner.start_token
                or str(row["owner_generation"]) != owner.generation
                or str(row["waiter_generation"]) != waiter_generation
            ):
                raise RuntimeOwnerMismatch("Attention belongs to a different runtime waiter")
            if existing is not None and str(existing["state"]) == "delivering":
                if str(row["state"]) != "resolving" or not row["resolution_token"]:
                    raise AttentionNotActionable(
                        "in-flight response no longer owns a resolving Attention"
                    )
                return AttentionResolutionClaim(
                    attention_id=attention_id,
                    attention_version=int(row["version"]),
                    operation="attention.respond",
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    resolution_token=str(row["resolution_token"]),
                    replayed=False,
                )
            if existing is not None:
                # ``reserved`` and pending cannot normally coexist because the
                # reservation and pending->resolving CAS share this transaction.
                # Treat externally-corrupted/interrupted evidence as in-flight,
                # never as permission to create a second claim.
                raise WorkOperationInProgress(
                    "Attention response reservation has not reached delivery"
                )
            if int(row["version"]) != expected_version:
                raise VersionConflict(
                    f"Attention {attention_id} is version {row['version']}, expected {expected_version}"
                )
            if str(row["state"]) != "pending":
                raise AttentionNotActionable(
                    f"Attention is {row['state']}, not pending"
                )
            lifecycle_timestamp = self._attention_lifecycle_timestamp(row, timestamp)
            conn.execute(
                "INSERT INTO idempotency_keys("
                "operation, idempotency_key, request_hash, state, subject_id, binding_json, "
                "response_json, created_at, updated_at) "
                "VALUES ('attention.respond', ?, ?, 'reserved', ?, ?, NULL, ?, ?)",
                (
                    idempotency_key,
                    request_hash,
                    attention_id,
                    binding_json,
                    lifecycle_timestamp,
                    lifecycle_timestamp,
                ),
            )
            public = self._transition_attention_in_txn(
                conn,
                attention_id=attention_id,
                expected_version=expected_version,
                next_state="resolving",
                event_type="attention.resolution_started",
                terminal_reason=None,
                resolution_token=resolution_token,
                timestamp=lifecycle_timestamp,
            )
            conn.execute(
                "UPDATE idempotency_keys SET state='delivering', updated_at=? "
                "WHERE operation='attention.respond' AND idempotency_key=? AND state='reserved'",
                (lifecycle_timestamp, idempotency_key),
            )
            return AttentionResolutionClaim(
                attention_id=attention_id,
                attention_version=int(public["version"]),
                operation="attention.respond",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resolution_token=resolution_token,
                replayed=False,
            )

        return self._write(mutate)

    def finalize_attention_resolution(
        self,
        claim: AttentionResolutionClaim,
        *,
        state: str,
        delivered: bool,
        terminal_reason: str | None = None,
        mutation_id: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Finalize a delivered response without ever accepting its raw value."""
        if not isinstance(claim, AttentionResolutionClaim):
            raise InvalidPublicData("claim must be an AttentionResolutionClaim")
        attention_id = validate_work_id(claim.attention_id, "attn")
        operation = _validate_operation(claim.operation)
        if operation != "attention.respond":
            raise InvalidPublicData("claim operation must be attention.respond")
        idempotency_key = _validate_idempotency_key(claim.idempotency_key)
        if not isinstance(claim.request_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", claim.request_hash
        ):
            raise InvalidPublicData("claim request_hash must be a lowercase SHA-256 digest")
        state = _bounded_text(state, "state", 32).strip().lower()
        if state not in {"resolved", "denied", "orphaned"}:
            raise InvalidTransition("resolution final state must be resolved, denied, or orphaned")
        if not isinstance(delivered, bool):
            raise InvalidPublicData("delivered must be a boolean")
        if state in {"resolved", "denied"} and not delivered:
            raise InvalidPublicData("resolved or denied requires accepted waiter delivery")
        if state == "orphaned" and delivered:
            raise InvalidPublicData("orphaned resolution cannot report delivered")
        mutation_id = validate_work_id(mutation_id or new_work_id("mut"), "mut")
        terminal_reason = _optional_text(terminal_reason, "terminal_reason", 256)
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            idempotency = self._idempotency_row(
                conn, operation, idempotency_key
            )
            if idempotency is None:
                raise WorkNotFound("Attention response reservation not found")
            if str(idempotency["request_hash"]) != claim.request_hash:
                raise IdempotencyConflict("Attention response envelope changed")
            binding = self._attention_resolution_binding(idempotency)
            if str(binding["attention_id"]) != attention_id:
                raise IdempotencyConflict(
                    "Attention response reservation belongs to a different Attention"
                )
            terminal_state = str(binding["terminal_state"])
            if str(idempotency["state"]) == "finalized":
                if state != terminal_state:
                    raise InvalidTransition(
                        f"{binding['kind']} action {binding['action']} must finalize as "
                        f"{terminal_state}, not {state}"
                    )
                response = _json_load(idempotency["response_json"])
                if not isinstance(response, dict):
                    raise WorkStoreSchemaError("finalized Attention receipt is malformed")
                if response.get("state") != terminal_state:
                    raise WorkStoreSchemaError(
                        "finalized Attention receipt violates its action binding"
                    )
                response = dict(response)
                response["replayed"] = True
                return response
            if str(idempotency["state"]) != "delivering":
                raise AttentionNotActionable(
                    f"Attention response is {idempotency['state']}, not delivering"
                )
            if state not in {terminal_state, "orphaned"}:
                raise InvalidTransition(
                    f"{binding['kind']} action {binding['action']} must finalize as "
                    f"{terminal_state}, not {state}"
                )
            row = conn.execute(
                "SELECT * FROM attention_items WHERE attention_id=?",
                (attention_id,),
            ).fetchone()
            if row is None:
                raise WorkNotFound(f"Attention {attention_id} not found")
            if str(row["state"]) != "resolving":
                raise AttentionNotActionable(
                    f"Attention is {row['state']}, not resolving"
                )
            if str(row["resolution_token"]) != str(claim.resolution_token):
                raise AttentionNotActionable("resolution token does not own this Attention")
            lifecycle_timestamp = self._attention_lifecycle_timestamp(row, timestamp)
            public = self._transition_attention_in_txn(
                conn,
                attention_id=attention_id,
                expected_version=int(row["version"]),
                next_state=state,
                event_type="attention.resolved" if state != "orphaned" else "attention.orphaned",
                terminal_reason=terminal_reason,
                resolution_token=None,
                timestamp=lifecycle_timestamp,
            )
            if state == "orphaned":
                conn.execute(
                    "UPDATE idempotency_keys SET state='uncertain', response_json=NULL, updated_at=? "
                    "WHERE operation=? AND idempotency_key=? AND state='delivering'",
                    (lifecycle_timestamp, operation, idempotency_key),
                )
                return {
                    "attention_id": attention_id,
                    "attention_version": int(public["version"]),
                    "state": "orphaned",
                    "delivered": False,
                    "replayed": False,
                }
            receipt: dict[str, Any] = {
                "mutation_id": mutation_id,
                "replayed": False,
                "attention_id": attention_id,
                "attention_version": int(public["version"]),
                "state": state,
                "delivered": delivered,
            }
            response_json = canonical_public_json(
                receipt, field="Attention mutation receipt"
            )
            conn.execute(
                "UPDATE idempotency_keys SET state='finalized', response_json=?, updated_at=? "
                "WHERE operation=? AND idempotency_key=? AND state='delivering'",
                (
                    response_json,
                    lifecycle_timestamp,
                    operation,
                    idempotency_key,
                ),
            )
            return receipt

        return self._write(mutate)

    # ------------------------------------------------------------------
    # Ordered public events and cursor primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _cursor_state(conn: sqlite3.Connection) -> tuple[str, int, int]:
        meta = {
            str(row[0]): str(row[1])
            for row in conn.execute(
                "SELECT key, value FROM work_meta WHERE key IN ('ledger_id', 'event_floor')"
            )
        }
        try:
            ledger_id = validate_work_id(meta["ledger_id"], "ledger")
            event_floor = int(meta["event_floor"])
        except (KeyError, ValueError) as exc:
            raise WorkStoreSchemaError("work cursor metadata is invalid") from exc
        row = conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM work_events").fetchone()
        # When retention deletes every row, MAX() falls back to zero even
        # though the cursor namespace has advanced.  ``event_floor - 1`` is
        # the retained empty-stream high-water until AUTOINCREMENT emits the
        # next event.
        high_water = max(int(row[0]) if row is not None else 0, event_floor - 1)
        return ledger_id, event_floor, high_water

    def cursor_state(self) -> dict[str, int | str]:
        """Return the current event namespace without loading projections."""

        with self._read() as conn:
            ledger_id, event_floor, high_water = self._cursor_state(conn)
            return {
                "ledger_id": ledger_id,
                "event_floor": event_floor,
                "high_water": high_water,
            }

    def list_events(
        self,
        *,
        after: int = 0,
        limit: int = 500,
        job_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(after, int) or isinstance(after, bool) or after < 0:
            raise InvalidPublicData("after must be a non-negative integer")
        limit = _bounded_limit(limit, maximum=500)
        if job_id is not None:
            job_id = validate_work_id(job_id, "job")
        with self._read() as conn:
            _, floor, high_water = self._cursor_state(conn)
            if after < floor - 1 or after > high_water:
                raise CursorExpired(
                    "event cursor is outside the retained ledger range",
                    data={"event_floor": floor, "high_water": high_water},
                )
            if job_id is None:
                rows = conn.execute(
                    "SELECT * FROM work_events WHERE event_id>? "
                    "ORDER BY event_id ASC LIMIT ?",
                    (after, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM work_events WHERE job_id=? AND event_id>? "
                    "ORDER BY event_id ASC LIMIT ?",
                    (job_id, after, limit),
                ).fetchall()
            return [self._event_public(row) for row in rows]

    def sync_delta(
        self,
        *,
        ledger_id: str,
        after: int,
        limit: int = 500,
        max_bytes: int = SYNC_MAX_BYTES,
    ) -> dict[str, Any]:
        """Read one fixed-watermark, count- and byte-bounded event page."""
        ledger_id = validate_work_id(ledger_id, "ledger")
        if not isinstance(after, int) or isinstance(after, bool) or after < 0:
            raise InvalidPublicData("after must be a non-negative integer")
        limit = _bounded_limit(limit, maximum=500)
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes < PUBLIC_JSON_MAX_BYTES
            or max_bytes > SYNC_MAX_BYTES
        ):
            raise InvalidPublicData(
                f"max_bytes must be between {PUBLIC_JSON_MAX_BYTES} and {SYNC_MAX_BYTES}"
            )
        with self._read() as conn:
            current_ledger, floor, watermark = self._cursor_state(conn)
            if ledger_id != current_ledger:
                raise CursorExpired(
                    "ledger_id changed; discard the projection and bootstrap",
                    data={"ledger_id": current_ledger, "bootstrap": True},
                )
            if after < floor - 1 or after > watermark:
                raise CursorExpired(
                    "event cursor is outside the retained ledger range",
                    data={
                        "ledger_id": current_ledger,
                        "event_floor": floor,
                        "high_water": watermark,
                        "bootstrap": True,
                    },
                )
            # Fetch one extra row to identify a count truncation without a
            # second query.  The read transaction fixes ``watermark``.
            rows = conn.execute(
                "SELECT * FROM work_events WHERE event_id>? AND event_id<=? "
                "ORDER BY event_id ASC LIMIT ?",
                (after, watermark, limit + 1),
            ).fetchall()
            base_page: dict[str, Any] = {
                "contract": {
                    "name": "fabric.work",
                    "version": 1,
                    "min_compatible": 1,
                },
                "ledger_id": current_ledger,
                "mode": "delta",
                "watermark": watermark,
                "cursor": after,
                "has_more": False,
                "next_page_token": None,
                "jobs": [],
                "attention": [],
                "events": [],
            }
            events: list[dict[str, Any]] = []
            used = len(
                canonical_public_json(
                    base_page, max_bytes=max_bytes, field="sync page envelope"
                ).encode("utf-8")
            ) + 64  # cursor digit growth + conservative envelope slack
            count_truncated = len(rows) > limit
            for row in rows[:limit]:
                event = self._event_public(row)
                event_size = len(
                    canonical_public_json(event, field="sync event").encode("utf-8")
                )
                addition = event_size + (1 if events else 0)
                if events and used + addition > max_bytes:
                    break
                if not events and used + addition > max_bytes:
                    raise InvalidPublicData(
                        "max_bytes is too small for the next bounded work event"
                    )
                events.append(event)
                used += addition
            byte_truncated = len(events) < min(len(rows), limit)
            if events:
                cursor = int(events[-1]["event_id"])
            else:
                cursor = watermark if after == watermark else after
            has_more = cursor < watermark and (count_truncated or byte_truncated or bool(rows))
            if not has_more:
                cursor = watermark
            page = dict(base_page)
            page.update({"cursor": cursor, "has_more": has_more, "events": events})
            canonical_public_json(page, max_bytes=max_bytes, field="sync page")
            return page

    def bootstrap_subject_page(
        self,
        *,
        subject_type: str,
        watermark: int | None = None,
        event_floor: int | None = None,
        after_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Keyset-page frozen bootstrap membership with constant query count.

        Membership is derived from each subject's last self-contained event at
        or below the first page's watermark.  Writes after that watermark may
        make a returned row's version newer, but cannot add a newly-created
        subject to later pages; its create/update event arrives in the delta.
        Rows whose entire event history predates retention are conservatively
        included.  Any retention-floor movement during the short bootstrap
        invalidates the token so that fallback cannot shift membership.
        """

        if subject_type not in {"job", "attention"}:
            raise InvalidPublicData("subject_type must be job or attention")
        if watermark is not None and (
            not isinstance(watermark, int)
            or isinstance(watermark, bool)
            or watermark < 0
        ):
            raise InvalidPublicData("watermark must be a non-negative integer")
        if event_floor is not None and (
            not isinstance(event_floor, int)
            or isinstance(event_floor, bool)
            or event_floor < 1
        ):
            raise InvalidPublicData("event_floor must be a positive integer")
        limit = _bounded_limit(limit, maximum=500)
        prefix = "job" if subject_type == "job" else "attn"
        normalized_after = "" if after_id is None else validate_work_id(after_id, prefix)

        with self._read() as conn:
            ledger_id, current_floor, high_water = self._cursor_state(conn)
            fixed_watermark = high_water if watermark is None else watermark
            fixed_floor = current_floor if event_floor is None else event_floor
            if (
                fixed_floor != current_floor
                or fixed_watermark < current_floor - 1
                or fixed_watermark > high_water
            ):
                raise CursorExpired(
                    "bootstrap membership is outside the retained ledger range",
                    data={
                        "ledger_id": ledger_id,
                        "event_floor": current_floor,
                        "high_water": high_water,
                        "bootstrap": True,
                    },
                )

            if subject_type == "job":
                rows = conn.execute(
                    "WITH latest_ids AS ("
                    " SELECT subject_id, MAX(event_id) AS event_id FROM work_events"
                    " WHERE subject_type='job' AND event_id<=? GROUP BY subject_id"
                    "), snapshot AS ("
                    " SELECT ids.subject_id,"
                    " COALESCE(json_extract(events.subject_json, '$.status'), '') AS status,"
                    " COALESCE(json_extract(events.subject_json, '$.updated_at'), 0) AS updated_at"
                    " FROM latest_ids AS ids JOIN work_events AS events"
                    " ON events.event_id=ids.event_id WHERE events.tombstone=0"
                    "), eligible AS ("
                    " SELECT subject_id FROM snapshot"
                    " WHERE status NOT IN ('succeeded','failed','cancelled','interrupted')"
                    " UNION ALL SELECT subject_id FROM ("
                    "  SELECT subject_id FROM snapshot"
                    "  WHERE status IN ('succeeded','failed','cancelled','interrupted')"
                    "  ORDER BY updated_at DESC, subject_id DESC LIMIT 100"
                    " )"
                    ") SELECT jobs.* FROM jobs"
                    " WHERE jobs.job_id>? AND ("
                    "  EXISTS (SELECT 1 FROM eligible WHERE eligible.subject_id=jobs.job_id)"
                    "  OR NOT EXISTS (SELECT 1 FROM work_events AS any_event"
                    "    WHERE any_event.subject_type='job'"
                    "    AND any_event.subject_id=jobs.job_id)"
                    " ) ORDER BY jobs.job_id ASC LIMIT ?",
                    (fixed_watermark, normalized_after, limit + 1),
                ).fetchall()
                selected = rows[:limit]
                run_ids = [str(row["current_run_id"]) for row in selected]
                run_rows: dict[str, sqlite3.Row] = {}
                if run_ids:
                    placeholders = ",".join("?" for _ in run_ids)
                    run_rows = {
                        str(row["run_id"]): row
                        for row in conn.execute(
                            f"SELECT * FROM job_runs WHERE run_id IN ({placeholders})",
                            run_ids,
                        )
                    }
                items = [
                    self._job_public_with_run(
                        row,
                        run_rows.get(str(row["current_run_id"])),
                    )
                    for row in selected
                ]
            else:
                rows = conn.execute(
                    "WITH latest_ids AS ("
                    " SELECT subject_id, MAX(event_id) AS event_id FROM work_events"
                    " WHERE subject_type='attention' AND event_id<=? GROUP BY subject_id"
                    "), snapshot AS ("
                    " SELECT ids.subject_id,"
                    " COALESCE(json_extract(events.subject_json, '$.state'), '') AS state,"
                    " COALESCE(json_extract(events.subject_json, '$.updated_at'), 0) AS updated_at"
                    " FROM latest_ids AS ids JOIN work_events AS events"
                    " ON events.event_id=ids.event_id WHERE events.tombstone=0"
                    "), eligible AS ("
                    " SELECT subject_id FROM snapshot"
                    " WHERE state IN ('pending','resolving')"
                    " UNION ALL SELECT subject_id FROM ("
                    "  SELECT subject_id FROM snapshot"
                    "  WHERE state NOT IN ('pending','resolving')"
                    "  ORDER BY updated_at DESC, subject_id DESC LIMIT 100"
                    " )"
                    ") SELECT attention_items.* FROM attention_items"
                    " WHERE attention_items.attention_id>? AND ("
                    "  EXISTS (SELECT 1 FROM eligible"
                    "    WHERE eligible.subject_id=attention_items.attention_id)"
                    "  OR NOT EXISTS (SELECT 1 FROM work_events AS any_event"
                    "    WHERE any_event.subject_type='attention'"
                    "    AND any_event.subject_id=attention_items.attention_id)"
                    " ) ORDER BY attention_items.attention_id ASC LIMIT ?",
                    (fixed_watermark, normalized_after, limit + 1),
                ).fetchall()
                items = [self._attention_public(row) for row in rows[:limit]]

            return {
                "ledger_id": ledger_id,
                "event_floor": fixed_floor,
                "watermark": fixed_watermark,
                "items": items,
                "has_more": len(rows) > limit,
            }

    def bootstrap_snapshot(
        self,
        *,
        terminal_job_limit: int = 100,
        attention_limit: int = 100,
    ) -> dict[str, Any]:
        """Capture an unpaged transactional bootstrap primitive.

        The JSON-RPC service owns authenticated multi-page tokens and the 1 MiB
        wire budget.  This store primitive gives it a fixed watermark and a
        consistent initial projection without holding a connection afterward.
        """
        terminal_job_limit = _bounded_limit(
            terminal_job_limit, maximum=100, field="terminal_job_limit"
        )
        attention_limit = _bounded_limit(
            attention_limit, maximum=100, field="attention_limit"
        )
        with self._read() as conn:
            ledger_id, floor, watermark = self._cursor_state(conn)
            nonterminal = conn.execute(
                "SELECT * FROM jobs WHERE status NOT IN ('succeeded','failed','cancelled','interrupted') "
                "ORDER BY updated_at DESC, job_id DESC"
            ).fetchall()
            terminal = conn.execute(
                "SELECT * FROM jobs WHERE status IN ('succeeded','failed','cancelled','interrupted') "
                "ORDER BY updated_at DESC, job_id DESC LIMIT ?",
                (terminal_job_limit,),
            ).fetchall()
            open_attention = conn.execute(
                "SELECT * FROM attention_items "
                "WHERE state IN ('pending','resolving') "
                "ORDER BY updated_at DESC, attention_id DESC"
            ).fetchall()
            terminal_attention = conn.execute(
                "SELECT * FROM attention_items "
                "WHERE state NOT IN ('pending','resolving') "
                "ORDER BY updated_at DESC, attention_id DESC LIMIT ?",
                (attention_limit,),
            ).fetchall()
            return {
                "contract": {
                    "name": "fabric.work",
                    "version": 1,
                    "min_compatible": 1,
                },
                "ledger_id": ledger_id,
                "event_floor": floor,
                "watermark": watermark,
                "jobs": [self._job_public(conn, row) for row in (*nonterminal, *terminal)],
                "attention": [
                    self._attention_public(row)
                    for row in (*open_attention, *terminal_attention)
                ],
            }

    # ------------------------------------------------------------------
    # Bounded retention and owner-reconciliation primitives
    # ------------------------------------------------------------------

    def run_retention(
        self,
        *,
        now: float | None = None,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
        event_batch_size: int = 1_000,
        idempotency_batch_size: int = 1_000,
        subject_batch_size: int = DEFAULT_RETENTION_SUBJECT_BATCH_SIZE,
    ) -> dict[str, int]:
        """Prune aged events, receipts, and terminal subjects in bounded work.

        Old events are pruned before new subject tombstones are appended, so a
        client can observe the deletion until the next retention horizon. No
        nonterminal subject or nonfinal idempotency receipt is ever selected.
        """
        timestamp = _now_seconds(now if now is not None else self._clock())
        if (
            isinstance(retention_seconds, bool)
            or not isinstance(retention_seconds, (int, float))
            or retention_seconds < 0
            or not math.isfinite(retention_seconds)
        ):
            raise InvalidPublicData("retention_seconds must be finite and non-negative")
        event_batch_size = _bounded_limit(
            event_batch_size, maximum=10_000, field="event_batch_size"
        )
        idempotency_batch_size = _bounded_limit(
            idempotency_batch_size,
            maximum=10_000,
            field="idempotency_batch_size",
        )
        subject_batch_size = _bounded_limit(
            subject_batch_size,
            maximum=1_000,
            field="subject_batch_size",
        )
        cutoff = timestamp - float(retention_seconds)
        job_terminal_states = tuple(sorted(JOB_TERMINAL_STATES))
        attention_terminal_states = tuple(sorted(ATTENTION_TERMINAL_STATES))
        job_state_placeholders = ",".join("?" for _ in job_terminal_states)

        def mutate(conn: sqlite3.Connection) -> dict[str, int]:
            # Keep subject tombstones fresh: old events must be pruned before
            # deleting the corresponding aggregate rows below.
            candidates = conn.execute(
                "SELECT event_id, created_at FROM work_events "
                "ORDER BY event_id ASC LIMIT ?",
                (event_batch_size,),
            ).fetchall()
            last_prunable = 0
            for row in candidates:
                if float(row["created_at"]) >= cutoff:
                    break
                last_prunable = int(row["event_id"])
            events_deleted = 0
            if last_prunable:
                cursor = conn.execute(
                    "DELETE FROM work_events WHERE event_id<=?", (last_prunable,)
                )
                events_deleted = int(cursor.rowcount)
                conn.execute(
                    "UPDATE work_meta SET value=? WHERE key='event_floor'",
                    (str(last_prunable + 1),),
                )

            # Fetch a bounded keyset for each terminal state, then merge the
            # small in-memory sets.  A single ``IN (...) ORDER BY`` query makes
            # SQLite sort every state branch; equality on the leading index
            # key instead preserves a bounded indexed walk.  We sort on final
            # time, not creation time: a long-lived item that was only just
            # resolved must not make maintenance scan an arbitrarily old
            # backlog before it reaches expired terminal work.
            subject_candidates: list[tuple[float, str, str, sqlite3.Row]] = []
            for state in attention_terminal_states:
                rows = conn.execute(
                    "SELECT attention_id, version, state, job_id, run_id, "
                    "COALESCE(resolved_at, updated_at) AS eligible_at "
                    "FROM attention_items WHERE state=? "
                    "AND COALESCE(resolved_at, updated_at)<? "
                    "ORDER BY COALESCE(resolved_at, updated_at), attention_id LIMIT ?",
                    (state, cutoff, subject_batch_size),
                ).fetchall()
                subject_candidates.extend(
                    (float(row["eligible_at"]), "attention", str(row["attention_id"]), row)
                    for row in rows
                )
            for status in job_terminal_states:
                rows = conn.execute(
                    "SELECT job_id, version, status, current_run_id, finished_at AS eligible_at "
                    "FROM jobs j WHERE j.status=? AND j.finished_at<? "
                    "AND NOT EXISTS (SELECT 1 FROM attention_items a WHERE a.job_id=j.job_id) "
                    "AND NOT EXISTS (SELECT 1 FROM job_runs r WHERE r.job_id=j.job_id "
                    f"AND r.status NOT IN ({job_state_placeholders})) "
                    "ORDER BY j.finished_at, j.job_id LIMIT ?",
                    (status, cutoff, *job_terminal_states, subject_batch_size),
                ).fetchall()
                subject_candidates.extend(
                    (float(row["eligible_at"]), "job", str(row["job_id"]), row)
                    for row in rows
                )

            # The total work remains hard-bounded by ``subject_batch_size``.
            # Selecting across both types avoids a steady Attention stream
            # starving terminal Jobs forever when the batch is small.
            subject_candidates.sort(key=lambda item: item[:3])
            attention_deleted = 0
            jobs_deleted = 0
            for _, subject_type, _, row in subject_candidates[:subject_batch_size]:
                if subject_type == "attention":
                    attention_deleted += self._tombstone_terminal_attention_row(
                        conn, row, timestamp=timestamp
                    )
                    continue
                deleted = self._tombstone_terminal_job_row(
                    conn,
                    row,
                    expected_version=int(row["version"]),
                    timestamp=timestamp,
                )
                jobs_deleted += deleted["jobs_deleted"]
                attention_deleted += deleted["attention_deleted"]

            # Like subject selection, receipt selection walks one indexed
            # final state at a time rather than asking SQLite to sort a union
            # of state ranges under the retention write transaction.
            id_candidates: list[tuple[float, str, str, sqlite3.Row]] = []
            for state in ("failed", "finalized"):
                rows = conn.execute(
                    "SELECT operation, idempotency_key, updated_at FROM idempotency_keys "
                    "WHERE state=? AND updated_at<? "
                    "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.job_id=subject_id "
                    f"AND j.status NOT IN ({job_state_placeholders})) "
                    "AND NOT EXISTS (SELECT 1 FROM attention_items a WHERE a.attention_id=subject_id "
                    "AND a.state IN ('pending','resolving')) "
                    "ORDER BY updated_at, idempotency_key LIMIT ?",
                    (state, cutoff, *job_terminal_states, idempotency_batch_size),
                ).fetchall()
                id_candidates.extend(
                    (
                        float(row["updated_at"]),
                        str(row["operation"]),
                        str(row["idempotency_key"]),
                        row,
                    )
                    for row in rows
                )
            id_candidates.sort(key=lambda item: item[:3])
            id_rows = [item[3] for item in id_candidates[:idempotency_batch_size]]
            if id_rows:
                conn.executemany(
                    "DELETE FROM idempotency_keys WHERE operation=? AND idempotency_key=? "
                    "AND state IN ('finalized','failed') AND updated_at<?",
                    ((row[0], row[1], cutoff) for row in id_rows),
                )
            conn.execute(
                "UPDATE work_meta SET value=? WHERE key='last_maintenance_at'",
                (repr(timestamp),),
            )
            return {
                "events_deleted": events_deleted,
                "idempotency_deleted": len(id_rows),
                "jobs_deleted": jobs_deleted,
                "attention_deleted": attention_deleted,
                "event_floor": last_prunable + 1 if last_prunable else int(
                    conn.execute(
                        "SELECT value FROM work_meta WHERE key='event_floor'"
                    ).fetchone()[0]
                ),
            }

        return self._write(mutate)

    def list_nonterminal_owners(self) -> list[dict[str, Any]]:
        """Group persisted owner proofs for out-of-transaction liveness probes."""
        with self._read() as conn:
            rows = conn.execute(
                "SELECT owner_boot_token, owner_pid, owner_start_token, owner_generation, "
                "SUM(run_count) AS run_count, SUM(attention_count) AS attention_count FROM ("
                "SELECT owner_boot_token, owner_pid, owner_start_token, owner_generation, "
                "COUNT(*) AS run_count, 0 AS attention_count FROM job_runs r "
                "JOIN jobs j ON j.current_run_id=r.run_id "
                "WHERE r.status NOT IN ('succeeded','failed','cancelled','interrupted') "
                "AND j.status NOT IN ('succeeded','failed','cancelled','interrupted') "
                "GROUP BY r.owner_boot_token, r.owner_pid, r.owner_start_token, r.owner_generation "
                "UNION ALL "
                "SELECT owner_boot_token, owner_pid, owner_start_token, owner_generation, "
                "0 AS run_count, COUNT(*) AS attention_count FROM attention_items "
                "WHERE state IN ('pending','resolving') "
                "GROUP BY owner_boot_token, owner_pid, owner_start_token, owner_generation"
                ") GROUP BY owner_boot_token, owner_pid, owner_start_token, owner_generation"
            ).fetchall()
            return [
                {
                    "owner": RuntimeOwner(
                        boot_token=str(row["owner_boot_token"]),
                        pid=int(row["owner_pid"]),
                        start_token=str(row["owner_start_token"]),
                        generation=str(row["owner_generation"]),
                    ),
                    "run_count": int(row["run_count"]),
                    "attention_count": int(row["attention_count"]),
                }
                for row in rows
            ]

    def reconcile_owner(
        self,
        owner: RuntimeOwner,
        classification: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Fail closed after a caller positively proves a persisted owner lost.

        Liveness probing is intentionally outside this retryable transaction.
        The caller may pass only positive loss evidence: a different boot or
        container instantiation, a positively dead PID, or a recycled PID with
        a different kernel start token.  ``live`` and ``owner_unverifiable``
        are rejected rather than guessed from elapsed time.

        One invocation processes at most 500 Attention and 500 current Runs so
        a pathological restored ledger cannot hold the writer lock forever.
        ``has_more`` tells startup reconciliation to run another bounded batch.
        """
        owner = owner.validated()
        classification = _bounded_text(
            classification, "classification", 32
        ).strip().lower()
        if classification not in {"different_boot", "dead", "pid_reused"}:
            raise InvalidPublicData(
                "reconciliation requires positive owner-loss evidence"
            )
        timestamp = _now_seconds(now if now is not None else self._clock())
        owner_params = (
            owner.boot_token,
            owner.pid,
            owner.start_token,
            owner.generation,
        )

        def mutate(conn: sqlite3.Connection) -> dict[str, Any]:
            attention_rows = conn.execute(
                "SELECT * FROM attention_items WHERE owner_boot_token=? AND owner_pid=? "
                "AND owner_start_token=? AND owner_generation=? "
                "AND state IN ('pending','resolving') "
                "ORDER BY attention_id LIMIT 501",
                owner_params,
            ).fetchall()
            attention_has_more = len(attention_rows) > 500
            attention_count = 0
            for row in attention_rows[:500]:
                state = str(row["state"])
                reason = (
                    "delivery_outcome_unknown" if state == "resolving" else "waiter_lost"
                )
                lifecycle_timestamp = self._attention_lifecycle_timestamp(row, timestamp)
                self._transition_attention_in_txn(
                    conn,
                    attention_id=str(row["attention_id"]),
                    expected_version=int(row["version"]),
                    next_state="orphaned",
                    event_type="attention.orphaned",
                    terminal_reason=reason,
                    resolution_token=None,
                    timestamp=lifecycle_timestamp,
                )
                conn.execute(
                    "UPDATE idempotency_keys SET state='uncertain', response_json=NULL, "
                    "updated_at=? WHERE operation='attention.respond' AND subject_id=? "
                    "AND state IN ('reserved','delivering')",
                    (lifecycle_timestamp, row["attention_id"]),
                )
                attention_count += 1

            run_rows = conn.execute(
                "SELECT r.run_id FROM job_runs r "
                "JOIN jobs j ON j.current_run_id=r.run_id "
                "WHERE r.owner_boot_token=? AND r.owner_pid=? AND r.owner_start_token=? "
                "AND r.owner_generation=? "
                "AND r.status NOT IN ('succeeded','failed','cancelled','interrupted') "
                "AND j.status NOT IN ('succeeded','failed','cancelled','interrupted') "
                "ORDER BY r.run_id LIMIT 501",
                owner_params,
            ).fetchall()
            run_has_more = len(run_rows) > 500
            run_count = 0
            for selected in run_rows[:500]:
                run = conn.execute(
                    "SELECT * FROM job_runs WHERE run_id=?", (selected["run_id"],)
                ).fetchone()
                if run is None:
                    continue
                job = conn.execute(
                    "SELECT * FROM jobs WHERE current_run_id=?", (run["run_id"],)
                ).fetchone()
                if job is None:
                    continue
                current = str(run["status"])
                if str(job["status"]) != current:
                    raise WorkStoreSchemaError(
                        "Job and current Run status diverged during reconciliation"
                    )
                if current in JOB_TERMINAL_STATES:
                    continue
                if current == "cancel_requested":
                    next_status = "cancelled"
                    reason = "cancel_confirmed_owner_lost"
                elif current in {"queued", "claimed"}:
                    next_status = "interrupted"
                    reason = "runner_never_started"
                else:
                    next_status = "interrupted"
                    reason = "runtime_owner_lost"
                error_json = canonical_public_json(
                    {"code": reason, "owner_loss": classification},
                    field="reconciliation error",
                )
                run_updated = conn.execute(
                    "UPDATE job_runs SET status=?, version=version+1, updated_at=?, "
                    "finished_at=?, error_json=? WHERE run_id=? AND version=? AND status=? "
                    "AND owner_boot_token=? AND owner_pid=? AND owner_start_token=? "
                    "AND owner_generation=?",
                    (
                        next_status,
                        timestamp,
                        timestamp,
                        error_json,
                        run["run_id"],
                        int(run["version"]),
                        current,
                        *owner_params,
                    ),
                )
                if run_updated.rowcount != 1:
                    continue
                job_updated = conn.execute(
                    "UPDATE jobs SET status=?, version=version+1, updated_at=?, finished_at=?, "
                    "error_json=? WHERE job_id=? AND version=? AND status=? AND current_run_id=?",
                    (
                        next_status,
                        timestamp,
                        timestamp,
                        error_json,
                        job["job_id"],
                        int(job["version"]),
                        current,
                        run["run_id"],
                    ),
                )
                if job_updated.rowcount != 1:
                    # BEGIN IMMEDIATE should make this unreachable.  Raising
                    # rolls back the already-updated Run rather than leaving a
                    # split aggregate.
                    raise VersionConflict(
                        f"Job {job['job_id']} changed during reconciliation"
                    )
                updated_job = conn.execute(
                    "SELECT * FROM jobs WHERE job_id=?", (job["job_id"],)
                ).fetchone()
                assert updated_job is not None
                self._append_event(
                    conn,
                    event_type=(
                        "job.cancelled" if next_status == "cancelled" else "job.interrupted"
                    ),
                    subject_type="job",
                    subject_id=str(job["job_id"]),
                    subject_version=int(updated_job["version"]),
                    subject=self._job_public(conn, updated_job),
                    job_id=str(job["job_id"]),
                    run_id=str(run["run_id"]),
                    tombstone=False,
                    created_at=timestamp,
                )
                run_count += 1
            return {
                "classification": classification,
                "runs_reconciled": run_count,
                "attention_reconciled": attention_count,
                "has_more": run_has_more or attention_has_more,
            }

        return self._write(mutate)

    def _tombstone_terminal_attention_row(
        self,
        conn: sqlite3.Connection,
        attention: sqlite3.Row,
        *,
        timestamp: float,
    ) -> int:
        """Append one Attention tombstone and delete its exact terminal row."""

        attention_id = str(attention["attention_id"])
        version = int(attention["version"])
        if str(attention["state"]) not in ATTENTION_TERMINAL_STATES:
            raise InvalidTransition("only terminal Attention can be tombstoned")
        self._append_event(
            conn,
            event_type="attention.deleted",
            subject_type="attention",
            subject_id=attention_id,
            subject_version=version + 1,
            subject=None,
            job_id=attention["job_id"],
            run_id=attention["run_id"],
            tombstone=True,
            created_at=timestamp,
        )
        deleted = conn.execute(
            "DELETE FROM attention_items WHERE attention_id=? AND version=?",
            (attention_id, version),
        )
        if deleted.rowcount != 1:
            raise VersionConflict("Attention changed during retention")
        return 1

    def _tombstone_terminal_job_row(
        self,
        conn: sqlite3.Connection,
        job: sqlite3.Row,
        *,
        expected_version: int,
        timestamp: float,
    ) -> dict[str, int]:
        """Append subject tombstones before deleting one exact terminal Job."""

        job_id = str(job["job_id"])
        if int(job["version"]) != expected_version:
            raise VersionConflict("Job version changed before retention")
        if str(job["status"]) not in JOB_TERMINAL_STATES:
            raise InvalidTransition("only terminal Jobs can be tombstoned")
        attention_rows = conn.execute(
            "SELECT * FROM attention_items WHERE job_id=?", (job_id,)
        ).fetchall()
        if any(str(row["state"]) not in ATTENTION_TERMINAL_STATES for row in attention_rows):
            raise InvalidTransition("Job still has nonterminal Attention")
        attention_deleted = sum(
            self._tombstone_terminal_attention_row(conn, row, timestamp=timestamp)
            for row in attention_rows
        )
        self._append_event(
            conn,
            event_type="job.deleted",
            subject_type="job",
            subject_id=job_id,
            subject_version=expected_version + 1,
            subject=None,
            job_id=job_id,
            run_id=job["current_run_id"],
            tombstone=True,
            created_at=timestamp,
        )
        conn.execute("DELETE FROM job_runs WHERE job_id=?", (job_id,))
        deleted = conn.execute(
            "DELETE FROM jobs WHERE job_id=? AND version=?", (job_id, expected_version)
        )
        if deleted.rowcount != 1:
            raise VersionConflict("Job changed during retention")
        return {"jobs_deleted": 1, "attention_deleted": attention_deleted}

    def tombstone_terminal_attention(
        self,
        attention_id: str,
        *,
        expected_version: int,
        now: float | None = None,
    ) -> dict[str, int]:
        """Delete one terminal Attention only after its retained tombstone."""

        attention_id = validate_work_id(attention_id, "attn")
        expected_version = _positive_int(expected_version, "expected_version")
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> dict[str, int]:
            attention = conn.execute(
                "SELECT * FROM attention_items WHERE attention_id=?", (attention_id,)
            ).fetchone()
            if attention is None:
                raise WorkNotFound(f"Attention {attention_id} not found")
            if int(attention["version"]) != expected_version:
                raise VersionConflict("Attention version changed before retention")
            return {
                "attention_deleted": self._tombstone_terminal_attention_row(
                    conn,
                    attention,
                    timestamp=timestamp,
                )
            }

        return self._write(mutate)

    def tombstone_terminal_job(
        self,
        job_id: str,
        *,
        expected_version: int,
        now: float | None = None,
    ) -> dict[str, int]:
        """Delete one terminal aggregate only after retained tombstone events."""

        job_id = validate_work_id(job_id, "job")
        expected_version = _positive_int(expected_version, "expected_version")
        timestamp = _now_seconds(now if now is not None else self._clock())

        def mutate(conn: sqlite3.Connection) -> dict[str, int]:
            job = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if job is None:
                raise WorkNotFound(f"Job {job_id} not found")
            return self._tombstone_terminal_job_row(
                conn,
                job,
                expected_version=expected_version,
                timestamp=timestamp,
            )

        return self._write(mutate)


def _work_store_sidecar_metadata(path: Path, suffix: str) -> tuple[bool, bool, int]:
    """Return ``(exists, regular, bytes)`` without following a sidecar link."""

    try:
        metadata = path.with_name(path.name + suffix).lstat()
    except FileNotFoundError:
        return False, True, 0
    except OSError:
        return False, False, 0
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return True, False, 0
    return True, True, int(metadata.st_size)


def _read_only_work_store_connection(path: Path) -> sqlite3.Connection:
    """Open an existing Work store without an initialization or write path."""

    connection = sqlite3.connect(
        f"{path.absolute().as_uri()}?mode=ro&immutable=1",
        uri=True,
        isolation_level=None,
        timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000.0,
    )
    connection.row_factory = sqlite3.Row
    # These pragmas are connection-local.  In particular, query_only blocks a
    # future diagnostic query from accidentally gaining a write side effect.
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
    return connection


def _work_store_fingerprint(metadata: os.stat_result) -> tuple[int, int, int, int]:
    """Capture the file identity and mutable fields relevant to a safe read."""

    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _work_store_race_result(
    path: Path,
    *,
    initial_metadata: os.stat_result,
    initial_wal_exists: bool,
    initial_shm_exists: bool,
    initial_journal_exists: bool,
) -> WorkStoreInspection | None:
    """Return a fail-closed result when immutable inspection lost its snapshot."""

    try:
        final_metadata = path.lstat()
    except OSError:
        final_metadata = None
    final_wal_exists, final_wal_regular, final_wal_size = _work_store_sidecar_metadata(
        path, "-wal"
    )
    final_shm_exists, final_shm_regular, _ = _work_store_sidecar_metadata(path, "-shm")
    final_journal_exists, final_journal_regular, final_journal_size = (
        _work_store_sidecar_metadata(path, "-journal")
    )
    if (
        final_metadata is None
        or not stat.S_ISREG(final_metadata.st_mode)
        or _work_store_fingerprint(final_metadata) != _work_store_fingerprint(initial_metadata)
        or final_wal_exists != initial_wal_exists
        or final_shm_exists != initial_shm_exists
        or final_journal_exists != initial_journal_exists
        or not final_wal_regular
        or not final_shm_regular
        or not final_journal_regular
    ):
        return WorkStoreInspection(
            path=path,
            status="inspection_raced",
            size_bytes=(int(final_metadata.st_size) if final_metadata is not None else 0),
            wal_size_bytes=final_wal_size,
            rollback_journal_size_bytes=final_journal_size,
        )
    return None


def _read_only_nonterminal_owner_summaries(
    conn: sqlite3.Connection,
) -> tuple[tuple[WorkStoreOwnerSummary, ...], bool]:
    """Return at most 64 aggregate owners without reading public payloads."""

    rows = conn.execute(
        "SELECT owner_boot_token, owner_pid, owner_start_token, owner_generation, "
        "SUM(run_count) AS run_count, SUM(attention_count) AS attention_count FROM ("
        "SELECT owner_boot_token, owner_pid, owner_start_token, owner_generation, "
        "COUNT(*) AS run_count, 0 AS attention_count FROM job_runs r "
        "JOIN jobs j ON j.current_run_id=r.run_id "
        "WHERE r.status NOT IN ('succeeded','failed','cancelled','interrupted') "
        "AND j.status NOT IN ('succeeded','failed','cancelled','interrupted') "
        "GROUP BY r.owner_boot_token, r.owner_pid, r.owner_start_token, r.owner_generation "
        "UNION ALL "
        "SELECT owner_boot_token, owner_pid, owner_start_token, owner_generation, "
        "0 AS run_count, COUNT(*) AS attention_count FROM attention_items "
        "WHERE state IN ('pending','resolving') "
        "GROUP BY owner_boot_token, owner_pid, owner_start_token, owner_generation"
        ") GROUP BY owner_boot_token, owner_pid, owner_start_token, owner_generation "
        "ORDER BY owner_pid, owner_boot_token, owner_start_token, owner_generation LIMIT 65"
    ).fetchall()
    truncated = len(rows) > 64
    summaries: list[WorkStoreOwnerSummary] = []
    for row in rows[:64]:
        owner = RuntimeOwner(
            boot_token=str(row["owner_boot_token"]),
            pid=int(row["owner_pid"]),
            start_token=str(row["owner_start_token"]),
            generation=str(row["owner_generation"]),
        ).validated()
        summaries.append(
            WorkStoreOwnerSummary(
                owner=owner,
                run_count=int(row["run_count"]),
                attention_count=int(row["attention_count"]),
            )
        )
    return tuple(summaries), truncated


def inspect_work_store(profile_home: str | Path) -> WorkStoreInspection:
    """Inspect ``work.db`` through a read-only/query-only SQLite connection.

    The function never creates a profile directory, database, WAL/SHM sidecar,
    lock, or migration.  It deliberately returns status codes instead of
    raising for ordinary on-disk health states so callers such as ``doctor``
    can report a corrupt or forward-versioned store without attempting repair.
    """

    path = Path(profile_home) / WORK_DB_FILENAME
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return WorkStoreInspection(path=path, status="missing")
    except OSError:
        return WorkStoreInspection(path=path, status="unavailable")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return WorkStoreInspection(path=path, status="invalid_path")

    size_bytes = int(metadata.st_size)
    wal_exists, wal_regular, wal_size_bytes = _work_store_sidecar_metadata(path, "-wal")
    shm_exists, shm_regular, _ = _work_store_sidecar_metadata(path, "-shm")
    journal_exists, journal_regular, journal_size_bytes = _work_store_sidecar_metadata(
        path, "-journal"
    )
    if not wal_regular or not shm_regular or not journal_regular:
        return WorkStoreInspection(
            path=path,
            status="invalid_sidecar",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
            rollback_journal_size_bytes=journal_size_bytes,
        )
    if wal_exists and not shm_exists:
        return WorkStoreInspection(
            path=path,
            status="wal_sidecar_incomplete",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
            rollback_journal_size_bytes=journal_size_bytes,
        )
    # A regular SQLite read connection updates the existing WAL index reader
    # marks even with ``query_only`` enabled.  That is a source-sidecar write,
    # so doctor must not deep-inspect a live WAL until a future lifecycle guard
    # can provide a closed snapshot.  The WAL presence/size is still useful
    # operational information and is reported without opening the store.
    if wal_exists:
        return WorkStoreInspection(
            path=path,
            status="live_wal",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
            rollback_journal_size_bytes=journal_size_bytes,
        )
    # In rollback-journal mode an uncommitted transaction can spill dirty
    # pages into the main file.  Immutable reads would then see a split,
    # non-authoritative view, so report the journal and do not inspect it.
    if journal_exists:
        return WorkStoreInspection(
            path=path,
            status="live_rollback_journal",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
            rollback_journal_size_bytes=journal_size_bytes,
        )
    if size_bytes == 0:
        return WorkStoreInspection(
            path=path,
            status="invalid_header",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
            rollback_journal_size_bytes=journal_size_bytes,
        )
    try:
        with path.open("rb") as handle:
            header = handle.read(len(_SQLITE_HEADER))
    except OSError:
        return WorkStoreInspection(
            path=path,
            status="unavailable",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
            rollback_journal_size_bytes=journal_size_bytes,
        )
    if header != _SQLITE_HEADER:
        return WorkStoreInspection(
            path=path,
            status="invalid_header",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
            rollback_journal_size_bytes=journal_size_bytes,
        )

    conn: sqlite3.Connection | None = None
    try:
        conn = _read_only_work_store_connection(path)
        app_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        quick_check = conn.execute("PRAGMA quick_check(1)").fetchone()
        integrity_ok = bool(
            quick_check is not None and str(quick_check[0]).strip().lower() == "ok"
        )
        common = {
            "path": path,
            "size_bytes": size_bytes,
            "wal_size_bytes": wal_size_bytes,
            "rollback_journal_size_bytes": journal_size_bytes,
            "application_id": app_id,
            "schema_version": version,
            "integrity_ok": integrity_ok,
        }

        def finish(candidate: WorkStoreInspection) -> WorkStoreInspection:
            return _work_store_race_result(
                path,
                initial_metadata=metadata,
                initial_wal_exists=wal_exists,
                initial_shm_exists=shm_exists,
                initial_journal_exists=journal_exists,
            ) or candidate

        if not integrity_ok:
            return finish(WorkStoreInspection(status="integrity_failed", **common))
        if app_id != WORK_APPLICATION_ID:
            return finish(WorkStoreInspection(status="foreign_store", **common))
        if version > WORK_SCHEMA_VERSION:
            return finish(WorkStoreInspection(status="future_schema", **common))
        if version not in {_WORK_SCHEMA_V1, WORK_SCHEMA_VERSION}:
            return finish(WorkStoreInspection(status="unsupported_schema", **common))

        mismatches = tuple(WorkLedger._schema_mismatches_for_version(conn, version))
        if mismatches:
            return finish(
                WorkStoreInspection(
                    status="schema_mismatch",
                    schema_mismatches=mismatches,
                    **common,
                )
            )
        meta = {
            str(row["key"]): str(row["value"])
            for row in conn.execute("SELECT key, value FROM work_meta")
        }
        required_meta = {"ledger_id", "event_floor", "created_at", "last_maintenance_at"}
        if set(meta) != required_meta:
            return finish(WorkStoreInspection(status="metadata_invalid", **common))
        try:
            ledger_id = validate_work_id(meta["ledger_id"], "ledger")
            event_floor = int(meta["event_floor"])
            created_at = float(meta["created_at"])
            last_maintenance_at = float(meta["last_maintenance_at"])
        except (InvalidWorkIdentifier, TypeError, ValueError):
            return finish(WorkStoreInspection(status="metadata_invalid", **common))
        if (
            event_floor < 1
            or not math.isfinite(created_at)
            or not math.isfinite(last_maintenance_at)
        ):
            return finish(WorkStoreInspection(status="metadata_invalid", **common))
        try:
            owner_summaries, owners_truncated = _read_only_nonterminal_owner_summaries(conn)
        except (TypeError, ValueError, WorkLedgerError, sqlite3.DatabaseError):
            return finish(WorkStoreInspection(status="owner_data_invalid", **common))
        return finish(
            WorkStoreInspection(
                status="legacy_schema" if version == _WORK_SCHEMA_V1 else "healthy",
                ledger_id=ledger_id,
                event_floor=event_floor,
                last_maintenance_at=last_maintenance_at,
                owner_summaries=owner_summaries,
                owners_truncated=owners_truncated,
                **common,
            )
        )
    except sqlite3.OperationalError as exc:
        return WorkStoreInspection(
            path=path,
            status="busy" if _is_busy_error(exc) else "unreadable",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
        )
    except (sqlite3.DatabaseError, OSError):
        return WorkStoreInspection(
            path=path,
            status="unreadable",
            size_bytes=size_bytes,
            wal_size_bytes=wal_size_bytes,
        )
    finally:
        if conn is not None:
            conn.close()


__all__ = [
    "ATTENTION_TERMINAL_STATES",
    "ATTENTION_TRANSITIONS",
    "AttentionNotActionable",
    "AttentionResolutionClaim",
    "CursorExpired",
    "DEFAULT_RETENTION_SECONDS",
    "DEFAULT_RETENTION_SUBJECT_BATCH_SIZE",
    "DETAIL_JSON_MAX_BYTES",
    "IDEMPOTENCY_TRANSITIONS",
    "IdempotencyConflict",
    "InvalidPublicData",
    "InvalidTransition",
    "InvalidWorkIdentifier",
    "JOB_TERMINAL_STATES",
    "JOB_TRANSITIONS",
    "PUBLIC_JSON_MAX_BYTES",
    "RuntimeOwner",
    "RuntimeOwnerMismatch",
    "SCHEMA_INDEX_SQL",
    "SCHEMA_TABLE_SQL",
    "SYNC_MAX_BYTES",
    "VersionConflict",
    "WORK_APPLICATION_ID",
    "WORK_DB_FILENAME",
    "WORK_SCHEMA_VERSION",
    "WorkLedger",
    "WorkLedgerError",
    "WorkNotFound",
    "WorkOperationInProgress",
    "WorkStoreBusy",
    "WorkStoreCorruptError",
    "WorkStoreFutureSchemaError",
    "WorkStoreReplacedError",
    "WorkStoreSchemaError",
    "WorkStoreSignatureError",
    "WorkStoreUnavailable",
    "canonical_public_json",
    "hash_attention_response_envelope",
    "hash_job_cancel_envelope",
    "hash_job_create_envelope",
    "new_work_id",
    "inspect_work_store",
    "validate_work_id",
    "WorkStoreInspection",
    "WorkStoreOwnerSummary",
]
