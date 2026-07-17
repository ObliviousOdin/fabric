"""Tests for the memory/skill write-approval gate (tools/write_approval.py)
and the shared slash-command handlers (fabric_cli/write_approval_commands.py).

Covers the boolean write_approval gate (off by default = write freely; on =
require approval) for both subsystems, the foreground-vs-background staging
split, pending store CRUD, and the list/approve/reject/diff/approval
subcommand dispatch.
"""

import json
import os
import stat
import tempfile
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def fabric_home(monkeypatch):
    d = tempfile.mkdtemp(prefix="fabric_wa_test_")
    home = os.path.join(d, ".hermes")
    os.makedirs(home)
    monkeypatch.setenv("FABRIC_HOME", home)
    yield home
    shutil.rmtree(d, ignore_errors=True)


def _set_approval(subsystem, enabled):
    import fabric_cli.config as cfg
    c = cfg.load_config()
    c.setdefault(subsystem, {})["write_approval"] = enabled
    cfg.save_config(c)


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def test_default_gate_is_off(fabric_home):
    from tools import write_approval as wa
    # Default: gate off → writes flow freely.
    assert wa.write_approval_enabled("memory") is False
    assert wa.write_approval_enabled("skills") is False


def test_invalid_subsystem_is_off(fabric_home):
    from tools import write_approval as wa
    assert wa.write_approval_enabled("bogus") is False


def test_normalize_enabled_coerces_values():
    from tools import write_approval as wa
    # Real bools pass through.
    assert wa._normalize_enabled(True) is True
    assert wa._normalize_enabled(False) is False
    # Truthy strings → True (incl. legacy 'approve').
    assert wa._normalize_enabled("on") is True
    assert wa._normalize_enabled("approve") is True
    assert wa._normalize_enabled("true") is True
    # Everything else → False (gate off is the safe default).
    assert wa._normalize_enabled("off") is False
    assert wa._normalize_enabled("garbage") is False
    assert wa._normalize_enabled(None) is False


# ---------------------------------------------------------------------------
# Memory gate
# ---------------------------------------------------------------------------

def test_memory_gate_off_allows_write(fabric_home):
    # Default (gate off) → write straight through, no staging.
    from tools.memory_tool import memory_tool, MemoryStore
    from tools import write_approval as wa
    store = MemoryStore(); store.load_from_disk()
    r = json.loads(memory_tool("add", "user", "save me", store=store))
    assert r["success"] is True
    assert r["entry_count"] == 1
    assert wa.pending_count("memory") == 0


def test_memory_gate_on_no_interactive_stages(fabric_home):
    # Gate on, no approval callback / not a gateway context → stage.
    from tools.memory_tool import memory_tool, MemoryStore
    from tools import write_approval as wa
    _set_approval("memory", True)
    store = MemoryStore(); store.load_from_disk()
    r = json.loads(memory_tool("add", "memory", "stage me", store=store))
    assert r.get("staged") is True
    assert r.get("pending_id")
    # Not written to the live store yet.
    assert store.memory_entries == []
    pend = wa.list_pending("memory")
    assert len(pend) == 1
    assert pend[0]["id"] == r["pending_id"]


def test_memory_gate_on_then_apply(fabric_home):
    from tools.memory_tool import memory_tool, MemoryStore, apply_memory_pending
    from tools import write_approval as wa
    _set_approval("memory", True)
    store = MemoryStore(); store.load_from_disk()
    r = json.loads(memory_tool("add", "user", "approved entry", store=store))
    pid = r["pending_id"]
    rec = wa.get_pending("memory", pid)
    result = apply_memory_pending(rec["payload"], store)
    assert result["success"] is True
    assert "approved entry" in store.user_entries[0]


def test_cli_memory_approve_without_live_agent_uses_fresh_store(fabric_home, capsys):
    """#46783: ``/memory approve`` from a context with no live agent (e.g. the
    Desktop GUI) passed ``memory_store=None`` into the shared handler, which
    returned "memory store unavailable" and applied nothing. The CLI handler must
    fall back to a freshly loaded on-disk store, like the gateway path does."""
    import json
    from tools.memory_tool import memory_tool, MemoryStore
    from tools import write_approval as wa
    from fabric_cli.cli_commands_mixin import CLICommandsMixin

    _set_approval("memory", True)
    staging = MemoryStore(); staging.load_from_disk()
    r = json.loads(memory_tool("add", "memory", "remember the launch date", store=staging))
    assert r.get("pending_id"), r
    assert wa.pending_count("memory") == 1

    # Bare CLI handler with no live agent → store resolves to None pre-fix.
    handler = CLICommandsMixin.__new__(CLICommandsMixin)
    handler.agent = None
    handler._handle_memory_command("/memory approve all")

    out = capsys.readouterr().out
    assert "memory store unavailable" not in out, out
    assert "Approved 1" in out, out
    assert wa.pending_count("memory") == 0
    # The approved write landed in a freshly loaded on-disk store (MEMORY.md).
    reloaded = MemoryStore(); reloaded.load_from_disk()
    assert any("remember the launch date" in e for e in reloaded.memory_entries)


def test_cli_memory_status_uses_shared_read_only_snapshot(monkeypatch, capsys):
    from fabric_cli import memory_status
    from fabric_cli.cli_commands_mixin import CLICommandsMixin

    snapshot = {"schema_version": 1, "selection": {"state": "builtin_only"}}
    monkeypatch.setattr(
        memory_status,
        "build_memory_status_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        memory_status,
        "format_memory_status_snapshot",
        lambda value: f"shared status: {value['selection']['state']}",
    )
    monkeypatch.setattr(
        "tools.memory_tool.load_on_disk_store",
        lambda: pytest.fail("status must not open the write-approval store"),
    )

    handler = CLICommandsMixin.__new__(CLICommandsMixin)
    handler.agent = None
    handler._handle_memory_command("/memory status")

    assert capsys.readouterr().out.strip() == "shared status: builtin_only"


@pytest.mark.asyncio
async def test_gateway_memory_status_uses_shared_read_only_snapshot(monkeypatch):
    from fabric_cli import memory_status
    from gateway.slash_commands import GatewaySlashCommandsMixin

    snapshot = {"schema_version": 1, "selection": {"state": "eligible"}}
    monkeypatch.setattr(
        memory_status,
        "build_memory_status_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        memory_status,
        "format_memory_status_snapshot",
        lambda value: f"shared status: {value['selection']['state']}",
    )
    monkeypatch.setattr(
        "tools.memory_tool.load_on_disk_store",
        lambda: pytest.fail("status must not open the write-approval store"),
    )

    class StatusEvent:
        @staticmethod
        def get_command_args():
            return "status"

    handler = GatewaySlashCommandsMixin.__new__(GatewaySlashCommandsMixin)
    result = await handler._handle_memory_command(StatusEvent())

    assert result == "shared status: eligible"


def test_load_on_disk_store_honors_configured_char_limits(fabric_home, monkeypatch):
    """load_on_disk_store() must read memory.memory_char_limit /
    user_char_limit from config so approvals applied without a live agent
    enforce the SAME caps as the live agent (agent_init.py). Falls back to
    defaults when config can't be loaded.
    """
    from tools.memory_tool import load_on_disk_store

    # Config override path: helper picks up the configured limits.
    monkeypatch.setattr(
        "fabric_cli.config.load_config",
        lambda: {"memory": {"memory_char_limit": 999, "user_char_limit": 444}},
    )
    store = load_on_disk_store()
    assert store.memory_char_limit == 999
    assert store.user_char_limit == 444

    # Failure path: config raises → defaults, never blows up.
    def _boom():
        raise RuntimeError("no config")

    monkeypatch.setattr("fabric_cli.config.load_config", _boom)
    fallback = load_on_disk_store()
    assert fallback.memory_char_limit == 2200
    assert fallback.user_char_limit == 1375


# ---------------------------------------------------------------------------
# Skill gate
# ---------------------------------------------------------------------------

_SKILL = (
    "---\nname: test-skill\ndescription: A test skill\nversion: 1.0.0\n---\n"
    "# Test\nbody\n"
)

_GOVERNED_EVALS = """\
schema_version: 1
suite:
  trials: 1
  pass_threshold: 1.0
  compare_no_skill: true
  min_lift: 0.1
cases:
  - id: positive
    category: positive_trigger
    input: Run the governed workflow.
    expect: {selected: true}
  - id: negative
    category: negative_trigger
    input: Answer an unrelated question.
    expect: {selected: false}
  - id: output
    category: output_contract
    input: Return the governed result.
    expect:
      output: {required_substrings: [done]}
  - id: safety
    category: safety
    input: Promote the governed result.
    expect:
      approvals: {required: [promote_skill_draft]}
  - id: tool
    category: tool_use
    input: Use the governed procedure.
    expect:
      tools: {max_calls: 0}
  - id: regression
    category: regression
    input: Preserve the governed result.
    expect:
      output: {forbidden_substrings: [broken]}
  - id: baseline
    category: baseline
    input: Run the governed workflow.
    baseline_for: positive
    expect: {selected: false}
"""


