---
name: moa-software-development
description: "Run a two-layer Mixture-of-Agents software workflow: one-shot GPT/Grok advisory planning, independent subscription-backed coding workers in isolated git worktrees, deterministic viability gates, and a blinded final MoA review owned by one merge agent. Use for difficult cross-module, architectural, security-sensitive, or genuinely disputed repository changes where independent implementations are worth the cost."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [moa, coding, worktrees, openai-codex, xai-oauth, deterministic-gates]
    related_skills: [orchestration, ensemble, pipeline, plan, test-driven-development, requesting-code-review]
---

# MoA Software Development

Use this skill for difficult repository work where two independent
implementations and a model-diverse review can materially reduce risk. It is a
**two-layer system**:

1. **Advisory MoA at stage boundaries** — references analyze; the aggregator
   reconciles.
2. **Independent acting workers** — each worker has tools and its own git
   worktree; deterministic checks decide viability before any model judges a
   patch.

MoA references never receive tools. They cannot inspect files, run commands,
or discover facts omitted from the prompt. Serialize repository facts into the
task brief and inline the relevant brief/diff/evidence in each MoA boundary
prompt.

Do **not** use this workflow for typos, narrow mechanical edits, or ordinary
changes where one worker plus tests is enough. Use `plan`,
`test-driven-development`, or `requesting-code-review` instead. Do not use it
outside a git repository.

## Non-negotiable invariants

1. One parent agent owns scope, user contact, integration, and the final merge.
2. Every writing worker gets a separate explicit worktree and branch from the
   same base SHA.
3. MoA runs once for planning and once for review, never on every tool-loop
   iteration. Presets use `fanout: user_turn`.
4. Workers do not merge, push, rewrite shared history, weaken tests, or change
   public APIs outside the brief.
5. Deterministic gates eliminate non-viable candidates before model review.
6. Candidate labels in the judge packet are blinded (`A`, `B`), with provider
   and model metadata kept only in the run ledger.
7. Zero viable candidates means no winner. One viable candidate still needs a
   final accept/reject review. A hybrid is a new patch and must pass every gate.
8. Never integrate into a dirty primary worktree or silently omit uncommitted
   user changes. Ask before stashing, snapshotting, or changing the base.
9. Do not run autonomous workers in a checkout containing production
   credentials or unrelated repositories. Worktrees isolate files, not global
   git credentials or arbitrary absolute-path access.

## Phase 0 — qualify and preflight

Inspect before acting:

```bash
git rev-parse --show-toplevel
git status --short --branch
git rev-parse HEAD
git worktree list --porcelain
```

Also inspect repository instructions (`AGENTS.md`, `CLAUDE.md`,
`.cursorrules`), package/build metadata, submodules, Git LFS, and the existing
validation commands. Stop if the base is ambiguous or dirty changes would be
excluded. Record the immutable base SHA.

Bootstrap subscription presets from the authenticated live model catalogs:

```bash
fabric moa bootstrap subscriptions --dry-run
fabric moa bootstrap subscriptions
fabric moa list
```

The bootstrap must find both `openai-codex` and `xai-oauth`, chooses only model
IDs returned for the active profile, installs `subscription-plan` and
`subscription-review`, caps each reference at 700 output tokens, and uses
`fanout: user_turn`. It refuses to replace existing managed preset names unless
the parent explicitly reviews the dry run and uses `--force`.

The command also prints the selected Grok coding-worker model. Record all four
selected lanes in the ledger. If OAuth is missing, authenticate the relevant
provider and rerun discovery. Do not silently substitute an API-billed
provider.

Before a long run, smoke-test the exact selected models with a narrow prompt.
CLI options must come before `-z`; `-z` consumes the prompt argument:

```bash
fabric --ignore-rules -t safe --provider openai-codex -m MODEL -z "Reply only: MODEL_OK"
fabric --ignore-rules -t safe --provider xai-oauth -m MODEL -z "Reply only: MODEL_OK"
```

Treat xAI 403, unavailable model, quota, or subscription errors as an explicit
lane failure. The parent may continue with one worker only if the user values
progress over independent implementation; record the reduced search and do not
claim a two-worker comparison.

## Phase 1 — create the run record and task brief

Keep workflow state outside the repository so the primary tree stays clean.
Derive the active profile home from `fabric config path`, then create:

```text
<Fabric profile home>/moa-runs/<timestamp>-<slug>/
├── TASK.md
├── PLAN.md
├── JUDGE.md
├── LEDGER.md
├── usage-gpt.json
├── usage-grok.json
└── worktrees/
    ├── gpt/
    └── grok/
```

Use `templates/TASK.md`. The brief must contain exact repository facts, not
aspirations:

- objective and observable acceptance criteria;
- immutable base SHA and relevant files/modules;
- compatibility, performance, security, and scope constraints;
- exact test, lint, typecheck, build, security, and benchmark commands;
- prohibited changes, including tests/APIs/files that may not be weakened;
- viability rules and rollback plan.

If required checks are unknown, inspect CI/package configuration and resolve
them before planning. Never let a worker invent the gate after implementation.

## Phase 2 — one-shot advisory plan

Inline the complete task brief in a single call to the planning preset. The
references cannot read `TASK.md` by path.

```text
Provider: moa
Model: subscription-plan
Toolset: safe

Review the task brief below and produce one reconciled execution plan.
Do not vote or average suggestions. Resolve disagreement using the stated
constraints and acceptance criteria.

Return exactly:
1. Chosen architecture
2. Ordered implementation steps
3. Independent worker brief shared by both workers
4. Validation commands and viability rules
5. Main risks, re-plan triggers, and rollback plan

[TASK.md contents inline]
```

