# build123d Modeling Patterns

Tested against build123d 0.11.1 (the pin in `requirements.txt`).

## Generator skeleton

Parameters as named constants at the top; exports share the file's basename.

```python
"""bracket.py — parametric L-bracket."""
from build123d import (
    Axis, BuildPart, BuildSketch, Circle, Locations, Mode, Plane,
    Rectangle, extrude, fillet, export_step, export_stl,
)

# Parameters (mm)
LEG_A = 40.0
LEG_B = 30.0
WIDTH = 20.0
THICKNESS = 3.0
HOLE_DIA = 4.5   # M4 clearance
FILLET_R = 2.0

with BuildPart() as bracket:
    with BuildSketch(Plane.XY):
        Rectangle(LEG_A, WIDTH)
    extrude(amount=THICKNESS)
    with BuildSketch(Plane.XZ.offset(-WIDTH / 2)):
        with Locations((-LEG_A / 2 + THICKNESS / 2, LEG_B / 2)):
            Rectangle(THICKNESS, LEG_B)
    extrude(amount=WIDTH)
    with BuildSketch(Plane.XY.offset(THICKNESS)):
        with Locations((LEG_A / 4, 0)):
            Circle(HOLE_DIA / 2)
    extrude(amount=-THICKNESS, mode=Mode.SUBTRACT)
    fillet(bracket.edges().filter_by(Axis.Y).group_by(Axis.X)[0], FILLET_R)

part = bracket.part
assert part.is_valid, "geometry invalid"     # property, NOT a method call
assert part.volume > 0, "non-positive volume"
print(f"volume={part.volume:.1f} mm^3 bbox={part.bounding_box().size}")

export_step(part, "bracket.step")
export_stl(part, "bracket.stl")
```

## Core vocabulary

| Concept | API |
|---|---|
| Part context | `with BuildPart() as p:` — result at `p.part` |
| 2D profile | `with BuildSketch(Plane.XY):` then `Rectangle`, `Circle`, `Polygon`, `SlotOverall`, `RegularPolygon` |
| Sketch → solid | `extrude(amount=…)`, `revolve(axis=…)`, `loft()`, `sweep(path=…)` |
| Boolean subtract | `mode=Mode.SUBTRACT` on any creating operation |
| Primitives | `Box`, `Cylinder`, `Sphere`, `Cone`, `Torus`, `Hole`, `CounterBoreHole`, `CounterSinkHole` |
| Repetition | `with Locations((x, y), …):`, `with GridLocations(dx, dy, nx, ny):`, `with PolarLocations(radius, count):` |
| Edge/face selection | `p.edges()`, `p.faces()` with `.filter_by(Axis.Z)`, `.filter_by(GeomType.CIRCLE)`, `.group_by(Axis.Z)[-1]`, `.sort_by(Axis.Z)[-1]` |
| Finishing | `fillet(edges, radius)`, `chamfer(edges, length)` |
| Placement | `Plane.XY.offset(z)`, `Plane.XZ`, `Location((x, y, z))`, `Rot(0, 0, 45)` |
| Measure | `part.volume`, `part.area`, `part.bounding_box().size`, `part.is_valid` |

Algebra mode is equivalent when a context manager feels heavy:
`part = Box(10, 10, 5) - Cylinder(2, 5)` then `export_step(part, …)`.

## Selector recipes

- Top face: `p.faces().sort_by(Axis.Z)[-1]`
- All vertical edges: `p.edges().filter_by(Axis.Z)`
- Outer edges of the top face: `p.faces().sort_by(Axis.Z)[-1].edges()`
- Hole edges only: `p.edges().filter_by(GeomType.CIRCLE)`
- Leftmost group of Y-parallel edges: `p.edges().filter_by(Axis.Y).group_by(Axis.X)[0]`

## Error → fix table

| Symptom | Cause / fix |
|---|---|
| `TypeError: 'bool' object is not callable` | `part.is_valid()` — it is a property; drop the parentheses |
| Fillet raises `StdFail_NotDone` | Radius too large for the edge, or the edge disappears in a later boolean. Shrink the radius; order fillets last |
| Subtract leaves no hole | Cutting sketch not on the face being cut — check the plane offset and extrude direction (`amount=-…` cuts downward) |
| Zero or negative volume | Open shell or self-intersecting profile; check sketches are closed and non-overlapping |
| Empty `edges()` selection | Filter ran before the feature existed; select after the operation that creates the edges |
| Export writes an empty file | Passed the builder, not the part — export `p.part`, not `p` |

## Assemblies

Position parts with explicit `Location` transforms and combine with
`Compound(children=[…])`; export the compound to a single STEP. Keep each
child a closed solid and give it a `label` so downstream tools can address
it. Verify mating with bounding-box arithmetic in the generator (assert the
gap or interference you intend), not by eye.
