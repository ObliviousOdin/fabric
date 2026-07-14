// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Badge } from "./Badge";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("Fabric Badge", () => {
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

  it("uses the system type contract without inherited display effects", async () => {
    await act(async () => root.render(<Badge>bundled</Badge>));
    const badge = container.querySelector("span");

    expect(badge?.dataset.tone).toBe("default");
    expect(badge?.className).toContain("font-sans");
    expect(badge?.className).not.toContain("font-compressed");
    expect(badge?.className).not.toContain("text-display");
  });

  it("preserves semantic tones and native span props", async () => {
    await act(async () =>
      root.render(
        <Badge aria-label="Gateway ready" tone="success">
          ready
        </Badge>,
      ),
    );
    const badge = container.querySelector("span");

    expect(badge?.dataset.tone).toBe("success");
    expect(badge?.getAttribute("aria-label")).toBe("Gateway ready");
    expect(badge?.className).toContain("text-success");
  });
});
