#!/usr/bin/env python3
"""Inspect and validate a DXF 2D drawing (laser-cut / waterjet profiles).

Reports entity counts by type, the drawing extents, and how many closed cut
profiles it contains, then fails when the file is empty or (optionally) when
any contour is left open. Pairs with build123d's ``ExportDXF`` authoring path
documented in references/dxf-drawings.md.

build123d exports a rectangle as four separate LINE entities and holes as
CIRCLE entities, so closure is judged structurally: circles and closed
polylines/splines count directly, and loose LINE/ARC segments are closed
only when every shared endpoint has even degree (no dangling ends).

Usage (with the skill venv's interpreter — see scripts/setup.sh):

    python dxfcheck.py plate.dxf --require-closed
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

SETUP_HINT = (
    "missing DXF dependency; run scripts/setup.sh and use the venv "
    "interpreter it prints"
)

_INHERENTLY_CLOSED = {"CIRCLE", "ELLIPSE"}
_QUANTIZE = 4  # decimal places for endpoint matching (0.1 micron)


def _key(x: float, y: float) -> tuple[float, float]:
    return (round(x, _QUANTIZE), round(y, _QUANTIZE))


def analyze_segments(endpoints: list[tuple[tuple, tuple]]) -> tuple[int, int]:
    """Return (closed_loop_count, open_endpoint_count) for line/arc segments.

    Each endpoint is a coordinate key; a vertex touched by an odd number of
    segment ends is a dangling (open) end. When no vertex is odd, every
    connected component of segments forms a closed loop.
    """
    degree: dict[tuple, int] = {}
    adjacency: dict[tuple, set] = {}
    for start, end in endpoints:
        degree[start] = degree.get(start, 0) + 1
        degree[end] = degree.get(end, 0) + 1
        adjacency.setdefault(start, set()).add(end)
        adjacency.setdefault(end, set()).add(start)

    open_ends = sum(1 for count in degree.values() if count % 2 == 1)
    if open_ends or not adjacency:
        return 0, open_ends

    # All vertices even-degree: count connected components (each a closed loop).
    seen: set = set()
    loops = 0
    for vertex in adjacency:
        if vertex in seen:
            continue
        loops += 1
        stack = [vertex]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(adjacency[node] - seen)
    return loops, 0


def _arc_endpoints(entity) -> tuple[tuple, tuple]:
    center = entity.dxf.center
    radius = entity.dxf.radius
    start = math.radians(entity.dxf.start_angle)
    end = math.radians(entity.dxf.end_angle)
    return (
        _key(center.x + radius * math.cos(start), center.y + radius * math.sin(start)),
        _key(center.x + radius * math.cos(end), center.y + radius * math.sin(end)),
    )


def polyline_segments(points: list[tuple[float, float]], closed: bool) -> tuple[list[tuple[tuple, tuple]], int]:
    """Return open-polyline segments and isolated open vertices.

    Closed polylines are already counted as profiles. Open polylines must be
    folded into the endpoint graph so a dangling contour cannot be hidden by a
    separate valid closed profile in the same DXF.
    """
    vertices = [_key(x, y) for x, y in points]
    if closed or not vertices:
        return [], 0
    if len(vertices) == 1:
        return [], 1
    return list(zip(vertices, vertices[1:])), 0


def collect_dxf_facts(path: Path) -> dict:
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise SystemExit(f"dxfcheck: {SETUP_HINT} ({exc})") from exc

    document = ezdxf.readfile(str(path))
    space = document.modelspace()
    counts: dict[str, int] = {}
    inherent_closed = 0
    segments: list[tuple[tuple, tuple]] = []
    isolated_open_vertices = 0
    xs: list[float] = []
    ys: list[float] = []

    for entity in space:
        name = entity.dxftype()
        counts[name] = counts.get(name, 0) + 1
        if name in _INHERENTLY_CLOSED:
            inherent_closed += 1
            if name == "CIRCLE":
                cx, cy, r = entity.dxf.center.x, entity.dxf.center.y, entity.dxf.radius
                xs.extend([cx - r, cx + r])
                ys.extend([cy - r, cy + r])
        elif name in {"LWPOLYLINE", "POLYLINE"}:
            closed = bool(getattr(entity, "closed", False) or entity.dxf.get("flags", 0) & 1)
            points = []
            try:
                points = [(point[0], point[1]) for point in entity.get_points("xy")]
            except (AttributeError, TypeError):
                pass

            if closed:
                inherent_closed += 1
            polyline_edges, isolated = polyline_segments(points, closed)
            segments.extend(polyline_edges)
            isolated_open_vertices += isolated
            for x, y in points:
                xs.append(x)
                ys.append(y)
        elif name == "SPLINE":
            if entity.closed:
                inherent_closed += 1
        elif name == "LINE":
            start = _key(entity.dxf.start.x, entity.dxf.start.y)
            end = _key(entity.dxf.end.x, entity.dxf.end.y)
            segments.append((start, end))
            xs.extend([entity.dxf.start.x, entity.dxf.end.x])
            ys.extend([entity.dxf.start.y, entity.dxf.end.y])
        elif name == "ARC":
            start, end = _arc_endpoints(entity)
            segments.append((start, end))
            xs.extend([start[0], end[0]])
            ys.extend([start[1], end[1]])

    segment_loops, open_endpoints = analyze_segments(segments)
    open_endpoints += isolated_open_vertices
    if xs and ys:
        min_x, min_y, max_x, max_y = min(xs), min(ys), max(xs), max(ys)
    else:
        min_x = min_y = max_x = max_y = 0.0

    return {
        "file": str(path),
        "entities": dict(sorted(counts.items())),
        "entity_total": sum(counts.values()),
        "closed_profiles": inherent_closed + segment_loops,
        "open_endpoints": open_endpoints,
        "extents_mm": {
            "min": [round(min_x, 4), round(min_y, 4)],
            "max": [round(max_x, 4), round(max_y, 4)],
            "size": [round(max_x - min_x, 4), round(max_y - min_y, 4)],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="DXF file to inspect")
    parser.add_argument("--require-closed", action="store_true",
                        help="fail unless every contour is closed (no open ends)")
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the facts document to this path")
    args = parser.parse_args(argv)

    if not args.target.is_file():
        raise SystemExit(f"dxfcheck: no such file: {args.target}")

    facts = collect_dxf_facts(args.target)
    failures = []
    if facts["entity_total"] == 0:
        failures.append("DXF contains no drawing entities")
    if args.require_closed:
        if facts["open_endpoints"]:
            failures.append(
                f"{facts['open_endpoints']} open segment endpoint(s) "
                "— a contour is not closed"
            )
        elif facts["closed_profiles"] == 0:
            failures.append("no closed profile (no cut loop)")
    facts["checks_passed"] = not failures
    facts["failures"] = failures

    document = json.dumps(facts, indent=2)
    print(document)
    if args.json is not None:
        args.json.write_text(document + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
