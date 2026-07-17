"""GitHub account utilities for Fabric.

Powers ``fabric setup github``: sign in with the OAuth device code flow (or a
personal access token), then optionally star the Fabric repository and file
issues (feature requests / bug reports) against it.

The token is stored as ``GITHUB_TOKEN`` in the active profile's ``.env`` via
``fabric_cli.config.save_env_value``, which is exactly where the GitHub skills
(``skills/github/github-auth/scripts/gh-env.sh``) already look for it — so
signing in during setup makes every GitHub skill work out of the box.

Token resolution order (matching the skills' gh-env.sh helper):
  1. GITHUB_TOKEN / GH_TOKEN env vars
  2. GITHUB_TOKEN in the Fabric profile's ``.env``
  3. ``gh auth token`` CLI fallback
"""

from __future__ import annotations

import json
import logging
import time
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
# need ``public_repo`` to star repositories and open issues on behalf of
# the user. This is the same App ID `gh auth login` uses for its own
# device flow, so the resulting gho_* token behaves exactly like a gh
# login token.
GITHUB_OAUTH_CLIENT_ID = "178c6fc778ccc68e1d6a"

# ``public_repo`` covers everything this module does: starring public
# repositories and creating issues on them. Deliberately narrower than the
# ``repo`` scope so a token minted here can't touch private repositories.
GITHUB_OAUTH_SCOPES = "public_repo"

GITHUB_API_BASE = "https://api.github.com"

# Env var search order for an existing token.
GITHUB_ENV_VARS = ("GITHUB_TOKEN", "GH_TOKEN")

# Polling constants (RFC 8628 device flow)
_DEVICE_CODE_POLL_INTERVAL = 5  # seconds
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


def _github_api_request(
    method: str,
    path: str,
    token: str,
    *,
    data: Optional[dict] = None,
    timeout: float = 15.0,
) -> tuple[int, Any]:
    """Perform a GitHub REST API request.

    Returns ``(status_code, parsed_json_or_None)``. HTTP error statuses are
    returned rather than raised; network-level failures raise ``OSError``.
    """
    import urllib.error
    import urllib.request

    url = path if path.startswith("http") else f"{GITHUB_API_BASE}{path}"
    body = json.dumps(data).encode() if data is not None else None

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    else:
        # PUT/DELETE without a body (e.g. starring) must send Content-Length: 0
        if method in {"PUT", "DELETE"}:
            headers["Content-Length"] = "0"

    req = urllib.request.Request(url, data=body, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def is_repo_starred(
    token: str,
    owner: str = FABRIC_REPO_OWNER,
    repo: str = FABRIC_REPO_NAME,
) -> Optional[bool]:
    """Return True/False for star state, or None when it can't be determined."""
    try:
        status, _ = _github_api_request("GET", f"/user/starred/{owner}/{repo}", token)
    except OSError as exc:
        logger.debug("GitHub star check failed: %s", exc)
        return None
    if status == 204:
        return True
    if status == 404:
        return False
    return None


def star_repo(
    token: str,
    owner: str = FABRIC_REPO_OWNER,
    repo: str = FABRIC_REPO_NAME,
) -> bool:
    """Star a repository on behalf of the authenticated user."""
    try:
        status, _ = _github_api_request("PUT", f"/user/starred/{owner}/{repo}", token)
    except OSError as exc:
        logger.debug("GitHub star request failed: %s", exc)
        return False
    return status == 204


def create_issue(
    token: str,
    title: str,
    body: str,
    *,
    owner: str = FABRIC_REPO_OWNER,
    repo: str = FABRIC_REPO_NAME,
    labels: Optional[list[str]] = None,
) -> Optional[dict]:
    """Create an issue and return its JSON payload (contains ``html_url``)."""
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    try:
        status, data = _github_api_request(
            "POST", f"/repos/{owner}/{repo}/issues", token, data=payload
        )
    except OSError as exc:
        logger.debug("GitHub issue creation failed: %s", exc)
        return None
    if status == 201 and isinstance(data, dict):
        return data
    logger.debug("GitHub issue creation returned status %s: %s", status, data)
    return None


# ─── OAuth device code flow ────────────────────────────────────────────────


def github_device_code_login(
    *,
    scopes: str = GITHUB_OAUTH_SCOPES,
    timeout_seconds: float = 300,
) -> Optional[str]:
    """Run the GitHub OAuth device code flow for a scoped user token.

    Prints instructions, polls for completion, and returns the gho_* access
    token on success or None on failure/cancellation. Same flow shape as
    ``copilot_auth.copilot_device_code_login`` but with a scoped OAuth App.
    """
    import urllib.parse
    import urllib.request

    device_code_url = "https://github.com/login/device/code"
    access_token_url = "https://github.com/login/oauth/access_token"

    data = urllib.parse.urlencode(
        {"client_id": GITHUB_OAUTH_CLIENT_ID, "scope": scopes}
    ).encode()

    req = urllib.request.Request(
        device_code_url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            device_data = json.loads(resp.read().decode())
    except Exception as exc:
        logger.error("Failed to initiate device authorization: %s", exc)
        print(f"  ✗ Failed to start device authorization: {exc}")
        return None

    verification_uri = device_data.get(
        "verification_uri", "https://github.com/login/device"
    )
    user_code = device_data.get("user_code", "")
    device_code = device_data.get("device_code", "")
    interval = max(device_data.get("interval", _DEVICE_CODE_POLL_INTERVAL), 1)

    if not device_code or not user_code:
        print("  ✗ GitHub did not return a device code.")
        return None

    print()
    print(f"  Open this URL in your browser: {verification_uri}")
    print(f"  Enter this code: {user_code}")
    print()
    print("  Waiting for authorization...", end="", flush=True)

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        time.sleep(interval)

        poll_data = urllib.parse.urlencode(
            {
                "client_id": GITHUB_OAUTH_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
        ).encode()

        poll_req = urllib.request.Request(
            access_token_url,
            data=poll_data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": _USER_AGENT,
            },
        )

        try:
            with urllib.request.urlopen(poll_req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
        except Exception:
            print(".", end="", flush=True)
            continue

        if result.get("access_token"):
            print(" ✓")
            return result["access_token"]

        error = result.get("error", "")
        if error == "authorization_pending":
            print(".", end="", flush=True)
            continue
        elif error == "slow_down":
            # RFC 8628: honor the server interval, else add 5 seconds
            server_interval = result.get("interval")
            if isinstance(server_interval, (int, float)) and server_interval > 0:
                interval = int(server_interval)
            else:
                interval += 5
            print(".", end="", flush=True)
            continue
        elif error == "expired_token":
            print()
            print("  ✗ Device code expired. Please try again.")
            return None
        elif error == "access_denied":
            print()
            print("  ✗ Authorization was denied.")
            return None
        elif error:
            print()
            print(f"  ✗ Authorization failed: {error}")
            return None

    print()
    print("  ✗ Timed out waiting for authorization.")
    return None
