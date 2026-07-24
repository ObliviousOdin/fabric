#!/usr/bin/env python3
"""FDM print-readiness checks for an STL mesh (no slicer required).

Reports whether a part fits the printer bed, how much steep-overhang area it
carries (support likely), the thinnest bounding dimension, and the triangle
count. Catches the common "looks fine, unprintable" failures before a slice.

Usage (with the skill venv's interpreter — see scripts/setup.sh):

    python printcheck.py part.stl --bed 220,220,250 --overhang-deg 45

Exit is non-zero when the part does not fit the bed; overhang and thin-wall
findings are reported as warnings (they depend on print orientation).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

SETUP_HINT = (
    "missing CAD dependencies; run scripts/setup.sh and use the venv "
    "interpreter it prints"
)


def parse_bed(text: str) -> tuple[float, float, float]:
    parts = [piece.strip() for piece in text.split(",")]
    if len(parts) != 3:
        raise ValueError("bed must be 'X,Y,Z' in mm, e.g. 220,220,250")
    x, y, z = (float(piece) for piece in parts)
    if min(x, y, z) <= 0:
        raise ValueError("bed dimensions must be positive")
    return x, y, z


def fits_bed(
    size: tuple[float, float, float], bed: tuple[float, float, float]
) -> bool:
    """True when *size* fits *bed*, allowing a 90-degree footprint rotation.

    Height is fixed (Z); the X/Y footprint may be rotated, so its two extents
    are matched against the bed's two footprint axes in sorted order.
    """
    if size[2] > bed[2]:
        return False
    footprint = sorted(size[:2])
    bed_footprint = sorted(bed[:2])
    return all(f <= b for f, b in zip(footprint, bed_footprint))


def overhang_fraction(normals_z: list[float], areas: list[float], limit_deg: float) -> float:
    """Fraction of downward-facing area steeper than the overhang limit.

    A face needs support when its downward tilt from vertical exceeds
    ``limit_deg``: normal_z < -sin(limit). Perfectly flat bottoms
    (normal_z == -1) count; near-vertical walls do not.
    """
    threshold = -math.sin(math.radians(limit_deg))
    total = sum(areas) or 1.0
    steep = sum(
        area for nz, area in zip(normals_z, areas) if nz < threshold
    )
    return steep / total


def collect_mesh_metrics(path: Path, bed, overhang_deg: float) -> dict:
    try:
        import numpy
        from stl import mesh as stl_mesh
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"printcheck: {SETUP_HINT} ({exc})") from exc

    body = stl_mesh.Mesh.from_file(str(path))
    points = body.vectors.reshape(-1, 3)
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    size = tuple(float(v) for v in (maxs - mins))

    # Per-triangle area and unit normal Z from mesh.normals (unnormalized).
    normals = body.normals
    lengths = numpy.linalg.norm(normals, axis=1)
    areas = (lengths / 2.0).tolist()
    with numpy.errstate(invalid="ignore", divide="ignore"):
        unit_nz = numpy.where(lengths > 0, normals[:, 2] / lengths, 0.0)
    frac = overhang_fraction(unit_nz.tolist(), areas, overhang_deg)

    return {
        "file": str(path),
        "triangles": int(len(body.vectors)),
        "bbox_size_mm": [round(v, 3) for v in size],
        "bed_mm": list(bed),
        "fits_bed": fits_bed(size, bed),
        "thinnest_dim_mm": round(min(size), 3),
        "overhang_deg": overhang_deg,
        "overhang_area_fraction": round(frac, 4),
        "support_likely": frac > 0.05,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="STL file to check")
    parser.add_argument("--bed", type=parse_bed, default=(220.0, 220.0, 250.0),
                        metavar="X,Y,Z", help="printer bed volume (default 220,220,250)")
    parser.add_argument("--overhang-deg", type=float, default=45.0,
                        help="overhang angle from vertical needing support (default 45)")
    parser.add_argument("--min-wall-mm", type=float, default=1.0,
                        help="warn when the thinnest dimension is below this (default 1.0)")
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the report to this path")
    args = parser.parse_args(argv)

    if not args.target.is_file():
        raise SystemExit(f"printcheck: no such file: {args.target}")
    if args.target.suffix.lower() != ".stl":
        raise SystemExit("printcheck: expects an STL mesh")

    metrics = collect_mesh_metrics(args.target, args.bed, args.overhang_deg)
    warnings = []
    if metrics["support_likely"]:
        warnings.append(
            f"{metrics['overhang_area_fraction'] * 100:.1f}% overhang area "
            f"beyond {args.overhang_deg} deg — supports likely"
        )
    if metrics["thinnest_dim_mm"] < args.min_wall_mm:
        warnings.append(
            f"thinnest dimension {metrics['thinnest_dim_mm']} mm is below "
            f"{args.min_wall_mm} mm"
        )
    metrics["warnings"] = warnings

    document = json.dumps(metrics, indent=2)
    print(document)
    if args.json is not None:
        args.json.write_text(document + "\n", encoding="utf-8")
    return 0 if metrics["fits_bed"] else 1


if __name__ == "__main__":
    sys.exit(main())
