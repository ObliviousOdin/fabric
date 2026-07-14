# Dashboard UI/UX Revamp — Research & Design Direction

> **Historical implementation record — superseded for current design decisions.**
> Use [`web/DESIGN.md`](../../web/DESIGN.md) and the
> [Workspace/Admin redesign plan](../plans/2026-07-14-fabric-enterprise-workspace-admin-redesign.md)
> as the active contract. Route names and component details below remain useful
> archaeology, but the inherited “agentic/terminal-grade” visual direction,
> teal identity, pervasive display typography, and legacy nav grouping are not
> current Fabric guidance.


Deep research into best-in-class minimalistic agent dashboard systems, combined with an
audit of the current Fabric web dashboard (`web/`), to define a design direction, IA
restructure, component strategy, and prioritized revamp roadmap.

Method: fan-out web research across 5 angles (exemplar agent platforms, minimalist
dev-tool design language, agent-specific UX patterns, component-library trade-offs,
IA/navigation for feature-heavy consoles) → 23 sources fetched → 50 claims extracted →
3-vote adversarial verification per claim (24 confirmed, 1 refuted) → synthesis. In
parallel, a full audit of `web/src` (shell, routing, theming, page patterns).

---

## 1. What the best minimalistic dashboards actually do

### 1.1 Linear — generated themes, chrome-first redesign

