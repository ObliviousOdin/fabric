# Blinded final review packet

You are the final merge-decision aggregator. Reference advisors have no tools and
cannot read files or retrieve omitted evidence. Review only the material inline.

Do not vote or average suggestions. Do not choose based on explanation quality.
Use TASK.md constraints, exact patch content, and deterministic gate evidence.
A candidate absent from the viable-candidate section is ineligible.

## Required verdict format

```text
VERDICT: A | B | HYBRID | ACCEPT | REJECT
RATIONALE: evidence tied to TASK.md and gate output
RISKS: unresolved issues only
INTEGRATION: exact commit or exact hybrid edits
REQUIRED_RECHECKS: commands to run after integration
```

`ACCEPT`/`REJECT` are for a one-viable-candidate run. `HYBRID` must describe an
implementable patch precisely; it becomes a new candidate and must pass all gates.

## Task brief

<complete TASK.md contents inline>

## Reconciled plan

<complete PLAN.md contents inline>

## Viable candidate A

Provider/model identity intentionally withheld.
Commit: `<sha>`
Changed files and diff stat:

```text
<exact output>
```

Deterministic gate evidence:

```text
<commands, exit codes, test counts, warnings, benchmarks>
```

Patch:

```diff
<exact diff from base SHA>
```

## Viable candidate B

Omit this section when only one candidate is viable.
Provider/model identity intentionally withheld.
Commit: `<sha>`
Changed files and diff stat:

```text
<exact output>
```

Deterministic gate evidence:

```text
<commands, exit codes, test counts, warnings, benchmarks>
```

Patch:

```diff
<exact diff from base SHA>
```

## Rejected candidates

List only labels and deterministic rejection reasons. Do not include their patches
in the review set.
