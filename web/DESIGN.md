# Fabric dashboard design system

This document is the contract for Fabric-owned dashboard surfaces and dashboard
plugins. It replaces the inherited upstream visual conventions as the default
product language while preserving historical themes as optional skins.

## Product character

Fabric should feel calm, direct, and inspectable. The interface explains what
the agents are doing, why they are doing it, and whether a person needs to act.
It should not resemble a terminal skin, an infrastructure inventory, or a
decorative AI control room.

The governing principles are:

1. Make the user's outcome the visual anchor.
2. Reveal capability in context instead of exposing the implementation tree.
3. Give every live state an explicit label and freshness signal.
4. Prefer tonal surfaces and one-pixel borders to glow, grain, or ornament.
5. Show less by default; make deeper operational detail easy to inspect.
6. Never use color as the only carrier of meaning.

## Foundations

### Typography

- Product language uses the theme's system-humanist sans stack.
- Technical values only—branches, paths, IDs, models, tools, timestamps, and
  logs—use the theme's monospace stack.
- Interface copy is sentence case. Uppercase display copy and tracked labels
  are not part of the canonical Fabric experience.
- Body copy is at least 14px; primary reading copy should be 15–16px.
- Line height is 1.45–1.6 for body copy and 1.15–1.3 for headings.

### Spacing and shape

- Use a 4px foundation with 8, 12, 16, 24, and 32px as the normal steps.
- Interactive targets are at least 44×44px, including icon-only controls.
- Default radius is 8px. Use smaller radii for compact controls and larger
  radii only for drawers or modal surfaces.
- Layout and spacing communicate hierarchy. Do not solve hierarchy with more
  borders, boxes, badges, or shadows.

### Color

Consume semantic dashboard tokens rather than literal colors. The canonical
themes are the generated Fabric Light and Fabric Dark pair.

| Role                  | Contract                                           |
| --------------------- | -------------------------------------------------- |
| Canvas                | Warm or neutral low-chroma background              |
| Raised surface        | Tonal surface with a 1px semantic border           |
| Primary text          | Highest accessible neutral contrast                |
| Secondary text        | WCAG AA at the rendered size                       |
| Interaction/selection | Cobalt/teal theme accent; one crisp outline        |
| Running               | Blue status indicator plus text; no selection ring |
| Complete              | Olive/green plus text or icon                      |
| Review/decision       | Coral/amber plus explicit action copy              |
| Blocked/failed        | Red plus explicit status and recovery copy         |
| Queued                | Neutral gray plus text                             |

Selection and status are separate concepts. The accent outline means selected,
never merely running. Glow is not a normal state.

## Work surfaces

The Kanban board, graph, timeline, and outline are projections of the same work
model. They share these primitives:

- `WorkStatusBadge`: icon, text, and semantic status color.
- `WorkNode`: explicit type label, human title, owner/run state, and progress.
- `ViewSwitcher`: Board, Graph, and Outline/Timeline projections.
- `ContextBar`: repository, branch, conversation, and freshness.
- `GraphToolbar`: filter, fit, and live-update controls.
- `InspectorDrawer`: selected work only, ordered by user meaning first.
- `ActivityRow`: concise, timestamped, and linked to its work item.

Node types must remain distinguishable without color:

- Goal: wide root that states the outcome and plan progress.
- Step/task: standard work card with completion or review state.
- Agent run: compact identity/run card attached to its task.
- Artifact/change: small leaf naming the output it represents.

Dependency edges are solid and spawn/ownership edges are dashed. Selecting a
node emphasizes its lineage and de-emphasizes unrelated work. The graph never
rearranges while the user is reading it.

## Interaction contract

- Every live view exposes `Live`, `Paused`, `Reconnecting`, or `Stale`, plus
  the last update time.
- `Pause updates` only freezes visual updates. `Pause agent…` is a separate,
  confirmed operational action that explains its consequence.
- Keyboard: arrow keys move between work nodes, Enter opens the inspector,
  and Escape closes it. Focus is always visible.
- Graph relationships have an equivalent Outline view for screen readers,
  zoomed layouts, keyboard users, and narrow screens.
- Motion communicates newly spawned or selected work only and respects
  `prefers-reduced-motion`.
- Empty states explain what the surface is for and offer a relevant next step.
- Narrow screens default to Board or Outline; details open as a full-width
  drawer instead of squeezing the graph.

## Shell hierarchy

Primary navigation is task-oriented: Chat, Work, Schedule, and Team. Technical
capabilities such as models, skills, plugins, MCP, channels, and webhooks belong
under contextual Build, Connect, or Settings groups. A user's active project
and goal should frame the experience before platform inventory.

## Compatibility

- Existing theme IDs and legacy plugin globals/classes remain compatibility
  seams, not visible brand language.
- Fabric Light/Dark are the default pair. Fabric Teal/Blue and other historical
  themes remain selectable skins.
- Existing `@nous-research/ui` primitives may continue to provide behavior
  while Fabric-owned wrapper styles define the visible product language.
- New dashboard plugins use the host's semantic tokens and current icon library
  instead of adding a second visual system.
