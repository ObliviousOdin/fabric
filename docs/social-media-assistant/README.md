# Fabric Social Media Assistant — Product Plan

**Status:** Draft product plan and implementation packet
**Date:** 2026-07-23
**Product area:** Fabric Social Studio and dashboard extension
**Design-partner context:** An anonymized B2B company LinkedIn-growth workflow

## Product decision

Build a decision-and-evidence system for a company’s LinkedIn growth work, not a content factory and not an autonomous publishing tool.

The first implementation is **mobile-first, not native-first**:

1. Preserve the shipped Social Studio Compose/Library flow for drafting in a Fabric session and copying a LinkedIn-ready caption.
2. Add a responsive, authenticated dashboard plugin for the durable operating ledger, manual evidence entry, and concise reports. It is usable from a phone browser.
3. Defer changes to the core gateway contract, mobile PWA navigation, and native iOS/Android navigation until the workflow proves useful and the extension boundary is insufficient.

## Current verified Fabric baseline

Fabric already ships **Social Studio** across desktop, web, iOS, and Android:

- `apps/shared/src/social.ts` defines the LinkedIn post prompt and `linkedin-post` fenced-block parser.
- Compose starts a Fabric chat with a structured social prompt.
- Library discovers post-ready assistant output from session transcripts and supports manual copy.

That shipped capability is text-first drafting. It is **not** a durable publishing ledger, source of analytics, social-network connector, or versioned approval system.

The mobile PWA is a focused chat shell and does not host dashboard plugins. Dashboard plugins are a separately authenticated extension surface. The MVP therefore opens the responsive dashboard plugin in a phone browser rather than adding a PWA tab or native screen prematurely.

## Why this is worth building

The anonymized workflow has a concrete ambition: improve company-page follower growth, qualified interaction, reach, and inbound demand. The hard problem is not generating more captions. It is retaining the truth about:

- which lane should speak today;
- what evidence supports the claim;
- whether a person actually posted externally;
- which metrics are user-supplied, partial, stale, or unavailable; and
- which next decision changed because of the evidence.

Fabric can make that loop disciplined without claiming access it does not have.

## Product promise

> Help a GTM operator choose the next social action, create an evidence-backed draft, hand it to a human for manual LinkedIn publishing, and record what is known afterward.

This is not a promise to guarantee distribution, engagement, follower growth, or inbound pipeline. LinkedIn’s presentation and algorithm are platform-controlled. Forecasts are labeled scenarios, not promises.

## Delivery path

| Phase | Outcome | Implementation boundary | Exit evidence |
| --- | --- | --- | --- |
| 0 — Social Studio safety | Reliable draft-only workflow | Existing Social Studio/session path; no social-network integration | Drafts are assistant-originated, manual-copy wording is unambiguous, and transcript failures are not shown as empty libraries |
| 1 — Responsive operating ledger | A mobile-browser GTM cockpit | Authenticated `social-gtm` dashboard plugin with profile-scoped local ledger | A user can link a session draft, approve an exact hash, record a user-supplied post URL and manual metrics, then read a truthful report |
| 2 — Evidence-led reporting | Better decisions from explicitly supplied data | Plugin reports, CSV export, non-publishing cron jobs | Reports distinguish unknown, zero, stale, partial, and user-supplied values |
| 3 — Validated native integration | Native convenience where proven valuable | Separate core/mobile RFC after plugin validation | One canonical contract, authentication model, and native UX are approved and tested |
| Future — External connector | Optional read-only platform data only | Separate authorization, legal, security, and product RFC | Explicit consent, scopes, token lifecycle, rate limits, auditability, and failure recovery are demonstrated |

## What ships in the first useful release

- a responsive dashboard tab supplied by a `social-gtm` plugin;
- company/founder lanes, goals, cadence, ownership, and content constraints;
- a link from a ledger item to its originating Fabric session and draft hash;
- explicit review/approval for the exact caption version;
- **Copy for manual LinkedIn publishing** — no publish, schedule, comment, follow, or reshare action;
- a user-supplied post URL/attestation record, clearly labeled as such;
- manual metric observations with source, observation date, capture date, coverage, and correction history;
- a concise SOD/EOD report and parseable CSV export; and
- non-publishing research/report cron jobs only after plugin-owned data access is verified.

The first release does not require LinkedIn API access, OAuth, scraping, native-app changes, PWA navigation changes, image generation, or automatic analytics retrieval.

## Non-negotiable boundaries

1. **No autonomous public action.** Agents and cron jobs may research, draft, classify supplied evidence, and prepare reports. They cannot publish, schedule, comment, react, follow, invite, or reshare.
2. **No fake analytics.** Unknown is not zero. Manual values are labeled user-supplied. A URL supplied by a user is not represented as API-verified platform data.
3. **No implicit publication.** Copying a caption or approving a draft is not proof of an external post.
4. **No use of chat history as a ledger.** Sessions remain the source of draft conversation; the plugin owns durable social operations data.
5. **No credentials in prompts, files, clients, or the ledger.** No LinkedIn credentials are requested in this release.
6. **No cron publishing.** Fabric cron is non-interactive and may auto-approve tools; it must be structurally unable to reach a publishing path.
7. **No AI-slop factory.** Draft creation begins with a source, a firsthand observation, approved proof, or an explicitly labeled opinion. The system may recommend holding rather than posting.
8. **No invented mobile support.** The initial experience is a responsive dashboard plugin, not a claimed PWA or native feature.

## Design-partner outcomes and KPI policy

The program may aim for 10,000 followers and materially stronger interaction and inbound demand, but it must first collect a baseline, due date, metric definition, and reporting window.

The original 7–15% daily-growth idea is an experiment hypothesis, not a compounding commitment. Use 7-day and 28-day comparisons; show sample size, coverage, and confidence. Keep followers, reach, qualified interaction, qualified inbound, meetings, and pipeline as separate outcomes.

## Inputs needed during onboarding

1. Current follower count, target date, and 30/60/90-day history where available.
2. Exact meaning of the interaction/reach objective and its comparison window.
3. ICP, offer, CTA, qualification criteria, owner, and definition of a LinkedIn-sourced inbound.
4. Company/founder voice boundaries, proof rules, prohibited claims, asset/privacy constraints, and topic pillars.
5. Publishing, reply, review, and reporting owners; cadence capacity and time zone.
6. An approved competitor/inspiration watchlist and source-retention policy.
7. The manual method for collecting post URLs and metric observations.

## Product documents

- [Product specification](PRODUCT_SPEC.md) — MVP scope, data rules, UX, security, and acceptance criteria.
- [Build handoff](BUILD_HANDOFF.md) — constrained implementation instructions for the plugin and Social Studio hardening.
- [Mobile operator guide](MOBILE_USER_GUIDE.md) — how to use the existing draft flow and the planned responsive operating ledger.

## Product success measures

During a 30-day active pilot, success means:

- every post record is explicitly marked draft, approved for manual copy, user-reported as posted, held, or unknown;
- manual metric observations retain their provenance and never appear as verified API data;
- the daily operating review takes under five minutes when inputs are available;
- the report states what changed, what is unknown, what is next, and who owns it; and
- the team can demonstrate that the system prevented at least one duplicate, unsupported claim, or mistaken “published” report.