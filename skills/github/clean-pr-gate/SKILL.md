---
name: clean-pr-gate
description: Use when the user says ship, push safely, gate/validate my changes, raise a clean PR, or asks you to do a task and then validate it. Runs a validate-before-push gate (intent, review, test, lint, docs, push, PR, CI) on committed work using Fabric's own subagents, then opens a clean PR.
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [gate, pre-push, code-review, pull-requests, ci, validation, clean-pr]
    related_skills: [requesting-code-review, github-pr-workflow, github-code-review, test-driven-development]
---

# Clean PR Gate

## Overview

A local gate that validates committed changes through a pipeline — **intent →
review → test → lint → docs → push → PR → CI** — before they reach the remote,
then opens a clean PR. It is the "kill the slop, raise a clean PR" workflow built
entirely on Fabric's own tools: a `requesting-code-review` review pass, an
independent reviewer subagent via `delegate_task`, and `github-pr-workflow` for
push/PR/CI. **No external binary.**

**Core principle:** no agent verifies its own work. The reviewer and fixer run in
fresh `delegate_task` contexts, not yours.

This skill is the missing glue: `requesting-code-review` reviews a diff and
`github-pr-workflow` opens a PR, but nothing drives a change from "committed on a
branch" all the way to "clean PR with green CI" while pausing for the decisions
only the user can make. That is this skill.

## When to Use

- User says "ship", "push safely", "gate this", "validate my changes", "raise a
  clean PR", "review before merge", or invokes `/clean-pr-gate`.
- User asks you to do a task **and then** validate it (task-first mode, below).
- After finishing a feature/fix that is committed on a feature branch.

**Don't use for:**
- Reviewing **someone else's** PR with inline comments → use `github-code-review`.
- Documentation-only or pure-config changes, or when the user says "skip
  verification" / "just push".

## Two modes

- **Validate-only** — bare `/clean-pr-gate`. The work is already committed;
  validate it and open the PR.
- **Task-first** — `/clean-pr-gate <task>`, e.g. "add a `--json` flag then gate
  it". First do the work yourself, then validate:
  1. **Check scope.** Run `git status` before changing anything. Preserve
     unrelated uncommitted changes; commit only what belongs to the task.
  2. **Do the work**, then **commit on a feature branch**. If the user is on the
     default branch, create a feature branch first (`git checkout -b <type>/<desc>`)
     — the gate validates committed history on a non-default branch.
  3. **Then validate**, using the task text as your intent (next section).

Everything below applies once the work is committed on a feature branch.

## Step 0 — Preconditions

Completion criterion: all four true before you start; otherwise fix the failing
one and re-check.

```bash
git rev-parse --is-inside-work-tree   # must be a git repo
git branch --show-current             # must NOT be the default branch (main/master)
git status --porcelain                # intended work committed; note any leftover
git log --oneline origin/HEAD..HEAD 2>/dev/null || git log --oneline -5
```

- Inside a git repo with a GitHub remote (`git remote get-url origin`).
- On a **feature branch**, not `main`/`master`. If on default, create one and
  move the commits (`git branch <feat>; git reset --hard origin/main` only when
  safe — otherwise cherry-pick).
- The work is **committed**. The gate validates committed history, not the dirty
  worktree. If uncommitted changes are the work, commit them first.

## Step 1 — Write the intent (required)

Before reviewing, write down **what the user set out to accomplish** — the goal
behind the change, plus the decisions and tradeoffs made along the way. You know
it from the conversation; capture it in a short paragraph.

This is not a description of the diff. The reviewer uses it to tell a **deliberate
choice** apart from a **mistake** — a thin one-line intent makes the reviewer flag
things the user already chose. Include: the objective, specific decisions, any
constraints or approaches ruled in/out, and anything the user explicitly asked for
that would look surprising in the diff. Store it as `$INTENT` for the reviewer
prompt in Step 2.

## Step 2 — Review gate

Run the `requesting-code-review` pipeline on the branch diff (`git diff origin/HEAD...HEAD`
or `git diff main...HEAD`): its static security scan, the independent reviewer
`delegate_task`, and the auto-fix loop. **Pass `$INTENT` into the reviewer prompt**
(add it as an `<intent>` block above `<code_changes>`) so deliberate choices are
not flagged.

Then **classify each finding** and act by its class — this is what makes the gate
raise a *clean* PR instead of silently rewriting the user's intent:

| Class | Meaning | Your action |
|-------|---------|-------------|
| `auto-fix` | Mechanical, low-risk (ignored error, missing guard, lint) | Fix it via a fix `delegate_task` (max 2 cycles), then re-review. |
| `no-op` | Informational only | Note it, continue. |
| `ask-user` | Challenges the user's intent or changes product behavior | **Stop. Escalate to the user** (see below). Do not fix, approve, or skip on your own. |

