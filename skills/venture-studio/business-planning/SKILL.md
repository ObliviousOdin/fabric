---
name: business-planning
description: "Turn an idea into a credible business plan — lean canvas, market sizing (TAM/SAM/SOM), competitive landscape, unit economics, financial projections, and an investor-ready narrative. Use when the user asks for a business plan, pitch material, a revenue model, or wants to sanity-check whether a business can work."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [business-plan, lean-canvas, unit-economics, financial-model, market-sizing, pitch]
    related_skills: [build-something-people-want, proposal-writing]
---

# Business Planning

Use this skill when the user brings an idea — a napkin sketch, a side project, an internal venture — and needs it turned into something a skeptical reader would fund, lend to, or approve. The output is a chain of connected artifacts: a one-page lean canvas, a defensible market size, a positioning read on competitors, unit economics with real formulas, a driver-based projection, and a narrative tuned to the audience. Every number must trace back to an assumption the user can point at and change.

Do not use this skill for product discovery or validating whether anyone wants the thing — load `build-something-people-want` with skill_view for that; a business plan built on an unvalidated problem is fiction with a spreadsheet attached. For writing a client proposal, RFP response, or grant application, load `proposal-writing` with skill_view instead.

## Route the request

| Request | Deliverable | Depth |
|---|---|---|
| "Can this business work?" / sanity check | Lean canvas + unit economics only | 1 pass, flag the riskiest boxes |
| Pitch material for investors | Canvas, sizing, landscape, economics, projection, deck-ready narrative | Full workflow |
| Loan application or bank package | Canvas, conservative projection, cash flow and debt-service focus | Full workflow, downside-weighted |
| Internal business case | Canvas, sizing, economics, milestones and kill criteria | Full workflow, opportunity-cost framing |
| "Build me the financial model" | Spreadsheet or code model from the projection skeleton | Steps 5-6 only |

If the user only wants one artifact (e.g. "just the TAM"), do that step alone — but state which upstream assumptions you had to invent, so they know what's load-bearing.

## Workflow

1. **Intake.** Ask what the business is, who pays, what it costs to deliver, and who the plan is *for* (investor, bank, boss, self). The audience changes the narrative and the tone of the numbers. If the user can't answer "who pays", stop and route to `build-something-people-want`.
2. **Lean canvas.** Draft the one-pager from the template below. Fill every box with the user's answers where you have them and explicit guesses where you don't. Mark the 2-3 boxes where a wrong guess kills the business as **RISKIEST** — everything downstream exists to pressure-test those boxes.
3. **Size the market bottom-up.** Count reachable buyers, multiply by a realistic price, apply a defensible penetration rate. Only then triangulate with top-down TAM from analyst reports found via `web_search`. If bottom-up and top-down disagree by more than 5x, the segmentation is wrong — fix it before proceeding.
4. **Map the competitive landscape as positioning.** Research 5-10 alternatives (including "do nothing" and spreadsheets/manual work). Choose two axes the *buyer* actually decides on, place everyone, and state the open position this business claims.
5. **Compute unit economics.** CAC, contribution margin, LTV, payback — with the formulas below, using the user's real or estimated inputs. If LTV:CAC or payback fails its benchmark, say so plainly and identify which input would have to change.
6. **Build the driver-based projection.** Three years, monthly for year 1 and quarterly after, driven by 3-5 explicit drivers from the skeleton below. Build the actual model with code tools — a Python script emitting CSV/XLSX (e.g. openpyxl or pandas) beats a hand-typed table, and the user can rerun it with new assumptions. Run it once and eyeball the outputs for absurdities.
7. **Write the narrative for the audience.** Use the arc table below. The same numbers get a different story for an investor than for a bank.
8. **Deliver and stress-test.** Save all artifacts as files in the workspace (never chat-only). Walk the user through the three assumptions most likely to be wrong and what each one breaks.

## Lean canvas (step 2)

One page, nine boxes, guesses allowed, blanks not. Deliver as `canvas.md`:

```markdown
# Lean Canvas: {venture name} — {date}

## Problem (top 3)                          [RISKIEST?]
1. ...
2. ...
3. Existing alternatives: ...

## Customer segments                        [RISKIEST?]
- Target segment: ...
- Early adopters (narrower): ...

## Unique value proposition
Single sentence: why this, for them, over alternatives.

## Solution (top 3 features only)
1. ...

## Channels
How you reach the early adopters, concretely: ...

## Revenue streams                          [RISKIEST?]
- Pricing model: ...  Price point: ...  Who signs the check: ...

## Cost structure
- Fixed: ...  Variable per unit/customer: ...

## Key metrics
The 2-3 numbers that prove the model is working: ...

## Unfair advantage
What cannot be easily copied or bought (real answer or "none yet"): ...
```

Tag at most three boxes RISKIEST, with one line each on what evidence would de-risk them. "None yet" is an acceptable unfair advantage; a vague one ("great team", "first mover") is not.

## Market sizing (step 3)

Bottom-up is the primary estimate; top-down is only a plausibility check.

- **TAM** — everyone who could conceivably buy this category, annual spend.
- **SAM** — the slice your channels and product can actually serve (geography, segment, language, compliance).
- **SOM** — what you can realistically win in 3-5 years given competition and sales capacity.

Bottom-up formula: `SOM = (# reachable target accounts) x (realistic annual price) x (penetration %)`. Every factor needs a source: census/industry data via `web_search`, directory or registry counts, comparable-company penetration. Show the arithmetic in the plan, not just the result. A SOM above ~10% of SAM in year 3 needs an extraordinary justification; write down why or lower it.

