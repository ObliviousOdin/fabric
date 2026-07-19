---
sidebar_position: 4
title: "Paywall & monetization (ideation)"
description: "Ideation for adding a paywall to Fabric: why a Botsi-style AI pricing layer is the last brick and not the first, what is legitimately paywallable on an Apache-2.0 project, the billing + entitlement foundation that must exist first, and a phased build order that starts with managed hosting and enterprise add-ons."
---

# Paywall & monetization (ideation)

:::caution This is ideation + roadmap, not a shipped product
There is **no first-party billing, checkout, or general entitlement store in the
repository today.** This page reasons about how a paywall is built on the
runtime Fabric already has, and how a Botsi-style AI pricing/paywall layer would
(and would not) fit. It follows the project's convention of describing staged
backend work honestly rather than shipping a mockup. It builds directly on the
[managed hosting](/deploy/managed-hosting) and [compute broker](/deploy/compute-broker)
designs — read those first.
:::

## The question

Can something like [Botsi](https://www.botsi.com) — an AI layer that shows the
right price and paywall to each user — be incorporated into the Fabric page to
get a paywall option?

**Short answer: yes, you can put a paywall on Fabric's hosted offering — but a
Botsi-style layer is the _last_ brick, not the first.** It is a decision-only
optimizer that presupposes a billing + entitlement + paywall stack Fabric does
not have yet. Build that foundation first (it is already scoped in
[managed hosting](/deploy/managed-hosting)), monetize the **service** rather than
the Apache-2.0 core, and treat an AI pricing layer as an optional, removable
add-on to revisit only once a hosted funnel produces real volume.

## Why Botsi is not a paywall

Botsi is a **decision layer, not a paywall and not a biller.** It trains a
per-app model that, at the moment a user hits a paywall, returns _which_
offer/price/variant to show. Its own positioning: it "sits on top of your
existing stack (RevenueCat / Superwall / internal infrastructure) and tells it
which paywall to show." It never renders your UI, never charges a card, and
never stores who-is-allowed-what.

It is also oriented at high-volume **mobile in-app-purchase** funnels (App Store
/ Play), priced as a percentage of subscription revenue, and its reinforcement
learning needs far more conversions than a high-value developer tool produces
early on. Fabric is a globally-sold web / desktop / CLI tool billed via a card
processor, not IAP.

:::note Verify Botsi's specifics before relying on them
`botsi.com` returns `403` to automated fetching, so its endpoint names, model
details, and price figures in any ideation come from search snippets and
third-party write-ups. Confirm against live docs before building on them.
:::

Two frictions worth naming up front:

- **Trust.** Showing different users different prices is an arbitrage and
  fairness hazard for a transparency-first technical audience.
- **Values.** A Botsi-style model's quality depends on streaming per-user
  behavioral signals to a third-party SaaS, which cuts against Fabric's
  local-first, privacy-respecting posture. Keep the OSS / self-hosted path
  optimizer-free regardless.

## A paywall is a layer cake

Every layer has to exist before the one above it means anything. Fabric already
has the bottom of the cake; the missing pieces are the middle.

```mermaid
flowchart TB
  L5["L5 · Optimizer — 'which offer to show' (Botsi / home-grown) · optional, later"]
  L4["L4 · Paywall surface — pricing page · upgrade modal · usage meter · build"]
  L3["L3 · Entitlement store — tier · flags · limits · quotas · build"]
  L2["L2 · Biller / checkout — plans · trials · renewals · tax · build (designed)"]
  L1["L1 · Account identity — a user a subscription attaches to · already here"]
  L5 -->|optimizes| L4 -->|reads| L3 -->|synced from| L2 -->|attaches to| L1
```

A Botsi-style layer is **L5**. Fabric has **L1** and a design for **L2**. The
load-bearing work is **L2–L4**.

## What Fabric already provides (the reuse map)

The pleasant surprise: this is not a green field. A working paid-access gate
already ships, inherited from an upstream account/credits integration.

| Foundation need | Existing Fabric primitive | Where |
| --- | --- | --- |
| Account identity a subscription can attach to | Fail-closed dashboard [auth gate](/user-guide/features/web-dashboard); OIDC "email login" and basic-auth both resolve a verified session | `plugins/dashboard_auth/self_hosted`, `plugins/dashboard_auth/basic` |
| A live entitlement gate to **mirror** | Capabilities already gated on a `paid_access` flag, with real upgrade copy ("Add credits or a subscription… at {billing_url}") | `fabric_cli/nous_account.py`, `agent/credits_tracker.py`, `agent/billing_view.py`, `agent/account_usage.py` |
| A single enforcement chokepoint | Middleware attaches a verified session to every non-public request; a latent capability field (`Principal.scopes`) is defined but not yet enforced by any route | `fabric_cli/dashboard_auth/middleware.py`, `fabric_cli/dashboard_auth/base.py` |
| A usage → cost engine | `normalize_usage()` + `estimate_usage_cost()` over a maintained per-model rate table | `agent/usage_pricing.py` |
| Per-session usage records | Sessions table records `user_id`, `billing_mode`, estimated/actual cost, `api_call_count`, token buckets — **per session**, cost **estimated** | `fabric_state.py` (repo root) |
| A control-plane design | Plan picker → checkout → provisioner → Postgres tenant registry with suspend / resume / destroy | [`deploy/managed-hosting`](/deploy/managed-hosting) |
| A metered-inference design | Shared-GPU broker, metered on tokens served, built on the proxy + credential pool + `usage_pricing` | [`deploy/compute-broker`](/deploy/compute-broker) |
| Fleet policy pinning | [Managed scope](/user-guide/managed-scope) `/etc/fabric` wins over user config and env, per key — the right place to pin per-tier caps | `fabric_cli/managed_scope.py` |

:::warning An inherited billing relationship to resolve
The `paid_access` gate is coupled to an upstream "Nous Portal" account/credits
integration (`plugins/dashboard_auth/nous`, `fabric_cli/proxy/adapters/nous_portal.py`).
Before wiring in a first-party processor, decide whether it **replaces** that
relationship or **coexists** with it — there may be an inherited revenue-share or
dependency worth mapping first.
:::

## What is paywallable — and what is not

Fabric's core is **Apache-2.0**: the grant is perpetual and irrevocable
(`LICENSE` §2). You cannot paywall code already in the open tree — anyone can
fork the last commit and host it free. Monetize the **service** and **new,
separable proprietary modules**, never the existing software.

| Tier | What it includes | Why it is legitimate |
| --- | --- | --- |
| **Free** | Local self-host, CLI, desktop, all auth, profiles, local-first state, local models | Already open and forkable; the adoption engine. Gating anything in the open tree only invites a fork. |
| **Managed hosting** *(monetize first)* | Click-to-deploy, per-tenant VM/container, uptime, no-ops convenience | "We run it for you" is squarely allowed (§9) and matches every open-core precedent. Enforced by provisioning state, not a client flag. |
| **Enterprise add-ons** *(monetize first)* | SSO/SAML, org RBAC, audit logs, fleet-policy management, seats; plus SLA support, warranty/indemnity | The reliably-paywalled open-core set, authored as **new proprietary modules** (separable works §1 lets you keep closed). §9 explicitly permits charging for support/warranty/indemnity. |
| **Pro** *(later)* | More agents/profiles, cron/automations, channels, full insights, premium model routes | Natural per-plan levers that map to real dashboard routes an entitlement check can gate for the hosted tier. |
| **Metered compute** *(later)* | Shared-GPU usage billed on tokens served | Genuinely usage-metered and network-served. Needs the per-request ledger below before billing on it. |

:::note Backlash tracks moving the line, not charging
Never gate a capability already shipping in the Apache-2.0 tree. Relicensing the
existing core (Commons Clause / BSL / SSPL) is both pointless (the grant is
irrevocable) and the single reliable trigger for forks and reputational damage
(Terraform, Elastic, Redis). If you want anti-reseller protection, apply a
source-available license **only to brand-new modules**, accepting the "not open
source" perception cost. Get IP/licensing counsel before any dual-licensing
decision, and clear the "Fabric" trademark (vs Microsoft Fabric and
`danielmiessler/fabric`) before building a commercial identity on the name.
:::

## Where a paywall wires in

```mermaid
flowchart LR
  subgraph Client["Untrusted clients"]
    WEB["web/ dashboard"]
    DESK["desktop app"]
  end
  subgraph Backend["Trusted backend"]
    GATE["Auth-gate middleware (entitlement check)"]
    ENT["Entitlement store (tier · flags · limits)"]
    TEN["Tenant registry (running / suspended)"]
  end
  subgraph Ext["External"]
    PROC["Processor (MoR or Stripe)"]
  end
  WEB --> GATE
  DESK --> GATE
  GATE --> ENT
  PROC -->|"webhooks (idempotent)"| ENT
  ENT --> TEN
```

1. **Enforcement chokepoint.** Add a per-account entitlement lookup where the
   auth middleware already attaches a verified session, or start enforcing the
   existing `Principal.scopes`. One file, fail-closed. Mirror the shipped
   `paid_access` gate pattern. Keep every processor/optimizer key server-side —
   `web/` and the desktop client are tamperable.
2. **Billing → entitlement sync.** Processor webhooks (created / updated /
   canceled) feed a server-side store keyed to the account. Treat "paid" and
   "unlocked" as two facts; make handlers idempotent and add a reconciliation
   job to kill paid-but-locked / churned-but-unlocked drift.
3. **Hosted = lifecycle is enforcement.** For the hosted tier, the
   [tenant registry](/deploy/managed-hosting#tenancy-with-profiles) running /
   suspended / destroyed state _is_ the paywall — a non-paying tenant is
   suspended at the infra layer. Strong isolation is one VM/container per tenant;
   profiles are explicitly **not** a security or billing boundary.
4. **Metered compute ledger (later).** Upgrade usage from per-session to a
   per-request ledger, group on the existing `user_id`, and add a
   credits/quota/markup layer with a **soft** cap that warns before a **hard**
   cap. The rate math exists in `agent/usage_pricing.py`; `fabric_cli/model_cost_guard.py`
   is only a warning today and must become an enforced budget.
5. **Paywall UI.** A static pricing page on the Docusaurus site → external
   checkout; an in-app upgrade modal + usage meter beside the auth widget,
   reading `/api/analytics/usage`; a reverse-trial banner. Drive all gates off
   the server flag so tiers are A/B-testable without shipping client code.

## Choosing a processor (open decision)

| Option | Trade-off |
| --- | --- |
| **Merchant-of-record** (Polar, Lemon Squeezy, Paddle) | The MoR becomes the legal seller and handles global VAT/GST/sales-tax for ~2% more. Best fit for a small team with no finance function. Recommended default. |
| **Stripe-direct** | Cheaper and full control, but **you** become merchant-of-record and owe global tax registration and remittance yourself (Stripe Tax only calculates). Better if usage-based metering dominates. |

This is left open pending the flat-vs-usage decision. For a first move built on
**managed hosting + enterprise add-ons** (flat/seat pricing), a merchant-of-record
is the lower-operational-burden choice; revisit if metered compute becomes the
primary line.

## Build order (roadmap)

Tailored to monetizing **managed hosting + enterprise add-ons first.** Each phase
ships on its own; a Botsi-style optimizer does not appear until the funnel earns
it.

1. **Phase 0 — Decide & publish the shopfront.** Written decision on what is
   gated; processor choice; an honest pricing page labeled "design/roadmap" per
   this repo's convention; IP counsel and trademark clearance.
2. **Phase 1 — Enterprise add-ons.** SSO/OIDC already exists
   (`plugins/dashboard_auth/self_hosted`); author RBAC (enforce `Principal.scopes`),
   audit logs, and fleet-policy management as **new proprietary modules** kept out
   of the OSS tree. These are the highest-ACV, lowest-volume, lowest-licensing-risk
   revenue and can precede full self-service billing (early deals can be invoiced
   manually).
3. **Phase 2 — Managed-hosting billing foundation.** Implement
   [managed hosting](/deploy/managed-hosting) steps 3–5: checkout → webhook →
   server-side entitlement store → Postgres tenant registry with
   suspend/resume/destroy; idempotent webhooks + reconciliation. Entitlement check
   added at the auth middleware.
4. **Phase 3 — Paywall UX + reverse trial.** Full features for ~14 days, then
   auto-downgrade to a capped free tier or suspend the hosted box; an in-app
   upgrade modal (explain-why + preview + one-click unlock + "continue without
   upgrading"), capped and shown at moments of value; a usage meter with a
   soft-limit banner.
5. **Phase 4 — Metered compute billing.** Per-request ledger; group billing on
   `user_id`; enforced credits/quota/markup; signed offline lease tokens for any
   paid desktop/self-install tier (accept it is honor-system, not DRM).
6. **Phase 5 — Optimization, only if volume justifies.** Rules-based upgrade
   triggers on Fabric's first-party signals; low-cardinality pricing-page A/B
   tests to significance. Only at **thousands of trials/month**: evaluate a
   Botsi-style web API or a home-grown bandit — removable, processor-fronted, and
   never on the OSS/self-host path.

## Risks to hold in view

- **Sequencing.** "Just add Botsi" reads as a shortcut but presupposes the very
  layers Fabric lacks; as step one it is cost before signal.
- **Metering honesty.** Usage is per-session and cost is estimated — billing
  before a per-request ledger makes disputes unresolvable and quotas
  unenforceable.
- **Webhook drift.** Billing ↔ entitlement desync is a classic revenue leak;
  needs idempotency + reconciliation.
- **Tenant isolation.** Profiles share the OS user, `HOME`, and git/ssh creds —
  real multi-tenant billing means one VM/container per tenant.
- **Forkability.** Any client-side gate can be stripped and the core self-hosted
  free; the moat is convenience, compute, brand, and enterprise features — not
  exclusivity over the software.

## Open decisions

- Flat tiers or usage-based? (Sets processor and pulls the per-request ledger
  earlier or later.)
- Merchant-of-record or Stripe-direct?
- Is a paid desktop / self-install tier in scope? (If yes, commit to signed
  offline leases and honor-system enforcement.)
- Does first-party billing replace or coexist with the inherited Nous Portal
  relationship?
- Source-available license for new modules, or stay all-Apache and rely on
  brand/hosting as the moat?
- Does the local-first brand permit any per-user behavioral data going to a
  third-party pricing SaaS, ever?

---

**Related:** [Managed hosting control plane](/deploy/managed-hosting) ·
[Shared compute broker](/deploy/compute-broker) ·
[Self-hosting](/deploy/self-hosting) ·
[Web dashboard & auth](/user-guide/features/web-dashboard) ·
[Managed scope](/user-guide/managed-scope) · [Profiles](/user-guide/profiles)
