import { PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { AuthWidget } from "@/components/AuthWidget";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ProfileSwitcher } from "@/components/ProfileSwitcher";
import { SidebarFooter } from "@/components/SidebarFooter";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { useI18n } from "@/i18n";
import type { Translations } from "@/i18n/types";
import type { StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";
import { themeAppearance, useTheme } from "@/themes";
import { SidebarIconWithTooltip } from "./SidebarIconWithTooltip";
import { SidebarNavLink } from "./SidebarNavLink";
import { SidebarSystemActions } from "./SidebarSystemActions";
import type { TooltipWarmRef } from "./SidebarTooltip";
import type { NavItem, NavSection, NavSectionId } from "./nav-model";

const PLUGIN_NAV_HEADING_ID = "hermes-sidebar-plugin-nav-heading";

function sectionLabel(id: NavSectionId, t: Translations): string {
  const s = t.app.navSections;
  switch (id) {
    case "work":
      return s?.work ?? "Work";
    case "observe":
      return s?.observe ?? "Observe";
    case "capabilities":
      return s?.capabilities ?? "Capabilities";
    case "connect":
      return s?.connect ?? "Connect";
    case "system":
      return s?.system ?? t.app.system;
  }
}

export function AppSidebar({
  collapsed,
  isDesktopCollapsed,
  mobileOpen,
  closeMobile,
  toggleCollapsed,
  sections,
  pluginItems,
  status,
  tooltipWarmRef,
}: AppSidebarProps) {
  const { t } = useI18n();
  const { theme } = useTheme();
  // plus-lighter is additive: on light canvases it clamps the wordmark to
  // near-white, so only blend when the active theme is actually dark.
  const isDarkAppearance = themeAppearance(theme) === "dark";

  const primarySections = sections.filter((s) => s.id !== "system");
  const systemSection = sections.find((s) => s.id === "system");
  // Hairline rules replace section labels in collapsed mode; the first
  // group needs none — the nav's own border-t already separates it.
  const pluginGroupHasRule = primarySections.length > 0;
  const systemHasRule = pluginGroupHasRule || pluginItems.length > 0;

  return (
    <aside
      id="app-sidebar"
      aria-label={t.app.navigation}
      className={cn(
        "fixed top-0 left-0 z-50 flex h-dvh max-h-dvh w-64 min-h-0 flex-col font-sans",
        "border-r border-current/20",
        "bg-background-base",
        "transition-[transform] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        "lg:sticky lg:top-0 lg:translate-x-0 lg:shrink-0 lg:overflow-hidden",
        "lg:transition-[width] lg:duration-300 lg:ease-[cubic-bezier(0.23,1,0.32,1)]",
        collapsed && "lg:w-14",
      )}
      style={{
        background: "var(--component-sidebar-background)",
        clipPath: "var(--component-sidebar-clip-path)",
        borderImage: "var(--component-sidebar-border-image)",
      }}
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center gap-2",
          "border-b border-current/20",
          collapsed ? "lg:justify-center lg:px-0" : "px-4 justify-between",
        )}
      >
        <div className={cn("flex items-center gap-2", collapsed && "lg:hidden")}>
          <PluginSlot name="header-left" />

          <Typography
            className="font-bold text-[1.125rem] leading-[0.95] tracking-[0.0525rem] text-midground uppercase"
            style={isDarkAppearance ? { mixBlendMode: "plus-lighter" } : undefined}
          >
            Fabric
          </Typography>
        </div>

        <Button
          ghost
          size="icon"
          onClick={closeMobile}
          aria-label={t.app.closeNavigation}
          className="lg:hidden text-text-secondary hover:text-midground"
        >
          <X />
        </Button>

        <Button
          ghost
          size="icon"
          onClick={toggleCollapsed}
          aria-label={collapsed ? t.common.expand : t.common.collapse}
          className="hidden lg:flex text-text-secondary hover:text-midground"
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </Button>
      </div>

      <ProfileSwitcher collapsed={isDesktopCollapsed} />

      <nav
        className="min-h-0 w-full flex-1 overflow-y-auto overflow-x-hidden border-t border-current/10 py-2"
        aria-label={t.app.navigation}
      >
        {primarySections.map((section, index) => (
          <SidebarNavGroup
            key={section.id}
            closeMobile={closeMobile}
            collapsed={isDesktopCollapsed}
            headingId={`fabric-sidebar-nav-${section.id}-heading`}
            items={section.items}
            label={sectionLabel(section.id, t)}
            showRule={index > 0}
            t={t}
            tooltipWarmRef={tooltipWarmRef}
          />
        ))}

        {pluginItems.length > 0 && (
          <SidebarNavGroup
            closeMobile={closeMobile}
            collapsed={isDesktopCollapsed}
            headingId={PLUGIN_NAV_HEADING_ID}
            items={pluginItems}
            label={t.app.pluginNavSection}
            showRule={pluginGroupHasRule}
            t={t}
            tooltipWarmRef={tooltipWarmRef}
          />
        )}

        {systemSection && (
          <SidebarNavGroup
            closeMobile={closeMobile}
            collapsed={isDesktopCollapsed}
            headingId="fabric-sidebar-nav-system-heading"
            items={systemSection.items}
            label={sectionLabel("system", t)}
            showRule={systemHasRule}
            t={t}
            tooltipWarmRef={tooltipWarmRef}
          />
        )}
      </nav>

      <SidebarSystemActions
        collapsed={isDesktopCollapsed}
        onNavigate={closeMobile}
        status={status}
        tooltipWarmRef={tooltipWarmRef}
      />

      <div
        className={cn(
          "flex shrink-0 items-center gap-2",
          "px-3 py-2",
          "border-t border-current/20",
          isDesktopCollapsed
            ? "lg:flex-col lg:items-start lg:gap-3 lg:py-3"
            : "justify-between",
        )}
      >
        <div
          className={cn(
            "flex min-w-0 items-center gap-2",
            isDesktopCollapsed && "lg:flex-col lg:items-start",
          )}
        >
          <PluginSlot name="header-right" />

          <SidebarIconWithTooltip
            collapsed={isDesktopCollapsed}
            label={t.theme?.switchTheme ?? "Switch theme"}
            tooltipWarmRef={tooltipWarmRef}
          >
            <ThemeSwitcher collapsed={isDesktopCollapsed} dropUp />
          </SidebarIconWithTooltip>

          <SidebarIconWithTooltip
            collapsed={isDesktopCollapsed}
            label={t.language.switchTo}
            tooltipWarmRef={tooltipWarmRef}
          >
            <LanguageSwitcher collapsed={isDesktopCollapsed} dropUp />
          </SidebarIconWithTooltip>
        </div>
      </div>

      <div
        className={cn("flex shrink-0 flex-col", isDesktopCollapsed && "lg:hidden")}
      >
        <AuthWidget />
        <SidebarFooter status={status} />
      </div>
    </aside>
  );
}

