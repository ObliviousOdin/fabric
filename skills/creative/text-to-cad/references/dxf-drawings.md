# DXF 2D Drawings

For flat, sheet-based fabrication — laser cutting, waterjet, CNC routing —
the deliverable is a 2D DXF of closed cut profiles, not a 3D solid.

## Authoring with build123d

Model the profile as a `BuildSketch` (or `BuildLine` for open paths) and
export with `ExportDXF`. A unit is required:

```python
from build123d import BuildSketch, Rectangle, Circle, Mode, Locations, Unit
from build123d.exporters import ExportDXF

with BuildSketch() as plate:
    Rectangle(80, 40)                      # outer cut
    with Locations((-30, 0), (30, 0)):
        Circle(2.5, mode=Mode.SUBTRACT)    # mounting holes

exporter = ExportDXF(unit=Unit.MM)
exporter.add_shape(plate.sketch)
exporter.write("plate.dxf")
```

Note: `ExportDXF` writes a rectangle as four `LINE` entities and holes as
`CIRCLE` entities — it does not emit a single closed `LWPOLYLINE`. That is
normal and still a closed cut; `dxfcheck.py` judges closure structurally.

To cut a flat pattern from a 3D part, section it first: take the face you
want (`part.faces().sort_by(Axis.Z)[-1]`), make a sketch from it, and export
that.

## Validating (`scripts/dxfcheck.py`)

```bash
VENV_PY="${FABRIC_HOME:-$HOME/.fabric}/text-to-cad/venv/bin/python"
"$VENV_PY" scripts/dxfcheck.py plate.dxf --require-closed
```

The JSON facts report entity counts by type, drawing extents (mm),
`closed_profiles`, and `open_endpoints`. Closure is structural:

- `CIRCLE`/`ELLIPSE`, closed `LWPOLYLINE`/`POLYLINE`, and closed `SPLINE`
  count as closed profiles directly.
- Loose `LINE`/`ARC` segments are closed only when every shared endpoint has
  even degree — any odd endpoint is a dangling open contour.

`--require-closed` fails (exit 1) on any open endpoint or when there is no
closed profile at all. A cutter will happily interpret an open contour as an
incomplete path, so gate on this before sending a job out.

## Checklist

- [ ] Units set explicitly on `ExportDXF` (mm)
- [ ] Every cut is a closed profile — `dxfcheck --require-closed` passes
- [ ] Extents match the intended sheet size
- [ ] Holes are `SUBTRACT`ed from the profile, not overlapping outlines
