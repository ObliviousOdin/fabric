from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import agent.memory_governance as memory_governance

from agent.memory_governance import (
    EXPIRED_PLACEHOLDER,
    audit_memory,
    capture_expiry_decisions,
    format_audit_report,
    record_committed_write,
    record_committed_write_best_effort,
    record_relevance_label,
    reset_governance,
    revalidate_record,
)


def _metadata(**overrides):
    base = {
        "write_origin": "assistant_tool",
        "execution_context": "foreground",
        "platform": "cli",
        "session_id": "raw-session-secret",
        "parent_session_id": "raw-parent-secret",
        "task_id": "raw-task-secret",
        "tool_call_id": "raw-tool-call-secret",
    }
    base.update(overrides)
    return base


def _record_add(home: Path, entry: str, *, target="memory", now=None, **metadata):
    assert record_committed_write(
        target=target,
        before_entries=[],
        after_entries=[entry],
        tool_args={"action": "add", "target": target, "content": entry},
        tool_result={"success": True, "done": True, "message": "Entry added."},
        metadata=_metadata(**metadata),
        home=home,
        now=now,
    )
    state = json.loads(
        (home / "memories" / ".governance" / "memory-governance.json").read_text()
    )
    return state["records"][-1]


def _write_entries(home: Path, target: str, entries: list[str]) -> None:
    memory_dir = home / "memories"
    memory_dir.mkdir(parents=True, exist_ok=True)
    filename = "USER.md" if target == "user" else "MEMORY.md"
    (memory_dir / filename).write_text("\n§\n".join(entries), encoding="utf-8")


def _state(home: Path):
    return json.loads(
        (home / "memories" / ".governance" / "memory-governance.json").read_text()
    )


def test_sidecar_is_closed_private_and_0600(tmp_path):
    entry = "User prefers high contrast interfaces"
    record = _record_add(tmp_path, entry)

    governance = tmp_path / "memories" / ".governance"
    state_path = governance / "memory-governance.json"
    key_path = governance / "memory-governance.key"
    lock_path = governance / ".lock"
    raw = state_path.read_text(encoding="utf-8")

    assert entry not in raw
    for secret in (
        "raw-session-secret",
        "raw-parent-secret",
        "raw-task-secret",
        "raw-tool-call-secret",
    ):
        assert secret not in raw
    assert record["source"]["session_ref"].startswith("hmac-sha256:")
    assert record["source"]["task_ref"].startswith("hmac-sha256:")
    assert record["scope"] == "profile"
    assert record["confidence"] == "unspecified"
    if os.name != "nt":
        assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(governance.stat().st_mode) == 0o700


def test_unknown_source_values_cannot_smuggle_arbitrary_text(tmp_path):
    record = _record_add(
        tmp_path,
        "fact",
        write_origin="API_TOKEN_123456789",
        execution_context="secret-context",
        platform="secret-platform",
        confidence="secret-confidence",
    )
    encoded = json.dumps(record)
    assert "API_TOKEN" not in encoded
    assert "secret-" not in encoded
    assert record["source"] == {
        "origin": "other",
        "context": "other",
        "platform": "other",
        "session_ref": record["source"]["session_ref"],
        "parent_session_ref": record["source"]["parent_session_ref"],
        "task_ref": record["source"]["task_ref"],
        "tool_call_ref": record["source"]["tool_call_ref"],
    }


