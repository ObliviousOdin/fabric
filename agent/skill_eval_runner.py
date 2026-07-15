"""Pure, deterministic evaluation of governed skill observations.

The runner deliberately does not execute a model, provider, tool, hook, or
command.  An external harness records one closed observation per manifest
trial and passes those records here.  This module validates the records,
applies the manifest's exact assertions, computes population variance and
pass rates, and compares only explicitly paired same-input no-skill trials.

Threshold semantics are intentionally strict:

* each case must meet its own ``pass_threshold`` (or the suite default);
* all trials together must meet the suite ``pass_threshold``;
* every case threshold must pass, so an easy case cannot hide a failed case;
* the mean of paired per-trial outcome deltas must meet ``suite.min_lift``.

``outcome_score`` is a caller-supplied finite value in ``[0, 1]``.  It is
used only for quality/lift statistics; deterministic manifest assertions
decide whether a trial passes.  Baseline observations must report
``selected: false`` and every baseline case must declare ``baseline_for``.
The producer remains responsible for actually running that observation with
the skill disabled; this data-only runner cannot and must not invoke it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.skill_evals import validate_eval_manifest


_OBSERVATION_KEYS = frozenset(
    {"selected", "output", "tools", "approvals", "outcome_score"}
)
_MAX_OBSERVATION_CASES = 500
_MAX_OUTPUT_BYTES = 128 * 1024
_MAX_EVENTS = 256
_MAX_EVENT_NAME_BYTES = 256
_MAX_TOTAL_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_EVENTS = 100_000


@dataclass(frozen=True)
class SkillEvalInputIssue:
    """One stable, non-sensitive observation or pairing error."""

    code: str
    message: str
    field: str | None = None


class SkillEvalInputError(ValueError):
    """Raised before evaluation when observations cannot be trusted."""

    def __init__(self, issues: tuple[SkillEvalInputIssue, ...]):
        self.issues = issues
        summary = "; ".join(issue.code for issue in issues)
        super().__init__(summary or "skill evaluation input is invalid")


@dataclass(frozen=True)
class SkillEvalAssertionFailure:
    """A failed deterministic assertion, without retaining observed content."""

    code: str
    field: str


@dataclass(frozen=True)
class SkillEvalTrialResult:
    """Result for one ordered trial in one manifest case."""

    trial: int
    passed: bool
    failures: tuple[SkillEvalAssertionFailure, ...]
    outcome_score: float


@dataclass(frozen=True)
class SkillEvalCaseResult:
    """Per-case threshold and variance report."""

    case_id: str
    category: str
    baseline_for: str | None
    threshold: float
    trial_count: int
    pass_count: int
    pass_rate: float
    pass_variance: float
    outcome_mean: float
    outcome_variance: float
    passed: bool
    trials: tuple[SkillEvalTrialResult, ...]


@dataclass(frozen=True)
class SkillEvalBaselinePairResult:
    """Same-input, same-trial-index outcome comparison."""

    skill_case_id: str
    baseline_case_id: str
    trial_count: int
    skill_outcome_mean: float
    baseline_outcome_mean: float
    mean_lift: float
    lift_variance: float


@dataclass(frozen=True)
class SkillEvalReport:
    """Immutable suite result suitable for a promotion gate or receipt."""

    manifest_digest: str
    suite_threshold: float
    min_lift: float
    trial_count: int
    pass_count: int
    pass_rate: float
    pass_variance: float
    outcome_mean: float
    outcome_variance: float
    case_pass_count: int
    case_pass_rate: float
    observed_lift: float
    lift_variance: float
    lift_passed: bool
    passed: bool
    failure_reasons: tuple[str, ...]
    cases: tuple[SkillEvalCaseResult, ...]
    baseline_pairs: tuple[SkillEvalBaselinePairResult, ...]


@dataclass(frozen=True)
class _Observation:
    selected: bool
    output: str
    tools: tuple[str, ...]
    approvals: tuple[str, ...]
    outcome_score: float


def run_skill_evaluation(
    skill_dir: Path,
    suite_path: str,
    observations: Mapping[str, list[Mapping[str, Any]]],
) -> SkillEvalReport:
    """Validate a manifest and evaluate an exact set of recorded trials.

    ``observations`` is keyed by case id.  Each value is an ordered list whose
    length must equal that case's effective trial count.  Every observation
    must contain exactly the five keys in :data:`_OBSERVATION_KEYS`; tool and
    approval arguments are intentionally not accepted.
    """

    validation = validate_eval_manifest(Path(skill_dir), suite_path)
    if not validation.ok or validation.manifest is None or validation.digest is None:
        issues = tuple(
            SkillEvalInputIssue(issue.code, issue.message, issue.field)
            for issue in validation.errors
        )
        if not issues:
            issues = (
                SkillEvalInputIssue(
                    "eval_manifest_unavailable",
                    "validated manifest data and digest are required",
                ),
            )
        raise SkillEvalInputError(issues)

    manifest = validation.manifest
    cases = manifest["cases"]
    suite = manifest["suite"]
    normalized = _validate_observations(cases, suite, observations)

    case_results: list[SkillEvalCaseResult] = []
    case_by_id: dict[str, SkillEvalCaseResult] = {}
    for case in cases:
        case_id = case["id"]
        result = _evaluate_case(case, suite, normalized[case_id])
        case_results.append(result)
        case_by_id[case_id] = result

    pair_results, lifts = _evaluate_baseline_pairs(cases, case_by_id)
    all_trials = [trial for case in case_results for trial in case.trials]
    passes = [1.0 if trial.passed else 0.0 for trial in all_trials]
    outcomes = [trial.outcome_score for trial in all_trials]
    pass_count = sum(1 for value in passes if value == 1.0)
    suite_threshold = float(suite["pass_threshold"])
    pass_rate = _mean(passes)
    case_pass_count = sum(1 for case in case_results if case.passed)
    case_pass_rate = case_pass_count / len(case_results)
    min_lift = float(suite.get("min_lift", 0.0))
    observed_lift = _mean(lifts)
    lift_passed = observed_lift >= min_lift

    failure_reasons: list[str] = []
    if any(not case.passed for case in case_results):
        failure_reasons.append("case_threshold")
    if pass_rate < suite_threshold:
        failure_reasons.append("suite_threshold")
    if not lift_passed:
        failure_reasons.append("min_lift")

    return SkillEvalReport(
        manifest_digest=validation.digest,
        suite_threshold=suite_threshold,
        min_lift=min_lift,
        trial_count=len(all_trials),
        pass_count=pass_count,
        pass_rate=pass_rate,
        pass_variance=_population_variance(passes),
        outcome_mean=_mean(outcomes),
        outcome_variance=_population_variance(outcomes),
        case_pass_count=case_pass_count,
        case_pass_rate=case_pass_rate,
        observed_lift=observed_lift,
        lift_variance=_population_variance(lifts),
        lift_passed=lift_passed,
        passed=not failure_reasons,
        failure_reasons=tuple(failure_reasons),
        cases=tuple(case_results),
        baseline_pairs=tuple(pair_results),
    )


def _validate_observations(
    cases: list[Mapping[str, Any]],
    suite: Mapping[str, Any],
    observations: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, tuple[_Observation, ...]]:
    issues: list[SkillEvalInputIssue] = []
    if type(observations) is not dict:
        raise SkillEvalInputError(
            (
                SkillEvalInputIssue(
                    "eval_observations_type",
                    "observations must be a plain mapping keyed by case id",
                    "observations",
                ),
            )
        )
    if len(observations) > _MAX_OBSERVATION_CASES:
        raise SkillEvalInputError(
            (
                SkillEvalInputIssue(
                    "eval_observations_too_many",
                    f"observations must not exceed {_MAX_OBSERVATION_CASES} cases",
                    "observations",
                ),
            )
        )

    expected_ids = {case["id"] for case in cases}
    if not all(type(case_id) is str for case_id in observations):
        _issue(
            issues,
            "eval_observation_case_id_type",
            "observation case ids must be strings",
            "observations",
        )
    actual_ids = {
        case_id for case_id in observations if type(case_id) is str
    }
    for case_id in sorted(expected_ids - actual_ids):
        _issue(
            issues,
            "eval_observation_case_missing",
            f"observations are missing case {case_id!r}",
            f"observations.{case_id}",
        )
    for case_id in sorted(actual_ids - expected_ids):
        _issue(
            issues,
            "eval_observation_case_extra",
            "observations contain an undeclared case",
            f"observations.{case_id}",
        )

    normalized: dict[str, tuple[_Observation, ...]] = {}
    suite_trials = suite["trials"]
    total_output_bytes = 0
    total_events = 0
    for case in cases:
        case_id = case["id"]
        if case_id not in observations:
            continue
        values = observations[case_id]
        field = f"observations.{case_id}"
        if type(values) is not list:
            _issue(
                issues,
                "eval_observation_trials_type",
                "case observations must be an ordered list",
                field,
            )
            continue
        expected_trials = case.get("trials", suite_trials)
        if len(values) != expected_trials:
            _issue(
                issues,
                "eval_observation_trials_mismatch",
                (
                    f"case requires exactly {expected_trials} observations; "
                    f"received {len(values)}"
                ),
                field,
            )
        parsed: list[_Observation] = []
        for index, value in enumerate(values[: max(expected_trials, 0)]):
            observation = _validate_observation(value, f"{field}[{index}]", issues)
            if observation is not None:
                total_output_bytes += _utf8_size(observation.output) or 0
                total_events += len(observation.tools) + len(observation.approvals)
                if total_output_bytes > _MAX_TOTAL_OUTPUT_BYTES:
                    _issue(
                        issues,
                        "eval_observation_output_budget_exceeded",
                        (
                            "total observation output must not exceed "
                            f"{_MAX_TOTAL_OUTPUT_BYTES} UTF-8 bytes"
                        ),
                        "observations",
                    )
                    raise SkillEvalInputError(tuple(issues))
                if total_events > _MAX_TOTAL_EVENTS:
                    _issue(
                        issues,
                        "eval_observation_event_budget_exceeded",
                        (
                            "total tool and approval events must not exceed "
                            f"{_MAX_TOTAL_EVENTS} entries"
                        ),
                        "observations",
                    )
                    raise SkillEvalInputError(tuple(issues))
                if case["category"] == "baseline" and observation.selected:
                    _issue(
                        issues,
                        "eval_baseline_selected",
                        "no-skill baseline observations must report selected: false",
                        f"{field}[{index}].selected",
                    )
                parsed.append(observation)
        if len(parsed) == expected_trials:
            normalized[case_id] = tuple(parsed)

    if issues:
        raise SkillEvalInputError(tuple(issues))
    return normalized


def _validate_observation(
    value: Any,
    field: str,
    issues: list[SkillEvalInputIssue],
) -> _Observation | None:
    if type(value) is not dict:
        _issue(
            issues,
            "eval_observation_type",
            "each observation must be a plain mapping",
            field,
        )
        return None

    if not all(type(key) is str for key in value):
        _issue(
            issues,
            "eval_observation_field_name_type",
            "observation field names must be strings",
            field,
        )
        return None
    keys = set(value)
    for key in sorted(_OBSERVATION_KEYS - keys):
        _issue(
            issues,
            "eval_observation_field_missing",
            f"observation field {key!r} is required",
            f"{field}.{key}",
        )
    for key in sorted(keys - _OBSERVATION_KEYS):
        _issue(
            issues,
            "eval_observation_field_extra",
            "observation contains an unsupported field",
            f"{field}.{key}",
        )
    if keys != _OBSERVATION_KEYS:
        return None

    selected = value["selected"]
    output = value["output"]
    score = value["outcome_score"]
    valid = True
    if type(selected) is not bool:
        _issue(
            issues,
            "eval_observation_selected_type",
            "selected must be a boolean",
            f"{field}.selected",
        )
        valid = False
    output_bytes = _utf8_size(output) if type(output) is str else None
    if type(output) is not str:
        _issue(
            issues,
            "eval_observation_output_type",
            "output must be a string",
            f"{field}.output",
        )
        valid = False
    elif output_bytes is None or output_bytes > _MAX_OUTPUT_BYTES:
        _issue(
            issues,
            "eval_observation_output_too_large",
            f"output must not exceed {_MAX_OUTPUT_BYTES} UTF-8 bytes",
            f"{field}.output",
        )
        valid = False

    tools = _validate_event_names(value["tools"], f"{field}.tools", issues)
    approvals = _validate_event_names(
        value["approvals"], f"{field}.approvals", issues
    )
    if tools is None or approvals is None:
        valid = False

    if (
        type(score) not in {int, float}
        or not math.isfinite(float(score))
        or not 0 <= score <= 1
    ):
        _issue(
            issues,
            "eval_observation_score_invalid",
            "outcome_score must be a finite number from 0 to 1",
            f"{field}.outcome_score",
        )
        valid = False

    if not valid:
        return None
    return _Observation(
        selected=selected,
        output=output,
        tools=tools,
        approvals=approvals,
        outcome_score=float(score),
    )


def _validate_event_names(
    value: Any,
    field: str,
    issues: list[SkillEvalInputIssue],
) -> tuple[str, ...] | None:
    if type(value) is not list:
        _issue(
            issues,
            "eval_observation_events_type",
            "event names must be an ordered list",
            field,
        )
        return None
    if len(value) > _MAX_EVENTS:
        _issue(
            issues,
            "eval_observation_events_too_many",
            f"event names must not exceed {_MAX_EVENTS} entries",
            field,
        )
        return None
    valid = True
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        if (
            type(item) is not str
            or not item.strip()
            or (_utf8_size(item) or _MAX_EVENT_NAME_BYTES + 1)
            > _MAX_EVENT_NAME_BYTES
            or any(ord(character) < 32 or ord(character) == 127 for character in item)
        ):
            _issue(
                issues,
                "eval_observation_event_name_invalid",
                (
                    "event names must be non-empty printable strings no longer "
                    f"than {_MAX_EVENT_NAME_BYTES} UTF-8 bytes"
                ),
                item_field,
            )
            valid = False
    return tuple(value) if valid else None


def _utf8_size(value: str) -> int | None:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _evaluate_case(
    case: Mapping[str, Any],
    suite: Mapping[str, Any],
    observations: tuple[_Observation, ...],
) -> SkillEvalCaseResult:
    trial_results = tuple(
        _evaluate_trial(case, observation, index)
        for index, observation in enumerate(observations)
    )
    pass_values = [1.0 if trial.passed else 0.0 for trial in trial_results]
    outcomes = [trial.outcome_score for trial in trial_results]
    pass_count = sum(1 for value in pass_values if value == 1.0)
    pass_rate = _mean(pass_values)
    threshold = float(case.get("pass_threshold", suite["pass_threshold"]))
    return SkillEvalCaseResult(
        case_id=case["id"],
        category=case["category"],
        baseline_for=case.get("baseline_for"),
        threshold=threshold,
        trial_count=len(trial_results),
        pass_count=pass_count,
        pass_rate=pass_rate,
        pass_variance=_population_variance(pass_values),
        outcome_mean=_mean(outcomes),
        outcome_variance=_population_variance(outcomes),
        passed=pass_rate >= threshold,
        trials=trial_results,
    )


def _evaluate_trial(
    case: Mapping[str, Any],
    observation: _Observation,
    trial: int,
) -> SkillEvalTrialResult:
    expect = case["expect"]
    failures: list[SkillEvalAssertionFailure] = []
    if "selected" in expect and observation.selected is not expect["selected"]:
        failures.append(
            SkillEvalAssertionFailure("selected_mismatch", "expect.selected")
        )

    output = expect.get("output", {})
    for index, substring in enumerate(output.get("required_substrings", [])):
        if substring not in observation.output:
            failures.append(
                SkillEvalAssertionFailure(
                    "output_required_missing",
                    f"expect.output.required_substrings[{index}]",
                )
            )
    for index, substring in enumerate(output.get("forbidden_substrings", [])):
        if substring in observation.output:
            failures.append(
                SkillEvalAssertionFailure(
                    "output_forbidden_present",
                    f"expect.output.forbidden_substrings[{index}]",
                )
            )

    tools = expect.get("tools", {})
    observed_tools = frozenset(observation.tools)
    for index, name in enumerate(tools.get("required", [])):
        if name not in observed_tools:
            failures.append(
                SkillEvalAssertionFailure(
                    "tool_required_missing", f"expect.tools.required[{index}]"
                )
            )
    for index, name in enumerate(tools.get("forbidden", [])):
        if name in observed_tools:
            failures.append(
                SkillEvalAssertionFailure(
                    "tool_forbidden_present", f"expect.tools.forbidden[{index}]"
                )
            )
    if "max_calls" in tools and len(observation.tools) > tools["max_calls"]:
        failures.append(
            SkillEvalAssertionFailure("tool_max_calls_exceeded", "expect.tools.max_calls")
        )

    approvals = expect.get("approvals", {})
    observed_approvals = frozenset(observation.approvals)
    for index, name in enumerate(approvals.get("required", [])):
        if name not in observed_approvals:
            failures.append(
                SkillEvalAssertionFailure(
                    "approval_required_missing",
                    f"expect.approvals.required[{index}]",
                )
            )
    for index, name in enumerate(approvals.get("forbidden", [])):
        if name in observed_approvals:
            failures.append(
                SkillEvalAssertionFailure(
                    "approval_forbidden_present",
                    f"expect.approvals.forbidden[{index}]",
                )
            )

    return SkillEvalTrialResult(
        trial=trial,
        passed=not failures,
        failures=tuple(failures),
        outcome_score=observation.outcome_score,
    )


def _evaluate_baseline_pairs(
    cases: list[Mapping[str, Any]],
    case_by_id: Mapping[str, SkillEvalCaseResult],
) -> tuple[list[SkillEvalBaselinePairResult], list[float]]:
    issues: list[SkillEvalInputIssue] = []
    pair_results: list[SkillEvalBaselinePairResult] = []
    all_lifts: list[float] = []
    for index, case in enumerate(cases):
        if case["category"] != "baseline":
            continue
        baseline_for = case.get("baseline_for")
        if not isinstance(baseline_for, str):
            _issue(
                issues,
                "eval_baseline_pair_missing",
                "baseline case must declare baseline_for before it can be run",
                f"cases[{index}].baseline_for",
            )
            continue

        baseline = case_by_id[case["id"]]
        skill_case = case_by_id[baseline_for]
        if baseline.trial_count != skill_case.trial_count:
            _issue(
                issues,
                "eval_baseline_trials_mismatch",
                "paired results must contain the same number of trials",
                f"cases[{index}].trials",
            )
            continue
        lifts = [
            skill_trial.outcome_score - baseline_trial.outcome_score
            for skill_trial, baseline_trial in zip(
                skill_case.trials, baseline.trials, strict=True
            )
        ]
        all_lifts.extend(lifts)
        pair_results.append(
            SkillEvalBaselinePairResult(
                skill_case_id=skill_case.case_id,
                baseline_case_id=baseline.case_id,
                trial_count=len(lifts),
                skill_outcome_mean=skill_case.outcome_mean,
                baseline_outcome_mean=baseline.outcome_mean,
                mean_lift=_mean(lifts),
                lift_variance=_population_variance(lifts),
            )
        )

    if not pair_results:
        _issue(
            issues,
            "eval_baseline_pairs_empty",
            "at least one explicit no-skill baseline pair is required",
            "cases",
        )
    if issues:
        raise SkillEvalInputError(tuple(issues))
    return pair_results, all_lifts


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("statistics require at least one value")
    return math.fsum(values) / len(values)


def _population_variance(values: list[float]) -> float:
    mean = _mean(values)
    return math.fsum((value - mean) ** 2 for value in values) / len(values)


def _issue(
    issues: list[SkillEvalInputIssue],
    code: str,
    message: str,
    field: str | None = None,
) -> None:
    issues.append(SkillEvalInputIssue(code, message, field))