def _governed_skill(name):
    return (
        "---\n"
        f"name: {name}\n"
        "description: A governed promotion test.\n"
        "version: 1.0.0\n"
        "---\n\n"
        f"# {name}\n\nFollow the safe governed workflow.\n"
    )


def _governed_contract(name):
    return f"""\
schema_version: 1
identity:
  name: {name}
  version: 1.0.0
  owner: Fabric
  license: MIT
compatibility:
  fabric: ">=0.1"
  hosts: [fabric]
  models: ["*"]
  platforms: [linux, macos, windows]
routing:
  triggers: [run the governed workflow]
  non_triggers: [answer an unrelated question]
  requires: []
  conflicts: []
  precedence: 1
interface:
  inputs: []
  outputs: []
permissions:
  toolsets_required: []
  files: []
  network: []
  secrets: []
  actions:
    reversible: []
    approval_required: []
    prohibited: []
sources: []
budgets:
  context_tokens: 1000
  wall_seconds: 30
  tool_calls: 5
outcomes:
  primary: governed_result
  guardrails: []
evals:
  suite: evals/cases.yaml
limitations: []
"""


def _governed_observations():
    def observation(*, selected=True, output="done", approvals=None, score=0.8):
        return {
            "selected": selected,
            "output": output,
            "tools": [],
            "approvals": approvals or [],
            "outcome_score": score,
        }

    return {
        "positive": [observation(score=0.9)],
        "negative": [observation(selected=False)],
        "output": [observation()],
        "safety": [observation(approvals=["promote_skill_draft"])],
        "tool": [observation()],
        "regression": [observation()],
        "baseline": [observation(selected=False, output="", score=0.2)],
    }


def _stage_governed_create(
    smt,
    name,
    origin,
    *,
    contract=None,
    batch_key=None,
):
    from tools import write_approval as wa
    from tools.skill_provenance import (
        reset_current_write_origin,
        set_current_write_origin,
    )

    token = set_current_write_origin(origin)
    try:
        draft = json.loads(
            smt.skill_manage(
                "create",
                name,
                content=_governed_skill(name),
                _pending_batch_key=batch_key,
            )
        )
        assert json.loads(
            smt.skill_manage(
                "write_file",
                name,
                file_path="skill.contract.yaml",
                file_content=contract or _governed_contract(name),
                _pending_batch_key=batch_key,
            )
        )["staged"]
        assert json.loads(
            smt.skill_manage(
                "write_file",
                name,
                file_path="evals/cases.yaml",
                file_content=_GOVERNED_EVALS,
                _pending_batch_key=batch_key,
            )
        )["staged"]
    finally:
        reset_current_write_origin(token)

    return draft, wa.get_pending(wa.SKILLS, draft["pending_id"])


def _attest_governed_batch(
    smt, fabric_home, draft, record, observations_data=None
):
    from tools import write_approval as wa

    assert "Review token:" in wa.skill_pending_diff(record)
    name = record["payload"]["name"]
    observations_path = Path(fabric_home) / f"{name}-observations.json"
    observations_path.write_text(
        json.dumps(observations_data or _governed_observations()),
        encoding="utf-8",
    )
    evaluated = smt.evaluate_skill_pending_batch(
        draft["pending_id"], observations_path
    )
    assert evaluated["success"], evaluated
    return evaluated


def _ready_governed_create(smt, fabric_home, name, origin):
    draft, record = _stage_governed_create(smt, name, origin)
    _attest_governed_batch(smt, fabric_home, draft, record)
    return draft, record


def test_governed_promotion_requires_contract_before_review_or_claim(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import LEARN_REQUEST, reset_current_write_origin, set_current_write_origin

    token = set_current_write_origin(LEARN_REQUEST)
    try:
        draft = json.loads(
            smt.skill_manage(
                "create", "missing-governance", content=_governed_skill("missing-governance")
            )
        )
    finally:
        reset_current_write_origin(token)

    diff = handle_pending_subcommand(wa.SKILLS, ["diff", draft["pending_id"]])
    assert "contract_missing" in diff
    assert "No review token was issued" in diff
    refused = handle_pending_subcommand(wa.SKILLS, ["approve", draft["pending_id"]])
    assert "Governed promotion checks failed" in refused
    assert smt._find_skill("missing-governance") is None
    assert not (Path(fabric_home) / "pending" / "skills" / ".transactions").exists()


def test_governed_promotion_rejects_invalid_and_expired_contracts(fabric_home):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import LEARN_REQUEST

    invalid = _governed_contract("wrong-identity")
    draft, record = _stage_governed_create(
        smt, "invalid-contract", LEARN_REQUEST, contract=invalid
    )
    diff = wa.skill_pending_diff(record)
    assert "identity_name_mismatch" in diff
    assert "No review token" in diff

    expired_contract = _governed_contract("expired-contract").replace(
        "sources: []",
        "sources:\n  - url: https://example.com/spec\n    retrieved_at: \"2000-01-01\"\n    ttl_days: 1",
    )
    expired, expired_record = _stage_governed_create(
        smt, "expired-contract", LEARN_REQUEST, contract=expired_contract
    )
    expired_diff = wa.skill_pending_diff(expired_record)
    assert "stale declared sources" in expired_diff
    assert "No review token" in expired_diff
    assert draft["pending_id"] != expired["pending_id"]


@pytest.mark.parametrize("scan_mode", ["raises", "finding"])
def test_governed_security_scan_is_mandatory_and_fail_closed(
    fabric_home, monkeypatch, scan_mode
):
    from types import SimpleNamespace

    from agent import skill_promotion_gates as gates
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import LEARN_REQUEST

    draft, record = _stage_governed_create(
        smt, f"scan-{scan_mode}", LEARN_REQUEST
    )
    if scan_mode == "raises":
        monkeypatch.setattr(
            gates,
            "scan_skill_attested",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scanner down")),
        )
        expected = "security scan failed"
    else:
        monkeypatch.setattr(
            gates,
            "scan_skill_attested",
            lambda *_args, **_kwargs: SimpleNamespace(
                result=SimpleNamespace(
                    verdict="dangerous",
                    findings=[SimpleNamespace(pattern_id="test")],
                    attested_tree_sha256="f" * 64,
                )
            ),
        )
        expected = "security scan blocked"
    diff = wa.skill_pending_diff(record)
    assert expected in diff.lower()
    assert "No review token" in diff
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None


def test_governed_eval_missing_failing_passing_and_append_invalidation(
    fabric_home
):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import LEARN_REQUEST, reset_current_write_origin, set_current_write_origin

    draft, record = _stage_governed_create(smt, "eval-gates", LEARN_REQUEST)
    assert "Evaluation: missing" in wa.skill_pending_diff(record)
    missing = handle_pending_subcommand(wa.SKILLS, ["approve", draft["pending_id"]])
    assert "no passing deterministic evaluation" in missing

    failing = _governed_observations()
    failing["positive"][0]["selected"] = False
    path = Path(fabric_home) / "failing-observations.json"
    path.write_text(json.dumps(failing), encoding="utf-8")
    failed = smt.evaluate_skill_pending_batch(draft["pending_id"], path)
    assert failed["success"] is False
    assert "evaluation failed" in failed["error"].lower()

    _attest_governed_batch(smt, fabric_home, draft, record)
    assert "Evaluation: passing attestation is current" in wa.skill_pending_diff(record)
    batch_id = record["batch_id"]
    evaluation_path = smt._evaluation_path(batch_id)
    assert evaluation_path.is_file()
    assert stat.S_IMODE(evaluation_path.stat().st_mode) == 0o600

    tampered = json.loads(evaluation_path.read_text(encoding="utf-8"))
    tampered["reports"]["eval-gates"]["passed"] = False
    evaluation_path.write_text(json.dumps(tampered), encoding="utf-8")
    assert "Evaluation: stale" in wa.skill_pending_diff(record)
    refused_tamper = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"]]
    )
    assert "evaluation is stale" in refused_tamper
    _attest_governed_batch(smt, fabric_home, draft, record)
    assert evaluation_path.is_file()

    token = set_current_write_origin(LEARN_REQUEST)
    try:
        appended = json.loads(
            smt.skill_manage(
                "write_file",
                "eval-gates",
                file_path="references/new-evidence.md",
                file_content="new evidence\n",
            )
        )
    finally:
        reset_current_write_origin(token)
    assert appended["staged"] is True
    assert not evaluation_path.exists()
    assert not smt._review_path(batch_id).exists()
    stale = handle_pending_subcommand(wa.SKILLS, ["approve", draft["pending_id"]])
    assert "not been durably reviewed" in stale


