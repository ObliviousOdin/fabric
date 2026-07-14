# WORK Section Revamp — Implementation Spec ("Agentic Look")

> **Historical implementation record — superseded for current design decisions.**
> Use [`web/DESIGN.md`](../../web/DESIGN.md) and the
> [Workspace/Admin guide](../../website/docs/user-guide/workspace-admin.md)
> as the active contract. Route names and component details below remain useful
> archaeology, but the inherited “agentic/terminal-grade” visual direction,
> teal identity, pervasive display typography, and legacy nav grouping are not
> current Fabric guidance.


Scope: the three pages in the **Work** nav group — Sessions, Cron, Chat — per the design
direction in `docs/design/dashboard-revamp-research.md` ("terminal-grade minimalism",
Langfuse-style run anatomy, AG-UI event-driven surfaces, value-density metric).

Status: implementation-ready. Every requirement is numbered (G/S/C/CH/N/R/B) for
reviewer reference. One design is specified per surface — no options.

Source-of-truth files audited (2026-07-13):

- Frontend: `web/src/pages/SessionsPage.tsx`, `web/src/pages/CronPage.tsx`,
  `web/src/pages/ChatPage.tsx`, `web/src/components/ChatSidebar.tsx`,
  `web/src/components/ChatSessionList.tsx`, `web/src/components/ui/{DataTable,EmptyState,Skeleton,PageToolbar}.tsx`,
  `web/src/lib/api.ts`
- Backend: `fabric_cli/web_server.py` (routes listed in §0), `fabric_state.py`
  (SessionDB schema + `list_sessions_rich` / `get_messages` / `list_cron_job_runs`),
  `cron/jobs.py` (job state machine), `tui_gateway/server.py` (`_emit` event catalog)

---

## 0. Data audit — what the backend actually serves TODAY

Everything in the main spec is buildable against these endpoints as they exist now.
Anything requiring new server work is in Appendix B only.

### 0.1 Sessions

| Endpoint | Shape (verified in `web_server.py`) |
|---|---|
| `GET /api/sessions?limit&offset&order=created\|recent&archived=exclude\|only\|include&source&exclude_sources&min_messages&cwd_prefix&profile` | `{sessions: Row[], total, limit, offset}` |
| `GET /api/sessions/search?q&profile` | `{results: [{session_id (lineage tip), lineage_root, snippet (matches wrapped in `>>>…<<<`), role, source, model, session_started}]}` |
| `GET /api/sessions/{id}` | full session row (incl. `system_prompt`) |
| `GET /api/sessions/{id}/messages?limit&offset` (limit clamped ≤500) | `{session_id, messages: Msg[], pagination: {limit, offset, returned}}` — **no total; use row `message_count`** |
| `GET /api/sessions/stats` | `{total, active_store, archived, messages, by_source}` |
| `GET /api/sessions/empty/count`, `DELETE /api/sessions/empty`, `POST /api/sessions/bulk-delete`, `PATCH /api/sessions/{id}` (title/archived), `GET /api/sessions/{id}/export`, `POST /api/sessions/prune` (rich filters + `dry_run`) | as currently used by SessionsPage |
| `GET /api/status` | gateway state, `gateway_platforms`, `active_sessions` |

**Session list Row** = `SELECT s.*` minus `system_prompt`/`model_config`, plus computed
fields. Fields available *today* (the TS `SessionInfo` type under-declares — several are
already in the JSON payload):

- Declared in TS: `id, source, model, title, started_at (epoch s), ended_at, last_active,
  is_active (derived: not ended AND active <300s), message_count, tool_call_count,
  input_tokens, output_tokens, preview, parent_session_id`
- **Present in payload but NOT yet in the TS type** (frontend-only unlock): `cwd`,
  `git_branch`, `end_reason`, `estimated_cost_usd`, `actual_cost_usd`, `api_call_count`,
  `archived (bool)`, `cache_read_tokens`, `reasoning_tokens`, `chat_type`, `user_id`.

**Message shape** (`get_messages` returns `SELECT *` per row): `id, role
(user|assistant|system|tool), content, tool_calls (parsed → [{id, function:{name,
arguments}}]), tool_name, tool_call_id, timestamp, finish_reason, reasoning…` — roles
and tool calls ARE distinguishable, so a chronology view is fully supported. Per-tool
**duration is NOT persisted** (only emitted live via `tool.complete` events) — see B4.

