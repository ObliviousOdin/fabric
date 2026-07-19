"""Process-local metadata supplied by immutable package entry points."""

from __future__ import annotations

_packaged_revision: str | None = None


def configure_packaged_revision(revision: str | None) -> None:
    """Record the source revision embedded by a package builder."""
    global _packaged_revision
    value = (revision or "").strip()
    _packaged_revision = value or None


def get_packaged_revision() -> str | None:
    """Return the package builder's source revision, when one was embedded."""
    return _packaged_revision
