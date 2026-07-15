"""Mechanical isolation contracts for the ``/learn`` authoring sandbox."""

from __future__ import annotations

import concurrent.futures
import json

import pytest


@pytest.fixture(autouse=True)
def _clear_policy_after_test():
    from fabric_cli.plugins import clear_thread_tool_whitelist
    from tools.skill_provenance import set_current_write_origin

    clear_thread_tool_whitelist()
    set_current_write_origin("foreground")
    yield
    clear_thread_tool_whitelist()
    set_current_write_origin("foreground")


def test_learn_policy_is_closed_and_skill_manage_is_only_writer(monkeypatch):
    from agent.skill_authoring_policy import (
        LEARN_ALLOWED_TOOLS,
        configure_turn_tool_policy,
    )
    from fabric_cli.plugins import get_pre_tool_call_block_message
    from tools.skill_provenance import LEARN_REQUEST

    monkeypatch.setattr("fabric_cli.plugins.invoke_hook", lambda *_a, **_k: [])
    configure_turn_tool_policy(LEARN_REQUEST)

    for allowed in LEARN_ALLOWED_TOOLS:
        assert get_pre_tool_call_block_message(allowed, {}) is None

    for denied in (
        "terminal",
        "write_file",
        "patch",
        "execute_code",
        "delegate_task",
        "memory",
        "clarify",
        "tool_call",
        "mcp_dynamic_unknown",
    ):
        message = get_pre_tool_call_block_message(denied, {})
        assert message is not None
        assert "Governed /learn authoring denied" in message


def test_policy_and_origin_propagate_to_concurrent_tool_worker(monkeypatch):
    from agent.skill_authoring_policy import configure_turn_tool_policy
    from fabric_cli.plugins import get_pre_tool_call_block_message
    from tools.skill_provenance import (
        LEARN_REQUEST,
        get_current_write_origin,
        set_current_write_origin,
    )
    from tools.thread_context import propagate_context_to_thread

    monkeypatch.setattr("fabric_cli.plugins.invoke_hook", lambda *_a, **_k: [])
    set_current_write_origin(LEARN_REQUEST)
    configure_turn_tool_policy(LEARN_REQUEST)

    def worker():
        return {
            "origin": get_current_write_origin(),
            "terminal": get_pre_tool_call_block_message("terminal", {}),
            "skill_manage": get_pre_tool_call_block_message("skill_manage", {}),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        observed = executor.submit(
            propagate_context_to_thread(worker)
        ).result(timeout=5)

    assert observed["origin"] == LEARN_REQUEST
    assert "Governed /learn authoring denied" in observed["terminal"]
    assert observed["skill_manage"] is None


def test_next_foreground_turn_clears_learn_policy(monkeypatch):
    from agent.skill_authoring_policy import configure_turn_tool_policy
    from fabric_cli.plugins import get_pre_tool_call_block_message
    from tools.skill_provenance import LEARN_REQUEST

    monkeypatch.setattr("fabric_cli.plugins.invoke_hook", lambda *_a, **_k: [])
    configure_turn_tool_policy(LEARN_REQUEST)
    assert get_pre_tool_call_block_message("terminal", {}) is not None

    configure_turn_tool_policy("assistant_tool")
    assert get_pre_tool_call_block_message("terminal", {}) is None


def test_background_review_keeps_its_separate_policy(monkeypatch):
    from agent.skill_authoring_policy import configure_turn_tool_policy
    from fabric_cli.plugins import (
        get_pre_tool_call_block_message,
        set_thread_tool_whitelist,
    )
    from tools.skill_provenance import BACKGROUND_REVIEW

    monkeypatch.setattr("fabric_cli.plugins.invoke_hook", lambda *_a, **_k: [])
    set_thread_tool_whitelist({"memory"}, "background denied {tool_name}")
    configure_turn_tool_policy(BACKGROUND_REVIEW)

    assert get_pre_tool_call_block_message("memory", {}) is None
    assert get_pre_tool_call_block_message("terminal", {}) == (
        "background denied terminal"
    )


def test_tool_search_call_is_denied_before_unwrap_even_when_hooks_skipped():
    import model_tools

    from agent.skill_authoring_policy import configure_turn_tool_policy
    from tools.skill_provenance import LEARN_REQUEST

    configure_turn_tool_policy(LEARN_REQUEST)
    result = json.loads(
        model_tools.handle_function_call(
            "tool_call",
            {"name": "mcp_dynamic_unknown", "arguments": {}},
            skip_pre_tool_call_hook=True,
        )
    )

    assert "Governed /learn authoring denied tool 'tool_call'" in result["error"]


def test_direct_dispatch_cannot_skip_learn_policy(monkeypatch):
    import model_tools

    from agent.skill_authoring_policy import configure_turn_tool_policy
    from tools.skill_provenance import LEARN_REQUEST

    monkeypatch.setattr(
        model_tools.registry,
        "dispatch",
        lambda *_args, **_kwargs: pytest.fail("denied tool reached registry"),
    )
    configure_turn_tool_policy(LEARN_REQUEST)
    result = json.loads(
        model_tools.handle_function_call(
            "terminal",
            {"command": "touch should-never-exist"},
            skip_pre_tool_call_hook=True,
        )
    )

    assert "Governed /learn authoring denied tool 'terminal'" in result["error"]


def test_marker_predicate_matches_surface_prompt_and_not_embedded_text():
    from agent.learn_prompt import build_learn_prompt
    from tools.skill_provenance import is_learn_request_message

    assert is_learn_request_message(build_learn_prompt("a source")) is True
    assert is_learn_request_message("\n  [/learn]\r\na source") is True
    assert is_learn_request_message("quote [/learn] in this answer") is False
    assert is_learn_request_message("[/learn]ing should stay ordinary") is False
