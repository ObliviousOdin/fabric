import { Link } from "react-router-dom";
import { gatewayLine } from "@/components/gateway-line";
import type { StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import {
  StatusSignal,
  type FabricStatusTone,
} from "@/components/fabric/StatusSignal";

/** Gateway + session summary for the System sidebar block (no separate strip chrome). */
export function SidebarStatusStrip({
  collapsed = false,
  status,
}: SidebarStatusStripProps) {
  const { t } = useI18n();

  if (status === null) {
    return (
      <div className={cn("px-4 py-3", collapsed && "lg:px-0")} aria-hidden>
        <div className="h-2 w-[70%] max-w-full animate-pulse rounded-sm bg-muted" />
      </div>
    );
  }

  const gw = gatewayLine(status, t);
  const toneMap: Record<string, FabricStatusTone> = {
    "text-success": "success",
    "text-warning": "warning",
    "text-destructive": "danger",
    "text-muted-foreground": "neutral",
  };
  const tone = toneMap[gw.tone] ?? "neutral";
  const detail = `${status.active_sessions} active`;

  return (
    <Link
      to="/admin/system"
      title={t.app.statusOverview}
      className={cn(
        "flex min-h-11 min-w-0 items-center px-4 text-left",
        "transition-colors hover:bg-muted/55",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        collapsed && "lg:justify-center lg:px-0",
      )}
    >
      <StatusSignal
        compact={collapsed}
        detail={detail}
        label={`System ${gw.label}`}
        pulse={tone === "success"}
        tone={tone}
      />
    </Link>
  );
}

interface SidebarStatusStripProps {
  collapsed?: boolean;
  status: StatusResponse | null;
}
