import type { ComponentType } from "react";
import {
  Activity,
  BarChart3,
  Clock,
  Code,
  Cpu,
  Database,
  Eye,
  FileText,
  FolderOpen,
  Globe,
  Heart,
  KeyRound,
  MessageSquare,
  Package,
  Puzzle,
  Settings,
  Shield,
  Sparkles,
  Star,
  Terminal,
  Users,
  Wrench,
  Zap,
} from "lucide-react";

import { APP_ROUTES, type AppSurface } from "@/app/routes";
import type { PluginManifest } from "@/plugins";

export interface NavItem {
  /** Path-segment aliases retained for third-party plugin position anchors. */
  anchorAliases?: readonly string[];
  icon: ComponentType<{ className?: string }>;
  label: string;
  labelKey?: string;
  path: string;
  surface: AppSurface;
}

export type NavSectionId = AppSurface;

export interface NavSection {
  id: NavSectionId;
  items: NavItem[];
}

/** Built-in navigation is a projection of the route catalog, preserving order. */
export const BUILTIN_NAV_ITEMS: NavItem[] = APP_ROUTES.flatMap((route) =>
  route.nav
    ? [
        {
          anchorAliases: route.nav.anchorAliases,
          icon: route.nav.icon,
          label: route.nav.label,
          labelKey: route.nav.labelKey,
          path: route.path,
          surface: route.surface,
        },
      ]
    : [],
);

// Compatibility exports for callers/plugins that still think in the old
// flat-chat-plus-rest shape. Their paths are canonical, not legacy aliases.
export const CHAT_NAV_ITEM = BUILTIN_NAV_ITEMS.find(
  (item) => item.path === "/workspace/chat",
)!;
export const BUILTIN_NAV_REST = BUILTIN_NAV_ITEMS.filter(
  (item) => item !== CHAT_NAV_ITEM,
);

const ICON_MAP: Record<string, ComponentType<{ className?: string }>> = {
  Activity,
  BarChart3,
  Clock,
  Cpu,
  FileText,
  FolderOpen,
  KeyRound,
  MessageSquare,
  Package,
  Settings,
  Puzzle,
  Sparkles,
  Terminal,
  Globe,
  Database,
  Shield,
  Users,
  Wrench,
  Zap,
  Heart,
  Star,
  Code,
  Eye,
};

function resolveIcon(
  name: string,
): ComponentType<{ className?: string }> {
  return ICON_MAP[name] ?? Puzzle;
}

function pathSegment(path: string): string {
  const clean = path.replace(/\/+$/, "");
  return clean.slice(clean.lastIndexOf("/") + 1);
}

function anchorKeys(item: NavItem): Set<string> {
  return new Set([pathSegment(item.path), ...(item.anchorAliases ?? [])]);
}

function knownAnchorSurface(target: string): AppSurface | undefined {
  for (const route of APP_ROUTES) {
    if (!route.nav) continue;
    const keys = new Set([
      pathSegment(route.path),
      ...(route.nav.anchorAliases ?? []),
    ]);
    if (keys.has(target)) return route.surface;
  }
  return undefined;
}

/**
 * Merge plugin navigation into the catalog projection while honoring the
 * established `tab.position` contract. Anchors match canonical segments and
 * legacy aliases (`after:sessions` still follows Conversations), and anchored
 * plugins inherit the target surface. Unanchored page plugins live under
 * Admin; full-workspace plugins live under Workspace.
 */
export function buildSidebarSections(
  builtIn: NavItem[],
  manifests: PluginManifest[],
  activeSurface: AppSurface = "workspace",
): { sections: NavSection[]; pluginItems: NavItem[] } {
  type Tag = NavSectionId | "plugins";
  const tagged: Array<{ item: NavItem; tag: Tag }> = builtIn.map((item) => ({
    item,
    tag: item.surface,
  }));

  for (const manifest of manifests) {
    if (manifest.tab.override || manifest.tab.hidden) continue;

    const baseSurface: AppSurface =
      manifest.tab.layout === "workspace" ? "workspace" : "admin";
    const pluginItem: NavItem = {
      anchorAliases: [manifest.name],
      path: manifest.tab.path,
      label: manifest.label,
      icon: resolveIcon(manifest.icon),
      surface: baseSurface,
    };

    const pos = manifest.tab.position ?? "end";
    let placed = false;
    if (pos.startsWith("after:") || pos.startsWith("before:")) {
      const after = pos.startsWith("after:");
      const target = pos.slice(after ? 6 : 7);
      // Prefer the most recently inserted match. Compatibility aliases can
      // intentionally duplicate a plugin's own name (Work Board accepts the
      // old `kanban` anchor); when that plugin is present, chained anchors
      // should follow the concrete plugin rather than the fallback alias.
      let idx = -1;
      for (let i = tagged.length - 1; i >= 0; i -= 1) {
        if (anchorKeys(tagged[i].item).has(target)) {
          idx = i;
          break;
        }
      }
      if (idx >= 0) {
        const inheritedSurface = tagged[idx].item.surface;
        tagged.splice(after ? idx + 1 : idx, 0, {
          item: { ...pluginItem, surface: inheritedSurface },
          tag: tagged[idx].tag,
        });
        placed = true;
      } else {
        // If a feature gate hid the anchor, keep the plugin discoverable on
        // that anchor's surface, matching the former dynamic-plugin fallback.
        pluginItem.surface = knownAnchorSurface(target) ?? baseSurface;
      }
    }
    if (!placed) tagged.push({ item: pluginItem, tag: "plugins" });
  }

  const surfaceItems = tagged
    .filter((entry) => entry.tag === activeSurface)
    .map((entry) => entry.item);
  const sections: NavSection[] = surfaceItems.length
    ? [{ id: activeSurface, items: surfaceItems }]
    : [];
  const pluginItems = tagged
    .filter(
      (entry) =>
        entry.tag === "plugins" && entry.item.surface === activeSurface,
    )
    .map((entry) => entry.item);

  return { sections, pluginItems };
}
