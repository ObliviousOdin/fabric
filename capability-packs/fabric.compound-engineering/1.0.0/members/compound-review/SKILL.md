---
name: compound-review
description: Independently review a completed engineering change against its approved contract, repository intent, and verification evidence. Use after implementation; this phase is report-only and never fixes, stages, commits, stashes, resets, or deploys.
---

# Fabric Compound Review

Review independently and report only. Do not edit files or perform repository,
deployment, account, or messaging mutations in this phase, even if fixes appear
obvious. A later explicit task may address accepted findings.

## Reconstruct the contract

Read the approved plan or diagnosis, change receipt, current diff, relevant
tests, local instructions, and history for intent. Confirm the diff is the
claimed scope and identify unrelated or missing changes before judging style.

## Review by user harm

Trace changed behavior and failure paths. Check:

- correctness, invariants, edge cases, and sibling call paths;
- state/config propagation, concurrency, retries, cleanup, and rollback;
- authorization, secrets, network, file, and trust-boundary effects;
- prompt-prefix stability, role alternation, and model-tool footprint when
  relevant;
- compatibility, migrations, observability, and operational recovery;
- whether tests prove the contract through real boundaries instead of mocks or
  snapshots alone;
- scope drift, speculative infrastructure, and duplicated mechanisms.

Rank only actionable findings as `critical`, `high`, `medium`, or `low`. Each
finding needs exact evidence, affected behavior, and a concrete remedy. Keep
preferences and optional improvements separate from defects. If no actionable
finding exists, say so directly.

Return a `ReviewReceipt` with reviewed revision/diff, contract evidence,
findings, verification independently rerun, unverified areas, scope assessment,
and status `approved`, `approved_with_limits`, `changes_required`, or `blocked`.
Only `approved` or explicitly accepted limits may hand off to
`compound-capture`.
