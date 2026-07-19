"""Private, file-backed launch context for the TUI process chain.

The TUI has two process boundaries: the Python CLI (or dashboard) launches
Node, and Node may launch ``tui_gateway``.  Launch-only values belong to that
specific process chain, not to the user's shell environment.  This module
provides a small versioned JSON contract that can cross both boundaries
without putting credentials or URLs in process arguments.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping


_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TuiLaunchContext:
    """Values fixed for one TUI launch.

    Empty values deliberately mean "not supplied".  Config resolution remains
    in its owning subsystem; this object only carries explicit launch choices.
    """

    version: int = _SCHEMA_VERSION
    cwd: str = ""
    active_session_file: str = ""
    model: str = ""
    provider: str = ""
    toolsets: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    query: str = ""
    image: str = ""
    checkpoints: bool = False
    pass_session_id: bool = False
    max_turns: int | None = None
    tool_progress: str = ""
    ignore_user_config: bool = False
    ignore_rules: bool = False
    resume: str = ""
    dashboard: bool = False
    terminal_background: str = ""
    gateway_url: str = ""
    sidecar_url: str = ""


_CONTEXT_FIELDS = {field.name for field in fields(TuiLaunchContext)}
_STRING_FIELDS = _CONTEXT_FIELDS - {
    "version",
    "toolsets",
    "skills",
    "checkpoints",
    "pass_session_id",
    "max_turns",
    "ignore_user_config",
    "ignore_rules",
    "dashboard",
}
_BOOLEAN_FIELDS = {
    "checkpoints",
    "pass_session_id",
    "ignore_user_config",
    "ignore_rules",
    "dashboard",
}
_current_context = TuiLaunchContext()


def _coerce_context(value: Mapping[str, Any] | TuiLaunchContext | None) -> TuiLaunchContext:
    if isinstance(value, TuiLaunchContext):
        value = asdict(value)
    if not isinstance(value, Mapping):
        return TuiLaunchContext()

    raw = {key: value[key] for key in _CONTEXT_FIELDS if key in value}
    if raw.get("version", _SCHEMA_VERSION) != _SCHEMA_VERSION:
        raise ValueError("unsupported TUI launch context version")

    for key in _STRING_FIELDS:
        if key in raw and not isinstance(raw[key], str):
            raise ValueError(f"TUI launch context field {key!r} must be a string")
    for key in _BOOLEAN_FIELDS:
        if key in raw and not isinstance(raw[key], bool):
            raise ValueError(f"TUI launch context field {key!r} must be a boolean")

    for key in ("toolsets", "skills"):
        items = raw.get(key, ())
        if not isinstance(items, (list, tuple)) or not all(
            isinstance(item, str) for item in items
        ):
            raise ValueError(
                f"TUI launch context field {key!r} must be a string list"
            )
        raw[key] = tuple(item.strip() for item in items if item.strip())

    max_turns = raw.get("max_turns")
    if max_turns is not None:
        if isinstance(max_turns, bool) or not isinstance(max_turns, int):
            raise ValueError("TUI launch context field 'max_turns' must be an integer")
        raw["max_turns"] = max_turns if max_turns > 0 else None

    return TuiLaunchContext(**raw)


def get_tui_launch_context() -> TuiLaunchContext:
    return _current_context


def configure_tui_launch_context(
    value: Mapping[str, Any] | TuiLaunchContext | None = None,
    **overrides: Any,
) -> TuiLaunchContext:
    """Replace the process-local context and return its previous value.

    The return value makes focused tests and embedders able to restore the
    prior context without retaining launch state between sessions.
    """

    global _current_context
    previous = _current_context
    if overrides:
        base = asdict(_coerce_context(value))
        base.update(overrides)
        value = base
    _current_context = _coerce_context(value)
    return previous


def write_tui_launch_context(
    value: Mapping[str, Any] | TuiLaunchContext,
    *,
    directory: str | os.PathLike[str] | None = None,
) -> Path:
    """Write *value* to a newly-created owner-only descriptor."""

    context = _coerce_context(value)
    fd, raw_path = tempfile.mkstemp(
        prefix="tui-launch-", suffix=".json", dir=directory
    )
    path = Path(raw_path)
    try:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            # Windows applies the current user's ACL to mkstemp files.  POSIX
            # callers still get the explicit owner-only mode above.
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


def consume_tui_launch_context(path: str | os.PathLike[str] | None) -> TuiLaunchContext:
    """Read and immediately unlink a launch descriptor.

    A missing path is the normal direct-entry/testing case and resolves to an
    empty context.  A supplied but unreadable or malformed descriptor is a
    startup error: silently falling back would apply the wrong profile/model or
    discard an explicit security flag.
    """

    if not path:
        return TuiLaunchContext()

    descriptor = Path(path)
    try:
        metadata = descriptor.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("TUI launch context is not a regular file")
        if os.name != "nt":
            if metadata.st_mode & 0o077:
                raise PermissionError("TUI launch context must be owner-only")
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise PermissionError(
                    "TUI launch context owner does not match this process"
                )
        with descriptor.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    finally:
        descriptor.unlink(missing_ok=True)
    if not isinstance(raw, Mapping):
        raise ValueError("TUI launch context must be a JSON object")
    return _coerce_context(raw)
