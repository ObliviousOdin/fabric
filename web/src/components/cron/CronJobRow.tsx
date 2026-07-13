import type { ReactNode } from "react";
import { ChevronDown, ChevronRight, Pause, Pencil, Play, Trash2, Zap } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import type { CronJob } from "@/lib/api";
import type { ScheduleDescribeStrings } from "@/lib/schedule";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import {
  AgentStatusBadge,
  cronJobAgentStatus,
  NextRunCountdown,
  RelativeTime,
} from "@/components/ui";
import {
  asText,
  getJobMode,
  getJobName,
  getJobProfile,
  getJobPrompt,
  getJobScheduleDisplay,
  getJobState,
  getJobTitle,
  getModelDisplay,
  getRepeatDisplay,
  profileLabel,
  truncateText,
} from "./job-utils";

const META_SEPARATOR = (
  <span aria-hidden="true" className="text-border">
    &#183;
  </span>
);

export interface CronJobRowProps {
  job: CronJob;
  scheduleStrings: ScheduleDescribeStrings;
  /**
   * C10: true only when actually-loaded run data shows the newest run
   * `is_active` — never inferred from `last_run_at` alone. Supersedes the
   * scheduling chip with a live badge until the run ends.
   */
  runningNow: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
  onPauseResume: () => void;
  onTrigger: () => void;
  onEdit: () => void;
  onDelete: () => void;
  /** Run-history drawer body (C6), rendered when `expanded`. */
  children?: ReactNode;
}

/**
 * C4 — cron job card restructured to the run-ledger "agent row" grammar:
 * title + `AgentStatusBadge` + last-outcome chip, mono meta line with the
 * `NextRunCountdown` centerpiece (C5) and `RelativeTime` (C9), trimmed
 * chip row, preserved prompt/error lines, unchanged trailing actions,
 * and an expand gesture opening the run-history drawer (C6).
 */
export function CronJobRow({
  job,
  scheduleStrings,
  runningNow,
  expanded,
  onToggleExpanded,
  onPauseResume,
  onTrigger,
  onEdit,
  onDelete,
  children,
}: CronJobRowProps) {
  const { t } = useI18n();

  const state = getJobState(job);
  const derived = cronJobAgentStatus(job);
  const promptText = getJobPrompt(job);
  const title = getJobTitle(job);
  const hasName = Boolean(getJobName(job));
  const deliver = asText(job.deliver);
  const mode = getJobMode(job);
  const modelDisplay = getModelDisplay(job);
  const rawExpr = asText(job.schedule?.expr);
  const toolsets = Array.isArray(job.enabled_toolsets)
    ? job.enabled_toolsets.filter(Boolean)
    : [];
  const skills = Array.isArray(job.skills) ? job.skills.filter(Boolean) : [];

  return (
    <Card className={cn(runningNow && "border-success/30 bg-success/[0.03]")}>
      <CardContent className="p-0">
        <div
          className="flex cursor-pointer items-start gap-4 px-4 py-4 transition-colors hover:bg-secondary/30"
          onClick={onToggleExpanded}
        >
          <span className="shrink-0 pt-0.5 text-muted-foreground">
            {expanded ? (
              <ChevronDown aria-hidden="true" className="h-4 w-4" />
            ) : (
              <ChevronRight aria-hidden="true" className="h-4 w-4" />
            )}
          </span>

          <div className="min-w-0 flex-1">
            {/* Line 1: title · status · last-outcome chip */}
            <div className="mb-1 flex min-w-0 flex-wrap items-center gap-2">
              <span className="truncate text-sm font-medium">{title}</span>
              {runningNow ? (
                <AgentStatusBadge status="live" />
              ) : (
                <AgentStatusBadge status={derived.status} label={derived.label} />
              )}
              {job.last_status && (
                <Badge
                  tone={job.last_status === "error" ? "destructive" : "success"}
                  className="text-xs"
                  title={job.last_error ?? job.last_run_at ?? undefined}
                >
                  {job.last_status}
                </Badge>
              )}
            </div>

            {/* Line 2: mono meta — schedule (human text, raw expr in title) ·
                next countdown · last relative · repeat */}
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
              <span title={rawExpr || undefined}>
                {getJobScheduleDisplay(job, scheduleStrings)}
              </span>
              {META_SEPARATOR}
              <span>
                {t.cron.next.toLowerCase()}:{" "}
                <NextRunCountdown nextRunAt={job.next_run_at} />
              </span>
              {META_SEPARATOR}
              <span>
                {t.cron.last.toLowerCase()}:{" "}
                <RelativeTime value={job.last_run_at} />
              </span>
              {META_SEPARATOR}
              <span className="font-mono-ui tabular-nums">
                repeat: {getRepeatDisplay(job)}
              </span>
            </div>

            {/* Line 3: trimmed outline chips */}
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <Badge tone="outline">{profileLabel(getJobProfile(job))}</Badge>
              {deliver && deliver !== "local" && (
                <Badge tone="outline">{deliver}</Badge>
              )}
              {skills.length > 0 && (
                <Badge tone="outline" title={skills.join(", ")}>
                  {skills.length === 1 ? skills[0] : `${skills.length} skills`}
                </Badge>
              )}
              {mode !== "agent" && <Badge tone="outline">{mode}</Badge>}
              {modelDisplay && (
                <Badge tone="outline" title={modelDisplay}>
                  <span className="font-mono-ui max-w-[14rem] truncate">
                    {modelDisplay}
                  </span>
                </Badge>
              )}
              {toolsets.length > 0 && (
                <Badge tone="outline" title={toolsets.join(", ")}>
                  {toolsets.length} toolsets
                </Badge>
              )}
            </div>

            {hasName && promptText && (
              <p className="mt-1.5 truncate text-xs text-muted-foreground">
                {truncateText(promptText, 100)}
              </p>
            )}
            {job.last_delivery_error && (
              <p className="mt-1 text-xs text-destructive">
                delivery: {job.last_delivery_error}
              </p>
            )}
            {job.last_error && (
              <p
                className="mt-1 line-clamp-2 text-xs text-destructive"
                title={job.last_error}
              >
                {job.last_error}
              </p>
            )}
          </div>

          <div
            className="flex shrink-0 items-center gap-1"
            // Actions live inside the expand-gesture area; a stray click on
            // the cluster's padding must not toggle the drawer.
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              ghost
              size="icon"
              title={state === "paused" ? t.cron.resume : t.cron.pause}
              aria-label={state === "paused" ? t.cron.resume : t.cron.pause}
              onClick={onPauseResume}
              className={state === "paused" ? "text-success" : "text-warning"}
            >
              {state === "paused" ? <Play /> : <Pause />}
            </Button>

            <Button
              ghost
              size="icon"
              title={t.cron.triggerNow}
              aria-label={t.cron.triggerNow}
              onClick={onTrigger}
            >
              <Zap />
            </Button>

            <Button
              ghost
              size="icon"
              title="Edit job"
              aria-label="Edit job"
              onClick={onEdit}
            >
              <Pencil />
            </Button>

            <Button
              ghost
              destructive
              size="icon"
              title={t.common.delete}
              aria-label={t.common.delete}
              onClick={onDelete}
            >
              <Trash2 />
            </Button>
          </div>
        </div>

        {expanded && children != null && (
          <div className="border-t border-border">{children}</div>
        )}
      </CardContent>
    </Card>
  );
}
