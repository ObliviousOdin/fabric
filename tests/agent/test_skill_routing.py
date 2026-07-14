from __future__ import annotations

from pathlib import Path

import yaml

from agent.skill_routing import MAX_ROUTING_LIMIT, rank_skill_candidates


def _legacy(name: str, description: str, category: str = "general") -> dict:
    return {"name": name, "description": description, "category": category}


def _governed_skill(
    root: Path,
    name: str,
    *,
    triggers: list[str],
    non_triggers: list[str] | None = None,
    precedence: int = 50,
) -> dict:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\nversion: 1.0.0\n"
        f"description: Governed {name}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    evals = skill_dir / "evals"
    evals.mkdir()
    # The contract validator requires the complete deterministic v1 suite.
    cases = [
        {
            "id": "positive-trigger-case",
            "category": "positive_trigger",
            "input": "bounded fixture",
            "expect": {"selected": True},
        },
        {
            "id": "negative-trigger-case",
            "category": "negative_trigger",
            "input": "bounded fixture",
            "expect": {"selected": False},
        },
        {
            "id": "output-contract-case",
            "category": "output_contract",
            "input": "bounded fixture",
            "expect": {"output": {"required_substrings": ["ok"]}},
        },
        {
            "id": "safety-case",
            "category": "safety",
            "input": "bounded fixture",
            "expect": {"approvals": {"required": ["confirm"]}},
        },
        {
            "id": "tool-use-case",
            "category": "tool_use",
            "input": "bounded fixture",
            "expect": {"tools": {"required": ["skill_view"]}},
        },
        {
            "id": "regression-case",
            "category": "regression",
            "input": "bounded fixture",
            "expect": {"output": {"forbidden_substrings": ["failure"]}},
        },
        {
            "id": "baseline-case",
            "category": "baseline",
            "input": "bounded fixture",
            "baseline_for": "positive-trigger-case",
            "expect": {
                "selected": False,
                "output": {"forbidden_substrings": ["failure"]},
            },
        },
    ]
    (evals / "cases.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "suite": {
                    "trials": 1,
                    "pass_threshold": 1.0,
                    "compare_no_skill": True,
                },
                "cases": cases,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    contract = {
        "schema_version": 1,
        "identity": {
            "name": name,
            "version": "1.0.0",
            "owner": "tests",
            "license": "Apache-2.0",
        },
        "compatibility": {
            "fabric": ">=0.1",
            "hosts": ["fabric"],
            "models": ["*"],
            "platforms": ["linux", "macos", "windows"],
        },
        "routing": {
            "triggers": triggers,
            "non_triggers": non_triggers or [],
            "requires": [],
            "conflicts": [],
            "precedence": precedence,
        },
        "interface": {
            "inputs": [
                {
                    "name": "request",
                    "type": "text",
                    "required": True,
                    "description": "test input",
                }
            ],
            "outputs": [
                {
                    "name": "result",
                    "type": "text",
                    "required": True,
                    "description": "test output",
                }
            ],
        },
        "permissions": {
            "toolsets_required": [],
            "files": [],
            "network": [],
            "secrets": [],
            "actions": {
                "reversible": [],
                "approval_required": [],
                "prohibited": [],
            },
        },
        "sources": [],
        "budgets": {"context_tokens": 1000, "wall_seconds": 30, "tool_calls": 3},
        "outcomes": {"primary": "result", "guardrails": []},
        "evals": {"suite": "evals/cases.yaml"},
        "limitations": [],
    }
    (skill_dir / "skill.contract.yaml").write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )
    return {
        "name": name,
        "description": f"Governed {name}",
        "category": "tests",
        "skill_dir": str(skill_dir),
    }


def test_exact_name_and_description_rank_deterministically():
    skills = [
        _legacy("python-debug", "Debug Python processes", "development"),
        _legacy("python-format", "Format Python source", "development"),
    ]

    ranked = rank_skill_candidates("please use python debug", skills)

    assert [item.name for item in ranked] == ["python-debug", "python-format"]
    assert ranked[0].reasons[0] == "name_phrase"
    assert ranked[0].contract_status == "legacy_unverified"


def test_verified_declared_trigger_beats_legacy_description(tmp_path):
    governed = _governed_skill(
        tmp_path,
        "release-workflow",
        triggers=["publish a versioned release"],
    )
    legacy = _legacy("release-notes", "Publish a versioned release")

    ranked = rank_skill_candidates("publish a versioned release", [legacy, governed])

    assert ranked[0].name == "release-workflow"
    assert "declared_trigger_phrase" in ranked[0].reasons
    assert ranked[0].contract_status == "verified"


def test_declared_non_trigger_vetoes_candidate(tmp_path):
    skill = _governed_skill(
        tmp_path,
        "github-publish",
        triggers=["open or update a pull request"],
        non_triggers=["review code without publishing"],
    )

    ranked = rank_skill_candidates("review code without publishing", [skill])

    assert ranked == ()


def test_precedence_cannot_make_unrelated_skill_appear(tmp_path):
    skill = _governed_skill(
        tmp_path,
        "astronomy",
        triggers=["calculate a stellar orbit"],
        precedence=100,
    )

    assert rank_skill_candidates("write a grocery list", [skill]) == ()


def test_invalid_contract_is_discoverable_without_trigger_authority(tmp_path):
    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken\ndescription: Repair a broken release\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "skill.contract.yaml").write_text("schema_version: 999\n")
    skill = {
        "name": "broken",
        "description": "Repair a broken release",
        "category": "tests",
        "skill_dir": str(skill_dir),
    }

    ranked = rank_skill_candidates("repair broken release", [skill])

    assert ranked[0].name == "broken"
    assert ranked[0].contract_status == "invalid"
    assert all("declared_trigger" not in reason for reason in ranked[0].reasons)


def test_limit_is_bounded_and_ties_are_stable():
    skills = [
        _legacy(f"skill-{index:02d}", "common routing words", "same")
        for index in range(40, -1, -1)
    ]

    ranked = rank_skill_candidates("common routing words", skills, limit=10_000)

    assert len(ranked) == MAX_ROUTING_LIMIT
    assert [item.name for item in ranked[:3]] == ["skill-00", "skill-01", "skill-02"]


def test_empty_or_punctuation_only_query_returns_nothing():
    skills = [_legacy("alpha", "Alpha helper")]

    assert rank_skill_candidates("", skills) == ()
    assert rank_skill_candidates("---", skills) == ()
