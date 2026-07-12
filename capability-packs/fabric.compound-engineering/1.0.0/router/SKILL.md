---
name: compound-engineering
description: Route engineering work through Fabric's evidence-driven spike, plan, debug, test, independent review, and durable capture phases. Use when a task should leave both verified behavior and reusable engineering knowledge behind.
---

# Fabric Compound Engineering

Act only as the phase selector. Do not investigate, plan, implement, review, or
capture inside this router. Load exactly one member with `skill_view` before
substantive work begins.

## Select the current phase

| Current condition | Load |
|---|---|
| Feasibility, dependency behavior, or approach is materially uncertain | `compound-spike` |
| The goal is understood and needs an implementation and verification contract | `compound-plan` |
| A failure is observed but its causal chain is not yet proven | `compound-debug` |
| A plan or diagnosis is approved and the user asked for the code change | `compound-test` |
| Implementation is complete and needs independent, report-only verification | `compound-review` |
| Review and checks pass and the reusable lesson needs a durable home | `compound-capture` |

Do not route directly from an unexplained failure to implementation. Do not
treat a recommended plan as approved, a green narrow test as independent
review, or an unverified conclusion as capture-ready evidence.

If two phases seem possible, choose the earliest unmet evidence gate. Ask one
short question only when the answer changes that selection. Never preload
multiple members.

## Preserve workflow and permission boundaries

- A phase may hand off to the next member only after returning its named
  receipt and meeting its completion condition.
- If a required member is missing, disabled, or unavailable, report that exact
  condition and stop rather than substituting a weaker method.
- Never enable tools, install dependencies, widen network access, or infer
  authority for mutations or external writes.
- Keep member bodies on demand so the conversation prefix and tool schema stay
  stable.

Return a concise `CompoundRoutingDecision` with selected phase/member, evidence
used, required input receipt, and any blocker, then hand control to that member.
