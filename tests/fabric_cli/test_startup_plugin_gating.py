"""Guards for CLI startup performance regression.

``fabric_cli.main`` skips eager plugin discovery at argparse-setup time
when the invocation is clearly targeting a known built-in subcommand.
This saves 500-650ms on ``fabric --help``, ``fabric version``,
``fabric logs``, etc., by not importing ``google.cloud.pubsub_v1``,
``aiohttp``, ``grpc``, and friends.

Two invariants:

1. ``_BUILTIN_SUBCOMMANDS`` must contain every subcommand that is actually
   registered by ``main()``.  If an entry is missing, plugin discovery
   runs unnecessarily for that command (correctness-safe, just slow).
   If an entry is PRESENT but the subcommand doesn't exist, a plugin
   could shadow the name — also bad.

2. ``_plugin_cli_discovery_needed()`` returns the right answer for the
   flag/positional parsing cases it's meant to handle.
"""

from __future__ import annotations

import io
import re
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest

from fabric_cli.main import (
    _BUILTIN_SUBCOMMANDS,
    _first_positional_argv,
    _plugin_cli_discovery_needed,
)


# ── helper: grab the live set of top-level subcommands from argparse ───────


def _top_level_help_text() -> str:
    """Run ``fabric --help`` in-process and return its rendered output.

    We patch ``_plugin_cli_discovery_needed`` to always return False so
    plugin-registered commands aren't included — we're validating the
    built-in-only set.
    """
    from fabric_cli import main as _main

    argv_backup = sys.argv[:]
    sys.argv = ["hermes", "--help"]
    buf = io.StringIO()
    try:
        with patch.object(_main, "_plugin_cli_discovery_needed", return_value=False):
            with redirect_stdout(buf):
                with pytest.raises(SystemExit):
                    _main.main()
    finally:
        sys.argv = argv_backup

    return buf.getvalue()


def _live_subcommand_names() -> set[str]:
    """Parse the built-in top-level subcommand names from ``fabric --help``."""

    text = _top_level_help_text()
    # argparse prints "{chat,model,...}" somewhere in the help output
    m = re.search(r"\{([a-zA-Z0-9_,\-]+)\}", text)
    assert m, f"Could not find subcommand group in --help output:\n{text[:500]}"
    return set(m.group(1).split(","))


def test_default_fabric_help_has_no_upstream_branding_or_portal(monkeypatch):
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)

    text = _top_level_help_text()

    assert "Nous" not in text
    assert "nousresearch" not in text.lower()
    assert "Hermes" not in text
    assert "portal" not in text.lower()


@pytest.mark.parametrize(
    "env_name,env_value",
    [
        ("FABRIC_MODEL_PROVIDERS", "nous"),
        ("FABRIC_CAPABILITY_CATALOG", "0"),
    ],
)
def test_explicit_legacy_opt_in_registers_portal(
    monkeypatch, env_name, env_value
):
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.setenv(env_name, env_value)

    text = _top_level_help_text()

    assert re.search(r"^\s+portal\s+Set up Nous Portal", text, re.MULTILINE)


