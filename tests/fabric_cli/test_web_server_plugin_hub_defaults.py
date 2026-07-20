"""Dashboard plugin-hub activation contracts for bundled defaults."""

from __future__ import annotations

from pathlib import Path


def test_plugin_hub_reports_bundled_default_enabled_as_active(
    monkeypatch, tmp_path: Path
) -> None:
    from fabric_cli import memory_status, plugins_cmd, web_server

    plugin_dir = tmp_path / "bundled" / "achievements"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "name: achievements\nversion: 2.0.0\nkind: standalone\ndefault_enabled: true\n",
        encoding="utf-8",
    )
    entry = (
        "achievements",
        "2.0.0",
        "Local Fabric Journey",
        "bundled",
        str(plugin_dir),
        "achievements",
    )

    monkeypatch.setattr(plugins_cmd, "_discover_all_plugins", lambda: [entry])
    monkeypatch.setattr(plugins_cmd, "_get_enabled_set", lambda: set())
    monkeypatch.setattr(plugins_cmd, "_get_disabled_set", lambda: set())
    monkeypatch.setattr(plugins_cmd, "_discover_context_engines", lambda: [])
    monkeypatch.setattr(plugins_cmd, "_get_current_context_engine", lambda: "")
    monkeypatch.setattr(web_server, "_get_dashboard_plugins", lambda: [])
    monkeypatch.setattr(web_server, "load_config", lambda: {})
    monkeypatch.setattr(web_server, "get_fabric_home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        web_server, "_discover_memory_provider_statuses", lambda _snapshot: []
    )
    monkeypatch.setattr(
        memory_status,
        "build_memory_status_snapshot",
        lambda: {"active": "none", "selection": "none"},
    )

    payload = web_server._merged_plugins_hub()

    assert len(payload["plugins"]) == 1
    assert payload["plugins"][0]["name"] == "achievements"
    assert payload["plugins"][0]["runtime_status"] == "enabled"


def test_plugin_hub_explicit_disable_wins_over_bundled_default(
    monkeypatch, tmp_path: Path
) -> None:
    from fabric_cli import memory_status, plugins_cmd, web_server

    plugin_dir = tmp_path / "bundled" / "achievements"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "name: achievements\ndefault_enabled: true\n",
        encoding="utf-8",
    )
    entry = (
        "achievements",
        "2.0.0",
        "Local Fabric Journey",
        "bundled",
        str(plugin_dir),
        "achievements",
    )

    monkeypatch.setattr(plugins_cmd, "_discover_all_plugins", lambda: [entry])
    monkeypatch.setattr(plugins_cmd, "_get_enabled_set", lambda: {"achievements"})
    monkeypatch.setattr(plugins_cmd, "_get_disabled_set", lambda: {"achievements"})
    monkeypatch.setattr(plugins_cmd, "_discover_context_engines", lambda: [])
    monkeypatch.setattr(plugins_cmd, "_get_current_context_engine", lambda: "")
    monkeypatch.setattr(web_server, "_get_dashboard_plugins", lambda: [])
    monkeypatch.setattr(web_server, "load_config", lambda: {})
    monkeypatch.setattr(web_server, "get_fabric_home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        web_server, "_discover_memory_provider_statuses", lambda _snapshot: []
    )
    monkeypatch.setattr(
        memory_status,
        "build_memory_status_snapshot",
        lambda: {"active": "none", "selection": "none"},
    )

    payload = web_server._merged_plugins_hub()

    assert payload["plugins"][0]["runtime_status"] == "disabled"