Compaction-handoff rows (prefix `[CONTEXT COMPACTION…]` / `[CONTEXT SUMMARY]:` with the
END-marker split, issue #29824) must keep their special rendering — the parsing helpers
in SessionsPage (`splitCompactionContent`, `COMPACTION_PREFIXES`) move with the timeline.

There is **no push channel** for the session list; `/api/events` requires a chat channel
id. List liveness stays poll-based (current 5 s overview poll + head-id change detection
in `session-refresh.ts`). Global event feed → B1.

### 0.2 Cron

| Endpoint | Shape |
|---|---|
| `GET /api/cron/jobs?profile=all\|<name>` | `CronJob[]` |
| `GET /api/cron/jobs/{id}` | one job |
| **`GET /api/cron/jobs/{id}/runs?limit≤100`** | `{runs: SessionRow[], limit}` — run sessions (`id = cron_{job}_{ts}`, `source="cron"`, same row shape as /api/sessions incl. tokens, message_count, is_active). **Exists today, unused by the web frontend — no `api.ts` binding yet.** |
| `POST .../pause`, `.../resume`, `.../trigger`, `PUT`, `DELETE`, `POST /api/cron/jobs`, `GET /api/cron/delivery-targets`, `GET /api/cron/blueprints` | as currently used |

`CronJob` fields: `id, name, prompt, script, skills[], schedule {kind, expr, run_at,
display}, schedule_display, repeat {times, completed}, enabled, state, deliver, model,
provider, no_agent, enabled_toolsets[], workdir, profile, last_run_at (ISO),
next_run_at (ISO), last_status ("ok"|"error"|null), last_error, last_delivery_error`.

Job `state` machine (`cron/jobs.py`): `scheduled | paused | error | completed`
(+ UI-derived `disabled` when `enabled === false`). There is **no persisted
"running now"** job state; a live run is inferable only from the runs list
(`is_active` on the newest run session) — see C10, B5.

### 0.3 Chat

- `WS /api/pty` — xterm/PTY transport. **Untouchable** (N1).
- `WS /api/ws` — JSON-RPC sidecar; connection states `idle | connecting | open | closed |
  error`; `session.create` sidecar; credential warnings.
- `WS /api/events?channel=<id>` — rebroadcast of **every** dispatcher emit from the PTY
  child. Verified event catalog (`tui_gateway/server.py _emit` call sites):
  `session.info` (model, provider, cwd, title, personality, reasoning_effort,
  service_tier, credential_warning…), `tool.start {tool_id, name, context, args_text?}`,
  `tool.complete {tool_id, name, args, duration_s, result, summary, inline_diff?,
  todos?}`, `tool.generating {name}`, `reasoning.delta/available`, `thinking.delta`,
  `message.start/delta/complete`, `status.update {kind, text}`, `approval.request`,
  `error`. **ChatSidebar currently consumes only `session.info` (title) and
  `dashboard.new_session_requested`** — the tool/reasoning stream is untapped, and it
  is the single biggest agentic-look win available with zero backend work.
- `GET /api/model/info?profile` — `{model, provider, auto/config/effective_context_length,
  capabilities {supports_tools, supports_vision, supports_reasoning, context_window,
  max_output_tokens, model_family}}`.
- `GET /api/sessions?order=recent` powers ChatSessionList.

---

## 1. Shared foundations (G-requirements)

### 1.1 One status vocabulary

**G1.** Define a single canonical status set used by all three pages:
`live | idle | scheduled | paused | failed | done`. Real data maps onto it as follows
(no invented states):

| Canonical | Tone (Badge) | Sessions | Cron job | Cron run | Chat connection |
|---|---|---|---|---|---|
| `live` | `success` + pulsing dot | `is_active === true` | — | run row `is_active` | sidecar `open` |
| `idle` | `secondary` | `ended_at === null` && stale (>300 s) | — | — | `idle` / `closed`; `connecting` uses `idle` tone with label override "connecting…" |
| `scheduled` | `outline` | — | `state === "scheduled"` (enabled) | — | — |
| `paused` | `warning` | — | `state === "paused"` OR `enabled === false` (label "disabled") | — | — |
| `failed` | `destructive` | — | `state === "error"` | — | sidecar `error` |
| `done` | `secondary`, no dot | `ended_at !== null` | `state === "completed"` | `ended_at !== null` | — |

Cron `last_status` ("ok"/"error") is a *last-outcome* signal, rendered as a separate
small chip (`success`/`destructive`), never conflated with the job's scheduling state.

**G2.** New shared component `AgentStatusBadge` in `web/src/components/ui/`:

```tsx
export type AgentStatus = "live" | "idle" | "scheduled" | "paused" | "failed" | "done";
export interface AgentStatusBadgeProps {
  status: AgentStatus;
  /** Override the default label (e.g. "connecting…", "disabled"); default = status word. */
  label?: string;
  /** Force/suppress the pulsing dot; default: true only for "live". */
  pulse?: boolean;
  className?: string;
}
```
Renders the DS `Badge` with the G1 tone + an optional `h-1.5 w-1.5 animate-pulse
rounded-full bg-current` dot (the exact idiom already used for the "live" badge in
SessionsPage). Labels lowercase, `text-xs`. All ad-hoc status badges on the three pages
are replaced by this component.

### 1.2 Shared micro-primitives

**G3.** `MonoId` (`components/ui/MonoId.tsx`):
```tsx
interface MonoIdProps { id: string; /** chars shown, default 8 */ chars?: number; copy?: boolean; className?: string }
```
Renders `font-mono-ui text-xs text-muted-foreground` truncated id (`id.slice(0, chars)`),
`title` = full id, click-to-copy with a transient check icon when `copy` (default true).
Used for session ids, cron job ids, run ids, tool_call ids.

**G4.** `RelativeTime` (`components/ui/RelativeTime.tsx`):
```tsx
interface RelativeTimeProps { value: number | string | null | undefined; /** epoch-seconds OR ISO string */ className?: string }
```
Normalizes the two backend timestamp dialects (sessions = epoch seconds float, cron =
ISO strings), renders via the existing `timeAgo()` util, `title` = absolute
`toLocaleString()`, re-renders on a shared 30 s interval (one module-level ticker, not
one interval per instance). Mono, `tabular-nums`.

**G5.** `NextRunCountdown` (`components/ui/NextRunCountdown.tsx`):
```tsx
interface NextRunCountdownProps { nextRunAt: string | null | undefined; className?: string }
```
Renders `in 2h 14m` / `in 45s` (mono, tabular-nums) from an ISO timestamp, ticking on
the same shared 30 s ticker (1 s tick only when <2 min remain). `nextRunAt` null/past →
renders `—` (past-due also gets `text-warning`). Cron-only today but generic.

**G6.** `RunRow` (`components/ui/RunRow.tsx`) — the shared "an agent ran" row used by
the Sessions list AND the Cron run-history drawer (justified across two pages; the
Chat session list stays on its lighter ListItem, see CH9):
```tsx
interface RunRowProps {
  title: ReactNode;                 // sans; italic-muted fallback handled by caller
  status: AgentStatus;              // → AgentStatusBadge
  statusLabel?: string;
  id: string;                       // → MonoId
  sourceIcon?: LucideIcon;          // SOURCE_CONFIG glyph
  model?: string | null;            // short name, mono chip
  meta?: ReactNode;                 // counters line (msgs · tools · tokens · cost)
  timestamp: number | string;       // → RelativeTime (last_active / started_at)
  selected?: boolean;               // checkbox state (Sessions only)
  onSelectClick?: (e: React.MouseEvent) => void; // omit → no checkbox rendered
  expanded?: boolean;
  onToggle?: () => void;
  actions?: ReactNode;              // trailing icon buttons
  children?: ReactNode;             // expansion body (timeline)
  className?: string;
}
```
Visual contract: 1px `border-border` box, no radius beyond theme default, hover
`bg-secondary/30`; `selected` → `border-primary/40 bg-primary/[0.06]`; `status ===
"live"` (and not selected) → `border-success/30 bg-success/[0.03]` (exact classes
already proven in SessionsPage — selection beats live, keep that precedence comment).
Grid: `[checkbox?] [source glyph] [title + chips row / meta row] [actions]`, meta row is
one wrapping `text-xs text-muted-foreground` line with `·` separators.

**G7.** `TimelineNode` (`components/ui/TimelineNode.tsx`) — Langfuse-inspired chronology
node for session transcripts:
```tsx
interface TimelineNodeProps {
  kind: "user" | "assistant" | "system" | "tool" | "handoff";
  label: string;                    // role label or "tool: name" or "Context handoff"
  timestamp?: number;               // → RelativeTime
  hit?: boolean;                    // FTS match ring + Badge, as today
  children: ReactNode;              // Markdown / pre content / ToolCallBlock list
}
```
Renders a left rail: 2px vertical line (`bg-border`) with a role-toned dot
(`user`→primary, `assistant`→success, `tool`→warning, `system`/`handoff`→muted), header
line `[dot] [label — text-xs font-semibold role-tone] [RelativeTime]`, body indented
under the rail. Replaces the full-width tinted `MessageBubble` blocks — the tint moves
from block backgrounds to the rail dot + label (density: less ink, same signal). The
existing `#29824` compaction split logic is retained verbatim and feeds `kind:"handoff"`.

**G8.** Summary strips use the existing DS `Stats` primitive
(`@nous-research/ui .../stats`, `items: {label, value}[]`) — values `tabular-nums`
mono, labels lowercase chrome style. The hand-rolled flex stat strip in SessionsPage is
replaced by it. Where a value needs a tone (e.g. failing count in red) pass a
`{key, node}` value.

### 1.3 Visual language rules (apply on all three pages)

**G9.** Type assignment: `text-display` uppercase-tracked **only** for chrome labels
(card headers, rail section titles, table headers — DataTable already does this);
`font-mondwest normal-case` for row titles/human text (existing convention);
`font-mono-ui` for every technical readout — ids, model names, cron expressions, token
counts, durations, countdowns, paths, tool names. No new font faces.

**G10.** Elevation = 1px `border-border` only. No new shadows (the terminal wrapper's
existing shadow in ChatPage is grandfathered, N1). No inline `oklch()`/hex — theme
tokens only (`text-success/warning/destructive/primary`, `bg-*/[0.03–0.10]` tints).

**G11.** Single accent: `primary` is reserved for selection/active/interactive
affordances. Status semantics only via `success/warning/destructive` tones through
`AgentStatusBadge`/Badge. Source icons stay monochrome per the existing
`SOURCE_CONFIG` comment.

**G12.** Density: no fixed row heights; spacing via Tailwind utilities so
`--theme-spacing-mul` keeps working. Counters and ids always `tabular-nums`.

**G13.** All three pages adopt `PageToolbar` for their filter/action rows (SessionsPage
and CronPage currently hand-roll these), and `EmptyState`/`Skeleton` for empty/loading
(SessionsPage currently hand-rolls both).

---

## 2. SESSIONS page — "run ledger" (S-requirements)

### 2.1 Information architecture

**S1.** Kill the `overview | list` Segmented split. One view, top-to-bottom:

1. **Summary strip** (leads, above the fold): `Stats` items — `sessions` (total),
   `active now` (green when >0; from `stats.active_store` is *store*-active, so use the
   count of `is_active` rows in the freshest overview fetch for "live now" and keep
   `in store` as its own stat), `messages`, `archived`; trailing cluster of per-source
   outline badges (`by_source`). Data: existing `/api/sessions/stats` + overview poll.
2. **Gateway strip** (conditional): the current alerts block (gateway `startup_failed`,
   platform `fatal`/`disconnected`) restyled as a single-row destructive-tinted 1px box;
   healthy platforms render as a one-line row of `platform-name` + `AgentStatusBadge
   status="live"` chips replacing the whole `PlatformsCard` card. The "Recent sessions"
   card is deleted outright — the ledger below *is* the recents.
3. **Toolbar** (`PageToolbar`): filters = FTS search input (unchanged behavior) +
   **source filter** `Segmented`/chips (`all | cli | telegram | discord | slack |
   whatsapp | cron`, driven by the server's existing `source=` param — resets page and
   clears selection like `updateSearch` does); actions = "Delete empty (N)"
   (unchanged gating) + compact pagination. "Prune old sessions" stays in the page
   header `end` slot.
4. **Bulk-selection bar** (unchanged logic; restyle only to the 1px-border idiom it
   already approximates).
5. **Run ledger**: `RunRow` list (S2), then bottom pagination.

**S2.** Each session renders as a `RunRow` "run":
- Leading: checkbox (existing shift-range semantics untouched), source glyph.
- Title line: title, else `preview.slice(0, 60)`, else italic "Untitled";
  `AgentStatusBadge` per G1 (live / idle / done).
- Meta line (mono, `·`-separated): `MonoId(id)` · model short-name · `N msgs` ·
  `N tools` (when >0) · `↑{input_tokens} ↓{output_tokens}` compact-formatted (`12.4k`)
  when either >0 · `$0.0123` from `estimated_cost_usd` when present (S3) ·
  `RelativeTime(last_active)`.
- Trailing actions (identical behavior, icons unchanged): resume-in-chat, rename
  (inline editor kept as-is), export, delete.
- FTS snippet line (with `>>>…<<<` highlight → `SnippetHighlight`, kept) below meta.

**S3.** Extend the TS `SessionInfo` interface in `api.ts` with the already-served
fields: `archived: boolean`, `end_reason?: string | null`, `cwd?: string | null`,
`git_branch?: string | null`, `estimated_cost_usd?: number | null`,
`actual_cost_usd?: number | null`, `api_call_count?: number`. Frontend-only change; no
backend edits (verified: list rows are `s.*` minus `system_prompt`/`model_config`).

**S4.** Row expansion = **chronology**, not bubbles: the expansion body renders
`TimelineNode`s from `getSessionMessages`. Mapping: `role` → `kind`; `tool_calls` on
assistant nodes render the existing `ToolCallBlock` (collapsed, mono name + `MonoId`
of `tool_call_id`, pretty-printed args on expand) nested under the assistant node;
`role:"tool"` rows render as `kind:"tool"` with `label = "tool: " + tool_name`;
compaction rows → `kind:"handoff"` via the retained #29824 split. Auto-scroll-to-first-
FTS-hit behavior (`data-search-hit` + `scrollIntoView`) is preserved.

**S5.** Long transcripts: when `session.message_count > 200`, fetch the tail first —
`getSessionMessages(id, { limit: 200, offset: message_count - 200 })` (add the
optional `limit`/`offset` params to the existing `api.getSessionMessages`; endpoint
already supports them) — and render a "Load earlier messages" ListItem at the top of
the timeline that pages backwards by 200. No total in the pagination object; derive
from `message_count`.

**S6.** Session detail context header inside the expansion (above the timeline), one
mono line: `cwd` (when present) · `git_branch` (when present) · `end_reason` (when
ended) · full model id. All fields available per S3.

**S7.** Polling/liveness: keep the existing 5 s overview poll + `shouldRefreshSessions`
head-id silent refresh exactly as-is (it is the only liveness mechanism; B1 replaces it
later). The poll also refreshes the "active now" stat (S1.1).

**S8.** Preserved flows (behavioral no-regression checklist): FTS search filtering the
current page against `snippetMap` (existing quirk kept — do not "fix" it into a server
round trip in this pass), debounce 300 ms, bulk shift-select anchor semantics,
select-all-on-page, bulk delete, delete-empty with global count refresh, single delete,
rename validation errors, export (blob download incl. `X-Fabric-Session-Token` header),
prune dialog, `PluginSlot name="sessions:top|bottom"`, page-header total badge and
"Prune" end-slot, `resume=` navigation to `/chat`.

### 2.2 Sessions states

**S9.** Loading: replace the full-page Spinner with layout-shaped `Skeleton`s — one
`line` (summary strip), one `block h-10` (toolbar), `row-list rows=6` (ledger).
`aria-busy="true"` on the container (CronPage already models this).

**S10.** Empty: `EmptyState icon={Clock}` — no sessions: title `t.sessions.noSessions`,
description `t.sessions.startConversation`, action = "Open chat" button navigating to
`/chat`. No search matches: title `t.sessions.noMatch`, action = "Clear search". Source
filter active with no rows: description names the filter, action clears it.

**S11.** Errors: list-fetch failures currently swallowed (`catch(() => {})`) — surface
a destructive-tinted 1px banner with a Retry button (reuses `loadSessions(page)`);
per-row message-fetch errors keep the inline error text but add Retry. Toasts for
mutations unchanged.

---

## 3. CRON page — "scheduled agents" (C-requirements)

### 3.1 Information architecture

**C1.** Top-to-bottom: (1) `Jobs | Blueprints` Segmented (kept), (2) **summary strip**,
(3) toolbar, (4) job roster, (5) modals unchanged.

**C2.** Summary strip (`Stats`, jobs view only): `jobs` (count) · `next run` (soonest
future `next_run_at` across jobs as `NextRunCountdown`; `—` when none) · `paused`
(count where paused/disabled; warning tone when >0) · `failing` (count where
`state==="error"` OR `last_status==="error"`; destructive tone when >0). All computed
client-side from the already-fetched jobs array.

**C3.** Toolbar (`PageToolbar`): filters = the existing profile `Select` (moved out of
the section-header row); the `H2 "Scheduled jobs (N)"` heading is dropped — the count
lives in the summary strip. Actions: none in-body ("Create" stays in the page header
end slot, unchanged).

**C4.** Job card → **agent row**. Keep `Card`/`CardContent` as the container (1 per
job) but restructure the content to the run-ledger grammar:
- Line 1: job title (sans) · `AgentStatusBadge` per G1 (`scheduled | paused (label
  "disabled" when enabled===false) | failed | done`) · **last-outcome chip**: when
  `last_status` present, a small Badge `ok`(success)/`error`(destructive) with
  `title={last_error ?? last_run_at}`.
- Line 2 (mono meta, `·`-separated): human schedule via existing `describeSchedule`
  (sans is fine here — it's human text) with `title` = raw `schedule.expr` (raw expr
  itself renders mono in the tooltip/title) · `next: <NextRunCountdown nextRunAt>` ·
  `last: <RelativeTime last_run_at>` · `repeat: N/M | forever` (existing
  `getRepeatDisplay`).
- Line 3 (chips, outline Badges — trimmed): profile · deliver (non-local only) ·
  `N skills` (title lists them) · mode when ≠ `agent` · model short-name **shown as its
  mono name** (replace today's uninformative literal "model" badge with the actual
  `provider/model` short form, `title` = full) · `N toolsets`.
- Prompt preview line and the two error lines (`last_delivery_error`, `last_error`)
  kept, `last_error` truncated to 2 lines with full text in `title`.
- Trailing actions unchanged: pause/resume, trigger (Zap), edit, delete.

**C5.** Countdown is the agentic centerpiece: `next:` uses `NextRunCountdown` (G5);
when the computed remaining time is negative (missed/past-due while enabled), render
`overdue` in `text-warning`. Data: `next_run_at` ISO already served.

**C6.** **Run history drawer** (new capability, zero backend work): each job row is
expandable (chevron affordance on the row body, same gesture as Sessions). On first
expand, call the **new** `api.getCronJobRuns(id, profile, limit=10)` binding for
`GET /api/cron/jobs/{job_id}/runs` (endpoint exists; add the fetch wrapper +
`{runs: SessionInfo[]; limit: number}` type to `api.ts`). Render each run as a
`RunRow` (no checkbox, no actions except "Open in Sessions" — navigates to
`/sessions` — and expand-to-timeline reusing S4's timeline against
`getSessionMessages(run.id, profile)`): status `live` when `is_active` else `done`;
meta = `MonoId(run.id)` · duration (`ended_at - started_at`, mono `1m 42s`) · `N msgs`
· `N tools` · tokens · `RelativeTime(started_at)`. Do **not** invent per-run
success/failure — outcome is job-level only (B5); runs are neutral `done`.

**C7.** Trigger feedback loop: after `triggerCronJob` succeeds, expand the job's run
drawer (if closed), and poll `getCronJobRuns(id, …)` + `loadJobs()` every 5 s while the
newest run `is_active`, stopping at settle or after 3 min. This makes "Trigger now"
visibly *run* instead of just toasting.

**C8.** Profile scoping, create/edit modal internals (`CronJobFormFields`,
`ScheduleBuilder`, advanced fields, validation messages), blueprints view, and delete
confirm flow are behaviorally untouched (N4). Only container polish allowed on the
modals: header label to chrome style, 1px borders (already true).

**C9.** Timestamp rendering: replace `formatTime` (`toLocaleString`) with
`RelativeTime` in row meta (absolute time preserved in `title`); modals/tooltips keep
absolute strings.

**C10.** "Running now" indicator: when a job's newest run (from an expanded drawer or
the C7 poll) `is_active`, show `AgentStatusBadge status="live"` next to the job title,
superseding the scheduled chip until the run ends. Only rendered when run data is
actually loaded — never inferred from `last_run_at` alone.

