"""Fabric runtime brand identity tests."""

from __future__ import annotations


def test_fabric_identity_is_silent_and_named_fabric(monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "1")

    from fabric_cli.fabric_brand import FABRIC_AGENT_IDENTITY, resolve_agent_identity

    text = resolve_agent_identity()
    assert text == FABRIC_AGENT_IDENTITY
    assert "Fabric" in text
    lowered = text.lower()
    assert "hermes" not in lowered
    assert "nous" not in lowered


def test_fabric_help_guidance_is_silent(monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "1")

    from fabric_cli.fabric_brand import resolve_help_guidance

    text = resolve_help_guidance().lower()
    assert "fabric" in text
    assert "obliviousodin.github.io/fabric/" in text
    assert "hermes" not in text
    assert "nous" not in text


def test_legacy_brand_toggle_cannot_disable_public_identity(monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "0")

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


def test_fabric_brand_enabled_defaults_on(monkeypatch):
    monkeypatch.delenv("FABRIC_BRAND", raising=False)

    from fabric_cli.fabric_brand import fabric_brand_enabled

    assert fabric_brand_enabled() is True


def test_system_prompt_uses_fabric_identity_when_branded(monkeypatch):
    monkeypatch.setenv("FABRIC_BRAND", "1")

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
    assert "Hermes Agent" not in stable
