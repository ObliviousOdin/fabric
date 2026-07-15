from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.memory_governance import audit_memory
from run_agent import AIAgent
from tools.memory_tool import MemoryStore


def _tool_defs():
    return [
        {
            "type": "function",
            "function": {
                "name": "memory",
                "description": "memory",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


@pytest.fixture
def governed_agent(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.memory_governance.get_fabric_home", lambda: tmp_path)
    monkeypatch.setattr(
        "tools.memory_tool.get_memory_dir", lambda: tmp_path / "memories"
    )
    with (
        patch("run_agent.get_tool_definitions", return_value=_tool_defs()),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            session_id="raw-session-id",
        )
    agent.client = MagicMock()
    agent._memory_store = MemoryStore()
    agent._memory_store.load_from_disk()
    agent._memory_manager = None
    return agent, tmp_path


def test_invoke_tool_path_records_committed_memory(governed_agent):
    agent, home = governed_agent
    result = json.loads(
        agent._invoke_tool(
            "memory",
            {"action": "add", "target": "memory", "content": "shell: zsh"},
            "raw-task-id",
            tool_call_id="raw-tool-call-id",
        )
    )
    assert result["success"] is True
    report = audit_memory(home=home)
    assert report["summary"]["governed_active_records"] == 1
    assert report["summary"]["untracked_entries"] == 0


def test_sequential_executor_path_records_committed_memory(governed_agent):
    from agent.tool_executor import execute_tool_calls_sequential

    agent, home = governed_agent
    tool_call = SimpleNamespace(
        id="raw-sequential-call-id",
        function=SimpleNamespace(
            name="memory",
            arguments=json.dumps(
                {"action": "add", "target": "user", "content": "theme: dark"}
            ),
        ),
    )
    assistant_message = SimpleNamespace(tool_calls=[tool_call])
    messages = []

    execute_tool_calls_sequential(
        agent,
        assistant_message,
        messages,
        effective_task_id="raw-sequential-task-id",
    )

    assert json.loads(messages[-1]["content"])["success"] is True
    report = audit_memory(home=home)
    assert report["summary"]["governed_active_records"] == 1
    assert report["summary"]["untracked_entries"] == 0


def test_approved_pending_write_records_commit_provenance(governed_agent):
    from tools.memory_tool import apply_memory_pending

    agent, home = governed_agent
    result = apply_memory_pending(
        {"action": "add", "target": "memory", "content": "editor: vim"},
        agent._memory_store,
    )
    assert result["success"] is True
    state = json.loads(
        (home / "memories" / ".governance" / "memory-governance.json").read_text()
    )
    assert state["records"][0]["source"]["origin"] == "approved_write"
    assert audit_memory(home=home)["summary"]["untracked_entries"] == 0
