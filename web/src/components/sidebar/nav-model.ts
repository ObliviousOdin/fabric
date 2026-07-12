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
  Plug,
  Puzzle,
  Radio,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Star,
  Terminal,
  Users,
  Webhook,
  Wrench,
  Zap,
} from "lucide-react";
import type { PluginManifest } from "@/plugins";

export interface NavItem {
  icon: ComponentType<{ className?: string }>;
  label: string;
  labelKey?: string;
  path: string;
}

export type NavSectionId =
  | "work"
  | "observe"
  | "capabilities"
  | "connect"
  | "system";

export interface NavSection {
  id: NavSectionId;
  items: NavItem[];
}

export const CHAT_NAV_ITEM: NavItem = {
  path: "/chat",
  labelKey: "chat",
  label: "Chat",
  icon: Terminal,
};

/** Built-in nav entries (minus /chat), ordered so each IA section is contiguous. */
export const BUILTIN_NAV_REST: NavItem[] = [
  // WORK
  {
    path: "/sessions",
    labelKey: "sessions",
    label: "Sessions",
    icon: MessageSquare,
  },
  { path: "/cron", labelKey: "cron", label: "Cron", icon: Clock },
  // OBSERVE
  { path: "/logs", labelKey: "logs", label: "Logs", icon: FileText },
  {
    path: "/analytics",
    labelKey: "analytics",
    label: "Analytics",
    icon: BarChart3,
  },
  // CAPABILITIES
  { path: "/models", labelKey: "models", label: "Models", icon: Cpu },
  { path: "/skills", labelKey: "skills", label: "Skills", icon: Package },
  { path: "/plugins", labelKey: "plugins", label: "Plugins", icon: Puzzle },
  { path: "/mcp", label: "MCP", icon: Plug },
  // CONNECT
  { path: "/channels", label: "Channels", icon: Radio },
  { path: "/webhooks", label: "Webhooks", icon: Webhook },
  { path: "/pairing", label: "Pairing", icon: ShieldCheck },
  { path: "/files", label: "Files", icon: FolderOpen },
  // SYSTEM (bottom cluster)
  { path: "/profiles", labelKey: "profiles", label: "Profiles", icon: Users },
  { path: "/config", labelKey: "config", label: "Config", icon: Settings },
  { path: "/env", labelKey: "keys", label: "Keys", icon: KeyRound },
  { path: "/system", label: "System", icon: Wrench },
];

const SECTION_OF_PATH: Record<string, NavSectionId> = {
  "/chat": "work",
  "/sessions": "work",
  "/cron": "work",
  "/logs": "observe",
  "/analytics": "observe",
  "/models": "capabilities",
  "/skills": "capabilities",
  "/plugins": "capabilities",
  "/mcp": "capabilities",
  "/channels": "connect",
  "/webhooks": "connect",
  "/pairing": "connect",
  "/files": "connect",
  "/profiles": "system",
  "/config": "system",
  "/env": "system",
  "/system": "system",
};

const SECTION_ORDER: NavSectionId[] = [
  "work",
  "observe",
  "capabilities",
  "connect",
  "system",
];

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

export function resolveIcon(
  name: string,
): ComponentType<{ className?: string }> {
  return ICON_MAP[name] ?? Puzzle;
}

/**
 * Merge plugin nav entries into the built-in list (honoring the manifest
 * `tab.position` contract: "end" | "after:<seg>" | "before:<seg>"), then
 * group the result into labeled sidebar sections.
 *
 * Section membership rules:
 * - built-ins map through SECTION_OF_PATH;
 * - a plugin item anchored via after:/before: joins its anchor's section
 *   (including the dynamic plugins group when anchored to another
 *   unanchored plugin);
 * - unanchored plugin items — and anchors whose target is absent (hidden
 *   built-in, unknown path) — fall back to the dynamic plugins group,
 *   matching the old flat-list behavior of appending at the end.
 */
export function buildSidebarSections(
  builtIn: NavItem[],
  manifests: PluginManifest[],
): { sections: NavSection[]; pluginItems: NavItem[] } {
  type Tag = NavSectionId | "plugins";
  // "system" fallback keeps a future built-in without a section mapping
  // visible in the sidebar instead of misfiling it under Plugins.
  const tagged: Array<{ item: NavItem; tag: Tag }> = builtIn.map((item) => ({
    item,
    tag: SECTION_OF_PATH[item.path] ?? "system",
  }));

  for (const manifest of manifests) {
    if (manifest.tab.override) continue;
    if (manifest.tab.hidden) continue;

    const pluginItem: NavItem = {
      path: manifest.tab.path,
      label: manifest.label,
      icon: resolveIcon(manifest.icon),
    };

    const pos = manifest.tab.position ?? "end";
    let placed = false;
    if (pos.startsWith("after:") || pos.startsWith("before:")) {
      const after = pos.startsWith("after:");
      const target = "/" + pos.slice(after ? 6 : 7);
      const idx = tagged.findIndex((e) => e.item.path === target);
      if (idx >= 0) {
        tagged.splice(after ? idx + 1 : idx, 0, {
          item: pluginItem,
          tag: tagged[idx].tag,
        });
        placed = true;
      }
    }
    if (!placed) {
      tagged.push({ item: pluginItem, tag: "plugins" });
    }
  }

  const sections = SECTION_ORDER.map((id) => ({
    id,
    items: tagged.filter((e) => e.tag === id).map((e) => e.item),
  })).filter((s) => s.items.length > 0);
  const pluginItems = tagged
    .filter((e) => e.tag === "plugins")
    .map((e) => e.item);

  return { sections, pluginItems };
}
