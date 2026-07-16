---
title: "Fabric Workspace and Admin"
description: "Understand Fabric's two coordinated web surfaces, their routes, responsive behavior, profile scope, and current delivery status."
sidebar_position: 1
---

# Fabric Workspace and Admin

Fabric's web experience is organized as two coordinated surfaces on the same
local-first runtime:

- **Workspace** helps business users start conversations, follow agent work,
  inspect evidence, and understand outcomes.
- **Admin** helps technical and security operators configure integrations,
  channels, models, credentials, and the runtime itself.

This is an information-architecture boundary, not a second agent core. The
browser, Desktop, TUI, CLI, messaging gateway, and APIs continue to use the
same Fabric runtime and profile model.

## What is available now

The first delivery establishes the web experience without inventing backend
capabilities that Fabric cannot yet enforce:

- responsive Workspace/Admin navigation and canonical URLs;
- a command palette and profile-aware shell;
- a live Home view built from runtime status, conversations, and automations;
- a persistent three-panel Chat built around the real `fabric --tui`;
- a Design brief builder that drafts a structured prompt into a fresh Chat;
- a persistent SQLite-backed Work surface with Board, Graph, and Outline views;
- existing management pages regrouped under the new information architecture;
- lazy route loading, shared screen states, canonical Fabric Light/Dark
  themes, and the Fabric violet token family;
- compatibility aliases for existing dashboard bookmarks and plugin routes.

The following capabilities remain staged backend work:

- authoritative tenant, team-workspace, and site scopes;
- server-enforced capabilities and role-based navigation;
- a provider-neutral typed Memory ledger with provenance, versions, conflicts,
  retrieval history, and corrections;
- durable approval requests and decisions;
- a unified cursor-based activity and notification service.

Fabric labels unavailable data as empty, degraded, or read-only instead of
showing synthetic work, approval, memory, or activity counts.

## Workspace map

| Screen        | Canonical route            | Current behavior                                                                                                                      |
| ------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Home          | `/workspace/home`          | Live gateway, conversation, automation, and readiness projections. Each source can fail independently.                                |
| Chat          | `/workspace/chat`          | Live persistent TUI, conversation rail, agent activity, best-effort Task/Evidence/Artifacts projections, and profile Memory status.    |
| Design        | `/workspace/design`        | Live brief builder for artifact type, design system, and fidelity; starts the generated prompt in a fresh Chat.                        |
| Work          | `/workspace/work`          | Live persistent per-board SQLite work data with Board, Graph, and Outline projections, task details, dependencies, runs, and updates. |
| Conversations | `/workspace/conversations` | Live session search, inspection, rename, export, archive, resume, and cleanup.                                                        |
| Agents        | `/workspace/agents`        | Live machine-profile management. Profiles configure agent runtimes; they are not human identities.                                    |
| Memory        | `/workspace/memory`        | Capability-aware placeholder until the selected provider exposes the typed ledger contract. Provider controls remain in Admin/System. |
| Knowledge     | `/workspace/knowledge`     | Live profile-scoped file and knowledge surface.                                                                                       |
| Automations   | `/workspace/automations`   | Live scheduled-job creation, editing, triggering, pausing, and run history.                                                           |
| Approvals     | `/workspace/approvals`     | Honest empty state until durable approval requests exist. Ephemeral tool prompts are not presented as a queue.                        |
| Activity      | `/workspace/activity`      | Read-only transition state until task, approval, automation, and agent events share one projection.                                   |
| Insights      | `/workspace/insights`      | Live session-derived token, cache, cost, and model usage views.                                                                       |

## Admin map

| Area                | Canonical route                   | Current behavior                                                                        |
| ------------------- | --------------------------------- | --------------------------------------------------------------------------------------- |
| Integrations        | `/admin/integrations`             | Plugin inventory, provider assignment, runtime state, and plugin actions.               |
| Skills              | `/admin/integrations/skills`      | Installed skills, toolsets, and skill-hub management.                                   |
| MCP                 | `/admin/integrations/mcp`         | MCP server configuration, testing, catalog install, and enablement.                     |
| Channels and Events | `/admin/channels-events`          | Messaging-channel configuration and connection state.                                   |
| Webhooks            | `/admin/channels-events/webhooks` | Event subscriptions, targets, enablement, and one-time secrets.                         |
| AI Runtime          | `/admin/ai-runtime/models`        | Model routes, providers, local inference, and runtime selection.                        |
| Security and Access | `/admin/security-access`          | Messaging pairing and revocation. Enterprise members and roles are not implemented yet. |
| Secrets             | `/admin/security-access/secrets`  | Profile-scoped API keys and credentials.                                                |
| System              | `/admin/system`                   | Host, gateway, memory-provider, credential-pool, update, and maintenance controls.      |
| Advanced            | `/admin/advanced`                 | Schema-driven `config.yaml` editor.                                                     |
| Logs                | `/admin/advanced/logs`            | Agent, gateway, and error logs with filters and live refresh.                           |
| Help                | `/admin/help`                     | In-product documentation links and support entry points.                                |

The main navigation shows the top-level entries. Related pages such as Skills,
MCP, Webhooks, Secrets, and Logs are reached from their parent area or the
command palette.

## Chat is one experience, not a React rewrite

Browser Chat keeps the real terminal experience in the center. Fabric does not
reimplement the transcript, composer, slash commands, or approval prompts as a
second React chat surface.

```text
Wide screens (1440px and above)
┌──────────────────┬──────────────────────────────┬──────────────────────┐
│ Conversations    │ Persistent fabric --tui      │ Agent + context      │
│ search + recent  │ transcript + composer        │ task / evidence /    │
│ sessions         │                              │ memory / artifacts   │
└──────────────────┴──────────────────────────────┴──────────────────────┘
```

