# Validation and Exports

## Validation sequence

Run after every regeneration, before showing results:

```bash
VENV_PY="${FABRIC_HOME:-$HOME/.fabric}/text-to-cad/venv/bin/python"
"$VENV_PY" scripts/cadcheck.py part.step --expect-bbox 40,20,30 --min-volume 3000
```

The JSON facts document reports: solid count, validity, volume (mm^3),
surface area, and the bounding box (size/min/max). Non-zero exit means a
requested check failed; the `failures` array says which.

What the checks do and do not prove:

- `is_valid` + positive volume — the kernel considers the shape a closed,
  well-formed solid. This catches open shells, self-intersections, and
  inverted booleans.
- `--expect-bbox` (orientation-insensitive, sorted extents) — the part is
  the size the brief promised. This catches unit errors and scale bugs, the
  two most common text-to-CAD failures.
- `--min-volume` — features actually cut/filled material (a bracket whose
  holes removed nothing, or a shell that removed everything, fails here).
- Nothing here proves *fit* against a mating part; assert mating gaps
  explicitly inside the generator when they matter.

In-generator assertions are the first gate — keep at minimum:

```python
assert part.is_valid, "geometry invalid"
assert part.volume > 0, "non-positive volume"
```

## Export matrix

STEP is always produced; add secondary formats per the request.

| Format | Use | build123d call |
|---|---|---|
| STEP (`.step`) | Primary. Lossless B-rep for CAD interchange and editing | `export_step(part, "p.step")` |
| STL (`.stl`) | Slicers / 3D printing (lossy mesh) | `export_stl(part, "p.stl")` |
| 3MF (`.3mf`) | Modern slicers, units + color preserved | `Mesher` → `mesher.add_shape(part); mesher.write("p.3mf")` |
| GLB (`.glb`) | Web/AR viewers | `export_gltf(part, "p.glb", binary=True)` |

Mesh quality: `export_stl(part, path, tolerance=0.001)` tightens facets for
small precise parts; the default is fine above ~20 mm. Never re-import a
mesh to continue modeling — go back to the generator.

## Snapshots

```bash
"$VENV_PY" scripts/cadsnap.py part.step -o part.png            # iso,front,top,right
"$VENV_PY" scripts/cadsnap.py part.stl -o part.png --views iso,bottom
```

Review the PNG against the brief: feature count (holes, ribs, bosses),
proportions, and obviously missing/extra material. The snapshot corroborates
the numeric checks; it never replaces them.

## Delivery block

End the final response with:

- artifact paths (generator + every export + snapshot)
- the cadcheck facts that were actually verified (not "validated" in the
  abstract — the numbers)
- assumptions carried over from the brief
- any check that was skipped, and why