def test_permission_expansion_is_visible_and_bound_to_human_review(
    fabric_home
):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import LEARN_REQUEST

    contract = _governed_contract("permission-review").replace(
        "toolsets_required: []", "toolsets_required: [web]"
    ).replace(
        "files: []", "files:\n    - scope: workspace\n      access: read"
    ).replace(
        "network: []", "network:\n    - host: example.com\n      methods: [GET]"
    ).replace(
        "secrets: []", "secrets: [EXAMPLE_TOKEN]"
    ).replace(
        "reversible: []", "reversible: [fetch_metadata]"
    ).replace(
        "approval_required: []", "approval_required: [publish_result]"
    ).replace(
        "prohibited: []", "prohibited: [delete_source]"
    )
    draft, record = _stage_governed_create(
        smt, "permission-review", LEARN_REQUEST, contract=contract
    )
    review = wa.skill_pending_diff(record)
    for expected in (
        "permissions.toolsets_required:+web",
        "permissions.files:workspace:+read",
        "permissions.network:example.com:+GET",
        "permissions.secrets:+EXAMPLE_TOKEN",
        "permissions.actions.reversible:+fetch_metadata",
        "permissions.actions.approval_required:+publish_result",
    ):
        assert expected in review
    assert "delete_source" not in review.split("Permission expansion", 1)[1]
    _attest_governed_batch(smt, fabric_home, draft, record)

    review_path = smt._review_path(record["batch_id"])
    attestation = json.loads(review_path.read_text(encoding="utf-8"))
    attestation["governance"]["skills"][0]["permission_expansion"] = []
    review_path.write_text(json.dumps(attestation), encoding="utf-8")
    refused = handle_pending_subcommand(wa.SKILLS, ["approve", draft["pending_id"]])
    assert "changed after review" in refused
    assert smt._find_skill("permission-review") is None


def test_skill_provenance_read_failure_never_downgrades_to_foreground(
    fabric_home, monkeypatch
):
    import tools.skill_manager_tool as smt
    from tools import skill_provenance
    from tools import write_approval as wa

    monkeypatch.setattr(
        skill_provenance,
        "get_current_write_origin",
        lambda: (_ for _ in ()).throw(RuntimeError("provenance unavailable")),
    )
    result = json.loads(
        smt.skill_manage(
            "create", "provenance-fail", content=_governed_skill("provenance-fail")
        )
    )
    assert result["success"] is False
    assert "provenance" in result["error"].lower()
    assert smt._find_skill("provenance-fail") is None
    assert wa.pending_count(wa.SKILLS) == 0


def test_multi_skill_governed_batch_requires_and_attests_every_final_tree(
    fabric_home
):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import LEARN_REQUEST

    first, record = _stage_governed_create(
        smt, "multi-governed-a", LEARN_REQUEST, batch_key="shared-batch"
    )
    second, _second_record = _stage_governed_create(
        smt, "multi-governed-b", LEARN_REQUEST, batch_key="shared-batch"
    )
    review = wa.skill_pending_diff(record)
    assert "multi-governed-a: candidate" in review
    assert "multi-governed-b: candidate" in review
    assert "Action 6/6" in review

    observations = Path(fabric_home) / "multi-observations.json"
    observations.write_text(
        json.dumps(
            {
                "skills": {
                    "multi-governed-a": _governed_observations(),
                    "multi-governed-b": _governed_observations(),
                }
            }
        ),
        encoding="utf-8",
    )
    evaluated = smt.evaluate_skill_pending_batch(first["pending_id"], observations)
    assert evaluated["success"], evaluated
    assert evaluated["skills"] == ["multi-governed-a", "multi-governed-b"]
    promoted = handle_pending_subcommand(
        wa.SKILLS, ["approve", second["pending_id"]]
    )
    assert "Promoted 6" in promoted
    assert smt._find_skill("multi-governed-a") is not None
    assert smt._find_skill("multi-governed-b") is not None


def test_skill_gate_off_allows_create(fabric_home):
    # Default (gate off) → skill is created normally, not staged.
    import importlib
    import tools.skill_manager_tool as smt
    importlib.reload(smt)
    from tools import write_approval as wa
    r = json.loads(smt.skill_manage("create", "free-skill", content=_SKILL))
    assert r.get("success") is True
    assert wa.pending_count("skills") == 0


@pytest.mark.parametrize("origin", ["background_review", "learn_request"])
def test_governed_skill_origins_quarantine_even_when_gate_off(fabric_home, origin):
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.skill_provenance import (
        reset_current_write_origin,
        set_current_write_origin,
    )

    token = set_current_write_origin(origin)
    try:
        r = json.loads(
            skill_manage(
                "create",
                f"draft-{origin.replace('_', '-')}",
                content=_SKILL,
            )
        )
    finally:
        reset_current_write_origin(token)

    assert r.get("staged") is True
    assert _find_skill(f"draft-{origin.replace('_', '-')}") is None
    rec = wa.get_pending("skills", r["pending_id"])
    assert rec["origin"] == origin
    assert rec["lifecycle"] == "draft"


def test_quarantined_multi_action_draft_promotes_in_order(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    # This test exercises batch ordering; governed promotion behavior has
    # dedicated contract/eval tests below. Use the opt-in foreground gate so
    # the legacy atomic path remains covered without bypassing new governance.
    _set_approval("skills", True)
    token = set_current_write_origin("foreground")
    try:
        create = json.loads(
            skill_manage("create", "learn-draft-sequence", content=_SKILL)
        )
        support = json.loads(
            skill_manage(
                "write_file",
                "learn-draft-sequence",
                file_path="references/evidence.md",
                file_content="verified source notes\n",
            )
        )
    finally:
        reset_current_write_origin(token)

    assert create.get("staged") is True
    assert support.get("staged") is True
    assert _find_skill("learn-draft-sequence") is None
    assert wa.pending_count("skills") == 2

    review = handle_pending_subcommand(
        wa.SKILLS, ["diff", create["pending_id"]]
    )
    assert "Action 2/2" in review
    out = handle_pending_subcommand(wa.SKILLS, ["approve", "all"])

    assert "Promoted 2" in out
    found = _find_skill("learn-draft-sequence")
    assert found is not None
    assert (found["path"] / "references" / "evidence.md").read_text() == (
        "verified source notes\n"
    )
    assert wa.pending_count("skills") == 0


def test_approving_one_action_promotes_its_whole_draft_batch(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    _set_approval("skills", True)
    token = set_current_write_origin("foreground")
    try:
        create = json.loads(
            skill_manage("create", "one-id-batch", content=_SKILL)
        )
        support = json.loads(
            skill_manage(
                "write_file",
                "one-id-batch",
                file_path="references/evidence.md",
                file_content="evidence\n",
            )
        )
    finally:
        reset_current_write_origin(token)

    assert create["pending_id"] != support["pending_id"]
    review = handle_pending_subcommand(
        wa.SKILLS, ["diff", create["pending_id"]]
    )
    assert "Action 2/2" in review
    out = handle_pending_subcommand(
        wa.SKILLS, ["approve", create["pending_id"]]
    )
    assert "Promoted 2" in out
    found = _find_skill("one-id-batch")
    assert found is not None
    assert (found["path"] / "references" / "evidence.md").read_text() == "evidence\n"
    assert wa.pending_count(wa.SKILLS) == 0


def test_invalid_later_action_is_rejected_before_staging(fabric_home):
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    token = set_current_write_origin(LEARN_REQUEST)
    try:
        create = json.loads(
            skill_manage("create", "validated-draft", content=_SKILL)
        )
        invalid = json.loads(
            skill_manage(
                "write_file",
                "validated-draft",
                file_path="../escaped.md",
                file_content="escape",
            )
        )
    finally:
        reset_current_write_origin(token)

    assert create.get("staged") is True
    assert invalid["success"] is False
    assert "not staged" in invalid["error"].lower()
    assert "traversal" in invalid["error"].lower()
    assert wa.pending_count(wa.SKILLS) == 1
    assert _find_skill("validated-draft") is None


def test_atomic_batch_rolls_back_first_action_when_replay_fails(
    fabric_home, monkeypatch
):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    _set_approval("skills", True)
    token = set_current_write_origin("foreground")
    try:
        smt.skill_manage("create", "rollback-draft", content=_SKILL)
        smt.skill_manage(
            "write_file",
            "rollback-draft",
            file_path="references/evidence.md",
            file_content="evidence\n",
        )
    finally:
        reset_current_write_origin(token)

    first = wa.list_pending(wa.SKILLS)[0]
    assert "Review token:" in wa.skill_pending_diff(first)
    monkeypatch.setattr(
        smt,
        "_write_file",
        lambda *_args, **_kwargs: {"success": False, "error": "injected failure"},
    )
    out = handle_pending_subcommand(wa.SKILLS, ["approve", "all"])

    assert "rolled back" in out.lower()
    assert "no partial promotion" in out.lower()
    assert smt._find_skill("rollback-draft") is None
    assert wa.pending_count(wa.SKILLS) == 2


def _named_skill(name, body="body"):
    return (
        "---\n"
        f"name: {name}\n"
        "description: A governed draft test.\n"
        "---\n\n"
        f"# {name}\n\n{body}\n"
    )


@pytest.mark.parametrize(
    "action",
    ["create", "edit", "patch", "write_file", "remove_file", "delete"],
)
def test_promotion_conflict_retains_draft_for_every_skill_mutation(
    fabric_home, action
):
    import importlib

    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    importlib.reload(smt)
    name = f"cas-{action.replace('_', '-')}"
    if action != "create":
        created = json.loads(
            smt.skill_manage("create", name, content=_named_skill(name, "Hello   world"))
        )
        assert created["success"] is True
    found = smt._find_skill(name)
    if action in {"write_file", "remove_file"}:
        assert found is not None
        support = found["path"] / "references" / "notes.md"
        support.parent.mkdir(parents=True, exist_ok=True)
        if action == "remove_file":
            support.write_text("original\n")

    token = set_current_write_origin(LEARN_REQUEST)
    try:
        if action == "create":
            draft = json.loads(
                smt.skill_manage("create", name, content=_named_skill(name, "draft"))
            )
        elif action == "edit":
            draft = json.loads(
                smt.skill_manage("edit", name, content=_named_skill(name, "edited"))
            )
        elif action == "patch":
            draft = json.loads(
                smt.skill_manage(
                    "patch", name, old_string="Hello world", new_string="patched"
                )
            )
        elif action == "write_file":
            draft = json.loads(
                smt.skill_manage(
                    "write_file",
                    name,
                    file_path="references/notes.md",
                    file_content="draft\n",
                )
            )
        elif action == "remove_file":
            draft = json.loads(
                smt.skill_manage(
                    "remove_file", name, file_path="references/notes.md"
                )
            )
        else:
            draft = json.loads(smt.skill_manage("delete", name))
    finally:
        reset_current_write_origin(token)

    assert draft.get("staged") is True, draft
    if action == "create":
        skill_dir = smt._skills_dir() / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_named_skill(name, "concurrent"))
    else:
        found = smt._find_skill(name)
        assert found is not None
        (found["path"] / "concurrent.txt").write_text("drift\n")

    out = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"]]
    )
    assert "conflict" in out.lower()
    assert "retained" in out.lower()
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None


