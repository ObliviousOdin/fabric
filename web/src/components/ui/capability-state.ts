import type { ComponentProps } from "react";
import type { Badge } from "@/components/fabric/Badge";

/**
 * One canonical capability-state vocabulary for every CAPABILITIES surface
 * (Skills, Toolsets, Plugins, MCP, memory/context providers) and the pure
 * mappers from real backend shapes onto it — no invented states (CAP2).
 *
 * Capabilities are equipment, not agents: `enabled/disabled` is
 * configuration, not lifecycle, so `AgentStatusBadge` is never used on
 * these pages. Rendering is plain DS `Badge` with the mapped tone; this
 * module stays component-free (same pattern as `agent-status.ts`) so fast
 * refresh keeps working and the mapping is unit-testable.
 */
export type CapabilityState =
  | "enabled"
  | "disabled"
  | "needs-setup"
  | "broken";

type BadgeTone = NonNullable<ComponentProps<typeof Badge>["tone"]>;

/**
 * CAP2 tone column: capability state → DS `Badge` tone.
 *
 * Deliberate corrections encoded here (spec CAP2/P2/X2):
 * - `disabled` is `outline`, never `destructive` — disabled is a choice,
 *   not a failure (fixes the Plugins-page tone bug).
 * - `needs-setup` is `warning`, not `destructive` — it needs setup, it
 *   isn't broken (plugin `auth_required`, unconfigured toolsets).
 */
export const CAPABILITY_STATE_TONES: Record<CapabilityState, BadgeTone> = {
  enabled: "success",
  disabled: "outline",
  "needs-setup": "warning",
  broken: "destructive",
};

/**
 * A derived capability state plus its English label. Callers may localize
 * via the optional `t.capabilities` group before display (O5 pattern);
 * unknown backend enum values pass through as their raw string and map to
 * the `disabled`/outline tone — render, never crash (R18).
 */
export interface DerivedCapabilityState {
  state: CapabilityState;
  /** English label; callers may localize before display. */
  label: string;
}

/**
 * Toolsets: `enabled && !configured` → needs setup (replaces the amber
 * literal, G10 fix); enabled → `active`; off → `inactive` (a toolset is
 * not-yet-enabled rather than explicitly switched off).
 */
export function toolsetCapabilityState(ts: {
  enabled: boolean;
  configured: boolean;
}): DerivedCapabilityState {
  if (ts.enabled && !ts.configured) {
    return { state: "needs-setup", label: "needs setup" };
  }
  if (ts.enabled) return { state: "enabled", label: "active" };
  return { state: "disabled", label: "inactive" };
}

/**
 * Plugins: `runtime_status` only — keep `disabled` (explicit choice) and
 * `inactive` (not-yet-enabled) as distinct words on the same outline tone
 * (CAP2). The P2 `needs auth` chip is a *separate* Badge the page renders
 * with `CAPABILITY_STATE_TONES["needs-setup"]` when `auth_required` — it
 * says something different from enabled/disabled, so it never merges into
 * this state.
 */
export function pluginCapabilityState(row: {
  runtime_status: string;
}): DerivedCapabilityState {
  switch (row.runtime_status) {
    case "enabled":
      return { state: "enabled", label: "enabled" };
    case "disabled":
      return { state: "disabled", label: "disabled" };
    case "inactive":
      return { state: "disabled", label: "inactive" };
    default:
      // Unknown value from a newer backend — raw label, outline tone (R18).
      return { state: "disabled", label: row.runtime_status };
  }
}

/**
 * MCP servers: the config `enabled` flag. Config, not health — health is
 * only knowable at explicit `/test`/`/auth` probe time and renders as a
 * separate `mcpProbeOutcome` chip. State badge `title`s must carry the
 * "takes effect on next gateway restart" copy (R16).
 */
export function mcpServerCapabilityState(s: {
  enabled: boolean;
}): DerivedCapabilityState {
  if (s.enabled) return { state: "enabled", label: "enabled" };
  return { state: "disabled", label: "disabled" };
}

/**
 * Memory/context providers: backend `status` enum → CAP2 states. Labels
 * match the existing Plugins-page `MEMORY_STATUS_LABEL` map (already
 * CAP2-conformant, P3).
 */
export function memoryProviderCapabilityState(p: {
  status: string;
}): DerivedCapabilityState {
  switch (p.status) {
    case "ready":
      return { state: "enabled", label: "ready" };
    case "needs_config":
      return { state: "needs-setup", label: "needs setup" };
    case "readiness_unknown":
      return { state: "needs-setup", label: "readiness unknown" };
    case "unavailable":
      return { state: "broken", label: "unavailable" };
    case "missing":
      return { state: "broken", label: "missing" };
    default:
      // Unknown value from a newer backend — raw label, outline tone (R18).
      return { state: "disabled", label: p.status };
  }
}

/**
 * A last-outcome chip (probe/scan result) — the cron `last_status`
 * precedent: rendered as a separate chip next to the state badge, never
 * merged into it (CAP2).
 */
export interface ProbeOutcome {
  tone: BadgeTone;
  /** English label; callers may localize/extend (e.g. append a RelativeTime). */
  label: string;
}

/**
 * MCP `/test` (and `/auth`) probe result → outcome chip:
 * `reachable · N tools` on success, `unreachable` on failure. Session-local
 * by design — there is no persisted MCP health (X-decision 1).
 */
export function mcpProbeOutcome(result: {
  ok: boolean;
  tools?: Array<unknown> | null;
}): ProbeOutcome {
  if (!result.ok) return { tone: "destructive", label: "unreachable" };
  const count = result.tools?.length ?? 0;
  return {
    tone: "success",
    label: `reachable · ${count} ${count === 1 ? "tool" : "tools"}`,
  };
}

/**
 * Skill-hub security-scan verdict → outcome chip (`safe/caution/dangerous`,
 * matching the ScanPanel token sweep: emerald→success, amber→warning,
 * red→destructive).
 */
export function scanVerdictOutcome(verdict: string): ProbeOutcome {
  switch (verdict) {
    case "safe":
      return { tone: "success", label: "safe" };
    case "caution":
      return { tone: "warning", label: "caution" };
    case "dangerous":
      return { tone: "destructive", label: "dangerous" };
    default:
      // Unknown verdict from a newer backend — raw label, outline tone (R18).
      return { tone: "outline", label: verdict };
  }
}
