import { cn } from "@/lib/utils";

export type SkeletonVariant = "line" | "block" | "row-list";

export interface SkeletonProps {
  /** `line` (single bar, default), `block` (panel-sized), `row-list` (n stacked lines). */
  variant?: SkeletonVariant;
  /** Number of bars for `row-list`; ignored otherwise. */
  rows?: number;
  className?: string;
}

/* Cycle a few widths so row lists read as text, not stripes. */
const ROW_WIDTHS = ["w-full", "w-11/12", "w-4/5"] as const;

const BAR = "animate-pulse rounded-sm bg-muted";

export function Skeleton({ variant = "line", rows = 3, className }: SkeletonProps) {
  if (variant === "row-list") {
    return (
      <div aria-hidden="true" className={cn("flex flex-col gap-2", className)}>
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className={cn(BAR, "h-4", ROW_WIDTHS[i % ROW_WIDTHS.length])} />
        ))}
      </div>
    );
  }
  return (
    <div
      aria-hidden="true"
      className={cn(BAR, variant === "block" ? "h-24 w-full" : "h-4 w-full", className)}
    />
  );
}
