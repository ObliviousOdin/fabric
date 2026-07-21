"""Process-local runtime bridge for Fabric's durable work ledger.

The ledger owns durable state.  This module deliberately owns only things that
cannot be put in SQLite: raw prompts waiting for a worker, live cancellation
callbacks, and exact waiter delivery callbacks.  Keeping that boundary sharp
is a security property -- ``work.db`` must never become an IPC channel for a
prompt, password, secret, or free-form answer.

The service is independent of :mod:`tui_gateway.server` so headless gateways,
tests, and future producers can use the same process-global capacity and owner
proof.  Agent construction and RPC adaptation are intentionally left to the
caller; in particular, no :class:`AIAgent` instance is retained here.
"""

from __future__ import annotations

import inspect
import json
import logging
import math
import os
import threading
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import Future
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any, Protocol, TypeVar, runtime_checkable

_log = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT_JOBS = 2
DEFAULT_MAX_QUEUED_JOBS = 32
DEFAULT_WORK_MAINTENANCE_INTERVAL_SECONDS = 60 * 60
DEFAULT_WORK_MAINTENANCE_RETRY_SECONDS = 60
WORK_MAINTENANCE_CATCHUP_DELAY_SECONDS = 1
MAX_WORK_MAINTENANCE_CATCHUP_BATCHES = 8
DEFAULT_WORK_RETENTION_EVENT_BATCH_SIZE = 1_000
DEFAULT_WORK_RETENTION_IDEMPOTENCY_BATCH_SIZE = 1_000
DEFAULT_WORK_RETENTION_SUBJECT_BATCH_SIZE = 100
MAX_AGENT_INPUT_BYTES = 32 * 1024
MAX_BACKGROUND_PROMPT_CHARS = 200_000
MAX_RECONCILIATION_BATCHES_PER_OWNER = 1_000
MAX_PUBLIC_DISPLAY_DEPTH = 6
MAX_PUBLIC_DISPLAY_ITEMS = 64
MAX_PUBLIC_DISPLAY_STRING_CHARS = 4_096
PROCESS_GENERATION = f"gen_{uuid.uuid4().hex}"

_T = TypeVar("_T")

__all__ = [
    "BackgroundRunSpec",
    "BackgroundRuntimeControl",
    "CapacityReservation",
    "DeliveryOutcomeUnknown",
    "DeliveryResult",
    "DEFAULT_WORK_MAINTENANCE_INTERVAL_SECONDS",
    "GlobalWorkScheduler",
    "LockedWaiter",
    "OwnerClassification",
    "OwnerProof",
    "OwnerProofUnavailable",
    "PROCESS_GENERATION",
    "RuntimeOwnerMismatch",
    "RuntimeRegistry",
    "SchedulerLimits",
    "SchedulerStats",
    "WaiterAlreadyConsumed",
    "WaiterIdentity",
    "WaiterRegistry",
    "WaiterUnavailable",
    "WorkCapacityExceeded",
    "WorkSchedulerClosed",
    "WorkService",
    "WorkServiceCache",
    "WorkServiceClosed",
    "WorkServiceLease",
    "WorkStoreRebound",
    "cached_service_for_profile",
    "classify_owner",
    "classify_owner_group",
    "coerce_owner_proof",
    "create_process_owner_proof",
    "get_global_work_scheduler",
    "normalize_profile_home",
    "sanitize_public_display",
    "service_for_profile",
    "shutdown_work_services",
]


