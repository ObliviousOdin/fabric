---
title: "Webapp Development"
sidebar_label: "Webapp Development"
description: "End-to-end playbook for production web apps — pick the stack, model the data, wire auth, payments, and background jobs, add tests and CI, deploy, and monitor"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Webapp Development

End-to-end playbook for production web apps — pick the stack, model the data, wire auth, payments, and background jobs, add tests and CI, deploy, and monitor. Use when the user wants a SaaS or internal tool built from scratch or a prototype taken to production.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/venture-studio/webapp-development` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `webapp`, `saas`, `full-stack`, `auth`, `payments`, `deployment` |
| Related skills | [`website-building`](/user-guide/skills/bundled/venture-studio/venture-studio-website-building), [`rstack`](/user-guide/skills/bundled/venture-studio/venture-studio-rstack), [`ios-app-development`](/user-guide/skills/bundled/venture-studio/venture-studio-ios-app-development), [`test-driven-development`](/user-guide/skills/bundled/software-development/software-development-test-driven-development) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Web App Development

Use this skill when the user wants a production web application — a SaaS product,
an internal tool, a customer portal — built from scratch, or a prototype hardened
for real users. It covers the whole arc from requirements through monitoring. The
organizing principle is **walking skeleton first**: a deployed hello-world with
CI running before any feature code.

Do NOT use this skill for:

- A static, marketing, or content site with no accounts or server-side state —
  load `website-building` with skill_view.
- A native mobile app — load `ios-app-development` with skill_view.
- A throwaway feasibility experiment — build a disposable spike instead and only
  return here once the idea is validated.

## Workflow

1. **Clarify requirements.** Ask the user, in one batch: who the users are, the
   3-5 core jobs the app must do at launch, whether payments are needed at v1,
   and hard constraints (existing infra, compliance, expected scale, team skills).
2. **Pick the stack** using the criteria below. State the choice and the reason
   in one paragraph; get the user's confirmation before scaffolding.
3. **Build the walking skeleton.** Repo, one trivial page, one health endpoint,
   database connected with migrations, CI running lint + tests on every push,
   deployed to the real hosting target. No features yet.
4. **Model the data.** Draft the entity table (template below), review it with
   the user, then write the actual schema and migrations.
5. **Wire auth.** Decide roll vs. hosted (table below), implement signup, login,
   session handling, and one protected route end-to-end.
6. **Build features in vertical slices.** Each slice goes route to database to UI
   with tests, merged and deployed before starting the next. For the test
   discipline inside each slice, load `test-driven-development` with skill_view.
7. **Integrate payments** (if in scope) with webhooks as the source of truth.
8. **Add background jobs** for anything slow or retryable: email, exports,
   third-party syncs.
9. **Harden**: config and secrets hygiene, structured logging, error tracking,
   uptime checks, backups.
10. **Run the launch-readiness checklist**, fix gaps, ship, and watch the
    dashboards for the first real traffic.

Loop steps 4-8 per feature area; steps 1-3 and 9-10 happen once per launch.

## Picking the stack

Three criteria dominate, in order:

1. **Team familiarity.** The user's team maintains this after you leave. A stack
   they know beats a marginally better one they don't.
2. **Hosting target.** If the company already runs Kubernetes, containers win; if
   there is no ops capacity, pick a platform that deploys from a git push.
3. **Boring-tech bias.** Default to tools with a decade of production history.
   Spend novelty budget only where the product differentiates.

| Shape | Examples | Best when | Watch out for |
|---|---|---|---|
| Server-rendered monolith | Rails, Django, Laravel | Small team, CRUD-heavy SaaS, fastest path to revenue | JS-heavy interactive views need sprinkles (htmx, Hotwire, Livewire) |
| Full-stack TypeScript | Next.js, Remix-style frameworks + Postgres | Team is JS-native; rich interactive UI; one language everywhere | Framework churn; server/client boundary bugs; hosting lock-in |
| API + separate SPA | Go/FastAPI backend, React front end | Multiple clients (web + mobile + partners) consume the same API | Two deploys, two test suites, CORS and auth token plumbing |
| Opinionated preset | load `rstack` with skill_view | User has no strong preference and wants a proven preconfigured setup | Check its conventions fit the hosting target before committing |

Default the database to PostgreSQL unless the user names a constraint (SQLite is
legitimate for single-server internal tools). Never pick a distributed database,
microservices, or an event bus for v1.

## Walking skeleton first

Deploy before features. The skeleton must include:

- Repo with formatter, linter, and a test runner wired to one passing test.
- CI (e.g. GitHub Actions) running lint + typecheck + tests on every push, and
  deploying on merge to main.
- Database provisioned, a migration tool installed, and migration 0001 applied
  in production.
- A `/healthz` endpoint returning app version and a database ping.
- The production URL live and shared with the user.

This front-loads every integration risk (DNS, TLS, credentials, pipeline) while
the app is trivial. If deploy is broken on day one, you find out on day one.

## Data modeling before endpoints

Schema mistakes compound; endpoint mistakes are cheap. Before writing routes,
draft and review:

```markdown
## Data model — {app name}

