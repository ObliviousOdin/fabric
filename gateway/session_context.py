"""
Session-scoped context variables for the Fabric gateway.

**Why this matters**

The gateway processes messages concurrently via ``asyncio``. The legacy
implementation stored each message's routing identity in process-global
environment state. Message A's value could therefore be overwritten by
Message B before Message A's agent finished running, routing background-task
notifications and tool calls to the wrong thread.

``contextvars.ContextVar`` values are *task-local*: each ``asyncio``
task (and any ``run_in_executor`` thread it spawns) gets its own copy,
so concurrent messages never interfere.

Consumers read an immutable typed snapshot. Session identity is deliberately
not exported to child-process environments; subprocess entrypoints that need a
session receive it explicitly in their argv or request payload.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

# Sentinel to distinguish "never set in this context" from "explicitly set to empty".
_UNSET: Any = object()

# ---------------------------------------------------------------------------
# Per-task session variables
# ---------------------------------------------------------------------------

_SESSION_PLATFORM: ContextVar = ContextVar("session.platform", default=_UNSET)
_SESSION_SOURCE: ContextVar = ContextVar("session.source", default=_UNSET)
_SESSION_CHAT_ID: ContextVar = ContextVar("session.chat_id", default=_UNSET)
_SESSION_CHAT_NAME: ContextVar = ContextVar("session.chat_name", default=_UNSET)
_SESSION_THREAD_ID: ContextVar = ContextVar("session.thread_id", default=_UNSET)
_SESSION_USER_ID: ContextVar = ContextVar("session.user_id", default=_UNSET)
_SESSION_USER_NAME: ContextVar = ContextVar("session.user_name", default=_UNSET)
_SESSION_KEY: ContextVar = ContextVar("session.key", default=_UNSET)
_SESSION_ID: ContextVar = ContextVar("session.id", default=_UNSET)
# In-process UI session/window id for multi-session desktop/TUI hosts. This is
# intentionally separate from the task-local durable conversation/session-db
# id: the UI id is the live frontend tab/window
# that commissioned a detached completion. Background completions use it as a
# precise return address so a stale/rotated durable session key cannot be
# consumed by whichever desktop poller wakes first.
_SESSION_UI_SESSION_ID: ContextVar = ContextVar("session.ui_id", default=_UNSET)
# ID of the message that triggered the current turn. Used as a reply anchor
# so background-process notifications stay inside the originating Telegram
# private-chat topic (those lanes route only with thread id + reply anchor).
_SESSION_MESSAGE_ID: ContextVar = ContextVar("session.message_id", default=_UNSET)

_SESSION_PROFILE: ContextVar = ContextVar("session.profile", default=_UNSET)

# Whether the current session's delivery channel can route an ASYNC completion
# back to the agent AFTER the current turn ends (i.e. wake a fresh turn).
#
# True  — CLI (in-process completion_queue drain) and the real gateway
#         platforms (Telegram/Discord/Slack/...), which hold a persistent
#         outbound channel and run the watcher/drain loops.
# False — stateless request/response adapters (the API server: every route,
#         spec and proprietary, tears down its channel when the turn ends, so
#         a background completion that finishes later has nowhere to go).
#
# Tools that promise async delivery (terminal notify_on_complete /
# watch_patterns, delegate_task background=True) read this via
# ``async_delivery_supported()`` and refuse to hand out a promise the channel
# can't keep — turning a silent no-op into an explicit contract.
#
# Default _UNSET => treated as supported, so CLI (which never sets a platform)
# and any contextvar-unaware path keep working. Stateless adapters opt OUT by
# setting ``supports_async_delivery = False`` on the adapter class; the gateway
# propagates that into this contextvar at session-bind time.
_SESSION_ASYNC_DELIVERY: ContextVar = ContextVar("session.async_delivery", default=_UNSET)

# Cron auto-delivery vars — set per-job in run_job() so concurrent jobs
# don't clobber each other's delivery targets.
_CRON_AUTO_DELIVER_PLATFORM: ContextVar = ContextVar(
    "cron_delivery.platform", default=_UNSET
)
_CRON_AUTO_DELIVER_CHAT_ID: ContextVar = ContextVar(
    "cron_delivery.chat_id", default=_UNSET
)
_CRON_AUTO_DELIVER_THREAD_ID: ContextVar = ContextVar(
    "cron_delivery.thread_id", default=_UNSET
)


@dataclass(frozen=True)
class SessionRuntimeContext:
    platform: str = ""
    source: str = ""
    chat_id: str = ""
    chat_name: str = ""
    thread_id: str = ""
    user_id: str = ""
    user_name: str = ""
    session_key: str = ""
    session_id: str = ""
    ui_session_id: str = ""
    message_id: str = ""
    profile: str = ""


@dataclass(frozen=True)
class CronDeliveryContext:
    platform: str = ""
    chat_id: str = ""
    thread_id: str = ""


def _read_text(var: ContextVar, default: str = "") -> str:
    value = var.get()
    if value is _UNSET:
        return default
    return "" if value is None else str(value)


def get_session_context() -> SessionRuntimeContext:
    """Return a stable typed snapshot of the active task's session."""
    return SessionRuntimeContext(
        platform=_read_text(_SESSION_PLATFORM),
        source=_read_text(_SESSION_SOURCE),
        chat_id=_read_text(_SESSION_CHAT_ID),
        chat_name=_read_text(_SESSION_CHAT_NAME),
        thread_id=_read_text(_SESSION_THREAD_ID),
        user_id=_read_text(_SESSION_USER_ID),
        user_name=_read_text(_SESSION_USER_NAME),
        session_key=_read_text(_SESSION_KEY),
        session_id=_read_text(_SESSION_ID),
        ui_session_id=_read_text(_SESSION_UI_SESSION_ID),
        message_id=_read_text(_SESSION_MESSAGE_ID),
        profile=_read_text(_SESSION_PROFILE),
    )


