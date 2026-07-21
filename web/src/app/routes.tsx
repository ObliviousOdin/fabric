/* eslint-disable react-refresh/only-export-components -- This module is an
   intentional data catalog of lazy component identities, not a refresh root. */
import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import {
  Activity,
  BarChart3,
  Clock,
  Cpu,
  Database,
  FolderOpen,
  HelpCircle,
  Home,
  MessageSquare,
  Palette,
  Plug,
  Radio,
  Rocket,
  Settings,
  Shield,
  ShieldCheck,
  Users,
  Workflow,
  Wrench,
} from "lucide-react";

import type { PluginManifest } from "@/plugins/types";

export type AppSurface = "workspace" | "admin";
export type RouteLayout = "page" | "workspace";

export interface RouteNavMeta {
  /** Legacy path segments accepted by plugin `after:` / `before:` anchors. */
  anchorAliases?: readonly string[];
  icon: ComponentType<{ className?: string }>;
  label: string;
  labelKey?: string;
}

export interface AppRouteDef {
  aliases?: readonly string[];
  component?: LazyExoticComponent<ComponentType>;
  id: string;
  layout: RouteLayout;
  nav?: RouteNavMeta;
  path: string;
  /** Persistent routes are hosted outside `<Routes>` to preserve live state. */
  persistent?: boolean;
  surface: AppSurface;
  /** Optional localized title for utility routes that are not primary nav. */
  title?: string;
  titleKey?: string;
}

