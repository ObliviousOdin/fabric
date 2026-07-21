# Dockplane Product Pack

This folder contains a source-grounded product and engineering plan for rebranding and hardening `oblien/openship` as **Dockplane**.

**Working tagline:** Deploy anywhere. Operate from one place.

## What OpenShip is

OpenShip is an open-source deployment control plane. It takes source from GitHub, a local folder, a template/URL, Dockerfile, or Docker Compose configuration and turns it into a running application.

The product is operated through:

- a Next.js dashboard;
- a CLI;
- an Electron desktop application;
- a REST API;
- and an MCP endpoint for AI clients.

Those clients are designed to call one Hono API. The API owns projects, deployments, services, domains, environments, hosts, backups, permissions, tokens, audit events, cloud operations, and related state. External work is delegated to adapters for Docker or direct-process runtime, SSH hosts, OpenResty routing, certificates, system checks, and managed cloud.

The same project model can target:

1. the machine running the control plane;
2. a user-owned Linux host reached over SSH;
3. managed cloud.

Self-hosted state can use PostgreSQL or embedded PGlite, while Redis/BullMQ support durable queues and production multi-process behavior.

## Straight assessment

The core architecture is promising. The scope is also too broad for its current maturity.

The inspected root version is `0.2.1`. The repository includes substantial implementation and documentation, but open issue reports cover installation, remote Docker/SSH, host adoption, ingress, desktop authentication, secure browser origins, DNS automation, and documentation drift. The email architecture explicitly says it describes a target state rather than the current state.

That means the right product move is not to market every feature more aggressively. It is to define a reliable core, label the rest honestly, and use the rebrand as a hardening boundary.

## Working rebrand

**Dockplane** was selected as a working name because it describes the architecture:

- code “docks” for inspection, build, and release;
- one control plane operates several destinations.

The name still requires formal legal, namespace, signing-identity, social-handle, package, and domain clearance.

## Included files

### `PRODUCT_SPEC.md`

The full product specification. It includes:

- product explanation;
- brand and positioning;
- users and jobs;
- principles and scope;
- stable, beta, and future feature boundaries;
- core user journeys;
- information architecture;
- detailed functional requirements;
- data model and state machines;
- technical architecture;
- security and threat model;
- reliability and performance targets;
- UX, accessibility, telemetry, packaging, upgrades, and commercial model;
- rebrand migration;
- roadmap;
- metrics;
- risks;
- Dockplane 1.0 definition of done.

### `GOAL.md`

The goal file for the product and repository. It defines:

- mission;
- north-star outcome;
- stable 1.0 scope;
- beta and out-of-scope work;
- non-negotiable rules;
- priority order;
- critical hardening work;
- success measures;
- milestones;
- rebrand constraints;
- the decision test for accepting changes.

Use this as the concise product-direction file at repository root.

### `AGENTS.md`

Repository instructions for coding agents and contributors. It defines:

- architectural invariants;
- repository map and toolchain;
- mandatory development workflow;
- API, database, adapter, security, host, runtime, CLI, dashboard, desktop, and MCP rules;
- rebrand compatibility behavior;
- required tests;
- documentation standards;
- prohibited shortcuts;
- completion-report format.

Use this at repository root so coding agents see it before making changes.

### `REBRAND_MAP.md`

The technical rename and migration plan. It maps:

- product and CLI names;
- package names;
- environment variables;
- data directories;
- cookies;
- PAT prefixes;
- Docker labels and resource names;
- system services;
- images;
- database internals;
- API/MCP;
- exports;
- desktop identities;
- domains and OAuth apps.

It also specifies compatibility windows, migration tests, rollout checklists, and what must not be changed through a blind global replacement.

## Recommended order of use

1. Approve or replace the working brand.
2. Approve the stable 1.0 scope in `GOAL.md`.
3. Use `PRODUCT_SPEC.md` to create epics and acceptance tests.
4. Add `AGENTS.md` to the repository root before agent-driven development.
5. Execute the truth-and-hardening milestone before visible rebrand work.
6. Use `REBRAND_MAP.md` for dual-name migration.
7. Promote beta features individually after they pass stable release gates.

## Source baseline

The pack was prepared from the public repository at inspected commit:

```text
a78cf47ccf6ec9a78c7156fe59826f81339ffeed
```

Observed repository state should be rechecked before implementation because the project is actively changing.
