# Dockplane Product Specification

**Document status:** Product and engineering specification  
**Working brand:** Dockplane  
**Tagline:** Deploy anywhere. Operate from one place.  
**Product category:** Open deployment control plane / application platform  
**Source baseline:** `oblien/openship`, default branch `main`, inspected at commit `a78cf47ccf6ec9a78c7156fe59826f81339ffeed`  
**Source package version:** `0.2.1`  
**Specification version:** `0.1`  
**Date:** 2026-07-20  
**Owner:** Product + Platform Engineering

> **Naming warning:** Dockplane is a working product name selected for this specification. A basic web search did not surface an obvious exact-name deployment platform, but that is not trademark, corporate-name, package-name, social-handle, or domain clearance. Complete formal clearance before publishing the name.

---

## 1. Executive summary

Dockplane is an open-source application delivery platform that turns source code into a running application on one of three destinations:

1. the machine running Dockplane;
2. a Linux server the user controls; or
3. Dockplane Cloud.

The product combines a deployment control plane, build and runtime adapters, traffic routing, certificates, operational tooling, team permissions, a web dashboard, a command-line interface, a desktop application, an HTTP API, and a permission-scoped MCP endpoint for AI agents.

The existing OpenShip repository already contains the core shape of this system. Its strongest architectural decision is that the dashboard, CLI, and desktop application are thin clients over the same Hono API. The API owns product state and delegates host operations to adapter packages rather than embedding Docker, SSH, routing, or cloud behavior directly in client code. The repository also contains substantial surfaces for projects, deployments, services, domains, servers, backups, analytics, notifications, audit, tokens, permissions, managed cloud, billing, and mail.

The repository is ambitious but early. Its root package is version `0.2.1`, its documentation explicitly marks parts of the email system as target-state rather than current-state, and open issue reports cover installation failures, remote Docker and SSH reliability, desktop authentication, plain-HTTP browser behavior, unsafe adoption of existing hosts, missing DNS-provider automation, and documentation drift. The rebrand must therefore be a product hardening program, not a cosmetic rename.

Dockplane 1.0 should ship a smaller, dependable promise:

> Connect a repository or local folder, review an explicit deployment plan, and put the application online on a supported Linux host with logs, HTTPS, rollback, backups, access control, and no hidden platform lock-in.

Managed cloud, desktop-local operation, bare-process execution, advanced mail hosting, multi-node scheduling, and automated DNS integrations can remain available as beta capabilities until they meet the same reliability bar.

---

## 2. What the current repository is

### 2.1 Plain-English explanation

OpenShip is a self-hostable platform-as-a-service and deployment control plane. It aims to give developers a Heroku- or Vercel-like workflow without forcing them to use a proprietary runtime or surrender their server.

A user points the product at a GitHub repository, a local directory, a URL/template, or a Compose file. The platform detects the stack, decides how to install and build it, starts a new release, waits for it to become healthy, connects a domain, and routes traffic to it. The same project can run on the local Dockplane machine, on a remote server over SSH, or in a managed cloud workspace.

The product is not just a UI over `docker run`. It has a persistent control plane that stores organizations, users, projects, environments, deployments, services, domains, settings, credentials, backup policies, audit events, and related state. Long-running and queued work is separated from request handling. Runtime and infrastructure operations are accessed through adapters.

### 2.2 Existing client surfaces

The repository provides four operator surfaces:

| Surface | Role |
|---|---|
| Web dashboard | Full graphical product experience for projects, deployments, servers, backups, team settings, billing, and other administration. |
| CLI | Installation, login, project linking, deployment, scripting, automation, CI, and direct operational commands. |
| Desktop app | Electron wrapper that can launch a local API and dashboard for a single-user machine. |
| API and MCP | Programmatic access for scripts, integrations, CI systems, and permission-scoped AI agents. |

These surfaces are intended to represent the same system state. Product logic must not diverge by client.

### 2.3 Existing control-plane shape

The documented architecture is:

```text
Dashboard ─┐
CLI ───────┼── HTTP /api/* ──> Hono API ──> database / queue
Desktop ───┘                         │
                                    └── platform adapters
                                          ├── runtime: Docker / bare / cloud
                                          ├── infra: routing / certificates
                                          └── system: checks / provisioning
```

The API is the only application component that should write platform state. This makes it possible to start a deployment in one interface and inspect or operate it from another without reconciling separate local models.

### 2.4 Existing technical stack

The inspected repository uses:

- TypeScript in a Bun/Turborepo monorepo;
- Node.js 22 or later as the supported Node runtime;
- Hono for the API;
- Better Auth for authentication;
- TypeBox and Zod for validation;
- Drizzle for database access;
- PostgreSQL for server installs and PGlite for embedded installs;
- Redis, BullMQ, and related stores for queues, cache, and rate limiting;
- Next.js, React, Tailwind, and shared UI packages for web interfaces;
- Electron for desktop packaging;
- Docker or direct host processes for self-managed runtimes;
- OpenResty and Certbot for self-hosted routing and HTTPS;
- Vitest for test suites;
- an Apache-2.0 license.

### 2.5 Existing product strengths

The most valuable product and architecture assets are:

1. **One control plane, several destinations.** Local, owned-server, and managed-cloud targets use one project model.
2. **Data ownership.** Self-hosted data can remain on the operator's infrastructure and can be exported.
3. **Portability.** Docker and ordinary Linux primitives reduce proprietary-runtime dependence.
4. **Thin clients.** Web, CLI, and desktop clients are views over one API.
5. **Explicit adapter boundary.** Runtime, infrastructure, and system behavior can evolve without contaminating every feature module.
6. **Scoped automation.** PATs and MCP connections can be read-only or resource-scoped and pass through the same permission system.
7. **Operational breadth.** Deployments, domains, backups, logs, teams, audit, and server access are designed as one product rather than separate tools.

### 2.6 Existing maturity gaps

The current repository should not be positioned as a finished, universally production-ready alternative to mature deployment platforms. The following are material launch risks:

- installation and packaging reports on clean Linux hosts;
- remote Docker and SSH connection lifecycle failures;
- OpenResty installation and host-ingress assumptions;
- browser failures when a self-hosted dashboard is served over insecure HTTP;
- unsafe mutation of hosts that already run Nginx, Certbot, or containers;
- manual DNS setup and a mismatch between wildcard-certificate marketing and current DNS-provider automation;
- incomplete or drifting documentation;
- desktop login/cookie edge cases;
- a broad mail-hosting subsystem whose own architecture document says it is moving toward a target state;
- multi-node, private networking, advanced monitoring, and autoscaling claims that should remain roadmap items until verified.

Dockplane's first product requirement is therefore trustworthiness.

---

## 3. Brand system

### 3.1 Working name

**Dockplane**

### 3.2 Name rationale

- **Dock** communicates the place where source arrives, is inspected, built, and prepared to run.
- **Plane** communicates a control plane that coordinates applications across different execution locations.
- The name does not limit the product to managed cloud or to Kubernetes.
- The metaphor supports a coherent vocabulary without forcing nautical language into every UI label.

### 3.3 Brand promise

> Dockplane gives developers one dependable control plane for deploying and operating applications on infrastructure they choose.

### 3.4 Positioning line

> An open deployment platform for your laptop, your servers, and managed cloud.

### 3.5 Message hierarchy

1. **Deploy anywhere.** Use the local machine, an owned Linux server, or managed compute.
2. **Operate from one place.** Projects, releases, domains, logs, backups, access, and automation share one control plane.
3. **Keep an exit.** Use standard containers, export platform data, and avoid a proprietary application runtime.
4. **Automate safely.** The API, CLI, and MCP tools use the same permission plane.
5. **Know what will change.** Host preflight and deployment plans are visible before mutation.

### 3.6 Voice

The brand should sound:

- technically precise;
- calm under failure;
- explicit about risks and destructive actions;
- respectful of operator ownership;
- free of exaggerated “zero configuration” claims when configuration is merely inferred;
- clear about beta and unsupported combinations.

Avoid phrases such as “magic,” “works with everything,” “production ready” without a qualification, and “zero downtime” for paths where the runtime cannot provide it.

### 3.7 Product vocabulary

| Current term | Dockplane term |
|---|---|
| Organization / workspace | Workspace |
| Project | Project |
| Environment | Environment |
| Deployment | Release attempt in user-facing prose; `deployment` remains the API/data term |
| Service | Service |
| Server | Host |
| Deploy target | Destination |
| Local | This machine |
| Server | Your host |
| Cloud | Dockplane Cloud |
| Sandboxed | Container |
| Direct / bare | Process |
| OpenShip Cloud | Dockplane Cloud |
| Openship instance | Dockplane control plane |

The API may retain existing entity names where changing them would create needless compatibility risk.

### 3.8 Proposed naming tokens

| Surface | New canonical form |
|---|---|
| Product | Dockplane |
| CLI binary | `dockplane` |
| npm package | `dockplane` |
| Package scope | `@dockplane/*` |
| Desktop product name | Dockplane |
| Data directory | `~/.dockplane` |
| PAT prefix | `dpl_pat_` |
| User agent | `dockplane/<version>` |
| Docker labels | `dockplane.project`, `dockplane.deployment`, `dockplane.service`, `dockplane.build` |
| Export file | `dockplane-export-<timestamp>.json` |
| Environment-variable prefix | `DOCKPLANE_` |
| Placeholder cloud domains | `app.<cleared-domain>`, `api.<cleared-domain>`, `*.run.<cleared-domain>` |

All public domain names in planning documents are placeholders until ownership is confirmed.

---

## 4. Product vision

### 4.1 Vision

Any developer should be able to turn ordinary source code into a recoverable, observable, secure application release on infrastructure they understand and can leave.

### 4.2 Mission

Make application delivery dependable without making infrastructure ownership an all-or-nothing choice.

### 4.3 North-star outcome

A user with a supported repository and a fresh supported Linux host can go from sign-in to a healthy HTTPS endpoint in ten minutes or less, with a clear record of what Dockplane changed and a tested rollback path.

### 4.4 Strategic thesis

Most simple deployment products optimize one of two extremes:

- exceptional developer experience on proprietary managed infrastructure; or
- full infrastructure ownership with considerable operational assembly.

Dockplane should occupy the middle: a consistent product experience that works against infrastructure chosen by the operator. The managed cloud is an optional destination, not the definition of the product.

### 4.5 Product goals

1. Make first deployment predictable.
2. Make every release recoverable.
3. Make host mutation inspectable and reversible.
4. Keep client behavior consistent through one API.
5. Keep self-hosted state portable.
6. Make agent automation least-privilege by default.
7. Establish a hard boundary between stable core and beta extensions.

### 4.6 Non-goals for 1.0

Dockplane 1.0 is not:

- a general-purpose Kubernetes distribution;
- a full infrastructure-as-code replacement;
- a multi-cloud network fabric;
- a managed database vendor;
- an email deliverability business;
- a replacement for every observability stack;
- a desktop development environment;
- a general CI system for arbitrary non-deployment workflows;
- a server control panel for unrelated workloads;
- a promise that every language or framework is auto-detected correctly;
- a guarantee of zero downtime in process mode;
- a system that silently takes ownership of an existing host.

---

## 5. Users and jobs to be done

### 5.1 Primary persona: independent developer

**Profile:** One developer or a very small team shipping websites, APIs, bots, workers, and small SaaS products.

**Jobs:**

- put a repository online without writing a CI pipeline;
- deploy to an affordable VPS;
- see build errors without SSH archaeology;
- attach a domain and HTTPS;
- roll back a bad release;
- back up stateful services;
- move providers without rebuilding the platform model.

**Success:** A project can be operated without becoming a part-time infrastructure engineer.

### 5.2 Primary persona: small product team

**Profile:** Two to twenty engineers with production and preview environments, shared credentials, and a need for basic governance.

**Jobs:**

- standardize deployment across projects;
- separate production and preview settings;
- restrict access to specific projects or hosts;
- review audit events;
- connect CI and internal automation;
- avoid giving every developer root access;
- retain the option to run sensitive workloads on owned infrastructure.

**Success:** The team has a consistent release workflow with fewer one-off server scripts.

### 5.3 Primary persona: self-hosting operator

**Profile:** Technical operator running a homelab, agency infrastructure, private VPS fleet, or customer-owned servers.

**Jobs:**

- inspect a host before Dockplane changes it;
- coexist with existing services;
- route public traffic separately from the management network;
- use Tailscale or private SSH paths;
- know which containers, volumes, services, routes, and certificates Dockplane owns;
- export all control-plane data;
- recover after an upgrade or machine loss.

**Success:** Dockplane is a well-behaved tenant, not a host takeover script.

### 5.4 Secondary persona: platform engineer

**Profile:** Engineer evaluating Dockplane as an internal application platform.

**Jobs:**

- expose a paved deployment path;
- integrate through REST, webhooks, and MCP;
- enforce organization and resource permissions;
- use external databases, Redis, S3, SFTP, and GitHub Apps;
- inspect deployment and audit events;
- extend runtime and infrastructure adapters.

**Success:** Teams use a supported path without bypassing organizational controls.

### 5.5 Secondary persona: AI coding or operations agent

**Profile:** An agent acting through an MCP client or API token.

**Jobs:**

- list projects and deployment status;
- inspect logs and configuration;
- trigger a scoped deployment;
- perform a low-risk restart;
- propose a domain or environment-variable change;
- avoid access to unrelated projects;
- avoid credential minting or privilege escalation.

**Success:** Automation is useful without granting broad, ambient authority.

---

## 6. Product principles

### 6.1 Plan before mutation

Dockplane must show what it intends to install, write, restart, expose, or delete before touching a host. A failed preflight must not leave a partially adopted machine.

### 6.2 One source of product truth

The API owns product state. Clients do not write the database directly, maintain shadow truth, or reimplement authorization.

### 6.3 Safe defaults over clever fallback

Authentication, permissions, secret handling, networking, and destructive operations fail closed. The system must not silently weaken isolation or authentication because a dependency is unavailable.

### 6.4 Recoverability is a feature, not documentation

A deployment is incomplete until health evaluation, rollback metadata, and operator-visible logs exist. A backup is incomplete until its destination is verified and restore has a tested path.

### 6.5 Portability must be demonstrable

“Portable” means the user can export state, understand runtime artifacts, and redeploy elsewhere. It is not merely a marketing statement about Docker.

### 6.6 Capability parity, presentation flexibility

Dashboard, CLI, API, and MCP may present different interaction models, but they must call the same business operations and enforce the same permissions.

### 6.7 Stable core, honest beta

Every capability receives a maturity label: stable, beta, experimental, or planned. Documentation, UI, API metadata, and release notes must agree.

### 6.8 Existing infrastructure is presumed valuable

Dockplane must never assume a connected server is disposable. It must discover conflicts and require explicit approval before changing shared host services.

---

## 7. Scope and release tiers

### 7.1 Dockplane Core 1.0 — stable scope

The 1.0 stability contract covers:

- self-hosted control plane on a supported single Linux host;
- PostgreSQL and Redis production configuration;
- local development with PGlite where explicitly supported;
- local-folder and GitHub repository sources;
- single-service and Docker Compose projects;
- container runtime on the control-plane host;
- container runtime on one connected Linux host over SSH;
- project, environment, service, deployment, and domain management;
- environment-variable and secret management;
- deterministic build plans and editable commands;
- deployment logs and runtime logs;
- health checks, release switching, redeploy, restart, cancel, and rollback;
- custom domains and non-wildcard HTTPS;
- backup destinations, policies, runs, verification, and restore;
- workspaces, roles, restricted grants, audit, PATs, and scoped tokens;
- web dashboard, CLI, REST API;
- read-only MCP plus explicitly authorized mutating tools;
- data export/import;
- update and rollback of the Dockplane control plane;
- documented support matrix and troubleshooting.

### 7.2 Beta scope

Beta capabilities may be shipped, but are not part of the 1.0 reliability guarantee:

- desktop app and zero-auth local mode;
- process/bare runtime;
- managed Dockplane Cloud destination;
- preview environments generated for pull requests;
- DNS-provider integrations and wildcard certificates;
- automated host adoption/import of pre-existing workloads;
- service shell and SSH terminal;
- advanced analytics;
- external ingress and tunnel providers;
- sleep mode and autoscaling;
- mail-server provisioning and webmail;
- migration of a project between self-hosted and cloud;
- multi-service monorepo auto-discovery beyond Compose.

### 7.3 Experimental or later

- multi-node self-hosted scheduling;
- high-availability control plane;
- private service networks spanning hosts;
- canary and percentage traffic shifting;
- visual arbitrary CI pipelines;
- GPU scheduling;
- organization SSO/SCIM;
- policy-as-code;
- fleet-wide secret rotation;
- managed databases as a service;
- cross-region deployment;
- marketplace extensions.

### 7.4 Feature maturity representation

Every UI and documentation page must display one of:

- **Stable** — covered by compatibility and reliability commitments;
- **Beta** — usable, but behavior or support matrix can change;
- **Experimental** — opt-in, no production promise;
- **Planned** — not available.

A feature may not be marketed as stable because code exists. Stability requires tests, documentation, upgrade behavior, support boundaries, and operational evidence.

---

## 8. Core user journeys

### 8.1 Journey A — install a self-hosted control plane

1. User selects a supported installation method.
2. Installer checks operating system, architecture, ports, disk, memory, Docker, DNS expectations, and conflicting services.
3. Installer prints a plan and generated secrets.
4. User confirms.
5. Dockplane installs from a versioned image or signed release artifact.
6. Health endpoint becomes ready.
7. First-run setup creates the initial owner through an internal, one-shot path.
8. Dashboard opens over localhost or a configured HTTPS origin.
9. Product records installation version and update channel.
10. User can export an installation diagnostic bundle with secrets removed.

**Requirements:**

- Prebuilt versioned images and binaries are the default. Building the platform from source is a contributor path, not the normal installation path.
- Installation must be idempotent.
- An interrupted installation must resume or roll back.
- The installer must never publish PostgreSQL or Redis to the host network by default.
- Public access requires explicit origin, TLS, and authentication configuration.
- Plain HTTP on a non-loopback address must trigger a blocking warning for browser features that require secure context.
- A fresh supported-host install is part of every release's automated test matrix.

### 8.2 Journey B — connect a source and create a project

1. User chooses GitHub, local folder, uploaded archive, template URL, or Compose.
2. Dockplane validates source access.
3. Detector identifies project roots, language/runtime, package manager, install command, build command, start command, output directory, ports, and services.
4. Product presents a proposed build plan with confidence and evidence.
5. User edits or accepts the plan.
6. User chooses workspace and initial environment.
7. Product stores source metadata and configuration.

**Requirements:**

- Detection never hides inferred values.
- Every inferred field states why it was selected.
- Low-confidence detection blocks auto-deploy until reviewed.
- Secrets are never inferred from repository files into platform state.
- Monorepo roots and changed-file filters are explicit.
- Repository access uses a GitHub App or a narrowly scoped token; cloud private keys do not reside on self-hosted instances.

### 8.3 Journey C — add an owned host

1. User enters management address, port, username, and credential.
2. Dockplane probes reachability and host identity.
3. Host key is shown and pinned.
4. A read-only adoption scan inventories OS, architecture, disk, memory, Docker, ports, firewalls, Nginx/OpenResty, Certbot, containers, networks, volumes, systemd units, and existing Dockplane artifacts.
5. Product classifies every planned change as create, reuse, conflict, or destructive.
6. User selects managed ingress mode:
   - Dockplane-managed ingress;
   - external ingress;
   - tunnel/provider ingress;
   - no public ingress.
7. User approves a plan.
8. Dockplane installs only approved prerequisites.
9. Host receives an ownership record and can be re-scanned later.

**Requirements:**

- Scan is read-only.
- Host key changes block connection until re-approved.
- Existing Nginx/OpenResty configuration is never edited without an explicit diff.
- Existing containers are not imported or labeled automatically.
- The product can manage applications without managing public ingress.
- Management and public addresses are independent fields.
- Credentials are encrypted at rest.
- SFTP and exec channels are closed deterministically and tested for leaks.
- Removing a host from Dockplane does not delete workloads by default.

### 8.4 Journey D — deploy

1. User selects project, environment, destination, runtime mode, and build location.
2. Dockplane shows a deployment plan.
3. Product creates an immutable deployment record that snapshots source revision, commands, environment references, resource limits, destination, runtime, and routing intent.
4. Build executes as a queued job.
5. Logs stream as structured events and human-readable text.
6. Artifact is produced and verified.
7. New release starts in isolation.
8. Health checks pass.
9. Traffic switches.
10. Old release enters retention or cleanup.
11. Notifications and audit events are emitted.

**Requirements:**

- One active deployment mutation per project environment.
- Shared host mutations are serialized.
- Build cancellation must clean temporary artifacts.
- A failed release before traffic switch leaves the current release untouched.
- Container releases support overlap and zero-downtime switching where the configured health check permits.
- Process releases disclose that a brief gap can occur.
- Every terminal state has a machine code, operator message, and remediation hint.
- A deployment cannot be “successful” if routing or required health checks failed.
- Logs remain available after job completion according to retention policy.

### 8.5 Journey E — attach a domain

