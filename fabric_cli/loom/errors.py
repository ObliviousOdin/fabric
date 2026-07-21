"""Typed errors for Loom.

Every error carries a stable ``code`` so the CLI, dashboard API, and agent
tools can map failures to consistent exit codes / HTTP statuses / tool results
without string-matching messages.
"""

from __future__ import annotations


class LoomError(Exception):
    """Base class for all Loom errors.

    Attributes:
        code: A stable, machine-readable error code (kebab-case).
    """

    code: str = "loom-error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    @property
    def message(self) -> str:
        return str(self)


class LoomValidationError(LoomError):
    """Input failed validation (bad name, missing field, unknown kind)."""

    code = "validation"


class LoomNotFoundError(LoomError):
    """A referenced host, project, or deployment does not exist."""

    code = "not-found"


class LoomConflictError(LoomError):
    """The operation conflicts with current state (e.g. duplicate name,
    a deployment already in progress, or an unsafe host mutation)."""

    code = "conflict"


class LoomDriverError(LoomError):
    """A runtime driver (local or SSH) failed to carry out an operation."""

    code = "driver"
