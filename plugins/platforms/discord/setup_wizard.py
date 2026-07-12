"""One-shot Discord setup helpers for team / customer onboarding.

Flow:
  1. Optional agent display name → writes/updates SOUL.md identity
  2. Paste bot token → validate via Discord API
  3. Print invite URL (client_id from token + recommended permissions)
  4. Allowlist + home channel (optional)
  5. Caller starts/restarts gateway

These helpers are pure enough to unit-test without the full adapter.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DISCORD_API_BASE = "https://discord.com/api/v10"

# Matches website/docs user-guide messaging permissions for a normal chat bot
# (send messages, embed, attach, history, slash commands, threads, etc.).
DEFAULT_BOT_PERMISSIONS = 274878286912

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-.]{50,}$")


@dataclass(frozen=True)
class DiscordBotIdentity:
    """Validated bot identity from ``GET /users/@me``."""

    id: str
    username: str
    discriminator: str | None = None
    application_id: str | None = None

    @property
    def invite_client_id(self) -> str:
        # For classic bots the application id equals the bot user id.
        return (self.application_id or self.id).strip()


def looks_like_bot_token(token: str) -> bool:
    token = (token or "").strip()
    if not token or " " in token:
        return False
    # Discord bot tokens are base64-ish segments separated by dots.
    if token.count(".") < 2:
        return False
    return bool(_TOKEN_RE.match(token))


def build_invite_url(
    client_id: str,
    *,
    permissions: int = DEFAULT_BOT_PERMISSIONS,
    scopes: tuple[str, ...] = ("bot", "applications.commands"),
) -> str:
    """Return a Discord OAuth2 invite URL for the given application/bot id."""
    cid = (client_id or "").strip()
    if not cid.isdigit():
        raise ValueError("client_id must be a numeric Discord snowflake")
    scope = "%20".join(scopes)
    return (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={cid}&permissions={int(permissions)}&scope={scope}"
    )


def validate_bot_token(
    token: str,
    *,
    timeout: float = 10.0,
    opener: Any = None,
) -> DiscordBotIdentity:
    """Validate a bot token against Discord and return the bot user.

    Raises ValueError on invalid token / API errors.
    """
    token = (token or "").strip()
    if not looks_like_bot_token(token):
        raise ValueError("That does not look like a Discord bot token")

    url = f"{DISCORD_API_BASE}/users/@me"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "Fabric-Discord-Setup (ObliviousOdin/fabric)",
            "Accept": "application/json",
        },
        method="GET",
    )
    open_fn = opener if opener is not None else urllib.request.urlopen
    try:
        with open_fn(req, timeout=timeout) as resp:
            raw = resp.read()
            status = getattr(resp, "status", None) or resp.getcode()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        if exc.code in (401, 403):
            raise ValueError("Discord rejected this bot token (unauthorized)") from exc
        raise ValueError(f"Discord API error HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Could not reach Discord API: {exc.reason}") from exc

    if status and int(status) >= 400:
        raise ValueError(f"Discord API error HTTP {status}")

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Discord returned a non-JSON response") from exc

    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError("Discord response missing bot id")
    if data.get("bot") is False:
        raise ValueError("Token is not a bot user token")

    return DiscordBotIdentity(
        id=str(data["id"]),
        username=str(data.get("username") or "bot"),
        discriminator=str(data["discriminator"]) if data.get("discriminator") else None,
        application_id=str(data["id"]),
    )


def agent_name_soul_text(agent_name: str) -> str:
    """Build a short SOUL.md identity for a named team/customer agent."""
    name = (agent_name or "").strip()
    if not name:
        raise ValueError("agent_name is required")
    return (
        f"# {name}\n\n"
        f"You are **{name}**, a Fabric agent powered by Fabric.\n\n"
        "Be helpful, direct, and reliable. Prefer action over ceremony.\n"
        "When messaging on Discord, stay concise and useful.\n"
    )


def write_agent_name_soul(
    home: Path,
    agent_name: str,
    *,
    force: bool = False,
) -> Path | None:
    """Write SOUL.md for *agent_name* under *home*.

    If SOUL.md already exists and *force* is False, leave it alone and return None
    (caller can still report the chosen name for display).
    """
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    soul = home / "SOUL.md"
    if soul.exists() and not force:
        existing = soul.read_text(encoding="utf-8", errors="replace").strip()
        if existing:
            return None
    soul.write_text(agent_name_soul_text(agent_name), encoding="utf-8")
    return soul
