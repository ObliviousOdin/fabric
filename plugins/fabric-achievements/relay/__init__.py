"""Fabric Achievements leaderboard relay.

A tiny, self-hostable service that lets several Fabric users share a
team leaderboard without any central Fabric cloud. The relay stores only
*aggregate* achievement profiles (scores, unlock counts, tier tallies,
and a chosen display name) — never raw session content. See ``README.md``
in this directory for the trust model and how to run it.

The package is intentionally split so the interesting logic is easy to
test without a socket:

* :mod:`store` — pure, thread-safe :class:`LeaderboardStore` (create team,
  join, publish, roster). No networking, no framework, JSON persistence.
* :mod:`server` — a thin ``http.server`` wrapper that maps HTTP requests
  onto the store. Depends only on the standard library.
"""
from __future__ import annotations

from .store import (
    LeaderboardStore,
    RelayError,
    TeamNotFoundError,
    AuthError,
    ValidationError,
)

__all__ = [
    "LeaderboardStore",
    "RelayError",
    "TeamNotFoundError",
    "AuthError",
    "ValidationError",
]
