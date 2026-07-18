---
name: code-cad
description: "Build parametric 3D models in Python with build123d or CadQuery — headless B-rep CAD with STEP/STL/DXF export, mass-property verification, and render-and-inspect loops. The primary agentic CAD workflow: the model is code, so it can be reviewed, diffed, and regenerated."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [CAD, 3D, Parametric, build123d, CadQuery, OpenSCAD, STEP, Fabrication]
    related_skills: [dxf-drafting, sheet-metal, freecad, blender-mcp]
    homepage: https://build123d.readthedocs.io
dependencies: [build123d]
---

# Code-CAD (build123d / CadQuery)

Code-first CAD is the strongest agent fit for mechanical design: no GUI
socket, deterministic rebuilds, real B-rep solids (OCCT kernel — the same
geometry kernel class as commercial CAD), and exports fab shops accept
(STEP, STL, 3MF, DXF). Prefer this over driving a GUI CAD unless the user
already lives in one.

- **build123d** (preferred): modern Pythonic API, context-manager sketches,
  first-class 2D→3D workflow.
- **CadQuery**: mature fluent API; huge example base.
- **OpenSCAD**: only when the user asks for it — CSG only, no fillets on
  B-rep edges, weaker exports.

## When to Use

- "Design a bracket / enclosure / mount / adapter / jig"
- "Make me a 3D-printable ..." / "Export STEP for machining"
- Parametric families ("same flange, 4 sizes")
- Generating the 3D source that feeds the `sheet-metal` or `dxf-drafting` skills

## Install

```bash
pip install build123d          # pulls OCCT bindings; first install is large
# optional: pip install cadquery
```

## Workflow

1. **Pin the spec first.** Write the parameter table (dimensions, materials,
   clearances, fastener sizes) as named constants at the top of the script.
   Ask about load direction and mating parts before modeling, not after.
2. **Model in a script**, not a REPL — the file is the deliverable:

```python
from build123d import *

# --- parameters (mm) ---
L, W, T = 80, 40, 5          # plate
HOLE_D, HOLE_INSET = 5.5, 8  # M5 clearance

with BuildPart() as bracket:
    Box(L, W, T)
    with Locations((L/2 - HOLE_INSET, W/2 - HOLE_INSET, 0),
                   (-(L/2 - HOLE_INSET), W/2 - HOLE_INSET, 0)):
        Hole(HOLE_D / 2)
    fillet(bracket.edges().filter_by(Axis.Z), radius=4)

export_step(bracket.part, "bracket.step")
export_stl(bracket.part, "bracket.stl")
```

3. **Verify numerically — every time, before showing the user:**

```python
p = bracket.part
print("volume mm^3:", p.volume)
print("bbox:", p.bounding_box())
print("mass g (6061 Al):", p.volume * 2.7e-3)
assert abs(p.bounding_box().size.X - L) < 1e-6
```

Volume and bounding box catch most modeling errors (a boolean that
silently failed, a hole that missed the body) cheaper than any render.

4. **Verify visually** — render headless and inspect:

```bash
pip install trimesh pillow
python -c "
import trimesh
m = trimesh.load('bracket.stl')
png = m.scene().save_image(resolution=(800, 600))
open('bracket.png', 'wb').write(png)
"
```

Then `vision_analyze("bracket.png")` and check the geometry matches the
spec (hole count, fillets, proportions). Iterate: edit parameters →
rerun → re-render. This closed loop is the harness.

5. **Export for the target process**: STEP for CNC/quoting, STL/3MF for
   printing, `export_dxf`/`section` of a face for laser cutting (then
   continue in the `dxf-drafting` skill).

## Pitfalls

- Millimeters are the default unit everywhere; state units in every
  message to the user and never mix inch dims without converting.
- Booleans that produce zero-volume or non-manifold results don't always
  raise — the volume assertion is your tripwire.
- Fillet/chamfer order matters: filleting after holes can fail on
  tangent edges; apply large fillets before small features when errors
  occur.
- `pip install build123d` on a fresh box downloads large OCCT wheels —
  run it in the background terminal, not execute_code (300s cap).
- Don't hand-write STEP/STL — always go through the kernel's exporters.

## Verification

A part is done when: script reruns cleanly from scratch; volume/bbox
assertions pass; the rendered PNG matches the spec on visual check; and
the STEP re-imports without errors (`import_step("bracket.step")`).
