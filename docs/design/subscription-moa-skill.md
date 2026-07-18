# Subscription-Backed MoA Advisor Skill

**Status:** Roadmap option — proposed, not scheduled.
**Component:** Skills (orchestration category) + documentation. No core changes.
**Related:** `website/docs/user-guide/features/mixture-of-agents.md`,
`fabric_cli/moa_config.py`, `agent/moa_loop.py`, `skills/orchestration/`.

## Problem and opportunity

Fabric users increasingly hold several flat-rate model subscriptions at once
(OpenAI Codex/ChatGPT, GitHub Copilot, Qwen, MiniMax, Nous — all already
connected through OAuth provider plugins). Between agent turns those
subscriptions sit idle, yet their marginal cost per additional call is
approximately zero until a quota cap is hit.

Fabric's Mixture-of-Agents feature can already fan a turn out to advisor
models on any mix of providers and aggregate on a primary model — the config
layer supports per-slot `{provider, model}` pairs, and the default preset
already includes a subscription provider as an advisor. What is missing is
not machinery but **packaging and judgment**:

1. Nothing teaches the agent (or the user) to compose presets from the
   subscriptions they actually have connected.
2. Nothing decides *when* an ensemble is worth the extra latency and quota —
   MoA today is all-or-nothing per turn or per session.
3. Nothing stewards subscription quota: an uncapped `per_iteration` fan-out
   on a long agentic session can exhaust a flat-rate plan's allowance.

Per the Footprint Ladder (AGENTS.md), this capability should ship as a
**skill** — not a new core tool, hook, or model-tool schema change.

## What exists today (verified in-repo)

- MoA is a virtual provider (`moa`) with named presets; each preset lists
  advisor `reference_models` as explicit provider/model pairs plus one
  `aggregator` slot (`fabric_cli/moa_config.py`). Presets are selectable from
  every model-picker surface; `/moa <prompt>` is a one-shot.
- Advisors run in parallel (cap 8, `agent/moa_loop.py`), receive only the
  conversation's user/assistant text (no tool schemas or system prompt), and
  each advisor's tokens are priced at its own model's rate for cost rollups.
- Two fan-out cadences exist: `per_iteration` (advice refreshes every tool
  iteration) and `user_turn` (advice once per user turn).
- `reference_max_tokens` caps advisor verbosity; the docs note advisor
  generation dominates per-turn latency.
- Subscription-auth provider plugins in-tree: `openai-codex`
  (`oauth_external`), `qwen-oauth`, `minimax` (OAuth variant), `nous`
  (device code), `copilot`, `copilot-acp`.
- Failed advisors are skipped rather than failing the turn.

## Research grounding

Findings from a July 2026 multi-source research pass with adversarial
verification. Confidence labels reflect that verification.

**Verified — safe to build on:**

- Ensembles of individually weaker models can beat a single stronger model:
  the original Mixture-of-Agents work reports 65.1% length-controlled win
  rate on AlpacaEval 2.0 using only open-source models vs 57.5% for GPT-4
  Omni (Wang et al., arXiv:2406.04692, ICLR 2025; Together AI reference
  implementation). Caveats: LLM-judged chat benchmarks, June-2024 frontier,
  not agentic/tool-use workloads.
- "Collaborativeness" is real: a model produces better answers when shown
  other models' outputs, even outputs from weaker models (same paper).
- The aggregator genuinely synthesizes rather than picking a best answer;
  generative aggregation beat an LLM ranker in the paper's ablations
  (medium confidence — numbers verified, design implication contested).
- **The controlling constraint (Self-MoA, arXiv:2502.00674, ICML 2025):**
  aggregating repeated samples of the *single best* model beat mixed-model
  MoA by 6.6% on AlpacaEval 2.0 and 3.8% averaged across MMLU/CRUX/MATH.
  Mixing different models reliably helps only when advisors are of
  **comparable quality with complementary strengths**. Design consequence:
  default presets must use a small roster of near-tier advisors, never a
  wide roster of weaker ones.
- Topology prior art: Together's reference implementation defaults to one
  parallel proposer layer (4 proposers) plus one aggregator — matching
  Fabric's existing single-layer shape. No need for multi-layer MoA.

**Directional only — cited but unverified in our pass:** routing/cascade
literature (RouteLLM arXiv:2406.18665, FrugalGPT arXiv:2305.05176, Hybrid
LLM arXiv:2404.14618) reports large cost savings from routing simple queries
to cheap paths and escalating hard ones. For this design the relevant
inversion: when advisors are flat-rate, selective triggering is a
**latency and quota budget** problem, not a dollar problem.

**Do not cite (refuted in verification):** the "2 heterogeneous agents match
16 homogeneous" heterogeneity-scaling claims (arXiv:2602.03794) and the
compute-matched "MoA beats self-consistency by 2.7 points" figures
(arXiv:2605.01566).

**Unsourced — must be validated during implementation:** quota structures,
rate limits, and terms-of-service posture of consumer subscription plans
under programmatic advisor use. At least one provider has publicly
restricted third-party access patterns to subscription backends. This is
the single biggest external risk to the premise (see Risks).

## Proposed design

