#!/usr/bin/env python3
"""Parametric ISO metric standard parts (fasteners) as build123d solids.

Emit off-the-shelf hardware — socket-head cap screws, hex nuts, flat washers —
sized from a metric callout, so generators mate to real parts instead of
placeholders. Threads are represented as plain cylinders/bores (printable,
kernel-cheap); the callout, not a modeled helix, is the source of truth.

Usage (with the skill venv's interpreter — see scripts/setup.sh):

    python stdparts.py screw  --size M4 --length 20 --out screw.step
    python stdparts.py nut     --size M4 --out nut.step
    python stdparts.py washer  --size M4 --out washer.step
    python stdparts.py list

Importable too: `from stdparts import make_screw, SCREW_SPECS`.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

SETUP_HINT = (
    "missing CAD dependencies; run scripts/setup.sh and use the venv "
    "interpreter it prints"
)

# DIN 912 socket-head cap screw: head_dia, head_height, shaft_dia (mm).
SCREW_SPECS = {
    "M2": (3.8, 2.0, 2.0),
    "M2.5": (4.5, 2.5, 2.5),
    "M3": (5.5, 3.0, 3.0),
    "M4": (7.0, 4.0, 4.0),
    "M5": (8.5, 5.0, 5.0),
    "M6": (10.0, 6.0, 6.0),
    "M8": (13.0, 8.0, 8.0),
}
# DIN 934 hex nut: across-flats, thickness, bore (mm).
NUT_SPECS = {
    "M2": (4.0, 1.6, 2.0),
    "M2.5": (5.0, 2.0, 2.5),
    "M3": (5.5, 2.4, 3.0),
    "M4": (7.0, 3.2, 4.0),
    "M5": (8.0, 4.0, 5.0),
    "M6": (10.0, 5.0, 6.0),
    "M8": (13.0, 6.5, 8.0),
}
# DIN 125 flat washer: inner_dia, outer_dia, thickness (mm).
WASHER_SPECS = {
    "M2": (2.2, 5.0, 0.3),
    "M2.5": (2.7, 6.0, 0.5),
    "M3": (3.2, 7.0, 0.5),
    "M4": (4.3, 9.0, 0.8),
    "M5": (5.3, 10.0, 1.0),
    "M6": (6.4, 12.0, 1.6),
    "M8": (8.4, 16.0, 1.6),
}


def circumradius_from_across_flats(across_flats: float) -> float:
    """Hex circumradius from the across-flats (wrench) width."""
    return across_flats / math.sqrt(3.0)


def _require_size(size: str, specs: dict) -> tuple:
    if size not in specs:
        raise ValueError(
            f"unknown size {size!r}; choose from {', '.join(sorted(specs))}"
        )
    return specs[size]


def make_screw(size: str, length: float):
    """Socket-head cap screw solid; *length* is the shaft below the head."""
    if length <= 0:
        raise ValueError("length must be positive")
    head_dia, head_h, shaft_dia = _require_size(size, SCREW_SPECS)
    try:
        from build123d import Align, Cylinder, Pos
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"stdparts: {SETUP_HINT} ({exc})") from exc
    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    shaft = Cylinder(shaft_dia / 2, length, align=bottom)
    head = Pos(0, 0, length) * Cylinder(head_dia / 2, head_h, align=bottom)
    return shaft + head


def make_nut(size: str):
    """Hex nut solid with a through bore."""
    across_flats, thickness, bore = _require_size(size, NUT_SPECS)
    try:
        from build123d import (
            BuildPart,
            BuildSketch,
            Circle,
            Mode,
            RegularPolygon,
            extrude,
        )
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"stdparts: {SETUP_HINT} ({exc})") from exc
    radius = circumradius_from_across_flats(across_flats)
    with BuildPart() as nut:
        with BuildSketch():
            RegularPolygon(radius, 6)
            Circle(bore / 2, mode=Mode.SUBTRACT)
        extrude(amount=thickness)
    return nut.part


def make_washer(size: str):
    """Flat washer solid (annulus)."""
    inner, outer, thickness = _require_size(size, WASHER_SPECS)
    try:
        from build123d import (
            BuildPart,
            BuildSketch,
            Circle,
            Mode,
            extrude,
        )
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"stdparts: {SETUP_HINT} ({exc})") from exc
    with BuildPart() as washer:
        with BuildSketch():
            Circle(outer / 2)
            Circle(inner / 2, mode=Mode.SUBTRACT)
        extrude(amount=thickness)
    return washer.part


BUILDERS = {
    "screw": (make_screw, SCREW_SPECS),
    "nut": (make_nut, NUT_SPECS),
    "washer": (make_washer, WASHER_SPECS),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    for kind in ("screw", "nut", "washer"):
        p = sub.add_parser(kind, help=f"emit a {kind}")
        p.add_argument("--size", required=True, help="metric callout, e.g. M4")
        if kind == "screw":
            p.add_argument("--length", type=float, required=True,
                           help="shaft length in mm")
        p.add_argument("--out", type=Path, required=True, help="output STEP path")
    sub.add_parser("list", help="list available sizes")
    args = parser.parse_args(argv)

    if args.kind == "list":
        for kind, (_builder, specs) in BUILDERS.items():
            print(f"{kind}: {', '.join(sorted(specs))}")
        return 0

    try:
        from build123d import export_step
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"stdparts: {SETUP_HINT} ({exc})") from exc

    if args.kind == "screw":
        part = make_screw(args.size, args.length)
    elif args.kind == "nut":
        part = make_nut(args.size)
    else:
        part = make_washer(args.size)

    export_step(part, str(args.out))
    print(f"written: {args.out} ({args.kind} {args.size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