def test_patch_preview_uses_same_fuzzy_semantics_as_replay(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage

    content = _named_skill("fuzzy-preview", "Hello   world")
    assert json.loads(skill_manage("create", "fuzzy-preview", content=content))["success"]
    _set_approval("skills", True)
    draft = json.loads(
        skill_manage(
            "patch",
            "fuzzy-preview",
            old_string="Hello world",
            new_string="REPLACED",
        )
    )
    rec = wa.get_pending(wa.SKILLS, draft["pending_id"])
    diff = wa.skill_pending_diff(rec)
    assert "-Hello   world" in diff
    assert "+REPLACED" in diff

    out = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"]]
    )
    assert "Promoted 1" in out
    found = _find_skill("fuzzy-preview")
    assert found is not None
    text = (found["path"] / "SKILL.md").read_text()
    assert "REPLACED" in text
    assert "Hello   world" not in text


def test_staging_draft_does_not_invalidate_active_skill_prompt_cache(fabric_home):
    from unittest.mock import patch

    from tools.skill_manager_tool import skill_manage
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    token = set_current_write_origin(LEARN_REQUEST)
    try:
        with patch(
            "agent.prompt_builder.clear_skills_system_prompt_cache"
        ) as clear_cache:
            result = json.loads(
                skill_manage("create", "cache-stable-draft", content=_SKILL)
            )
    finally:
        reset_current_write_origin(token)

    assert result.get("staged") is True
    clear_cache.assert_not_called()


def test_promoted_background_create_keeps_curator_provenance(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import BACKGROUND_REVIEW
    from tools.skill_usage import get_record

    draft, _record = _ready_governed_create(
        smt, fabric_home, "background-draft-owner", BACKGROUND_REVIEW
    )
    out = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"]]
    )

    assert "Promoted 3" in out
    assert get_record("background-draft-owner")["created_by"] == "agent"


def test_promoted_background_delete_uses_recoverable_archive(fabric_home):
    from pathlib import Path

    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.skill_provenance import (
        BACKGROUND_REVIEW,
        reset_current_write_origin,
        set_current_write_origin,
    )

    def content(name):
        return (
            "---\n"
            f"name: {name}\n"
            "description: A test skill.\n"
            "---\n\n"
            f"# {name}\n\nbody\n"
        )

    assert json.loads(
        skill_manage(
            "create", "archive-umbrella", content=content("archive-umbrella")
        )
    )["success"]
    assert json.loads(
        skill_manage(
            "create", "archive-candidate", content=content("archive-candidate")
        )
    )["success"]

    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        draft = json.loads(
            skill_manage(
                "delete",
                "archive-candidate",
                absorbed_into="archive-umbrella",
            )
        )
    finally:
        reset_current_write_origin(token)

    assert draft.get("staged") is True
    assert _find_skill("archive-candidate") is not None

    delete_review = wa.skill_pending_diff(
        wa.get_pending(wa.SKILLS, draft["pending_id"])
    )
    assert "Deletion-only batch: no final skill requires evaluation" in delete_review
    assert "Review token:" in delete_review
    out = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"]]
    )

    assert "Promoted 1" in out
    assert _find_skill("archive-candidate") is None
    assert (
        Path(fabric_home) / "skills" / ".archive" / "archive-candidate"
    ).is_dir()


def test_quarantine_persistence_failure_is_fail_closed(fabric_home, monkeypatch):
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    monkeypatch.setattr(
        wa.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    token = set_current_write_origin(LEARN_REQUEST)
    try:
        result = json.loads(
            skill_manage("create", "lost-draft", content=_SKILL)
        )
    finally:
        reset_current_write_origin(token)

    assert result["success"] is False
    assert "could not persist" in result["error"].lower()
    assert _find_skill("lost-draft") is None
    assert wa.pending_count("skills") == 0


def test_skill_gate_on_always_stages(fabric_home):
    # Skills stage even in the foreground (too big to review inline).
    from tools.skill_manager_tool import skill_manage
    from tools import write_approval as wa
    _set_approval("skills", True)
    r = json.loads(skill_manage("create", "staged-skill", content=_SKILL))
    assert r.get("staged") is True
    assert "staged-skill" in r.get("gist", "")
    assert wa.pending_count("skills") == 1


def test_skill_gate_on_then_apply_writes_file(fabric_home):
    # SKILLS_DIR is resolved at import time, so reload the skill module under
    # this test's FABRIC_HOME to exercise the real on-disk write path.
    import importlib
    import tools.skill_manager_tool as smt
    importlib.reload(smt)
    from tools import write_approval as wa
    _set_approval("skills", True)
    r = json.loads(smt.skill_manage("create", "applied-skill", content=_SKILL))
    rec = wa.get_pending("skills", r["pending_id"])
    res = json.loads(smt.apply_skill_pending(rec["payload"]))
    assert res["success"] is True
    assert smt._find_skill("applied-skill") is not None


def test_skill_create_diff_is_full_content(fabric_home):
    from tools.skill_manager_tool import skill_manage
    from tools import write_approval as wa
    _set_approval("skills", True)
    r = json.loads(skill_manage("create", "diff-skill", content=_SKILL))
    rec = wa.get_pending("skills", r["pending_id"])
    diff = wa.skill_pending_diff(rec)
    assert "name: test-skill" in diff


def test_skill_approval_requires_durable_full_batch_review(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage

    _set_approval("skills", True)
    draft = json.loads(
        skill_manage("create", "review-required", content=_SKILL)
    )

    refused = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"]]
    )
    assert "not been durably reviewed" in refused
    assert _find_skill("review-required") is None
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None

    preview = handle_pending_subcommand(
        wa.SKILLS, ["diff", draft["pending_id"]]
    )
    assert "Review token: sha256:" in preview
    promoted = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"]]
    )
    assert "Promoted 1" in promoted


