# CAPABILITIES Section Revamp — Implementation Spec ("Agentic Look")

> **Historical implementation record — superseded for current design decisions.**
> Use [`web/DESIGN.md`](../../web/DESIGN.md) and the
> [Workspace/Admin guide](../../website/docs/user-guide/workspace-admin.md)
> as the active contract. Route names and component details below remain useful
> archaeology, but the inherited “agentic/terminal-grade” visual direction,
> teal identity, pervasive display typography, and legacy nav grouping are not
> current Fabric guidance.


Scope: the four pages in the **Capabilities** nav group — Models, Skills, Plugins,
MCP — per the design direction in `docs/design/dashboard-revamp-research.md`
("terminal-grade minimalism", single accent, mono for technical readouts,
value-density metric) and the shared vocabulary shipped by
`docs/design/work-section-spec.md` (G1–G13) and `docs/design/observe-section-spec.md`
(O1–O7).

Framing: **Capabilities is the agent's loadout.** Models are what the agent thinks
with, Skills/Toolsets are what it knows and can do, Plugins are what extends it, MCP
servers are what it can reach. Every item on these pages renders in one shared
grammar — identity, state, provenance, usage evidence, actions — so the section
reads as one equipment manifest, not four unrelated admin screens.

Status: implementation-ready. Requirements are numbered `CAP` (shared), `M` (Models),
`K` (Skills), `P` (Plugins), `X` (MCP). Non-goals and risks continue the Work/Observe
numbering (`N13+`, `R15+`) so all three specs can be referenced together without
collisions. `G*`/`O*` references are the Work/Observe shared rules, reused as-is.
Appendix B continues at `B16`.

Source-of-truth files audited (2026-07-13):

- Frontend: `web/src/pages/ModelsPage.tsx`, `web/src/pages/SkillsPage.tsx`,
  `web/src/pages/PluginsPage.tsx`, `web/src/pages/McpPage.tsx`,
  `web/src/components/{ToolsetConfigDrawer,SkillEditorDialog,ModelPickerDialog,ModelReloadConfirm,LocalOllamaSetupCard}.tsx`,
  `web/src/components/ui/` (full barrel: `AgentStatusBadge`, `MonoId`,
  `RelativeTime`, `NextRunCountdown`, `RunRow`, `TimelineNode`, `DataTable`,
  `EmptyState`, `Skeleton`, `PageToolbar`, `agent-status.ts`, `time.ts`),
  `web/src/lib/api.ts`
- Backend: `fabric_cli/web_server.py` — models (~L5383–6000, ~L15613), local
  providers/Ollama (~L5488–5706), skills + toolsets (~L14859–15450), skill hub
  (~L13654–14050), MCP (~L12200–12700), plugins hub (~L17994–18320), analytics
  usage (~L15542); `agent/insights.py` (tool/skill usage shapes)

---

## 0. Data audit — what the backend actually serves TODAY

Everything in the main spec is buildable against these endpoints as they exist now.
Anything requiring server work is in Appendix B only.

### 0.1 Models

| Endpoint | Shape (verified) |
|---|---|
| `GET /api/analytics/models?days&profile` (~L15613) | `{models: Entry[], totals{distinct_models,total_input,total_output,total_cache_read,total_reasoning,total_estimated_cost,total_actual_cost,total_sessions,total_api_calls}, period_days}`. Entry = `{model, provider (billing_provider), input/output/cache_read/reasoning_tokens, estimated_cost, actual_cost, sessions, api_calls, tool_calls, last_used_at (epoch s), avg_tokens_per_session, capabilities{supports_tools,supports_vision,supports_reasoning,context_window,max_output_tokens,model_family}}`. Server folds session-only duplicate rows into the accounted provider row. |
| `GET /api/model/auxiliary?profile` (~L5830) | `{tasks: [{task, provider ("auto" = main), model, base_url}] × 11 fixed slots (_AUX_TASK_SLOTS), main: {provider, model}}` |
| `GET /api/model/moa` / `PUT /api/model/moa` (~L5881) | normalized MoA config: presets map (`reference_models[], aggregator, temperatures, max_tokens, enabled`) + `default_preset`/`active_preset` + legacy flat fields |
| `POST /api/model/set` (~L5941) | `{scope: main\|auxiliary, provider, model, task, base_url?, api_key?, confirm_expensive_model?}` → may return `{confirm_required: true, confirm_message}` (expensive-model guard). Writes config.yaml — **new sessions only**. |
| `GET /api/model/options?profile&refresh` (~L5708) | picker payload (providers + curated models + pricing + capabilities), 1:1 with the TUI `model.options` RPC — consumed by `ModelPickerDialog` |
| `GET /api/model/info?profile` (~L5383) | `{model, provider, auto/config/effective_context_length, capabilities}` — **currently used by Chat only, not ModelsPage** |
| `GET /api/providers/local` (~L5536) | passive Ollama catalog row (`configured`, `base_url`, `model`, setup/pull commands); never probes the network |
| `POST /api/providers/local/ollama/discover` (~L5607) | `{state: reachable\|unreachable\|auth_failed\|protocol_mismatch, models[], issue_code}` — explicit action, localhost/private-address only (SSRF guard) |
| `POST /api/providers/local/ollama/configure` (~L5634) | verifies model installed, persists provider/model/base_url, may flip `security.egress_mode=local_ai`, deactivates prior auth provider |
| `GET /api/config` | `dashboard.show_token_analytics` gate (default off) — same gate + rationale as Observe A2 |

No per-model "recent runs" listing exists: `GET /api/sessions` filters by
`source/archived/min_messages/cwd_prefix/profile` only — **no `model=` filter**
(Appendix B16). Provider OAuth endpoints (`/api/providers/oauth*`) are consumed by
`OAuthProvidersCard` on the **Env (Keys) page**, not ModelsPage — key/OAuth entry
stays there (N15).

### 0.2 Skills + Toolsets + Hub

**`GET /api/skills?profile`** (~L14859) → `SkillInfo[]`. Served fields:
`name, description, category, enabled` **plus two fields the TS type does not
declare** (frontend-only unlock, verified ~L14880–14887):

- `usage: number` — activity count from `tools/skill_usage.load_usage()`
- `provenance: "hub" | "bundled" | "agent"` — hub-installed > bundled > agent/local
  (the "agent" tier is the one the user may edit/delete)

