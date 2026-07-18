---
name: pipeline
description: "Chain subagents through staged handoffs — research, plan, build, verify as separate fresh-context stages connected by explicit artifact contracts on disk. Use for multi-phase work where each phase benefits from a clean context and a reviewable intermediate artifact."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [pipeline, stages, handoff, artifacts, workflow]
    related_skills: [orchestration, fan-out, adversarial-verify, plan]
---

# Pipeline

Use this skill to run multi-phase work as a chain of fresh-context subagents —
research, plan, build, verify — where each stage hands the next a durable
artifact on disk instead of chat memory. Reach for it when the phases depend
on each other, each phase benefits from a clean context, and you want a
reviewable intermediate artifact at every boundary.

Do NOT use it for independent parallel tasks — load `fan-out` with skill_view.
To execute an existing plan task-by-task with implementer and reviewer loops,
load `subagent-driven-development` with skill_view; that skill can run INSIDE
this one's build stage. For a standalone adversarial check of finished work,
load `adversarial-verify` with skill_view. And if the whole job fits one
context comfortably, do it inline — a pipeline adds cost to small work, not
quality.

## Stage anatomy

A pipeline is 3-5 coarse stages. Every boundary between stages has a written
artifact contract: the exact output file path, its format, and a must-contain
list. Subagents start with a completely fresh conversation — zero knowledge of
this session — so the artifact IS the handoff. The next stage reads a file,
never a memory.

| Stage | Reads | Writes | Skill to load inside | Stage constraint (in context prose) |
|---|---|---|---|---|
| Research | 00-task-brief.md | 10-research-brief.md | `spike` for throwaway-prototype questions | May read repo + web; write only the research brief |
| Plan | 10-research-brief.md | 20-plan.md | `plan` | Do not modify source files; write only the plan artifact |
| Build | 20-plan.md | branch diff + 30-build-report.md | `test-driven-development` or `subagent-driven-development` | Implement and test per plan; write the build report |
| Verify | 20-plan.md + the diff | 40-verification-report.md | `requesting-code-review` | Report-only: do not edit, commit, or push |

Adapt the stage list to the work — a docs pipeline might be research, outline,
draft, edit — but keep the shape: coarse stages, file artifacts, one contract
per boundary. Store artifacts in a run directory so a future session can
resume from the last accepted artifact cold:

```
.fabric/pipelines/YYYY-MM-DD-[slug]/
    00-task-brief.md      (parent writes: goal, constraints, repo paths)
    contracts.md          (per boundary: output path, format, must-contain)
    10-research-brief.md
    20-plan.md
    30-build-report.md    (branch name, files touched, test command + output)
    40-verification-report.md
```

## Workflow

1. **Scope the stages.** Pick 3-5 coarse stages with a genuine context break
   between each — different inputs, different mindset, or different constraints.
   If two adjacent stages would share most of their context, merge them.
2. **Write the contracts first.** Before dispatching anything, write
   `contracts.md`: for each boundary, the output file path, format, and a
   must-contain checklist you can verify by reading the file. Resolve every
   ambiguity with the user NOW — children cannot use `clarify`, so any
   question a stage would ask becomes a silent guess instead.
3. **Write stage zero yourself.** Author `00-task-brief.md` in the parent:
   the goal, hard constraints, absolute repo paths, and how to run tests.
   This file substitutes for the conversation history no child will ever see.
4. **Dispatch one stage.** One `delegate_task` call per stage, never a
   `tasks` batch across stages — batches run in parallel and a batched build
   would read a plan that does not exist yet. The context must be
   self-contained: name the input artifact paths to read, restate the output
   contract verbatim, and name the skill to load. Children inherit the
   parent's toolsets (no per-task narrowing); put "do not modify source"
   and similar constraints in context prose. From the top-level agent the child runs in the background and
   its summary re-enters the conversation as a new message when it finishes;
   interrupting the parent cancels it.
5. **Review the artifact.** When the summary arrives, do not trust it — open
   the output file and check it against the contract: file exists, format
   matches, every must-contain item present, scope respected. You are
   checking contract compliance, not redoing the stage's work.
6. **Gate.** Accept and dispatch the next stage; or redo — dispatch a fresh
   child whose context quotes the specific contract gaps (do not patch a
   half-right artifact by hand in the parent, and do not argue with a child
   that has already exited); or escalate to the user when the artifact
   reveals the task brief itself was wrong. Human-in-the-loop lives here, in
   the parent, because it can live nowhere else.
7. **Verify with fresh eyes, then deliver.** The verify stage must be a
   separate child that reads only the plan and the produced diff — never the
   builder judging its own work, and not you either. Deliver the final
   artifact paths plus a two-line trail: which stages ran, which were redone.

Worked stage dispatch (stage 2 of the table above):

