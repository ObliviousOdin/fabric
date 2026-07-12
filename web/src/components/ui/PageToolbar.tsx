import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface PageToolbarProps {
  /** Accessible name for the toolbar (localize at the call site). */
  label?: string;
  /** Filter cluster — `FilterGroup`/`Segmented` groups, period buttons, search inputs. */
  filters?: ReactNode;
  /** Action cluster — refresh, toggles, primary actions; pushed to the trailing edge. */
  actions?: ReactNode;
  /** Extra content appended after `filters` inside the leading cluster. */
  children?: ReactNode;
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
  children,
  className,
}: PageToolbarProps) {
  return (
    <div
      role="toolbar"
      aria-label={label}
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2",
        className,
      )}
    >
      {filters || children ? (
        <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-3">
          {filters}
          {children}
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
