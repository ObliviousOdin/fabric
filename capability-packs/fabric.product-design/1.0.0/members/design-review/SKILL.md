---
name: design-review
description: Audit a product-design implementation against its brief and selected direction, then fix and reverify only when authorized. Use for visual QA, UX critique, accessibility and responsive review, or final design acceptance.
---

# Fabric Design Review

Treat a request to review, audit, or critique as report-only. Enter
`audit_and_fix` mode only when the user also asked to implement or fix the
findings. Never infer mutation permission from the existence of source code.

## Establish the review contract

Require the `DesignBrief`, selected `DirectionDecision`, and implementation or
preview target when they exist. If an artifact is missing, name the limitation
and review only what can be supported; do not reconstruct an unapproved brief.

Prefer the rendered product at the required viewports and interaction states.
When browser or device verification is unavailable, inspect source and tests
but label rendered behavior `unverified`.

## Audit systematically

Check the complete journey for:

- information hierarchy, comprehension, and primary-action clarity;
- layout, spacing rhythm, alignment, density, and content resilience;
- every required empty, loading, partial, success, error, permission, offline,
  and destructive state;
- keyboard flow, focus order/visibility, semantics, labels, errors, contrast,
  zoom, and reduced motion;
- responsive behavior, overflow, touch targets, and orientation changes;
- consistency with existing primitives and the selected direction;
- latency feedback, duplicate-action protection, and recovery paths;
- privacy, trust, and permission cues promised by the brief.

Capture exact locations, reproduction steps, viewport/state, and evidence for
each finding. Rank severity by user harm and blocked task completion:
`critical`, `high`, `medium`, or `low`. Distinguish defects from preferences.

## Fix only within authorization

In `audit_and_fix` mode, address findings in severity order while preserving
the selected direction and unrelated user changes. Re-run the relevant checks
and capture before/after evidence. If a fix requires a broader product
decision, new dependency, external write, account, paywall, ticket, deploy, or
permission expansion, stop and request that separate authority.

## Return `DesignReviewReceipt`

Include review mode, targets and artifact identifiers, severity-ranked
findings, evidence and reproduction steps, fixes made, before/after evidence,
checks with exact results, unresolved risks, source-only limitations, and one
status:

- `verified`: every required acceptance check was exercised and passed;
- `verified_with_limits`: exercised checks passed but named evidence or
  environment limits remain;
- `changes_required`: report-only findings remain;
- `blocked`: required evidence or authority is unavailable.

Do not use `verified` for a source-only review or when any required state was
not exercised.
