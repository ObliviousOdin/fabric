---
name: compound-plan
description: Turn an understood engineering goal and repository evidence into an implementation-ready change contract. Use before coding work that crosses components, changes behavior, carries rollout risk, or needs explicit verification and rollback.
---

# Fabric Compound Plan

Design the change; do not implement it in this phase.

## Ground the plan

Read the relevant code, tests, configuration, history, and local instructions.
Describe current behavior at the exact boundary that will change. Record facts,
decisions, assumptions, and open questions separately. If feasibility remains
materially uncertain, return `spike_required`. If the task is a bug without a
proven causal chain, return `diagnosis_required`.

## Specify the change contract

Define:

- intended behavior, non-goals, and user-visible states;
- affected components, ownership boundaries, and data flow;
- lifecycle and parameter contracts, invariants, failure behavior, and
  compatibility requirements;
- security, privacy, prompt-cache, tool-schema, profile, and concurrency impact;
- migration, rollout, observability, recovery, and rollback behavior;
- tests that relate behavior across boundaries rather than freeze incidental
  values;
- representative end-to-end evidence and negative cases;
- ordered implementation steps with exact likely paths and dependencies.

Prefer extending existing mechanisms to adding parallel managers, hooks, or
core tools. Name any decision that requires the user, an owner, credentials,
external access, or a materially different scope.

Return an `EngineeringPlan` with evidence inspected, current-state model,
proposed design, contracts/invariants, execution order, tests, rollout and
rollback, risks, open decisions, and `approval_status`. The plan completes when
another engineer can implement it without inventing architecture or silently
changing scope.
