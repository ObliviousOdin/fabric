import { Stats } from "@nous-research/ui/ui/components/stats";
import type { CronJob } from "@/lib/api";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import { NextRunCountdown, useNowMs } from "@/components/ui";
import { summarizeCronJobs } from "./job-utils";

/**
 * C2 — jobs-view summary strip on the DS `Stats` primitive (G8): `jobs` ·
 * `next run` (soonest future `next_run_at` as a live countdown; `—` when
 * none) · `paused` (warning tone when >0) · `failing` (destructive tone
 * when >0). All computed client-side from the already-fetched jobs array.
 */
export function CronSummaryStrip({ jobs }: { jobs: CronJob[] }) {
  const { t } = useI18n();
  // Shared 30 s ticker: "soonest future run" is time-dependent — once the
  // soonest run fires, the strip must advance to the next candidate.
  const nowMs = useNowMs();
  const summary = summarizeCronJobs(jobs, nowMs);

  const count = (value: number, tone?: string) => ({
    key: String(value),
    node: (
      <span
        className={cn(
          "font-mono-ui tabular-nums",
          tone && value > 0 ? tone : undefined,
        )}
      >
        {value}
      </span>
    ),
  });

  return (
    <Stats
      items={[
        {
          label: t.cron.agents?.statJobs ?? "jobs",
          value: count(summary.total),
        },
        {
          label: t.cron.agents?.statNextRun ?? "next run",
          value: {
            key: summary.nextRunAt ?? "none",
            node: <NextRunCountdown nextRunAt={summary.nextRunAt} />,
          },
        },
        {
          label: t.cron.agents?.statPaused ?? "paused",
          value: count(summary.paused, "text-warning"),
        },
        {
          label: t.cron.agents?.statFailing ?? "failing",
          value: count(summary.failing, "text-destructive"),
        },
      ]}
    />
  );
}
