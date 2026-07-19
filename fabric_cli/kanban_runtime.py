"""Typed runtime context for one dispatcher-spawned Kanban worker.

The dispatcher and worker are separate processes, but their task identity is
not user configuration and does not belong in the process environment.  The
dispatcher writes a short-lived, owner-only JSON descriptor and passes its
path through a hidden command-line argument.  The worker reads and unlinks
that descriptor before normal startup, then every Kanban subsystem reads this
process-local typed context.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Iterator, Mapping


_SCHEMA_VERSION = 1
_HIDDEN_ARG = "--kanban-worker-context"


@dataclass(frozen=True)
class KanbanRuntimeContext:
    """Values fixed for the lifetime of one worker process."""

    version: int = _SCHEMA_VERSION
    task_id: str = ""
    board: str = ""
    db_path: str = ""
    workspaces_root: str = ""
    workspace: str = ""
    branch: str = ""
    run_id: int | None = None
    claim_lock: str = ""
    tenant: str = ""
    profile: str = ""
    goal_mode: bool = False
    goal_max_turns: int | None = None

    @property
    def is_worker(self) -> bool:
        return bool(self.task_id)


_CONTEXT_FIELDS = {field.name for field in fields(KanbanRuntimeContext)}
_current_context = KanbanRuntimeContext()


def _positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_context(
    value: Mapping[str, Any] | KanbanRuntimeContext | None,
) -> KanbanRuntimeContext:
    if isinstance(value, KanbanRuntimeContext):
        return value
    if not isinstance(value, Mapping):
        return KanbanRuntimeContext()

    raw = {key: value[key] for key in _CONTEXT_FIELDS if key in value}
    if raw.get("version", _SCHEMA_VERSION) != _SCHEMA_VERSION:
        raise ValueError("unsupported Kanban worker context version")

    for name in (
        "task_id",
        "board",
        "db_path",
        "workspaces_root",
        "workspace",
        "branch",
        "claim_lock",
        "tenant",
        "profile",
    ):
        if name in raw:
            raw[name] = str(raw[name] or "").strip()
    raw["run_id"] = _positive_int(raw.get("run_id"))
    raw["goal_max_turns"] = _positive_int(raw.get("goal_max_turns"))
    raw["goal_mode"] = bool(raw.get("goal_mode", False))
    return KanbanRuntimeContext(**raw)


def get_kanban_runtime_context() -> KanbanRuntimeContext:
    """Return the context bound to this process."""

    return _current_context


def configure_kanban_runtime_context(
    value: Mapping[str, Any] | KanbanRuntimeContext | None = None,
    **overrides: Any,
) -> KanbanRuntimeContext:
    """Replace the process-local context and return its previous value."""

    global _current_context
    previous = _current_context
    if overrides:
        base = asdict(_coerce_context(value))
        base.update(overrides)
        value = base
    _current_context = _coerce_context(value)
    return previous


@contextmanager
def scoped_kanban_runtime_context(
    value: Mapping[str, Any] | KanbanRuntimeContext | None = None,
    **overrides: Any,
) -> Iterator[KanbanRuntimeContext]:
    """Temporarily bind a context, primarily for direct callers and tests."""

    previous = configure_kanban_runtime_context(value, **overrides)
    try:
        yield get_kanban_runtime_context()
    finally:
        configure_kanban_runtime_context(previous)


def current_worker_task_id() -> str:
    return get_kanban_runtime_context().task_id


def is_kanban_worker() -> bool:
    return get_kanban_runtime_context().is_worker


def current_profile_name(*, fallback: str = "worker") -> str:
    """Resolve the trusted worker profile or the active interactive profile."""

    profile = get_kanban_runtime_context().profile
    if profile:
        return profile
    try:
        from fabric_cli.profiles import get_active_profile_name

        return get_active_profile_name() or fallback
    except Exception:
        return fallback


def write_kanban_runtime_context(
    value: Mapping[str, Any] | KanbanRuntimeContext,
    *,
    directory: str | os.PathLike[str] | None = None,
) -> Path:
    """Write a new owner-only worker descriptor and return its path."""

    context = _coerce_context(value)
    if not context.task_id:
        raise ValueError("Kanban worker context requires a task id")
    fd, raw_path = tempfile.mkstemp(
        prefix="kanban-worker-", suffix=".json", dir=directory
    )
    path = Path(raw_path)
    try:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            # Windows applies the creating user's ACL to mkstemp files.
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(context), handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise
    return path


def consume_kanban_runtime_context(
    path: str | os.PathLike[str],
) -> KanbanRuntimeContext:
    """Read and immediately unlink an owner-only worker descriptor."""

    descriptor = Path(path)
    try:
        metadata = descriptor.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Kanban worker context is not a regular file")
        if os.name != "nt":
            if metadata.st_mode & 0o077:
                raise PermissionError("Kanban worker context must be owner-only")
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise PermissionError(
                    "Kanban worker context owner does not match this process"
                )
        with descriptor.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    finally:
        descriptor.unlink(missing_ok=True)
    if not isinstance(raw, Mapping):
        raise ValueError("Kanban worker context must be a JSON object")
    context = _coerce_context(raw)
    if not context.task_id:
        raise ValueError("Kanban worker context requires a task id")
    return context


def consume_context_argument(argv: list[str]) -> bool:
    """Consume the hidden descriptor argument from ``argv`` in place.

    This runs before dotenv loading, plugin discovery, or argparse setup.  The
    hidden argument is process-internal and is removed so relaunches cannot
    accidentally reuse an already-consumed descriptor.
    """

    found: list[tuple[int, str, int]] = []
    index = 1
    while index < len(argv):
        item = argv[index]
        if item == _HIDDEN_ARG:
            if index + 1 >= len(argv):
                raise ValueError(f"{_HIDDEN_ARG} requires a descriptor path")
            found.append((index, argv[index + 1], 2))
            index += 2
            continue
        if item.startswith(_HIDDEN_ARG + "="):
            found.append((index, item.split("=", 1)[1], 1))
        index += 1
    if not found:
        return False
    if len(found) != 1:
        raise ValueError(f"{_HIDDEN_ARG} may be provided only once")
    arg_index, path, width = found[0]
    del argv[arg_index : arg_index + width]
    configure_kanban_runtime_context(consume_kanban_runtime_context(path))
    return True


def worker_context_argv(path: str | os.PathLike[str]) -> list[str]:
    """Return the private argv pair used to launch a worker process."""

    return [_HIDDEN_ARG, os.fspath(path)]
