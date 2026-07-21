# AGENTS.md — Dockplane repository instructions

## Purpose

This repository is the codebase currently named OpenShip and being hardened and rebranded as **Dockplane**.

Dockplane is an open deployment control plane. It builds and operates applications on:

- the machine running Dockplane;
- Linux hosts connected over SSH; or
- Dockplane Cloud.

The repository contains a broad feature set, but the engineering priority is a reliable, safe core. Do not expand claims or stable scope merely because a module exists.

Read `GOAL.md` and `PRODUCT_SPEC.md` before making product-level changes.

## Product truth

The architectural center is one control-plane API.

```text
Dashboard ─┐
CLI ───────┼── HTTP /api/* ──> API ──> DB + durable jobs
Desktop ───┘                       │
MCP/API clients ───────────────────┘
                                   └── adapters
                                         ├── runtime
                                         ├── infrastructure
                                         └── system/host
```

The dashboard, CLI, desktop app, REST clients, and MCP clients are interfaces to the same backend behavior. They are not independent implementations.

The stable product goal is self-hosted, single-control-plane deployment to the local machine and owned Linux hosts using the container runtime. Desktop, process mode, managed cloud, wildcard DNS, advanced mail, and multi-node features are beta or later unless the specification is explicitly changed.

## Repository map

```text
apps/
  api/          Hono control-plane API, services, workers, webhooks
  cli/          CLI and self-host launcher
  dashboard/    Next.js operator dashboard
  desktop/      Electron wrapper and local service launcher
  email/        beta mail engine and webmail work
  web/          marketing site and documentation

packages/
  adapters/     runtime, infrastructure, and host/system adapters
  core/         pure shared types, stack detection, constants, errors
  db/           control-plane Drizzle schema, client, repositories
  db-email/     email-specific schema and repositories
  onboarding/   shared setup flows and API client
  ui/           shared React components
```

Additional root files include Docker Compose, environment examples, release scripts, Turborepo configuration, TypeScript configuration, and documentation.

## Toolchain

Use the repository-pinned toolchain:

- Bun `1.3.10`;
- Node.js `22` or later;
- TypeScript strict mode;
- Turborepo;
- Prettier;
- Vitest;
- Docker where the affected behavior requires it.

Use Bun for workspace dependency and script operations. Do not introduce a second lockfile or run a package-manager conversion.

Common commands:

```bash
bun install --frozen-lockfile

bun dev:local
bun dev:api
bun dev:dashboard
bun dev:web
bun dev:desktop
bun dev:email

bun run test
bun run build
bun run lint
bun format

bun run --cwd apps/api lint
bun run --cwd apps/api test

bun run --cwd apps/dashboard test
bun run --cwd packages/adapters test

bun db:generate
bun db:migrate
```

Run the smallest relevant checks during iteration and the required broader checks before declaring completion.

## Mandatory architecture invariants

### API is the only product-state writer

- Clients must not write the control-plane database directly.
- Desktop code must not create a separate product-state implementation.
- MCP tools must not bypass API routes or application services.
- Scripts that mutate product state must call the API or an explicit internal service entry point with the same authorization and invariants.

### Controllers are transport; services own behavior

The normal API module pattern is:

```text
<name>.routes.ts       route definitions and permission metadata
<name>.controller.ts   HTTP parsing and response mapping
<name>.service.ts      business rules and state transitions
<name>.schema.ts       request/response validation schemas
```

Keep controllers thin. Do not put orchestration, authorization shortcuts, shell commands, or database transaction logic in route files.

### Repositories own data access

- Database reads and writes belong in `packages/db` repositories or the established repository layer.
- Workspace scope must be enforced at the data/service boundary.
- A client-supplied resource ID is never sufficient authorization.
- Do not scatter raw SQL through controllers.
- Do not return secret columns from general repository reads.

### Adapters own external side effects

Docker, process, SSH, routing, certificates, host provisioning, source-provider, backup-provider, and cloud-provider operations belong behind adapters.

Do not call Docker, `ssh`, `systemctl`, OpenResty, Certbot, or cloud APIs directly from dashboard code or ordinary feature services.

For a mutating infrastructure operation, prefer:

```text
inspect -> plan -> approve/validate -> apply -> verify -> record
```

Do not combine discovery and mutation when the operator needs to see conflicts first.

