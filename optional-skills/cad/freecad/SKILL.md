---
name: freecad
description: "Automate FreeCAD headlessly — parametric solids, STEP/DXF import-export, TechDraw drawings, and SheetMetal unfolding via freecadcmd Python scripts, no GUI required. Open-source parametric CAD with a full Python API."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [CAD, FreeCAD, Parametric, TechDraw, Drawings, SheetMetal, STEP, Open-Source]
    related_skills: [code-cad, sheet-metal, dxf-drafting]
    homepage: https://www.freecad.org
prerequisites:
  commands: [freecadcmd]
---

# FreeCAD (headless automation)

FreeCAD is open-source parametric CAD (OCCT kernel) with a complete
Python API and a true headless mode: `freecadcmd script.py` runs any
model/drawing/export job with no GUI. Reach for it over `code-cad` when
you need FreeCAD-specific capabilities: **TechDraw** (dimensioned 2D
drawing sheets from 3D models), the **SheetMetal workbench** (fold/unfold),
opening `.FCStd` files the user sends, or Assembly workbenches.

## Install

```bash
# Linux
sudo apt install freecad        # or the AppImage for current releases
# macOS: brew install --cask freecad
# The CLI is `freecadcmd` (sometimes FreeCADCmd); GUI-linked modules like
# TechDraw work headless in recent releases via Xvfb if they complain:
xvfb-run freecadcmd script.py
```

## Headless Modeling Script

```python
# freecadcmd make_plate.py
import FreeCAD as App
import Part

doc = App.newDocument("plate")
box = Part.makeBox(100, 60, 5)
hole = Part.makeCylinder(2.75, 5, App.Vector(15, 15, 0))
plate = box.cut(hole)
Part.export([doc.addObject("Part::Feature", "Plate").Shape], "plate.step") \
    if False else None
obj = doc.addObject("Part::Feature", "Plate"); obj.Shape = plate
doc.recompute()

Part.export([obj], "plate.step")
print("volume:", plate.Volume, "bbox:", plate.BoundBox)   # verify numerically
```

Run: `freecadcmd make_plate.py`. Always print `Volume`/`BoundBox` and
assert against the spec — same verification discipline as `code-cad`.

## Dimensioned Drawings (TechDraw)

The reason to use FreeCAD in an agent pipeline: turning a STEP into a
dimensioned drawing sheet programmatically.

```python
import FreeCAD as App, Import, TechDraw

doc = App.newDocument()
Import.insert("bracket.step", doc.Name)
page = doc.addObject("TechDraw::DrawPage", "Page")
tmpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
tmpl.Template = App.getResourceDir() + "Mod/TechDraw/Templates/A4_LandscapeTD.svg"
page.Template = tmpl
view = doc.addObject("TechDraw::DrawViewPart", "Front")
view.Source = doc.Objects[0]; view.Direction = (0, 0, 1); view.Scale = 1.0
page.addView(view)
doc.recompute()
TechDraw.writeDXFPage(page, "bracket_drawing.dxf")   # or writeSVGPage
```

Render the SVG/DXF to PNG (see `dxf-drafting`) and `vision_analyze` it
before delivering — check views, scale, and that dimensions attached.

## SheetMetal Unfold

Install the SheetMetal workbench once (Addon Manager, or clone
`https://github.com/shaise/FreeCAD_SheetMetal` into `~/.local/share/FreeCAD/Mod/`),
then unfold headlessly — used by the `sheet-metal` skill for flat patterns.

## Community MCP

Community FreeCAD MCP servers exist (GUI-embedded RPC, experimental).
For agent work prefer headless `freecadcmd` scripts: deterministic,
versionable, no desktop session required. If the user wants live GUI
interaction, the blender-mcp-style socket pattern applies — vet the
specific addon before recommending it.

## Pitfalls

- `doc.recompute()` after every feature change — stale shapes export silently.
- FreeCAD's Python is its OWN interpreter: `pip install` into your venv
  does nothing for freecadcmd scripts. Pure-geometry work that needs
  libraries belongs in `code-cad` instead.
- Unit is mm internally; `Part.makeBox(1, 1, 1)` is a 1 mm cube.
- Version-sensitive APIs (TechDraw especially): print
  `App.Version()` in the script and adapt; test the script before
  claiming the drawing is done.
