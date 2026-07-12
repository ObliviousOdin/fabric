"""Profile-scoped policy for external-memory content writes.

External memory adapters can persist user-derived content through several
different hooks (turn sync, session extraction, compression, delegation, and
provider tools).  This module keeps the configuration decision small, pure,
and shared by runtime and status surfaces.

Only the YAML boolean ``true`` grants consent.  Strings, numbers, missing
values, and malformed sections fail closed.  The policy never reads an
environment variable: consent is non-secret, profile-owned configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


EXTERNAL_MEMORY_WRITE_CONSENT_KEY = "external_write_consent"


@dataclass(frozen=True)
class ExternalMemoryWritePolicy:
    """Resolved external-memory write decision for one profile."""

    allowed: bool
    explicitly_configured: bool
    valid: bool
    reason: str

    def as_status_dict(self) -> dict[str, Any]:
        """Return the stable, non-secret shape shared by status surfaces."""

        return {
            "state": "allowed" if self.allowed else "blocked",
            "consent_valid": self.valid,
            "consent_granted": self.allowed,
            "reason": self.reason,
        }


def resolve_external_memory_write_policy(
    memory_config: Mapping[str, Any] | object | None,
) -> ExternalMemoryWritePolicy:
    """Resolve external-write consent from one profile's ``memory`` mapping.

    A literal YAML boolean is required so a typo such as ``"yes"`` cannot
    silently broaden the data boundary.  The caller supplies the already
    profile-scoped config mapping; no global cache or environment fallback is
    consulted here.
    """

    if not isinstance(memory_config, Mapping):
        return ExternalMemoryWritePolicy(
            allowed=False,
            explicitly_configured=False,
            valid=False,
            reason="memory_config_invalid",
        )

    if EXTERNAL_MEMORY_WRITE_CONSENT_KEY not in memory_config:
        return ExternalMemoryWritePolicy(
            allowed=False,
            explicitly_configured=False,
            valid=True,
            reason="consent_required",
        )

    raw = memory_config.get(EXTERNAL_MEMORY_WRITE_CONSENT_KEY)
    if raw is True:
        return ExternalMemoryWritePolicy(
            allowed=True,
            explicitly_configured=True,
            valid=True,
            reason="explicit_profile_consent",
        )
    if raw is False:
        return ExternalMemoryWritePolicy(
            allowed=False,
            explicitly_configured=True,
            valid=True,
            reason="consent_disabled",
        )
    return ExternalMemoryWritePolicy(
        allowed=False,
        explicitly_configured=True,
        valid=False,
        reason="consent_must_be_boolean",
    )
