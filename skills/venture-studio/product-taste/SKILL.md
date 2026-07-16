---
name: product-taste
description: "Develop and apply product taste — build reference libraries of great products, critique with precise vocabulary, set explicit quality bars, and make taste-driven calls about what to build, keep, and cut. Use when the user asks whether a product feels right, wants an opinionated direction, or needs to choose between plausible options."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [taste, product-judgment, critique, quality-bar, curation, decisions]
    related_skills: [impeccable-craft, design, design-studio]
---

# Product Taste

Use this skill when the user needs a judgment call about product quality or
direction: "does this feel right?", "which of these should we build?", "what
would make this great instead of fine?", or "just pick one — be opinionated."
It turns taste from a vibe into an operation: a curated reference set, a
written point of view, falsifiable quality bars, a critique in precise
vocabulary, and a decision the user can hold you to later.

Do not use it for execution work. To design or build the surface itself, load
`design` with skill_view. To raise the finish of an already-decided artifact,
load `impeccable-craft` with skill_view. To run a structured multi-concept
exploration, load `design-studio` with skill_view. This skill decides what
deserves to exist and at what bar; the siblings make it exist.

## Route the request

| The user is asking | Do this |
|---|---|
| "Does this product or feature feel right?" | Run the full workflow; deliver the critique template below |
| "Pick a direction, be opinionated" | Steps 1-4, then one recommendation with a named runner-up and kill criteria |
| "What should we cut?" | Steps 1-3, then the subtraction pass in step 6 |
| "Set a quality standard for this project" | Steps 2-4; deliver the quality-bar template as a durable file |
| "Make this screen beautiful" | Wrong skill — load `design` with skill_view |
| "Polish this to a very high standard" | Wrong skill — load `impeccable-craft` with skill_view |
| "Explore several concepts before choosing" | Load `design-studio` with skill_view; feed this skill's quality bars into its judging round |

## Workflow

1. **Frame the call.** Write one sentence: what decision is being made, for
   which user, and what "great" buys that user. If the audience, domain, or
   stakes are unclear, ask the user two or three pointed questions before
   forming any opinion. Taste without a named user is just preference.
2. **Assemble a reference set.** Pick 3-5 exemplar products for this specific
   domain and write down why each one earns its place (rules below). Open the
   references in the browser and use them live — screenshots, flows, copy —
   rather than reciting reputation from memory.
3. **Extract a point of view.** Compress the reference set into 3-6 written
   principles, each stated as a tradeoff you are willing to pay for. Save
   them to a file in the repo (for example `notes/TASTE.md`) so later calls
   are consistent instead of moody.
4. **Set the quality bar.** Translate the point of view into falsifiable
   statements about the product — things a skeptic could test and prove
   wrong. Use the quality-bar template.
5. **Critique the candidate.** Walk the actual product or proposal — run it,
   click through it, read the copy aloud. Record specific observations tied
   to user effect, never bare verdicts. Use the critique template.
6. **Make the call — subtract first.** Decide what to build, keep, and cut.
   The default move is removal; addition must pay rent (rules below). State
   one recommendation, its strongest counterargument, and what evidence
   would change your mind.
7. **Close the loop.** If the user agrees, record the decision next to the
   quality bars. If the user overrides you, disagree-and-commit: note the
   reservation once, in writing, then execute their call at full quality.

## Assembling a reference set

A reference earns its place with a specific, nameable move — never with
general prestige. "Stripe, because it's great" teaches nothing. "Stripe's
docs, because every code sample is runnable against a test key within one
minute of landing on the page" is a move you can steal, test against, and
apply somewhere else.

Rules for the set:

- **Same economics as the target.** Judge an internal ops tool against great
  internal tools, not against consumer apps with hundred-person polish teams.
  A reference from mismatched economics sets a bar you cannot honestly meet
  or one far too low.
- **One near-miss.** Include a product that almost works and name exactly
  where it breaks. Negative space sharpens the bar more than a fourth hero.
- **Inspectable now.** Prefer references the user can open today. Use the
  browser to capture the specific screen or flow being cited; taste built on
  a remembered 2019 version of a product is stale.
- **One move per reference.** If a product earns its place for three reasons,
  you have not yet found the load-bearing one. Keep digging until each row
  names a single move.

Record the set as a table:

| Reference | The move that earns its place | What to steal | What to ignore |
|---|---|---|---|
| (product) | (one specific, observable move) | (the transferable principle) | (parts with mismatched economics) |

## Extracting a point of view

A principle is a preference stated as a tradeoff: "we favor X over Y, even
when it costs Z." If no reasonable team could adopt the reverse, it is not a
principle — "we value quality" is decoration; "we ship one workflow that
never breaks before we ship a second workflow" is a point of view. Aim for
3-6. More than six means nothing is actually being traded off. Write them to
a file, date them, and cite them by name when making later calls.

## Critique vocabulary