The strongest reference for a theme-system rebuild. Linear does **not** hand-author its
~98 theme variables; it generates the entire palette from **three inputs — base color,
accent color, and contrast — in LCH color space**. Perceptual uniformity lets it derive
elevation surfaces (background → panel → dialog → modal) programmatically, and the
explicit contrast variable yields high-contrast accessibility themes for free.
*(Verified 3-0 against Linear's own redesign write-up.)*

Their redesign method is equally transferable: the ~six-week redesign focused **first on
foundational chrome** — sidebar, tabs, headers, filters, panels — to cut visual noise,
enforce alignment of labels/icons/buttons, and increase navigation hierarchy and
density. Early explorations used only black/white opacities to establish elevation
before any color was applied. Aesthetic: ultra-minimal neutrals plus a **single**
restrained accent (`#5e6ad2`), never a second chromatic accent.

### 1.2 Vercel Geist — monochrome precision

Black-and-white foundation (`#171717` / `#ffffff`), 1px-border elevation instead of
shadows, Geist Sans for UI + Geist Mono for anything technical (IDs, paths, logs,
tokens). Principles: simplicity, minimalism, speed. The shared pattern with Linear:
**monochrome surfaces + exactly one accent + mono type for technical text.**

### 1.3 AG-UI — agent dashboards are event-driven, not fetch-and-render

Agentic apps break the request/response model: agents are long-running, streaming,
nondeterministic, mix structured and unstructured IO, and compose recursively via
sub-agents. The verified building-block checklist for agent UX:

- streaming chat with cancel/resume
- shared typed state with event-sourced diffs
- thinking-steps visualization from traces and tool events
- frontend tool calls and backend tool rendering
- human-in-the-loop interrupts and agent steering
- sub-agent composition, tool-output streaming

Fabric's dashboard today is mostly poll-and-render (e.g. Logs polls on a 5s interval);
this is the biggest architectural gap.

### 1.4 Langfuse — the trace/run-detail anatomy

A session/run detail view should render as a **hierarchy of nested observations** —
initial model call, tool executions, final step — where each node shows **timing,
inputs, outputs, and cost** (cost on model-call nodes). Per-request essentials: prompt,
response, token usage, latency, intermediate tool/retrieval steps. This is the model
for Fabric's Sessions detail view.

### 1.5 Chat + live activity pane — strong candidate, not settled standard

The claim that split-screen chat-left/activity-right is "the dominant agent UI" was
**refuted (0-3)** in verification. What survived: agent UIs must serve two functions at
once — *communicating* with the agent and *observing* what it does — and a
chat-plus-activity layout is one credible way to do that (Devin, OpenHands, ChatGPT
agent). Claude Code-style unified interleaved timelines are the main alternative. Treat
this as a design decision to prototype, not an industry default to copy.

### 1.6 Minimalism = value density, not sparseness

UI density is **value delivered per unit of space and time**. Visual sparseness is an
unreliable proxy; loading/streaming latency is the biggest factor in temporal density.
A fast-streaming logs view is "denser" than a slow sparse one. Success metric for the
revamp: **signal per pixel and per millisecond**, not fewer elements.

### 1.7 Command palettes — layer, don't lead

Verified guidance: don't make a hidden power-user surface the primary navigation; keep
visible sidebar navigation strong, and layer a ⌘K palette on top as an accelerator once
the plain path works. Even keyboard-first exemplars (Linear, Superhuman) retain visible
navigation. Fabric currently has **no** global palette (only the chat composer's slash
popover), so this is a net-new surface.

---

## 2. Current-state audit (web/)

Stack: React 19 + Vite + React Router 7 + Tailwind v4 + `@nous-research/ui` 0.18.2,
lucide-react icons. Key findings:

**Shell & IA**
- Sidebar-only shell (`App.tsx`), `w-64` collapsing to `w-14`, off-canvas below 1024px.
- **One flat group of ~16 nav items** — no sectioning — plus a dynamic Plugins group.
- Per-page headers via a `PageHeaderProvider` slot API; each page re-implements its own
  toolbar markup inside the slots.
- `DocsPage.tsx` is orphaned (not routed, not imported).

**Theming**
- 8 presets, only one light theme; no `prefers-color-scheme` handling.
- Token model is a 3-layer palette (background/midground/foreground) applied as CSS
  variables on `:root`, with a shadcn-compat bridge in `index.css` (`@theme inline`)
  remapping `--color-card`, `--color-muted`, etc. This is already conceptually close to
  Linear's generated-theme approach — fewer inputs, derived surfaces — and is the right
  bones to build on.
- Density multiplier (`--theme-spacing-mul`) already scales Tailwind spacing globally.

**Design language**
- Uppercase-tracked display type for chrome; `ListItem`/`Card` grids everywhere except
  a bespoke `<table>` + one-off sort hook in AnalyticsPage only.
- Motion is minimal CSS keyframes. **`gsap`, `motion`, `three`, `@react-three/fiber`,
  and `leva` are declared in `package.json` but never imported** — dead weight.
- Inline `oklch()`/hex literals in 6 files bypass the token system.

**Agent-specific UI**
- Chat is a real embedded terminal (`@xterm/xterm` + PTY over WebSocket) rendering the
  TUI — there is **no React-side tool-call renderer, streaming markdown, or message
  model** in the dashboard.
- Token/cost surfaces exist only on AnalyticsPage, which is default-off.
- Logs are 5s-interval polling with keyword-heuristic colorization, not a live stream.

**Missing shared patterns**
- No DataTable, EmptyState, Skeleton, or PageToolbar primitives; loading/empty states
  are ad-hoc per page.
- Keyboard handling is ad-hoc in 8 files; no global shortcut registry, no ⌘K.
- Page monoliths: `SystemPage` 63 KB, `SessionsPage` 58 KB, `SkillsPage` 56 KB,
  `ProfilesPage` 49 KB, `ChannelsPage`/`ModelsPage` 47 KB, `App.tsx` 42 KB / 1359 lines.
- Incomplete legacy-to-Fabric rename across storage keys, CSS classes, DOM ids, and
  API fields.

---

## 3. Component library recommendation: shadcn/ui on Base UI

As of **July 2, 2026, Base UI is shadcn/ui's default primitive library** (`npx shadcn
init` defaults to it; Base UI is stable at 1.6.0 with 6M+ weekly downloads, built by
the original Radix creators; shadcn/create users were choosing it over Radix ~2:1
before the flip). Radix remains supported (`npx shadcn init -b radix`) but the shadcn
team explicitly recommends Base UI for new projects — which a ground-up revamp is.
*(Verified 3-0 ×4 against the official changelog and npm.)*

Fabric's exact stack (React 19 + Vite + Tailwind v4) is a first-class shadcn target,
and the copy-in code-ownership model (plain code in-repo, no wrapper-library lock-in,
upgrades follow upstream paths) suits an open-source local-first project. For
Analytics, use the shadcn charts (Tremor-lineage, Recharts-based) rather than a
separate charting dependency.

**Relationship to `@nous-research/ui`:** the pragmatic path is coexistence during
migration — shadcn components are copied into `web/src/components/ui/` and adopted
page-by-page, with the existing shadcn-compat CSS-variable bridge already in place.
Caveat (flagged in verification): the Base UI default is days old at research time, so
third-party shadcn registries may lag; pin versions and prefer first-party blocks.

---

## 4. Recommended design direction

**"Terminal-grade minimalism":** Geist-like monochrome surface system + one accent
(keep Fabric teal as the single chromatic accent), 1px-border elevation, mono type
(existing JetBrains Mono) for every technical readout — session ids, model names,
token counts, cron expressions, log lines — and the existing uppercase-tracked display
type reserved for chrome labels only.

**Theme system (evolve, don't replace):** extend the current 3-layer palette into a
Linear-style generated system — inputs: base color, accent, contrast, density → derive
the full 18-token shadcn surface set in OKLCH via Tailwind v4 `@theme` tokens. Add a
true light/dark axis with `prefers-color-scheme` support and an automatic high-contrast
variant from the contrast input. Existing YAML user themes keep working by mapping onto
the same inputs.

**Event-driven data layer:** replace polling with a unified event stream (the gateway
already exposes `/api/events?channel=`) powering live session lists, streaming logs,
and run status — per the AG-UI rationale and the value-density metric (latency is
density).

### IA restructure (~20 flat items → 4 groups + system)

| Group | Pages |
|---|---|
| **Work** | Chat, Sessions, Cron |
| **Observe** | Logs, Analytics |
| **Capabilities** | Models, Skills, Plugins, MCP |
| **Connect** | Channels, Webhooks, Pairing, Files |
| **System** (bottom cluster) | Profiles, Config, Keys (Env), System |

Plugins keep their injected group; ⌘K palette layered on top for navigation + actions
(restart gateway, new session, switch profile, switch theme).

---

## 5. Prioritized roadmap

**Phase 0 — Debt removal (days).** Remove the 5 unused deps (`gsap`, `motion`, `three`,
`@react-three/fiber`, `leva`); delete or route `DocsPage`; extract `App.tsx` sidebar
sub-components into `components/`; finish the legacy-to-Fabric rename behind the
existing migration shims.

**Phase 1 — Foundation: tokens & theme system.** OKLCH generated themes (base/accent/
contrast/density inputs → derived surface scale), light+dark+high-contrast, shadcn/ui
(Base UI) init, and the shared primitives every page needs: DataTable (replacing the
Analytics one-off), EmptyState, Skeleton, PageToolbar.

**Phase 2 — Shell & chrome (the Linear move).** Grouped sidebar per the IA above,
aligned nav rows, denser hierarchy, proper DS tooltips for collapsed mode, unified page
header/toolbar contract, consistent empty/loading states rolled out page-by-page.

**Phase 3 — Agent views (the differentiator).** Session detail as a Langfuse-style
nested tool-call timeline (timing, inputs, outputs, token/cost per model-call node)
alongside the existing chat surface; live streaming Logs over the event channel with
virtualization; always-available lightweight token/cost meter (not gated behind
Analytics); gateway/agent status indicators unified into one status component.

**Phase 4 — Accelerators & long tail.** Global ⌘K command palette + shortcut registry
with discoverable help; Analytics rebuilt on shadcn charts; remaining pages migrated;
page-monolith decomposition as each page is touched.

---

## 6. Sources & confidence

High-confidence (3-0 verified, primary sources): Linear redesign write-up
(linear.app/now/how-we-redesigned-the-linear-ui), AG-UI docs (docs.ag-ui.com),
Langfuse tracing docs (langfuse.com/docs/tracing), shadcn/ui changelog & docs
(ui.shadcn.com). Medium-confidence (verified but blog-tier or single-author): Geist/
Linear aesthetic characterization (vercel.com/geist, VoltAgent/awesome-design-md),
UI-density essay (mattstromawn.com/writing/ui-density), command-palette guidance
(uxpatterns.dev, maggieappleton.com). Refuted: "split-screen is the dominant agent UI
layout" (0-3).

Open questions worth a follow-up spike: (1) empirical trust/comprehension evidence for
split chat+activity vs unified interleaved timelines; (2) Base UI ecosystem maturity
for complex data tables/virtualized lists; (3) SSE vs WebSocket event-sourced diffs for
the local-first event layer without adopting the full AG-UI protocol.