## Competitive landscape (step 4)

The deliverable is a positioning claim, not a feature checklist. Format:

| Alternative | What the buyer pays | Strength | Where it loses |
|---|---|---|---|
| Incumbent A | ... | ... | ... |
| Point tool B | ... | ... | ... |
| Manual / spreadsheets | staff time | free, familiar | doesn't scale, error-prone |
| Do nothing | the problem's cost | zero effort | the pain persists |

Then pick two axes buyers genuinely trade off (e.g. price vs. depth, self-serve vs. high-touch — not "innovative vs. legacy") and state in one paragraph which quadrant is open and why this business can hold it. If no quadrant is open, that is a finding — report it.

## Unit economics (step 5)

Compute all four, show the inputs:

- **CAC** = fully loaded sales + marketing spend in a period / new customers won in that period. Fully loaded means salaries and tools, not just ad spend.
- **Contribution margin per customer** = revenue per customer per month − variable costs to serve (COGS, hosting, support, payment fees).
- **LTV** = contribution margin per customer per month / monthly churn rate. (Equivalently: margin x average customer lifetime in months.)
- **CAC payback (months)** = CAC / contribution margin per customer per month.

Rules of thumb to test against: LTV:CAC of 3+ is healthy; payback under 12 months is strong, over 24 is alarming for a venture-scale business; contribution margin must be positive per unit or growth just scales losses. When churn data doesn't exist yet, present LTV as a range across 2-3 churn scenarios rather than one flattering number.

## Driver-based projection (step 6)

Never project revenue as a curve; project the 3-5 drivers and let revenue fall out. Pick drivers the team can actually act on. Skeleton (adapt drivers to the business):

```markdown
# 3-Year Projection — driver-based

## Drivers (the only numbers anyone should argue about)
| Driver | Y1 | Y2 | Y3 | Basis |
|---|---|---|---|---|
| Qualified leads / month | 40 | 120 | 300 | channel math from step 3 |
| Lead -> customer conversion | 5% | 7% | 8% | comparable benchmark, source |
| Avg revenue per customer / month | $250 | $270 | $290 | pricing page + expansion |
| Monthly churn | 3.0% | 2.5% | 2.0% | improves with product maturity |
| CAC | $1,100 | $950 | $900 | spend plan / conversion |

## Computed outputs (never hand-edited)
| Output | Y1 | Y2 | Y3 |
|---|---|---|---|
| Customers (EOY) | | | |
| ARR / revenue | | | |
| Gross margin | | | |
| Operating costs | | | |
| Net cash burn / generation | | | |
| Cash position (given funding) | | | |
```

Build this as a real model in code: assumptions block at the top, computation, CSV/XLSX out. Include a downside case (cut conversion and raise churn ~30%) — banks and honest founders both need it. The headline chart is cash position over time, because running out of cash is how plans actually die.

## Narrative arc by audience (step 7)

| Audience | Arc | Leads with | Numbers they scrutinize | Never do |
|---|---|---|---|---|
| Investors | problem, why now, solution, traction, market, moat, team, ask | upside and growth rate | SOM path, LTV:CAC, burn multiple | present the downside case as the plan |
| Banks / lenders | stable demand, cash flow, collateral, repayment | predictability | debt-service coverage, downside cash flow | pitch a hockey stick |
| Internal stakeholders | strategic fit, cost of inaction, resource ask, milestones, kill criteria | opportunity cost | payback vs. alternatives, headcount | hide the kill criteria |

Write the narrative as a standalone document (`plan.md` or a deck outline) that references the model's numbers — never duplicate numbers by hand, cite the model so a re-run stays consistent.

## Common failure modes

- **Top-down-only sizing.** "1% of a $40B market" is not a plan; it's a ratio. Bottom-up first, always.
- **Revenue projected directly.** If revenue isn't computed from drivers, the projection can't be argued with — which means it can't be believed.
- **CAC without salaries.** Counting only ad spend flatters CAC by 2-5x. Fully loaded or nothing.
- **LTV from a guessed churn presented as fact.** Pre-revenue businesses must show churn scenarios, not a single 12-year customer lifetime.
- **Hockey stick with no mechanism.** Growth inflections need a named cause (channel unlock, pricing change, sales hires ramping) with a date and a cost.
- **Feature-table "competitive analysis".** A checkmark grid where you win every row convinces no one. Positioning axes and an honest "where they win" column do.
- **Riskiest boxes never revisited.** The canvas flags them in step 2; steps 3-6 must actually test them, and the final narrative must say what evidence now exists.
- **One plan for all audiences.** The investor deck sent to a bank reads as reckless; the bank package sent to a VC reads as unambitious.
- **Numbers living only in prose.** If the model isn't a rerunnable file, every assumption change means rewriting the document by hand — build the spreadsheet with code tools and cite it.
- **Skipping validation.** If nobody has confirmed the problem exists, stop planning and load `build-something-people-want` with skill_view.

## Output

- `canvas.md` — lean canvas with RISKIEST flags
- `market.md` — TAM/SAM/SOM with sources and arithmetic shown
- `landscape.md` — alternatives table plus positioning claim
- `model/` — driver-based model as code plus generated CSV/XLSX, base and downside cases
- `plan.md` — the audience-tuned narrative referencing the model

Keep all of it in the workspace under a directory the user names (default `business-plan/`), so the plan survives the conversation and the model can be rerun when reality updates the assumptions.