`PUT /api/skills/toggle` (per-skill enable/disable, profile-scoped).
`GET /api/skills/content`, `POST /api/skills`, `PUT /api/skills/content` — the
SkillEditorDialog paths (server-side frontmatter/name/size validation via the same
`skill_manage` pipeline; bypasses the agent write-approval gate by design).

**`GET /api/tools/toolsets?profile`** (~L14984) → `[{name, label, description,
enabled, available, configured, tools: string[]}]` (tools = resolved tool names).
`PUT /api/tools/toolsets/{name}` toggle; `GET .../config`, `GET .../models`,
`PUT .../model`, `PUT .../provider`, `PUT .../env`, `POST .../post-setup` — all
owned by `ToolsetConfigDrawer` (provider pick, key entry, install-hook log tail).

**Skill hub** (all exist and are wired):
`GET /api/skills/hub/sources` → `{sources: [{id, label, rate_limited?, available?,
searchable}], index_available, featured: Result[≤12], installed: {identifier →
{name, trust_level, scan_verdict}}}` · `GET /api/skills/hub/search?q&source&limit`
(cap 50, 30 s fan-out; returns `results/source_counts/timed_out/installed`) ·
`GET .../preview` (SKILL.md + file manifest, no install) · `GET .../scan`
(quarantine + `scan_skill` + install policy: `verdict safe|caution|dangerous`,
`policy allow|ask|deny`, findings with severity) · `POST .../install|uninstall|update`
(spawn CLI action; UI tails via `GET /api/actions/{name}/status`).

**No "capability pack" concept exists anywhere in the backend or frontend** —
no endpoint, no field, no grouping beyond `category`, `provenance`, and toolsets.
(Decision in §3.1.)

**Toolset usage evidence exists indirectly:** `GET /api/analytics/usage` serves
`tools: [{tool_name, count}]` and the server comment says explicitly "the desktop
Capabilities page aggregates these per toolset" (~L15605). `ToolsetInfo.tools`
lists exactly those tool names → per-toolset call counts are a client-side join.

### 0.3 Plugins

**`GET /api/dashboard/plugins/hub?profile`** (~L18169 → `_merged_plugins_hub`
~L18051) → one response for the whole page:

- `plugins[]`: `{name, version, description, source (user|git|bundled|…),
  runtime_status: "enabled"|"disabled"|"inactive", has_dashboard_manifest,
  dashboard_manifest (tab path/hidden/override, slots[]), path,
  can_remove, can_update_git, auth_required, auth_command ("fabric auth <name>"),
  user_hidden}`
- `orphan_dashboard_plugins[]`: dashboard-only manifests with no agent plugin
- `providers`: `{memory_provider, memory_selection {configured, state, runtime_active:
  "unknown"}, memory_options: MemoryProviderInfo[] (status ready|needs_config|
  unavailable|missing|readiness_unknown, capabilities map, setup {pip/external
  deps, required_env, dependencies_installed}), context_engine, context_options}`

Mutations: `POST /api/dashboard/agent-plugins/install` ·
`POST .../{name}/enable|disable|update` · `DELETE .../{name}` ·
`PUT /api/dashboard/plugin-providers` (memory/context selection; server enforces
readiness) · `POST /api/dashboard/plugins/{name}/visibility` (sidebar hide) ·
`GET /api/dashboard/plugins/rescan`. Memory provider detail:
`GET/PUT /api/memory/providers/{name}/config`, `POST .../setup` (runs declared
install steps, returns per-step results).

No plugin usage/telemetry data of any kind is served (Appendix B19).

### 0.4 MCP

**`GET /api/mcp/servers`** (~L12246; summary ~L12230) → `{servers: [{name,
transport: "http"|"stdio"|"unknown", url, command, args[], env (values redacted),
auth, enabled, tools: string[] | null (enabled-tool selection; null = all)}]}`.

Mutations/actions: `POST /api/mcp/servers` (create; validates + rejects suspicious
command/args) · `DELETE .../{name}` · `PUT .../{name}/enabled` (config flag —
"takes effect on next gateway restart") · `POST .../{name}/test` → `{ok, error?,
tools: [{name, description}], prompts: number, resources: number}` — **the
`prompts`/`resources` counts are served but missing from the TS `McpTestResult`
type** (frontend unlock) · `POST .../{name}/auth` — full OAuth browser flow with
token snapshot/restore, **exists server-side but has NO `api.ts` binding and no UI**
(~L12394; frontend unlock, X7).

**`GET /api/mcp/catalog`** (~L12532) → `{entries: [{name, description, source,
transport, auth_type: api_key|oauth|none, required_env [{name,prompt,required}],
command, args, url, install_url, install_ref, bootstrap[], default_enabled,
post_install, needs_install, installed, enabled}], diagnostics: [{name, kind,
message}]}`. `POST /api/mcp/catalog/install` → sync for plain entries, or
`{background: true, action}` for git-bootstrap entries — **the action name is
returned but McpPage never tails it** (the skills-hub log-tail pattern applies; X8).

**There is no persisted or background MCP health.** Health is only knowable at the
moment of an explicit `/test` (or `/auth`) probe; results live in page state and
die on unmount. (Decision in §1.2; background health = Appendix B21.)

---

## 1. Shared capability grammar (CAP-requirements)

### 1.1 The five zones

**CAP1.** Every capability item on all four pages renders its content in five
zones, in this order (zones may be empty, never reordered):

1. **Identity** — the item's name. Mono (`font-mono-ui`) whenever the name is a
   technical identifier the user might type or grep (model ids, skill names, MCP
   server names, tool names, plugin package names, hub identifiers); sans only for
   genuinely human labels (toolset display labels, catalog display names alongside
   their technical id). Long ids truncate with full value in `title`.
2. **State** — enabled/disabled/needs-setup/error, per the CAP2 table. Rendered as
   the item's Switch (where toggling is the primary action) plus at most one state
   Badge; never two badges saying the same thing.
3. **Provenance** — where it came from and what version: provider/vendor, source
   (hub/bundled/agent, user/git, catalog source, trust level), version, transport.
   Outline/secondary Badges + mono text; monochrome (G11).
4. **Usage evidence** — real numbers only, where data exists today (Models: full
   token/session block; Skills: `usage` count; Toolsets: per-toolset call sum;
   MCP/Plugins: none — zone omitted, never faked). Mono `tabular-nums`; R4
   discipline (no `0`-noise, segments render conditionally).
5. **Actions** — trailing buttons/menus. Destructive actions rightmost, behind
   confirm dialogs (unchanged flows).

**CAP2. Capability-state vocabulary.** Capabilities are equipment, not agents:
`enabled/disabled` is configuration, not lifecycle, so **`AgentStatusBadge` is NOT
used on these four pages** (O2 discipline — no real G1 status exists here; the G1
word `paused` stays cron vocabulary, and painting every disabled skill
warning-toned would be noise). Instead, one shared mapping table, applied with
plain DS `Badge` tones everywhere:

| Capability state | Tone | Label | Sources that map to it |
|---|---|---|---|
| enabled / active | `success` | `enabled` / `active` / `installed` | skill `enabled`, toolset `enabled`, plugin `runtime_status==="enabled"`, MCP server `enabled`, catalog/hub `installed`, memory provider `ready` |
| disabled / off | `outline` | `disabled` / `inactive` | skill/toolset/MCP `enabled===false`, plugin `runtime_status==="disabled"\|"inactive"` (keep the two words distinct — `disabled` is explicit, `inactive` is not-yet-enabled) |
| needs setup | `warning` | `needs setup` | toolset `enabled && !configured`, memory provider `needs_config`/`readiness_unknown`, plugin `auth_required`, MCP catalog `required_env` unfilled |
| broken / missing | `destructive` | `unavailable` / `missing` | memory provider `unavailable`/`missing`, orphaned configured provider |
| last-outcome (probe/scan) | `success`/`destructive` chip | `reachable · N tools` / `unreachable`; scan `safe/caution/dangerous` | MCP `/test` result, hub scan verdict — rendered as a **separate outcome chip** (the cron `last_status` precedent), never merged into the state badge |

New pure module `web/src/components/ui/capability-state.ts`: the tone table plus
mappers `toolsetCapabilityState(ts)`, `pluginCapabilityState(row)`,
`mcpServerCapabilityState(s)`, `memoryProviderCapabilityState(p)` — component-free,
unit-tested, same pattern as `agent-status.ts`. No new badge component is needed;
the DS `Badge` with the mapped tone is sufficient.

**CAP3. Component strategy: one shared row, not one shared card.** The four pages
have three genuinely different densities (dense toggle-rows, mid-weight
config rows, analytics-rich cards). Forcing one `CapabilityCard` across all of them
would repeat the mistake CH9 avoided. Decision:

- **New shared `CapabilityRow`** (`web/src/components/ui/CapabilityRow.tsx`) — the
  list-row shape shared by Skills rows, MCP server rows, MCP catalog rows, plugin
  rows, and hub result rows (5 consumers; RunRow needed only 2 to justify itself):

  ```tsx
  export interface CapabilityRowProps {
    /** Identity zone. */
    name: string;
    mono?: boolean;                    // default true (CAP1.1)
    icon?: LucideIcon;                 // monochrome glyph, muted
    /** State zone. */
    switch?: { checked: boolean; onChange(): void; busy?: boolean }; // leading Switch
    badges?: ReactNode;                // state + provenance Badges (caller-ordered)
    /** Body. */
    description?: ReactNode;           // text-xs muted, line-clamp-2
    meta?: ReactNode;                  // mono meta line (`·`-separated), tabular-nums
    detail?: ReactNode;                // full-width extra block (test results, env hints…)
    /** Actions zone. */
    actions?: ReactNode;               // trailing cluster
    dimmed?: boolean;                  // disabled items: opacity-60 on body, not actions
    className?: string;
  }
  ```

  Visual contract: 1px `border-border` box (or borderless inside a bordered list
  container — caller picks via `className`), hover `bg-secondary/30`, grid
  `[switch?] [icon?] [name+badges / description / meta / detail] [actions]`.
  No fixed heights (G12).
- **Models keep Card composition.** `ModelCard` is an analytics card (stacked token
  bar, 3-stat grid), not a row; it adopts the CAP1 zone order and shared chips but
  stays a page-local component (M6).
- **Toolset cards migrate to `CapabilityRow`** in a 1-col list (K7) — their current
  grid-card layout holds less signal per pixel than a row with a meta line.

**CAP4. Type unlocks (frontend-only, verified served).** Extend in `api.ts`:
- `SkillInfo`: `usage: number; provenance: "hub" | "bundled" | "agent"` (§0.2)
- `McpTestResult`: `prompts?: number; resources?: number` (§0.4)
- Add binding `api.authMcpServer(name)` → `POST /api/mcp/servers/{name}/auth`
  (endpoint exists, unbound; X7)
No backend edits.

**CAP5. Timestamps and ids.** Every rendered timestamp goes through
`RelativeTime` (`last_used_at` epoch-seconds on Models; nothing else in this
section serves timestamps today). Every technical identifier surfaced outside its
own identity zone (hub identifiers in meta lines, action names in log headers)
renders via `MonoId` or plain `font-mono-ui` (R3/O4 discipline). ModelsPage's
`timeAgo()` call is replaced by `RelativeTime` (shared ticker, absolute in `title`).

**CAP6. G-rules apply wholesale.** G9 type assignment (chrome labels
uppercase-tracked only; mono for every technical readout), G10 (1px-border
elevation, tokens only — the amber literals called out in K11/K12 are bugs to fix),
G11 (single accent: `primary` = selection/interaction only; the current
`text-primary` Sparkles icon and hub link colors are grandfathered as interactive
affordances), G12 (density, `tabular-nums`), G13 (PageToolbar / EmptyState /
Skeleton on every page — Skills, Plugins, and MCP currently hand-roll all three).

**CAP7. Cross-links into Sessions/Analytics — decision.**
- **ACCEPT: in-place usage evidence.** Render counts where the data is already on
  the wire (M-zone stats, K5 skill `usage`, K8 toolset call sums). This is the
  honest version of "used by N runs": the number without a pretend-filter link.
- **REJECT: filtered deep links ("used by N runs" → Sessions).** `GET /api/sessions`
  has no `model=`/`skill=` filter (§0.1) and SessionsPage/AnalyticsPage read no URL
  query params (verified in the Observe audit, Appendix A-1). A chip that navigates
  to an unfiltered page is a broken promise. Plain unparameterized "open
  Analytics" links are allowed where they already exist (the Config link in the
  token notice). True cross-links need B16 + Work-spec A-1.

**CAP8. `dashboard.show_token_analytics` gate.** Models keeps the same tile-level
gate semantics Observe A2 established: token/cost surfaces (▲) hide when the gate
is off; session counts, capability data, and assignments always render. The gate
copy is the compact one-row warning notice (Observe A1.2 pattern), not the current
inline paragraph. Skills/Plugins/MCP have no token surfaces — no gate.

**CAP9. Loading discipline.** All four pages replace full-page `Spinner`s with
layout-shaped `Skeleton`s + `aria-busy` (Skills and MCP currently block the whole
page on a centered spinner; Plugins spins inline). Background refreshes never
skeleton (existing rule).

**CAP10. Install/action logs.** The skills-hub action-log card (spawn → poll
`getActionStatus` → mono `pre` tail → done/running Badge) is the single idiom for
every long-running install in the section. MCP catalog background installs adopt
it (X8); plugin install/update keep their synchronous toasts (their endpoints are
synchronous — no action to tail).

---

## 2. MODELS page — "the loadout's brain" (M-requirements)

### 2.1 Decisions on the table

- **Assignment surface at top — ACCEPT (formalized).** `ModelSettingsPanel`
  already is the assignment surface; it becomes the page's explicit hero:
  "what model is the agent running" answers above the fold, before any analytics.
  Reject the alternative (folding main/aux/MoA into per-card menus only) — the
  `UseAsMenu` stays as a shortcut, but assignment state must be legible without
  opening menus.
- **Ollama local-model management placement — ACCEPT: stays on ModelsPage.** It is
  loadout setup (pick the brain), not credential management; `configure` writes
  `model.*` config exactly like `/api/model/set` does. It renders inside the
  assignment zone (M2), keeping its explicit-discovery behavior verbatim (the
  SSRF-guard/no-passive-probe design is security-reviewed — N14). Rejected:
  moving it to Env/Keys (that page owns secrets, not model selection).
- **Provider OAuth flows — REJECT for this page.** They live on Env/Keys
  (`OAuthProvidersCard`) and are reachable from the picker's failure copy; nothing
  on ModelsPage calls the OAuth endpoints today. No migration in this pass (N15).
- **Per-model "recent runs" drawer — REJECT.** No `model=` session filter exists
  (§0.1); a client-side filter over one page of sessions would silently mean
  "recent runs among the last N". Usage evidence stays aggregate (`sessions`,
  `last_used_at`, tokens). B16.

### 2.2 Information architecture

**M1.** Top-to-bottom (▲ = gated by CAP8):

1. `PluginSlot models:top` (kept).
2. **Assignment surface** (M2) — full-width, replaces the current 2-col split of
   settings vs stats.
3. **Fleet stats strip** — the existing `Stats` card, kept; ▲ token/cost items per
   CAP8; the gate paragraph becomes the compact notice (CAP8).
4. **Usage cards grid** (`md:grid-cols-2 xl:grid-cols-3`, kept) — `ModelCard`s
   restructured per M6.
5. `PluginSlot models:bottom` (kept).

Header: period buttons + refresh in `afterTitle` (kept as-is).

**M2.** Assignment surface (evolves `ModelSettingsPanel` + `LocalOllamaSetupCard`):
one Card, chrome label `loadout`, subtitle "applies to new sessions" (kept —
load-bearing copy):

- **Main row** (hero): Star glyph · `provider/model` mono
  (`(unset)` italic-muted when empty) · capability chips for the main model when
  resolvable from the already-fetched analytics entry match (Tools/Vision/
  Reasoning/family — no new fetch; hide when no match) · `Change` Button →
  existing `ModelPickerDialog` + expensive-model confirm + `ModelReloadConfirm`
  flow, bit-for-bit (N16).
- **Auxiliary row**: summary `N overrides · M auto` (kept) · `Configure` →
  `AuxiliaryTasksModal` unchanged internally except container polish (1px borders
  already present).
- **MoA row**: summary `N references · provider/aggregator` (kept) · `Configure` →
  `MoaModelsModal` unchanged internally (preset CRUD, no-recursive-MoA guard).
- **Local runtime row(s)**: `LocalOllamaSetupCard` content inlined as the fourth
  row group when `GET /api/providers/local` returns rows — discovery stays an
  explicit button (`Refresh`), configure flow, `local_ai` egress note, all
  behavior unchanged (N14). When the provider is `configured`, its row shows the
  success-tone `active` state badge per CAP2.

**M3.** Aux-assignment legibility: the assignment surface's auxiliary row `title`
lists the overridden tasks (`vision → groq/llama-4-fast, …`) so hover answers
"which overrides" without opening the modal. Data already in `aux.tasks`.

**M4.** ▲Stats items exactly as today (`models used, total tokens, input, output,
est. cost, sessions` / ungated: `models used, sessions`). Values mono
`tabular-nums` (G8/G12 — the `Stats` primitive already does this).

**M5.** `AUX_TASKS` label/hint table stays the frontend mirror of
`_AUX_TASK_SLOTS` (comment kept; drift risk noted in R18).

**M6.** `ModelCard` restructure to CAP1 zones (page-local component, CAP3):

- Identity: `#rank` mono · short model name mono (`title` = full id) ·
  provenance: provider Badge (secondary) + `ctx`/`out` token counts (kept).
- State: `main` chip (primary-tinted, kept — this is an *assignment* marker, the
  one sanctioned primary-accent chip on the page since assignment ≈ selection,
  G11) · `aux · <task>` chip (kept, muted).
- Usage evidence: ▲`TokenBar` (kept verbatim — it already uses the two
  `--series-*-token` theme vars, the only sanctioned chart colors, O1) ·
  ▲3-stat grid (sessions / avg / api calls, kept) · ungated fallback: `sessions`
  count (kept) · footer: ▲cost + ▲tool_calls (conditional, R4) +
  `RelativeTime(last_used_at)` (CAP5 — replaces `timeAgo`).
- Capability chips row (kept; the `bg-success/10` Tools chip is token-based and
  compliant).
- Actions: `UseAsMenu` kept, entire flow unchanged (assign main/aux,
  `confirm_required` → `ConfirmDialog`, outside-click close) (N16).

**M7.** Card ordering/`key` unchanged (`model:provider`, server-sorted by total
tokens). The `ring-1 ring-primary/40` main-model treatment is kept (selection
accent, G11).

**M8.** Number formatting: the page-local `formatTokens`/`formatCost` are
consolidated with `lib/format.formatTokenCount` into `web/src/lib/format.ts`
exports used by both Models and the Observe surfaces — one compact-format
implementation, not three (pure-refactor; no display change).

