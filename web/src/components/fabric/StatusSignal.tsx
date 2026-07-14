import { cn } from "@/lib/utils";

export type FabricStatusTone =
  | "neutral"
  | "live"
  | "success"
  | "warning"
  | "danger";

export interface StatusSignalProps {
  className?: string;
  compact?: boolean;
  detail?: string;
  label: string;
  pulse?: boolean;
  tone?: FabricStatusTone;
}

const TONE_STYLES: Record<FabricStatusTone, string> = {
  neutral: "border-text-tertiary text-text-tertiary",
  live: "border-primary text-primary",
  success: "border-success text-success",
  warning: "border-warning text-warning",
  danger: "border-destructive text-destructive",
};

/**
 * Fabric's compact operational signal. Shape and text carry state together;
 * purple is reserved for a selected/live thread instead of tinting a panel.
 */
export function StatusSignal({
  className,
  compact = false,
  detail,
  label,
  pulse = false,
  tone = "neutral",
}: StatusSignalProps) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2", className)}>
      <span
        aria-hidden="true"
        className={cn(
          "relative grid h-3 w-3 shrink-0 place-items-center border",
          tone === "warning"
            ? "rotate-45"
            : tone === "danger"
              ? "rounded-[2px]"
              : "rounded-full",
          TONE_STYLES[tone],
          pulse && "motion-safe:animate-pulse",
        )}
      >
        {(tone === "live" || tone === "success") && (
          <span className="h-1 w-1 rounded-full bg-current" />
        )}
        {tone === "warning" && <span className="h-px w-1.5 bg-current" />}
      </span>
      <span
        className={cn(
          "min-w-0 truncate text-sm font-medium text-foreground",
          compact && "sr-only",
        )}
      >
        {label}
      </span>
      {detail && !compact && (
        <span className="min-w-0 truncate text-xs text-text-tertiary">
          {detail}
        </span>
      )}
    </span>
  );
}
