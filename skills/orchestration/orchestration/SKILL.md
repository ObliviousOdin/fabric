---
name: orchestration
description: "Front door for multi-agent work — decide when to orchestrate at all, then route between subagent ensembles, parallel fan-out, staged pipelines, a builder crew, adversarial verification, kanban worker lanes for durable boards, and Mixture of Agents for multi-model answers. Use when a task feels too big for one context, the user asks for parallel work, subagents, a team of agents, or an ensemble."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [orchestration, subagents, delegation, multi-agent, routing]
    related_skills: [ensemble, fan-out, pipeline, builder-crew, adversarial-verify, subagent-driven-development]
---

# Orchestration

Use this as the front door for multi-agent work: a task that feels too big
for one context, or a user asking for parallel work, subagents, a team of
agents, or an ensemble. This skill decides whether to orchestrate at all,
then routes to exactly one specialist pattern. It never runs a pattern from
memory — load the chosen member skill with skill_view and follow it.

Do NOT use this skill when the shape is already known. Executing an existing
implementation plan through per-task subagents is `subagent-driven-development`
— load it with skill_view. No plan yet? Load `plan`. A throwaway experiment
to de-risk one unknown is `spike`. Generating options rather than executing
is `brainstorming`. Changing delegation configuration itself is
`fabric-agent`.

## First decision: orchestrate at all?

Orchestration is not a default. Delegate only when at least one of these
holds:

- **Independent subproblems.** The work splits into pieces that never need
  to see each other's edits or reasoning.
- **Perspective diversity.** The answer improves when several agents attack
  the same question without anchoring on one line of thought.
- **Context too large.** The raw material (logs, files, search results)
  would flood this context; children can digest it and return summaries.
- **Verification independence.** The check is only trustworthy if the
  checker never saw the author's reasoning.

One context wins — do the work directly, no delegation — when:

- **Edits are deeply coupled.** Changes that must land together across
  shared files serialize anyway; parallel children produce conflicts.
- **The task is small.** For anything under roughly ten minutes of focused
  work, spawning, context-packing, and summary loss cost more than they
  save.
- **The exchange is latency-sensitive.** Conversational back-and-forth
  cannot wait on child turnaround, and children cannot talk to the user.

If no orchestrate condition holds, stop here and do the work in this
context. That is a correct outcome of this skill, not a failure.

## Route the job

Pick the single row that matches the job shape, then load exactly one member
skill with skill_view and read it in full before spawning anything.

| Job shape | Route | Mechanism |
|---|---|---|
| One question, several independent perspectives merged into one answer | `ensemble` | Batch of leaf children on the same goal from different angles; parent synthesizes |
| Many similar independent items processed the same way | `fan-out` | One task per item in a `tasks` batch; identical instructions, different inputs |
| Stages where each stage consumes the previous stage's output | `pipeline` | Sequential delegate_task calls; the parent carries state between stages |
| One deliverable built by distinct roles (spec, build, test, review) | `builder-crew` | Role-shaped delegations coordinated by the parent |
| Independent judgment on work already produced | `adversarial-verify` | Fresh leaf that receives the artifact but never the author's reasoning |
| Executing an implementation plan task-by-task with reviews | `subagent-driven-development` | Implementer plus two-stage review children per task |
| Durable or long-running board that must survive interrupts | Kanban worker lanes (see the kanban feature docs) | Board with worker lanes; workers get lifecycle guidance injected automatically |
| Several models contributing to one reply | Mixture of Agents: `moa` provider presets | Reference models analyze, an aggregator model writes the reply; model-level, no delegate_task |

Two rows need care:

- Kanban worker lanes are not a delegate_task pattern. Delegated children
  are process-local: /stop or a parent interrupt cancels every active
  child, and nothing survives the parent process exiting — so durable,
  long-running multi-agent work belongs on the board, not in a delegation
  chain.
- Mixture of Agents is model-level ensembling (several models, one
  response) configured as a named `moa` provider preset — not agent-level.
  "Use multiple models" routes there; "use multiple agents" routes to
  `ensemble` or `fan-out`.

## Workflow

1. **Qualify.** Apply the first-decision test. If one context wins, say so
   and do the work directly.
2. **Route.** Pick one routing-table row. Load that one member skill with
   skill_view and read it fully. Do not blend rows; if a job spans two
   shapes, the dominant shape wins and the other becomes a stage inside it.
3. **Check limits.** Defaults are 3 concurrent children
   (`delegation.max_concurrent_children`) and flat depth 1
   (`delegation.max_spawn_depth`), which makes `role="orchestrator"` a
   no-op. Size the plan to the current config; raise a knob via the
   `fabric-agent` skill or `fabric config set` only when the pattern
   requires it — never assume it is already raised.
4. **Pack context.** Write every goal and context to the contract below
   before spawning. This step is where orchestrations die.
5. **Execute.** Follow the member skill's loop. Delegations from the
   top-level agent run in the background; results re-enter the conversation
   as new messages when children finish.
6. **Integrate.** Merge child summaries yourself. Children never see each
   other's output unless you explicitly pass it into a later child's
   context.
7. **Verify.** When the result matters, route verification through a fresh
   child (`adversarial-verify`) instead of approving your own merge.
