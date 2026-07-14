import type { ReactNode } from "react";
import { Badge } from "@/components/fabric/Badge";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { RelativeTime } from "./RelativeTime";

export type TimelineNodeKind =
  | "user"
  | "assistant"
  | "system"
  | "tool"
  | "handoff";

export interface TimelineNodeProps {
  kind: TimelineNodeKind;
  /** Role label or `"tool: name"` or `"Context handoff"`. */
  label: string;
  /** Epoch seconds → `RelativeTime`. */
  timestamp?: number;
  /** FTS match: warning ring + "match" badge, `data-search-hit` anchor. */
  hit?: boolean;
  /** Markdown / pre content / ToolCallBlock list. */
  children: ReactNode;
}

// Role tint lives in the rail dot + label instead of a full-width block
// background (density: less ink, same signal). Single accent rule (G11):
// primary marks the human turn; agent activity uses the status tones.
const KIND_TONES: Record<TimelineNodeKind, { dot: string; label: string }> = {
  user: { dot: "bg-primary", label: "text-primary" },
  assistant: { dot: "bg-success", label: "text-success" },
  tool: { dot: "bg-warning", label: "text-warning" },
  system: { dot: "bg-muted-foreground", label: "text-muted-foreground" },
  handoff: { dot: "bg-muted-foreground", label: "text-muted-foreground italic" },
};

/**
 * Langfuse-inspired chronology node for session transcripts: a left rail
 * (2px `bg-border` line + role-toned dot), a `[dot] [label] [time]`
 * header, and the body indented under the rail. FTS hits keep the
 * existing `data-search-hit` + warning-ring treatment so
 * auto-scroll-to-first-hit keeps working.
 */
export function TimelineNode({
  kind,
  label,
  timestamp,
  hit,
  children,
}: TimelineNodeProps) {
  const { t } = useI18n();
  const tone = KIND_TONES[kind];
  return (
    <div
      className={cn("flex gap-3", hit && "ring-1 ring-warning/40")}
      data-search-hit={hit || undefined}
    >
      <div aria-hidden="true" className="flex shrink-0 flex-col items-center pt-1">
        <span className={cn("h-2 w-2 rounded-full", tone.dot)} />
        <span className="mt-1 w-0.5 flex-1 bg-border" />
      </div>
      <div className="min-w-0 flex-1 pb-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className={cn("text-xs font-semibold", tone.label)}>
            {label}
          </span>
          {hit && (
            <Badge tone="warning" className="px-1.5 py-0 text-xs">
              {t.common.match}
            </Badge>
          )}
          {timestamp !== undefined && (
            <RelativeTime
              value={timestamp}
              className="text-xs text-text-tertiary"
            />
          )}
        </div>
        <div className="mt-1 min-w-0">{children}</div>
      </div>
    </div>
  );
}
