---
title: "Proposal Writing"
sidebar_label: "Proposal Writing"
description: "Write winning proposals — client project proposals, statements of work, RFP responses, and partnership or grant pitches with discovery-driven structure, tier..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Proposal Writing

Write winning proposals — client project proposals, statements of work, RFP responses, and partnership or grant pitches with discovery-driven structure, tiered pricing, and clear scope boundaries. Use when the user needs to pitch work to a client, respond to an RFP, or turn a conversation into a signed engagement.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/venture-studio/proposal-writing` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `proposals`, `sow`, `rfp`, `pitch`, `pricing`, `sales` |
| Related skills | [`business-planning`](/user-guide/skills/bundled/venture-studio/venture-studio-business-planning), [`website-building`](/user-guide/skills/bundled/venture-studio/venture-studio-website-building) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Proposal Writing

Use this skill when the user needs to turn interest into a signed engagement — a client
project proposal, a statement of work, an RFP response, or a partnership or grant pitch.
The deliverable is a document a specific buyer can say yes to: framed around their
outcome, priced as options, and bounded tightly enough that the work stays profitable.

Do NOT use this for internal strategy, financial models, or market sizing — load
`business-planning` with skill_view instead. If the ask is to build the site or landing
page that presents the offer, load `website-building` with skill_view. This skill owns
the persuasion document itself, from discovery through signature and follow-up.

## Route the request

| Situation | Deliverable | Emphasis |
|---|---|---|
| Prospect call happened, no formal ask yet | Proposal (2-4 pages) | Their situation first, outcomes, three price tiers |
| Scope verbally agreed, needs paper | Statement of work | Deliverables, acceptance criteria, payment schedule, change process |
| Formal RFP with submission rules | RFP response | Mirror their structure, compliance matrix, evaluator ergonomics |
| Partnership or grant opportunity | Pitch memo | Shared upside or funder mission, credibility evidence, one concrete ask |

Proposals and SOWs often travel together: the proposal sells the decision, the SOW
survives it. When the user asks for "a proposal" for work that is already agreed,
confirm which document they actually need — frequently it is both.

## Workflow

1. **Discover.** Interview the user before drafting a line. Mine whatever exists: call
   notes, email threads, the RFP document, the prospect's website. Capture the buyer's
   own vocabulary verbatim — you will reuse it word for word.
2. **Qualify.** Decide with the user whether to bid at all. No budget signal, no access
   to the decision maker, and a column-fodder RFP are all reasons to decline or to send
   a one-page interest letter instead of a full proposal.
3. **Frame.** Write the outcome statement first — one sentence naming the business
   result the buyer gets, in their words. Everything else in the document exists to
   make that sentence credible.
4. **Draft.** Fill the skeleton below. Their situation before your solution, outcomes
   before activities, price only after value has been established.
5. **Price.** Build three options (see the pricing pattern). Anchor high, make the
   middle tier the obvious choice, and price the outcome rather than the hours where
   the engagement allows it.
6. **Bound.** Write the exclusions, assumptions, and change process with the same care
   as the pitch. Every ambiguous noun in scope becomes a free feature later.
7. **Review.** Re-read as the buyer's most skeptical stakeholder: strike self-praise,
   verify every number, and check that a reader who skims only headings and the
   pricing table still gets the full argument.
8. **Deliver and follow up.** Save to `proposals/YYYY-MM-DD-client-slug/` in the
   workspace, produce whatever format the buyer expects (markdown, PDF via pandoc, or
   a doc), and set the follow-up cadence before the proposal goes out.

## Discovery before drafting

Never draft from the user's summary alone. Ask, or extract from source material:

- **Their words for the problem.** What exact phrases did the buyer use? "Onboarding
  takes too long" and "churn in week one" are different proposals. Quote them.
- **The cost of the problem.** What does it cost per month in revenue, hours, or risk?
  This number sets the price ceiling and belongs in the opening section.
- **Decision process.** Who signs, who influences, who can veto? What is the buyer's
  stated timeline, and what happens on their side if nothing changes?
- **Budget signals.** Was a range named? What have they paid for similar work? If the
  user has no signal, add a qualification question to the follow-up plan rather than
  guessing low.
- **Success criteria.** How will the buyer know it worked 90 days after delivery?
- **Competing options.** Other vendors, in-house build, or doing nothing — the proposal
  must beat the strongest of these, and "do nothing" usually is.

If the user cannot answer the first two, recommend a short discovery call before the
proposal. A proposal written blind reads as generic and gets priced like a commodity.

## Structure that sells

Order matters more than eloquence. The reader should see themselves in the first
paragraph, the destination in the second, and your fee only after both.

- Open with **their situation** — problem, cost, and stakes in their vocabulary. No
  company history, no "we are pleased to submit."
- State **outcomes, not activities**: "cut invoice processing from 6 days to 1" beats
  "implement workflow automation." Put activities inside the SOW, not the pitch.
- Show **the path** briefly: 3-5 phases with what the buyer sees at the end of each.
- Present **investment as options**, never a single take-it-or-leave-it number.
- Close with **proof and next step**: one relevant result or reference, then the exact
  action that starts the engagement (signature, deposit, kickoff date).

Keep it short. Two to four pages wins against ten; length signals insecurity.

## Pricing as options

Single prices get negotiated; option sets get chosen from. Build three tiers where the
middle one is what you expect to sell:

| | Foundation | Growth (recommended) | Partner |
|---|---|---|---|
| Outcome | Core problem solved | Core plus measurement and iteration | Ongoing ownership of the result |
| Scope | Phases 1-2 | Phases 1-4 | Phases 1-4 + quarterly cycles |
| Timeline | 4 weeks | 8 weeks | 8 weeks, then continuous |
| Support | 2 weeks post-launch | 60 days | Ongoing |
| Investment | $X | $1.7-2X | $3X+ or monthly retainer |

Rules of thumb: the top tier exists to anchor — it must be real and deliverable, but
its main job is making the middle tier look reasonable. Differentiate tiers by outcome
and risk-coverage, not by arbitrarily withheld features. Never offer a tier the user
would resent delivering. Show payment terms next to price: a deposit (commonly 30-50%)
due at signature, remainder tied to milestones — not to open-ended "completion."

## Scope boundaries and assumptions

Scope creep is a writing failure before it is a client failure. Include, always:

- **In scope**: countable deliverables — "up to 5 page templates," "2 revision rounds
  per deliverable," "1 production deployment." Numbers, not adjectives.
- **Out of scope**: name the adjacent work the buyer will predictably ask for (content
  writing, historical data migration, third-party license fees, post-launch features)
  and state it is available under the change process.
- **Assumptions**: client provides brand assets by kickoff, one consolidated feedback
  channel, staging access within 5 business days, feedback returned within 3 business
  days or the timeline shifts day-for-day.
- **Change process**: any request outside the bullets above gets a short written change
  order with price and schedule impact, signed before work starts. Two sentences in the
  proposal; it will save the whole engagement.

## SOW essentials

When the decision is made and paper is needed, the SOW carries: parties and effective
date; deliverables as a numbered list with acceptance criteria per item ("deliverable
is accepted when [observable test]; feedback within N business days or it is deemed
accepted"); schedule with milestone dates; payment schedule tied to those milestones;
the change-order process; ownership and IP transfer terms (commonly upon final
payment); confidentiality; and termination terms (notice period, payment for work
completed). Flag to the user that a lawyer should review anything above their
comfort threshold — draft the business terms, do not play counsel.

## RFP responses

RFPs are graded, not read. Optimize for the evaluator with a scoring rubric:

- **Mirror their structure exactly.** Same section numbers, same headings, same order.
  If the RFP asks questions, answer each one under its own number — never make an
  evaluator hunt.
- **Build a compliance matrix** and put it up front:

| RFP requirement | Ref | Response | Where addressed |
|---|---|---|---|
| Vendor must support SSO (3.2.1) | 3.2.1 | Comply | Section 4, p. 6 |
| On-premise deployment (3.4) | 3.4 | Partial — hybrid offered | Section 5, p. 8 |

- Mark each requirement Comply / Partial / Exception, and explain every non-Comply
  honestly with a mitigation. Evaluators punish discovered gaps far harder than
  disclosed ones.
- Obey submission mechanics to the letter — page limits, fonts, file naming, deadline,
  portal. Compliant-but-plain beats brilliant-but-disqualified.
- Ask allowed clarifying questions early; the answers are intelligence competitors
  may not bother to collect.

## Follow-up cadence

The proposal is not delivered until a next step is scheduled. Default cadence to
propose to the user: (1) send the proposal, then request a 20-minute walkthrough call
within 2-3 business days — never "let me know your thoughts"; (2) if silent, follow up
on day 3 with one specific question ("does the Growth timeline work for your Q4
date?"); (3) day 7, share one new useful item — a relevant result, an answer to
something raised on the call; (4) day 14, a polite close-the-loop note naming a
proposal expiry date. Put a validity window (2-4 weeks) in the proposal itself so the
expiry is real. Offer to draft each follow-up message when the date arrives.

## Proposal skeleton

```markdown
# [Outcome-framed title, e.g. "Cutting invoice processing to one day"]
Prepared for [Client] · [Date] · Valid through [Date]

