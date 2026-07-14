"""Runtime isolation policy for governed ``/learn`` authoring turns.

``/learn`` intentionally reuses Fabric's stable tool schema so starting a
skill draft does not invalidate the conversation's cached prompt prefix.  The
authority boundary therefore lives at dispatch time: a context-local allowlist
admits source reads and the quarantined ``skill_manage`` writer, while every
other tool (including tools discovered dynamically after the prompt was built)
fails closed.
"""

from __future__ import annotations

from collections.abc import Iterable

from tools.skill_provenance import BACKGROUND_REVIEW, LEARN_REQUEST


# Closed by design.  Adding a tool here is a security review, not routine tool
# registration.  ``skill_manage`` is the only writer and the learn origin makes
# every one of its actions land in the pending draft store.
LEARN_ALLOWED_TOOLS = frozenset(
    {
        # Local and remote source reads.
        "read_file",
        "search_files",
        "web_extract",
        "web_search",
        "vision_analyze",
        "video_analyze",
        # The current/earlier conversation may itself be the requested source.
        "session_search",
        # Inspect the existing library, then author only through quarantine.
        "skills_list",
        "skill_view",
        "skill_manage",
        # Safe loop bookkeeping and read-only progressive-disclosure catalog.
        # ``tool_call`` is deliberately absent and denied before unwrap.
        "todo",
        "tool_search",
        "tool_describe",
    }
)

LEARN_TOOL_DENIAL = (
    "Governed /learn authoring denied tool '{tool_name}'. This single-turn "
    "workflow may only read named sources and submit quarantined drafts with "
    "skill_manage. Re-run /learn with any missing source or clarification."
)


def configure_turn_tool_policy(origin: str) -> None:
    """Install the runtime tool policy for one agent turn.

    Background review owns its separate memory/skills whitelist and installs
    it before entering the turn, so leave that binding intact.  Every other
    origin clears a previous turn's policy; ``/learn`` then replaces it with
    the closed authoring allowlist.  This makes reused gateway/CLI threads safe
    without changing the model-visible tool schema.
    """
    from fabric_cli.plugins import (
        clear_thread_tool_whitelist,
        set_thread_tool_whitelist,
    )

    if origin == BACKGROUND_REVIEW:
        return
    clear_thread_tool_whitelist()
    if origin == LEARN_REQUEST:
        set_thread_tool_whitelist(
            set(LEARN_ALLOWED_TOOLS),
            deny_msg_fmt=LEARN_TOOL_DENIAL,
        )


def disallowed_learn_tools(tool_names: Iterable[str]) -> frozenset[str]:
    """Return names outside the closed policy (useful for diagnostics/tests)."""
    return frozenset(name for name in tool_names if name not in LEARN_ALLOWED_TOOLS)
