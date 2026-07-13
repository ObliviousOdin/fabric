import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface PageToolbarProps {
  /** Accessible name for the control row (localize at the call site). */
  label?: string;
  /** Filter cluster — `FilterGroup`/`Segmented` groups, period buttons, search inputs. */
  filters?: ReactNode;
  /** Action cluster — refresh, toggles, primary actions; pushed to the trailing edge. */
  actions?: ReactNode;
  className?: string;
}

/**
 * Standard toolbar row for page headers (`PageHeaderProvider` `afterTitle` /
 * `end` slots) and in-page filter rows: filters cluster leading, actions
 * trailing, both wrapping on narrow widths. As a block-level flex row it
 * fills its container in page bodies but shrinks to content inside the
 * header's inline slots.
 */
export function PageToolbar({
  label,
  filters,
  actions,
  className,
}: PageToolbarProps) {
  return (
    <div
      // role="group", not "toolbar": children are plain Tab stops — the
      // toolbar role would promise roving-tabindex/arrow-key traversal.
      role="group"
      aria-label={label}
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2",
        className,
      )}
    >
      {filters ? (
        <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-3">
          {filters}
        </div>
      ) : null}
      {actions ? (
        <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      ) : null}
    </div>
  );
}
