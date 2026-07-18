---
name: builder-crew
description: "Assemble a virtual product crew of subagent specialists — product, design, engineering, quality, and growth roles with written charters, each delegated a self-contained brief, coordinated by you as the founder-proxy. Use when a founder-sized task spans several disciplines at once and the user wants a team, a crew, or a company-in-a-box on the job."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [crew, roles, virtual-team, founders, coordination]
    related_skills: [orchestration, pipeline, ensemble, fan-out, design-studio, webapp-development]
---

# Builder Crew

Use this skill when a founder-sized task spans several disciplines at once —
"build and launch this", "take my idea to a shippable v1", "put a team on
it" — and the user wants a crew, not a single hand. Assemble a small virtual
company: 3-5 subagent specialists with written charters and named
deliverables, sequenced in dependency waves, with yourself as the
founder-proxy who briefs every role, integrates their output, and owns every
decision and every word said to the user.

Do NOT use it for a purely engineering flow (research, plan, build, verify)
— load `pipeline` with skill_view. Independent same-shaped tasks are
`fan-out`; several lenses on ONE question are `ensemble`; executing an
existing implementation plan task-by-task is `subagent-driven-development`.
For depth in a single discipline, skip the crew and load the venture-studio
specialist directly — `design-studio` for brand and product shaping,
`webapp-development` for the build itself. No committed concept yet? Load
`brainstorming` first. Unsure which pattern fits at all? Load
`orchestration`, the front door.

## The crew

Pick 3-5 roles for the task at hand, never more. A role earns its place with
a distinct deliverable no other role produces; a role whose output would
restate another's gets cut before dispatch. Default bench:

| Role | Owns | Default deliverable |
|---|---|---|
| Product strategist | Problem, target user, v1 scope, non-goals, success metric | `product-brief.md` |
| Designer | Flows, hierarchy, one visual direction inside the brief's scope | `design-direction.md` plus mockup files |
| Engineer | Working software honoring brief and design; spike first when risky | code in the workspace plus `build-notes.md` |
| Quality reviewer | Independent verdict against the brief; hunts what the crew missed | `quality-report.md` |
| Growth | Positioning, launch copy, first-100-users plan | `growth-plan.md` |

Swap the bench for the domain — a hardware task might trade growth for a
manufacturing role — but keep the shape: one strategist-type role that fixes
scope first, at least one maker, and one reviewer who built none of what is
being reviewed.

Every role is one `delegate_task` call, or one entry in a batch for a
parallel wave. Roles start with a completely fresh conversation: they know
nothing about the user, this conversation, or each other beyond what the
brief carries. Deliverables are FILES in the workspace, never chat summaries
— the child's summary tells you where the file is and what was decided; the
file is the handoff.

## Crew charter

Write the charter before dispatching anyone and keep it in the workspace:

```markdown
# Crew charter: [slug]

Founder-proxy: the parent agent. All user contact, sequencing,
integration, and tie-breaking decisions stay here.
Workspace: /abs/path/.fabric/crew/2026-07-18-[slug]/

## Product strategist
Charter: Owns what v1 is and is not. One sharp target user, one
success metric, explicit non-goals. Done means a designer and an
engineer could start from the brief without asking a question.
Deliverable: product-brief.md
Inputs: the user's ask (wave 1 — no dependencies)

## Designer
Charter: [one paragraph — what this role owns, to what standard]
Deliverable: design-direction.md
Inputs: product-brief.md (wave 2)

[one block per remaining role]

## Waves
1. product strategist
2. designer + engineering spike     (parallel — inputs exist)
3. engineer build
4. quality reviewer + growth        (parallel)
```

Waves group roles whose inputs already exist on disk. Parallelize only
inside a wave; a role whose input is another role's deliverable waits for
that wave to close. The classic sequence — product brief, then design
direction and engineering spike in parallel, then build, then quality pass —
fits most product tasks unchanged.

## Workflow

1. **Qualify.** Confirm the task genuinely spans three or more disciplines.
   If it collapses into one discipline or one staged pipeline, route per the
   opening paragraph — a crew on a one-role task is pure overhead.
2. **Charter.** Pick roles, write the charter file with one-paragraph
   charters, named deliverable files, and waves. Show the user the role list
   and wave plan in a few lines and incorporate their reaction; this is the
   last cheap moment to cut a role.
3. **Stage the workspace.** Create the crew directory, save the charter,
   copy in whatever the roles will need: specs, repo paths, brand rules.
4. **Dispatch the wave.** One `delegate_task` per solo role; one batch for a
   parallel wave. Each brief must be self-contained: charter paragraph
   pasted in, absolute workspace path, exact deliverable path and outline,
   decisions already made, paths of upstream deliverables to read, and an
   instruction to record assumptions instead of asking questions — crew
   roles cannot reach the user. Keep each wave within
   `delegation.max_concurrent_children` (default 3); a larger batch returns
   a tool error, it is not trimmed.
5. **Integrate and decide.** When a wave returns, read every deliverable
   yourself. Where outputs conflict — design wants a wizard, the spike says
   the data source cannot support it — make the founder call explicitly,
   record it in the charter, and carry it into the next wave's briefs.
   Escalate only genuine fork-in-the-road choices to the user, batched.
6. **Repeat** steps 4-5 wave by wave until the maker waves are done.
7. **Quality pass.** The quality reviewer is always a fresh subagent briefed
   with the product brief and the finished work's paths — never review your
   own integration inline and call it QA. Triage the report: fix blockers,
   dispatching a fix role if the fix is sizable; consciously defer the rest.
