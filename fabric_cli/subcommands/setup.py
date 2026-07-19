"""``fabric setup`` subcommand parser.

Extracted verbatim from ``fabric_cli/main.py:main()`` (god-file Phase 2).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

from typing import Callable

from fabric_cli.fabric_capabilities import fabric_model_provider_visible


def build_setup_parser(subparsers, *, cmd_setup: Callable) -> None:
    """Attach the ``setup`` subcommand to ``subparsers``."""
    # =========================================================================
    # setup command
    # =========================================================================
    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactive setup wizard",
        description="Configure Fabric with an interactive wizard. "
        "Run a specific section: fabric setup "
        "model|tts|terminal|gateway|tools|github|tailscale|agent",
    )
    setup_parser.add_argument(
        "section",
        nargs="?",
        choices=[
            "model",
            "tts",
            "terminal",
            "gateway",
            "tools",
            "github",
            "tailscale",
            "agent",
        ],
        default=None,
        help="Run a specific setup section instead of the full wizard",
    )
    setup_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Non-interactive mode (use defaults/env vars)",
    )
    setup_parser.add_argument(
        "--reset", action="store_true", help="Reset configuration to defaults"
    )
    setup_parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="(Default on existing installs.) Re-run the full wizard, "
        "showing current values as defaults. Kept for backwards "
        "compatibility — a bare 'fabric setup' now does this.",
    )
    setup_parser.add_argument(
        "--quick",
        action="store_true",
        help="On existing installs: only prompt for items that are missing "
        "or unset, instead of running the full reconfigure wizard.",
    )
    # The upstream Nous onboarding shortcut is opt-in in Fabric. Keep
    # the complete flow available for explicitly opted-in deployments, while
    # leaving both parsing and help clean for the customer default.
    if fabric_model_provider_visible("nous"):
        setup_parser.add_argument(
            "--portal",
            action="store_true",
            help="One-shot Nous Portal setup: log in via OAuth, pick a Nous "
            "model, set Nous as the inference provider, and opt into the Tool "
            "Gateway. Skips the rest of the wizard.",
        )
        setup_parser.add_argument(
            "--client-id",
            help=(
                "Registered Nous OAuth client ID (required with --portal for "
                "first-time login)"
            ),
        )
    # Allow scripted setup to suppress the post-setup dashboard offer.
    setup_parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Do not offer to start the Fabric dashboard after setup",
    )
    setup_parser.set_defaults(func=cmd_setup)
