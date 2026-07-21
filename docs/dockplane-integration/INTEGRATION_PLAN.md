# Dockplane → Fabric integration plan

**Status:** Draft for review · ideation + phased roadmap
**Working name for the rebranded plane:** **Loom** (textile-family, fits Fabric; needs legal/namespace clearance — see [Brand](#5-rebrand-working-name-loom))
**Author:** integration working notes
**Source pack:** [`source-spec/`](./source-spec/) (Dockplane product spec, goal, agents, rebrand map)

---

## 0. TL;DR

- **What we're integrating.** *Dockplane* is a rebrand/hardening plan for `oblien/openship`, an open-source **deployment control plane** (a self-hostable Heroku/Vercel: source → build → deploy to your machine / an SSH Linux host / cloud, with domains, TLS, rollback, backups, RBAC, REST API, and an **MCP endpoint built for AI agents**).
- **The goal.** Make it ours (rebrand) and **cut GitHub CI/CD spend**.
- **The honest constraint.** Dockplane is a **TypeScript/Bun** monorepo; Fabric is **Python**. They do not merge cheaply at the code level. Integration means *run it as a companion service Fabric drives*, *fork+rebrand it*, or *rebuild its concepts in Python*.
- **The honest CI math.** A deploy plane cuts **deploy + Linux build** minutes directly. It does **not** magically remove **macOS/iOS/Windows** minutes (those OSes are inherent to desktop/mobile packaging). Those are cut by (a) **not running them on every PR** and (b) **self-hosted runners** — which the plane's host-adoption/provisioning layer is perfect for managing.
- **The recommendation.** A **nested, three-phase** plan where each phase ships value and you can stop anywhere:
  - **Phase 0 (days):** Cut CI spend *now* with workflow gating + caching. **No Dockplane required.**
  - **Phase 1 (weeks):** Stand up the rebranded plane + self-hosted runners; move build/deploy load off GitHub.
  - **Phase 2 (months):** Fuse the plane into Fabric as an **agent-operable deploy plane**. This is "make it our own."

---

## 1. What each system is (grounded)

### 1.1 Dockplane (the thing we're pulling in)

From the source pack in [`source-spec/`](./source-spec/):

- **Category:** open deployment control plane. Point it at a GitHub repo / local folder / archive / Dockerfile / Compose → it detects the stack, produces an editable build plan, builds, starts a candidate release, health-checks, switches traffic, and keeps rollback/backup data.
- **Destinations:** (1) the machine running the control plane, (2) a Linux host you own over SSH, (3) managed cloud.
- **Surfaces:** Next.js dashboard, CLI, Electron desktop, **REST API under `/api`**, and **an MCP endpoint at `POST /api/mcp`** designed for permission-scoped AI agents.
- **Architecture invariant:** all clients are thin views over one Hono API; only the API writes state; external side-effects go through **adapters** (runtime / infrastructure / system / source / backup / notification).
- **Stack:** TypeScript, Bun/Turborepo monorepo, Hono, Better Auth, Drizzle, PostgreSQL (or embedded PGlite), Redis/BullMQ, Vitest, Apache-2.0.
- **Maturity (per the spec's own straight assessment):** promising core, too-broad scope, root version `0.2.1`, open issues around install, remote Docker/SSH, ingress, desktop auth, DNS automation, and doc drift. The spec's whole thesis is: **define a reliable core, label the rest honestly, and use the rebrand as a hardening boundary.**

### 1.2 Fabric (the host we're integrating into)

- **Category:** local-first **Python** AI agent runtime — CLI, Ink TUI, desktop app, web dashboard, cron, and messaging gateways, all over one agent core.
- **Already has the seeds of a deploy plane:**
  - [`deploy/`](../../deploy/) — `docker-compose.hosted.yml` (always-on gateway + dashboard + Caddy TLS), `provision.sh` (idempotent secret/config seeding), `Caddyfile`, `cloud-init.yaml`.
  - [`deploy/compute-broker/`](../../deploy/compute-broker/) — Vast.ai + vLLM bootstrap to serve a frontier model behind an OpenAI-compatible endpoint.
- **Already has the agent-plane primitives** Dockplane wants a client for: MCP support, a tool/skill system, cron/scheduling, and multi-agent delegation.
- **State:** local by default under `~/.fabric` (`%LOCALAPPDATA%\fabric` on Windows).

### 1.3 Why the two fit

| Fabric has | Dockplane has | Combined |
|---|---|---|
| Agent runtime + MCP client + tools/skills | MCP endpoint **built for agents** | Agents that can *operate* deployments |
| `deploy/` compose + Caddy + provision + cloud-init | Host adoption, SSH provisioning, rollback, backups, domains | The missing control plane over Fabric's raw deploy assets |
| `compute-broker` (spin up GPU boxes) | Destination + runtime adapters | One plane to provision *and* deploy onto those boxes |
| Its own GitHub Actions CI/CD (costly) | Self-hosted build + deploy engine | Move CI/CD load off GitHub |

The fit is real. The catch is language/runtime — addressed in [§4](#4-integration-architecture-options).

---

## 2. The strategic thesis: how a deploy plane saves CI/CD

GitHub Actions bills (or rate-limits) **runner minutes**, weighted by OS:

- Linux standard runner ≈ **1×**
- Windows ≈ **2×**
- macOS ≈ **10×**

Plus artifact **storage/egress** and, for private repos, overage beyond the monthly free minutes.

A deployment control plane attacks this in three ways:

1. **Move the *deploy* step off Actions.** Today a push runs a GitHub-hosted deploy job. With the plane, a push/webhook triggers **your** control plane to build+deploy on **your** box. Those minutes leave GitHub entirely.
2. **Move *Linux build/test* onto owned hardware.** The plane builds as part of deploying; the same boxes can run the heavy Linux test/build matrix as **self-hosted runners**. You trade metered minutes for a flat VPS bill.
3. **Manage a self-hosted runner fleet safely.** The plane's host adoption / SSH / provisioning / health is exactly the layer that keeps self-hosted runners (including a **Mac mini** and a **Windows box** for the 10×/2× jobs) patched, labeled, and healthy — the part everyone skips and regrets.

### 2.1 The honest limits (read this before promising savings)

- **A deploy plane will not remove macOS/iOS/Windows minutes by itself.** Those OSes are *required* to package desktop (Electron) and mobile (iOS) builds. The plane helps you *host your own* macOS/Windows runners; it doesn't let Linux build an iOS app.
- **The single biggest immediate cut needs no Dockplane at all:** stop running the expensive OS jobs on **every PR** (see [§3](#3-current-fabric-ci-cost-map)). That's Phase 0.
- **Public-repo caveat that changes the ROI.** For a **public** repo, GitHub-hosted **standard** runners are **free**. If `ObliviousOdin/fabric` is public, the dollar savings are near-zero until you use *large* runners or blow past storage — the real wins become **speed, control, queue-time, and larger runners**. If the repo is **private**, the macOS/Windows minutes are direct cash. **→ Confirm public vs. private before sizing the savings** (open question O-1 in [§9](#9-open-questions--decision-log)).

---

## 3. Current Fabric CI cost map

Measured from `.github/workflows/` in this repo:

| Workflow | Triggers | Runners | Cost weight | Runs on every PR? |
|---|---|---|---|---|
| `release-channels.yml` | PR, push→main, dispatch | `build` ubuntu → **smoke matrix `[ubuntu-24.04, macos-15, windows-2025]`** → deploy ubuntu | **macOS 10×, Win 2×** | **Yes** |
| `mobile.yml` | PR, push→main | ubuntu → **`macos-15`** (iOS) → ubuntu | **macOS 10×** | **Yes** |
| `desktop-packaging.yml` | PR, push→main, dispatch | ubuntu → **matrix runner (multi-OS Electron)** | mixed, some 10×/2× | **Yes** |
| `public-ci.yml` | PR, push→main, dispatch | ubuntu ×3 | 1× | Yes (cheap) |
| `docs-pages.yml` | push→main | ubuntu | 1× | No |
| `skills-index.yml` | schedule 2×/day | ubuntu | 1× | No |

**Where the money/minutes go:** the macOS + Windows legs of `release-channels`, `mobile`, and `desktop-packaging` — all firing on **every pull request**. That is the Phase 0 target.

---

## 4. Integration architecture options

Because Fabric is Python and Dockplane is TS/Bun, "integrate" resolves to one of three patterns. They are **not** mutually exclusive over time (you can start with A and migrate toward C).

### Option A — Companion service, driven via MCP + REST *(recommended default)*

Run the rebranded plane as a **sidecar service** (its own container(s): API + Postgres + Redis). Fabric drives it through the tooling Fabric already has:

- Fabric registers the plane's **MCP endpoint** as a connector → agents get `deploy`, `rollback`, `logs`, `status` tools with least-privilege tokens.
- Fabric's CLI/skills wrap the plane's **REST `/api`** for scripted deploys.
- The plane lives in `deploy/` alongside the existing compose assets, or in a new `apps/loom/` (git subtree/submodule of the fork).

**Pros:** lowest risk; keeps the plane upstream-mergeable; fastest to a working demo; clean security boundary (the plane holds infra creds, Fabric holds none).
**Cons:** two runtimes to operate (Node + Python); two release trains; heavier resource footprint (Postgres+Redis).

### Option B — Fork & rebrand OpenShip as a Fabric-branded sibling

Fork `oblien/openship` outright, execute the [`REBRAND_MAP`](./source-spec/REBRAND_MAP.md) (dual-brand, compatibility shims), ship it as a Fabric-family product (its own repo or a monorepo folder).

**Pros:** maximum control and "make it our own"; can prune scope to the reliable core; owns the roadmap.
**Cons:** you now maintain a large TS deployment platform *and* Fabric; must track upstream security fixes; the rebrand itself is a multi-week hardening program (the spec is explicit about this).

### Option C — Concepts-only: a lean Python-native deploy plane inside Fabric

Don't ship the TS codebase. Use the **spec** as the design and build a minimal deploy plane in Python that extends the existing `deploy/` + `compute-broker`, exposing the same API/MCP shape.

**Pros:** one runtime; deepest long-term fit; smallest operational footprint; reuses Fabric's job/cron/auth primitives.
**Cons:** most build effort; you re-implement adapters, state machines, and rollback that OpenShip already has; slowest to first value.

### Recommendation

**Start with A** (companion service) to get real deploys + CI offload working in weeks, **while harvesting the spec** so that if/when the maintenance of a TS platform isn't worth it, you can migrate the *surface Fabric depends on* (MCP tools + `/api` contract) to a Python implementation (C) without changing how Fabric calls it. Option B only if owning the full platform is itself a product goal.

> **Fork this decision:** the phases below are written for **Option A**. If you prefer B or C, Phase 1's "stand up the plane" tasks change but Phases 0 and 2 are largely the same.

---

## 5. Rebrand (working name: "Loom")

The source pack uses **Dockplane** as its working name and repeatedly warns it needs trademark/namespace/domain/handle clearance. Since the ask is to "make it our own" and fold it into Fabric, a **textile-family** name keeps the metaphor coherent:

| Candidate | Rationale | Watch-outs |
|---|---|---|
| **Loom** *(lead)* | A loom weaves threads into fabric — i.e., weaves source into running deployments. Short, memorable, on-brand. | `loom.com` (video) exists → clearance needed; possible npm/pkg collisions. |
| **Warp** | The warp is the foundational threads a fabric is built on. Technical, terse. | Common word; several dev tools use it (e.g. Warp terminal). |
| **Keep "Dockplane"** | Zero naming risk now; decide later. | Doesn't "make it our own." |

Whatever the name, **follow [`REBRAND_MAP.md`](./source-spec/REBRAND_MAP.md) discipline** rather than a global find-replace:
- Rename **visible brand** immediately (Class A).
- Dual-support **public technical surfaces** — CLI shim, env vars (`LOOM_*` + legacy `OPENSHIP_*`), data dir, PAT prefix, Docker labels — with precedence + warnings (Class B).
- **Preserve historical data**, internal table/migration names, and third-party/license text (Classes C/D/E).
- Centralize brand constants in one module; keep `/api` and `POST /api/mcp` paths stable.

> **Fork this decision:** name is a working placeholder (open question O-2). Everything below says "the plane" so it survives a name change.

---

## 6. Phased roadmap

Each phase has an **exit test**. You can stop after any phase and keep the value.

### Phase 0 — Cut CI spend now (no Dockplane) · ~days

The fastest, cheapest win. Pure GitHub Actions hygiene.

- **Gate the expensive OS jobs off the every-PR path.** Move the `macos-15` / `windows-2025` legs of `release-channels`, `mobile`, and `desktop-packaging` to run only on: tags/releases, a `full-ci` label, `workflow_dispatch`, or a nightly schedule — not every PR. Keep the **ubuntu** legs on PRs for fast signal.
- **Add `paths:`/`paths-ignore:` filters** so mobile/desktop workflows don't fire on docs- or Python-only changes.
- **Confirm `concurrency: cancel-in-progress` on PRs** everywhere (already present in `release-channels`; replicate in `mobile`/`desktop-packaging`).
- **Tighten caching** (uv, npm, and platform build caches) and **artifact retention** (drop 30-day retentions that aren't needed).
- **Instrument spend first:** capture a baseline from the org's **Actions usage/billing** page so Phase 0's cut is measurable.

**Exit test:** a typical PR triggers **only ubuntu** jobs; macOS/Windows minutes per week drop by the majority; baseline vs. after is documented.

> Depending on the public/private answer (O-1), Phase 0 may already deliver most of the achievable savings. **Do Phase 0 regardless** — Phases 1–2 build on a clean CI.

### Phase 1 — Stand up the plane + self-hosted runners · ~weeks

- **Deploy the plane (Option A).** Add the rebranded control plane to `deploy/` (compose service: API + Postgres + Redis) behind the existing Caddy. Reuse `provision.sh` patterns for secrets. Bind admin to loopback/private; nothing public without explicit TLS + auth (matches the plane's own fail-closed rules and Fabric's `deploy/README` safety notes).
- **Adopt one Linux host** through the plane (read-only scan → approved provisioning plan) — dogfood the host-adoption flow on a cheap VPS (Hetzner/DO/Vultr/Contabo per `deploy/README`).
- **Register self-hosted GitHub Actions runners** on owned boxes:
  - Linux runner(s) for the heavy Linux build/test matrix.
  - Optionally a **Mac mini** + a **Windows** box for the 10×/2× jobs; let the plane keep them provisioned/healthy.
  - Point the gated workflows' `runs-on:` at `self-hosted` labels.
- **Move the deploy step to the plane.** Replace the `deploy-*` jobs in `release-channels.yml` with a webhook/CLI call that hands the verified artifact to the plane, which builds/switches/rolls-back on owned infra.
- **Security:** self-hosted runners must **not** run untrusted PR code from forks (use `pull_request_target` carefully or restrict to trusted branches); scope the plane's tokens least-privilege; keep infra creds only in the plane.

**Exit test:** a merge to `main` builds + deploys Fabric through the plane on owned hardware with logs + a tested rollback; the Linux matrix runs on self-hosted runners; GitHub-metered minutes drop again, measurably.

### Phase 2 — Fuse into Fabric as an agent-operable plane · ~months

This is "make it our own."

- **Expose the plane as first-class Fabric tools/skills.** Register its MCP endpoint as a Fabric connector; ship a `deploy` capability pack so agents can `status / logs / deploy / rollback / restart` under least-privilege, human-approval-gated for destructive ops (the plane already models read-only vs. destructive tool hints).
- **Unify the operator surfaces.** Surface deploy status in Fabric's dashboard/TUI; one login; consistent branding (the rebrand).
- **Wire `compute-broker` in as a destination/runtime adapter** so Fabric can provision a GPU box *and* deploy a workload onto it from one flow.
- **Decide the long-term runtime** (stay on Option A, or migrate the Fabric-facing surface to Python per Option C). Because Fabric only depends on the **MCP tools + `/api` contract**, this swap is invisible to users.
- **Harden per the spec's Milestone 1** (install reliability, SSH/remote-Docker lifecycle, ingress, backup/restore integrity, workspace/permission tests) for the paths Fabric actually uses — don't inherit OpenShip's full scope.

**Exit test:** a Fabric agent, given least-privilege creds, can take a repo from source to a healthy HTTPS endpoint on owned infra and roll back — all from within Fabric, under one brand.

---

## 7. Effort & value at a glance

| Phase | Effort | GitHub-spend impact | "Make it our own" | Risk |
|---|---|---|---|---|
| 0 — CI gating | Days | **High** (if private) / speed+quota (if public) | None | Very low |
| 1 — Plane + runners | Weeks | High (flat VPS cost replaces minutes) | Partial | Medium (ops, runner security) |
| 2 — Fusion | Months | Marginal beyond P1 | **Full** | Medium-high (two runtimes, hardening) |

---

## 8. Risks & mitigations

- **Runtime split (Node + Python).** → Option A isolates it as a service; keep a migration path to C so Fabric never couples to Bun internals.
- **Self-hosted runner security.** → Never run fork PR code on self-hosted runners; ephemeral runners; least-privilege tokens; network isolation.
- **Inheriting OpenShip's maturity gaps.** → Adopt the spec's "reliable core, honest beta" boundary; only harden paths Fabric uses; label the rest beta/experimental.
- **Rebrand breakage.** → Follow `REBRAND_MAP` dual-brand discipline; no global find-replace; keep `/api` + `/api/mcp` stable; migrate only after backup+verify.
- **Public-repo savings mirage.** → Confirm O-1 up front; if public, frame the win as speed/control/large-runners, not dollars.
- **Operational burden of Postgres+Redis.** → Start with the plane's embedded PGlite / single-process mode for evaluation; graduate to Postgres+Redis only for the production plane.
- **License/attribution.** → OpenShip is Apache-2.0 (compatible with Fabric's Apache-2.0); preserve NOTICE/attribution when forking.

---

## 9. Open questions / decision log

| # | Question | Why it matters | Default taken here |
|---|---|---|---|
| O-1 | Is `ObliviousOdin/fabric` **public or private**? | Determines whether CI savings are dollars or speed/quota | Assumed *savings matter* → plan optimizes minutes regardless |
| O-2 | Final **brand name**? | Rebrand scope, namespace/domain clearance | Working name **Loom**; plan is name-agnostic |
| O-3 | **Integration architecture** A / B / C? | Shapes Phase 1 build | **A (companion service)** |
| O-4 | Ambition: stop at Phase 0, 1, or go to 2? | Resourcing | **Phased, all three, stop anywhere** |
| O-5 | Do we need **macOS/iOS** builds at all, or can mobile ship less often? | Biggest single cost lever | Assumed needed but **gated off every-PR** |
| O-6 | Budget/hardware for self-hosted runners (incl. a Mac mini)? | Phase 1 feasibility | TBD |

---

## 10. Immediate next actions

1. **Answer O-1** (public/private) and pull the org's **Actions usage baseline** — one screenshot/export.
2. **Ship Phase 0** as a small PR: gate macOS/Windows/desktop/mobile jobs off the every-PR path + add path filters + confirm concurrency cancels. Measure the drop.
3. **Spike Phase 1** on one cheap VPS: run the rebranded plane via compose in `deploy/`, adopt the VPS as a host, register one self-hosted Linux runner, and move one deploy job to the plane.
4. **Confirm the fork decision** (O-3) and **brand** (O-2) before any rename work.

---

*Source material for this plan lives in [`source-spec/`](./source-spec/): `PRODUCT_SPEC.md`, `GOAL.md`, `AGENTS.md`, `REBRAND_MAP.md`, `README.md` — the Dockplane pack for `oblien/openship` @ `a78cf47`.*
