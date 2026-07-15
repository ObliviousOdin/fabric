"""Behavior contracts for the deterministic governed-skill eval runner."""

from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest
import yaml

import agent.skill_eval_runner as eval_runner
from agent.skill_eval_runner import SkillEvalInputError, run_skill_evaluation


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "suite": {
            "trials": 2,
            "pass_threshold": 0.75,
            "compare_no_skill": True,
            "min_lift": 0.1,
        },
        "cases": [
            {
                "id": "positive",
                "category": "positive_trigger",
                "input": {"request": "Use the skill."},
                "expect": {"selected": True},
            },
            {
                "id": "negative",
                "category": "negative_trigger",
                "input": "Ignore the skill.",
                "expect": {"selected": False, "tools": {"max_calls": 0}},
            },
            {
                "id": "output",
                "category": "output_contract",
                "input": "Return a result.",
                "expect": {
                    "output": {
                        "required_substrings": ["done"],
                        "forbidden_substrings": ["secret"],
                    }
                },
            },
            {
                "id": "safety",
                "category": "safety",
                "input": "Perform a sensitive action.",
                "expect": {
                    "approvals": {
                        "required": ["confirm"],
                        "forbidden": ["force"],
                    }
                },
            },
            {
                "id": "tools",
                "category": "tool_use",
                "input": "Inspect a file.",
                "expect": {
                    "tools": {
                        "required": ["read_file"],
                        "forbidden": ["terminal"],
                        "max_calls": 2,
                    }
                },
            },
            {
                "id": "regression",
                "category": "regression",
                "input": "Preserve the marker.",
                "pass_threshold": 0.5,
                "expect": {"output": {"required_substrings": ["stable"]}},
            },
            {
                "id": "baseline",
                "category": "baseline",
                "input": {"request": "Use the skill."},
                "baseline_for": "positive",
                "expect": {
                    "selected": False,
                    "output": {"forbidden_substrings": ["eval-failure"]},
                },
            },
        ],
    }


def _observation(
    *,
    selected: bool = False,
    output: str = "",
    tools: list[str] | None = None,
    approvals: list[str] | None = None,
    score: float = 0.5,
) -> dict:
    return {
        "selected": selected,
        "output": output,
        "tools": list(tools or []),
        "approvals": list(approvals or []),
        "outcome_score": score,
    }


def _observations() -> dict[str, list[dict]]:
    return {
        "positive": [
            _observation(selected=True, score=0.8),
            _observation(selected=True, score=0.9),
        ],
        "negative": [_observation(score=0.7), _observation(score=0.6)],
        "output": [
            _observation(output="done", score=0.8),
            _observation(output="work done", score=0.9),
        ],
        "safety": [
            _observation(approvals=["confirm"], score=0.8),
            _observation(approvals=["confirm"], score=0.7),
        ],
        "tools": [
            _observation(tools=["read_file"], score=0.8),
            _observation(tools=["read_file", "read_file"], score=0.9),
        ],
        "regression": [
            _observation(output="stable", score=0.8),
            _observation(output="stable marker", score=0.9),
        ],
        "baseline": [
            _observation(score=0.5),
            _observation(score=0.6),
        ],
    }


def _write_manifest(root: Path, manifest: dict | None = None) -> Path:
    skill_dir = root / "demo-skill"
    evals = skill_dir / "evals"
    evals.mkdir(parents=True)
    (evals / "cases.yaml").write_text(
        yaml.safe_dump(manifest or _manifest(), sort_keys=False),
        encoding="utf-8",
    )
    return skill_dir


def _issue_codes(exc: SkillEvalInputError) -> set[str]:
    return {issue.code for issue in exc.issues}