### Deployment snapshots are immutable

When a deployment starts, snapshot:

- source revision;
- build plan;
- environment references;
- service configuration;
- resources;
- destination;
- runtime mode;
- health checks;
- routing intent.

Do not mutate an in-progress deployment because project settings changed. Create a new deployment or operation.

### Long-running work is durable

Builds, deployments, backups, restores, migrations, host provisioning, and destructive cleanup must not depend on an HTTP connection or browser tab remaining open.

Use the established job abstraction. Jobs need durable state, attempt information, progress events, cancellation semantics, and idempotency.

### Self-hosted core does not require cloud secrets

Cloud-only modules and provider credentials must be gated by mode and capability.

A normal self-hosted instance must start and operate without:

- Stripe;
- managed-cloud provider credentials;
- the Dockplane Cloud GitHub App private key;
- cloud billing configuration.

Missing cloud configuration must not cause unrelated self-host routes to return 500 or prevent boot.

## Working protocol

### Before editing

1. Read the relevant product requirement in `PRODUCT_SPEC.md`.
2. Inspect the nearest implementation, tests, schema, docs, and callers.
3. Identify whether the feature is stable, beta, experimental, or planned.
4. Identify the source of truth: API service, repository, core helper, or adapter.
5. Check compatibility impact for existing OpenShip installations.
6. State or write down the failure modes before choosing the implementation.

Do not begin with a repo-wide rename, broad refactor, or dependency upgrade unless the task specifically requires it.

### During implementation

- Make the smallest coherent change.
- Preserve strict types.
- Prefer explicit state and error codes to boolean ambiguity.
- Add tests with the behavior change, not later.
- Keep external side effects mockable.
- Make retries idempotent.
- Keep cleanup ownership-safe.
- Update docs and examples that describe the changed behavior.
- Keep logs useful but secret-free.
- Do not silently ignore unsupported configuration.

### Before completion

1. Review the diff for unrelated changes.
2. Run formatting.
3. Run focused type checks and tests.
4. Run broader build/test commands appropriate to the impact.
5. Validate migrations from the previous state.
6. Check self-hosted mode without cloud credentials when API code changed.
7. Check authorization and workspace scope for every new route.
8. Check compatibility aliases when public naming changed.
9. Update changelog/release notes when user-visible.
10. Report what was tested and what could not be tested.

## Error handling

Every operator-facing failure should have:

- a stable machine code;
- a concise message;
- stage or subsystem;
- resource/job/request identifier;
- retryability;
- remediation guidance;
- an internal cause retained for logs without leaking secrets.

Do not turn all failures into generic messages such as:

- `Deployment failed`;
- `Docker build failed`;
- `Something went wrong`;
- `Internal server error` without a request ID.

Examples of failures that must remain distinguishable:

- source authentication;
- source clone;
- install command;
- application build;
- artifact missing;
- Docker daemon unavailable;
- SSH session exhaustion;
- host key mismatch;
- router validation;
- DNS verification;
- certificate issuance;
- application health check;
- backup destination;
- restore checksum;
- permission denial.

Unhandled API errors may return a generic message, but structured internal logs and a request ID must preserve diagnosis.

## Security rules

### Route permissions

- Every mounted route declares a `resource:action` permission tag.
- The startup assertion for untagged routes must remain active.
- Do not add “temporary” public mutations.
- Health endpoints and signed webhooks are explicit exceptions, not precedents.
- Authorization occurs server-side even when UI hides an action.

### Workspace isolation

- Resolve the workspace from authenticated context and validated request semantics.
- Confirm membership or token workspace scope.
- Query resources within that workspace.
- For restricted principals, check resource grants and inheritance.
- Return not found for inaccessible resources where existence is sensitive.
- Add cross-workspace tests for every new resource type.

### Authentication

- Browser sessions use httpOnly cookies.
- PATs are bearer credentials for non-browser clients.
- Do not accept bearer tokens from trusted dashboard browser origins.
- PAT plaintext is shown once and only hashes are stored.
- Authentication subsystem errors fail unavailable, not anonymous.
- Desktop zero-auth requires all documented loopback and mode gates.
- Never trust `Host` or forwarded headers for loopback identity without configured proxy trust.

### Secrets

