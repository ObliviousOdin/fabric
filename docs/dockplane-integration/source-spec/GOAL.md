# GOAL.md — Dockplane

## Mission

Build Dockplane into a dependable, open deployment control plane that lets developers deploy and operate applications on the local machine, on Linux hosts they control, or in managed cloud without changing product workflows or surrendering an exit path.

The immediate objective is not to preserve every OpenShip claim. It is to turn the repository's strongest architecture into a stable product.

## Product promise

> Connect source code, review the plan, deploy to infrastructure you choose, and recover when something goes wrong.

A user should be able to understand:

- what Dockplane will change;
- where the application will run;
- which release is live;
- why a deployment failed;
- how to roll back;
- where data and credentials live;
- how to export or move the system;
- what an automation token or agent is allowed to do.

## Source baseline

This goal applies to the rebrand and hardening of the repository currently named OpenShip:

- repository: `oblien/openship`;
- inspected default-branch commit: `a78cf47ccf6ec9a78c7156fe59826f81339ffeed`;
- inspected root version: `0.2.1`;
- license: Apache-2.0;
- working replacement brand: Dockplane.

Dockplane is a working name until legal, package, handle, signing-identity, and domain clearance is complete.

## North-star outcome

On a fresh supported Linux host, a developer with a supported repository can reach a healthy HTTPS production endpoint in ten minutes or less, then complete a tested rollback and verified backup/restore without manual repair of Dockplane internals.

## Stable 1.0 scope

Dockplane 1.0 is complete when it provides a dependable version of all of the following:

1. A self-hosted control plane using PostgreSQL and Redis in the production reference topology.
2. GitHub, local-folder/archive, Dockerfile, and Docker Compose project sources.
3. Explicit stack detection and an editable build plan.
4. Container deployments on:
   - the Dockplane machine; and
   - one connected Linux host over SSH.
5. A read-only host adoption scan and operator-approved provisioning plan.
6. Separation of management address, public application address, and ingress mode.
7. Dockplane-managed ingress or external-ingress operation.
8. Non-wildcard custom domains with automatic HTTPS and renewal monitoring.
9. Durable deployment jobs, live logs, health checks, traffic switching, cancel, redeploy, restart, and rollback.
10. Environment and secret management.
11. Project/service resource settings with accurate enforcement descriptions.
12. Backup destinations, verified policies, scheduled runs, prepare/apply restore, and instance export/import.
13. Workspaces, roles, restricted grants, PATs, audit events, and revocation.
14. Dashboard, CLI, REST API, and permission-scoped MCP operations that call the same backend behavior.
15. Signed, versioned releases with tested install, update, database migration, and rollback paths.
16. OpenShip-to-Dockplane compatibility for data, commands, and configuration during the published migration window.
17. Complete support, security, topology, migration, and troubleshooting documentation.

## Beta scope

The following may ship, but must be labeled Beta until they meet the same release criteria:

- desktop application and zero-auth loopback mode;
- direct/process runtime;
- Dockplane Cloud;
- pull-request preview environments;
- DNS-provider automation and wildcard certificates;
- automated import of existing containers or Compose workloads;
- interactive host and service terminals;
- advanced traffic analytics;
- tunnel providers;
- sleep mode and autoscaling;
- project transfer between self-hosted and cloud;
- self-hosted email and webmail.

Beta code must not weaken or destabilize stable core operation.

## Out of scope for 1.0

Do not hold 1.0 for:

- Kubernetes;
- multi-node self-host scheduling;
- high-availability control plane;
- cross-host private networking;
- multi-region cloud;
- canary traffic percentages;
- visual arbitrary CI pipelines;
- enterprise SSO/SCIM;
- policy-as-code;
- GPU scheduling;
- a managed database service;
- a general server-control-panel feature set;
- stable email hosting.

## Non-negotiable product rules

### 1. Plan before mutation

No host, router, certificate, restore target, or destructive resource is changed before Dockplane produces an explicit plan or confirmation boundary.

### 2. The API is the source of product truth

