import { useState, type FocusEvent, type MouseEvent } from "react";
import { gatewayLine } from "@/components/SidebarStatusStrip";
import { useI18n } from "@/i18n";
import type { StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SidebarTooltip, type TooltipWarmRef } from "./SidebarTooltip";

/** Collapsed-sidebar stand-in for the status strip: a single gateway dot. */
export function GatewayDot({ collapsed, status, tooltipWarmRef }: GatewayDotProps) {
  const { t } = useI18n();
  const [hovered, setHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<HTMLElement | null>(null);

  const toneToColor: Record<string, string> = {
    "text-success": "bg-success",
    "text-warning": "bg-warning",
    "text-destructive": "bg-destructive",
    "text-muted-foreground": "bg-muted-foreground",
  };

  let color: string;
  let label: string;

  if (!status) {
    color = "bg-midground/20";
    label = t.status.gateway;
  } else {
    const gw = gatewayLine(status, t);
    color = toneToColor[gw.tone] ?? "bg-muted-foreground";
    label = `${t.status.gateway} ${gw.label}`;
  }
  const showTooltip = (
    event: MouseEvent<HTMLDivElement> | FocusEvent<HTMLDivElement>,
  ) => {
    setHovered(true);
    setTooltipAnchor(event.currentTarget);
  };
  const hideTooltip = () => {
    setHovered(false);
    setTooltipAnchor(null);
  };

  return (
    <div
      className={cn(
        "hidden lg:flex py-3 pl-[1.625rem] transition-opacity duration-300",
        collapsed
          ? "lg:opacity-100"
          : "lg:opacity-0 lg:h-0 lg:py-0 lg:overflow-hidden",
      )}
      role="status"
      aria-label={label}
      tabIndex={collapsed ? 0 : -1}
      onMouseEnter={collapsed ? showTooltip : undefined}
      onMouseLeave={collapsed ? hideTooltip : undefined}
      onFocus={collapsed ? showTooltip : undefined}
      onBlur={collapsed ? hideTooltip : undefined}
    >
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", color)} />

      {hovered && tooltipAnchor && (
        <SidebarTooltip
          anchor={tooltipAnchor}
          label={label}
          warmRef={tooltipWarmRef}
        />
      )}
    </div>
  );
}

interface GatewayDotProps {
  collapsed: boolean;
  status: StatusResponse | null;
  tooltipWarmRef: TooltipWarmRef;
}