## Your situation
[2-3 paragraphs: their problem in their words, what it costs them, why now.]

## The outcome
[One bold sentence: the business result. Then 3-4 measurable success criteria.]

## How we get there
[Phase 1 — name]: [what the client sees at the end of it]
[Phase 2 — name]: [...]
[Phase 3 — name]: [...]

## Your investment
[Three-tier options table. Recommended tier marked. Payment terms below it.]

## What's included — and what's not
In scope: [countable deliverables]
Out of scope: [named adjacent work, available via change order]
Assumptions: [client-side responsibilities and response times]
Changes: [two-sentence change-order process]

## Why us
[One relevant result with a number. One reference. Nothing generic.]

## Next step
[Exact action: sign by X, deposit Y, kickoff Z. Who does what.]
```

## Common failure modes

- **Writing before discovery.** A proposal built from the user's one-line summary
  mirrors nobody's words and prices against nothing. Interview first, always.
- **Leading with yourself.** "About us" on page one tells the buyer the document is
  about you. Their situation opens; credentials appear once, late, with evidence.
- **Activity lists instead of outcomes.** Deliverables ("12 workshops") without the
  result they buy invite line-item shopping and price-cutting.
- **One price.** A single number turns the conversation into yes/no/negotiate. Options
  turn it into which-one.
- **Uncountable scope.** "Design support" and "reasonable revisions" are blank checks.
  Every scope line needs a number a stranger could audit.
- **Burying the price.** Hiding the number in an appendix reads as apologetic. Present
  it confidently after value, with tiers, on its own page or section.
- **Ignoring RFP mechanics.** A superb response in the wrong format, over the page
  limit, or an hour late scores zero. Compliance is the entry fee.
- **No expiry, no next step.** Open-ended proposals decay silently. Every proposal
  names a validity window and a scheduled conversation.
- **Overpromising to win.** A signed engagement the user cannot deliver profitably is
  a loss with extra steps. Sanity-check margin per tier before it ships.