- Use established encryption helpers.
- Never log secret values, private keys, access tokens, passwords, connection strings with credentials, or decrypted export bundles.
- Secret replacement forms return metadata, not existing plaintext.
- Redact before persistence and streaming.
- Tests should include common and adversarial secret formats.
- Do not store credentials in repository-local files.

### Host commands

Treat every project field, service name, path, branch, domain, username, and environment value as hostile input.

- Prefer argument arrays and APIs over shell interpolation.
- Quote through one reviewed helper when a shell is unavoidable.
- Reject newlines and control characters where they have no valid use.
- Test injection strings.
- Use least privilege.
- Do not pipe unverified remote scripts into a privileged shell.
- Pin and verify downloaded artifacts.

### Build execution

Repository code is untrusted.

- Do not run a user build in the control-plane process.
- Preserve runtime isolation.
- Block or warn on privileged Compose options according to product policy.
- Do not mount the host Docker socket into customer application containers by default.
- Avoid exposing control-plane environment variables to builds.
- Enforce resource and time limits.

### MCP and agents

- Tools map to ordinary API operations.
- Filter `tools/list` by capability.
- Recheck auth and permissions on every call.
- Never expose auth, token-minting, consent, or MCP administration routes as tools.
- Mark read-only and destructive tools accurately.
- Keep agent identity in audit events.
- Do not treat natural-language intent as authorization.
- High-risk operations should support an explicit approval boundary.

## Host and runtime rules

### Scan before provisioning

A new host flow is read-only until a plan is approved.

Scan for:

- OS and architecture;
- memory, CPU, disk;
- package manager;
- Docker and daemon access;
- listening ports;
- firewall;
- Nginx, OpenResty, Caddy, Traefik, Apache;
- Certbot and certificate paths;
- containers, networks, and volumes;
- systemd units;
- existing Dockplane/OpenShip ownership markers.

Do not edit a pre-existing proxy merely because a desired include is missing.

### Separate addresses

Do not reuse one `host` field for all meanings.

Keep distinct:

- SSH/management address;
- public application address;
- ingress/router address;
- dashboard/API public origin.

This is required for private networks, Tailscale, external proxies, NAT, and Cloudflare-like ingress.

### Resource ownership

Cleanup requires positive ownership.

For Docker resources, retain recognition of both:

- `dockplane.*` labels; and
- legacy `openship.*` labels.

Names can support diagnosis but are not enough to authorize deletion.

Never delete an ambiguous volume, container, network, certificate, config file, or system service.

### SSH lifecycle

- Pin host keys.
- Close exec, SFTP, tunnel, and Docker-over-SSH channels deterministically.
- Bound connection-pool size and idle lifetime.
- Test repeated build/deploy loops beyond typical `MaxSessions` defaults.
- Reset unhealthy pooled connections.
- Distinguish transport failure from application build failure.

### Routing

- Generate configuration in a temporary location.
- Validate before reload.
- Atomically activate where possible.
- Keep the previous working config.
- A failed candidate or certificate operation must not remove the existing healthy route.
- Support external-ingress mode without requiring ports 80/443.

### Runtime isolation

Container mode is the stable default.

- unique deployment resources;
- project-scoped networks;
- project-scoped named volumes;
- dynamic host ports behind the router;
- explicit resource limits;
- labels and ownership records.

Process mode is weaker isolation. Do not present CPU/memory caps as enforced if they are not. Do not promise zero downtime where processes cannot overlap.

## Database changes

### Schema work

- Change schema in `packages/db/src/schema/`.
- Generate a migration for production changes.
- Do not use `db:push` as a substitute for a committed production migration.
- Include defaults/backfills for existing rows.
- Avoid long blocking migrations where a staged migration is possible.
- Document irreversible changes.
- Test upgrading representative prior data.

### Transactions

Use transactions when a product invariant spans multiple writes, especially:

- creating deployment plus job;
- traffic switch plus active-release state;
- token/consent revocation;
- destructive cleanup state;
- import/merge;
- billing or usage idempotency.

External side effects cannot be rolled back by a database transaction. Use operation states and compensation rather than pretending they are atomic.

### Secrets and exports

- Preserve encrypted-at-rest behavior.
- Export secrets only in the established passphrase-sealed bundle.
- Import validates format and passphrase before writes.
- Keep replace and merge behavior deterministic.
- Accept legacy OpenShip formats during the compatibility window.

### Internal-name restraint