def test_add_replace_remove_and_batch_lifecycle(tmp_path):
    original = "timezone: UTC"
    replacement = "timezone: America/Chicago"
    first = _record_add(tmp_path, original)

    assert record_committed_write(
        target="memory",
        before_entries=[original],
        after_entries=[replacement],
        tool_args={
            "action": "replace",
            "target": "memory",
            "old_text": "timezone:",
            "content": replacement,
        },
        tool_result={"success": True, "done": True},
        metadata=_metadata(),
        home=tmp_path,
    )
    records = _state(tmp_path)["records"]
    old = next(item for item in records if item["id"] == first["id"])
    new = next(item for item in records if item["status"] == "active")
    assert old["status"] == "superseded"
    assert old["superseded_by"] == new["id"]
    assert old["terminal_source"]["task_ref"].startswith("hmac-sha256:")
    assert new["supersedes_content_id"] == old["content_id"]

    assert record_committed_write(
        target="memory",
        before_entries=[replacement],
        after_entries=["editor: vim"],
        tool_args={
            "target": "memory",
            "operations": [
                {"action": "remove", "old_text": "timezone:"},
                {"action": "add", "content": "editor: vim"},
            ],
        },
        tool_result={"success": True, "done": True},
        metadata=_metadata(write_origin="background_review", execution_context="background_review"),
        home=tmp_path,
    )
    records = _state(tmp_path)["records"]
    replacement_record = next(item for item in records if item["id"] == new["id"])
    added_record = next(
        item for item in records if item["status"] == "active" and item["id"] != new["id"]
    )
    assert replacement_record["status"] == "removed"
    assert replacement_record["removed_at"] is not None
    assert added_record["source"]["origin"] == "background_review"


def test_batch_collapses_replacement_chains_and_tracks_readded_identity(tmp_path):
    original = "fact-a"
    first = _record_add(tmp_path, original)
    final_entries = ["fact-c", original]
    assert record_committed_write(
        target="memory",
        before_entries=[original],
        after_entries=final_entries,
        tool_args={
            "target": "memory",
            "operations": [
                {"action": "replace", "old_text": "fact-a", "content": "fact-b"},
                {"action": "replace", "old_text": "fact-b", "content": "fact-c"},
                {"action": "add", "content": original},
            ],
        },
        tool_result={"success": True, "done": True},
        metadata=_metadata(),
        home=tmp_path,
    )
    records = _state(tmp_path)["records"]
    superseded = next(item for item in records if item["id"] == first["id"])
    active = [item for item in records if item["status"] == "active"]
    assert superseded["status"] == "superseded"
    assert len(active) == 2
    assert superseded["superseded_by"] in {item["id"] for item in active}
    assert {item["content_sha256"] for item in active} == {
        memory_governance.content_digest("fact-c"),
        memory_governance.content_digest(original),
    }


def test_idempotent_or_staged_result_does_not_create_state(tmp_path):
    assert record_committed_write(
        target="memory",
        before_entries=["same"],
        after_entries=["same"],
        tool_args={"action": "add", "content": "same"},
        tool_result={"success": True, "message": "Entry already exists (no duplicate added)."},
        metadata=_metadata(),
        home=tmp_path,
    )
    assert not (tmp_path / "memories" / ".governance").exists()
    assert not record_committed_write(
        target="memory",
        before_entries=[],
        after_entries=[],
        tool_args={"action": "add", "content": "staged"},
        tool_result={"success": True, "staged": True},
        metadata=_metadata(),
        home=tmp_path,
    )


def test_corrupt_sidecar_fails_non_destructively(tmp_path):
    governance = tmp_path / "memories" / ".governance"
    governance.mkdir(parents=True)
    state_path = governance / "memory-governance.json"
    corrupt = b'{"schema":"wrong","memory_text":"must survive"}'
    state_path.write_bytes(corrupt)

    assert not record_committed_write_best_effort(
        target="memory",
        before_entries=[],
        after_entries=["new fact"],
        tool_args={"action": "add", "content": "new fact"},
        tool_result={"success": True},
        metadata=_metadata(),
        home=tmp_path,
    )
    assert state_path.read_bytes() == corrupt
    _write_entries(tmp_path, "memory", ["legacy remains usable"])
    report = audit_memory(home=tmp_path)
    assert report["status"] == "degraded"
    assert report["summary"]["untracked_entries"] == 1
    decisions = capture_expiry_decisions(
        {"memory": ["legacy remains usable"], "user": []}, home=tmp_path
    )
    assert decisions == {"memory": {}, "user": {}}


