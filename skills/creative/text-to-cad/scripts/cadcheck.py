#!/usr/bin/env python3
"""Geometry facts and pass/fail validation for STEP and STL artifacts.

Usage (with the skill venv's interpreter — see scripts/setup.sh):

    python cadcheck.py part.step [--expect-bbox X,Y,Z] [--tolerance MM]
                       [--min-volume MM3] [--json out.json]

Prints a JSON facts document to stdout and exits non-zero when any
requested check fails, so it can gate a generation pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SETUP_HINT = (
    "missing CAD dependencies; run scripts/setup.sh and use the venv "
    "interpreter it prints"
)


def parse_bbox(text: str) -> tuple[float, float, float]:
    """Parse an 'X,Y,Z' bounding-box size in mm."""
    parts = [piece.strip() for piece in text.split(",")]
    if len(parts) != 3:
        raise ValueError("expected three comma-separated numbers, e.g. 40,20,30")
    x, y, z = (float(piece) for piece in parts)
    if min(x, y, z) <= 0:
        raise ValueError("bounding-box sizes must be positive")
    return x, y, z


def check_facts(
    facts: dict,
    expect_bbox: tuple[float, float, float] | None = None,
    tolerance: float = 0.1,
    min_volume: float | None = None,
) -> list[str]:
    """Return human-readable failure strings for *facts* against the targets.

    The bbox comparison is orientation-insensitive: sorted extents are
    compared so a part modeled with swapped axes still passes.
    """
    failures: list[str] = []
    if not facts.get("is_valid", False):
        failures.append("geometry is not a valid solid")
    if facts.get("volume_mm3", 0) <= 0:
        failures.append("volume is not positive")
    if min_volume is not None and facts.get("volume_mm3", 0) < min_volume:
        failures.append(
            f"volume {facts.get('volume_mm3'):.1f} mm^3 is below "
            f"the minimum {min_volume:.1f} mm^3"
        )
    if expect_bbox is not None:
        actual = sorted(facts.get("bbox_size_mm", (0.0, 0.0, 0.0)))
        expected = sorted(expect_bbox)
        for got, want in zip(actual, expected):
            if abs(got - want) > tolerance:
                failures.append(
                    f"bbox {tuple(round(v, 3) for v in actual)} differs from "
                    f"expected {tuple(expected)} beyond {tolerance} mm"
                )
                break
    return failures


def collect_step_facts(path: Path) -> dict:
    try:
        from build123d import import_step
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"cadcheck: {SETUP_HINT} ({exc})") from exc

    shape = import_step(str(path))
    solids = shape.solids()
    box = shape.bounding_box()
    return {
        "file": str(path),
        "format": "step",
        "units": "mm (STEP convention)",
        "solids": len(solids),
        "is_valid": bool(shape.is_valid),
        "volume_mm3": float(shape.volume),
        "area_mm2": float(shape.area),
        "bbox_size_mm": [float(box.size.X), float(box.size.Y), float(box.size.Z)],
        "bbox_min_mm": [float(box.min.X), float(box.min.Y), float(box.min.Z)],
        "bbox_max_mm": [float(box.max.X), float(box.max.Y), float(box.max.Z)],
    }


def collect_stl_facts(path: Path) -> dict:
    try:
        import numpy
        from stl import mesh as stl_mesh
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"cadcheck: {SETUP_HINT} ({exc})") from exc

    body = stl_mesh.Mesh.from_file(str(path))
    volume, _cog, _inertia = body.get_mass_properties()
    mins = body.vectors.reshape(-1, 3).min(axis=0)
    maxs = body.vectors.reshape(-1, 3).max(axis=0)
    size = maxs - mins
    return {
        "file": str(path),
        "format": "stl",
        "units": "mm (by skill convention; STL is unitless)",
        "triangles": int(len(body.vectors)),
        "is_valid": bool(numpy.isfinite(volume) and volume > 0),
        "volume_mm3": float(volume),
        "bbox_size_mm": [float(v) for v in size],
        "bbox_min_mm": [float(v) for v in mins],
        "bbox_max_mm": [float(v) for v in maxs],
    }


def collect_facts(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix in {".step", ".stp"}:
        return collect_step_facts(path)
    if suffix == ".stl":
        return collect_stl_facts(path)
    raise SystemExit(f"cadcheck: unsupported file type {suffix!r} (need STEP or STL)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="STEP or STL file to inspect")
    parser.add_argument("--expect-bbox", type=parse_bbox, default=None,
                        metavar="X,Y,Z", help="expected bbox size in mm")
    parser.add_argument("--tolerance", type=float, default=0.1,
                        help="bbox tolerance in mm (default 0.1)")
    parser.add_argument("--min-volume", type=float, default=None,
                        metavar="MM3", help="minimum solid volume in mm^3")
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the facts document to this path")
    args = parser.parse_args(argv)

    if not args.target.is_file():
        raise SystemExit(f"cadcheck: no such file: {args.target}")

    facts = collect_facts(args.target)
    failures = check_facts(
        facts,
        expect_bbox=args.expect_bbox,
        tolerance=args.tolerance,
        min_volume=args.min_volume,
    )
    facts["checks_passed"] = not failures
    facts["failures"] = failures

    document = json.dumps(facts, indent=2)
    print(document)
    if args.json is not None:
        args.json.write_text(document + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