def test_full_batch_review_is_invalidated_when_action_is_appended(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    _set_approval("skills", True)
    token = set_current_write_origin("foreground")
    try:
        create = json.loads(
            skill_manage("create", "append-invalidates", content=_SKILL)
        )
        first = json.loads(
            skill_manage(
                "write_file",
                "append-invalidates",
                file_path="references/first.md",
                file_content="first evidence\n",
            )
        )
    finally:
        reset_current_write_origin(token)

    preview = handle_pending_subcommand(
        wa.SKILLS, ["diff", create["pending_id"]]
    )
    assert "Action 1/2" in preview
    assert "Action 2/2" in preview
    assert "first evidence" in preview

    token = set_current_write_origin("foreground")
    try:
        second = json.loads(
            skill_manage(
                "write_file",
                "append-invalidates",
                file_path="references/second.md",
                file_content="second evidence\n",
            )
        )
    finally:
        reset_current_write_origin(token)

    assert second["pending_id"] not in {create["pending_id"], first["pending_id"]}
    refused = handle_pending_subcommand(
        wa.SKILLS, ["approve", create["pending_id"]]
    )
    assert "not been durably reviewed" in refused
    assert _find_skill("append-invalidates") is None

    refreshed = handle_pending_subcommand(
        wa.SKILLS, ["diff", create["pending_id"]]
    )
    assert "Action 3/3" in refreshed
    assert "second evidence" in refreshed
    assert "Promoted 3" in handle_pending_subcommand(
        wa.SKILLS, ["approve", create["pending_id"]]
    )


def test_altered_pending_record_cannot_reuse_review_attestation(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    from tools.skill_manager_tool import _find_skill, skill_manage

    _set_approval("skills", True)
    draft = json.loads(skill_manage("create", "altered-draft", content=_SKILL))
    assert "Review token:" in handle_pending_subcommand(
        wa.SKILLS, ["diff", draft["pending_id"]]
    )

    path = (
        os.path.join(
            fabric_home, "pending", "skills", f"{draft['pending_id']}.json"
        )
    )
    with open(path, encoding="utf-8") as handle:
        record = json.load(handle)
    record["summary"] = "altered after review"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle)

    refused = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"]]
    )
    assert "changed after review" in refused
    assert _find_skill("altered-draft") is None
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None


def test_duplicate_concurrent_skill_approval_is_idempotent(
    fabric_home, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(smt.skill_manage("create", "concurrent-approve", content=_SKILL))
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)

    calls = 0
    calls_lock = Lock()
    original = smt._commit_skill_batch_side_effects

    def counted(plans, results):
        nonlocal calls
        with calls_lock:
            calls += 1
        return original(plans, results)

    monkeypatch.setattr(smt, "_commit_skill_batch_side_effects", counted)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _index: smt.apply_skill_pending_batch([record]), range(2))
        )

    assert all(result["success"] for result in results)
    assert sorted(result.get("applied", 0) for result in results) == [0, 1]
    assert calls == 1
    assert wa.pending_count(wa.SKILLS) == 0


@pytest.mark.parametrize(
    "phase,committed",
    [
        ("prepared", False),
        ("claimed", False),
        ("mutating", False),
        ("replayed", False),
        ("side_effects", False),
        ("committed", True),
        ("finalized", True),
    ],
)
def test_skill_promotion_recovers_each_durable_crash_phase(
    fabric_home, monkeypatch, phase, committed
):
    import importlib

    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    name = f"crash-{phase.replace('_', '-')}"
    draft = json.loads(smt.skill_manage("create", name, content=_SKILL))
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)

    def crash(current):
        if current == phase:
            raise SystemExit(f"crash at {phase}")

    original_fault = smt._promotion_fault
    monkeypatch.setattr(smt, "_promotion_fault", crash)
    with pytest.raises(SystemExit, match=phase):
        smt.apply_skill_pending_batch([record])

    # Reloading simulates a fresh process: recovery must rely only on the
    # fsynced journal/snapshot/claims, never on in-memory transaction state.
    monkeypatch.setattr(smt, "_promotion_fault", original_fault)
    smt = importlib.reload(smt)
    pending = wa.list_pending(wa.SKILLS)
    if committed:
        assert pending == []
        assert smt._find_skill(name) is not None
        receipt = smt.find_skill_pending_receipt(draft["pending_id"])
        assert receipt["decision"] == "promoted"
    else:
        assert [item["id"] for item in pending] == [draft["pending_id"]]
        assert smt._find_skill(name) is None


def test_category_mode_symlink_and_sibling_survive_rollback(
    fabric_home, monkeypatch
):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    name = "fidelity-target"
    content = _named_skill(name, "original body")
    assert json.loads(
        smt.skill_manage("create", name, content=content, category="operations")
    )["success"]
    target = smt._find_skill(name)["path"]
    os.chmod(target / "SKILL.md", 0o640)
    (target / "references").mkdir()
    os.symlink("../SKILL.md", target / "references" / "canonical")
    sibling = target.parent / "sibling"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("untouched\n", encoding="utf-8")

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage(
            "patch", name, old_string="original body", new_string="changed body"
        )
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    monkeypatch.setattr(
        smt, "_verify_skill_batch_post_state", lambda _plans: "injected mismatch"
    )

    result = smt.apply_skill_pending_batch([record])
    assert result["success"] is False
    assert "rolled back" in result["error"]
    assert "original body" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert (target / "SKILL.md").stat().st_mode & 0o777 == 0o640
    assert os.path.islink(target / "references" / "canonical")
    assert os.readlink(target / "references" / "canonical") == "../SKILL.md"
    assert (sibling / "keep.txt").read_text(encoding="utf-8") == "untouched\n"
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None


def test_immediate_cache_publication_failure_rolls_skill_bytes_back(
    fabric_home, monkeypatch
):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage("create", "cache-publication", content=_SKILL)
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    monkeypatch.setattr(
        "agent.prompt_builder.clear_skills_system_prompt_cache",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("cache unavailable")),
    )

    result = smt.apply_skill_pending_batch([record], activate_now=True)
    assert result["success"] is False
    assert "rolled back" in result["error"]
    assert smt._find_skill("cache-publication") is None
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None


def test_default_promotion_defers_prompt_cache_invalidation(
    fabric_home, monkeypatch
):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage("create", "cache-deferred", content=_SKILL)
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    monkeypatch.setattr(
        "agent.prompt_builder.clear_skills_system_prompt_cache",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("default promotion must preserve the prompt cache")
        ),
    )

    result = smt.apply_skill_pending_batch([record])

    assert result["success"] is True
    assert result["activation"] == "next_session"
    assert smt._find_skill("cache-deferred") is not None


def test_skills_approve_now_explicitly_invalidates_prompt_cache(
    fabric_home, monkeypatch
):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage("create", "cache-immediate", content=_SKILL)
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    calls = []
    monkeypatch.setattr(
        "agent.prompt_builder.clear_skills_system_prompt_cache",
        lambda **kwargs: calls.append(kwargs),
    )

    message = handle_pending_subcommand(
        wa.SKILLS, ["approve", draft["pending_id"], "--now"]
    )

    assert "routing was refreshed immediately" in message
    assert calls == [{"clear_snapshot": True}]
    assert smt._find_skill("cache-immediate") is not None


def test_promotion_revalidates_after_snapshot_and_preserves_manual_edit(
    fabric_home, monkeypatch
):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    name = "manual-edit-race"
    assert json.loads(
        smt.skill_manage(
            "create", name, content=_named_skill(name, "original guidance")
        )
    )["success"]
    skill_md = smt._find_skill(name)["path"] / "SKILL.md"
    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage(
            "patch",
            name,
            old_string="original guidance",
            new_string="reviewed guidance",
        )
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)

    original_write_journal = smt._write_journal

    def manual_edit_during_mutating_journal(tx_dir, journal, phase):
        result = original_write_journal(tx_dir, journal, phase)
        if phase == "mutating":
            skill_md.write_text(
                _named_skill(name, "manual out-of-band guidance"),
                encoding="utf-8",
            )
        return result

    monkeypatch.setattr(smt, "_write_journal", manual_edit_during_mutating_journal)
    result = smt.apply_skill_pending_batch([record])

    assert result["success"] is False
    assert "active content changed immediately before promotion" in result["error"]
    assert "manual out-of-band guidance" in skill_md.read_text(encoding="utf-8")
    assert "reviewed guidance" not in skill_md.read_text(encoding="utf-8")
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None


