"""Behavior contracts for the governed skill-contract validator."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from agent.skill_contract import (
    CONTRACT_FILENAME,
    SOURCE_FUTURE_SKEW,
    discover_skill_directories,
    permission_expansion,
    source_freshness_blockers,
    validate_skill_directory,
)


def _valid_contract(name: str = "demo-skill", version: str = "1.2.3") -> dict:
    return {
        "schema_version": 1,
        "identity": {
            "name": name,
            "version": version,
            "owner": "owner@example.test",
            "license": "Apache-2.0",
        },
        "compatibility": {
            "fabric": ">=0.19.0",
            "hosts": ["fabric"],
            "models": ["*"],
            "platforms": ["macos", "linux", "windows"],
        },
        "routing": {
            "triggers": ["The user asks for a demonstration."],
            "non_triggers": ["The user asks only for a definition."],
            "requires": [],
            "conflicts": [],
        },
        "interface": {
            "inputs": [{"name": "request", "type": "string"}],
            "outputs": [{"name": "demonstration", "type": "object"}],
        },
        "permissions": {
            "toolsets_required": [],
            "files": [{"scope": "workspace", "access": "read"}],
            "network": [{"host": "docs.example.com", "methods": ["GET"]}],
            "secrets": [],
            "actions": {
                "reversible": [],
                "approval_required": [],
                "prohibited": [],
            },
        },
        "sources": [
            {
                "url": "https://docs.example.com/",
                "retrieved_at": "2026-07-14",
                "ttl_days": 30,
            }
        ],
        "budgets": {
            "context_tokens": 2_000,
            "wall_seconds": 30,
            "tool_calls": 2,
        },
        "outcomes": {
            "primary": "The requested demonstration is correct.",
            "guardrails": ["Do not modify user files."],
        },
        "evals": {"suite": "evals/suite.yaml"},
        "limitations": ["Does not cover production deployment."],
    }


def _valid_eval_manifest() -> dict:
    return {
        "schema_version": 1,
        "suite": {
            "trials": 3,
            "pass_threshold": 0.8,
            "compare_no_skill": True,
            "min_lift": 0,
        },
        "cases": [
            {
                "id": "positive",
                "category": "positive_trigger",
                "input": "Use the demo skill.",
                "expect": {"selected": True},
            },
            {
                "id": "negative",
                "category": "negative_trigger",
                "input": "Ignore the demo skill.",
                "expect": {"selected": False},
            },
            {
                "id": "output",
                "category": "output_contract",
                "input": "Return the demonstration.",
                "expect": {
                    "output": {"required_substrings": ["demonstration"]}
                },
            },
            {
                "id": "safety",
                "category": "safety",
                "input": "Perform a sensitive action.",
                "expect": {"approvals": {"required": ["sensitive_action"]}},
            },
            {
                "id": "tools",
                "category": "tool_use",
                "input": "Do not call tools.",
                "expect": {"tools": {"max_calls": 0}},
            },
            {
                "id": "regression",
                "category": "regression",
                "input": "Preserve this behavior.",
                "expect": {"selected": True},
            },
            {
                "id": "baseline",
                "category": "baseline",
                "input": "Use the demo skill.",
                "baseline_for": "positive",
                "expect": {
                    "selected": False,
                    "output": {"forbidden_substrings": ["eval-failure"]}
                },
            },
        ],
    }


def _write_skill(
    root: Path,
    *,
    name: str = "demo-skill",
    version: str = "1.2.3",
    contract: dict | None = None,
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\nversion: {version}\ndescription: Demo\n---\n# Demo\n",
        encoding="utf-8",
    )
    if contract is not None:
        (skill_dir / "evals").mkdir()
        (skill_dir / "evals" / "suite.yaml").write_text(
            yaml.safe_dump(_valid_eval_manifest(), sort_keys=False), encoding="utf-8"
        )
        (skill_dir / CONTRACT_FILENAME).write_text(
            yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
        )
    return skill_dir


def test_missing_contract_is_backward_compatible_unless_required(tmp_path):
    skill_dir = _write_skill(tmp_path)

    optional = validate_skill_directory(skill_dir)
    required = validate_skill_directory(skill_dir, require_contract=True)

    assert optional.status == "legacy_unverified"
    assert optional.ok
    assert optional.errors == ()
    assert [issue.code for issue in optional.warnings] == ["legacy_unverified"]
    assert optional.path == skill_dir / CONTRACT_FILENAME
    assert not required.ok
    assert required.status == "invalid"
    assert [issue.code for issue in required.errors] == ["contract_missing"]


def test_valid_contract_cross_checks_identity_and_has_canonical_digest(tmp_path):
    contract = _valid_contract()
    skill_dir = _write_skill(tmp_path, contract=contract)

    reference_time = datetime(2026, 7, 15, tzinfo=timezone.utc)
    first = validate_skill_directory(
        skill_dir,
        require_contract=True,
        reference_time=reference_time,
    )
    (skill_dir / CONTRACT_FILENAME).write_text(
        yaml.safe_dump(contract, sort_keys=True), encoding="utf-8"
    )
    second = validate_skill_directory(
        skill_dir,
        require_contract=True,
        reference_time=reference_time,
    )

    assert first.ok and second.ok
    assert first.status == "verified"
    assert first.contract == contract
    assert first.digest == second.digest
    assert first.digest is not None and len(first.digest) == 64
    assert first.issues == ()


@pytest.mark.parametrize("missing", ["routing", "permissions", "outcomes"])
def test_present_contract_fails_closed_when_required_section_is_missing(
    tmp_path, missing
):
    contract = _valid_contract()
    del contract[missing]
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert result.status == "invalid"
    assert any(
        issue.code == "section_missing" and issue.field == missing
        for issue in result.errors
    )


def test_contract_rejects_identity_drift_and_negative_budgets(tmp_path):
    contract = _valid_contract(name="different-name", version="2.0.0")
    contract["budgets"]["tool_calls"] = -1
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)
    codes = {issue.code for issue in result.errors}

    assert not result.ok
    assert "identity_name_mismatch" in codes
    assert "identity_version_mismatch" in codes
    assert any(issue.field == "budgets.tool_calls" for issue in result.errors)


@pytest.mark.parametrize(
    "suite",
    ["../outside.yaml", "/tmp/outside.yaml", "evals\\suite.yaml", "./evals/suite.yaml"],
)
def test_eval_suite_path_must_be_portable_and_contained(tmp_path, suite):
    contract = _valid_contract()
    contract["evals"]["suite"] = suite
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.code == "eval_suite_unsafe" for issue in result.errors)


def test_eval_suite_must_exist_and_cannot_be_a_symlink(tmp_path):
    contract = _valid_contract()
    skill_dir = _write_skill(tmp_path, contract=contract)
    suite = skill_dir / "evals" / "suite.yaml"
    suite.unlink()
    outside = tmp_path / "outside.yaml"
    outside.write_text("cases: []\n", encoding="utf-8")
    try:
        suite.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.code == "eval_suite_unsafe" for issue in result.errors)


def test_present_contract_fails_closed_when_eval_manifest_is_invalid(tmp_path):
    skill_dir = _write_skill(tmp_path, contract=_valid_contract())
    (skill_dir / "evals" / "suite.yaml").write_text(
        "schema_version: 1\ncases: []\n", encoding="utf-8"
    )

    result = validate_skill_directory(skill_dir, require_contract=True)

    assert not result.ok
    assert result.status == "invalid"
    assert any(issue.code == "eval_field_missing" for issue in result.errors)
    assert any(issue.code == "eval_category_missing" for issue in result.errors)


def test_eval_validator_exception_fails_contract_closed(monkeypatch, tmp_path):
    skill_dir = _write_skill(tmp_path, contract=_valid_contract())

    def fail_safely(_skill_dir, _suite):
        raise RuntimeError("validator unavailable")

    monkeypatch.setattr("agent.skill_contract.validate_eval_manifest", fail_safely)

    result = validate_skill_directory(skill_dir, require_contract=True)

    assert not result.ok
    assert any(
        issue.code == "eval_manifest_validation_failed"
        for issue in result.errors
    )


def test_malformed_contract_is_never_treated_as_legacy(tmp_path):
    skill_dir = _write_skill(tmp_path)
    (skill_dir / CONTRACT_FILENAME).write_text("identity: [\n", encoding="utf-8")

    result = validate_skill_directory(skill_dir)

    assert result.status == "invalid"
    assert not result.ok
    assert result.contract is None
    assert result.digest is None
    assert [issue.code for issue in result.errors] == ["contract_yaml_invalid"]


def test_discovery_is_deterministic_and_ignores_archives_and_support_copies(tmp_path):
    skills = tmp_path / "skills"
    alpha = _write_skill(skills, name="alpha", version="1.0.0")
    beta = _write_skill(skills / "category", name="beta", version="1.0.0")
    copied = alpha / "references" / "copied"
    copied.mkdir(parents=True)
    (copied / "SKILL.md").write_text("# copy\n", encoding="utf-8")
    archived = skills / ".archive" / "old"
    archived.mkdir(parents=True)
    (archived / "SKILL.md").write_text("# old\n", encoding="utf-8")

    assert discover_skill_directories(skills) == (alpha, beta)
    assert discover_skill_directories(skills / "missing") == ()


def test_permission_expansion_reports_authority_and_removed_constraints():
    before = copy.deepcopy(_valid_contract()["permissions"])
    before["toolsets_required"] = ["file"]
    before["actions"]["approval_required"] = ["deploy"]
    before["actions"]["prohibited"] = ["delete"]
    after = copy.deepcopy(before)
    after["toolsets_required"].append("terminal")
    after["files"][0]["access"] = "read_write"
    after["actions"]["approval_required"] = []
    after["actions"]["prohibited"] = []

    assert permission_expansion(before, after) == (
        "permissions.actions.approval_required",
        "permissions.actions.prohibited",
        "permissions.files",
        "permissions.toolsets_required",
    )


def test_permission_expansion_ignores_tightening_and_accepts_whole_contracts():
    before = _valid_contract()
    after = copy.deepcopy(before)
    before["permissions"]["network"] = [
        {"host": "api.example.com", "methods": ["GET"]}
    ]
    after["permissions"]["network"] = []
    after["permissions"]["actions"]["approval_required"] = ["publish"]
    after["permissions"]["actions"]["prohibited"] = ["delete"]

    assert permission_expansion(before, after) == ()


def test_canonical_permission_and_source_collections_are_strictly_typed(tmp_path):
    contract = _valid_contract()
    contract["permissions"]["files"] = {"read": ["workspace"]}
    contract["permissions"]["network"] = ["docs.example.com"]
    contract["sources"] = {"references": []}
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)
    fields = {issue.field for issue in result.errors}

    assert not result.ok
    assert "permissions.files" in fields
    assert "permissions.network[0]" in fields
    assert "sources" in fields


def test_sources_require_quoted_iso_dates_and_nonnegative_ttl(tmp_path):
    contract = _valid_contract()
    contract["sources"][0]["retrieved_at"] = "not-a-date"
    contract["sources"][0]["ttl_days"] = -1
    skill_dir = _write_skill(tmp_path, contract=contract)

    invalid = validate_skill_directory(skill_dir)
    assert {issue.field for issue in invalid.errors} >= {
        "sources[0].retrieved_at",
        "sources[0].ttl_days",
    }

    raw = yaml.safe_dump(_valid_contract(), sort_keys=False).replace(
        "'2026-07-14'", "2026-07-14"
    )
    (skill_dir / CONTRACT_FILENAME).write_text(raw, encoding="utf-8")
    unquoted = validate_skill_directory(skill_dir)

    assert not unquoted.ok
    assert any(
        issue.field == "sources[0].retrieved_at" and "quoted ISO" in issue.message
        for issue in unquoted.errors
    )


@pytest.mark.parametrize(
    "retrieved_at",
    [
        "2025-02-29",
        "2026-07-14T12:00:00",
        "2026-07-14 12:00:00Z",
        "2026-07-14T12:00:60Z",
    ],
)
def test_source_retrieval_time_rejects_impossible_or_ambiguous_values(
    tmp_path, retrieved_at
):
    contract = _valid_contract()
    contract["sources"][0]["retrieved_at"] = retrieved_at
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(
        skill_dir,
        reference_time=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
    )

    assert not result.ok
    assert any(
        issue.code == "source_retrieved_at_invalid"
        and issue.field == "sources[0].retrieved_at"
        for issue in result.errors
    )


def test_source_date_only_and_offset_timestamps_normalize_to_utc(tmp_path):
    contract = _valid_contract()
    contract["sources"] = [
        {
            "url": "https://date.example.com/",
            "retrieved_at": "2024-02-29",
            "ttl_days": 1_000,
        },
        {
            "url": "https://offset.example.com/",
            "retrieved_at": "2026-07-14T02:00:00+02:00",
            "ttl_days": 1,
        },
    ]
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(
        skill_dir,
        reference_time=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert result.ok
    assert [issue.code for issue in result.warnings] == ["source_expired"]
    assert result.warnings[0].field == "sources[1]"
    assert "2026-07-15T00:00:00Z" in result.warnings[0].message


def test_mixed_source_expiry_is_nonfatal_but_blocks_promotion_policy(tmp_path):
    contract = _valid_contract()
    contract["sources"] = [
        {
            "url": "https://stale.example.com/",
            "retrieved_at": "2026-07-01",
            "ttl_days": 1,
        },
        {
            "url": "https://fresh.example.com/",
            "retrieved_at": "2026-07-14",
            "ttl_days": 30,
        },
    ]
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(
        skill_dir,
        require_contract=True,
        reference_time=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
    )

    assert result.ok
    assert result.status == "verified"
    assert [(issue.code, issue.field) for issue in result.warnings] == [
        ("source_expired", "sources[0]")
    ]
    assert source_freshness_blockers(result) == result.warnings


def test_zero_day_ttl_expires_at_the_normalized_retrieval_instant(tmp_path):
    contract = _valid_contract()
    contract["sources"][0].update(
        retrieved_at="2026-07-14T08:00:00-04:00",
        ttl_days=0,
    )
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(
        skill_dir,
        reference_time=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
    )

    assert result.ok
    assert [(issue.code, issue.field) for issue in source_freshness_blockers(result)] == [
        ("source_expired", "sources[0]")
    ]


@pytest.mark.parametrize(
    "offset,expected_ok",
    [
        (SOURCE_FUTURE_SKEW, True),
        (SOURCE_FUTURE_SKEW + timedelta(seconds=1), False),
    ],
)
def test_source_future_skew_has_an_inclusive_five_minute_boundary(
    tmp_path, offset, expected_ok
):
    reference_time = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
    contract = _valid_contract()
    contract["sources"][0]["retrieved_at"] = (
        reference_time + offset
    ).isoformat().replace("+00:00", "Z")
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir, reference_time=reference_time)

    assert result.ok is expected_ok
    future_errors = [
        issue for issue in result.errors if issue.code == "source_retrieved_at_future"
    ]
    assert bool(future_errors) is not expected_ok


def test_source_freshness_reference_time_does_not_change_contract_digest(tmp_path):
    contract = _valid_contract()
    contract["sources"][0].update(retrieved_at="2026-07-14", ttl_days=1)
    skill_dir = _write_skill(tmp_path, contract=contract)

    fresh = validate_skill_directory(
        skill_dir,
        reference_time=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
    )
    expired = validate_skill_directory(
        skill_dir,
        reference_time=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert fresh.ok and expired.ok
    assert source_freshness_blockers(fresh) == ()
    assert source_freshness_blockers(expired)
    assert fresh.contract == expired.contract == contract
    assert fresh.digest == expired.digest


def test_source_freshness_requires_an_aware_reference_time(tmp_path):
    skill_dir = _write_skill(tmp_path, contract=_valid_contract())

    with pytest.raises(ValueError, match="explicit UTC offset"):
        validate_skill_directory(
            skill_dir,
            reference_time=datetime(2026, 7, 14, 12),
        )


def test_duplicate_contract_yaml_keys_fail_closed(tmp_path):
    skill_dir = _write_skill(tmp_path, contract=_valid_contract())
    contract_path = skill_dir / CONTRACT_FILENAME
    raw = contract_path.read_text(encoding="utf-8")
    contract_path.write_text(
        raw.replace("schema_version: 1\n", "schema_version: 1\nschema_version: 1\n", 1),
        encoding="utf-8",
    )

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert result.contract is None
    assert result.digest is None
    assert any(issue.code == "contract_yaml_duplicate_key" for issue in result.errors)


def test_broken_contract_symlink_is_invalid_not_legacy(tmp_path):
    skill_dir = _write_skill(tmp_path)
    try:
        (skill_dir / CONTRACT_FILENAME).symlink_to(skill_dir / "missing-contract.yaml")
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    result = validate_skill_directory(skill_dir)

    assert result.status == "invalid"
    assert not result.ok
    assert any(issue.code == "contract_not_regular_file" for issue in result.errors)
    assert not any(issue.code == "legacy_unverified" for issue in result.warnings)


@pytest.mark.parametrize(
    "content,code",
    [
        (
            "---\nname: demo-skill\nname: duplicate\ndescription: Demo\n---\nBody\n",
            "skill_frontmatter_duplicate_key",
        ),
        (
            "---\nname: demo-skill\ndescription: ''\n---\nBody\n",
            "skill_description_missing",
        ),
        (
            "---\nname: demo-skill\ndescription: Demo\n---\n   \n",
            "skill_body_missing",
        ),
    ],
)
def test_legacy_status_never_masks_malformed_skill_document(tmp_path, content, code):
    skill_dir = _write_skill(tmp_path)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    result = validate_skill_directory(skill_dir)

    assert result.status == "invalid"
    assert not result.ok
    assert any(issue.code == code for issue in result.errors)
    assert any(issue.code == "legacy_unverified" for issue in result.warnings)


def test_legacy_skill_md_symlink_is_invalid(tmp_path):
    skill_dir = _write_skill(tmp_path)
    skill_md = skill_dir / "SKILL.md"
    skill_md.unlink()
    outside = tmp_path / "outside-skill.md"
    outside.write_text(
        "---\nname: demo-skill\ndescription: Demo\n---\nBody\n",
        encoding="utf-8",
    )
    try:
        skill_md.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.code == "skill_missing" for issue in result.errors)


def test_yaml_alias_bomb_is_rejected_before_loading(tmp_path):
    skill_dir = _write_skill(tmp_path, contract=_valid_contract())
    lines = ["a0: &a0 [x, x, x, x, x, x, x, x]"]
    for level in range(1, 9):
        aliases = ", ".join([f"*a{level - 1}"] * 8)
        lines.append(f"a{level}: &a{level} [{aliases}]")
    payload = "\n".join(lines) + "\n"
    assert len(payload.encode("utf-8")) < 1_000
    (skill_dir / CONTRACT_FILENAME).write_text(payload, encoding="utf-8")

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert result.contract is None
    assert any(issue.code == "contract_yaml_unsafe" for issue in result.errors)


def test_oversized_yaml_integer_becomes_invalid_result_not_exception(tmp_path):
    skill_dir = _write_skill(tmp_path, contract=_valid_contract())
    contract_path = skill_dir / CONTRACT_FILENAME
    raw = contract_path.read_text(encoding="utf-8")
    contract_path.write_text(raw + "oversized: " + ("9" * 5_000) + "\n", encoding="utf-8")

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert result.contract is None
    assert any(issue.code == "contract_yaml_invalid" for issue in result.errors)


def test_yaml_nesting_depth_is_bounded(tmp_path):
    skill_dir = _write_skill(tmp_path, contract=_valid_contract())
    deeply_nested = "[" * 70 + "0" + "]" * 70
    (skill_dir / CONTRACT_FILENAME).write_text(
        f"schema_version: 1\nextra: {deeply_nested}\n", encoding="utf-8"
    )

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.code == "contract_yaml_unsafe" for issue in result.errors)


def test_yaml_node_count_is_bounded(tmp_path):
    skill_dir = _write_skill(tmp_path, contract=_valid_contract())
    oversized_sequence = "items:\n" + "".join(
        f"  - item-{index}\n" for index in range(10_050)
    )
    (skill_dir / CONTRACT_FILENAME).write_text(
        oversized_sequence, encoding="utf-8"
    )

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.code == "contract_yaml_unsafe" for issue in result.errors)


def test_raw_permission_section_cannot_hide_behind_permissions_extension_key():
    before = {
        "toolsets_required": ["file"],
        "files": [],
        "network": [],
        "secrets": [],
        "actions": {"reversible": [], "approval_required": [], "prohibited": []},
        "permissions": {},
    }
    after = copy.deepcopy(before)
    after["toolsets_required"].append("terminal")
    after["files"].append({"scope": "workspace", "access": "read_write"})

    assert permission_expansion(before, after) == (
        "permissions.files",
        "permissions.toolsets_required",
    )


def test_canonical_permission_tightening_is_not_expansion():
    before = copy.deepcopy(_valid_contract()["permissions"])
    before["files"][0]["access"] = "read_write"
    before["network"][0]["methods"] = ["GET", "POST"]
    after = copy.deepcopy(before)
    after["files"][0]["access"] = "read"
    after["network"][0]["methods"] = ["GET"]

    assert permission_expansion(before, after) == ()


def test_canonical_permission_additions_are_expansion():
    before = copy.deepcopy(_valid_contract()["permissions"])
    after = copy.deepcopy(before)
    after["files"][0]["access"] = "read_write"
    after["network"][0]["methods"].append("POST")

    assert permission_expansion(before, after) == (
        "permissions.files",
        "permissions.network",
    )


def test_malformed_permission_change_is_conservatively_expansion():
    before = copy.deepcopy(_valid_contract()["permissions"])
    after = copy.deepcopy(before)
    after["files"] = {"workspace": "read"}
    after["network"] = ["docs.example.com"]

    assert permission_expansion(before, after) == (
        "permissions.files",
        "permissions.network",
    )
    assert permission_expansion(after, after) == (
        "permissions.files",
        "permissions.network",
    )


def test_unknown_authority_fields_are_conservatively_expanding():
    before = copy.deepcopy(_valid_contract()["permissions"])
    after = copy.deepcopy(before)
    after["files"][0]["path"] = "../../etc"
    after["network"][0]["proxy"] = "evil.example"

    assert permission_expansion(before, after) == (
        "permissions.files",
        "permissions.network",
    )


@pytest.mark.parametrize(
    "files",
    [
        [{"scope": "project", "access": "read"}],
        [{"scope": "skill", "access": "write"}],
        [
            {"scope": "workspace", "access": "read"},
            {"scope": "workspace", "access": "write"},
        ],
    ],
)
def test_file_authority_uses_closed_unique_scopes_and_read_only_skill(
    tmp_path, files
):
    contract = _valid_contract()
    contract["permissions"]["files"] = files
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.field and issue.field.startswith("permissions.files") for issue in result.errors)


@pytest.mark.parametrize(
    "host",
    [
        "https://example.com",
        "*.example.com",
        "user@example.com",
        "example.com/path",
        "EXAMPLE.com",
        "example.com:0",
        "example.com:080",
        "example.com:65536",
        "bad_host",
    ],
)
def test_network_authority_rejects_noncanonical_hosts(tmp_path, host):
    contract = _valid_contract()
    contract["permissions"]["network"] = [{"host": host, "methods": ["GET"]}]
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.field == "permissions.network[0].host" for issue in result.errors)


@pytest.mark.parametrize(
    "host", ["example.com", "example.com:443", "127.0.0.1:8000", "::1", "[::1]:8000"]
)
def test_network_authority_accepts_canonical_dns_ip_and_ports(tmp_path, host):
    contract = _valid_contract()
    contract["permissions"]["network"] = [{"host": host, "methods": ["GET"]}]
    skill_dir = _write_skill(tmp_path, contract=contract)

    assert validate_skill_directory(skill_dir).ok


@pytest.mark.parametrize("methods", [["get"], ["CONNECT"], ["GET", "GET"]])
def test_network_methods_are_unique_uppercase_closed_set(tmp_path, methods):
    contract = _valid_contract()
    contract["permissions"]["network"][0]["methods"] = methods
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.field == "permissions.network[0].methods" for issue in result.errors)


@pytest.mark.parametrize(
    "secret", ["github_token", "GITHUB-TOKEN", "1TOKEN", "_TOKEN"]
)
def test_secret_permissions_use_environment_variable_names(tmp_path, secret):
    contract = _valid_contract()
    contract["permissions"]["secrets"] = [secret]
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.field == "permissions.secrets[0]" for issue in result.errors)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/docs",
        "https://user:password@example.com/docs",
        "file:///tmp/docs",
        "https:///missing-host",
        "https://*/docs",
    ],
)
def test_sources_require_https_host_without_credentials(tmp_path, url):
    contract = _valid_contract()
    contract["sources"][0]["url"] = url
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.field == "sources[0].url" for issue in result.errors)


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8000/docs", "http://127.0.0.1/docs", "http://[::1]:8000/docs"],
)
def test_sources_allow_http_only_for_loopback_development(tmp_path, url):
    contract = _valid_contract()
    contract["sources"][0]["url"] = url
    skill_dir = _write_skill(tmp_path, contract=contract)

    assert validate_skill_directory(skill_dir).ok


@pytest.mark.parametrize("missing", ["requires", "conflicts"])
def test_routing_dependency_and_conflict_lists_are_required(tmp_path, missing):
    contract = _valid_contract()
    del contract["routing"][missing]
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.field == f"routing.{missing}" for issue in result.errors)


def test_unknown_governance_and_authority_keys_fail_closed(tmp_path):
    contract = _valid_contract()
    contract["extension"] = True
    contract["identity"]["publisher"] = "someone"
    contract["compatibility"]["runtimes"] = ["python"]
    contract["routing"]["fallback"] = "other-skill"
    contract["interface"]["inputs"][0]["schema"] = "free-form"
    contract["permissions"]["ambient"] = True
    contract["permissions"]["files"][0]["path"] = "../../etc"
    contract["permissions"]["network"][0]["proxy"] = "evil.example"
    contract["permissions"]["actions"]["unreviewed"] = ["publish"]
    contract["sources"][0]["trusted"] = True
    contract["budgets"]["cost_usd"] = 10
    contract["outcomes"]["secondary"] = "engagement"
    contract["evals"]["trials"] = 3
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)
    unknown_fields = {
        issue.field for issue in result.errors if issue.code == "field_unknown"
    }

    assert unknown_fields == {
        "extension",
        "identity.publisher",
        "compatibility.runtimes",
        "routing.fallback",
        "interface.inputs[0].schema",
        "permissions.ambient",
        "permissions.files[0].path",
        "permissions.network[0].proxy",
        "permissions.actions.unreviewed",
        "sources[0].trusted",
        "budgets.cost_usd",
        "outcomes.secondary",
        "evals.trials",
    }


def test_interface_requires_closed_descriptor_mappings(tmp_path):
    contract = _valid_contract()
    contract["interface"]["inputs"] = ["request"]
    contract["interface"]["outputs"] = [
        {"name": "receipt", "type": "object", "required": "yes"}
    ]
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert {issue.field for issue in result.errors} >= {
        "interface.inputs[0]",
        "interface.outputs[0].required",
    }


def test_network_methods_cannot_be_empty(tmp_path):
    contract = _valid_contract()
    contract["permissions"]["network"][0]["methods"] = []
    skill_dir = _write_skill(tmp_path, contract=contract)

    result = validate_skill_directory(skill_dir)

    assert not result.ok
    assert any(issue.field == "permissions.network[0].methods" for issue in result.errors)
