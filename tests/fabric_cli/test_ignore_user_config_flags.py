"""Tests for the in-process ``--ignore-user-config`` and ``--ignore-rules`` policy."""

from __future__ import annotations

import sys
import textwrap
import types


def _write_user_config(tmp_path, model_default: str) -> None:
    config_yaml = textwrap.dedent(
        f"""
        model:
          default: {model_default}
          provider: openrouter
        agent:
          system_prompt: "from user config"
        """
    ).lstrip()
    (tmp_path / "config.yaml").write_text(config_yaml, encoding="utf-8")


def _load_cli_config(monkeypatch, tmp_path, *, ignore_user_config: bool):
    import cli

    monkeypatch.setattr(cli, "_fabric_home", tmp_path)
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "project" / "cli.py"))
    return cli.load_cli_config(ignore_user_config=ignore_user_config)


def test_user_config_loaded_by_default(tmp_path, monkeypatch):
    _write_user_config(tmp_path, "anthropic/claude-sonnet-4.6")

    cfg = _load_cli_config(monkeypatch, tmp_path, ignore_user_config=False)

    assert cfg["model"]["default"] == "anthropic/claude-sonnet-4.6"
    assert cfg["agent"]["system_prompt"] == "from user config"


def test_user_config_skipped_when_requested(tmp_path, monkeypatch):
    _write_user_config(tmp_path, "anthropic/claude-sonnet-4.6")

    cfg = _load_cli_config(monkeypatch, tmp_path, ignore_user_config=True)

    assert cfg["agent"].get("system_prompt", "") != "from user config"
    assert cfg["model"].get("default", "") != "anthropic/claude-sonnet-4.6"


def test_cmd_chat_forwards_ignore_flags_in_process(monkeypatch):
    import fabric_cli.main as main_mod
    from fabric_cli._parser import build_top_level_parser

    parser, _subparsers, chat_parser = build_top_level_parser()
    chat_parser.set_defaults(func=main_mod.cmd_chat)
    args = parser.parse_args(["chat", "--ignore-user-config", "--ignore-rules"])
    captured: dict[str, object] = {}
    fake_cli = types.ModuleType("cli")
    fake_cli.main = lambda **kwargs: captured.update(kwargs)

    monkeypatch.setattr(main_mod, "_has_any_provider_configured", lambda: True)
    monkeypatch.setattr(main_mod, "_pin_kanban_board_context", lambda: None)
    monkeypatch.setattr(main_mod, "_sync_bundled_skills_for_startup", lambda: None)
    monkeypatch.setattr(main_mod, "_termux_should_prefetch_update_check", lambda: False)
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    main_mod.cmd_chat(args)

    assert captured["ignore_user_config"] is True
    assert captured["ignore_rules"] is True


def test_real_parser_registers_ignore_flags():
    from fabric_cli._parser import build_top_level_parser

    parser, _subparsers, chat_parser = build_top_level_parser()
    top_dests = {action.dest for action in parser._actions}
    chat_dests = {action.dest for action in chat_parser._actions}

    assert {"ignore_user_config", "ignore_rules"} <= top_dests
    assert {"ignore_user_config", "ignore_rules"} <= chat_dests