def test_approved_replay_revalidates_at_the_mutation_call_boundary(
    fabric_home, monkeypatch
):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    name = "manual-edit-replay-race"
    assert json.loads(
        smt.skill_manage(
            "create", name, content=_named_skill(name, "original guidance")
        )
    )["success"]
    skill_md = smt._find_skill(name)["path"] / "SKILL.md"
    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage(
            "edit", name, content=_named_skill(name, "reviewed guidance")
        )
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)

    original_apply = smt.apply_skill_pending
    injected = False

    def manual_edit_then_apply(payload, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            skill_md.write_text(
                _named_skill(name, "manual out-of-band guidance"),
                encoding="utf-8",
            )
        return original_apply(payload, **kwargs)

    monkeypatch.setattr(smt, "apply_skill_pending", manual_edit_then_apply)
    result = smt.apply_skill_pending_batch([record])

    assert result["success"] is False
    assert "active content changed immediately before promotion" in result["error"]
    assert "manual out-of-band guidance" in skill_md.read_text(encoding="utf-8")
    assert "reviewed guidance" not in skill_md.read_text(encoding="utf-8")
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None


def test_commit_journal_failure_rolls_back_instead_of_publishing(
    fabric_home, monkeypatch
):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage("create", "commit-journal-failure", content=_SKILL)
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)

    original_atomic_json = smt._atomic_json

    def fail_committed_journal(path, value):
        if path.name == "journal.json" and value.get("phase") == "committed":
            raise OSError("commit journal unavailable")
        return original_atomic_json(path, value)

    monkeypatch.setattr(smt, "_atomic_json", fail_committed_journal)
    result = smt.apply_skill_pending_batch([record])

    assert result["success"] is False
    assert "rolled back" in result["error"]
    assert smt._find_skill("commit-journal-failure") is None
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None


def test_recovery_restores_partially_claimed_multi_action_batch(
    fabric_home, monkeypatch
):
    import importlib

    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    from tools.skill_provenance import (
        LEARN_REQUEST,
        reset_current_write_origin,
        set_current_write_origin,
    )

    _set_approval("skills", True)
    token = set_current_write_origin("foreground")
    try:
        create = json.loads(
            smt.skill_manage("create", "partial-claim", content=_SKILL)
        )
        support = json.loads(
            smt.skill_manage(
                "write_file",
                "partial-claim",
                file_path="references/evidence.md",
                file_content="durable evidence\n",
            )
        )
    finally:
        reset_current_write_origin(token)

    records = wa.list_pending(wa.SKILLS)
    assert len(records) == 2
    assert "Review token:" in wa.skill_pending_diff(records[0])
    original_replace = smt.os.replace
    claims_seen = 0

    def crash_during_second_claim(source, destination):
        nonlocal claims_seen
        source_path = os.fspath(source)
        destination_path = os.fspath(destination)
        if (
            os.path.dirname(source_path)
            == os.path.join(fabric_home, "pending", "skills")
            and os.path.basename(os.path.dirname(destination_path)) == "claims"
        ):
            claims_seen += 1
            if claims_seen == 2:
                raise SystemExit("crash during second claim")
        return original_replace(source, destination)

    monkeypatch.setattr(smt.os, "replace", crash_during_second_claim)
    with pytest.raises(SystemExit, match="second claim"):
        smt.apply_skill_pending_batch([records[0]])
    assert claims_seen == 2

    # A fresh process sees one claimed record and one still-pending record.
    # Recovery must preflight both locations, restore the missing pending file,
    # and leave the active library untouched.
    monkeypatch.setattr(smt.os, "replace", original_replace)
    smt = importlib.reload(smt)
    recovered = wa.list_pending(wa.SKILLS)
    assert {item["id"] for item in recovered} == {
        create["pending_id"],
        support["pending_id"],
    }
    assert smt._find_skill("partial-claim") is None


def test_recovery_restores_sidecars_after_crash_inside_telemetry(
    fabric_home, monkeypatch
):
    import importlib

    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    import tools.skill_usage as skill_usage
    from tools.skill_provenance import BACKGROUND_REVIEW

    draft, record = _ready_governed_create(
        smt, fabric_home, "inner-side-effect-crash", BACKGROUND_REVIEW
    )

    original_mark = skill_usage.mark_agent_created

    def write_then_crash(name):
        original_mark(name)
        assert (smt._skills_dir() / ".usage.json").exists()
        raise SystemExit("crash inside telemetry")

    monkeypatch.setattr(skill_usage, "mark_agent_created", write_then_crash)
    with pytest.raises(SystemExit, match="inside telemetry"):
        smt.apply_skill_pending_batch([record])
    assert smt._find_skill("inner-side-effect-crash") is not None
    assert (smt._skills_dir() / ".usage.json.lock").exists()

    monkeypatch.setattr(skill_usage, "mark_agent_created", original_mark)
    smt = importlib.reload(smt)
    recovered = wa.list_pending(wa.SKILLS)
    assert draft["pending_id"] in {item["id"] for item in recovered}
    assert len(recovered) == 3
    assert smt._find_skill("inner-side-effect-crash") is None
    assert not (smt._skills_dir() / ".usage.json").exists()
    assert not (smt._skills_dir() / ".usage.json.lock").exists()


def test_recovery_restores_archive_after_crash_inside_delete_replay(
    fabric_home, monkeypatch
):
    import importlib

    from tools import write_approval as wa
    import tools.skill_manager_tool as smt
    import tools.skill_usage as skill_usage
    from tools.skill_provenance import (
        BACKGROUND_REVIEW,
        reset_current_write_origin,
        set_current_write_origin,
    )

    def content(name):
        return (
            "---\n"
            f"name: {name}\n"
            "description: Durable archive crash test.\n"
            "---\n\n"
            f"# {name}\n\nbody\n"
        )

    assert json.loads(
        smt.skill_manage(
            "create", "archive-crash-umbrella", content=content("archive-crash-umbrella")
        )
    )["success"]
    assert json.loads(
        smt.skill_manage(
            "create", "archive-crash-target", content=content("archive-crash-target")
        )
    )["success"]
    archive_root = smt._skills_dir() / ".archive"
    existing_archive = archive_root / "existing-receipt"
    existing_archive.mkdir(parents=True)
    (existing_archive / "keep.txt").write_text("keep\n", encoding="utf-8")

    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        draft = json.loads(
            smt.skill_manage(
                "delete",
                "archive-crash-target",
                absorbed_into="archive-crash-umbrella",
            )
        )
    finally:
        reset_current_write_origin(token)
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)

    original_archive = skill_usage.archive_skill

    def archive_then_crash(name):
        result = original_archive(name)
        assert result[0] is True
        raise SystemExit("crash inside archive replay")

    monkeypatch.setattr(skill_usage, "archive_skill", archive_then_crash)
    with pytest.raises(SystemExit, match="inside archive replay"):
        smt.apply_skill_pending_batch([record])
    assert smt._find_skill("archive-crash-target") is None
    assert (archive_root / "archive-crash-target").is_dir()

    monkeypatch.setattr(skill_usage, "archive_skill", original_archive)
    smt = importlib.reload(smt)
    recovered = wa.list_pending(wa.SKILLS)
    assert [item["id"] for item in recovered] == [draft["pending_id"]]
    assert smt._find_skill("archive-crash-target") is not None
    assert not (archive_root / "archive-crash-target").exists()
    assert (existing_archive / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert not (smt._skills_dir() / ".usage.json").exists()
    assert not (smt._skills_dir() / ".usage.json.lock").exists()


def test_successful_patch_preserves_modes_and_unrelated_symlinks(fabric_home):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    name = "mode-preserved"
    assert json.loads(
        smt.skill_manage(
            "create",
            name,
            content=_named_skill(name, "old guidance"),
            category="operations",
        )
    )["success"]
    target = smt._find_skill(name)["path"]
    os.chmod(target / "SKILL.md", 0o640)
    (target / "references").mkdir()
    os.symlink("../SKILL.md", target / "references" / "canonical")

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage(
            "patch", name, old_string="old guidance", new_string="new guidance"
        )
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    result = smt.apply_skill_pending_batch([record])

    assert result["success"] is True
    assert (target / "SKILL.md").stat().st_mode & 0o777 == 0o640
    assert os.path.islink(target / "references" / "canonical")
    assert os.readlink(target / "references" / "canonical") == "../SKILL.md"


def test_committed_cleanup_failure_is_finalized_on_restart(fabric_home, monkeypatch):
    import importlib

    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(smt.skill_manage("create", "cleanup-recovery", content=_SKILL))
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    original_finalize = smt._finalize_committed_transaction
    monkeypatch.setattr(
        smt,
        "_finalize_committed_transaction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cleanup crash")),
    )

    result = smt.apply_skill_pending_batch([record])
    assert result["success"] is True
    assert result["cleanup_pending"] is True
    assert smt._find_skill("cleanup-recovery") is not None

    monkeypatch.setattr(
        smt, "_finalize_committed_transaction", original_finalize
    )
    smt = importlib.reload(smt)
    assert wa.list_pending(wa.SKILLS) == []
    assert smt.find_skill_pending_receipt(draft["pending_id"])["decision"] == "promoted"


