from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

from fabric_cli.subcommands.memory import build_memory_parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    build_memory_parser(subparsers, cmd_memory=lambda _args: None)
    return parser


def test_memory_audit_parser_accepts_json():
    args = _parser().parse_args(["memory", "audit", "--json"])
    assert args.command == "memory"
    assert args.memory_command == "audit"
    assert args.json_output is True


def test_memory_revalidate_parser_requires_record_id():
    args = _parser().parse_args(
        ["memory", "revalidate", "mem_0123456789abcdef0123456789abcdef"]
    )
    assert args.memory_command == "revalidate"
    assert args.record_id == "mem_0123456789abcdef0123456789abcdef"


def test_cmd_memory_audit_json_is_machine_readable(monkeypatch, capsys):
    from fabric_cli.main import cmd_memory

    report = {
        "schema": "fabric.memory-governance-audit/v1",
        "status": "ok",
        "summary": {},
    }
    monkeypatch.setattr("agent.memory_governance.audit_memory", lambda: report)
    cmd_memory(SimpleNamespace(memory_command="audit", json_output=True))
    assert json.loads(capsys.readouterr().out) == report


def test_cmd_memory_revalidate_surfaces_next_session_boundary(monkeypatch, capsys):
    from fabric_cli.main import cmd_memory

    monkeypatch.setattr(
        "agent.memory_governance.revalidate_record",
        lambda _record_id: {
            "success": True,
            "record_id": "mem_0123456789abcdef0123456789abcdef",
            "last_validated_at": "2026-07-14T00:00:00.000Z",
            "review_after": "2027-01-10T00:00:00.000Z",
            "expires_at": None,
        },
    )
    cmd_memory(
        SimpleNamespace(
            memory_command="revalidate",
            record_id="mem_0123456789abcdef0123456789abcdef",
        )
    )
    output = capsys.readouterr().out
    assert "Revalidated" in output
    assert "new sessions" in output


def test_cmd_memory_targeted_reset_prunes_governance(monkeypatch, tmp_path, capsys):
    from agent.memory_governance import audit_memory, record_committed_write
    from fabric_cli.main import cmd_memory

    monkeypatch.setenv("FABRIC_HOME", str(tmp_path))
    memory_dir = tmp_path / "memories"
    memory_dir.mkdir(parents=True)
    entry = "shell: zsh"
    (memory_dir / "MEMORY.md").write_text(entry, encoding="utf-8")
    assert record_committed_write(
        target="memory",
        before_entries=[],
        after_entries=[entry],
        tool_args={"action": "add", "content": entry},
        tool_result={"success": True, "message": "Entry added."},
        metadata={
            "write_origin": "assistant_tool",
            "execution_context": "foreground",
            "platform": "cli",
        },
        home=tmp_path,
    )

    cmd_memory(SimpleNamespace(memory_command="reset", target="memory", yes=True))

    assert not (memory_dir / "MEMORY.md").exists()
    assert audit_memory(home=tmp_path)["summary"]["governed_active_records"] == 0
    assert "Reset matching memory governance state" in capsys.readouterr().out
