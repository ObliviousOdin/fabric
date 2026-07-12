"""``hermes logout`` subcommand parser.

Extracted verbatim from ``fabric_cli/main.py:main()`` (god-file Phase 2).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

from typing import Callable

from fabric_cli.fabric_capabilities import fabric_model_provider_visible


def build_logout_parser(subparsers, *, cmd_logout: Callable) -> None:
    """Attach the ``logout`` subcommand to ``subparsers``."""
    # =========================================================================
    # logout command
    # =========================================================================
    logout_parser = subparsers.add_parser(
        "logout",
        help="Clear authentication for an inference provider",
        description="Remove stored credentials and reset provider config",
    )
    providers = ["openai-codex", "xai-oauth", "spotify"]
    if fabric_model_provider_visible("nous"):
        providers.insert(0, "nous")
    logout_parser.add_argument(
        "--provider",
        choices=providers,
        default=None,
        help="Provider to log out from (default: active provider)",
    )
    logout_parser.set_defaults(func=cmd_logout)
