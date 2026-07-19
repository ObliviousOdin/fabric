"""Smoke tests for the batch-extracted subcommand parser builders.

Each ``build_<group>_parser`` should attach its subcommand to a subparsers
group and wire ``func`` to the injected handler. These are intentionally
light — the byte-identical ``--help`` verification done at extraction time is
the real behavioral guarantee; this just guards against a module failing to
import or a builder raising.
"""

from __future__ import annotations

import argparse

import pytest

from fabric_cli.subcommands.auth import build_auth_parser
from fabric_cli.subcommands.backup import build_backup_parser
from fabric_cli.subcommands.config import build_config_parser
from fabric_cli.subcommands.dashboard import build_dashboard_parser
from fabric_cli.subcommands.debug import build_debug_parser
from fabric_cli.subcommands.doctor import build_doctor_parser
from fabric_cli.subcommands.dump import build_dump_parser
from fabric_cli.subcommands.gui import build_gui_parser
from fabric_cli.subcommands.hooks import build_hooks_parser
from fabric_cli.subcommands.import_cmd import build_import_cmd_parser
from fabric_cli.subcommands.logout import build_logout_parser
from fabric_cli.subcommands.logs import build_logs_parser
from fabric_cli.subcommands.model import build_model_parser
from fabric_cli.subcommands.mcp import build_mcp_parser
from fabric_cli.subcommands.postinstall import build_postinstall_parser
from fabric_cli.subcommands.prompt_size import build_prompt_size_parser
from fabric_cli.subcommands.security import build_security_parser
from fabric_cli.subcommands.setup import build_setup_parser
from fabric_cli.subcommands.slack import build_slack_parser
from fabric_cli.subcommands.status import build_status_parser
from fabric_cli.subcommands.uninstall import build_uninstall_parser
from fabric_cli.subcommands.update import build_update_parser
from fabric_cli.subcommands.version import build_version_parser
from fabric_cli.subcommands.webhook import build_webhook_parser
from fabric_cli.subcommands.whatsapp import build_whatsapp_parser
from fabric_cli._parser import build_top_level_parser


def _h(name):
    def handler(args):  # pragma: no cover - identity only
        return name
    handler.__name__ = f"cmd_{name}"
    return handler


# (subcommand_name, builder, handler_kwargs, sample_argv)
SINGLE_HANDLER_CASES = [
    ("model", build_model_parser, "cmd_model", ["model"]),
    ("setup", build_setup_parser, "cmd_setup", ["setup"]),
    ("postinstall", build_postinstall_parser, "cmd_postinstall", ["postinstall"]),
    ("whatsapp", build_whatsapp_parser, "cmd_whatsapp", ["whatsapp"]),
    ("slack", build_slack_parser, "cmd_slack", ["slack"]),
    ("logout", build_logout_parser, "cmd_logout", ["logout"]),
    ("auth", build_auth_parser, "cmd_auth", ["auth"]),
    ("status", build_status_parser, "cmd_status", ["status"]),
    ("webhook", build_webhook_parser, "cmd_webhook", ["webhook"]),
    ("hooks", build_hooks_parser, "cmd_hooks", ["hooks"]),
    ("doctor", build_doctor_parser, "cmd_doctor", ["doctor"]),
    ("security", build_security_parser, "cmd_security", ["security"]),
    ("dump", build_dump_parser, "cmd_dump", ["dump"]),
    ("debug", build_debug_parser, "cmd_debug", ["debug"]),
    ("backup", build_backup_parser, "cmd_backup", ["backup"]),
    ("import", build_import_cmd_parser, "cmd_import", ["import", "/tmp/x.zip"]),
    ("config", build_config_parser, "cmd_config", ["config"]),
    ("version", build_version_parser, "cmd_version", ["version"]),
    ("update", build_update_parser, "cmd_update", ["update"]),
    ("uninstall", build_uninstall_parser, "cmd_uninstall", ["uninstall"]),
    ("gui", build_gui_parser, "cmd_gui", ["gui"]),
    ("logs", build_logs_parser, "cmd_logs", ["logs"]),
    ("prompt-size", build_prompt_size_parser, "cmd_prompt_size", ["prompt-size"]),
]


@pytest.mark.parametrize("name,builder,kw,argv", SINGLE_HANDLER_CASES, ids=[c[0] for c in SINGLE_HANDLER_CASES])
def test_single_handler_builders(name, builder, kw, argv):
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    handler = _h(name)
    builder(sub, **{kw: handler})
    ns = parser.parse_args(argv)
    assert ns.func is handler


def test_setup_help_does_not_advertise_or_parse_nous_portal(monkeypatch):
    """Fabric setup must not expose the upstream Nous onboarding shortcut."""
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_setup_parser(sub, cmd_setup=_h("setup"))

    subparsers_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    setup_parser = subparsers_action.choices["setup"]
    help_text = setup_parser.format_help()

    assert "--portal" not in help_text
    assert "Nous Portal" not in help_text

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["setup", "--portal"])
    assert exc_info.value.code == 2


def test_chat_help_uses_fabric_and_curated_provider_examples():
    _parser, _subparsers, chat_parser = build_top_level_parser()
    help_text = chat_parser.format_help()

    assert "Fabric itself" in help_text
    assert "GPT or Grok" in help_text
    assert "anthropic/" not in help_text.lower()


