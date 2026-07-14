import { useState, type FocusEvent, type MouseEvent } from "react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import type { Translations } from "@/i18n/types";
import { SidebarTooltip, type TooltipWarmRef } from "./SidebarTooltip";
import { navItemLabel } from "./nav-label";
import type { NavItem } from "./nav-model";

export function SidebarNavLink({
  closeMobile,
  collapsed,
  item,
  tooltipWarmRef,
  t,
}: SidebarNavLinkProps) {
  const { path, icon: Icon } = item;
  const [hovered, setHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<HTMLElement | null>(null);

  const navLabel = navItemLabel(item, t);
  const showTooltip = (
    event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>,
  ) => {
    setHovered(true);
    setTooltipAnchor(event.currentTarget);
  };
  const hideTooltip = () => {
    setHovered(false);
    setTooltipAnchor(null);
  };

  return (
    <li
      onMouseEnter={collapsed ? showTooltip : undefined}
      onMouseLeave={collapsed ? hideTooltip : undefined}
    >
      <NavLink
        to={path}
        end={path === "/workspace/conversations"}
        onClick={closeMobile}
        aria-label={collapsed ? navLabel : undefined}
        onFocus={collapsed ? showTooltip : undefined}
        onBlur={collapsed ? hideTooltip : undefined}
        className={({ isActive }) =>
          cn(
            "relative flex h-11 min-h-11 items-center gap-3 px-5",
            "font-sans text-sm",
            "whitespace-nowrap transition-colors cursor-pointer",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
            isActive
              ? "bg-primary/[0.07] text-foreground"
              : "text-text-secondary hover:bg-muted/55 hover:text-foreground",
          )
        }
        style={{
          clipPath: "var(--component-tab-clip-path)",
        }}
      >
        {({ isActive }) => (
          <>
            <Icon
              className={cn(
                "h-4 w-4 shrink-0",
                isActive && "text-primary",
              )}
            />

            <span
              className={cn(
                "truncate transition-opacity duration-300",
                collapsed ? "lg:opacity-0" : "lg:opacity-100",
              )}
            >
              {navLabel}
            </span>

            {isActive && (
              <>
                <span
                  aria-hidden
                  className="absolute bottom-2 left-3 top-2 w-0.5 bg-primary"
                />
                <span
                  aria-hidden
                  className="absolute bottom-2 left-3 h-0.5 w-3 bg-primary"
                />
              </>
            )}
          </>
        )}
      </NavLink>

      {collapsed && hovered && tooltipAnchor && (
        <SidebarTooltip
          anchor={tooltipAnchor}
          label={navLabel}
          warmRef={tooltipWarmRef}
        />
      )}
    </li>
  );
}

interface SidebarNavLinkProps {
  closeMobile: () => void;
  collapsed: boolean;
  item: NavItem;
  t: Translations;
  tooltipWarmRef: TooltipWarmRef;
}