### Phase 1 — the skill (core deliverable)

A new `subscription-moa` skill under `skills/orchestration/` (agentskills.io
format, standard frontmatter, platforms: all). Contents:

- **Preset composition workflow.** Inspect which subscription/OAuth
  providers are connected (`fabric status` / provider credential state),
  then guide creation of one or two named presets via `fabric moa configure`
  or config.yaml edits:
  - `advisors-max`: all connected subscription models as advisors, primary
    session model as aggregator.
  - `advisors-lean`: the two strongest connected subscription models only.
- **Opinionated defaults, from evidence:** 2–4 advisors of comparable tier
  (Self-MoA constraint); `fanout: user_turn` for subscription advisors
  (quota stewardship); `reference_max_tokens: 600` starting point (latency);
  aggregator = the user's primary model so tool-calling behavior is
  unchanged.
- **When-to-use judgment** (the skill's routing section): reach for a MoA
  turn on high-stakes, open-ended, or ambiguous work (design calls,
  reviews, hard diagnoses); stay single-model for mechanical or
  low-ambiguity turns. Explicit cross-references to the existing
  `ensemble` (subagent briefs) and `adversarial-verify` skills so the
  taxonomy in `skills/orchestration/ensemble/SKILL.md` stays coherent.
- **Quota stewardship guidance:** prefer `/moa` one-shots over switching
  the session onto a preset; warn about `per_iteration` cadence on long
  tool loops; note advisor failures degrade gracefully.

Effort: S–M. No core code required.

### Phase 2 — selective triggering (follow-up option)

Teach the skill (and optionally a `/goal`-style helper) to escalate
selectively: single-model first, fan out only when the turn looks hard
(user asks for a decision/review/estimate, prior attempt failed, or the
user explicitly asks for a second opinion). This recovers the
"spend only when the turn warrants it" property from the routing
literature, inverted for a zero-marginal-cost regime: the budget being
protected is latency and subscription quota.

A lightweight complexity signal could later ride the existing auxiliary
model plumbing (`agent/auxiliary_client.py`) rather than a new classifier
dependency. That is deliberately out of scope for Phase 1 and would need
its own footprint review.

### Phase 3 — measurement (stretch)

Add an eval manifest under the skill (`evals/cases.yaml`, per
`docs/design/skill-evaluation-runner.md`) comparing single-model vs
MoA-preset outcomes on a small fixed task set, so the quality claim is
measured in Fabric rather than imported from chat benchmarks. Session cost
rollups already attribute advisor tokens per-model, giving the raw data.

## Non-goals

- No new core model tools, hooks, or toolset changes.
- No multi-layer MoA (single proposer layer + aggregator matches both the
  reference implementation and Fabric's existing loop).
- No automatic per-turn model routing in core; anything beyond skill-level
  judgment is a separate proposal.
- No changes to the MoA config schema (current schema already suffices).

## Risks

1. **Subscription terms of service.** Programmatic advisor fan-out on
   consumer plans may violate provider ToS or trip anti-abuse rate limits;
   account suspension would hurt users' primary workflows, not just the
   ensemble. Mitigation: the skill documents this risk, defaults to
   `user_turn` cadence and lean rosters, and never retries aggressively.
   A ToS review per provider belongs in Phase 1 acceptance criteria.
2. **Quota exhaustion.** Flat-rate plans meter by requests/tokens per
   window. Mitigation: defaults above, plus guidance to keep one
   subscription out of the advisor roster as the user's interactive
   reserve.
3. **OAuth transport brittleness.** Subscription backends are the least
   stable transports in the provider stack. Existing skip-on-failure
   behavior contains this; the skill should set expectations.
4. **Quality regression risk.** Per Self-MoA, a badly composed roster
   (weak advisors) can make answers worse. The skill's defaults encode the
   comparable-tier rule; the Phase 3 eval verifies it locally.
5. **Latency.** Advisor generation dominates turn wall time; mitigated by
   `reference_max_tokens` and `user_turn` cadence defaults.

## Open questions

- Do aggregation gains transfer from LLM-judged chat benchmarks to agentic
  tool-use turns? (Phase 3 exists to answer this locally.)
- Is a roster of near-frontier subscription models precisely the
  comparable-quality/complementary-strengths regime where mixing beats
  self-sampling — or should the skill also offer a self-MoA preset
  (N samples of the primary model) as a control?
- What complexity signal is worth its cost for Phase 2 — pure prompt-side
  heuristics, primary-model self-assessment, or an auxiliary-model check?
- Per-provider programmatic-use posture: which connected subscription
  providers explicitly permit this pattern?

## Acceptance criteria (Phase 1)

- `skills/orchestration/subscription-moa/SKILL.md` passes the skills
  authoring checks and cross-references `ensemble` / `adversarial-verify`
  without overlapping their triggers.
- Following the skill from a fresh setup with two connected subscription
  providers yields a working preset and a successful `/moa` one-shot.
- Documented ToS/rate-limit review for each subscription provider named in
  the skill.
- Website docs page for the skill generated per the bundled-skill docs
  pipeline; `website/docs/user-guide/features/mixture-of-agents.md` gains a
  short "subscription advisor presets" section linking to it.
