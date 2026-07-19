"""Tests for the ByteRover memory provider config gates."""

import threading

import plugins.memory.byterover as byterover
from plugins.memory.byterover import ByteRoverMemoryProvider


def test_shared_provider_config_remains_available(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.config.load_config",
        lambda: {"memory": {"provider_config": {"auto_extract": False}}},
    )

    assert byterover._load_plugin_config() == {"auto_extract": False}


def test_auto_extract_false_skips_sync_turn(monkeypatch):
    calls = []
    provider = ByteRoverMemoryProvider({"auto_extract": False})
    provider.initialize("session-1")

    monkeypatch.setattr("plugins.memory.byterover._run_brv", lambda *args, **kwargs: calls.append((args, kwargs)))

    provider.sync_turn("please remember this detail", "acknowledged")

    assert calls == []
    assert provider._sync_thread is None


def test_auto_extract_false_skips_memory_write(monkeypatch):
    calls = []
    provider = ByteRoverMemoryProvider({"auto_extract": "false"})
    provider.initialize("session-1")

    monkeypatch.setattr("plugins.memory.byterover._run_brv", lambda *args, **kwargs: calls.append((args, kwargs)))

    provider.on_memory_write("add", "user", "User prefers concise responses")

    assert calls == []


def test_auto_extract_false_skips_pre_compress(monkeypatch):
    calls = []
    provider = ByteRoverMemoryProvider({"auto_extract": "off"})
    provider.initialize("session-1")

    monkeypatch.setattr("plugins.memory.byterover._run_brv", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = provider.on_pre_compress([
        {"role": "user", "content": "remember this"},
        {"role": "assistant", "content": "stored"},
    ])

    assert result == ""
    assert calls == []


def test_auto_extract_false_keeps_explicit_curate_tool(monkeypatch):
    calls = []
    provider = ByteRoverMemoryProvider({"auto_extract": False})
    provider.initialize("session-1")

    def fake_run(args, **kwargs):
        calls.append(args)
        return {"success": True, "output": "ok"}

    monkeypatch.setattr("plugins.memory.byterover._run_brv", fake_run)

    result = provider.handle_tool_call("brv_curate", {"content": "Important project fact"})

    assert "Memory curated successfully" in result
    assert calls == [["curate", "--", "Important project fact"]]


def test_background_sync_keeps_profile_secret_scope_after_parent_exits(
    monkeypatch, tmp_path
):
    from agent.secret_scope import (
        current_secret_scope,
        reset_secret_scope,
        set_secret_scope,
    )
    from fabric_constants import (
        reset_fabric_home_override,
        set_fabric_home_override,
    )

    release = threading.Event()
    observed = {}

    def fake_run(*_args, **_kwargs):
        assert release.wait(timeout=2)
        observed.update(current_secret_scope() or {})
        return {"success": True, "output": "ok"}

    monkeypatch.setattr("plugins.memory.byterover._run_brv", fake_run)
    home_token = set_fabric_home_override(tmp_path)
    secret_token = set_secret_scope({"BRV_API_KEY": "profile-brv-key"})
    provider = ByteRoverMemoryProvider({"auto_extract": True})
    try:
        provider.initialize("session-1")
        provider.sync_turn("please remember this detail", "acknowledged")
    finally:
        reset_secret_scope(secret_token)
        reset_fabric_home_override(home_token)

    release.set()
    provider._sync_thread.join(timeout=2)
    assert observed == {"BRV_API_KEY": "profile-brv-key"}
