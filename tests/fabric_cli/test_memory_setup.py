from types import SimpleNamespace
from unittest.mock import MagicMock
import argparse

import pytest

import fabric_cli.memory_setup as memory_setup
from fabric_cli.memory_setup import _CANCELLED, _curses_select
from fabric_cli.subcommands.memory import build_memory_parser


def test_curses_select_cancel_defaults_to_selected(monkeypatch):
    captured = {}

    def fake_radiolist(title, items, selected=0, *, cancel_returns=None):
        captured.update({
            "title": title,
            "items": items,
            "selected": selected,
            "cancel_returns": cancel_returns,
        })
        return cancel_returns

    monkeypatch.setattr("fabric_cli.curses_ui.curses_radiolist", fake_radiolist)

    result = _curses_select("Pick one", [("first", "desc"), ("second", "")], default=1)

    assert result == 1
    assert captured == {
        "title": "Pick one",
        "items": ["first - desc", "second"],
        "selected": 1,
        "cancel_returns": 1,
    }


def test_curses_select_accepts_explicit_cancel_value(monkeypatch):
    captured = {}

    def fake_radiolist(title, items, selected=0, *, cancel_returns=None):
        captured["cancel_returns"] = cancel_returns
        return cancel_returns

    monkeypatch.setattr("fabric_cli.curses_ui.curses_radiolist", fake_radiolist)

    result = _curses_select("Pick one", [("first", "")], default=0, cancel_returns=_CANCELLED)

    assert result == _CANCELLED
    assert captured["cancel_returns"] == _CANCELLED


def test_curses_select_clears_after_picker_returns(monkeypatch):
    events = []

    def fake_radiolist(title, items, selected=0, *, cancel_returns=None):
        events.append("picker")
        return selected

    monkeypatch.setattr("fabric_cli.curses_ui.curses_radiolist", fake_radiolist)
    monkeypatch.setattr(memory_setup, "_clear_interactive_transition", lambda: events.append("clear"))

    result = _curses_select("Pick one", [("first", "")], default=0)

    assert result == 0
    assert events == ["picker", "clear"]


def test_cmd_setup_top_level_cancel_writes_nothing(monkeypatch):
    save_config = MagicMock()
    load_config = MagicMock(side_effect=AssertionError("cancel should not load config"))

    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: [("fake", "local", object())])
    monkeypatch.setattr(memory_setup, "_curses_select", lambda *args, **kwargs: kwargs["cancel_returns"])
    monkeypatch.setattr("fabric_cli.config.load_config", load_config)
    monkeypatch.setattr("fabric_cli.config.save_config", save_config)

    memory_setup.cmd_setup(SimpleNamespace())

    load_config.assert_not_called()
    save_config.assert_not_called()


@pytest.mark.parametrize(
    ("selection", "expected"),
    [(0, True), (1, False)],
)
def test_external_write_consent_prompt_persists_explicit_profile_choice(
    monkeypatch, capsys, selection, expected
):
    config = {"memory": {}}
    captured = {}

    def choose(title, items, default=0, **kwargs):
        captured.update(title=title, items=items, default=default, kwargs=kwargs)
        return selection

    monkeypatch.setattr(memory_setup, "_curses_select", choose)

    assert memory_setup._prompt_external_write_consent(config, "fake") is True
    assert config["memory"]["external_write_consent"] is expected
    assert captured["default"] == 1
    assert captured["kwargs"]["cancel_returns"] == _CANCELLED
    output = capsys.readouterr().out
    assert "completed turns" in output
    assert "active profile" in output


def test_external_write_consent_prompt_cancel_preserves_existing_value(monkeypatch):
    config = {"memory": {"external_write_consent": True}}
    monkeypatch.setattr(
        memory_setup,
        "_curses_select",
        lambda *args, **kwargs: _CANCELLED,
    )

    assert memory_setup._prompt_external_write_consent(config, "fake") is False
    assert config["memory"]["external_write_consent"] is True


def test_cancelled_provider_setup_cannot_persist_new_consent(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "memory:\n  provider: fake\n  external_write_consent: false\n",
        encoding="utf-8",
    )
    before = memory_setup._file_signature(config_path)
    save_config = MagicMock()
    monkeypatch.setattr("fabric_cli.config.save_config", save_config)
    monkeypatch.setattr(
        "fabric_cli.config.load_config",
        lambda: {"memory": {"provider": "fake", "external_write_consent": False}},
    )

    memory_setup._persist_consent_after_provider_setup(
        config_path=config_path,
        before_signature=before,
        consent=True,
    )

    save_config.assert_not_called()


