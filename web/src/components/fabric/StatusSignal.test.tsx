// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { StatusSignal } from "./StatusSignal";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("StatusSignal", () => {
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

  it("pairs a non-color state marker with readable status text", async () => {
    await act(async () => {
      root.render(
        <StatusSignal
          detail="updated now"
          label="Gateway live"
          pulse
          tone="live"
        />,
      );
    });

    expect(container.textContent).toContain("Gateway live");
    expect(container.textContent).toContain("updated now");
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });
});
