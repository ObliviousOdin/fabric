"""``fabric monitor`` (alias ``fabric top``) subcommand parser.

Handler injected from ``fabric_cli/main.py`` to avoid importing ``main``.
"""

from __future__ import annotations

from typing import Callable


def build_monitor_parser(subparsers, *, cmd_monitor: Callable) -> None:
    """Attach the ``monitor`` subcommand (and its ``top`` alias)."""
    monitor_parser = subparsers.add_parser(
        "monitor",
        aliases=["top"],
        help="Live host monitor — CPU, memory, disk, load, network, GPU",
        description=(
            "Live terminal view of this machine's CPU, memory, disk, load "
            "average, network throughput and GPU utilisation. Refreshes in "
            "place; press Ctrl-C to quit."
        ),
    )
    monitor_parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="Refresh interval in seconds (default: 2)",
    )
    monitor_parser.add_argument(
        "--once",
        action="store_true",
        help="Print a single frame and exit",
    )
    monitor_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one raw stats sample as JSON and exit",
    )
    monitor_parser.set_defaults(func=cmd_monitor)
