# Loom — implemented MVP

This document describes what actually shipped in the first Loom feature release,
how to use it, and how it maps to the phased plan in
[`INTEGRATION_PLAN.md`](./INTEGRATION_PLAN.md).

**Loom** is Fabric's native deployment plane. Rather than bolt on the
TypeScript/Bun Dockplane/OpenShip codebase as a second runtime, Loom implements
the same product concepts — from
[`source-spec/`](./source-spec/) — directly in Python, so one code path serves
the CLI, the dashboard, the desktop app, and Fabric agents.

> Working name. "Loom" is a working brand pending trademark/namespace/domain
> clearance (see the rebrand discipline in
> [`source-spec/REBRAND_MAP.md`](./source-spec/REBRAND_MAP.md)).

## What it does

Loom takes a source (a Docker Compose project, a folder, or the built-in
"host Fabric itself" template) and runs it on a destination you choose — **this
machine** or **a Linux host over SSH** — following the non-negotiable rules from
the spec:

- **Plan before mutation.** Every deploy produces an explicit plan you confirm
  before anything is changed.
- **One source of truth.** The CLI, dashboard API, and agent tools all call one
  service (`LoomService`); none writes state directly.
- **Fail closed.** A candidate that fails to build, start, or pass its health
  check never displaces the currently healthy release.
- **Recoverable.** Every release is retained; rollback is a new, audited
  operation, not a silent mutation of history.
- **Least-privilege agents.** The agent tool gates `deploy`/`rollback` behind
  human approval and fails closed when non-interactive.

## Architecture

```
CLI  ─┐
API  ─┼─ LoomService ── LoomStore (SQLite: $FABRIC_HOME/loom.db)
tools ┘        │
               └── RuntimeDriver ── LocalDriver (subprocess docker compose)
                                 └── SshDriver  (tools/environments/ssh.py)
```

| Layer | Module | Responsibility |
|---|---|---|
| Brand | `fabric_cli/loom/brand.py` | Central `LOOM_` env prefix, `loom.db`, label namespace |
| Models | `fabric_cli/loom/models.py` | `Host`/`Project`/`Deployment` + deployment & host state machines |
| Store | `fabric_cli/loom/store.py` | Per-profile SQLite (WAL, additive schema) |
| Drivers | `fabric_cli/loom/drivers.py` | `LocalDriver`, `SshDriver` (reuses Fabric's SSH env) |
| Service | `fabric_cli/loom/service.py` | Orchestration: scan, plan, apply, supersede, rollback |
| CLI | `fabric_cli/subcommands/loom.py`, `fabric_cli/loom/cli.py` | `fabric loom …` |
| API | `fabric_cli/web_server.py` | `/api/loom/*` REST endpoints |
| Tools | `tools/loom_tool.py` | The agent-facing `loom` tool (opt-in `loom` toolset) |
| UI | `web/src/pages/DeployPage.tsx` | The non-technical "Deploy" dashboard page |

### Deployment state machine

```
planned -> building -> starting -> health_checking -> active
                 \          \             \
                  -> failed  -> failed     -> failed        (previous release kept)
active -> superseded | rolled_back  ->(rollback)-> active
```

## Using it

### From the CLI

```bash
fabric loom setup                      # registers "this-machine" and prints next steps
fabric loom host add box --kind ssh --address 1.2.3.4 --user root --key ~/.ssh/id_ed25519
fabric loom host scan box              # read-only adoption scan (OS/arch/docker)
fabric loom project add site --kind compose --source /srv/site --compose-file docker-compose.yml
fabric loom deploy site this-machine   # shows the plan, asks to confirm, then deploys
fabric loom status                     # hosts / projects / active deployments
fabric loom rollback site this-machine # reactivate the previous release
fabric loom logs <deployment-id>
```

`deploy` shows the plan and prompts before mutating; pass `--yes` for
non-interactive use and `--allow-destructive` to approve destructive steps.

### From the dashboard / desktop

Open the dashboard (`fabric dashboard`) and go to **Deploy** (admin surface).
The page walks a non-technical user through: pick where to run it → pick what to
deploy → review the plan → deploy, with live status and logs. The desktop app
serves the same page from the same backend.

### From a Fabric agent

Enable the `loom` toolset (`fabric tools`). Agents then get one `loom` tool with
actions `status | hosts | projects | deployments | plan | deploy | rollback |
logs`. `deploy` and `rollback` require human approval before running.

### Over REST

`GET/POST /api/loom/*` — see [`INTEGRATION_PLAN.md`](./INTEGRATION_PLAN.md) and
the endpoint list in `fabric_cli/web_server.py`. Mutating routes require the
dashboard session token.

## Mapping to the plan

| Plan phase | Status |
|---|---|
| **Phase 0** — gate macOS/Windows CI legs off every PR | **Done** (`release-channels`, `mobile`, `desktop-packaging`) |
| **Phase 1** — a deploy plane on owned infra (local + SSH), plan/apply/rollback | **MVP done** (Python-native, Option C) |
| **Phase 2** — agent-operable + dashboard/desktop fusion | **MVP done**: agent `loom` tool + Deploy dashboard page |

## Deliberately out of MVP scope

Faithful to the spec's "reliable core, honest beta" boundary, these are **not**
in this release and should be labelled beta/planned when added: managed cloud,
DNS-provider automation and wildcard certs, cloud provider API drivers
(Hetzner/DO create-box), backup/restore engine, preview environments, multi-node
scheduling, per-tenant RBAC/metering, and the OpenShip data-migration importer.
Real Docker/SSH execution runs when a host is configured; the test suite uses a
fake driver so no Docker/SSH is required in CI.

## Tests

- `tests/loom/` — state machine, store round-trips, and service plan/apply/
  rollback/scan (fake driver).
- `tests/fabric_cli/test_loom_parser_builder.py`, `test_loom_cli.py` — CLI.
- `tests/tools/test_loom_tool.py` — agent tool + approval gating.
- `tests/fabric_cli/test_web_server_loom.py` — REST endpoints.
- `web/src/pages/DeployPage.test.tsx` — dashboard page.
