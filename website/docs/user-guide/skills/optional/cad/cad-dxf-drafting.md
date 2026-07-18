---
title: "Dxf Drafting"
sidebar_label: "Dxf Drafting"
description: "Create and edit DXF files in Python with ezdxf — 2D profiles for laser/waterjet/plasma cutting, dimensioned drawings, layers and blocks, R12 export for fab s..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Dxf Drafting

Create and edit DXF files in Python with ezdxf — 2D profiles for laser/waterjet/plasma cutting, dimensioned drawings, layers and blocks, R12 export for fab shops, and render-to-image verification.

## Skill metadata

| | |
|---|---|
| Source | Optional — install with `fabric skills install official/cad/dxf-drafting` |
| Path | `optional-skills/cad/dxf-drafting` |
| Version | `1.0.0` |
| Author | community |
| License | MIT |
| Dependencies | `ezdxf` |
| Platforms | linux, macos, windows |
| Tags | `DXF`, `CAD`, `Drafting`, `Laser-Cutting`, `Waterjet`, `2D`, `ezdxf`, `Fabrication` |
| Related skills | [`code-cad`](/user-guide/skills/optional/cad/cad-code-cad), [`sheet-metal`](/user-guide/skills/optional/cad/cad-sheet-metal) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# DXF Drafting (ezdxf)

[ezdxf](https://ezdxf.readthedocs.io) creates, reads, and modifies DXF
files without any CAD application. Use it for cut profiles (laser,
waterjet, plasma, CNC router), dimensioned 2D drawings, and inspecting
DXFs the user sends you.

## When to Use

- "Sketch a DXF" / "make a cut file" / "laser-cut template"
- Flat patterns handed off from the `sheet-metal` skill
- Reading a customer DXF: layers, entities, dimensions, bounding box
- Batch edits: rescale, re-layer, merge profiles, nest simple layouts

## Install

```bash
pip install ezdxf          # pure Python; matplotlib optional for rendering
```

## Creating a Cut Profile

```python
import ezdxf

doc = ezdxf.new("R2010", setup=True)   # setup=True: default dimstyles
doc.units = ezdxf.units.MM             # ALWAYS set units explicitly
msp = doc.modelspace()

doc.layers.add("CUT", color=1)         # red = cut (common shop convention)
doc.layers.add("ENGRAVE", color=5)

# outer profile as a closed LWPOLYLINE (shops want closed contours)
msp.add_lwpolyline(
    [(0, 0), (100, 0), (100, 60), (0, 60)],
    close=True, dxfattribs={"layer": "CUT"},
)
msp.add_circle((15, 15), radius=2.75, dxfattribs={"layer": "CUT"})  # M5 clearance

doc.saveas("plate.dxf")
```

## Verify Before Delivering — Always

Round-trip and check geometry numerically:

```python
import ezdxf
from ezdxf import bbox

doc = ezdxf.readfile("plate.dxf")
msp = doc.modelspace()
extents = bbox.extents(msp)
print("entities:", len(msp), "bbox:", extents.extmin, extents.extmax)
# closed contours check
for e in msp.query("LWPOLYLINE"):
    assert e.closed, f"open contour on layer {e.dxf.layer}"
```

Render a preview and inspect it with vision:

```python
import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt

doc = ezdxf.readfile("plate.dxf")
fig = plt.figure(); ax = fig.add_axes([0, 0, 1, 1])
Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(doc.modelspace())
fig.savefig("plate_preview.png", dpi=150)
```

Then `vision_analyze("plate_preview.png")` against the spec (hole count
and positions, outline shape, no stray entities).

## Shop-Compatibility Rules

- Many older CAM packages want **DXF R12**: `doc.saveas` after
  `ezdxf.new("R12")`, or convert with `ezdxf.addons.r12writer` for pure
  geometry. When a shop rejects a file, R12 with everything exploded to
  LWPOLYLINE/LINE/ARC is the safe fallback.
- One part per file unless the shop asks for nested sheets.
- Kerf compensation is the shop's job by default — draw TRUE dimensions
  and say so; only offset contours if explicitly asked (then state the
  kerf value used).
- Text for engraving: use simple fonts and put it on its own layer.
  Convert to geometry only if the shop can't take TEXT entities.
- SPLINEs are a common rejection cause — approximate with arcs/polylines
  (`ezdxf.path` tools: `path.to_lwpolylines`) when targeting plasma/older CAM.

## Pitfalls

- DXF has no enforced units — a file that "looks right" in mm imports as
  inches somewhere else. Set `doc.units` AND tell the user what units the
  file is in, every time.
- `bbox.extents` on an empty modelspace returns an invalid box — check
  entity count first.
- Dimensions added with `add_linear_dim` need `.render()` called on the
  dimension object or they won't display in most viewers.
