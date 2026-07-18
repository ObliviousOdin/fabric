---
name: fusion360
description: "Automate Autodesk Fusion (Fusion 360) via its add-in Python API — scripted modeling, parameter tables, STEP/STL/DXF export, and drawing generation. Desktop-only (Windows/macOS, no headless mode); know when to use it vs. code-CAD."
version: 1.0.0
author: community
license: MIT
platforms: [macos, windows]
metadata:
  fabric:
    tags: [CAD, Fusion-360, Autodesk, Parametric, CAM, Scripting]
    related_skills: [code-cad, freecad, sheet-metal]
    homepage: https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-A92A4B10-3781-4925-94C6-47DA85A4F65A
---

# Autodesk Fusion (Fusion 360)

Fusion's automation surface is the **add-in API**: Python (or C++)
scripts that run INSIDE the desktop application (`adsk.core` /
`adsk.fusion` modules). Understand the constraints before promising a
workflow:

- Scripts run in Fusion's embedded Python, inside a running GUI session.
- **No headless mode, no Linux.** Windows/macOS desktop only.
- No official MCP server; community Fusion MCP bridges exist but are
  young — vet any specific one before trusting it with a user's designs.

**Rule of thumb**: if the job is "generate/iterate parts programmatically",
prefer the `code-cad` or `freecad` skills (headless, deterministic). Use
Fusion automation when the user already works in Fusion — existing
designs, CAM setups, Fusion-native sheet metal — or needs its CAM.

## When to Use

- "Script this in my Fusion design" / batch-edit user parameters
- Exporting a user's Fusion designs (STEP/STL/DXF) programmatically
- Driving a parameter table to regenerate a family of parts
- Fusion sheet-metal flat patterns and CAM post-processing

## Script Deployment

Scripts live in Fusion's Scripts folder; the user runs them from
**UTILITIES → ADD-INS → Scripts and Add-Ins** (Shift+S):

- Windows: `%APPDATA%\Autodesk\Autodesk Fusion 360\API\Scripts\`
- macOS: `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/Scripts/`

Each script is a folder with a `.py` + `.manifest`. Write the file there,
then ask the user to run it in Fusion and paste back any message-box
output — the agent cannot execute inside Fusion itself.

## Script Skeleton

```python
import adsk.core, adsk.fusion, traceback

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent

        # change a user parameter (drives the parametric model)
        p = design.userParameters.itemByName("plate_length")
        p.expression = "120 mm"

        # export STEP
        em = design.exportManager
        opts = em.createSTEPExportOptions("/tmp/part.step")
        em.execute(opts)
        ui.messageBox("Exported /tmp/part.step")
    except Exception:
        if ui: ui.messageBox(traceback.format_exc())
```

Key API entry points: `design.userParameters` (parameter tables),
`rootComponent.sketches` + `extrudeFeatures` (modeling),
`design.exportManager` (STEP/STL/IGES/3MF/FBX),
`sketch.saveAsDXF` (2D), sheet-metal via `Component.flatPattern`
(`FlatPatternExportOptions` exports the flat DXF).

## Parameter-Driven Families

The highest-leverage pattern with a human in the loop: build the model
once with named user parameters, then generate scripts that set parameter
values and export — one run per variant. Keep the dimension math (bend
allowances etc.) in YOUR script, not in fragile sketch expressions.

## Pitfalls

- The API runs on Fusion's UI thread — long loops freeze the app; batch
  exports should yield with `adsk.doEvents()`.
- Personal-use licenses restrict some export formats (e.g. STEP export
  availability has shifted between license tiers — verify with the
  user's tier before promising a format).
- Cloud-stored designs: `app.activeProduct` only sees the OPEN document;
  batch jobs across many designs need the Data API or manual opens.
- Fusion units are cm internally in the API (`adsk.core.ValueInput`
  expressions with explicit units avoid 10× errors — always write
  `"120 mm"`, never bare numbers).
