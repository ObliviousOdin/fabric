# Fabric Social Media Assistant — Product Plan

**Status:** Proposed product plan and implementation packet
**Date:** 2026-07-23
**Product area:** Fabric Mobile, gateway-backed Social workspace
**Primary design partner:** Example Company
**Source use case:** a GTM leader operating Example Company's LinkedIn company page from mobile, coordinating agent research and content while retaining human control of every external post.

## The product decision

Build **Social** as a first-class workspace inside the existing Fabric Mobile clients—not as a separate social-media app and not as a chat prompt template.

Social gives an operator one truthful place to:

1. set a growth goal and working forecast;
2. produce and review company-page content with a specialized agent ensemble;
3. publish manually on LinkedIn, then record the exact post URL;
4. capture analytics with provenance and explicit coverage;
5. read mobile-first start-of-day (SOD) and end-of-day (EOD) growth briefs; and
6. export a clean CSV/PDF evidence ledger.

Every workspace shows a **data-health** state so an operator can see whether a conclusion rests on verified, partial, stale, or unavailable evidence.

The operating principle is **evidence before optimism**. A company can have excellent creative output while still being unable to prove whether it drives reach or pipeline. Social must make that gap visible rather than disguising it with empty metrics or assumed publication.

## Current Fabric baseline

Fabric `main` already ships **Social Studio** across desktop, web, iOS, and Android: a shared LinkedIn post-prompt builder, a `linkedin-post` artifact convention, and Compose/Library flows that let an operator draft a post in chat and copy a completed caption. This proposal does not replace or duplicate that capability.

It specifies the next layer: a persistent, gateway-authoritative Social workspace that promotes Social Studio’s draft/artifact output into versioned content, human review, manual-publish proof, metrics, reports, and decision history. The existing Compose and Library flows remain the draft-entry and artifact-discovery path.

## Why this is worth building

The Example Company workflow exposed a repeated mobile operations problem:

- The team has a concrete outcome: grow the company LinkedIn page to 10,000 followers and materially increase qualified interaction and inbound demand.
- The actual work is multi-step: research, competitor review, angle selection, drafting, visual direction, founder/company coordination, approval, manual publication, comments, metric capture, reporting, and iteration.
- Today these steps are dispersed across chat, documents, LinkedIn, screenshots, assets, and scheduled reminders.
- The hardest failure is not writing copy. It is losing the truth about what was published, what was measured, and which activity actually created a business outcome.

Fabric already has the correct foundation: authoritative gateway sessions, agent/tool execution on the gateway, user approvals, background work, artifacts, mobile pairing, native iOS/Android clients, and a capability-negotiated wire protocol. The missing product layer is a persistent social-growth operating model that turns those pieces into one mobile routine.

## Product promise

> Run a disciplined social-growth experiment from your phone, with clear human approval, proof of what happened, and a daily record of what changed.

This is **not** a promise to guarantee LinkedIn growth. Algorithms, audience, content quality, distribution, and sales follow-up remain external variables. Fabric should make experiments faster and outcomes more legible; it must not manufacture causal claims.

## Plan at a glance

| Phase | Outcome | Scope | Exit evidence |
| --- | --- | --- | --- |
| 0 — Contract and data truth | One authoritative Social workspace model | Gateway contracts, profile-private store, content/evidence/metric state machines, capability gate | Cross-client parser fixtures; no client can show unsupported or fabricated social state |
| 1 — Mobile operating loop | An operator can run today’s plan and record manual publication | Promote Social Studio into a Social destination; setup, Today, content queue, post detail, manual URL capture, CSV export | iOS, Android, PWA screenshots and tests for empty/loading/offline/partial-data states |
| 2 — Measurement loop | Daily reports become evidence-led | Screenshot/CSV import, metric snapshots, data health, SOD/EOD brief, forecast inputs | A report correctly distinguishes `0`, unknown, stale, partial, and verified data |
| 3 — Agent ensemble | Repeatable content and research operations | Role prompts, research briefs, competitor watchlists, content-review and reporting jobs | Agent output is attached to a content item with sources, effort, decision, and review history |
| 4 — Approved integrations | Less manual reporting where platform access permits | Read-only OAuth/API connector behind explicit consent; CRM/UTM attribution adapters | Tokens are server-side and revocable; connector limitations are visible; no silent publishing |
| 5 — Experiment intelligence | Better decisions, not opaque automation | Cohort comparisons, cadence/format/angle experiments, forecast ranges, learned playbook | Recommendations cite sample size, comparison window, evidence quality, and uncertainty |

## What ships first

The minimum valuable release is deliberately narrow:

- one organization/brand workspace;
- one company LinkedIn channel in **manual capture** mode;
- target, baseline, due date, and simple funnel definitions;
- an agent-generated daily plan and content queue;
- mobile review of a post draft, preview, asset, and evidence;
- a manual-publish handoff with copy-to-clipboard and exact URL capture;
- explicit content states (`draft`, `approved for manual publish`, `posted—unverified`, `publication verified`, `metrics partial`, `measured`);
- manual metric entry or screenshot/CSV evidence import;
- SOD/EOD executive briefs plus CSV/PDF artifact export.