1. User enters domain and target environment/service.
2. Dockplane determines required DNS records.
3. Product distinguishes management address, origin address, and public ingress address.
4. User creates records manually or authorizes a supported DNS provider.
5. Product verifies control and resolution.
6. Certificate is issued.
7. Route becomes active.
8. Renewal is monitored.

**Requirements:**

- DNS verification must use authoritative results, not only the control-plane resolver cache.
- Product displays exact records and propagation state.
- Wildcard certificates are beta until DNS-01 automation is available.
- Certificate failure never takes down an existing valid route.
- External-ingress mode can produce upstream routing instructions without installing OpenResty.
- The product reports renewal expiry risk before service impact.

### 8.6 Journey F — roll back

1. User opens release history.
2. Product shows source revision, artifact identity, config snapshot, migration note, and health history.
3. User chooses rollback.
4. Dockplane verifies that retained artifacts and required secrets still exist.
5. Product starts or reactivates the selected release.
6. Health check passes.
7. Traffic switches.
8. Rollback event is audited.

**Requirements:**

- Rollback is a new operation with its own status, not silent mutation of old history.
- Database rollback is not implied by application rollback.
- If schema compatibility is uncertain, UI must warn and offer backup/restore guidance.
- Rollback must be tested automatically for every stable runtime.

### 8.7 Journey G — back up and restore

1. User adds and verifies a destination: S3-compatible, SFTP, existing host, or local disk where supported.
2. User creates a service or project policy.
3. Policy defines schedule, retention, pre-deploy behavior, and hooks.
4. Runs execute independently of browser sessions.
5. Restore begins with a non-destructive download and integrity check.
6. User confirms destructive apply.
7. Service stops, data is replaced, service restarts, and health is checked.
8. Audit and notification events are emitted.

**Requirements:**

- Destination verification writes, reads, and removes a test object.
- Unverified destinations cannot be selected for stable policies.
- Restore is a two-phase operation.
- Product recommends a fresh backup of current state before apply.
- Checksums and size are verified.
- Backup success rates and last verified restore are visible.
- A “backup exists” badge must not imply the backup has been restore-tested.

### 8.8 Journey H — authorize an agent

1. User opens MCP settings or creates a scoped PAT.
2. User selects read-only/full-control and resource grants.
3. OAuth clients complete PKCE consent where supported.
4. Agent sees only allowed tools.
5. Every tool call re-enters API authentication, validation, and authorization.
6. Destructive tools carry explicit hints and can require human confirmation.
7. User revokes the client or token at any time.

**Requirements:**

- Auth, token, and MCP administration routes can never be exposed as agent tools.
- Scoped clients cannot list resources outside their grants.
- Read-only credentials cannot mutate.
- A destructive tool must not be auto-approved solely because a client has write access.
- Audit events identify the agent client and human grant owner.
- MCP must not become a parallel business-logic implementation.

---

## 9. Information architecture

### 9.1 Global navigation

Stable dashboard navigation:

- Overview
- Projects
- Hosts
- Backups
- Activity
- Settings

Conditional navigation:

- Cloud
- Billing
- Email (beta)
- Library/templates
- Documentation/help

### 9.2 Workspace switcher

The workspace switcher must:

- show active role;
- display whether the workspace is local or cloud-owned;
- prevent accidental cross-workspace operations;
- persist the last selection per client;
- never override an org-scoped token.

### 9.3 Project navigation

Each project contains:

- Overview
- Releases
- Services
- Domains
- Environment
- Logs
- Backups
- Analytics
- Settings

### 9.4 Host navigation

Each host contains:

- Overview
- Adoption scan
- Workloads
- Networking
- Certificates
- Resource usage
- Terminal (beta)
- Activity
- Settings

### 9.5 Global activity

A unified activity feed combines:

- deployments;
- rollbacks;
- restarts;
- domain and certificate changes;
- backup and restore events;
- host provisioning;
- user, token, and agent actions;
- billing events where applicable.

Activity is not a replacement for the immutable audit log. The feed is optimized for operations; audit is optimized for accountability.

---

## 10. Functional requirements

Priority codes:

- **P0** — required for stable 1.0;
- **P1** — required soon after 1.0 or for a complete beta;
- **P2** — later;
- **P3** — exploratory.

### 10.1 Identity, authentication, and workspaces

| ID | Requirement | Priority |
|---|---|---|
| ID-001 | Every resource must resolve to exactly one workspace unless it is explicitly system-global. | P0 |
| ID-002 | The system must support owner, admin, member, and restricted roles. | P0 |
| ID-003 | Restricted members must have no access by default and receive explicit resource grants. | P0 |
| ID-004 | Grants must support read, write, and admin levels, with higher levels satisfying lower levels. | P0 |
| ID-005 | Project grants must inherit to deployments, services, domains, and project environment variables. | P0 |
| ID-006 | Host grants must inherit to runtime operations and terminal access on that host. | P0 |
| ID-007 | Every API route must declare a permission tag. The API must refuse startup when a mounted route lacks one. | P0 |
| ID-008 | Cross-workspace resource probing must return not-found behavior rather than reveal existence. | P0 |
| ID-009 | Dashboard authentication must use signed, httpOnly cookies with secure attributes appropriate to the origin. | P0 |
| ID-010 | PATs must be high-entropy, shown once, stored only as hashes, revocable, expirable, workspace-bound, and optionally read-only or resource-scoped. | P0 |
| ID-011 | Bearer credentials from trusted dashboard browser origins must be rejected to reduce replay of stolen tokens. | P0 |
| ID-012 | Desktop zero-auth mode must be limited to an explicitly enabled loopback-only process and must never activate for public or CLI-managed instances. | P0 for desktop beta |
| ID-013 | Authentication subsystem failure must return an unavailable error and must never fall through to a weaker authentication mode. | P0 |
| ID-014 | OAuth login with GitHub and Google may be enabled by the operator, but local email/password authentication must remain available for self-hosted installs. | P1 |
| ID-015 | Session, token, invite, and agent revocation must take effect on the next authorization check. | P0 |
| ID-016 | Ownership transfer must require recent authentication and explicit confirmation. | P1 |
| ID-017 | Enterprise SSO and SCIM are out of stable 1.0 scope. | P2 |

### 10.2 Source connections

| ID | Requirement | Priority |
|---|---|---|
| SRC-001 | Projects must support GitHub repository sources. | P0 |
| SRC-002 | Projects must support a local folder or uploaded archive source. | P0 |
| SRC-003 | Projects must support Docker Compose files without translating away unsupported fields silently. | P0 |
| SRC-004 | URL/template deployment must record the original source and resolved content revision. | P1 |
| SRC-005 | Source credentials must be encrypted at rest and excluded from logs, exports without passphrase protection, and diagnostic bundles. | P0 |
| SRC-006 | GitHub App installation access must be used for managed multi-tenant cloud. | P0 for Cloud beta |
| SRC-007 | Self-hosted deployments must not require possession of the managed cloud's GitHub App private key. | P0 |
| SRC-008 | Users must select repository, branch, project root, and automatic-deployment policy. | P0 |
| SRC-009 | Commit SHA must be snapshotted for every Git-backed deployment. | P0 |
| SRC-010 | Webhooks must verify signatures, deduplicate delivery IDs, and be safe to retry. | P0 |
| SRC-011 | Monorepo changed-file filters must not skip a deployment when shared dependencies changed. | P1 |
| SRC-012 | Future GitLab, Bitbucket, and generic Git support must use the source-provider interface rather than GitHub-specific branches in deployment services. | P2 |

### 10.3 Stack detection and build plans

| ID | Requirement | Priority |
|---|---|---|
| BLD-001 | Dockplane must detect supported language/runtime, package manager, project root, install command, build command, start command, output directory, and likely port. | P0 |
| BLD-002 | Detection output must include confidence and evidence. | P0 |
| BLD-003 | Users must be able to override every inferred command or path. | P0 |
| BLD-004 | Accepted build settings must become an explicit versioned build plan. | P0 |
| BLD-005 | Lockfiles must determine package manager when unambiguous. | P0 |
| BLD-006 | A repository with conflicting lockfiles must require user selection rather than guessing. | P0 |
| BLD-007 | The build pipeline must expose named phases: prepare, source, install, build, package, and verify. | P0 |
| BLD-008 | Build logs must identify phase, timestamp, stream, and attempt. | P0 |
| BLD-009 | Build execution must have CPU, memory, disk, duration, and output-size limits. | P0 |
| BLD-010 | Build caches must be namespaced by workspace, project, source revision inputs, platform, and toolchain. | P1 |
| BLD-011 | Secrets used during build must not persist in final images or cache keys by default. | P0 |
| BLD-012 | Build location must be independent of runtime destination where supported. | P1 |
| BLD-013 | Build artifacts must have an immutable digest and provenance record. | P0 |
| BLD-014 | Artifact verification must confirm that the expected image or package exists before deployment begins. | P0 |
| BLD-015 | Build cancellation must terminate child processes and clean temporary resources. | P0 |
| BLD-016 | User-defined build images are allowed only from explicitly configured registries and must be visible in the plan. | P1 |
| BLD-017 | Supply-chain signing and SBOM generation are recommended for 1.x and required before enterprise positioning. | P1 |

### 10.4 Projects, environments, and services

| ID | Requirement | Priority |
|---|---|---|
| PRJ-001 | A project represents one deployable product and belongs to one workspace. | P0 |
| PRJ-002 | Projects must support production, preview, and development environment types. | P0 |
| PRJ-003 | Environments must maintain separate deployments, domains, environment variables, and destination defaults. | P0 |
| PRJ-004 | Production is the only default stable environment. Preview creation is opt-in. | P0 |
| PRJ-005 | A project may contain one service or multiple services. | P0 |
| PRJ-006 | Compose services must preserve service dependencies, private ports, public ports, volumes, health checks, and commands where supported. | P0 |
| PRJ-007 | Unsupported Compose fields must produce a blocking or explicit degraded-mode message. | P0 |
| PRJ-008 | Each service may have its own start command, health check, resources, route, and backup policy. | P0 |
| PRJ-009 | A service must be private unless explicitly exposed. | P0 |
| PRJ-010 | Environment variables must support plain and secret values, environment scope, service scope, bulk import, and audit history without revealing secret values. | P0 |
| PRJ-011 | Secret values must never be returned after creation except through an explicit secure replacement/export flow. | P0 |
| PRJ-012 | Deleting a project must present retained deployments, volumes, backups, domains, and host artifacts and require a selected cleanup policy. | P0 |
| PRJ-013 | Project deletion must be asynchronous, resumable, auditable, and idempotent. | P0 |
| PRJ-014 | Project transfer between workspaces must validate destination permissions and resource compatibility. | P2 |

### 10.5 Deployment orchestration

