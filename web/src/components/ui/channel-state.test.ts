import { describe, expect, it } from "vitest";

import {
  channelConfigState,
  channelRuntimeStatus,
  KNOWN_CHANNEL_STATES,
} from "@/components/ui/channel-state";

describe("CN2 channel runtime-axis mapping", () => {
  it("maps gateway-persisted runtime states onto the G1 vocabulary", () => {
    expect(channelRuntimeStatus("connected")).toEqual({ status: "live" });
    expect(channelRuntimeStatus("disconnected")).toEqual({
      status: "failed",
      label: "disconnected",
    });
    expect(channelRuntimeStatus("fatal")).toEqual({
      status: "failed",
      label: "error",
    });
  });

  it("maps the gateway-level web overlays", () => {
    expect(channelRuntimeStatus("startup_failed")).toEqual({
      status: "failed",
      label: "start failed",
    });
    expect(channelRuntimeStatus("gateway_stopped")).toEqual({
      status: "idle",
      label: "gateway stopped",
    });
  });

  it("returns null for config-axis and unknown states", () => {
    expect(channelRuntimeStatus("disabled")).toBeNull();
    expect(channelRuntimeStatus("not_configured")).toBeNull();
    expect(channelRuntimeStatus("pending_restart")).toBeNull();
    expect(channelRuntimeStatus("some_future_state")).toBeNull();
    expect(channelRuntimeStatus("")).toBeNull();
  });
});

describe("CN2 channel config-axis mapping", () => {
  it("maps the web-server configuration overlays onto CAP2 states", () => {
    expect(channelConfigState("disabled")).toEqual({
      state: "disabled",
      label: "disabled",
    });
    expect(channelConfigState("not_configured")).toEqual({
      state: "needs-setup",
      label: "not configured",
    });
    expect(channelConfigState("pending_restart")).toEqual({
      state: "needs-setup",
      label: "restart to apply",
    });
  });

  it("returns null for runtime-axis and unknown states", () => {
    expect(channelConfigState("connected")).toBeNull();
    expect(channelConfigState("disconnected")).toBeNull();
    expect(channelConfigState("fatal")).toBeNull();
    expect(channelConfigState("startup_failed")).toBeNull();
    expect(channelConfigState("gateway_stopped")).toBeNull();
    expect(channelConfigState("some_future_state")).toBeNull();
    expect(channelConfigState("")).toBeNull();
  });
});

describe("CN1 two-axis discipline", () => {
  it("exactly one mapper claims every known state (the axes never merge)", () => {
    for (const state of KNOWN_CHANNEL_STATES) {
      const runtime = channelRuntimeStatus(state);
      const config = channelConfigState(state);
      const claimed = Number(runtime !== null) + Number(config !== null);
      expect(claimed, `state "${state}"`).toBe(1);
    }
  });

  it("neither mapper claims unknown states — callers render them raw (R18)", () => {
    for (const state of ["brand_new_state", "degraded", "draining"]) {
      // `degraded`/`draining` are gateway *process* states, never platform
      // states — they belong to `gatewayAgentStatus`, not this module.
      expect(channelRuntimeStatus(state)).toBeNull();
      expect(channelConfigState(state)).toBeNull();
    }
  });

  it("preserves every label of the shipped ChannelsPage STATE_BADGE table", () => {
    // The 8-row inline table this module replaces (H2): same words,
    // shared tones.
    const labels: Record<string, string> = {};
    for (const state of KNOWN_CHANNEL_STATES) {
      const runtime = channelRuntimeStatus(state);
      const config = channelConfigState(state);
      labels[state] = runtime
        ? (runtime.label ?? runtime.status)
        : (config?.label ?? state);
    }
    expect(labels).toEqual({
      connected: "live",
      disconnected: "disconnected",
      fatal: "error",
      startup_failed: "start failed",
      gateway_stopped: "gateway stopped",
      disabled: "disabled",
      not_configured: "not configured",
      pending_restart: "restart to apply",
    });
  });
});
