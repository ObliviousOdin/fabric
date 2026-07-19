import json
from pathlib import Path

import pytest

from agent.memory_provider import (
    MemoryCapabilitySupport as Capability,
    MemoryProviderCapabilities,
)
from fabric_cli.memory_status import (
    _provider_config_values,
    build_memory_status_snapshot,
    format_memory_status_snapshot,
)


class FakeProvider:
    def __init__(self, *, schema=None, capabilities=None):
        self._schema = schema or []
        self._capabilities = capabilities or MemoryProviderCapabilities()

    def get_config_schema(self):
        return self._schema

    def get_capabilities(self):
        return self._capabilities


def test_common_provider_config_remains_below_provider_specific_values(tmp_path):
    values = _provider_config_values(
        "fake",
        home=tmp_path,
        config={
            "memory": {
                "provider_config": {"shared": "common", "priority": "common"},
                "fake": {"priority": "specific"},
            }
        },
    )

    assert values == {"shared": "common", "priority": "specific"}


def _snapshot(
    tmp_path: Path,
    *,
    config: dict,
    ready: bool = True,
    provider: object | None = None,
    name: str = "fake",
    provider_dir: Path | None = None,
    env: dict[str, str] | None = None,
):
    provider = provider or FakeProvider()
    provider_dir = provider_dir or (tmp_path / "plugins" / "memory" / name)
    provider_dir.mkdir(parents=True, exist_ok=True)
    return build_memory_status_snapshot(
        config=config,
        home=tmp_path,
        env=env or {},
        discover=lambda: [(name, "Fake memory", ready)],
        load_provider=lambda requested: provider if requested == name else None,
        find_provider_dir=lambda requested: provider_dir if requested == name else None,
    )


@pytest.mark.parametrize(
    ("memory_enabled", "user_enabled", "expected"),
    [
        (True, True, "eligible"),
        (True, False, "eligible"),
        (False, True, "eligible"),
        (False, False, "tiers_disabled"),
    ],
)
def test_selection_state_never_claims_runtime_activation(
    tmp_path, memory_enabled, user_enabled, expected
):
    snapshot = _snapshot(
        tmp_path,
        config={
            "memory": {
                "provider": "fake",
                "memory_enabled": memory_enabled,
                "user_profile_enabled": user_enabled,
            }
        },
    )

    assert snapshot["selection"] == {
        "configured": "fake",
        "state": expected,
        "runtime_active": "unknown",
    }
    row = snapshot["providers"][0]
    assert row["activation_eligible"] is (expected == "eligible")
    assert row["runtime_active"] == "unknown"
    assert row["health"] == {
        "state": "unknown",
        "checked": False,
        "reason": "not_probed",
    }


def test_configuration_dependencies_and_health_are_distinct(tmp_path):
    provider = FakeProvider(
        schema=[
            {
                "key": "api_key",
                "secret": True,
                "required": True,
                "env_var": "FAKE_MEMORY_KEY",
            }
        ]
    )
    snapshot = _snapshot(
        tmp_path,
        config={"memory": {"provider": "fake"}},
        ready=False,
        provider=provider,
    )

    row = snapshot["providers"][0]
    assert row["installed"] is True
    assert row["readiness"]["configuration_complete"] is False
    assert row["readiness"]["dependencies_available"] is True
    assert row["readiness"]["adapter_ready"] is False
    assert row["health"]["state"] == "unknown"
    assert snapshot["selection"]["state"] == "needs_config"


def test_selected_missing_provider_is_preserved(tmp_path):
    snapshot = build_memory_status_snapshot(
        config={"memory": {"provider": "user-memory"}},
        home=tmp_path,
        env={},
        discover=lambda: [],
        load_provider=lambda _name: None,
        find_provider_dir=lambda _name: None,
    )

    assert snapshot["selection"]["state"] == "missing"
    assert len(snapshot["providers"]) == 1
    row = snapshot["providers"][0]
    assert row["name"] == "user-memory"
    assert row["installed"] is False
    assert row["selected"] is True


