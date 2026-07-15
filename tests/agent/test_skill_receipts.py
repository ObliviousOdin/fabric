from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.skill_permissions import derive_skill_risk_lane
from agent.skill_receipts import (
    JOURNAL_FILENAME,
    ReceiptIOError,
    ReceiptValidationError,
    _clear_receipt_correlations_for_tests,
    _clear_skill_identity_cache,
    _governance_lane,
    aggregate_receipts,
    append_receipt,
    bind_pending_activation_receipts,
    finalize_agent_turn_receipts_best_effort,
    read_receipts,
    record_activation,
    record_outcome,
    record_turn_outcome_best_effort,
    validate_receipt,
)
from agent.skill_utils import is_excluded_skill_path
from fabric_constants import reset_fabric_home_override, set_fabric_home_override


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


@pytest.fixture(autouse=True)
def _isolated_receipt_correlations():
    _clear_receipt_correlations_for_tests()
    yield
    _clear_receipt_correlations_for_tests()


def _config(*, max_bytes: int = 1024 * 1024, max_files: int = 4) -> dict:
    return {
        "skills": {
            "receipts": {
                "enabled": True,
                "max_bytes": max_bytes,
                "max_files": max_files,
            }
        }
    }


def _activation(
    event_id: str = "act_00000000000000000000000000000001",
    *,
    name: str = "demo-skill",
    version: str = "1.0.0",
    timestamp: str = "2026-07-14T12:00:00.000Z",
) -> dict:
    return {
        "schema": "fabric.skill-receipt/v1",
        "event": "activation",
        "event_id": event_id,
        "timestamp": timestamp,
        "profile": "default",
        "skill": {
            "name": name,
            "version": version,
            "tree_sha256": DIGEST_A,
            "contract_sha256": None,
            "contract_status": "legacy_unverified",
        },
        "selection": {"source": "explicit_slash", "reason": "user_invoked"},
        "governance": {"mode": "legacy", "lane": "unknown"},
    }


def _outcome(
    activation_id: str,
    event_id: str = "out_00000000000000000000000000000001",
    *,
    status: str = "completed",
    duration_ms: int = 100,
    timestamp: str = "2026-07-14T12:00:01.000Z",
    rollback: str | None = None,
    routing_relevant: bool | None = None,
) -> dict:
    guardrails = [{"key": "safe_result", "passed": True}]
    if routing_relevant is not None:
        guardrails.append({"key": "routing_relevant", "passed": routing_relevant})
    return {
        "schema": "fabric.skill-receipt/v1",
        "event": "outcome",
        "event_id": event_id,
        "timestamp": timestamp,
        "profile": "default",
        "activation_ids": [activation_id],
        "status": status,
        "duration_ms": duration_ms,
        "counts": {
            "api_calls": 2,
            "tool_calls": 3,
            "total_tokens": 50,
            "approvals": 1,
            "cost_microusd": 25,
        },
        "outcome_key": "task_completed",
        "guardrails": guardrails,
        "digests": {"active": DIGEST_A, "prior": None, "rollback": rollback},
    }


def _make_skill(root: Path, *, body: str = "Do the work.") -> Path:
    skill_dir = root / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: demo-skill\n"
        "description: A deterministic receipt test skill.\n"
        "version: 1.0.0\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return skill_dir


@pytest.mark.parametrize(
    "toolset",
    [
        "browser",
        "code_execution",
        "context_engine",
        "delegation",
        "memory",
        "skills",
        "terminal",
        "web",
    ],
)
def test_receipt_lane_matches_runtime_for_opaque_effect_toolsets(toolset):
    contract = {
        "permissions": {
            "toolsets_required": [toolset],
            "files": [],
            "network": [],
            "secrets": [],
            "actions": {"approval_required": [], "prohibited": []},
        }
    }

    runtime_lane = derive_skill_risk_lane(contract, "verified")

    assert runtime_lane == "elevated"
    assert _governance_lane(contract, "verified") == runtime_lane


