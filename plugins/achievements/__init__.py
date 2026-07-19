"""Fabric's private, local achievement journey plugin."""

from __future__ import annotations


def register(ctx) -> None:
    """Register observers only; loading performs no I/O or thread creation."""
    from .observer import HOOKS

    for hook_name, callback in HOOKS.items():
        ctx.register_hook(hook_name, callback)
    return None


__all__ = ["register"]