def test_user_provider_inventory_is_not_removed_by_beginner_curation(tmp_path):
    user_dir = tmp_path / "user-plugins" / "my-memory"
    snapshot = _snapshot(
        tmp_path,
        config={"memory": {"provider": "my-memory"}},
        name="my-memory",
        provider_dir=user_dir,
    )

    assert [row["name"] for row in snapshot["providers"]] == ["my-memory"]
    assert snapshot["providers"][0]["source"] == "user"


def test_default_status_inventory_never_executes_user_provider_code(tmp_path):
    provider_dir = tmp_path / "plugins" / "unsafe-memory"
    provider_dir.mkdir(parents=True)
    (provider_dir / "__init__.py").write_text(
        "# MemoryProvider marker for static discovery\n"
        "raise AssertionError('user provider status code executed')\n",
        encoding="utf-8",
    )
    (provider_dir / "plugin.yaml").write_text(
        "description: Static-only test provider\n",
        encoding="utf-8",
    )

    snapshot = build_memory_status_snapshot(
        config={"memory": {"provider": "unsafe-memory"}},
        home=tmp_path,
        env={},
    )

    row = next(
        provider for provider in snapshot["providers"] if provider["name"] == "unsafe-memory"
    )
    assert row["source"] == "user"
    assert row["lifecycle"]["load"] == "not_inspected"
    assert set(row["capabilities"].values()) == {"unknown"}
    assert snapshot["selection"]["state"] == "readiness_unknown"


def test_unobserved_profile_env_cannot_emit_legacy_ready_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MEMORY_KEY", "default-profile-secret")
    provider = FakeProvider(
        schema=[
            {
                "key": "api_key",
                "secret": True,
                "required": True,
                "env_var": "FAKE_MEMORY_KEY",
            }
        ]
    )
    snapshot = _snapshot(
        tmp_path,
        config={"memory": {"provider": "fake"}},
        provider=provider,
        ready=True,
        env={"FAKE_MEMORY_KEY": "worker-profile-secret"},
    )

    row = snapshot["providers"][0]
    assert row["readiness"]["profile_observation_reliable"] is False
    assert row["readiness"]["adapter_ready"] is None
    assert row["available"] is False
    assert row["status"] == "readiness_unknown"
    assert snapshot["selection"]["state"] == "readiness_unknown"


def test_snapshot_never_serializes_provider_values_or_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv("FAKE_MEMORY_KEY", raising=False)
    provider = FakeProvider(
        schema=[
            {
                "key": "api_key",
                "secret": True,
                "required": True,
                "env_var": "FAKE_MEMORY_KEY",
            }
        ]
    )
    secret = "do-not-serialize-this-token"
    snapshot = _snapshot(
        tmp_path,
        config={
            "memory": {
                "provider": "fake",
                "fake": {"api_key": secret, "endpoint": "https://private.invalid"},
            }
        },
        provider=provider,
        env={"FAKE_MEMORY_KEY": secret},
    )

    serialized = json.dumps(snapshot)
    assert secret not in serialized
    assert "https://private.invalid" not in serialized


