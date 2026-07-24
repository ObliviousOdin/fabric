#!/usr/bin/env python3
"""Render multi-view PNG snapshots of a STEP or STL part for visual review.

Usage (with the skill venv's interpreter — see scripts/setup.sh):

    python cadsnap.py part.step -o part.png [--views iso,front,top,right]

STEP input is tessellated to a temporary STL first; the mesh is then drawn
with matplotlib (headless-safe, no GPU or display required).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

SETUP_HINT = (
    "missing CAD dependencies; run scripts/setup.sh and use the venv "
    "interpreter it prints"
)

# View name -> (elevation, azimuth) in degrees for matplotlib's 3D camera.
VIEW_ANGLES = {
    "iso": (30, -60),
    "front": (0, -90),
    "top": (90, -90),
    "right": (0, 0),
    "back": (0, 90),
    "left": (0, 180),
    "bottom": (-90, -90),
}


def parse_views(text: str) -> list[str]:
    views = [piece.strip().lower() for piece in text.split(",") if piece.strip()]
    if not views:
        raise ValueError("at least one view is required")
    unknown = sorted(set(views) - set(VIEW_ANGLES))
    if unknown:
        raise ValueError(
            f"unknown views: {', '.join(unknown)} "
            f"(choose from {', '.join(sorted(VIEW_ANGLES))})"
        )
    return views


def grid_shape(count: int) -> tuple[int, int]:
    """Rows/columns for *count* view panels, widest-first."""
    if count <= 0:
        raise ValueError("count must be positive")
    if count == 1:
        return 1, 1
    columns = 2 if count <= 4 else 3
    rows = (count + columns - 1) // columns
    return rows, columns


def step_to_temp_stl(path: Path) -> Path:
    try:
        from build123d import export_stl, import_step
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"cadsnap: {SETUP_HINT} ({exc})") from exc

    shape = import_step(str(path))
    handle = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    handle.close()
    export_stl(shape, handle.name)
    return Path(handle.name)


def render(mesh_path: Path, out_path: Path, views: list[str]) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        from stl import mesh as stl_mesh
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"cadsnap: {SETUP_HINT} ({exc})") from exc

    body = stl_mesh.Mesh.from_file(str(mesh_path))
    points = body.vectors.reshape(-1, 3)
    mins, maxs = points.min(axis=0), points.max(axis=0)
    center = (mins + maxs) / 2
    radius = float((maxs - mins).max()) / 2 or 1.0

    rows, columns = grid_shape(len(views))
    figure = plt.figure(figsize=(4 * columns, 4 * rows))
    for index, view in enumerate(views, start=1):
        axes = figure.add_subplot(rows, columns, index, projection="3d")
        collection = Poly3DCollection(
            body.vectors, facecolor="#8fa8c8", edgecolor="#2f4058", linewidth=0.1
        )
        axes.add_collection3d(collection)
        for setter, mid in (
            (axes.set_xlim, center[0]),
            (axes.set_ylim, center[1]),
            (axes.set_zlim, center[2]),
        ):
            setter(mid - radius, mid + radius)
        elevation, azimuth = VIEW_ANGLES[view]
        axes.view_init(elev=elevation, azim=azimuth)
        axes.set_title(view)
        axes.set_axis_off()
    figure.tight_layout()
    figure.savefig(out_path, dpi=110)
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="STEP or STL file to render")
    parser.add_argument("-o", "--out", type=Path, required=True,
                        help="output PNG path")
    parser.add_argument("--views", type=parse_views, default=None,
                        help="comma-separated views (default iso,front,top,right)")
    args = parser.parse_args(argv)

    if not args.target.is_file():
        raise SystemExit(f"cadsnap: no such file: {args.target}")
    views = args.views or ["iso", "front", "top", "right"]

    suffix = args.target.suffix.lower()
    cleanup: Path | None = None
    if suffix in {".step", ".stp"}:
        mesh_path = cleanup = step_to_temp_stl(args.target)
    elif suffix == ".stl":
        mesh_path = args.target
    else:
        raise SystemExit(
            f"cadsnap: unsupported file type {suffix!r} (need STEP or STL)"
        )

    try:
        render(mesh_path, args.out, views)
    finally:
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)
    print(f"snapshot written: {args.out} ({', '.join(views)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