def test_successful_legacy_provider_setup_gets_selected_consent(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("memory:\n  provider: old\n", encoding="utf-8")
    before = memory_setup._file_signature(config_path)
    # A legacy hook writes config independently and ignores the mapping passed
    # by memory_setup; changing size is a deterministic success signature.
    config_path.write_text("memory:\n  provider: fake\n", encoding="utf-8")
    persisted = {"memory": {"provider": "fake"}}
    save_config = MagicMock()
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: persisted)
    monkeypatch.setattr("fabric_cli.config.save_config", save_config)

    memory_setup._persist_consent_after_provider_setup(
        config_path=config_path,
        before_signature=before,
        consent=True,
    )

    assert persisted["memory"]["external_write_consent"] is True
    save_config.assert_called_once_with(persisted)


def test_cmd_setup_builtin_selection_still_saves_builtin(monkeypatch):
    save_config = MagicMock()
    config = {"memory": {"provider": "openviking"}}
    providers = [("fake", "local", object())]

    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: providers)
    monkeypatch.setattr(memory_setup, "_curses_select", lambda *args, **kwargs: len(providers))
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr("fabric_cli.config.save_config", save_config)

    memory_setup.cmd_setup(SimpleNamespace())

    assert config["memory"]["provider"] == ""
    assert config["memory"]["external_write_consent"] is False
    save_config.assert_called_once_with(config)


def test_cmd_setup_clears_interactive_picker_before_provider_post_setup(monkeypatch):
    events = []

    class PostSetupProvider:
        def post_setup(self, hermes_home, config):
            events.append("post_setup")

    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: [("openviking", "local", PostSetupProvider())])
    monkeypatch.setattr(memory_setup, "_curses_select", lambda *args, **kwargs: events.append("select") or 0)
    monkeypatch.setattr(memory_setup, "_clear_interactive_transition", lambda: events.append("clear"), raising=False)
    monkeypatch.setattr(
        memory_setup,
        "_prompt_external_write_consent",
        lambda config, name: events.append("consent") or True,
    )
    monkeypatch.setattr(memory_setup, "_install_dependencies", lambda name: events.append("install"))
    monkeypatch.setattr(memory_setup, "get_fabric_home", lambda: "/tmp/hermes-test")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: {"memory": {}})

    memory_setup.cmd_setup(SimpleNamespace())

    assert events == ["select", "clear", "consent", "install", "post_setup"]


def test_cmd_setup_provider_clears_before_provider_post_setup(monkeypatch):
    events = []

    class PostSetupProvider:
        def post_setup(self, hermes_home, config):
            events.append("post_setup")

    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: [("openviking", "local", PostSetupProvider())])
    monkeypatch.setattr(memory_setup, "_clear_interactive_transition", lambda: events.append("clear"), raising=False)
    monkeypatch.setattr(
        memory_setup,
        "_prompt_external_write_consent",
        lambda config, name: events.append("consent") or True,
    )
    monkeypatch.setattr(memory_setup, "_install_dependencies", lambda name: events.append("install"))
    monkeypatch.setattr(memory_setup, "get_fabric_home", lambda: "/tmp/hermes-test")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: {"memory": {}})

    memory_setup.cmd_setup_provider("openviking")

    assert events == ["clear", "consent", "install", "post_setup"]


def test_cmd_setup_provider_explicit_slug_bypasses_curated_picker(monkeypatch):
    events = []

    class InstalledProvider:
        def get_config_schema(self):
            return []

        def post_setup(self, hermes_home, config):
            events.append(("post_setup", hermes_home))

    provider = InstalledProvider()
    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: [])
    monkeypatch.setattr("plugins.memory.load_memory_provider", lambda name: provider if name == "mem0" else None)
    monkeypatch.setattr(memory_setup, "_clear_interactive_transition", lambda: events.append(("clear", "")))
    monkeypatch.setattr(
        memory_setup,
        "_prompt_external_write_consent",
        lambda config, name: events.append(("consent", name)) or True,
    )
    monkeypatch.setattr(memory_setup, "_install_dependencies", lambda name: events.append(("install", name)))
    monkeypatch.setattr(memory_setup, "get_fabric_home", lambda: "/tmp/fabric-profile")
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: {"memory": {}})

    memory_setup.cmd_setup_provider("mem0")

    assert events == [
        ("clear", ""),
        ("consent", "mem0"),
        ("install", "mem0"),
        ("post_setup", "/tmp/fabric-profile"),
    ]


