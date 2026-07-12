---
name: compound-spike
description: Resolve one material engineering uncertainty with a bounded, disposable experiment and explicit evidence. Use before planning when feasibility, an API, dependency behavior, performance, or an architectural assumption is unknown.
---

# Fabric Compound Spike

Turn uncertainty into a decision without quietly building production code.

## Frame the experiment

State one decision the spike must unlock, the competing hypotheses, the
smallest observation that distinguishes them, a time or scope bound, and a
stop condition. Inspect existing code and documentation before experimenting.
Separate verified facts from assumptions.

Prefer a disposable harness, temporary branch/worktree artifact, existing
test fixture, or read-only probe. Do not modify production behavior unless the
user explicitly requested that form of experiment. Never use real customer
data, expose secrets, create accounts, publish, deploy, purchase, or widen
network access without separate authority.

## Run and interpret

1. Record the baseline and exact environment.
2. Change one material variable at a time.
3. Capture commands, inputs, outputs, timings, and failure details needed to
   reproduce the observation.
4. Test the strongest plausible counterexample within the bound.
5. Stop when the decision is supported, falsified, or the bound is exhausted.

Do not present a prototype as production-ready. Remove disposable artifacts
unless the user asked to retain them, and name anything intentionally left in
the workspace.

Return a `SpikeResult` with question, hypotheses, method, evidence, result,
limitations, artifacts retained/removed, and one decision: `proceed`,
`do_not_proceed`, `revise_assumption`, or `still_unknown`. A `still_unknown`
result must say what evidence or authority is missing.
