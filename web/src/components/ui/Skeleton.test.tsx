// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Skeleton } from "@/components/ui/Skeleton";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("Skeleton", () => {
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

  it("renders a single pulsing token-colored bar by default", async () => {
    await act(async () => {
      root.render(<Skeleton />);
    });

    const bar = container.firstElementChild as HTMLElement;
    expect(bar.className).toContain("animate-pulse");
    expect(bar.className).toContain("bg-muted");
    expect(bar.getAttribute("aria-hidden")).toBe("true");
  });

  it("renders n bars for the row-list variant", async () => {
    await act(async () => {
      root.render(<Skeleton variant="row-list" rows={5} />);
    });

    const list = container.firstElementChild as HTMLElement;
    expect(list.children).toHaveLength(5);
    for (const bar of Array.from(list.children)) {
      expect((bar as HTMLElement).className).toContain("animate-pulse");
    }
  });

  it("merges className overrides onto the block variant", async () => {
    await act(async () => {
      root.render(<Skeleton variant="block" className="h-40" />);
    });

    const bar = container.firstElementChild as HTMLElement;
    // twMerge drops the default h-24 in favor of the override.
    expect(bar.className).toContain("h-40");
    expect(bar.className).not.toContain("h-24");
  });
});
