---
title: "Build Something People Want"
sidebar_label: "Build Something People Want"
description: "Startup methodology for making something people want — pick a real problem, run customer discovery interviews, scope a minimum lovable product, measure produ..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Build Something People Want

Startup methodology for making something people want — pick a real problem, run customer discovery interviews, scope a minimum lovable product, measure product-market fit signals, iterate, and launch. Use when the user wants to start a company, validate an idea, find first users, or asks why nobody is using their product.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/venture-studio/build-something-people-want` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `startup`, `product-market-fit`, `mvp`, `customer-discovery`, `validation`, `launch` |
| Related skills | [`business-planning`](/user-guide/skills/bundled/venture-studio/venture-studio-business-planning), [`brainstorming`](/user-guide/skills/bundled/venture-studio/venture-studio-brainstorming), [`d2c-smart-products`](/user-guide/skills/bundled/venture-studio/venture-studio-d2c-smart-products) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Build Something People Want

Use this skill when the user wants to start a company, validate an idea, find
first users, or figure out why nobody uses what they built. It is the front
door for the zero-to-one arc: problem selection, customer discovery, minimum
lovable product scoping, first-100-user launch, product-market fit
measurement, and the iterate-or-pivot call.

Do NOT use this skill when the user needs a formal business plan, financial
model, or investor deck — load `business-planning` with skill_view. When they
have no idea yet and want to generate candidates, load `brainstorming` with
skill_view first, then return here to validate the shortlist. For physical or
connected consumer products, also load `d2c-smart-products` with skill_view —
the method here applies, but hardware adds supply and margin constraints.

## Route by stage

| The user says | Stage | Enter at step |
|---|---|---|
| "I want to start something" / "is this idea any good?" | Idea | 1 |
| "People I talked to seemed excited" | Discovery | 2 |
| "Should I build X or Y first?" | Scoping | 4 |
| "How do I get my first users?" | Launch | 5 |
| "I built it but nobody uses it" | Pre-PMF diagnosis | 6, then back to 2 |
| "Growth is flat — pivot?" | Decision | 7 |

Persist artifacts under `discovery/`: one file per interview, `assumptions.md`,
`mlp-scope.md`, and `traction/` for weekly reviews. Chat is not a filing system.

## Workflow

1. **Pick the problem.** Score candidates on founder-problem fit and
   frequency x intensity (below). Kill weak candidates before interviewing.
2. **Map assumptions.** Write `discovery/assumptions.md`: every belief the
   idea depends on, ranked by fatality x uncertainty. Top item goes first.
3. **Interview.** Run 10-15 discovery interviews per segment with the script
   template below; draft outreach, source interviewees, write up same day.
4. **Synthesize and scope.** Extract patterns, then scope the minimum lovable
   product: the smallest thing that tests the riskiest surviving assumption
   with real usage, not the smallest version of the full vision.
5. **Launch to the first 100.** Manual, unscalable recruitment. Instrument
   activation and retention from day one — even a spreadsheet counts.
6. **Measure PMF signals.** Cohort retention curves, the very-disappointed
   survey, and organic pull. Run the weekly traction review.
7. **Iterate or pivot.** Change one axis at a time based on evidence, or
   double down when the curves say so.

## Problem selection

Before any interview, pressure-test the problem itself:

- **Founder-problem fit.** Has the user lived this problem, or do they have
  unfair access to the people who have? Will they still care in five years?
  "I read that this market is big" is borrowed conviction — flag it.
- **Frequency x intensity.** Ask where the problem sits:

| | Low intensity | High intensity |
|---|---|---|
| **Low frequency** | Walk away | Hard: urgency exists but recall and reach are poor (insurance-shaped) |
| **High frequency** | Nice-to-have; monetization will fight you | Build here — daily pain people already pay or hack around |

- **Existing spend test.** Are people already paying money, time, or hacked-up
  spreadsheets to cope? Zero current workaround usually means no real problem.

Write the surviving problem statement as one sentence naming a specific person:
"[Segment] struggles to [job] because [obstacle], and currently copes by
[workaround]."

## Customer discovery interviews

The purpose is to learn facts about the interviewee's life, not to collect
opinions about the idea. Enforce three rules in every script you draft:

1. **Past behavior, not hypotheticals.** "Walk me through the last time you
   dealt with this" beats "would you use a tool that…" every time — people
   are honest historians and terrible forecasters.
2. **Never pitch.** Once you describe the product, every answer after it is
   polite noise. If a demo must happen, hold it after the discovery questions.
3. **Compliments are noise; commitments are signal.** "Cool idea!" costs
   nothing. Time (a follow-up meeting), reputation (an intro to their boss), or
   money (a preorder) are the only answers that count.

Agent tasks here: draft the outreach message, generate each session's script
from the template, and write the scorecard within an hour of the session.

```markdown
# Discovery interview — [name], [segment/role], [date]

**Assumption under test:** [A1 from assumptions.md]

## Warm-up (2 min)
- Their role, their week, where this job fits in it.

## Past behavior (15 min — the core)
- "Walk me through the last time you [did the job]."
- "What did you try before that? What happened?"
- "What do you use today? What did it cost you — money, time, favors?"
- "When it went wrong, what did that cost?"
- Follow every vague answer with "tell me about the specific time."

## Prioritization (5 min)
- "Of everything on your plate, where does this rank? What's above it?"

## Commitment ask (2 min)
- Ask for something that costs them: a follow-up, an intro, pilot data,
  or a card on file for early access. Note exactly what they agree to.

