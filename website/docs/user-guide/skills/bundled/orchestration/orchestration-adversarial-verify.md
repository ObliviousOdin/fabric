---
title: "Adversarial Verify"
sidebar_label: "Adversarial Verify"
description: "Verify work with independent skeptic subagents — spawn fresh-context reviewers charged with refuting a claim, finding what breaks, or failing a ship-readines..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Adversarial Verify

Verify work with independent skeptic subagents — spawn fresh-context reviewers charged with refuting a claim, finding what breaks, or failing a ship-readiness bar before you trust or ship it. Use before merging risky changes, publishing numbers, or acting on a conclusion a single context produced.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/orchestration/adversarial-verify` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `verification`, `red-team`, `review`, `skeptics`, `quality-gate` |
| Related skills | [`orchestration`](/user-guide/skills/bundled/orchestration/orchestration-orchestration), [`ensemble`](/user-guide/skills/bundled/orchestration/orchestration-ensemble), [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review), [`test-driven-development`](/user-guide/skills/bundled/software-development/software-development-test-driven-development) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Adversarial Verification

Use this skill to independently verify a claim before you trust it, ship it, or
report it: a bugfix that "works now", a benchmark number, a data analysis, a
"safe to merge" call. The mechanism is `delegate_task`: spawn fresh-context
skeptic subagents whose only job is to refute the claim, and treat the claim as
unverified until they fail to break it.

Do NOT use this skill to execute work — load `subagent-driven-development` with
skill_view to drive a build through subagents (its per-task reviews run during
construction; this skill gates the finished claim). For a human-facing review
writeup, load `requesting-code-review`. When a failing-then-passing test can
settle the claim, write the test — `test-driven-development` is the cheaper
first line, and this gate assumes it already ran. Several independent lenses on
an OPEN question — a decision not yet made, no finished artifact to attack — is
`ensemble`, not verification; this skill needs a produced claim to refute. For
open-ended exploration of a risk area with no specific claim yet, load `spike`.

## The independence rule

The verifier must not be the author. A context that produced a conclusion will
defend it; re-reading your own diff verifies your reasoning, not the code.
`delegate_task` children start with a completely fresh conversation — zero
knowledge of your history — which is exactly the property this gate needs.
Protect it deliberately:

- Give verifiers the ARTIFACT and the CLAIM: paths, commits, commands, inputs,
  the observable behavior at stake.
- Never give them the REASONING that produced the artifact ("the root cause was
  X, so the fix must be right"). Reasoning transfers your bias; the verifier
  inherits your blind spot along with it.
- Frame every charge as refutation: "find inputs where this fails", "try to
  break this", "assume the claim is false until you cannot make it fail". A
  prompt that asks "confirm this works" buys a yes.
- Verifiers are report-only. They never edit, commit, or fix — the parent
  applies fixes. Children cannot ask the user anything, and a verifier that
  patches what it finds has stopped being a gate.

## Workflow

1. **Isolate the claim.** Write one falsifiable sentence: "commit C fixes crash
   X for input class Y", "the numbers in report.md reproduce from raw/ within
   1%". If no evidence could refute the sentence as phrased, sharpen it before
   spawning anything.
2. **Package the evidence.** Collect everything a stranger needs to attack the
   claim: absolute repo path, branch and commit ids, build and test commands,
   input data locations, the original observable failure. Strip your reasoning
   and your confidence.
3. **Pick lenses.** One refuter for routine claims. For high stakes — merging
   risky changes, publishing numbers, security-relevant behavior — use 2-3
   diverse lenses so a shared blind spot must fool independent angles. Batches
   of up to 3 run in parallel at the default
   `delegation.max_concurrent_children` of 3; a larger batch returns a tool
   error (never truncated), so stay at 3 lenses or raise the limit first
   (`fabric config set delegation.max_concurrent_children 4`, or via the
   `fabric-agent` skill).
4. **Dispatch refuters.** One `delegate_task` call with a `tasks` array. Each
   task's goal and context must stand alone — fresh context, see the rule
   above. Report-only toolsets: `["terminal", "file"]` when they must run
   things, `["file"]` for pure reading, `["web"]` for citation checks.
   Delegations run in the background; verdicts re-enter the conversation as
   messages when children finish, and interrupting yourself interrupts all of
   them.
5. **Collect verdicts** in the structured format below. A verifier that replies
   in prose instead of the format gets re-dispatched, not interpreted
   charitably.
6. **Adjudicate.** Majority rules across lenses, with one asymmetry: a single
   REFUTED with reproducible evidence outranks two CONFIRMED, because a
   refutation is constructive (there is a failing case) while a confirmation is
   only the absence of found failure. Escalate genuinely uncertain or split
   verdicts to the user with both evidence sets — never average disagreement
   into a soft pass.
7. **Fix and re-verify.** Apply fixes yourself in the parent, then dispatch NEW
   fresh verifiers against the updated artifact. Do not resume the old
   children and do not self-certify the fix. The loop closes only on a clean
   adversarial pass.

### Verdict format

Require this exact block from every verifier — paste it verbatim into context:

```
VERDICT: CONFIRMED | REFUTED | INCONCLUSIVE
CLAIM: [the claim restated in the verifier's own words]
ATTACKS TRIED: [numbered; exact commands and inputs for each]
EVIDENCE: [verbatim output for the decisive attacks]
CONFIDENCE: [high | medium | low, plus the biggest untested angle]
```

CONFIRMED means "I attacked this N ways and could not break it", never "it
looks right". REFUTED must include a reproducible failing case. INCONCLUSIVE
means the verifier could not exercise the claim at all — usually the parent's
packaging failed, not the artifact.

### Lens menu

| Lens | Charge | Typical toolsets |
|---|---|---|
| Repro / correctness | Reproduce the original failure before the change; prove it gone after; hunt hostile input variants | terminal, file |
| Regression | Diff behavior before and after the change; find anything that worked and now does not | terminal, file |
| Security | Attack the trust boundaries the change touches: authz bypass, injection, unsafe input handling | terminal, file |
| Does-it-reproduce | Rerun an analysis or benchmark from raw inputs; compare against the published numbers | terminal, file |
| Claim audit | Check a document's factual claims and citations against primary sources | web, file |

## Worked example: gating a bugfix

Claim to gate: "commit 4f2a91c on branch fix/date-parse fixes the ValueError
when importing CSVs with European-format dates, without breaking existing date
handling." Two lenses, one batch — fits the default concurrency of 3. Note
what the contexts contain (paths, commits, commands, attack plans) and what
they omit (any theory of the root cause or how the fix works).

```python
delegate_task(tasks=[
    {
        "goal": "Refute this claim: commit 4f2a91c on branch fix/date-parse fixes the crash where importing a CSV containing European-format dates (e.g. 13/02/2026) raised ValueError from parse_date() in src/importer/dates.py.",
        "context": """You are an independent verifier with no prior knowledge of this work.
Assume the claim is FALSE until you cannot make it fail.

Repo: /home/user/webapp (Python 3.12). Clone it to a scratch directory so the
tree you attack is your own: git clone /home/user/webapp /tmp/verify-dates
The fix is commit 4f2a91c; its parent 4f2a91c^ still contains the bug.
Import a CSV with: python -m importer.cli import PATH.csv  (from the repo root).

Attack plan:
1. At 4f2a91c^, construct a CSV with 13/02/2026-style dates and reproduce the
   ValueError. If the original bug will not reproduce, report INCONCLUSIVE.
2. At 4f2a91c, rerun the identical input, then at least five hostile variants:
   ambiguous 03/04/2026, two-digit years, mixed formats in one file, empty
   date fields, non-date garbage.

Report only — do not edit, commit, or push anything.
Reply with exactly this block:
VERDICT: CONFIRMED | REFUTED | INCONCLUSIVE
CLAIM: / ATTACKS TRIED: / EVIDENCE: / CONFIDENCE:""",
        "role": "leaf",
        "toolsets": ["terminal", "file"]
    },
    {
        "goal": "Refute this claim: commit 4f2a91c on branch fix/date-parse of the repo at /home/user/webapp introduces no regressions in date handling or the CSV importer.",
        "context": """You are an independent verifier with no prior knowledge of this work.
Hunt for anything commit 4f2a91c breaks that worked before it.

Repo: /home/user/webapp (Python 3.12). Clone to /tmp/verify-regress.
Test suite: pytest tests/ -q  (from the repo root).

Attack plan:
1. Run the full suite at 4f2a91c^ and at 4f2a91c; diff the results. Any test
   passing before and failing after is REFUTED, with that diff as evidence.
2. Read the change (git show 4f2a91c) and probe behavior it touches that the
   suite does not cover: ISO dates like 2026-02-13, US-format dates that
   previously parsed, timestamps, empty files.

Report only — do not edit, commit, or push anything.
Reply with exactly the VERDICT / CLAIM / ATTACKS TRIED / EVIDENCE /
CONFIDENCE block.""",
        "role": "leaf",
        "toolsets": ["terminal", "file"]
    }
])
```

Adjudicate the returned verdicts:

| Verdicts | Parent action |
|---|---|
| All CONFIRMED at high or medium confidence | Trust the claim; record the pass in your summary |
| Any REFUTED with reproducible evidence | Apply the fix yourself, then dispatch new fresh verifiers |
| Any INCONCLUSIVE | Repackage the context (usually your packaging bug) and re-dispatch that lens |
| Split after a re-run, or all low confidence | Escalate to the user with both evidence sets; do not average |

## Cost and limits

Every verifier is a full agent loop; three lenses can more than triple what
the gate costs. Do not orchestrate when a single context is cheaper and good
enough: claims a test can settle (run `test-driven-development` first), pure
style questions, or artifacts small enough that reading them here settles the
matter. This skill earns its cost only when the risk of your own bias exceeds
the price of independent eyes. Multi-model consensus is a different tool —
`moa` provider presets ensemble models inside one response; this skill
ensembles fresh agent contexts.

Defaults you depend on: `delegation.max_concurrent_children` is 3 (floor 1, no
hard ceiling; oversized batches are a tool error), and
`delegation.max_spawn_depth` is 1, so verifiers are leaves and
`role="orchestrator"` is a no-op until the depth is raised to 2+. Raise either
with `fabric config set` or the `fabric-agent` skill; note
`delegation.orchestrator_enabled: false` forces every child to leaf. Depth-3
trees can reach 27 concurrent leaves — verification almost never justifies
that. Children also never get `clarify`, so an under-specified context becomes
INCONCLUSIVE spend, not a question back to you. Durable recurring verification
(nightly reproduce jobs) belongs on the kanban board with worker lanes, not in
`delegate_task` chains.

## Common failure modes

- **Leaking the author's reasoning.** A root-cause theory in the verifier's
  context makes it verify your theory, not the behavior. Symptom: verdicts
  that echo your own phrasing back at you.
- **Confirm-framed prompts.** "Verify this works" and "double-check my fix"
  produce agreement. Every charge must be a refutation with a concrete attack
  plan.
- **Judging your own work.** "Carefully re-checking" in the authoring context
  is proofreading, not verification. If the stakes justify a gate, they
  justify a fresh context.
- **Treating one pass as proof.** CONFIRMED means the attacks tried all
  failed. After any fix, the artifact is new — dispatch new verifiers.
- **Verifying style instead of the claim.** A verdict about naming and
  structure means the lens drifted; the claim was behavioral. Re-dispatch with
  a sharper attack plan.
- **Under-packed context.** Missing paths, commands, or commit ids turn spend
  into INCONCLUSIVE noise. The verifier cannot ask; the packaging step is
  load-bearing.
- **Verifiers with write access.** A verifier that fixes what it finds hides
  the change from the parent and stops being a gate. Report-only, always.
- **Fan-out on dependent verdicts.** If lens B needs lens A's output, sequence
  two delegations; batching them starves B. Batch only independent lenses.
- **Averaging away disagreement.** A 2-1 split on a high-stakes claim is not
  66% confidence — it is an unresolved dispute. Escalate it with the evidence.
