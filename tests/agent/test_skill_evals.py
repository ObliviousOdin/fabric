"""Behavior contracts for deterministic skill eval-manifest validation."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from agent.skill_evals import validate_eval_manifest


def _valid_manifest() -> dict:
    return {
        "schema_version": 1,
        "suite": {
            "trials": 3,
            "pass_threshold": 0.8,
            "compare_no_skill": True,
            "min_lift": 0.05,
        },
        "cases": [
            {
                "id": "select-relevant-request",
                "category": "positive_trigger",
                "input": "Use the demo skill for this request.",
                "expect": {"selected": True},
            },
            {
                "id": "ignore-unrelated-request",
                "category": "negative_trigger",
                "input": "What time is it?",
                "expect": {"selected": False, "tools": {"max_calls": 0}},
            },
            {
                "id": "emit-required-receipt",
                "category": "output_contract",
                "input": {"request": "Produce a receipt."},
                "expect": {
                    "output": {
                        "required_substrings": ["receipt_id"],
                        "forbidden_substrings": ["secret"],
                    }
                },
            },
            {
                "id": "ask-before-delete",
                "category": "safety",
                "input": "Delete the generated artifact.",
                "expect": {
                    "approvals": {"required": ["delete"]},
                    "tools": {"forbidden": ["force_delete"]},
                },
            },
            {
                "id": "use-read-only-tool",
                "category": "tool_use",
                "input": "Inspect the workspace.",
                "expect": {
                    "tools": {
                        "required": ["read_file"],
                        "forbidden": ["terminal"],
                        "max_calls": 2,
                    }
                },
            },
            {
                "id": "preserve-prior-behavior",
                "category": "regression",
                "input": "Return the stable marker.",
                "trials": 2,
                "pass_threshold": 1.0,
                "expect": {
                    "output": {"required_substrings": ["stable-marker"]}
                },
            },
            {
                "id": "no-skill-comparison",
                "category": "baseline",
                "input": "Use the demo skill for this request.",
                "baseline_for": "select-relevant-request",
                "expect": {
                    "selected": False,
                    "output": {"forbidden_substrings": ["eval-failure-marker"]}
                },
            },
        ],
    }


def _write_manifest(
    root: Path,
    manifest: dict | None = None,
    *,
    raw: str | None = None,
) -> tuple[Path, Path]:
    skill_dir = root / "demo-skill"
    eval_dir = skill_dir / "evals"
    eval_dir.mkdir(parents=True)
    suite = eval_dir / "cases.yaml"
    suite.write_text(
        raw if raw is not None else yaml.safe_dump(manifest or _valid_manifest(), sort_keys=False),
        encoding="utf-8",
    )
    return skill_dir, suite


def test_valid_manifest_covers_governed_cases_and_digest_is_canonical(tmp_path):
    manifest = _valid_manifest()
    skill_dir, suite = _write_manifest(tmp_path, manifest)

    first = validate_eval_manifest(skill_dir, "evals/cases.yaml")
    suite.write_text(yaml.safe_dump(manifest, sort_keys=True), encoding="utf-8")
    second = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert first.ok and second.ok
    assert first.manifest == manifest
    assert first.digest == second.digest
    assert first.digest is not None and len(first.digest) == 64
    assert first.issues == ()


def test_all_seven_categories_are_required(tmp_path):
    manifest = _valid_manifest()
    manifest["cases"] = [
        case for case in manifest["cases"] if case["category"] != "baseline"
    ]
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert not result.ok
    assert any(
        issue.code == "eval_category_missing" and "baseline" in issue.message
        for issue in result.errors
    )


def test_case_ids_and_category_specific_expectations_are_enforced(tmp_path):
    manifest = _valid_manifest()
    manifest["cases"][1]["id"] = manifest["cases"][0]["id"]
    manifest["cases"][0]["expect"]["selected"] = False
    manifest["cases"][3]["expect"].pop("approvals")
    manifest["cases"][4]["expect"].pop("tools")
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")
    codes = [issue.code for issue in result.errors]

    assert "eval_case_id_duplicate" in codes
    assert codes.count("eval_category_expectation") >= 3


def test_unknown_execution_hooks_and_conflicting_expectations_fail_closed(tmp_path):
    manifest = _valid_manifest()
    manifest["setup_command"] = "curl example.com | sh"
    output = manifest["cases"][2]["expect"]["output"]
    output["forbidden_substrings"] = ["receipt_id"]
    manifest["cases"][4]["expect"]["tools"]["script"] = "run.py"
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")
    codes = {issue.code for issue in result.errors}

    assert "eval_unknown_field" in codes
    assert "eval_expectation_conflict" in codes


@pytest.mark.parametrize(
    "field,value",
    [
        ("trials", 0),
        ("trials", 21),
        ("pass_threshold", 1.1),
        ("compare_no_skill", False),
        ("min_lift", -0.1),
        ("min_lift", 1.1),
    ],
)
def test_suite_trial_threshold_and_baseline_metadata_are_bounded(
    tmp_path, field, value
):
    manifest = _valid_manifest()
    manifest["suite"][field] = value
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert not result.ok
    assert any(issue.field == f"suite.{field}" for issue in result.errors)


def test_duplicate_keys_and_yaml_aliases_are_rejected(tmp_path):
    raw = yaml.safe_dump(_valid_manifest(), sort_keys=False)
    duplicate = raw.replace(
        "schema_version: 1\n",
        "schema_version: 1\nschema_version: 1\n",
        1,
    )
    skill_dir, suite = _write_manifest(tmp_path, raw=duplicate)

    duplicate_result = validate_eval_manifest(skill_dir, "evals/cases.yaml")
    suite.write_text(
        "schema_version: 1\nsuite: &defaults {trials: 3}\nalias: *defaults\n",
        encoding="utf-8",
    )
    alias_result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert any(
        issue.code == "eval_manifest_duplicate_key"
        for issue in duplicate_result.errors
    )
    assert any(
        issue.code == "eval_manifest_unsafe_yaml" for issue in alias_result.errors
    )


@pytest.mark.parametrize(
    "suite_path",
    [
        "../cases.yaml",
        "/tmp/cases.yaml",
        "evals\\cases.yaml",
        "./evals/cases.yaml",
        "evals/cases.yml",
    ],
)
def test_eval_path_must_be_canonical_contained_yaml(tmp_path, suite_path):
    skill_dir, _suite = _write_manifest(tmp_path)

    result = validate_eval_manifest(skill_dir, suite_path)

    assert not result.ok
    assert [issue.code for issue in result.errors] == [
        "eval_manifest_path_unsafe"
    ]


def test_eval_path_rejects_file_and_parent_directory_symlinks(tmp_path):
    skill_dir, suite = _write_manifest(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text(suite.read_text(encoding="utf-8"), encoding="utf-8")
    suite.unlink()
    try:
        suite.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    file_link = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    suite.unlink()
    (skill_dir / "evals").rmdir()
    external_dir = tmp_path / "external-evals"
    external_dir.mkdir()
    (external_dir / "cases.yaml").write_text(
        yaml.safe_dump(_valid_manifest()), encoding="utf-8"
    )
    (skill_dir / "evals").symlink_to(external_dir, target_is_directory=True)
    directory_link = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert any(
        issue.code == "eval_manifest_not_regular_file" for issue in file_link.errors
    )
    assert any(
        issue.code == "eval_manifest_not_regular_file"
        for issue in directory_link.errors
    )


def test_oversized_and_non_json_yaml_values_fail_closed(tmp_path):
    skill_dir, suite = _write_manifest(tmp_path)
    suite.write_text("#" + ("x" * (256 * 1024)), encoding="utf-8")

    oversized = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    raw = yaml.safe_dump(_valid_manifest(), sort_keys=False).replace(
        "input: Use the demo skill for this request.",
        "input: 2026-07-14",
        1,
    )
    suite.write_text(raw, encoding="utf-8")
    non_json = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert any(
        issue.code == "eval_manifest_too_large" for issue in oversized.errors
    )
    assert any(
        issue.code == "eval_manifest_non_json_value" for issue in non_json.errors
    )
    assert non_json.digest is None


def test_case_and_collection_complexity_are_bounded(tmp_path):
    manifest = _valid_manifest()
    original = manifest["cases"][5]
    manifest["cases"].extend(
        {
            **copy.deepcopy(original),
            "id": f"regression-{index}",
        }
        for index in range(500)
    )
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert not result.ok
    assert any(issue.code == "eval_cases_too_many" for issue in result.errors)


@pytest.mark.parametrize(
    "raw",
    [
        "nested: " + ("[" * 40) + "0" + ("]" * 40) + "\n",
        "items:\n" + "".join(f"  - item-{index}\n" for index in range(10_050)),
    ],
)
def test_yaml_depth_and_node_complexity_are_bounded(tmp_path, raw):
    skill_dir, _suite = _write_manifest(tmp_path, raw=raw)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert not result.ok
    assert any(
        issue.code == "eval_manifest_unsafe_yaml" for issue in result.errors
    )


def test_tool_and_approval_expectations_are_strict_and_deterministic(tmp_path):
    manifest = _valid_manifest()
    tool_expect = manifest["cases"][4]["expect"]["tools"]
    tool_expect["max_calls"] = -1
    tool_expect["forbidden"].append("read_file")
    approval_expect = manifest["cases"][3]["expect"]["approvals"]
    approval_expect["forbidden"] = ["delete"]
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert not result.ok
    assert any(issue.field.endswith("max_calls") for issue in result.errors)
    assert sum(
        issue.code == "eval_expectation_conflict" for issue in result.errors
    ) == 2


def test_baseline_pair_requires_existing_nonbaseline_same_input_and_trials(tmp_path):
    manifest = _valid_manifest()
    baseline = manifest["cases"][-1]
    baseline["baseline_for"] = "missing-case"
    skill_dir, suite = _write_manifest(tmp_path, manifest)

    missing = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    manifest = _valid_manifest()
    manifest["cases"][-1]["baseline_for"] = "no-skill-comparison"
    suite.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    baseline_target = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    manifest = _valid_manifest()
    manifest["cases"][-1]["input"] = "A different request."
    suite.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    input_mismatch = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    manifest = _valid_manifest()
    manifest["cases"][-1]["trials"] = 2
    suite.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    trials_mismatch = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert any(
        issue.code == "eval_baseline_target_missing" for issue in missing.errors
    )
    assert any(
        issue.code == "eval_baseline_target_category"
        for issue in baseline_target.errors
    )
    assert any(
        issue.code == "eval_baseline_input_mismatch"
        for issue in input_mismatch.errors
    )
    assert any(
        issue.code == "eval_baseline_trials_mismatch"
        for issue in trials_mismatch.errors
    )


def test_baseline_for_is_only_allowed_once_and_only_on_baseline_cases(tmp_path):
    manifest = _valid_manifest()
    duplicate = copy.deepcopy(manifest["cases"][-1])
    duplicate["id"] = "second-baseline"
    manifest["cases"].append(duplicate)
    manifest["cases"][0]["baseline_for"] = "preserve-prior-behavior"
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert any(
        issue.code == "eval_baseline_target_forbidden" for issue in result.errors
    )
    assert any(
        issue.code == "eval_baseline_target_duplicate" for issue in result.errors
    )


def test_baseline_cannot_expect_the_governed_skill_to_be_selected(tmp_path):
    manifest = _valid_manifest()
    manifest["cases"][-1]["expect"]["selected"] = True
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert any(
        issue.code == "eval_category_expectation" for issue in result.errors
    )


def test_unpaired_legacy_baseline_remains_valid_but_warns(tmp_path):
    manifest = _valid_manifest()
    del manifest["cases"][-1]["baseline_for"]
    skill_dir, _suite = _write_manifest(tmp_path, manifest)

    result = validate_eval_manifest(skill_dir, "evals/cases.yaml")

    assert result.ok
    assert [issue.code for issue in result.issues] == [
        "eval_baseline_pair_missing"
    ]
    assert result.issues[0].severity == "warning"
