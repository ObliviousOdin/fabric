import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  /** Lucide icon component (not an element): `icon={BarChart3}`. */
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  /** Optional call-to-action, typically a DS `<Button>`. */
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-6 py-12 text-center text-muted-foreground",
        className,
      )}
    >
      {Icon ? <Icon aria-hidden="true" className="mb-3 h-8 w-8 opacity-40" /> : null}
      {/* Real heading (same level as the DS CardTitle's <h3>) so the empty
          state is reachable via screen-reader heading navigation. */}
      <h3 className="text-sm font-medium">{title}</h3>
      {description ? (
        <p className="mt-1 text-xs text-text-tertiary">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
