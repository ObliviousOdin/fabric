---
name: design-explore
description: Generate and compare genuinely distinct product-design directions from an approved DesignBrief. Use when the problem is defined but hierarchy, interaction model, navigation, density, or visual direction has not been selected.
---

# Fabric Design Explore

Require an approved `DesignBrief`. If the brief is missing, contradictory, or
still awaiting a material decision, return `brief_required` and stop instead
of designing against invented requirements.

## Explore distinct systems

Inspect the existing product and design system before generating directions.
Use research or competitive references only when available and permitted;
identify inspiration without copying a proprietary branded surface.

Create at least three directions that differ in meaningful product behavior or
system choices, not only color, typeface, or decoration. Vary dimensions such
as:

- information hierarchy and progressive disclosure;
- navigation and interaction model;
- density, pacing, and content emphasis;
- state transitions and feedback;
- responsive composition;
- visual voice in service of the product goal.

For every direction:

1. Give it a clear thesis and describe the primary journey.
2. Show how it handles every required brief state.
3. Identify the reusable primitives and any intentional system changes.
4. Explain accessibility and responsive implications.
5. Estimate implementation complexity without pretending to know facts that
   were not inspected.
6. Name risks, tradeoffs, and evidence that would falsify the direction.

Use the best available medium for comparison—structured text, wireframes,
mockups, or prototypes—without adding dependencies or publishing externally
unless the user authorized that action.

## Compare without silently deciding

Score or assess each direction against every acceptance check in the brief.
Explain meaningful tradeoffs and recommend one, but do not treat the
recommendation as the user's selection. If the user has not selected a
direction, stop before implementation.

Return a `DirectionDecision` containing:

- the brief version or digest used;
- at least three direction summaries and their evidence/artifact locations;
- acceptance-check comparison;
- accessibility, responsive, complexity, and risk tradeoffs;
- recommendation and rationale;
- rejected shortcuts or proprietary-cloning risks;
- unresolved questions;
- `selection`: the explicit selected direction or `selection_required`.

This phase completes only when the alternatives are materially distinct and
the decision state is explicit.