```python
delegate_task(
    goal="Write the implementation plan for the rate-limiter feature and save it to /home/user/api/.fabric/pipelines/2026-07-18-rate-limiter/20-plan.md",
    context="""PIPELINE STAGE 2 of 4 (plan). You start with no other context;
    everything you need is below or inside the named files.

    READ FIRST:
    - /home/user/api/.fabric/pipelines/2026-07-18-rate-limiter/00-task-brief.md (goal, constraints)
    - /home/user/api/.fabric/pipelines/2026-07-18-rate-limiter/10-research-brief.md (accepted research findings)

    PROJECT: Python 3.12 FastAPI service at /home/user/api. Tests run with
    `pytest` from the repo root. Redis is already a dependency.

    METHOD: load the `plan` skill with skill_view and follow it.

    OUTPUT CONTRACT — write /home/user/api/.fabric/pipelines/2026-07-18-rate-limiter/20-plan.md containing:
    - numbered tasks, each 2-5 minutes of work, with exact file paths
    - a per-task test command
    - an explicit out-of-scope list
    Do not modify any source files during this stage."""
)
```

Every dispatch in a pipeline must pass this test: could a stranger with no
access to this conversation complete the stage from the goal, the context,
and the named files alone? If not, the context is under-packed.

## Nested pipelines

A stage can itself be a pipeline: dispatch it with `role="orchestrator"` so
the child keeps `delegate_task` and runs its own inner stages, reporting one
artifact back to you. This is gated by `delegation.max_spawn_depth`, which
defaults to 1 (flat) — at the default, `role="orchestrator"` is a no-op and
the child cannot delegate. Raise it deliberately in config.yaml (via
`fabric config set delegation.max_spawn_depth 2`, or load `fabric-agent` with
skill_view), and know that `delegation.orchestrator_enabled: false` forces
every child to leaf regardless of the role you pass. Cost multiplies per
level: depth 3 with 3 children each can reach 27 concurrent leaves. One level
of nesting is almost always enough; prefer more stages over deeper trees.

## Cost and limits

Subagents multiply spend. Every stage re-reads the artifact trail and pays
for a full reasoning loop, so a four-stage pipeline typically costs several
times what a single-context attempt would — and for work under roughly an
hour, the single context is usually both cheaper AND better, because nothing
is lost at handoffs. Do not pipeline: single-file fixes, exploratory work
where the stages are not yet knowable, or tasks needing frequent user
input mid-stage (children cannot ask; you only hear from them at the end).

Concurrency defaults to 3 children (`delegation.max_concurrent_children`,
floor 1, no hard ceiling; oversized batches return a tool error rather than
truncating). A sequential pipeline runs one child at a time, so the limit
binds only when a stage fans out internally or an orchestrator child runs a
nested pipeline. Depth defaults to 1 (`delegation.max_spawn_depth`). Change
either with `fabric config set` or by loading `fabric-agent` with skill_view.

`delegate_task` chains are not durable: interrupting the parent interrupts
all active children, and nothing outlives the session. For a pipeline that
should run for days or survive restarts, put the stages on the kanban board
with worker lanes instead. The artifact directory pays off either way — a
killed pipeline resumes from the last accepted artifact, not from zero.

## Common failure modes

- **Implicit handoffs.** A context saying "continue from the plan we
  discussed" hands the child nothing — it has no conversation history. Name
  every input file by absolute path and restate constraints in each dispatch.
- **Stages too thin.** Per-function or per-file stages spend more tokens on
  handoff overhead than on work. A stage should justify its fresh context;
  if its contract fits in one sentence, merge it into a neighbor.
- **Fan-out on dependent stages.** Putting plan and build in one `tasks`
  batch runs them in parallel; build reads an empty file. Batches are for
  independent work — a pipeline is sequential by definition.
- **Skipping artifact review.** Dispatching stage N+1 the moment stage N
  returns makes the contract decoration. A defective plan compounds through
  build and verify; the review gate is where the pipeline earns its cost.
- **Judging your own work.** Letting the builder self-certify, or verifying
  the diff yourself in the parent, collapses the independence the verify
  stage exists to provide. Fresh child, plan plus diff, nothing else.
- **Chat-memory artifacts.** Output that exists only in a child's final
  summary is lossy and unreviewable. The contract requires a file on disk;
  confirm the file exists before you accept anything the summary claims.
- **Ambiguity deferred to children.** `clarify` is blocked for subagents, so
  an underspecified contract becomes a confident guess. Settle open
  questions with the user before dispatch, never during a stage.
- **Patching artifacts by hand.** Quietly rewriting a failed artifact in the
  parent pollutes your context with stage-level work and hides the contract
  gap. Redispatch with the gaps quoted; keep the parent an orchestrator.
