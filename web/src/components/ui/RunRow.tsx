import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Checkbox } from "@nous-research/ui/ui/components/checkbox";
import { cn, themedBody } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { AgentStatusBadge, type AgentStatus } from "./AgentStatusBadge";
import { MonoId } from "./MonoId";
import { RelativeTime } from "./RelativeTime";

export interface RunRowProps {
  /** Row title (sans); italic-muted "untitled" fallback handled by caller. */
  title: ReactNode;
  status: AgentStatus;
  statusLabel?: string;
  /** Technical id → `MonoId`. */
  id: string;
  /** SOURCE_CONFIG glyph; rendered monochrome (G11). */
  sourceIcon?: LucideIcon;
  /** Model short name, mono chip in the meta line. */
  model?: string | null;
  /** Counters line (msgs · tools · tokens · cost), `·`-separated by caller. */
  meta?: ReactNode;
  /** last_active / started_at → `RelativeTime`. */
  timestamp: number | string;
  /** Checkbox state (Sessions only). */
  selected?: boolean;
  /** Omit → no checkbox rendered. */
  onSelectClick?: (e: React.MouseEvent) => void;
  expanded?: boolean;
  onToggle?: () => void;
  /** Trailing icon buttons. */
  actions?: ReactNode;
  /** Expansion body (timeline). */
  children?: ReactNode;
  className?: string;
}

const SEPARATOR = (
  <span aria-hidden="true" className="text-border">
    &#183;
  </span>
);

/**
 * The shared "an agent ran" row (Sessions ledger + Cron run-history
 * drawer): 1px `border-border` box, hover tint, `[checkbox?] [source
 * glyph] [title + status / meta row] [actions]` grid with an optional
 * expansion body below.
 */
export function RunRow({
  title,
  status,
  statusLabel,
  id,
  sourceIcon: SourceIcon,
  model,
  meta,
  timestamp,
  selected,
  onSelectClick,
  expanded,
  onToggle,
  actions,
  children,
  className,
}: RunRowProps) {
  const { t } = useI18n();

  // Selected rows get the stronger primary tint so the selection state is
  // unambiguous. Beat the live styling — explicit user selection takes
  // priority over "this agent is live" (precedence proven in SessionsPage).
  const containerClasses = selected
    ? "border-primary/40 bg-primary/[0.06]"
    : status === "live"
      ? "border-success/30 bg-success/[0.03]"
      : "border-border";

  return (
    <div
      className={cn(
        "max-w-full min-w-0 overflow-hidden border transition-colors",
        containerClasses,
        className,
      )}
    >
      <div
        className={cn(
          "flex items-start gap-3 p-3 transition-colors hover:bg-secondary/30",
          onToggle && "cursor-pointer",
        )}
        onClick={onToggle}
      >
        {onSelectClick && (
          <span className="flex shrink-0 items-center pt-0.5">
            {/* onClick directly on the Checkbox: carries the real shiftKey
                for range-select and covers Space activation too; selection
                must never toggle expansion. */}
            <Checkbox
              checked={!!selected}
              onClick={(e) => {
                e.stopPropagation();
                onSelectClick(e);
              }}
              aria-label={t.sessions.selectSession}
            />
          </span>
        )}
        {SourceIcon && (
          <span className="shrink-0 pt-0.5 text-muted-foreground">
            <SourceIcon aria-hidden="true" className="h-4 w-4" />
          </span>
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className={cn(themedBody, "min-w-0 flex-1 truncate text-sm")}>
              {title}
            </span>
            <AgentStatusBadge status={status} label={statusLabel} />
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
            <MonoId id={id} />
            {model ? (
              <>
                {SEPARATOR}
                <span
                  title={model}
                  className="font-mono-ui max-w-[min(100%,12rem)] truncate"
                >
                  {model}
                </span>
              </>
            ) : null}
            {meta ? (
              <>
                {SEPARATOR}
                {meta}
              </>
            ) : null}
            {SEPARATOR}
            <RelativeTime value={timestamp} className="shrink-0" />
          </div>
        </div>
        {actions && (
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        )}
      </div>
      {expanded && children != null && (
        <div className="border-t border-border">{children}</div>
      )}
    </div>
  );
}