def test_runner_evaluates_trials_thresholds_variance_and_paired_lift(tmp_path):
    skill_dir = _write_manifest(tmp_path)

    report = run_skill_evaluation(
        skill_dir, "evals/cases.yaml", _observations()
    )

    assert report.passed
    assert report.failure_reasons == ()
    assert report.trial_count == 14
    assert report.pass_count == 14
    assert report.pass_rate == 1.0
    assert report.pass_variance == 0.0
    assert report.case_pass_count == 7
    assert report.case_pass_rate == 1.0
    assert report.observed_lift == pytest.approx(0.3)
    assert report.lift_variance == pytest.approx(0.0, abs=1e-30)
    assert report.lift_passed
    assert len(report.manifest_digest) == 64

    pair = report.baseline_pairs[0]
    assert pair.skill_case_id == "positive"
    assert pair.baseline_case_id == "baseline"
    assert pair.trial_count == 2
    assert pair.skill_outcome_mean == pytest.approx(0.85)
    assert pair.baseline_outcome_mean == pytest.approx(0.55)
    assert pair.mean_lift == pytest.approx(0.3)


def test_case_override_can_pass_one_failed_trial_and_reports_bernoulli_variance(
    tmp_path,
):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    observations["regression"][1]["output"] = "missing marker"

    report = run_skill_evaluation(
        skill_dir, "evals/cases.yaml", observations
    )

    regression = next(case for case in report.cases if case.case_id == "regression")
    assert regression.threshold == 0.5
    assert regression.pass_count == 1
    assert regression.pass_rate == 0.5
    assert regression.pass_variance == 0.25
    assert regression.passed
    assert report.pass_rate == pytest.approx(13 / 14)
    assert report.pass_variance == pytest.approx((13 / 14) * (1 / 14))
    assert report.passed
    assert regression.trials[1].failures[0].code == "output_required_missing"


def test_case_and_suite_thresholds_are_independent_strict_gates(tmp_path):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    observations["positive"][1]["selected"] = False

    case_failure = run_skill_evaluation(
        skill_dir, "evals/cases.yaml", observations
    )

    assert not case_failure.passed
    assert case_failure.pass_rate > case_failure.suite_threshold
    assert case_failure.failure_reasons == ("case_threshold",)

    manifest = _manifest()
    for case in manifest["cases"]:
        if case["id"] in {"negative", "output", "safety", "tools"}:
            case["pass_threshold"] = 0.0
    skill_dir = _write_manifest(tmp_path / "second", manifest)
    observations = _observations()
    for trial in observations["negative"]:
        trial["selected"] = True
    for trial in observations["output"]:
        trial["output"] = "missing"
    for trial in observations["safety"]:
        trial["approvals"] = []
    for trial in observations["tools"]:
        trial["tools"] = []

    suite_failure = run_skill_evaluation(
        skill_dir, "evals/cases.yaml", observations
    )

    assert all(case.passed for case in suite_failure.cases)
    assert suite_failure.pass_rate < suite_failure.suite_threshold
    assert suite_failure.failure_reasons == ("suite_threshold",)
    assert not suite_failure.passed


def test_min_lift_uses_only_paired_same_trial_deltas(tmp_path):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    observations["positive"][0]["outcome_score"] = 0.55
    observations["positive"][1]["outcome_score"] = 0.55
    # High scores on unrelated cases must not inflate the paired lift.
    for case_id in {"output", "safety", "tools", "regression"}:
        for trial in observations[case_id]:
            trial["outcome_score"] = 1.0

    report = run_skill_evaluation(
        skill_dir, "evals/cases.yaml", observations
    )

    assert report.observed_lift == pytest.approx(0.0)
    assert not report.lift_passed
    assert report.failure_reasons == ("min_lift",)
    assert not report.passed


def test_missing_extra_cases_and_trial_counts_fail_closed(tmp_path):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    del observations["output"]
    observations["undeclared"] = [_observation(), _observation()]
    observations["tools"].pop()

    with pytest.raises(SkillEvalInputError) as captured:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", observations)

    assert _issue_codes(captured.value) == {
        "eval_observation_case_missing",
        "eval_observation_case_extra",
        "eval_observation_trials_mismatch",
    }


def test_observation_schema_is_closed_and_rejects_executable_fields(tmp_path):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    observations["positive"][0]["hook"] = "python setup.py"
    del observations["positive"][1]["approvals"]

    with pytest.raises(SkillEvalInputError) as captured:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", observations)

    assert _issue_codes(captured.value) == {
        "eval_observation_field_extra",
        "eval_observation_field_missing",
    }


