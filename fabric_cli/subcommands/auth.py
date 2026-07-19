"""``fabric auth`` subcommand parser.

Extracted verbatim from ``fabric_cli/main.py:main()`` (god-file Phase 2).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

import argparse
from typing import Callable

from fabric_cli.fabric_capabilities import fabric_model_provider_visible


_ACCOUNT_PROVIDERS = ("openai-codex", "xai-oauth")


def _nonnegative_revision(value: str) -> int:
    """Argparse type for optimistic provider-account revisions."""

    revision = int(value)
    if revision < 0:
        raise argparse.ArgumentTypeError("revision must be non-negative")
    return revision


def _add_account_output_options(parser, *, revision: bool = False) -> None:
    if revision:
        parser.add_argument(
            "--expected-revision",
            type=_nonnegative_revision,
            help=(
                "Require this provider revision. Required for JSON mutations; "
                "interactive output may safely retry once when omitted."
            ),
        )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the shared provider-account JSON response",
    )


def build_auth_parser(subparsers, *, cmd_auth: Callable) -> None:
    """Attach the ``auth`` subcommand to ``subparsers``."""
    auth_parser = subparsers.add_parser(
        "auth",
        help="Manage pooled provider credentials",
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_action")
    auth_add = auth_subparsers.add_parser("add", help="Add a pooled credential")
    auth_add.add_argument(
        "provider",
        help="Provider id (for example: openai-codex, openai-api, xai-oauth, xai)",
    )
    auth_add.add_argument(
        "--type",
        dest="auth_type",
        choices=["oauth", "api-key", "api_key"],
        help="Credential type to add",
    )
    auth_add.add_argument("--label", help="Optional display label")
    auth_add.add_argument(
        "--api-key", help="API key value (otherwise prompted securely)"
    )
    if fabric_model_provider_visible("nous"):
        auth_add.add_argument("--portal-url", help="Nous portal base URL")
        auth_add.add_argument("--inference-url", help="Nous inference base URL")
    auth_add.add_argument("--client-id", help="OAuth client id")
    auth_add.add_argument("--scope", help="OAuth scope override")
    auth_add.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open a browser for OAuth login",
    )
    auth_add.add_argument(
        "--timeout", type=float, help="OAuth/network timeout in seconds"
    )
    auth_add.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification for OAuth login",
    )
    auth_add.add_argument("--ca-bundle", help="Custom CA bundle for OAuth login")
    auth_list = auth_subparsers.add_parser("list", help="List pooled credentials")
    auth_list.add_argument("provider", nargs="?", help="Optional provider filter")
    auth_remove = auth_subparsers.add_parser(
        "remove", help="Remove a pooled credential by index, id, or label"
    )
    auth_remove.add_argument("provider", help="Provider id")
    auth_remove.add_argument(
        "target", help="Credential index, entry id, or exact label"
    )
    auth_reset = auth_subparsers.add_parser(
        "reset", help="Clear exhaustion status for all credentials for a provider"
    )
    auth_reset.add_argument("provider", help="Provider id")
    auth_status = auth_subparsers.add_parser(
        "status", help="Show auth status for a provider"
    )
    auth_status.add_argument("provider", help="Provider id")
    auth_logout = auth_subparsers.add_parser(
        "logout", help="Log out a provider and clear stored auth state"
    )
    auth_logout.add_argument("provider", help="Provider id")

    auth_account = auth_subparsers.add_parser(
        "account",
        help="Manage ChatGPT or Grok account ownership",
        description=(
            "Manage profile-scoped personal ownership or a durable "
            "Fabric-managed access request. OAuth codes are never included in "
            "managed requests or email handoffs."
        ),
    )
    auth_account.add_argument("provider", choices=_ACCOUNT_PROVIDERS)
    account_actions = auth_account.add_subparsers(dest="account_action", required=True)

    account_status = account_actions.add_parser(
        "status", help="Show the profile-scoped ownership/request snapshot"
    )
    _add_account_output_options(account_status)

    account_personal = account_actions.add_parser(
        "personal", help="Use a personal ChatGPT or Grok subscription"
    )
    _add_account_output_options(account_personal, revision=True)
    account_personal.add_argument("--label", help="Optional credential label")
    account_personal.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the provider verification page",
    )
    account_personal.add_argument(
        "--timeout", type=float, help="OAuth/network timeout in seconds"
    )

    account_request = account_actions.add_parser(
        "request", help="Create or reuse a Fabric-managed access request"
    )
    account_request.add_argument(
        "--device-label",
        required=True,
        help="Short label for this Fabric device (1-120 UTF-8 bytes)",
    )
    _add_account_output_options(account_request, revision=True)

    for action, help_text in (
        (
            "handoff-attempted",
            "Record an attempted local email handoff (delivery remains unverified)",
        ),
        ("cancel", "Cancel the active managed-access request"),
        (
            "acknowledge",
            "Record a trusted local-operator acknowledgement",
        ),
        ("reject", "Record a trusted local-operator rejection"),
    ):
        action_parser = account_actions.add_parser(action, help=help_text)
        action_parser.add_argument(
            "--request-id",
            help=(
                "Exact active request reference. Required for JSON mutations; "
                "human output may use the current active request when omitted."
            ),
        )
        _add_account_output_options(action_parser, revision=True)

    auth_accounts = auth_subparsers.add_parser(
        "accounts", help="Manage the profile-scoped provider-account store"
    )
    account_store_actions = auth_accounts.add_subparsers(
        dest="store_action", required=True
    )
    accounts_repair = account_store_actions.add_parser(
        "repair",
        help="Repair the entire provider-account store after confirmation",
        description=(
            "Reset every provider-account record only after preserving a private "
            "backup of an existing safe state file. Newer schemas, redirected "
            "paths, hard links, and unsafe permissions are never overwritten."
        ),
    )
    accounts_repair.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Confirm resetting every provider-account record",
    )
    accounts_repair.add_argument(
        "--json",
        action="store_true",
        help="Emit the stable provider-account JSON result or error response",
    )

    auth_spotify = auth_subparsers.add_parser(
        "spotify", help="Authenticate Fabric with Spotify via PKCE"
    )
    auth_spotify.add_argument(
        "spotify_action",
        nargs="?",
        choices=["login", "status", "logout"],
        default="login",
    )
    auth_spotify.add_argument("--client-id", help="Spotify app client_id")
    auth_spotify.add_argument(
        "--redirect-uri",
        help="Allow-listed localhost redirect URI for your Spotify app",
    )
    auth_spotify.add_argument("--scope", help="Override requested Spotify scopes")
    auth_spotify.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not attempt to open the browser automatically",
    )
    auth_spotify.add_argument(
        "--timeout", type=float, help="Callback/token exchange timeout in seconds"
    )
    # Allow scripted auth to suppress the post-auth dashboard offer.
    auth_parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Do not offer to start the Fabric dashboard after auth",
    )
    auth_parser.set_defaults(func=cmd_auth)
