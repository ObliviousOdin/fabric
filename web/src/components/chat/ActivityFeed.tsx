import { Card } from "@nous-research/ui/ui/components/card";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import {
  formatToolDuration,
  type ActivityFeedState,
  type StatusFeedRow,
  type ToolFeedRow,
} from "./activity-feed";

export interface ActivityFeedProps {
  feed: ActivityFeedState;
  className?: string;
}

/**
 * Live activity ticker for the Chat rail (CH3), driven entirely by the
 * already-open `/api/events` subscription (state machine in
 * `./activity-feed.ts`, throttle-flushed by `ChatSidebar`). Hidden until
 * the first activity event arrives — a fresh PTY shows no empty box.
 *
 * A ticker, not a transcript: tool name (mono) + context + duration +
 * summary only; result bodies and inline diffs stay in the terminal.
 */
export function ActivityFeed({ feed, className }: ActivityFeedProps) {
  const { t } = useI18n();
  if (!feed.seenAny) return null;

  return (
    <Card className={cn("flex shrink-0 flex-col gap-1.5 px-3 py-2", className)}>
      <div className="text-display text-xs tracking-wider text-text-tertiary">
        {t.chatRail?.activity ?? "activity"}
      </div>

      <div
        role="log"
        className="flex max-h-[40vh] min-h-0 flex-col gap-1 overflow-y-auto overflow-x-hidden text-xs"
      >
        {feed.approvalPending && (
          <div className="flex items-start gap-1.5 border border-warning/40 bg-warning/5 px-1.5 py-1 text-warning">
            <span
              aria-hidden="true"
              className="mt-1 h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-current motion-reduce:animate-none"
            />
            <span className="wrap-break-word min-w-0 flex-1">
              {t.chatRail?.waitingApproval ??
                "waiting for approval — respond in the terminal"}
            </span>
          </div>
        )}

        {feed.stateLine && (
          <div className="flex items-center gap-1.5 text-text-secondary">
            <span
              aria-hidden="true"
              className={cn(
                "h-1.5 w-1.5 shrink-0 animate-pulse rounded-full motion-reduce:animate-none",
                feed.stateLine === "responding"
                  ? "bg-success"
                  : "bg-muted-foreground",
              )}
            />
            <span
              className={cn(
                "truncate font-mono-ui",
                feed.stateLine === "reasoning" && "italic",
              )}
            >
              {feed.stateLine === "responding"
                ? (t.chatRail?.responding ?? "responding…")
                : (t.chatRail?.reasoning ?? "reasoning…")}
            </span>
          </div>
        )}

        {feed.rows.map((row) =>
          row.rowKind === "tool" ? (
            <ToolRow key={row.key} row={row} running={t.chatRail?.running} />
          ) : (
            <StatusRow key={row.key} row={row} />
          ),
        )}
      </div>
    </Card>
  );
}

function ToolRow({ row, running }: { row: ToolFeedRow; running?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex min-w-0 items-center gap-1.5">
        <span
          aria-hidden="true"
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            row.running
              ? "animate-pulse bg-warning motion-reduce:animate-none"
              : "bg-success",
          )}
        />
        <span className="shrink-0 truncate font-mono-ui text-foreground">
          {row.name}
        </span>
        {row.context && (
          <span
            className="min-w-0 flex-1 truncate text-text-tertiary"
            title={row.context}
          >
            {row.context}
          </span>
        )}
        <span className="ml-auto shrink-0 pl-1 font-mono-ui tabular-nums text-text-secondary">
          {row.running
            ? (running ?? "running…")
            : row.durationS !== undefined
              ? formatToolDuration(row.durationS)
              : null}
        </span>
      </div>
      {!row.running && row.summary && (
        <div className="truncate pl-3 text-text-tertiary" title={row.summary}>
          {row.summary}
        </div>
      )}
    </div>
  );
}

function StatusRow({ row }: { row: StatusFeedRow }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-text-secondary">
      <span
        aria-hidden="true"
        className="h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground"
      />
      <span className="min-w-0 flex-1 truncate" title={row.text}>
        {row.text}
      </span>
    </div>
  );
}
