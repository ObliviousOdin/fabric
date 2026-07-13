/**
 * Shared dashboard primitives ("terminal-grade minimalism"): token-only
 * styling, 1px-border elevation, mono type for technical readouts, spacing
 * via Tailwind utilities so everything scales with `--theme-spacing-mul`.
 */

/**
 * Generic sortable table. Typed columns (`key`/`header`/`sortable`/`align`/
 * `mono`/`render`), client-side sorting with nulls-last semantics and an
 * optional `defaultSortKey`, chrome-idiom header row. Callers render their
 * own empty state (typically an `<EmptyState />`) instead of the table.
 */
export { DataTable } from "./DataTable";
export type { DataTableColumn, DataTableProps } from "./DataTable";

/**
 * Centered muted empty placeholder: lucide icon slot + title + description +
 * optional action button. Used standalone in cards and page bodies.
 */
export { EmptyState } from "./EmptyState";
export type { EmptyStateProps } from "./EmptyState";

/**
 * Token-based loading placeholder (`bg-muted` + `animate-pulse`, no shimmer
 * gradients). Variants: `line`, `block`, `row-list` (n stacked lines).
 */
export { Skeleton } from "./Skeleton";
export type { SkeletonProps, SkeletonVariant } from "./Skeleton";

/**
 * Standard page toolbar row for `PageHeaderProvider` slots and in-page filter
 * rows — filters cluster leading, actions trailing, wraps on narrow widths.
 */
export { PageToolbar } from "./PageToolbar";
export type { PageToolbarProps } from "./PageToolbar";

/**
 * Canonical agent-status vocabulary (`live | idle | scheduled | paused |
 * failed | done`) + the shared badge that renders it (G1/G2): DS `Badge`
 * tone per status, optional pulsing live dot, lowercase `text-xs` labels.
 * The pure mappers (`./agent-status`) translate real backend shapes
 * (session rows, cron jobs, chat sidecar connection states) onto the
 * vocabulary.
 */
export {
  AGENT_STATUS_TONES,
  chatConnectionAgentStatus,
  cronJobAgentStatus,
  gatewayAgentStatus,
  sessionAgentStatus,
} from "./agent-status";
export type { AgentStatus, DerivedAgentStatus } from "./agent-status";
export { AgentStatusBadge } from "./AgentStatusBadge";
export type { AgentStatusBadgeProps } from "./AgentStatusBadge";

/**
 * Canonical capability-state vocabulary (`enabled | disabled | needs-setup
 * | broken`) for the CAPABILITIES section (CAP2): DS `Badge` tone per
 * state, pure mappers from real backend shapes (toolsets, plugins, MCP
 * servers, memory providers) plus the last-outcome chip mappers (MCP
 * probe, hub scan verdict). Component-free — rendering is plain `Badge`.
 */
export {
  CAPABILITY_STATE_TONES,
  mcpProbeOutcome,
  mcpServerCapabilityState,
  memoryProviderCapabilityState,
  pluginCapabilityState,
  scanVerdictOutcome,
  toolsetCapabilityState,
} from "./capability-state";
export type {
  CapabilityState,
  DerivedCapabilityState,
  ProbeOutcome,
} from "./capability-state";

/**
 * The CN1/CN2 two-axis mapping for the messaging-platform `state` overlay
 * (Channels, SessionsPage GatewayStrip): runtime states (`connected |
 * disconnected | fatal` + gateway-level overlays) → the G1 agent-status
 * vocabulary; configuration overlays (`disabled | not_configured |
 * pending_restart`) → the CAP2 capability-state vocabulary. Exactly one
 * mapper claims each known state; unknown states return null from both and
 * render raw (R18).
 */
export {
  channelConfigState,
  channelRuntimeStatus,
  KNOWN_CHANNEL_STATES,
} from "./channel-state";

/**
 * Shared capability row (CAP3) — the five-zone grammar (identity / state /
 * provenance / usage evidence / actions) for skill, toolset, plugin, MCP
 * server and catalog/hub rows: 1px box, optional leading Switch + glyph,
 * mono identity, badges, mono meta line, trailing actions, optional
 * expansion body.
 */
export { CapabilityRow } from "./CapabilityRow";
export type {
  CapabilityRowProps,
  CapabilityRowSwitch,
} from "./CapabilityRow";

/**
 * Truncated mono id (sessions, cron jobs, runs, tool calls) with full id in
 * `title` and click-to-copy + transient check icon.
 */
export { MonoId } from "./MonoId";
export type { MonoIdProps } from "./MonoId";

/**
 * Time infrastructure (`./time`): the epoch-seconds-vs-ISO normalization
 * every timestamp render must funnel through (R3), the shared 30 s/1 s
 * ticker, and the pure countdown formatter.
 */
export {
  formatCountdown,
  normalizeEpochSeconds,
  subscribeSharedTick,
  useNowMs,
} from "./time";

/**
 * Relative timestamp ("4m ago", absolute time in `title`) re-rendering on
 * the shared module-level ticker — one interval, not one per instance.
 */
export { RelativeTime } from "./RelativeTime";
export type { RelativeTimeProps } from "./RelativeTime";

/**
 * Live `in 2h 14m` countdown to an ISO timestamp (cron `next_run_at`),
 * 1 s resolution inside the final two minutes, `overdue` warning past due.
 */
export { NextRunCountdown } from "./NextRunCountdown";
export type { NextRunCountdownProps } from "./NextRunCountdown";

/**
 * Shared "an agent ran" row for the Sessions ledger and the Cron
 * run-history drawer: 1px box, optional checkbox/source glyph, title +
 * `AgentStatusBadge`, mono meta line, trailing actions, expansion body.
 */
export { RunRow } from "./RunRow";
export type { RunRowProps } from "./RunRow";

/**
 * Run-row metadata vocabulary (`./source-icons`): the monochrome source
 * glyph mapping (G11) plus the compact token (`12.5k`) and cost (`$0.0123`)
 * formatters shared by the Sessions ledger and the Analytics workload
 * report — one mapping so a run reads the same on every page.
 */
export {
  SOURCE_ICONS,
  formatCompact,
  formatCost,
  sourceIcon,
} from "./source-icons";

/**
 * Chronology node for session transcripts: left rail with role-toned dot,
 * `[dot] [label] [time]` header, indented body; keeps the FTS
 * `data-search-hit` anchor contract.
 */
export { TimelineNode } from "./TimelineNode";
export type { TimelineNodeKind, TimelineNodeProps } from "./TimelineNode";
