// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { PluginAliasRedirect } from "./PluginAliasRedirect";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function LocationProbe() {
  const location = useLocation();
  return <output>{`${location.pathname}${location.search}${location.hash}`}</output>;
}

describe("PluginAliasRedirect", () => {
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

  it("preserves board, view, task, and hash state on a legacy route", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter
          initialEntries={["/kanban?board=alpha&view=graph&task=t-1#node"]}
        >
          <Routes>
            <Route path="/kanban" element={<PluginAliasRedirect to="/work" />} />
            <Route path="/work" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    expect(container.querySelector("output")?.textContent).toBe(
      "/work?board=alpha&view=graph&task=t-1#node",
    );
  });
});
