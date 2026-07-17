"""``fabric login`` subcommand parser.

Extracted verbatim from ``fabric_cli/main.py:main()`` (god-file Phase 2).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

import argparse
from typing import Callable

from fabric_cli.fabric_capabilities import fabric_model_provider_visible


def build_login_parser(subparsers, *, cmd_login: Callable) -> None:
    """Attach the deprecated ``login`` subcommand to ``subparsers``.

    ``fabric login`` was removed in favor of ``fabric auth`` / ``fabric model``
    (the runtime handler in ``fabric_cli/auth.py::login_command`` just prints a
    deprecation message and exits).  The subparser is kept registered so that
    old scripts/aliases invoking ``fabric login [--flags]`` still receive the
    actionable deprecation message rather than an argparse ``invalid choice:
    'login'`` error — but:

    - The subparser is registered WITHOUT a ``help=`` kwarg so the row is
      omitted from ``fabric --help`` (argparse only lists subcommands that
      have a help string).  This hides a command that no longer works (#24756)
      without the ``help=argparse.SUPPRESS`` ``==SUPPRESS==`` leak that
      argparse emits for a top-level subparser on Python 3.12+.
    - ``--provider`` accepts ANY value (no ``choices=``) so that, e.g.,
      ``fabric login --provider anthropic`` reaches the deprecation handler and
      gets pointed at ``fabric model`` instead of crashing in argparse with
      ``invalid choice: 'anthropic'`` before the handler can run.
    """
    login_parser = subparsers.add_parser(
        "login",
        description=(
            "Deprecated. Use `fabric auth` to manage credentials, "
            "`fabric model` to select a provider, or `fabric setup` for full setup."
        ),
    )
    # No ``choices=`` on purpose — the handler is a deprecation notice that
    # ignores the value, and a restrictive list would reject providers the user
    # legitimately wants (e.g. ``anthropic``) with an argparse error before the
    # friendly redirect message is ever printed.
    login_parser.add_argument(
        "--provider",
        default=None,
        help="(deprecated) Provider name; ignored — see `fabric model`",
    )
    legacy_help = fabric_model_provider_visible("nous")
    login_parser.add_argument(
        "--portal-url",
        help=(
            "Portal base URL (default: production portal)"
            if legacy_help
            else argparse.SUPPRESS
        ),
    )
    login_parser.add_argument(
        "--inference-url",
        help=(
            "Inference API base URL (default: production inference API)"
            if legacy_help
            else argparse.SUPPRESS
        ),
    )
    login_parser.add_argument(
        "--client-id",
        default=None,
        help=(
            "OAuth client id to use (default: hermes-cli)"
            if legacy_help
            else argparse.SUPPRESS
        ),
    )
    login_parser.add_argument(
        "--scope",
        default=None,
        help="OAuth scope to request" if legacy_help else argparse.SUPPRESS,
    )
    login_parser.add_argument(
        "--no-browser",
        action="store_true",
        help=(
            "Do not attempt to open the browser automatically"
            if legacy_help
            else argparse.SUPPRESS
        ),
    )
    login_parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help=(
            "HTTP request timeout in seconds (default: 15)"
            if legacy_help
            else argparse.SUPPRESS
        ),
    )
    login_parser.add_argument(
        "--ca-bundle",
        help=(
            "Path to CA bundle PEM file for TLS verification"
            if legacy_help
            else argparse.SUPPRESS
        ),
    )
    login_parser.add_argument(
        "--insecure",
        action="store_true",
        help=(
            "Disable TLS verification (testing only)"
            if legacy_help
            else argparse.SUPPRESS
        ),
    )
    login_parser.set_defaults(func=cmd_login)
