import type { GatewayCapabilities } from "@fabric/shared";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import validFixture from "../../../mobile/contracts/gateway-capabilities-v1.json";
import { ExecutionNotice } from "./execution-notice";

describe("ExecutionNotice", () => {
  it("renders the canonical execution truth for a verified gateway", () => {
    const html = renderToStaticMarkup(
      <ExecutionNotice
        onRetry={vi.fn()}
        state={{
          kind: "verified",
          capabilities: validFixture as GatewayCapabilities,
        }}
      />,
    );

    expect(html).toContain("Runs on this gateway");
    expect(html).toContain("survives a phone disconnect");
    expect(html).toContain("gateway restart interrupts non-durable work");
    expect(html).toContain("v0.21.0");
  });

  it.each([
    [{ kind: "negotiating" } as const, "Checking gateway compatibility"],
    [{ kind: "legacy" } as const, "Gateway compatibility unverified"],
    [
      { kind: "incompatible", minimum: 2 } as const,
      "Fabric mobile update required",
    ],
    [
      { kind: "invalid", message: "Bad payload." } as const,
      "Gateway contract invalid",
    ],
  ])("renders the %s state with explicit status copy", (state, expected) => {
    const html = renderToStaticMarkup(
      <ExecutionNotice onRetry={vi.fn()} state={state} />,
    );
    expect(html).toContain(expected);
  });
});
