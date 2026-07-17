"""External-memory content writes require explicit profile consent."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider
from agent.memory_write_policy import resolve_external_memory_write_policy
from fabric_constants import reset_fabric_home_override, set_fabric_home_override


class _RecordingProvider(MemoryProvider):
    def __init__(self, name: str = "external") -> None:
        self._name = name
        self.calls: list[tuple[str, Any]] = []
        self.fail_sync = False

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self.calls.append(("initialize", session_id))

    def system_prompt_block(self) -> str:
        self.calls.append(("system_prompt", None))
        return "Provider write instructions"

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self.calls.append(("prefetch", query))
        return "safe recalled fact"

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        self.calls.append(("queue_prefetch", query))

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        if self.fail_sync:
            raise RuntimeError(
                "secret-token=provider-secret raw-user-content=private-fact"
            )
        self.calls.append(("sync_turn", user_content))

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        self.calls.append(("tool_schemas", None))
        return [
            {
                "name": "external_memory_action",
                "description": "May read or mutate provider memory",
                "parameters": {},
            }
        ]

    def handle_tool_call(
        self, tool_name: str, args: dict[str, Any], **kwargs: Any
    ) -> str:
        self.calls.append(("provider_tool", dict(args)))
        return json.dumps({"success": True})

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        self.calls.append(("turn_start", message))

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        self.calls.append(("session_end", list(messages)))

    def on_session_switch(self, new_session_id: str, **kwargs: Any) -> None:
        self.calls.append(("session_switch", new_session_id))

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        self.calls.append(("pre_compress", list(messages)))
        return "provider compression context"

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append(("memory_write", content))

    def on_delegation(
        self,
        task: str,
        result: str,
        *,
        child_session_id: str = "",
        **kwargs: Any,
    ) -> None:
        self.calls.append(("delegation", result))

    def shutdown(self) -> None:
        self.calls.append(("shutdown", None))


def _exercise_content_write_surfaces(manager: MemoryManager) -> None:
    messages = [{"role": "user", "content": "private transcript"}]
    manager.build_system_prompt()
    manager.sync_all("private user turn", "private assistant turn", messages=messages)
    manager.on_turn_start(1, "private user turn")
    manager.on_session_end(messages)
    manager.on_session_switch("next-session")
    manager.on_pre_compress(messages)
    manager.on_memory_write("add", "memory", "private durable fact")
    manager.on_delegation("private task", "private delegated result")
    manager.handle_tool_call("external_memory_action", {"content": "private tool fact"})
    manager.flush_pending(timeout=5)


def test_external_content_writes_default_to_denied_while_recall_remains_available():
    provider = _RecordingProvider()
    manager = MemoryManager()
    manager.add_provider(provider)

    assert manager.external_write_consent is False
    assert "safe recalled fact" in manager.prefetch_all("recall query")
    manager.queue_prefetch_all("next recall query")
    _exercise_content_write_surfaces(manager)
    manager.flush_pending(timeout=5)

    operations = [operation for operation, _value in provider.calls]
    assert operations == ["prefetch", "queue_prefetch"]
    assert manager.get_all_tool_schemas() == []
    assert manager.has_tool("external_memory_action") is False


def test_explicit_consent_enables_every_guarded_content_write_surface():
    provider = _RecordingProvider()
    manager = MemoryManager(external_write_consent=True)
    manager.add_provider(provider)

    _exercise_content_write_surfaces(manager)

    operations = {operation for operation, _value in provider.calls}
    assert {
        "system_prompt",
        "sync_turn",
        "turn_start",
        "session_end",
        "session_switch",
        "pre_compress",
        "memory_write",
        "delegation",
        "provider_tool",
    } <= operations
    assert manager.has_tool("external_memory_action") is True


def test_mixed_unclassified_tool_and_prompt_surface_fails_closed_but_recall_does_not():
    class _MixedProvider(_RecordingProvider):
        def get_tool_schemas(self) -> list[dict[str, Any]]:
            return [
                {"name": "provider_search", "description": "read", "parameters": {}},
                {"name": "provider_store", "description": "write", "parameters": {}},
            ]

        def system_prompt_block(self) -> str:
            self.calls.append(("system_prompt", None))
            return "Use provider_search to read and provider_store to write."

    provider = _MixedProvider()
    manager = MemoryManager()
    manager.add_provider(provider)

    # The provider ABI has no machine-readable per-tool or per-prompt-fragment
    # effect declaration. Exposing only the name that looks read-only would be
    # an unsafe heuristic, so the mixed surface is withheld as one unit.
    assert manager.get_all_tool_schemas() == []
    assert manager.build_system_prompt() == ""
    assert "safe recalled fact" in manager.prefetch_all("read-only recall")
    assert provider.calls == [("prefetch", "read-only recall")]


def test_denied_session_rebind_disables_recall_instead_of_leaking_old_scope():
    provider = _RecordingProvider()
    manager = MemoryManager()
    manager.add_provider(provider)
    manager.initialize_all("session-one")

    assert "safe recalled fact" in manager.prefetch_all(
        "before switch", session_id="session-one"
    )
    manager.on_session_switch("session-two", reset=True)

    assert manager.prefetch_all("after switch", session_id="session-two") == ""
    assert manager.initialization_states == {"external": "disabled"}
    assert ("session_switch", "session-two") not in provider.calls


def test_denied_same_session_compression_does_not_disable_read_only_recall():
    provider = _RecordingProvider()
    manager = MemoryManager()
    manager.add_provider(provider)
    manager.initialize_all("same-session")

    manager.on_session_switch("same-session", reset=False, reason="compression")

    assert "safe recalled fact" in manager.prefetch_all(
        "after compression", session_id="same-session"
    )


def test_builtin_provider_behavior_is_unchanged_without_external_consent():
    provider = _RecordingProvider(name="builtin")
    manager = MemoryManager()
    manager.add_provider(provider)

    _exercise_content_write_surfaces(manager)

    operations = {operation for operation, _value in provider.calls}
    assert "sync_turn" in operations
    assert "session_end" in operations
    assert "provider_tool" in operations
    assert manager.has_tool("external_memory_action") is True


def test_provider_failure_log_never_echoes_exception_or_content(caplog):
    provider = _RecordingProvider()
    provider.fail_sync = True
    manager = MemoryManager(external_write_consent=True)
    manager.add_provider(provider)

    with caplog.at_level(logging.WARNING):
        manager.sync_all("private-fact", "assistant", session_id="s1")
        assert manager.flush_pending(timeout=5)

    assert "memory_provider_operation_failed" in caplog.text
    assert "operation=sync_turn" in caplog.text
    assert "provider-secret" not in caplog.text
    assert "private-fact" not in caplog.text


@pytest.mark.parametrize(
    ("memory_config", "allowed", "valid", "reason"),
    [
        ({}, False, True, "consent_required"),
        ({"external_write_consent": False}, False, True, "consent_disabled"),
        ({"external_write_consent": True}, True, True, "explicit_profile_consent"),
        ({"external_write_consent": "true"}, False, False, "consent_must_be_boolean"),
        ({"external_write_consent": 1}, False, False, "consent_must_be_boolean"),
        (None, False, False, "memory_config_invalid"),
    ],
)
def test_consent_parser_requires_a_literal_yaml_boolean(
    memory_config, allowed, valid, reason
):
    policy = resolve_external_memory_write_policy(memory_config)
    assert policy.allowed is allowed
    assert policy.valid is valid
    assert policy.reason == reason


def test_config_validation_rejects_string_consent():
    from fabric_cli.config import validate_config_structure

    issues = validate_config_structure(
        {"memory": {"external_write_consent": "true"}}
    )

    assert any(
        issue.severity == "error"
        and "memory.external_write_consent" in issue.message
        for issue in issues
    )


def test_environment_cannot_grant_external_write_consent(monkeypatch):
    monkeypatch.setenv("EXTERNAL_MEMORY_WRITE_CONSENT", "true")
    monkeypatch.setenv("FABRIC_EXTERNAL_MEMORY_WRITE_CONSENT", "true")

    assert resolve_external_memory_write_policy({}).allowed is False
    assert (
        resolve_external_memory_write_policy(
            {"external_write_consent": "${EXTERNAL_MEMORY_WRITE_CONSENT}"}
        ).allowed
        is False
    )

def test_consent_isolated_by_profile_home(tmp_path: Path):
    allowed_home = tmp_path / "profiles" / "allowed"
    denied_home = tmp_path / "profiles" / "denied"
    allowed_home.mkdir(parents=True)
    denied_home.mkdir(parents=True)
    (allowed_home / "config.yaml").write_text(
        "memory:\n  external_write_consent: true\n",
        encoding="utf-8",
    )
    (denied_home / "config.yaml").write_text(
        "memory:\n  external_write_consent: false\n",
        encoding="utf-8",
    )

    from fabric_cli.config import load_config

    decisions = []
    for home in (allowed_home, denied_home, allowed_home):
        token = set_fabric_home_override(home)
        try:
            config = load_config()
            decisions.append(
                resolve_external_memory_write_policy(config.get("memory")).allowed
            )
        finally:
            reset_fabric_home_override(token)

    assert decisions == [True, False, True]
