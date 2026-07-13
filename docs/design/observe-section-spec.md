# OBSERVE Section Revamp — Implementation Spec ("Agentic Look")

Scope: the two pages in the **Observe** nav group — Logs, Analytics — per the design
direction in `docs/design/dashboard-revamp-research.md` ("terminal-grade minimalism",
value-density metric, monitoring-room framing) and the shared vocabulary shipped by
`docs/design/work-section-spec.md` (G1–G13, `web/src/components/ui/` primitives).

Framing: **Observe is the monitoring room for a fleet of agents.** Logs reads as the
fleet's *activity stream*; Analytics reads as the fleet's *workload report*. Everything
in the main spec is buildable against endpoints as they exist today; valuable-but-
missing data lives in Appendix B only.

Status: implementation-ready. Requirements are numbered `O` (shared), `L` (Logs),
`A` (Analytics). Non-goals and risks continue the Work-spec numbering (`N7+`, `R8+`)
so both specs can be referenced together without collisions. `G*` references are the
Work-spec shared rules, unchanged and reused as-is.

Source-of-truth files audited (2026-07-13):

- Frontend: `web/src/pages/LogsPage.tsx`, `web/src/pages/AnalyticsPage.tsx`,
  `web/src/components/ui/` (index + `AgentStatusBadge`, `MonoId`, `RelativeTime`,
  `NextRunCountdown`, `RunRow`, `TimelineNode`, `DataTable`, `EmptyState`, `Skeleton`,
  `PageToolbar`, `agent-status.ts`, `time.ts`), `web/src/lib/api.ts`
  (`getLogs`, `getAnalytics`, `AnalyticsResponse` types), `web/src/index.css`
  (`--series-input-token` / `--series-output-token`), `web/src/i18n/types.ts` (`t.logs`)
- Backend: `fabric_cli/web_server.py` (`GET /api/logs` ~L11184,
  `GET /api/analytics/usage` ~L15542, `GET /api/analytics/models` ~L15613, sessions
  endpoints per Work spec §0.1), `fabric_cli/logs.py` (`LOG_FILES`, `_read_tail`,
  line-grammar regexes, `_LEVEL_ORDER`), `fabric_logging.py` (`_LOG_FORMAT`,
  `COMPONENT_PREFIXES`, session-tag record factory), `agent/insights.py`
  (`InsightsEngine.generate` — skills + tools shapes)

---

## 0. Data audit — what the backend actually serves TODAY

### 0.1 Logs

**`GET /api/logs?file&lines&level&component&search`** → `{file, lines: string[]}`.
Verified server behavior (`web_server.py` ~L11184–11234, `fabric_cli/logs.py`):

| Param | Server semantics | Frontend today |
|---|---|---|
| `file` | Any key of `LOG_FILES`: `agent, errors, gateway, gui, desktop, mcp` | **Only offers `agent, errors, gateway`** — 3 files unexposed |
| `lines` | Clamped to ≤500 (2000-line raw window when `search` present) | 50/100/200/500 |
| `level` | **Minimum-level** filter (`_LEVEL_ORDER`: DEBUG<INFO<WARNING<ERROR<CRITICAL), i.e. `WARNING` = WARNING **and above**. Lines with no parseable level token **always pass** | Sent as-is; UI labels imply exact-match |
| `component` | Logger-name-prefix filter via `COMPONENT_PREFIXES`: `gateway, agent, tools, cli, cron, gui` | **`gui` missing from the UI's COMPONENTS list** |
| `search` | Case-insensitive substring post-filter over a 2000-line raw tail, trimmed to `lines` | **Exists server-side, entirely unused by the frontend** |

There is **no** `since` param, no structured/parsed line objects, no level counts, no
pagination/cursor, and no push/stream channel — the endpoint is a filtered tail. The
CLI's `session_filter` exists in `_read_tail` but is **not exposed** on the web
endpoint (Appendix B).

**Line grammar** (`fabric_logging._LOG_FORMAT`):
`%(asctime)s %(levelname)s%(session_tag)s %(name)s: %(message)s` →

```
2026-07-13 09:41:22,318 INFO [tg_12345_67] gateway.telegram: message text…
2026-07-13 09:41:22,318 ERROR agent.run_agent: Traceback (most recent call last):
    <continuation lines carry no timestamp/level>
```

- `session_tag` = ` [<session_id>]` when the record was emitted inside a session
  context, else empty — **session correlation is parseable client-side**.
- Backend parsing regexes to mirror in TS (from `fabric_cli/logs.py`):
  - timestamp: `^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})`
  - level: `\s(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s`
  - logger name: `\s(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)(?:\s+\[.*?\])?\s+(\S+):`
  - session tag: `\s(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\[([^\]]+)\]\s`