| Entity | Key fields | Belongs to | Notes |
|---|---|---|---|
| Account | name, plan, created_at | — | Tenant root; every row below hangs off it |
| User | email (unique), role | Account | Roles: owner, member |
| ... | ... | ... | ... |

**Tenancy rule:** every tenant-owned table carries account_id; every query
filters by it (or row-level security enforces it).
**Soft-delete policy:** {which tables, and why}
**Open questions:** {anything the user must decide}
```

Rules of thumb: timestamps on every table; foreign keys enforced in the database,
not just the ORM; money as integer cents plus a currency column, never floats; an
audit/events table from day one where money or permissions are involved.

## Auth: roll vs. hosted

| Factor | Roll your own (framework auth) | Hosted provider (identity service) |
|---|---|---|
| Email + password + sessions | Mature framework generators make this safe | Works, but adds a network dependency for login |
| Social login / SSO / SAML | Weeks of fiddly work | Their core competency; hours |
| Cost at scale | Free forever | Per-MAU pricing bites at growth |
| Data ownership & migration | Full control | Exporting password hashes later is painful |
| MFA, breach detection | You own it | Built in |

Decision rule: internal tools and simple B2C email/password — the framework's
built-in auth with secure session cookies. B2B SaaS heading toward enterprise
SSO — hosted provider from the start. Either way: a modern password KDF
(argon2/bcrypt), httpOnly + secure + SameSite session cookies rather than JWTs
in localStorage, and rate limits on login and password reset.

## Payments: webhooks are the source of truth

Never grant entitlements from the client-side redirect after checkout — users
close tabs, redirects fail, and the redirect is forgeable. The pattern:

1. Client starts checkout; server creates the provider's checkout session.
2. Provider processes payment and fires a webhook to your endpoint.
3. Webhook handler verifies the signature, then upserts a local subscription row
   keyed by the provider's IDs (customer, subscription, event).
4. App code reads entitlements only from that local row — never live from the
   provider API on the request path.
5. Handle the full lifecycle: created, updated, payment_failed, canceled.

Make handlers idempotent (store processed event IDs; providers retry) and return
2xx fast, deferring slow work to a background job. Test locally with the
provider's CLI webhook forwarder; reconcile against the provider API nightly.

## Background jobs

Anything slower than ~200ms, retryable, or third-party-flaky leaves the request
path: email, webhook processing, exports, imports, external API syncs. Use the
boring queue for the stack (Sidekiq/GoodJob, Celery, BullMQ, or a Postgres-backed
queue — fine at small scale and one less service). Every job must be idempotent,
carry a bounded retry policy with backoff, and land in a dead-letter state that
alerts a human rather than retrying forever. Schedule recurring work (reconciles,
digests, cleanup) with the same system, not cron on a forgotten box.

## Testing strategy

Shape the suite as a pyramid: many fast unit tests on domain logic (money,
permissions, state machines), a solid middle layer of integration tests hitting
real routes with a real test database — the layer that catches the most bugs per
line — and a handful of end-to-end browser tests covering only the money paths:
signup, login, checkout, the core job. Load
`test-driven-development` with skill_view and follow its red-green-refactor
discipline while implementing slices. CI runs the full suite on every push; fix
or delete a flaky test the week it first flakes.

## Config and secrets

- All config via environment variables; one committed `.env.example` listing
  every variable with a placeholder, never a real value.
- `.env` in `.gitignore` before the first secret exists; if a secret ever lands
  in git history, rotate it — deleting the commit is not enough.
- Distinct values per environment (dev/staging/prod), stored in the platform's
  secret manager, not in CI logs or chat.
- Validate required config at boot and crash loudly if missing; never fall back
  to a default secret.

## Deployment

| Option | Fits | Cost shape |
|---|---|---|
| PaaS (git-push platforms) | Default for small teams; zero ops | Modest flat fee; rises with scale |
| Containers on managed runtime | Existing container infra or unusual runtimes | Cheap-ish; you own the Dockerfile |
| Serverless/edge functions | Spiky traffic, JS-native stacks | Per-request; watch cold starts and DB connection limits |
| VPS + systemd | Cost-sensitive, ops-comfortable users | Cheapest; you are the pager |

Whatever the target: deploys must be one command or one merge, migrations run
automatically before or during rollout with a rehearsed rollback, and staging
mirrors production closely enough that a green staging deploy is meaningful.

## Observability baseline

Minimum before launch, all wired into the skeleton, not bolted on later:

- **Structured logs** (JSON, one event per line) with a request ID propagated
  through background jobs.
- **Error tracking** (Sentry-class) capturing unhandled exceptions from server,
  browser, and workers, with release tagging.
- **Uptime checks** on `/healthz` and the login page from an external monitor,
  alerting a channel a human actually reads.
- **Job queue depth and failure alerts** — a stalled queue is the most common invisible outage.

## Launch-readiness checklist

Copy into the repo as `LAUNCH.md`, fill in, and review with the user line by line:

```markdown
**Launch readiness — {app name}**

