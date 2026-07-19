from __future__ import annotations

import os

import pytest

from fabric_cli.kanban_runtime import (
    KanbanRuntimeContext,
    consume_context_argument,
    consume_kanban_runtime_context,
    get_kanban_runtime_context,
    write_kanban_runtime_context,
)


def _context() -> KanbanRuntimeContext:
    return KanbanRuntimeContext(
        task_id="t_roundtrip",
        board="project",
        db_path="/state/project.db",
        workspaces_root="/workspaces",
        workspace="/workspaces/t_roundtrip",
        branch="project/t_roundtrip",
        run_id=7,
        claim_lock="host:1:claim",
        tenant="acme",
        profile="builder",
        goal_mode=True,
        goal_max_turns=9,
    )


def test_descriptor_round_trip_is_owner_only_and_consumed(tmp_path):
    path = write_kanban_runtime_context(_context(), directory=tmp_path)
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0

    restored = consume_kanban_runtime_context(path)

    assert restored == _context()
    assert not path.exists()


def test_hidden_argument_is_removed_and_context_bound(tmp_path):
    path = write_kanban_runtime_context(_context(), directory=tmp_path)
    argv = ["fabric", "--accept-hooks", "--kanban-worker-context", str(path), "chat"]

    assert consume_context_argument(argv) is True

    assert argv == ["fabric", "--accept-hooks", "chat"]
    assert get_kanban_runtime_context() == _context()
    assert not path.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not portable")
def test_descriptor_rejects_group_readable_file_and_still_unlinks(tmp_path):
    path = write_kanban_runtime_context(_context(), directory=tmp_path)
    path.chmod(0o640)

    with pytest.raises(PermissionError, match="owner-only"):
        consume_kanban_runtime_context(path)

    assert not path.exists()


def test_duplicate_hidden_arguments_fail_closed(tmp_path):
    first = write_kanban_runtime_context(_context(), directory=tmp_path)
    second = write_kanban_runtime_context(_context(), directory=tmp_path)
    argv = [
        "fabric",
        "--kanban-worker-context",
        str(first),
        "--kanban-worker-context",
        str(second),
        "chat",
    ]

    with pytest.raises(ValueError, match="only once"):
        consume_context_argument(argv)

    first.unlink()
    second.unlink()