### 2.3 Data mapping (endpoint → field → display)

| Surface | Source | Field | Display |
|---|---|---|---|
| Main/aux rows | `/api/model/auxiliary` | `main`, `tasks[]` | mono `provider · model`; override counts |
| MoA row | `/api/model/moa` | `presets`, `reference_models`, `aggregator` | mono summary |
| Local runtime | `/api/providers/local` + discover/configure | `configured, base_url, model, state, models[]` | assignment row + explicit discovery flow |
| Stats strip | `/api/analytics/models` | `totals.*` | `Stats`, ▲ per CAP8 |
| Model card | `/api/analytics/models` | entry fields + `capabilities` | CAP1 zones per M6 |
| `main`/`aux` chips | `/api/model/auxiliary` matched on `provider+model` | — | assignment chips |
| Gate | `/api/config` | `dashboard.show_token_analytics` | CAP8 |

### 2.4 States

**M9.** Loading: kept skeleton layout (`block h-40` for the stats slot + 6 ×
`block h-44` grid, `aria-busy`) plus one `block h-40` for the assignment surface
(currently the settings panel renders empty-ish while `aux` is null — skeleton it
until the first `/api/model/auxiliary` resolves).

**M10.** Empty: existing `EmptyState icon={Cpu}` (no models data → "start a
session") kept, action = Refresh. Assignment surface is never empty (unset slots
render `(unset)`).

**M11.** Errors: the bare centered destructive text becomes the shared
destructive-tinted 1px banner + Retry (`load()`); `getAuxiliaryModels` failures
stay non-fatal (assignment rows render `(unset)` + a one-line inline warning
instead of silently blank). Focus/visibility refetch of aux (the 1 s-debounced
listener) is kept verbatim.

---

## 3. SKILLS page — "what the agent knows" (K-requirements)

### 3.1 Decisions on the table

- **Capability-pack grouping — REJECT.** No pack concept exists in the backend
  (§0.2 — verified: no endpoint, field, or manifest grouping). Inventing packs
  client-side from name prefixes would be fabricated taxonomy. What ships instead,
  from served-but-unused data: **provenance grouping** (`hub | bundled | agent`)
  as filter chips + per-row chips (K4), and the existing category rail (kept). If
  packs become a real backend concept, that's B18.
- **Skill usage evidence — ACCEPT (zero-cost).** `usage` is already in every
  `/api/skills` row (§0.2); it renders as a mono `N uses` meta segment (K5).
  REJECT joining `analytics/usage.skills.top_skills` into the list for
  `last_used_at`: an extra InsightsEngine fetch that covers only top skills —
  partial data presented as complete. Per-skill `last_used_at` in `/api/skills`
  is B17.
- **Toolset usage evidence — ACCEPT (client-side join).** One lazy
  `getAnalytics(30)` fetch on first toolsets-view activation; sum `tools[].count`
  over each `ToolsetInfo.tools` (the join the server comment prescribes, §0.2).
  Labeled `~N calls · 30d` with the R14 best-effort caveat in `title`. Counts are
  exact-local-fact class, not token-gated (Observe A2 rationale).
- **Hub browser — keep, restyle only.** Search fan-out, featured landing,
  preview, security scan, install action-log are recent, complete features; they
  adopt `CapabilityRow` + shared states but change no behavior (N17).

### 3.2 Information architecture

**K1.** Layout kept: filter rail (`aside`) + content pane; views
`skills | toolsets | hub`. Changes inside that frame only.

**K2.** Rail: `PanelItem`s kept (All / Toolsets / Browse hub). Below the view
items, two chrome-labeled groups when in skills view: **provenance** chips —
`hub (N) · bundled (N) · agent (N)` (new, from K4 data; radio-toggle like
categories; `agent` labeled "custom" in UI copy) — then the existing
**categories** list (unchanged behavior, counts kept).

**K3.** Header: enabled-count `afterTitle` + search input `end` slot kept.
Search additionally matches `provenance` (cheap, client-side).

**K4.** `SkillRow` → `CapabilityRow` consumer #1:
- switch: enable toggle (existing optimistic update + toast + per-skill busy set,
  unchanged).
- name: mono, dimmed when disabled (kept).
- badges: provenance chip (`hub`→secondary, `bundled`→outline, `agent`→outline
  labeled `custom`). No enabled-Badge — the Switch **is** the state zone
  (CAP1.2: never two indicators for one state).