- At **1440px and above**, both supporting rails are visible.
- From **1024px to 1439px**, one user-selected supporting rail is visible.
- Below **1024px**, Chat is center-first and Conversations or Context opens in
  an accessible sheet.

The PTY/xterm instance stays mounted while you navigate, so a live terminal is
not restarted merely because another page opened. Supporting rails load only
when visible and fail independently; an event-feed or Memory-status error does
not take down the terminal.

The Task, Evidence, and Artifacts tabs project the existing PTY semantic event
stream into a bounded, session-scoped read model. Task shows the live session
identity and any structured checklist; Evidence shows recent tool lifecycle
events; Artifacts detects file, image, and export paths reported by tools. The
Memory tab independently reads the selected profile's provider selection,
readiness state, and built-in `MEMORY.md` / `USER.md` sizes. It does not invent
retrieval excerpts or provenance that the terminal session did not report.

These projections are deliberately best-effort. Losing the event subscriber or
Memory status request degrades only the rail; the TUI remains usable. They add
no model tool, do not mutate the prompt, and do not trigger an extra inference
request, so they do not change model speed or prompt-cache behavior.

The Work card in the same rail is an explicit bridge, not automatic coupling.
It shows selected-board counts and links, while **Track chat in Work** creates
one idempotent Triage task linked to the current TUI session. Chats remain
transient until the user chooses that action, and tracking writes directly to
SQLite without invoking the model.

## Work is durable and multi-view

`/workspace/work` is the bundled `kanban` dashboard integration, backed by the
same per-board SQLite databases used by `fabric kanban`, `/kanban`, and the
task-scoped `kanban_*` tools. The default board lives at
`~/.fabric/kanban.db`; named boards live under
`~/.fabric/kanban/boards/<slug>/kanban.db`.

- **Board** is the operational status view: Triage, Todo, Scheduled, Ready,
  In Progress, Blocked, Review, and Done, with Archived available on demand.
- **Graph** projects goals, dependency edges, active agent runs, and results.
- **Outline** presents the same graph as an accessible linear hierarchy.

The selected board, view, and task are reflected in the URL, so links such as
`/workspace/work?board=default&view=graph&task=t_abcd` are shareable. The
legacy `/work` and `/kanban` paths resolve to the same surface.

## Team Pages is a separate reference integration

The bundled `team-pages` dashboard integration provides optional,
config-driven static reference pages for shared links, priorities, metrics,
and status. It is intentionally hidden from primary navigation and loads only
when its direct route, `/admin/integrations/team-pages`, is opened. It does not
create agent profiles, people, tasks, or work-board data.

`/team` is therefore an alias for **Agents**, not Team Pages. Agents manages
machine profiles; Work manages durable tasks and runs; Team Pages renders
operator-authored reference blocks. Keeping those concepts separate avoids
presenting configuration as live team state.

## Profiles are not enterprise scopes

A Fabric **profile** is an independent agent configuration and memory island.
It can have its own model route, credentials, skills, memory, sessions, and
`FABRIC_HOME`. Switching profiles changes which agent runtime the dashboard
reads or controls.

A profile is not:

- a tenant or billing boundary;
- a team workspace;
- a site or deployment boundary;
- a person, role, or permission bundle.

The Phase 1 shell reports a loopback dashboard as local access and treats it as
the operator-owned surface. It does not yet resolve an authoritative
`local-owner` actor record. A non-loopback dashboard uses the documented
authentication gate. Authentication does not by itself provide enterprise
resource authorization; authoritative memberships, capabilities, and resource
isolation remain a later backend delivery.

## Route compatibility

Existing bookmarks continue to work. Fabric preserves the query string and
hash when it resolves a legacy route.

| Legacy route                  | Canonical route              |
| ----------------------------- | ---------------------------- |
| `/`                           | `/workspace/home`            |
| `/chat`                       | `/workspace/chat`            |
| `/design`                     | `/workspace/design`          |
| `/work`, `/kanban`            | `/workspace/work`            |
| `/sessions`                   | `/workspace/conversations`   |
| `/cron`                       | `/workspace/automations`     |
| `/analytics`                  | `/workspace/insights`        |
| `/profiles`, `/team`          | `/workspace/agents`          |
| `/files`                      | `/workspace/knowledge`       |
| `/models`                     | `/admin/ai-runtime/models`   |
| `/skills`, `/plugins`, `/mcp` | `/admin/integrations/...`    |
| `/channels`, `/webhooks`      | `/admin/channels-events/...` |
| `/pairing`, `/env`            | `/admin/security-access/...` |
| `/system`                     | `/admin/system`              |
| `/config`, `/logs`            | `/admin/advanced/...`        |
| `/docs`                       | `/admin/help`                |

## States and themes

New route shells share vocabulary for normal, loading, empty,
filtered-empty, degraded, offline, permission-denied, read-only, in-progress,
success, failure, conflict, and destructive-confirmation states. Existing live
screens adopt these states as their data contracts are updated.

Fabric Light and Fabric Dark are the canonical generated themes. Both use
neutral woven surfaces and one restrained action color derived from the Fabric
primary `#4628CC`; status colors retain their semantic meaning. Compact and
comfortable density, high contrast, and optional expressive themes remain
available through the theme controls.

For startup flags, dependencies, authentication, APIs, remote operation, and
theme/plugin extension, continue to the [Web Dashboard guide](/user-guide/features/web-dashboard).
