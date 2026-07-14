// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ChatContextTabs } from "./ChatContextPanel";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("ChatContextTabs", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(<ChatContextTabs />));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("exposes Task, Evidence, Memory, and Artifacts as an accessible tab set", () => {
    const tablist = container.querySelector(
      '[role="tablist"][aria-label="Context type"]',
    );
    expect(tablist).not.toBeNull();

    const tabs = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    );
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Task",
      "Evidence",
      "Memory",
      "Artifacts",
    ]);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");

    const panel = container.querySelector('[role="tabpanel"]');
    expect(panel?.textContent).toContain("Task context is unavailable");
    expect(panel?.textContent).toContain("does not expose linked task data");
    expect(panel?.textContent).toContain("Unavailable in this view");
  });

  it("supports arrow, Home, and End keyboard navigation", async () => {
    const selected = () =>
      container.querySelector<HTMLButtonElement>(
        '[role="tab"][aria-selected="true"]',
      );

    selected()?.focus();
    await act(async () => {
      selected()?.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "ArrowRight",
        }),
      );
    });
    expect(selected()?.textContent).toBe("Evidence");
    expect(document.activeElement).toBe(selected());
    expect(container.querySelector('[role="tabpanel"]')?.textContent).toContain(
      "Evidence is unavailable",
    );

    await act(async () => {
      selected()?.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "End",
        }),
      );
    });
    expect(selected()?.textContent).toBe("Artifacts");

    await act(async () => {
      selected()?.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "Home",
        }),
      );
    });
    expect(selected()?.textContent).toBe("Task");
  });
});
