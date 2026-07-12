"""Early, profile-scoped egress checks for process entry points.

The ordinary environment loader may contact an external secret manager, and
several runtime entry points start update checks or MCP discovery during
bootstrap.  A configured ``air_gapped`` mode is intentionally unavailable
until Fabric has a verified whole-process network boundary, so those side
effects must be deferred before credentials are loaded.

This module deliberately performs no caching.  Every call reads the active
profile and managed policy again so a long-lived or profile-switching process
cannot reuse another profile's decision.
"""

from __future__ import annotations

from agent.egress_policy import EgressPolicy, policy_from_config, require_policy_available


def load_startup_egress_policy() -> EgressPolicy:
    """Load the active profile's strict, unexpanded egress policy snapshot."""

    # Import lazily so entry points can apply their profile override before the
    # config path is resolved.  load_egress_policy_config() reads YAML only: it
    # does not expand ${...}, access credentials, run a subprocess, or use the
    # network.
    from fabric_cli.config import load_egress_policy_config

    return policy_from_config(load_egress_policy_config())


def network_bootstrap_permitted() -> bool:
    """Whether network-capable bootstrap may run before command dispatch.

    Invalid/unreadable policy input is fail-closed here.  The command entry
    point later reports the stable configuration error while still allowing
    local repair/status commands to run without secret-manager or update
    traffic.
    """

    try:
        return load_startup_egress_policy().available
    except Exception:
        return False


def require_runtime_egress_available(*, surface: str) -> EgressPolicy:
    """Reject an unavailable runtime before its first external side effect."""

    policy = load_startup_egress_policy()
    require_policy_available(policy, surface=surface)
    return policy


__all__ = [
    "load_startup_egress_policy",
    "network_bootstrap_permitted",
    "require_runtime_egress_available",
]