- `mcp` (`mcp-stderr.log`) and `desktop` are **not** in this grammar (raw subprocess
  stderr / Electron output) — parsing must degrade gracefully.
- Logs are **not profile-scoped**: the endpoint reads the *server process's*
  `get_fabric_home()/logs`, unlike analytics/sessions which take `?profile=`.

### 0.2 Analytics

**`GET /api/analytics/usage?days&profile`** (per-session-row aggregation over the
sessions table + `InsightsEngine`):

| Key | Shape (verified ~L15599) | TS declaration status |
|---|---|---|
| `daily[]` | `{day (YYYY-MM-DD), input_tokens, output_tokens, cache_read_tokens, reasoning_tokens, estimated_cost, actual_cost, sessions, api_calls}` | Fully declared, **cost/api_calls unused by the page** |
| `by_model[]` | `{model, input_tokens, output_tokens, estimated_cost, sessions, api_calls}` | Declared, **estimated_cost/api_calls unused** |
| `totals` | `{total_input, total_output, total_cache_read, total_reasoning, total_estimated_cost, total_actual_cost, total_sessions, total_api_calls}` | Declared, **costs/cache/reasoning unused** |
| `skills` | `{summary: {total_skill_loads, total_skill_edits, total_skill_actions, distinct_skills_used}, top_skills: [{skill, view_count, manage_count, total_count, percentage, last_used_at}]}` | Declared; summary unused |
| `tools[]` | `[{tool_name, count}]` desc-ordered (InsightsEngine `_get_tool_usage`) | **Served but NOT in `AnalyticsResponse` — frontend-only unlock** |
| `period_days` | echo of `days` | declared |

**`GET /api/analytics/models?days&profile`** — richer per-model rows (cache/reasoning
tokens, tool_calls, avg_tokens_per_session, capabilities). Consumed by ModelsPage;
Observe does **not** duplicate it (N8).

**Session rows as an Observe data source** (Work spec §0.1, re-verified):
`GET /api/sessions?limit&offset&order=created|recent&source&…` rows carry
`estimated_cost_usd`, `actual_cost_usd`, `api_call_count`, `input_tokens`,
`output_tokens`, `tool_call_count`, `message_count`, `is_active`, `ended_at`,
`last_active`, `model`, `source`. `GET /api/sessions/stats` →
`{total, active_store, archived, messages, by_source}`. Order is **created/recent
only — no cost/token ordering** (Appendix B for "top sessions by cost").

**The gate:** AnalyticsPage renders nothing but an explainer card unless config
`dashboard.show_token_analytics === true` (default off), because local token/cost
numbers exclude auxiliary calls, retries, and cache writes and can undercount 10x–100x
vs provider billing. Note the gate rationale applies to **token/cost estimates only**
— session counts, skill action counts, and tool call counts are exact local facts.

---

## 1. Shared Observe rules (O-requirements)

**O1. G-rules apply wholesale.** G9 (type assignment), G10 (1px-border elevation, no
inline hex/oklch — the two `--series-*-token` vars are theme tokens and remain the
only sanctioned chart colors), G11 (single accent; status via success/warning/
destructive tones only), G12 (density, `tabular-nums`), G13 (PageToolbar/EmptyState/
Skeleton everywhere). Both pages already comply substantially; this spec closes the
gaps rather than re-stating them.

**O2. Status vocabulary reuse, correctly scoped.** Log lines and analytics rows are
*not* agents, so `AgentStatusBadge` is used **only** where a real G1 status exists:
(a) the Logs "streaming" indicator (L4) — `status="live"` while follow-polling is
active, mapped exactly like the Work pages' live badge; (b) Analytics "recent runs"
rows (A6) — `sessionAgentStatus(row)` from `agent-status.ts`, identical to the
Sessions ledger. Log severity is **not** mapped onto AgentStatus (severity ≠ agent
lifecycle); it keeps the existing text-tone treatment (`text-destructive/-warning/
-foreground/-text-tertiary`). No new status words are invented.

**O3. Timestamps.** Any rendered (non-verbatim) timestamp goes through
`RelativeTime` / the shared `time.ts` ticker (R3 discipline). Verbatim log-line text
is never rewritten — raw lines stay copy-paste-faithful (L8).

