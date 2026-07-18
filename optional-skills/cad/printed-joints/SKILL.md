---
name: printed-joints
description: "Design working joints and mechanisms for FDM printing — pivots and pin hinges, sliders and dovetails, snap-fits with cantilever strain math, print-in-place clearances, printed threads and heat-set inserts, ball joints and detents. Clearance tables and parametric build123d examples."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [3D-Printing, Joints, Hinges, Sliders, Snap-Fit, Mechanisms, Print-In-Place, Tolerances]
    related_skills: [3d-printing, code-cad]
---

# Printed Joints & Mechanisms

Numbers-first design of moving/mating features for FDM. Every joint here
follows the same loop: pick clearance from the table → model
parametrically (`code-cad`) → **print a test coupon of just the joint** →
adjust one variable → commit to the full part.

## Clearance Table (per side / radial, tuned 0.4 mm nozzle)

| Fit | Clearance | Use |
|-----|-----------|-----|
| Press / interference | 0.00–0.10 mm | pins glued/pressed, bearing seats |
| Snug (assembled, no play) | 0.15 mm | lids, locating bosses |
| Running (moves freely after assembly) | 0.20–0.30 mm | pivots, axles, drawer slides |
| Print-in-place (fused-risk gap) | 0.40–0.50 mm | hinges/links printed assembled |

These are starting points — printers vary; the coupon is the truth.
Vertical (Z) clearances need ~1 layer height extra vs XY.

## Pivots & Hinges

**Pin hinge (assembled)** — strongest, simplest:
- Bore = pin Ø + 2×0.25 mm running clearance; knuckle wall ≥ 2 mm.
- Best pins aren't printed: use a machine screw, dowel, or a straight
  length of 1.75 mm filament melted over at the ends (the filament-pin
  trick) for small hinges.
- If the pin IS printed: print it horizontally (bending load along
  layers), Ø ≥ 5 mm, and expect to sand it.

**Print-in-place hinge**:
- Radial gap 0.45 mm, axial gap 0.5 mm between knuckles.
- Kill elephant's foot where the moving surface meets the bed: 0.5 mm
  chamfer on all bottom edges of both halves, or float the joint one
  layer above the bed on a sacrificial raft ring.
- Free the joint immediately after printing, while warm — first flex
  breaks the micro-welds.

```python
# build123d: parametric knuckle pair (sketch of the core geometry)
PIN_D, CLR, KN_W, KN_GAP = 5.0, 0.45, 8.0, 0.5
bore = PIN_D + 2 * CLR
# leaf A knuckles at y = 0, 2*(KN_W+KN_GAP); leaf B offset by KN_W+KN_GAP
# ...Cylinder(bore/2) holes through leaf-B knuckles, pin fused to leaf A
```

## Sliders & Rails

- **Dovetail**: 45–60° flank angle, 0.25 mm clearance per side, length ≥
  2× width for smooth travel. Print the groove standing up (flanks in the
  layer plane) — printed-down dovetails have rough top surfaces.
- **T-slot / rectangular rail**: easier than dovetail to print cleanly;
  0.25 mm per side, add a lead-in chamfer on the entry end.
- Long slides bind from mid-print warp: add grease (PTFE-safe), keep
  engagement ≥ 15 mm, and prefer 2 short contact pads over one long face
  (less surface = less stiction).
- Detent for position holding: a printed bump + a slot that flexes,
  0.3–0.5 mm interference, oriented to flex in the layer plane.

## Snap-Fits (cantilever) — do the math

Maximum safe deflection of a straight cantilever snap arm:

```python
def max_deflection(strain, L, t):
    """strain: material allowable; L: arm length; t: thickness (bend dir)."""
    return strain * L**2 / (1.5 * t)
```

Allowable strain (FDM, conservative): PLA 1.5–2 %, PETG 3–4 %,
ABS/ASA 4–5 %, PA 6–8 %, TPU effectively unlimited.

Rules:
- The arm MUST flex in the layer plane (print the clip lying down or
  design the flex direction horizontal). A snap loaded across layers
  snaps — once.
- Taper the arm (t at root → 0.6t at tip) for ~40 % more travel at the
  same strain; add a root fillet ≥ t/2.
- Engagement ramp 30–45° in, 80–90° out for permanent clips; 45° out
  for serviceable ones.
- PLA snap-fits fatigue in tens of cycles — for repeated use switch
  material (PETG+) or switch joint (screw boss, quarter-turn).

## Threads & Fasteners

- **Heat-set inserts** are the default for anything serviced more than
  twice: boss wall ≥ 2 mm around insert, hole per the insert maker's
  spec, install with a soldering iron at low temp; pull-out beats any
  printed thread.
- **Printed threads** work at M8+ (or modeled trapezoidal/ACME profiles
  at any size): model with 0.2–0.3 mm radial clearance, 2+ perimeters,
  print axis vertical.
- **Captive nut pockets**: hex pocket = nut across-flats + 0.2 mm, slot
  from the side so gravity/bridging works; stops rotation and beats
  inserts for high torque.
- Below M8, don't thread plastic: use inserts, captive nuts, or
  self-tapping screws into a 0.85× core-diameter hole.

## Ball Joints & Other

- Ball-and-socket: socket wraps 200–220° of the ball, 0.25 mm clearance,
  slit the socket rim (2–3 relief cuts) so it snaps over; print ball
  stem-down. Holds pose; not load-bearing.
- Living hinges: PLA lasts single-digit cycles — only TPU (or PP if the
  printer handles it) makes real living hinges; otherwise use a pin
  hinge. Say this instead of printing a PLA living hinge that will fail.
- Gears/leadscrews: printable and beyond this skill's scope — flag
  backlash ≈ clearance and suggest PA/PETG over PLA for wear.

## Test Coupons (always offer)

Before a full print, generate a coupon: for a pivot, a 15 mm tall
knuckle pair; for a slider, 20 mm of rail + shoe; for clearances, a pin
plate with bores at 0.15/0.20/0.25/0.30/0.40. Coupons print in minutes
and turn tolerance guessing into measurement — report which bore fit and
regenerate the part with that number.

## Verification

A mechanism design is done when: clearances are stated per joint (and
where they came from — table vs coupon); flex/load directions are
verified against layer orientation; the mesh passes `3d-printing`
validation; and a coupon exists (or the user explicitly declined it).
