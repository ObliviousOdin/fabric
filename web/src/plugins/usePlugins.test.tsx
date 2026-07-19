// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PluginManifest } from "./types";

const { getPlugins } = vi.hoisted(() => ({ getPlugins: vi.fn() }));
vi.mock("@/lib/api", () => ({
  api: { getPlugins },
  DASHBOARD_BASE_PATH: "",
}));

import { shouldLoadPluginAssets, usePlugins } from "./usePlugins";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function manifest(
  name: string,
  options: {
    hidden?: boolean;
    path?: string;
    aliases?: string[];
    override?: string;
    slots?: string[];
  } = {},
): PluginManifest {
  return {
    name,
    label: name,
    description: name,
    icon: "Circle",
    version: "1.0.0",
    tab: {
      path: options.path ?? `/${name}`,
      hidden: options.hidden,
      aliases: options.aliases,
      override: options.override,
    },
    slots: options.slots,
    entry: "dist/index.js",
    css: "dist/style.css",
    has_api: false,
    source: "test",
  };
}

function Probe() {
  const { loading } = usePlugins();
  return <output>{loading ? "loading" : "ready"}</output>;
}

describe("usePlugins asset loading", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    getPlugins.mockReset();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document
      .querySelectorAll('[data-fabric-plugin], link[href^="/dashboard-plugins/"]')
      .forEach((element) => element.remove());
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("keeps a hidden page-only integration off the chat startup path", async () => {
    getPlugins.mockResolvedValue([
      manifest("work"),
      manifest("team-pages", {
        hidden: true,
        path: "/admin/integrations/team-pages",
      }),
    ]);

    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/chat"]}>
          <Probe />
        </MemoryRouter>,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toBe("ready");
    expect(document.querySelector('[data-fabric-plugin="work"]')).not.toBeNull();
    expect(
      document.querySelector('[data-fabric-plugin="team-pages"]'),
    ).toBeNull();
  });

  it("loads a hidden integration when its direct route is open", async () => {
    getPlugins.mockResolvedValue([
      manifest("team-pages", {
        hidden: true,
        path: "/admin/integrations/team-pages",
      }),
    ]);

    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/admin/integrations/team-pages"]}>
          <Probe />
        </MemoryRouter>,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toBe("ready");
    expect(
      document.querySelector('[data-fabric-plugin="team-pages"]'),
    ).not.toBeNull();
  });

  it("keeps hidden slot providers eager and recognizes aliases", () => {
    expect(
      shouldLoadPluginAssets(
        manifest("slot", { hidden: true, slots: ["chat:rail"] }),
        "/chat",
      ),
    ).toBe(true);
    expect(
      shouldLoadPluginAssets(
        manifest("legacy", {
          hidden: true,
          path: "/admin/legacy",
          aliases: ["/old-team/"],
        }),
        "/old-team",
      ),
    ).toBe(true);
    expect(
      shouldLoadPluginAssets(
        manifest("chat-override", {
          hidden: true,
          path: "/internal/chat-override",
          override: "/chat",
        }),
        "/workspace/chat",
      ),
    ).toBe(true);
  });
});
