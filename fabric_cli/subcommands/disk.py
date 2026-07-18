"""``fabric disk`` subcommand parser.

Builds the ``disk`` command tree (``usage`` / ``clean``) and injects the
``cmd_disk`` handler so this module never imports ``fabric_cli.main``.
Mirrors the pattern in ``fabric_cli/subcommands/memory.py``.
"""

from __future__ import annotations

import argparse
from typing import Callable


def build_disk_parser(subparsers, *, cmd_disk: Callable) -> None:
    """Attach the ``disk`` subcommand to ``subparsers``."""
    from fabric_cli.disk import RECLAIMABLE_KEYS

    disk_parser = subparsers.add_parser(
        "disk",
        help="Inspect and reclaim Fabric's on-disk storage",
        description=(
            "Report how much disk space Fabric is using and reclaim "
            "regenerable data (caches, rotated logs, traces, scratch).\n\n"
            "See: https://obliviousodin.github.io/fabric/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
    fabric disk usage              Break down space used, largest-first
    fabric disk du --all           Include empty categories
    fabric disk usage --json       Machine-readable output
    fabric disk clean              Preview what would be reclaimed (dry-run)
    fabric disk clean --yes        Delete reclaimable caches/logs/traces
    fabric disk clean --only cache Clean just the cache category
    fabric disk clean --skip logs --yes             Clean everything but logs
""",
    )
    disk_sub = disk_parser.add_subparsers(dest="disk_command")

    # ---- usage / du ----
    usage_parser = disk_sub.add_parser(
        "usage",
        aliases=["du"],
        help="Show how much disk each Fabric store is using",
        description="Report per-category disk usage under the Fabric home.",
    )
    usage_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print a machine-readable JSON report",
    )
    usage_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include categories that are currently empty",
    )
    usage_parser.add_argument(
        "--profile",
        metavar="NAME",
        default=None,
        help="Report usage for another profile instead of the active one",
    )

    # ---- clean ----
    clean_parser = disk_sub.add_parser(
        "clean",
        help="Delete reclaimable data (caches, traces, old logs) — dry-run unless --yes",
        description=(
            "Reclaim regenerable Fabric data. Dry-run by default: prints what "
            "would be removed and deletes nothing until you pass --yes. Never "
            "touches sessions, memories, credentials, config, backups, or "
            "databases."
        ),
    )
    clean_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Actually delete (default is a dry-run preview)",
    )
    clean_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="With --yes, skip the confirmation prompt (required non-interactively)",
    )
    clean_parser.add_argument(
        "--only",
        nargs="+",
        metavar="CATEGORY",
        choices=RECLAIMABLE_KEYS,
        help=f"Clean only these categories (choices: {', '.join(RECLAIMABLE_KEYS)})",
    )
    clean_parser.add_argument(
        "--skip",
        nargs="+",
        metavar="CATEGORY",
        choices=RECLAIMABLE_KEYS,
        help="Clean everything reclaimable except these categories",
    )

    disk_parser.set_defaults(func=cmd_disk, _disk_parser=disk_parser)