Do not rename database tables or columns only for branding. User-facing value is low and migration risk is high. Internal `openship` names may remain until a major-version migration has a concrete benefit.

## API changes

### Route design

- Follow existing module patterns.
- Validate path, query, headers, and body.
- Keep response and error shapes stable.
- Use asynchronous operation resources for long jobs.
- Add idempotency handling for retryable mutations.
- Return request IDs.
- Paginate collections.
- Document mode availability.

### Breaking changes

Within Dockplane 1.x:

- do not remove documented fields;
- add fields compatibly;
- deprecate before removal;
- preserve `/api`;
- preserve CLI JSON contracts;
- preserve export readability;
- preserve legacy naming aliases as documented.

A brand rename is not permission to break the API.

### Webhooks

- Verify provider signature.
- Apply replay protection.
- Deduplicate delivery IDs.
- Make processing idempotent.
- Record receipt and result without storing unnecessary secret payload.
- Respond quickly and queue heavy work.

## Dashboard rules

- The dashboard is an API client.
- Do not embed direct infrastructure credentials or provider SDK secrets in client code.
- Derive API and redirect origins from runtime configuration.
- Use same-origin proxying or explicit trusted origins.
- Present maturity labels.
- Present plan/diff before host changes and destructive operations.
- Do not use color alone for status.
- Preserve keyboard and screen-reader operation.
- Provide text/table alternatives to charts.
- Show exact error code and job/request ID in expandable diagnostics.
- Never imply “backed up” means “restore-tested.”
- Do not hide weaker process isolation.

Shared visual components belong in `packages/ui` when they are genuinely reusable. Product-specific behavior can remain in the dashboard.

## CLI rules

Canonical command is `dockplane`; legacy `openship` remains a shim during 1.x.

- Human output is readable.
- `--json` output is stable and free of spinners/ANSI noise.
- Exit codes distinguish common failure classes.
- Non-interactive use never prompts unexpectedly.
- Destructive actions require explicit confirmation flags/tokens.
- `--follow` reconnects from a cursor where supported.
- Credentials are stored outside project directories with restrictive permissions or OS keychain support.
- CLI commands call the same API as the dashboard.
- Keep legacy command aliases covered by tests.

## Desktop rules

Desktop is beta unless explicitly promoted.

- Run the same API and dashboard.
- Bind to loopback.
- Use dynamic ports.
- Protect PGlite with a single-instance lock.
- Derive redirects from the active origin.
- Refuse public/CLI-managed zero-auth.
- Keep data export compatible with self-host.
- Sign updates before stable promotion.
- Do not add desktop-only product state.

## Rebrand rules

### Canonical new public names

- `Dockplane`
- `dockplane`
- `@dockplane/*`
- `~/.dockplane`
- `dpl_pat_`
- `DOCKPLANE_*`
- `dockplane.*` Docker labels
- `dockplane-export-*.json`

### Required compatibility

- `openship` binary remains a shim through Dockplane 1.x.
- Legacy `OPENSHIP_*` environment variables are accepted with explicit precedence rules.
- Legacy `~/.openship` data is detected and migrated only after backup.
- Legacy `opsh_pat_` tokens remain valid during 1.x or until rotated.
- Legacy `openship.*` labels are recognized indefinitely for safe ownership.
- Legacy exports remain importable through at least 2.x.
- `/api` stays unchanged in 1.x.
- Database/table names are not force-renamed for branding.

### Naming implementation

Use centralized constants/configuration for visible product name, command examples, website origins, token prefix, data paths, labels, and user agents.

Do not run an unreviewed global replacement of `openship`.

Classify each occurrence:

1. visible brand — rename;
2. public compatibility surface — dual support;
3. historical data — preserve/read;
4. internal identifier with no user value — defer;
5. third-party or license text — do not alter incorrectly.

## Testing requirements

### Minimum focused checks

For API logic:

```bash
bun run --cwd apps/api lint
bun run --cwd apps/api test
```

For dashboard logic:

```bash
bun run --cwd apps/dashboard test
bun run --cwd apps/dashboard build
```

For adapter logic:

```bash
bun run --cwd packages/adapters test
```

For shared types:

```bash
bun run lint
```

### Required broader checks by change type

