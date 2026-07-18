# Task: <short title>

Run ID: `<timestamp>-<slug>`
Repository: `<absolute repository path>`
Base SHA: `<immutable git SHA>`
Merge owner: `parent Fabric agent`
Prompt version: `moa-software-development/v1`

## Objective

Describe the one outcome that must be delivered.

## Relevant files and modules

- `<path>` — why it is relevant

## Current behavior and evidence

Include exact observed behavior, errors, reproduction steps, and repository facts.
Do not include assumptions as facts.

## Constraints

- Compatibility:
- Performance:
- Security/privacy:
- Platform/runtime:
- Scope:

## Acceptance criteria

- [ ] Observable condition 1
- [ ] Observable condition 2
- [ ] Regression coverage exists

## Required deterministic checks

Run from the candidate worktree. Every mandatory command must exit zero.

```bash
<test command>
<lint command>
<typecheck command>
<build command>
<security or benchmark command, when required>
```

## Viability rules

A candidate is non-viable if any required check fails, tests are weakened, public
contracts change outside scope, dependencies are unexplained, or the patch cannot
be audited from a commit based on the recorded SHA.

## Prohibited changes

- Tests or validation configuration that may not be weakened/deleted:
- Public APIs that may not change:
- Files/modules that are out of scope:
- Dependencies that may not be added:
- Remote actions workers may not perform: push, merge, release, deploy

## Worker handoff

Both workers receive this exact brief and the reconciled plan. They implement
independently and must not inspect each other's branch or worktree.

## Risks and rollback

- Main risks:
- Re-plan trigger:
- Rollback procedure:
