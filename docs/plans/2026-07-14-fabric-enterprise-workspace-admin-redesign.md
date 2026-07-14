# FDS-001: Fabric Enterprise Workspace and Admin Redesign

> **Status:** Phase 1 implemented — enterprise backend contracts deferred
> **Author:** Codex with parallel Fabric audits
> **Date:** 2026-07-14
> **Branch:** main
> **Decision:** Use the Rabot design language, the supplied Fabric wordmark, a persistent TUI-backed browser Chat, and a real scope/capability contract.

## Problem

Fabric has capable but separately evolved dashboard, desktop, TUI, CLI, plugin, and documentation surfaces. The dashboard exposes implementation-shaped pages such as Sessions, Cron, Models, Config, and Logs; it does not yet present the durable multi-agent work model, role-aware Workspace/Admin split, enterprise memory ledger, or complete state coverage requested for a white-label operations platform. The current brand contract also enforces Fabric blue even though the supplied Rabot system and new Fabric mark establish purple as the primary family.

## Solution

Create two coordinated experiences—Fabric Workspace for operators and Fabric Admin for technical/security administrators—on a shared static token and brand foundation. Preserve the dashboard's embedded `fabric --tui` as the browser Chat transcript/composer, place independently-failing React conversation and context rails around it, introduce a lazy route catalog with legacy aliases, and build enterprise scope/RBAC as enforced backend contracts rather than client-only navigation.

The product object model is:

```text
Conversation
  -> durable Work item
  -> plan and named agent runs
  -> dependencies, handoffs, retries, evidence, artifacts
  -> approval decision
  -> outcome, activity, and versioned memory
```

## Delivery Status

| Delivery | Status | What it means |
|---|---|---|
| Static Rabot tokens and Fabric brand assets | Shipped in Phase 1 | Canonical `#4628CC`, generated Light/Dark foundations, responsive marks, and static cross-surface artifacts are available. System sans remains the runtime default while Inter provenance is unresolved. |
| Workspace/Admin route catalog and shell | Shipped in Phase 1 | Canonical lazy routes, navigation order, command-palette entries, responsive shell behavior, legacy aliases, and machine-profile controls are implemented. |
| Home and responsive three-panel Chat | Shipped in Phase 1 | Home uses real independently-settled projections. Chat retains one persistent TUI/PTy and rearranges conversations/context at the documented breakpoints. |
| Existing product capabilities under the new IA | Shipped in Phase 1 | Conversations, Agents/profiles, Knowledge, Automations, Insights, Integrations, Channels and Events, AI Runtime, Security and Access, System, Advanced, and Help map to existing live pages. |
| Work Board, typed Memory, Approvals, and Activity route states | Shipped as honest contracts | Routes and shared empty/degraded/read-only states exist; they do not fabricate durable services that the backend cannot return. |
| Tenant/workspace/site model and capability enforcement | Deferred to Phase 2 | No enterprise-tenancy or RBAC claim is made until authoritative actor context, server guards, migrations, and isolation tests ship. |
| Durable work, approvals, activity/notifications, and versioned Memory services | Deferred to Phase 2 | Steps 7–9 remain the backend delivery plan. Plugin-provided work can be linked through the generic extension contract today. |

Phase 1 is a complete, usable product foundation, not completion of the hosted
enterprise control plane. Navigation grouping is presentational until the same
capability contract authorizes every corresponding backend resource.

## Acceptance Criteria

- [x] When Fabric loads at `/`, the user lands on `/workspace/home`; legacy paths continue to resolve with query strings and hashes intact.
- [x] Workspace navigation exposes Home, Chat, Work Board, Conversations, Agents, Memory, Knowledge, Automations, Approvals, Activity, and Insights in that order.
- [x] Admin navigation exposes Integrations, Channels & Events, AI Runtime, Security & Access, System, Advanced, and Help from the same route catalog.
- [ ] Role/capability filtering is driven by the same server-enforced contract as route authorization. **Deferred to Phase 2; Phase 1 does not treat hidden navigation as security.**
- [x] Browser Chat retains one persistent PTY/xterm instance while navigation changes, with conversations on the left, the TUI in the center, and task/evidence/memory/artifact context on the right.
- [x] At widths below 1024px, Chat is center-first and secondary panels open as accessible sheets; at 1024–1439px one secondary panel is visible; at 1440px and above all three panels may be visible.
- [x] The initial web entry chunk does not statically import xterm, Observable Plot, QRCode, or route-page implementations.
- [x] Light, dark, high-contrast-compatible, compact, and comfortable modes use the Rabot token family with `#4628CC` as canonical primary and system sans for Phase 1; monospace remains limited to technical values and terminal content. Inter remains pending license/provenance.
- [x] The supplied Fabric wordmark is represented by a canonical full lockup and a simplified lowercase `f` mark for compact, maskable, native, and monochrome contexts; the bracket underline appears only in the full lockup.
- [x] Existing user-owned PWA work under `web/public/icons/`, `web/public/manifest.webmanifest`, `web/src/lib/pwa-manifest.test.ts`, and `website/docs/getting-started/mobile.md` is preserved.
- [x] Each new route shell uses the shared state contract for normal, loading, empty, filtered-empty, degraded, offline, permission-denied, read-only, in-progress, success, failure, conflict, and destructive-confirmation states.
- [x] Machine agent profiles remain independent configuration/memory islands and are never relabeled as tenant, workspace, site, or human-role scope.
- [ ] Local installs resolve to an authoritative local-owner `ActorContext`; hosted installs do not expose tenant/workspace/site choices until the backend returns authoritative memberships. **Deferred to Phase 2; Phase 1 reports verified local/auth mode only.**
- [x] No new core model tools or mutable per-turn system-prompt content are introduced.
- [ ] No regressions occur in plugin route overrides, legacy plugin nav anchors, the embedded TUI, desktop Chat, profile selection, or auth redirect handling.
- [ ] Tests pass: `npm test --workspace web`, `npm run typecheck --workspace web`, relevant desktop/TUI tests, and focused Python authorization/brand tests.
- [ ] Lint and production builds pass for every changed workspace.

## Constraints

- Do NOT reimplement the browser transcript, composer, slash commands, or terminal in React. Extend `ui-tui` for primary Chat behavior and use React only for supporting rails.
- Do NOT unmount the embedded Chat PTY when navigating away; its process, WebSocket, and xterm state must survive.
- Do NOT rename machine profiles to workspaces. `fabric_cli/profiles.py` intentionally isolates profile homes, configuration, skills, and memory.
- Do NOT use the Kanban `tenant` string as an authorization boundary; it is currently a filter/tag.
- Do NOT rely on hidden navigation for security. Every protected read, mutation, export, delete, attachment, and WebSocket path needs server-side capability and scope enforcement.
- Do NOT add behavioral `HERMES_*` or `FABRIC_*` environment variables. Rollout and behavior settings belong in `config.yaml`; `.env` remains credentials-only.
- Do NOT add a core model tool for Workspace/Admin UI capabilities.
- Do NOT mutate historical conversation messages or rebuild the system prompt when memory is corrected. Active prompt bytes remain stable for the agent lifetime.
- Do NOT add a runtime-heavy design-system dependency. Generated tokens and brand artifacts must be static and tree-shakable.
- Do NOT add Google-hosted fonts. A self-hosted Inter asset may ship only with confirmed provenance and its license; otherwise use the existing system stack until that condition is met.
- Do NOT change public plugin route behavior without compatibility aliases for `/chat`, `/sessions`, `/cron`, and other current paths and anchors.
- Do NOT special-case the Kanban plugin in core routing. Extend the generic plugin tab contract when a plugin needs aliases/surface/section metadata.
- Do NOT edit or replace unrelated dirty-worktree files.
- Must work in loopback dashboard, authenticated dashboard, headless `fabric serve`, Electron desktop, TUI, CLI, macOS, Windows, and Linux wherever those surfaces already run.
- Web supporting rails must fail non-destructively so a sidecar/API failure never breaks the PTY.

## Runtime Modes

| Mode | Behavior | Availability and guard notes |
|---|---|---|
| Dashboard, loopback | Full Workspace/Admin UI with ephemeral header token | Resolve an explicit `local-owner` actor with full local capabilities. Never infer hosted multi-tenant membership. |
| Dashboard, authenticated | Full UI filtered by verified capabilities and selected authoritative scope | Cookie session and service-token routes use the same `ActorContext`; client filtering is presentational only. |
| `fabric serve` headless | JSON-RPC, WS, and API only; no SPA is mounted | Brand/route code is absent. Scope and authorization checks still apply to every backend transport. |
| Electron desktop | Separate React Chat surface plus shared tokens and domain contracts | Desktop must not depend on the dashboard frontend and must tolerate backend startup/restart. |
| Dashboard Chat hidden | Persistent Chat host remains mounted with `display:none` | No new socket/process is created on each navigation. Expensive context polling pauses while hidden. |
| Narrow/mobile web | Center-first Chat; rails are separate modal sheets | Focus is trapped in the open sheet, Escape closes, and the terminal remains mounted beneath it. |
| TUI | Existing Ink experience with generated terminal-safe color aliases | No browser-only shell code or SVG runtime dependency. |
| Classic CLI / gateway | Existing prompt-toolkit/Rich and messaging adapters | Only terminal-safe brand values change; command and prompt caching behavior is unchanged. |
| Offline/degraded | Cached shell remains usable; unavailable data surfaces explicit state | Chat terminal failure and supporting-rail failure remain independently recoverable. |

For each WebSocket or message target, send only when the existing transport reports the target open/alive. A destroyed Electron window, hidden dashboard Chat, or absent SPA in headless mode must not cause retries that spawn duplicate processes.

## Pre-implementation Technical Context

The references below record the baseline used to design Phase 1. The canonical
current web route source is now `web/src/app/routes.tsx`; delivery status above
takes precedence where the baseline and implemented tree differ.

### Routing and Chat baseline before Phase 1

1. `web/src/App.tsx:83-103` defines built-in routes, while `web/src/components/sidebar/nav-model.ts:52-120` separately defines navigation and section mapping. `web/src/lib/resolve-page-title.ts:3` is a third routing-derived table, so a namespace migration can drift.
2. `web/src/App.tsx:71-79` documents the persistent Chat invariant. The host at `web/src/App.tsx:446-472` is rendered outside `<Routes>` and hidden instead of unmounted.
3. `web/src/pages/ChatPage.tsx:577-593` uses WebGL only on wide hosts and falls back on narrow screens.
4. `web/src/pages/ChatPage.tsx:1101-1188` renders the terminal and one right rail containing both `ChatSidebar` and `ChatSessionList`. Presentation can be rearranged without touching the PTY lifecycle.
5. `web/src/components/ChatSidebar.tsx:136` throttles high-frequency event rendering. That throttle remains in force.

### Theme and brand baseline before Phase 1

1. At the planning baseline, `web/src/themes/generated.ts:24-40` defined the generated theme inputs with `#0053fd` as the accent. Phase 1 replaces it with the canonical `#4628CC`.
2. `web/src/themes/generate.ts:312-413` derives accessible accent, text, status, and border pairs using OKLCH and contrast constraints. This generator is retained.
3. `web/src/themes/generate.ts:428-437` emits typography, radius, and density; the current UI stack is system sans.
4. `web/src/index.css:57-113` supplies pre-hydration theme fallbacks and work-rail tokens.
5. `scripts/fabric-brand-audit.py:394` currently enforces the old blue and must be changed with the canonical token, not bypassed.
6. The Rabot ZIP provides `primary.600 = #4628CC`, Inter faces, a 4px spacing grid, 4/8/12/16px radii, semantic status colors, light components, and static page examples. It is a source of design intent, not a runtime package to copy wholesale.

### Auth and scope baseline before Phase 1

1. `fabric_cli/dashboard_auth/base.py:9-25` stores verified identity and `org_id` but no human roles or workspace/site memberships.
2. `fabric_cli/dashboard_auth/base.py:28-53` gives service tokens optional scopes, but current request routing does not consistently enforce them.
3. `fabric_cli/dashboard_auth/routes.py:592-605` returns identity from `/api/auth/me` without roles/capabilities.
4. `web/src/lib/api.ts:58-109` applies machine-profile scope to selected endpoint families. This is configuration targeting, not enterprise tenancy.
5. `web/src/lib/api.ts:133-196` distinguishes session expiry from domain 401s and handles loopback token rotation. This behavior must be preserved.
6. `web/src/lib/api.ts:1525-1532` mirrors the current identity payload.
7. `fabric_cli/dashboard_auth/middleware.py:255` attaches a session; `fabric_cli/web_server.py:644` broadly gates APIs by authentication. Resource authorization remains future backend work, not a client assumption.

### Durable work and memory baseline before Phase 1

1. `fabric_cli/kanban_db.py:1094` and the Kanban dashboard plugin already represent tasks, runs, dependencies, retries, attachments, events, and warnings. Its `tenant` field remains a tag until migrated to indexed scope columns.
2. `fabric_state.py:808` sessions do not yet carry tenant/workspace/site ownership. Existing messaging `user_id` must not be reinterpreted as dashboard ownership.
3. `agent/memory_provider.py:112` declares provider capabilities but does not provide a universal facts/episodes/procedures/policies/version/conflict ledger.
4. `agent/system_prompt.py:514` caches the system prompt for the agent lifetime; corrections must create versions and reconcile asynchronously rather than mutate an active prompt.

### Key files

| File | Role |
|---|---|
| `web/src/App.tsx:71-111` | Persistent Chat route contract and current route table. |
| `web/src/App.tsx:237-283` | Plugin loading/override window and computed route/nav model. |
| `web/src/App.tsx:446-472` | Persistent Chat host that must never remount on navigation. |
| `web/src/components/sidebar/nav-model.ts:33-120` | Current separate nav and section model. |
| `web/src/components/sidebar/AppSidebar.tsx:87-175` | Brand, profile switcher, and grouped navigation shell. |
| `web/src/pages/ChatPage.tsx:988-1192` | Current terminal and supporting-rail layout. |
| `web/src/contexts/ProfileProvider.tsx:12-35` | Machine-profile selection contract. |
| `web/src/themes/generated.ts:20-40` | Canonical generated theme inputs. |
| `web/src/themes/generate.ts:312-439` | Existing accessible theme derivation and density/radius output. |
| `web/src/index.css:57-113` | Pre-hydration theme/token fallbacks. |
| `apps/desktop/src/styles.css:124-165` | Current desktop primary and UI accent aliases. |
| `apps/desktop/src/styles.css:317-319` | Desktop UI sans stack. |
| `apps/desktop/src/components/brand-mark.tsx:1` | Desktop compact brand component. |
| `ui-tui/src/theme.ts:254` | Existing TUI Rabot-purple-compatible theme path. |
| `fabric_cli/dashboard_auth/base.py:9-53` | Human session and service-token principal contracts. |
| `fabric_cli/dashboard_auth/routes.py:592-605` | Current SPA identity bootstrap endpoint. |
| `web/src/lib/api.ts:58-109` | Agent-profile request targeting. |
| `fabric_cli/profiles.py:4` | Profile independence intent. |
| `fabric_cli/kanban_db.py:1094` | Existing durable task primitives. |
| `agent/memory_provider.py:112` | Existing provider capability abstraction. |
| `agent/system_prompt.py:514` | Active prompt-cache invariant. |
| `scripts/fabric-brand-audit.py:394` | CI brand-primary assertion. |

### Route and navigation model

Canonical route definitions are table-driven:

```ts
export interface AppRouteDef {
  id: string;
  path: string;
  aliases: readonly string[];
  surface: "workspace" | "admin";
  section: string;
  layout: "page" | "workspace";
  requiredCapability?: Capability;
  nav?: {
    label: string;
    icon: ComponentType<{ className?: string }>;
    end?: boolean;
  };
  component: LazyExoticComponent<ComponentType>;
}
```

| Legacy path | Canonical path |
|---|---|
| `/` | `/workspace/home` |
| `/chat` | `/workspace/chat` |
| `/sessions` | `/workspace/conversations` |
| `/cron` | `/workspace/automations` |
| `/analytics` | `/workspace/insights` |
| `/profiles`, `/profiles/new` | `/workspace/agents`, `/workspace/agents/new` |
| `/files` | `/workspace/knowledge` |
| `/models` | `/admin/ai-runtime/models` |
| `/skills`, `/plugins`, `/mcp` | `/admin/integrations/skills`, `/admin/integrations/plugins`, `/admin/integrations/mcp` |
| `/channels`, `/webhooks` | `/admin/channels-events/channels`, `/admin/channels-events/webhooks` |
| `/pairing`, `/env` | `/admin/security-access/pairing`, `/admin/security-access/credentials` |
| `/system` | `/admin/system` |
| `/config`, `/logs` | `/admin/advanced/config`, `/admin/advanced/logs` |
| `/docs` | `/admin/help` |

Alias redirects use the current location:

```tsx
function LegacyRouteRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search}${location.hash}`} replace />;
}
```

Plugin overrides match canonical paths or aliases, and plugin position anchors normalize both old and new route IDs. `/chat?resume=...`, `/chat?learn=...`, `?profile=...`, and the PWA's existing `./chat` start URL remain valid.

### Enterprise access model

These nouns remain distinct:

```text
Tenant       security, billing, brand boundary
Workspace    team operations boundary
Site         optional physical/deployment boundary
Profile      independent agent config/memory island
Principal    human or service identity
Membership   principal + scope + role + capabilities
Binding      workspace/site -> allowed agent profiles
```

The authoritative request projection is:

```python
@dataclass(frozen=True)
class ActorContext:
    principal_id: str
    provider: str
    tenant_id: str
    workspace_id: str
    site_id: str | None
    roles: tuple[str, ...]
    capabilities: frozenset[str]
    membership_version: int
    auth_scheme: str
```

The client consumes one bootstrap response:

```ts
export interface ExperienceBootstrap {
  actor: {
    principalId: string;
    provider: string;
    roles: readonly string[];
    capabilities: readonly Capability[];
  };
  selection: ScopeSelection;
  availableScopes: readonly ScopeOption[];
  machineProfile: string;
  unreadNotifications: number;
}
```

Local mode returns one synthetic tenant, personal workspace, this-device site, and `local-owner` principal. Hosted mode returns only memberships verified by the backend. No arbitrary client-supplied scope becomes trusted.

### Shared screen-state model

```ts
export type ScreenStateKind =
  | "normal"
  | "loading"
  | "empty"
  | "filtered-empty"
  | "degraded"
  | "offline"
  | "permission-denied"
  | "read-only"
  | "in-progress"
  | "success"
  | "failure"
  | "conflict"
  | "destructive-confirmation";

export interface ScreenStateCopy {
  kind: ScreenStateKind;
  title: string;
  description: string;
  primaryAction?: { label: string; action: string };
  secondaryAction?: { label: string; action: string };
}
```

Every route declares supported states; reusable state surfaces provide consistent iconography, tone, actions, ARIA semantics, retry behavior, and destructive confirmation.

## Design Contracts

### 3a. Lifecycle Matrix

#### Persistent browser Chat resources

| Transition | Owned state | What must happen |
|---|---|---|
| Off → On | PTY child, PTY WebSocket, xterm, fit/unicode/link/render addons | Create once on the first Chat visit, attach listeners, fit, and send initial dimensions. |
| On → Off | Same resources | Only destroy on app teardown, explicit session restart, profile change that requires a new process, or terminal end; ordinary route navigation only hides the host. |
| On → On (profile/channel/session config changed) | Connection URL and PTY child | Run the existing controlled restart path: close the old socket/process, dispose terminal listeners/addons, then create exactly one replacement with the new parameters. |
| On → On (config unchanged) | Same resources | Reuse; do not create another socket, sidecar, slash worker, terminal, or event subscription. |

#### Supporting Chat rail requests

| Transition | Owned state | What must happen |
|---|---|---|
| Off → On | Active rail tab, `AbortController`, response cache | Fetch only the active visible rail for the selected session. |
| On → Off | In-flight request/subscription | Abort or unsubscribe; retain a bounded last-good projection for degraded rendering. |
| On → On (session/tab/scope changed) | Request key and controller | Abort stale work, derive a new key, and fetch the new projection. Never paint a prior session's evidence into the new session. |
| On → On (config unchanged) | Cached projection | Reuse without another request. |

#### Scope selection

| Transition | Owned state | What must happen |
|---|---|---|
| Off → On | Verified bootstrap and selected scope | Load one authoritative bootstrap; validate persisted selection against returned memberships. |
| On → Off | Scope state | Clear in-memory sensitive projections on logout/session expiry. |
| On → On (membership version or selected scope changed) | Actor cache and resource queries | Invalidate old scoped caches, re-resolve server context, abort stale requests, and navigate to the nearest permitted route if necessary. |
| On → On (config unchanged) | Actor cache | Reuse cached membership projection; no repeated bootstrap per component. |

#### Theme and density

| Transition | Owned state | What must happen |
|---|---|---|
| Off → On | CSS variables and persisted preference | Apply pre-hydration defaults, then the stored/OS-selected light/dark theme and density. |
| On → Off | N/A | Theme remains document-owned for app lifetime; remove only test-owned listeners during teardown. |
| On → On (theme/density/tenant brand changed) | Generated CSS variable set | Atomically apply the newly derived variable map and update native theme metadata. |
| On → On (config unchanged) | CSS variable set | Reuse; do not rerun generation or trigger layout work. |

### 3b. Parameter Contracts

| Method | Scoping parameter | Collection/query iterated | Filter applied |
|---|---|---|---|
| `resolveActorContext(principal, requestedScope)` | `requestedScope` | Verified memberships for `principal` | Exact tenant/workspace/site membership match; otherwise reject before resource lookup. |
| `hasCapability(actor, capability)` | `actor` | `actor.capabilities` | Exact capability or documented wildcard expansion computed by the server. |
| `routesForActor(routes, actor)` | `requiredCapability` | Route catalog | Include when absent or `hasCapability(actor, requiredCapability)`; presentation only. |
| `listConversations(actor, cursor)` | `actor` | Scoped conversation index | `tenant_id`, `workspace_id`, optional `site_id`, then cursor predicate. Never profile fan-out first. |
| `loadWorkBoard(actor, boardId)` | `actor`, `boardId` | Scoped board registry | Board scope must equal actor selection before task query. Legacy `tenant` tag is not checked for auth. |
| `listActivity(actor, cursor)` | `actor` | Activity store | Compound scope columns plus stable `(created_at, id)` cursor. |
| `listNotifications(actor, unreadOnly)` | `actor.principal_id` | Notification projection | Exact principal and actor scope; unread predicate when requested. |
| `loadMemoryRecord(actor, recordId)` | `actor`, `recordId` | Typed memory ledger | Exact scope and `memory.read`; provenance visibility is filtered server-side. |
| `decideApproval(actor, approvalId, version)` | `actor`, `approvalId`, `version` | Durable approval record | Exact scope, `approval.decide`, eligible approver policy, and matching optimistic version. |
| `fetchRail(sessionId, scope, tab)` | `sessionId`, `scope`, `tab` | Rail endpoint/cache | Key by all three values; abort a request when any value changes. |

### 3c. Return Value Contracts

| Method | Return type | Success means | Failure/empty means | Caller must |
|---|---|---|---|---|
| `resolveActorContext(...)` | `ActorContext` or authorization error | Scope and capabilities are verified | Missing/invalid membership | Stop before resource lookup; return 403 without revealing existence. |
| `hasCapability(...)` | `boolean` | Action may proceed to resource guard | Capability absent | Render permission state in client; backend rejects action regardless of client state. |
| `getExperienceBootstrap()` | `ExperienceBootstrap` | Actor and selections are authoritative | 401/403/503 | Redirect only for the existing structured unauthenticated/session-expired envelope; render permission/degraded states otherwise. |
| `decideApproval(...)` | `DecisionResult` discriminated union | Decision committed and activity emitted | `conflict`, `expired`, `forbidden`, `already_decided` | Never retry a conflict blindly; refresh record and show the matching state. |
| `fetchRail(...)` | `Promise<RailProjection>` | Projection matches current request key | Abort/error | Ignore aborts; retain last-good content only with a degraded label; never affect terminal readiness. |
| `buildBrandAssets(check)` | process exit code | All generated assets match manifest | Drift, missing source, invalid dimension/hash | CI fails; developer runs generator and reviews visual output. |
| `resolveRoute(path)` | `ResolvedRoute | null` | Canonical identity and alias are known | Unknown path | Route to the nearest permitted home, preserving no sensitive query from unknown paths. |

### 3d. Guard Parity

| Side effect | Template file | Guard condition to preserve/copy |
|---|---|---|
| Auth-expiry redirect | `web/src/lib/api.ts:145-165` | `(body.error === "unauthenticated" || body.error === "session_expired") && body.login_url` |
| Loopback stale-token reload | `web/src/lib/api.ts:176-195` | `!window.__HERMES_AUTH_REQUIRED__ && !options?.allowUnauthorized` plus the existing one-shot sessionStorage guard. |
| PTY WebGL activation | `web/src/pages/ChatPage.tsx:582-593` | `terminalTierWidthPx(host) >= 768` and `try/catch` fallback to the default renderer. |
| Persistent Chat visibility | `web/src/App.tsx:446-472` | Embedded Chat stays mounted and uses `display: isChatPath ? undefined : "none"`. Route identity replaces exact raw-path comparison but not the lifecycle behavior. |
| Chat supporting sidecar failure | `web/src/pages/ChatPage.tsx:995-997` | Terminal remains usable when the supporting sidecar fails. |
| WebSocket send | Existing PTY/gateway send sites | Send only when the socket is open; do not queue duplicate process-control messages across reconnects. |
| API mutation | Existing dashboard auth middleware plus new authorization wrapper | Valid authentication **and** resolved scope **and** required capability **and** resource-scope match. |
| Memory correction | `agent/system_prompt.py:514` | Active system prompt bytes are not regenerated; write a new memory version and apply on a later agent lifecycle. |
| Plugin override | `web/src/App.tsx:113-170` | An override may target canonical path or alias; preserve the current plugin loading wait before unknown-route fallback. |

### 3e. Test Harness Requirements

| Assertion | Harness must return | Negative-path test |
|---|---|---|
| Legacy route preserves query/hash | MemoryRouter initial entry `/chat?resume=s1#tail` | Unknown legacy path does not retain sensitive query data. |
| Chat is not remounted | Mock Chat component with stable mount counter and navigate away/back | Profile/config change uses exactly one controlled remount. |
| Entry chunk excludes heavy routes | Vite manifest with dynamic route chunks | Build fails if entry statically imports xterm/Plot/QRCode. |
| Capability-filtered navigation | Bootstrap with a restricted operator capability set | Direct navigation renders permission denied; hidden link alone is not accepted as enforcement. |
| Local-owner compatibility | Loopback resolver returns synthetic local scope and full local capability set | Hosted/authenticated path never falls back to local owner. |
| Scope isolation | Two tenants with duplicate-looking resource IDs | Every cross-tenant read/search/export/delete/WS attempt returns non-disclosing denial. |
| Approval conflict state | First decision commits version N, second uses N | Second write returns conflict/already-decided and produces no duplicate activity. |
| Rail failure does not break Chat | PTY mock ready; rail endpoint rejects | Terminal remains connected and rail renders degraded/retry. |
| Theme contrast | Rabot purple input on generated light/dark canvases | Arbitrary low-contrast tenant accent is adjusted to required ratios. |
| Brand assets deterministic | Canonical SVG/PNG sources and expected manifest | Modified/missing/hash-drift asset fails `--check`. |
| PWA integration preserved | Existing untracked manifest and icons | Build/test fails for missing manifest link, theme meta, touch icon, or invalid dimensions. |
| Prompt cache preserved | Active agent prompt captured before memory correction | Byte-for-byte prompt remains identical until a new agent lifecycle. |

## Implementation Plan

The plan is intentionally phased. Phase 1 is the performance/brand/shell foundation that can ship without pretending the current data model is multi-tenant. Phases 2–4 add the enforced operational domains needed for the complete enterprise product.

### Step 1: Freeze contracts with failing tests

- [ ] Add route-catalog tests covering uniqueness, canonical/alias resolution, query/hash preservation, plugin legacy anchors, capability filtering, and Chat identity.
- [ ] Add built-manifest tests proving the initial shell does not import heavy route chunks.
- [ ] Add token/contrast and brand-asset manifest tests before changing canonical values.
- [ ] Verification: `npm exec --workspace web vitest run src/app/route-catalog.test.tsx src/app/entry-chunks.test.ts` fails only on the missing implementation.

```ts
expect(resolveRoute("/chat")?.id).toBe("workspace.chat");
expect(resolveRoute("/workspace/chat")?.id).toBe("workspace.chat");
expect(new Set(APP_ROUTES.map(route => route.path)).size).toBe(APP_ROUTES.length);
expect(entryImports).not.toContain(expect.stringMatching(/xterm|plot|qrcode/i));
```

### Step 2: Establish static Rabot tokens and Fabric brand artifacts — Phase 1 shipped

- [x] Add a zero-runtime-dependency `apps/design-system` workspace containing primitives, semantic light/dark tokens, density, motion, and canonical SVG sources.
- [x] Reconstruct the supplied full wordmark as vector geometry; retain the bracket only in the full lockup. Create simplified optical and monochrome lowercase `f` marks.
- [x] Add deterministic asset generation/checking and a `brand-assets.json` dimension/hash manifest.
- [x] Alias static output onto existing web, desktop, TUI, CLI, website, bootstrap, ACP, PWA, and native packaging variables/paths.
- [x] Change the brand audit from old blue to Rabot purple; do not weaken contrast tests.
- [x] Retain the system stack and record Inter as pending because committed license/provenance is not available.
- [ ] Verification: `.venv/bin/python scripts/build_brand_assets.py --check` and focused brand tests pass.

```ts
export const rabot = {
  color: {
    primary: { 600: "#4628CC" },
    focus: "#6D55DD",
  },
  radius: { sm: "4px", md: "8px", lg: "12px", xl: "16px" },
  density: { compact: 0.875, comfortable: 1 },
} as const;
```

### Step 3: Replace route duplication with a lazy catalog — Phase 1 shipped

- [x] Create `web/src/app/routes.tsx` as the source for routes, titles, nav order, surface, aliases, and layout identity. Capability metadata remains a Phase 2 addition.
- [x] Use `React.lazy` for page implementations. Load Chat/xterm on first Chat visit and then keep it mounted for the process lifetime.
- [x] Update plugin matching to accept canonical paths and aliases and normalize legacy anchors such as `after:sessions`.
- [x] Preserve the current plugin-load window before unknown-route redirect.
- [x] Keep `/chat` functional for the existing PWA work.
- [ ] Verification: route tests, persistent Chat test, typecheck, and production build pass.

```ts
export const APP_ROUTES: readonly AppRouteDef[] = [
  {
    id: "chat",
    path: "/workspace/chat",
    aliases: ["/chat"],
    surface: "workspace",
    layout: "page",
    persistent: true,
    nav: { label: "Chat", icon: MessageSquare },
  },
];
```

### Step 4: Build the Workspace/Admin shell — Phase 1 shell shipped, access enforcement deferred

- [x] Replace current Work/Observe/Capabilities/Connect/System groupings with an explicit Workspace/Admin surface switcher backed by the catalog.
- [x] Retain the machine `ProfileSwitcher` as an agent-profile control; do not render it as tenant/workspace/site.
- [x] Add command palette route entries from the same catalog. Capability filtering remains deferred with the access contract.
- [x] Add a shared state surface for all 14 required state kinds and use it for new route shells.
- [ ] Show verified organization/local-owner context. Render a scope picker only when the authoritative bootstrap returns multiple allowed scopes.
- [x] Add no notification bell until durable producers/read state exist; reserve the shell slot without a false unread count.
- [ ] Verification: shell a11y, capability-filtering, route permission, density, theme, and mobile navigation tests pass.

```tsx
const visibleRoutes = APP_ROUTES.filter(
  route => !route.requiredCapability || hasCapability(actor, route.requiredCapability),
);

return (
  <nav aria-label={`${surface === "workspace" ? "Workspace" : "Admin"} navigation`}>
    {visibleRoutes.filter(route => route.surface === surface && route.nav).map(renderRoute)}
  </nav>
);
```

### Step 5: Deliver the first critical responsive screens — Phase 1 shipped

- [x] Home: render real gateway, conversation, automation, access-mode, and readiness projections with independently settled loading/degraded states; avoid fabricated work or approval analytics.
- [x] Conversations: reuse the session read model and expose search/filter/detail without cross-profile unbounded fan-out.
- [x] Chat: rearrange exactly one `ChatSessionList`, one persistent terminal, and one `ChatSidebar`/context rail across responsive breakpoints.
- [x] Work Board: retain the generic plugin route seam and provide a correct empty/install state when unavailable.
- [x] Memory: expose an explicit typed-ledger capability/degraded state without inventing facts, episodes, provenance, or retrieval history.
- [x] Admin AI Runtime: compose existing models/provider/configuration surfaces under the new namespace. Resource permissions remain Phase 2.
- [ ] Verification: responsive landmark tests, keyboard sheet behavior, rail failure isolation, and visual snapshots at phone/tablet/desktop sizes pass.

```tsx
<div className="chat-workspace" data-secondary-panel={secondaryPanel}>
  <aside aria-label="Conversations"><ChatSessionList {...sessionProps} /></aside>
  <main aria-label="Fabric chat terminal"><PersistentTuiPane /></main>
  <aside aria-label="Task context"><ChatContextRail {...contextProps} /></aside>
</div>
```

### Step 6: Add the authoritative access foundation — Phase 2 deferred

- [ ] Add `fabric_access/` with tenants, workspaces, sites, principals, memberships, roles, capabilities, profile bindings, migrations, and indexed control DB queries.
- [ ] Resolve one `ActorContext` per request and publish `/api/v1/me/context`.
- [ ] Bind WS tickets to actor, selected scope, endpoint purpose/path, channel, expiry, and single use.
- [ ] Apply identical capability/scope guards across cookie auth, service tokens, loopback/desktop, TUI RPC, plugin HTTP/WS, and profile selection.
- [ ] Backfill existing installs to synthetic local tenant/personal workspace/this-device site/local-owner.
- [ ] Verification: role/action matrix, token scope, WS replay/expiry/purpose, and two-tenant isolation E2E tests pass.

```python
def require_capability(capability: str):
    async def guard(request: Request) -> ActorContext:
        actor = await resolve_actor_context(request)
        if capability not in actor.capabilities:
            raise HTTPException(status_code=403, detail="Forbidden")
        return actor
    return guard
```

### Step 7: Scope conversations and durable work — Phase 2 deferred

- [ ] Add tenant/workspace/site/owner/profile bindings and compound indexes to sessions without repurposing messaging `user_id`.
- [ ] Replace dashboard cross-profile session aggregation with an incrementally maintained scoped conversation index.
- [ ] Add a scoped board registry and true scope columns/indexes to Kanban while retaining the legacy `tenant` field as a tag.
- [ ] Extend the generic plugin tab contract with aliases/surface/section metadata and migrate Kanban without a core special case.
- [ ] Verification: migration, WAL concurrency, partial migration, query-plan, export/delete/attachment, and plugin compatibility tests pass.

```sql
CREATE INDEX IF NOT EXISTS idx_conversation_scope_updated
ON conversation_index(tenant_id, workspace_id, site_id, updated_at DESC, conversation_id);

CREATE INDEX IF NOT EXISTS idx_task_scope_status_updated
ON kanban_tasks(tenant_id, workspace_id, site_id, status, updated_at DESC, id);
```

### Step 8: Make approvals, activity, and notifications durable — Phase 2 deferred

- [ ] Add approval requests/decisions with policy reference, evidence, eligible approvers, expiry, optimistic version, idempotency key, and restart reconciliation.
- [ ] Add transactional outboxes that project a unified cursor-based activity stream and per-user durable notifications.
- [ ] Implement initial notification producers: approval pending, task blocked/failed, automation failed, and agent intervention required.
- [ ] Keep approval transactions local/short; perform no network I/O while holding a decision lock.
- [ ] Verification: double-decision, separation-of-duties, expiry, restart, outbox replay, cursor order, read-state, and backpressure tests pass.

```sql
UPDATE approvals
SET status = :decision, decided_by = :principal, version = version + 1
WHERE id = :id AND version = :expected_version AND status = 'pending';
```

### Step 9: Add provider-neutral versioned Memory — Phase 2 deferred

- [ ] Introduce a capability-gated typed memory-record adapter for facts, episodes, procedures, policies, candidates, conflicts, provenance, temporal validity, versions, retrieval history, and corrections.
- [ ] Keep providers that lack a capability usable in explicit degraded/read-only states.
- [ ] Make corrections append versions and reconcile asynchronously for future agent lifecycles.
- [ ] Verification: provider capability matrix, provenance visibility, conflict workflow, temporal queries, retrieval history, degraded states, and byte-identical active prompt tests pass.

```python
correction = MemoryVersion(
    record_id=record.id,
    parent_version=record.version,
    corrected_by=actor.principal_id,
    valid_from=now,
    payload=validated_payload,
)
store.append_version(correction)
reconciliation_outbox.enqueue(record.id, correction.version)
```

### Step 10: Complete platform adapters and engineering handoff

- [ ] Apply generated tokens/assets to desktop, TUI, CLI, website, bootstrap installer, ACP, PWA, tray/menu bar, installers, and native package metadata.
- [ ] Keep desktop Chat independent; reuse pure contracts/tokens through a dependency-free shared package rather than importing dashboard React code.
- [ ] Produce sitemap, role navigation matrix, user flows, annotated responsive wireframes, component/state catalog, clickable prototype route, and engineering handoff tables tied to implemented components and APIs.
- [ ] Record bundle budgets, accessibility results, endpoint authorization coverage, DB query plans, and migration/rollback instructions.
- [ ] Verification: all changed workspace builds, platform brand tests, accessibility audits, and cross-platform smoke tests pass.

```ts
export const bundleBudgets = {
  shellEntryGzipKb: 180,
  routeChunkGzipKb: 250,
  chatFirstLoadGzipKb: 600,
} as const;
```

## UI/UX Changes

### Sitemap

```text
Fabric
├── Workspace
│   ├── Home
│   ├── Chat
│   ├── Work Board
│   ├── Conversations
│   ├── Agents
│   ├── Memory
│   ├── Knowledge
│   ├── Automations
│   ├── Approvals
│   ├── Activity
│   └── Insights
└── Admin
    ├── Integrations
    │   ├── Skills
    │   ├── Plugins
    │   └── MCP
    ├── Channels & Events
    │   ├── Channels
    │   └── Webhooks
    ├── AI Runtime
    │   ├── Models & Providers
    │   ├── Agent Profiles
    │   └── Memory Provider
    ├── Security & Access
    │   ├── Members & Roles
    │   ├── Pairing
    │   └── Credentials
    ├── System
    ├── Advanced
    │   ├── Configuration
    │   └── Logs
    └── Help
```

### Role navigation matrix (Phase 2 target)

| Role | Primary landing | Workspace | Admin |
|---|---|---|---|
| Operator | Home | Chat, Work, Conversations, Knowledge, Approvals (assigned), Activity | None by default |
| Manager | Home | All operator pages plus Agents, Memory, Automations, Insights | Read-only AI Runtime where granted |
| Builder | Work Board | Workspace build/agent/memory surfaces | Integrations, Channels & Events, AI Runtime |
| Security admin | Activity | Permission-scoped Workspace views | Security & Access, Activity/audit, System read-only |
| Platform admin | Admin / AI Runtime | All granted Workspace pages | All Admin domains |
| Auditor | Activity | Read-only Activity, Approvals, Insights, provenance | Read-only Security/System evidence |

Capabilities, not role names, determine actual access. Roles are membership bundles and may be tenant-customized.

### Target user flows after durable services ship

1. **Ask to durable work:** start in Chat -> agent proposes a work item -> inspect plan/evidence in context rail -> confirm -> follow named agents/handoffs on Work Board -> resolve approval -> receive outcome/activity -> accept memory candidate.
2. **Operational intervention:** Home shows blocked task -> open Work Board dependency graph -> inspect failed run and retry history -> reassign/handoff -> approve retry or edit input -> verify artifact and outcome.
3. **Memory correction:** search Memory -> inspect fact/version/provenance/retrieval history -> flag conflict -> create correction -> review temporal validity -> publish new version -> future agent lifecycle uses reconciled version.
4. **Admin setup:** choose tenant/workspace/site -> connect integration -> map channel/event -> configure AI Runtime/profile binding -> apply access policy -> run connection and permission checks -> observe audit activity.

### Responsive annotated wireframe

```text
>= 1440px
┌──────────────┬───────────────────────┬─────────────────────────────────┬──────────────────────┐
│ Product nav  │ Conversations         │ Persistent fabric --tui        │ Context              │
│ scope/switch │ search + recent       │ transcript + composer          │ task/evidence/memory  │
│ Workspace    │ one live list         │ never remounted on nav          │ artifacts/activity   │
│ Admin        │                       │                                 │ lazy tab fetches     │
└──────────────┴───────────────────────┴─────────────────────────────────┴──────────────────────┘

1024–1439px: Product nav + terminal + one user-selected secondary panel.
<1024px: Compact top/bottom shell + terminal; Conversations and Context open as separate sheets.
```

### Visual language

- System sans is the Phase 1 UI default. Licensed self-hosted Inter may replace it after provenance is committed; monospace remains limited to terminal, IDs, timestamps, hashes, code, and model/token values.
- Sentence case; uppercase limited to established short technical labels.
- Purple is action/focus/selection, not decorative wash. Status colors remain semantic and independently contrast-tested.
- 4px base grid with compact/comfortable density multipliers. Common radii are 4/8/12/16px.
- Motion communicates continuity and state only, respects `prefers-reduced-motion`, and avoids layout-triggering transitions.
- Light, dark, and high-contrast-compatible theme derivation use the existing accessible generator.

## Migration / Rollout

1. **Shipped:** static token/brand output and route aliases; legacy URLs remain supported.
2. **Shipped in local/auth-mode form:** the Workspace/Admin shell without an arbitrary enterprise scope selector. Authoritative local-owner/verified memberships remain part of Step 6.
3. Add authoritative access tables and context endpoint behind a `config.yaml` rollout setting; dual-read during migration.
4. Backfill local installations transactionally and verify counts/indexes before enforcement.
5. Add scoped conversation/board reads and writes, then enforce per resource family after two-tenant E2E coverage.
6. Add durable approvals/activity/notifications, then enable their navigation items.
7. Add typed Memory capabilities provider-by-provider; unsupported providers render degraded/read-only states.
8. Retire legacy endpoint implementations only after guarded aliases, telemetry-free local audit evidence, and documented rollback exist.

Rollback preserves legacy route aliases and old database columns until the new scoped queries and backfills have passed verification. No outbound telemetry is introduced.

## Test Plan

- [ ] Unit: route catalog invariants, aliases, titles, nav order, capabilities, state copy, token contrast, brand manifest.
- [ ] Component: Workspace/Admin switcher, scope visibility, command palette, permission/read-only/degraded states, responsive Chat rails, focus return, keyboard navigation.
- [ ] Integration: persistent Chat navigation lifecycle, plugin overrides/anchors, auth expiry, loopback token rotation, rail abort/failure isolation, PWA deep link.
- [ ] Backend: actor resolution, role/action matrix, service-token scopes, loopback local owner, WS ticket purpose/replay/expiry, route guard introspection.
- [ ] Data: two-tenant isolation, session/board migrations, WAL concurrency, query plans, cursor pagination, approval optimistic locking, outbox idempotency.
- [ ] Memory: capability matrix, versions/conflicts/provenance/temporal validity/retrievals/corrections, active prompt byte stability.
- [ ] Accessibility: WCAG AA contrast, landmarks, focus order/visibility, sheet/dialog trapping and return, non-color state meaning, reduced motion, 200% zoom.
- [ ] Visual: phone/tablet/desktop widths in light/dark/compact/comfortable, every required state on the six critical screens.
- [ ] Performance: initial entry imports, gzip budgets, hidden-tab polling pause, one persistent PTY, bounded rail requests, conversation/activity query plans.
- [ ] Platform: web, desktop macOS/Windows/Linux, TUI, CLI, website, PWA, installer, tray/menu, ACP.
- [ ] Lint: `npm run lint --workspace web` and each changed TypeScript workspace.
- [ ] Typecheck: `npm run typecheck --workspace web`, desktop, TUI, and installer as changed.
- [ ] Build: `npm run build --workspace web`, desktop, TUI, installer, and website as changed.
- [ ] Python: focused `pytest` targets for auth/access, Kanban, memory, ACP, native branding, and brand audit.

## Out of Scope

- Rewriting the agent core, replacing the embedded browser TUI with a second React Chat, or changing model provider semantics.
- Treating third-party SaaS observability products as core plugins; those remain standalone integrations.
- A single atomic release of every enterprise backend domain. Access/resource isolation must precede claims of hosted multi-tenancy.
- Automatic tracing of the supplied raster as canonical vector geometry; the logo requires deliberate reconstruction and optical variants.
- Shipping unlicensed font files. Visual parity does not override font provenance.
- Converting every messaging-channel-native UI into the full Workspace/Admin shell; channels receive concise task/approval/status adaptations.
- Introducing analytics or usage attribution without an explicit generic opt-in.

## Open Questions

- Confirm the legal/provenance source for the ZIP's Inter WOFF2 files before committing them. The implementation uses the system stack until confirmed.
- Hosted role bundle names and default capability matrices need product/security approval; enforcement is capability-based so naming can change without route rewrites.
- White-label tenant customization beyond name, primary color, mark, and wordmark needs a later governance contract for contrast-safe limits.
- The exact durable notification retention/read policy should be selected with the activity-store retention policy.

None of these questions block Phase 1. They block only the corresponding licensed font, hosted-default role, expanded white-label, or durable notification decisions.

## Self-Review

- [x] Every acceptance criterion has a corresponding implementation step.
- [x] Runtime Modes covers dashboard, headless, desktop, hidden Chat, mobile, TUI, CLI, and degraded operation.
- [x] Lifecycle Matrix includes all four transitions for persistent Chat, supporting rails, scope, and theme state.
- [x] Every method with a scoping parameter in this design has a Parameter Contracts row.
- [x] Every meaningful return value has a caller obligation in Return Value Contracts.
- [x] Every high-consequence side effect matches a named guard/template reference.
- [x] Every test assertion has explicit harness setup in Test Harness Requirements.
- [x] No placeholder steps (`TBD`, `implement X`, or `similar to step N`) remain.
- [x] Out of Scope lists adjacent concerns that are deliberately excluded.
- [x] Key files include actual line references.

## RSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---|---|---|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent second opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests | 0 | — | — |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |

**VERDICT:** Internal source, product, design-system, and enterprise-domain audits are complete. Formal rstack review passes remain available, but the user explicitly authorized the recommended direction and Phase 1 implementation.