def test_cmd_status_uses_shared_snapshot_without_provider_probe_or_config(
    monkeypatch, capsys
):
    config = {
        "memory": {
            "provider": "openviking",
            "openviking": {
                "endpoint": "http://stale.local",
                "api_key": "do-not-print",
            },
        }
    }
    snapshot = {
        "selected_external_provider": "openviking",
        "memory_enabled": True,
        "user_profile_enabled": True,
        "any_tier_enabled": True,
        "providers": [
            {
                "name": "openviking",
                "discovered": True,
                "available": True,
                "selected": True,
                "activation_eligible": True,
                "source": "bundled",
                "capabilities": {"recall": "supported"},
            }
        ],
        "issues": [],
    }
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        "fabric_cli.memory_status.build_memory_status_snapshot",
        lambda **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        memory_setup,
        "_get_available_providers",
        lambda: pytest.fail("status must not invoke provider-specific hooks"),
    )

    memory_setup.cmd_status(SimpleNamespace())

    output = capsys.readouterr().out
    assert "http://stale.local" not in output
    assert "do-not-print" not in output
    assert "Runtime:   not observed; live health not probed" in output


@pytest.mark.parametrize(
    ("memory_enabled", "user_profile_enabled", "memory_text", "user_text"),
    [
        (True, False, "MEMORY.md: enabled", "USER.md:   disabled"),
        (False, True, "MEMORY.md: disabled", "USER.md:   enabled"),
        (False, False, "MEMORY.md: disabled", "USER.md:   disabled"),
    ],
)
def test_cmd_status_reports_effective_memory_tiers(
    monkeypatch,
    capsys,
    memory_enabled,
    user_profile_enabled,
    memory_text,
    user_text,
):
    config = {
        "memory": {
            "memory_enabled": memory_enabled,
            "user_profile_enabled": user_profile_enabled,
            "provider": "holographic",
        }
    }
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr(
        memory_setup,
        "_get_available_providers",
        lambda: [
            (
                "holographic",
                "local",
                SimpleNamespace(is_available=lambda: True),
            )
        ],
    )

    memory_setup.cmd_status(SimpleNamespace())

    output = capsys.readouterr().out
    assert memory_text in output
    assert user_text in output
    if not memory_enabled and not user_profile_enabled:
        assert "configured, inactive — all memory tiers disabled" in output
        assert "Plugin:" not in output


def test_memory_help_describes_effective_tiers(capsys):
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    build_memory_parser(subparsers, cmd_memory=lambda _args: None)

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["memory", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "always active" not in output
    assert "memory.memory_enabled" in output
    assert "memory.user_profile_enabled" in output
    assert "supermemory" in output


def test_memory_off_does_not_claim_builtin_tiers_are_active(monkeypatch, capsys):
    from fabric_cli.main import cmd_memory

    config = {
        "memory": {
            "provider": "holographic",
            "memory_enabled": False,
            "user_profile_enabled": False,
        }
    }
    saved = []
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: config)
    monkeypatch.setattr("fabric_cli.config.save_config", lambda value: saved.append(value))

    cmd_memory(SimpleNamespace(memory_command="off"))

    output = capsys.readouterr().out
    assert config["memory"]["provider"] == ""
    assert config["memory"]["external_write_consent"] is False
    assert saved == [config]
    assert "External memory provider disabled" in output
    assert "tier settings were not changed" in output
    assert "built-in only" not in output


def test_cmd_setup_generic_choice_cancel_writes_nothing(tmp_path, monkeypatch):
    class ChoiceProvider:
        def __init__(self):
            self.save_config = MagicMock()

        def get_config_schema(self):
            return [{
                "key": "mode",
                "description": "Mode",
                "default": "one",
                "choices": ["one", "two"],
            }]

    provider = ChoiceProvider()
    selections = iter([0, 1, _CANCELLED])
    save_config = MagicMock()
    install_dependencies = MagicMock()

    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: [("fake", "local", provider)])
    monkeypatch.setattr(memory_setup, "_curses_select", lambda *args, **kwargs: next(selections))
    monkeypatch.setattr(memory_setup, "_install_dependencies", install_dependencies)
    monkeypatch.setattr(memory_setup, "get_fabric_home", lambda: tmp_path)
    monkeypatch.setattr("fabric_cli.config.load_config", lambda: {"memory": {}})
    monkeypatch.setattr("fabric_cli.config.save_config", save_config)

    memory_setup.cmd_setup(SimpleNamespace())

    install_dependencies.assert_called_once_with("fake")
    save_config.assert_not_called()
    provider.save_config.assert_not_called()
    assert not (tmp_path / ".env").exists()