| ID | Requirement | Priority |
|---|---|---|
| DEP-001 | Every deployment must snapshot source, build plan, runtime plan, destination, environment references, resource limits, health checks, and routing intent. | P0 |
| DEP-002 | A deployment snapshot must not change after execution starts. A change creates a new deployment. | P0 |
| DEP-003 | Deployment operations must be processed as durable jobs rather than tied to HTTP request lifetime. | P0 |
| DEP-004 | At most one mutating deployment operation may run per project environment. | P0 |
| DEP-005 | Shared host routing and system mutations must be serialized or transactionally coordinated. | P0 |
| DEP-006 | Job retries must be stage-aware and idempotent. | P0 |
| DEP-007 | A retry must not create duplicate active containers, routes, certificates, or audit events. | P0 |
| DEP-008 | A container deployment must start the candidate release before switching traffic. | P0 |
| DEP-009 | Existing live traffic must remain on the previous healthy release until candidate health succeeds. | P0 |
| DEP-010 | Health failure before traffic switch must mark the candidate failed and leave the previous release active. | P0 |
| DEP-011 | Failure after traffic switch must trigger configured auto-revert policy. | P0 |
| DEP-012 | Process mode must disclose stop/start downtime and attempt to restart the previous release on failure. | P0 for process beta |
| DEP-013 | Deployment status must be represented by a documented state machine. | P0 |
| DEP-014 | Operators must be able to cancel queued and cancelable running deployments. | P0 |
| DEP-015 | Cancellation after an irreversible stage must explain what completed and what cleanup remains. | P0 |
| DEP-016 | Redeploy must create a new deployment attempt using a selected historical or current configuration snapshot. | P0 |
| DEP-017 | Rollback must verify artifact availability and environment compatibility before apply. | P0 |
| DEP-018 | Release retention must be configurable by count and age, with at least one known-good release retained by default. | P0 |
| DEP-019 | A database migration command, when configured, must run in an explicit stage with logs and failure semantics. | P1 |
| DEP-020 | The product must never imply that application rollback reverses database migrations. | P0 |
| DEP-021 | Preview releases must have bounded lifetime, cleanup, and cost/resource limits. | P1 |
| DEP-022 | Deployment concurrency across independent hosts may scale horizontally after durable locking is proven. | P2 |

### 10.6 Runtime destinations and isolation

| ID | Requirement | Priority |
|---|---|---|
| RUN-001 | A deployment destination must be one of this machine, an owned host, or Dockplane Cloud. | P0 |
| RUN-002 | Destination selection must be snapshotted per deployment. | P0 |
| RUN-003 | Container mode is the default stable runtime for self-managed hosts. | P0 |
| RUN-004 | Each single-service container deployment must have a unique name and immutable ownership labels. | P0 |
| RUN-005 | Multi-service projects must receive a project-scoped private network. | P0 |
| RUN-006 | Named volumes must be project-scoped to prevent accidental cross-project reuse. | P0 |
| RUN-007 | Existing unscoped volumes must be detected and protected from accidental adoption. | P0 |
| RUN-008 | Public services must use dynamic host ports behind the router unless external-ingress mode requires a different explicit plan. | P0 |
| RUN-009 | Memory limits must be enforced where the runtime supports hard limits. | P0 |
| RUN-010 | CPU, memory, and disk limits must report whether they are hard, weighted, advisory, or unsupported. | P0 |
| RUN-011 | Process mode must be labeled weaker isolation and must not be recommended for untrusted multi-tenant workloads. | P0 |
| RUN-012 | Runtime cleanup must remove only resources positively owned by Dockplane. | P0 |
| RUN-013 | Ownership must be established using labels plus an internal resource record; names alone are insufficient. | P0 |
| RUN-014 | Cloud workspaces must be isolated by tenant and deployment according to a documented cloud threat model. | P0 for Cloud beta |
| RUN-015 | Kubernetes support, if added, must be a runtime adapter and must not become a prerequisite for core product operation. | P2 |

### 10.7 Host management and provisioning

| ID | Requirement | Priority |
|---|---|---|
| HST-001 | Host connection must support key-based SSH and may support passwords for initial setup. | P0 |
| HST-002 | SSH host keys must be pinned. | P0 |
| HST-003 | Management address, public application address, and ingress address must be separate concepts. | P0 |
| HST-004 | A read-only scan must precede provisioning. | P0 |
| HST-005 | Scan results must include operating system, architecture, resources, package manager, Docker, ports, firewall, proxy, certificates, existing workloads, and Dockplane ownership markers. | P0 |
| HST-006 | Provisioning must generate an operator-visible plan and diff. | P0 |
| HST-007 | Existing Nginx, OpenResty, Caddy, Traefik, Apache, or Certbot installations must be treated as conflicts or integration points, not overwritten. | P0 |
| HST-008 | External-ingress mode must allow Dockplane to run workloads without managing ports 80/443. | P0 |
| HST-009 | Host prerequisites must be version-pinned and installed through idempotent steps. | P0 |
| HST-010 | Provisioning failure must produce a cleanup/recovery plan. | P0 |
| HST-011 | All SSH, SFTP, tunnel, and Docker-over-SSH channels must have bounded lifetime and deterministic closure. | P0 |
| HST-012 | Connection pools must expose health, idle timeout, maximum sessions, and reset behavior. | P0 |
| HST-013 | Host removal must offer detach, stop managed workloads, or destructive cleanup as separate explicit choices. | P0 |
| HST-014 | Existing workload import is beta and requires positive recognition plus operator mapping. | P1 |
| HST-015 | A future outbound agent/deployer model must preserve the same permission and ownership semantics. | P2 |

### 10.8 Networking, domains, and certificates

| ID | Requirement | Priority |
|---|---|---|
| NET-001 | Dockplane-managed ingress must route by hostname to the current healthy release. | P0 |
| NET-002 | Routing configuration changes must be validated before reload. | P0 |
| NET-003 | Router reload failure must preserve the previous working configuration. | P0 |
| NET-004 | Domain records must support draft, pending verification, active, error, and detached states. | P0 |
| NET-005 | Custom-domain verification must prevent one workspace from claiming another workspace's domain. | P0 |
| NET-006 | The product must generate exact A/AAAA/CNAME/TXT instructions appropriate to the ingress mode. | P0 |
| NET-007 | Automatic certificate issuance and renewal must support non-wildcard domains in stable 1.0. | P0 |
| NET-008 | Wildcard issuance requires DNS-01 provider integration and remains beta until available. | P1 |
| NET-009 | DNS-provider tokens must be minimally scoped, encrypted, and provider-specific. | P1 |
| NET-010 | Existing certificates must not be replaced while still valid unless renewal or operator action requires it. | P0 |
| NET-011 | Certificate expiry and renewal failures must generate alerts. | P0 |
| NET-012 | HTTP-to-HTTPS redirect must be configurable per domain. | P0 |
| NET-013 | WebSocket and long-lived HTTP connection support must be part of routing tests. | P0 |
| NET-014 | HTTP/2 support is required; HTTP/3 and edge CDN are Cloud beta features unless independently verified for self-host. | P1 |
| NET-015 | Tunnels must be provider adapters and must not be required for ordinary owned-host deployments. | P1 |

### 10.9 Logs, metrics, analytics, and health

| ID | Requirement | Priority |
|---|---|---|
| OBS-001 | Build, deploy, runtime, router, backup, and system logs must use a shared event envelope. | P0 |
| OBS-002 | Logs must carry workspace, project, environment, deployment, service, host, job, severity, timestamp, and source where applicable. | P0 |
| OBS-003 | Secret redaction must occur before persistence and streaming. | P0 |
| OBS-004 | Log streaming must resume from a cursor after reconnect. | P0 |
| OBS-005 | Operators must be able to download a bounded log bundle. | P0 |
| OBS-006 | Default retention must be documented and configurable. | P0 |
| OBS-007 | Container CPU, memory, restart count, and basic disk/network metrics must be available for stable container runtimes. | P0 |
| OBS-008 | Health checks must support HTTP, TCP, and command checks with timeout, interval, retries, and initial delay. | P0 |
| OBS-009 | Health state must distinguish platform health, release health, and application health. | P0 |
| OBS-010 | Analytics must not block request routing or deployments if unavailable. | P0 |
| OBS-011 | Traffic analytics must disclose sampling, retention, and privacy behavior. | P1 |
| OBS-012 | OpenTelemetry export should be offered as an integration rather than replacing internal operational events. | P1 |
| OBS-013 | Alerting destinations must support email and webhook in stable scope; Slack and other channels may be adapters. | P0/P1 |
| OBS-014 | Alert deduplication, retry, and delivery status must be visible. | P0 |

### 10.10 Backups and recovery

| ID | Requirement | Priority |
|---|---|---|
| BAK-001 | Stable destinations: S3-compatible, SFTP, existing managed host, and local disk on self-host. | P0 |
| BAK-002 | Every destination must have a connection-verification operation. | P0 |
| BAK-003 | Credentials must be encrypted and omitted from ordinary reads. | P0 |
| BAK-004 | Policies must support schedule, manual-only, retain count, retain days, and pre-deploy trigger. | P0 |
| BAK-005 | Policies may support pre- and post-hooks, with explicit execution context and timeouts. | P0 |
| BAK-006 | Backup jobs must be durable, resumable where feasible, and safe to retry. | P0 |
| BAK-007 | Every successful backup must record checksum, size, destination object, tool/method, source service, and time. | P0 |
| BAK-008 | Retention must never prune protected backups. | P0 |
| BAK-009 | Restore must have prepare and apply phases. | P0 |
| BAK-010 | Prepare must download or access the backup, verify integrity, and identify required downtime without changing live data. | P0 |
| BAK-011 | Apply must require a confirmation token or exact-name confirmation. | P0 |
| BAK-012 | Restore must emit audit, status, and notification events. | P0 |
| BAK-013 | The dashboard must show last successful backup and last successful restore test separately. | P0 |
| BAK-014 | Instance export/import must be versioned and support encrypted secret bundles. | P0 |
| BAK-015 | Import must support replace and merge with deterministic conflict behavior. | P0 |
| BAK-016 | Dockplane must accept valid legacy OpenShip exports during the compatibility window. | P0 |

### 10.11 Audit and notifications

| ID | Requirement | Priority |
|---|---|---|
| AUD-001 | Every meaningful state-changing action must produce an immutable audit event. | P0 |
| AUD-002 | Audit events must identify human or agent actor, credential/client, workspace, action, target, result, IP where appropriate, and timestamp. | P0 |
| AUD-003 | Secret values and raw credentials must never enter audit payloads. | P0 |
| AUD-004 | Audit reads must be permission-protected and filterable. | P0 |
| AUD-005 | Stable retention behavior must be documented. | P0 |
| NTF-001 | Notification subscriptions must be per workspace and event category. | P0 |
| NTF-002 | Delivery channels must be testable. | P0 |
| NTF-003 | Failed deliveries must retry with bounded exponential backoff. | P0 |
| NTF-004 | Notification failure must not roll back the operation that generated it. | P0 |
| NTF-005 | Repeated identical incidents must be grouped to prevent alert floods. | P1 |