8. **Deliver.** Report as the founder: what shipped, where each deliverable
   lives, decisions made on the user's behalf, open questions. The user
   hears one voice — yours.

## Worked example: the first two waves

```python
# Wave 1 — product strategist, solo: everything downstream depends on it.
delegate_task(
    goal="Write the v1 product brief for 'Shelfie' to "
         "/home/user/work/.fabric/crew/2026-07-18-shelfie/product-brief.md",
    context="""You are the product strategist on a five-role product crew.
Your charter: own what v1 is and is not — one sharp target user, one
success metric, explicit non-goals. Done means a designer and an engineer
could start without asking a question.

The user's ask, verbatim: a web app where friends track and lend books
from their personal shelves. Constraints from the user: solo maintainer,
no budget for paid APIs, must run on their existing VPS via Docker.

Write product-brief.md with sections: Problem, Target user, v1 features
(max 5), Non-goals, Success metric, Riskiest assumption. Decide anything
ambiguous yourself and record it under 'Assumptions' — you cannot ask
the user questions."""
)

# Wave 2 — designer and engineering spike in parallel. Both inputs now
# exist on disk. Two tasks, within the default concurrency limit of 3.
delegate_task(tasks=[
    {
        "goal": "Write the design direction for Shelfie to /home/user/"
                "work/.fabric/crew/2026-07-18-shelfie/design-direction.md",
        "context": "You are the designer on a product crew. First read "
                   "the brief at /home/user/work/.fabric/crew/2026-07-18-"
                   "shelfie/product-brief.md; stay inside its scope and "
                   "non-goals. Deliver: core flows for the v1 features, "
                   "information hierarchy, one visual direction (type, "
                   "color, density) with rationale, as plain markdown. "
                   "Record assumptions instead of asking questions."
    },
    {
        "goal": "Spike Shelfie's riskiest technical unknown; write "
                "findings to /home/user/work/.fabric/crew/2026-07-18-"
                "shelfie/spike-notes.md",
        "context": "You are the engineer on a product crew, in spike "
                   "mode: throwaway code, learning is the deliverable. "
                   "Read /home/user/work/.fabric/crew/2026-07-18-shelfie/"
                   "product-brief.md; its 'Riskiest assumption' section "
                   "names the unknown (book metadata without paid APIs). "
                   "Constraints: free sources only, Docker on a small "
                   "VPS. Deliver: what you tried, what worked, the "
                   "recommended build approach, snippets inline. Record "
                   "assumptions instead of asking questions."
    }
])
```

Between waves, read both files and reconcile them: if the spike kills a
feature, amend the brief, note the decision in the charter, and say so in
the wave-3 build brief. Then dispatch the build.

## Cost and limits

Every role is a full agent loop: a five-role crew costs roughly five times
the tokens of inline work, plus your integration reading. Do not orchestrate
when one context can hold the whole job — a small feature, one document, one
discipline — inline is cheaper AND better, because nothing is lost at
handoffs. The crew earns its cost only when disciplines genuinely need
separate framings and fresh contexts.

Operating limits at defaults:

- Parallel roles per wave: `delegation.max_concurrent_children`, default 3,
  floor 1, no hard ceiling. Oversized batches error rather than queue.
- Depth: `delegation.max_spawn_depth` defaults to 1, so every role is a
  leaf and `role="orchestrator"` is a no-op. Raise it to 2 before giving a
  role its own workers (say, an engineer running an implement-review loop),
  and mind the multiplication — depth 3 with 3 children each can reach 27
  concurrent leaves. `delegation.orchestrator_enabled: false` forces every
  role to leaf regardless.
- Change these under the `delegation:` key in config.yaml, via the
  `fabric-agent` skill or `fabric config set`.
- Roles never get `clarify`, `memory`, `send_message`, `execute_code`,
  `cronjob`, or (as leaves) `delegate_task`. Brief accordingly.
- Interrupting you interrupts every active role; in-flight work is lost. A
  crew that must survive days or restarts belongs on the kanban board with
  worker lanes, not in delegate_task chains.

## Common failure modes

- **Too many roles.** Seven roles is a costume party, not a company. Cap at
  five; merge any role that cannot name a deliverable the others lack.
- **Role cosplay.** Titles without distinct outputs — a "CMO" who returns
  the strategist's brief with adjectives. Cut the role or sharpen its
  charter until its file could not have been written by anyone else.
- **Letting roles talk to the user.** They cannot: children have no
  `clarify`. A brief that expects mid-task questions produces a stalled or
  guessing role. Put decisions IN the brief; have roles log assumptions.
- **Integrating contradictions without a decision.** The design says wizard,
  the build ships tabs, the growth copy promises the wizard. Every conflict
  gets an explicit founder call written into the charter before the next
  wave — silence here compounds into an incoherent product.
- **Under-packed briefs.** "Design the app" with no charter, paths, or
  constraints wastes an entire role — the child knows nothing you do not
  pack in. Reread each brief asking: could a stranger execute this cold?
- **Judging your own work.** Skipping the quality role because you already
  "checked it" while integrating. You assembled it; you are blind to it.
- **Fan-out on dependent roles.** Batching the designer with the build (not
  the spike) means the engineer builds without a direction. Parallelism is
  a property of a wave, not a virtue: inputs on disk first.
- **Chat-only deliverables.** If the only copy of the design lives in a
  child's summary, it is already degraded. Files in the workspace, always.
