"""Stable config defaults for the staged skills-governance rollout."""

from agent.skill_distribution_policy import OBSERVE as DISTRIBUTION_OBSERVE
from agent.skill_distribution_policy import load_distribution_policy
from agent.skill_permissions import OBSERVE as PERMISSIONS_OBSERVE
from agent.skill_permissions import load_permission_settings
from agent.skill_receipts import load_receipt_settings
from fabric_cli.config import DEFAULT_CONFIG


def test_governance_defaults_are_safe_and_observable() -> None:
    skills = DEFAULT_CONFIG["skills"]

    assert skills["permissions"] == {"mode": PERMISSIONS_OBSERVE}
    assert skills["distribution"] == {"mode": DISTRIBUTION_OBSERVE}
    assert skills["receipts"] == {
        "enabled": True,
        "max_bytes": 1_048_576,
        "max_files": 4,
    }
    assert load_permission_settings(DEFAULT_CONFIG).mode == PERMISSIONS_OBSERVE
    assert load_distribution_policy(DEFAULT_CONFIG).mode == DISTRIBUTION_OBSERVE
    assert load_receipt_settings(DEFAULT_CONFIG).enabled is True


def test_governance_policy_loaders_fail_safely_on_malformed_values() -> None:
    malformed = {
        "skills": {
            "permissions": {"mode": "future"},
            "distribution": {"mode": "future"},
            "receipts": {
                "enabled": "yes",
                "max_bytes": -1,
                "max_files": 999,
            },
        }
    }

    assert load_permission_settings(malformed).mode == PERMISSIONS_OBSERVE
    assert load_distribution_policy(malformed).mode == DISTRIBUTION_OBSERVE
    receipts = load_receipt_settings(malformed)
    assert receipts.enabled is True
    assert receipts.max_bytes == 1_048_576
    assert receipts.max_files == 4