def test_default_portal_command_is_unknown(monkeypatch, capsys):
    from fabric_cli import main as _main

    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.setattr(sys, "argv", ["fabric", "portal"])

    with patch.object(_main, "_plugin_cli_discovery_needed", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            _main.main()

    assert exc_info.value.code == 2
    assert "invalid choice: 'portal'" in capsys.readouterr().err


# ── _first_positional_argv ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["hermes"], None),
        (["hermes", "--help"], None),
        (["hermes", "-h"], None),
        (["hermes", "--version"], None),
        (["hermes", "-w"], None),
        # -p / --profile is stripped from sys.argv by
        # _apply_profile_override() at import time, so it never reaches
        # _first_positional_argv. We test with just -w / --tui here.
        (["hermes", "-w", "--tui"], None),
        (["hermes", "version"], "version"),
        (["hermes", "--tui", "chat"], "chat"),
        (["hermes", "-w", "logs"], "logs"),
        (["hermes", "chat", "hello world"], "chat"),
        (["hermes", "gateway", "run"], "gateway"),
        # Top-level value-taking flags: the value should be skipped.
        (["hermes", "-m", "gpt5", "chat"], "chat"),
        (["hermes", "--model", "gpt5", "chat", "hi"], "chat"),
        (["hermes", "-m", "gpt5", "--provider", "openai", "chat"], "chat"),
        (["hermes", "-z", "hello world"], None),
        (["hermes", "-z", "hello", "chat"], "chat"),
        (["hermes", "--model=gpt5", "chat"], "chat"),     # inline form
        (["hermes", "--", "chat"], "chat"),               # -- terminator
        (["hermes", "-w", "--"], None),
        # Unknown positional after skipped flags → plugin-cmd candidate.
        (["hermes", "some-plugin-cmd"], "some-plugin-cmd"),
        (["hermes", "-m", "gpt5", "some-plugin-cmd"], "some-plugin-cmd"),
    ],
)
def test_first_positional_argv(argv, expected):
    with patch.object(sys, "argv", argv):
        assert _first_positional_argv() == expected


# ── _plugin_cli_discovery_needed ───────────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["hermes"],                          # bare → chat
        ["hermes", "--help"],                # top-level help
        ["hermes", "-h"],
        ["hermes", "version"],               # known built-in
        ["hermes", "logs"],
        ["hermes", "gateway", "run"],
        ["hermes", "--tui"],
        ["hermes", "-w", "--tui"],
        ["hermes", "chat", "hi"],
        ["hermes", "help"],                  # accepted built-in-ish
        ["hermes", "-m", "gpt5", "chat"],    # flag-value-skipping
    ],
)
def test_discovery_skipped_for_builtins(argv):
    with patch.object(sys, "argv", argv):
        assert _plugin_cli_discovery_needed() is False


@pytest.mark.parametrize(
    "argv",
    [
        ["hermes", "meet", "join"],          # potential google_meet plugin
        ["hermes", "honcho", "status"],      # potential memory plugin
        ["hermes", "unknown-subcmd"],
    ],
)
def test_discovery_runs_for_unknown_positional(argv):
    with patch.object(sys, "argv", argv):
        assert _plugin_cli_discovery_needed() is True


# ── _BUILTIN_SUBCOMMANDS ↔ argparse registration parity ────────────────────


def test_builtin_set_covers_every_registered_subcommand(monkeypatch):
    """Every subcommand registered in main() must appear in the set.

    Missing entries cause a slow-path regression (correctness stays
    fine — discovery just runs unnecessarily).
    """
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    live = _live_subcommand_names()
    # "help" is synthetic — an argparse-implicit convenience we include
    # in the set so ``fabric help <cmd>`` skips discovery; it won't show
    # up as a subparser in the --help output.
    declared = _BUILTIN_SUBCOMMANDS - {"help"}
    missing_from_declaration = live - declared
    assert not missing_from_declaration, (
        f"_BUILTIN_SUBCOMMANDS is missing these live subcommands: "
        f"{sorted(missing_from_declaration)}. Add them to "
        f"fabric_cli/main.py::_BUILTIN_SUBCOMMANDS so plugin discovery "
        f"can be skipped when the user targets them."
    )


def test_builtin_set_has_no_phantom_entries(monkeypatch):
    """No entry in the set should refer to a subcommand that no longer exists.

    A phantom entry means plugin discovery gets incorrectly skipped for
    a name that — if a plugin actually registered it — would fail to
    parse. Keeps the set honest.
    """
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    live = _live_subcommand_names()
    # ``portal`` is a compatibility-gated built-in and is intentionally absent
    # from the default public parser unless that legacy provider is enabled.
    allowed_synthetic = {"help", "portal"}
    phantom = _BUILTIN_SUBCOMMANDS - live - allowed_synthetic
    assert not phantom, (
        f"_BUILTIN_SUBCOMMANDS has entries that are not registered as "
        f"top-level subparsers: {sorted(phantom)}"
    )
