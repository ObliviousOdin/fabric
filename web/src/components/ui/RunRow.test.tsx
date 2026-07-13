// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { RunRow } from "@/components/ui/RunRow";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

const BASE = {
  title: "Fix the flaky test",
  id: "sess_0123456789abcdef",
  timestamp: Date.now() / 1000 - 60,
};

describe("RunRow", () => {
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

  it("tints live rows, but selection beats live", async () => {
    await act(async () => {
      root.render(<RunRow {...BASE} status="live" />);
    });
    let box = container.firstElementChild as HTMLElement;
    expect(box.className).toContain("border-success/30");

    await act(async () => {
      root.render(
        <RunRow {...BASE} status="live" selected onSelectClick={() => {}} />,
      );
    });
    box = container.firstElementChild as HTMLElement;
    expect(box.className).toContain("border-primary/40");
    expect(box.className).not.toContain("border-success/30");
  });

  it("renders the checkbox only when onSelectClick is provided", async () => {
    await act(async () => {
      root.render(<RunRow {...BASE} status="done" />);
    });
    expect(container.querySelector("[role=checkbox]")).toBeNull();

    await act(async () => {
      root.render(<RunRow {...BASE} status="done" onSelectClick={() => {}} />);
    });
    expect(container.querySelector("[role=checkbox]")).not.toBeNull();
  });

  it("makes the expand gesture keyboard-operable when onToggle is provided", async () => {
    let toggles = 0;
    await act(async () => {
      root.render(
        <RunRow {...BASE} status="done" onToggle={() => toggles++} expanded={false} />,
      );
    });
    const row = container.querySelector("[role=button]") as HTMLElement;
    expect(row).not.toBeNull();
    expect(row.getAttribute("tabindex")).toBe("0");
    expect(row.getAttribute("aria-expanded")).toBe("false");
    await act(async () => {
      row.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    expect(toggles).toBe(1);

    // Without onToggle the row is inert — no phantom button semantics.
    await act(async () => {
      root.render(<RunRow {...BASE} status="done" />);
    });
    expect(container.querySelector("[role=button]")).toBeNull();
  });

  it("truncates the id and shows the expansion body only when expanded", async () => {
    await act(async () => {
      root.render(
        <RunRow {...BASE} status="done" model="hermes-4-405b">
          <div data-testid="timeline">timeline body</div>
        </RunRow>,
      );
    });
    expect(container.textContent).toContain("sess_012");
    expect(container.textContent).not.toContain("sess_0123456789abcdef");
    expect(container.textContent).toContain("hermes-4-405b");
    expect(container.querySelector("[data-testid=timeline]")).toBeNull();

    await act(async () => {
      root.render(
        <RunRow {...BASE} status="done" expanded>
          <div data-testid="timeline">timeline body</div>
        </RunRow>,
      );
    });
    expect(container.querySelector("[data-testid=timeline]")).not.toBeNull();
  });
});
