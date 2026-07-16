---
title: "Design Studio"
sidebar_label: "Design Studio"
description: "Facilitate a design-studio sprint — frame the brief, gather references, generate several distinct concept directions in parallel, critique against explicit c..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Design Studio

Facilitate a design-studio sprint — frame the brief, gather references, generate several distinct concept directions in parallel, critique against explicit criteria, converge, and hand off an implementation-ready spec. Use for open-ended design exploration; for building the final UI itself, load the design skill.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/venture-studio/design-studio` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `design-studio`, `concepts`, `critique`, `moodboard`, `divergence`, `workshop` |
| Related skills | [`design`](/user-guide/skills/bundled/creative/creative-design), [`brainstorming`](/user-guide/skills/bundled/venture-studio/venture-studio-brainstorming), [`product-taste`](/user-guide/skills/bundled/venture-studio/venture-studio-product-taste) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Design Studio

Use this skill when the user wants **open-ended design exploration** — "explore
some directions for the onboarding flow", "I don't know what this dashboard
should look like", "give me a few concepts before we commit". The studio method
trades one premature answer for several genuinely different ones, then earns
convergence through critique against written criteria. The deliverable is a
decision plus an implementation-ready spec, never the final UI itself.

Do not use this when the direction is already decided and the user wants the
interface built — skip straight to loading `design` with skill_view. Do not use
it for idea generation that has no designed surface (names, feature lists,
positioning) — load `brainstorming` with skill_view. When you need to calibrate
what "good" even looks like in this product category before judging anything,
load `product-taste` with skill_view first and carry its criteria into the brief.

## Workspace

Keep every studio artifact as ordinary files so the exploration survives the
session. Create a sprint directory in the active workspace:

```
.fabric/studio/<slug>/
  brief.md          the one-page brief (step 1)
  moodboard.md      annotated references (step 2)
  concepts/         one directory per direction (step 3)
    a-<name>/
    b-<name>/
  critique.md       scoring and round notes (step 4)
  spec.md           handoff spec for the winner (step 6)
```

Never keep the only copy of a concept in chat state.

## Workflow

1. **Frame** — interview the user, write the one-page brief, get sign-off.
2. **Reference** — gather 5-10 annotated references into a moodboard.
3. **Diverge** — produce 3-5 genuinely distinct concept directions in parallel.
4. **Critique** — score every direction against the brief criteria, in rounds.
5. **Converge** — pick one direction, graft the best elements from the losers.
6. **Specify** — write the handoff spec.
7. **Route** — hand the spec to `design` for construction.

Each step gates the next. Do not diverge before the brief is signed off, and do
not converge before at least one full critique round has run.

### 1. Frame the brief

Ask the user targeted questions until you can fill every section below without
guessing: who is this for, what must it achieve, how will we know a direction
is better than another, and what is off the table. Three to six questions is
usually enough; batch them in one message. Then write `brief.md`:

```markdown
# Studio Brief: <project>

## Problem
One paragraph. What is broken or missing today, in the user's words.

## Audience
Who uses this surface, in what context, with what prior knowledge.

## Success criteria
3-6 numbered, testable criteria. Every critique round scores against
exactly these. Example: "1. A first-time visitor can state what the
product does within 5 seconds."

## Constraints
Hard limits: brand, stack, accessibility floor, timeline, must-keep
elements, legal. Anything not listed here is negotiable.

## Explicitly out of scope
What this sprint will not decide.
```

Show the brief to the user and get explicit sign-off before continuing. The
criteria are the contract for the whole sprint — vague criteria here means
unfalsifiable critique later.

### 2. Gather references

Build `moodboard.md` with 5-10 references. Use web search and page fetches for
live products, and screenshot or quote what matters. For each reference record:
source, what specifically to steal (a layout rhythm, a density choice, a color
strategy), and what to avoid from the same source. Pull at least two references
from *outside* the product's category — the best divergence fuel is usually
adjacent, not competitive. Never plan to copy a reference's identity or content;
references supply vocabulary, not assets.

### 3. Diverge: 3-5 distinct directions

Produce 3-5 concept directions. **Distinct means different theses, not
different paint.** Two concepts that share a layout and differ in accent color
are one concept. Force distinctness by assigning each direction a different
position on at least two axes:

| Axis | Pole A | Pole B |
|---|---|---|
| Density | Editorial, spacious | Instrument panel, dense |
| Guidance | Opinionated single path | Open workspace, user-driven |
| Tone | Warm, human, illustrated | Precise, technical, typographic |
| Structure | Linear narrative flow | Hub with satellites |
| Motion | Still, print-like | Alive, state always in transition |

For each direction create `concepts/<letter>-<name>/` containing a card and a
rough artifact. The card:

```markdown
# Concept <letter>: <evocative name>