const WorkspaceHomePage = lazy(() => import("@/pages/WorkspaceHomePage"));
const DesignPage = lazy(() => import("@/pages/DesignPage"));
const WorkspacePlaceholderPage = lazy(
  () => import("@/pages/WorkspacePlaceholderPage"),
);
const SessionsPage = lazy(() => import("@/pages/SessionsPage"));
const FilesPage = lazy(() => import("@/pages/FilesPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const ModelsPage = lazy(() => import("@/pages/ModelsPage"));
const LogsPage = lazy(() => import("@/pages/LogsPage"));
const CronPage = lazy(() => import("@/pages/CronPage"));
const ProfilesPage = lazy(() => import("@/pages/ProfilesPage"));
const ProfileBuilderPage = lazy(() => import("@/pages/ProfileBuilderPage"));
const SkillsPage = lazy(() => import("@/pages/SkillsPage"));
const PluginsPage = lazy(() => import("@/pages/PluginsPage"));
const McpPage = lazy(() => import("@/pages/McpPage"));
const PairingPage = lazy(() => import("@/pages/PairingPage"));
const ChannelsPage = lazy(() => import("@/pages/ChannelsPage"));
const WebhooksPage = lazy(() => import("@/pages/WebhooksPage"));
const SystemPage = lazy(() => import("@/pages/SystemPage"));
const DeployPage = lazy(() => import("@/pages/DeployPage"));
const ConfigPage = lazy(() => import("@/pages/ConfigPage"));
const EnvPage = lazy(() => import("@/pages/EnvPage"));
const DocsPage = lazy(() => import("@/pages/DocsPage"));

/**
 * One catalog owns route identity, lazy page loading, IA surface, titles and
 * sidebar order. Legacy URLs remain aliases so bookmarks, plugin overrides and
 * deep links continue to work while the canonical Workspace/Admin IA settles.
 */
export const APP_ROUTES: readonly AppRouteDef[] = [
  // Fabric Workspace — user-facing work, in the requested primary order.
  {
    id: "home",
    path: "/workspace/home",
    surface: "workspace",
    layout: "page",
    component: WorkspaceHomePage,
    nav: { label: "Home", labelKey: "home", icon: Home },
  },
  {
    id: "chat",
    path: "/workspace/chat",
    aliases: ["/chat"],
    surface: "workspace",
    layout: "page",
    persistent: true,
    nav: { label: "Chat", labelKey: "chat", icon: MessageSquare },
  },
  {
    id: "design",
    path: "/workspace/design",
    aliases: ["/design"],
    surface: "workspace",
    layout: "page",
    component: DesignPage,
    nav: { label: "Design", labelKey: "design", icon: Palette },
  },
  {
    id: "work-board",
    path: "/workspace/work",
    aliases: ["/kanban", "/work"],
    surface: "workspace",
    layout: "page",
    component: WorkspacePlaceholderPage,
    nav: {
      label: "Work Board",
      labelKey: "workBoard",
      icon: Workflow,
      anchorAliases: ["kanban"],
    },
  },
  {
    id: "conversations",
    path: "/workspace/conversations",
    aliases: ["/sessions"],
    surface: "workspace",
    layout: "page",
    component: SessionsPage,
    nav: {
      label: "Conversations",
      labelKey: "conversations",
      icon: MessageSquare,
      anchorAliases: ["sessions"],
    },
  },
  {
    id: "agents",
    path: "/workspace/agents",
    aliases: ["/profiles", "/team"],
    surface: "workspace",
    layout: "page",
    component: ProfilesPage,
    nav: {
      label: "Agents",
      labelKey: "agents",
      icon: Users,
      anchorAliases: ["profiles", "team"],
    },
  },
  {
    id: "agent-new",
    path: "/workspace/agents/new",
    aliases: ["/profiles/new"],
    surface: "workspace",
    layout: "page",
    component: ProfileBuilderPage,
  },
  {
    id: "memory",
    path: "/workspace/memory",
    surface: "workspace",
    layout: "page",
    component: WorkspacePlaceholderPage,
    nav: { label: "Memory", labelKey: "memory", icon: Database },
  },
  {
    id: "knowledge",
    path: "/workspace/knowledge",
    aliases: ["/files"],
    surface: "workspace",
    layout: "page",
    component: FilesPage,
    nav: {
      label: "Knowledge",
      labelKey: "knowledge",
      icon: FolderOpen,
      anchorAliases: ["files"],
    },
  },
  {
    id: "automations",
    path: "/workspace/automations",
    aliases: ["/cron"],
    surface: "workspace",
    layout: "page",
    component: CronPage,
    nav: {
      label: "Automations",
      labelKey: "automations",
      icon: Clock,
      anchorAliases: ["cron"],
    },
  },
  {
    id: "approvals",
    path: "/workspace/approvals",
    surface: "workspace",
    layout: "page",
    component: WorkspacePlaceholderPage,
    nav: {
      label: "Approvals",
      labelKey: "approvals",
      icon: ShieldCheck,
    },
  },
  {
    id: "activity",
    path: "/workspace/activity",
    surface: "workspace",
    layout: "page",
    component: WorkspacePlaceholderPage,
    nav: { label: "Activity", labelKey: "activity", icon: Activity },
  },
  {
    id: "insights",
    path: "/workspace/insights",
    aliases: ["/analytics"],
    surface: "workspace",
    layout: "page",
    component: AnalyticsPage,
    nav: {
      label: "Insights",
      labelKey: "insights",
      icon: BarChart3,
      anchorAliases: ["analytics"],
    },
  },

  // Fabric Admin — technical, operational and security configuration.
  {
    id: "integrations",
    path: "/admin/integrations",
    aliases: ["/plugins", "/admin/integrations/plugins"],
    surface: "admin",
    layout: "page",
    component: PluginsPage,
    nav: {
      label: "Integrations",
      labelKey: "integrations",
      icon: Plug,
      anchorAliases: ["plugins", "skills", "mcp"],
    },
  },
  {
    id: "integration-skills",
    path: "/admin/integrations/skills",
    aliases: ["/skills"],
    surface: "admin",
    layout: "page",
    component: SkillsPage,
    title: "Skills",
    titleKey: "skills",
  },
  {
    id: "integration-mcp",
    path: "/admin/integrations/mcp",
    aliases: ["/mcp"],
    surface: "admin",
    layout: "page",
    component: McpPage,
  },
  {
    id: "channels-events",
    path: "/admin/channels-events",
    aliases: ["/channels", "/admin/channels-events/channels"],
    surface: "admin",
    layout: "page",
    component: ChannelsPage,
    nav: {
      label: "Channels and Events",
      labelKey: "channelsEvents",
      icon: Radio,
      anchorAliases: ["channels", "webhooks"],
    },
  },
  {
    id: "channel-webhooks",
    path: "/admin/channels-events/webhooks",
    aliases: ["/webhooks"],
    surface: "admin",
    layout: "page",
    component: WebhooksPage,
  },
  {
    id: "ai-runtime",
    path: "/admin/ai-runtime/models",
    aliases: ["/models"],
    surface: "admin",
    layout: "page",
    component: ModelsPage,
    nav: {
      label: "AI Runtime",
      labelKey: "aiRuntime",
      icon: Cpu,
      anchorAliases: ["models"],
    },
  },
  {
    id: "security-access",
    path: "/admin/security-access",
    aliases: ["/pairing", "/admin/security-access/pairing"],
    surface: "admin",
    layout: "page",
    component: PairingPage,
    nav: {
      label: "Security and Access",
      labelKey: "securityAccess",
      icon: Shield,
      anchorAliases: ["pairing", "env"],
    },
  },
  {
    id: "security-secrets",
    path: "/admin/security-access/secrets",
    aliases: ["/env"],
    surface: "admin",
    layout: "page",
    component: EnvPage,
    title: "Keys",
    titleKey: "keys",
  },
  {
    id: "system",
    path: "/admin/system",
    aliases: ["/system"],
    surface: "admin",
    layout: "page",
    component: SystemPage,
    nav: {
      label: "System",
      labelKey: "system",
      icon: Wrench,
      anchorAliases: ["system"],
    },
  },
  {
    id: "deploy",
    path: "/admin/deploy",
    surface: "admin",
    layout: "page",
    component: DeployPage,
    nav: { label: "Deploy", labelKey: "deploy", icon: Rocket },
  },
  {
    id: "advanced",
    path: "/admin/advanced",
    aliases: ["/config", "/admin/advanced/config"],
    surface: "admin",
    layout: "page",
    component: ConfigPage,
    nav: {
      label: "Advanced",
      labelKey: "advanced",
      icon: Settings,
      anchorAliases: ["config", "logs"],
    },
  },
  {
    id: "advanced-logs",
    path: "/admin/advanced/logs",
    aliases: ["/logs"],
    surface: "admin",
    layout: "page",
    component: LogsPage,
    title: "Logs",
    titleKey: "logs",
  },
  {
    id: "help",
    path: "/admin/help",
    aliases: ["/docs"],
    surface: "admin",
    layout: "page",
    component: DocsPage,
    nav: { label: "Help", labelKey: "help", icon: HelpCircle },
  },
] as const;

export const DEFAULT_ROUTE = "/workspace/home";

function normalizePath(pathname: string): string {
  return pathname.replace(/\/+$/, "") || "/";
}

export function routeForPath(pathname: string): AppRouteDef | undefined {
  const normalized = normalizePath(pathname);
  return APP_ROUTES.find(
    (route) =>
      route.path === normalized ||
      route.aliases?.some((alias) => normalizePath(alias) === normalized),
  );
}

export function canonicalPathForPath(pathname: string): string | undefined {
  return routeForPath(pathname)?.path;
}

/** Canonical ownership target for a plugin path/override. */
export function canonicalPluginTargetPath(pathname: string): string {
  const normalized = normalizePath(pathname);
  // `/` was the replaceable home page before the enterprise IA. It now owns
  // canonical Workspace Home rather than becoming a disconnected literal URL.
  if (normalized === "/") return DEFAULT_ROUTE;
  return canonicalPathForPath(normalized) ?? normalized;
}

export interface PluginRouteMetadata {
  label: string;
  layout?: RouteLayout;
  path: string;
}

/** Metadata paths share the same ownership identity as rendered overrides. */
export function pluginRouteMetadata(
  manifests: readonly PluginManifest[],
): PluginRouteMetadata[] {
  return manifests.flatMap((manifest) => {
    const requestedPath = manifest.tab.override ?? manifest.tab.path;
    const canonicalPath = canonicalPluginTargetPath(requestedPath);
    const metadata = {
      label: manifest.label,
      layout: manifest.tab.layout,
    };
    return manifest.tab.override && normalizePath(manifest.tab.override) === "/"
      ? [
          { ...metadata, path: "/" },
          { ...metadata, path: canonicalPath },
        ]
      : [{ ...metadata, path: canonicalPath }];
  });
}

export function canonicalLocationForPath(
  pathname: string,
  search = "",
  hash = "",
): string | undefined {
  const path = canonicalPathForPath(pathname);
  return path ? `${path}${search}${hash}` : undefined;
}

export function isChatPath(pathname: string): boolean {
  return routeForPath(pathname)?.id === "chat";
}

export function routeLayoutForPath(pathname: string): RouteLayout | undefined {
  return routeForPath(pathname)?.layout;
}

export function routeSurfaceForPath(pathname: string): AppSurface {
  const route = routeForPath(pathname);
  if (route) return route.surface;
  return normalizePath(pathname).startsWith("/admin") ? "admin" : "workspace";
}

export function routeMatchesOverride(
  route: AppRouteDef,
  overridePath: string | undefined,
): boolean {
  if (!overridePath) return false;
  const normalized = normalizePath(overridePath);
  // Before the Workspace/Admin IA, `/` was the replaceable home route. Keep
  // that extension contract attached to canonical Home as well as the literal
  // root route so a custom home remains custom after redirects/nav clicks.
  if (route.id === "home" && normalized === "/") return true;
  return (
    route.path === normalized ||
    route.aliases?.some((alias) => normalizePath(alias) === normalized) === true
  );
}

export function overrideForRoute(
  route: AppRouteDef,
  manifests: readonly PluginManifest[],
): PluginManifest | undefined {
  return manifests.find((manifest) =>
    routeMatchesOverride(route, manifest.tab.override),
  );
}

/**
 * Resolve a plugin override for any concrete path, including shell-owned
 * paths such as `/` that intentionally are not represented in APP_ROUTES.
 * Catalog routes still accept their canonical path and every legacy alias.
 */
export function overrideForPath(
  pathname: string,
  manifests: readonly PluginManifest[],
): PluginManifest | undefined {
  const route = routeForPath(pathname);
  if (route) return overrideForRoute(route, manifests);

  const normalized = normalizePath(pathname);
  return manifests.find(
    (manifest) =>
      manifest.tab.override !== undefined &&
      normalizePath(manifest.tab.override) === normalized,
  );
}

export function isBuiltinPath(pathname: string): boolean {
  return routeForPath(pathname) !== undefined;
}
