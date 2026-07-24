# Writing the CAD Brief

The brief is a short written contract between the request and the generator.
Every downstream step (model, check, snapshot review) verifies against it.

## Template

```
Part: <name>
Purpose: <one line>
Units: mm
Envelope: X x Y x Z mm (bounding box)
Features:
  - <feature>: <dimensions, positions, counts>
Datums: <base plane, symmetry, origin choice>
Material/process hint: <FDM print, CNC aluminum, laser-cut, unknown>
Validation targets: bbox <X,Y,Z> ±0.1; volume > <V> mm^3; <feature counts>
Assumptions: <every number you chose that the user did not give>
```

## Extracting from prose

- Convert all units to mm at brief time (1 in = 25.4 mm), never in code.
- Resolve relative language into numbers: "thin wall" → 2.0 mm, "small
  clearance" → 0.2–0.4 mm, "roughly palm-sized" → ~80–100 mm envelope. Record
  each choice under Assumptions.
- Screw callouts imply diameters: M3/M4/M5 clearance 3.4/4.5/5.5 mm;
  M3/M4/M5 tapping in plastic 2.5/3.3/4.2 mm.
- If a load-bearing dimension is genuinely unguessable (a mating part's bolt
  pattern, an exact bore), ask the user; a wrong assumption there makes the
  part scrap, not a draft.

## Extracting from images and drawings

- Dimensioned 2D drawings are authoritative: read every dimension into the
  brief and flag any the drawing omits.
- Undimensioned photos give proportions only. Anchor scale with one known
  object or ask for one reference measurement; state the anchor in
  Assumptions.
- Note the projection you interpreted (first-angle vs third-angle) when it
  changes the geometry.

## Completion criterion

The brief is done when a stranger could model the part from the brief alone
— no dimension left implicit, every guess labeled as an assumption, and
validation targets concrete enough for `cadcheck.py` flags
(`--expect-bbox`, `--min-volume`).
