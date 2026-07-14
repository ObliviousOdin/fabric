// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import WorkspacePlaceholderPage from "./WorkspacePlaceholderPage";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("WorkspacePlaceholderPage route identity", () => {
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

  it("keeps the route-specific state for a trailing-slash URL", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/workspace/memory/"]}>
          <WorkspacePlaceholderPage />
        </MemoryRouter>,
      );
    });

    expect(container.textContent).toContain(
      "Typed Memory ledger is not exposed by this runtime",
    );
    expect(container.textContent).not.toContain(
      "This experience is not available yet",
    );
  });
});