def test_receipt_lane_matches_runtime_for_standard_read_only_contract():
    contract = {
        "permissions": {
            "toolsets_required": ["file"],
            "files": [{"access": "read", "path": "workspace/**"}],
            "network": [],
            "secrets": [],
            "actions": {"approval_required": [], "prohibited": []},
        }
    }

    runtime_lane = derive_skill_risk_lane(contract, "verified")

    assert runtime_lane == "standard"
    assert _governance_lane(contract, "verified") == runtime_lane


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt", "the user's private prompt"),
        ("response", "the model's private response"),
        ("tool_arguments", {"token": "secret"}),
        ("file_content", "private bytes"),
        ("error", "arbitrary failure text"),
    ],
)
def test_activation_rejects_privacy_unsafe_unknown_fields(field, value):
    receipt = _activation()
    receipt[field] = value
    with pytest.raises(ReceiptValidationError, match="unknown receipt fields"):
        validate_receipt(receipt)


def test_outcome_rejects_unknown_text_and_count_fields():
    receipt = _outcome("act_00000000000000000000000000000001")
    receipt["error_message"] = "secret-bearing model output"
    with pytest.raises(ReceiptValidationError, match="unknown receipt fields"):
        validate_receipt(receipt)

    receipt = _outcome("act_00000000000000000000000000000001")
    receipt["counts"]["custom_note"] = 1
    with pytest.raises(ReceiptValidationError, match="unknown counts fields"):
        validate_receipt(receipt)


def test_local_receipts_can_be_disabled_without_creating_state(tmp_path):
    config = {"skills": {"receipts": {"enabled": False}}}
    assert append_receipt(_activation(), home=tmp_path, config=config) is False
    assert not (tmp_path / "skills" / ".governance").exists()


def test_context_identifiers_are_hmac_bound_and_files_are_private(tmp_path):
    skill_dir = _make_skill(tmp_path)
    activation_id = record_activation(
        skill_dir=skill_dir,
        canonical_name="demo-skill",
        source="explicit_slash",
        reason="user_invoked",
        session_id="session-private-123",
        task_id="task-private-456",
        turn_id="turn-private-789",
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )
    assert activation_id and activation_id.startswith("act_")
    records = read_receipts(home=tmp_path, config=_config())
    assert len(records) == 1
    record = records[0]
    serialized = json.dumps(record)
    assert "session-private-123" not in serialized
    assert "task-private-456" not in serialized
    assert "turn-private-789" not in serialized
    assert record["session_ref"].startswith("hmac-sha256:")
    governance = tmp_path / "skills" / ".governance"
    for name in (JOURNAL_FILENAME, "skill-receipts.key", "skill-receipts.lock"):
        path = governance / name
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (governance / "skill-receipts.key").stat().st_size == 32


def test_wrong_sized_context_key_fails_closed_for_receipt_only(tmp_path):
    skill_dir = _make_skill(tmp_path)
    governance = tmp_path / "skills" / ".governance"
    governance.mkdir()
    (governance / "skill-receipts.key").write_bytes(b"short")
    with pytest.raises(ReceiptIOError, match="exactly 32 bytes"):
        record_activation(
            skill_dir=skill_dir,
            source="preload",
            reason="session_preload",
            home=tmp_path,
            config=_config(),
            timestamp=NOW,
        )


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation requires elevated Windows privileges"
)
def test_redirected_plugin_skill_directory_is_not_hashed(tmp_path):
    real_home = tmp_path / "real"
    real_skill = _make_skill(real_home)
    redirected = tmp_path / "plugin-skill"
    redirected.symlink_to(real_skill, target_is_directory=True)
    with pytest.raises(ReceiptIOError, match="non-symlink directory"):
        record_activation(
            skill_dir=redirected,
            canonical_name="plugin:demo-skill",
            source="skill_view",
            reason="agent_selected",
            home=tmp_path / "profile",
            config=_config(),
            timestamp=NOW,
        )


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation requires elevated Windows privileges"
)
def test_symlinked_governance_and_journal_are_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / ".governance").symlink_to(target, target_is_directory=True)
    with pytest.raises(ReceiptIOError, match="non-symlink directory"):
        append_receipt(_activation(), home=tmp_path, config=_config())

    (skills / ".governance").unlink()
    governance = skills / ".governance"
    governance.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("", encoding="utf-8")
    (governance / JOURNAL_FILENAME).symlink_to(outside)
    with pytest.raises(ReceiptIOError, match="regular and non-symlink"):
        append_receipt(_activation(), home=tmp_path, config=_config())