| Change | Required validation |
|---|---|
| API route/service | typecheck, module tests, authorization tests, API smoke |
| DB schema | generated migration, upgrade test, repository tests, export/import impact |
| runtime adapter | unit tests, local integration, repeated cleanup, ownership test |
| SSH/host adapter | channel stress, host-key test, reconnect, conflict scan |
| routing/cert | config validation, rollback, existing-route preservation |
| deployment state | state-transition tests, retry/idempotency, cancellation, recovery |
| dashboard workflow | component/unit test, API integration, accessibility smoke |
| CLI command | human output, JSON output, exit code, non-interactive path |
| MCP tool | capability filter, read-only, scoped resource, cross-workspace denial, audit |
| rebrand | new path plus every promised legacy alias |
| installer/release | clean install, update, rollback, checksum/signature |
| backup/restore | destination verification, checksum, two-phase restore, failure recovery |

### Reference applications

Maintain small fixtures for:

- Node.js;
- Python;
- Go;
- static site;
- Dockerfile;
- Docker Compose with web + database + named volume;
- failing build;
- failing health check;
- WebSocket application;
- monorepo;
- hostile names/paths for injection tests.

### Test honesty

Do not mark a path tested when:

- only types compiled;
- a mock bypassed the risky boundary;
- an integration test was skipped;
- Docker/SSH behavior was inferred from unit tests;
- cloud configuration was present during a self-host test;
- a migration started from an empty database only.

Report limitations explicitly.

## Documentation rules

Documentation is part of the release.

Update the relevant material under `apps/web/content/docs/` when behavior changes.

Requirements:

- commands must run against released binaries;
- maturity labels must be visible;
- self-host and cloud behavior must be distinguished;
- destructive steps include consequences and recovery;
- examples must use Dockplane canonical names while migration pages show legacy forms;
- screenshots must match the current UI or be clearly marked pending;
- generated API references should come from source where possible;
- known limitations must not be hidden in issue trackers;
- translated destructive instructions must not remain stale.

Do not claim:

- wildcard support without DNS-01 automation;
- “any Linux” without support-matrix evidence;
- zero downtime for process mode;
- automatic safe adoption without scan/plan behavior;
- stable mail hosting while its target architecture is incomplete;
- multi-node/autoscaling/CDN behavior without verified implementation and operations.

## Dependencies

- Prefer existing dependencies and platform APIs.
- Add a dependency only when it materially reduces risk or complexity.
- Check maintenance, license, size, security history, runtime compatibility, and Bun/Node behavior.
- Do not introduce overlapping libraries for validation, logging, HTTP, queues, or ORM without a migration decision.
- Pin security-sensitive external binaries and artifacts.
- Include lockfile changes only when intended.

## Commits and pull requests

Follow repository conventions:

- Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, `chore:`;
- branch prefixes `feat/`, `fix/`, `docs/`, `chore/`;
- formatted code;
- focused diff.

A good change description states:

1. problem;
2. user impact;
3. architecture choice;
4. security/compatibility impact;
5. tests run;
6. migration or rollout;
7. remaining limitation.

Do not mix a rebrand sweep, dependency update, refactor, and behavior change into one unreviewable change.

## Prohibited shortcuts

Do not:

- write product state from a client;
- bypass permission middleware;
- disable the missing-permission startup check;
- weaken auth when the auth backend fails;
- trust resource IDs without workspace scope;
- log secrets for debugging;
- run untrusted builds in the API process;
- interpolate untrusted input into shell commands casually;
- overwrite existing proxy configuration without a plan;
- delete Docker resources based only on names;
- silently accept unsupported Compose fields;
- report queued work as completed;
- promise zero downtime for process mode;
- hide cleanup failures;
- require cloud credentials for self-hosted core;
- expose token or auth administration through MCP;
- change public names without legacy handling;
- rename database internals solely for cosmetic consistency;
- call a feature stable because a happy-path demo works;
- close a task without stating tests and limitations.

## Agent completion format

When an agent completes a coding task, its final report should contain:

### Changed

A concise description of behavior and files.

### Why

The product or reliability problem solved.

### Compatibility and security

Any public contract, migration, permission, secret, host, or rebrand effect.

### Validation

Exact commands and integration scenarios run.

### Remaining limits

Anything not tested, beta-only, environment-dependent, or intentionally deferred.

Be direct. Do not describe work as complete when a required integration path was not exercised.