The dashboard, CLI, desktop app, and MCP endpoint do not write the database directly and do not implement separate business logic.

### 3. Existing infrastructure is not disposable

A connected host may already contain valuable services. Dockplane scans first, identifies conflicts, and modifies only resources the operator explicitly approves.

### 4. Ownership must be provable

Cleanup relies on positive ownership records and labels, not name patterns alone. Ambiguous resources are preserved and surfaced for review.

### 5. Security fails closed

Authentication errors, missing authorization tags, provider failures, and agent ambiguity must not downgrade to weaker access.

### 6. Recoverability is part of deployment

A successful production release has logs, health evaluation, immutable source/config identity, retained rollback data, and a documented data-recovery path.

### 7. Stable means tested and supported

Code existence is not enough. Stable features have compatibility behavior, tests, documentation, upgrade coverage, known limits, and operational error handling.

### 8. Self-hosting remains useful without cloud

Core deployment, domains, backups, access control, audit, API, and export do not require a paid Dockplane Cloud account.

### 9. Agents receive least privilege

Agent credentials are read-only or scoped by default. MCP tools pass through ordinary API authorization, and credential-administration routes are never tools.

### 10. Truth beats marketing

Do not claim wildcard certificates, CDN, autoscaling, “any Linux,” “any stack,” “zero downtime,” or production readiness beyond the combinations proven by release tests.

## Priority order

When work competes, use this order:

1. security and prevention of data loss;
2. host safety;
3. successful installation and upgrade;
4. deployment correctness and rollback;
5. backup and restore;
6. error clarity and diagnostics;
7. API/client consistency;
8. performance and operator convenience;
9. beta features;
10. visual polish and marketing breadth.

Do not trade a higher item for a lower item without an explicit product decision.

## Required architecture

```text
Dashboard ─┐
CLI ───────┼── /api/* ──> Control-plane API ──> DB + durable jobs
Desktop ───┘                         │
MCP/API clients ─────────────────────┘
                                     │
                                     └── adapters
                                           ├── runtime
                                           ├── infrastructure
                                           ├── system/host
                                           ├── source
                                           ├── backup
                                           └── notification
```

Architecture invariants:

- only the API writes control-plane state;
- controllers are transport code;
- services own business rules;
- repositories own database access and workspace scoping;
- adapters own external side effects;
- deploy-time configuration is snapshotted;
- cloud-only configuration is never required for self-host startup;
- long-running work is durable and independent of browser/request lifetime.

## Critical hardening work

Before the rebrand is treated as a launch, resolve and prove the following classes of failure:

1. Clean Linux installation and package-distribution reliability.
2. Versioned prebuilt images and signed release artifacts.
3. Remote Docker artifact verification.
4. SSH/SFTP channel lifecycle and connection-pool exhaustion.
5. OpenResty/proxy installation on supported hosts.
6. Safe coexistence with existing Nginx, Certbot, containers, ports, and volumes.
7. External-ingress support.
8. Desktop origin, cookie, and redirect correctness.
9. Secure-context behavior for non-loopback dashboard origins.
10. DNS-provider and wildcard-certificate claim alignment.
11. Documentation/code drift.
12. Restore integrity and failure recovery.
13. OpenShip-to-Dockplane data and configuration migration.
14. Permission and MCP cross-workspace tests.
15. Email isolation from the core release path.

An issue report is not automatically proof that a current defect remains, but every reported class above must have a reproducible test or an explicit disposition.

## Success measures

### Activation

- At least 95% of automated fresh-host installations succeed before 1.0; target 99% after launch.
- At least 90% of supported reference projects complete their first deployment without manual host repair.
- Median supported first deployment to healthy HTTPS is ten minutes or less.
- Low-confidence stack detection never silently auto-deploys.

### Deployment reliability

- At least 99.5% of deployments succeed after a valid artifact exists and dependencies are healthy.
- At least 99.9% of traffic switches succeed after candidate health passes.
- At least 99.9% of eligible rollbacks succeed with a retained compatible artifact.
- No acknowledged durable job is silently lost.
- Cleanup-pending resources are visible and retryable.

