"""Secret-free, profile-scoped status for Fabric's egress contract."""

from __future__ import annotations

from typing import Any

from agent.egress_policy import EgressPolicyConfigurationError
from fabric_cli.egress_startup import load_startup_egress_policy


_MODE_SCOPES = {
    "online": "unrestricted_application_network",
    "local_ai": "ai_inference_routes",
    "air_gapped": "whole_process_network",
}


def build_egress_status_snapshot() -> dict[str, Any]:
    """Return a stable snapshot without credentials, URLs, or raw errors."""

    try:
        policy = load_startup_egress_policy()
    except EgressPolicyConfigurationError as exc:
        return {
            "mode": "unknown",
            "status": "unavailable",
            "available": False,
            "scope": "unknown",
            "reason": exc.reason,
            "allowed_private_cidr_count": 0,
        }
    except Exception:
        return {
            "mode": "unknown",
            "status": "unavailable",
            "available": False,
            "scope": "unknown",
            "reason": "policy_inspection_failed",
            "allowed_private_cidr_count": 0,
        }

    return {
        "mode": policy.mode.value,
        "status": "available" if policy.available else "unavailable",
        "available": policy.available,
        "scope": _MODE_SCOPES[policy.mode.value],
        "reason": policy.unavailable_reason,
        # Count only. The approved ranges can expose private topology and are
        # already visible to their owner in config.yaml.
        "allowed_private_cidr_count": len(policy.allowed_cidrs),
    }


__all__ = ["build_egress_status_snapshot"]