def get_cron_delivery_context() -> CronDeliveryContext:
    """Return the active scheduled job's explicit delivery target."""
    return CronDeliveryContext(
        platform=_read_text(_CRON_AUTO_DELIVER_PLATFORM),
        chat_id=_read_text(_CRON_AUTO_DELIVER_CHAT_ID),
        thread_id=_read_text(_CRON_AUTO_DELIVER_THREAD_ID),
    )


def set_current_session_id(session_id: str) -> None:
    """Update the active task-local session id.

    Long-lived single-process entrypoints like the CLI can rotate sessions via
    ``/new``, ``/resume``, ``/branch``, or compression splits without
    reconstructing the entire agent.
    """
    _SESSION_ID.set(session_id)


def get_current_session_id(default: str = "") -> str:
    """Return the active task-local durable session id.

    The durable database session id is an in-process agent concern. It is
    deliberately not exported to child processes.
    """
    value = _SESSION_ID.get()
    if value is _UNSET:
        return default
    return value


def set_session_vars(
    platform: str = "",
    source: str = "",
    chat_id: str = "",
    chat_name: str = "",
    thread_id: str = "",
    user_id: str = "",
    user_name: str = "",
    session_key: str = "",
    session_id: str = "",
    message_id: str = "",
    profile: str = "",
    cwd: str = "",
    async_delivery: bool = True,
    ui_session_id: str = "",
) -> list:
    """Set all session context variables and return reset tokens.

    Call ``clear_session_vars(tokens)`` in a ``finally`` block when the handler
    exits. Note ``clear_session_vars`` resets every var to ``""`` rather than
    restoring prior values — these
    helpers are not nestable/stack-safe, and the returned tokens are accepted
    only for API compatibility.

    ``cwd`` pins the logical working directory for this context.

    ``async_delivery`` declares whether this session's channel can route a
    background completion back to the agent after the turn ends (see
    ``_SESSION_ASYNC_DELIVERY`` / ``async_delivery_supported``). Stateless
    request/response adapters (the API server) pass ``False``.
    """
    tokens = [
        _SESSION_PLATFORM.set(platform),
        _SESSION_SOURCE.set(source),
        _SESSION_CHAT_ID.set(chat_id),
        _SESSION_CHAT_NAME.set(chat_name),
        _SESSION_THREAD_ID.set(thread_id),
        _SESSION_USER_ID.set(user_id),
        _SESSION_USER_NAME.set(user_name),
        _SESSION_KEY.set(session_key),
        _SESSION_ID.set(session_id),
        _SESSION_UI_SESSION_ID.set(ui_session_id),
        _SESSION_MESSAGE_ID.set(message_id),
        _SESSION_PROFILE.set(profile),
        _SESSION_ASYNC_DELIVERY.set(bool(async_delivery)),
    ]
    try:
        from agent.runtime_cwd import set_session_cwd

        set_session_cwd(cwd)
    except Exception:
        pass
    return tokens


def set_cron_delivery_context(
    *,
    platform: str = "",
    chat_id: str = "",
    thread_id: str = "",
) -> list:
    """Bind a scheduled job's delivery target to the current task."""
    return [
        _CRON_AUTO_DELIVER_PLATFORM.set(platform),
        _CRON_AUTO_DELIVER_CHAT_ID.set(chat_id),
        _CRON_AUTO_DELIVER_THREAD_ID.set(thread_id),
    ]


