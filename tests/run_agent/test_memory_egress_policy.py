"""External-memory trust-boundary tests for restricted egress modes."""

from __future__ import annotations

import builtins
from unittest.mock import patch


class RecordingBuiltinMemoryStore:
    instances: list["RecordingBuiltinMemoryStore"] = []

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        self.loaded = False
        self.__class__.instances.append(self)

    def load_from_disk(self):
        self.loaded = True


def test_local_ai_keeps_builtin_memory_but_never_imports_external_adapter():
    """The local files load while every external-provider seam stays cold."""

    from agent import memory_manager
    from run_agent import AIAgent

    RecordingBuiltinMemoryStore.instances.clear()
    cfg = {
        "security": {"egress_mode": "local_ai"},
        "memory": {
            "memory_enabled": True,
            "user_profile_enabled": True,
            "provider": "bomb-provider",
        },
        "agent": {},
    }
    policy_cfg = {
        "security": {
            "egress_mode": "local_ai",
            "local_ai_allowed_cidrs": [],
        }
    }
    real_import = builtins.__import__
    attempted_adapter_imports: list[str] = []

    def guarded_import(name, *args, **kwargs):
        if name == "plugins.memory" or name.startswith("plugins.memory."):
            attempted_adapter_imports.append(name)
            raise AssertionError("external memory module imported")
        return real_import(name, *args, **kwargs)

    def injection_bomb(_agent):
        raise AssertionError("external memory tools injected")

    with (
        patch("fabric_cli.config.load_config", return_value=cfg),
        patch(
            "fabric_cli.config.load_egress_policy_config",
            return_value=policy_cfg,
        ),
        patch("tools.memory_tool.MemoryStore", RecordingBuiltinMemoryStore),
        patch.object(
            memory_manager,
            "inject_memory_provider_tools",
            side_effect=injection_bomb,
        ),
        patch("agent.model_metadata.get_model_context_length", return_value=204_800),
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
        patch("builtins.__import__", side_effect=guarded_import),
    ):
        agent = AIAgent(
            api_key="no-key-required",
            base_url="http://127.0.0.1:11434/v1",
            provider="custom",
            model="local-model",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=False,
        )

    assert attempted_adapter_imports == []
    assert agent._memory_manager is None
    assert agent._memory_store is RecordingBuiltinMemoryStore.instances[0]
    assert agent._memory_store.loaded is True
    assert agent._memory_enabled is True
    assert agent._user_profile_enabled is True

