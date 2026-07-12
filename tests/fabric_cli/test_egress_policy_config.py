"""Config defaults and diagnostics for the profile AI egress contract."""

from pathlib import Path

import pytest
import yaml

from agent.egress_policy import EgressPolicyConfigurationError
from fabric_cli.config import (
    DEFAULT_CONFIG,
    load_egress_policy_config,
    validate_config_structure,
)
from fabric_constants import reset_fabric_home_override, set_fabric_home_override


def test_egress_defaults_are_additive_and_online():
    security = DEFAULT_CONFIG["security"]
    assert security["egress_mode"] == "online"
    assert security["local_ai_allowed_cidrs"] == []


def test_valid_local_ai_config_has_no_egress_issues():
    issues = validate_config_structure(
        {
            "security": {
                "egress_mode": "local_ai",
                "local_ai_allowed_cidrs": [
                    "192.168.40.0/24",
                    "100.96.0.0/16",
                    "fd12:3456::/48",
                ],
            }
        }
    )
    assert not [issue for issue in issues if "egress" in issue.message.lower()]
    assert not [
        issue for issue in issues if "local_ai_allowed_cidrs" in issue.message
    ]


def test_security_must_be_mapping():
    issues = validate_config_structure({"security": ["local_ai"]})
    assert any(
        issue.severity == "error" and "security must be a YAML mapping" in issue.message
        for issue in issues
    )


def test_invalid_mode_is_an_error_without_echoing_raw_value():
    secretish = "local_ai?token=do-not-print"
    issues = validate_config_structure(
        {"security": {"egress_mode": secretish}}
    )
    errors = [issue for issue in issues if issue.severity == "error"]
    assert any("security.egress_mode" in issue.message for issue in errors)
    assert all(secretish not in issue.message + issue.hint for issue in errors)


def test_allowed_cidrs_must_be_list():
    issues = validate_config_structure(
        {"security": {"local_ai_allowed_cidrs": "192.168.1.0/24"}}
    )
    assert any(
        issue.severity == "error" and "must be a YAML list" in issue.message
        for issue in issues
    )


def test_public_or_noncanonical_cidr_is_rejected_without_echoing_value():
    for value in ("8.8.8.0/24", "192.168.1.7/24"):
        issues = validate_config_structure(
            {"security": {"local_ai_allowed_cidrs": [value]}}
        )
        errors = [issue for issue in issues if issue.severity == "error"]
        assert any("local_ai_allowed_cidrs[0]" in issue.message for issue in errors)
        assert all(value not in issue.message + issue.hint for issue in errors)


def test_preflight_config_loader_never_expands_credential_references(
    tmp_path, monkeypatch
):
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security": {"egress_mode": "local_ai"},
                "model": {
                    "provider": "custom:remote",
                    "base_url": "https://example.com/v1",
                },
                "providers": {
                    "remote": {
                        "base_url": "https://example.com/v1",
                        "api_key": "${REMOTE_API_KEY}",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fabric_cli.config._config_env_value",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("egress preflight must not read a credential")
        ),
    )

    token = set_fabric_home_override(home)
    try:
        config = load_egress_policy_config()
    finally:
        reset_fabric_home_override(token)

    assert config["providers"]["remote"]["api_key"] == "${REMOTE_API_KEY}"


def test_missing_profile_config_keeps_online_default(tmp_path):
    home = tmp_path / "missing-profile"
    home.mkdir()
    token = set_fabric_home_override(home)
    try:
        config = load_egress_policy_config()
    finally:
        reset_fabric_home_override(token)

    assert config["security"]["egress_mode"] == "online"


def test_existing_malformed_profile_config_fails_closed(tmp_path):
    home = tmp_path / "malformed-profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        "security:\n  egress_mode: [\n", encoding="utf-8"
    )

    token = set_fabric_home_override(home)
    try:
        with pytest.raises(EgressPolicyConfigurationError) as caught:
            load_egress_policy_config()
    finally:
        reset_fabric_home_override(token)

    assert caught.value.reason == "config_unreadable"
    assert str(home) not in str(caught.value)


def test_existing_unreadable_profile_config_fails_closed(
    tmp_path, monkeypatch
):
    home = tmp_path / "unreadable-profile"
    home.mkdir()
    config_path = home / "config.yaml"
    config_path.write_text("security: {egress_mode: local_ai}\n", encoding="utf-8")
    real_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path == config_path:
            raise PermissionError("sensitive filesystem detail")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    token = set_fabric_home_override(home)
    try:
        with pytest.raises(EgressPolicyConfigurationError) as caught:
            load_egress_policy_config()
    finally:
        reset_fabric_home_override(token)

    assert caught.value.reason == "config_unreadable"
    assert "sensitive filesystem detail" not in str(caught.value)


def test_existing_dangling_profile_config_symlink_fails_closed(tmp_path):
    home = tmp_path / "dangling-profile"
    home.mkdir()
    (home / "config.yaml").symlink_to(home / "missing-policy.yaml")

    token = set_fabric_home_override(home)
    try:
        with pytest.raises(EgressPolicyConfigurationError) as caught:
            load_egress_policy_config()
    finally:
        reset_fabric_home_override(token)

    assert caught.value.reason == "config_unreadable"


def test_existing_malformed_managed_config_fails_closed(
    tmp_path, monkeypatch
):
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        "security: {egress_mode: local_ai}\n", encoding="utf-8"
    )
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "config.yaml").write_text(
        "security:\n  egress_mode: [\n", encoding="utf-8"
    )
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))

    token = set_fabric_home_override(home)
    try:
        with pytest.raises(EgressPolicyConfigurationError) as caught:
            load_egress_policy_config()
    finally:
        reset_fabric_home_override(token)

    assert caught.value.reason == "managed_config_unreadable"
    assert str(managed) not in str(caught.value)
