"""Memory status behavior under ``local_ai`` and ``air_gapped`` policies."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from agent.memory_provider import MemoryProviderCapabilities
from fabric_cli import memory_status
from fabric_cli.memory_status import (
    build_memory_status_snapshot,
    format_memory_status_snapshot,
)


class RecordingProvider:
    def __init__(self):
        self.available_calls = 0
        self.schema_calls = 0
        self.capability_calls = 0
        self.initialize_calls = 0
        self.health_calls = 0

    def is_available(self):
        self.available_calls += 1
        return True

    def get_config_schema(self):
        self.schema_calls += 1
        return []

    def get_capabilities(self):
        self.capability_calls += 1
        return MemoryProviderCapabilities()

    def initialize(self, *args, **kwargs):
        self.initialize_calls += 1
        raise AssertionError("status initialized provider")

    def health_check(self):
        self.health_calls += 1
        raise AssertionError("status probed provider health")


def _restricted_snapshot(
    tmp_path: Path,
    *,
    mode: str,
    provider_dir: Path,
    name: str,
    load_provider,
):
    memory_dir = tmp_path / "memories"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "MEMORY.md").write_text("local built-in fact", encoding="utf-8")
    return build_memory_status_snapshot(
        config={
            "security": {"egress_mode": mode},
            "memory": {
                "provider": name,
                "memory_enabled": True,
                "user_profile_enabled": True,
                name: {
                    "api_key": "do-not-serialize-secret",
                    "endpoint": "https://memory-secret.invalid/path?token=secret",
                },
            },
        },
        home=tmp_path,
        env={"MEMORY_SECRET": "do-not-serialize-secret"},
        discover=lambda: [(name, "Static adapter description", None)],
        load_provider=load_provider,
        find_provider_dir=lambda requested: provider_dir if requested == name else None,
    )


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("local_ai", "external_memory_adapters_not_policy_integrated"),
        ("air_gapped", "whole_process_network_boundary_missing"),
    ],
)
@pytest.mark.parametrize("source", ["bundled", "user"])
def test_restricted_status_never_loads_or_probes_any_adapter(
    tmp_path,
    mode,
    reason,
    source,
):
    name = "honcho" if source == "bundled" else "user-memory"
    if source == "bundled":
        provider_dir = (
            Path(memory_status.__file__).resolve().parents[1]
            / "plugins"
            / "memory"
            / "honcho"
        )
    else:
        provider_dir = tmp_path / "plugins" / name
        provider_dir.mkdir(parents=True)
        (provider_dir / "__init__.py").write_text(
            "# MemoryProvider marker; must never be imported\n",
            encoding="utf-8",
        )

    calls = []

    def load_bomb(requested):
        calls.append(requested)
        raise AssertionError(
            "adapter loader leaked https://secret.invalid/?key=do-not-serialize"
        )

    snapshot = _restricted_snapshot(
        tmp_path,
        mode=mode,
        provider_dir=provider_dir,
        name=name,
        load_provider=load_bomb,
    )

    assert calls == []
    assert snapshot["selection"] == {
        "configured": name,
        "state": "unavailable",
        "runtime_active": "unknown",
    }
    assert snapshot["eligible_external_provider"] is None
    assert snapshot["builtin"]["enabled"] is True
    assert snapshot["builtin_files"]["memory"] == len("local built-in fact")

    row = next(item for item in snapshot["providers"] if item["name"] == name)
    assert row["source"] == source
    assert row["status"] == "unavailable"
    assert row["available"] is False
    assert row["activation_eligible"] is False
    assert row["lifecycle"]["load"] == "not_inspected"
    assert row["readiness"] == {
        "configuration_complete": None,
        "dependencies_available": None,
        "adapter_ready": None,
        "profile_observation_reliable": False,
    }
    assert set(row["capabilities"].values()) == {"unknown"}

    policy_issue = next(
        issue
        for issue in snapshot["issues"]
        if issue["code"] == "external_memory_blocked_by_egress_policy"
    )
    assert policy_issue["provider"] == name
    assert policy_issue["mode"] == mode
    assert policy_issue["reason"] == reason
    formatted = format_memory_status_snapshot(snapshot)
    assert "Readiness: unavailable" in formatted
    assert policy_issue["message"] in formatted

    serialized = json.dumps(snapshot)
    assert "do-not-serialize-secret" not in serialized
    assert "memory-secret.invalid" not in serialized
    assert "secret.invalid" not in serialized


def test_restricted_default_inventory_does_not_import_memory_plugin_loader(
    tmp_path,
    monkeypatch,
):
    real_import = builtins.__import__
    attempted: list[str] = []

    def guarded_import(name, *args, **kwargs):
        if name == "plugins.memory" or name.startswith("plugins.memory."):
            attempted.append(name)
            raise AssertionError("memory adapter package imported")
        return real_import(name, *args, **kwargs)

    callback_attempts: list[str] = []

    def callback_bomb(*_args, **_kwargs):
        callback_attempts.append("called")
        raise AssertionError("injected live adapter discovery boundary called")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    snapshot = build_memory_status_snapshot(
        config={
            "security": {"egress_mode": "local_ai"},
            "memory": {"provider": "honcho"},
        },
        home=tmp_path,
        env={},
        discover=callback_bomb,
        load_provider=callback_bomb,
        find_provider_dir=callback_bomb,
    )

    assert attempted == []
    assert callback_attempts == []
    assert snapshot["selection"]["state"] == "unavailable"


def test_restricted_selected_provider_stays_unavailable_when_tiers_are_disabled(
    tmp_path,
):
    calls: list[str] = []
    snapshot = build_memory_status_snapshot(
        config={
            "security": {"egress_mode": "local_ai"},
            "memory": {
                "provider": "recording",
                "memory_enabled": False,
                "user_profile_enabled": False,
            },
        },
        home=tmp_path,
        env={},
        discover=lambda: [("recording", "Recording", None)],
        load_provider=lambda name: calls.append(name),
        find_provider_dir=lambda _name: tmp_path / "plugins" / "recording",
    )

    assert calls == []
    assert snapshot["selection"]["state"] == "unavailable"
    assert snapshot["any_tier_enabled"] is False
    assert any(
        issue["code"] == "external_memory_blocked_by_egress_policy"
        for issue in snapshot["issues"]
    )


def test_air_gapped_unavailable_issue_is_visible_without_external_provider(tmp_path):
    snapshot = build_memory_status_snapshot(
        config={
            "security": {"egress_mode": "air_gapped"},
            "memory": {"provider": ""},
        },
        home=tmp_path,
        env={},
        discover=lambda: [],
        load_provider=lambda _name: None,
        find_provider_dir=lambda _name: None,
    )

    assert snapshot["selection"]["state"] == "builtin_only"
    issue = next(
        item
        for item in snapshot["issues"]
        if item["code"] == "egress_policy_unavailable"
    )
    assert issue["reason"] == "whole_process_network_boundary_missing"
    assert issue["message"] in format_memory_status_snapshot(snapshot)


def test_policy_status_is_uncached_across_sequential_profile_snapshots(tmp_path):
    provider = RecordingProvider()
    provider_dir = tmp_path / "plugins" / "recording"
    provider_dir.mkdir(parents=True)
    common = {
        "home": tmp_path,
        "env": {},
        "discover": lambda: [("recording", "Recording", None)],
        "load_provider": lambda _name: provider,
        "find_provider_dir": lambda _name: provider_dir,
    }

    restricted = build_memory_status_snapshot(
        config={
            "security": {"egress_mode": "local_ai"},
            "memory": {"provider": "recording"},
        },
        **common,
    )
    online = build_memory_status_snapshot(
        config={
            "security": {"egress_mode": "online"},
            "memory": {"provider": "recording"},
        },
        **common,
    )

    assert restricted["selection"]["state"] == "unavailable"
    assert online["selection"]["state"] == "eligible"
    assert provider.available_calls == 1
    assert provider.schema_calls == 1
    assert provider.capability_calls == 1
    assert provider.initialize_calls == 0
    assert provider.health_calls == 0
