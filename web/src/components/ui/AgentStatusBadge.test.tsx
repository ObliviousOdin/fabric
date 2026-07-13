// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  AGENT_STATUS_TONES,
  chatConnectionAgentStatus,
  cronJobAgentStatus,
  gatewayAgentStatus,
  sessionAgentStatus,
} from "@/components/ui/agent-status";
import { AgentStatusBadge } from "@/components/ui/AgentStatusBadge";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("G1 status mapping", () => {
  it("maps session rows: is_active → live, ended → done, stale → idle", () => {
    expect(sessionAgentStatus({ is_active: true, ended_at: null })).toBe("live");
    expect(sessionAgentStatus({ is_active: false, ended_at: 1720000000 })).toBe(
      "done",
    );
    expect(sessionAgentStatus({ is_active: false, ended_at: null })).toBe(
      "idle",
    );
  });

  it("maps cron jobs through the scheduled|paused|error|completed machine", () => {
    expect(cronJobAgentStatus({ enabled: true, state: "scheduled" })).toEqual({
      status: "scheduled",
    });
    expect(cronJobAgentStatus({ enabled: true, state: "paused" })).toEqual({
      status: "paused",
    });
    expect(cronJobAgentStatus({ enabled: true, state: "error" })).toEqual({
      status: "failed",
    });
    expect(cronJobAgentStatus({ enabled: true, state: "completed" })).toEqual({
      status: "done",
    });
    // Unknown/missing state degrades to scheduled, never an invented state.
    expect(cronJobAgentStatus({ enabled: true, state: null })).toEqual({
      status: "scheduled",
    });
  });

  it("maps enabled === false to paused with the 'disabled' label, beating state", () => {
    expect(cronJobAgentStatus({ enabled: false, state: "scheduled" })).toEqual({
      status: "paused",
      label: "disabled",
    });
    expect(cronJobAgentStatus({ enabled: false, state: "error" })).toEqual({
      status: "paused",
      label: "disabled",
    });
  });

  it("maps chat sidecar connection states", () => {
    expect(chatConnectionAgentStatus("open")).toEqual({ status: "live" });
    expect(chatConnectionAgentStatus("error")).toEqual({ status: "failed" });
    expect(chatConnectionAgentStatus("connecting")).toEqual({
      status: "idle",
      label: "connecting…",
    });
    expect(chatConnectionAgentStatus("idle")).toEqual({ status: "idle" });
    expect(chatConnectionAgentStatus("closed")).toEqual({ status: "idle" });
  });

  it("maps the gateway process lifecycle (Y2), incl. draining/degraded", () => {
    expect(gatewayAgentStatus("running", true)).toEqual({ status: "live" });
    // `running` beats a stale/odd state string, and vice versa.
    expect(gatewayAgentStatus(null, true)).toEqual({ status: "live" });
    expect(gatewayAgentStatus("running", false)).toEqual({ status: "live" });
    expect(gatewayAgentStatus("starting", false)).toEqual({
      status: "idle",
      label: "starting…",
    });
    expect(gatewayAgentStatus("startup_failed", false)).toEqual({
      status: "failed",
      label: "start failed",
    });
    expect(gatewayAgentStatus("draining", false)).toEqual({
      status: "paused",
      label: "draining",
    });
    expect(gatewayAgentStatus("degraded", false)).toEqual({
      status: "paused",
      label: "degraded",
    });
    expect(gatewayAgentStatus("stopped", false)).toEqual({
      status: "idle",
      label: "stopped",
    });
    expect(gatewayAgentStatus(null, false)).toEqual({
      status: "idle",
      label: "stopped",
    });
    // Unknown value from a newer backend — raw label, never crash (R18).
    expect(gatewayAgentStatus("hibernating", false)).toEqual({
      status: "idle",
      label: "hibernating",
    });
  });

  it("assigns the G1 tone column", () => {
    expect(AGENT_STATUS_TONES).toEqual({
      live: "success",
      idle: "secondary",
      scheduled: "outline",
      paused: "warning",
      failed: "destructive",
      done: "secondary",
    });
  });
});

describe("AgentStatusBadge", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("shows the pulsing dot only for live by default", async () => {
    await act(async () => {
      root.render(<AgentStatusBadge status="live" />);
    });
    expect(container.textContent).toContain("live");
    expect(container.querySelector(".animate-pulse")).not.toBeNull();

    await act(async () => {
      root.render(<AgentStatusBadge status="done" />);
    });
    expect(container.textContent).toContain("done");
    expect(container.querySelector(".animate-pulse")).toBeNull();
  });

  it("honors pulse and label overrides", async () => {
    await act(async () => {
      root.render(
        <AgentStatusBadge status="idle" label="connecting…" pulse />,
      );
    });
    expect(container.textContent).toContain("connecting…");
    expect(container.querySelector(".animate-pulse")).not.toBeNull();

    await act(async () => {
      root.render(<AgentStatusBadge status="live" pulse={false} />);
    });
    expect(container.querySelector(".animate-pulse")).toBeNull();
  });
});