### 10.12 CLI

| ID | Requirement | Priority |
|---|---|---|
| CLI-001 | The canonical binary is `dockplane`. | P0 |
| CLI-002 | Stable commands must include install/up, open, stop, login, init/link, deploy, projects, deployments, domains, hosts, backups, tokens, data transfer, and diagnostics. | P0 |
| CLI-003 | Every command must support non-interactive output appropriate to CI where meaningful. | P0 |
| CLI-004 | Machine-readable output must be available as JSON and use stable field names. | P0 |
| CLI-005 | Exit codes must distinguish validation, authentication, authorization, conflict, remote failure, timeout, and canceled operation. | P0 |
| CLI-006 | `--follow` streams logs and resumes safely after transient disconnects. | P0 |
| CLI-007 | Destructive commands require confirmation unless an explicit non-interactive confirmation flag/token is supplied. | P0 |
| CLI-008 | The CLI must never store a full-access token in a repository directory. | P0 |
| CLI-009 | Credentials must use OS keychain where available, with a permission-restricted file fallback. | P1 |
| CLI-010 | The legacy `openship` binary must remain as a compatibility shim for the announced window. | P0 during migration |
| CLI-011 | CLI and dashboard must use the same API operations. | P0 |

### 10.13 REST API

| ID | Requirement | Priority |
|---|---|---|
| API-001 | All product routes remain under `/api` for compatibility in 1.x. | P0 |
| API-002 | API requests and responses use JSON except streams, files, and WebSocket paths. | P0 |
| API-003 | Validation errors use a stable machine-readable shape with field details. | P0 |
| API-004 | Typed errors include a stable code; unhandled errors do not leak internals. | P0 |
| API-005 | Every collection endpoint supports documented pagination. | P0 |
| API-006 | Mutating endpoints that can be retried must accept idempotency keys. | P0 |
| API-007 | Long-running operations return a job or operation resource rather than hold the request open. | P0 |
| API-008 | Every response includes a request ID. | P0 |
| API-009 | Rate-limit headers and retry guidance must be consistent. | P0 |
| API-010 | Health and readiness are separate: liveness indicates process operation; readiness indicates dependency readiness. | P0 |
| API-011 | API schema must be published from source and used to validate first-party clients where practical. | P1 |
| API-012 | Breaking changes require a versioned migration plan and deprecation period. | P0 |
| API-013 | Cloud-only and self-host-only routes must return intentional availability behavior and may not crash due to absent configuration. | P0 |

### 10.14 MCP and agent access

| ID | Requirement | Priority |
|---|---|---|
| MCP-001 | MCP remains a stateless Streamable HTTP JSON-RPC endpoint at `POST /api/mcp` unless a standards change requires a documented migration. | P0 |
| MCP-002 | OAuth 2.1 with PKCE is the preferred authentication mode. | P0 |
| MCP-003 | Static PAT authentication remains available for clients without OAuth. | P0 |
| MCP-004 | `tools/list` must be filtered by credential capability. | P0 |
| MCP-005 | `tools/call` must re-enter ordinary API validation, authentication, and authorization. | P0 |
| MCP-006 | Tool implementations map to API operations and may not bypass services. | P0 |
| MCP-007 | Auth, token, invite, billing-payment, and MCP-client administration routes are never exposed as tools. | P0 |
| MCP-008 | Each tool declares read-only and destructive hints. | P0 |
| MCP-009 | High-risk destructive tools must support a policy requiring human approval even when the token has permission. | P1 |
| MCP-010 | Agent audit events must distinguish client, token, and initiating user. | P0 |
| MCP-011 | Agent-visible errors must not reveal inaccessible resources. | P0 |
| MCP-012 | Tool schemas must be stable enough for clients to cache within a release line. | P1 |

### 10.15 Desktop

| ID | Requirement | Priority |
|---|---|---|
| DSK-001 | Desktop is a beta distribution of the same API and dashboard, not a separate product backend. | P0 |
| DSK-002 | Local API and dashboard must bind to loopback by default on dynamically selected ports. | P0 |
| DSK-003 | A single-instance lock must protect the embedded database directory. | P0 |
| DSK-004 | The app must recover stale locks after verified process death and reject a lock owned by another active machine/process. | P0 |
| DSK-005 | Desktop login and redirect origins must be derived from the active local origin rather than hardcoded. | P0 |
| DSK-006 | Desktop updates must be signed and support rollback to the prior version. | P1 |
| DSK-007 | Desktop data export must use the same format as self-hosted export. | P0 |
| DSK-008 | The desktop app must clearly distinguish local projects from cloud-owned projects. | P0 |
| DSK-009 | Desktop must not be required to deploy to an owned host. | P0 |

### 10.16 Managed cloud and billing

| ID | Requirement | Priority |
|---|---|---|
| CLD-001 | Dockplane Cloud is a destination and a hosted control-plane mode built from the same core source. | P1 |
| CLD-002 | Cloud-owned projects are canonical in the cloud; a self-hosted instance acts as a gateway and must not maintain a divergent shadow copy. | P0 for Cloud beta |
| CLD-003 | Cloud operations must use explicit workspace identity and scoped server-side sessions. | P0 |
| CLD-004 | Managed compute must expose concrete CPU, memory, disk, region, sleep, and cost behavior. | P1 |
| CLD-005 | Usage metering must be idempotent, auditable, and reconcile to provider records. | P1 |
| CLD-006 | Billing outage must not corrupt project state. | P0 |
| CLD-007 | Plan limits must be enforced in the API, not only in UI. | P0 |
| CLD-008 | A customer must be able to bring a cloud project home through a documented transfer operation where the runtime permits it. | P1 |
| CLD-009 | Autoscaling, multi-region, and CDN claims remain beta until service-level evidence exists. | P1/P2 |
| CLD-010 | Self-hosted core functionality must not require a paid cloud account. | P0 |

### 10.17 Email subsystem

| ID | Requirement | Priority |
|---|---|---|
| MAIL-001 | Email hosting is a separately labeled beta module, not part of Dockplane Core 1.0. | P0 |
| MAIL-002 | The product must state that it provisions and operates a complex mail stack with independent security and deliverability obligations. | P0 |
| MAIL-003 | Administrative identity, mailbox identity, and webmail state must remain separate. | P1 |
| MAIL-004 | Upstream mail daemons retain ownership of their own schemas and configuration where the architecture specifies it. | P1 |
| MAIL-005 | Public mail administration endpoints must not be introduced solely for convenience. | P1 |
| MAIL-006 | DKIM, SPF, DMARC, reverse DNS, blocklist health, queue health, spam/virus scanning, backups, and update behavior require end-to-end tests before stable labeling. | P1 |
| MAIL-007 | DMARC aggregate report ingestion and surfacing is a future operational feature. | P2 |
| MAIL-008 | Email must be removable or disableable without affecting core deployment operation. | P0 |

---

## 11. Data model

### 11.1 Core entities

| Entity | Purpose | Key relationships |
|---|---|---|
| User | Human identity | Memberships, sessions, tokens, audit events |
| Workspace | Ownership and authorization boundary | Projects, hosts, domains, backups, settings, billing |
| Membership | User role within a workspace | User + workspace + role |
| Grant | Resource-scoped permission | Principal + resource type/id + access levels |
| Token | Hashed PAT metadata | User, workspace, grants, read-only, expiry |
| Agent client | MCP OAuth client and consent | User, workspace, grants, issued credentials |
| Project | Deployable product | Workspace, source, environments, services |
| Environment | Isolated release lane | Project, variables, domains, deployments |
| Source connection | Repository or folder metadata | Project, provider, credentials reference |
| Build plan | Versioned source-to-artifact instructions | Project/environment, detector evidence |
| Service | Runtime component | Project, routes, volumes, resources, health |
| Host | Owned execution machine | Workspace, credentials, scans, workloads |
| Destination | This machine, host, or cloud target | Deployment snapshot |
| Deployment | Immutable release attempt | Project, environment, source revision, build/runtime snapshot |
| Artifact | Built image or package | Deployment/build, digest, provenance |
| Route/domain | Public hostname mapping | Environment/service, certificate |
| Certificate | TLS lifecycle record | Domains, issuer, expiry, status |
| Secret | Encrypted value reference | Workspace/project/environment/service |
| Job | Durable asynchronous work | Operation, status, attempts, lease |
| Log event | Structured operational record | Job/deployment/service/host |
| Metric sample | Operational measurement | Service/host/deployment |
| Backup destination | Storage location and credentials | Workspace |
| Backup policy | Schedule and retention | Project/service + destination |
| Backup run | Immutable backup attempt | Policy, source, checksum, object |
| Restore operation | Prepared/apply state | Backup run, target service |
| Notification channel | Delivery configuration | Workspace |
| Notification subscription | Event-to-channel mapping | Workspace |
| Audit event | Immutable accountability record | Actor, action, resource, result |
| Usage record | Cloud metering unit | Workspace/project/resource |
| Subscription | Commercial plan state | Workspace |

### 11.2 Data ownership rules

1. Every workspace-owned row includes `workspace_id` or is reachable through a parent that does.
2. Repository methods must enforce workspace scope; controller-supplied IDs are not trusted alone.
3. Self-hosted local and owned-host project state is canonical in the self-hosted database.
4. Cloud-project state is canonical in Dockplane Cloud.
5. The gateway must not pretend to provide offline writes for cloud-owned objects.
6. Secrets are encrypted with a per-installation or managed key strategy and are never stored as plaintext.
7. Tokens are hashed rather than encrypted because retrieval is not required.
8. Deployment snapshots retain configuration references or sealed values sufficient to explain what ran without exposing secrets.
9. Audit records are append-only at the application layer.
10. Export format is schema-versioned and includes a manifest.

### 11.3 Identifier rules

- Public identifiers use non-sequential, unguessable IDs.
- Human slugs are not authorization boundaries.
- IDs remain stable through rename.
- Import collision behavior is deterministic.
- Provider IDs and internal IDs remain separate fields.
- Legacy OpenShip identifiers are accepted during import without rewriting historical meaning.

---

## 12. State machines

### 12.1 Deployment state

Recommended top-level states:

```text
draft
  -> queued
  -> preparing
  -> sourcing
  -> installing
  -> building
  -> packaging
  -> artifact_verifying
  -> starting
  -> health_checking
  -> routing
  -> active
```