- description line kept (`line-clamp-2`, no-description fallback).
- meta: `N uses` (only when `usage > 0`, R4) · category (only when the category
  rail isn't already filtering to it).
- actions: Edit pencil (hover-reveal kept, `aria-label` kept) → `SkillEditorDialog`.

**K5.** `SkillInfo` type unlock per CAP4; `usage`/`provenance` are display-only
(no sorting change; alphabetical sort kept).

**K6.** Skills card header: kept (icon + category title + count Badge + `Learn a
skill` + `New skill` buttons). Both dialogs unchanged: `SkillEditorDialog`
(create/edit SKILL.md, server-side validation errors inline, saved-toast +
list reload) and the Learn dialog (dir/URL/free-text → single-line `/learn` →
`navigate(/chat?learn=…)`) — N17.

**K7.** Toolsets view: grid cards → single-column `CapabilityRow` list:
- icon: `toolsetIcon(name)` (kept, monochrome).
- name: label (sans — human label) with mono `name` in `title`.
- badges: CAP2 state — `active`(success) / `inactive`(outline) /
  `needs setup`(warning, replaces the `text-amber-300` literal — G10 fix).
- description kept.
- meta: `N tools` (count; the full tool-name chip dump moves into `title` and the
  drawer — a 20-chip row per card fails signal-per-pixel) · `~N calls · 30d`
  (K-decision 3; only when analytics resolved and sum > 0).
- actions: `Configure` → `ToolsetConfigDrawer` (unchanged: toggle, provider
  select, env keys, post-setup log tail; refresh-on-change callback kept — but
  fix: `refreshToolsets` currently drops the profile param; pass
  `selectedProfile` like the initial load does — R19).

**K8.** Hub view (`HubBrowser`) — restyle to shared primitives, behavior frozen:
- search bar card + `Update all` kept; `ConnectedHubs` chips keep the
  rate-limited/index-down dimming + titles.
- `HubResultCard` → `CapabilityRow` consumer #2: name mono + trust Badge
  (`trusted`→success, `builtin`→secondary, `community`→warning, else outline —
  existing `trustVisual`) + source Badge + `installed` Badge; description;
  meta = tag chips (≤5, kept) + identifier mono; actions = Details / Install
  (installed → disabled check Button). Timed-out warning row drops the
  `text-amber-400` literal for `text-warning` (G10).
- `SkillDetailDialog` (preview tab, scan tab, repo link, install) and `ScanPanel`
  (verdict header, severity tally, policy chip, findings list) unchanged except
  the same amber/emerald/red literal → token sweep (`text-emerald-400`→
  `text-success`, `text-red-400`→`text-destructive`, `text-amber-400`→
  `text-warning`).
- action-log card: kept verbatim (CAP10 reference implementation).

### 3.3 Data mapping

| Surface | Endpoint | Fields | Display |
|---|---|---|---|
| Skill rows | `GET /api/skills` | `name, description, category, enabled, usage, provenance` | CapabilityRow per K4 |
| Provenance chips | same | `provenance` counts | rail chips (K2) |
| Toggle | `PUT /api/skills/toggle` | — | Switch |
| Toolset rows | `GET /api/tools/toolsets` | `name,label,description,enabled,configured,tools[]` | CapabilityRow per K7 |
| Toolset usage | `GET /api/analytics/usage` | `tools[].{tool_name,count}` ∩ `ts.tools` | `~N calls · 30d` meta |
| Hub landing | `GET /api/skills/hub/sources` | sources/featured/installed | chips + featured rows |
| Hub search | `GET /api/skills/hub/search` | results/source_counts/timed_out | rows + `SearchMeta` |
| Preview / scan | `GET .../preview`, `GET .../scan` | — | detail dialog (unchanged) |
| Installs | `POST .../install|update` + `GET /api/actions/{name}/status` | `lines, running` | action-log card |

### 3.4 States

**K9.** Loading: full-page Spinner → skeletons: rail `block h-48`, content
`row-list rows={8}` (skills) / `rows={4}` (toolsets), `aria-busy`. Profile-switch
keeps the stale-list-until-new-arrives behavior (comment kept).

**K10.** Empty: the three bare `<p>` empties become `EmptyState`:
skills-none → icon Package, action "New skill"; search/category no-match →
action "Clear search/filter"; toolsets no-match → icon Wrench. Hub landing
no-featured keeps its explainer card; hub no-results → `EmptyState icon={Search}`.

**K11.** Errors: initial load failure currently toasts the mislabeled
`t.common.loading` — replace with destructive banner + Retry in the content pane.
Hub search/preview/scan error toasts kept. Toggle failure toast kept.

---

## 4. PLUGINS page — "what extends the agent" (P-requirements)

### 4.1 Decisions on the table

- **Reorder: roster before forms — ACCEPT.** The page currently opens with two
  full-size forms (providers, install) and buries the actual loadout (installed
  plugins) below them. Loadout-first: roster at top, engines (providers) second,
  install last. Rejected alternative — keeping form-first — fails the "what is
  my agent running" glanceability test that defines the section.
- **Memory/context providers stay on this page — ACCEPT.** They are plugin-backed
  engine selection (the options come from the same discovery), i.e. an assignment
  surface exactly parallel to Models' M2. They are NOT moved to Config.
- **Usage evidence — none exists (§0.3).** Zone omitted; B19.

### 4.2 Information architecture

**P1.** Top-to-bottom: (1) `PluginSlot plugins:top`, (2) **plugin roster**,
(3) orphan dashboard plugins (conditional, kept), (4) **engines card**
(providers), (5) **install card**, (6) `PluginSlot plugins:bottom`. Header:
rescan button in `afterTitle` (kept).

**P2.** Roster rows (`PluginRowCard` → `CapabilityRow` consumer #3):
- name mono (plugin ids are technical) · badges: CAP2 state from
  `runtime_status` (`enabled`→success; `disabled`→outline `disabled`;
  `inactive`→outline `inactive` — **fixes the current tone bug where
  `disabled` renders destructive**, a G11 violation: disabled is a choice, not a
  failure) · `v{version}` outline (mono digits; `—` when empty) · source outline
  (`source: user|git|bundled`) · `needs auth` warning Badge when `auth_required`
  (destructive → warning per CAP2: it needs setup, it isn't broken).
- description kept; `dashboard slots: …` line kept (mono, muted);
  `auth_command` `CommandBlock` kept; no-dashboard-tab italic note kept.
- meta: none (no usage data — CAP1.4 honesty).
- actions unchanged in behavior: Enable/Disable · Open tab (Link) · Update (git
  rows) · sidebar visibility Eye/EyeOff toggle · Remove (confirm dialog kept).
  Busy row dims (kept).

**P3.** Engines card (chrome label `engines`): the memory-provider +
context-engine selectors, all current logic frozen (N18): selection Select,
CAP2 status Badge (existing `MEMORY_STATUS_*` maps are already CAP2-conformant),
selection-state Badge (`MEMORY_SELECTION_*` maps kept, incl. `eligible next
session` truthfulness), capabilities/"adapter potential" box, deletion-guarantee
warning, `MemoryProviderSetupHint` (install-deps flow + per-step results),
needs-config notice, dynamic config fields (secret show/hide, `when` visibility,
leave-blank-keeps-secret), Save buttons, missing-provider destructive notice.
Restyle only: 1px borders (already), chrome labels, mono for provider names.

**P4.** Install card: identifier Input (mono, kept) + force/enable Switches +
Install button + hint lines — behavior kept (toasts for warnings/missing_env).
One addition: after a successful install the roster scrolls/flashes the new row
(`plugin_name` is in the response) so the loadout change is visible where the
loadout lives.

**P5.** Orphan dashboard plugins: kept as a muted list under the roster, restyled
to the 1px-box idiom; Open-tab links kept.

### 4.3 Data mapping

| Surface | Endpoint | Fields | Display |
|---|---|---|---|
| Roster | `/api/dashboard/plugins/hub` | `plugins[]` | CapabilityRow per P2 |
| Engines | same | `providers.*` | P3 card |
| Provider fields | `/api/memory/providers/{name}/config` | `fields[]` | dynamic form (kept) |
| Provider setup | `POST /api/memory/providers/{name}/setup` | `results[]` | setup-results block (kept) |
| Install | `POST /api/dashboard/agent-plugins/install` | `plugin_name, warnings, missing_env` | toasts + roster flash |
| Row actions | enable/disable/update/DELETE/visibility | — | unchanged |
| Rescan | `/api/dashboard/plugins/rescan` | `count` | header button + toast |

### 4.4 States

**P6.** Loading: inline spinner → `Skeleton row-list rows={4}` (roster) +
`block h-64` (engines), `aria-busy`.

**P7.** Empty roster: bare "no results" `<p>` → `EmptyState icon={Blocks}`,
title "No plugins installed", description pointing at the install card, action =
"Install a plugin" (scrolls to/focuses the identifier input).

**P8.** Errors: `loadHub` failure currently toasts the mislabeled
`t.common.loading` — destructive banner + Retry replaces it. Mutation error
toasts kept (they surface server `detail` strings, which are good copy).

---

## 5. MCP page — "what the agent can reach" (X-requirements)

### 5.1 Decisions on the table

- **MCP health as agent-status — REJECT.** No persisted or background health
  exists (§0.4); health is only known at explicit-probe time and `AgentStatusBadge`
  is agent-lifecycle vocabulary (CAP2/O2). Faking a standing `live/failed` from a
  possibly-hours-old manual test would violate the no-invented-states rule.
  What ships instead: the probe result as a **last-outcome chip** with its
  timestamp (`reachable · 12 tools · 3m ago` / destructive `unreachable · 3m
  ago`), session-local exactly as today. Standing health needs B21.
- **OAuth login from the dashboard — ACCEPT (endpoint exists, unbound).**
  `POST /api/mcp/servers/{name}/auth` is fully implemented server-side (snapshot/
  restore, 403-registration copy) with no UI. Binding + a `Login` action is the
  same class of zero-backend unlock as Work-spec C6. (X7)
- **Catalog install log tail — ACCEPT.** Background installs already return the
  action name; adopt the skills-hub log card (CAP10). (X8)
- **Tool-selection editing (`server.tools` allowlist) — REJECT this pass.** The
  field is served and a `PUT /api/mcp/servers` whole-map replace could write it,
  but a safe tool-picker UI needs the live tool list per server (i.e. a probe)
  and careful merge semantics — scope it as its own follow-up (Appendix A-2),
  not a rider on a restyle.

### 5.2 Information architecture

**X1.** Top-to-bottom: (1) **servers roster** with count, (2) restart-note strip,
(3) **catalog** with count + intro line, modals unchanged. Header `end`: `Add
Server` (kept).

**X2.** Server rows (`CapabilityRow` consumer #4):
- icon `Server`; name mono; badges: transport Badge — **retoned to
  outline/secondary for both `http` and `stdio`** (the current success/warning
  toning says HTTP is good and stdio is dangerous, which is a G11 semantics leak;
  transport is provenance, not status) · CAP2 `disabled` outline Badge when off ·
  `auth: oauth`/`header` outline Badge when set (currently unrendered though
  served).
- meta (mono): endpoint URL or `command args…` (kept, truncate + `title`) ·
  `N env vars` (kept) · `N/all tools enabled` when `tools !== null` (served,
  currently unrendered).
- detail: last test result — outcome chip per X-decision 1 + tool-name list
  (kept) extended with `· N prompts · N resources` when nonzero (CAP4 unlock).
- actions: Enable/Disable (kept, incl. `restartNote` truthfulness — it stays,
  restyled to the warning-tinted 1px box) · Test (Zap, kept) · `Login` (new, X7;
  shown only for http servers with `auth === "oauth"` or after a test failure
  whose error mentions OAuth/401) · Delete (confirm kept).
- `dimmed` when disabled (kept, moved to the CapabilityRow prop).

**X3.** Roster header adds a one-line summary: `N servers · M enabled` (mono,
muted) — computed client-side; no fake health tally (X-decision 1).

**X4.** Catalog rows (`CapabilityRow` consumer #5):
- name mono · transport Badge (X2 toning) · `auth: <type>` outline · source link
  (`source ↗`, kept) or Badge · `installed` success Badge + `disabled` outline
  (kept).
- description; connection detail (`Endpoint:`/`Runs:` mono, kept); `Installs
  from:` + `bootstrap commands` + `Setup notes` disclosures kept **verbatim** —
  they are the documented trust model (N19); per-entry diagnostics warnings kept.
- actions: Install (env-var modal flow kept: required-env password inputs,
  first-missing-field error) → on `background: true`, the CAP10 action-log card
  appears at the top of the catalog section tailing
  `GET /api/actions/{action}/status` until `running === false`, then both lists
  reload (today's immediate reload shows nothing changed for slow clones).

**X5.** Add-server modal: unchanged fields/validation (name/transport/url/
command/args/env parse). Container polish only.

**X6.** OAuth login (new, zero-backend): `api.authMcpServer(name)` binding
(CAP4); clicking `Login` shows a persistent inline "waiting for browser flow…"
row on the server (the request blocks for up to minutes — no global spinner),
then renders the returned tools as a fresh test result or the server's error
copy (including the pre-approved-clients 403 explanation, which the backend
already writes for us) in the detail zone. Concurrent logins on the same server
are prevented by the existing single-`testing`-style busy key.

**X7/X8.** (Defined above in decisions — numbered for reviewer reference:
X7 = OAuth binding + Login action; X8 = catalog install action-log adoption.)

### 5.3 Data mapping

| Surface | Endpoint | Fields | Display |
|---|---|---|---|
| Server rows | `GET /api/mcp/servers` | summary fields incl. `auth`, `tools` | CapabilityRow per X2 |
| Test | `POST .../{name}/test` | `ok, error, tools[], prompts, resources` | outcome chip + detail |
| Login | `POST .../{name}/auth` | `ok, error, tools[]` | X6 flow |
| Toggle | `PUT .../{name}/enabled` | — | button + restart note |
| Catalog | `GET /api/mcp/catalog` | entries + diagnostics | CapabilityRow per X4 |
| Catalog install | `POST /api/mcp/catalog/install` (+ `/api/actions/{a}/status`) | `background, action` | sync toast or log card |

### 5.4 States

**X9.** Loading: full-page Spinner → `Skeleton row-list rows={3}` (servers) +
`rows={5}` (catalog), `aria-busy`.

**X10.** Empty: servers → `EmptyState icon={Server}`, title "No MCP servers",
description "Add a server or install one from the catalog below", action = "Add
Server" (opens the modal). Catalog-empty card → `EmptyState icon={Package}`.

**X11.** Errors: `loadServers`/`loadCatalog` failures currently only toast,
leaving blank sections — each section gets an inline destructive banner + Retry
(section-scoped: a broken catalog must not hide configured servers). Test/auth
failures render in the row detail zone (existing pattern, kept).

---

## 6. Non-goals and risks (continuing Work/Observe numbering)

**N13.** No backend changes of any kind in the main spec — every requirement is
frontend-only against verified existing endpoints (Appendix B holds the rest).

**N14.** The Ollama discovery/configure flow's security posture is untouchable:
explicit-action discovery (never on mount), localhost/private-only URL guard,
egress-mode write, auth-provider deactivation. Any diff to
`LocalOllamaSetupCard`'s fetch triggers or to the request payloads is a review
flag.

**N15.** No provider-credential or OAuth-provider UI moves onto ModelsPage; Env
(Keys) keeps `OAuthProvidersCard` and all secret entry. (MCP-server OAuth, X6, is
a different flow on a different page and is in scope.)

**N16.** Model assignment logic frozen: `ModelPickerDialog` internals,
`confirm_required` expensive-model round-trip, `ModelReloadConfirm`, aux
`__reset__` semantics, MoA preset CRUD + no-recursive-MoA guard, the
`applies to new sessions` contract. Restyle containers only.

**N17.** Skills flows frozen: toggle write path, SkillEditorDialog validation
round-trip, Learn-a-skill `/chat?learn=` handoff, hub search fan-out/dedupe,
preview/scan/install/update action plumbing, profile scoping via
`useProfileScope` on every call.

**N18.** Plugin/provider write paths frozen: memory-provider save (visible-fields
filter, secret keep-if-blank), provider setup runner, context-engine save,
plugin enable/disable/update/remove/visibility endpoints and their gating flags
(`can_remove`, `can_update_git`).

**N19.** The MCP trust-model disclosures (command/args/url, install source,
bootstrap commands, setup notes) must remain visible pre-install — do not
collapse them away in the restyle beyond the existing `<details>`.

**N20.** No new polling loops anywhere in the section except the two existing
bounded action-log polls (skills hub, X8's reuse of the same machinery); no
virtualization; no ⌘K work; i18n via existing `t.*` tables with English
fallbacks (new keys optional-typed, O5 pattern).

**R15.** Concurrent-edit hazard: another process is editing this repo; all four
pages (and `api.ts`) must be rebased at build time. Highest-risk merge zones:
ModelsPage's `UseAsMenu`/assignment plumbing and the skills HubBrowser (both
recently reworked).

**R16.** `enabled` ≠ running, everywhere in this section: skills/toolsets apply
to new sessions, MCP toggles need a gateway restart, plugin enable takes effect
on next load, memory selection is `eligible next session`. Every state badge
`title` must carry the applicable "takes effect…" copy — the section must never
imply a live hot-swap it can't deliver (the backend copy strings already exist;
reuse them).

**R17.** MCP `/test` and `/auth` block server-side for seconds-to-minutes
(stdio cold starts, browser flows). UI must keep per-row busy state (never a
page-level spinner) and tolerate a navigation-away mid-flight (state is
row-local and droppable; the backend flow completes or restores tokens on its
own).

**R18.** Frontend mirrors of backend tables can drift: `AUX_TASKS` ↔
`_AUX_TASK_SLOTS`, memory status/selection label maps ↔ backend enums,
`CATEGORY_LABELS`. Keep the "must match" comments adjacent to each table; new
unknown enum values must render as their raw string, never crash (the CAP2
mappers default to outline/raw-label).

**R19.** `SkillsPage.refreshToolsets` omits the profile argument the initial
load passes — on a non-default profile, a drawer change refreshes the *wrong
profile's* toolsets. Fix in the K7 migration (pass `selectedProfile ||
undefined`).

**R20.** The K8 toolset-usage join inherits InsightsEngine's best-effort
extraction (R14): label with `~`, caveat in `title`, and never let an analytics
fetch failure break the toolsets view (degrade to no meta segment, log only).

**R21.** `CapabilityRow` serves five consumers with different densities — resist
prop creep. If a consumer needs more than the CAP3 prop surface, it composes its
own body in `detail`/`meta` rather than growing the shared interface (the
DataTable lesson: shared primitives stay dumb).

---

## Appendix A — Out-of-scope frontend enablers (continuing Observe's A-numbering)

**A-2.** MCP per-server tool-selection editor: UI over the served `tools`
allowlist via `PUT /api/mcp/servers` whole-map replace, seeded from a live
`/test` tool list. Needs its own design (merge semantics, stale-probe handling).

**A-3.** SessionsPage/AnalyticsPage URL-param support (Observe A-1) is the
prerequisite for every "used by N runs" deep link rejected in CAP7.

## Appendix B — "Needs backend" (explicitly NOT in the main spec)

**B16. Model/skill filters on sessions.** `model=` (and ideally `skill=`) params
on `GET /api/sessions` → unlocks per-model "recent runs" drawers on ModelsPage
and true CAP7 cross-links (with A-3).

**B17. Per-skill `last_used_at`.** Add to `GET /api/skills` rows (the usage
store already tracks timestamps) → "last used 2d ago" on skill rows without the
partial top-skills join rejected in §3.1.

**B18. First-class skill packs/collections.** If grouping beyond
category/provenance is wanted, it must be a backend concept (manifest field or
hub metadata), not a client-side naming heuristic.

**B19. Plugin usage telemetry.** Tool-call counts attributed to plugin-provided
tools (the registry knows `provides_tools`) → gives Plugins its empty usage zone.

**B20. MCP tool-call attribution.** Per-server call counts (the agent knows
which server owns each MCP tool) → usage evidence on server rows.

**B21. Persisted MCP health.** Background/interval probe with `last_probe_at` +
`last_probe_ok` on the server summary (or an events channel) → would justify a
standing health indicator; until then health stays probe-time-only (X-decision 1).

**B22. Restart-required signal.** A server-computed `pending_restart: true` on
MCP servers / plugins whose config differs from the running gateway's snapshot →
replaces the blanket restart-note string with per-item truth (R16).

**B23. Toolset usage server-side.** Move the K8 client join into
`GET /api/tools/toolsets` (`calls_30d` per toolset) — the server already owns
both sides of the join and can do it exactly.
