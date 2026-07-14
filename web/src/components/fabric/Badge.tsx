import { forwardRef, type ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type BadgeTone =
  | "default"
  | "destructive"
  | "outline"
  | "secondary"
  | "success"
  | "warning";

export interface BadgeProps extends Omit<ComponentProps<"span">, "color"> {
  tone?: BadgeTone;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  default: "border-border/80 bg-muted/45 text-foreground",
  destructive: "border-destructive/35 bg-destructive/[0.08] text-destructive",
  outline: "border-border bg-transparent text-text-secondary",
  secondary: "border-border/70 bg-muted/55 text-text-secondary",
  success: "border-success/35 bg-success/[0.08] text-success",
  warning: "border-warning/40 bg-warning/[0.08] text-warning",
};

/**
 * Fabric's dependency-light status/provenance chip.
 *
 * It intentionally avoids the inherited Lens/BlendMode chain: badges are
 * quiet ledger annotations, not miniature brand effects. The prop and tone
 * contract matches the component exposed through the dashboard plugin SDK.
 */
export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { className, tone = "default", ...props },
  ref,
) {
  return (
    <span
      ref={ref}
      data-tone={tone}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap border px-2 py-1",
        "font-sans text-[0.6875rem] font-medium leading-none tracking-normal",
        TONE_CLASSES[tone],
        className,
      )}
      {...props}
    />
  );
});
