"""Deterministic validation for governed skill evaluation manifests.

The manifest is data, never executable configuration.  This module parses a
bounded, alias-free YAML subset and validates assertions that a future eval
harness can apply to recorded outputs, tool calls, and approval events.  It
does not import providers, call models, execute hooks, or mutate a skill.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


EVAL_SCHEMA_VERSION = 1

_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_YAML_NODES = 10_000
_MAX_YAML_DEPTH = 32
_MAX_CASES = 500
_MAX_LIST_ITEMS = 256
_MAX_TRIALS = 20
_MAX_STRING_BYTES = 32 * 1024

_CATEGORIES = frozenset(
    {
        "positive_trigger",
        "negative_trigger",
        "output_contract",
        "safety",
        "tool_use",
        "regression",
        "baseline",
    }
)
_ROOT_KEYS = frozenset({"schema_version", "suite", "cases"})
_SUITE_KEYS = frozenset(
    {"trials", "pass_threshold", "compare_no_skill", "min_lift"}
)
_CASE_KEYS = frozenset(
    {
        "id",
        "category",
        "input",
        "trials",
        "pass_threshold",
        "baseline_for",
        "expect",
    }
)
_EXPECT_KEYS = frozenset({"selected", "output", "tools", "approvals"})
_OUTPUT_KEYS = frozenset({"required_substrings", "forbidden_substrings"})
_TOOLS_KEYS = frozenset({"required", "forbidden", "max_calls"})
_APPROVAL_KEYS = frozenset({"required", "forbidden"})
_CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class _DuplicateYamlKeyError(ValueError):
    """Raised when YAML contains an ambiguous mapping key."""


class _UnsafeYamlStructureError(ValueError):
    """Raised when YAML exceeds the supported data-only subset."""


@dataclass(frozen=True)
class EvalManifestIssue:
    """One stable, machine-readable eval-manifest finding."""

    severity: str
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class EvalManifestValidation:
    """Validation result for one deterministic eval manifest."""

    path: Path
    manifest: dict[str, Any] | None
    digest: str | None
    issues: tuple[EvalManifestIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> tuple[EvalManifestIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")


def validate_eval_manifest(
    skill_dir: Path,
    suite_path: str,
) -> EvalManifestValidation:
    """Validate a contained, regular eval manifest without executing it."""

    skill_dir = Path(skill_dir)
    candidate = _candidate_path(skill_dir, suite_path)
    issues: list[EvalManifestIssue] = []

    if candidate is None:
        fallback = skill_dir / str(suite_path)
        _error(
            issues,
            "eval_manifest_path_unsafe",
            "eval suite must be a canonical relative .yaml path inside the skill",
            "evals.suite",
        )
        return EvalManifestValidation(fallback, None, None, tuple(issues))

    if not _contained_regular_file(skill_dir, candidate):
        _error(
            issues,
            "eval_manifest_not_regular_file",
            "eval suite must be an existing regular file and traverse no symlinks",
            "evals.suite",
        )
        return EvalManifestValidation(candidate, None, None, tuple(issues))

    try:
        size = candidate.stat().st_size
    except OSError as exc:
        _error(
            issues,
            "eval_manifest_read_failed",
            f"could not stat eval manifest: {exc}",
        )
        return EvalManifestValidation(candidate, None, None, tuple(issues))
    if size > _MAX_MANIFEST_BYTES:
        _error(
            issues,
            "eval_manifest_too_large",
            f"eval manifest exceeds {_MAX_MANIFEST_BYTES} bytes",
        )
        return EvalManifestValidation(candidate, None, None, tuple(issues))

    try:
        raw = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _error(
            issues,
            "eval_manifest_read_failed",
            f"could not read eval manifest: {exc}",
        )
        return EvalManifestValidation(candidate, None, None, tuple(issues))

    try:
        _check_yaml_structure(raw)
        loaded = yaml.safe_load(raw)
    except _DuplicateYamlKeyError as exc:
        _error(issues, "eval_manifest_duplicate_key", str(exc))
        return EvalManifestValidation(candidate, None, None, tuple(issues))
    except _UnsafeYamlStructureError as exc:
        _error(issues, "eval_manifest_unsafe_yaml", str(exc))
        return EvalManifestValidation(candidate, None, None, tuple(issues))
    except (yaml.YAMLError, ValueError, RecursionError) as exc:
        _error(
            issues,
            "eval_manifest_yaml_invalid",
            f"invalid eval manifest YAML: {exc}",
        )
        return EvalManifestValidation(candidate, None, None, tuple(issues))

    if not isinstance(loaded, dict):
        _error(
            issues,
            "eval_manifest_not_mapping",
            "eval manifest root must be a mapping",
        )
        return EvalManifestValidation(candidate, None, None, tuple(issues))

    manifest: dict[str, Any] = loaded
    canonical_problem = _find_noncanonical_value(manifest)
    if canonical_problem is not None:
        field, message = canonical_problem
        _error(issues, "eval_manifest_non_json_value", message, field)
        digest = None
    else:
        digest = _canonical_digest(manifest)

    _validate_schema(manifest, issues)
    return EvalManifestValidation(candidate, manifest, digest, tuple(issues))


def _candidate_path(skill_dir: Path, suite_path: str) -> Path | None:
    if not isinstance(suite_path, str) or not suite_path or "\x00" in suite_path:
        return None
    if "\\" in suite_path or suite_path.startswith("/"):
        return None
    if re.match(r"^[A-Za-z]:", suite_path):
        return None
    if any(part in {"", ".", ".."} for part in suite_path.split("/")):
        return None
    pure = PurePosixPath(suite_path)
    if pure.suffix != ".yaml":
        return None
    return skill_dir.joinpath(*pure.parts)


def _contained_regular_file(skill_dir: Path, candidate: Path) -> bool:
    try:
        root_mode = skill_dir.lstat().st_mode
        if not stat.S_ISDIR(root_mode) or skill_dir.is_symlink():
            return False
        root_resolved = skill_dir.resolve(strict=True)
        candidate_resolved = candidate.resolve(strict=True)
        candidate_resolved.relative_to(root_resolved)

        relative = candidate.relative_to(skill_dir)
        current = skill_dir
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        mode = candidate.lstat().st_mode
        return stat.S_ISREG(mode) and not candidate.is_symlink()
    except (OSError, ValueError):
        return False


def _check_yaml_structure(raw: str) -> None:
    token_count = 0
    for token in yaml.scan(raw, Loader=yaml.SafeLoader):
        token_count += 1
        if token_count > _MAX_YAML_NODES * 4:
            raise _UnsafeYamlStructureError(
                f"YAML token count exceeds {_MAX_YAML_NODES * 4}"
            )
        if isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)):
            raise _UnsafeYamlStructureError(
                "YAML anchors and aliases are not supported"
            )

    document = yaml.compose(raw, Loader=yaml.SafeLoader)
    node_count = 0

    def visit(node: yaml.Node, field: str = "", depth: int = 0) -> None:
        nonlocal node_count
        if depth > _MAX_YAML_DEPTH:
            raise _UnsafeYamlStructureError(
                f"YAML nesting exceeds {_MAX_YAML_DEPTH} levels"
            )
        node_count += 1
        if node_count > _MAX_YAML_NODES:
            raise _UnsafeYamlStructureError(
                f"YAML node count exceeds {_MAX_YAML_NODES}"
            )

        if isinstance(node, yaml.MappingNode):
            seen: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                key_text = str(key_node.value)
                key = (key_node.tag, key_text)
                if key in seen:
                    location = f" at {field}" if field else ""
                    raise _DuplicateYamlKeyError(
                        f"duplicate YAML key {key_text!r}{location}"
                    )
                seen.add(key)
                child = f"{field}.{key_text}" if field else key_text
                visit(key_node, f"{child}.__key__", depth + 1)
                visit(value_node, child, depth + 1)
        elif isinstance(node, yaml.SequenceNode):
            for index, child in enumerate(node.value):
                visit(child, f"{field}[{index}]", depth + 1)

    if document is not None:
        visit(document)


def _find_noncanonical_value(
    value: Any,
    field: str = "",
    ancestors: set[int] | None = None,
) -> tuple[str | None, str] | None:
    ancestors = set() if ancestors is None else ancestors
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value.encode("utf-8")) > _MAX_STRING_BYTES:
            return field or None, f"strings must not exceed {_MAX_STRING_BYTES} bytes"
        return None
    if isinstance(value, float):
        if math.isfinite(value):
            return None
        return field or None, "numbers must be finite"
    if isinstance(value, (dict, list)):
        marker = id(value)
        if marker in ancestors:
            return field or None, "recursive values are not supported"
        ancestors.add(marker)
        try:
            if isinstance(value, dict):
                for key, child in value.items():
                    if not isinstance(key, str):
                        return field or None, "mapping keys must be strings"
                    child_field = f"{field}.{key}" if field else key
                    problem = _find_noncanonical_value(child, child_field, ancestors)
                    if problem is not None:
                        return problem
            else:
                if len(value) > _MAX_LIST_ITEMS and field != "cases":
                    return field or None, (
                        f"lists must not exceed {_MAX_LIST_ITEMS} entries"
                    )
                for index, child in enumerate(value):
                    child_field = f"{field}[{index}]" if field else f"[{index}]"
                    problem = _find_noncanonical_value(child, child_field, ancestors)
                    if problem is not None:
                        return problem
        finally:
            ancestors.remove(marker)
        return None
    return field or None, f"unsupported YAML value type: {type(value).__name__}"


def _canonical_digest(manifest: Mapping[str, Any]) -> str:
    payload = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_schema(
    manifest: Mapping[str, Any],
    issues: list[EvalManifestIssue],
) -> None:
    _reject_unknown_keys(manifest, _ROOT_KEYS, "", issues)
    version = manifest.get("schema_version")
    if type(version) is not int or version != EVAL_SCHEMA_VERSION:
        _error(
            issues,
            "eval_schema_version_unsupported",
            f"schema_version must be {EVAL_SCHEMA_VERSION}",
            "schema_version",
        )

    suite = _required_mapping(manifest, "suite", "", issues)
    if suite is not None:
        _validate_suite(suite, issues)

    cases = manifest.get("cases")
    if not isinstance(cases, list):
        _error(issues, "eval_field_type", "cases must be a list", "cases")
        return
    if not cases:
        _error(issues, "eval_cases_empty", "cases must not be empty", "cases")
    if len(cases) > _MAX_CASES:
        _error(
            issues,
            "eval_cases_too_many",
            f"cases must not exceed {_MAX_CASES} entries",
            "cases",
        )

    seen_ids: set[str] = set()
    seen_categories: set[str] = set()
    for index, case in enumerate(cases[:_MAX_CASES]):
        field = f"cases[{index}]"
        if not isinstance(case, dict):
            _error(issues, "eval_field_type", f"{field} must be a mapping", field)
            continue
        category = _validate_case(case, field, seen_ids, issues)
        if category is not None:
            seen_categories.add(category)

    if isinstance(suite, Mapping):
        _validate_baseline_pairs(cases[:_MAX_CASES], suite, issues)

    for category in sorted(_CATEGORIES - seen_categories):
        _error(
            issues,
            "eval_category_missing",
            f"cases must include category {category!r}",
            "cases",
        )


def _validate_suite(
    suite: Mapping[str, Any],
    issues: list[EvalManifestIssue],
) -> None:
    _reject_unknown_keys(suite, _SUITE_KEYS, "suite", issues)
    _validate_trials(suite, "trials", "suite.trials", issues, required=True)
    _validate_ratio(
        suite,
        "pass_threshold",
        "suite.pass_threshold",
        issues,
        required=True,
    )
    compare = suite.get("compare_no_skill")
    if type(compare) is not bool:
        _error(
            issues,
            "eval_field_type",
            "suite.compare_no_skill must be true",
            "suite.compare_no_skill",
        )
    elif not compare:
        _error(
            issues,
            "eval_field_value",
            "suite.compare_no_skill must be true for governed evals",
            "suite.compare_no_skill",
        )
    if "min_lift" in suite:
        value = suite["min_lift"]
        if (
            not _is_number(value)
            or not math.isfinite(float(value))
            or not 0 <= value <= 1
        ):
            _error(
                issues,
                "eval_field_value",
                "suite.min_lift must be a finite number from 0 to 1",
                "suite.min_lift",
            )


def _validate_case(
    case: Mapping[str, Any],
    field: str,
    seen_ids: set[str],
    issues: list[EvalManifestIssue],
) -> str | None:
    _reject_unknown_keys(case, _CASE_KEYS, field, issues)
    case_id = case.get("id")
    if not isinstance(case_id, str) or not _CASE_ID_RE.fullmatch(case_id):
        _error(
            issues,
            "eval_case_id_invalid",
            f"{field}.id must be a lowercase portable identifier",
            f"{field}.id",
        )
    elif case_id in seen_ids:
        _error(
            issues,
            "eval_case_id_duplicate",
            f"duplicate eval case id {case_id!r}",
            f"{field}.id",
        )
    else:
        seen_ids.add(case_id)

    category = case.get("category")
    valid_category: str | None = None
    if not isinstance(category, str) or category not in _CATEGORIES:
        _error(
            issues,
            "eval_category_invalid",
            f"{field}.category must be one of {', '.join(sorted(_CATEGORIES))}",
            f"{field}.category",
        )
    else:
        valid_category = category

    baseline_for = case.get("baseline_for")
    if "baseline_for" in case and (
        not isinstance(baseline_for, str)
        or not _CASE_ID_RE.fullmatch(baseline_for)
    ):
        _error(
            issues,
            "eval_baseline_target_invalid",
            f"{field}.baseline_for must be a lowercase portable case identifier",
            f"{field}.baseline_for",
        )
    if "baseline_for" in case and valid_category != "baseline":
        _error(
            issues,
            "eval_baseline_target_forbidden",
            "baseline_for is supported only on baseline cases",
            f"{field}.baseline_for",
        )

    input_value = case.get("input")
    if not (
        isinstance(input_value, str) and bool(input_value.strip())
    ) and not (isinstance(input_value, dict) and bool(input_value)):
        _error(
            issues,
            "eval_input_invalid",
            f"{field}.input must be a non-empty string or non-empty data mapping",
            f"{field}.input",
        )

    _validate_trials(case, "trials", f"{field}.trials", issues, required=False)
    _validate_ratio(
        case,
        "pass_threshold",
        f"{field}.pass_threshold",
        issues,
        required=False,
    )

    expect = _required_mapping(case, "expect", field, issues)
    if expect is not None:
        _validate_expect(expect, valid_category, f"{field}.expect", issues)
    return valid_category


def _validate_baseline_pairs(
    cases: list[Any],
    suite: Mapping[str, Any],
    issues: list[EvalManifestIssue],
) -> None:
    """Validate optional v1 baseline links without breaking older manifests.

    ``baseline_for`` is additive in schema v1.  Older manifests remain valid,
    but receive a warning and cannot be executed by the first-class runner
    until their baseline cases are paired explicitly.
    """

    indexed: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            continue
        case_id = case.get("id")
        if (
            isinstance(case_id, str)
            and _CASE_ID_RE.fullmatch(case_id)
            and case_id not in indexed
        ):
            indexed[case_id] = (index, case)

    paired_targets: dict[str, int] = {}
    suite_trials = suite.get("trials")
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping) or case.get("category") != "baseline":
            continue
        field = f"cases[{index}].baseline_for"
        if "baseline_for" not in case:
            _warning(
                issues,
                "eval_baseline_pair_missing",
                "baseline case has no baseline_for link and cannot be run for lift",
                field,
            )
            continue

        target_id = case.get("baseline_for")
        if not isinstance(target_id, str) or not _CASE_ID_RE.fullmatch(target_id):
            continue
        target_entry = indexed.get(target_id)
        if target_entry is None:
            _error(
                issues,
                "eval_baseline_target_missing",
                f"baseline_for references unknown case {target_id!r}",
                field,
            )
            continue

        target_index, target = target_entry
        if target.get("category") == "baseline":
            _error(
                issues,
                "eval_baseline_target_category",
                "baseline_for must reference a non-baseline case",
                field,
            )
            continue
        if target_id in paired_targets:
            prior = paired_targets[target_id]
            _error(
                issues,
                "eval_baseline_target_duplicate",
                (
                    f"baseline_for target {target_id!r} is already paired by "
                    f"cases[{prior}]"
                ),
                field,
            )
            continue
        paired_targets[target_id] = index

        if _canonical_value(case.get("input")) != _canonical_value(
            target.get("input")
        ):
            _error(
                issues,
                "eval_baseline_input_mismatch",
                (
                    "baseline input must exactly match its paired case input; "
                    f"target is cases[{target_index}]"
                ),
                f"cases[{index}].input",
            )

        baseline_trials = case.get("trials", suite_trials)
        target_trials = target.get("trials", suite_trials)
        if (
            type(baseline_trials) is int
            and type(target_trials) is int
            and baseline_trials != target_trials
        ):
            _error(
                issues,
                "eval_baseline_trials_mismatch",
                (
                    "baseline and paired case must use the same effective trial "
                    f"count; target is cases[{target_index}]"
                ),
                f"cases[{index}].trials",
            )


def _canonical_value(value: Any) -> bytes | None:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return None


def _validate_expect(
    expect: Mapping[str, Any],
    category: str | None,
    field: str,
    issues: list[EvalManifestIssue],
) -> None:
    _reject_unknown_keys(expect, _EXPECT_KEYS, field, issues)
    selected = expect.get("selected")
    if "selected" in expect and type(selected) is not bool:
        _error(
            issues,
            "eval_field_type",
            f"{field}.selected must be a boolean",
            f"{field}.selected",
        )

    output = _optional_mapping(expect, "output", field, issues)
    tools = _optional_mapping(expect, "tools", field, issues)
    approvals = _optional_mapping(expect, "approvals", field, issues)
    output_has_assertion = False
    tools_has_assertion = False
    approvals_has_assertion = False
    if output is not None:
        output_has_assertion = _validate_list_expectation(
            output, _OUTPUT_KEYS, f"{field}.output", issues
        )
    if tools is not None:
        tools_has_assertion = _validate_tool_expectation(
            tools, f"{field}.tools", issues
        )
    if approvals is not None:
        approvals_has_assertion = _validate_list_expectation(
            approvals, _APPROVAL_KEYS, f"{field}.approvals", issues
        )

    if (
        "selected" not in expect
        and not output_has_assertion
        and not tools_has_assertion
        and not approvals_has_assertion
    ):
        _error(
            issues,
            "eval_expectation_empty",
            f"{field} must contain at least one deterministic assertion",
            field,
        )

    if category == "positive_trigger" and selected is not True:
        _error(
            issues,
            "eval_category_expectation",
            "positive_trigger cases must expect selected: true",
            f"{field}.selected",
        )
    elif category == "negative_trigger" and selected is not False:
        _error(
            issues,
            "eval_category_expectation",
            "negative_trigger cases must expect selected: false",
            f"{field}.selected",
        )
    elif category == "baseline" and selected is True:
        _error(
            issues,
            "eval_category_expectation",
            "baseline cases cannot expect the governed skill to be selected",
            f"{field}.selected",
        )
    elif category == "output_contract" and not output_has_assertion:
        _error(
            issues,
            "eval_category_expectation",
            "output_contract cases must declare output assertions",
            f"{field}.output",
        )
    elif category == "tool_use" and not tools_has_assertion:
        _error(
            issues,
            "eval_category_expectation",
            "tool_use cases must declare tool assertions",
            f"{field}.tools",
        )
    elif category == "safety" and not approvals_has_assertion:
        _error(
            issues,
            "eval_category_expectation",
            "safety cases must declare approval assertions",
            f"{field}.approvals",
        )


def _validate_list_expectation(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    field: str,
    issues: list[EvalManifestIssue],
) -> bool:
    _reject_unknown_keys(value, allowed, field, issues)
    required = _string_list(value, "required" if field.endswith("approvals") else "required_substrings", field, issues)
    forbidden = _string_list(value, "forbidden" if field.endswith("approvals") else "forbidden_substrings", field, issues)
    overlap = set(required) & set(forbidden)
    if overlap:
        _error(
            issues,
            "eval_expectation_conflict",
            f"{field} required and forbidden entries overlap: {', '.join(sorted(overlap))}",
            field,
        )
    return bool(required or forbidden)


def _validate_tool_expectation(
    tools: Mapping[str, Any],
    field: str,
    issues: list[EvalManifestIssue],
) -> bool:
    _reject_unknown_keys(tools, _TOOLS_KEYS, field, issues)
    required = _string_list(tools, "required", field, issues)
    forbidden = _string_list(tools, "forbidden", field, issues)
    overlap = set(required) & set(forbidden)
    if overlap:
        _error(
            issues,
            "eval_expectation_conflict",
            f"{field} required and forbidden tools overlap: {', '.join(sorted(overlap))}",
            field,
        )
    if "max_calls" in tools:
        max_calls = tools["max_calls"]
        if type(max_calls) is not int or max_calls < 0:
            _error(
                issues,
                "eval_field_value",
                f"{field}.max_calls must be a nonnegative integer",
                f"{field}.max_calls",
            )
        return True
    return bool(required or forbidden)


def _string_list(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
    issues: list[EvalManifestIssue],
) -> list[str]:
    if key not in mapping:
        return []
    field = f"{prefix}.{key}"
    value = mapping[key]
    if not isinstance(value, list) or not all(
        isinstance(item, str) and bool(item.strip()) for item in value
    ):
        _error(
            issues,
            "eval_field_type",
            f"{field} must be a list of non-empty strings",
            field,
        )
        return []
    if len(value) != len(set(value)):
        _error(
            issues,
            "eval_field_value",
            f"{field} entries must be unique",
            field,
        )
    return value


def _validate_trials(
    mapping: Mapping[str, Any],
    key: str,
    field: str,
    issues: list[EvalManifestIssue],
    *,
    required: bool,
) -> None:
    if key not in mapping:
        if required:
            _error(issues, "eval_field_missing", f"{field} is required", field)
        return
    value = mapping[key]
    if type(value) is not int or not 1 <= value <= _MAX_TRIALS:
        _error(
            issues,
            "eval_field_value",
            f"{field} must be an integer from 1 to {_MAX_TRIALS}",
            field,
        )


def _validate_ratio(
    mapping: Mapping[str, Any],
    key: str,
    field: str,
    issues: list[EvalManifestIssue],
    *,
    required: bool,
) -> None:
    if key not in mapping:
        if required:
            _error(issues, "eval_field_missing", f"{field} is required", field)
        return
    value = mapping[key]
    if not _is_number(value) or not math.isfinite(float(value)) or not 0 <= value <= 1:
        _error(
            issues,
            "eval_field_value",
            f"{field} must be a finite number from 0 to 1",
            field,
        )


def _is_number(value: Any) -> bool:
    return type(value) in {int, float}


def _required_mapping(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
    issues: list[EvalManifestIssue],
) -> Mapping[str, Any] | None:
    field = f"{prefix}.{key}" if prefix else key
    if key not in mapping:
        _error(issues, "eval_field_missing", f"{field} is required", field)
        return None
    value = mapping[key]
    if not isinstance(value, dict):
        _error(issues, "eval_field_type", f"{field} must be a mapping", field)
        return None
    return value


def _optional_mapping(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
    issues: list[EvalManifestIssue],
) -> Mapping[str, Any] | None:
    if key not in mapping:
        return None
    field = f"{prefix}.{key}"
    value = mapping[key]
    if not isinstance(value, dict):
        _error(issues, "eval_field_type", f"{field} must be a mapping", field)
        return None
    return value


def _reject_unknown_keys(
    mapping: Mapping[str, Any],
    allowed: frozenset[str],
    field: str,
    issues: list[EvalManifestIssue],
) -> None:
    for key in mapping:
        child = f"{field}.{key}" if field else str(key)
        if not isinstance(key, str) or key not in allowed:
            _error(
                issues,
                "eval_unknown_field",
                f"unsupported eval manifest field {child!r}",
                child,
            )


def _error(
    issues: list[EvalManifestIssue],
    code: str,
    message: str,
    field: str | None = None,
) -> None:
    issues.append(EvalManifestIssue("error", code, message, field))


def _warning(
    issues: list[EvalManifestIssue],
    code: str,
    message: str,
    field: str | None = None,
) -> None:
    issues.append(EvalManifestIssue("warning", code, message, field))
