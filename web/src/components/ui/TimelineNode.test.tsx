// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TimelineNode } from "@/components/ui/TimelineNode";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("TimelineNode", () => {
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

  it("tones the rail dot and label by kind", async () => {
    await act(async () => {
      root.render(
        <TimelineNode kind="assistant" label="Assistant">
          <p>hello</p>
        </TimelineNode>,
      );
    });
    expect(container.querySelector(".bg-success")).not.toBeNull();
    const label = container.querySelector(".text-success");
    expect(label?.textContent).toBe("Assistant");
    expect(container.textContent).toContain("hello");
  });

  it("marks FTS hits with the anchor attribute, ring and match badge", async () => {
    await act(async () => {
      root.render(
        <TimelineNode kind="user" label="User" hit>
          <p>needle</p>
        </TimelineNode>,
      );
    });
    const node = container.querySelector("[data-search-hit]") as HTMLElement;
    expect(node).not.toBeNull();
    expect(node.className).toContain("ring-warning/40");
    expect(container.textContent).toContain("match");
  });

  it("renders no hit affordances or timestamp by default", async () => {
    await act(async () => {
      root.render(
        <TimelineNode kind="handoff" label="Context handoff">
          <p>summary</p>
        </TimelineNode>,
      );
    });
    expect(container.querySelector("[data-search-hit]")).toBeNull();
    expect(container.querySelector("time")).toBeNull();
    // Handoff renders in the muted tone.
    expect(container.querySelector(".text-muted-foreground")).not.toBeNull();
  });
});
