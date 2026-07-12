"""Unit tests for the ``fabric ollama`` parser builder."""

from __future__ import annotations

import argparse

import pytest

from fabric_cli.subcommands.ollama import build_ollama_parser


def _sentinel_handler(args):  # pragma: no cover - only identity is asserted
    return args


def _build() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fabric")
    subparsers = parser.add_subparsers(dest="command")
    build_ollama_parser(subparsers, cmd_ollama=_sentinel_handler)
    return parser


def test_ollama_pull_defaults_and_dispatch() -> None:
    args = _build().parse_args(["ollama", "pull"])

    assert args.command == "ollama"
    assert args.ollama_action == "pull"
    assert args.model is None
    assert args.host is None
    assert args.yes is False
    assert args.func is _sentinel_handler


def test_ollama_pull_accepts_model_host_and_confirmation() -> None:
    args = _build().parse_args(
        [
            "ollama",
            "pull",
            "qwen3:8b",
            "--host",
            "http://127.0.0.1:11434",
            "--yes",
        ]
    )

    assert args.model == "qwen3:8b"
    assert args.host == "http://127.0.0.1:11434"
    assert args.yes is True


def test_ollama_pull_help_describes_only_supported_surface(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _build().parse_args(["ollama", "pull", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "usage: fabric ollama pull" in output
    assert "[model]" in output
    assert "--host HOST" in output
    assert "--yes" in output
    assert "--api-key" not in output


@pytest.mark.parametrize("verb", ["list", "progress", "cancel"])
def test_ollama_rejects_unsupported_verbs(verb: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _build().parse_args(["ollama", verb])

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "option_args",
    [["--api-key", "placeholder"], ["--background"], ["--insecure"]],
)
def test_ollama_pull_rejects_unsupported_options(option_args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _build().parse_args(["ollama", "pull", "model:latest", *option_args])

    assert exc_info.value.code == 2
