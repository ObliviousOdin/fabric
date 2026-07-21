# REBRAND_MAP.md — OpenShip to Dockplane

## Purpose

This document turns the Dockplane working brand into an implementation plan.

It is intentionally conservative. A platform rebrand touches executable names, package metadata, data directories, cookies, environment variables, token prefixes, Docker labels, images, service names, exports, documentation, domains, desktop signing identities, and historical records. A blind repository-wide replacement would break installations and could cause Dockplane to lose track of resources it created under the OpenShip name.

The rule is:

> Rename the user-visible product immediately; migrate public technical surfaces with dual support; leave low-value internal names alone until they can be changed safely.

Dockplane remains a working name until legal and namespace clearance is complete.

---

## 1. Brand definition

| Element | Dockplane |
|---|---|
| Product name | Dockplane |
| Company/product relationship | Company name undecided; product is Dockplane |
| Tagline | Deploy anywhere. Operate from one place. |
| Category | Open deployment control plane |
| One-line description | Build, deploy, and operate applications on your machine, your Linux hosts, or managed cloud from one control plane. |
| CLI | `dockplane` |
| Short technical prefix | `dpl` |
| Package scope | `@dockplane/*` |
| Environment prefix | `DOCKPLANE_` |
| Docker label namespace | `dockplane.*` |
| Default data directory | `~/.dockplane` |
| PAT prefix | `dpl_pat_` |
| Export filename | `dockplane-export-<timestamp>.json` |
| User agent | `dockplane/<version>` |
| Desktop product name | Dockplane |

Public domains are not specified until they are owned.

---

## 2. Classification rules

Every `openship`, `OpenShip`, `OPENSHIP`, `opsh`, and related reference must be classified before changing it.

### Class A — visible brand

Examples:

- page titles;
- navigation;
- desktop product name;
- CLI help;
- documentation prose;
- email sender display name;
- app icons;
- screenshots;
- package descriptions;
- website metadata.

**Action:** Rename to Dockplane in the first dual-brand release.

### Class B — public compatibility surface

Examples:

- CLI binary;
- npm package;
- environment variables;
- data paths;
- PAT prefixes;
- Docker labels;
- image names;
- service names;
- export filenames;
- cookies;
- integration identifiers.

**Action:** Introduce Dockplane form, continue reading or executing the OpenShip form, define precedence, warn when safe, and remove only through a major-version plan.

### Class C — historical data

Examples:

- old audit event messages;
- stored deployment logs;
- export manifests;
- image tags referenced by historical deployments;
- existing container labels;
- release metadata;
- user-created project names containing OpenShip.

**Action:** Preserve. Render old brand where it is historical. Never rewrite user content without request.

### Class D — internal identifier

Examples:

- table names;
- migration IDs;
- internal directory names not exposed to users;
- private function names;
- database names;
- old test fixtures.

**Action:** Leave in place unless the rename has a real maintenance or safety benefit. Add comments or aliases if needed.

### Class E — third-party or legal text

Examples:

- upstream licenses;
- vendored email-engine references;
- external URLs;
- copyright attribution;
- package names owned by third parties.

**Action:** Do not alter incorrectly. Review individually.

---

## 3. Public surface map

### 3.1 Product text

| OpenShip form | Dockplane form | Migration behavior |
|---|---|---|
| Openship / OpenShip | Dockplane | Replace visible current-product text |
| Openship Cloud | Dockplane Cloud | Replace visible current-product text |
| Openship Desktop | Dockplane Desktop | Replace visible current-product text |
| Openship CLI | Dockplane CLI | Replace visible current-product text |
| Openship instance | Dockplane control plane / Dockplane instance | Prefer “control plane” where precise |
| openship.io examples | Cleared Dockplane domain | Do not publish placeholder as owned |

Centralize visible product strings. Do not keep dozens of literal brand strings distributed across UI code.

### 3.2 CLI

| Surface | Legacy | Canonical |
|---|---|---|
| Binary | `openship` | `dockplane` |
| npm package | `openship` | `dockplane` |
| Config directory | current implementation-specific path | Dockplane path |
| User agent | `openship/<version>` | `dockplane/<version>` |

Migration:

1. Publish `dockplane`.
2. Keep `openship` package/binary as a thin shim that executes the same implementation.
3. Print a non-blocking deprecation notice only in interactive mode.
4. Never add the warning to `--json` output.
5. Keep aliases through Dockplane 1.x.
6. Ensure both commands read the same credential/config store.
7. Prevent two installations from creating conflicting services.
8. Test all documented OpenShip commands used by migration guides.

Example:

```text
$ openship deploy

OpenShip has been renamed Dockplane.
This command remains supported through Dockplane 1.x.
Use: dockplane deploy
```

The command must still run.

### 3.3 Package names

Proposed mapping:

| Current | Proposed |
|---|---|
| root package `openship` | `dockplane` |
| CLI package `openship` | `dockplane` |
| `@repo/api` | optionally `@dockplane/api` |
| `@repo/core` | optionally `@dockplane/core` |
| `@repo/db` | optionally `@dockplane/db` |
| `@repo/adapters` | optionally `@dockplane/adapters` |
| `@repo/ui` | optionally `@dockplane/ui` |
| `@repo/onboarding` | optionally `@dockplane/onboarding` |

Workspace package scopes are private implementation details today. Rename them only if the change improves clarity and all workspace references can move atomically. This is lower priority than the public CLI package.

### 3.4 Environment variables

Brand-specific variables should gain `DOCKPLANE_` names.

Examples:

| Legacy | Canonical |
|---|---|
| `OPENSHIP_TARGET` | `DOCKPLANE_TARGET` |
| `OPENSHIP_REQUIRE_REDIS` | `DOCKPLANE_REQUIRE_REDIS` |
| `OPENSHIP_JOB_RUNNER` | `DOCKPLANE_JOB_RUNNER` |
| `OPENSHIP_CACHE_STORE` | `DOCKPLANE_CACHE_STORE` |
| `OPENSHIP_RATE_LIMIT_STORE` | `DOCKPLANE_RATE_LIMIT_STORE` |
| `OPENSHIP_EXTRA_TRUSTED_ORIGINS` | `DOCKPLANE_EXTRA_TRUSTED_ORIGINS` |
| `OPENSHIP_REQUIRE_AUTH` | `DOCKPLANE_REQUIRE_AUTH` |
| `OPENSHIP_PUBLIC_URL` | `DOCKPLANE_PUBLIC_URL` |
| `OPENSHIP_ALLOW_ZERO_AUTH` | `DOCKPLANE_ALLOW_ZERO_AUTH` |
| `OPENSHIP_DEV_LOCK_TAKEOVER` | `DOCKPLANE_DEV_LOCK_TAKEOVER` |

Generic variables may remain generic:

- `NODE_ENV`;
- `DATABASE_URL`;
- `REDIS_URL`;
- `PORT`;
- `CLOUD_MODE`;
- `DEPLOY_MODE`;
- `BETTER_AUTH_SECRET`;
- `BETTER_AUTH_URL`;
- provider-standard variables.

Precedence:

1. canonical `DOCKPLANE_*`;
2. legacy `OPENSHIP_*`;
3. default.

If both forms are set with different values:

- fail startup for security- or topology-sensitive values;
- otherwise use the canonical value and emit a clear warning.

Do not silently pick one for auth mode, public URL, trusted origins, data directory, or key material.

### 3.5 Data directories

Canonical:

```text
~/.dockplane
```

Legacy examples may include:

```text
~/.openship
~/.openship/data
```

Migration flow:

1. Detect canonical and legacy directories.
2. If both contain data, stop and require operator selection.
3. Acquire the legacy single-instance lock.
4. Create a backup/export.
5. Copy or atomically rename only when filesystem semantics are safe.
6. Preserve permissions and ownership.
7. Write a migration manifest with source, destination, versions, checksums, and time.
8. Start from canonical directory.
9. Run database and secret verification.
10. Retain a rollback pointer or untouched legacy backup.
11. Never let two processes open the same PGlite data.

Do not use a symlink as the only migration strategy across all platforms without testing lock and backup behavior.

### 3.6 Cookies

Current names may include OpenShip branding.

Proposed:

- `dockplane.session_token`;
- `dockplane-cloud.session_token`.

Cookie-name migration is sensitive because an abrupt rename signs users out and can create duplicate sessions.

Plan:

1. read canonical cookie first;
2. read valid legacy cookie second during compatibility period;
3. issue canonical cookie after successful legacy authentication;
4. revoke or expire legacy cookie when practical;
5. keep self-hosted and cloud cookie namespaces distinct;
6. test same-origin and cross-subdomain deployments;
7. derive domain/secure/same-site values from topology.

Never broaden a cookie domain merely for brand migration.

### 3.7 PATs

Canonical prefix:

```text
dpl_pat_
```

Legacy prefix:

```text
opsh_pat_
```

Plan:

- issue only new tokens after rebrand;
- validate both prefixes during Dockplane 1.x;
- store token type/version metadata;
- prompt users to rotate legacy tokens;
- never rewrite plaintext tokens, because plaintext is not stored;
- preserve hash comparison and entropy;
- ensure prefix parsing does not become an authorization decision;
- retain revocation and workspace scope.

### 3.8 Docker resources

Canonical labels:

```text
dockplane.project
dockplane.deployment
dockplane.service
dockplane.build
```

Legacy labels:

```text
openship.project
openship.deployment
openship.service
openship.build
```

Rules:

- new resources receive canonical labels;
- during 1.x, optionally also apply legacy labels if an older component must see them;
- discovery and cleanup recognize both forever;
- if canonical and legacy labels disagree, stop and require review;
- do not relabel running historical containers automatically;
- ownership records in the database remain required;
- names alone never authorize deletion.

Resource names may move from:

```text
openship-<...>
```

to:

```text
dockplane-<...>
```

Do not rename running containers, networks, volumes, or systemd units only for appearance. New resources use Dockplane names; historical resources retain their names until naturally replaced.

### 3.9 System services and process units

Potential new names:

```text
dockplane.service
dockplane-api.service
dockplane-worker.service
dockplane-<deployment>.service
```

Legacy units must be detected. Upgrade must not start both old and new control-plane services against the same database or ports.

Migration:

1. stop legacy control-plane unit;
2. verify no other active process owns the data directory;
3. install canonical unit;
4. preserve environment and restart policy;
5. start canonical unit;
6. verify readiness;
7. retain disabled legacy unit for rollback until operator removes it.

Historical application process units may remain until redeployment.

### 3.10 Container images and registries

Proposed canonical image pattern:

```text
ghcr.io/<cleared-org>/dockplane-api:<version>
ghcr.io/<cleared-org>/dockplane-dashboard:<version>
ghcr.io/<cleared-org>/dockplane-web:<version>
```

Migration requirements:

- publish immutable version tags and digests;
- keep legacy image aliases for the compatibility window;
- upgrade resolves by digest where practical;
- do not delete historical images needed for rollback;
- sign release images;
- update Compose examples to use released images rather than forcing source builds;
- retain a source-build path for contributors.

### 3.11 Database names and schemas

Possible current names include `openship` database names and internal columns.

Default decision:

- do not rename the production database in Dockplane 1.x;
- do not rename tables solely for branding;
- do not rewrite historical migration IDs;
- expose the Dockplane brand in UI and configuration while retaining safe internals;
- document that an internal legacy name is not evidence of incomplete migration.

A future major-version rename needs:

- tested dump/restore;
- connection-string migration;
- rollback;
- large-database time estimate;
- operator opt-in.

### 3.12 API

Keep:

```text
/api
```

Do not introduce `/dockplane/api` or change route paths for branding.

Response payloads should not rename stable entity fields solely for brand consistency. New API documentation uses Dockplane prose.

Headers or error codes containing OpenShip may gain canonical aliases, but old clients remain accepted through 1.x.

### 3.13 MCP

- Endpoint stays `POST /api/mcp`.
- Server display name becomes Dockplane.
- Example client key becomes `dockplane`.
- Tool names remain route-derived unless a separate API version changes them.
- OAuth issuer metadata uses the cleared Dockplane origin.
- Existing connected clients are migrated without silently widening consent.
- Consent text and audit actor labels use Dockplane.
- Legacy client names remain historical.

### 3.14 Exports and imports

Canonical filename:

```text
dockplane-export-2026-07-20T120000Z.json
```

Manifest additions:

```json
{
  "format": "dockplane-instance-export",
  "formatVersion": 1,
  "product": "Dockplane",
  "sourceProduct": "OpenShip",
  "sourceVersion": "0.2.1"
}
```

Rules:

- Dockplane imports old OpenShip exports;
- export parser uses format/version, not filename;
- unknown future versions fail before writes;
- import verifies passphrase before mutation;
- historical IDs and names remain intact;
- merge behavior is deterministic;
- migration report lists skipped/conflicting rows;
- secrets are re-encrypted under destination keys.

### 3.15 Logs and audit

New logs use Dockplane in current component names. Historical messages remain unchanged.

Do not rewrite audit events because:

- they describe what the system reported at the time;
- rewriting weakens evidentiary value;
- large rewrites add migration risk.

UI may annotate:

> “OpenShip was the previous product name.”

### 3.16 Domains, OAuth apps, and webhooks

Before public release:

- own final product domains;
- register Dockplane OAuth apps;
- register/update GitHub App;
- update callback URLs;
- rotate webhook secrets where required;
- support transition callbacks while old clients migrate;
- verify cookie and CORS topology;
- update certificate names;
- update transactional email SPF/DKIM/DMARC.

Do not assume redirects alone are sufficient for OAuth or webhook migration.

### 3.17 Desktop identities

Desktop rebrand includes:

- `productName`;
- app ID/bundle ID;
- executable name;
- icons;
- signing certificates;
- update feed;
- installer names;
- protocol handlers;
- data directory;
- window title;
- crash-report product.

Changing app ID may cause the OS to treat Dockplane as a new app. Decide deliberately whether to:

- retain the legacy app ID during 1.x for seamless upgrade; or
- ship a migration helper that transfers data and settings.

Code signing and update identity must be tested on each supported OS.

### 3.18 Email identities

Email module changes require care:

- product admin UI becomes Dockplane;
- mailbox domains are customer-owned and do not change;
- Postfix/Dovecot/iRedMail/Zero upstream names remain where technically accurate;
- sender display names and templates change only after domain authentication is configured;
- existing DKIM keys and mail domains must not be regenerated merely for brand;
- audit history remains historical.

---

## 4. Central implementation layer

Create a single shared brand/config module for values that truly must agree:

```ts
export const BRAND = {
  productName: "Dockplane",
  cliName: "dockplane",
  legacyCliName: "openship",
  envPrefix: "DOCKPLANE_",
  legacyEnvPrefix: "OPENSHIP_",
  dataDirName: ".dockplane",
  legacyDataDirName: ".openship",
  patPrefix: "dpl_pat_",
  legacyPatPrefix: "opsh_pat_",
  dockerLabelPrefix: "dockplane",
  legacyDockerLabelPrefix: "openship",
} as const;
```

Do not use the shared module to hide environment-specific URLs that belong in runtime configuration.

Add helpers for:

- canonical/legacy environment lookup;
- path detection and migration;
- PAT prefix recognition;
- Docker label dual recognition;
- deprecation messages;
- export manifest product/version;
- current and legacy service discovery.

---

## 5. Migration tests

Required automated cases:

1. New Dockplane install with no legacy data.
2. Legacy data directory only.
3. Canonical and legacy directories both populated.
4. Interrupted data migration.
5. Legacy PGlite lock active.
6. Legacy PostgreSQL-backed install.
7. Legacy CLI command in interactive mode.
8. Legacy CLI command with `--json`.
9. Canonical and legacy environment variables equal.
10. Canonical and legacy environment variables conflict.
11. Legacy PAT validation and revocation.
12. New PAT validation.
13. Legacy Docker labels discovered and cleaned safely.
14. Conflicting canonical and legacy labels.
15. Historical containers continue serving through control-plane rebrand.
16. Legacy export import with secrets.
17. Legacy export import without secrets.
18. Current export round trip.
19. Cookie migration on supported dashboard topologies.
20. Desktop data migration and rollback.
21. Old system service disabled before new service starts.
22. Upgrade from inspected OpenShip release to Dockplane release.
23. Rollback from Dockplane to the supported pre-migration state.
24. MCP connected-client consent remains scoped.
25. No self-host startup dependency on new cloud domains or credentials.

---

## 6. Rollout checklist

### Before announcement

- [ ] Trademark and name clearance complete.
- [ ] Domains owned.
- [ ] npm and container namespaces reserved.
- [ ] GitHub organization/repository plan approved.
- [ ] Desktop signing identity approved.
- [ ] OAuth and GitHub App transition plan tested.
- [ ] Brand constants merged.
- [ ] Legacy inventory complete.
- [ ] Migration tests passing.
- [ ] Security review complete.
- [ ] User migration guide published.
- [ ] Support team has rollback procedure.

### Dual-brand release

- [ ] Dockplane visible everywhere current-product text appears.
- [ ] `dockplane` command published.
- [ ] `openship` shim works.
- [ ] New env vars documented.
- [ ] Legacy env vars accepted.
- [ ] Data migration backs up first.
- [ ] Both PAT prefixes validate.
- [ ] Both label namespaces are recognized.
- [ ] Legacy exports import.
- [ ] Existing services keep running.
- [ ] Release notes state exact compatibility period.

### Default Dockplane release

- [ ] Docs use Dockplane commands by default.
- [ ] Legacy use warnings are non-breaking.
- [ ] Migration success metrics are reviewed.
- [ ] Known incompatibilities are public.
- [ ] No cleanup removes legacy-owned resources incorrectly.

### Future major removal

- [ ] Usage is low enough to justify removal.
- [ ] At least two stable minor releases carried warnings.
- [ ] Standalone migration checker exists.
- [ ] Export/import path remains.
- [ ] Major-version guide and rollback are tested.

---

## 7. Do not do this

Do not:

- run a global replacement of every `openship` string;
- rename the database during the visual rebrand;
- invalidate existing PATs without a security need;
- stop recognizing legacy Docker labels;
- rename running containers or volumes for cosmetics;
- start a second control-plane service against the same data;
- silently choose between two populated data directories;
- publish placeholder domains as if owned;
- move OAuth callbacks without a transition plan;
- widen cookie domains;
- rewrite audit history;
- remove legacy commands in a minor release;
- use the rebrand to introduce unrelated API breaking changes;
- claim migration success without testing a populated installation.

---

## 8. Completion definition

The rebrand is complete when a new user sees Dockplane everywhere, while an existing OpenShip user can upgrade without losing data, credentials, running workloads, domains, backups, permissions, automation, or a supported rollback path.

The presence of safe legacy identifiers inside the system is acceptable. Breaking an installation to achieve textual purity is not.