function SidebarNavGroup({
  closeMobile,
  collapsed,
  headingId,
  items,
  label,
  showRule,
  t,
  tooltipWarmRef,
}: SidebarNavGroupProps) {
  return (
    <div
      aria-labelledby={headingId}
      className="flex flex-col pb-1"
      role="group"
    >
      {showRule && collapsed && (
        <span
          aria-hidden
          className="mx-4 my-1.5 hidden border-t border-current/10 lg:block"
        />
      )}

      <span
        className={cn(
          "px-5 pt-2.5 pb-1",
          "font-sans text-display text-xs uppercase tracking-[0.12em] text-text-tertiary",
          collapsed && "lg:hidden",
        )}
        id={headingId}
      >
        {label}
      </span>

      <ul className="flex flex-col">
        {items.map((item) => (
          <SidebarNavLink
            closeMobile={closeMobile}
            collapsed={collapsed}
            item={item}
            key={item.path}
            t={t}
            tooltipWarmRef={tooltipWarmRef}
          />
        ))}
      </ul>
    </div>
  );
}

interface AppSidebarProps {
  closeMobile: () => void;
  collapsed: boolean;
  isDesktopCollapsed: boolean;
  mobileOpen: boolean;
  pluginItems: NavItem[];
  sections: NavSection[];
  status: StatusResponse | null;
  toggleCollapsed: () => void;
  tooltipWarmRef: TooltipWarmRef;
}

interface SidebarNavGroupProps {
  closeMobile: () => void;
  collapsed: boolean;
  headingId: string;
  items: NavItem[];
  label: string;
  showRule: boolean;
  t: Translations;
  tooltipWarmRef: TooltipWarmRef;
}
