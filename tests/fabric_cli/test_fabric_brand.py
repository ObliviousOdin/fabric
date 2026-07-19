"""Fabric runtime brand identity tests."""

from __future__ import annotations


def test_agent_identity_is_canonically_fabric():
    from fabric_cli.fabric_brand import FABRIC_AGENT_IDENTITY, resolve_agent_identity

    text = resolve_agent_identity()
    assert text == FABRIC_AGENT_IDENTITY
    assert "Fabric" in text


def test_help_guidance_points_to_fabric_docs():
    from fabric_cli.fabric_brand import resolve_help_guidance

    text = resolve_help_guidance().lower()
    assert "fabric" in text
    assert "obliviousodin.github.io/fabric/" in text


def test_identity_resolvers_share_canonical_constants():
    from fabric_cli.fabric_brand import (
        FABRIC_AGENT_IDENTITY,
        FABRIC_HELP_GUIDANCE,
        FABRIC_SOUL_MD,
        resolve_agent_identity,
        resolve_default_soul,
        resolve_help_guidance,
    )

    assert resolve_agent_identity() == FABRIC_AGENT_IDENTITY
    assert resolve_default_soul() == FABRIC_SOUL_MD
    assert resolve_help_guidance() == FABRIC_HELP_GUIDANCE


def test_system_prompt_uses_fabric_identity():
    from types import SimpleNamespace
    from unittest.mock import patch

    from agent.system_prompt import build_system_prompt_parts
    from fabric_cli.fabric_brand import FABRIC_AGENT_IDENTITY, FABRIC_HELP_GUIDANCE

    agent = SimpleNamespace(
        load_soul_identity=False,
        skip_context_files=True,
        valid_tool_names=[],
        _task_completion_guidance=False,
        _tool_use_enforcement=False,
        _environment_probe=False,
        _kanban_worker_guidance="",
        _memory_store=None,
        _memory_manager=None,
        model="",
        provider="",
        platform="",
        pass_session_id=False,
        session_id="",
    )

    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_nous_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", return_value=""),
    ):
        stable = build_system_prompt_parts(agent)["stable"]

    assert FABRIC_AGENT_IDENTITY in stable
    assert FABRIC_HELP_GUIDANCE in stable
    assert "Fabric Agent" not in stable
