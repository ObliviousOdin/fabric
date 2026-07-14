import type { ReactNode } from "react";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { cn } from "@/lib/utils";
import {
  SCREEN_STATE_PRESENTATION,
  type ScreenStateKind,
} from "./screen-state";

export interface ScreenStateProps {
  kind: Exclude<ScreenStateKind, "normal">;
  title: string;
  description: ReactNode;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
  className?: string;
  compact?: boolean;
}

/**
 * Shared state grammar for Workspace and Admin screens. It renders only
 * states the caller actually knows; `normal` deliberately has no component
 * so real content stays the source of truth.
 */
export function ScreenState({
  kind,
  title,
  description,
  primaryAction,
  secondaryAction,
  className,
  compact = false,
}: ScreenStateProps) {
  const presentation = SCREEN_STATE_PRESENTATION[kind];
  const Icon = presentation.icon;

  return (
    <Card
      role={presentation.role}
      aria-live={kind === "loading" || kind === "in-progress" ? "polite" : undefined}
      aria-busy={kind === "loading" || kind === "in-progress" ? true : undefined}
      className={cn("border-border/80 bg-card/80", className)}
    >
      <CardContent
        className={cn(
          "flex min-w-0 flex-col items-center justify-center text-center",
          compact ? "gap-2 px-4 py-6" : "gap-3 px-6 py-10",
        )}
      >
        <span
          className={cn(
            "grid place-items-center rounded-lg border border-current/15 bg-current/5",
            compact ? "h-9 w-9" : "h-11 w-11",
            presentation.tone,
          )}
        >
          <Icon
            aria-hidden="true"
            className={cn(
              compact ? "h-4 w-4" : "h-5 w-5",
              (kind === "loading" || kind === "in-progress") &&
                "animate-spin motion-reduce:animate-none",
            )}
          />
        </span>
        <div className="max-w-xl">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {description}
          </div>
        </div>
        {(primaryAction || secondaryAction) && (
          <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
            {primaryAction}
            {secondaryAction}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
