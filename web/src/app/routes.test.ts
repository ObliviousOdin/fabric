import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { PluginManifest } from "@/plugins/types";
import {
  APP_ROUTES,
  canonicalPluginTargetPath,
  DEFAULT_ROUTE,
  canonicalLocationForPath,
  canonicalPathForPath,
  isChatPath,
  overrideForPath,
  overrideForRoute,
  pluginRouteMetadata,
  routeForPath,
  routeSurfaceForPath,
} from "./routes";

function manifest(override: string): PluginManifest {
  return {
    name: "chat-replacement",
    label: "Chat replacement",
    description: "Test plugin",
    icon: "Puzzle",
    version: "1.0.0",
    tab: { path: "/replacement", override },
    entry: "/replacement.js",
    has_api: false,
    source: "test",
  };
}

describe("application route catalog", () => {
  it("owns unique canonical and legacy paths", () => {
    const paths = APP_ROUTES.flatMap((route) => [
      route.path,
      ...(route.aliases ?? []),
    ]);

    expect(new Set(paths).size).toBe(paths.length);
    expect(DEFAULT_ROUTE).toBe("/workspace/home");
  });

  it("keeps Workspace navigation in the product-specified order", () => {
    expect(
      APP_ROUTES.filter(
        (route) => route.surface === "workspace" && route.nav,
      ).map((route) => route.nav?.label),
    ).toEqual([
      "Home",
      "Chat",
      "Design",
      "Work Board",
      "Conversations",
      "Agents",
      "Memory",
      "Knowledge",
      "Automations",
      "Approvals",
      "Activity",
      "Insights",
    ]);
  });

  it("keeps Admin navigation in the product-specified order", () => {
    expect(
      APP_ROUTES.filter(
        (route) => route.surface === "admin" && route.nav,
      ).map((route) => route.nav?.label),
    ).toEqual([
      "Integrations",
      "Channels and Events",
      "AI Runtime",
      "Security and Access",
      "System",
      "Deploy",
      "Advanced",
      "Help",
    ]);
  });

  it("maps shipped legacy URLs to canonical Workspace and Admin routes", () => {
    expect(canonicalPathForPath("/chat")).toBe("/workspace/chat");
    expect(canonicalPathForPath("/design")).toBe("/workspace/design");
    expect(canonicalPathForPath("/kanban")).toBe("/workspace/work");
    expect(canonicalPathForPath("/work")).toBe("/workspace/work");
    expect(canonicalPathForPath("/team")).toBe("/workspace/agents");
    expect(canonicalPathForPath("/sessions/")).toBe(
      "/workspace/conversations",
    );
    expect(canonicalPathForPath("/plugins")).toBe("/admin/integrations");
    expect(canonicalPathForPath("/env")).toBe(
      "/admin/security-access/secrets",
    );
  });

  it("preserves query and hash state when canonicalizing a legacy link", () => {
    expect(
      canonicalLocationForPath(
        "/chat",
        "?resume=session-1&profile=ops",
        "#activity",
      ),
    ).toBe(
      "/workspace/chat?resume=session-1&profile=ops#activity",
    );
    expect(
      canonicalLocationForPath(
        "/work",
        "?board=alpha&view=graph&task=t-1",
        "#node",
      ),
    ).toBe(
      "/workspace/work?board=alpha&view=graph&task=t-1#node",
    );
  });

  it("does not carry query or hash material from an unknown URL", () => {
    expect(
      canonicalLocationForPath(
        "/not-a-fabric-route",
        "?access_token=secret",
        "#private",
      ),
    ).toBeUndefined();
  });

  it("gives canonical and legacy Chat one persistent route identity", () => {
    expect(isChatPath("/workspace/chat")).toBe(true);
    expect(isChatPath("/chat/")).toBe(true);
    expect(routeForPath("/chat")).toBe(routeForPath("/workspace/chat"));
    expect(routeSurfaceForPath("/chat")).toBe("workspace");
    expect(routeSurfaceForPath("/admin/advanced")).toBe("admin");
  });

  it("maps the retired Team page to the truthful Agents surface", () => {
    expect(routeForPath("/team")).toBe(routeForPath("/workspace/agents"));
    expect(canonicalLocationForPath("/team", "?profile=ops", "#active")).toBe(
      "/workspace/agents?profile=ops#active",
    );
  });

  it("allows plugins to override a route through canonical or legacy identity", () => {
    const chat = routeForPath("/workspace/chat");
    expect(chat).toBeDefined();
    expect(overrideForRoute(chat!, [manifest("/chat")])?.name).toBe(
      "chat-replacement",
    );
    expect(
      overrideForRoute(chat!, [manifest("/workspace/chat")])?.name,
    ).toBe("chat-replacement");
  });

  it("preserves shell-path plugin overrides that are outside the route catalog", () => {
    const rootReplacement = manifest("/");

    expect(overrideForPath("/", [rootReplacement])).toBe(rootReplacement);
    expect(overrideForPath("/workspace/home", [rootReplacement])).toBe(
      rootReplacement,
    );
    expect(overrideForPath("/workspace/chat", [manifest("/chat")])?.name).toBe(
      "chat-replacement",
    );
  });

  it("canonicalizes the legacy root plugin target to Workspace Home", () => {
    expect(canonicalPluginTargetPath("/")).toBe(DEFAULT_ROUTE);
    expect(canonicalPluginTargetPath("/sessions/")).toBe(
      "/workspace/conversations",
    );
    expect(canonicalPluginTargetPath("/custom/")).toBe("/custom");
  });

  it("projects root override label and workspace layout onto both identities", () => {
    const rootReplacement = manifest("/");
    rootReplacement.label = "Custom home";
    rootReplacement.tab.layout = "workspace";

    expect(pluginRouteMetadata([rootReplacement])).toEqual([
      { label: "Custom home", layout: "workspace", path: "/" },
      {
        label: "Custom home",
        layout: "workspace",
        path: "/workspace/home",
      },
    ]);
  });

  it("does not statically import route pages or xterm from the initial shell", () => {
    const appSource = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
    const catalogSource = readFileSync(
      new URL("./routes.tsx", import.meta.url),
      "utf8",
    );

    expect(appSource).not.toMatch(/from\s+["']@\/pages\//);
    expect(catalogSource).not.toMatch(/from\s+["']@\/pages\//);
    expect(`${appSource}\n${catalogSource}`).not.toMatch(/@xterm\//);
    expect(appSource).toContain('lazy(() => import("@/pages/ChatPage"))');
  });
});