**Auto-fix loop:** dispatch a **third** context (not you, not the reviewer) that
fixes ONLY the reported `auto-fix` findings — see `requesting-code-review` Step 7.
Re-run review after each fix. Max 2 cycles; if still failing, escalate.

Completion criterion: every finding is resolved, noted as `no-op`, or escalated —
none left undecided.

## Step 3 — Escalate `ask-user` findings

A finding is `ask-user` when it challenges the user's deliberate intent or changes
product behavior — that call is theirs, not yours. Before responding:

- Relay each `ask-user` finding **verbatim** — its file, line, and full
  description. Do not paraphrase or pre-judge.
- Ask how to proceed, then act on their answer: fix (with their guidance),
  accept as-is, or skip.

Use `AskUserQuestion` when you have concrete options; otherwise ask in prose.
**Exception:** if the user gave standing consent to drive the whole run unattended
("just gate it, don't check back"), resolve `ask-user` findings on your judgment
and note each decision in the final report.

## Step 4 — Test and lint gates

From `requesting-code-review` Step 3, baseline-aware:

- Capture the failure count **before** your changes as the baseline (stash, run,
  pop). Only **new** failures block.
- Run the project's tests and linters (auto-detect: pytest / npm test / cargo /
  go; ruff/mypy/eslint/tsc/clippy/go vet). In this repo, tests run via
  `scripts/run_tests.sh`.
- New failures are `auto-fix` findings → back to Step 2's fix loop. Pre-existing
  failures are `no-op` (note them).

Completion criterion: no new test or lint regressions versus baseline.

## Step 5 — Docs check

If the diff changes a public interface (CLI flags, API, config keys) but touches
no docs/README/help text, raise one `ask-user` finding — updating user-facing docs
is a product decision. Otherwise `no-op`.

## Step 6 — Push and open the PR

Only after Steps 2–5 are clean. Follow `github-pr-workflow`:

```bash
git push -u origin HEAD
```

Open the PR with a body that reflects `$INTENT` (summary + test plan). Check for a
repo PR template (`.github/pull_request_template.md`) and mirror its headings if
present. **Do not** open the PR before the gate is clean — that defeats the gate.

Completion criterion: branch pushed, PR created, PR URL captured.

## Step 7 — CI watch and auto-fix

Follow `github-pr-workflow` §4–5: watch checks, and on failure diagnose → fix on
the same branch → push → re-check, up to 3 attempts. A real, out-of-scope failure
is an `ask-user` escalation, not something to force past.

## Step 8 — Outcome

Report one of:

- **checks-passed** — validated and CI green, PR open but **not merged**. You are
  done driving. Give the user the PR URL and ask them to review and merge. Do not
  wait on the merge or self-merge unless the user asked you to.
- **passed** — cleared and the PR was merged/closed (only if the user asked you to
  merge).
- **failed** — a gate or CI blocked it. Say exactly what blocks it and either
  retry or hand back the diagnosis. Never leave the user at a silent failure.

On success, close the loop concisely: what was validated, what the reviewer found,
and — if the fix loop changed anything — **list each fix** so the user can review
what their original change missed.

## Common Pitfalls

1. **Skipping intent.** Without `$INTENT`, the reviewer flags deliberate choices as
   bugs and the gate churns. Always do Step 1.
2. **Fixing `ask-user` findings yourself.** Product/intent calls belong to the
   user. Escalate; don't silently rewrite.
3. **Verifying your own work.** The reviewer and fixer must be separate
   `delegate_task` contexts, never your own.
4. **Pushing before the gate is clean.** Push is Step 6, after review/test/lint —
   not the first thing you do.
5. **Gating on the default branch or a dirty tree.** Step 0 exists for this.
   Commit and branch first.
6. **Infinite fix loops.** Cap auto-fix at 2 cycles, CI auto-fix at 3, then
   escalate.
7. **Counting pre-existing failures as regressions.** Baseline first; only new
   failures block.

## Verification Checklist

- [ ] On a feature branch, work committed, GitHub remote present (Step 0)
- [ ] `$INTENT` written from the conversation, not the diff (Step 1)
- [ ] Review ran in a fresh subagent with `$INTENT` supplied (Step 2)
- [ ] Every finding resolved, noted, or escalated — none undecided
- [ ] `ask-user` findings relayed verbatim and decided by the user (Step 3)
- [ ] No new test/lint regressions vs baseline (Step 4)
- [ ] Public-interface changes have docs or an `ask-user` finding (Step 5)
- [ ] PR opened only after the gate was clean; PR URL captured (Step 6)
- [ ] CI green or its failure escalated (Step 7)
- [ ] Outcome reported with the fix list, if any (Step 8)