### Security and trust

- Zero cross-workspace authorization bypasses.
- Zero mounted routes without permission tags.
- Zero secret values in persisted logs in the redaction test corpus.
- Every successful state-changing operation has an audit event.
- Every destructive agent operation is attributable to a client and human grant owner.
- Every host mutation is preceded by a recorded plan or approved operation.

### Recovery

- Stable backup destinations pass write/read/delete verification.
- Restore prepare validates checksum and target before mutation.
- Instance export/import round trips projects, access, and encrypted secrets.
- Upgrade from the previous stable version and rollback are tested for every release.
- Legacy OpenShip exports remain importable during the compatibility commitment.

### Product quality

- P0 API/CLI/dashboard operations have parity.
- Stable workflows have end-to-end tests and troubleshooting docs.
- Feature maturity labels match actual availability.
- Accessibility target for critical dashboard workflows is WCAG 2.2 AA.

## Milestones

### Milestone 0 — establish truth

- inventory modules and feature flags;
- assign maturity labels;
- build supported-host and reference-app matrices;
- create stable error taxonomy;
- reproduce or close high-risk issue classes;
- document current data and cloud boundaries.

**Exit:** The team can state exactly what works, where, and under which version.

### Milestone 1 — harden the core

- reliable distribution;
- safe host scan/plan/apply;
- SSH and remote Docker reliability;
- managed/external ingress;
- deployment and rollback state machines;
- backup/restore integrity;
- security and workspace test suites;
- upgrade recovery.

**Exit:** End-to-end self-hosted reference scenario passes repeatedly in clean environments.

### Milestone 2 — dual-name rebrand

- central brand configuration;
- Dockplane UI and packages;
- `dockplane` CLI;
- `openship` compatibility shim;
- environment aliasing;
- data-directory and export migration;
- token-prefix compatibility;
- documentation migration.

**Exit:** Existing OpenShip test installations upgrade without loss and can roll back.

### Milestone 3 — Dockplane 1.0

- all stable P0 requirements;
- published support and compatibility policy;
- signed release;
- security review;
- complete docs;
- public known limitations.

**Exit:** Definition of done in `PRODUCT_SPEC.md` passes.

### Milestone 4 — expand with evidence

- cloud;
- previews;
- DNS providers;
- agent approvals;
- advanced metrics;
- fleet/agent model.

Beta capabilities become stable one at a time; they do not inherit stability from the 1.0 label.

## Rebrand constraints

Canonical new forms:

- product: Dockplane;
- CLI: `dockplane`;
- package scope: `@dockplane/*`;
- data directory: `~/.dockplane`;
- token prefix: `dpl_pat_`;
- labels: `dockplane.*`;
- environment prefix: `DOCKPLANE_`.

Compatibility requirements:

- retain `openship` CLI shim through Dockplane 1.x;
- accept legacy environment variables through 1.x;
- recognize legacy Docker labels indefinitely for safe ownership and cleanup;
- import legacy exports at least through 2.x;
- avoid forced database/table renames in 1.x;
- keep `/api` stable in 1.x;
- migrate only after a backup and verification step.

## Decision test

Before accepting a change, ask:

1. Does it make deployment or recovery more dependable?
2. Does it preserve the single-control-plane architecture?
3. Does it avoid taking ownership of unrelated infrastructure?
4. Does it retain least privilege?
5. Does it work without Dockplane Cloud when it belongs to core?
6. Can the behavior be tested on a clean supported environment?
7. Is the failure visible and actionable?
8. Is the compatibility impact documented?
9. Is the maturity label honest?
10. Is this more important than unresolved P0 hardening?

A “no” does not automatically reject the change, but it requires explicit justification.

## Completion statement

The goal is achieved when Dockplane is no longer best described as an ambitious early deployment platform.

It is achieved when operators can trust it to install cleanly, state its plan, deploy predictably, leave healthy traffic alone when a candidate fails, restore from verified data, respect workspace boundaries, survive upgrades, and get out of the way when they choose another platform.
