---
name: brainstorming
description: "Structured brainstorming and ideation sessions — diverge with SCAMPER, reverse brainstorming, crazy-8s and analogy prompts, then converge with affinity mapping and weighted scoring into ranked, testable concept briefs. Use when the user wants to generate ideas, name options, explore a problem space, or kick off a new product, feature, campaign, or company."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [brainstorming, ideation, scamper, crazy-8s, divergent-thinking, workshop]
    related_skills: [design-studio, build-something-people-want, business-planning]
---

# Brainstorming

Use this skill when the user wants to generate options rather than execute a
known one: exploring a problem space, naming something, kicking off a new
product, feature, campaign, or company, or simply getting unstuck. It is the
front door for ideation in the venture-studio track — everything downstream
assumes the ranked, testable concept pipeline this skill produces.

Do NOT use this skill when the concept is already chosen. If the user has a
concept and wants it shaped into a product or brand, load `design-studio` with
skill_view. If they want one specific idea pressure-tested against real
demand, load `build-something-people-want` with skill_view. If they need a
market model, financials, or a plan document, load `business-planning` with
skill_view. Brainstorming ends where commitment begins.

## Workflow

Run every session through this loop. Steps 3-5 may repeat if the first pass
produces a thin or samey pool.

1. **Frame** — turn the topic into one sharp generative prompt.
2. **Set the mode** — interactive workshop, solo generation, or hybrid.
3. **Diverge** — 2-4 rounds of volume-first generation, judgment deferred.
4. **Cluster** — affinity-map the raw pool into named themes.
5. **Converge** — dot-vote or score the pool down to 3-5 survivors.
6. **Brief** — write a one-page concept brief per survivor, each with its
   riskiest assumption and the cheapest test that could kill it.
7. **Hand off** — save all artifacts and route to the next skill.

### 1. Frame the prompt

Rewrite the user's topic as a "How might we..." question — broad enough to
admit surprising answers, narrow enough that answers are comparable.

- Too broad: "How might we improve healthcare?"
- Too narrow: "How might we add a reminder button to the settings page?"
- Right: "How might we get patients to actually finish a course of physio
  exercises at home?"

Ask the user to confirm the framing before generating anything, and capture
constraints explicitly (budget, team, timeline, tech, brand). Constraints are
fuel for later rounds, not fences around round one.

Create a working directory for the session and start the log:

```
.fabric/brainstorms/YYYY-MM-DD-[slug]/
    session.md      (prompt, constraints, rounds, pool, clusters, scoring)
    briefs/         (one file per surviving concept)
```

### 2. Set the mode

| Signal | Mode | How it runs |
|---|---|---|
| User is present, responsive, says "let's brainstorm" | Interactive | Facilitate: run one round at a time, show output, collect their additions and reactions between rounds |
| User is async, or asks "give me ideas" | Solo | Generate all rounds yourself, then present the clustered pool with your scoring for the user to overrule |
| User is present but cold-starting | Hybrid | Solo-generate a warm-up wall of 15-20 ideas, then switch to interactive rounds on top of it |

Interactive rules: add every user idea to the pool verbatim and numbered, no
critique during divergence. If the user converges early ("oh, I like #7"),
mark it as a favorite and finish the round — early lock-in is the most common
way sessions die. Two thin responses in a row means switch technique or drop
to hybrid.

Solo rules: still run distinct rounds with distinct techniques. A single
50-idea dump collapses into one mental groove; separate rounds force separate
grooves. Generating from 2-3 different user personas per round helps.

### 3. Diverge

Rules that hold across every round: volume before quality, judgment deferred,
every idea numbered and one line long (`N. [name] — [one sentence]`), build on
earlier ideas rather than only replacing them, and deliberately include a few
bad or illegal-under-constraints ideas — they mark the edges of the space.

| Technique | Mechanism | Best for | Target per round |
|---|---|---|---|
| Free listing | Unfiltered warm-up dump | Opening any session | 15-20 |
| SCAMPER | Substitute, Combine, Adapt, Magnify/minify, Put to other uses, Eliminate, Reverse — applied to an existing product or process | Improving something that already exists | 10-14 (aim for 2 per letter) |
| Reverse brainstorming | List ways to cause or worsen the problem, then invert each into a fix | Stuck sessions; process and service problems | 10+ inversions |
| Crazy-8s | Eight distinct concepts in one fast pass, roughly a minute of thought each, no elaboration | Forcing structural variety; product and UI concepts | Exactly 8 |
| Analogy prompts | "How would [a hospital / a casino / a courier network / a game studio] solve this?" | Breaking domain fixation | 6-10 across 2-3 analogies |
| Constraint flips | Remove or invert one captured constraint: what if it were free? 10x the price? no screen? shipped in a day? | Testing whether constraints are real | 6-10 |

