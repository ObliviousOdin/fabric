#!/usr/bin/env python3
"""Combine placed STEP parts into one assembly and flag unintended overlap.

Each part is imported, translated (and optionally rotated about Z), labeled,
and merged into a single Compound exported as one STEP. Bounding-box overlap
between every pair is reported so interference is caught numerically rather
than by eye.

Usage (with the skill venv's interpreter — see scripts/setup.sh):

    python assembly.py \
        --part base.step:0,0,0 \
        --part lid.step:0,0,20:rz=90 \
        --out enclosure.step

Exit is non-zero when any pair's bounding boxes overlap beyond --clearance
(default 0.0 mm), unless --allow-overlap is given (press-fits, fasteners).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SETUP_HINT = (
    "missing CAD dependencies; run scripts/setup.sh and use the venv "
    "interpreter it prints"
)


class Placement:
    """A parsed --part spec: path plus an (x, y, z) offset and Z rotation."""

    def __init__(self, path: Path, offset: tuple[float, float, float], rz: float):
        self.path = path
        self.offset = offset
        self.rz = rz

    @property
    def label(self) -> str:
        return self.path.stem


def parse_placement(spec: str) -> Placement:
    """Parse 'path:x,y,z' or 'path:x,y,z:rz=DEG'."""
    segments = spec.split(":")
    if len(segments) < 2:
        raise ValueError(
            f"placement {spec!r} must be 'path:x,y,z' (optional ':rz=DEG')"
        )
    path = Path(segments[0])
    coords = [piece.strip() for piece in segments[1].split(",")]
    if len(coords) != 3:
        raise ValueError(f"placement {spec!r} needs three offsets 'x,y,z'")
    offset = tuple(float(piece) for piece in coords)
    rz = 0.0
    for extra in segments[2:]:
        key, _, value = extra.partition("=")
        if key.strip() != "rz":
            raise ValueError(f"unknown placement option {extra!r} (only 'rz=DEG')")
        rz = float(value)
    return Placement(path, offset, rz)  # type: ignore[arg-type]


def boxes_overlap(a: dict, b: dict, clearance: float = 0.0) -> bool:
    """True when axis-aligned bounding boxes *a* and *b* interpenetrate.

    Each box is {'min': (x, y, z), 'max': (x, y, z)}. A shared face
    (touching, not overlapping) is not an overlap. *clearance* shrinks each
    box so a tiny modeled interference within tolerance is ignored.
    """
    for axis in range(3):
        a_min, a_max = a["min"][axis] + clearance, a["max"][axis] - clearance
        b_min, b_max = b["min"][axis] + clearance, b["max"][axis] - clearance
        if a_max <= b_min or b_max <= a_min:
            return False
    return True


def _placed_solid(placement: Placement):
    from build123d import Pos, Rot, import_step

    shape = import_step(str(placement.path))
    if placement.rz:
        shape = Rot(0, 0, placement.rz) * shape
    shape = Pos(*placement.offset) * shape
    shape.label = placement.label
    return shape


def build_assembly(placements: list[Placement], out: Path, clearance: float):
    try:
        from build123d import Compound, export_step
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"assembly: {SETUP_HINT} ({exc})") from exc

    solids = []
    boxes: list[tuple[str, dict]] = []
    for placement in placements:
        if not placement.path.is_file():
            raise SystemExit(f"assembly: no such part: {placement.path}")
        solid = _placed_solid(placement)
        box = solid.bounding_box()
        boxes.append(
            (
                placement.label,
                {
                    "min": (box.min.X, box.min.Y, box.min.Z),
                    "max": (box.max.X, box.max.Y, box.max.Z),
                },
            )
        )
        solids.append(solid)

    assembly = Compound(children=solids)
    export_step(assembly, str(out))

    overlaps = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes_overlap(boxes[i][1], boxes[j][1], clearance):
                overlaps.append(f"{boxes[i][0]} <-> {boxes[j][0]}")
    return assembly, overlaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", action="append", type=parse_placement,
                        required=True, metavar="PATH:x,y,z[:rz=DEG]",
                        help="a placed STEP part (repeatable)")
    parser.add_argument("--out", type=Path, required=True,
                        help="output assembly STEP path")
    parser.add_argument("--clearance", type=float, default=0.0,
                        help="overlap tolerance in mm (default 0)")
    parser.add_argument("--allow-overlap", action="store_true",
                        help="report overlaps but exit 0 (press-fits, screws)")
    args = parser.parse_args(argv)

    _assembly, overlaps = build_assembly(args.part, args.out, args.clearance)
    print(f"written: {args.out} ({len(args.part)} parts)")
    if overlaps:
        print("overlap detected between: " + "; ".join(overlaps))
        return 0 if args.allow_overlap else 1
    print("no bounding-box overlap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
