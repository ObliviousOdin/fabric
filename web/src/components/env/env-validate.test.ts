import { describe, expect, it } from "vitest";
import { PROVIDER_PROBE_KEYS, providerProbeOutcome } from "./env-validate";

describe("PROVIDER_PROBE_KEYS", () => {
  it("mirrors the server probe map exactly (R28)", () => {
    // fabric_cli/web_server.py::_CREDENTIAL_PROBES + the OPENAI_BASE_URL branch.
    expect([...PROVIDER_PROBE_KEYS].sort()).toEqual([
      "GEMINI_API_KEY",
      "OPENAI_API_KEY",
      "OPENAI_BASE_URL",
      "OPENROUTER_API_KEY",
      "XAI_API_KEY",
    ]);
  });
});

describe("providerProbeOutcome", () => {
  it("maps an accepted credential to a success chip", () => {
    expect(
      providerProbeOutcome({ ok: true, reachable: true, message: "" }),
    ).toEqual({
      kind: "accepted",
      tone: "success",
      label: "key accepted",
      message: "",
    });
  });

  it("includes the catalog size for the base-URL branch", () => {
    expect(
      providerProbeOutcome({
        ok: true,
        reachable: true,
        message: "",
        models: ["m1", "m2"],
      }).label,
    ).toBe("accepted · 2 models");
    expect(
      providerProbeOutcome({
        ok: true,
        reachable: true,
        message: "",
        models: ["m1"],
      }).label,
    ).toBe("accepted · 1 model");
  });

  it("maps an unreachable probe to a warning, not a failure", () => {
    const outcome = providerProbeOutcome({
      ok: false,
      reachable: false,
      message: "Could not reach the provider to verify the key.",
    });
    expect(outcome.kind).toBe("unreachable");
    expect(outcome.tone).toBe("warning");
    expect(outcome.message).toMatch(/Could not reach/);
  });

  it("maps a rejected credential to a destructive chip with the server detail", () => {
    const outcome = providerProbeOutcome({
      ok: false,
      reachable: true,
      message: "That API key was rejected.",
    });
    expect(outcome.kind).toBe("rejected");
    expect(outcome.tone).toBe("destructive");
    expect(outcome.message).toBe("That API key was rejected.");
  });
});