Pick 2-4 techniques per session. Quantity targets for the total pool before
converging: 40-60 ideas for company- or product-scale prompts, 25-40 for a
feature or campaign, 15-25 for a naming exercise. If the pool is under target
or reads as variations on one theme, run one more round using the technique
most unlike the ones already used.

Log every round in `session.md` as it completes — technique, count, and the
numbered ideas. The raw pool is a deliverable, not scaffolding.

### 4. Cluster (affinity mapping)

Read the full pool and group ideas by underlying job or mechanism, never by
surface features. Aim for 4-8 clusters; each cluster gets a noun-phrase name
that could plausibly title a strategy ("ambient accountability", "pay-per-
outcome tooling"). Merge duplicates but record the merge count — repeated
independent arrival is weak evidence of gravity. Keep genuine orphans in a
`wildcards` cluster instead of force-fitting them.

In interactive mode, present the clustering and let the user rename, split,
or merge before any scoring happens.

### 5. Converge

Choose one of two mechanisms:

- **Dot vote** — fast, for interactive sessions. Give the user N votes where
  N is half the cluster count rounded up; they may stack votes. You vote too,
  but reveal yours only after theirs to avoid anchoring.
- **Weighted scoring matrix** — for solo sessions or high-stakes prompts.
  Agree the criteria and weights BEFORE any scores are revealed, then score
  each cluster's strongest concept 1-5 per criterion.

Default matrix (adjust weights with the user, keep 3-5 criteria):

| Concept | Impact x3 | Feasibility x2 | Novelty x1 | User excitement x2 | Total /40 |
|---|---|---|---|---|---|

Prefer concepts that spike on one or two criteria over concepts that score a
flat 3 on everything — brainstorm output should be interesting, not merely
safe. Keep 3-5 survivors: fewer than 3 means you converged too hard for this
stage; more than 5 means the briefs will be thin.

### 6. Write concept briefs

One page per survivor, saved to `briefs/[slug].md`, using this skeleton:

```markdown
# Concept: [name]

**One-liner:** [what it is, for whom, in one sentence]
**Origin:** [round and technique it emerged from; idea numbers merged in]
**Who it serves:** [specific person or segment, not "everyone who..."]
**How it works:** [3-5 sentences of mechanism — the walk through a real use]
**Why now / why us:** [what changed, or what unfair advantage applies]
**Nearest neighbors:** [2-3 existing solutions and the one-line difference]
**Riskiest assumption:** [the single belief that, if false, kills this]
**Cheapest test:** [runnable in under a week on trivial budget]
**Kill criteria:** [the concrete test result that means: drop it]
**Score:** [total/40, rank N of M] or [dot votes received]
```

The riskiest assumption is usually about demand or behavior, not technology —
"clinics will pay per recovered patient" beats "we can build the mobile app".
Phrase it so it can actually be false; "users want convenience" cannot fail
and is therefore worthless. Cheapest tests to reach for: a landing-page smoke
test with a signup form, 5 problem interviews with the target segment, a
concierge or wizard-of-oz run, a fake-door button in an existing product, or
two ad variants against the same audience. You can draft the interview script
or landing copy on the spot if the user wants to run the test immediately.

### 7. Hand off

Present the briefs ranked, with the scoring table and a one-paragraph
recommendation. Then route: load `design-studio` with skill_view to shape a
chosen concept into a product or brand, `build-something-people-want` with
skill_view to run its cheapest test against real demand, or
`business-planning` with skill_view if the winner implies a company. Confirm
`session.md` contains the prompt, every round, the full pool, the clusters,
and the scoring — a future session should be able to resume from it cold.

## Common failure modes

- **Converging during divergence.** Evaluating ideas as they land halves the
  pool and biases it toward the obvious. Defer all judgment to step 5.
- **Fifty shades of one idea.** The pool is 40 variations of the first
  concept. Fix by switching to the most dissimilar technique — usually
  analogy prompts or constraint flips — not by generating more of the same.
- **Prompt at the wrong altitude.** Too broad and ideas are incomparable; too
  narrow and the session is feature-polishing. Reframe and restart rather
  than pushing through — a bad prompt taxes every later step.
- **Criteria invented after scoring.** Choosing weights once favorites are
  known is rationalization wearing a spreadsheet. Lock the matrix first.
- **Feasibility bias.** Solo-generated pools overweight what is easy to
  build. Keep novelty and excitement in the matrix and protect at least one
  wildcard through to the brief stage.
- **Briefs without teeth.** A riskiest assumption that cannot be false, or a
  "cheapest test" that takes a quarter, means the brief is decoration. Every
  brief must name a result that would kill the concept.
- **Losing the pool.** Saving only the survivors throws away reusable raw
  material; losing rounds this week seed winning rounds next quarter.
- **Treating the user's opener as the framing.** "We should brainstorm names
  for the app" often hides "we're not sure what the app is". Probe once
  before accepting the stated prompt.