**O4. Ids.** Session ids surfaced outside verbatim log text (Analytics run rows,
Logs' session-filter chip in the toolbar) render via `MonoId`.

**O5. i18n.** New strings go through `t.logs.*` / `t.analytics.*` with optional keys +
English fallbacks, matching the `t.logs.noLinesHint ?? "…"` pattern already on the
page (types in `web/src/i18n/types.ts` gain optional members; no restructuring, N6).

**O6. No new dependencies.** No charting library, no virtualization library, no log-
parsing library. All parsing is the four regexes in §0.1 mirrored into a small pure
module `web/src/lib/log-lines.ts` (L2) with unit tests.

**O7. Polling discipline.** Both pages remain poll-based (no event channel exists for
logs or analytics — Appendix B). All polls stay visibility-gated exactly like the
current LogsPage tick. No poll may get faster than today's 2 s.

---

## 2. LOGS page — "activity stream" (L-requirements)

### 2.1 Decisions on the table (explicit accept/reject)

- **Correlate log lines to sessions/runs — ACCEPT (client-side, in-page).** The
  `[session_id]` tag is machine-parseable from the line grammar (§0.1) at zero backend
  cost, and the server's unused `search` param gives us server-side session filtering
  for free (substring match over the 2000-line window — the session tag is a
  substring). Clicking a session tag filters the stream to that session (L9). What is
  *rejected* in this pass: cross-page deep-linking into a session's transcript —
  SessionsPage reads no URL query params today (verified: no `useSearchParams` /
  `location.search`), so a "open in Sessions" jump has nothing to land on. That is an
  out-of-scope frontend enabler (Appendix A1), not a backend gap.
- **Level facet chips with counts — ACCEPT, window-scoped.** True whole-file level
  counts don't exist server-side (no counts endpoint — B10), but counts *within the
  fetched window* are computable client-side and are honest if labeled as such. Chips
  keep the server's **minimum-level radio semantics** (they replace the Segmented,
  they don't become multi-select toggles — the server filter is `>=` and we don't
  fake exact-match, §0.1). See L5.
