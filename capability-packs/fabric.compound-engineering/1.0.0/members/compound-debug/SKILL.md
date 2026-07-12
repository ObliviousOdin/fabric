---
name: compound-debug
description: Prove the causal chain behind an observed failure before proposing a repair. Use for regressions, flaky behavior, integration failures, data corruption, performance changes, or any bug whose root cause is not already evidenced.
---

# Fabric Compound Debug

Diagnose before repair. Do not change product behavior in this phase unless the
user separately authorizes a reversible diagnostic instrument or urgent
containment.

## Establish the failure

Capture expected versus observed behavior, a minimal reproduction, environment,
frequency, earliest known occurrence, and affected scope. Reproduce on the
current code when safe. If it cannot be reproduced, identify which evidence is
missing rather than choosing a plausible story.

Trace the real runtime path across configuration, state, boundaries, and I/O.
Use history to understand intentional behavior before treating an omission or
restriction as a defect.

## Test causal hypotheses

Maintain a short hypothesis table with prediction, discriminating observation,
result, and confidence. Start at the boundary where good state becomes bad.
Prefer read-only inspection and narrow instrumentation. Change one variable at
a time, retain raw evidence needed to reproduce the conclusion, and actively
test a credible alternative cause.

A correlation, nearby code smell, or passing mock is not a root cause. The
diagnosis must identify the mechanism and show why it produces the observed
symptom along the executed path.

Return a `DebugDiagnosis` with reproduction, timeline/data flow, hypotheses and
experiments, root cause or `root_cause_unproven`, affected sibling paths,
containment status, recommended behavior change, regression guard, and
remaining uncertainty. Hand off to `compound-test` only when the causal chain
is proven and the user requested a fix.
