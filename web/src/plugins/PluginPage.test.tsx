// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PluginPage } from "./PluginPage";
import { exposePluginSDK } from "./registry";

vi.mock("@/i18n", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "Loading",
        pluginLoadFailed: "Load failed",
        pluginNotRegistered: "Not registered",
      },
    },
  }),
}));

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

interface RoutedPluginProps {
  navigate: (path: string, options?: { replace?: boolean }) => void;
  location: { pathname: string; search: string; hash: string };
}

function RoutedPlugin({ navigate, location }: RoutedPluginProps) {
  return (
    <div>
      <output>{`${location.pathname}${location.search}${location.hash}`}</output>
      <button
        onClick={() =>
          navigate("/work?board=default&view=outline#selected", {
            replace: false,
          })
        }
      >
        Change view
      </button>
    </div>
  );
}

describe("PluginPage", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    exposePluginSDK();
    window.__FABRIC_PLUGINS__?.register("routed-test", RoutedPlugin);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("keeps plugin route writes synchronized with React Router", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter
          basename="/fabric"
          initialEntries={["/fabric/work?board=default&view=graph"]}
        >
          <Routes>
            <Route path="*" element={<PluginPage name="routed-test" />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    expect(container.querySelector("output")?.textContent).toBe(
      "/work?board=default&view=graph",
    );

    await act(async () => container.querySelector("button")?.click());

    expect(container.querySelector("output")?.textContent).toBe(
      "/work?board=default&view=outline#selected",
    );
  });

  it("exposes the Film icon through the shared plugin SDK", () => {
    expect(window.__FABRIC_PLUGIN_SDK__?.icons?.Film).toBeDefined();
  });

  it("exposes the host React DOM helpers without requiring a bundled renderer", () => {
    expect(window.__FABRIC_PLUGIN_SDK__?.ReactDOM.createPortal).toBeTypeOf(
      "function",
    );
  });
});