Every observation must connect what you saw to what it does to the user.
"I like it" and "it feels off" are placeholders for work not yet done.
Translate reflexes into mechanism and effect:

| Reflex verdict | Precise replacement |
|---|---|
| "Feels clunky" | "Completing one intent takes three confirmations; the effort exceeds the action's stakes" |
| "Feels cheap" | "Spacing and alignment vary across sibling elements, signaling that no one checked, so the user trusts the data less" |
| "Too busy" | "Four elements compete for the primary action; a first-time user cannot rank them, so they stall" |
| "Feels slow" | "No response within the first 100ms of the tap, so the user re-taps and fires the action twice" |
| "Confusing" | "The label promises one outcome and the behavior delivers another; the user's model breaks on step 2" |
| "Delightful" | "The empty state teaches the core loop in one line and one click, so activation needs no docs" |

Severity comes from user effect, not from how much the flaw bothers you:
blocks the core loop, then erodes trust, then adds friction, then cosmetic —
in that order.

## Quality bars

A quality bar is a falsifiable statement about the product plus the exact
procedure that tests it. If nobody can lose a bet about a bar, rewrite it.
"Onboarding should be delightful" is untestable; "a first-time user reaches
a saved result in under two minutes without opening docs" can be timed,
failed, and fixed.

````markdown
# Quality bars — [product / surface]
Point of view: [link to TASTE.md]   Date: [date]

## Bar: [falsifiable statement]
- Test: [exact procedure — commands to run, flow to click, what to measure]
- Current: PASS | FAIL | UNTESTED — [evidence: timing, screenshot, output]
- Owner check: [who or what re-verifies this and when]

## Bar: ...
````

Keep bars few (5-9), and prune any bar that has passed trivially for months —
it has stopped doing work.

## Critique template

Deliver critiques as a file the user can act on, not as chat prose:

````markdown
# Critique: [product / feature] — [date]
Frame: [the one-sentence decision and named user from step 1]
References consulted: [3-5, each with its earning move]

## What is working
- [specific observation → user effect] (keep; do not break in fixes)

## Findings (ordered by user effect)
1. **[observation]** — Mechanism: [why it happens]. Effect: [what it does
   to the user]. Severity: blocks-loop | erodes-trust | friction | cosmetic.
   Fix direction: [smallest change that resolves the effect].

## Subtraction candidates
- [element]: nothing observable breaks if removed — cut.

## The call
Recommendation: [one direction]. Runner-up: [name it and why it lost].
Strongest counterargument: [steelman]. Would change my mind: [evidence].
````

## Subtraction as the main move

When deciding what to build, keep, and cut, run removal before addition:

- For every element, ask: what observable thing breaks if this is gone? If
  the honest answer is "nothing", cut it. "Someone might want it" is not
  observable.
- One hero per surface. Each screen or flow gets one primary action; every
  additional call-to-action taxes the first.
- Additions pay rent: a new element must either serve a quality bar or
  retire an existing element. Net element count should trend flat.
- Cut whole features before degrading one. A product that does three things
  well beats one that does five things adequately — the reference set almost
  always confirms this.
- Write down what was cut and why, so the idea can return when evidence
  does. A recorded cut is reversible; a quiet one relitigates forever.

## Disagree-and-commit

State the recommendation plainly, with a confidence level and the evidence
that would flip it. If the user chooses differently: restate their call to
confirm you understood it, record your reservation once in the decision file,
then execute their direction at the full quality bar. No hedged half-effort,
no re-arguing the point without new evidence. When new evidence does arrive
(a failed bar, user complaints matching your reservation), raise it once,
citing the record — not "I told you so", but "the bar we wrote now fails."

## Common failure modes

- **Prestige laundering.** Citing a famous product without naming the move.
  If the row's second column is empty, the reference is decoration.
- **Taste as adjectives.** A critique full of "clean", "elegant", "dated"
  with zero user effects. Every finding must survive the "so what happens to
  the user?" question.
- **Unfalsifiable bars.** "Should feel fast" instead of a measured threshold
  with a test procedure. If a skeptic cannot run the test, it is not a bar.
- **Cross-economics comparison.** Holding a two-person team's internal tool
  to consumer-flagship polish, or excusing a consumer product with internal
  tool standards. Match the reference set's economics in step 2.
- **Addition bias.** Every critique round ending with more elements. If the
  subtraction-candidates section is empty twice in a row, you are decorating,
  not judging.
- **Both-sidesing the call.** Presenting balanced options when the user asked
  for a pick. The deliverable is one recommendation with a named runner-up.
- **Novelty worship.** Penalizing convention for being conventional.
  Conventions are compressed user learning; deviate only where the point of
  view says the tradeoff is worth the relearning cost.
- **Sandbagging after commit.** Executing an overridden decision at reduced
  quality. The reservation lives in the record, never in the work.
- **Moody consistency.** Re-deriving taste from scratch each session. Read
  the saved point of view and quality bars before every new call, and update
  them instead of contradicting them silently.