Terminal and alternate states:

```text
failed
canceled
superseded
rolled_back
cleanup_pending
cleanup_failed
```

Rules:

- State transitions are append-only events with current state materialized for reads.
- `active` means the release is serving the intended route and required health checks passed.
- A deployment can become `superseded` when another release becomes active.
- `rolled_back` describes a release displaced by an explicit rollback operation; the rollback itself has an operation record.
- A failure must record phase, code, safe-to-retry status, and operator remediation.
- `cleanup_pending` is not hidden behind a successful terminal state.

### 12.2 Host state

```text
new
-> probing
-> scanned
-> plan_ready
-> provisioning
-> ready
```

Alternate states:

```text
conflict
degraded
unreachable
credential_error
provision_failed
detached
```

A host can run workloads while `degraded`, but the UI must show which capabilities are unsafe or unavailable.

### 12.3 Domain state

```text
draft
-> dns_pending
-> ownership_verified
-> certificate_pending
-> active
```

Alternate states:

```text
dns_error
certificate_error
renewal_at_risk
detached
```

### 12.4 Backup state

```text
queued
-> preparing
-> copying
-> uploading
-> verifying
-> succeeded
```

Alternate states:

```text
failed
canceled
pruned
```

### 12.5 Restore state

```text
requested
-> preparing
-> prepared
-> applying
-> verifying
-> succeeded
```

Alternate states:

```text
prepare_failed
expired
apply_failed
recovery_required
canceled
```

Prepared restore tokens expire and are one-time use.

---

## 13. Architecture specification

### 13.1 Monorepo layout

The current broad layout should remain recognizable:

```text
apps/
  api/          control plane and API
  cli/          command-line client and self-host launcher
  dashboard/    operator web application
  desktop/      Electron packaging and local service launcher
  web/          marketing and documentation
  email/        beta mail engine/webmail integration

packages/
  adapters/     runtime, infrastructure, and system adapters
  core/         pure shared logic, types, errors, detection
  db/           control-plane schema and repositories
  db-email/     email-owned schema and repositories
  onboarding/   shared setup flows and API client
  ui/           shared visual components
```

A rebrand should not trigger an unnecessary physical restructuring. Rename package metadata and visible brands first; refactor directories only when it reduces long-term ambiguity.

### 13.2 Control plane

The API is responsible for:

- authentication and authorization;
- input validation;
- workspace resolution;
- product state transitions;
- transaction boundaries;
- job submission;
- adapter coordination;
- audit events;
- notifications;
- API and MCP contract;
- mode-based module availability.

Controllers remain transport-oriented. Services own business behavior. Repositories own data access. Adapters own external side effects.

### 13.3 Queue and worker model

Stable production operation requires Redis-backed durable jobs. An in-memory runner is allowed only for development or explicitly documented single-process evaluation.

Job requirements:

- lease/heartbeat;
- attempt count;
- deduplication key;
- idempotency key;
- cancelability;
- progress events;
- structured result/error;
- dead-letter visibility;
- per-host and per-project concurrency keys;
- startup recovery of abandoned leases.

The API must not report that work completed merely because it was queued.

### 13.4 Adapter contracts

Adapter categories:

1. **Runtime adapter**
   - build or receive artifact;
   - start candidate;
   - inspect;
   - health;
   - stop;
   - remove;
   - stream logs;
   - metrics;
   - exec where allowed.

2. **Infrastructure adapter**
   - plan route;
   - apply route;
   - validate configuration;
   - issue/renew certificate;
   - inspect DNS/provider;
   - rollback route.

3. **System adapter**
   - probe host;
   - scan prerequisites/conflicts;
   - produce provisioning plan;
   - apply approved steps;
   - inspect resources;
   - clean owned artifacts.

4. **Source provider**
   - authenticate;
   - list repositories/branches;
   - resolve revision;
   - fetch source;
   - configure webhook.

5. **Backup provider**
   - verify destination;
   - put/get/delete/list object;
   - checksum;
   - report capability.

6. **Notification provider**
   - validate channel;
   - send;
   - report result.

Every adapter method must separate **plan** from **apply** when it can mutate external infrastructure.

### 13.5 Database

- PostgreSQL is required for production multi-process and cloud deployments.
- PGlite is supported for desktop and explicitly bounded single-process installations.
- Migration files are mandatory for production schema changes.
- The API applies or verifies migrations through a single controlled path.
- Destructive migrations require a backup and rollback note.
- Database repositories return domain-safe results rather than raw cross-workspace records.
- Tests cover both relevant database drivers where behavior could diverge.

### 13.6 API-to-dashboard topology

The dashboard should use a same-origin or explicitly trusted proxy pattern. Origin, cookie domain, CORS, CSRF, and redirect behavior must be generated from runtime configuration rather than hardcoded hostnames.

Supported topologies must be documented:

1. dashboard and API behind one public origin;
2. dashboard and API on separate trusted subdomains;
3. local loopback desktop;
4. private management origin with external application ingress.

### 13.7 Release artifacts

Release distribution includes:

- versioned CLI package;
- signed server archives;
- versioned container images;
- desktop installers;
- checksums;
- provenance/signature metadata;
- changelog;
- upgrade notes;
- release advisory metadata.

A Docker Compose example that builds from source may remain, but production documentation should prefer versioned images after they exist.

---

## 14. Security specification

### 14.1 Security objectives

Dockplane is a privileged system. It can read source code, hold deployment secrets, connect to servers, start containers, change routes, issue certificates, restore data, and expose operations to agents. Its security model must assume that compromise can affect both the control plane and every managed application.

Objectives:

1. prevent cross-workspace data and runtime access;
2. prevent unauthenticated or under-authorized mutation;
3. minimize credential scope and plaintext lifetime;
4. prevent host takeover through unsafe automation;
5. preserve an audit trail;
6. make agent authority explicit and revocable;
7. prevent application workloads from silently acquiring control-plane credentials;
8. ensure a dependency failure does not downgrade security.

### 14.2 Threat model

Material threats include:

- IDOR and workspace-scope mistakes;
- stolen session or PAT credentials;
- malicious repository code executed during build;
- secrets printed in build output;
- container escape or dangerous bind mount;
- command injection through project fields;
- SSH man-in-the-middle or host-key change;
- hostile or compromised connected host;
- unsafe modification of a pre-existing proxy;
- webhook replay or forgery;
- cross-project volume/network collision;
- SSRF through health checks, webhooks, providers, or source URLs;
- archive path traversal;
- untrusted Compose capabilities;
- agent prompt injection leading to destructive tool calls;
- billing or cloud-session confusion;
- vulnerable desktop update;
- backup exfiltration or destructive restore;
- malicious import file;
- dependency and release supply-chain compromise.

### 14.3 Mandatory controls

#### Authorization

- Workspace scope is derived and checked server-side.
- All mounted API routes carry permission tags.
- Resource loaders combine ID and workspace.
- Restricted grants inherit only through documented resource trees.
- Denied resource access returns not found where existence is sensitive.
- Internal endpoints require an independent internal token and network/topology controls.
- Cloud-to-self-host and self-host-to-cloud requests use distinct trust boundaries.

#### Secrets

- Secrets are encrypted with authenticated encryption.
- Keys are installation-specific or managed through a dedicated key service in cloud.
- PATs are hashed.
- Secret values are redacted before log persistence.
- Build secrets use ephemeral mounts or environment injection and are not baked into artifacts.
- Diagnostic export defaults to no secrets.
- Data export includes secrets only in a separately passphrase-sealed bundle.
- Secret rotation and key-loss behavior are documented.

#### Builds

- Build execution is untrusted code execution.
- Cloud builds run in isolated ephemeral workers.
- Self-hosted builds warn that repository code can access the selected build machine within runtime boundaries.
- Privileged containers are blocked in stable mode.
- Host Docker socket mounts into application containers are blocked unless an operator enables an explicit dangerous override.
- Compose fields such as `privileged`, host PID/network, devices, capabilities, and arbitrary bind mounts require policy review and prominent warnings.
- Archive extraction rejects absolute paths, traversal, device files, and unsafe links.

#### Hosts and SSH

- Host keys are pinned.
- Credentials are workspace-scoped and encrypted.
- Commands use structured argument handling where possible.
- Shell interpolation is reviewed and tested with hostile input.
- Provisioning runs through an explicit plan.
- Existing system configuration is backed up before an approved edit.
- Ownership markers prevent cleanup of unrelated resources.
- Channel and connection limits are enforced.

#### Network

- Management endpoints require authentication and HTTPS when not loopback.
- Public application ingress is separated from control-plane ingress.
- Internal PostgreSQL and Redis are not publicly exposed by default.
- Webhook signatures and replay windows are enforced.
- Outbound fetches apply SSRF protections and allowed protocols.
- CORS uses explicit trusted origins.
- CSRF protections cover cookie-authenticated mutations.
- Proxy headers are trusted only from configured proxies.

#### Agents

- Agent tools are a curated subset.
- Agent credentials are read-only or scoped by default.
- Tool calls use the same API authorization.
- Destructive operations can require human approval.
- Credentials, auth administration, and consent administration are excluded.
- Tool output is treated as potentially sensitive.
- Audit identifies agent client and initiating grant.

### 14.4 Security release gates

Before stable 1.0:

- independent review of authentication and workspace authorization;
- tests proving every route has a permission tag;
- cross-workspace API and MCP test suite;
- command-injection review of host and deployment adapters;
- archive-extraction tests;
- secret-redaction tests;
- signed releases and update verification;
- documented vulnerability-reporting process;
- dependency scanning and patch policy;
- backup/import parser limits;
- threat-model review for desktop zero-auth;
- host-adoption safety tests;
- no unresolved known critical or high-severity security issue.

### 14.5 Security documentation

The product must publish:

- authentication methods;
- permission model;
- runtime isolation differences;
- local/cloud data boundary;
- secret custody;
- host ownership and mutation behavior;
- supported deployment topologies;
- update and vulnerability policy;
- MCP authority model;
- backup encryption and restore risks;
- hardening guide for internet-facing self-hosted instances.

---

## 15. Reliability and non-functional requirements

### 15.1 Service-level objectives

For stable self-hosted core under supported configuration:

| Area | Objective |
|---|---|
| API availability | 99.9% monthly, excluding operator host failure and scheduled maintenance |
| Successful redeploy after artifact exists | 99.5% |
| Successful traffic switch when candidate health passes | 99.9% |
| Rollback operation success with retained compatible artifact | 99.9% |
| Durable job loss | 0 acknowledged jobs |
| Audit-event loss for successful mutations | 0 |
| Certificate renewal before expiry | 99.9% of eligible managed certificates |
| Backup schedule execution | 99% within the defined scheduling window |
| Cross-workspace authorization bypass | 0 |
| Fresh supported-host installation success | at least 95% in automated clean-host matrix before 1.0; target 99% after 1.0 |

