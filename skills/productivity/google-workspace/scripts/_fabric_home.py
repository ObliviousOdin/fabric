"""Resolve the Fabric home for standalone skill scripts.

Skill scripts may run outside the Fabric process (e.g. system Python,
nix env, CI) where ``fabric_constants`` is not importable.  This module
provides the same home-resolution contract without requiring it on
``sys.path``.

When ``fabric_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
using only the stdlib.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from fabric_constants import get_fabric_home
    try:
        from fabric_constants import display_fabric_home
    except ImportError:
        def display_fabric_home() -> str:
            home = get_fabric_home()
            try:
                return "~/" + str(home.relative_to(Path.home()))
            except ValueError:
                return str(home)
except (ModuleNotFoundError, ImportError):

    def get_fabric_home() -> Path:
        """Return the agent home directory (default: ~/.fabric)."""
        val = os.environ.get("FABRIC_HOME", "").strip()
        if val:
            return Path(val)
        return Path.home() / ".fabric"

    def display_fabric_home() -> str:
        """Return a user-friendly ``~/``-shortened display string."""
        home = get_fabric_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
