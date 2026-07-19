import argparse
import json
from types import SimpleNamespace

from fabric_cli import plugins_cmd


def _args(**kwargs):
    defaults = {
        "enabled": False,
        "user": False,
        "no_bundled": False,
        "plain": False,
        "json": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_filter_plugin_entries_enabled_only():
    entries = [
        ("disk-cleanup", "2.0.0", "Bundled", "bundled", None, "disk-cleanup"),
        ("web-search-plus", "2.2.0", "Search", "git", None, "web-search-plus"),
        ("old-plugin", "1.0.0", "Old", "user", None, "old-plugin"),
    ]

    filtered = plugins_cmd._filter_plugin_entries(
        entries,
        _args(enabled=True),
        enabled={"disk-cleanup", "web-search-plus"},
        disabled={"old-plugin"},
    )

    assert [entry[0] for entry in filtered] == ["disk-cleanup", "web-search-plus"]


def test_filter_plugin_entries_no_bundled():
    entries = [
        ("disk-cleanup", "2.0.0", "Bundled", "bundled", None, "disk-cleanup"),
        ("drawthings-grpc", "0.3.0", "Draw Things", "user", None, "drawthings-grpc"),
        ("web-search-plus", "2.2.0", "Search", "git", None, "web-search-plus"),
    ]

    filtered = plugins_cmd._filter_plugin_entries(
        entries,
        _args(no_bundled=True),
        enabled=set(),
        disabled=set(),
    )

    assert [entry[0] for entry in filtered] == ["drawthings-grpc", "web-search-plus"]


def test_cmd_list_plain_compact_output(monkeypatch, capsys):
    entries = [
        ("disk-cleanup", "2.0.0", "Bundled", "bundled", None, "disk-cleanup"),
        ("web-search-plus", "2.2.0", "Search", "git", None, "web-search-plus"),
    ]
    monkeypatch.setattr(plugins_cmd, "_discover_all_plugins", lambda: entries)
    monkeypatch.setattr(plugins_cmd, "_get_enabled_set", lambda: {"web-search-plus"})
    monkeypatch.setattr(plugins_cmd, "_get_disabled_set", lambda: set())

    plugins_cmd.cmd_list(_args(plain=True, no_bundled=True))

    out = capsys.readouterr().out
    assert "web-search-plus" in out
    assert "enabled" in out
    assert "disk-cleanup" not in out
    assert "Search" not in out  # plain mode stays compact, no descriptions


def test_cmd_list_json_output(monkeypatch, capsys):
    entries = [("web-search-plus", "2.2.0", "Search", "git", None, "web-search-plus")]
    monkeypatch.setattr(plugins_cmd, "_discover_all_plugins", lambda: entries)
    monkeypatch.setattr(plugins_cmd, "_get_enabled_set", lambda: {"web-search-plus"})
    monkeypatch.setattr(plugins_cmd, "_get_disabled_set", lambda: set())

    plugins_cmd.cmd_list(_args(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "name": "web-search-plus",
            "status": "enabled",
            "version": "2.2.0",
            "description": "Search",
            "source": "git",
        }
    ]


def test_discover_all_plugins_includes_entrypoint_plugins(monkeypatch, tmp_path):
    bundled_dir = tmp_path / "bundled"
    user_dir = tmp_path / "user"
    bundled_dir.mkdir()
    user_dir.mkdir()

    dist = SimpleNamespace(
        version="0.1.0",
        metadata={"Summary": "Karpathy-style LLM Wikis for Fabric"},
    )
    entry_point = SimpleNamespace(
        name="wiki",
        value="adapters.fabric.cli_plugin",
        group="fabric_agent.plugins",
        dist=dist,
    )

    monkeypatch.setattr(plugins_cmd, "_plugins_dir", lambda: user_dir)
    monkeypatch.setattr(
        "fabric_cli.plugins.get_bundled_plugins_dir",
        lambda: bundled_dir,
    )
    monkeypatch.setattr(
        plugins_cmd.importlib.metadata,
        "entry_points",
        lambda: [entry_point],
    )

    entries = plugins_cmd._discover_all_plugins()

    assert entries == [
        (
            "wiki",
            "0.1.0",
            "Karpathy-style LLM Wikis for Fabric",
            "entrypoint",
            "adapters.fabric.cli_plugin",
            "wiki",
        )
    ]


def test_cmd_list_json_output_includes_entrypoint_source(monkeypatch, capsys):
    entries = [
        (
            "wiki",
            "0.1.0",
            "Karpathy-style LLM Wikis for Fabric",
            "entrypoint",
            "adapters.fabric.cli_plugin",
            "wiki",
        )
    ]
    monkeypatch.setattr(plugins_cmd, "_discover_all_plugins", lambda: entries)
    monkeypatch.setattr(plugins_cmd, "_get_enabled_set", lambda: {"wiki"})
    monkeypatch.setattr(plugins_cmd, "_get_disabled_set", lambda: set())

    plugins_cmd.cmd_list(_args(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "name": "wiki",
            "status": "enabled",
            "version": "0.1.0",
            "description": "Karpathy-style LLM Wikis for Fabric",
            "source": "entrypoint",
        }
    ]


def _default_enabled_entry(tmp_path, *, source="bundled", raw_value="true"):
    plugin_dir = tmp_path / source / "achievements"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "name: achievements\n"
        "version: 2.0.0\n"
        f"default_enabled: {raw_value}\n"
    )
    return (
        "achievements",
        "2.0.0",
        "Fabric journeys",
        source,
        plugin_dir,
        "achievements",
    )


def test_bundled_manifest_default_is_effectively_enabled(tmp_path):
    entry = _default_enabled_entry(tmp_path)

    assert plugins_cmd._entry_plugin_status(entry, set(), set()) == "enabled"
    assert plugins_cmd._filter_plugin_entries(
        [entry], _args(enabled=True), set(), set()
    ) == [entry]
    assert plugins_cmd._plugin_runtime_status(
        "achievements",
        set(),
        set(),
        "achievements",
        source="bundled",
        default_enabled=True,
    ) == "enabled"


def test_cmd_list_json_reports_bundled_manifest_default_as_enabled(
    tmp_path, monkeypatch, capsys
):
    entry = _default_enabled_entry(tmp_path)
    monkeypatch.setattr(plugins_cmd, "_discover_all_plugins", lambda: [entry])
    monkeypatch.setattr(plugins_cmd, "_get_enabled_set", lambda: set())
    monkeypatch.setattr(plugins_cmd, "_get_disabled_set", lambda: set())

    plugins_cmd.cmd_list(_args(json=True))

    assert json.loads(capsys.readouterr().out)[0]["status"] == "enabled"


def test_default_enabled_does_not_override_disable(tmp_path):
    entry = _default_enabled_entry(tmp_path)

    assert (
        plugins_cmd._entry_plugin_status(entry, set(), {"achievements"})
        == "disabled"
    )


def test_nonbundled_manifest_cannot_self_enable(tmp_path):
    entry = _default_enabled_entry(tmp_path, source="user")

    assert plugins_cmd._entry_plugin_status(entry, set(), set()) == "not enabled"
    assert plugins_cmd._plugin_runtime_status(
        "achievements",
        set(),
        set(),
        "achievements",
        source="user",
        default_enabled=True,
    ) == "inactive"


def test_string_default_enabled_is_not_treated_as_boolean_true(tmp_path):
    entry = _default_enabled_entry(tmp_path, raw_value='"true"')

    assert plugins_cmd._entry_plugin_status(entry, set(), set()) == "not enabled"