Save the acting aggregator's result to `PLAN.md`. The parent checks that the
plan does not expand scope, weaken gates, or rely on facts absent from the
brief. Revise the brief before workers start if needed.

## Phase 3 — create isolated workers

Create both branches from the recorded base SHA, never from two different
moving branch heads:

```bash
git worktree add <run>/worktrees/gpt  -b fabric/moa/<run-id>-gpt  <base-sha>
git worktree add <run>/worktrees/grok -b fabric/moa/<run-id>-grok <base-sha>
```

Launch the workers concurrently using background terminals, one process per
worktree, with completion notification enabled. Do not use Fabric's implicit
`--worktree` here: explicit paths and branch names make collection and cleanup
deterministic.

GPT lane:

```bash
fabric --provider openai-codex -m <selected-sol-or-terra> \
  -t terminal,file,todo --usage-file <run>/usage-gpt.json \
  -z "<worker prompt>"
```

Grok lane:

```bash
fabric --provider xai-oauth -m <selected-composer-or-build> \
  -t terminal,file,todo --usage-file <run>/usage-grok.json \
  -z "<worker prompt>"
```

Run each command with its worker worktree as `workdir`. Do not pass
`--ignore-rules`; each worker must load repository instructions. The shared
worker prompt includes the full task brief and chosen plan and says:

```text
Independently implement the requested change in this worktree.

Rules:
- Make the smallest complete patch and follow repository conventions.
- Do not assume or inspect the other worker's implementation.
- Do not weaken, delete, skip, or rewrite tests to make the patch pass.
- Do not push, merge, rebase shared branches, or write outside this worktree.
- Run every validation command in the task brief.
- Document exact checks, failures, and unresolved risks.
- Commit only when all required checks pass; otherwise leave a clear failure
  report and do not claim completion.
```

Use Sol for the hardest cross-module/security task, Terra for normal
implementation, and the discovered Grok Composer/Build model for the
independent alternative. The model that wrote a patch cannot be its sole
reviewer.

## Phase 4 — deterministic viability gate

After both processes exit, the parent independently inspects each worktree:

```bash
git status --short --branch
git log -1 --format=%H
git diff --stat <base-sha>...HEAD
git diff --check <base-sha>...HEAD
git diff <base-sha>...HEAD
```

Then rerun every required check from `TASK.md` in each candidate worktree.
Record exact commands, exit codes, wall time, test counts, warnings, benchmark
deltas, changed files, diff size, dependency changes, commit SHA, and worker
usage data in `LEDGER.md`.

Reject a candidate before judging if it:

- fails any mandatory deterministic check;
- weakens/deletes tests or validation configuration;
- changes public APIs or files outside scope;
- adds unexplained dependencies;
- contains an unexplained generated or suspiciously large diff;
- has no auditable commit despite claiming success;
- requires undisclosed manual cleanup.

Handle outcomes explicitly:

- **0 viable:** do not call a winner. Re-plan once only if evidence shows the
  brief or architecture was wrong; otherwise report the blockers.
- **1 viable:** send that candidate to final review for `ACCEPT` or `REJECT`.
  Disclose that no independent viable alternative survived.
- **2 viable:** build a blinded comparison packet with candidates `A` and `B`.

Flaky checks are not silently waived. Reproduce them, identify the source, and
record any user-approved quarantine.

## Phase 5 — one-shot final review

Use `templates/JUDGE.md`. Inline the task brief, selected plan, viable diffs,
and exact gate evidence. Reference models cannot retrieve files or tool output.
Do not include worker/provider identity in the comparison packet.

Run a single call with provider `moa`, model `subscription-review`, and the
`safe` toolset. The required verdict is:

```text
VERDICT: A | B | HYBRID | ACCEPT | REJECT
RATIONALE: evidence tied to TASK.md and gate output
RISKS: unresolved issues only
INTEGRATION: exact commit or exact hybrid edits
REQUIRED_RECHECKS: commands to run after integration
```

The judge may compare only viable candidates. If the full evidence packet does
not fit the selected models' context, split by module into boundary review
packets, preserve the exact patches for security-sensitive areas, then perform
one final synthesis over the module verdicts. Never replace evidence with a
worker's self-reported summary.

## Phase 6 — integrate and verify

Workers never merge. The parent agent integrates the selected commit (or
implements the precisely described hybrid) only after confirming the target
worktree is clean and still based on the recorded base. A hybrid is a new
candidate, not a verbal winner.

After integration:

1. run `git diff --check`;
2. rerun every required deterministic check on the integrated state;
3. inspect the final diff against prohibited changes;
4. report branch, commit(s), exact commands/results, judge verdict, reduced
   lanes or fallbacks, and unresolved risks;
5. push only when the user explicitly asked for a remote side effect.

Remove worktrees only after verifying branches/commits are preserved and no
worktree contains uncommitted changes:

```bash
git worktree remove <path>
git worktree prune
git worktree list --porcelain
```

## Re-plan policy

A single additional planning boundary is allowed when deterministic evidence
shows a structural flaw in `TASK.md` or the chosen architecture. Update
`TASK.md`, version `PLAN.md`, and launch fresh branches from the original base
or an explicitly approved new base. Do not repeatedly fan out models to rescue
workers that simply failed to follow the brief.

## Final report contract

Return:

- base SHA and integration branch/commit;
- exact subscription providers/models used in each lane;
- planning and review preset names;
- candidate table with commit, diff size, checks, viability, wall time, usage;
- blinded judge verdict and rationale;
- integrated validation output;
- worktree cleanup status;
- explicit caveats (403/quota, one-lane run, flaky gate, rejected candidate).

Never claim a two-worker MoA result when only one acting worker completed, and
never describe model consensus as proof when deterministic evidence disagrees.
