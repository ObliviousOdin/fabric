"""Fabric-tools-as-MCP server for the codex_app_server runtime.

When the user runs `openai/*` turns through the codex app-server, codex
owns the loop and builds its own tool list. By default, that means
Fabric's richer tool surface — web search, browser automation,
delegate_task subagents, vision analysis, persistent memory, skills,
cross-session search, image generation, TTS — is unreachable.

This module exposes a curated subset of those Fabric tools to the
spawned codex subprocess via stdio MCP. Codex registers it as a normal
MCP server (per `~/.codex/config.toml [mcp_servers.fabric-tools]`) and
the user gets full Fabric capability inside a Codex turn.

Scope (what we expose):
  - web_search, web_extract              — Firecrawl, no codex equivalent
  - browser_navigate / _click / _type /  — Camofox/Browserbase automation
    _snapshot / _scroll / _back / _press /
    _get_images / _console / _vision
  - vision_analyze                       — image inspection by vision model
  - image_generate                       — image generation
  - skill_view, skills_list              — Fabric's skill library
  - text_to_speech                       — TTS
  - kanban_* (complete/block/comment/    — kanban worker + orchestrator
    heartbeat/show/list/create/            handoff (typed worker context,
    unblock/link)                          writes the pinned board DB)

What we DO NOT expose:
  - terminal / shell                     — codex's own shell tool
  - read_file / write_file / patch       — codex's apply_patch + shell
  - search_files / process               — codex's shell
  - clarify                              — codex's own UX
  - delegate_task / memory /             — `_AGENT_LOOP_TOOLS` in Fabric
    session_search / todo                  (model_tools.py). They require
                                           the running AIAgent context to
                                           dispatch (mid-loop state), so a
                                           stateless MCP callback can't
                                           drive them. See the inline
                                           comment on EXPOSED_TOOLS below.

Run with: python -m agent.transports.fabric_tools_mcp_server
Spawned by: CodexAppServerSession.ensure_started() when the runtime is
            active and config opts in.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Tools we expose. Each name MUST match a registered Fabric tool that
# `model_tools.handle_function_call()` can dispatch.
#
# What we deliberately DO NOT expose:
#   - terminal / shell / read_file / write_file / patch / search_files /
#     process — codex's built-ins cover these and approval routes through
#     codex's own UI.
#   - delegate_task / memory / session_search / todo — these are
#     `_AGENT_LOOP_TOOLS` in Fabric (model_tools.py:493). They require
#     the running AIAgent context to dispatch (mid-loop state), so a
#     stateless MCP callback can't drive them. Fabric's default runtime
#     keeps these working; the codex_app_server runtime cannot.
EXPOSED_TOOLS: tuple[str, ...] = (
    "web_search",
    "web_extract",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_press",
    "browser_snapshot",
    "browser_scroll",
    "browser_back",
    "browser_get_images",
    "browser_console",
    "browser_vision",
    "vision_analyze",
    "image_generate",
    "skill_view",
    "skills_list",
    "text_to_speech",
    # Kanban worker handoff tools — gated on dispatcher-bound worker context.
    # Without these
    # in the callback, a worker spawned with openai_runtime=codex_app_server
    # could do the work but couldn't report completion back to the kernel,
    # making it hang until timeout. Stateless dispatch reads typed context and
    # writes directly to the pinned board database.
    "kanban_complete",
    "kanban_block",
    "kanban_comment",
    "kanban_heartbeat",
    "kanban_show",
    "kanban_list",
    # NOTE: kanban_create / kanban_unblock / kanban_link are orchestrator-
    # only — the Kanban tool gates them on worker context being absent.
    # They're exposed here for orchestrator agents running on the Codex
    # runtime that need to dispatch new tasks.
    "kanban_create",
    "kanban_unblock",
    "kanban_link",
)


def _build_server() -> Any:
    """Create the FastMCP server with Fabric tools attached. Lazy imports
    so the module can be imported without the mcp package installed
    (we degrade to a clear error only when actually run)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - install hint
        raise ImportError(
            f"fabric-tools MCP server requires the 'mcp' package: {exc}"
        ) from exc

    # Discover Fabric tools so dispatch works.
    from model_tools import (
        get_tool_definitions,
        handle_function_call,
    )

    mcp = FastMCP(
        "fabric-tools",
        instructions=(
            "Fabric's tool surface, exposed for use inside a Codex "
            "session. Use these for capabilities Codex's built-in toolset "
            "doesn't cover: web search/extract, browser automation, "
            "subagent delegation, vision, image generation, persistent "
            "memory, skills, and cross-session search."
        ),
    )

    # Pull authoritative Fabric tool schemas for the ones we expose, so
    # MCP clients see the same parameter docs Fabric gives the model.
    all_defs = {
        td["function"]["name"]: td["function"]
        for td in (get_tool_definitions(quiet_mode=True) or [])
        if isinstance(td, dict) and td.get("type") == "function"
    }

    exposed_count = 0

    for name in EXPOSED_TOOLS:
        spec = all_defs.get(name)
        if spec is None:
            logger.debug(
                "skipping %s — not registered in this Fabric process", name
            )
            continue

        description = spec.get("description") or f"Fabric {name} tool"
        params_schema = spec.get("parameters") or {"type": "object", "properties": {}}

        # FastMCP wants a Python callable. Build a closure that takes the
        # arguments dict, dispatches via handle_function_call, and returns
        # the result string. We use add_tool() for full control over the
        # input schema (FastMCP's @tool() decorator inspects type hints,
        # which we can't get from a JSON schema at runtime).
        def _make_handler(tool_name: str):
            def _dispatch(**kwargs: Any) -> str:
                try:
                    return handle_function_call(tool_name, kwargs or {})
                except Exception as exc:
                    logger.exception("tool %s raised", tool_name)
                    return json.dumps({"error": str(exc), "tool": tool_name})
            _dispatch.__name__ = tool_name
            _dispatch.__doc__ = description
            return _dispatch

        try:
            mcp.add_tool(
                _make_handler(name),
                name=name,
                description=description,
                # FastMCP accepts JSON schema directly via the
                # input_schema parameter on newer versions; older
                # versions use parameters_schema. Try both for compat.
            )
        except TypeError:
            # Older mcp SDK signature — fall back to decorator-style.
            handler = _make_handler(name)
            handler = mcp.tool(name=name, description=description)(handler)

        exposed_count += 1

    logger.info(
        "fabric-tools MCP server registered %d/%d tools",
        exposed_count,
        len(EXPOSED_TOOLS),
    )
    return mcp


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for `python -m agent.transports.fabric_tools_mcp_server`."""
    argv = argv or sys.argv[1:]
    private_argv = ["fabric-tools-mcp", *argv]
    try:
        from fabric_cli.kanban_runtime import consume_context_argument

        consume_context_argument(private_argv)
    except (OSError, ValueError, PermissionError) as exc:
        sys.stderr.write(f"fabric-tools MCP: invalid worker context: {exc}\n")
        return 2
    argv = private_argv[1:]
    verbose = "--verbose" in argv or "-v" in argv

    log_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        stream=sys.stderr,  # MCP uses stdio for protocol — logs MUST go to stderr
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Keep secret redaction enabled on the MCP wire.
    from agent.redact import configure_redaction

    configure_redaction(True)

    try:
        server = _build_server()
    except ImportError as exc:
        sys.stderr.write(f"fabric-tools MCP server cannot start: {exc}\n")
        return 2

    # FastMCP runs with stdio transport by default when launched as a
    # subprocess.
    try:
        server.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.exception("fabric-tools MCP server crashed")
        sys.stderr.write(f"fabric-tools MCP server error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
