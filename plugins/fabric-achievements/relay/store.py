"""Pure, thread-safe leaderboard store for the Fabric Achievements relay.

This module holds *all* of the relay's logic and none of its plumbing, so
the interesting behaviour — team creation, invite-secret verification,
per-member auth, profile sanitisation, ranking — is unit-testable without
opening a socket. :mod:`fabric_achievements.relay.server` is a thin HTTP
shell over this class.

Privacy / trust model
---------------------
The store keeps only what a leaderboard needs and nothing that could leak a
user's work:

* A team has a name, an owner, a hashed ``join_secret`` (the shared thing an
  invite link carries), and a set of members.
* A member has a display name, a hashed per-member ``member_token`` (proves
  "I am this member" on later publishes), and an aggregate ``profile``.
* A ``profile`` is sanitised on the way in: scores/counts/tier tallies and a
  short list of unlocked-badge *metadata* (ids/names from the static public
  catalogue). Session titles, ids, transcripts, file paths, and free-form
  fields are dropped — they never enter the store.

Secrets are never stored in the clear: ``join_secret`` and ``member_token``
are salted-SHA256 hashed and compared with :func:`hmac.compare_digest`.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

# The canonical tier ladder shared with the achievements plugin. Kept here
# (rather than imported) so the relay stays a zero-Fabric-dependency service.
TIER_NAMES = ["Copper", "Silver", "Gold", "Diamond", "Olympian"]

# Bounds that keep a hostile or buggy client from bloating the store.
MAX_DISPLAY_NAME = 64
MAX_TEAM_NAME = 64
MAX_TOP_ACHIEVEMENTS = 8
MAX_CATEGORY_KEYS = 40
MAX_MEMBERS_PER_TEAM = 500
MAX_STRING_FIELD = 80
# Global cap on team count. create_team is unauthenticated (anyone who can
# reach the relay can create a team), and every write re-serializes the whole
# store, so an uncapped relay is a memory/disk DoS with O(N^2) persistence
# amplification. This bounds it; run the relay on a trusted network regardless.
MAX_TEAMS = 1000


class RelayError(Exception):
    """Base error. ``status`` is the HTTP code the server should emit."""

    status = 400

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class ValidationError(RelayError):
    status = 400


class AuthError(RelayError):
    status = 403


class TeamNotFoundError(RelayError):
    status = 404


def _now() -> int:
    return int(time.time())


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _gen_secret() -> str:
    return secrets.token_urlsafe(24)


def _hash_secret(secret: str, salt: str) -> str:
    """Salted SHA-256. Not a password KDF, but these are 24-byte random
    tokens (not user passwords), so a fast hash with a per-value salt is an
    appropriate, dependency-free choice for defence-in-depth at rest."""
    return hashlib.sha256((salt + ":" + secret).encode("utf-8")).hexdigest()


def _verify_secret(secret: str, salt: str, expected_hash: str) -> bool:
    if not secret or not expected_hash:
        return False
    candidate = _hash_secret(secret, salt)
    return hmac.compare_digest(candidate, expected_hash)


def _clean_str(value: Any, *, max_len: int, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    # Strip control characters so a display name can't smuggle newlines /
    # escape sequences into a reviewer's terminal or another user's UI.
    cleaned = "".join(ch for ch in value if ch == " " or ch.isprintable()).strip()
    return cleaned[:max_len] if cleaned else default


def _clean_int(value: Any, *, minimum: int = 0, maximum: int = 10**12) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(minimum, min(maximum, n))


def sanitize_profile(raw: Any) -> Dict[str, Any]:
    """Coerce a client-supplied profile into a bounded, leak-free shape.

    Anything unexpected is dropped rather than trusted. This is the single
    choke point where external data enters the store, so it is deliberately
    strict: only known keys survive, strings are length-capped and
    control-stripped, and collections are bounded.
    """
    if not isinstance(raw, dict):
        raise ValidationError("profile must be an object")

    tier_counts_in = raw.get("tier_counts") if isinstance(raw.get("tier_counts"), dict) else {}
    tier_counts = {tier: _clean_int(tier_counts_in.get(tier, 0)) for tier in TIER_NAMES}

    category_counts: Dict[str, int] = {}
    cats_in = raw.get("category_counts")
    if isinstance(cats_in, dict):
        for key, val in list(cats_in.items())[:MAX_CATEGORY_KEYS]:
            name = _clean_str(key, max_len=MAX_STRING_FIELD)
            if name:
                category_counts[name] = _clean_int(val)

    top: List[Dict[str, str]] = []
    top_in = raw.get("top_achievements")
    if isinstance(top_in, list):
        for item in top_in[:MAX_TOP_ACHIEVEMENTS]:
            if not isinstance(item, dict):
                continue
            top.append({
                "id": _clean_str(item.get("id"), max_len=MAX_STRING_FIELD),
                "name": _clean_str(item.get("name"), max_len=MAX_STRING_FIELD),
                "tier": _clean_str(item.get("tier"), max_len=16),
                "category": _clean_str(item.get("category"), max_len=MAX_STRING_FIELD),
                "icon": _clean_str(item.get("icon"), max_len=32),
            })

    highest = _clean_str(raw.get("highest_tier"), max_len=16)
    if highest not in TIER_NAMES:
        highest = ""

    return {
        "score": _clean_int(raw.get("score")),
        "unlocked_count": _clean_int(raw.get("unlocked_count")),
        "discovered_count": _clean_int(raw.get("discovered_count")),
        "secret_count": _clean_int(raw.get("secret_count")),
        "total_count": _clean_int(raw.get("total_count")),
        "tier_counts": tier_counts,
        "highest_tier": highest or None,
        "category_counts": category_counts,
        "top_achievements": top,
        "client_generated_at": _clean_int(raw.get("generated_at")) or None,
    }


class LeaderboardStore:
    """In-memory team/roster store with optional JSON persistence.

    All public methods are safe to call from multiple threads. Secrets are
    accepted in the clear (over the wire) and verified against stored hashes;
    they are never persisted or returned in the clear.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.RLock()
        self._teams: Dict[str, Dict[str, Any]] = {}
        if self._path is not None:
            self._load()

    # ---- persistence ---------------------------------------------------
    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        if os.name != "nt":
            try:
                self._path.chmod(0o600)
            except OSError:
                pass
            try:
                self._path.parent.chmod(0o700)
            except OSError:
                pass
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(data, dict) and isinstance(data.get("teams"), dict):
            self._teams = data["teams"]

    def _persist_locked(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            try:
                self._path.parent.chmod(0o700)
            except OSError:
                pass
        payload = {"schema_version": SCHEMA_VERSION, "teams": self._teams}
        tmp: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp = Path(handle.name)
                if os.name != "nt":
                    os.chmod(tmp, 0o600)
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(self._path)
            if os.name != "nt":
                try:
                    directory_fd = os.open(self._path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError:
                    # The rename is already committed. Do not report failure
                    # and roll memory back to a state that disagrees with disk.
                    pass
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass

    def _persist_with_rollback_locked(self, previous: Dict[str, Dict[str, Any]]) -> None:
        """Persist a mutation or restore the last durable in-memory state."""
        try:
            self._persist_locked()
        except Exception:
            self._teams = previous
            raise

    # ---- internal helpers ---------------------------------------------
    def _get_team(self, team_id: str) -> Dict[str, Any]:
        team = self._teams.get(team_id)
        if not team:
            raise TeamNotFoundError("team not found", status=404)
        return team

    # ---- public API ----------------------------------------------------
    def create_team(self, *, name: str, display_name: str) -> Dict[str, Any]:
        """Create a team and enrol the caller as its owner.

        Returns the team id, the shareable ``join_secret`` (goes into the
        invite link), and the owner's member id + ``member_token``. Secrets
        are returned exactly once — only their hashes are retained.
        """
        clean_name = _clean_str(name, max_len=MAX_TEAM_NAME, default="Untitled Team")
        owner_display = _clean_str(display_name, max_len=MAX_DISPLAY_NAME, default="Owner")
        team_id = _gen_id("tm")
        join_secret = _gen_secret()
        owner_member_id = _gen_id("mb")
        owner_token = _gen_secret()
        salt = secrets.token_hex(8)
        now = _now()
        with self._lock:
            if len(self._teams) >= MAX_TEAMS:
                raise ValidationError("relay is at team capacity", status=429)
            previous = copy.deepcopy(self._teams)
            self._teams[team_id] = {
                "id": team_id,
                "name": clean_name,
                "salt": salt,
                "join_secret_hash": _hash_secret(join_secret, salt),
                "created_at": now,
                "owner_member_id": owner_member_id,
                "members": {
                    owner_member_id: {
                        "id": owner_member_id,
                        "display_name": owner_display,
                        "member_token_hash": _hash_secret(owner_token, salt),
                        "role": "owner",
                        "joined_at": now,
                        "updated_at": now,
                        "profile": None,
                    }
                },
            }
            self._persist_with_rollback_locked(previous)
        return {
            "team_id": team_id,
            "team_name": clean_name,
            "join_secret": join_secret,
            "member_id": owner_member_id,
            "member_token": owner_token,
            "role": "owner",
        }

    def join_team(self, *, team_id: str, join_secret: str, display_name: str) -> Dict[str, Any]:
        """Enrol a new member after verifying the shared invite secret."""
        with self._lock:
            team = self._get_team(team_id)
            if not _verify_secret(join_secret, team["salt"], team["join_secret_hash"]):
                raise AuthError("invalid invite secret", status=403)
            if len(team["members"]) >= MAX_MEMBERS_PER_TEAM:
                raise ValidationError("team is full", status=409)
            previous = copy.deepcopy(self._teams)
            member_id = _gen_id("mb")
            member_token = _gen_secret()
            now = _now()
            team["members"][member_id] = {
                "id": member_id,
                "display_name": _clean_str(display_name, max_len=MAX_DISPLAY_NAME, default="Member"),
                "member_token_hash": _hash_secret(member_token, team["salt"]),
                "role": "member",
                "joined_at": now,
                "updated_at": now,
                "profile": None,
            }
            self._persist_with_rollback_locked(previous)
            return {
                "team_id": team_id,
                "team_name": team["name"],
                "member_id": member_id,
                "member_token": member_token,
                "role": "member",
            }

    def _auth_member(self, team: Dict[str, Any], member_id: str, member_token: str) -> Dict[str, Any]:
        member = team["members"].get(member_id)
        if not member or not _verify_secret(member_token, team["salt"], member["member_token_hash"]):
            raise AuthError("invalid member credentials", status=403)
        return member

    def publish(
        self,
        *,
        team_id: str,
        member_id: str,
        member_token: str,
        profile: Any,
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store (or replace) a member's aggregate profile.

        A member can only update its own row — proven by ``member_token``.
        The profile is sanitised before storage. ``display_name`` may be
        updated at the same time (users rename themselves).
        """
        clean_profile = sanitize_profile(profile)
        with self._lock:
            team = self._get_team(team_id)
            member = self._auth_member(team, member_id, member_token)
            previous = copy.deepcopy(self._teams)
            member["profile"] = clean_profile
            member["updated_at"] = _now()
            if display_name is not None:
                new_name = _clean_str(display_name, max_len=MAX_DISPLAY_NAME)
                if new_name:
                    member["display_name"] = new_name
            self._persist_with_rollback_locked(previous)
            return {"ok": True, "updated_at": member["updated_at"]}

    def unpublish(self, *, team_id: str, member_id: str, member_token: str) -> Dict[str, Any]:
        """Retract a member's published profile without leaving the team.

        Used when a member turns off "share my stats": their row stays (they're
        still a member) but shows as not-shared with an empty score.
        """
        with self._lock:
            team = self._get_team(team_id)
            member = self._auth_member(team, member_id, member_token)
            previous = copy.deepcopy(self._teams)
            member["profile"] = None
            member["updated_at"] = _now()
            self._persist_with_rollback_locked(previous)
            return {"ok": True}

    def leave(self, *, team_id: str, member_id: str, member_token: str) -> Dict[str, Any]:
        """Remove a member from a team (authenticated by the member token)."""
        with self._lock:
            team = self._teams.get(team_id)
            if not team or member_id not in team["members"]:
                return {"ok": True}
            self._auth_member(team, member_id, member_token)
            previous = copy.deepcopy(self._teams)
            team["members"].pop(member_id, None)
            # Drop the whole team once the last member leaves so the store
            # doesn't accumulate empty husks.
            if not team["members"]:
                self._teams.pop(team_id, None)
            self._persist_with_rollback_locked(previous)
            return {"ok": True}

    def _require_owner(self, team: Dict[str, Any], member_id: str, member_token: str) -> Dict[str, Any]:
        member = self._auth_member(team, member_id, member_token)
        if member.get("role") != "owner":
            raise AuthError("only the team owner may do that", status=403)
        return member

    def rotate_join_secret(self, *, team_id: str, member_id: str, member_token: str) -> Dict[str, Any]:
        """Owner-only: mint a fresh invite secret, invalidating old links."""
        with self._lock:
            team = self._get_team(team_id)
            self._require_owner(team, member_id, member_token)
            previous = copy.deepcopy(self._teams)
            new_secret = _gen_secret()
            team["join_secret_hash"] = _hash_secret(new_secret, team["salt"])
            self._persist_with_rollback_locked(previous)
            return {"ok": True, "join_secret": new_secret}

    def kick_member(self, *, team_id: str, member_id: str, member_token: str, target_member_id: str) -> Dict[str, Any]:
        """Owner-only: remove another member from the team."""
        with self._lock:
            team = self._get_team(team_id)
            self._require_owner(team, member_id, member_token)
            if target_member_id == member_id:
                raise ValidationError("use leave to remove yourself", status=400)
            if target_member_id not in team["members"]:
                raise TeamNotFoundError("member not found", status=404)
            previous = copy.deepcopy(self._teams)
            team["members"].pop(target_member_id, None)
            self._persist_with_rollback_locked(previous)
            return {"ok": True}

    def leaderboard(
        self,
        *,
        team_id: str,
        join_secret: Optional[str] = None,
        member_id: Optional[str] = None,
        member_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the ranked roster.

        Reading requires proof of membership: either the shared invite
        secret (anyone with the link) or a valid member token. This keeps a
        team's roster from being scraped by anyone who merely guesses a team
        id, while preserving the "anyone I invited can view" behaviour.
        """
        with self._lock:
            team = self._get_team(team_id)
            authed = False
            if join_secret is not None and _verify_secret(join_secret, team["salt"], team["join_secret_hash"]):
                authed = True
            elif member_id and member_token:
                member = team["members"].get(member_id)
                if member and _verify_secret(member_token, team["salt"], member["member_token_hash"]):
                    authed = True
            if not authed:
                raise AuthError("membership proof required to view leaderboard", status=403)

            rows = []
            for member in team["members"].values():
                profile = member.get("profile") or {}
                rows.append({
                    "member_id": member["id"],
                    "display_name": member.get("display_name") or "Member",
                    "role": member.get("role", "member"),
                    "score": int(profile.get("score", 0) or 0),
                    "unlocked_count": int(profile.get("unlocked_count", 0) or 0),
                    "total_count": int(profile.get("total_count", 0) or 0),
                    "highest_tier": profile.get("highest_tier"),
                    "tier_counts": profile.get("tier_counts") or {},
                    "category_counts": profile.get("category_counts") or {},
                    "top_achievements": profile.get("top_achievements") or [],
                    "has_published": member.get("profile") is not None,
                    "updated_at": member.get("updated_at"),
                })
            rows = rank_rows(rows)
            return {
                "team_id": team_id,
                "team_name": team["name"],
                "member_count": len(rows),
                "generated_at": _now(),
                "leaderboard": rows,
            }

    def stats(self) -> Dict[str, Any]:
        """Cheap health/inspection payload (no secrets)."""
        with self._lock:
            return {
                "teams": len(self._teams),
                "members": sum(len(t["members"]) for t in self._teams.values()),
                "schema_version": SCHEMA_VERSION,
            }


def rank_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort by score desc, then unlock count desc, then name; assign ``rank``.

    Equal scores share a rank (standard "1224" competition ranking) so ties
    read correctly on the board.
    """
    ordered = sorted(
        rows,
        key=lambda r: (-int(r.get("score", 0) or 0), -int(r.get("unlocked_count", 0) or 0), str(r.get("display_name", "")).lower()),
    )
    last_key: Optional[tuple] = None
    last_rank = 0
    for index, row in enumerate(ordered, start=1):
        key = (int(row.get("score", 0) or 0), int(row.get("unlocked_count", 0) or 0))
        if key != last_key:
            last_rank = index
            last_key = key
        row["rank"] = last_rank
    return ordered
