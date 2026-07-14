"""End-to-end concurrent dispatch guard for governed ``/learn`` turns."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _tool_defs(*names: str) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


def _call(name: str, call_id: str):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments="{}"),
    )


def test_concurrent_dispatch_blocks_denied_tool_and_keeps_learn_origin():
    import run_agent

    from agent.skill_authoring_policy import configure_turn_tool_policy
    from fabric_cli.plugins import clear_thread_tool_whitelist
    from tools.skill_provenance import (
        LEARN_REQUEST,
        get_current_write_origin,
        set_current_write_origin,
    )

    with (
        patch(
            "run_agent.get_tool_definitions",
            return_value=_tool_defs("web_search", "terminal"),
        ),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = run_agent.AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        agent.client = MagicMock()

    observed: list[tuple[str, str]] = []

    def fake_handle(name, args, task_id, **kwargs):
        observed.append((name, get_current_write_origin()))
        return json.dumps({"ok": True, "tool": name})

    set_current_write_origin(LEARN_REQUEST)
    configure_turn_tool_policy(LEARN_REQUEST)
    try:
        assistant = SimpleNamespace(
            tool_calls=[_call("web_search", "allowed"), _call("terminal", "denied")]
        )
        messages: list[dict] = []
        with patch("run_agent.handle_function_call", side_effect=fake_handle):
            agent._execute_tool_calls_concurrent(
                assistant,
                messages,
                "learn-task",
            )
    finally:
        clear_thread_tool_whitelist()
        set_current_write_origin("foreground")

    assert observed == [("web_search", LEARN_REQUEST)]
    assert len(messages) == 2
    assert '"ok": true' in messages[0]["content"]
    assert (
        "Governed /learn authoring denied tool 'terminal'"
        in messages[1]["content"]
    )
