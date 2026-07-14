import { PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef } from "react";
import { Button } from "@nous-research/ui/ui/components/button";
import { AuthWidget } from "@/components/AuthWidget";
import { FabricBrand } from "@/components/brand/FabricBrand";
import { ExperienceSwitcher } from "@/components/experience/ExperienceSwitcher";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ProfileSwitcher } from "@/components/ProfileSwitcher";
import { SidebarStatusStrip } from "@/components/SidebarStatusStrip";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { useI18n } from "@/i18n";
import type { Translations } from "@/i18n/types";
import type { StatusResponse } from "@/lib/api";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";
import { themeAppearance, useTheme } from "@/themes";
import type { AppSurface } from "@/app/routes";
import { SidebarIconWithTooltip } from "./SidebarIconWithTooltip";
import { SidebarNavLink } from "./SidebarNavLink";
import type { TooltipWarmRef } from "./SidebarTooltip";
import type { NavItem, NavSection, NavSectionId } from "./nav-model";

const PLUGIN_NAV_HEADING_ID = "hermes-sidebar-plugin-nav-heading";
const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function sectionLabel(id: NavSectionId, t: Translations): string {
  return id === "workspace"
    ? (t.app.enterpriseNav?.workspace ?? "Workspace")
    : (t.app.enterpriseNav?.admin ?? "Admin");
}

export function AppSidebar({
  collapsed,
  isDesktopCollapsed,
  isMobile,
  mobileOpen,
  surface,
  closeMobile,
  toggleCollapsed,
  sections,
  pluginItems,
  status,
  tooltipWarmRef,
}: AppSidebarProps) {
  const { t } = useI18n();
  const { theme } = useTheme();
  const sidebarRef = useRef<HTMLElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const brandAppearance = themeAppearance(theme);

  const pluginGroupHasRule = sections.length > 0;
  const mobileDrawerOpen = isMobile && mobileOpen;
  const mobileDrawerHidden = isMobile && !mobileOpen;
  useBodyScrollLock(mobileDrawerOpen);

  useEffect(() => {
    if (!mobileDrawerOpen) return;
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const first =
        sidebarRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (first ?? sidebarRef.current)?.focus();
    });

    return () => {
      cancelled = true;
      const target = restoreFocusRef.current;
      restoreFocusRef.current = null;
      if (target?.isConnected) target.focus();
    };
  }, [mobileDrawerOpen]);

  const handleDrawerKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (!mobileDrawerOpen) return;
    // A portaled nested modal is outside the aside DOM even though React
    // bubbles it through this component tree. That modal owns its own keys.
    if (
      event.target instanceof Node &&
      !sidebarRef.current?.contains(event.target)
    ) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeMobile();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = Array.from(
      sidebarRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ??
        [],
    );
    if (focusable.length === 0) {
      event.preventDefault();
      sidebarRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (
      event.shiftKey &&
      (active === first || !sidebarRef.current?.contains(active))
    ) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <aside
      ref={sidebarRef}
      id="app-sidebar"
      aria-label={t.app.navigation}
      aria-hidden={mobileDrawerHidden ? true : undefined}
      aria-modal={mobileDrawerOpen ? true : undefined}
      inert={mobileDrawerHidden ? true : undefined}
      onKeyDown={handleDrawerKeyDown}
      role={isMobile ? "dialog" : undefined}
      tabIndex={mobileDrawerOpen ? -1 : undefined}
      className={cn(
        "fixed top-0 left-0 z-50 flex h-dvh max-h-dvh w-64 min-h-0 flex-col font-sans",
        "border-r border-border/80",
        "bg-background-base",
        "transition-[transform] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        "lg:sticky lg:top-0 lg:translate-x-0 lg:shrink-0 lg:overflow-hidden",
        "lg:transition-[width] lg:duration-300 lg:ease-[cubic-bezier(0.23,1,0.32,1)]",
        collapsed && "lg:w-14",
      )}
      style={{
        background:
          "color-mix(in srgb, var(--midground-base) 2%, var(--background-base))",
      }}
    >
      <div
        className={cn(
          "flex h-16 shrink-0 items-center gap-2",
          "border-b border-border/70",
          isDesktopCollapsed
            ? "lg:justify-center lg:gap-0 lg:px-0"
            : "justify-between px-4",
        )}
      >
        <div
          className={cn(
            "flex min-w-0 items-center gap-2",
            isDesktopCollapsed && "lg:gap-0",
          )}
        >
          <div className={cn("contents", isDesktopCollapsed && "lg:hidden")}>
            <PluginSlot name="header-left" />
          </div>

          <FabricBrand
            appearance={brandAppearance}
            compact={isDesktopCollapsed}
          />
        </div>

        <Button
          data-mobile-drawer-close="true"
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

      <ExperienceSwitcher
        collapsed={isDesktopCollapsed}
        onNavigate={closeMobile}
        surface={surface}
      />

      {/* Profiles scope agent configuration and memory. They intentionally do
          not stand in for the tenant/workspace/site scope of the app shell. */}
      <div data-scope-kind="agent-profile">
        <ProfileSwitcher collapsed={isDesktopCollapsed} />
      </div>

      <nav
        className="min-h-0 w-full flex-1 overflow-y-auto overflow-x-hidden py-2"
        aria-label={t.app.navigation}
      >
        {sections.map((section, index) => (
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
      </nav>

      <div
        className={cn(
          "flex shrink-0 items-center gap-1",
          "border-t border-border/70 px-2 py-1.5",
          isDesktopCollapsed
            ? "lg:flex-col lg:px-1 lg:py-2"
            : "justify-between",
        )}
      >
        <SidebarStatusStrip collapsed={isDesktopCollapsed} status={status} />

        <div
          className={cn(
            "flex min-w-0 items-center gap-1",
            isDesktopCollapsed && "lg:flex-col",
          )}
        >
          <PluginSlot name="header-right" />

          <SidebarIconWithTooltip
            collapsed
            label={t.theme?.switchTheme ?? "Switch theme"}
            tooltipWarmRef={tooltipWarmRef}
          >
            <ThemeSwitcher collapsed dropUp />
          </SidebarIconWithTooltip>

          <SidebarIconWithTooltip
            collapsed
            label={t.language.switchTo}
            tooltipWarmRef={tooltipWarmRef}
          >
            <LanguageSwitcher collapsed dropUp />
          </SidebarIconWithTooltip>
        </div>
      </div>

      <div
        className={cn(
          "flex shrink-0 flex-col",
          isDesktopCollapsed && "lg:hidden",
        )}
      >
        <AuthWidget />
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
          "font-sans text-xs font-medium tracking-normal text-text-tertiary",
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
  isMobile: boolean;
  mobileOpen: boolean;
  surface: AppSurface;
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
