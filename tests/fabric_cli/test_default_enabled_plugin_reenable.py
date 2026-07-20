"""Security contracts for re-enabling repository-default plugins."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fabric_cli import plugins, plugins_cmd
from fabric_cli.plugins import PluginManager


def _write_plugin(base: Path, name: str, *, default_enabled: bool) -> Path:
    plugin_dir = base / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.safe_dump({
            "name": name,
            "version": "1.0.0",
            "kind": "standalone",
            "default_enabled": default_enabled,
        }),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "def register(ctx):\n    pass\n",
        encoding="utf-8",
    )
    return plugin_dir


def _read_plugin_lists(home: Path) -> tuple[list[str], list[str]]:
    config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    plugin_config = config["plugins"]
    return plugin_config["enabled"], plugin_config["disabled"]


@pytest.mark.parametrize("surface", ["cli", "dashboard"])
def test_default_enable_disable_reenable_does_not_grant_future_user_shadow(
    surface: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Repository trust must not become a reusable same-key allow-list grant."""
    home = tmp_path / "home"
    bundled = tmp_path / "bundled"
    user_plugins = home / "plugins"
    home.mkdir()
    user_plugins.mkdir()
    _write_plugin(bundled, "journeys", default_enabled=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump({"plugins": {"enabled": [], "disabled": []}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("FABRIC_HOME", str(home))
    monkeypatch.setattr(plugins, "get_bundled_plugins_dir", lambda: bundled)
    monkeypatch.setattr(plugins_cmd, "_plugins_dir", lambda: user_plugins)
    monkeypatch.setattr(plugins_cmd, "_discover_entrypoint_plugins", lambda: [])
    monkeypatch.setattr(PluginManager, "_scan_entry_points", lambda _self: [])
    monkeypatch.setattr(plugins_cmd, "_toggle_plugin_toolset", lambda *_a, **_kw: None)

    if surface == "cli":
        plugins_cmd.cmd_disable("journeys")
        plugins_cmd.cmd_enable("journeys")
    else:
        disabled = plugins_cmd.dashboard_set_agent_plugin_enabled(
            "journeys", enabled=False
        )
        reenabled = plugins_cmd.dashboard_set_agent_plugin_enabled(
            "journeys", enabled=True
        )
        assert disabled["ok"] is True
        assert reenabled["ok"] is True

    # Re-enable removes the explicit deny, but repository-default activation
    # remains implicit instead of being copied into the reusable allow-list.
    assert _read_plugin_lists(home) == ([], [])

    # A later user plugin wins discovery precedence for the same key. It must
    # still be opt-in and therefore stay unloaded.
    _write_plugin(user_plugins, "journeys", default_enabled=False)
    manager = PluginManager()
    manager.discover_and_load()

    loaded = manager._plugins["journeys"]
    assert loaded.manifest.source == "user"
    assert loaded.enabled is False
    assert loaded.error == (
        "not enabled in config (run `fabric plugins enable journeys` to activate)"
    )


def test_composite_reenable_keeps_repository_default_implicit(monkeypatch) -> None:
    """The interactive CLI toggle must scrub old grants for defaults too."""
    saved_enabled: list[set[str]] = []
    saved_disabled: list[set[str]] = []
    monkeypatch.setattr(plugins_cmd, "_get_enabled_set", lambda: {"journeys"})
    monkeypatch.setattr(
        plugins_cmd,
        "_save_enabled_set",
        lambda value: saved_enabled.append(set(value)),
    )
    monkeypatch.setattr(
        plugins_cmd,
        "_save_disabled_set",
        lambda value: saved_disabled.append(set(value)),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    from rich.console import Console

    plugins_cmd._run_composite_fallback(
        ["journeys"],
        ["journeys [bundled]"],
        {0},
        {"journeys"},
        [],
        Console(),
        default_enabled_indices={0},
    )

    assert saved_enabled == [set()]
    assert saved_disabled == [set()]