8. **Report.** Deliver the synthesis with exact absolute file paths, and
   name any child that failed or returned thin results.

## The context-packing contract

Children start with a completely fresh conversation — zero knowledge of this
conversation, your prior tool calls, or each other. They cannot ask the user
anything, so every ambiguity becomes a silent guess. Before any
delegate_task call, confirm each task passes this checklist:

- Absolute paths for every file, directory, and working directory.
- The actual data inline: error text, requirements, code snippets — never
  "the error above" or "as discussed".
- Constraints: language and tool versions, style rules, what must NOT
  change.
- A definition of done plus the exact output format for the final summary —
  that summary is the only thing you will ever see from the child.
- Verification commands to run, with expected results.
- No pronouns pointing outside the task ("it", "that bug", "our approach").

Worked example — a fan-out batch that passes the checklist:

```python
delegate_task(tasks=[
    {
        "goal": "Audit src/auth/session.py for insecure session handling",
        "context": """Project: /home/user/webapp (Python 3.11, Flask 3.0).
        File to audit: /home/user/webapp/src/auth/session.py.
        Check: cookie flags, expiry, fixation on login, logout invalidation.
        Do not modify any files. Output findings as lines of
        'severity | line | issue | suggested fix', or 'NO FINDINGS'.""",
        "role": "leaf"
    },
    {
        "goal": "Audit src/auth/tokens.py for JWT validation flaws",
        "context": """Project: /home/user/webapp (Python 3.11, PyJWT 2.8).
        File to audit: /home/user/webapp/src/auth/tokens.py.
        Check: algorithm pinning, expiry, audience and issuer validation.
        Do not modify any files. Output findings as lines of
        'severity | line | issue | suggested fix', or 'NO FINDINGS'.""",
        "role": "leaf"
    },
    {
        "goal": "Audit src/auth/passwords.py for password-handling flaws",
        "context": """Project: /home/user/webapp (Python 3.11, bcrypt 4.1).
        File to audit: /home/user/webapp/src/auth/passwords.py.
        Check: hashing parameters, comparison timing, reset-token entropy.
        Do not modify any files. Output findings as lines of
        'severity | line | issue | suggested fix', or 'NO FINDINGS'.""",
        "role": "leaf"
    }
])
```

Each goal stands alone, each context repeats the shared conventions instead
of referencing a sibling, and the batch is exactly 3 tasks — the default
`max_concurrent_children`. A larger batch returns a tool error; it is not
truncated to fit. Children inherit the parent's toolsets and cannot be
narrowed per task, so constraints like "do not modify any files" live in
the context prose, not in a tool restriction.

## Cost and limits

Every child is a full model loop. A 3-child batch costs roughly four times
the same work done inline — three children plus the parent's packing and
synthesis — and returns less information: one structured summary per child,
never their intermediate reasoning or tool calls. Orchestrate because the
shape demands it, never for the aesthetics of a team.

| Knob | Default | Effect |
|---|---|---|
| `delegation.max_concurrent_children` | 3 | Parallel children per batch. Floor 1, no hard ceiling. Oversized batches are a tool error. |
| `delegation.max_spawn_depth` | 1 | Tree depth. 1 = flat: `role="orchestrator"` is a no-op. Raise to 2+ for nested trees. |
| `delegation.orchestrator_enabled` | true | Set false to force every child to leaf regardless of `role`. |

Depth multiplies rather than adds: `max_spawn_depth: 3` with 3 children per
level can reach 27 concurrent leaves. Raise depth deliberately, one level at
a time, via the `fabric-agent` skill or `fabric config set`.

Do NOT orchestrate when the task fits one context, when edits are coupled,
when the user is waiting mid-conversation, or when the work must survive
interrupts — interrupting the parent cancels all active children, so
durable work goes to the kanban board's worker lanes instead.

## Common failure modes

- **Under-packed context.** The child receives "fix the bug we found" and
  no bug. It cannot ask, so it invents one. Every task passes the checklist
  or does not ship.
- **Judging your own work.** The parent synthesizes, then approves its own
  synthesis. Independence requires a fresh child via `adversarial-verify`.
- **Fan-out on dependent tasks.** Parallel children editing shared files or
  needing each other's output. Dependencies mean `pipeline`, not a batch.
- **Orchestrating the trivial.** A subagent spawned to read one file burns
  a full model loop to save none. Small tasks stay in this context.
- **`role="orchestrator"` at default depth.** With `max_spawn_depth: 1` the
  child silently cannot spawn workers and limps along as a leaf. Raise the
  knob first or design flat.
- **Blending patterns from memory.** Improvising a hybrid instead of
  loading one member skill produces a workflow nobody debugged. Route to
  exactly one row.
- **Expecting a dialogue.** Parents see only each child's final summary —
  no questions, no progress reports. Demand the output format up front.
- **delegate_task for durable work.** One interrupt cancels the whole tree
  and discards in-progress work. Long-lived boards belong in kanban worker
  lanes.
- **Models confused with agents.** Reaching for delegation when the user
  wants several models in one answer. That is Mixture of Agents — an `moa`
  provider preset, no subagents involved.
