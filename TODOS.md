# TODOS

Organize future work under `## <Component>` headings. Within each component,
keep items sorted from P0 through P4 and use the template below.

<!--
## Component

### Title

**What:** One-line description of the work.

**Why:** The concrete problem it solves or value it unlocks.

**Context:** Enough detail to resume the work later.

**Effort:** S / M / L / XL
**Priority:** P0 / P1 / P2 / P3 / P4
**Depends on:** None
-->

## Skills

### Subscription-backed MoA advisor skill (option)

**What:** A `subscription-moa` orchestration skill that composes Mixture of
Agents presets from the user's connected subscription/OAuth providers
(openai-codex, copilot, qwen-oauth, minimax, nous) as advisor models, with an
existing primary model as aggregator.

**Why:** Flat-rate subscriptions sit idle between turns; their marginal cost
per advisor call is ~zero until quota caps. MoA core support already exists
(virtual `moa` provider, per-slot provider/model presets, `/moa`,
`reference_max_tokens`, `user_turn` fan-out) — what's missing is preset
composition guidance, when-to-fan-out judgment, and quota stewardship. Ships
as a skill per the Footprint Ladder; no core changes.

**Context:** Full plan, research grounding (MoA / Self-MoA evidence and the
comparable-tier advisor constraint), phases, risks (subscription ToS review
is a Phase 1 acceptance criterion), and acceptance criteria in
[docs/design/subscription-moa-skill.md](docs/design/subscription-moa-skill.md).
Tracked as a roadmap option — not scheduled.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Completed

No completed items yet.
