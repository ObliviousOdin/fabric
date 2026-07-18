---
name: sheet-metal
description: "Design sheet-metal parts for fabrication — bend allowance and K-factor math, flat-pattern development, DXF flats for laser cutting, FreeCAD SheetMetal unfolding, and design rules for bend-and-cut services (min flange, hole-to-bend distance, reliefs)."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [Sheet-Metal, Fabrication, Bending, Flat-Pattern, K-Factor, DXF, Manufacturing]
    related_skills: [dxf-drafting, code-cad, freecad, parts-sourcing]
---

# Sheet Metal Fabrication

Design bent sheet-metal parts and produce the flat patterns fab services
cut and bend from. The deliverables are: a 3D model (STEP), a flat-pattern
DXF, and a bend table (line positions, directions, angles, radii).

## When to Use

- "Design a bracket / chassis / enclosure to be bent from sheet"
- "Unfold this part" / "make the flat pattern"
- Checking a design against fab-service rules before quoting
- Bend allowance / flat length calculations

## The Math (do this in Python, show your work)

Flat length = sum of flange outer lengths − bend deductions, or sum of
neutral-axis arc lengths. Use bend allowance (BA):

```python
import math

def bend_allowance(angle_deg, inner_radius, thickness, k_factor=0.44):
    """Neutral-axis arc length consumed by one bend."""
    return math.radians(angle_deg) * (inner_radius + k_factor * thickness)

def flat_length(flange_lengths, bends):
    """flange_lengths: outside dims; bends: list of (angle, r_inner, t, k)."""
    setback = sum(
        2 * (r + t) * math.tan(math.radians(a) / 2) - bend_allowance(a, r, t, k)
        for a, r, t, k in bends
    )
    return sum(flange_lengths) - setback
```

K-factor rules of thumb (verify with the shop — theirs wins):
- Air bending steel/aluminum: 0.40–0.45 (0.44 default)
- Bottoming: ~0.42; coining: ~0.38
- Larger R/t → K approaches 0.5

Inner bend radius: default to R = material thickness unless the shop
specifies tooling radii. Aluminum 6061-T6 cracks on tight bends — use
R ≥ 1.5t (5052 bends happily at 1t; prefer 5052 for bent parts).

## Design Rules (check EVERY part against these)

| Rule | Minimum |
|------|---------|
| Flange length | 4 × t (below this the brake can't grip) |
| Hole/slot to bend line | 2.5 × t + R (else holes deform) |
| Bend relief width | ≥ t (depth ≥ R + t) at flange-edge bends |
| Corner gap between meeting flanges | ~2 × t |
| Slot-and-tab | tab ≥ 2 × t wide |

State every violation to the user with the fix — moving a hole, adding a
relief, lengthening a flange.

## Flat Pattern via FreeCAD (headless, scriptable)

FreeCAD's SheetMetal workbench unfolds parts programmatically — see the
`freecad` skill for setup. Sketch:

```python
# freecadcmd unfold_script.py
import FreeCAD, Part, importDXF
doc = FreeCAD.openDocument("bracket.FCStd")
# ... SheetMetal workbench Unfold on the base face ...
importDXF.export([doc.Unfold], "bracket_flat.dxf")
```

For parts you modeled with the `code-cad` skill, an alternative that
avoids FreeCAD: model the part AS its flat pattern in build123d (compute
flat length with the math above), export the face to DXF directly, and
provide the bend table alongside.

## Deliverables Checklist

1. `part.step` — the bent 3D model (for review/quoting)
2. `part_flat.dxf` — flat pattern, closed contours, bend lines on a
   separate `BEND` layer (dashed), units stated
3. Bend table: bend #, direction (up/down), angle, inner radius, bend
   line position from datum edge
4. Material + thickness + finish callout (e.g. "5052-H32, 2.0 mm, deburred")

Verify the flat with the `dxf-drafting` skill's round-trip checks, and
sanity-check flat dimensions: flat length must be LESS than the sum of
outside flange dims (if not, your deduction sign is wrong).

## Fab Services

Upload STEP (they unfold themselves) or flat DXF + bend table:
- **meviy** (Misumi): STEP upload, instant sheet-metal quotes — pairs
  with the `parts-sourcing` skill
- SendCutSend / OSH Cut / Fabworks etc.: publish per-material minimum
  flange, bend radius, and hole-size tables — fetch the current rules for
  the user's chosen material with web tools before finalizing, and use
  the service's numbers over the defaults above.

## Pitfalls

- Don't scale flat patterns for kerf — shops compensate in CAM.
- Bend lines must be geometry on their own layer, never burned into the
  cut profile.
- Hems and jogs have their own allowances — quote shop tables rather than
  the generic BA formula.
- Countersinks near bends deform: keep ≥ 3t + R from the bend line.