def test_symlink_sidecar_is_rejected_without_touching_target(tmp_path):
    if os.name == "nt":
        pytest.skip("symlink permissions differ on Windows")
    governance = tmp_path / "memories" / ".governance"
    governance.mkdir(parents=True)
    victim = tmp_path / "victim.json"
    victim.write_text("do-not-touch", encoding="utf-8")
    (governance / "memory-governance.json").symlink_to(victim)

    assert not record_committed_write_best_effort(
        target="memory",
        before_entries=[],
        after_entries=["fact"],
        tool_args={"action": "add", "content": "fact"},
        tool_result={"success": True},
        metadata=_metadata(),
        home=tmp_path,
    )
    assert victim.read_text(encoding="utf-8") == "do-not-touch"


def test_fifo_lock_is_rejected_without_blocking_or_writing_state(tmp_path):
    if os.name == "nt" or not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are not available on this platform")
    governance = tmp_path / "memories" / ".governance"
    governance.mkdir(parents=True)
    os.mkfifo(governance / ".lock")

    assert not record_committed_write_best_effort(
        target="memory",
        before_entries=[],
        after_entries=["fact"],
        tool_args={"action": "add", "content": "fact"},
        tool_result={"success": True},
        metadata=_metadata(),
        home=tmp_path,
    )
    assert not (governance / "memory-governance.json").exists()
    assert revalidate_record(
        "mem_0123456789abcdef0123456789abcdef", home=tmp_path
    )["error"] == "governance_state_unsafe"
    assert not record_relevance_label(
        "mem_0123456789abcdef0123456789abcdef",
        relevant=True,
        home=tmp_path,
    )
    assert not reset_governance("all", home=tmp_path)


def test_symlink_lock_is_rejected_without_changing_target(tmp_path):
    if os.name == "nt":
        pytest.skip("symlink permissions differ on Windows")
    governance = tmp_path / "memories" / ".governance"
    governance.mkdir(parents=True)
    victim = tmp_path / "lock-victim"
    victim.write_text("unchanged", encoding="utf-8")
    (governance / ".lock").symlink_to(victim)

    assert not record_committed_write_best_effort(
        target="memory",
        before_entries=[],
        after_entries=["fact"],
        tool_args={"action": "add", "content": "fact"},
        tool_result={"success": True},
        metadata=_metadata(),
        home=tmp_path,
    )
    assert victim.read_text(encoding="utf-8") == "unchanged"


def test_regular_file_swap_during_open_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    replacement = tmp_path / "replacement.json"
    path.write_text("original", encoding="utf-8")
    replacement.write_text("replacement", encoding="utf-8")
    real_open = os.open
    swapped = False

    def swapping_open(candidate, flags, *args):
        nonlocal swapped
        fd = real_open(candidate, flags, *args)
        if Path(candidate) == path and not swapped:
            swapped = True
            os.replace(replacement, path)
        return fd

    monkeypatch.setattr(memory_governance.os, "open", swapping_open)
    with pytest.raises(memory_governance.MemoryGovernanceError, match="changed"):
        memory_governance._read_regular_file(path, 1024)


