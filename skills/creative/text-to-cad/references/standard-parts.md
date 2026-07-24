# Standard Parts (Fasteners)

`scripts/stdparts.py` emits off-the-shelf ISO metric hardware as STEP solids
so generators mate to real dimensions instead of guessed placeholders.
Threads are represented as plain cylinders/bores — the metric callout, not a
modeled helix, is the source of truth (printable, kernel-cheap, and correct
for clearance/interference reasoning).

## CLI

```bash
VENV_PY="${FABRIC_HOME:-$HOME/.fabric}/text-to-cad/venv/bin/python"
"$VENV_PY" scripts/stdparts.py list                                  # sizes
"$VENV_PY" scripts/stdparts.py screw  --size M4 --length 20 --out screw.step
"$VENV_PY" scripts/stdparts.py nut    --size M4 --out nut.step
"$VENV_PY" scripts/stdparts.py washer --size M4 --out washer.step
```

Sizes M2–M8. Specs follow DIN 912 (socket-head cap screw), DIN 934 (hex
nut), DIN 125 (flat washer). Validate any emitted part with `cadcheck.py`
like any other STEP.

## Import path

The builders are importable, so a generator can drop hardware straight into
an assembly:

```python
import sys
sys.path.insert(0, "scripts")
from stdparts import make_screw, make_nut, SCREW_SPECS

screw = make_screw("M4", 16)     # a build123d solid
head_dia, head_h, shaft_dia = SCREW_SPECS["M4"]
```

## Sizing rules of thumb

- Clearance hole for a screw = the shaft diameter from the callout plus the
  clearance from `cad-brief.md` (M3/M4/M5 → 3.4/4.5/5.5 mm).
- Counterbore for a socket head = head diameter + ~0.5 mm, depth = head
  height so the screw sits flush.
- Leave the head-height plus washer thickness of stack clearance above a
  tapped boss.

## Off-the-shelf beyond fasteners

For bearings, motors, extrusion, and connectors, prefer looking up the real
part's datasheet dimensions and modeling a simple envelope solid at those
dimensions (labelled) rather than approximating — the envelope is what
matters for fit. `references/providers.md` notes upstream catalogs
(step.parts) if a broader library is needed.
