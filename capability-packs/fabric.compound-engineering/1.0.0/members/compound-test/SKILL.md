---
name: compound-test
description: Implement an approved engineering change through a behavior-first regression or acceptance check, then verify the smallest complete solution. Use after an approved plan or proven diagnosis when the user asked to build or fix the behavior.
---

# Fabric Compound Test

Require an approved `EngineeringPlan` or proven `DebugDiagnosis` and explicit
authority to change the scoped workspace. Otherwise return `plan_required`,
`diagnosis_required`, or `mutation_not_authorized`.

## Establish the behavior guard

Choose the narrowest test level that fails for the intended behavioral reason
and exercises the real boundary: unit for a local invariant, integration for
configuration/state/I/O, or end-to-end for a user-visible contract. Run the
guard before implementation and confirm its failure is meaningful rather than
a fixture or environment error.

For behavior that cannot be automated immediately, define a deterministic
verification procedure and explain the remaining risk. Never weaken, delete,
or overfit an existing test merely to make the suite green.

## Implement and verify

Make the smallest coherent change that satisfies the approved contract and
covers sibling paths in the same bug class. Reuse existing abstractions,
preserve unrelated user changes, and avoid new dependencies or surface area
without approval.

Run the new guard, relevant neighboring tests, static checks, and the real path
appropriate to the risk. Inspect failures rather than repeatedly patching at
random. Keep claims exact: distinguish passed, failed, skipped, and not run.

Return a `ChangeReceipt` with plan/diagnosis identifier, failing-before
evidence, changed paths and behavior, passing-after evidence, sibling coverage,
commands/results, limitations, rollback notes, and readiness for independent
`compound-review`. Do not mark the work independently verified yourself.