def test_concurrent_writes_produce_complete_json_lines(tmp_path):
    config = _config()

    def write(index: int) -> None:
        receipt = _activation(f"act_{index:032x}")
        append_receipt(receipt, home=tmp_path, config=config)

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(write, range(1, 81)))

    path = tmp_path / "skills" / ".governance" / JOURNAL_FILENAME
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 80
    assert len({json.loads(line)["event_id"] for line in lines}) == 80


def test_rotation_is_bounded_and_retains_newest_records(tmp_path):
    config = _config(max_bytes=64 * 1024, max_files=2)
    # Inflate valid records with optional context refs until rotation occurs.
    for index in range(1, 240):
        receipt = _activation(f"act_{index:032x}")
        receipt["session_ref"] = "hmac-sha256:" + f"{index:064x}"[-64:]
        append_receipt(receipt, home=tmp_path, config=config)

    governance = tmp_path / "skills" / ".governance"
    journals = sorted(governance.glob("skill-receipts*.jsonl"))
    assert [path.name for path in journals] == [
        "skill-receipts.1.jsonl",
        "skill-receipts.jsonl",
    ]
    assert all(path.stat().st_size <= 64 * 1024 for path in journals)
    ids = {record["event_id"] for record in read_receipts(home=tmp_path, config=config)}
    assert "act_000000000000000000000000000000ef" in ids
    assert "act_00000000000000000000000000000001" not in ids


def test_corrupt_lines_are_skipped_without_losing_valid_receipts(tmp_path):
    config = _config()
    append_receipt(_activation(), home=tmp_path, config=config)
    path = tmp_path / "skills" / ".governance" / JOURNAL_FILENAME
    with path.open("ab") as handle:
        handle.write(b"not-json\n")
        handle.write(b'{"event":"activation","prompt":"private"}\n')
    records = read_receipts(home=tmp_path, config=config)
    assert [record["event_id"] for record in records] == [
        "act_00000000000000000000000000000001"
    ]


def test_deterministic_aggregation_separates_completion_from_routing_precision():
    a1 = _activation("act_00000000000000000000000000000001")
    a2 = _activation(
        "act_00000000000000000000000000000002",
        timestamp="2026-07-14T12:00:02.000Z",
    )
    a3 = _activation(
        "act_00000000000000000000000000000003",
        version="2.0.0",
        timestamp="2026-07-14T12:00:04.000Z",
    )
    o1 = _outcome(a1["event_id"], routing_relevant=True)
    o2 = _outcome(
        a2["event_id"],
        "out_00000000000000000000000000000002",
        status="failed",
        duration_ms=300,
        timestamp="2026-07-14T12:00:03.000Z",
        rollback=DIGEST_B,
        routing_relevant=False,
    )
    first = aggregate_receipts([o2, a3, a1, o1, a2])
    second = aggregate_receipts([a2, o1, a1, a3, o2])
    assert first == second
    v1 = first["skills"][0]
    assert v1["activations"] == 2
    assert v1["completion_coverage"] == 0.5
    assert v1["completion_rate"] == 0.5
    assert v1["failure_rate"] == 0.5
    assert v1["routing_precision"] == 0.5
    assert v1["latency_ms"] == {"average": 200.0, "p50": 100, "p95": 300}
    assert v1["budget_totals"]["total_tokens"] == 100
    assert v1["approvals"] == 2
    assert v1["rollback_count"] == 1
    v2 = first["skills"][1]
    assert v2["routing_precision"] is None
    assert first["totals"]["routing_precision"] == 0.5


def test_explicit_outcome_api_round_trips_structured_metrics(tmp_path):
    activation_id = "act_00000000000000000000000000000001"
    append_receipt(_activation(activation_id), home=tmp_path, config=_config())
    outcome_id = record_outcome(
        activation_ids=[activation_id],
        status="interrupted",
        duration_ms=125,
        counts={"api_calls": 1, "tool_calls": 2, "total_tokens": 30},
        outcome_key="user_stopped",
        guardrails=[{"key": "no_unapproved_write", "passed": True}],
        active_digest=DIGEST_A,
        prior_digest=DIGEST_B,
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )
    assert outcome_id and outcome_id.startswith("out_")
    records = read_receipts(home=tmp_path, config=_config())
    assert records[-1]["status"] == "interrupted"


