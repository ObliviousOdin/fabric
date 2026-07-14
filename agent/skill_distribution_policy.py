"""Staged rollout policy for signed skill installs.

The policy is intentionally data-only and defaults to observation.  It does
not fetch metadata or alter the model-visible skill/tool surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


OBSERVE = "observe"
ENFORCE_LEARNED = "enforce_learned"
ENFORCE_ALL = "enforce_all"
DISTRIBUTION_MODES = frozenset({OBSERVE, ENFORCE_LEARNED, ENFORCE_ALL})


@dataclass(frozen=True)
class DistributionPolicy:
    mode: str = OBSERVE

    def requires_signed_release(self, *, provenance: str) -> bool:
        """Whether an activation source is inside this enforcement cohort."""

        if self.mode == ENFORCE_ALL:
            return True
        if self.mode == ENFORCE_LEARNED:
            return provenance in {"learned", "background_review"}
        return False


def load_distribution_policy(
    config: Mapping[str, Any] | None = None,
) -> DistributionPolicy:
    """Read ``skills.distribution.mode`` with a safe observation default."""

    if config is None:
        try:
            from fabric_cli.config import load_config_readonly

            config = load_config_readonly()
        except Exception:
            config = {}
    skills = config.get("skills") if isinstance(config, Mapping) else None
    distribution = skills.get("distribution") if isinstance(skills, Mapping) else None
    raw_mode = distribution.get("mode") if isinstance(distribution, Mapping) else None
    mode = raw_mode if isinstance(raw_mode, str) else OBSERVE
    if mode not in DISTRIBUTION_MODES:
        mode = OBSERVE
    return DistributionPolicy(mode=mode)


__all__ = [
    "DISTRIBUTION_MODES",
    "ENFORCE_ALL",
    "ENFORCE_LEARNED",
    "OBSERVE",
    "DistributionPolicy",
    "load_distribution_policy",
]