def test_profile_scoped_tiers_and_file_sizes_do_not_cross(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    (first / "memories").mkdir(parents=True)
    (second / "memories").mkdir(parents=True)
    (first / "memories" / "MEMORY.md").write_text("first", encoding="utf-8")
    (second / "memories" / "MEMORY.md").write_text("second-profile", encoding="utf-8")

    common = dict(
        env={},
        discover=lambda: [],
        load_provider=lambda _name: None,
        find_provider_dir=lambda _name: None,
    )
    one = build_memory_status_snapshot(
        config={"memory": {"memory_enabled": True, "user_profile_enabled": False}},
        home=first,
        **common,
    )
    two = build_memory_status_snapshot(
        config={"memory": {"memory_enabled": False, "user_profile_enabled": True}},
        home=second,
        **common,
    )

    assert one["tiers"]["memory"] == {"enabled": True, "bytes": 5}
    assert two["tiers"]["memory"] == {"enabled": False, "bytes": 14}
    assert one["tiers"]["user"]["enabled"] is False
    assert two["tiers"]["user"]["enabled"] is True


def test_formatter_labels_eligibility_and_health_truthfully(tmp_path):
    snapshot = _snapshot(
        tmp_path,
        config={"memory": {"provider": "fake"}},
        provider=FakeProvider(
            capabilities=MemoryProviderCapabilities(
                recall=Capability.SUPPORTED,
                delete=Capability.UNSUPPORTED,
            )
        ),
    )

    output = format_memory_status_snapshot(snapshot)
    assert "Readiness: eligible" in output
    assert "Runtime:   not observed; live health not probed" in output
    assert "Adapter potential: recall" in output
    assert "active" not in output.lower()


def test_external_write_policy_is_separate_from_provider_readiness(tmp_path):
    snapshot = _snapshot(
        tmp_path,
        config={"memory": {"provider": "fake"}},
    )

    assert snapshot["selection"]["state"] == "eligible"
    assert snapshot["write_policy"]["external_provider_writes"] == {
        "state": "blocked",
        "consent_valid": True,
        "consent_granted": False,
        "reason": "consent_required",
    }
    assert "External capture: blocked (profile consent required)" in (
        format_memory_status_snapshot(snapshot)
    )


def test_external_write_policy_hint_preserves_named_profile(tmp_path, monkeypatch):
    snapshot = _snapshot(
        tmp_path,
        config={"memory": {"provider": "fake"}},
    )
    monkeypatch.setattr(
        "fabric_cli.profiles.get_active_profile_name",
        lambda: "team alpha",
    )

    output = format_memory_status_snapshot(snapshot)

    assert (
        "fabric -p 'team alpha' config set "
        "memory.external_write_consent true" in output
    )


def test_explicit_external_write_consent_does_not_claim_runtime_activation(tmp_path):
    snapshot = _snapshot(
        tmp_path,
        config={
            "memory": {
                "provider": "fake",
                "external_write_consent": True,
            }
        },
    )

    assert snapshot["selection"] == {
        "configured": "fake",
        "state": "eligible",
        "runtime_active": "unknown",
    }
    policy = snapshot["write_policy"]["external_provider_writes"]
    assert policy["state"] == "allowed"
    assert policy["consent_granted"] is True
    assert policy["reason"] == "explicit_profile_consent"
    assert "External capture: allowed by explicit profile consent" in (
        format_memory_status_snapshot(snapshot)
    )


def test_invalid_external_write_consent_fails_closed_without_serializing_value(tmp_path):
    raw_value = "secret-looking-invalid-value"
    snapshot = _snapshot(
        tmp_path,
        config={
            "memory": {
                "provider": "fake",
                "external_write_consent": raw_value,
            }
        },
    )

    policy = snapshot["write_policy"]["external_provider_writes"]
    assert policy["state"] == "blocked"
    assert policy["consent_valid"] is False
    assert policy["reason"] == "consent_must_be_boolean"
    assert raw_value not in json.dumps(snapshot)
    assert "External capture: blocked (consent must be YAML true or false)" in (
        format_memory_status_snapshot(snapshot)
    )


def test_external_write_policy_does_not_bleed_between_profile_snapshots(tmp_path):
    common = dict(
        env={},
        discover=lambda: [],
        load_provider=lambda _name: None,
        find_provider_dir=lambda _name: None,
    )
    allowed = build_memory_status_snapshot(
        config={"memory": {"external_write_consent": True}},
        home=tmp_path / "allowed",
        **common,
    )
    denied = build_memory_status_snapshot(
        config={"memory": {"external_write_consent": False}},
        home=tmp_path / "denied",
        **common,
    )

    assert allowed["write_policy"]["external_provider_writes"]["state"] == "allowed"
    assert denied["write_policy"]["external_provider_writes"]["state"] == "blocked"
