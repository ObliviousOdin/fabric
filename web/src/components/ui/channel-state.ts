import type { DerivedAgentStatus } from "./agent-status";
import type { DerivedCapabilityState } from "./capability-state";

/**
 * One shared mapping for the messaging-platform `state` overlay (CN2) —
 * consumed by ChannelsPage and SessionsPage's `GatewayStrip` so a channel
 * wears the same words and tones on every surface.
 *
 * The backend field mixes two axes (verified in `fabric_cli/web_server.py`
 * `_platform_entry`, ~L7361–7379): the gateway itself only ever persists
 * `connected | disconnected | fatal` (`gateway/platforms/base.py`
 * `_mark_connected`/`_mark_disconnected`/`_set_fatal_error`, ~L3075);
 * everything else — `disabled`, `not_configured`, `pending_restart`,
 * `startup_failed`, `gateway_stopped` — is a web-server-derived overlay
 * computed per request. CN1 formalizes the split:
 *
 * - **Runtime axis** (`channelRuntimeStatus`): a link that is actually
 *   up/down → the G1 agent-status vocabulary (`AgentStatusBadge`).
 * - **Configuration axis** (`channelConfigState`): enabled/disabled/
 *   needs-setup → the CAP2 capability-state vocabulary (plain `Badge`).
 *
 * Exactly one mapper returns non-null for every known state (asserted in
 * the unit tests); the frontend never re-derives the overlay itself from
 * `enabled`/`configured` (R23). Unknown states from a newer backend return
 * null from both mappers — callers render the raw string on the
 * idle/outline tone, never crash (R18).
 *
 * Component-free (same pattern as `agent-status.ts` /
 * `capability-state.ts`) so fast refresh keeps working and the mapping is
 * unit-testable.
 */

/** Runtime-axis states (persisted by the gateway, plus gateway-level web overlays). */
export function channelRuntimeStatus(
  state: string,
): DerivedAgentStatus | null {
  switch (state) {
    case "connected":
      return { status: "live" };
    case "disconnected":
      return { status: "failed", label: "disconnected" };
    case "fatal":
      return { status: "failed", label: "error" };
    case "startup_failed":
      return { status: "failed", label: "start failed" };
    case "gateway_stopped":
      return { status: "idle", label: "gateway stopped" };
    default:
      return null;
  }
}

/** Config-axis states (web-server overlay; never gateway-persisted). */
export function channelConfigState(
  state: string,
): DerivedCapabilityState | null {
  switch (state) {
    case "disabled":
      return { state: "disabled", label: "disabled" };
    case "not_configured":
      return { state: "needs-setup", label: "not configured" };
    case "pending_restart":
      return { state: "needs-setup", label: "restart to apply" };
    default:
      return null;
  }
}

/**
 * The full known vocabulary served today (§0.1 of the Connect/System spec):
 * three gateway-persisted runtime states + five web-server overlays. Used
 * by the unit tests to assert the two mappers partition it exactly; NOT a
 * gate at render time — unknown states must still render raw (R18).
 */
export const KNOWN_CHANNEL_STATES = [
  "connected",
  "disconnected",
  "fatal",
  "startup_failed",
  "gateway_stopped",
  "disabled",
  "not_configured",
  "pending_restart",
] as const;
