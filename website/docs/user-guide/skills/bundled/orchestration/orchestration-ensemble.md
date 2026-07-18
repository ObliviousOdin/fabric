---
title: "Ensemble"
sidebar_label: "Ensemble"
description: "Run a subagent ensemble on one hard problem — spawn several specialists with deliberately different lenses on the same question, then judge and synthesize th..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ensemble

Run a subagent ensemble on one hard problem — spawn several specialists with deliberately different lenses on the same question, then judge and synthesize their answers into one stronger result. Use for high-stakes decisions, designs, estimates, or diagnoses where a single perspective is likely to miss something.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/orchestration/ensemble` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `ensemble`, `subagents`, `diversity`, `judging`, `synthesis` |
| Related skills | [`orchestration`](/user-guide/skills/bundled/orchestration/orchestration-orchestration), [`adversarial-verify`](/user-guide/skills/bundled/orchestration/orchestration-adversarial-verify), [`brainstorming`](/user-guide/skills/bundled/venture-studio/venture-studio-brainstorming) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Ensemble

Use this skill when one hard question deserves several independent minds:
a go/no-go migration call, an architecture choice, a cost or effort estimate,
a stubborn diagnosis, any decision where being wrong is expensive and a
single pass is likely to anchor on its first plausible answer. You will
dispatch one `delegate_task` batch of subagents that all attack the SAME
problem through deliberately different lenses, judge their answers against a
rubric fixed in advance, and synthesize one result stronger than any member.

Do NOT use this for executing a plan task-by-task — load
`subagent-driven-development` with skill_view. Do not use it to generate raw
idea volume; divergence is `brainstorming`'s job, an ensemble evaluates and
decides. To de-risk one unknown with a throwaway experiment, load `spike`.
Independent judgment on work that already exists — a diff, a claim, a
benchmark — is `adversarial-verify`: an ensemble answers an open question,
it does not attack a finished artifact. A code diff wanting a human-facing
review writeup goes to `requesting-code-review`. And if the user
wants several MODELS blended into one reply rather than several briefs, that
is Mixture of Agents — a model-level `moa` provider preset where reference
models analyze first and an aggregator model writes the response; set that up
via the `fabric-agent` skill instead of delegating agents at all.

## Workflow

1. **Freeze the problem statement** — one paragraph every member receives verbatim.
2. **Design the lenses** — three genuinely different charters, not three copies.
3. **Lock the rubric** — scoring criteria written down BEFORE any answer exists.
4. **Dispatch the batch** — one `delegate_task` call, one task per lens.
5. **Judge** — score answers against the rubric, yourself or via a fresh judge.
6. **Synthesize** — winner as backbone, minority insights grafted in, dissent kept.
7. **Deliver** — recommendation, score table, and what would change the answer.

### 1. Freeze the problem statement

Write a self-contained problem block: the question as one sentence, the
concrete situation (absolute paths, numbers, error text, constraints), and
what a complete answer must contain. Subagents start with a completely fresh
conversation — zero knowledge of this session — so anything not in this block
does not exist for them. If the question is still ambiguous, resolve it with
the user NOW: children never get the `clarify` tool and cannot ask later.

### 2. Design the lenses

Pick three lenses that can genuinely disagree about this problem. Three is
the sweet spot: enough diversity to surface blind spots, and it exactly fits
the default `delegation.max_concurrent_children` of 3 — a wider ensemble
requires raising that key first (see Cost and limits).

| Lens | Charter | Strong for |
|---|---|---|
| Risk-first | Assume it ships and then fails. Enumerate failure modes, blast radius, rollback paths; recommend whatever minimizes the worst outcome | Migrations, launches, irreversible calls |
| User-first | Argue only from observable user or operator experience: latency, breakage, workflow change, support burden | Product and API decisions |
| Simplest-thing | Champion the least machinery that plausibly works; treat every added component as guilty until proven necessary | Architecture, build-vs-buy |
| Maintainer | Optimize for the on-call engineer in year three: debuggability, upgrade paths, bus factor | Infrastructure, dependencies |
| Contrarian | Build the strongest case AGAINST the obvious or default answer, steelman included | Consensus-smelling decisions |
| Evidence-first | Claim nothing the repo, docs, or data cannot back; cite file paths and measured numbers for every assertion | Estimates, diagnoses |

Each lens gets a two-part charter in its `context`: what it optimizes for and
what it is explicitly allowed to ignore. Give every task the SAME output
contract so answers are comparable — recommendation in one line, top three
arguments, top three risks, confidence 1-5, evidence cited by path.

### 3. Lock the rubric

Write the rubric before dispatching — never after reading answers, or you
will rationalize a favorite. Keep it to 3-5 criteria plus a tie-break:

```markdown
## Rubric (locked before any answer was read)
- Follows from evidence: conclusion is forced by what the answer shows, /5
- Grounding: cites real paths and measured numbers, not vibes, /5
- Risk coverage: names the failure that would actually hurt most, /5
- Actionability: work could start tomorrow from this answer alone, /5
Tie-break: the answer whose worst named risk has the best mitigation.
```

### 4. Dispatch the batch

One `delegate_task` call with a `tasks` array. Repeat the frozen problem
block verbatim in every task's context — never write "the migration discussed
above"; there is no above. Keep `role` at its default of "leaf": an ensemble
is flat, and with `delegation.max_spawn_depth` at its default of 1,
"orchestrator" would be a no-op anyway. Worked example:

```python
delegate_task(tasks=[
    {
        "goal": "Recommend for or against migrating shopd's background jobs from Redis/rq to Postgres SKIP LOCKED queues, arguing risk-first.",
        "context": """PROBLEM (identical for all reviewers): The app at /home/user/shopd runs ~40k background jobs/day on rq + Redis 6 (single node, no persistence). Ops wants one less datastore; a draft Postgres queue lives in /home/user/shopd/jobs/pg_queue.py. Postgres 15 already hosts the primary DB at ~30% load. Question: migrate, stay, or stage it?
YOUR LENS — RISK-FIRST: assume the migration ships and then fails in production. Enumerate concrete failure modes (lock contention, vacuum bloat, job loss during cutover), blast radius, and rollback story. Recommend whatever minimizes the worst outcome. Ignore elegance and long-term simplicity.
OUTPUT CONTRACT: one-line RECOMMENDATION; top 3 arguments; top 3 risks; confidence 1-5; every claim about the codebase cited by file path.""",
        "toolsets": ["terminal", "file"]
    },
    {
        "goal": "Recommend for or against migrating shopd's background jobs from Redis/rq to Postgres SKIP LOCKED queues, arguing simplest-thing.",
        "context": """PROBLEM (identical for all reviewers): The app at /home/user/shopd runs ~40k background jobs/day on rq + Redis 6 (single node, no persistence). Ops wants one less datastore; a draft Postgres queue lives in /home/user/shopd/jobs/pg_queue.py. Postgres 15 already hosts the primary DB at ~30% load. Question: migrate, stay, or stage it?
YOUR LENS — SIMPLEST-THING: champion the least total machinery that plausibly works. Count moving parts, configs, and failure domains under each option; treat every component as guilty until proven necessary. Ignore hypothetical future scale.
OUTPUT CONTRACT: one-line RECOMMENDATION; top 3 arguments; top 3 risks; confidence 1-5; every claim about the codebase cited by file path.""",
        "toolsets": ["terminal", "file"]
    },
    {
        "goal": "Recommend for or against migrating shopd's background jobs from Redis/rq to Postgres SKIP LOCKED queues, arguing maintainer-first.",
        "context": """PROBLEM (identical for all reviewers): The app at /home/user/shopd runs ~40k background jobs/day on rq + Redis 6 (single node, no persistence). Ops wants one less datastore; a draft Postgres queue lives in /home/user/shopd/jobs/pg_queue.py. Postgres 15 already hosts the primary DB at ~30% load. Question: migrate, stay, or stage it?
YOUR LENS — MAINTAINER: optimize for the on-call engineer in year three. Weigh debuggability, monitoring, upgrade paths, and how each option fails at 3am. Ignore one-time migration effort.
OUTPUT CONTRACT: one-line RECOMMENDATION; top 3 arguments; top 3 risks; confidence 1-5; every claim about the codebase cited by file path.""",
        "toolsets": ["terminal", "file"]
    }
])
```

The batch runs in the background; each child's final structured summary
re-enters the conversation as a new message when it finishes. You never see
their intermediate reasoning — the output contract is your only window, which
is why every task must carry it.

### 5. Judge

Two modes; pick before reading any answer.

**Self-judge** when answers are short and you did not author a favorite:
score each answer criterion by criterion in rubric order, writing scores as
you go, before forming an overall impression.

**Fresh judge subagent** when you drafted the charters and might pet one
lens, or when answers are long. The judge sees ONLY the rubric and the
anonymized answers — strip lens names and reorder to Answer A/B/C so it
scores content, not charter:

```python
delegate_task(
    goal="Score three anonymized recommendations against the rubric provided and name a winner.",
    context="""You are judging answers to: should shopd migrate background jobs from Redis/rq to Postgres SKIP LOCKED queues? You know nothing else about the project; judge only what is on the page.
RUBRIC (locked before answers were written): follows-from-evidence /5; grounding in cited paths and numbers /5; risk coverage /5; actionability /5. Tie-break: best-mitigated worst risk.
ANSWER A: [full text, lens name removed]
ANSWER B: [full text, lens name removed]
ANSWER C: [full text, lens name removed]
OUTPUT: a score table (answer x criterion), one paragraph per answer on its decisive strength or flaw, and WINNER: A/B/C."""
)
```

### 6. Synthesize

The winner is the backbone, not the whole result. Walk the losing answers
for grafts: any risk, constraint, or piece of evidence the winner missed gets
merged in with attribution to its lens. A disagreement that survives judging
is a finding — report it as an open question with what evidence would settle
it. Never average three recommendations into a mushy middle; the ensemble
exists to sharpen the decision, not to blur it.

### 7. Deliver

Report: the recommendation, the score table, grafted minority insights,
surviving dissent, and the single observation that would flip the answer.
If the decision leads to build work, route onward — `plan` to shape it,
`subagent-driven-development` to execute it.

## Cost and limits

A 3-lens ensemble plus a judge costs roughly 4-5x a single-context answer.
Reserve it for questions where a wrong call costs more than that multiple;
for factual questions, checkable answers, or lenses that would obviously
converge, a single careful pass is cheaper AND better.

- Defaults: 3 concurrent children (`delegation.max_concurrent_children`,
  floor 1, no ceiling) and spawn depth 1 (`delegation.max_spawn_depth`, so
  `role="orchestrator"` is a no-op). Raise them in config.yaml under
  `delegation:` via the `fabric-agent` skill or `fabric config set`.
- A batch larger than the concurrency limit returns a tool error — it is not
  truncated. Check the limit before designing a 4+ lens ensemble.
- Keep the ensemble flat. Depth multiplies spend: depth 3 with 3 children
  each can reach 27 concurrent leaves.
- Interrupting the parent interrupts all active children; mid-flight work is
  discarded. An ensemble spanning hours or needing durability belongs on the
  kanban board with worker lanes, not in a `delegate_task` chain.

## Common failure modes

- **Three copies in trench coats.** Lenses that differ only by adjective
  ("thorough", "careful", "detailed") produce one answer three times. Every
  pair of charters must be able to disagree about THIS problem.
- **Under-packed context.** "Evaluate the migration we discussed" — children
  have zero conversation history. If the problem block is not in the task
  context, the child is answering a different question.
- **Rubric after answers.** Criteria chosen once you know the answers is
  rationalization wearing a table. Lock the rubric at step 3.
- **Judging your own favorite.** You wrote the charters; self-judging with
  lens names visible rewards the brief you liked writing. Anonymize, or hand
  judging to a fresh subagent.
- **Averaging into mush.** "Do a partial migration, sort of" satisfies no
  lens and inherits everyone's risks. Pick a winner; graft; keep dissent.
- **Fan-out on dependent tasks.** If lens B needs lens A's output, this is a
  pipeline, not an ensemble — run it sequentially or use
  `subagent-driven-development`.
- **No shared output contract.** Three answers in three formats cannot be
  scored on one rubric. The contract line goes in every task, verbatim.
- **Ensemble as procrastination.** If the user has already decided, or a
  20-minute direct investigation would settle it, spawning a committee is
  expensive theater.
- **Wrong layer.** Wanting GPT, Gemini, and a local model to weigh in is a
  model-level `moa` preset (via the `fabric-agent` skill), not three
  subagents on the same model with different briefs.