def test_turn_correlation_closes_activation_with_efficiency_metrics(tmp_path):
    skill_dir = _make_skill(tmp_path)
    activation_id = record_activation(
        skill_dir=skill_dir,
        source="skill_view",
        reason="agent_selected",
        session_id="private-session",
        task_id="private-task",
        turn_id="private-turn",
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )

    outcome_id = record_turn_outcome_best_effort(
        turn_id="private-turn",
        status="completed",
        duration_ms=250,
        counts={
            "api_calls": 2,
            "tool_calls": 3,
            "total_tokens": 80,
            "cache_read_tokens": 20,
            "cost_microusd": 40,
        },
        home=tmp_path,
        config=_config(),
    )

    assert activation_id and outcome_id
    records = read_receipts(home=tmp_path, config=_config())
    assert records[-1]["activation_ids"] == [activation_id]
    assert "private-turn" not in json.dumps(records)
    metrics = aggregate_receipts(records)
    assert metrics["totals"]["completion_coverage"] == 1.0
    skill_metrics = metrics["skills"][0]
    assert skill_metrics["budget_totals"]["tool_calls"] == 3
    assert skill_metrics["budget_totals"]["cache_read_tokens"] == 20
    assert skill_metrics["budget_totals"]["cost_microusd"] == 40
    assert skill_metrics["outcomes"] == {}


def test_pre_turn_activation_binds_only_to_its_exact_task(tmp_path):
    skill_dir = _make_skill(tmp_path)
    activation_id = record_activation(
        skill_dir=skill_dir,
        source="explicit_slash",
        reason="user_invoked",
        session_id="shared-session",
        task_id="expected-task",
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )

    assert (
        bind_pending_activation_receipts(
            turn_id="wrong-turn",
            task_id="other-task",
            session_id="shared-session",
        )
        == 0
    )
    assert (
        bind_pending_activation_receipts(
            turn_id="expected-turn",
            task_id="expected-task",
            session_id="shared-session",
        )
        == 1
    )
    outcome_id = record_turn_outcome_best_effort(
        turn_id="expected-turn",
        status="failed",
        duration_ms=10,
        counts={"api_calls": 1},
        home=tmp_path,
        config=_config(),
    )
    assert activation_id and outcome_id
    assert (
        record_turn_outcome_best_effort(
            turn_id="wrong-turn",
            status="completed",
            duration_ms=1,
            home=tmp_path,
            config=_config(),
        )
        is None
    )


def test_session_preload_is_not_falsely_attributed_to_first_turn(tmp_path):
    skill_dir = _make_skill(tmp_path)
    activation_id = record_activation(
        skill_dir=skill_dir,
        source="preload",
        reason="session_preload",
        session_id="preload-session",
        task_id="preload-session",
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )

    assert activation_id
    assert (
        bind_pending_activation_receipts(
            turn_id="first-turn",
            task_id="first-task",
            session_id="preload-session",
        )
        == 0
    )
    assert (
        record_turn_outcome_best_effort(
            turn_id="first-turn",
            status="completed",
            duration_ms=1,
            home=tmp_path,
            config=_config(),
        )
        is None
    )


