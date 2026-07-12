"""Top-level CLI routing contract for ``fabric ollama``."""

from __future__ import annotations

import sys

import pytest

from fabric_cli import main as cli_main


def test_main_routes_ollama_pull_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_pull(args) -> int:
        captured.update(model=args.model, host=args.host, yes=args.yes)
        return 0

    monkeypatch.setattr("fabric_cli.ollama_pull.cmd_ollama_pull", fake_pull)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fabric",
            "ollama",
            "pull",
            "qwen3:8b",
            "--host",
            "http://127.0.0.1:11434",
            "--yes",
        ],
    )

    cli_main.main()

    assert captured == {
        "model": "qwen3:8b",
        "host": "http://127.0.0.1:11434",
        "yes": True,
    }


@pytest.mark.parametrize("exit_code", [1, 130])
def test_main_preserves_ollama_pull_failure_codes(
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
) -> None:
    monkeypatch.setattr(
        "fabric_cli.ollama_pull.cmd_ollama_pull", lambda _args: exit_code
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["fabric", "ollama", "pull", "qwen3:8b", "--yes"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_main.main()

    assert exc_info.value.code == exit_code


def test_bare_ollama_command_returns_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["fabric", "ollama"])

    with pytest.raises(SystemExit) as exc_info:
        cli_main.main()

    assert exc_info.value.code == 2
    assert (
        "usage: fabric ollama pull [MODEL] [--host URL] [--yes]"
        in capsys.readouterr().err
    )


def test_session_name_coalescing_stops_at_ollama_command() -> None:
    assert cli_main._coalesce_session_name_args(
        ["-c", "my", "session", "ollama", "pull", "qwen3:8b"]
    ) == ["-c", "my session", "ollama", "pull", "qwen3:8b"]

