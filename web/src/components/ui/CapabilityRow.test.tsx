// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { CapabilityRow } from "@/components/ui/CapabilityRow";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("CapabilityRow", () => {
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

  it("renders the identity mono by default, sans on mono={false}", async () => {
    await act(async () => {
      root.render(<CapabilityRow name="hub-search" />);
    });
    let title = container.querySelector("[title='hub-search']") as HTMLElement;
    expect(title).not.toBeNull();
    expect(title.className).toContain("font-mono-ui");

    await act(async () => {
      root.render(<CapabilityRow name="Web Search" mono={false} />);
    });
    title = container.querySelector("[title='Web Search']") as HTMLElement;
    expect(title.className).not.toContain("font-mono-ui");
  });

  it("renders the switch only when provided, labelled with the row name", async () => {
    await act(async () => {
      root.render(<CapabilityRow name="hub-search" />);
    });
    expect(container.querySelector("[role=switch]")).toBeNull();

    await act(async () => {
      root.render(
        <CapabilityRow
          name="hub-search"
          switch={{ checked: true, onChange: () => {} }}
        />,
      );
    });
    const sw = container.querySelector("[role=switch]") as HTMLElement;
    expect(sw).not.toBeNull();
    expect(sw.getAttribute("aria-checked")).toBe("true");
    expect(sw.getAttribute("aria-label")).toBe("hub-search");
  });

  it("disables the switch while busy", async () => {
    await act(async () => {
      root.render(
        <CapabilityRow
          name="hub-search"
          switch={{ checked: false, onChange: () => {}, busy: true }}
        />,
      );
    });
    const sw = container.querySelector("[role=switch]") as HTMLButtonElement;
    expect(sw.disabled).toBe(true);
  });

  it("makes the expand gesture keyboard-operable when onToggle is provided", async () => {
    let toggles = 0;
    await act(async () => {
      root.render(
        <CapabilityRow
          name="github"
          onToggle={() => toggles++}
          expanded={false}
        />,
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
    await act(async () => {
      row.dispatchEvent(
        new KeyboardEvent("keydown", { key: " ", bubbles: true }),
      );
    });
    expect(toggles).toBe(2);

    // Without onToggle the row is inert — no phantom button semantics.
    await act(async () => {
      root.render(<CapabilityRow name="github" />);
    });
    expect(container.querySelector("[role=button]")).toBeNull();
  });

  it("toggling the switch never toggles expansion", async () => {
    let toggles = 0;
    let changes = 0;
    await act(async () => {
      root.render(
        <CapabilityRow
          name="hub-search"
          switch={{ checked: false, onChange: () => changes++ }}
          onToggle={() => toggles++}
          expanded={false}
        />,
      );
    });
    const sw = container.querySelector("[role=switch]") as HTMLElement;
    await act(async () => {
      sw.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(changes).toBe(1);
    expect(toggles).toBe(0);

    // Keyboard activation on the switch must not reach the row either
    // (the currentTarget guard).
    await act(async () => {
      sw.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    expect(toggles).toBe(0);
  });

  it("shows the expansion body only when expanded", async () => {
    await act(async () => {
      root.render(
        <CapabilityRow name="github" onToggle={() => {}} expanded={false}>
          <div data-testid="body">test results</div>
        </CapabilityRow>,
      );
    });
    expect(container.querySelector("[data-testid=body]")).toBeNull();

    await act(async () => {
      root.render(
        <CapabilityRow name="github" onToggle={() => {}} expanded>
          <div data-testid="body">test results</div>
        </CapabilityRow>,
      );
    });
    expect(container.querySelector("[data-testid=body]")).not.toBeNull();
  });

  it("dims the body but never the actions", async () => {
    await act(async () => {
      root.render(
        <CapabilityRow
          name="hub-search"
          dimmed
          description="Search installed hubs"
          actions={<button data-testid="action">Configure</button>}
        />,
      );
    });
    const title = container.querySelector(
      "[title='hub-search']",
    ) as HTMLElement;
    const body = title.closest(".opacity-60") as HTMLElement;
    expect(body).not.toBeNull();
    const action = container.querySelector(
      "[data-testid=action]",
    ) as HTMLElement;
    expect(action.closest(".opacity-60")).toBeNull();
  });
});