def test_agent_turn_finalizer_uses_deltas_and_current_turn_tools_only(tmp_path):
    skill_dir = _make_skill(tmp_path)
    activation_id = record_activation(
        skill_dir=skill_dir,
        source="skill_view",
        reason="agent_selected",
        turn_id="current-turn",
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )
    agent = SimpleNamespace(
        _current_turn_id="current-turn",
        session_input_tokens=110,
        session_output_tokens=55,
        session_prompt_tokens=120,
        session_completion_tokens=60,
        session_total_tokens=180,
        session_cache_read_tokens=25,
        session_cache_write_tokens=4,
        session_reasoning_tokens=8,
        session_estimated_cost_usd=0.0015,
    )
    baseline = {
        "previous_turn_id": "previous-turn",
        "started_at": 0.0,
        "session_input_tokens": 100,
        "session_output_tokens": 50,
        "session_prompt_tokens": 105,
        "session_completion_tokens": 50,
        "session_total_tokens": 155,
        "session_cache_read_tokens": 20,
        "session_cache_write_tokens": 4,
        "session_reasoning_tokens": 5,
        "session_estimated_cost_usd": 0.001,
    }
    result = {
        "completed": True,
        "failed": False,
        "interrupted": False,
        "api_calls": 2,
        "messages": [
            {"role": "user", "content": "previous"},
            {"role": "assistant", "tool_calls": [{"id": "old"}]},
            {"role": "tool", "content": "old"},
            {"role": "user", "content": "private current prompt"},
            {
                "role": "assistant",
                "tool_calls": [{"id": "one"}, {"id": "two"}],
            },
            {"role": "assistant", "content": "private response"},
        ],
    }

    token = set_fabric_home_override(tmp_path)
    try:
        outcome_id = finalize_agent_turn_receipts_best_effort(
            agent=agent,
            result=result,
            baseline=baseline,
        )
    finally:
        reset_fabric_home_override(token)

    assert activation_id and outcome_id
    outcome = read_receipts(home=tmp_path, config=_config())[-1]
    assert outcome["activation_ids"] == [activation_id]
    assert outcome["counts"]["api_calls"] == 2
    assert outcome["counts"]["tool_calls"] == 2
    assert outcome["counts"]["input_tokens"] == 10
    assert outcome["counts"]["total_tokens"] == 25
    assert outcome["counts"]["cost_microusd"] == 500
    encoded = json.dumps(outcome)
    assert "private current prompt" not in encoded
    assert "private response" not in encoded


def test_agent_forwarder_finalizes_receipts_and_permission_turn(tmp_path, monkeypatch):
    import agent.conversation_loop as conversation_loop
    import agent.skill_receipts as receipts
    from agent.skill_permissions import (
        bind_staged_skill_permission_leases,
        get_current_permission_turn_id,
    )
    from run_agent import AIAgent

    skill_dir = _make_skill(tmp_path)
    agent = SimpleNamespace(
        _current_turn_id=None,
        session_input_tokens=10,
        session_output_tokens=5,
        session_prompt_tokens=10,
        session_completion_tokens=5,
        session_total_tokens=15,
        session_cache_read_tokens=2,
        session_cache_write_tokens=0,
        session_reasoning_tokens=1,
        session_estimated_cost_usd=0.001,
    )
    monkeypatch.setattr(
        receipts,
        "load_receipt_settings",
        lambda _config=None: receipts.ReceiptSettings(True, 1024 * 1024, 4),
    )

    def fake_conversation(*_args, **_kwargs):
        agent._current_turn_id = "wrapper-turn"
        bind_staged_skill_permission_leases(
            turn_id="wrapper-turn",
            task_id="wrapper-task",
            session_id="wrapper-session",
        )
        record_activation(
            skill_dir=skill_dir,
            source="skill_view",
            reason="agent_selected",
            turn_id="wrapper-turn",
            home=tmp_path,
            config=_config(),
            timestamp=NOW,
        )
        agent.session_input_tokens += 7
        agent.session_output_tokens += 3
        agent.session_prompt_tokens += 7
        agent.session_completion_tokens += 3
        agent.session_total_tokens += 10
        agent.session_cache_read_tokens += 2
        agent.session_reasoning_tokens += 1
        agent.session_estimated_cost_usd += 0.00025
        return {
            "completed": True,
            "failed": False,
            "interrupted": False,
            "api_calls": 1,
            "messages": [
                {"role": "user", "content": "private"},
                {"role": "assistant", "tool_calls": [{"id": "call"}]},
            ],
            "final_response": "done",
        }

    monkeypatch.setattr(conversation_loop, "run_conversation", fake_conversation)
    token = set_fabric_home_override(tmp_path)
    try:
        result = AIAgent.run_conversation(agent, "private")
    finally:
        reset_fabric_home_override(token)

    assert result["final_response"] == "done"
    assert get_current_permission_turn_id() is None
    outcome = read_receipts(home=tmp_path, config=_config())[-1]
    assert outcome["event"] == "outcome"
    assert outcome["counts"]["api_calls"] == 1
    assert outcome["counts"]["tool_calls"] == 1
    assert outcome["counts"]["total_tokens"] == 10
    assert outcome["counts"]["cost_microusd"] == 250


