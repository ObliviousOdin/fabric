"""Behavior contracts for turn-scoped governed-skill permission leases."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import agent.skill_permissions as permissions
from agent.skill_permissions import (
    activate_skill_permission_lease,
    bind_staged_skill_permission_leases,
    evaluate_skill_tool_call,
    finalize_current_turn_permission_leases,
    get_current_permission_turn_id,
    get_turn_permission_snapshot,
    stage_skill_permission_lease,
)


def _eval_manifest() -> dict:
    return {
        "schema_version": 1,
        "suite": {
            "trials": 1,
            "pass_threshold": 1.0,
            "compare_no_skill": True,
        },
        "cases": [
            {
                "id": "positive",
                "category": "positive_trigger",
                "input": "fixture",
                "expect": {"selected": True},
            },
            {
                "id": "negative",
                "category": "negative_trigger",
                "input": "fixture",
                "expect": {"selected": False},
            },
            {
                "id": "output",
                "category": "output_contract",
                "input": "fixture",
                "expect": {"output": {"required_substrings": ["ok"]}},
            },
            {
                "id": "safety",
                "category": "safety",
                "input": "fixture",
                "expect": {"approvals": {"required": ["confirm"]}},
            },
            {
                "id": "tools",
                "category": "tool_use",
                "input": "fixture",
                "expect": {"tools": {"max_calls": 10}},
            },
            {
                "id": "regression",
                "category": "regression",
                "input": "fixture",
                "expect": {"selected": True},
            },
            {
                "id": "baseline",
                "category": "baseline",
                "input": "fixture",
                "baseline_for": "positive",
                "expect": {"selected": False},
            },
        ],
    }


def _contract(
    name: str,
    *,
    toolsets: list[str] | None = None,
    files: list[dict] | None = None,
    network: list[dict] | None = None,
    approvals: list[str] | None = None,
    prohibitions: list[str] | None = None,
    tool_calls: int = 20,
) -> dict:
    return {
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
            "triggers": ["test permission leases"],
            "non_triggers": [],
            "requires": [],
            "conflicts": [],
            "precedence": 50,
        },
        "interface": {
            "inputs": [{"name": "request", "type": "text"}],
            "outputs": [{"name": "result", "type": "text"}],
        },
        "permissions": {
            "toolsets_required": toolsets or [],
            "files": files or [],
            "network": network or [],
            "secrets": [],
            "actions": {
                "reversible": [],
                "approval_required": approvals or [],
                "prohibited": prohibitions or [],
            },
        },
        "sources": [],
        "budgets": {
            "context_tokens": 2_000,
            "wall_seconds": 60,
            "tool_calls": tool_calls,
        },
        "outcomes": {"primary": "result", "guardrails": []},
        "evals": {"suite": "evals/cases.yaml"},
        "limitations": [],
    }


def _write_skill(root: Path, name: str, contract: dict | None) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\nversion: 1.0.0\ndescription: Test\n---\n# Test\n",
        encoding="utf-8",
    )
    if contract is not None:
        (skill_dir / "evals").mkdir()
        (skill_dir / "evals" / "cases.yaml").write_text(
            yaml.safe_dump(_eval_manifest(), sort_keys=False), encoding="utf-8"
        )
        (skill_dir / "skill.contract.yaml").write_text(
            yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
        )
    return skill_dir


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    permissions._clear_permission_leases_for_tests()
    monkeypatch.setattr(
        permissions, "_classify_provenance", lambda _path, _name: "learned"
    )
    yield
    permissions._clear_permission_leases_for_tests()


def _activate(
    skill_dir: Path,
    *,
    turn: str = "turn-1",
    task: str = "task-1",
    mode: str = "enforce_all",
    workspace: Path | None = None,
):
    return activate_skill_permission_lease(
        skill_dir=skill_dir,
        canonical_name=skill_dir.name,
        turn_id=turn,
        task_id=task,
        session_id="session-1",
        workspace_root=workspace or skill_dir.parent,
        config={"skills": {"permissions": {"mode": mode}}},
    )


def _call(
    tool: str,
    args: dict,
    *,
    turn: str = "turn-1",
    task: str = "task-1",
    toolset: str,
):
    return evaluate_skill_tool_call(
        tool_name=tool,
        function_args=args,
        turn_id=turn,
        task_id=task,
        session_id="session-1",
        toolset=toolset,
    )


def test_stacked_prohibition_wins_and_approval_requirements_union(tmp_path):
    first = _write_skill(
        tmp_path,
        "first-skill",
        _contract(
            "first-skill",
            toolsets=["terminal", "file"],
            approvals=["write_file", "terminal"],
        ),
    )
    second = _write_skill(
        tmp_path,
        "second-skill",
        _contract(
            "second-skill",
            toolsets=["terminal", "file"],
            files=[{"scope": "workspace", "access": "read_write"}],
            prohibitions=["terminal"],
        ),
    )
    assert _activate(first).allowed
    assert _activate(second).allowed

    prohibited = _call("terminal", {"command": "true"}, toolset="terminal")
    approval = _call(
        "write_file", {"path": str(tmp_path / "out.txt")}, toolset="file"
    )

    assert prohibited.action == "block"
    assert prohibited.code == "action_prohibited"
    assert prohibited.effective_lane == "restricted"
    assert approval.action == "approve"
    assert approval.code == "approval_required"
    assert approval.approval_key and "write_file" in approval.approval_key


def test_opaque_effect_toolsets_are_elevated_but_emit_explicit_gaps(tmp_path):
    skill = _write_skill(
        tmp_path,
        "terminal-risk",
        _contract(
            "terminal-risk", toolsets=["terminal", "code_execution"]
        ),
    )
    activation = _activate(skill)
    terminal = _call("terminal", {"command": "true"}, toolset="terminal")
    code = _call(
        "execute_code", {"code": "pass"}, toolset="code_execution"
    )

    assert activation.lane == "elevated"
    assert terminal.action == "allow"
    assert terminal.effective_lane == "elevated"
    assert "terminal_file_effects_uninspectable" in terminal.observations
    assert "terminal_network_uninspectable" in terminal.observations
    assert code.action == "allow"
    assert "code_file_effects_uninspectable" in code.observations
    assert "code_network_uninspectable" in code.observations


def test_rollout_modes_enforce_only_the_selected_provenance(monkeypatch, tmp_path):
    legacy = _write_skill(tmp_path, "legacy-skill", contract=None)

    observed = _activate(legacy, mode="observe")
    assert observed.action == "observed"
    assert observed.contract_status == "legacy_unverified"

    permissions._clear_permission_leases_for_tests()
    learned = _activate(legacy, mode="enforce_learned")
    assert learned.action == "blocked"
    assert learned.code == "contract_not_verified"

    monkeypatch.setattr(
        permissions, "_classify_provenance", lambda _path, _name: "bundled"
    )
    bundled = _activate(legacy, mode="enforce_learned")
    assert bundled.action == "observed"

    enforced_all = _activate(legacy, mode="enforce_all")
    assert enforced_all.action == "blocked"


def test_file_scopes_reject_traversal_symlink_escape_and_skill_write(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill = _write_skill(
        tmp_path / "skills",
        "file-skill",
        _contract(
            "file-skill",
            toolsets=["file"],
            files=[
                {"scope": "workspace", "access": "read_write"},
                {"scope": "skill", "access": "read"},
            ],
        ),
    )
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert _activate(skill, workspace=workspace).allowed

    allowed = _call(
        "write_file", {"path": str(workspace / "ok.txt")}, toolset="file"
    )
    traversal = _call(
        "read_file", {"path": "../outside.txt"}, toolset="file"
    )
    symlink = _call("read_file", {"path": str(link)}, toolset="file")
    skill_write = _call(
        "write_file", {"path": str(skill / "SKILL.md")}, toolset="file"
    )

    assert allowed.action == "allow"
    assert traversal.code == "file_scope_not_declared"
    assert symlink.code == "file_scope_not_declared"
    assert skill_write.code == "file_scope_not_declared"
    snapshot = get_turn_permission_snapshot("turn-1")
    assert snapshot is not None
    assert str(outside) not in json.dumps(snapshot)
    assert str(link) not in json.dumps(snapshot)


def test_network_hosts_and_methods_are_exact_when_url_is_inspectable(tmp_path):
    skill = _write_skill(
        tmp_path,
        "network-skill",
        _contract(
            "network-skill",
            toolsets=["web", "browser"],
            network=[{"host": "example.com", "methods": ["GET"]}],
        ),
    )
    assert _activate(skill).allowed

    exact = _call(
        "web_extract", {"urls": ["https://example.com/docs"]}, toolset="web"
    )
    subdomain = _call(
        "web_extract",
        {"urls": ["https://sub.example.com/docs"]},
        toolset="web",
    )
    observed_gap = _call("web_search", {"query": "test"}, toolset="web")
    indirect_browser = _call(
        "browser_click", {"ref": "e1"}, toolset="browser"
    )

    assert exact.action == "allow"
    assert subdomain.code == "network_target_not_declared"
    assert observed_gap.action == "allow"
    assert "network_target_uninspectable" in observed_gap.observations
    assert indirect_browser.action == "allow"
    assert (
        "browser_network_effect_uninspectable"
        in indirect_browser.observations
    )

    permissions._clear_permission_leases_for_tests()
    post_only = copy.deepcopy(_contract("post-skill", toolsets=["browser"]))
    post_only["permissions"]["network"] = [
        {"host": "example.com", "methods": ["POST"]}
    ]
    post_skill = _write_skill(tmp_path, "post-skill", post_only)
    assert _activate(post_skill).allowed
    method_mismatch = _call(
        "browser_navigate", {"url": "https://example.com"}, toolset="browser"
    )
    assert method_mismatch.code == "network_target_not_declared"


def test_toolset_and_tool_budget_are_enforced_atomically(tmp_path):
    skill = _write_skill(
        tmp_path,
        "budget-skill",
        _contract(
            "budget-skill",
            toolsets=["file"],
            files=[{"scope": "workspace", "access": "read"}],
            tool_calls=1,
        ),
    )
    assert _activate(skill, workspace=tmp_path).allowed

    wrong_toolset = _call("web_search", {"query": "x"}, toolset="web")
    exhausted = _call(
        "read_file", {"path": str(tmp_path / "x")}, toolset="file"
    )
    assert wrong_toolset.code == "toolset_not_declared"
    assert exhausted.code == "tool_budget_exhausted"

    permissions._clear_permission_leases_for_tests()
    assert _activate(skill, workspace=tmp_path).allowed
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(
            pool.map(
                lambda _index: _call(
                    "read_file", {"path": str(tmp_path / "x")}, toolset="file"
                ),
                range(8),
            )
        )
    assert sum(item.action == "allow" for item in decisions) == 1
    assert sum(item.code == "tool_budget_exhausted" for item in decisions) == 7


def test_wall_and_context_budgets_are_recorded_without_false_context_enforcement(
    tmp_path,
):
    contract = _contract(
        "budget-shapes",
        toolsets=["file"],
        files=[{"scope": "workspace", "access": "read"}],
    )
    contract["budgets"]["context_tokens"] = 321
    contract["budgets"]["wall_seconds"] = 0
    skill = _write_skill(tmp_path, "budget-shapes", contract)
    assert _activate(skill, workspace=tmp_path).allowed

    decision = _call(
        "read_file", {"path": str(tmp_path / "x")}, toolset="file"
    )
    snapshot = get_turn_permission_snapshot("turn-1")

    assert decision.code == "wall_budget_exhausted"
    assert snapshot is not None
    assert snapshot["leases"][0]["context_token_limit"] == 321
    assert snapshot["leases"][0]["wall_seconds_limit"] == 0
    assert "context_token_budget_uninspectable" in snapshot["observations"]


def test_concurrent_turns_are_isolated_and_task_fallback_is_unambiguous(tmp_path):
    skill = _write_skill(
        tmp_path,
        "isolated-skill",
        _contract(
            "isolated-skill",
            toolsets=["file"],
            files=[{"scope": "workspace", "access": "read"}],
            tool_calls=1,
        ),
    )
    assert _activate(skill, turn="turn-a", task="task-a", workspace=tmp_path).allowed
    assert _activate(skill, turn="turn-b", task="task-b", workspace=tmp_path).allowed

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(
            pool.map(
                lambda pair: _call(
                    "read_file",
                    {"path": str(tmp_path / "x")},
                    turn=pair[0],
                    task=pair[1],
                    toolset="file",
                ),
                [("turn-a", "task-a"), ("turn-b", "task-b")],
            )
        )
    assert first.action == second.action == "allow"

    nested = evaluate_skill_tool_call(
        tool_name="read_file",
        function_args={"path": str(tmp_path / "x")},
        turn_id=None,
        task_id="task-a",
        toolset="file",
    )
    assert nested.code == "tool_budget_exhausted"


def test_registry_cleanup_is_bounded(monkeypatch, tmp_path):
    skill = _write_skill(
        tmp_path,
        "bounded-skill",
        _contract("bounded-skill", toolsets=["file"]),
    )
    monkeypatch.setattr(permissions, "_MAX_ACTIVE_TURNS", 2)
    for index in range(3):
        assert _activate(skill, turn=f"turn-{index}", task=f"task-{index}").allowed

    assert get_turn_permission_snapshot("turn-0") is None
    assert get_turn_permission_snapshot("turn-1") is not None
    assert get_turn_permission_snapshot("turn-2") is not None
    evicted = evaluate_skill_tool_call(
        tool_name="read_file",
        function_args={"path": str(tmp_path / "input.txt")},
        turn_id="turn-0",
        task_id="task-0",
        toolset="file",
    )
    assert evicted.action == "block"
    assert evicted.code == "lease_registry_evicted"


def test_skill_view_forces_same_batch_sequential_order():
    from agent.tool_dispatch_helpers import _should_parallelize_tool_batch

    calls = [
        SimpleNamespace(
            function=SimpleNamespace(name="skill_view", arguments='{"name":"x"}')
        ),
        SimpleNamespace(
            function=SimpleNamespace(name="read_file", arguments='{"path":"x"}')
        ),
    ]
    assert not _should_parallelize_tool_batch(calls)


def test_skill_view_tool_establishes_the_current_turn_lease(monkeypatch, tmp_path):
    import tools.skill_usage as skill_usage
    import tools.skills_tool as skills_tool

    skill = _write_skill(
        tmp_path,
        "viewed-skill",
        _contract(
            "viewed-skill",
            toolsets=["file"],
            files=[{"scope": "workspace", "access": "read"}],
        ),
    )
    monkeypatch.setattr(skills_tool, "_skills_dir", lambda: tmp_path)
    monkeypatch.setattr(
        permissions,
        "load_permission_settings",
        lambda config=None: permissions.PermissionSettings("enforce_all"),
    )
    monkeypatch.setattr(skill_usage, "bump_use", lambda _name: None)
    monkeypatch.setattr(skill_usage, "bump_view", lambda _name: None)
    monkeypatch.setattr(
        "agent.skill_receipts.record_activation_best_effort", lambda **_kw: None
    )

    payload = json.loads(
        skills_tool._skill_view_with_bump(
            {"name": skill.name},
            turn_id="view-turn",
            task_id="view-task",
            session_id="view-session",
        )
    )

    assert payload["success"] is True
    snapshot = get_turn_permission_snapshot("view-turn")
    assert snapshot is not None
    assert snapshot["leases"][0]["skill"] == "viewed-skill"
    assert snapshot["leases"][0]["enforced"] is True


def test_dispatcher_uses_existing_approval_gate_without_exposing_args(
    monkeypatch, tmp_path
):
    import model_tools
    import tools.approval as approval

    secret_path = tmp_path / "private-name.txt"
    skill = _write_skill(
        tmp_path / "skills",
        "approval-skill",
        _contract(
            "approval-skill",
            toolsets=["file"],
            files=[{"scope": "workspace", "access": "read"}],
            approvals=["read_file"],
        ),
    )
    assert _activate(skill, workspace=tmp_path).allowed
    captured: dict[str, str] = {}

    def deny(tool_name, reason, *, rule_key="", approval_callback=None):
        del approval_callback
        captured.update(tool=tool_name, reason=reason, rule_key=rule_key)
        return {"approved": False, "message": "denied"}

    monkeypatch.setattr(approval, "request_tool_approval", deny)
    monkeypatch.setattr(
        model_tools.registry,
        "dispatch",
        lambda _name, _args, **_kwargs: json.dumps({"success": True}),
    )

    result = json.loads(
        model_tools.handle_function_call(
            "read_file",
            {"path": str(secret_path)},
            task_id="task-1",
            session_id="session-1",
            turn_id="turn-1",
            skip_pre_tool_call_hook=True,
            skip_tool_request_middleware=True,
        )
    )

    assert result["permission_code"] == "approval_denied"
    assert captured["tool"] == "read_file"
    assert captured["rule_key"].startswith("skill_permissions:")
    assert str(secret_path) not in captured["reason"]
    assert str(secret_path) not in json.dumps(result)


def test_sequential_direct_agent_tool_is_denied_before_execution(tmp_path):
    from agent.tool_executor import _run_agent_tool_execution_middleware

    skill = _write_skill(
        tmp_path,
        "direct-todo",
        _contract(
            "direct-todo",
            toolsets=["todo"],
            prohibitions=["todo"],
        ),
    )
    assert _activate(skill).allowed
    executed = False

    def execute(_args):
        nonlocal executed
        executed = True
        return "unexpected"

    result, _ = _run_agent_tool_execution_middleware(
        SimpleNamespace(
            session_id="session-1",
            _current_turn_id="turn-1",
        ),
        function_name="todo",
        function_args={"todos": [{"content": "private"}]},
        effective_task_id="task-1",
        tool_call_id="call-1",
        execute=execute,
    )

    assert executed is False
    assert json.loads(result)["permission_code"] == "action_prohibited"
    assert "private" not in result


def test_concurrent_direct_agent_tool_route_uses_same_permission_guard(tmp_path):
    from agent.agent_runtime_helpers import invoke_tool

    skill = _write_skill(
        tmp_path,
        "direct-memory",
        _contract(
            "direct-memory",
            toolsets=["memory"],
            prohibitions=["memory"],
        ),
    )
    assert _activate(skill).allowed
    agent = SimpleNamespace(
        session_id="session-1",
        _current_turn_id="turn-1",
        _current_api_request_id="request-1",
        _context_engine_tool_names=set(),
        _memory_manager=None,
    )

    result = invoke_tool(
        agent,
        "memory",
        {"action": "add", "content": "private"},
        "task-1",
        tool_call_id="call-1",
        pre_tool_block_checked=True,
        skip_tool_request_middleware=True,
    )

    assert json.loads(result)["permission_code"] == "action_prohibited"
    assert "private" not in result


def test_activation_does_not_change_model_tool_schema(tmp_path):
    from model_tools import get_tool_definitions

    skill = _write_skill(
        tmp_path,
        "cache-stable-skill",
        _contract("cache-stable-skill", toolsets=["file"]),
    )
    before = copy.deepcopy(get_tool_definitions(quiet_mode=True))
    assert _activate(skill).allowed
    after = copy.deepcopy(get_tool_definitions(quiet_mode=True))

    assert before == after


def test_one_shot_staged_lease_binds_to_exactly_one_turn(tmp_path):
    skill = _write_skill(
        tmp_path / "skills",
        "staged-once",
        _contract(
            "staged-once",
            toolsets=["file"],
            files=[{"scope": "workspace", "access": "read"}],
        ),
    )
    decision = stage_skill_permission_lease(
        skill_dir=skill,
        canonical_name="staged-once",
        scope_id="session-staged",
        workspace_root=tmp_path,
        config={"skills": {"permissions": {"mode": "enforce_all"}}},
    )

    assert decision.allowed
    assert decision.code == "turn_lease_staged"
    assert bind_staged_skill_permission_leases(
        turn_id="bound-turn-1", session_id="session-staged"
    ) == 1
    assert get_turn_permission_snapshot("bound-turn-1") is not None
    assert bind_staged_skill_permission_leases(
        turn_id="bound-turn-2", session_id="session-staged"
    ) == 0
    assert get_turn_permission_snapshot("bound-turn-2") is None


def test_session_staged_lease_rebinds_with_an_independent_budget(tmp_path):
    skill = _write_skill(
        tmp_path / "skills",
        "session-staged",
        _contract(
            "session-staged",
            toolsets=["file"],
            files=[{"scope": "workspace", "access": "read"}],
            tool_calls=1,
        ),
    )
    decision = stage_skill_permission_lease(
        skill_dir=skill,
        canonical_name="session-staged",
        scope_id="persistent-session",
        session_wide=True,
        workspace_root=tmp_path,
        config={"skills": {"permissions": {"mode": "enforce_all"}}},
    )

    assert decision.code == "session_lease_staged"
    for turn_id in ("session-turn-1", "session-turn-2"):
        assert bind_staged_skill_permission_leases(
            turn_id=turn_id, session_id="persistent-session"
        ) == 1
        first = evaluate_skill_tool_call(
            tool_name="read_file",
            function_args={"path": str(tmp_path / "input.txt")},
            turn_id=turn_id,
            toolset="file",
        )
        second = evaluate_skill_tool_call(
            tool_name="read_file",
            function_args={"path": str(tmp_path / "input.txt")},
            turn_id=turn_id,
            toolset="file",
        )
        assert first.action == "allow"
        assert second.code == "tool_budget_exhausted"


def test_staged_capacity_blocks_new_enforced_scope_without_evicting_old(
    monkeypatch, tmp_path
):
    first_skill = _write_skill(
        tmp_path / "skills",
        "first-staged",
        _contract("first-staged", toolsets=["file"]),
    )
    second_skill = _write_skill(
        tmp_path / "skills",
        "second-staged",
        _contract("second-staged", toolsets=["file"]),
    )
    monkeypatch.setattr(permissions, "_MAX_STAGED_SCOPES", 1)

    first = stage_skill_permission_lease(
        skill_dir=first_skill,
        canonical_name="first-staged",
        scope_id="scope-one",
        config={"skills": {"permissions": {"mode": "enforce_all"}}},
    )
    second = stage_skill_permission_lease(
        skill_dir=second_skill,
        canonical_name="second-staged",
        scope_id="scope-two",
        config={"skills": {"permissions": {"mode": "enforce_all"}}},
    )

    assert first.allowed
    assert second.action == "blocked"
    assert second.code == "staged_registry_capacity_exceeded"
    assert bind_staged_skill_permission_leases(
        turn_id="still-bound", session_id="scope-one"
    ) == 1


def test_scheduled_skill_stages_against_the_concrete_cron_session(
    monkeypatch, tmp_path
):
    from cron.scheduler import _build_job_prompt
    import tools.skill_usage
    import tools.skills_tool

    skill = _write_skill(
        tmp_path,
        "scheduled-skill",
        _contract("scheduled-skill", toolsets=["file"]),
    )
    monkeypatch.setattr(
        permissions,
        "load_permission_settings",
        lambda _config=None: permissions.PermissionSettings("enforce_all"),
    )
    monkeypatch.setattr(
        tools.skills_tool,
        "skill_view",
        lambda _name: json.dumps(
            {
                "success": True,
                "name": "scheduled-skill",
                "skill_dir": str(skill),
                "content": "# Scheduled fixture",
            }
        ),
    )
    monkeypatch.setattr(tools.skill_usage, "bump_use", lambda _name: None)

    prompt = _build_job_prompt(
        {
            "id": "job-1",
            "_permission_scope": "cron-session-1",
            "skills": ["scheduled-skill"],
            "prompt": "run",
        }
    )

    assert "Scheduled fixture" in prompt
    assert bind_staged_skill_permission_leases(
        turn_id="cron-turn-1", session_id="cron-session-1"
    ) == 1
    assert get_turn_permission_snapshot("cron-turn-1") is not None


def test_context_turn_stack_clears_nested_concrete_turns_only(tmp_path):
    skill = _write_skill(
        tmp_path,
        "nested-cleanup",
        _contract("nested-cleanup", toolsets=["file"]),
    )
    bind_staged_skill_permission_leases(turn_id="outer-turn")
    assert _activate(skill, turn="outer-turn").allowed
    bind_staged_skill_permission_leases(turn_id="inner-turn")
    assert _activate(skill, turn="inner-turn").allowed

    assert get_current_permission_turn_id() == "inner-turn"
    assert finalize_current_turn_permission_leases() == "inner-turn"
    assert get_turn_permission_snapshot("inner-turn") is None
    late_inner = evaluate_skill_tool_call(
        tool_name="read_file",
        function_args={"path": str(tmp_path / "late")},
        turn_id="inner-turn",
        toolset="file",
    )
    assert late_inner.code == "lease_registry_evicted"
    assert late_inner.action == "block"
    assert get_turn_permission_snapshot("outer-turn") is not None
    assert get_current_permission_turn_id() == "outer-turn"
    assert finalize_current_turn_permission_leases() == "outer-turn"
    assert get_current_permission_turn_id() is None


@pytest.mark.parametrize("raises", [False, True])
def test_agent_forwarder_finally_clears_early_return_and_error_paths(
    monkeypatch, tmp_path, raises
):
    import agent.conversation_loop
    from run_agent import AIAgent

    skill = _write_skill(
        tmp_path,
        "forwarder-cleanup",
        _contract("forwarder-cleanup", toolsets=["file"]),
    )

    def fake_run(*_args, **_kwargs):
        bind_staged_skill_permission_leases(turn_id="forwarder-turn")
        assert _activate(skill, turn="forwarder-turn").allowed
        if raises:
            raise RuntimeError("fixture")
        return {"completed": True}

    monkeypatch.setattr(agent.conversation_loop, "run_conversation", fake_run)
    if raises:
        with pytest.raises(RuntimeError, match="fixture"):
            AIAgent.run_conversation(SimpleNamespace(), "test")
    else:
        assert AIAgent.run_conversation(SimpleNamespace(), "test") == {
            "completed": True
        }

    assert get_current_permission_turn_id() is None
    assert get_turn_permission_snapshot("forwarder-turn") is None


def test_pre_prologue_nested_failure_preserves_outer_permission_turn(
    monkeypatch, tmp_path
):
    import agent.conversation_loop
    from run_agent import AIAgent

    skill = _write_skill(
        tmp_path,
        "outer-preserved",
        _contract("outer-preserved", toolsets=["file"]),
    )
    bind_staged_skill_permission_leases(turn_id="outer-preserved-turn")
    assert _activate(skill, turn="outer-preserved-turn").allowed

    def fail_before_prologue(*_args, **_kwargs):
        raise RuntimeError("before prologue")

    monkeypatch.setattr(
        agent.conversation_loop, "run_conversation", fail_before_prologue
    )
    with pytest.raises(RuntimeError, match="before prologue"):
        AIAgent.run_conversation(SimpleNamespace(), "test")

    assert get_current_permission_turn_id() == "outer-preserved-turn"
    assert get_turn_permission_snapshot("outer-preserved-turn") is not None
    assert finalize_current_turn_permission_leases() == "outer-preserved-turn"
