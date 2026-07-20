// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { IntegrationCapabilityDirectory } from "./IntegrationCapabilityDirectory";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("IntegrationCapabilityDirectory", () => {
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

  it("links the Integrations parent to its canonical Skills Hub and MCP routes", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <IntegrationCapabilityDirectory />
        </MemoryRouter>,
      );
    });

    expect(container.textContent).toContain("Capability library");
    expect(container.textContent).toContain("Skills Hub");

    const links = Array.from(container.querySelectorAll("a"));
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/admin/integrations/skills",
      "/admin/integrations/mcp",
    ]);
    expect(links[0].getAttribute("aria-label")).toBe(
      "Browse skills: Skills Hub",
    );
  });
});