def test_partial_key_writes_are_completed(tmp_path, monkeypatch):
    real_write = os.write

    def partial_write(fd, data):
        payload = bytes(data)
        return real_write(fd, payload[: max(1, len(payload) // 2)])

    monkeypatch.setattr(memory_governance.os, "write", partial_write)
    _record_add(tmp_path, "fact")
    key_path = tmp_path / "memories" / ".governance" / "memory-governance.key"
    assert key_path.stat().st_size == 32


def test_key_fstat_failure_preserves_primary_error(tmp_path, monkeypatch):
    governance = tmp_path / "memories" / ".governance"
    governance.mkdir(parents=True)
    monkeypatch.setattr(
        memory_governance.os,
        "fstat",
        lambda _fd: (_ for _ in ()).throw(OSError("fstat failed")),
    )

    with pytest.raises(OSError, match="fstat failed"):
        memory_governance._load_or_create_key_locked(governance)


def test_zero_length_key_write_is_rejected_before_state_commit(tmp_path, monkeypatch):
    governance = tmp_path / "memories" / ".governance"
    governance.mkdir(parents=True)
    (governance / ".lock").write_bytes(b"\0")
    monkeypatch.setattr(memory_governance.os, "write", lambda _fd, _data: 0)
    assert not record_committed_write_best_effort(
        target="memory",
        before_entries=[],
        after_entries=["fact"],
        tool_args={"action": "add", "content": "fact"},
        tool_result={"success": True},
        metadata=_metadata(),
        home=tmp_path,
    )
    assert not (
        tmp_path / "memories" / ".governance" / "memory-governance.json"
    ).exists()
    assert not (
        tmp_path / "memories" / ".governance" / "memory-governance.key"
    ).exists()


def test_existing_governance_directory_permissions_are_hardened(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permission modes are not portable to Windows")
    governance = tmp_path / "memories" / ".governance"
    governance.mkdir(parents=True, mode=0o755)
    governance.chmod(0o755)

    _record_add(tmp_path, "fact")

    assert stat.S_IMODE(governance.stat().st_mode) == 0o700


def test_atomic_state_replace_failure_preserves_prior_sidecar(tmp_path, monkeypatch):
    _record_add(tmp_path, "first")
    path = tmp_path / "memories" / ".governance" / "memory-governance.json"
    before = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("simulated crash window")

    monkeypatch.setattr(memory_governance.os, "replace", fail_replace)
    assert not record_committed_write_best_effort(
        target="memory",
        before_entries=["first"],
        after_entries=["first", "second"],
        tool_args={"action": "add", "content": "second"},
        tool_result={"success": True, "message": "Entry added."},
        metadata=_metadata(),
        home=tmp_path,
    )
    assert path.read_bytes() == before


def test_expiry_is_neutral_and_frozen_until_next_store(tmp_path, monkeypatch):
    from tools.memory_tool import MemoryStore

    entry = "private governed fact"
    _write_entries(tmp_path, "memory", [entry])
    old = datetime.now(timezone.utc) - timedelta(days=5)
    record = _record_add(tmp_path, entry, now=old, expiry_interval_days=1)

    monkeypatch.setattr("agent.memory_governance.get_fabric_home", lambda: tmp_path)
    monkeypatch.setattr(
        "tools.memory_tool.get_memory_dir", lambda: tmp_path / "memories"
    )
    store = MemoryStore()
    store.load_from_disk()
    snapshot = store.format_for_system_prompt("memory")
    assert EXPIRED_PLACEHOLDER in snapshot
    assert entry not in snapshot
    assert entry in store.memory_entries
    assert record["id"] in format_audit_report(audit_memory(home=tmp_path))

    result = revalidate_record(record["id"], home=tmp_path)
    assert result["success"] is True
    # Revalidation updates the next-session policy only.  This store's frozen
    # snapshot is byte-stable for the rest of the session.
    assert store.format_for_system_prompt("memory") == snapshot
    store.load_from_disk()
    assert store.format_for_system_prompt("memory") == snapshot

    next_store = MemoryStore()
    next_store.load_from_disk()
    assert entry in next_store.format_for_system_prompt("memory")


def test_expired_orphan_duplicate_does_not_hide_or_revalidate_current_occurrence(tmp_path):
    entry = "timezone: UTC"
    current = datetime.now(timezone.utc)
    first = _record_add(tmp_path, entry, now=current - timedelta(days=10))
    state = _state(tmp_path)
    duplicate = memory_governance._new_record(
        target="memory",
        digest=first["content_sha256"],
        source=first["source"],
        confidence="unspecified",
        current=current - timedelta(days=5),
        review_days=180,
        expiry_days=1,
        supersedes_content_id=None,
    )
    state["records"].append(duplicate)
    state["generation"] += 1
    with memory_governance._state_lock(tmp_path, create=False) as governance:
        memory_governance._write_state_locked(governance, state)
    _write_entries(tmp_path, "memory", [entry])

    assert capture_expiry_decisions(
        {"memory": [entry], "user": []}, home=tmp_path, now=current
    ) == {"memory": {}, "user": {}}
    assert revalidate_record(duplicate["id"], home=tmp_path, now=current) == {
        "success": False,
        "error": "record_orphaned",
    }
    report = audit_memory(home=tmp_path, now=current)
    assert [item["record_id"] for item in report["orphaned_records"]] == [
        duplicate["id"]
    ]


def test_audit_reconciles_duplicates_conflicts_untracked_orphans_and_metrics(tmp_path):
    tracked = "editor: vim"
    missing = "shell: zsh"
    tracked_record = _record_add(
        tmp_path,
        tracked,
        now=datetime.now(timezone.utc) - timedelta(days=400),
    )
    missing_record = record_committed_write(
        target="memory",
        before_entries=[tracked],
        after_entries=[tracked, missing],
        tool_args={"action": "add", "content": missing},
        tool_result={"success": True, "message": "Entry added."},
        metadata=_metadata(),
        home=tmp_path,
    )
    assert missing_record
    _write_entries(
        tmp_path,
        "memory",
        [tracked, tracked, "timezone: UTC", "timezone: America/Chicago"],
    )

    report = audit_memory(home=tmp_path)
    assert report["status"] == "attention"
    assert report["summary"]["exact_duplicate_groups"] == 1
    assert report["summary"]["candidate_contradictions"] == 1
    assert report["summary"]["orphaned_records"] == 1
    assert report["summary"]["untracked_entries"] == 3
    assert report["candidate_contradictions"][0]["classification"] == "candidate_contradiction"
    serialized = json.dumps(report)
    assert "timezone: UTC" not in serialized
    assert "America/Chicago" not in serialized
    assert report["retrieval_precision"] is None

    assert record_relevance_label(tracked_record["id"], relevant=True, home=tmp_path)
    assert audit_memory(home=tmp_path)["retrieval_precision"] == 1.0


def test_audit_surfaces_cross_target_duplicates_and_conflict_candidates(tmp_path):
    shared = "editor: vim"
    _write_entries(tmp_path, "memory", [shared, "timezone: UTC"])
    _write_entries(tmp_path, "user", [shared, "timezone: America/Chicago"])

    report = audit_memory(home=tmp_path)
    cross_duplicates = [
        item for item in report["exact_duplicates"] if item["target"] == "cross_target"
    ]
    cross_conflicts = [
        item
        for item in report["candidate_contradictions"]
        if item["target"] == "cross_target"
    ]
    assert len(cross_duplicates) == 1
    assert cross_duplicates[0]["targets"] == {"memory": 1, "user": 1}
    assert len(cross_conflicts) == 1
    assert cross_conflicts[0]["targets"] == ["memory", "user"]


def test_revalidate_rejects_orphan_and_refreshes_current_record(tmp_path):
    entry = "current fact"
    _write_entries(tmp_path, "memory", [entry])
    old = datetime.now(timezone.utc) - timedelta(days=300)
    record = _record_add(tmp_path, entry, now=old, review_interval_days=30)

    current = datetime.now(timezone.utc)
    result = revalidate_record(record["id"], home=tmp_path, now=current)
    assert result["success"] is True
    assert result["last_validated_at"].startswith(str(current.year))

    _write_entries(tmp_path, "memory", [])
    assert revalidate_record(record["id"], home=tmp_path)["error"] == "record_orphaned"


def test_targeted_reset_prunes_only_matching_records(tmp_path):
    _record_add(tmp_path, "memory fact", target="memory")
    _record_add(tmp_path, "user fact", target="user")

    assert reset_governance("memory", home=tmp_path)
    records = _state(tmp_path)["records"]
    assert [record["target"] for record in records] == ["user"]
    assert reset_governance("all", home=tmp_path)
    assert not (tmp_path / "memories" / ".governance" / "memory-governance.json").exists()
    assert not (tmp_path / "memories" / ".governance" / "memory-governance.key").exists()


def test_profile_isolation_uses_distinct_state_and_hmac_keys(tmp_path):
    first_home = tmp_path / "first"
    second_home = tmp_path / "second"
    first = _record_add(first_home, "same fact")
    second = _record_add(second_home, "same fact")

    assert first["content_sha256"] == second["content_sha256"]
    assert first["source"]["session_ref"] != second["source"]["session_ref"]
    assert (first_home / "memories" / ".governance" / "memory-governance.json").exists()
    assert (second_home / "memories" / ".governance" / "memory-governance.json").exists()
