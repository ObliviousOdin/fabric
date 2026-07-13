// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { BarChart3 } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("EmptyState", () => {
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

  it("renders icon, title, description, and action", async () => {
    await act(async () => {
      root.render(
        <EmptyState
          icon={BarChart3}
          title="No usage data"
          description="Start a session"
          action={<button type="button">Reload</button>}
        />,
      );
    });

    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.textContent).toContain("No usage data");
    expect(container.textContent).toContain("Start a session");
    expect(container.querySelector("button")?.textContent).toBe("Reload");
  });

  it("renders title-only without icon, description, or action", async () => {
    await act(async () => {
      root.render(<EmptyState title="Nothing here" />);
    });

    expect(container.textContent).toBe("Nothing here");
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });
});
