import { describe, expect, it } from "vitest";
import { Film } from "lucide-react";

import { en } from "@/i18n/en";
import type { PluginManifest } from "@/plugins/types";
import { navItemLabel } from "./nav-label";
import { BUILTIN_NAV_ITEMS, buildSidebarSections } from "./nav-model";

function manifest(
  name: string,
  {
    layout = "page",
    position,
  }: {
    layout?: "page" | "workspace";
    position?: string;
  } = {},
): PluginManifest {
  return {
    name,
    label: name,
    description: "Test plugin",
    icon: "Puzzle",
    version: "1.0.0",
    tab: { path: `/${name}`, layout, position },
    entry: `/${name}.js`,
    has_api: false,
    source: "test",
  };
}

function pathsFor(
  manifests: PluginManifest[],
  surface: "workspace" | "admin" = "workspace",
): { sections: string[]; plugins: string[] } {
  const nav = buildSidebarSections(BUILTIN_NAV_ITEMS, manifests, surface);
  return {
    sections: nav.sections.flatMap((section) =>
      section.items.map((item) => item.path),
    ),
    plugins: nav.pluginItems.map((item) => item.path),
  };
}

describe("sidebar navigation model", () => {
  it("renders the new IA labels instead of legacy translated names", () => {
    const labels = BUILTIN_NAV_ITEMS.map((item) => navItemLabel(item, en));

    expect(labels).toContain("Conversations");
    expect(labels).toContain("Design");
    expect(labels).toContain("Agents");
    expect(labels).toContain("Automations");
    expect(labels).toContain("Insights");
    expect(labels).toContain("Integrations");
    expect(labels).toContain("AI Runtime");
    expect(labels).toContain("Advanced");
    expect(labels).toContain("Help");
    expect(labels).not.toContain("Sessions");
    expect(labels).not.toContain("Profiles");
  });

  it("honors legacy position anchors after canonicalizing built-in paths", () => {
    const paths = pathsFor([manifest("kanban", { position: "after:sessions" })]);
    const conversations = paths.sections.indexOf("/workspace/conversations");

    expect(conversations).toBeGreaterThanOrEqual(0);
    expect(paths.sections[conversations + 1]).toBe("/kanban");
  });

  it("keeps chained plugin anchors on the surface they follow", () => {
    const paths = pathsFor([
      manifest("kanban", { position: "after:sessions" }),
      manifest("team", { position: "after:kanban" }),
    ]);
    const kanban = paths.sections.indexOf("/kanban");

    expect(paths.sections[kanban + 1]).toBe("/team");
    expect(paths.plugins).not.toContain("/team");
  });

  it("anchors after Work Board through the shipped kanban compatibility key", () => {
    const paths = pathsFor([manifest("team", { position: "after:kanban" })]);
    const workBoard = paths.sections.indexOf("/workspace/work");

    expect(paths.sections[workBoard + 1]).toBe("/team");
  });

  it.each([
    ["skills", "/admin/integrations"],
    ["mcp", "/admin/integrations"],
    ["webhooks", "/admin/channels-events"],
    ["env", "/admin/security-access"],
    ["logs", "/admin/advanced"],
  ])("preserves the former %s top-level plugin anchor", (anchor, parent) => {
    const paths = pathsFor(
      [manifest(`after-${anchor}`, { position: `after:${anchor}` })],
      "admin",
    );
    const parentIndex = paths.sections.indexOf(parent);

    expect(parentIndex).toBeGreaterThanOrEqual(0);
    expect(paths.sections[parentIndex + 1]).toBe(`/after-${anchor}`);
  });

  it("keeps a plugin on its known surface when a gated anchor is absent", () => {
    const withoutInsights = BUILTIN_NAV_ITEMS.filter(
      (item) => item.path !== "/workspace/insights",
    );
    const nav = buildSidebarSections(
      withoutInsights,
      [manifest("achievements", { position: "after:analytics" })],
      "workspace",
    );

    expect(nav.pluginItems.map((item) => item.path)).toContain(
      "/achievements",
    );
  });

  it("places unanchored page plugins in Admin and workspace plugins in Workspace", () => {
    const plugins = [
      manifest("page-plugin"),
      manifest("workspace-plugin", { layout: "workspace" }),
    ];

    expect(pathsFor(plugins, "admin").plugins).toContain("/page-plugin");
    expect(pathsFor(plugins, "workspace").plugins).toContain(
      "/workspace-plugin",
    );
  });

  it("resolves the Film icon for media workspace plugins", () => {
    const studio = manifest("studio", { layout: "workspace" });
    studio.icon = "Film";

    const nav = buildSidebarSections(BUILTIN_NAV_ITEMS, [studio], "workspace");

    expect(nav.pluginItems).toHaveLength(1);
    expect(nav.pluginItems[0].icon).toBe(Film);
  });
});
