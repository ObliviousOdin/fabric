---
name: 3d-printing
description: "Prepare parts for FDM 3D printing — generate and validate STL/3MF (watertight mesh checks with trimesh), design-for-printing rules (overhangs, orientation, anisotropy, hole compensation), material selection, and headless slicing via PrusaSlicer/OrcaSlicer CLI for time and filament estimates."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [3D-Printing, STL, 3MF, FDM, Slicing, Mesh, DFM, Fabrication]
    related_skills: [code-cad, printed-joints]
dependencies: [trimesh]
---

# 3D Printing (FDM)

Take a model from the `code-cad` skill (or a user file) to a print-ready,
validated STL/3MF plus a slicer estimate. The deliverable is never just
"an STL" — it is a mesh that passes validation, oriented for the load
case, with print settings stated.

## When to Use

- "Make this 3D-printable" / "export an STL" / "print this"
- Checking or repairing a mesh the user sends
- Estimating print time/material before committing
- Choosing material, orientation, walls/infill for a load-bearing part

## Export from Code-CAD

```python
from build123d import *
export_stl(part, "part.stl")                        # mesh; unit-less format
export_step(part, "part.step")                      # keep the B-rep source too
```

Prefer **3MF** when the slicer will consume it directly (units and
metadata are embedded; STL has no units — state "millimeters" every time
you hand over an STL).

## Validate the Mesh — Every Time

```python
import trimesh
m = trimesh.load("part.stl")
assert m.is_watertight, "not watertight — slicer will produce garbage"
assert m.is_winding_consistent
assert m.volume > 0
print("volume mm^3:", m.volume, "| bbox:", m.extents, "| faces:", len(m.faces))
```

Quick repairs for user-supplied meshes: `trimesh.repair.fix_normals(m)`,
`fill_holes(m)`, then re-check. If repair fails, go back to the B-rep
source instead of patching a broken mesh.

Visual check: render to PNG (see `code-cad`) and `vision_analyze` it.

## Design Rules (FDM, 0.4 mm nozzle defaults)

- **Overhangs**: ≤ 45° from vertical prints clean; steeper needs support
  or a design change (chamfer instead of horizontal overhang under holes).
- **Bridges**: keep ≤ ~10 mm; teardrop or diamond horizontal holes.
- **Walls**: minimum rigid feature = 2 perimeters ≈ 0.8–1.2 mm; never
  design 0.5 mm walls.
- **Holes print undersize** by ~0.1–0.3 mm: for accurate bores, add 0.2 mm
  to modeled diameter or design to drill/ream after printing.
- **First layer flare (elephant's foot)**: chamfer 0.3–0.5 mm on
  bottom edges of anything that mates.
- **Anisotropy is the big one**: parts are 2–5× weaker across layers
  (Z) than along them. Orient so working loads run IN the layer plane;
  never put a snap-fit or thin pin loaded in bending across layers.
- **Orientation trade**: the face on the bed is the flattest and
  dimensionally truest; overhung faces are the roughest.

## Material Choice (quick table)

| Material | Use | Notes |
|----------|-----|-------|
| PLA | prototypes, rigid fixtures | stiffest, brittle, creeps warm (>50°C) |
| PETG | functional outdoor/mechanical | tougher, slight stringing, good default |
| ABS/ASA | heat + outdoor durable | needs enclosure; ASA for UV |
| TPU | seals, flexures, grips | flexible; slow printing |
| PA/Nylon (CF) | gears, high-load | strong, absorbs moisture — dry it |

## Slice Headlessly for Estimates

PrusaSlicer and OrcaSlicer both run from the CLI:

```bash
prusa-slicer --export-gcode --load printer_profile.ini -o part.gcode part.stl
# estimates are embedded as comments:
grep -E "estimated printing time|filament used" part.gcode
```

Report estimated time and grams with the deliverable. If no profile
exists, say the estimate is with generic 0.2 mm/20% settings — don't
present slicer defaults as tuned numbers. Run slicing in the terminal
tool (background for large models), not execute_code.

## Strength Settings Guidance

Perimeters beat infill: for a stronger part recommend 4–6 walls and
20–40% infill before 100% infill. State layer height trade (0.2 mm
default; 0.12 for fine detail; 0.28 for draft).

## Verification

Done means: mesh passes watertight/winding/volume checks; orientation
and its reasoning stated; slicer estimate produced (or explicitly
skipped); units stated; and for mating/moving parts, clearances from
the `printed-joints` skill applied and a test coupon suggested.
