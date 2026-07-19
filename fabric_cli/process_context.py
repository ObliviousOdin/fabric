"""Process-wide runtime surface classification.

This is deliberately in-process state. A child process starts with the
default surface unless its own entry point classifies it, so safety decisions
cannot be changed accidentally by inheriting a parent environment variable.
"""

from __future__ import annotations

from enum import Enum


class ProcessSurface(str, Enum):
    COMMAND = "command"
    GATEWAY = "gateway"


_PROCESS_SURFACE = ProcessSurface.COMMAND


def mark_gateway_process() -> None:
    """Classify the current process as the long-running messaging gateway."""
    global _PROCESS_SURFACE
    _PROCESS_SURFACE = ProcessSurface.GATEWAY


def is_gateway_process() -> bool:
    """Return whether the current process hosts the messaging gateway."""
    return _PROCESS_SURFACE is ProcessSurface.GATEWAY