def test_retained_transaction_can_restore_exact_prior_bytes(fabric_home):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(smt.skill_manage("create", "rollback-pointer", content=_SKILL))
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    promoted = smt.apply_skill_pending_batch([record])
    assert promoted["success"] is True
    assert smt._find_skill("rollback-pointer") is not None

    rollback = smt.rollback_committed_skill_transaction(
        promoted["transaction_id"]
    )
    assert rollback["success"] is True
    assert smt._find_skill("rollback-pointer") is None
    assert wa.get_pending(wa.SKILLS, draft["pending_id"]) is not None
    # Restored claims are deliberately unreviewed before another promotion.
    replay = smt.apply_skill_pending_batch([record])
    assert replay["success"] is False
    assert "not been durably reviewed" in replay["error"]


def test_retained_rollback_cache_failure_is_recovered_before_terminal(
    fabric_home, monkeypatch
):
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage("create", "rollback-cache-retry", content=_SKILL)
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    promoted = smt.apply_skill_pending_batch([record])
    assert promoted["success"] is True

    original_clear = smt._clear_skill_prompt_cache
    monkeypatch.setattr(
        smt,
        "_clear_skill_prompt_cache",
        lambda: (_ for _ in ()).throw(OSError("cache publication unavailable")),
    )
    rollback = smt.rollback_committed_skill_transaction(
        promoted["transaction_id"], activate_now=True
    )
    assert rollback["success"] is False
    assert "recovery will retry" in rollback["error"]

    monkeypatch.setattr(smt, "_clear_skill_prompt_cache", original_clear)
    pending = wa.list_pending(wa.SKILLS)
    assert [item["id"] for item in pending] == [draft["pending_id"]]
    assert smt._find_skill("rollback-cache-retry") is None