## Thesis
One sentence: the bet this direction makes about the audience.

## Axes
Density: ... | Guidance: ... | Tone: ... (positions, not adjectives)

## What it looks like
3-5 sentences walking the primary screen top to bottom.

## Strongest against criteria
Which brief criteria this direction should win, and why.

## Known weakness
The criterion it will likely lose. Name it before critique does.

## Rough artifact
Path and one line on what it shows.
```

The rough artifact is a timeboxed sketch, not a build: a single-file HTML page
with hardcoded content, or an annotated wireframe description in markdown.
Spend roughly equal effort on each direction — an artifact-quality gap rigs the
critique. If subagent delegation is available, fan the directions out in
parallel with one subagent per concept, giving each the brief, the moodboard,
and its assigned axis positions.

### 4. Critique rounds

Critique in `critique.md`, one section per round. A round has three moves:

1. **Score.** Rate every concept against every brief criterion, 1-5, with a
   one-line justification per cell. Present as a table:

   | Criterion | A: Ledger | B: Atlas | C: Pulse |
   |---|---|---|---|
   | 1. Instant comprehension | 4 — headline does the work | 2 — map needs decoding | 3 |
   | 2. Scales to 100 items | 2 | 5 — clustering built in | 4 |

2. **Steelman.** Before eliminating anything, write the strongest honest case
   for the *lowest-scoring* concept. If the steelman reveals a criterion the
   brief missed, stop and amend the brief with the user before proceeding.
3. **Cut and harvest.** Eliminate the weakest direction, but record its
   graftable elements — any cell where it scored highest — in a "harvest" list.

Show scores to the user between rounds and invite disagreement; their gut
reaction against a score is signal about the brief, not noise. Run rounds until
two directions remain, then run one head-to-head round on the top criteria only.

### 5. Converge

Pick the winner by total against the criteria, with the user breaking ties.
Then graft: walk the harvest list and adopt any element that improves the
winner *without breaking its thesis*. A graft that dilutes the thesis is
rejected even if it scored well in isolation — note the rejection and the
reason. Update the winner's concept card to reflect the grafted final form and
confirm the composite with the user.

### 6. Handoff spec

Write `spec.md` so that a builder with zero sprint context can construct the
surface without reopening any decision:

```markdown
# Spec: <project> — <winning concept name>

## Decision
Winning thesis in one sentence, plus the 2-3 grafted elements and
their source concepts.

## Screens and states
Per screen: layout walkthrough, key components, empty/loading/error
states, responsive behavior.

## Visual direction
Type scale intent, color strategy, density, motion policy — as intent
plus pointers to moodboard entries, not a full token set.

## Rejected directions
One line each: name, thesis, decisive criterion it lost on.

## Open questions
Anything deferred to build time, each with a suggested default.
```

The "rejected directions" section is not ceremony — it prevents the build phase
from accidentally re-litigating a settled question.

### 7. Route to build

Hand off construction: load `design` with skill_view and give it `spec.md` plus
the moodboard. The `design` skill composes the specialist build skills (artifact
construction, `design-md` contracts, named references) — do not reimplement its
workflow here, and do not let the studio sprint drift into polishing production
UI. If build reveals that a spec decision is unworkable, return to step 5 with
the new constraint rather than improvising a new direction mid-build.

## Common failure modes

- **Variations masquerading as directions.** Three concepts with the same
  layout and different fonts. Test: if you can describe two concepts' theses in
  one sentence, merge them and generate a real alternative.
- **Diverging before the brief is signed.** Concepts generated against a fuzzy
  brief get judged by whim, and the sprint decays into "show me more options."
- **Criteria written after the concepts.** Retro-fitted criteria always crown
  the facilitator's secret favorite. Criteria are frozen at step 1; amending
  them mid-sprint requires the user's explicit agreement, logged in the brief.
- **Uneven artifact fidelity.** The direction that got the polished sketch wins
  regardless of merit. Timebox each artifact identically.
- **Critique as vibes.** "B feels stronger" is not a score. Every judgment must
  cite a numbered criterion; anything else is a brief defect to fix upstream.
- **Convergence by committee blend.** Averaging all concepts into one produces
  a thesis-free mush. Pick one spine, graft selectively, reject grafts that
  fight the thesis.
- **Skipping the steelman.** The cheapest insurance in the method. Most
  amended-brief moments come from defending the losing concept honestly.
- **Building the winner inside the studio.** The sprint ends at `spec.md`.
  Construction belongs to `design`; a studio that ships UI has skipped the
  handoff and lost the spec discipline that makes the build reviewable.
