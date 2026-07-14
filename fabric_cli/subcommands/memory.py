"""``fabric memory`` subcommand parser.

Extracted from ``fabric_cli/main.py:main()`` (god-file Phase 2 follow-up).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

from typing import Callable


def build_memory_parser(subparsers, *, cmd_memory: Callable) -> None:
    """Attach the ``memory`` subcommand to ``subparsers``."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Configure and audit persistent memory",
        description=(
            "Set up and manage built-in memory governance and external provider plugins.\n\n"
            "Available providers: honcho, openviking, mem0, hindsight,\n"
            "holographic, retaindb, byterover, supermemory.\n\n"
            "Only one external provider can be active at a time.\n"
            "MEMORY.md and USER.md are controlled independently by the\n"
            "memory.memory_enabled and memory.user_profile_enabled settings.\n"
            "External providers activate only while at least one tier is enabled."
        ),
    )
    memory_sub = memory_parser.add_subparsers(dest="memory_command")
    _setup_parser = memory_sub.add_parser(
        "setup", help="Interactive provider selection and configuration"
    )
    _setup_parser.add_argument(
        "provider",
        nargs="?",
        default=None,
        help="Provider to configure directly (e.g. honcho), skipping the picker",
    )
    memory_sub.add_parser("status", help="Show memory tiers and provider config")
    memory_sub.add_parser(
        "off",
        help="Disable external provider (built-in tier settings unchanged)",
    )
    _audit_parser = memory_sub.add_parser(
        "audit",
        help="Audit MEMORY.md/USER.md provenance, lifecycle, and consistency",
    )
    _audit_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the privacy-safe machine-readable audit",
    )
    _revalidate_parser = memory_sub.add_parser(
        "revalidate",
        help="Revalidate one governed memory record by opaque id",
    )
    _revalidate_parser.add_argument(
        "record_id",
        help="Opaque record id from `fabric memory audit --json`",
    )
    _reset_parser = memory_sub.add_parser(
        "reset",
        help="Erase all built-in memory (MEMORY.md and USER.md)",
    )
    _reset_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    _reset_parser.add_argument(
        "--target",
        choices=["all", "memory", "user"],
        default="all",
        help="Which store to reset: 'all' (default), 'memory', or 'user'",
    )
    memory_parser.set_defaults(func=cmd_memory)