## Scorecard (fill immediately after)
- Problem raised unprompted: yes / no
- Current workaround and its real cost: ...
- Intensity (1-5, from evidence not enthusiasm): ...
- Commitment secured: none / follow-up / intro / pilot / money
- Verbatim quotes worth keeping: ...
```

Stop interviewing a segment when the last three sessions taught you nothing
new. Ten consistent stories beat forty scattered ones.

## Scoping the minimum lovable product

Return to `assumptions.md`. The MLP exists to test the riskiest assumption that
interviews could not settle — usually "will they actually change behavior,"
which only shipped software answers. Match the test to the assumption:

| Riskiest assumption | Cheapest honest test |
|---|---|
| People want the outcome at all | Landing page + concrete offer; measure signups against real traffic |
| They'll pay | Presale or signed pilot agreement before building |
| The workflow fits their life | Concierge: deliver the service manually for 5 users |
| The hard part is automatable | Wizard-of-oz front end, humans behind the curtain |
| Retention survives week 2 | Single-feature build, instrumented, for one cohort |

Scope rule: cut every feature that does not bear on the assumption, then make
what remains feel finished — small and polished converts; broad and broken
teaches nothing because users bounce off bugs, not off the value proposition.
Write `discovery/mlp-scope.md`: assumption, test, cut list, and a pass/fail
threshold agreed with the user before building starts.

## First 100 users

Do things that don't scale. In order of typical yield:

1. **Direct outreach** from the founder's own account to people matching the
   interview profile — draft 20 personalized messages, not one blast.
2. **Existing watering holes** — forums, group chats, and communities where
   the segment already complains about the problem. Contribute, then invite.
3. **Interviewees first.** Everyone who gave a commitment during the
   discovery interviews (step 3) gets white-glove onboarding, ideally live.
4. **Launch platforms and niche newsletters** — useful for a spike of
   trialists, but treat that traffic as a retention test, not a win.

Founder-led onboarding for the entire first cohort: watch each user hit the
core action, log where they stall, fix the top stall weekly. Define activation
as one concrete event ("invited a teammate") and count it by hand if needed —
a script over server logs or a shared sheet is enough at this scale.

## Measuring product-market fit

Three signal families, strongest first:

- **Retention curves that flatten.** Plot each weekly signup cohort's activity
  over time (write the script; a CSV and 30 lines of code suffice). A curve
  that plateaus above zero means some group can't stop using it — find who
  they are and narrow toward them. A curve sliding to zero means no amount of
  top-of-funnel fixes the business.
- **The very-disappointed survey.** Ask users active at least twice in the
  past two weeks: "How would you feel if you could no longer use this?" —
  very / somewhat / not disappointed. Above roughly 40% "very disappointed" is
  the classic PMF benchmark; below it, mine the "somewhat" group for what is
  missing. Never survey tourists — one-visit users dilute the reading.
- **Organic pull.** Unpaid signups mentioning a friend, inbound feature
  requests phrased as "when will you…", complaints during downtime, users
  stretching the product past its intended use. Log these verbatim in the
  weekly review; their absence after months of iteration is itself data.

```markdown
# Traction review — week of [date]

## Numbers
| Metric | Last week | This week | Notes |
|---|---|---|---|
| New signups (organic / outreach) | | | |
| Activated (core action) | | | |
| Week-2+ retained actives | | | |
| Very-disappointed % (if surveyed) | | | |

## Cohort snapshot
- Oldest cohort curve: flattening / still decaying / dead

## Shipped this week
- ...

## Learned this week (evidence, not vibes)
- ...

## Top stall in onboarding and the fix shipping next
- ...

## Decision
- Continue current bet / adjust [one axis] / trigger pivot review
```

## Iterate or pivot

Set the review cadence and kill criteria with the user in advance — deciding
under disappointment produces thrash. Then apply:

- **Iterate** when the problem is confirmed (interviews show intensity, some
  cohort retains) but activation, channel, or pricing leaks. Change one thing
  per cycle and re-measure.
- **Pivot** when the evidence says the problem is weak — low intensity in
  interviews, no workarounds found, retention at zero across cohorts despite
  onboarding fixes. Pivot along one axis only: same problem/new solution, same
  solution/new segment, or same segment/new problem (often the adjacent pain
  interviews kept surfacing). A full reset is a new idea; return to step 1.
- **Double down** when a sub-segment's curve flattens high: narrow the
  positioning to them, raise prices before adding features, then widen.

## Common failure modes

- **Pitching in interviews.** The user "validates" with a demo and a nodding
  head. Strip the pitch; re-run with past-behavior questions.
- **Counting compliments.** Ten "I'd totally use that" with zero commitments
  is a rejection delivered politely.
- **Building before talking.** Months of code to avoid ten conversations.
  The interviews are cheaper than the rewrite.
- **MVP as compressed vision.** Shipping a thin slice of everything instead of
  a complete test of one assumption — broad and broken teaches nothing.
- **Vanity metrics.** Signups and page views up, retained actives flat. The
  weekly review template exists to make this visible.
- **Averaging across segments.** Two audiences with opposite needs produce
  lukewarm aggregate data; split every metric by segment before concluding.
- **Scaling acquisition before retention flattens.** Paid growth on a leaky
  bucket burns money to manufacture bad news later.
- **Pivot ping-pong.** Changing segment, problem, and solution simultaneously
  destroys the ability to learn which change mattered.
- **No kill criteria.** Without pre-agreed thresholds, every review ends in
  "one more month." Write the thresholds in `mlp-scope.md` on day one.
