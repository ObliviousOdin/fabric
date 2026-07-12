---
name: product-design
description: Route product and UX work through Fabric's brief, exploration, build, and verification phases. Use when a request spans a product-design workflow or needs the correct design phase selected before work begins.
---

# Fabric Product Design

Act only as the workflow selector. Do not write the brief, generate directions,
edit implementation files, or perform the review inside this router.

## Select one phase

Use the request and any named design artifacts to determine the current phase.
Load exactly one member with `skill_view` before substantive work begins.

| Current need | Load |
|---|---|
| Clarify the product problem, user, constraints, states, and success evidence | `design-brief` |
| Generate and compare materially different directions from an approved brief | `design-explore` |
| Produce the selected direction or implement the complete product slice | `design-build` |
| Audit the result, fix only when authorized, and capture verification evidence | `design-review` |

Treat a brief as approved only when its decision owner or the user has accepted
its problem and acceptance contract. Treat a direction as selected only when the
user or an explicit product contract identifies it. Do not infer approval from a
recommendation.

If the phase is genuinely ambiguous, ask one short question that distinguishes
the possible phases. Do not preload members while waiting for the answer.

## Preserve the boundary

- Load one member for one phase. A later phase may be loaded only after the
  active member reaches its completion condition.
- If a required member is missing, disabled, or unavailable in the current
  session, name that exact condition and stop. Do not silently substitute a
  different method.
- Never enable tools, change permissions, install dependencies, or widen
  network access. The selected member inherits the current session boundary.
- Keep all member bodies on demand. Do not quote or aggregate them into this
  router.

Return a concise `RoutingDecision` containing the selected phase, selected
member, evidence used to select it, required input artifact, and any blocking
condition. Then hand control to that member.
