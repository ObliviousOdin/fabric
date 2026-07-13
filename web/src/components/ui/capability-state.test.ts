import { describe, expect, it } from "vitest";

import {
  CAPABILITY_STATE_TONES,
  mcpProbeOutcome,
  mcpServerCapabilityState,
  memoryProviderCapabilityState,
  pluginCapabilityState,
  scanVerdictOutcome,
  toolsetCapabilityState,
} from "@/components/ui/capability-state";

describe("CAPABILITY_STATE_TONES", () => {
  it("encodes the CAP2 tone column", () => {
    expect(CAPABILITY_STATE_TONES).toEqual({
      enabled: "success",
      disabled: "outline",
      "needs-setup": "warning",
      broken: "destructive",
    });
  });

  it("never tones disabled as destructive (the Plugins-page bug)", () => {
    expect(CAPABILITY_STATE_TONES.disabled).not.toBe("destructive");
  });
});

describe("toolsetCapabilityState", () => {
  it("maps enabled+configured to active", () => {
    expect(toolsetCapabilityState({ enabled: true, configured: true })).toEqual(
      { state: "enabled", label: "active" },
    );
  });

  it("maps enabled-but-unconfigured to needs setup (warning, not amber literal)", () => {
    expect(
      toolsetCapabilityState({ enabled: true, configured: false }),
    ).toEqual({ state: "needs-setup", label: "needs setup" });
  });

  it("maps off to inactive regardless of configuration", () => {
    expect(
      toolsetCapabilityState({ enabled: false, configured: false }),
    ).toEqual({ state: "disabled", label: "inactive" });
    expect(
      toolsetCapabilityState({ enabled: false, configured: true }),
    ).toEqual({ state: "disabled", label: "inactive" });
  });
});

describe("pluginCapabilityState", () => {
  it("keeps disabled and inactive as distinct words on the same tone", () => {
    expect(pluginCapabilityState({ runtime_status: "enabled" })).toEqual({
      state: "enabled",
      label: "enabled",
    });
    expect(pluginCapabilityState({ runtime_status: "disabled" })).toEqual({
      state: "disabled",
      label: "disabled",
    });
    expect(pluginCapabilityState({ runtime_status: "inactive" })).toEqual({
      state: "disabled",
      label: "inactive",
    });
  });

  it("renders unknown runtime_status values raw instead of crashing (R18)", () => {
    expect(pluginCapabilityState({ runtime_status: "hibernating" })).toEqual({
      state: "disabled",
      label: "hibernating",
    });
  });
});

describe("mcpServerCapabilityState", () => {
  it("maps the config enabled flag", () => {
    expect(mcpServerCapabilityState({ enabled: true })).toEqual({
      state: "enabled",
      label: "enabled",
    });
    expect(mcpServerCapabilityState({ enabled: false })).toEqual({
      state: "disabled",
      label: "disabled",
    });
  });
});

describe("memoryProviderCapabilityState", () => {
  it("maps the backend status enum onto CAP2 states", () => {
    expect(memoryProviderCapabilityState({ status: "ready" })).toEqual({
      state: "enabled",
      label: "ready",
    });
    expect(memoryProviderCapabilityState({ status: "needs_config" })).toEqual({
      state: "needs-setup",
      label: "needs setup",
    });
    expect(
      memoryProviderCapabilityState({ status: "readiness_unknown" }),
    ).toEqual({ state: "needs-setup", label: "readiness unknown" });
    expect(memoryProviderCapabilityState({ status: "unavailable" })).toEqual({
      state: "broken",
      label: "unavailable",
    });
    expect(memoryProviderCapabilityState({ status: "missing" })).toEqual({
      state: "broken",
      label: "missing",
    });
  });

  it("renders unknown status values raw instead of crashing (R18)", () => {
    expect(memoryProviderCapabilityState({ status: "warming_up" })).toEqual({
      state: "disabled",
      label: "warming_up",
    });
  });
});

describe("mcpProbeOutcome", () => {
  it("renders successful probes as reachable with the tool count", () => {
    expect(mcpProbeOutcome({ ok: true, tools: [{}, {}, {}] })).toEqual({
      tone: "success",
      label: "reachable · 3 tools",
    });
  });

  it("singularizes a one-tool probe and tolerates missing tools", () => {
    expect(mcpProbeOutcome({ ok: true, tools: [{}] }).label).toBe(
      "reachable · 1 tool",
    );
    expect(mcpProbeOutcome({ ok: true }).label).toBe("reachable · 0 tools");
    expect(mcpProbeOutcome({ ok: true, tools: null }).label).toBe(
      "reachable · 0 tools",
    );
  });

  it("renders failed probes as a destructive unreachable chip", () => {
    expect(mcpProbeOutcome({ ok: false, tools: [] })).toEqual({
      tone: "destructive",
      label: "unreachable",
    });
  });
});

describe("scanVerdictOutcome", () => {
  it("maps the safe/caution/dangerous verdicts", () => {
    expect(scanVerdictOutcome("safe")).toEqual({
      tone: "success",
      label: "safe",
    });
    expect(scanVerdictOutcome("caution")).toEqual({
      tone: "warning",
      label: "caution",
    });
    expect(scanVerdictOutcome("dangerous")).toEqual({
      tone: "destructive",
      label: "dangerous",
    });
  });

  it("renders unknown verdicts raw on the outline tone (R18)", () => {
    expect(scanVerdictOutcome("sus")).toEqual({ tone: "outline", label: "sus" });
  });
});
