---
name: design-build
description: Produce or implement a selected product-design direction as a coherent, responsive, accessible slice. Use only after an approved DesignBrief and explicit DirectionDecision identify what should be built.
---

# Fabric Design Build

Require both an approved `DesignBrief` and an explicit selected direction. If
either is absent, return `brief_required` or `selection_required` and stop.

## Ground the implementation

Inspect the repository, existing design system, route structure, data
contracts, tests, and local instructions before editing. Preserve user changes
and reuse established primitives unless the approved direction explicitly
requires a system change. State any mismatch between the selected direction
and the actual codebase before resolving it.

Build the smallest complete journey that satisfies the brief—not an isolated
happy-path screenshot. Include:

- semantic structure and sensible reading order;
- keyboard operation, visible focus, labels, and error association;
- required empty, loading, partial, success, error, permission, and destructive
  states;
- responsive behavior at the product's supported breakpoints;
- realistic long, short, missing, localized, and stale content;
- latency and action feedback;
- motion that respects reduced-motion preferences;
- tests and preview instructions appropriate to the repository.

When the requested output is a mockup or specification rather than code,
produce the selected deliverable with the same state, accessibility, content,
and responsive completeness. Do not imply that a visual artifact is a tested
implementation.

## Protect scope and trust

- Do not clone proprietary branded UI, introduce an unapproved dependency,
  replace unrelated code, or widen permissions or network access.
- Keep changes inside the user-authorized workspace and product slice.
- Do not create accounts, publish assets, deploy, purchase services, or send
  messages unless those external actions were separately authorized.
- Preserve the brief's non-goals. Record desirable follow-ups instead of
  smuggling them into the build.

## Verify and hand off

Run the narrowest reliable static, unit, interaction, accessibility, and build
checks available for the changed slice. Preview the result when the current
tools permit it. Do not mark checks passed when they were not run.

Return an `ImplementationReceipt` containing changed artifacts, brief and
direction identifiers, acceptance checks exercised, state coverage,
accessibility/responsive evidence, tests with exact results, preview target,
known limitations, deferred work, and readiness for `design-review`.