Cloud SLOs require a separate public service policy.

### 15.2 Performance targets

- Dashboard primary pages reach usable state within 2.5 seconds at p75 on a normal broadband connection when the API is healthy.
- API list/read endpoints complete within 300 ms p95 excluding external-provider calls and large log queries.
- Mutations that enqueue work acknowledge within 500 ms p95.
- Live log propagation is under 2 seconds p95.
- Host preflight begins within 2 seconds and streams progress.
- Traffic switch after health success occurs within 5 seconds p95 on managed ingress.
- CLI startup for local help/version is under 300 ms on supported machines.
- The API supports at least 100 concurrent log streams on the documented single-node reference configuration.
- Large lists use pagination and bounded queries.
- Export/import and logs enforce size limits and streaming to avoid unbounded memory.

### 15.3 Resilience

- PostgreSQL and Redis dependency loss results in explicit degraded/readiness state.
- Authentication dependency failure never becomes anonymous access.
- Worker restarts recover leased jobs.
- Duplicate webhooks and client retries are idempotent.
- Router configuration uses validate-then-swap.
- Certificate issuance failure retains current certificates.
- Cloud provider or billing failure does not delete running workloads.
- Notification failure is isolated.
- Analytics failure is isolated.
- Cleanup work is durable and visible.
- Every destructive multi-step operation has a recovery state.

### 15.4 Compatibility

Stable 1.x promises:

- documented REST fields are not removed without deprecation;
- CLI JSON output remains compatible within 1.x;
- export format is backward readable within 1.x;
- legacy OpenShip exports remain importable for the migration period;
- `openship` CLI aliases and selected environment variables remain supported for the announced compatibility window;
- existing databases upgrade through migrations;
- existing containers and routes continue running during control-plane upgrade where architecture permits;
- feature maturity labels may improve without breaking stable behavior.

### 15.5 Supported-host matrix

The stable matrix must be explicit rather than “any Linux.” Initial recommendation:

- Ubuntu LTS: primary;
- Debian stable: primary;
- x86_64: primary;
- arm64: supported after automated release validation;
- Docker Engine versions: documented minimum and tested current range;
- SSH server: OpenSSH supported range;
- process mode: beta;
- SELinux-heavy distributions and immutable OS variants: experimental until tested.

The exact versions must be generated from CI and release metadata, not hardcoded indefinitely in this document.

### 15.6 Capacity and limits

Every installation must expose configured limits:

- projects per workspace;
- concurrent builds;
- concurrent deployments per host;
- log retention and maximum event size;
- upload and import size;
- artifact retention;
- backup concurrency;
- API rate limits;
- WebSocket/log stream count;
- host connection pool size;
- environment-variable count and size;
- domain count;
- agent tool-call rate.

Cloud plans may vary these limits; self-hosted defaults must be editable with safe bounds.

---

## 16. User experience requirements

### 16.1 First-run experience

The first-run flow must answer:

1. Where is this control plane running?
2. Is it private, local-only, or internet-facing?
3. Which database and queue mode are active?
4. Who is the initial owner?
5. Will Dockplane manage ingress?
6. Is the instance linked to Dockplane Cloud?
7. What is the first supported path to deploy?

The setup summary remains accessible later.

### 16.2 Progressive disclosure

Simple projects should not expose every infrastructure field immediately. The default path is:

- source;
- detected plan;
- destination;
- environment;
- deploy.

Advanced controls expand in place and remain visible in a final review.

### 16.3 Plan and diff UI

Before host provisioning, domain changes, restore, project deletion, or major migration, show:

- resources affected;
- exact creates/updates/deletes;
- downtime expectation;
- rollback behavior;
- credentials used;
- unsupported or risky fields;
- confirmation requirement.

### 16.4 Error design

Every operational error has:

- human summary;
- stable machine code;
- stage;
- resource;
- safe-to-retry indicator;
- likely cause;
- recommended next action;
- request/job ID;
- a path to sanitized diagnostics.

Do not collapse SSH exhaustion, image verification, DNS failure, and application build failure into the same generic message.

### 16.5 Destructive-action design

High-risk actions use escalating protection:

- ordinary delete: confirm;
- production delete: type resource name;
- restore apply: prepared token plus confirmation;
- host cleanup: itemized selection;
- workspace deletion: recent authentication plus delayed or recoverable window;
- agent destructive call: configurable human approval.

### 16.6 Status design

Avoid ambiguous green states. Distinguish:

- configured;
- verified;
- active;
- healthy;
- backed up;
- restore-tested;
- reachable;
- managed;
- degraded.

### 16.7 Accessibility

Stable dashboard target:

- WCAG 2.2 AA;
- full keyboard operation;
- visible focus;
- semantic status and error announcements;
- non-color-only state;
- reduced-motion support;
- chart data available as table/text;
- terminal accessibility limitations documented with alternatives;
- contrast tested in light and dark themes.

### 16.8 Localization

The current project already contains multiple localized README and UI resources. Dockplane should:

- keep English as source language;
- use stable message keys;
- avoid concatenated grammar;
- localize status, errors, and critical warnings before marketing copy;
- track translation coverage per release;
- fall back safely to English;
- avoid shipping stale translated instructions for destructive operations.

---

## 17. Privacy and telemetry

### 17.1 Self-hosted default

A self-hosted instance sends no product telemetry to Dockplane Cloud unless the operator opts in or uses a cloud-linked feature that inherently requires communication.

### 17.2 Required external communication

The product must document communication used for:

- version/update checks;
- GitHub or other source providers;
- certificate authorities;
- configured DNS providers;
- configured backup destinations;
- cloud linking and cloud projects;
- billing;
- crash reporting, if enabled;
- notification channels.

### 17.3 Telemetry categories

Opt-in telemetry may include:

- installation mode and version;
- anonymized feature usage;
- deployment success/failure code;
- performance timing;
- update success;
- crash signature.

It must not include:

- source code;
- repository private names without explicit consent;
- environment variable values;
- credentials;
- raw logs;
- domain names by default;
- file paths that reveal usernames;
- email content.

### 17.4 Controls

- Telemetry state is visible in settings.
- Operators can disable it.
- Diagnostic bundles are previewable before upload.
- Cloud service telemetry follows a published privacy policy and retention policy.
- Audit logs are customer data, not product analytics.

---

## 18. Packaging, installation, and upgrades

### 18.1 Distribution channels

Stable release should provide:

- npm-distributed CLI;
- shell installer that verifies checksums/signatures;
- versioned OCI images;
- Docker Compose example using released images;
- server archive for CLI-managed local service;
- desktop installers for supported platforms;
- source-build documentation for contributors.

### 18.2 Installation modes

1. **CLI-managed service**
   - installs API/dashboard assets;
   - runs as OS service;
   - appropriate for one-box self-hosting.

2. **Docker Compose**
   - API, dashboard, PostgreSQL, Redis;
   - production-friendly reference topology;
   - external proxy optional.

3. **Desktop**
   - embedded local service and PGlite;
   - beta.

4. **Source development**
   - Bun workspace setup;
   - not production distribution.

### 18.3 Upgrade behavior

Before upgrade:

- verify disk space;
- verify database backup or offer export;
- fetch release advisory;
- show migration and downtime notes;
- verify artifact signature.

During upgrade:

- stop only required components;
- apply migration once;
- preserve current application workloads where possible;
- retain previous binary/image;
- run readiness check.

After upgrade:

- run health and schema checks;
- surface changed feature flags;
- offer rollback when schema compatibility permits;
- record audit/system event.

### 18.4 Release channels

- Stable
- Beta
- Nightly/development

Self-hosted production defaults to Stable. Channel changes require acknowledgment.

### 18.5 Release criteria

A stable release cannot be cut unless:

- build and test matrix passes;
- supported clean-host install matrix passes;
- upgrade from previous stable passes;
- rollback test passes where supported;
- database migration test passes;
- dashboard/API/CLI smoke tests pass;
- security dependency threshold passes;
- documentation version is published;
- checksums and signatures are generated;
- release advisories are complete.

---

## 19. Commercial model

### 19.1 Editions

**Dockplane Community**

- Apache-2.0 core;
- self-hosted control plane;
- owned-host deployments;
- dashboard, CLI, API, scoped MCP;
- core backups, domains, permissions, and audit;
- community support.

**Dockplane Cloud**

- hosted control plane and managed compute destination;
- managed edge, certificate operations, metering, and billing;
- convenience integrations;
- commercial support according to plan.

**Dockplane Enterprise — later**

Potential additions:

- SSO/SCIM;
- policy-as-code;
- long-term audit retention;
- compliance exports;
- premium support;
- private networking and dedicated workers;
- advanced approval workflows.

The open core must remain useful without the cloud product. Artificially disabling basic self-hosted deployment, export, backups, or access control would contradict the product promise.

### 19.2 Pricing principles

- Charge for managed infrastructure, convenience, support, and enterprise governance.
- Do not charge users to retrieve or export their data.
- Make resource units understandable.
- Separate compute cost from control-plane subscription when practical.
- Provide budget and usage alerts.
- Avoid pricing that makes bring-your-own-host intentionally painful.

---

## 20. Rebrand and migration plan

### 20.1 Rebrand strategy

The rebrand is a compatibility migration, not a global search-and-replace. Renaming every database, path, environment variable, and API object in one release would create avoidable failure risk.

### 20.2 Phases

#### Phase A — internal readiness

- complete brand clearance;
- reserve domains, package names, container names, handles, and app signing identities;
- add centralized brand constants;
- inventory all visible and internal OpenShip strings;
- classify each as safe rename, compatibility alias, or deferred internal name;
- freeze new `openship`-prefixed public surface except migration code.

#### Phase B — dual-brand technical release

- display Dockplane as product;
- publish `dockplane` CLI;
- keep `openship` CLI shim;
- accept both new and legacy environment variables;
- read legacy data directories and migrate with backup;
- accept old PAT prefix while issuing new prefix;
- import old exports;
- preserve `/api`;
- preserve database table names unless a migration has real value;
- publish explicit compatibility table.

#### Phase C — default Dockplane

- documentation and installers use only Dockplane commands;
- legacy names produce deprecation warnings;
- package and image aliases remain available;
- telemetry measures remaining legacy use without collecting sensitive data.

#### Phase D — legacy removal

- remove only after a major version;
- announce at least two stable minor releases in advance;
- provide a standalone migration checker;
- never strand an existing data directory or export without a supported path.

### 20.3 Compatibility window

Recommended minimum:

