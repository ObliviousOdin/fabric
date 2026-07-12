"""``fabric ollama`` subcommand parser."""

from __future__ import annotations

from typing import Callable


def build_ollama_parser(subparsers, *, cmd_ollama: Callable) -> None:
    """Attach the ``ollama`` command group to ``subparsers``."""
    ollama_parser = subparsers.add_parser(
        "ollama",
        help="Manage local Ollama models",
        description="Manage models on a local or private Ollama server",
    )
    ollama_subparsers = ollama_parser.add_subparsers(dest="ollama_action")

    pull_parser = ollama_subparsers.add_parser(
        "pull",
        help="Pull and verify an Ollama model",
        description="Pull an Ollama model in the foreground and verify installation",
    )
    pull_parser.add_argument(
        "model",
        nargs="?",
        help="Model to pull (uses the configured local Ollama model when omitted)",
    )
    pull_parser.add_argument(
        "--host",
        help="Local or private Ollama server URL",
    )
    pull_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the pull without prompting",
    )

    ollama_parser.set_defaults(func=cmd_ollama)