- **Component facet chips with counts — REJECT counts, keep the Segmented.**
  Component membership is decided by `COMPONENT_PREFIXES` in `fabric_logging.py`
  (Python). Mirroring that mapping into TS to compute counts would drift silently the
  next time a prefix is added (it grew as recently as #41112). Counts on component
  chips wait for a structured-lines endpoint (B9); the component filter itself stays,
  gains the missing `gui` option (L6), and hides for unstructured files (L7).
- **Paused-at-line pin + resume delta counter — ACCEPT.** Purely client-side, and it
  is the single biggest "monitoring room" affordance: scrolling up must never mean
  losing your place or the stream. Algorithm and degradation are specified (L11) —
  this is the one genuinely novel piece of logic on the page, treat it as such in
  review.
- **Default the stream to live — ACCEPT.** `autoRefresh` currently defaults off,
  which makes the "activity stream" a static file viewer on first visit. Default ON,
  persisted in `localStorage` (`fabric.logs.autoRefresh`), still visibility-gated
  (O7). Rejected alternative — keeping default-off — fails the temporal-density test
  (research doc §1.6): a monitoring page that starts frozen delivers zero signal per
  millisecond.

### 2.2 Information architecture (above the fold)

**L1.** Top-to-bottom:

1. **Page header** (slots, existing): title; `afterTitle` = current filter-summary
   Badge (now also includes the active search/session term when set) + refresh
   button; `end` = live/paused control (L4).
2. **Toolbar** (`PageToolbar`, existing): filters =
   `file` Segmented (now 6 files, L6) · **level facet chips** (L5) · `component`
   Segmented (+`gui`, hidden for `mcp`/`desktop`, L7) · `lines` Segmented ·
   **search input** (new, L9).
3. **Stream card**: header row = `FileText` icon + `<file>.log` mono name +
   **in-view tally** (L5b, right-aligned) ; body = the log scroller (existing
   follow-mode machinery retained verbatim) with pause pin (L11) and jump-to-latest
   chip (now with delta counter, L11).

No summary Stats strip: unlike Sessions/Cron there is no truthful page-level
aggregate to show (any number would be window-scoped and duplicate L5b).

### 2.3 Components and behavior

**L2.** New pure module `web/src/lib/log-lines.ts` (no React):

```ts
export interface ParsedLogLine {
  raw: string;                    // verbatim, always rendered as-is
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL" | null;
  sessionId: string | null;       // from the [tag], when present
  loggerName: string | null;
  isContinuation: boolean;        // no leading timestamp (traceback/wrapped line)
  classification: "error" | "warning" | "info" | "debug"; // display tone
}
export function parseLogLine(raw: string, prev?: ParsedLogLine): ParsedLogLine;
```

Mirrors the §0.1 regexes. `classification`: from the parsed `level` token when
present (`CRITICAL`→error); else, for continuation lines, **inherit `prev`'s
classification** (tracebacks stay red end-to-end — today each continuation line is
re-classified by keyword and flickers tones); else fall back to the existing keyword
heuristic (`classifyLine`) — it remains the right answer for `mcp`/`desktop` lines
that have no level token. This replaces the current substring heuristic as primary
because `upper.includes("ERROR")` misfires on any INFO line whose *message* mentions
"error" (word-bounded token beats substring).

**L3.** Line rendering (replaces the bare `div` map):
- Verbatim `raw` text, `font-mono-ui text-xs leading-5`, tone per
  `classification` via the existing `LINE_COLORS` map, existing hover
  `bg-secondary/20`. Continuation lines get `pl-4` soft indent (indentation is
  outside the text node; copy fidelity preserved).
- When `sessionId` is present, the tag's characters are wrapped in an interactive
  span (`decoration-dotted underline-offset-2 hover:text-foreground cursor-pointer`,
  `title="filter this session"`): click applies the session filter (L9). The span
  contains exactly the original `[…]` characters — selection/copy of the line is
  byte-identical to the file (O3).
- `key` stays index-based (lines are a sliding window without identity — B9).

**L4.** Live control (header `end` slot): the Switch + label is replaced by a single
toggle rendered as `AgentStatusBadge` — `status="live"` label `streaming` while
`autoRefresh && follow`, `status="live" pulse={false}` label `streaming (scrolled)`
while `autoRefresh && !follow`; when `autoRefresh` is off render `status="idle"`
with label `paused` (idle tone, G1-consistent: the stream isn't failed or done,
just not moving — do not reuse the warning-toned `paused` status, that word is
cron-lifecycle vocabulary). Clicking the badge toggles
`autoRefresh`. Keep an `aria-pressed` button wrapper for a11y; keep the existing
`t.logs.autoRefresh` as its `aria-label`.

**L5.** Level facet chips (page-local component `LevelChips`, not promoted to
`ui/` — single consumer):
- One chip per `ALL | DEBUG | INFO | WARNING | ERROR` (unchanged set — CRITICAL
  folds into ERROR's chip count, matching `classifyLine` and `_LEVEL_ORDER`'s ≥
  semantics). Radio behavior identical to today's Segmented (min-level, server-side).
- Each chip shows a window-scoped count of **exact** parsed levels among currently
  rendered lines: `ERROR 3` = "3 error-classified lines in view". `ALL` shows total
  line count. Counts recompute from the parsed array (L2) — no extra fetch.
- When a min-level other than ALL is active, chips *below* the threshold render
  muted without counts (their lines aren't in the window; showing 0 would lie).
- Style: 1px-border chips, mono `tabular-nums` counts, active chip
  `border-primary/40 bg-primary/[0.06]` (selection = accent, G11); error/warning
  chips tint their count only (`text-destructive`/`text-warning`), never the chip
  surface.

**L5b.** In-view tally (stream-card header, right side): one muted mono line,
`N lines · X err · Y warn` (err/warn segments only when >0, R4 discipline), same
data as L5. This is the glanceable "is anything on fire" readout when the toolbar
is scrolled away or collapsed on mobile.

**L6.** File selector gains the three unexposed files: `agent, errors, gateway, gui,
desktop, mcp` (server's `LOG_FILES`, §0.1). Labels stay uppercase chrome
(`formatFilterLabel`). On narrow widths the Segmented already wraps.

**L7.** Component filter: add `gui` to `COMPONENTS` (server supports it; currently a
silent gap). When `file` is `mcp` or `desktop`, hide the component FilterGroup and
force `component="all"` — those files don't carry logger names, so any component
prefix filter would blank the stream server-side (verified `_line_matches_component`
returns False for unparseable lines).

**L8.** Fetch pipeline: `api.getLogs` gains the `search?: string` param (query-string
passthrough; server already implements it). The existing fetch/poll/visibility/
follow machinery is otherwise **retained verbatim** — same 2 s interval, same
background-fetch loading suppression, same `followRef` pin effect, same
FOLLOW_THRESHOLD_PX. When `search` (or a session filter) is active, the poll
interval stretches to 5 s: each such request makes the server scan a 2000-line raw
window (§0.1), and a monitoring tab should not do that every 2 s (O7).

**L9.** Search + session filter:
- Toolbar search input (right-aligned in `filters`, 300 ms debounce — same constant
  as SessionsPage), placeholder `search lines…`, mono input text. Maps to the server
  `search` param; results are still the *tail* of matches (server trims to `lines`).
- Clicking a line's session tag (L3) sets the same search state to the session id
  and renders it as a dismissible chip in the toolbar: `MonoId(sessionId)` + ✕.
  Session filter and free-text search share the single `search` slot (the server has
  one param; last action wins; the chip form is shown whenever the term came from a
  tag click).
- Active search is reflected in the header filter-summary badge (`AGENT · ALL · all
  · "needle"`), and re-engages follow on change like every other filter (existing
  effect).

**L10.** Line count semantics stay honest: the label says `LINES` and the chip counts
say "in view" (`title` attributes spell out "of the last N fetched lines"). Never
present window counts as file totals (that needs B10).

**L11.** Pause pin + resume delta ("jump to latest +N"):
- When follow disengages (user scrolls up), record `pauseAnchor = lines[lines.length
  - 1]` … more precisely the **last 3 raw lines** as an overlap key, plus the current
  line count.
- Render a pin divider after that line: a full-width 1px `border-warning/40` rule
  with a centered chrome label `— paused here —` (`text-[10px] uppercase tracking`
  `text-warning`). The divider is display-only (not part of copyable stream text —
  it's a separate element between line divs).
- On each background poll while paused, locate the overlap key in the fresh array
  (search from the end for the 3-line subsequence; 3 lines make false positives
  negligible even for repetitive logs). Delta = fresh lines after the match. The
  jump-to-latest chip becomes `↓ jump to latest · +N` (mono count, `tabular-nums`).
- Degradation: if the overlap key is no longer inside the fetched window (≥`lines`
  new lines arrived, or rotation truncated the file), show `+{lines}+` (e.g. `+500+`)
  and move the pin divider to the top of the stream with label `— earlier lines
  scrolled out —`. If the fetch was for *different filters*, the pin resets (filter
  changes already re-engage follow today; keep that).
- Clicking jump: existing behavior (re-engage follow, scroll to bottom) + clears the
  pin. The pin also clears when the user manually scrolls back to the bottom
  (existing `atBottom` detection flips follow on — same path).
- While paused **and** `autoRefresh` is on, polling continues (the stream below the
  fold keeps advancing) — pausing is a *viewport* state, not a fetch state. This is
  the AG-UI "cancel/resume reading without losing the stream" gesture in
  poll-clothing.

### 2.4 Data mapping (endpoint → field → display)

| Surface | Source | Field | Display |
|---|---|---|---|
| Stream lines | `GET /api/logs` | `lines[]` | verbatim mono text, tone per L2 classification |
| Level chips / tally | client parse (L2) | `level` per line | `tabular-nums` counts, window-scoped |
| Session tag chip | client parse (L2) | `sessionId` | interactive span in-line; `MonoId` chip in toolbar when filtering |
| Search / session filter | `GET /api/logs` | `search` param | server-side substring filter |
| File name | request state | `file` | `<file>.log` mono in card header |
| Filter summary badge | request state | `file·level·component·search` | header `afterTitle` Badge (existing, extended) |
| Streaming badge | client state | `autoRefresh && follow` | `AgentStatusBadge` live/idle per L4 |

### 2.5 Logs states

**L12.** Loading: existing `Skeleton variant="row-list" rows={12}` inside the
scroller, kept. First-load only; background polls never skeleton (existing).

**L13.** Empty: existing `EmptyState icon={FileText}` kept (including the `font-sans`
reset comment — that fix stays). Two refinements: when a `search`/session filter is
active, description names the term and the action button is "Clear search"; when the
file simply doesn't exist yet (server returns `{lines: []}` for missing files),
description = existing `noLinesHint` fallback.

**L14.** Error: the destructive banner gains a Retry button (`fetchLogs()`);
background-poll errors must not clear the last-good lines (today `setError` renders
the banner above stale content — keep that, and add `error` auto-clear on next
successful poll, which already happens via `setError(null)`).

---

## 3. ANALYTICS page — "agent workload report" (A-requirements)

### 3.1 Decisions on the table (explicit accept/reject)

- **Reframe around agents/runs — ACCEPT.** The page's own endpoint already serves
  run counts, per-model workload, skill and tool action counts, and cost estimates;
  the sessions endpoints add a concrete "recent runs" ledger. The page stops being
  "token counter" and becomes "what has the fleet been doing" (A1).
- **Cost per session ("top sessions by cost") — REJECT for the main spec.**
  `GET /api/sessions` orders by `created|recent` only; a cost leaderboard computed
  from one fetched page would silently mean "most expensive of the last N", which is
  a different (and misleading) claim. A bounded, honestly-labeled **Recent runs**
  ledger (A6) ships instead; true cost ordering is B11.
- **Tokens per model — ACCEPT (already shipped, extended).** `by_model` gains its
  already-served `estimated_cost` and `api_calls` columns (A5). No new fetch.
- **Busiest skills — ACCEPT (already shipped, kept).** Plus the served-but-undeclared
  `tools[]` becomes a **Busiest tools** table (A7) — tool calls are the purest
  "agent workload" signal the backend has, and it's been on the wire unused.
- **`show_token_analytics` gate: page-level → tile-level — ACCEPT.** The gate's
  documented rationale (local token/cost estimates diverge from billing) indicts
  only the token/cost surfaces. Session counts, skill actions, and tool calls are
  exact local facts — hiding them behind a token-accuracy disclaimer makes the page
  default-dead for no reason. The gate becomes surface-scoped (A2); the config key
  and its default (off) are unchanged (N9).
- **Charts — keep `TokenBarChart` as-is.** It already follows the codebase dataviz
  craft rules: theme series tokens (`--series-*-token`) via `color-mix`, no chart
  dependency, 1px-bordered tooltip card, min-1px bars for nonzero values, sparse
  3-point x-axis labels. The only changes are gating (A2) and tooltip additions from
  already-fetched fields (A4). Rejected: adding a cost line/series (dual-axis mixing
  $ and tokens in one plot violates the "one claim per chart" craft rule and the
  gate rationale makes cost the least trustworthy series on the page); rejected:
  Recharts/shadcn charts migration (roadmap Phase 4, not this pass; no new deps, O6).

### 3.2 Information architecture (above the fold)

**A1.** Top-to-bottom (gated surfaces marked ▲):

1. **Header toolbar** (existing `afterTitle` PageToolbar): period 7d/30d/90d +
   refresh. Unchanged, but now always rendered (the page always has content — the
   `showTokens === false ? null :` suppression is removed).
2. **Token-estimate notice** (only when gate off): the current explainer card
   shrinks to a compact one-row 1px `border-warning/30 bg-warning/[0.04]` notice —
   `token & cost estimates hidden — local counts diverge from provider billing ·
   Config` (link). The full three-paragraph explanation moves into a `<details>`
   expansion inside the notice (content verbatim from today's card — it is good
   copy, just wrongly load-bearing).
3. **Workload summary strip** (`Stats` card, G8): `runs` (`totals.total_sessions`,
   with `~N/day` suffix as today) · `api calls` (`totals.total_api_calls`) ·
   `skill actions` (`skills.summary.total_skill_actions`) · `tool calls` (sum of
   `tools[].count`) · ▲`tokens` (`total_input + total_output`, formatted) ·
   ▲`est. cost` (`total_estimated_cost`, `$` mono; omit when 0 — R4).
4. ▲**Daily token chart** (`TokenBarChart`, kept) beside the Stats card in the
   existing `lg:grid-cols-2`. When gated off, the grid slot is taken by the
   **runs-by-source card** (A8) so the fold stays two-up.
5. **Recent runs** card (A6).
6. ▲**Daily breakdown** table (existing, + cost column A4).
7. ▲**Per-model** table (existing, + cost/api-calls columns A5).
8. **Busiest skills** table (existing `SkillTable`, ungated now) and **Busiest
   tools** table (A7), side by side ≥`lg`.

### 3.3 Components and data mapping

**A2.** Gate mechanics: `showTokens` keeps its config fetch. It now controls only the
▲ surfaces: tokens/cost Stats items, `TokenBarChart`, `DailyTable`, `ModelTable`
(the whole table — every column beyond model name is token-derived or cost), and the
token/cost segments elsewhere. Everything else fetches and renders regardless —
which means `getAnalytics` is now **always** called (the skills/tools/sessions
aggregates come from the same response). The `load()` early-return on `!showTokens`
is removed; the response is simply partially displayed.
*Privacy note for review:* the gate never protected data from the network — the
endpoint was always open; it shaped display honesty only. Tile-level scope preserves
exactly that intent.

**A3.** Type unlock (frontend-only): add to `AnalyticsResponse` in `api.ts`:
`tools: { tool_name: string; count: number }[]` (§0.2 — already served).

**A4.** `DailyTable` gains an `est. cost` column: `estimated_cost` → `$X.XX` mono,
right-aligned, rendered as `—` when 0 (R4). `TokenBarChart` tooltip gains two lines
from already-plotted-day data: `runs: {sessions}` and `est: ${estimated_cost}`
(cost line only when > 0). No visual changes to bars/axis/legend.

**A5.** `ModelTable` gains `est. cost` (`estimated_cost`, same formatting as A4) and
`api calls` (`api_calls`, mono right) columns. Default sort stays `input_tokens`.
Model names stay mono (already `mono: true`).

**A6.** **Recent runs** card (new, page-local `RecentRunsCard`): the fleet ledger
excerpt.
- Data: `GET /api/sessions?limit=20&order=recent&archived=exclude` (existing
  `api.listSessions` binding + existing params; profile = management profile like
  every other call on the page). One fetch on mount + on refresh button; **no poll**
  (Analytics is a report, not a monitor — Sessions owns liveness; O7/N6).
- Render: `RunRow` per session — third consumer of the shared primitive (after
  Sessions, Cron drawer). Props mapping: `title` = title/preview/italic-untitled
  exactly as Work spec S2 · `status` = `sessionAgentStatus(row)` · `id` → `MonoId` ·
  `sourceIcon` from `SOURCE_CONFIG` · `model` short name · `meta` = `N msgs` ·
  `N tools` (when >0) · `↑in ↓out` compact (when >0) · `$est` (when present —
  ungated, matching the Sessions ledger's S2 precedent so the same run never shows
  cost on one page and hides it on another) · `timestamp` = `last_active`.
  No checkbox, no expansion, single action: "open in Sessions" (navigates to
  `/sessions`; per-row deep-link is Appendix A1).
- Card header: chrome label `recent runs` + muted `last 20` qualifier — the honest
  bound from the reframe decision (§3.1).

**A7.** **Busiest tools** table (new, mirrors `SkillTable`): columns `tool`
(`tool_name`, mono, sortable) · `calls` (`count`, mono right, sortable, default
sort). Rows = `data.tools`. `DataTable` + card idiom identical to SkillTable, icon
`Wrench` (lucide). Show top 15, with a muted `+N more` footer line when longer
(tool lists are long-tailed; 15 keeps the fold honest).
*Accuracy footnote in `title` on the header icon:* counts merge two extraction paths
and take `max()` on overlap (InsightsEngine) — "best-effort count", not billing.

**A8.** **Runs by source** card (new, small): from `GET /api/sessions/stats`
`by_source` — one row per source: monochrome source glyph (G11) + name + mono count
+ a proportional 1px-high bar (`bg-primary/40`, width = count/max — a meter, not a
chart; no series colors, no axes). Rendered in the fold grid when the chart is gated
off (A1.4); below the recent-runs card otherwise. One extra cheap fetch, already
bound (`api.getSessionStats`).

### 3.4 Data mapping summary (endpoint → field → display)

| Surface | Endpoint | Fields | Display |
|---|---|---|---|
| Summary strip | `/api/analytics/usage` | `totals.*`, `skills.summary.total_skill_actions`, Σ`tools[].count` | `Stats` items, mono `tabular-nums`; tokens/cost gated |
| Daily chart ▲ | `/api/analytics/usage` | `daily[].input_tokens/output_tokens` (+`sessions`, `estimated_cost` tooltip) | `TokenBarChart` unchanged |
| Daily table ▲ | `/api/analytics/usage` | `daily[].day/sessions/input/output/estimated_cost` | `DataTable` |
| Model table ▲ | `/api/analytics/usage` | `by_model[].model/sessions/tokens/estimated_cost/api_calls` | `DataTable` |
| Skills table | `/api/analytics/usage` | `skills.top_skills[]` | existing `SkillTable` |
| Tools table | `/api/analytics/usage` | `tools[].tool_name/count` | new `DataTable` card (A7) |
| Recent runs | `/api/sessions?limit=20&order=recent` | row fields per S2/S3 | `RunRow` list (A6) |
| Runs by source | `/api/sessions/stats` | `by_source` | glyph + count + meter (A8) |
| Gate | `/api/config` | `dashboard.show_token_analytics` | tile-level visibility (A2) |

### 3.5 Analytics states

**A9.** Loading: existing skeleton layout kept (two `block h-40` + `row-list rows=6`,
`aria-busy`), plus one `row-list rows=4` for the recent-runs card. Sections resolve
independently (usage fetch vs sessions fetch) — each card skeletons on its own.

**A10.** Empty: the existing all-empty `EmptyState icon={BarChart3}` condition
extends to include `data.tools.length === 0` and an empty recent-runs fetch; its
action becomes "Open chat" (→ `/chat`), matching S10's pattern. Per-card emptiness:
a card with zero rows renders nothing (current behavior — `if (x.length === 0)
return null` — kept), except recent-runs which shows a compact EmptyState ("No runs
yet") since it's the page's anchor surface.

**A11.** Errors: usage-fetch error keeps the destructive card but gains a Retry
button (`load()`); sessions/stats fetch errors degrade *silently to hidden cards* —
they are supplementary; a broken supplementary card must not take down the report
(log to console only).

---

## 4. Non-goals and risks (continuing Work-spec numbering)

**N7.** No log streaming transport in this pass — no WebSocket/SSE tailing, no
`/api/events` abuse (it requires a chat channel id). The 2 s visibility-gated poll
stays the liveness mechanism until B9/B12.

**N8.** No duplication of `/api/analytics/models` surfaces — per-model capability
cards belong to ModelsPage. Observe's model table stays the compact usage table.

**N9.** The `dashboard.show_token_analytics` config key, its default (off), and its
schema entry are untouched — only the *scope* of what it hides changes (A2). No new
config keys.

**N10.** No virtualization: the stream is ≤500 lines by server clamp, recent runs
≤20 — plain DOM is fine (and the follow-pin scroll math depends on it staying
plain).

**N11.** No server-side changes of any kind in the main spec — every requirement
above is frontend-only against verified existing endpoints (the entire Appendix B
is the "wants backend" bucket).

**N12.** Log text is never transformed, truncated, re-wrapped-with-inserted-chars,
or syntax-highlighted beyond whole-line tone + the L3 tag span. Copy fidelity is a
feature (operators paste these lines into issues).

**R8.** Concurrent-edit hazard: LogsPage was just revamped (follow mode, visibility
gating, keyword classification) and AnalyticsPage recently adopted DataTable —
implementers must rebase onto the live files; the follow/pin machinery in LogsPage
(`followRef`, `useLayoutEffect` pin, FOLLOW_THRESHOLD_PX) is the highest-risk merge
zone and L11 builds directly on it.

**R9.** Level-token parsing vs server filtering asymmetry: lines with no parseable
level pass the server's min-level filter (§0.1), so a `≥ ERROR` view will contain
unleveled traceback continuations — chip counts (L5) and the tally (L5b) must count
those under their inherited/heuristic classification, not drop them, or counts
won't sum to the visible line count.

**R10.** The `search` code path makes the server read a 2000-line raw window per
request; L8's 5 s backoff is load-bearing — do not "simplify" it back to 2 s.

**R11.** Delta counting (L11) is heuristic under a sliding tail window: repeated
identical lines can theoretically alias the 3-line overlap key. Consequence is a
wrong `+N`, never data loss. Do not attempt to strengthen it with timestamps
(sub-second duplicates are common); wait for B9 line identity instead.

**R12.** Cost fields are estimates and frequently 0/null (R4 applies everywhere):
every `$` segment and cost column renders conditionally; totals of 0 render `—`,
not `$0.00`. The A1.2 notice is the only place the divergence caveat lives —
don't sprinkle warning icons per cell.

**R13.** Logs are server-home-scoped while analytics/sessions are profile-scoped
(§0.1): on a multi-profile install the Logs page shows the gateway process's home
logs regardless of the dashboard's management profile. Pre-existing behavior, now
adjacent to profile-scoped surfaces on the same nav group — the Logs header
filter-summary badge must NOT display a profile name (it would be a lie).

**R14.** `skills.percentage` and `tools` counts come from InsightsEngine heuristics
(JSON extraction + `max()` merge). Present as activity signals ("busiest"), never
as billing-grade metrics; A7's title-footnote is the designated disclosure.

---

## Appendix A — Out-of-scope frontend enablers (not backend, not Observe)

**A-1.** SessionsPage URL-param support (`/sessions?q=<term>` prefilling FTS search,
or `?focus=<id>`): would upgrade L9's in-page session filter and A6's "open in
Sessions" into true cross-page deep links. Touches SessionsPage only; natural
companion to Work-spec B7 (server-side FTS pagination).

## Appendix B — "Needs backend" (explicitly NOT in the main spec)

**B9. Structured log lines.** `GET /api/logs` variant returning parsed objects
(`{ts, level, session_id, logger, message, seq}`) with a stable per-line `seq`.
Unlocks: exact React keys, robust pause-delta (kills R11), component counts (the
COMPONENT_PREFIXES mapping applied server-side per line), session chips without
client regex mirroring, and a `since_seq` incremental poll that stops re-shipping
the whole window every 2 s.

**B10. Whole-file facet counts.** `GET /api/logs/summary?file` → counts per level /
component / session over the last N lines or M minutes. Turns L5's window-scoped
counts into real facet counts, and enables an honest "errors in the last hour"
stat strip on Logs.

**B11. Cost/token ordering on sessions.** `order=cost|tokens` (or `sort=` +
`min_cost=`) on `GET /api/sessions`. Unlocks the true "top sessions by cost"
leaderboard rejected in §3.1, replacing A6's bounded recent-runs framing.

**B12. Log follow channel.** SSE or WS tail (server already has `_follow_log`
logic CLI-side) so the activity stream becomes push-driven — the research doc's
event-driven mandate (§1.3) applied to Observe; obsoletes the poll and most of L11's
delta arithmetic.

**B13. Session filter on the logs endpoint.** `_read_tail` already accepts
`session_filter`; exposing `session=` on `GET /api/logs` gives exact session
correlation instead of the L9 substring ride-along (substring can false-positive on
ids quoted inside message bodies).

**B14. Per-source/per-day analytics dimension.** `daily` grouped by `source` (or a
`by_source` block with tokens/cost, not just the sessions-stats counts) would let
the workload report answer "which channel burns the budget" — the by-source meter
(A8) currently shows run counts only.

**B15. Billing-grade usage.** The gate exists because local estimates exclude
auxiliary calls/retries/cache writes (§0.2). Provider-side usage ingestion (or
counting auxiliary calls into `api_call_count`/token columns) is the only real fix;
until then the A1.2 notice stays permanent.
