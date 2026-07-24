# Print Prep (FDM)

`scripts/printcheck.py` catches the common "looks fine, unprintable" failures
from an STL, without needing a slicer installed.

```bash
VENV_PY="${FABRIC_HOME:-$HOME/.fabric}/text-to-cad/venv/bin/python"
"$VENV_PY" scripts/printcheck.py part.stl --bed 220,220,250 --overhang-deg 45
```

## What it reports

| Field | Meaning |
|---|---|
| `bbox_size_mm` | Part extents |
| `fits_bed` | Fits the bed, allowing a 90° footprint rotation. **Gates exit code** |
| `thinnest_dim_mm` | Smallest overall dimension — a thin-wall proxy |
| `overhang_area_fraction` | Fraction of surface area steeper than `--overhang-deg` from vertical (support likely) |
| `support_likely` | True when overhang area exceeds 5% |
| `warnings` | Human-readable overhang / thin-wall notes |

Exit is non-zero only when the part does not fit the bed. Overhang and
thin-wall are **warnings**, not failures — they depend on print orientation,
which the check cannot choose for the user.

## Interpreting it

- **Doesn't fit** → scale down, split into printable parts, or confirm a
  larger printer. Re-check after.
- **High overhang** → the part likely needs supports as oriented. Options:
  reorient (re-export the STL rotated), add chamfers/fillets under 45° to
  self-support, or accept supports. The default bed is common (220×220×250,
  Ender-class); pass `--bed` for the real machine.
- **Thin dimension below the nozzle-driven minimum** (default warns under
  1.0 mm; set `--min-wall-mm` to ~2× line width) → thicken the wall or it
  will print gappy or not at all.

## Where it sits in the pipeline

Run print prep after EXPORT, on the STL, once the STEP has already passed
`cadcheck.py`. It answers "will this print as oriented?", a separate question
from "is the geometry valid?". For actual G-code, hand the STL to the user's
slicer (PrusaSlicer, Cura, OrcaSlicer) — this skill validates readiness, it
does not slice.