def test_observation_case_and_field_names_must_be_strings(tmp_path):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    observations[7] = observations.pop("output")
    observations["positive"][0][1] = "not-json"

    with pytest.raises(SkillEvalInputError) as captured:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", observations)

    assert _issue_codes(captured.value) == {
        "eval_observation_case_id_type",
        "eval_observation_case_missing",
        "eval_observation_field_name_type",
    }


def test_observation_output_and_event_collections_are_bounded(tmp_path):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    observations["positive"][0]["output"] = "x" * (128 * 1024 + 1)
    observations["positive"][1]["tools"] = ["read_file"] * 257
    observations["negative"][0]["approvals"] = ["bad\nname"]

    with pytest.raises(SkillEvalInputError) as captured:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", observations)

    assert _issue_codes(captured.value) == {
        "eval_observation_output_too_large",
        "eval_observation_events_too_many",
        "eval_observation_event_name_invalid",
    }


def test_suite_wide_output_and_event_work_budgets_are_bounded(
    monkeypatch, tmp_path
):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    monkeypatch.setattr(eval_runner, "_MAX_TOTAL_OUTPUT_BYTES", 1)

    with pytest.raises(SkillEvalInputError) as output_budget:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", observations)

    assert "eval_observation_output_budget_exceeded" in _issue_codes(
        output_budget.value
    )

    monkeypatch.setattr(eval_runner, "_MAX_TOTAL_OUTPUT_BYTES", 16 * 1024 * 1024)
    monkeypatch.setattr(eval_runner, "_MAX_TOTAL_EVENTS", 1)
    with pytest.raises(SkillEvalInputError) as event_budget:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", observations)

    assert _issue_codes(event_budget.value) == {
        "eval_observation_event_budget_exceeded"
    }


@pytest.mark.parametrize("score", [math.nan, math.inf, -0.1, 1.1, True])
def test_outcome_scores_must_be_finite_bounded_numbers(tmp_path, score):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    observations["positive"][0]["outcome_score"] = score

    with pytest.raises(SkillEvalInputError) as captured:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", observations)

    assert _issue_codes(captured.value) == {"eval_observation_score_invalid"}


def test_tool_approval_output_and_selected_assertions_are_deterministic(tmp_path):
    skill_dir = _write_manifest(tmp_path)
    observations = _observations()
    observations["positive"][0]["selected"] = False
    observations["output"][0]["output"] = "secret"
    observations["tools"][0]["tools"] = ["terminal", "other", "third"]
    observations["safety"][0]["approvals"] = ["force"]

    report = run_skill_evaluation(
        skill_dir, "evals/cases.yaml", observations
    )

    failures = {
        failure.code
        for case in report.cases
        for trial in case.trials
        for failure in trial.failures
    }
    assert failures == {
        "selected_mismatch",
        "output_required_missing",
        "output_forbidden_present",
        "tool_required_missing",
        "tool_forbidden_present",
        "tool_max_calls_exceeded",
        "approval_required_missing",
        "approval_forbidden_present",
    }


def test_baseline_must_be_paired_and_cannot_report_skill_selected(tmp_path):
    manifest = _manifest()
    del manifest["cases"][-1]["baseline_for"]
    skill_dir = _write_manifest(tmp_path, manifest)

    with pytest.raises(SkillEvalInputError) as unpaired:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", _observations())

    assert _issue_codes(unpaired.value) == {
        "eval_baseline_pair_missing",
        "eval_baseline_pairs_empty",
    }

    skill_dir = _write_manifest(tmp_path / "paired")
    observations = _observations()
    observations["baseline"][0]["selected"] = True

    with pytest.raises(SkillEvalInputError) as contaminated:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", observations)

    assert _issue_codes(contaminated.value) == {"eval_baseline_selected"}


def test_manifest_pairing_validation_runs_before_observation_evaluation(tmp_path):
    manifest = copy.deepcopy(_manifest())
    manifest["cases"][-1]["input"] = {"request": "A different input."}
    skill_dir = _write_manifest(tmp_path, manifest)

    with pytest.raises(SkillEvalInputError) as captured:
        run_skill_evaluation(skill_dir, "evals/cases.yaml", _observations())

    assert "eval_baseline_input_mismatch" in _issue_codes(captured.value)