def clear_cron_delivery_context(tokens: list | None = None) -> None:
    """Clear the current task's scheduled delivery target."""
    _CRON_AUTO_DELIVER_PLATFORM.set("")
    _CRON_AUTO_DELIVER_CHAT_ID.set("")
    _CRON_AUTO_DELIVER_THREAD_ID.set("")


def clear_session_vars(tokens: list) -> None:
    """Mark session context variables as explicitly cleared.

    Sets all variables to ``""`` so that readers observe an explicitly cleared
    context. The *tokens* argument is accepted for API compatibility with
    callers that saved the return value of ``set_session_vars``, but the
    actual clearing uses ``var.set("")`` rather than ``var.reset(token)``
    to ensure the "explicitly cleared" state is distinguishable from
    "never set" (which holds the ``_UNSET`` sentinel).
    """
    for var in (
        _SESSION_PLATFORM,
        _SESSION_SOURCE,
        _SESSION_CHAT_ID,
        _SESSION_CHAT_NAME,
        _SESSION_THREAD_ID,
        _SESSION_USER_ID,
        _SESSION_USER_NAME,
        _SESSION_KEY,
        _SESSION_ID,
        _SESSION_UI_SESSION_ID,
        _SESSION_MESSAGE_ID,
        _SESSION_PROFILE,
    ):
        var.set("")
    # Reset async-delivery capability to the "never set" sentinel rather than a
    # falsy value: a cleared context should fall back to the default-supported
    # behavior (CLI / unaware paths), not be mistaken for an opted-out
    # stateless adapter.
    _SESSION_ASYNC_DELIVERY.set(_UNSET)
    try:
        from agent.runtime_cwd import clear_session_cwd

        clear_session_cwd()
    except Exception:
        pass


def reset_session_vars() -> None:
    """Reset every session context variable to ``_UNSET`` for THIS context.

    Distinct from :func:`clear_session_vars`, which sets the vars to ``""``
    when a handler finishes. This helper restores the ``_UNSET`` sentinel
    ("never bound in this context"), which is what a freshly-spawned task should
    look like *before* it binds its own session.

    🔴 Why this exists — the cross-session ContextVar inheritance leak.
    Each gateway message is processed in its own ``asyncio`` task, created via
    ``create_task`` (which snapshots the *current* context with
    ``copy_context``).  When message B's task is spawned from a context where a
    concurrent message A had already called :func:`set_session_vars`, B inherits
    A's **set** ContextVars.  Until B calls its own ``set_session_vars`` there is
    a window where B could read A's task-local identity. Calling
    ``reset_session_vars`` at the top of the per-message handler drops that
    inherited identity before B binds its own context a few steps later.

    ``_SESSION_ASYNC_DELIVERY`` is reset explicitly below. Without it, a task
    spawned from a context where a
    sibling adapter bound ``async_delivery=False`` (the stateless API server)
    inherits that ``False`` through the pre-bind window, and
    ``async_delivery_supported`` wrongly reports the new turn's channel as
    unable to route a background completion until ``set_session_vars`` runs.
    """
    for var in (
        _SESSION_PLATFORM,
        _SESSION_SOURCE,
        _SESSION_CHAT_ID,
        _SESSION_CHAT_NAME,
        _SESSION_THREAD_ID,
        _SESSION_USER_ID,
        _SESSION_USER_NAME,
        _SESSION_KEY,
        _SESSION_UI_SESSION_ID,
        _SESSION_MESSAGE_ID,
        _SESSION_PROFILE,
        _CRON_AUTO_DELIVER_PLATFORM,
        _CRON_AUTO_DELIVER_CHAT_ID,
        _CRON_AUTO_DELIVER_THREAD_ID,
    ):
        var.set(_UNSET)
    _SESSION_ID.set(_UNSET)
    # Reset the async-delivery capability to "never bound here" (_UNSET) for the
    # same inheritance-leak reason as the mapped vars above — see clear_session_vars,
    # which resets this var on the handler-exit path for the symmetric concern.
    _SESSION_ASYNC_DELIVERY.set(_UNSET)
    try:
        from agent.runtime_cwd import clear_session_cwd

        clear_session_cwd()
    except Exception:
        pass


def async_delivery_supported() -> bool:
    """Whether the current session can deliver a background completion later.

    Returns ``False`` only when the active session was explicitly bound by a
    stateless adapter (the API server) that cannot route a notification back to
    the agent after the turn ends. CLI, cron, and the real gateway platforms —
    and any path that never bound the contextvar — return ``True``.

    Tools that promise async delivery (``terminal`` notify_on_complete /
    watch_patterns, ``delegate_task`` background=True) consult this before
    registering a watcher / dispatching a detached child, so they can refuse a
    promise the channel can't keep instead of silently no-op'ing.
    """
    value = _SESSION_ASYNC_DELIVERY.get()
    if value is _UNSET:
        return True
    return bool(value)
