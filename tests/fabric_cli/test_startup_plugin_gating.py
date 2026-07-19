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
    sys.argv = ["fabric", "--help"]
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


def test_default_help_uses_curated_model_provider_catalog(monkeypatch):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )

    text = _top_level_help_text()

    assert "Nous" not in text
    assert "nousresearch" not in text.lower()
    assert "Fabric" in text
    assert "portal" not in text.lower()


@pytest.mark.parametrize(
    "capabilities",
    [
        {"model_providers": ["nous"]},
        {"enabled": False},
    ],
)
def test_model_provider_catalog_controls_portal_registration(
    monkeypatch, capabilities
):
    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: capabilities,
    )

    text = _top_level_help_text()

    assert re.search(r"^\s+portal\s+Set up Nous Portal", text, re.MULTILINE)


def test_portal_command_is_absent_from_default_catalog(monkeypatch, capsys):
    from fabric_cli import main as _main

    monkeypatch.setattr(
        "fabric_cli.fabric_capabilities._load_capabilities_config",
        lambda: {},
    )
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
        (["fabric"], None),
        (["fabric", "--help"], None),
        (["fabric", "-h"], None),
        (["fabric", "--version"], None),
        (["fabric", "-w"], None),
        # -p / --profile is stripped from sys.argv by
        # _apply_profile_override() at import time, so it never reaches
        # _first_positional_argv. We test with just -w / --tui here.
        (["fabric", "-w", "--tui"], None),
        (["fabric", "version"], "version"),
        (["fabric", "--tui", "chat"], "chat"),
        (["fabric", "-w", "logs"], "logs"),
        (["fabric", "chat", "hello world"], "chat"),
        (["fabric", "gateway", "run"], "gateway"),
        # Top-level value-taking flags: the value should be skipped.
        (["fabric", "-m", "gpt5", "chat"], "chat"),
        (["fabric", "--model", "gpt5", "chat", "hi"], "chat"),
        (["fabric", "-m", "gpt5", "--provider", "openai", "chat"], "chat"),
        (["fabric", "-z", "hello world"], None),
        (["fabric", "-z", "hello", "chat"], "chat"),
        (["fabric", "--model=gpt5", "chat"], "chat"),     # inline form
        (["fabric", "--", "chat"], "chat"),               # -- terminator
        (["fabric", "-w", "--"], None),
        # Unknown positional after skipped flags → plugin-cmd candidate.
        (["fabric", "some-plugin-cmd"], "some-plugin-cmd"),
        (["fabric", "-m", "gpt5", "some-plugin-cmd"], "some-plugin-cmd"),
    ],
)
def test_first_positional_argv(argv, expected):
    with patch.object(sys, "argv", argv):
        assert _first_positional_argv() == expected


# ── _plugin_cli_discovery_needed ───────────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["fabric"],                          # bare → chat
        ["fabric", "--help"],                # top-level help
        ["fabric", "-h"],
        ["fabric", "version"],               # known built-in
        ["fabric", "logs"],
        ["fabric", "gateway", "run"],
        ["fabric", "--tui"],
        ["fabric", "-w", "--tui"],
        ["fabric", "chat", "hi"],
        ["fabric", "help"],                  # accepted built-in-ish
        ["fabric", "-m", "gpt5", "chat"],    # flag-value-skipping
    ],
)
def test_discovery_skipped_for_builtins(argv):
    with patch.object(sys, "argv", argv):
        assert _plugin_cli_discovery_needed() is False


@pytest.mark.parametrize(
    "argv",
    [
        ["fabric", "meet", "join"],          # potential google_meet plugin
        ["fabric", "honcho", "status"],      # potential memory plugin
        ["fabric", "unknown-subcmd"],
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
    live = _live_subcommand_names()
    # ``portal`` is catalog-gated and intentionally absent from the default
    # public parser unless its provider is included.
    allowed_synthetic = {"help", "portal"}
    phantom = _BUILTIN_SUBCOMMANDS - live - allowed_synthetic
    assert not phantom, (
        f"_BUILTIN_SUBCOMMANDS has entries that are not registered as "
        f"top-level subparsers: {sorted(phantom)}"
    )