def test_skill_digest_cache_hits_and_invalidates_on_content_change(
    tmp_path, monkeypatch
):
    skill_dir = _make_skill(tmp_path)
    _clear_skill_identity_cache()
    from tools import skill_install

    real_hash = skill_install.sha256_tree
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return real_hash(*args, **kwargs)

    monkeypatch.setattr(skill_install, "sha256_tree", counted)
    first = record_activation(
        skill_dir=skill_dir,
        source="explicit_slash",
        reason="user_invoked",
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )
    second = record_activation(
        skill_dir=skill_dir,
        source="explicit_slash",
        reason="user_invoked",
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )
    assert first and second
    assert len(calls) == 1

    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8"
    )
    os.utime(skill_md, None)
    third = record_activation(
        skill_dir=skill_dir,
        source="explicit_slash",
        reason="user_invoked",
        home=tmp_path,
        config=_config(),
        timestamp=NOW,
    )
    assert third
    assert len(calls) == 2
    digests = [
        record["skill"]["tree_sha256"]
        for record in read_receipts(home=tmp_path, config=_config())
    ]
    assert digests[0] == digests[1]
    assert digests[2] != digests[1]


def test_governance_directory_is_never_a_discoverable_skill(tmp_path):
    hidden = tmp_path / "skills" / ".governance" / "poison" / "SKILL.md"
    hidden.parent.mkdir(parents=True)
    hidden.write_text(
        "---\nname: poison\ndescription: hidden\n---\nbody", encoding="utf-8"
    )
    assert is_excluded_skill_path(hidden) is True


def test_explicit_slash_activation_integration(tmp_path):
    import agent.skill_commands as skill_commands

    _make_skill(tmp_path)
    token = set_fabric_home_override(tmp_path)
    try:
        skill_commands._skill_commands = {}
        with patch("tools.skills_tool.SKILLS_DIR", tmp_path / "skills"):
            commands = skill_commands.scan_skill_commands()
            assert "/demo-skill" in commands
            message = skill_commands.build_skill_invocation_message(
                "/demo-skill", "run it", task_id="session-1"
            )
        assert message and "run it" in message
        records = read_receipts(home=tmp_path, config=_config())
        activation = records[-1]
        assert activation["selection"] == {
            "source": "explicit_slash",
            "reason": "user_invoked",
        }
        assert "session-1" not in json.dumps(activation)
    finally:
        skill_commands._skill_commands = {}
        reset_fabric_home_override(token)


def test_skill_view_tool_activation_carries_turn_correlation(tmp_path):
    from tools.skills_tool import _skill_view_with_bump

    _make_skill(tmp_path)
    token = set_fabric_home_override(tmp_path)
    try:
        with patch("tools.skills_tool.SKILLS_DIR", tmp_path / "skills"):
            result = json.loads(
                _skill_view_with_bump(
                    {"name": "demo-skill"},
                    session_id="session-1",
                    task_id="task-1",
                    turn_id="turn-1",
                )
            )
        assert result["success"] is True
        activation = read_receipts(home=tmp_path, config=_config())[-1]
        assert activation["selection"]["source"] == "skill_view"
        assert set(activation) >= {"session_ref", "task_ref", "turn_ref"}
        assert "turn-1" not in json.dumps(activation)
    finally:
        reset_fabric_home_override(token)


def test_cron_declared_skill_activation_integration(tmp_path):
    from cron.scheduler import _build_job_prompt

    _make_skill(tmp_path)
    token = set_fabric_home_override(tmp_path)
    try:
        with patch("tools.skills_tool.SKILLS_DIR", tmp_path / "skills"):
            prompt = _build_job_prompt({
                "id": "0123456789ab",
                "name": "daily-demo",
                "prompt": "run the report",
                "skills": ["demo-skill"],
            })
        assert "scheduled cron job" in prompt
        activation = read_receipts(home=tmp_path, config=_config())[-1]
        assert activation["selection"] == {
            "source": "scheduled",
            "reason": "declared_job",
        }
    finally:
        reset_fabric_home_override(token)