def sanitize_public_display(
    value: Any,
    *,
    max_string_chars: int = MAX_PUBLIC_DISPLAY_STRING_CHARS,
    _depth: int = 0,
) -> Any:
    """Return bounded recursively redacted JSON-safe display data.

    Raw prompts and waiter responses never call this function because they do
    not cross the durable boundary at all.  It is for the deliberately public
    labels and payload fragments that do enter ``work.db``.  ``force=True``
    makes the boundary independent of a user's display-redaction preference.
    """

    if _depth > MAX_PUBLIC_DISPLAY_DEPTH:
        raise ValueError("public display data is nested too deeply")
    if isinstance(value, str):
        try:
            from agent.redact import redact_sensitive_text

            redacted = redact_sensitive_text(value, force=True)
        except Exception:
            # Redaction is a security boundary here, so dependency failure is
            # fail-closed and never interpolates the original value.
            redacted = "[redacted]"
        return str(redacted)[:max_string_chars]
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("public display numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_PUBLIC_DISPLAY_ITEMS:
            raise ValueError("public display object has too many fields")
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("public display object keys must be strings")
            key = sanitize_public_display(
                raw_key,
                max_string_chars=128,
                _depth=_depth + 1,
            )
            if not isinstance(key, str) or not key or key in result:
                raise ValueError("public display object has an invalid field")
            result[key] = sanitize_public_display(
                raw_value,
                max_string_chars=max_string_chars,
                _depth=_depth + 1,
            )
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_PUBLIC_DISPLAY_ITEMS:
            raise ValueError("public display array has too many items")
        return [
            sanitize_public_display(
                item,
                max_string_chars=max_string_chars,
                _depth=_depth + 1,
            )
            for item in value
        ]
    raise ValueError("public display data must contain JSON values")


class WorkServiceError(RuntimeError):
    """Base class for typed runtime-service failures."""


class OwnerProofUnavailable(WorkServiceError):
    """The process cannot construct the complete proof required to own work."""


class RuntimeOwnerMismatch(WorkServiceError):
    """A mutation targeted work owned by another process or generation."""


class WaiterUnavailable(WorkServiceError):
    """The exact in-process waiter no longer exists."""


class WaiterAlreadyConsumed(WorkServiceError):
    """A different resolution already consumed the waiter."""


class DeliveryOutcomeUnknown(WorkServiceError):
    """A delivery callback raised after delivery may already have occurred."""


class WorkCapacityExceeded(WorkServiceError):
    """The process-global running plus queued work capacity is full."""

    retryable = True


class WorkSchedulerClosed(WorkServiceError):
    """The process-global scheduler no longer accepts work."""


class WorkServiceClosed(WorkServiceError):
    """A profile service has been shut down."""


class WorkStoreRebound(WorkServiceError):
    """The ledger identity changed underneath a cached profile service."""


def normalize_profile_home(profile_home: str | Path) -> Path:
    """Return the canonical, case-normalized absolute profile path.

    ``Path.resolve(strict=False)`` collapses symlinks where possible and also
    normalizes ``..`` components for a not-yet-created profile.  ``normcase``
    prevents duplicate cache entries on case-insensitive platforms.
    """

    path = Path(profile_home).expanduser()
    try:
        path = path.resolve(strict=False)
    except (OSError, RuntimeError):
        path = path.absolute()
    return Path(os.path.normcase(str(path)))


@dataclass(frozen=True, slots=True)
class OwnerProof:
    """Complete creator identity stored on a Run or Attention item."""

    boot_token: str
    pid: int
    start_token: str
    generation: str

    def __post_init__(self) -> None:
        if not isinstance(self.boot_token, str) or not self.boot_token.strip():
            raise OwnerProofUnavailable("boot/container identity is unavailable")
        if not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid <= 0:
            raise OwnerProofUnavailable("process id is unavailable")
        if not isinstance(self.start_token, str) or not self.start_token.strip():
            raise OwnerProofUnavailable("process start identity is unavailable")
        if not isinstance(self.generation, str) or not self.generation.strip():
            raise OwnerProofUnavailable("process generation is unavailable")
        if any(
            len(value.encode("utf-8")) > 512
            for value in (self.boot_token, self.start_token, self.generation)
        ):
            raise OwnerProofUnavailable("process owner identity exceeds 512 bytes")

    def validated(self) -> OwnerProof:
        """Match WorkLedger's structural ``RuntimeOwner`` validation API."""

        return self


def _default_boot_token() -> str | None:
    """Return a tagged boot/container-instantiation identity.

    Linux uses Fabric's boot-id plus PID-1 start identity.  On macOS and
    Windows (and unusual Linux containers without readable ``/proc``), the
    canonical psutil boot time is used with an explicit source tag.  Returning
    ``None`` is intentional: accepting new execution without this evidence
    would make safe restart reconciliation impossible.
    """

    try:
        from gateway.drain_control import current_instantiation_epoch

        epoch = str(current_instantiation_epoch() or "").strip()
    except Exception:
        epoch = ""
    if epoch:
        return f"instantiation:{epoch}"

    try:
        import psutil  # type: ignore

        boot_centiseconds = int(round(float(psutil.boot_time()) * 100))
    except Exception:
        return None
    if boot_centiseconds <= 0:
        return None
    return f"psutil_boot_cs:{boot_centiseconds}"


def _default_start_token(pid: int) -> str | None:
    try:
        from gateway.status import get_process_start_time

        value = get_process_start_time(pid)
    except Exception:
        value = None
    return None if value is None else str(value)


def _default_pid_exists(pid: int) -> bool | None:
    try:
        # ``_pid_exists`` is the existing cross-platform implementation.  It
        # is intentionally imported lazily so work_service remains import-safe
        # while gateway.status initializes.  A public wrapper can replace this
        # adapter without changing the service contract.
        from gateway.status import _pid_exists

        return bool(_pid_exists(pid))
    except Exception:
        return None


def create_process_owner_proof(
    *,
    pid: int | None = None,
    generation: str = PROCESS_GENERATION,
    boot_token_provider: Callable[[], str | None] = _default_boot_token,
    start_token_provider: Callable[[int], str | int | None] = _default_start_token,
) -> OwnerProof:
    """Build complete proof for this process or reject execution."""

    owner_pid = os.getpid() if pid is None else int(pid)
    boot_token = str(boot_token_provider() or "").strip()
    raw_start = start_token_provider(owner_pid)
    start_token = "" if raw_start is None else str(raw_start).strip()
    return OwnerProof(
        boot_token=boot_token,
        pid=owner_pid,
        start_token=start_token,
        generation=str(generation or "").strip(),
    )


def coerce_owner_proof(value: object) -> OwnerProof:
    """Adapt a ledger ``RuntimeOwner``/mapping into the service proof type."""

    if isinstance(value, OwnerProof):
        return value
    if isinstance(value, tuple) and value:
        # Grouped candidate APIs commonly return ``(owner, row_count)``.
        value = value[0]
    if isinstance(value, Mapping) and "owner" in value:
        # WorkLedger includes grouped run/attention counts beside the proof.
        value = value["owner"]
    if isinstance(value, Mapping):
        get = value.get
    else:
        get = lambda key, default=None: getattr(value, key, default)
    return OwnerProof(
        boot_token=str(get("boot_token", "") or ""),
        pid=int(get("pid", 0) or 0),
        start_token=str(get("start_token", "") or ""),
        generation=str(get("generation", "") or ""),
    )


class OwnerClassification(str, Enum):
    """Positive owner observations used by restart reconciliation."""

    LIVE = "live"
    DIFFERENT_BOOT = "different_boot"
    DEAD = "dead"
    PID_REUSED = "pid_reused"
    UNVERIFIABLE = "owner_unverifiable"

    @property
    def recoverable(self) -> bool:
        return self in {
            OwnerClassification.DIFFERENT_BOOT,
            OwnerClassification.DEAD,
            OwnerClassification.PID_REUSED,
        }


def classify_owner(
    owner: OwnerProof,
    *,
    current_boot_token: str | None,
    pid_exists: Callable[[int], bool | None] = _default_pid_exists,
    start_token_probe: Callable[[int], str | int | None] = _default_start_token,
) -> OwnerClassification:
    """Classify an owner using only positive evidence.

    Unavailable/failed probes are never interpreted as death.  In particular,
    a live PID whose kernel start token cannot be read remains
    ``owner_unverifiable`` and must not be interrupted or adopted.
    """

    current_boot = str(current_boot_token or "").strip()
    if current_boot and current_boot != owner.boot_token:
        return OwnerClassification.DIFFERENT_BOOT

    try:
        alive = pid_exists(owner.pid)
    except Exception:
        alive = None
    if alive is False:
        return OwnerClassification.DEAD
    if alive is not True:
        return OwnerClassification.UNVERIFIABLE

    try:
        current_start = start_token_probe(owner.pid)
    except Exception:
        current_start = None
    if current_start is None or not str(current_start).strip():
        return OwnerClassification.UNVERIFIABLE
    if str(current_start).strip() != owner.start_token:
        return OwnerClassification.PID_REUSED
    return OwnerClassification.LIVE


def classify_owner_group(
    owners: Iterable[OwnerProof],
    *,
    current_boot_token: str | None,
    pid_exists: Callable[[int], bool | None] = _default_pid_exists,
    start_token_probe: Callable[[int], str | int | None] = _default_start_token,
) -> dict[OwnerProof, OwnerClassification]:
    """Classify owners while probing each distinct OS identity once."""

    result: dict[OwnerProof, OwnerClassification] = {}
    observations: dict[tuple[str, int, str], OwnerClassification] = {}
    for owner in owners:
        os_identity = (owner.boot_token, owner.pid, owner.start_token)
        classification = observations.get(os_identity)
        if classification is None:
            classification = classify_owner(
                owner,
                current_boot_token=current_boot_token,
                pid_exists=pid_exists,
                start_token_probe=start_token_probe,
            )
            observations[os_identity] = classification
        result[owner] = classification
    return result


@dataclass(frozen=True, slots=True)
class SchedulerLimits:
    max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_JOBS
    max_queued_jobs: int = DEFAULT_MAX_QUEUED_JOBS

    def __post_init__(self) -> None:
        if isinstance(self.max_concurrent_jobs, bool) or self.max_concurrent_jobs < 1:
            raise ValueError("max_concurrent_jobs must be a positive integer")
        if isinstance(self.max_queued_jobs, bool) or self.max_queued_jobs < 0:
            raise ValueError("max_queued_jobs must be a non-negative integer")

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> SchedulerLimits:
        work: Mapping[str, Any] = {}
        if isinstance(config, Mapping):
            gateway = config.get("gateway")
            if isinstance(gateway, Mapping):
                candidate = gateway.get("work")
                if isinstance(candidate, Mapping):
                    work = candidate

        def _coerce(key: str, default: int, *, minimum: int) -> int:
            raw = work.get(key, default)
            if isinstance(raw, bool):
                return default
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return default
            return value if value >= minimum else default

        return cls(
            max_concurrent_jobs=_coerce(
                "max_concurrent_jobs", DEFAULT_MAX_CONCURRENT_JOBS, minimum=1
            ),
            max_queued_jobs=_coerce(
                "max_queued_jobs", DEFAULT_MAX_QUEUED_JOBS, minimum=0
            ),
        )


@dataclass(frozen=True, slots=True)
class BackgroundRunSpec:
    """Immutable raw-prompt reservation passed to a background runner.

    ``agent_inputs_json`` is a canonical JSON snapshot rather than a live
    mapping or factory closure.  Consequently this object cannot retain a
    parent agent, mutable session dictionary, or profile config object.
    """

    job_id: str
    run_id: str
    profile_home: str
    runtime_session_id: str
    source_session_key: str
    prompt: str
    owner: OwnerProof
    agent_inputs_json: str = "{}"

    def __post_init__(self) -> None:
        for field_name in ("job_id", "run_id", "runtime_session_id", "source_session_key"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if not isinstance(self.prompt, str) or not self.prompt:
            raise ValueError("prompt is required")
        if len(self.prompt) > MAX_BACKGROUND_PROMPT_CHARS:
            raise ValueError(
                f"prompt exceeds {MAX_BACKGROUND_PROMPT_CHARS} characters"
            )
        normalized_home = str(normalize_profile_home(self.profile_home))
        object.__setattr__(self, "profile_home", normalized_home)
        try:
            decoded = json.loads(self.agent_inputs_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("agent_inputs_json must contain valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("agent_inputs_json must encode an object")
        try:
            canonical = json.dumps(
                decoded,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("agent_inputs_json must contain canonical JSON values") from exc
        if len(canonical.encode("utf-8")) > MAX_AGENT_INPUT_BYTES:
            raise ValueError(f"agent construction inputs exceed {MAX_AGENT_INPUT_BYTES} bytes")
        object.__setattr__(self, "agent_inputs_json", canonical)

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        run_id: str,
        profile_home: str | Path,
        runtime_session_id: str,
        source_session_key: str,
        prompt: str,
        owner: OwnerProof,
        agent_inputs: Mapping[str, Any] | None = None,
    ) -> BackgroundRunSpec:
        try:
            snapshot = json.dumps(
                dict(agent_inputs or {}),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("agent construction inputs must be JSON-safe") from exc
        return cls(
            job_id=job_id,
            run_id=run_id,
            profile_home=str(profile_home),
            runtime_session_id=runtime_session_id,
            source_session_key=source_session_key,
            prompt=prompt,
            owner=owner,
            agent_inputs_json=snapshot,
        )

    @property
    def interaction_key(self) -> str:
        return f"work:{self.run_id}"

    def agent_inputs(self) -> dict[str, Any]:
        """Return a fresh mutable copy for constructing a new agent."""

        value = json.loads(self.agent_inputs_json)
        assert isinstance(value, dict)
        return value


class BackgroundRuntimeControl:
    """Cancellation and sensitivity state for one creator-owned Run.

    The control may retain the *new* background agent only while it executes;
    it never references the foreground/parent agent or session dictionary.
    Cancellation is sticky so a request received while the Run is queued is
    delivered immediately when its agent is attached.
    """

    __slots__ = ("_agent", "_cancelled", "_lock", "_sensitive_input")

    def __init__(self) -> None:
        self._agent: object | None = None
        self._cancelled = threading.Event()
        self._lock = threading.RLock()
        self._sensitive_input = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def sensitive_input(self) -> bool:
        with self._lock:
            return self._sensitive_input

    def mark_sensitive_input(self) -> None:
        with self._lock:
            self._sensitive_input = True

    def attach_agent(self, agent: object) -> None:
        with self._lock:
            self._agent = agent
            cancel_now = self._cancelled.is_set()
        if cancel_now:
            self._interrupt(agent)

    def detach_agent(self, agent: object) -> None:
        with self._lock:
            if self._agent is agent:
                self._agent = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            agent = self._agent
        if agent is not None:
            self._interrupt(agent)

    @staticmethod
    def _interrupt(agent: object) -> None:
        interrupt = getattr(agent, "interrupt", None)
        if callable(interrupt):
            interrupt()


@dataclass(frozen=True, slots=True)
class SchedulerStats:
    reserved: int
    queued: int
    running: int
    max_concurrent_jobs: int
    max_queued_jobs: int
    closed: bool


@dataclass(slots=True)
class _WorkItem:
    token: str
    owner_key: str
    spec: BackgroundRunSpec | None
    runner: Callable[[BackgroundRunSpec], Any]
    future: Future[Any]
    on_abandon: Callable[[BackgroundRunSpec, str], None] | None


class CapacityReservation:
    """Single-use admission token reserved before the ledger transaction."""

    __slots__ = ("_scheduler", "owner_key", "token")

    def __init__(self, scheduler: GlobalWorkScheduler, owner_key: str, token: str) -> None:
        self._scheduler = scheduler
        self.owner_key = owner_key
        self.token = token

    @property
    def active(self) -> bool:
        return self._scheduler._reservation_active(self.token, self.owner_key)

    def release(self) -> bool:
        """Release an unsubmitted token, for example after a ledger failure."""

        return self._scheduler._release_reservation(self.token, self.owner_key)

    def __enter__(self) -> CapacityReservation:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


class GlobalWorkScheduler:
    """One bounded worker queue shared by every profile service."""

    def __init__(self, limits: SchedulerLimits | None = None) -> None:
        self.limits = limits or SchedulerLimits()
        self._condition = threading.Condition(threading.RLock())
        self._reservations: dict[str, str] = {}
        self._queue: deque[_WorkItem] = deque()
        self._running: dict[str, str] = {}
        self._workers: list[threading.Thread] = []
        self._closed = False

    def reserve(self, *, owner_key: str) -> CapacityReservation:
        """Atomically reserve running/queue capacity before durable create."""

        owner = str(owner_key).strip()
        if not owner:
            raise ValueError("owner_key is required")
        with self._condition:
            if self._closed:
                raise WorkSchedulerClosed("work scheduler is shut down")
            total = len(self._reservations) + len(self._queue) + len(self._running)
            maximum = self.limits.max_concurrent_jobs + self.limits.max_queued_jobs
            if total >= maximum:
                raise WorkCapacityExceeded(
                    "process-global background work capacity is exhausted"
                )
            token = f"cap_{uuid.uuid4().hex}"
            self._reservations[token] = owner
            return CapacityReservation(self, owner, token)

    def submit(
        self,
        reservation: CapacityReservation,
        spec: BackgroundRunSpec,
        runner: Callable[[BackgroundRunSpec], _T],
        *,
        on_abandon: Callable[[BackgroundRunSpec, str], None] | None = None,
    ) -> Future[_T]:
        """Consume a reservation and queue one immutable run specification."""

        future: Future[_T] = Future()
        with self._condition:
            if self._closed:
                self._reservations.pop(reservation.token, None)
                raise WorkSchedulerClosed("work scheduler is shut down")
            owner = self._reservations.get(reservation.token)
            if owner is None or owner != reservation.owner_key:
                raise WorkServiceError("capacity reservation is missing or already consumed")
            self._reservations.pop(reservation.token)
            self._queue.append(
                _WorkItem(
                    token=reservation.token,
                    owner_key=owner,
                    spec=spec,
                    runner=runner,
                    future=future,
                    on_abandon=on_abandon,
                )
            )
            self._ensure_workers_locked()
            self._condition.notify()
        return future

    def cancel_queued(
        self,
        future: Future[Any],
        *,
        reason: str = "cancelled_before_start",
    ) -> bool:
        """Remove one not-yet-started item and release its capacity promptly.

        The abandonment callback runs outside the scheduler lock because it
        may perform ledger I/O and acquire service locks.  If the worker won
        the dequeue race, this returns ``False`` and the caller must use its
        running-work cancellation path instead.
        """

        abandoned: tuple[_WorkItem, BackgroundRunSpec] | None = None
        with self._condition:
            kept: deque[_WorkItem] = deque()
            while self._queue:
                item = self._queue.popleft()
                if abandoned is None and item.future is future:
                    spec = item.spec
                    if spec is not None:
                        future.cancel()
                        item.spec = None
                        abandoned = (item, spec)
                        continue
                kept.append(item)
            self._queue = kept
            if abandoned is not None:
                self._condition.notify_all()

        if abandoned is None:
            return False
        item, spec = abandoned
        self._notify_abandoned(item, spec, reason)
        return True

    def _ensure_workers_locked(self) -> None:
        while len(self._workers) < self.limits.max_concurrent_jobs:
            worker = threading.Thread(
                target=self._worker,
                name=f"fabric-work-{len(self._workers)}",
                daemon=True,
            )
            self._workers.append(worker)
            worker.start()

    def _worker(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if self._closed and not self._queue:
                    return
                item = self._queue.popleft()
                self._running[item.token] = item.owner_key

            spec = item.spec
            try:
                if spec is None:
                    continue
                if not item.future.set_running_or_notify_cancel():
                    self._notify_abandoned(item, spec, "cancelled_before_start")
                    continue
                try:
                    value = item.runner(spec)
                except BaseException as exc:
                    item.future.set_exception(exc)
                else:
                    item.future.set_result(value)
            finally:
                # Drop the scheduler's last raw-prompt reference before making
                # the capacity available to a later submitter.
                item.spec = None
                spec = None
                with self._condition:
                    self._running.pop(item.token, None)
                    self._condition.notify_all()

    @staticmethod
    def _notify_abandoned(item: _WorkItem, spec: BackgroundRunSpec, reason: str) -> None:
        callback = item.on_abandon
        if callback is None:
            return
        try:
            callback(spec, reason)
        except Exception as exc:
            _log.error(
                "background work abandon callback failed reason=%s error_type=%s",
                reason,
                type(exc).__name__,
            )

    def cancel_owner(self, owner_key: str, *, reason: str = "service_shutdown") -> int:
        """Drop queued/reserved payloads for one profile, never another."""

        abandoned: list[tuple[_WorkItem, BackgroundRunSpec]] = []
        with self._condition:
            for token, owner in list(self._reservations.items()):
                if owner == owner_key:
                    self._reservations.pop(token, None)

            kept: deque[_WorkItem] = deque()
            while self._queue:
                item = self._queue.popleft()
                if item.owner_key != owner_key:
                    kept.append(item)
                    continue
                spec = item.spec
                if spec is not None:
                    abandoned.append((item, spec))
                if not item.future.done():
                    item.future.set_exception(WorkSchedulerClosed(reason))
                item.spec = None
            self._queue = kept
            self._condition.notify_all()

        for item, spec in abandoned:
            self._notify_abandoned(item, spec, reason)
        return len(abandoned)

    def owner_load(self, owner_key: str) -> int:
        with self._condition:
            return (
                sum(owner == owner_key for owner in self._reservations.values())
                + sum(item.owner_key == owner_key for item in self._queue)
                + sum(owner == owner_key for owner in self._running.values())
            )

    def stats(self) -> SchedulerStats:
        with self._condition:
            return SchedulerStats(
                reserved=len(self._reservations),
                queued=len(self._queue),
                running=len(self._running),
                max_concurrent_jobs=self.limits.max_concurrent_jobs,
                max_queued_jobs=self.limits.max_queued_jobs,
                closed=self._closed,
            )

    def shutdown(self, *, wait: bool = False, timeout: float | None = None) -> None:
        """Stop admission, discard queued payloads, and optionally join workers."""

        abandoned: list[tuple[_WorkItem, BackgroundRunSpec]] = []
        with self._condition:
            if not self._closed:
                self._closed = True
                self._reservations.clear()
                while self._queue:
                    item = self._queue.popleft()
                    spec = item.spec
                    if spec is not None:
                        abandoned.append((item, spec))
                    if not item.future.done():
                        item.future.set_exception(
                            WorkSchedulerClosed("work scheduler is shut down")
                        )
                    item.spec = None
                self._condition.notify_all()
            workers = tuple(self._workers)

        for item, spec in abandoned:
            self._notify_abandoned(item, spec, "scheduler_shutdown")

        if wait:
            deadline = None if timeout is None else monotonic() + max(0.0, timeout)
            for worker in workers:
                if worker is threading.current_thread():
                    continue
                remaining = None if deadline is None else max(0.0, deadline - monotonic())
                worker.join(remaining)

    def _reservation_active(self, token: str, owner_key: str) -> bool:
        with self._condition:
            return self._reservations.get(token) == owner_key

    def _release_reservation(self, token: str, owner_key: str) -> bool:
        with self._condition:
            if self._reservations.get(token) != owner_key:
                return False
            self._reservations.pop(token)
            self._condition.notify_all()
            return True


_global_scheduler_lock = threading.RLock()
_global_scheduler: GlobalWorkScheduler | None = None


def _limits_from_current_config() -> SchedulerLimits:
    try:
        from fabric_cli.config import load_config

        config = load_config()
    except Exception:
        config = None
    return SchedulerLimits.from_config(config)


def get_global_work_scheduler(
    *, limits: SchedulerLimits | None = None
) -> GlobalWorkScheduler:
    """Return the one process-global scheduler, independent of profile."""

    global _global_scheduler
    with _global_scheduler_lock:
        if _global_scheduler is None or _global_scheduler.stats().closed:
            _global_scheduler = GlobalWorkScheduler(limits or _limits_from_current_config())
        elif limits is not None and _global_scheduler.limits != limits:
            _log.warning(
                "Ignoring per-caller work scheduler limits %s; process-global limits are %s",
                limits,
                _global_scheduler.limits,
            )
        return _global_scheduler


@dataclass(slots=True)
class _RuntimeRecord:
    run_id: str
    owner: OwnerProof
    cancel: Callable[[], None]
    lock: threading.RLock
    cancel_signalled: bool = False


class RuntimeRegistry:
    """Exact-generation live Run registry with at-most-once interruption."""

    def __init__(self, local_owner: OwnerProof) -> None:
        self._local_owner = local_owner
        self._lock = threading.RLock()
        self._records: dict[str, _RuntimeRecord] = {}

    def register(
        self,
        *,
        run_id: str,
        owner: OwnerProof,
        cancel: Callable[[], None],
    ) -> None:
        self._require_local(owner)
        record = _RuntimeRecord(run_id, owner, cancel, threading.RLock())
        with self._lock:
            if run_id in self._records:
                raise WorkServiceError(f"runtime already registered: {run_id}")
            self._records[run_id] = record

    def cancel(self, run_id: str, *, owner: OwnerProof) -> bool:
        self._require_local(owner)
        with self._lock:
            record = self._records.get(run_id)
        if record is None:
            return False
        with record.lock:
            if record.owner != owner:
                raise RuntimeOwnerMismatch("runtime owner generation does not match")
            if record.cancel_signalled:
                return False
            record.cancel_signalled = True
            callback = record.cancel
        callback()
        return True

    def unregister(self, run_id: str, *, owner: OwnerProof) -> bool:
        self._require_local(owner)
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return False
            if record.owner != owner:
                raise RuntimeOwnerMismatch("runtime owner generation does not match")
            self._records.pop(run_id)
            return True

    def shutdown(self) -> int:
        with self._lock:
            records = tuple(self._records.values())
            self._records.clear()
        count = 0
        for record in records:
            with record.lock:
                if record.cancel_signalled:
                    continue
                record.cancel_signalled = True
                callback = record.cancel
            try:
                callback()
            except Exception as exc:
                _log.error(
                    "runtime cancellation failed run_id=%s error_type=%s",
                    record.run_id,
                    type(exc).__name__,
                )
            count += 1
        return count

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._records)

    def _require_local(self, owner: OwnerProof) -> None:
        if owner != self._local_owner:
            raise RuntimeOwnerMismatch("runtime belongs to another process generation")


@dataclass(frozen=True, slots=True)
class WaiterIdentity:
    attention_id: str
    waiter_generation: str
    runtime_session_id: str
    owner: OwnerProof


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    attention_id: str
    waiter_generation: str
    resolution_token: str
    accepted: bool
    outcome_known: bool
    replayed: bool = False


@dataclass(slots=True)
class _WaiterRecord:
    identity: WaiterIdentity
    deliver: Callable[[object], bool | None]
    cancel: Callable[[], None] | None
    terminal: Callable[[], None] | None
    lock: threading.RLock
    delivered_token: str | None = None
    delivery_result: DeliveryResult | None = None
    terminal_notified: bool = False


# ATTENTION CLAIM / DELIVERY / FINALIZE
# =====================================
# RPC exact attention/version/idempotency
#               |
#               v
# per-item lock + exact local owner/waiter generation
#               |
#               v
# ledger CAS: pending -> resolving (reserved receipt)
#               |
#               +-- waiter missing after CAS -> orphaned; never try another
#               |
#               v
# waiter marks resolution token consumed BEFORE handing off raw value
#               |
#               v
# ledger finalizes resolved/denied + sanitized receipt
#
# Crash after callback acceptance but before the final durable commit:
# startup sees resolving/nonfinal receipt and records
# orphaned(delivery_outcome_unknown).  Raw input is never replayed.


class LockedWaiter:
    """A waiter handle valid only while its per-item registry lock is held."""

    __slots__ = ("_record",)

    def __init__(self, record: _WaiterRecord) -> None:
        self._record = record

    @property
    def identity(self) -> WaiterIdentity:
        return self._record.identity

    def deliver_once(self, *, resolution_token: str, raw_value: object) -> DeliveryResult:
        token = str(resolution_token).strip()
        if not token:
            raise ValueError("resolution_token is required")
        record = self._record
        prior = record.delivery_result
        if record.delivered_token is not None:
            if record.delivered_token != token:
                raise WaiterAlreadyConsumed("waiter was consumed by another resolution")
            if prior is None or not prior.outcome_known:
                raise DeliveryOutcomeUnknown("prior waiter delivery outcome is unknown")
            return replace(prior, replayed=True)

        # Mark the token consumed *before* invoking arbitrary callback code.
        # If it signals a thread and then raises, replay must remain forbidden.
        record.delivered_token = token
        try:
            callback_result = record.deliver(raw_value)
        except BaseException as exc:
            record.delivery_result = DeliveryResult(
                attention_id=record.identity.attention_id,
                waiter_generation=record.identity.waiter_generation,
                resolution_token=token,
                accepted=False,
                outcome_known=False,
            )
            raise DeliveryOutcomeUnknown("waiter delivery outcome is unknown") from exc

        result = DeliveryResult(
            attention_id=record.identity.attention_id,
            waiter_generation=record.identity.waiter_generation,
            resolution_token=token,
            accepted=callback_result is not False,
            outcome_known=True,
        )
        record.delivery_result = result
        return result

    def cancel_if_pending(self) -> bool:
        """Wake an undelivered waiter after its durable terminal commit."""

        record = self._record
        if record.delivered_token is not None or record.cancel is None:
            return False
        try:
            record.cancel()
        except Exception as exc:
            _log.error(
                "attention waiter cancellation failed attention_id=%s error_type=%s",
                record.identity.attention_id,
                type(exc).__name__,
            )
            return False
        return True

    def notify_terminal(self) -> bool:
        """Signal one caller only after its durable terminal commit."""

        record = self._record
        if record.terminal_notified:
            return False
        record.terminal_notified = True
        if record.terminal is None:
            return False
        try:
            record.terminal()
        except Exception as exc:
            _log.error(
                "attention terminal callback failed attention_id=%s error_type=%s",
                record.identity.attention_id,
                type(exc).__name__,
            )
            return False
        return True


class WaiterRegistry:
    """Per-Attention locks and exact, one-shot raw-value delivery."""

    def __init__(self, local_owner: OwnerProof) -> None:
        self._local_owner = local_owner
        self._lock = threading.RLock()
        self._records: dict[str, _WaiterRecord] = {}

    def register(
        self,
        *,
        attention_id: str,
        runtime_session_id: str,
        owner: OwnerProof,
        deliver: Callable[[object], bool | None],
        cancel: Callable[[], None] | None = None,
        terminal: Callable[[], None] | None = None,
        waiter_generation: str | None = None,
    ) -> WaiterIdentity:
        self._require_local(owner)
        generation = str(waiter_generation or f"wait_{uuid.uuid4().hex}").strip()
        if not attention_id.strip() or not runtime_session_id.strip() or not generation:
            raise ValueError("attention, runtime session, and waiter generation are required")
        identity = WaiterIdentity(attention_id, generation, runtime_session_id, owner)
        record = _WaiterRecord(
            identity,
            deliver,
            cancel,
            terminal,
            threading.RLock(),
        )
        with self._lock:
            if attention_id in self._records:
                raise WorkServiceError(f"waiter already registered: {attention_id}")
            self._records[attention_id] = record
        return identity

    @contextmanager
    def lock_and_require_local_owner(
        self,
        *,
        attention_id: str,
        owner: OwnerProof,
        waiter_generation: str,
    ) -> Iterator[LockedWaiter]:
        self._require_local(owner)
        with self._lock:
            record = self._records.get(attention_id)
        if record is None:
            raise WaiterUnavailable("matching attention waiter is unavailable")
        with record.lock:
            with self._lock:
                if self._records.get(attention_id) is not record:
                    raise WaiterUnavailable("matching attention waiter is unavailable")
            if record.identity.owner != owner:
                raise RuntimeOwnerMismatch("attention waiter belongs to another owner")
            if record.identity.waiter_generation != waiter_generation:
                raise WaiterUnavailable("attention waiter generation does not match")
            yield LockedWaiter(record)

    def deliver_once(
        self,
        *,
        attention_id: str,
        owner: OwnerProof,
        waiter_generation: str,
        resolution_token: str,
        raw_value: object,
    ) -> DeliveryResult:
        with self.lock_and_require_local_owner(
            attention_id=attention_id,
            owner=owner,
            waiter_generation=waiter_generation,
        ) as waiter:
            return waiter.deliver_once(
                resolution_token=resolution_token,
                raw_value=raw_value,
            )

    def unregister(
        self,
        attention_id: str,
        *,
        owner: OwnerProof,
        waiter_generation: str,
    ) -> bool:
        self._require_local(owner)
        with self._lock:
            record = self._records.get(attention_id)
            if record is None:
                return False
            if record.identity.owner != owner:
                raise RuntimeOwnerMismatch("attention waiter belongs to another owner")
            if record.identity.waiter_generation != waiter_generation:
                raise WaiterUnavailable("attention waiter generation does not match")
            self._records.pop(attention_id)
            return True

    def get_identity(self, attention_id: str) -> WaiterIdentity:
        """Return the exact live waiter identity without exposing its callback."""

        with self._lock:
            record = self._records.get(attention_id)
            if record is None:
                raise WaiterUnavailable("matching attention waiter is unavailable")
            return record.identity

    def list_identities(
        self,
        *,
        runtime_session_id: str | None,
        limit: int = 100,
    ) -> tuple[WaiterIdentity, ...]:
        """Return one bounded session batch without removing or waking it."""

        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._lock:
            identities: list[WaiterIdentity] = []
            for record in self._records.values():
                if (
                    runtime_session_id is not None
                    and record.identity.runtime_session_id != runtime_session_id
                ):
                    continue
                identities.append(record.identity)
                if len(identities) >= limit:
                    break
            return tuple(identities)

    def cancel_session(self, runtime_session_id: str) -> int:
        with self._lock:
            records = [
                record
                for record in self._records.values()
                if record.identity.runtime_session_id == runtime_session_id
            ]
            for record in records:
                self._records.pop(record.identity.attention_id, None)
        return self._cancel_records(records)

    def shutdown(self) -> int:
        with self._lock:
            records = list(self._records.values())
            self._records.clear()
        return self._cancel_records(records)

    @staticmethod
    def _cancel_records(records: Iterable[_WaiterRecord]) -> int:
        count = 0
        for record in records:
            callback = record.cancel
            if callback is None:
                continue
            with record.lock:
                if record.delivered_token is not None:
                    continue
                try:
                    callback()
                except Exception as exc:
                    _log.error(
                        "attention waiter cancellation failed attention_id=%s error_type=%s",
                        record.identity.attention_id,
                        type(exc).__name__,
                    )
                count += 1
        return count

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._records)

    def _require_local(self, owner: OwnerProof) -> None:
        if owner != self._local_owner:
            raise RuntimeOwnerMismatch("attention belongs to another process generation")


@runtime_checkable
class WorkLedgerProtocol(Protocol):
    """Small structural boundary needed by the runtime service."""

    @property
    def ledger_id(self) -> str: ...

    def run_retention(
        self,
        *,
        event_batch_size: int = DEFAULT_WORK_RETENTION_EVENT_BATCH_SIZE,
        idempotency_batch_size: int = DEFAULT_WORK_RETENTION_IDEMPOTENCY_BATCH_SIZE,
        subject_batch_size: int = DEFAULT_WORK_RETENTION_SUBJECT_BATCH_SIZE,
    ) -> Mapping[str, int]: ...

    def close(self) -> None: ...


def _ledger_identity(ledger: object) -> str:
    value = getattr(ledger, "ledger_id", None)
    if callable(value):
        value = value()
    if value is None:
        getter = getattr(ledger, "get_ledger_id", None)
        value = getter() if callable(getter) else None
    identity = str(value or "").strip()
    if not identity:
        raise WorkStoreRebound("ledger identity is unavailable")
    return identity


def _retention_counter(result: object, field: str) -> int:
    """Read a bounded numeric maintenance result without logging arbitrary data."""

    if not isinstance(result, Mapping):
        return 0
    value = result.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


class WorkService:
    """Profile-scoped runtime state paired with one durable ledger instance."""

    def __init__(
        self,
        profile_home: str | Path,
        *,
        ledger: WorkLedgerProtocol,
        scheduler: GlobalWorkScheduler | None = None,
        owner: OwnerProof | None = None,
        pid_exists: Callable[[int], bool | None] = _default_pid_exists,
        start_token_probe: Callable[[int], str | int | None] = _default_start_token,
        clock: Callable[[], float] = monotonic,
        auto_reconcile: bool = True,
        maintenance_interval_seconds: float = DEFAULT_WORK_MAINTENANCE_INTERVAL_SECONDS,
        maintenance_retry_seconds: float = DEFAULT_WORK_MAINTENANCE_RETRY_SECONDS,
        maintenance_event_batch_size: int = DEFAULT_WORK_RETENTION_EVENT_BATCH_SIZE,
        maintenance_idempotency_batch_size: int = DEFAULT_WORK_RETENTION_IDEMPOTENCY_BATCH_SIZE,
        maintenance_subject_batch_size: int = DEFAULT_WORK_RETENTION_SUBJECT_BATCH_SIZE,
    ) -> None:
        if (
            isinstance(maintenance_interval_seconds, bool)
            or not isinstance(maintenance_interval_seconds, (int, float))
            or not math.isfinite(maintenance_interval_seconds)
            or maintenance_interval_seconds <= 0
        ):
            raise ValueError("maintenance_interval_seconds must be finite and positive")
        if (
            isinstance(maintenance_retry_seconds, bool)
            or not isinstance(maintenance_retry_seconds, (int, float))
            or not math.isfinite(maintenance_retry_seconds)
            or maintenance_retry_seconds <= 0
        ):
            raise ValueError("maintenance_retry_seconds must be finite and positive")
        for field, value, maximum in (
            ("maintenance_event_batch_size", maintenance_event_batch_size, 10_000),
            ("maintenance_idempotency_batch_size", maintenance_idempotency_batch_size, 10_000),
            ("maintenance_subject_batch_size", maintenance_subject_batch_size, 1_000),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= maximum
            ):
                raise ValueError(f"{field} must be an integer from 1 through {maximum}")
        self.profile_home = normalize_profile_home(profile_home)
        self.work_db_path = self.profile_home / "work.db"
        self.cache_key = os.path.normcase(str(self.work_db_path))
        self.owner = owner or create_process_owner_proof()
        self.ledger = ledger
        self._ledger_id = _ledger_identity(ledger)
        self.scheduler = scheduler or get_global_work_scheduler()
        self.runtimes = RuntimeRegistry(self.owner)
        self.waiters = WaiterRegistry(self.owner)
        self._pid_exists = pid_exists
        self._start_token_probe = start_token_probe
        self._clock = clock
        self._lock = threading.RLock()
        self._maintenance_condition = threading.Condition(self._lock)
        self._closed = False
        self._last_used = clock()
        self._maintenance_interval_seconds = float(maintenance_interval_seconds)
        self._maintenance_retry_seconds = float(maintenance_retry_seconds)
        self._maintenance_event_batch_size = maintenance_event_batch_size
        self._maintenance_idempotency_batch_size = maintenance_idempotency_batch_size
        self._maintenance_subject_batch_size = maintenance_subject_batch_size
        self._maintenance_due_at = self._last_used
        self._maintenance_running = False
        self._maintenance_runs = 0
        self._maintenance_failures = 0
        self._maintenance_events_deleted = 0
        self._maintenance_idempotency_deleted = 0
        self._maintenance_jobs_deleted = 0
        self._maintenance_attention_deleted = 0
        self._maintenance_catchup_batches = 0
        self._job_controls: dict[str, BackgroundRuntimeControl] = {}
        self._job_futures: dict[str, Future[Any]] = {}
        if auto_reconcile:
            self.reconcile_startup()

    @property
    def ledger_id(self) -> str:
        self.assert_store_fence()
        return self._ledger_id

    @property
    def last_used(self) -> float:
        with self._lock:
            return self._last_used

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def is_idle(self) -> bool:
        with self._lock:
            if self._maintenance_running:
                return False
        return (
            self.runtimes.active_count == 0
            and self.waiters.active_count == 0
            and self.scheduler.owner_load(self.cache_key) == 0
        )

    @property
    def maintenance_due_at(self) -> float:
        """Monotonic deadline used by the cache's one background maintainer."""

        with self._lock:
            return self._maintenance_due_at

    @property
    def maintenance_counters(self) -> dict[str, int]:
        """Redacted, process-local retention counters for future doctor output."""

        with self._lock:
            return {
                "runs": self._maintenance_runs,
                "failures": self._maintenance_failures,
                "events_deleted": self._maintenance_events_deleted,
                "idempotency_deleted": self._maintenance_idempotency_deleted,
                "jobs_deleted": self._maintenance_jobs_deleted,
                "attention_deleted": self._maintenance_attention_deleted,
            }

    def touch(self) -> None:
        with self._lock:
            self._require_open_locked()
            self._last_used = self._clock()

    def assert_store_fence(self) -> None:
        with self._lock:
            self._assert_store_fence_locked()

    def _assert_store_fence_locked(self) -> None:
        """Verify the live service still owns the ledger while admission is locked."""

        self._require_open_locked()
        self._assert_ledger_identity()

    def _assert_ledger_identity(self) -> None:
        """Verify stable ledger identity without taking the service lock."""

        assert_identity = getattr(self.ledger, "assert_store_identity", None)
        if callable(assert_identity):
            assert_identity()
        current = _ledger_identity(self.ledger)
        if current != self._ledger_id:
            raise WorkStoreRebound(
                "work ledger was replaced; restart the profile service before mutating"
            )

    def reserve_background_capacity(self) -> CapacityReservation:
        # Keep the service-open check, scheduler reservation, and touch in one
        # critical section.  Otherwise shutdown can cancel the old owner load
        # between the check and reserve, leaving a reservation created after
        # cleanup while this method raises from ``touch()``.
        with self._lock:
            self._assert_store_fence_locked()
            reservation = self.scheduler.reserve(owner_key=self.cache_key)
            self._last_used = self._clock()
            return reservation

    def submit_background(
        self,
        reservation: CapacityReservation,
        spec: BackgroundRunSpec,
        runner: Callable[[BackgroundRunSpec], _T],
        *,
        on_abandon: Callable[[BackgroundRunSpec, str], None] | None = None,
    ) -> Future[_T]:
        # Submission is an admission commit.  Serialize it with shutdown so a
        # successfully queued/started Run is always returned to its caller;
        # shutdown may subsequently cancel queued work, but cannot make this
        # method report WorkServiceClosed after the scheduler accepted it.
        with self._lock:
            self._assert_store_fence_locked()
            if reservation.owner_key != self.cache_key:
                raise RuntimeOwnerMismatch("capacity belongs to another profile service")
            if normalize_profile_home(spec.profile_home) != self.profile_home:
                raise RuntimeOwnerMismatch("background Run belongs to another profile")
            if spec.owner != self.owner:
                raise RuntimeOwnerMismatch(
                    "background Run belongs to another process generation"
                )
            future = self.scheduler.submit(
                reservation,
                spec,
                runner,
                on_abandon=on_abandon,
            )
            future.add_done_callback(lambda _future: self._touch_if_open())
            self._last_used = self._clock()
            return future

    def _touch_if_open(self) -> None:
        with self._lock:
            if not self._closed:
                self._last_used = self._clock()

    def run_due_maintenance(self) -> bool:
        """Run one bounded retention batch when this profile is due.

        The cache invokes this from its sole background maintainer, never from
        a Job or Attention transition.  The service lock only reserves the
        attempt; SQLite work happens after it is released so interactive
        mutations and cache lookups do not wait behind retention.
        """

        with self._lock:
            if self._closed or self._maintenance_running:
                return False
            now = self._clock()
            if now < self._maintenance_due_at:
                return False
            # Reserve the single attempt before touching SQLite. The cache can
            # have only one maintainer, but direct callers are also safe.
            self._maintenance_running = True

        started_at = monotonic()
        try:
            self._assert_ledger_identity()
            run_retention = getattr(self.ledger, "run_retention", None)
            if not callable(run_retention):
                raise RuntimeError("work ledger does not support bounded retention")
            result = run_retention(
                event_batch_size=self._maintenance_event_batch_size,
                idempotency_batch_size=self._maintenance_idempotency_batch_size,
                subject_batch_size=self._maintenance_subject_batch_size,
            )
        except BaseException as exc:
            duration_ms = max(0, round((monotonic() - started_at) * 1_000))
            with self._lock:
                self._maintenance_running = False
                self._maintenance_failures += 1
                self._maintenance_due_at = self._clock() + min(
                    self._maintenance_retry_seconds,
                    self._maintenance_interval_seconds,
                )
                self._maintenance_condition.notify_all()
            if not isinstance(exc, Exception):
                raise
            _log.warning(
                "work retention failed error_type=%s duration_ms=%d",
                type(exc).__name__,
                duration_ms,
            )
            return False

        events_deleted = _retention_counter(result, "events_deleted")
        idempotency_deleted = _retention_counter(result, "idempotency_deleted")
        jobs_deleted = _retention_counter(result, "jobs_deleted")
        attention_deleted = _retention_counter(result, "attention_deleted")
        duration_ms = max(0, round((monotonic() - started_at) * 1_000))
        saturated = (
            events_deleted >= self._maintenance_event_batch_size
            or idempotency_deleted >= self._maintenance_idempotency_batch_size
            or jobs_deleted + attention_deleted >= self._maintenance_subject_batch_size
        )
        with self._lock:
            self._maintenance_running = False
            self._maintenance_runs += 1
            self._maintenance_events_deleted += events_deleted
            self._maintenance_idempotency_deleted += idempotency_deleted
            self._maintenance_jobs_deleted += jobs_deleted
            self._maintenance_attention_deleted += attention_deleted
            if saturated and self._maintenance_catchup_batches < MAX_WORK_MAINTENANCE_CATCHUP_BATCHES:
                self._maintenance_catchup_batches += 1
                self._maintenance_due_at = self._clock() + WORK_MAINTENANCE_CATCHUP_DELAY_SECONDS
            else:
                self._maintenance_catchup_batches = 0
                self._maintenance_due_at = self._clock() + self._maintenance_interval_seconds
            self._maintenance_condition.notify_all()

        log = (
            _log.info
            if events_deleted or idempotency_deleted or jobs_deleted or attention_deleted
            else _log.debug
        )
        log(
            "work retention completed events_deleted=%d idempotency_deleted=%d "
            "jobs_deleted=%d attention_deleted=%d duration_ms=%d",
            events_deleted,
            idempotency_deleted,
            jobs_deleted,
            attention_deleted,
            duration_ms,
        )
        return True

    @staticmethod
    def _replayed_receipt(existing: Mapping[str, Any]) -> dict[str, Any] | None:
        response = existing.get("response")
        if existing.get("state") != "finalized" or not isinstance(response, Mapping):
            return None
        receipt = dict(response)
        receipt["replayed"] = True
        receipt["runtime_started"] = False
        return receipt

    def create_background_job(
        self,
        *,
        runtime_session_id: str,
        source_session_key: str,
        text: str,
        title: str,
        idempotency_key: str,
        agent_inputs: Mapping[str, Any],
        runner: Callable[[BackgroundRunSpec, BackgroundRuntimeControl], Any],
        source: str = "mobile",
        on_changed: Callable[[BackgroundRunSpec, Mapping[str, Any]], None] | None = None,
        on_complete: Callable[[BackgroundRunSpec, Any, str | None], None] | None = None,
    ) -> dict[str, Any]:
        """Admit, durably create, and schedule one creator-bound background Run.

        The idempotency preflight intentionally happens before capacity
        reservation. A concurrent first-create race is still safe: both callers
        may reserve, but the ledger creates one row and the replaying caller
        releases its unused reservation without submitting a second Run.
        """

        from fabric_cli.work_ledger import (
            IdempotencyConflict,
            InvalidPublicData,
            WorkOperationInProgress,
            hash_job_create_envelope,
        )

        if not isinstance(text, str) or not text:
            raise InvalidPublicData("text must be a non-empty string")
        if len(text) > MAX_BACKGROUND_PROMPT_CHARS:
            raise InvalidPublicData(
                f"text exceeds {MAX_BACKGROUND_PROMPT_CHARS} characters"
            )
        sanitized_title = sanitize_public_display(title, max_string_chars=200)

        request_hash = hash_job_create_envelope(
            kind="background_prompt",
            title=sanitized_title,
        )
        get_idempotency = getattr(self.ledger, "get_idempotency")
        existing = get_idempotency(
            operation="job.create", idempotency_key=idempotency_key
        )
        if existing is not None:
            if existing.get("request_hash") != request_hash:
                raise IdempotencyConflict(
                    "idempotency key was reused for a different public envelope"
                )
            replay = self._replayed_receipt(existing)
            if replay is None:
                raise WorkOperationInProgress("Job creation is still in progress")
            return replay

        # Validate and canonicalize every raw, process-local Run input before
        # reserving capacity or committing the durable Job.  The real Job/Run
        # ids are supplied by the ledger below; replacing these valid sentinels
        # cannot re-open validation of any caller-controlled field.
        validated_spec = BackgroundRunSpec.create(
            job_id="job_" + "0" * 32,
            run_id="run_" + "0" * 32,
            profile_home=self.profile_home,
            runtime_session_id=runtime_session_id,
            source_session_key=source_session_key,
            prompt=text,
            owner=self.owner,
            agent_inputs=agent_inputs,
        )

        reservation = self.reserve_background_capacity()
        try:
            receipt = getattr(self.ledger, "create_job")(
                kind="background_prompt",
                title=sanitized_title,
                source=source,
                owner=self.owner,
                idempotency_key=idempotency_key,
                source_session_key=source_session_key,
                runtime_session_id=runtime_session_id,
                runtime_summary={
                    "execution_location": "gateway",
                    "kind": "in_process_agent",
                    "requires_gateway_host_online": True,
                    "result_ref": f"session:{runtime_session_id}",
                    "survives_client_disconnect": True,
                    "survives_gateway_restart": False,
                    "tool_execution": "gateway",
                },
                run_runtime={
                    "kind": "in_process_agent",
                    "owner_state": "creator_bound",
                },
            )
            if receipt.get("replayed"):
                # The ledger detected a concurrent duplicate create for this key
                # (a same-instant first-create race the preflight could not see).
                # Return the same truthful shape as the preflight replay so a
                # client keying on runtime_started is never told a second runtime
                # started for a Run this caller did not schedule.
                reservation.release()
                replayed_receipt = dict(receipt)
                replayed_receipt["replayed"] = True
                replayed_receipt["runtime_started"] = False
                return replayed_receipt

            job = receipt["job"]
            run = job["current_run"]
            spec = replace(
                validated_spec,
                job_id=str(job["job_id"]),
                run_id=str(run["run_id"]),
            )
            runtime_registered = False
            failure_code = "runtime_setup_failed"
            try:
                control = BackgroundRuntimeControl()
                with self._lock:
                    self._assert_store_fence_locked()
                    self._job_controls[spec.job_id] = control
                    self.runtimes.register(
                        run_id=spec.run_id,
                        owner=spec.owner,
                        cancel=control.cancel,
                    )
                    runtime_registered = True
                self._notify_changed(on_changed, spec, job)
                failure_code = "scheduler_submit_failed"
                future = self.submit_background(
                    reservation,
                    spec,
                    lambda queued_spec: self._execute_background_job(
                        queued_spec,
                        control=control,
                        runner=runner,
                        on_changed=on_changed,
                        on_complete=on_complete,
                    ),
                    on_abandon=lambda queued_spec, reason: self._abandon_background_job(
                        queued_spec,
                        reason=reason,
                        on_changed=on_changed,
                        on_complete=on_complete,
                    ),
                )
            except BaseException:
                try:
                    self._finalize_background_failure(
                        spec,
                        code=failure_code,
                        on_changed=on_changed,
                        on_complete=on_complete,
                    )
                finally:
                    with self._lock:
                        self._job_controls.pop(spec.job_id, None)
                    if runtime_registered:
                        with suppress(Exception):
                            self.runtimes.unregister(spec.run_id, owner=spec.owner)
                raise
            with self._lock:
                if spec.job_id in self._job_controls:
                    self._job_futures[spec.job_id] = future
            public_receipt = dict(receipt)
            public_receipt["runtime_started"] = True
            return public_receipt
        except BaseException:
            reservation.release()
            raise

    @staticmethod
    def _notify_changed(
        callback: Callable[[BackgroundRunSpec, Mapping[str, Any]], None] | None,
        spec: BackgroundRunSpec,
        subject: Mapping[str, Any],
    ) -> None:
        if callback is None:
            return
        try:
            callback(spec, subject)
        except Exception:
            _log.debug("work.changed callback failed job_id=%s", spec.job_id, exc_info=True)

    @staticmethod
    def _notify_complete(
        callback: Callable[[BackgroundRunSpec, Any, str | None], None] | None,
        spec: BackgroundRunSpec,
        result: Any,
        error_code: str | None,
    ) -> None:
        if callback is None:
            return
        try:
            callback(spec, result, error_code)
        except Exception:
            _log.debug(
                "background completion callback failed job_id=%s",
                spec.job_id,
                exc_info=True,
            )

    def _transition_creator_job(
        self,
        spec: BackgroundRunSpec,
        *,
        next_status: str,
        on_changed: Callable[[BackgroundRunSpec, Mapping[str, Any]], None] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if spec.owner != self.owner:
            raise RuntimeOwnerMismatch("Run belongs to another process generation")
        with self._lock:
            if self._job_controls.get(spec.job_id) is None:
                raise RuntimeOwnerMismatch("Run is not owned by this service")
        job = getattr(self.ledger, "get_job")(spec.job_id, detail=False)
        current_run = job.get("current_run")
        if not isinstance(current_run, Mapping) or current_run.get("run_id") != spec.run_id:
            raise RuntimeOwnerMismatch("Run is no longer the Job's current attempt")
        transitioned = getattr(self.ledger, "transition_job")(
            spec.job_id,
            expected_version=int(job["version"]),
            next_status=next_status,
            **kwargs,
        )
        self._notify_changed(on_changed, spec, transitioned)
        return transitioned

    def _execute_background_job(
        self,
        spec: BackgroundRunSpec,
        *,
        control: BackgroundRuntimeControl,
        runner: Callable[[BackgroundRunSpec, BackgroundRuntimeControl], Any],
        on_changed: Callable[[BackgroundRunSpec, Mapping[str, Any]], None] | None,
        on_complete: Callable[[BackgroundRunSpec, Any, str | None], None] | None,
    ) -> Any:
        result: Any = None
        error_code: str | None = None
        try:
            current = getattr(self.ledger, "get_job")(spec.job_id, detail=False)
            if control.cancelled or current["status"] == "cancel_requested":
                if current["status"] == "queued":
                    self._transition_creator_job(
                        spec,
                        next_status="cancel_requested",
                        on_changed=on_changed,
                    )
                self._transition_creator_job(
                    spec,
                    next_status="cancelled",
                    on_changed=on_changed,
                    summary="Background work cancelled",
                )
                error_code = "cancelled"
                return None

            self._transition_creator_job(
                spec,
                next_status="claimed",
                on_changed=on_changed,
                claim_token=f"claim_{uuid.uuid4().hex}",
            )
            if control.cancelled:
                self._transition_creator_job(
                    spec,
                    next_status="cancel_requested",
                    on_changed=on_changed,
                )
                self._transition_creator_job(
                    spec,
                    next_status="cancelled",
                    on_changed=on_changed,
                    summary="Background work cancelled",
                )
                error_code = "cancelled"
                return None
            self._transition_creator_job(
                spec,
                next_status="running",
                on_changed=on_changed,
            )
            result = runner(spec, control)
            current = getattr(self.ledger, "get_job")(spec.job_id, detail=False)
            if control.cancelled or current["status"] == "cancel_requested":
                if current["status"] != "cancel_requested":
                    self._transition_creator_job(
                        spec,
                        next_status="cancel_requested",
                        on_changed=on_changed,
                    )
                self._transition_creator_job(
                    spec,
                    next_status="cancelled",
                    on_changed=on_changed,
                    event_type="job.run_late_result",
                    summary="Background work cancelled",
                )
                error_code = "cancelled"
            elif control.sensitive_input:
                self._transition_creator_job(
                    spec,
                    next_status="succeeded",
                    on_changed=on_changed,
                    summary="Background work completed",
                    result_omitted_reason="sensitive_input",
                )
            else:
                # Never copy the agent's conversation/result dictionary into
                # work.db: it can contain the raw prompt or tool secrets. The
                # durable Job points at its session authority instead.
                self._transition_creator_job(
                    spec,
                    next_status="succeeded",
                    on_changed=on_changed,
                    summary="Background work completed",
                    result={"completed": True},
                )
            return result
        except BaseException as exc:
            error_code = "background_execution_failed"
            _log.error(
                "background Run failed job_id=%s run_id=%s error_type=%s",
                spec.job_id,
                spec.run_id,
                type(exc).__name__,
            )
            try:
                current = getattr(self.ledger, "get_job")(spec.job_id, detail=False)
                if current["status"] == "cancel_requested" or control.cancelled:
                    if current["status"] != "cancel_requested":
                        self._transition_creator_job(
                            spec,
                            next_status="cancel_requested",
                            on_changed=on_changed,
                        )
                    self._transition_creator_job(
                        spec,
                        next_status="cancelled",
                        on_changed=on_changed,
                        summary="Background work cancelled",
                    )
                    error_code = "cancelled"
                elif current["status"] in {"claimed", "running", "waiting_attention"}:
                    self._transition_creator_job(
                        spec,
                        next_status="failed",
                        on_changed=on_changed,
                        summary="Background work failed",
                        error={
                            "code": "background_execution_failed",
                            "message": "Background execution failed",
                        },
                    )
            except Exception as finalize_exc:
                _log.error(
                    "could not finalize failed background Run job_id=%s error_type=%s",
                    spec.job_id,
                    type(finalize_exc).__name__,
                )
            raise exc
        finally:
            completion_result = result
            if control.sensitive_input:
                # A model may echo a clarify/secret/sudo response.  Taint the
                # whole completion egress, not only the durable result row.
                completion_result = (
                    {"final_response": "Background work completed"}
                    if error_code is None
                    else None
                )
            self._notify_complete(on_complete, spec, completion_result, error_code)
            with suppress(Exception):
                self.runtimes.unregister(spec.run_id, owner=spec.owner)
            with self._lock:
                self._job_controls.pop(spec.job_id, None)
                self._job_futures.pop(spec.job_id, None)

    def _finalize_background_failure(
        self,
        spec: BackgroundRunSpec,
        *,
        code: str,
        on_changed: Callable[[BackgroundRunSpec, Mapping[str, Any]], None] | None,
        on_complete: Callable[[BackgroundRunSpec, Any, str | None], None] | None,
    ) -> None:
        try:
            current = getattr(self.ledger, "get_job")(spec.job_id, detail=False)
            if current["status"] == "queued":
                current_run = current.get("current_run")
                if (
                    not isinstance(current_run, Mapping)
                    or current_run.get("run_id") != spec.run_id
                ):
                    raise RuntimeOwnerMismatch(
                        "Run is no longer the Job's current attempt"
                    )
                transitioned = getattr(self.ledger, "transition_job")(
                    spec.job_id,
                    expected_version=int(current["version"]),
                    next_status="interrupted",
                    summary="Background work could not start",
                    error={"code": code, "message": "Background worker unavailable"},
                )
                self._notify_changed(on_changed, spec, transitioned)
        finally:
            self._notify_complete(on_complete, spec, None, code)

    def _abandon_background_job(
        self,
        spec: BackgroundRunSpec,
        *,
        reason: str,
        on_changed: Callable[[BackgroundRunSpec, Mapping[str, Any]], None] | None,
        on_complete: Callable[[BackgroundRunSpec, Any, str | None], None] | None,
    ) -> None:
        try:
            current = getattr(self.ledger, "get_job")(spec.job_id, detail=False)
            if current["status"] == "cancel_requested":
                self._transition_creator_job(
                    spec,
                    next_status="cancelled",
                    on_changed=on_changed,
                    summary="Background work cancelled",
                )
                code = "cancelled"
            elif current["status"] == "queued":
                self._transition_creator_job(
                    spec,
                    next_status="interrupted",
                    on_changed=on_changed,
                    summary="Background work interrupted before start",
                    error={
                        "code": "runner_never_started",
                        "message": "Background worker stopped before execution",
                    },
                )
                code = "runner_never_started"
            else:
                return
            self._notify_complete(on_complete, spec, None, code)
        except Exception as exc:
            _log.error(
                "could not finalize abandoned background Run job_id=%s reason=%s "
                "error_type=%s",
                spec.job_id,
                reason,
                type(exc).__name__,
            )
        finally:
            with suppress(Exception):
                self.runtimes.unregister(spec.run_id, owner=spec.owner)
            with self._lock:
                self._job_controls.pop(spec.job_id, None)
                self._job_futures.pop(spec.job_id, None)

    def cancel_background_job(
        self,
        *,
        job_id: str,
        expected_version: int,
        idempotency_key: str,
        on_changed: Callable[[BackgroundRunSpec, Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """CAS cancellation for an exact Job owned by this process generation."""

        from fabric_cli.work_ledger import (
            RuntimeOwnerMismatch as LedgerRuntimeOwnerMismatch,
        )

        # Replay is resolved by the ledger before inspecting the Job's current
        # version.  That ordering is essential: the first successful request
        # advances the version, but an exact retry must return its original
        # receipt rather than spuriously failing the stale CAS.
        existing = getattr(self.ledger, "get_idempotency")(
            operation="job.cancel", idempotency_key=idempotency_key
        )
        if existing is not None:
            return getattr(self.ledger, "cancel_job")(
                job_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                owner=self.owner,
            )

        job = getattr(self.ledger, "get_job")(job_id, detail=False)
        if str(job.get("status")) in {
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }:
            return getattr(self.ledger, "cancel_job")(
                job_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                owner=self.owner,
            )
        if int(job["version"]) != expected_version:
            from fabric_cli.work_ledger import VersionConflict

            raise VersionConflict("Job version does not match expected_version")
        run = job.get("current_run")
        run_id = str(run.get("run_id") if isinstance(run, Mapping) else "")
        with self._lock:
            control = self._job_controls.get(job_id)
            future = self._job_futures.get(job_id)
        if control is None or not run_id:
            raise LedgerRuntimeOwnerMismatch(
                "Job runtime is not owned by this process generation"
            )

        receipt = getattr(self.ledger, "cancel_job")(
            job_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            owner=self.owner,
        )
        if not receipt.get("newly_cancelled"):
            return receipt
        spec = BackgroundRunSpec.create(
            job_id=job_id,
            run_id=run_id,
            profile_home=self.profile_home,
            runtime_session_id=str(job.get("runtime_session_id") or job_id),
            source_session_key=str(job.get("source_session_key") or job_id),
            prompt="[runtime-owned prompt omitted]",
            owner=self.owner,
        )
        # The durable transition and finalized idempotency receipt are both
        # committed before any observer or process-local runtime is notified.
        self._notify_changed(on_changed, spec, receipt["job"])
        try:
            self.runtimes.cancel(run_id, owner=self.owner)
        except Exception as exc:
            # Agent interrupt hooks are arbitrary runtime code.  Cancellation
            # is already durable and BackgroundRuntimeControl is sticky before
            # invoking the hook, so an interrupt failure must not turn the
            # acknowledged mutation into an RPC error or skip queue eviction.
            _log.debug(
                "background runtime interrupt failed run_id=%s error_type=%s",
                run_id,
                type(exc).__name__,
            )
        if future is not None:
            # Remove a queued prompt immediately so it does not retain raw
            # input or consume process-global capacity behind unrelated work.
            # The abandonment callback owns its terminal ``cancelled``
            # transition.  A dequeue race falls through to the sticky runtime
            # cancellation signal above.
            if not self.scheduler.cancel_queued(
                future,
                reason="cancel_requested",
            ):
                future.cancel()
        return receipt

    def set_job_waiting_attention(
        self,
        spec: BackgroundRunSpec,
        *,
        waiting: bool,
        on_changed: Callable[[BackgroundRunSpec, Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Move a creator-owned running Run into/out of its attention wait."""

        return self._transition_creator_job(
            spec,
            next_status="waiting_attention" if waiting else "running",
            on_changed=on_changed,
        )

    def create_attention_waiter(
        self,
        *,
        source_session_key: str,
        runtime_session_id: str,
        request_id: str,
        kind: str,
        title: str,
        public_payload: Mapping[str, Any],
        deliver: Callable[[object], bool | None],
        cancel: Callable[[], None] | None = None,
        terminal: Callable[[], None] | None = None,
        sensitive: bool = False,
        job_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Register a local waiter, then commit its durable public Attention."""

        from fabric_cli.work_ledger import new_work_id

        sanitized_title = sanitize_public_display(title, max_string_chars=200)
        sanitized_payload = sanitize_public_display(public_payload)
        if not isinstance(sanitized_title, str) or not isinstance(
            sanitized_payload, Mapping
        ):
            raise ValueError("Attention public display data is invalid")
        with self._lock:
            self._require_open_locked()
            attention_id = new_work_id("attn")
            identity = self.waiters.register(
                attention_id=attention_id,
                runtime_session_id=runtime_session_id,
                owner=self.owner,
                deliver=deliver,
                cancel=cancel,
                terminal=terminal,
            )
            try:
                return getattr(self.ledger, "create_attention")(
                    attention_id=attention_id,
                    source_session_key=source_session_key,
                    runtime_session_id=runtime_session_id,
                    request_id=request_id,
                    kind=kind,
                    title=sanitized_title,
                    public_payload=sanitized_payload,
                    owner=self.owner,
                    waiter_generation=identity.waiter_generation,
                    sensitive=sensitive,
                    job_id=job_id,
                    run_id=run_id,
                )
            except BaseException:
                self.waiters.unregister(
                    attention_id,
                    owner=self.owner,
                    waiter_generation=identity.waiter_generation,
                )
                raise

    def _finalized_attention_replay(
        self,
        *,
        attention_id: str,
        expected_version: int,
        idempotency_key: str,
        kind: str,
        action: str,
        outcome: str,
    ) -> dict[str, Any] | None:
        """Replay a committed receipt without consulting a process waiter."""

        from fabric_cli.work_ledger import (
            IdempotencyConflict,
            WorkStoreSchemaError,
            hash_attention_response_envelope,
        )

        expected_hash = hash_attention_response_envelope(
            attention_id=attention_id,
            expected_version=expected_version,
            kind=kind,
            action=action,
        )
        existing = getattr(self.ledger, "get_idempotency")(
            operation="attention.respond",
            idempotency_key=idempotency_key,
        )
        if existing is None:
            return None
        if existing.get("request_hash") != expected_hash:
            raise IdempotencyConflict(
                "idempotency key was reused for a different public envelope"
            )
        if existing.get("subject_id") != attention_id:
            raise IdempotencyConflict(
                "idempotency key belongs to a different Attention"
            )
        if existing.get("state") != "finalized":
            return None
        response = existing.get("response")
        if not isinstance(response, Mapping):
            raise WorkStoreSchemaError("finalized Attention receipt is malformed")
        if (
            response.get("attention_id") != attention_id
            or response.get("state") != outcome
            or response.get("delivered") is not True
        ):
            raise WorkStoreSchemaError(
                "finalized Attention receipt violates its response binding"
            )
        replay = dict(response)
        replay["replayed"] = True
        return replay

    def _resume_drained_attention_job(self, attention: Mapping[str, Any]) -> None:
        """Resume a creator-owned waiting Run after its last Attention closes."""

        job_id = str(attention.get("job_id") or "")
        if not job_id:
            return
        try:
            job = getattr(self.ledger, "get_job")(job_id, detail=False)
            if (
                job.get("status") != "waiting_attention"
                or int(job.get("open_attention_count") or 0) != 0
            ):
                return
            current_run = job.get("current_run")
            run_id = str(
                current_run.get("run_id")
                if isinstance(current_run, Mapping)
                else ""
            )
            with self._lock:
                locally_owned = self._job_controls.get(job_id) is not None
            if not locally_owned or not run_id:
                return
            spec = BackgroundRunSpec.create(
                job_id=job_id,
                run_id=run_id,
                profile_home=self.profile_home,
                runtime_session_id=str(job.get("runtime_session_id") or job_id),
                source_session_key=str(job.get("source_session_key") or job_id),
                prompt="[runtime-owned prompt omitted]",
                owner=self.owner,
            )
            self._transition_creator_job(
                spec,
                next_status="running",
                on_changed=None,
            )
        except Exception as exc:
            # Resolution is already committed.  A concurrent terminal/cancel
            # transition is benign and must not turn a successful response
            # into an RPC failure.  Never log exception text: callback/model
            # errors can contain the raw response.
            _log.debug(
                "background Attention resume skipped job_id=%s error_type=%s",
                job_id,
                type(exc).__name__,
            )

    def _attention_terminal_cleanup(
        self,
        attention: Mapping[str, Any],
        identity: WaiterIdentity | None,
    ) -> None:
        if identity is not None:
            try:
                self.waiters.unregister(
                    identity.attention_id,
                    owner=self.owner,
                    waiter_generation=identity.waiter_generation,
                )
            except (WaiterUnavailable, RuntimeOwnerMismatch):
                pass
        self._resume_drained_attention_job(attention)

    def respond_attention(
        self,
        *,
        attention_id: str,
        expected_version: int,
        idempotency_key: str,
        action: str,
        raw_value: object,
    ) -> dict[str, Any]:
        """Claim, deliver, and finalize one exact local Attention response."""

        from fabric_cli.work_ledger import ATTENTION_ACTION_OUTCOMES

        attention = getattr(self.ledger, "get_attention")(attention_id)
        kind = str(attention["kind"])
        outcome = ATTENTION_ACTION_OUTCOMES.get(kind, {}).get(action)
        if outcome is None:
            from fabric_cli.work_ledger import InvalidPublicData

            raise InvalidPublicData("action is not valid for this Attention kind")
        replay = self._finalized_attention_replay(
            attention_id=attention_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            kind=kind,
            action=action,
            outcome=outcome,
        )
        if replay is not None:
            self._resume_drained_attention_job(attention)
            return replay
        persisted_generation = getattr(
            self.ledger, "assert_attention_owner"
        )(
            attention_id,
            owner=self.owner,
        )
        identity: WaiterIdentity | None = None
        terminal_waiter: LockedWaiter | None = None
        receipt: dict[str, Any] | None = None
        terminal_error: BaseException | None = None
        try:
            identity = self.waiters.get_identity(attention_id)
            if identity.waiter_generation != persisted_generation:
                raise WaiterUnavailable(
                    "matching attention waiter generation is unavailable"
                )
            with self.waiters.lock_and_require_local_owner(
                attention_id=attention_id,
                owner=self.owner,
                waiter_generation=identity.waiter_generation,
            ) as waiter:
                claim = getattr(self.ledger, "begin_attention_resolution")(
                    attention_id,
                    expected_version=expected_version,
                    idempotency_key=idempotency_key,
                    kind=kind,
                    action=action,
                    owner=self.owner,
                    waiter_generation=identity.waiter_generation,
                )
                if claim.receipt is not None:
                    receipt = dict(claim.receipt)
                else:
                    assert claim.resolution_token is not None
                    if (
                        kind == "approval"
                        and isinstance(raw_value, Mapping)
                        and raw_value.get("reason")
                    ):
                        job_id = str(attention.get("job_id") or "")
                        with self._lock:
                            control = self._job_controls.get(job_id)
                        if control is not None:
                            control.mark_sensitive_input()
                    try:
                        delivery = waiter.deliver_once(
                            resolution_token=claim.resolution_token,
                            raw_value=raw_value,
                        )
                    except DeliveryOutcomeUnknown as exc:
                        getattr(self.ledger, "finalize_attention_resolution")(
                            claim,
                            state="orphaned",
                            delivered=False,
                            terminal_reason="delivery_outcome_unknown",
                        )
                        terminal_error = exc
                    else:
                        if not delivery.accepted:
                            getattr(self.ledger, "finalize_attention_resolution")(
                                claim,
                                state="orphaned",
                                delivered=False,
                                terminal_reason="waiter_rejected",
                            )
                            terminal_error = WaiterUnavailable(
                                "matching attention waiter rejected the response"
                            )
                        else:
                            receipt = getattr(
                                self.ledger, "finalize_attention_resolution"
                            )(
                                claim,
                                state=outcome,
                                delivered=True,
                            )
                terminal_waiter = waiter
        except WaiterUnavailable:
            # A concurrent identical responder may have finalized and removed
            # the waiter between our preflight and lock acquisition.
            replay = self._finalized_attention_replay(
                attention_id=attention_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                kind=kind,
                action=action,
                outcome=outcome,
            )
            if replay is not None:
                self._resume_drained_attention_job(attention)
                return replay
            raise
        self._attention_terminal_cleanup(attention, identity)
        if terminal_waiter is not None:
            terminal_waiter.notify_terminal()
        if terminal_error is not None:
            raise terminal_error
        assert receipt is not None
        return receipt

    def cancel_attention_session(
        self,
        runtime_session_id: str,
        *,
        terminal_reason: str,
    ) -> list[dict[str, Any]]:
        """Drain one session in bounded exact-waiter batches."""

        return self._drain_attention_waiters(
            runtime_session_id=runtime_session_id,
            terminal_reason=terminal_reason,
            resume_jobs=True,
        )

    def _drain_attention_waiters(
        self,
        *,
        runtime_session_id: str | None,
        terminal_reason: str,
        resume_jobs: bool,
    ) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        while identities := self.waiters.list_identities(
            runtime_session_id=runtime_session_id,
            limit=100,
        ):
            progress = 0
            for identity in identities:
                try:
                    item = self.cancel_attention(
                        identity.attention_id,
                        terminal_reason=terminal_reason,
                        _resume_job=resume_jobs,
                    )
                    if item is not None:
                        changed.append(item)
                    progress += 1
                except WaiterUnavailable:
                    # A responder can finalize and unregister after the batch
                    # snapshot; that item is already drained.
                    try:
                        self.waiters.get_identity(identity.attention_id)
                    except WaiterUnavailable:
                        progress += 1
                except Exception as exc:
                    _log.debug(
                        "attention teardown failed attention_id=%s error_type=%s",
                        identity.attention_id,
                        type(exc).__name__,
                    )
            if progress == 0:
                break
        return changed

    def cancel_attention(
        self,
        attention_id: str,
        *,
        terminal_reason: str,
        _resume_job: bool = True,
    ) -> dict[str, Any] | None:
        """Cancel one exact local waiter, committing before it is awakened."""

        return self._terminate_attention(
            attention_id,
            terminal_reason=terminal_reason,
            pending_state="cancelled",
            resume_job=_resume_job,
        )

    def expire_attention(
        self,
        attention_id: str,
        *,
        terminal_reason: str = "waiter_timeout",
    ) -> dict[str, Any] | None:
        """Expire one exact local waiter whose response deadline elapsed."""

        return self._terminate_attention(
            attention_id,
            terminal_reason=terminal_reason,
            pending_state="expired",
            resume_job=True,
        )

    def _terminate_attention(
        self,
        attention_id: str,
        *,
        terminal_reason: str,
        pending_state: str,
        resume_job: bool,
    ) -> dict[str, Any] | None:
        """Close one exact waiter durably before its callback is awakened."""

        persisted_generation = getattr(
            self.ledger, "assert_attention_owner"
        )(
            attention_id,
            owner=self.owner,
        )
        identity = self.waiters.get_identity(attention_id)
        if identity.owner != self.owner:
            raise RuntimeOwnerMismatch("Attention belongs to another process generation")
        if identity.waiter_generation != persisted_generation:
            raise WaiterUnavailable("matching attention waiter generation is unavailable")
        with self.waiters.lock_and_require_local_owner(
            attention_id=attention_id,
            owner=self.owner,
            waiter_generation=identity.waiter_generation,
        ) as waiter:
            attention = getattr(self.ledger, "get_attention")(attention_id)
            state = str(attention["state"])
            if state not in {"pending", "resolving"}:
                self.waiters.unregister(
                    attention_id,
                    owner=self.owner,
                    waiter_generation=identity.waiter_generation,
                )
                return None
            changed = getattr(self.ledger, "terminate_attention_waiter")(
                attention_id,
                expected_version=int(attention["version"]),
                owner=self.owner,
                waiter_generation=identity.waiter_generation,
                terminal_reason=terminal_reason,
                pending_state=pending_state,
            )
            self.waiters.unregister(
                attention_id,
                owner=self.owner,
                waiter_generation=identity.waiter_generation,
            )
            waiter.cancel_if_pending()
        if resume_job:
            self._resume_drained_attention_job(changed)
        waiter.notify_terminal()
        return changed

    def reconcile_startup(self) -> dict[OwnerProof, OwnerClassification]:
        """Reconcile only owners proven dead/recycled/from another boot.

        The ledger API is intentionally structural while ``work_ledger.py`` is
        independently testable: a ledger that has not implemented recovery yet
        simply yields no candidates.  No raw runtime state is inferred here.
        """

        self.assert_store_fence()
        list_owners = getattr(self.ledger, "list_nonterminal_owners", None)
        reconcile = getattr(self.ledger, "reconcile_owner", None)
        if not callable(list_owners) or not callable(reconcile):
            return {}

        candidates = list(list_owners())
        proofs = [coerce_owner_proof(candidate) for candidate in candidates]
        classifications = classify_owner_group(
            proofs,
            current_boot_token=self.owner.boot_token,
            pid_exists=self._pid_exists,
            start_token_probe=self._start_token_probe,
        )
        for candidate, proof in zip(candidates, proofs, strict=True):
            classification = classifications[proof]
            if not classification.recoverable:
                continue
            ledger_owner = (
                candidate["owner"]
                if isinstance(candidate, Mapping) and "owner" in candidate
                else candidate
            )
            for batch in range(MAX_RECONCILIATION_BATCHES_PER_OWNER):
                outcome = self._invoke_reconcile(
                    reconcile,
                    ledger_owner,
                    classification,
                )
                if not isinstance(outcome, Mapping) or not outcome.get("has_more"):
                    break
            else:
                _log.warning(
                    "work reconciliation batch cap reached owner_pid=%d classification=%s",
                    proof.pid,
                    classification.value,
                )
        return classifications

    @staticmethod
    def _invoke_reconcile(
        reconcile: Callable[..., object],
        candidate: object,
        classification: OwnerClassification,
    ) -> object:
        """Call either the keyword or positional form of the ledger adapter."""

        try:
            parameters = inspect.signature(reconcile).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "owner" in parameters and "classification" in parameters:
            return reconcile(owner=candidate, classification=classification.value)
        return reconcile(candidate, classification.value)

    def shutdown(self) -> None:
        """Drop only this profile's queued secrets and wake its live waiters."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            while self._maintenance_running:
                self._maintenance_condition.wait()
        self.scheduler.cancel_owner(self.cache_key, reason="profile_service_shutdown")
        try:
            self._drain_attention_waiters(
                runtime_session_id=None,
                terminal_reason="profile_service_shutdown",
                resume_jobs=False,
            )
        except Exception as exc:
            _log.error(
                "durable Attention shutdown drain failed error_type=%s",
                type(exc).__name__,
            )
        self.waiters.shutdown()
        self.runtimes.shutdown()
        close = getattr(self.ledger, "close", None)
        if callable(close):
            close()

    def _require_open_locked(self) -> None:
        if self._closed:
            raise WorkServiceClosed("profile work service is shut down")


@dataclass(slots=True)
class _CacheEntry:
    service: WorkService
    references: int
    last_used: float


class WorkServiceLease:
    """Explicit caller reference preventing idle cache eviction."""

    __slots__ = ("_cache", "_key", "service", "_closed", "_close_lock")

    def __init__(self, cache: WorkServiceCache, key: str, service: WorkService) -> None:
        self._cache = cache
        self._key = key
        self.service = service
        self._closed = False
        self._close_lock = threading.Lock()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._cache._release(self._key)

    def __enter__(self) -> WorkService:
        return self.service

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def _default_ledger_factory(profile_home: Path) -> WorkLedgerProtocol:
    from fabric_cli.work_ledger import WorkLedger

    return WorkLedger(profile_home)  # type: ignore[return-value]


class WorkServiceCache:
    """Normalized profile cache with reference and idle-eviction fences."""

    def __init__(
        self,
        *,
        scheduler: GlobalWorkScheduler | None = None,
        ledger_factory: Callable[[Path], WorkLedgerProtocol] = _default_ledger_factory,
        owner: OwnerProof | None = None,
        idle_ttl: float = 300.0,
        clock: Callable[[], float] = monotonic,
        service_factory: Callable[..., WorkService] = WorkService,
        maintenance_enabled: bool = False,
    ) -> None:
        if idle_ttl < 0:
            raise ValueError("idle_ttl must be non-negative")
        self._scheduler = scheduler or get_global_work_scheduler()
        self._ledger_factory = ledger_factory
        self._owner = owner or create_process_owner_proof()
        self._idle_ttl = idle_ttl
        self._clock = clock
        self._service_factory = service_factory
        self._maintenance_enabled = maintenance_enabled
        self._maintenance_stop = threading.Event()
        self._maintenance_wakeup = threading.Event()
        self._maintenance_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._entries: dict[str, _CacheEntry] = {}
        self._closed = False
        if self._maintenance_enabled:
            self._maintenance_thread = threading.Thread(
                target=self._maintenance_loop,
                name="fabric-work-maintenance",
                daemon=True,
            )
            self._maintenance_thread.start()

    @staticmethod
    def _key(profile_home: str | Path) -> tuple[Path, str]:
        home = normalize_profile_home(profile_home)
        return home, os.path.normcase(str(home / "work.db"))

    def get(self, profile_home: str | Path) -> WorkService:
        home, key = self._key(profile_home)
        with self._lock:
            entry = self._get_or_create_locked(home, key)
            now = self._clock()
            entry.last_used = now
            entry.service._touch_if_open()
            service = entry.service
        self._request_maintenance()
        return service

    def acquire(self, profile_home: str | Path) -> WorkServiceLease:
        home, key = self._key(profile_home)
        with self._lock:
            entry = self._get_or_create_locked(home, key)
            entry.references += 1
            entry.last_used = self._clock()
            entry.service._touch_if_open()
            lease = WorkServiceLease(self, key, entry.service)
        self._request_maintenance()
        return lease

    def _request_maintenance(self) -> None:
        """Wake the sole maintainer without doing SQLite work on the caller path."""

        if self._maintenance_enabled:
            self._maintenance_wakeup.set()

    def _maintenance_wait_seconds(self) -> float:
        with self._lock:
            if self._closed:
                return 0.0
            services = tuple(entry.service for entry in self._entries.values())
        if not services:
            return float(DEFAULT_WORK_MAINTENANCE_INTERVAL_SECONDS)
        now = self._clock()
        next_due = min(service.maintenance_due_at for service in services)
        return max(0.0, next_due - now)

    def _run_due_maintenance(self) -> int:
        """Run due profile batches without holding the cache lock."""

        with self._lock:
            if self._closed:
                return 0
            services = tuple(entry.service for entry in self._entries.values())
        ran = 0
        for service in services:
            try:
                ran += int(service.run_due_maintenance())
            except Exception as exc:
                # A custom service factory must not take down maintenance for
                # the other profiles.  Do not interpolate the exception text:
                # it can include a filesystem path or external implementation
                # detail.
                _log.warning(
                    "work maintenance runner failed error_type=%s",
                    type(exc).__name__,
                )
        return ran

    def _maintenance_loop(self) -> None:
        """One daemon per production cache; no Job/Attention path runs it."""

        while not self._maintenance_stop.is_set():
            self._maintenance_wakeup.wait(timeout=self._maintenance_wait_seconds())
            self._maintenance_wakeup.clear()
            if self._maintenance_stop.is_set():
                return
            self._run_due_maintenance()

    def peek(self, profile_home: str | Path) -> WorkService | None:
        """Return an existing service without creating or touching one."""

        _home, key = self._key(profile_home)
        with self._lock:
            if self._closed:
                return None
            entry = self._entries.get(key)
            return entry.service if entry is not None else None

    def _get_or_create_locked(self, home: Path, key: str) -> _CacheEntry:
        if self._closed:
            raise WorkServiceClosed("work service cache is shut down")
        entry = self._entries.get(key)
        if entry is not None:
            entry.service.assert_store_fence()
            return entry
        ledger = self._ledger_factory(home)
        try:
            service = self._service_factory(
                home,
                ledger=ledger,
                scheduler=self._scheduler,
                owner=self._owner,
                clock=self._clock,
            )
        except BaseException:
            close = getattr(ledger, "close", None)
            if callable(close):
                close()
            raise
        entry = _CacheEntry(service=service, references=0, last_used=self._clock())
        self._entries[key] = entry
        return entry

    def _release(self, key: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.references = max(0, entry.references - 1)
            entry.last_used = self._clock()

    def evict_idle(self) -> int:
        now = self._clock()
        victims: list[WorkService] = []
        with self._lock:
            for key, entry in list(self._entries.items()):
                if entry.references:
                    continue
                last_used = max(entry.last_used, entry.service.last_used)
                if now - last_used < self._idle_ttl or not entry.service.is_idle:
                    continue
                self._entries.pop(key)
                victims.append(entry.service)
        for service in victims:
            service.shutdown()
        return len(victims)

    def invalidate(self, profile_home: str | Path) -> bool:
        _, key = self._key(profile_home)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return True
            if entry.references or not entry.service.is_idle:
                return False
            self._entries.pop(key)
        entry.service.shutdown()
        return True

    def shutdown_all(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            services = [entry.service for entry in self._entries.values()]
            self._entries.clear()
            maintenance_thread = self._maintenance_thread
        self._maintenance_stop.set()
        self._maintenance_wakeup.set()
        for service in services:
            service.shutdown()
        if maintenance_thread is not None and maintenance_thread is not threading.current_thread():
            maintenance_thread.join()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)


_global_service_cache_lock = threading.RLock()
_global_service_cache: WorkServiceCache | None = None


def service_for_profile(profile_home: str | Path) -> WorkService:
    """Return the cached service for a server-authorized profile home."""

    global _global_service_cache
    with _global_service_cache_lock:
        if _global_service_cache is None:
            _global_service_cache = WorkServiceCache(maintenance_enabled=True)
        cache = _global_service_cache
    return cache.get(profile_home)


def cached_service_for_profile(profile_home: str | Path) -> WorkService | None:
    """Return a live cached service without resurrecting global work state."""

    with _global_service_cache_lock:
        cache = _global_service_cache
    if cache is None:
        return None
    return cache.peek(profile_home)


def shutdown_work_services(*, wait_for_scheduler: bool = False) -> None:
    """Close every profile service and the process-global scheduler."""

    global _global_service_cache, _global_scheduler
    with _global_service_cache_lock:
        cache = _global_service_cache
        _global_service_cache = None
        if cache is not None:
            cache.shutdown_all()
        with _global_scheduler_lock:
            scheduler = _global_scheduler
            _global_scheduler = None
    if scheduler is not None:
        scheduler.shutdown(wait=wait_for_scheduler)
