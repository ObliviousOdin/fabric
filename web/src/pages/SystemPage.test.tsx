// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { EgressStatusCard } from "@/components/EgressStatusCard";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("EgressStatusCard", () => {
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

  it("renders enforced local-AI scope and the approved private-network count", async () => {
    await act(async () => {
      root.render(
        <EgressStatusCard
          egress={{
            allowed_private_cidr_count: 2,
            available: true,
            mode: "local_ai",
            reason: null,
            scope: "ai_inference_routes",
            status: "available",
          }}
        />,
      );
    });

    expect(container.textContent).toContain("Network & AI egress");
    expect(container.textContent).toContain("local_ai");
    expect(container.textContent).toContain("ai inference routes");
    expect(container.textContent).toContain("2 explicitly approved");
  });

  it("renders unavailable air-gap reason without claiming a private allowlist", async () => {
    await act(async () => {
      root.render(
        <EgressStatusCard
          egress={{
            allowed_private_cidr_count: 0,
            available: false,
            mode: "air_gapped",
            reason: "whole_process_network_boundary_missing",
            scope: "whole_process",
            status: "unavailable",
          }}
        />,
      );
    });

    expect(container.textContent).toContain("unavailable");
    expect(container.textContent).toContain("whole process network boundary missing");
    expect(container.textContent).not.toContain("explicitly approved");
  });
});