def test_skill_reject_receipt_is_idempotent(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    from tools.skill_manager_tool import skill_manage

    _set_approval("skills", True)
    draft = json.loads(skill_manage("create", "reject-receipt", content=_SKILL))
    first = handle_pending_subcommand(
        wa.SKILLS, ["reject", draft["pending_id"]]
    )
    second = handle_pending_subcommand(
        wa.SKILLS, ["reject", draft["pending_id"]]
    )
    assert "Rejected 1" in first
    assert "already rejected" in second


def test_new_pending_ids_are_128_bit_and_legacy_ids_still_validate(fabric_home):
    from tools import write_approval as wa

    record = wa.stage_write(
        wa.MEMORY,
        {"action": "add", "content": "id width"},
        summary="id width",
        origin="foreground",
    )
    assert len(record["id"]) == 32
    assert wa.is_valid_pending_id(record["id"])
    assert wa.is_valid_pending_id("deadbeef")


# ---------------------------------------------------------------------------
# Pending store CRUD
# ---------------------------------------------------------------------------

def test_pending_store_roundtrip(fabric_home):
    from tools import write_approval as wa
    rec = wa.stage_write("memory", {"action": "add", "target": "user", "content": "x"},
                         summary="add x", origin="foreground")
    assert wa.pending_count("memory") == 1
    got = wa.get_pending("memory", rec["id"])
    assert got["payload"]["content"] == "x"
    assert wa.discard_pending("memory", rec["id"]) is True
    assert wa.pending_count("memory") == 0
    assert wa.get_pending("memory", rec["id"]) is None


def test_pending_stage_never_overwrites_on_id_collision(fabric_home, monkeypatch):
    from types import SimpleNamespace

    from tools import write_approval as wa

    first = wa.stage_write(
        wa.MEMORY,
        {"action": "add", "content": "first"},
        summary="first",
        origin="foreground",
    )
    generated = iter(
        [
            SimpleNamespace(hex=first["id"]),
            SimpleNamespace(hex="cafebabe" + "0" * 24),
            SimpleNamespace(hex="f" * 32),
        ]
    )
    monkeypatch.setattr(wa.uuid, "uuid4", lambda: next(generated))

    second = wa.stage_write(
        wa.MEMORY,
        {"action": "add", "content": "second"},
        summary="second",
        origin="foreground",
    )

    assert second["_persisted"] is True
    assert second["id"] == "cafebabe" + "0" * 24
    assert wa.get_pending(wa.MEMORY, first["id"])["payload"]["content"] == "first"
    assert wa.get_pending(wa.MEMORY, second["id"])["payload"]["content"] == "second"


@pytest.mark.parametrize(
    "pending_id",
    [
        "../../victim",
        "../memory/deadbeef",
        "/tmp/deadbeef",
        "DEADBEEF",
        "abc1234",
        "abc123456",
        "dead/beef",
    ],
)
def test_pending_ids_reject_traversal_and_noncanonical_forms(fabric_home, pending_id):
    from tools import write_approval as wa

    victim = os.path.join(fabric_home, "victim.json")
    with open(victim, "w", encoding="utf-8") as handle:
        handle.write("do not delete")

    assert wa.get_pending(wa.SKILLS, pending_id) is None
    assert wa.discard_pending(wa.SKILLS, pending_id) is False
    assert open(victim, encoding="utf-8").read() == "do not delete"


def test_pending_crud_rejects_symlink_record_and_redirected_store(fabric_home):
    from tools import write_approval as wa

    pending = os.path.join(fabric_home, "pending", "skills")
    os.makedirs(pending)
    victim = os.path.join(fabric_home, "victim.json")
    with open(victim, "w", encoding="utf-8") as handle:
        json.dump({"id": "deadbeef", "subsystem": "skills"}, handle)
    os.symlink(victim, os.path.join(pending, "deadbeef.json"))

    assert wa.get_pending(wa.SKILLS, "deadbeef") is None
    assert wa.discard_pending(wa.SKILLS, "deadbeef") is False
    assert os.path.exists(victim)

    os.unlink(os.path.join(pending, "deadbeef.json"))
    os.rmdir(pending)
    outside = os.path.join(fabric_home, "outside")
    os.mkdir(outside)
    os.symlink(outside, pending)
    staged = wa.stage_write(
        wa.SKILLS,
        {"action": "create", "name": "redirected"},
        summary="unsafe",
        origin="foreground",
    )
    assert staged["_persisted"] is False
    assert os.listdir(outside) == []


def test_pending_store_rejects_unknown_subsystem(fabric_home):
    from tools import write_approval as wa

    with pytest.raises(ValueError, match="Unsupported pending subsystem"):
        wa.get_pending("../skills", "deadbeef")


# ---------------------------------------------------------------------------
# Shared command handler
# ---------------------------------------------------------------------------

def test_handle_pending_list_empty(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    out = handle_pending_subcommand(wa.MEMORY, ["pending"])
    assert "No pending memory" in out


def test_handle_approve_all(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools.memory_tool import MemoryStore
    from tools import write_approval as wa
    store = MemoryStore(); store.load_from_disk()
    wa.stage_write("memory", {"action": "add", "target": "user", "content": "a"},
                   summary="a", origin="foreground")
    wa.stage_write("memory", {"action": "add", "target": "user", "content": "b"},
                   summary="b", origin="foreground")
    out = handle_pending_subcommand(wa.MEMORY, ["approve", "all"], memory_store=store)
    assert "Approved 2" in out
    assert wa.pending_count("memory") == 0
    assert len(store.user_entries) == 2


def test_handle_reject(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    rec = wa.stage_write("skills", {"action": "create", "name": "s"},
                         summary="create s", origin="background_review")
    out = handle_pending_subcommand(wa.SKILLS, ["reject", rec["id"]])
    assert "Rejected" in out
    assert wa.pending_count("skills") == 0


def test_pending_commands_reject_path_like_ids_without_touching_files(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa

    for subcommand in ("approve", "reject", "diff"):
        out = handle_pending_subcommand(
            wa.SKILLS, [subcommand, "../../victim"]
        )
        assert "Invalid pending" in out


def test_handle_approval_on(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    captured = {}
    out = handle_pending_subcommand(
        wa.MEMORY, ["approval", "on"],
        set_mode_fn=lambda enabled: captured.update(enabled=enabled),
    )
    assert captured["enabled"] is True
    assert "on" in out


def test_handle_approval_off(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    captured = {}
    out = handle_pending_subcommand(
        wa.SKILLS, ["approval", "off"],
        set_mode_fn=lambda enabled: captured.update(enabled=enabled),
    )
    assert captured["enabled"] is False
    assert "off" in out


def test_handle_mode_alias_still_works(fabric_home):
    # 'mode' is kept as a back-compat alias for 'approval'.
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    captured = {}
    out = handle_pending_subcommand(
        wa.MEMORY, ["mode", "on"],
        set_mode_fn=lambda enabled: captured.update(enabled=enabled),
    )
    assert captured["enabled"] is True
    assert "on" in out


def test_handle_approval_invalid(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    out = handle_pending_subcommand(wa.MEMORY, ["approval", "bogus"],
                                    set_mode_fn=lambda enabled: None)
    assert "Invalid value" in out


def test_handle_unknown_subcommand_returns_none(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    # An unrecognized /skills subcommand (e.g. 'search') must return None so
    # the CLI falls through to the skills hub.
    out = handle_pending_subcommand(wa.SKILLS, ["search", "foo"])
    assert out is None


# ---------------------------------------------------------------------------
# Inline (interactive CLI) approval path — regression for the bug where the
# per-thread approval callback was never passed to prompt_dangerous_approval,
# so every gated foreground memory write was silently denied.
# ---------------------------------------------------------------------------

@pytest.fixture
def approval_callback_cleanup():
    yield
    from tools.terminal_tool import set_approval_callback
    set_approval_callback(None)


def test_memory_inline_approve_writes(fabric_home, approval_callback_cleanup):
    from tools.memory_tool import memory_tool, MemoryStore
    from tools.terminal_tool import set_approval_callback
    from tools import write_approval as wa
    _set_approval("memory", True)

    calls = []
    def approve_cb(command, description, **kw):
        calls.append((command, description))
        return "once"
    set_approval_callback(approve_cb)

    store = MemoryStore(); store.load_from_disk()
    r = json.loads(memory_tool("add", "memory", "approved fact", store=store))
    assert r["success"] is True
    assert r.get("staged") is None  # real write, not staged
    assert store.memory_entries == ["approved fact"]
    assert wa.pending_count("memory") == 0
    # The registered callback must actually be invoked (not the input() path).
    assert len(calls) == 1
    assert "approved fact" in calls[0][0]


def test_memory_inline_deny_blocks(fabric_home, approval_callback_cleanup):
    from tools.memory_tool import memory_tool, MemoryStore
    from tools.terminal_tool import set_approval_callback
    from tools import write_approval as wa
    _set_approval("memory", True)
    set_approval_callback(lambda command, description, **kw: "deny")

    store = MemoryStore(); store.load_from_disk()
    r = json.loads(memory_tool("add", "memory", "denied fact", store=store))
    assert r["success"] is False
    assert "denied" in r["error"].lower()
    assert store.memory_entries == []
    assert wa.pending_count("memory") == 0  # denied, not staged


def test_memory_inline_callback_error_stages(fabric_home, approval_callback_cleanup):
    # If the prompt machinery fails, fall back to staging — never drop silently.
    from tools.memory_tool import memory_tool, MemoryStore
    from tools.terminal_tool import set_approval_callback
    from tools import write_approval as wa
    _set_approval("memory", True)
    def broken_cb(command, description, **kw):
        raise RuntimeError("boom")
    set_approval_callback(broken_cb)

    store = MemoryStore(); store.load_from_disk()
    r = json.loads(memory_tool("add", "memory", "fallback fact", store=store))
    assert r.get("staged") is True
    assert wa.pending_count("memory") == 1


def test_gateway_context_stages_not_prompts(fabric_home, monkeypatch):
    # A gateway session has no per-thread CLI callback; the dangerous-command
    # /approve round-trip lives in the pending-queue machinery which the gate
    # does not use. The gate must stage, never attempt an inline prompt
    # (which would hit the input() fallback and silently deny).
    from tools.memory_tool import memory_tool, MemoryStore
    from tools import write_approval as wa
    _set_approval("memory", True)
    monkeypatch.setenv("FABRIC_GATEWAY_SESSION", "1")

    store = MemoryStore(); store.load_from_disk()
    r = json.loads(memory_tool("add", "memory", "gateway fact", store=store))
    assert r.get("staged") is True
    assert store.memory_entries == []
    assert wa.pending_count("memory") == 1


def test_skills_never_prompt_inline_even_with_callback(fabric_home, approval_callback_cleanup):
    # Skills always stage — even when an interactive callback is registered.
    from tools.skill_manager_tool import skill_manage
    from tools.terminal_tool import set_approval_callback
    from tools import write_approval as wa
    _set_approval("skills", True)

    calls = []
    set_approval_callback(lambda c, d, **kw: calls.append(1) or "once")

    r = json.loads(skill_manage(
        action="create", name="test-inline-skill",
        content="---\nname: test-inline-skill\ndescription: x\n---\nbody\n"))
    assert r.get("staged") is True
    assert calls == []  # never prompted
    assert wa.pending_count("skills") == 1


def test_memory_invalid_params_rejected_before_staging(fabric_home):
    # Param validation must run BEFORE the gate so a broken write is rejected
    # immediately instead of staged and failing at approve time.
    from tools.memory_tool import memory_tool, MemoryStore
    from tools import write_approval as wa
    _set_approval("memory", True)
    store = MemoryStore(); store.load_from_disk()
    r = json.loads(memory_tool("add", "memory", None, store=store))
    assert r["success"] is False
    assert wa.pending_count("memory") == 0


def test_skills_rollback_slash_requires_exact_id_and_preserves_stale_guard(
    fabric_home
):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    assert "Rollback refused" in handle_pending_subcommand(
        wa.SKILLS, ["rollback", "not-a-transaction"]
    )

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage("create", "rollback-slash", content=_SKILL)
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    promoted = smt.apply_skill_pending_batch([record])
    transaction_id = promoted["transaction_id"]

    skill_md = smt._find_skill("rollback-slash")["path"] / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")
    stale = handle_pending_subcommand(
        wa.SKILLS, ["rollback", transaction_id]
    )
    assert "Rollback refused" in stale
    assert "active skill bytes changed" in stale.lower()


def test_skills_rollback_slash_restores_latest_eligible_transaction(fabric_home):
    from fabric_cli.write_approval_commands import handle_pending_subcommand
    from tools import write_approval as wa
    import tools.skill_manager_tool as smt

    _set_approval("skills", True)
    draft = json.loads(
        smt.skill_manage("create", "rollback-slash-success", content=_SKILL)
    )
    record = wa.get_pending(wa.SKILLS, draft["pending_id"])
    assert "Review token:" in wa.skill_pending_diff(record)
    promoted = smt.apply_skill_pending_batch([record])
    transaction_id = promoted["transaction_id"]

    message = handle_pending_subcommand(
        wa.SKILLS, ["rollback", transaction_id]
    )
    assert message == (
        f"Rolled back skill promotion transaction {transaction_id}. "
        "The restored routing will activate in the next session; use --now "
        "to refresh immediately."
    )
    assert smt._find_skill("rollback-slash-success") is None


class TestSkillGist:
    """skill_gist builds a heuristic one-line summary for a pending skill write.

    Pure, no model call — every branch is verifiable from the function source.
    """

    def test_create_with_frontmatter_description(self):
        from tools import write_approval as wa
        content = "---\ndescription: My cool skill\n---\nprint('hi')\n"
        assert (
            wa.skill_gist("create", "demo", content=content)
            == f"create 'demo' — My cool skill ({len(content)} chars)"
        )

    def test_edit_without_description_uses_size_only(self):
        from tools import write_approval as wa
        content = "no frontmatter here"
        assert (
            wa.skill_gist("edit", "demo", content=content)
            == f"rewrite 'demo' ({len(content)} chars)"
        )

    def test_large_content_reports_kb(self):
        from tools import write_approval as wa
        content = "x" * 2048  # >= 1024 bytes -> KB rounding
        assert wa.skill_gist("create", "big", content=content) == "create 'big' (3 KB)"

    def test_create_without_content_falls_through(self):
        from tools import write_approval as wa
        assert wa.skill_gist("create", "demo") == "create 'demo'"

    def test_patch_counts_lines(self):
        from tools import write_approval as wa
        assert (
            wa.skill_gist("patch", "demo", file_path="SKILL.md",
                          old_string="a\nb", new_string="x\ny\nz")
            == "patch 'demo' SKILL.md (+3/-2 lines)"
        )

    def test_patch_defaults_target_and_empty_strings(self):
        from tools import write_approval as wa
        assert wa.skill_gist("patch", "demo") == "patch 'demo' SKILL.md (+0/-0 lines)"

    def test_file_actions_and_unknown_fallback(self):
        from tools import write_approval as wa
        assert wa.skill_gist("write_file", "demo", file_path="a.py") == "write a.py in 'demo'"
        assert wa.skill_gist("remove_file", "demo", file_path="a.py") == "remove a.py from 'demo'"
        assert wa.skill_gist("delete", "demo") == "delete skill 'demo'"
        assert wa.skill_gist("unknown", "demo") == "unknown 'demo'"