- legacy CLI and environment aliases: through all of Dockplane 1.x;
- legacy export import: at least through Dockplane 2.x;
- legacy PAT validation: through 1.x, with rotation prompts;
- old Docker labels: recognized indefinitely for ownership and cleanup;
- old database names: no forced rename in 1.x;
- old API paths: unchanged in 1.x.

### 20.4 Product migration UX

On first Dockplane start against OpenShip data:

1. detect legacy installation;
2. stop before mutation;
3. show discovered paths, version, and planned changes;
4. create backup/export;
5. migrate config and copy/rename data only when safe;
6. retain rollback marker;
7. start Dockplane;
8. verify projects, hosts, domains, and secrets;
9. show a migration report.

---

## 21. Roadmap

### Phase 0 — truth and hardening

**Goal:** Establish a reliable baseline before public rebrand.

Deliver:

- automated supported-host installation matrix;
- prebuilt images and signed artifacts;
- SSH/SFTP channel lifecycle fixes and tests;
- remote Docker verification tests;
- desktop origin/cookie fixes;
- secure-context handling;
- safe host adoption scan and provisioning plan;
- external-ingress mode;
- documentation inventory and maturity labels;
- stable error taxonomy;
- restore test coverage;
- current feature flags and module availability map.

Exit gate: a fresh host can install, deploy a reference app, attach HTTPS, redeploy, roll back, back up, restore, update Dockplane, and export data in CI.

### Phase 1 — Dockplane rebrand beta

**Goal:** Introduce brand without breaking installations.

Deliver:

- product visual identity and centralized naming;
- `dockplane` CLI with `openship` shim;
- data-directory migration;
- environment alias layer;
- PAT prefix migration;
- export compatibility;
- renamed desktop assets and installers;
- documentation under Dockplane;
- migration checker and report.

Exit gate: an OpenShip 0.2.x test installation upgrades with no lost projects, secrets, hosts, domains, backups, or access records.

### Phase 2 — Dockplane 1.0 core

**Goal:** Stable self-hosted deployment platform.

Deliver:

- stable single-node Compose and CLI-managed install;
- container deployments to local and owned host;
- GitHub/local/Compose sources;
- plan-before-mutation host flow;
- managed or external ingress;
- non-wildcard HTTPS;
- logs, health, rollback;
- backup/restore;
- roles, grants, tokens, audit;
- CLI/API/dashboard parity;
- read-only/scoped MCP;
- support and compatibility policy.

Exit gate: all P0 requirements and acceptance criteria pass.

### Phase 3 — cloud and automation

Deliver:

- Dockplane Cloud public beta/GA;
- cloud project transfer;
- pull-request previews;
- DNS providers and wildcard certificates;
- agent approval policies;
- richer metrics and OpenTelemetry;
- autosleep and clear metering.

### Phase 4 — fleet platform

Deliver after evidence:

- outbound host agents;
- multi-node placement;
- high availability;
- private networking;
- canary traffic;
- policy-as-code;
- enterprise identity;
- multi-region cloud.

Mail hosting should follow its own readiness roadmap and should not block the core platform.

---

## 22. Success metrics

### 22.1 Activation

- percentage of new installations reaching healthy control plane;
- median time from first dashboard load to first successful deployment;
- first-deployment success rate by source/runtime/OS;
- percentage of detector plans accepted without edit;
- percentage of connected hosts completing safe preflight.

### 22.2 Reliability

- deployment success by phase and adapter;
- rollback success;
- rate of cleanup-pending resources;
- SSH reconnect/channel exhaustion rate;
- certificate issuance and renewal success;
- backup success and restore-test success;
- upgrade success and rollback rate;
- number of support incidents caused by documentation mismatch.

### 22.3 Retention and value

- active workspaces deploying weekly;
- projects with repeat successful deployments;
- projects with a domain, health check, and backup policy;
- API/CLI/MCP adoption;
- self-host to cloud and cloud to self-host transfer completion;
- number of active owned hosts.

### 22.4 Trust

- percentage of host changes preceded by a visible plan;
- unresolved high-severity security findings;
- cross-workspace authorization test failures;
- destructive operations without audit events;
- backup destinations verified;
- users who successfully export their instance;
- legacy migration success.

### 22.5 North-star metric

**Healthy recoverable projects:** production projects that, in the last 30 days, have:

- a successful deployment;
- a passing health signal;
- an active route or explicitly private service;
- a retained rollback artifact;
- and a successful backup or documented stateless classification.

This metric rewards actual operability rather than raw deploy counts.

---

## 23. Risk register

| Risk | Impact | Likelihood | Response |
|---|---|---:|---|
| Scope remains too broad | Product appears unreliable despite substantial features | High | Freeze stable 1.0 scope; label beta aggressively |
| Rebrand breaks installations | Data loss and loss of trust | Medium | Dual-name compatibility, migration backups, major-version removal only |
| Host provisioning overwrites existing infrastructure | Production outage | High | Read-only scan, explicit diff, external ingress, ownership markers |
| SSH connection leaks | Failed remote deploys | Medium/High | deterministic channel closure, pool limits, stress tests |
| Runtime cleanup deletes unrelated resources | Severe data loss | Medium | labels + internal ownership record + deny ambiguous cleanup |
| “Zero downtime” claim is inaccurate | Misleading product behavior | Medium | runtime-specific language and tests |
| Wildcard/SSL claims exceed implementation | Failed domains | High | non-wildcard stable; DNS-01 beta only |
| Email expands security burden | Abuse, deliverability, compromise | High | independent beta module and launch gates |
| Cloud dependency creeps into self-host | Violates core promise | Medium | CI self-host without cloud credentials; architectural review |
| MCP grants too much authority | Destructive agent action | Medium | scoped default, curated tools, approval policies, audit |
| PGlite used beyond safe topology | corruption or availability issues | Medium | explicit single-process limit and startup lock |
| Docs drift from code | failed installs and support burden | High | docs-as-release artifact and source-generated references |
| Container builds execute malicious code | control-plane compromise | High | isolated workers, warnings, limits, no privileged defaults |
| Update/migration failure | platform outage | Medium | preflight, backup, one-time migration, prior version retention |
| Brand conflict | forced second rename | Unknown | professional legal and domain clearance before public use |

---

## 24. Definition of done for Dockplane 1.0

Dockplane 1.0 is done only when all of the following are true:

### Installation

- Supported clean-host matrix passes.
- Released images/binaries are signed and versioned.
- Installation is idempotent.
- Public deployment requires secure authentication and trusted-origin configuration.
- Uninstall/detach behavior is documented.

### Deployment

- Reference apps for Node, Python, Go, static output, Dockerfile, and Compose deploy successfully.
- Local and remote container targets pass.
- Build and deployment cancellation pass.
- Health-based switch and failed-candidate behavior pass.
- Rollback passes.
- Resource cleanup is verified not to touch unrelated resources.

### Host safety

- Scan is read-only.
- Existing proxy/container conflicts are detected.
- External-ingress mode works.
- Host-key pinning works.
- SSH/SFTP stress test does not leak sessions.
- Management and public addresses can differ.

### Domains

- Manual DNS instructions and verification work.
- Non-wildcard certificate issue and renewal pass.
- Existing route survives certificate failure.
- WebSocket routing passes.
- Wildcards are not labeled stable without DNS-01 automation.

### Data and recovery

- Backup destination verification works for stable providers.
- Scheduled and pre-deploy backups pass.
- Prepare/apply restore passes.
- Instance export/import round trip passes with and without secret bundle.
- Legacy OpenShip export import passes.
- Upgrade and rollback test passes.

### Access and security

- Every route carries a permission tag.
- Cross-workspace API and MCP suites pass.
- PAT hashing, expiry, revocation, read-only, and scope pass.
- Secret redaction tests pass.
- Destructive actions are audited.
- No unresolved critical/high security finding.
- Signed update verification passes.

### Clients

- Dashboard, CLI, API, and MCP use shared operations.
- CLI JSON contracts are documented.
- Dashboard critical workflows meet accessibility target.
- Desktop is labeled beta unless its separate gates pass.
- Legacy `openship` shim works and warns.

### Documentation and support

- Installation, topology, host adoption, domains, backups, restore, update, security, MCP, and migration guides are complete.
- Feature maturity labels match runtime availability.
- Troubleshooting maps common failures to stable error codes.
- Support matrix is published.
- Known limitations are public.

---

## 25. Open product decisions

These decisions require owner approval before implementation freezes:

1. Is Dockplane Cloud part of the company launch or a later destination?
2. Will the canonical public product domain use `.com`, `.dev`, or another cleared domain?
3. Does Community include multi-user restricted grants indefinitely?
4. What is the minimum legacy OpenShip compatibility period?
5. Is `deployment` renamed to `release` only in UI, or also in API v2 later?
6. Is process mode supported on macOS outside desktop?
7. Which Linux distributions are stable at 1.0?
8. Does Docker Compose stable scope permit bind mounts outside managed paths?
9. Which DNS provider is first?
10. Does an owned host require root/sudo, or can a rootless constrained mode be stable?
11. What is the default log retention on self-hosted installations?
12. What is the control-plane update policy for unattended security releases?
13. Which MCP mutations require human approval by default?
14. Does the cloud product build customer code in dedicated or pooled workers at each plan?
15. Is mail maintained as part of Dockplane, moved to a separate repository/product, or removed from 1.0 distributions?

---

## 26. Source-grounding notes

This specification is derived from the repository's documented and coded product shape, including:

- root `README.md` and `package.json`;
- `CONTRIBUTING.md`;
- architecture documents under `apps/web/content/docs/architecture/`;
- security documents under `apps/web/content/docs/security/`;
- API, dashboard, CLI, MCP, guide, and backup documentation;
- package manifests for API, dashboard, CLI, and desktop;
- root Docker Compose and environment reference;
- the email target-architecture document;
- open GitHub issue reports available during review.

Observed repository state should be revalidated before implementation because the source is actively developed.

### Interpretation policy

- A feature appearing in documentation or code means it is part of the product surface, not automatically that it is stable.
- An open issue report is evidence of a reported risk, not proof that every current installation still has the defect.
- The email architecture explicitly calls itself target state and is therefore treated as beta/incubating.
- Claims such as wildcard certificates, CDN, autoscaling, multi-node operation, and production readiness require end-to-end verification before they are retained in Dockplane marketing.
- Internal names may remain temporarily when changing them has higher migration risk than user value.

---

## 27. Final product statement

Dockplane should not launch as “OpenShip with a new logo.”

It should launch as the hardened version of the repository's best idea:

> A single, open control plane that can build, deploy, route, observe, recover, and automate applications across infrastructure the user chooses.

The decisive product work is reliability, host safety, recoverability, and truthful scope. The name change is useful only if it marks that standard.