This release does **not** require LinkedIn API access. It creates value even when the operator must paste a post URL and upload analytics screenshots. That is essential because LinkedIn data/API access varies by account, role, product approval, and permission.

## Non-negotiable boundaries

1. **No unattended posting or commenting.** `Approved for manual publish` means the human may publish; it never means Fabric may post.
2. **No fake analytics.** Unknown is shown as unknown. Missing values remain null, never zero.
3. **No implicit publication.** A content item is not “published” merely because a draft was selected, copied, or scheduled externally. It needs an operator attestation and then verifiable evidence.
4. **No local source of truth.** Mobile is a view and action surface over gateway-owned state, exactly like existing Fabric sessions and Work.
5. **No secret handling in chat or client storage.** OAuth tokens and platform credentials are optional server-side integration material, stored/revoked through the gateway’s credential boundary—not embedded in prompts, screenshots, or mobile caches.
6. **No algorithm promises.** “Show more,” reach, and engagement predictions are hypotheses. The UI may offer a copy preview but cannot claim deterministic LinkedIn distribution.
7. **No data blend without labels.** Company-page, founder-profile, paid, organic, and competitor observations remain separately labeled.

## The Example Company design-partner use case

### Target outcome

- Grow Example Company’s company LinkedIn page toward **10,000 followers** by a user-selected target date.
- Increase quality-adjusted interaction and reach; the original 200% objective becomes a baseline-relative quarterly target after a real baseline and time window are recorded.
- Create more qualified inbound interest, not merely more reactions.

### Actual operating constraints observed

- Company and founder content must be separate but coordinated.
- LinkedIn analytics may be inaccessible to Fabric; reports must still be useful and honest.
- A draft, a scheduled item, and a confirmed live post are materially different facts.
- The team wants concise mobile executive reporting: what changed, what was done, what is next, and what is expected.
- The user wants content assistance and agent delegation, but not autonomous public posting.
- Custom visuals can cost meaningful effort; their incremental performance must be measured rather than assumed.

### Product decisions derived from this use case

| Observed problem | Product response |
| --- | --- |
| Post state was uncertain | Versioned content lifecycle and evidence requirements |
| Metrics were missing | Data-health score, field-level provenance, null vs zero semantics |
| Reports risked treating drafts as results | Reporting only counts verified publication and labels all other state explicitly |
| Mobile executive review was needed | Today/SOD/EOD cards optimized for one-handed scanning and decision-making |
| LinkedIn cannot always be automated | Manual capture is a supported primary path, not an error state |
| Content could feel repetitive/AI-generated | Voice profile, prior-post similarity check, human review, and source-backed claims |
| Marketing work needed multiple specialties | Scoped agent roles with one accountable growth-plan owner |

## Open context to collect during onboarding

The setup wizard and the GTM lead’s first working session should collect these inputs. The product remains usable with partial answers, but it must label affected forecasts and recommendations as incomplete.

1. **Target and baseline:** current followers, target date, 30/60/90-day historical page metrics, and whether the 200% target applies to impressions, engagement rate, qualified engagement, or all of them.
2. **Business outcome:** ICP, geographies, sectors, role titles, offer/CTA, qualification criteria, sales owner, and CRM definition of a LinkedIn-sourced inbound.
3. **Content system:** company/founder/employee voice boundaries, topic pillars, proof assets, customer/legal permissions, prohibited claims, and visual capacity.
4. **Distribution system:** who publishes, who comments, how employee amplification works, paid-media budget, and competitors/watchlists.
5. **Measurement system:** LinkedIn page-admin access, approved API availability, website analytics, UTM naming convention, CRM connection, and evidence-retention policy.
6. **Operating cadence:** desired SOD/EOD time zone and delivery times, weekly review day, publishing windows, approval SLA, and weekly production capacity.

## Required product documents

- [Product specification](PRODUCT_SPEC.md) — requirements, states, contracts, measurements, rollout, and acceptance criteria.
- [Build handoff](BUILD_HANDOFF.md) — the execution prompt for an implementation agent/team.
- [Mobile user guide](MOBILE_USER_GUIDE.md) — how a GTM operator runs the workflow from a phone.

## Early KPI policy

The original request mentioned daily 7–15% growth. The product should **not** put a compounding daily growth target on a volatile small sample as a commitment. Instead:

- use follower growth and reach targets at 30/60/90-day and quarterly horizons;
- use 7-day and 28-day rolling comparisons for trend detection;
- treat 7–15% as an experiment-improvement ambition only when a comparable sample is large enough;
- display confidence, sample size, and data coverage next to every recommendation; and
- keep qualified inbounds, meetings, and pipeline as separate downstream outcomes.

## Success measures for the product itself

Within 30 days of an active workspace, a successful product pilot should demonstrate:

- ≥90% of published content has a recorded URL and publication status;
- ≥80% of expected 24-hour and 7-day metric checkpoints are captured or explicitly marked unavailable;
- an operator can complete the daily review in under five minutes when data is available;
- every external post has a recorded human approval/publish handoff; and
- the weekly report can state which inputs are evidence, which are assumptions, and which decisions changed because of data.
