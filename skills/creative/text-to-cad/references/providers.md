# Text-to-CAD Provider Landscape

Why this skill is code-first, and when to reach for something else.

## Backends compared

| Approach | Output | Editable? | Deterministic? | Needs |
|---|---|---|---|---|
| **build123d** (this skill's default) | B-rep STEP + meshes | Yes — parameter edits in the generator | Yes | Skill venv (OpenCASCADE wheels) |
| CadQuery | B-rep STEP + meshes | Yes | Yes | Same kernel; fluent-API style |
| OpenSCAD | CSG meshes (STL/AMF; no STEP) | Yes (scad source) | Yes | `openscad` binary |
| Zoo Text-to-CAD API (`scripts/zoo_text_to_cad.py`) | STEP/GLTF from an ML model | No — regenerate from a new prompt | No | `ZOO_API_TOKEN`, network |

Decision rules:

- Dimensioned, mechanical, mating-critical → **build123d** (default).
- User hands you existing CadQuery/OpenSCAD source → stay in that tool's
  language rather than porting; both can be driven from the same venv or a
  system `openscad`.
- Organic/sculptural shape, or 3+ parametric iterations failed to converge →
  offer the **Zoo cloud fallback**, with the caveats that it needs a token,
  sends the prompt off-machine, and returns a non-parametric artifact.
- STEP is required → OpenSCAD is out (mesh-only kernel).

## Ecosystem notes

Projects worth knowing when a user asks for more than this skill covers
(current as of 2026-07; treat as pointers, not endorsements):

- `earthtojake/text-to-cad` (MIT) — the agent-skills collection this skill's
  workflow shape is adapted from: STEP-first build123d generation plus
  sibling skills for DXF, URDF/SRDF/SDF robot formats, G-code slicing,
  printer control, and a browser CAD viewer. If a user wants the full
  robotics/fabrication toolchain rather than part generation, point them
  there.
- `agentcad` — an MCP server + CLI wrapping build123d/CadQuery script
  execution, previews, and version diffs; an alternative integration path if
  a user prefers connecting an external MCP server over an in-repo skill.
- Zoo (formerly KittyCAD) — the hosted ML text-to-CAD API used by
  `scripts/zoo_text_to_cad.py`, plus KCL, their own CAD language.
- FreeCAD — headless Python scripting for STEP/STL when a full GUI CAD
  package is already installed; heavier than the venv route for generation.

## Attribution

The pipeline shape (brief → generate → validate → snapshot, STEP-first) is
adapted from the MIT-licensed `earthtojake/text-to-cad` project. All code in
this skill is original to Fabric.