## Correctness
- [ ] All core-job flows pass in staging (list each; link to e2e test)
- [ ] Payments lifecycle verified: purchase, upgrade, payment failure, cancel
- [ ] Webhook signature verification on; replay test performed

## Security
- [ ] Auth rate-limited; password reset tokens expire and are single-use
- [ ] Every tenant-scoped query filtered by account (spot-check three endpoints)
- [ ] Dependencies audited; no known-critical CVEs
- [ ] Secrets rotated out of any dev/test values; none present in git history

## Operations
- [ ] Automated daily database backups; one restore actually rehearsed
- [ ] Rollback procedure written and tested once
- [ ] Error tracking, uptime monitor, and queue alerts firing to {channel}
- [ ] Custom domain, TLS, and www/apex redirect verified

## Business
- [ ] Privacy policy and terms linked; data-deletion request path exists
- [ ] Support contact reachable from the app
- [ ] Owner: {name} — go/no-go decision recorded on {date}
```

## Common failure modes

- **Features before skeleton.** Two weeks of local-only code, then a three-day
  deployment slog that reveals the architecture assumes localhost. Deploy first.
- **Entitlements from the redirect.** Granting access on checkout success-URL
  hit instead of the webhook; users pay and get nothing, or forge access.
- **Non-idempotent webhook and job handlers.** Provider retries double-charge or
  double-email; store and check processed IDs.
- **Cross-tenant leaks.** One forgotten `account_id` filter in a list endpoint.
  Prefer row-level security or a scoped query helper over discipline.
- **JWTs in localStorage** to feel modern; any XSS becomes full account
  takeover. Server sessions in httpOnly cookies are the boring correct default.
- **Resume-driven stack choice.** Microservices, event buses, or a serverless
  mesh for an app with 40 users. The comparison table exists to prevent this.
- **Untested restore.** Backups never restored are hopes; rehearse one restore before launch.
