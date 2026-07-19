"""Fabric achievements plugin.

The product surface is provided by the dashboard manifest and its backend
router.  It intentionally registers no model tools or lifecycle hooks.
"""

from __future__ import annotations


def register(_ctx) -> None:
    """General-plugin entry point; achievements add no agent-core surface."""
    return None


__all__ = ["register"]
