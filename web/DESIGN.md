# Fabric Woven Operations design contract

This document is the source of truth for Fabric-owned Workspace and Admin
surfaces, dashboard plugins, and future engineering handoff. It replaces the
inherited upstream console language as the canonical product experience.
Historical skins remain compatibility seams; they do not define Fabric.

## Product character

Fabric is a multi-agent operations platform. It should feel calm, direct, and
inspectable: users can see how an objective becomes durable work, which agent
owns the next step, what evidence supports an outcome, and where a person must
intervene.

The design direction is **Woven Operations**. The visual identity comes from
causal relationships—threads, handoffs, provenance, dependencies, and
artifacts—not from decorative AI chrome.

The governing principles are:

1. Make the user's objective and next decision the visual anchors.
2. Show relationships between work, agents, memory, evidence, and approvals.
3. Give every live state an explicit label and freshness signal.
4. Use purple for action, focus, and the active thread—not as a page wash.
5. Prefer ledger sections and ruled groups to grids of equal-weight cards.
6. Show less by default; keep operational depth one inspection away.
7. Never use color as the only carrier of meaning.

Fabric must not resemble a terminal skin, a generic SaaS metrics dashboard, a
warehouse portal, or a decorative AI control room. Avoid teal/cyan page washes,
glow, grain, novelty display fonts, uppercase chrome, bubbly card grids, and
gradient actions.

## Foundation layers

Tokens have four distinct responsibilities:

1. **Foundation** — Fabric violet, neutral ramps, spacing, type, and
   motion.
2. **Product semantics** — canvas, surfaces, text, border, status, thread, and
   bracket roles.
3. **Components** — control- and pattern-specific aliases.
4. **Tenant brand** — logo and action accent only.

A tenant-specific accent may affect primary actions, focus, selection
markers, charts that explicitly represent the tenant, and active thread
segments. It must not replace default text, structural borders, all icons, all
status colors, or the whole canvas.

The canonical source is `apps/design-system/src/tokens/tokens.json`; generated
CSS and JavaScript are artifacts, not hand-edited sources.

## Color

Fabric Light uses a warm woven-paper neutral. Fabric Dark uses violet-charcoal.
Both use the canonical Fabric purple `#4628CC` as a restrained action accent.

| Role           | Fabric Light | Fabric Dark                              |
| -------------- | ------------ | ---------------------------------------- |
| Canvas         | `#FCFAF6`    | `#0E0C11`                                |
| Surface        | `#F6F4F0`    | `#151318`                                |
| Raised surface | `#F0EEEA`    | `#1D1A1F`                                |
| Inset surface  | `#EDEBE7`    | `#201E23`                                |
| Primary text   | `#221F1A`    | `#EAE6EE`                                |
| Muted text     | `#5B5852`    | `#ADA9B1`                                |
| Border         | `#D1CFCB`    | `#28252A`                                |
| Brand/action   | `#4628CC`    | accessible violet derived from `#4628CC` |
| Active thread  | `#4628CC`    | `#9481E6`                                |

Color budget:

- Neutral surfaces should occupy at least 90% of normal application screens.
- Purple marks selected, focused, or user-controlled elements.
- Status colors stay semantic and independent from selection.
- Status color should normally occupy a dot, icon, line, or 8–12% tint rather
  than an entire panel.

Status language pairs shape or icon, label, and color:

- Live: ring plus restrained breathing motion.
- Running: directional thread segment.
- Queued: hollow diamond.
- Waiting for approval: split amber marker.
- Complete: check plus completion time.
- Blocked or failed: red square plus recovery copy.

## Typography

- Product UI uses the native system sans stack. This avoids a render-blocking
  font request and reads naturally on each supported desktop platform.
- Technical values only—paths, IDs, versions, hashes, models, tools,
  timestamps, and logs—use the theme monospace stack.
- JetBrains Mono is reserved for the embedded terminal and technical readouts.
- Interface copy is sentence case. Uppercase display copy and wide tracked
  labels are not part of canonical Fabric.
- Body and navigation copy are 14–16px. Metadata is never below 12px.
- Use 600 as the normal heading ceiling; reserve 700 for exceptional emphasis.
- Body line height is 1.45–1.6. Heading line height is 1.15–1.3.

The inherited Collapse, Mondwest, Rules Expanded, and Rules Compressed faces
must not be loaded by the canonical application. Compatibility classes map to
the system sans until their consumers migrate to Fabric-owned primitives.

## Spacing and shape

- Use a 4px foundation with 8, 12, 16, 24, and 32px as normal steps.
- Interactive targets are at least 44×44px, including icon-only controls.
- Default radius is 8px. Use 12px for object previews and dialogs.
- Chips and compact controls may use 4px; pills are reserved for binary or
  bounded status.
- Layout and spacing communicate hierarchy. Do not solve hierarchy with more
  borders, boxes, badges, or shadows.
- Shadows belong to overlays, previews, and selected movable objects—not every
  section.

## Signature motifs

The motifs are functional structural cues, never wallpaper.

### Woven canvas

`.fabric-woven-canvas` provides a subtle crossing-line field for onboarding,
empty, planning, or graph canvases. Do not apply it behind dense reading or to
every page.

### Thread

`.fabric-thread` creates the causal spine for events, handoffs, evidence,
memory retrievals, approvals, and artifacts. `data-active="true"` marks only
the currently executing or selected lineage.

