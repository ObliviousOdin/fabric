---
title: "Text To Cad — Text-to-CAD: prose or drawings to parametric STEP/STL/3MF/GLB parts (build123d)"
sidebar_label: "Text To Cad"
description: "Text-to-CAD: prose or drawings to parametric STEP/STL/3MF/GLB parts (build123d)"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Text To Cad

Text-to-CAD: prose or drawings to parametric STEP/STL/3MF/GLB parts (build123d).

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/creative/text-to-cad` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `cad`, `build123d`, `step`, `stl`, `3d-printing`, `parametric`, `hardware` |
| Related skills | [`hardware-manufacturing`](/user-guide/skills/bundled/venture-studio/venture-studio-hardware-manufacturing) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Text-to-CAD

## Overview

Turn a natural-language description (optionally with reference images or 2D
drawings) into a parametric CAD part. You write a small **build123d** Python
generator, run it in the skill's isolated environment, validate the geometry
numerically, and deliver **STEP as the primary artifact** with STL/3MF/GLB as
secondary exports plus PNG snapshots for visual review. The `.py` generator
*is* the model: it is source-controlled, parameter-editable, and regenerating
it reproduces every artifact byte-for-byte deterministically.

Code-first modeling (build123d on the OpenCASCADE kernel) is the default
because it is deterministic and reviewable. A cloud fallback
(`scripts/zoo_text_to_cad.py`, Zoo Text-to-CAD API) exists for organic or
underspecified shapes where parametric code is not converging — see
`references/providers.md` for the landscape and trade-offs.

## When to Use

- "Design/model/CAD me a &lt;part>" — brackets, enclosures, plates, adapters,
  spacers, mounts, gears, jigs, fixtures
- Producing STEP/STL/3MF/GLB files for machining, 3D printing, or import into
  Fusion 360 / FreeCAD / Onshape
- Modifying a part this skill generated earlier (edit the generator, rerun)
- Measuring or sanity-checking an existing STEP/STL file (`scripts/cadcheck.py`)

Don't use for: photorealistic renders or concept art (image generation),
animated 3D scenes (`manim-video`), architectural BIM, CAM toolpaths, or
manufacturing strategy beyond the part itself (`hardware-manufacturing`).

## Modeling Defaults

State any deviation explicitly in the brief; otherwise these hold:

| Convention | Default |
|---|---|
| Units | millimeters, everywhere |
| Base plane / up axis | XY plane, +Z up |
| Solids | closed, positive volume |
| Enclosure walls | 2.0–3.0 mm |
| M3 / M4 / M5 clearance holes | 3.4 / 4.5 / 5.5 mm |
| Cosmetic fillets | 1.0–3.0 mm where geometrically safe |

## Environment (isolated — never core dependencies)

CAD libraries are heavyweight and **must not** enter `pyproject.toml` or
`uv.lock`. The skill owns a private virtualenv:

```bash
bash scripts/setup.sh        # creates ${FABRIC_HOME:-~/.fabric}/text-to-cad/venv
```

`setup.sh` installs the pinned `requirements.txt` (build123d, numpy-stl,
matplotlib) with `uv` when available, else `pip`. It prints the venv's python
path on success — use that interpreter for every script below. Done when:
`setup.sh` exits 0 and prints the interpreter path.

## Pipeline

```
BRIEF --> SETUP --> MODEL --> CHECK --> EXPORT --> SNAPSHOT --> REVIEW
```

1. **BRIEF** — Extract every dimension, unit, datum, and validation target
   from the request into a short written brief (see `references/cad-brief.md`
   for prose/image/drawing extraction). Done when: every dimension has a
   number + unit, or a named assumption from the defaults table.
2. **SETUP** — Run `scripts/setup.sh`. Done when: it prints the venv python.
3. **MODEL** — Write `<part>.py` next to where the outputs belong, parameters
   as named constants at the top, exports sharing the generator's basename
   (`bracket.py` → `bracket.step`). Patterns, selectors, and error fixes:
   `references/build123d-modeling.md`. Never edit generated artifacts by
   hand; edit the generator. Done when: the generator runs clean under the
   venv python and writes its exports.
4. **CHECK** — `<venv-python> scripts/cadcheck.py <part>.step
   --expect-bbox X,Y,Z --min-volume V` prints JSON geometry facts (solids,
   volume, area, bounding box, validity) and exits non-zero on failure. Done
   when: facts match the brief's targets within tolerance.
5. **EXPORT** — STEP is mandatory; add STL/3MF/GLB per the request
   (`references/validation-and-exports.md`). Done when: every requested
   format exists on disk.
6. **SNAPSHOT** — `<venv-python> scripts/cadsnap.py <part>.step -o
   <part>.png` renders iso/front/top/right views. Review the PNG against the
   brief. Done when: the snapshot visually matches the brief (hole count,
   proportions, features present).
7. **REVIEW / ITERATE** — On any mismatch, change the smallest responsible
   parameter or feature in the generator and rerun steps 3–6. Done when: the
   final response lists artifact paths, the cadcheck facts that were actually
   verified, the snapshot, and every assumption made.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/setup.sh` | Preflight + create/refresh the isolated venv |
| `scripts/cadcheck.py` | Geometry facts + pass/fail validation for STEP/STL |
| `scripts/cadsnap.py` | Multi-view PNG snapshots from STEP/STL |
| `scripts/zoo_text_to_cad.py` | Cloud generation via the Zoo Text-to-CAD API |

## Cloud Fallback: Zoo Text-to-CAD

For organic shapes or when parametric code is not converging after ~3
iterations, offer the Zoo ML API (requires the `ZOO_API_TOKEN` environment
variable; the user creates a token at zoo.dev):

```bash
<venv-python> scripts/zoo_text_to_cad.py "a 40mm herringbone gear" --format step --out gear.step
```

Cloud output is a mesh-derived artifact, not a parameter-editable generator —
say so when delivering it, and still run CHECK and SNAPSHOT on the result.

## Common Pitfalls

1. **`Part.is_valid` is a property, not a method** in current build123d —
   `part.is_valid()` raises `TypeError: 'bool' object is not callable`.
2. **Editing exported STEP/STL by hand.** The generator is the source of
   truth; regenerate instead, or the next rerun silently reverts your edit.
3. **Installing CAD deps into the repo or system python.** They belong only
   in the skill venv; `uv.lock`/`pyproject.toml` changes are a shared-surface
   violation and will be rejected.
4. **Delivering STL without STEP.** Meshes are lossy; STEP is the primary,
   editable interchange artifact. Export both.
5. **Unit drift.** build123d is unitless — the mm convention only holds if
   every literal is mm. Convert inches/cm in the brief, not in the code.
6. **Trusting the picture.** A snapshot that "looks right" can hide a
   non-manifold solid or an off-by-2x scale. cadcheck facts are the gate;
   the snapshot is corroboration.
7. **Subtracting holes after fillets.** Order features so fillets come last;
   filleting edges consumed by a later boolean fails or produces slivers.

## Verification Checklist

- [ ] Brief written; every dimension numbered or explicitly assumed
- [ ] Generator `<part>.py` runs clean in the skill venv
- [ ] `cadcheck.py` passed: closed solid, positive volume, bbox within brief
- [ ] STEP exported; requested secondary formats (STL/3MF/GLB) exported
- [ ] Snapshot PNG rendered and reviewed against the brief
- [ ] Final response lists artifact paths, verified facts, and assumptions
- [ ] No changes to `pyproject.toml`, `uv.lock`, or the system python
