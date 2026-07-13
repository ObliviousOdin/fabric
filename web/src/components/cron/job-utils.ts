import type { CronJob } from "@/lib/api";
import {
  describeSchedule,
  type ScheduleDescribeStrings,
} from "@/lib/schedule";
import { normalizeEpochSeconds } from "@/components/ui";

/**
 * Pure cron-job display helpers shared by `CronPage` and the extracted
 * `components/cron/*` row/drawer components. Moved out of the page
 * monolith verbatim (behavior-preserving) plus the C2/C6 derivations
 * (summary-strip rollup, run duration, compact counters).
 */

export function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function truncateText(value: string, maxLength: number): string {
  return value.length > maxLength ? value.slice(0, maxLength) + "..." : value;
}

export function getJobPrompt(job: CronJob): string {
  return asText(job.prompt);
}

export function getJobName(job: CronJob): string {
  return asText(job.name).trim();
}

export function getJobTitle(job: CronJob): string {
  const name = getJobName(job);
  if (name) return name;

  const prompt = getJobPrompt(job);
  if (prompt) return truncateText(prompt, 60);

  const script = asText(job.script);
  if (script) return truncateText(script, 60);

  return job.id || "Cron job";
}

export function getJobScheduleDisplay(
  job: CronJob,
  strings: ScheduleDescribeStrings,
): string {
  // Prefer a structured render so cron expressions like
  // ``30 14 * * 1,3,5`` surface as "Weekly on Mon, Wed, Fri at 14:30"
  // in the list instead of the raw five-field gibberish. Falls back
  // through the existing chain (``schedule_display`` from the backend,
  // then the structured ``display`` field, then the raw ``expr``) so
  // legacy job rows still render *something* meaningful.
  return describeSchedule(
    job.schedule,
    asText(job.schedule_display) || asText(job.schedule?.display),
    strings,
  );
}

export function getJobState(job: CronJob): string {
  return asText(job.state) || (job.enabled === false ? "disabled" : "scheduled");
}

export function getRepeatDisplay(job: CronJob): string {
  const repeat = job.repeat;
  if (!repeat || repeat.times == null) return "forever";
  const completed = repeat.completed ?? 0;
  return completed > 0 ? `${completed}/${repeat.times}` : `${repeat.times} times`;
}

export function getJobMode(job: CronJob): string {
  if (job.no_agent) return "no_agent";
  if (job.script) return "script+agent";
  return "agent";
}

export function getModelDisplay(job: CronJob): string {
  const provider = asText(job.provider);
  const model = asText(job.model);
  if (provider && model) return `${provider}/${model}`;
  return model || provider;
}

export function getJobProfile(job: CronJob): string {
  return asText(job.profile) || asText(job.profile_name) || "default";
}

export function getJobKey(job: CronJob): string {
  return `${getJobProfile(job)}:${job.id}`;
}

export function splitJobKey(key: string): { profile: string; id: string } {
  const idx = key.indexOf(":");
  if (idx === -1) return { profile: "default", id: key };
  return { profile: key.slice(0, idx) || "default", id: key.slice(idx + 1) };
}

export function profileLabel(profile: string): string {
  return profile === "default" ? "default" : profile;
}

// ── C2 — summary-strip rollup (client-side, from the fetched jobs) ─────

export interface CronJobsSummary {
  total: number;
  /** Soonest strictly-future `next_run_at` ISO across jobs; null when none. */
  nextRunAt: string | null;
  /** `state === "paused"` OR `enabled === false`. */
  paused: number;
  /** `state === "error"` OR `last_status === "error"`. */
  failing: number;
}

export function summarizeCronJobs(
  jobs: CronJob[],
  nowMs = Date.now(),
): CronJobsSummary {
  let nextRunAt: string | null = null;
  let nextRunSeconds = Infinity;
  let paused = 0;
  let failing = 0;
  for (const job of jobs) {
    const isPaused = job.state === "paused" || job.enabled === false;
    if (isPaused) paused += 1;
    if (job.state === "error" || job.last_status === "error") failing += 1;
    // Paused/disabled/completed jobs never fire: the backend keeps a stale
    // `next_run_at` on pause (cron/jobs.py pause_job), so a non-schedulable
    // job must not feed the "next run" stat.
    if (isPaused || job.state === "completed") continue;
    const seconds = normalizeEpochSeconds(job.next_run_at);
    // Only strictly-future runs feed the "next run" stat — a stale past-due
    // timestamp would render "overdue" where the spec wants the soonest
    // upcoming run (C2); per-row past-due still shows via C5.
    if (seconds !== null && seconds * 1000 > nowMs && seconds < nextRunSeconds) {
      nextRunSeconds = seconds;
      nextRunAt = job.next_run_at ?? null;
    }
  }
  return { total: jobs.length, nextRunAt, paused, failing };
}

// ── C6 — run-row derivations ───────────────────────────────────────────

/**
 * Wall-clock duration of a finished run (`ended_at - started_at`, epoch
 * seconds) as compact mono text: `42s` / `1m 42s` / `1h 02m`. Null while
 * the run is still open or on nonsense input — meta segments render
 * conditionally, never placeholder noise (R4).
 */
export function formatRunDuration(
  startedAt: number | null | undefined,
  endedAt: number | null | undefined,
): string | null {
  const start = normalizeEpochSeconds(startedAt);
  const end = normalizeEpochSeconds(endedAt);
  if (start === null || end === null || end < start) return null;
  const totalSeconds = Math.round(end - start);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 60) return `${minutes}m ${totalSeconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** Compact counter for token totals: `842` / `12.4k` / `1.2M` (S2 idiom). */
export function formatCompactCount(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "0";
  if (value < 1000) return String(Math.round(value));
  const scaled = value < 1_000_000 ? value / 1000 : value / 1_000_000;
  const suffix = value < 1_000_000 ? "k" : "M";
  const text = scaled >= 100 ? String(Math.round(scaled)) : scaled.toFixed(1);
  return `${text.replace(/\.0$/, "")}${suffix}`;
}
