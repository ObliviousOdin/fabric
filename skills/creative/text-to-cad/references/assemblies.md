# Assemblies

Two ways to assemble, depending on where the parts come from.

## In-generator (parts you model together)

Position each solid with an explicit `Location`/`Pos`/`Rot`, give it a
`label`, and merge into one `Compound`. Assert the mating relationship you
intend rather than trusting the picture:

```python
from build123d import Box, Compound, Pos, export_step

base = Box(40, 40, 4); base.label = "base"
post = Pos(0, 0, 4) * Box(8, 8, 20); post.label = "post"

# Intended contact: post sits on the base's top face at z = 4.
assert abs(post.bounding_box().min.Z - base.bounding_box().max.Z) < 1e-6

asm = Compound(children=[base, post])
export_step(asm, "asm.step")
```

Prefer explicit transforms over build123d joints for a first pass — they are
easier to reason about and diff. Reach for `RigidJoint`/`RevoluteJoint`
(`references/build123d-modeling.md`) only when you need articulation or
connector semantics.

## From separate STEP files (`scripts/assembly.py`)

When parts already exist as STEP (e.g. a generated bracket plus
`stdparts.py` hardware), place them by transform without re-modeling:

```bash
VENV_PY="${FABRIC_HOME:-$HOME/.fabric}/text-to-cad/venv/bin/python"
"$VENV_PY" scripts/assembly.py \
    --part bracket.step:0,0,0 \
    --part screw.step:10,0,4:rz=0 \
    --out mount.step
```

Each `--part` is `PATH:x,y,z` with an optional `:rz=DEG` (rotation about Z).
The script exports one combined STEP and checks every pair's bounding boxes:

- **exit 0, "no bounding-box overlap"** — clear.
- **exit 1, "overlap detected"** — boxes interpenetrate. Real interference,
  or an intended fit (screw in a bore, press-fit pin). For intended fits,
  re-run with `--allow-overlap` (reports but exits 0) — the bbox test is
  deliberately conservative and cannot tell a bore from a collision.

`--clearance MM` shrinks each box before comparison to ignore a modeled
interference that is within tolerance.

## Validating the result

An assembly STEP is still a STEP: `cadcheck.py asm.step` reports the solid
count (one per part) and combined bounds. `cadsnap.py asm.step` renders it
for review, and `cadviewer.py` (after a GLB export) gives an orbitable view
for handoff.
