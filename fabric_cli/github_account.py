"""GitHub account utilities for Fabric.

Powers ``fabric setup github``: sign in with the OAuth device code flow (or a
personal access token), then optionally star the Fabric repository. Issue
filing (feature requests / bug reports) is handled by the
``skills/github/fabric-contribute`` skill, which uses ``gh``/``curl`` directly.

Tokens minted here are stored as ``GITHUB_TOKEN`` in the active profile's
``.env`` via ``fabric_cli.config.save_env_value`` — one of the places the
GitHub skills (``skills/github/github-auth/scripts/gh-env.sh``) resolve
credentials from, so signing in during setup makes them work out of the box.

Token resolution order (this module):
  1. GH_TOKEN / GITHUB_TOKEN env vars (matching GitHub CLI precedence)
  2. GITHUB_TOKEN in the Fabric profile's ``.env``
  3. ``gh auth token`` CLI fallback
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The canonical upstream repository — starred / filed against by default.
FABRIC_REPO_OWNER = "ObliviousOdin"
FABRIC_REPO_NAME = "fabric"
FABRIC_REPO_SLUG = f"{FABRIC_REPO_OWNER}/{FABRIC_REPO_NAME}"
FABRIC_REPO_URL = f"https://github.com/{FABRIC_REPO_SLUG}"

# OAuth device code flow client ID — the GitHub CLI's public OAuth App.
# Unlike the VS Code GitHub App used by copilot_auth (which can only mint
# unscoped ghu_* tokens), an OAuth App can request classic scopes, and we
# need ``public_repo`` to star repositories on behalf of the user. This is
# the same App ID `gh auth login` uses for its own device flow, so the
# resulting gho_* token behaves exactly like a gh login token. Trade-off:
# GitHub's consent page and the user's authorized-apps list attribute the
# grant to "GitHub CLI", not Fabric — the sign-in flow says so up front.
GITHUB_OAUTH_CLIENT_ID = "178c6fc778ccc68e1d6a"

# GitHub requires ``public_repo`` to star public repositories. The scope grants
# read/write access to all of the user's public repositories, which also enables
# the GitHub skills to push, open PRs, and file issues. It is deliberately
# narrower than ``repo`` so a token minted here cannot touch private repositories.
GITHUB_OAUTH_SCOPES = "public_repo"

GITHUB_API_BASE = "https://api.github.com"
_REQUEST_TIMEOUT_SECONDS = 15.0

# Env var search order for an existing token matches GitHub CLI.
GITHUB_ENV_VARS = ("GH_TOKEN", "GITHUB_TOKEN")

_USER_AGENT = "FabricAgent/1.0"


# ─── Token resolution ──────────────────────────────────────────────────────


def resolve_github_token() -> tuple[str, str]:
    """Resolve a GitHub token for API use.

    Returns ``(token, source)`` where ``source`` describes where the token
    came from, or ``("", "")`` when no token is available anywhere.
    """
    import os

    # 1. Process environment
    for env_var in GITHUB_ENV_VARS:
        val = os.getenv(env_var, "").strip()
        if val:
            return val, env_var

    # 2. Fabric profile .env
    try:
        from fabric_cli.config import get_env_value

        val = (get_env_value("GITHUB_TOKEN") or "").strip()
        if val:
            return val, "fabric .env"
    except Exception as exc:  # pragma: no cover - config import edge cases
        logger.debug("Fabric .env token lookup failed: %s", exc)

    # 3. gh CLI credential store
    try:
        from fabric_cli.copilot_auth import _try_gh_cli_token

        val = _try_gh_cli_token() or ""
        if val:
            return val, "gh auth token"
    except Exception as exc:  # pragma: no cover - gh probing edge cases
        logger.debug("gh CLI token lookup failed: %s", exc)

    return "", ""


def save_github_token(token: str) -> None:
    """Persist the token to the Fabric profile's ``.env`` as GITHUB_TOKEN."""
    from fabric_cli.config import save_env_value

    save_env_value("GITHUB_TOKEN", token.strip())


# ─── GitHub REST helpers ───────────────────────────────────────────────────


def _github_api_request(method: str, path: str, token: str) -> tuple[int, Any]:
    """Perform a body-less GitHub REST API request (GET / PUT / DELETE).

    Returns ``(status_code, parsed_json_or_None)``. HTTP error statuses are
    returned rather than raised; network-level failures raise ``OSError``.
    """
    import urllib.error
    import urllib.request

    url = f"{GITHUB_API_BASE}{path}"

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # PUT/DELETE without a body (e.g. starring) must send Content-Length: 0
    if method in {"PUT", "DELETE"}:
        headers["Content-Length"] = "0"

    req = urllib.request.Request(url, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code

    parsed: Any = None
    if raw:
        try:
            parsed = json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError):
            parsed = None
    return status, parsed


def fetch_github_user(token: str) -> Optional[dict]:
    """Return the authenticated user's profile, or None if the token is bad."""
    try:
        status, data = _github_api_request("GET", "/user", token)
    except OSError as exc:
        logger.debug("GitHub /user request failed: %s", exc)
        return None
    if status == 200 and isinstance(data, dict):
        return data
    return None


def is_repo_starred(token: str) -> Optional[bool]:
    """Return True/False for the Fabric repo's star state, None when unknown."""
    try:
        status, _ = _github_api_request(
            "GET", f"/user/starred/{FABRIC_REPO_SLUG}", token
        )
    except OSError as exc:
        logger.debug("GitHub star check failed: %s", exc)
        return None
    if status == 204:
        return True
    if status == 404:
        return False
    return None


def star_repo(token: str) -> bool:
    """Star the Fabric repository on behalf of the authenticated user."""
    try:
        status, _ = _github_api_request(
            "PUT", f"/user/starred/{FABRIC_REPO_SLUG}", token
        )
    except OSError as exc:
        logger.debug("GitHub star request failed: %s", exc)
        return False
    return status == 204


# ─── OAuth device code flow ────────────────────────────────────────────────


def github_device_code_login() -> Optional[str]:
    """Sign in to GitHub with a ``public_repo``-scoped device-code flow.

    Returns the gho_* access token, or None on failure/cancellation.
    """
    from fabric_cli.copilot_auth import device_code_login

    # The consent page shows the OAuth App's name, which is "GitHub CLI"
    # (see GITHUB_OAUTH_CLIENT_ID above) — say so before sending the user
    # there so the attribution isn't a surprise.
    print()
    print("  GitHub's authorization page will show this request as 'GitHub CLI' —")
    print("  Fabric signs in through the GitHub CLI's public app and requests")
    print("  read/write access to your public repositories (no private repos).")

    return device_code_login(GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_SCOPES)
