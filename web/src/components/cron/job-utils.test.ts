import { describe, expect, it } from "vitest";

import type { CronJob } from "@/lib/api";
import {
  formatCompactCount,
  formatRunDuration,
  getJobKey,
  splitJobKey,
  summarizeCronJobs,
} from "@/components/cron/job-utils";

const NOW_MS = Date.parse("2026-07-13T12:00:00Z");

function job(overrides: Partial<CronJob>): CronJob {
  return { id: "job", enabled: true, state: "scheduled", ...overrides };
}

describe("summarizeCronJobs (C2)", () => {
  it("counts paused as state=paused OR enabled=false, failing as state/last_status error", () => {
    const summary = summarizeCronJobs(
      [
        job({ id: "a" }),
        job({ id: "b", state: "paused" }),
        job({ id: "c", enabled: false }),
        job({ id: "d", state: "error" }),
        job({ id: "e", last_status: "error" }),
      ],
      NOW_MS,
    );
    expect(summary.total).toBe(5);
    expect(summary.paused).toBe(2);
    expect(summary.failing).toBe(2);
  });

  it("picks the soonest strictly-future next_run_at, ignoring past-due timestamps", () => {
    const soon = "2026-07-13T12:05:00Z";
    const later = "2026-07-13T14:00:00Z";
    const past = "2026-07-13T11:00:00Z";
    const summary = summarizeCronJobs(
      [
        job({ id: "a", next_run_at: later }),
        job({ id: "b", next_run_at: past }),
        job({ id: "c", next_run_at: soon }),
        job({ id: "d", next_run_at: null }),
      ],
      NOW_MS,
    );
    expect(summary.nextRunAt).toBe(soon);
  });

  it("ignores next_run_at on jobs that will never fire (paused/disabled/completed)", () => {
    const soon = "2026-07-13T12:05:00Z";
    const later = "2026-07-13T14:00:00Z";
    const summary = summarizeCronJobs(
      [
        // pause_job keeps the stale next_run_at — it must not win the stat.
        job({ id: "a", state: "paused", next_run_at: soon }),
        job({ id: "b", enabled: false, next_run_at: soon }),
        job({ id: "c", state: "completed", next_run_at: soon }),
        job({ id: "d", next_run_at: later }),
      ],
      NOW_MS,
    );
    expect(summary.nextRunAt).toBe(later);
  });

  it("returns null next run when nothing is scheduled in the future", () => {
    expect(
      summarizeCronJobs([job({ id: "a", next_run_at: null })], NOW_MS)
        .nextRunAt,
    ).toBeNull();
    expect(summarizeCronJobs([], NOW_MS).nextRunAt).toBeNull();
  });
});

describe("formatRunDuration (C6)", () => {
  it("formats seconds / minutes / hours tiers", () => {
    const start = 1_700_000_000; // realistic epoch seconds (0 is rejected)
    expect(formatRunDuration(start, start + 42)).toBe("42s");
    expect(formatRunDuration(start, start + 102)).toBe("1m 42s");
    expect(formatRunDuration(start, start + 3_720)).toBe("1h 02m");
  });

  it("is null for open or nonsense runs (R4 — no placeholder noise)", () => {
    expect(formatRunDuration(100, null)).toBeNull();
    expect(formatRunDuration(null, 100)).toBeNull();
    expect(formatRunDuration(200, 100)).toBeNull();
  });
});

describe("formatCompactCount", () => {
  it("keeps small counts verbatim and compacts k/M", () => {
    expect(formatCompactCount(842)).toBe("842");
    expect(formatCompactCount(12_400)).toBe("12.4k");
    expect(formatCompactCount(1_000)).toBe("1k");
    expect(formatCompactCount(250_000)).toBe("250k");
    expect(formatCompactCount(1_200_000)).toBe("1.2M");
  });
});

describe("job keys", () => {
  it("round-trips profile:id through getJobKey/splitJobKey", () => {
    const j = job({ id: "daily_report", profile: "work" });
    const key = getJobKey(j);
    expect(key).toBe("work:daily_report");
    expect(splitJobKey(key)).toEqual({ profile: "work", id: "daily_report" });
    expect(splitJobKey("naked-id")).toEqual({
      profile: "default",
      id: "naked-id",
    });
  });
});