### 3.2 Cron states

**C11.** Loading: existing Skeleton block layout kept, plus one `line` for the summary
strip. Run-drawer loading = `Skeleton variant="row-list" rows={3}` inside the drawer.

**C12.** Empty: existing `EmptyState icon={Clock}` in Card kept (title/description/CTA
unchanged). Empty run drawer: `EmptyState` compact (`className="py-6"`), title
"No runs yet", description "Trigger now to run this job immediately", action = Trigger
button (same handler as the row's Zap).

**C13.** Errors: `loadJobs` failure currently toasts `t.common.loading` (a mislabel) —
replace with a destructive banner + Retry in the jobs view body; run-drawer fetch
failure = inline destructive text + Retry. Mutation toasts unchanged.

---

## 4. CHAT shell — "mission control rail" (CH-requirements)

The terminal pane (xterm + PTY + clipboard + resize machinery) is out of scope (N1).
All changes are in the right rail (`ChatSidebar`, `ChatSessionList`) and their mobile
sheet arrangement — the shell around the terminal, not the terminal.

### 4.1 Agent status rail (ChatSidebar)

**CH1.** Rail order (desktop `lg:w-60` column and the mobile sheet render the same
stack): (1) **Agent card**, (2) Reasoning card (existing, gated on
`supports_reasoning`), (3) **Activity feed** (new), (4) notices/banners (existing),
(5) session switcher (ChatSessionList) filling remaining height.

**CH2.** Agent card (evolves the current model card): chrome label `agent`; body rows:
- `model` — mono short name, existing picker Button + ChevronDown behavior and the
  whole ModelPickerDialog / ModelReloadConfirm / REST `setModelAssignment` flow
  unchanged (N5). `title` = full model id.
- `context` — new read-only mono line `ctx 200k` from `effective_context_length`
  (already fetched via `getModelInfo`; format compact, hide when 0).
- connection — `AgentStatusBadge` mapped per G1 from the sidecar `ConnectionState`
  (`open→live`, `connecting→idle` + label "connecting…", `idle/closed→idle`,
  `error→failed`), replacing the current `STATE_LABEL/STATE_TONE` Badge.
- When `session.info` has `cwd`: a truncated mono `cwd` line (`title` = full path).

**CH3.** **Activity feed** (new card, chrome label `activity`): consume the
**already-open** `/api/events` subscription in ChatSidebar (extend the existing
`ws.addEventListener("message")` switch — no new socket). Handle:
- `tool.start` → append row: warning-toned dot, mono tool `name`, muted `context`,
  ticking "…running" until matched `tool.complete` (match on `tool_id`).
- `tool.complete` → finalize row: `duration_s` (mono, `1.8s`), `summary` (muted,
  truncated, `title` = full). No result bodies, no `inline_diff` rendering in the rail
  (the terminal already shows them) — the rail is a ticker, not a transcript.
- `message.start` / `message.complete` → transient "responding…" state line
  (success-toned dot) at the feed head; `thinking.delta` / `reasoning.delta` →
  transient "reasoning…" state line (muted, italic). These are single mutually
  exclusive state lines, not appended rows.
- `approval.request` → pinned warning row "waiting for approval — respond in the
  terminal" until any subsequent event arrives for that session.
- `status.update {kind, text}` → muted one-line row.
Retention: keep the last **20** tool rows in memory (FIFO), newest at top; feed body
`max-h` ≈ 40vh, `overflow-y-auto`. Feed resets when `channel`/`version` changes
(same scope-key reset the sidebar already implements). Card hidden until the first
event arrives (fresh PTY with no activity → no empty box).

**CH4.** Live title: existing `session.info` → `titleFromSessionInfoPayload` →
page-header title flow unchanged. Additionally mirror the title as the first line of
the Agent card when present (mono-adjacent sans, truncated) so the rail identifies the
run even when the header is off-screen (mobile sheet).

**CH5.** Error/banner behavior preserved: sidecar error banner + reconnect button,
events-feed disconnect message (`"events feed disconnected — tool calls may not
appear"` becomes literally true once CH3 lands), credential warning, model-notice
cards — all keep current logic; restyle only to 1px-border tinted boxes (already
close).

### 4.2 Session switcher (ChatSessionList)

**CH6.** Keep it a navigation-only surface (its header comment is right — no
management actions creep). Changes: section chrome label stays; each row adds a
leading 6px status dot — success-pulse when `is_active`, transparent otherwise — and
the meta line becomes mono (`RelativeTime` · `N msgs` · source when ≠ cli). Active row
keeps the `border-l-2 border-primary bg-primary/10` treatment (accent = selection,
G11).

**CH7.** "New session" button, pick-to-`?resume=` semantics, request-token stale-fetch
guard, refresh button, and `order=recent` fetch are unchanged.

**CH8.** List refresh on session end: when ChatPage flips `sessionEnded` to true (PTY
close 4410/clean), bump the list's reload nonce (pass an optional `refreshSignal:
number` prop from ChatPage) so the just-finished conversation appears immediately.

**CH9.** ChatSessionList intentionally does **not** adopt `RunRow` — the rail needs a
denser one-line-and-a-half idiom; forcing the shared row here would cost density for
consistency the vocabulary (dot, mono meta, RelativeTime) already provides.

### 4.3 Chat shell states

**CH10.** Terminal-pane banners (token missing, reconnecting, close-code messages,
"Session ended" overlay + restart) are existing behavior — keep, restyle banner to the
shared warning-tinted 1px box. No spinner is ever shown over the terminal.

**CH11.** Rail loading: Agent card renders immediately with `—` placeholders (current
behavior); Activity feed hidden until first event (CH3); session list keeps its
Spinner-inline loading, swap to `Skeleton variant="row-list" rows={4}` for
first load only.

**CH12.** Rail errors: per CH5; session-list error keeps inline error + Retry.

---

## 5. Non-goals (N) and risks (R)

**N1.** Do not touch PTY/xterm internals: WebSocket lifecycle, attach-token logic,
resize/fit machinery, clipboard/OSC 52 paths, SGR mouse filtering, reconnect/backoff,
close-code contract (4401/4403/4404/4408/4409/4410), terminal theme wiring, the
terminal wrapper's shadow. Any diff inside `ChatPage`'s main connect effect is a
review flag.

**N2.** SessionsPage FTS search must keep working exactly as shipped: 300 ms debounce,
`>>>…<<<` snippet highlighting, filter-current-page-by-snippetMap behavior,
auto-scroll-to-hit. No server-side search redesign in this pass.

**N3.** All destructive flows preserved bit-for-bit: bulk select (shift-range anchor
semantics and the clear-on-page/search/view-change rule), bulk delete, delete-empty,
prune (incl. its validation), single delete idempotency expectations, cron delete
confirm. Confirm dialogs stay `DeleteConfirmDialog`.

**N4.** No redesign of the cron create/edit form internals, ScheduleBuilder, or
Blueprints; no changes to cron payload building/validation (`lib/cron-job.ts`,
`lib/schedule.ts`).

**N5.** No changes to model-picker/reasoning-picker logic (REST `model/set` path,
expensive-model confirm, reload-confirm flow).

**N6.** No new polling loops beyond C7's bounded trigger-follow poll; no virtualized
lists; no ⌘K work (separate roadmap phase); no i18n restructuring (new strings go
through the existing `t.*` tables with English fallbacks like current code does).

**R1.** Another process is editing this repo concurrently — implementers must rebase
against current `SessionsPage.tsx`/`CronPage.tsx` at build time; the #29824 compaction
logic and NS-504 restart affordance are recent fixes that must survive the refactor.

**R2.** `is_active` is a heuristic (not-ended AND <300 s since activity). "live" can
be up to 5 min stale and a crashed process can look live briefly. Copy in tooltips
should say "active in the last 5 min", not "running".

**R3.** Timestamp dialects (epoch seconds vs ISO) are an off-by-1000 bug factory —
all rendering must go through `RelativeTime`/`NextRunCountdown` (G4/G5), which own
the normalization.

**R4.** Token/cost fields are frequently 0/null (gateway sources, older rows, unpriced
models). Meta segments must render conditionally, never `↑0 ↓0` / `$0.00` noise.

**R5.** SessionsPage is a 58 KB monolith; the refactor should extract `RunRow`,
timeline, and the summary strip as it goes, but resist page-wide rewrites of the
selection/search state machine (highest regression-risk code on the page).

**R6.** Cron `profile=all` fans out across profiles; `getCronJobRuns` must always pass
the job's own profile (`getJobProfile(job)`) or run lookups will hit the wrong
`state.db`. Session endpoints must keep defaulting to `getManagementProfile()`.

**R7.** The Activity feed shares one events socket with the title/new-session
handlers; a malformed frame must never break the existing handlers (wrap new handling
in its own try/catch, as the current parser does).

---

## Appendix B — "Needs backend" (explicitly NOT in the main spec)

**B1. Global session event channel.** A profile-scoped `/api/events` channel (or SSE)
emitting session lifecycle events (`session.started/ended/updated`) so the Sessions
ledger and the "active now" stat go event-driven instead of the 5 s poll. Today
`/api/events` only rebroadcasts per-chat-PTY channels.

**B2. Persisted per-tool timing in transcripts.** `tool.complete.duration_s` exists
only as a live event; the messages table stores no duration. Langfuse-grade "timing
per node" in the S4 chronology for *historical* sessions needs a `duration_s` (and
ideally started/finished timestamps) column or sidecar table on tool messages.

**B3. Per-message token/cost attribution.** Tokens/cost are session-level only.
Per-node cost display (research doc §1.4 "cost on model-call nodes") needs per-call
usage rows (the data exists transiently at the provider-response level).

**B4. Session duration for gateway/chat sources.** `ended_at` is null for
never-finalized sessions; an authoritative closed-at (or heartbeat) would firm up the
`idle` vs `done` mapping (see R2).

**B5. Per-run outcome for cron runs.** Run sessions carry no success/error flag; only
job-level `last_status` exists. A `run_status` on the run session (or a runs table
with exit status + delivery status) would let C6 rows show pass/fail chips and enable
a job "health sparkline" (last-10-runs strip).

**B6. Cron `running` state on the job object.** A `state:"running"` (or
`current_run_id`) on `GET /api/cron/jobs` would replace the C7/C10 poll-and-infer
dance with a direct field.

**B7. Server-side FTS-scoped session listing.** `list_sessions_rich` already accepts
`search_query`/`id_query`; exposing them on `GET /api/sessions` would let search
paginate across the whole store instead of filtering the current page (removes the N2
quirk properly).

**B8. Turn-level usage events on the chat channel.** If `message.complete` (or a new
`usage.update`) carried token counts, the Chat rail could show a live context/token
meter — matching the roadmap's "always-available token meter" — without polling
analytics endpoints.