### Bracket

`.fabric-bracket` adapts the wordmark underline into a selected-region marker.
Use it for an active navigation region, focused artifact, or inspector section;
never put brackets around every card.

## Surface model

Use three primary surface types:

1. **Canvas** — navigation and page composition.
2. **Ledger section** — operational lists, status, history, and compact
   summaries separated by rules.
3. **Raised object** — artifacts, previews, dialogs, and the selected task.

Cards represent objects, not arbitrary layout containers. A row of four equal
metric cards is rarely the right hierarchy for Fabric. Home should read as an
operations briefing: what needs attention, what is in motion, what completed,
and what evidence was produced.

## Workspace and Admin

Workspace and Admin are coordinated experiences with different emphases.

### Workspace

Workspace is objective-first and action-oriented. Its primary navigation is
Home, Chat, Work Board, Conversations, Agents, Memory, Knowledge, Automations,
Approvals, Activity, and Insights. Surfaces prioritize objectives, named
agents, dependencies, handoffs, evidence, artifacts, and decisions.

Chat keeps the real PTY-backed transcript and composer. Supporting panels use
the thread language to connect conversation, live agent activity, task context,
evidence, memory, and artifacts without becoming a second chat implementation.

### Admin

Admin is policy-, configuration-, and risk-oriented. Its primary navigation is
Integrations, Channels and Events, AI Runtime, Security and Access, System,
Advanced, and Help. It uses the same tokens and motifs but favors explicit
tables, policy summaries, audit trails, and destructive-action clarity.

The two experiences must look related without duplicating the same page
hierarchy or forcing technical inventory into Workspace.

## Shell hierarchy

- Keep a responsive left navigation shell.
- Put tenant, workspace, and site scope in the persistent top scope bar.
- Show agent profile as secondary context, never as a tenant substitute.
- The active navigation item uses a bracket/edge marker instead of a filled
  dark row.
- The bottom of the rail contains only identity, one health signal, and access
  to settings.
- Detailed gateway state, restart/update controls, version, and authentication
  diagnostics belong in Admin/System or a compact system popover.
- Light/dark is a quick preference. The full legacy/custom theme gallery lives
  under Advanced rather than occupying the primary rail.

## Work surfaces

The board, graph, timeline, and outline are projections of one durable work
model. They share:

- `StatusSignal`: icon or shape, label, semantic status, and freshness.
- `WorkNode`: type, human title, named owner, run state, and progress.
- `ContextBar`: tenant/workspace/site, agent profile, conversation, freshness.
- `Inspector`: selected work ordered by user meaning first.
- `ActivityRow`: concise, timestamped, and linked to its source work.

Goal, task, agent run, approval, artifact, and memory evidence must remain
distinguishable without color. Dependency edges are solid; spawn or ownership
edges are dashed. Selection emphasizes lineage and de-emphasizes unrelated
work. Graphs never rearrange while the user is reading them.

## Interaction and state contract

- Every live view exposes Live, Paused, Reconnecting, or Stale plus last update.
- Pause updates freezes presentation only. Pausing an agent is a separate,
  confirmed operational action.
- Motion communicates newly spawned, handed-off, or selected work and respects
  `prefers-reduced-motion`.
- Use the shared easing curve with 100ms press, 150–200ms state change, and
  300ms drawer/dialog durations. Animate opacity and transform only.
- Keyboard users can move through work, open inspection, and dismiss overlays;
  focus is always visible.
- Relationship views have an equivalent outline for screen readers, keyboard
  users, zoomed layouts, and narrow screens.
- Every screen accounts for normal, loading, empty, filtered-empty, degraded,
  offline, permission-denied, read-only, in-progress, success, failure,
  conflict, and destructive-confirmation states.

## Performance contract

- Route screens remain lazy; shell primitives must not import page-only effects.
- English is the boot dictionary. Other locale dictionaries load only when
  selected and remain cached after their first successful load.
- Canonical badges use Fabric's dependency-light ledger chip, including through
  the plugin SDK. A status/provenance chip must not pull Lens, BlendMode, Leva,
  GSAP, canvas, or WebGL infrastructure into the initial application graph.
- Public asset directories contain only assets requested at runtime. Legacy
  display fonts do not remain as inert build payload.
- Performance changes are measured against HTML-referenced initial bytes; moving
  eager code to another preloaded chunk is not an improvement.

## Iconography

Canonical icons use a 20–24px grid, 1.75–2px stroke, round caps and joins, and
`currentColor`. A `FabricIcon` boundary should normalize imported glyphs while
first-party thread, handoff, approval, artifact, provenance, and memory-conflict
icons are developed. No emoji or Unicode glyphs stand in for interface icons.

## Compatibility

- Existing theme IDs and plugin globals remain compatibility seams.
- Fabric Light/Dark are the canonical pair. Historical teal, blue, and novelty
  themes are optional skins, not examples of the Fabric product language.
- Existing `@nous-research/ui` code may continue to provide behavior while
  Fabric-owned wrappers take over rendering and visual decisions.
- New dashboard plugins consume host semantic tokens and motif utilities.
- A surface should remain recognizably Fabric with the logo removed; passing
  that test requires the thread, bracket, ledger, and restrained-color grammar,
  not more branding decoration.
