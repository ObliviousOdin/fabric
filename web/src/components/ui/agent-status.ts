import type { ComponentProps } from "react";
import type { Badge } from "@nous-research/ui/ui/components/badge";

/**
 * One canonical status vocabulary for every WORK surface (Sessions, Cron,
 * Chat) and the pure mappers from real backend shapes onto it — no
 * invented states (G1). Rendering lives in `AgentStatusBadge.tsx`; this
 * module stays component-free so fast refresh keeps working.
 */
export type AgentStatus =
  | "live"
  | "idle"
  | "scheduled"
  | "paused"
  | "failed"
  | "done";

type BadgeTone = NonNullable<ComponentProps<typeof Badge>["tone"]>;

/** G1 tone column: canonical status → DS `Badge` tone. */
export const AGENT_STATUS_TONES: Record<AgentStatus, BadgeTone> = {
  live: "success",
  idle: "secondary",
  scheduled: "outline",
  paused: "warning",
  failed: "destructive",
  done: "secondary",
};

/** A derived status plus an optional label override (e.g. "disabled"). */
export interface DerivedAgentStatus {
  status: AgentStatus;
  /** English label override; callers may localize before display. */
  label?: string;
}

/**
 * Session rows (and cron run rows, which share the session row shape):
 * `is_active` → live, ended → done, otherwise idle (not ended but stale).
 *
 * Note `is_active` is a heuristic — "activity in the last 5 min", not
 * "process running" (R2) — so tooltips should say "active", not "running".
 */
export function sessionAgentStatus(session: {
  is_active: boolean;
  ended_at: number | null;
}): AgentStatus {
  if (session.is_active) return "live";
  if (session.ended_at !== null) return "done";
  return "idle";
}

/**
 * Cron jobs: the `scheduled | paused | error | completed` state machine plus
 * the UI-derived "disabled" flavour of paused when `enabled === false`.
 * `last_status` ("ok"/"error") is a separate last-outcome chip — never
 * conflated with the scheduling state here (G1).
 */
export function cronJobAgentStatus(job: {
  enabled: boolean;
  state?: string | null;
}): DerivedAgentStatus {
  if (!job.enabled) return { status: "paused", label: "disabled" };
  switch (job.state) {
    case "paused":
      return { status: "paused" };
    case "error":
      return { status: "failed" };
    case "completed":
      return { status: "done" };
    default:
      // "scheduled" and anything unknown from a newer backend.
      return { status: "scheduled" };
  }
}

/**
 * Gateway process lifecycle (Y2): the served `gateway_state` enum
 * (`starting | running | draining | degraded | startup_failed | stopped |
 * null`, `/api/status` §0.1) plus the `gateway_running` boolean other
 * payloads carry (SystemPage, per-profile gateways on ProfilesPage).
 *
 * `draining`/`degraded` ride the warning-toned `paused` status with
 * truthful labels — they are real states served today, not inventions.
 * Unknown values from a newer backend render raw on the idle tone, never
 * crash (R18).
 */
export function gatewayAgentStatus(
  state: string | null,
  running: boolean,
): DerivedAgentStatus {
  if (running || state === "running") return { status: "live" };
  switch (state) {
    case "starting":
      return { status: "idle", label: "starting…" };
    case "startup_failed":
      return { status: "failed", label: "start failed" };
    case "draining":
      return { status: "paused", label: "draining" };
    case "degraded":
      return { status: "paused", label: "degraded" };
    case "stopped":
    case null:
      return { status: "idle", label: "stopped" };
    default:
      // Unknown value from a newer backend — raw label, idle tone (R18).
      return { status: "idle", label: state };
  }
}

/**
 * Chat sidecar connection: `open` → live, `error` → failed, `connecting` →
 * idle tone with a "connecting…" label override, `idle`/`closed` → idle.
 */
export function chatConnectionAgentStatus(
  state: "idle" | "connecting" | "open" | "closed" | "error",
): DerivedAgentStatus {
  switch (state) {
    case "open":
      return { status: "live" };
    case "error":
      return { status: "failed" };
    case "connecting":
      return { status: "idle", label: "connecting…" };
    default:
      return { status: "idle" };
  }
}
