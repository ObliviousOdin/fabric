"""Unit tests for ``fabric_cli.toolset_validation``.

Pure logic — the validity predicate is injected, so these tests need neither the
tool registry nor a running Fabric.
"""

import pytest

from fabric_cli.toolset_validation import validate_platform_toolsets

# A representative set of real toolset names.
_KNOWN = {
    "fabric-cli",
    "fabric-telegram",
    "fabric-discord",
    "terminal",
    "web",
}


def _is_valid(name):
    return name in _KNOWN


def test_valid_config_produces_no_warnings():
    cfg = {"cli": ["fabric-cli"], "telegram": ["fabric-telegram"]}
    assert validate_platform_toolsets(cfg, _is_valid) == []


def test_unknown_name_warns_and_suggests_platform_bundle():
    warnings = validate_platform_toolsets(
        {"cli": ["unknown-toolset"]},
        _is_valid,
    )
    unknown = [
        warning
        for warning in warnings
        if "unknown toolset 'unknown-toolset'" in warning
    ]
    assert len(unknown) == 1
    # Actionable: points at the valid name the entry should have been.
    assert "did you mean 'fabric-cli'?" in unknown[0]
    # And the zero-valid-toolsets safety net fires.
    assert any("zero valid toolsets" in w for w in warnings)


def test_mixed_valid_and_invalid_flags_only_the_invalid():
    cfg = {"cli": ["fabric-cli"], "discord": ["bogus"]}
    warnings = validate_platform_toolsets(cfg, _is_valid)
    # One valid entry exists, so no zero-valid warning.
    assert not any("zero valid toolsets" in w for w in warnings)
    assert len(warnings) == 1
    assert "platform 'discord'" in warnings[0]
    assert "unknown toolset 'bogus'" in warnings[0]


def test_unknown_without_valid_platform_default_omits_suggestion():
    # The platform has no known default toolset, so no "did you mean" hint.
    warnings = validate_platform_toolsets({"mystery": ["nope"]}, _is_valid)
    unknown = [w for w in warnings if "unknown toolset 'nope'" in w]
    assert len(unknown) == 1
    assert "did you mean" not in unknown[0]


@pytest.mark.parametrize("value", [None, {}, [], "fabric-cli", 42])
def test_non_dict_or_empty_yields_no_warnings(value):
    assert validate_platform_toolsets(value, _is_valid) == []


def test_scalar_toolset_value_is_accepted():
    # Some configs store the toolset as a bare string rather than a list.
    assert validate_platform_toolsets({"cli": "fabric-cli"}, _is_valid) == []


def test_non_string_entries_are_skipped_not_counted_invalid():
    cfg = {"cli": [None, 123, "fabric-cli"]}
    # The junk entries are ignored; the valid one keeps it from being "zero".
    assert validate_platform_toolsets(cfg, _is_valid) == []


def test_all_invalid_reports_each_and_the_zero_state():
    cfg = {"cli": ["unknown-cli"], "discord": ["unknown-discord"]}
    warnings = validate_platform_toolsets(cfg, _is_valid)
    assert sum("unknown toolset" in w for w in warnings) == 2
    assert any("zero valid toolsets" in w for w in warnings)


def test_real_validate_toolset_suggests_the_canonical_platform_bundle():
    # Tie the helper to the canonical registry rather than only the fixture.
    from toolsets import validate_toolset

    assert validate_toolset("fabric-cli") is True
    assert validate_toolset("unknown-toolset") is False
    warnings = validate_platform_toolsets(
        {"cli": ["unknown-toolset"]},
        validate_toolset,
    )
    assert any("did you mean 'fabric-cli'?" in w for w in warnings)
