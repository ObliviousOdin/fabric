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
from fabric_cli.subcommands.login import build_login_parser
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
    ("login", build_login_parser, "cmd_login", ["login"]),
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
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    handler = _h(name)
    builder(sub, **{kw: handler})
    ns = parser.parse_args(argv)
    assert ns.func is handler


def test_setup_help_does_not_advertise_or_parse_nous_portal(monkeypatch):
    """Fabric setup must not expose the upstream Nous onboarding shortcut."""
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
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
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_model_parser(sub, cmd_model=_h("model"))
    help_text = sub.choices["model"].format_help()

    assert "Nous" not in help_text
    assert "hermes-cli" not in help_text
    assert "--portal-url" not in help_text
    assert "--inference-url" not in help_text
    args = parser.parse_args(["model", "--no-browser", "--timeout", "9"])
    assert args.no_browser is True
    assert args.timeout == 9


def test_model_help_restores_nous_flags_under_legacy_opt_in(monkeypatch):
    monkeypatch.setenv("FABRIC_MODEL_PROVIDERS", "openai-api,nous")
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
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
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
    for forbidden in ("Nous", "Anthropic", "OpenRouter", "Hermes"):
        assert forbidden not in "\n".join((add_help, spotify_help, mcp_help))
    assert "Authenticate Fabric with Spotify" in auth.format_help()
    assert "curated MCPs" in mcp_help
    with pytest.raises(SystemExit):
        parser.parse_args(["auth", "add", "nous", "--portal-url", "https://x"])


def test_auth_help_restores_nous_flags_under_legacy_opt_in(monkeypatch):
    monkeypatch.setenv("FABRIC_MODEL_PROVIDERS", "openai-api,nous")
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_auth_parser(sub, cmd_auth=_h("auth"))

    args = parser.parse_args(
        ["auth", "add", "nous", "--portal-url", "https://portal.example"]
    )
    assert args.portal_url == "https://portal.example"


@pytest.mark.parametrize(
    "env_name,env_value",
    [
        ("FABRIC_MODEL_PROVIDERS", "nous"),
        ("FABRIC_CAPABILITY_CATALOG", "0"),
    ],
)
def test_setup_portal_is_restored_by_explicit_legacy_opt_in(
    monkeypatch, env_name, env_value
):
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.setenv(env_name, env_value)

    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command")
    build_setup_parser(sub, cmd_setup=_h("setup"))

    args = parser.parse_args(["setup", "--portal"])
    assert args.portal is True
    assert "Nous Portal" in sub.choices["setup"].format_help()


def test_dashboard_builder_two_handlers():
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    dash, reg = _h("dashboard"), _h("dashboard_register")
    build_dashboard_parser(sub, cmd_dashboard=dash, cmd_dashboard_register=reg)
    # bare dashboard -> launch handler
    assert parser.parse_args(["dashboard"]).func is dash
    # dashboard register -> register handler
    assert parser.parse_args(["dashboard", "register"]).func is reg


def test_dashboard_register_is_hidden_without_legacy_catalog_opt_in(monkeypatch):
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
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
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.setenv("FABRIC_MODEL_PROVIDERS", "nous")
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


# ── deprecated `fabric login` fails gracefully, not with argparse error ────
#
# `fabric login` is a removed command; its handler (`login_command` in
# `fabric_cli/auth.py`) prints a deprecation notice pointing at `fabric auth` /
# `fabric model` and exits 0.  Two behavior contracts guard the UX:
#   1. ANY `--provider <value>` (including ones the user actually wants, like
#      `anthropic`) must parse and reach the handler — never crash in argparse
#      with `invalid choice` before the friendly redirect is printed (#24756).
#   2. The subcommand must not advertise itself in the parser help row.


def _login_parser():
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    build_login_parser(sub, cmd_login=_h("login"))
    return parser


@pytest.mark.parametrize("provider", ["anthropic", "nous", "openai-codex", "totally-made-up"])
def test_login_accepts_any_provider_value(provider):
    """Deprecated `login` must route every `--provider` to the handler.

    A restrictive `choices=` list (the pre-fix behavior) rejected providers
    like `anthropic` with an argparse error *before* the deprecation message
    could run, so the user just saw `invalid choice: 'anthropic'` and assumed
    the feature was broken rather than relocated.
    """
    ns = _login_parser().parse_args(["login", "--provider", provider])
    assert ns.func.__name__ == "cmd_login"
    assert ns.provider == provider


def test_login_subparser_help_is_suppressed():
    """The deprecated `login` row must not appear in `fabric --help`.

    Must hold without leaking argparse's literal `==SUPPRESS==` placeholder,
    which `help=argparse.SUPPRESS` emits for a top-level subparser on 3.12+.
    The fix omits the `help=` kwarg entirely instead.
    """
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    build_login_parser(sub, cmd_login=_h("login"))
    help_text = parser.format_help()
    # The misleading old help string must be gone from the top-level usage.
    assert "Authenticate with an inference provider" not in help_text
    # And no leaked SUPPRESS placeholder row.
    assert "==SUPPRESS==" not in help_text
