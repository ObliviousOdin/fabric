from types import SimpleNamespace


def test_autostart_pref_reads_dashboard_config(monkeypatch):
    from fabric_cli import config as config_mod
    from fabric_cli.fabric_autostart import _autostart_pref

    monkeypatch.setattr(
        config_mod,
        "load_config_readonly",
        lambda: {"dashboard": {"autostart": "always"}},
    )

    assert _autostart_pref() == "always"


def test_autostart_never_skips_launch(monkeypatch):
    from fabric_cli import config as config_mod
    from fabric_cli import fabric_autostart as autostart

    monkeypatch.setattr(
        config_mod,
        "load_config_readonly",
        lambda: {"dashboard": {"autostart": "never"}},
    )
    monkeypatch.setattr(
        autostart,
        "_already_running",
        lambda: (_ for _ in ()).throw(AssertionError("must not probe")),
    )

    autostart.maybe_launch_dashboard(SimpleNamespace(no_dashboard=False), trigger="setup")


def test_autostart_pref_tolerates_malformed_config(monkeypatch):
    from fabric_cli import config as config_mod
    from fabric_cli.fabric_autostart import _autostart_pref

    monkeypatch.setattr(config_mod, "load_config_readonly", lambda: {"dashboard": []})

    assert _autostart_pref() == "ask"