def test_model_help_hides_nous_flags_but_keeps_xai_oauth_controls(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_model_parser(sub, cmd_model=_h("model"))
    help_text = sub.choices["model"].format_help()

    assert "Nous" not in help_text
    assert "--portal-url" not in help_text
    assert "--inference-url" not in help_text
    args = parser.parse_args(["model", "--no-browser", "--timeout", "9"])
    assert args.no_browser is True
    assert args.timeout == 9


def test_model_help_restores_nous_flags_under_explicit_opt_in(monkeypatch):
    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"model_providers": "openai-api,nous".split(",")})
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_model_parser(sub, cmd_model=_h("model"))
    help_text = sub.choices["model"].format_help()

    assert "Nous login" in help_text
    args = parser.parse_args(
        ["model", "--portal-url", "https://portal.example", "--insecure"]
    )
    assert args.portal_url == "https://portal.example"
    assert args.insecure is True


def test_auth_and_mcp_help_are_customer_clean_by_default(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_auth_parser(sub, cmd_auth=_h("auth"))
    build_mcp_parser(sub, cmd_mcp=_h("mcp"))

    auth = sub.choices["auth"]
    auth_nested = next(
        action
        for action in auth._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    add_help = auth_nested.choices["add"].format_help()
    spotify_help = auth_nested.choices["spotify"].format_help()
    mcp_help = sub.choices["mcp"].format_help()

    assert "openai-codex" in add_help
    for forbidden in ("Nous", "Anthropic", "OpenRouter"):
        assert forbidden not in "\n".join((add_help, spotify_help, mcp_help))
    assert "Authenticate Fabric with Spotify" in auth.format_help()
    assert "curated MCPs" in mcp_help
    with pytest.raises(SystemExit):
        parser.parse_args(["auth", "add", "nous", "--portal-url", "https://x"])


def test_auth_help_restores_nous_flags_under_explicit_opt_in(monkeypatch):
    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"model_providers": "openai-api,nous".split(",")})
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_auth_parser(sub, cmd_auth=_h("auth"))

    args = parser.parse_args(
        ["auth", "add", "nous", "--portal-url", "https://portal.example"]
    )
    assert args.portal_url == "https://portal.example"


@pytest.mark.parametrize(
    "capabilities",
    [
        {"model_providers": ["nous"]},
        {"enabled": False},
    ],
)
def test_setup_portal_is_restored_by_explicit_nous_opt_in(
    monkeypatch, capabilities
):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: capabilities,
    )

    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_setup_parser(sub, cmd_setup=_h("setup"))

    args = parser.parse_args([
        "setup",
        "--portal",
        "--client-id",
        "registered-nous-client",
    ])
    assert args.portal is True
    assert args.client_id == "registered-nous-client"
    assert "Nous Portal" in sub.choices["setup"].format_help()


def test_portal_parser_accepts_client_id_before_or_after_login():
    from fabric_cli.portal_cli import add_parser

    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    add_parser(sub)

    direct = parser.parse_args([
        "portal",
        "--client-id",
        "registered-nous-client",
    ])
    before_login = parser.parse_args([
        "portal",
        "--client-id",
        "registered-nous-client",
        "login",
    ])
    after_login = parser.parse_args([
        "portal",
        "login",
        "--client-id",
        "registered-nous-client",
    ])

    assert direct.client_id == "registered-nous-client"
    assert direct.portal_command is None
    assert before_login.client_id == "registered-nous-client"
    assert before_login.portal_command == "login"
    assert after_login.client_id == "registered-nous-client"
    assert after_login.portal_command == "login"


def test_dashboard_builder_two_handlers():
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    dash, reg = _h("dashboard"), _h("dashboard_register")
    build_dashboard_parser(sub, cmd_dashboard=dash, cmd_dashboard_register=reg)
    # bare dashboard -> launch handler
    assert parser.parse_args(["dashboard"]).func is dash
    # dashboard register -> register handler
    assert parser.parse_args(["dashboard", "register"]).func is reg


def test_dashboard_register_is_hidden_without_catalog_opt_in(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_dashboard_parser(
        sub,
        cmd_dashboard=_h("dashboard"),
        cmd_dashboard_register=_h("dashboard_register"),
    )

    help_text = sub.choices["dashboard"].format_help()
    assert "register" not in help_text
    assert "Nous" not in help_text
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["dashboard", "register"])
    assert exc_info.value.code == 2


def test_dashboard_register_is_restored_by_explicit_legacy_opt_in(monkeypatch):
    monkeypatch.setattr("fabric_cli.fabric_capabilities._load_capabilities_config", lambda: {"model_providers": "nous".split(",")})
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    register = _h("dashboard_register")
    build_dashboard_parser(
        sub,
        cmd_dashboard=_h("dashboard"),
        cmd_dashboard_register=register,
    )

    args = parser.parse_args(["dashboard", "register"])
    assert args.func is register
    dashboard = sub.choices["dashboard"]
    nested = next(
        action
        for action in dashboard._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert "Nous Portal" in nested.choices["register"].format_help()
