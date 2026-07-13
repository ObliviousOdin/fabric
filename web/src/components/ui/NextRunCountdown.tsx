import { cn } from "@/lib/utils";
import {
  FAST_TICK_WINDOW_MS,
  formatCountdown,
  normalizeEpochSeconds,
  useNowMs,
} from "./time";

export interface NextRunCountdownProps {
  /** ISO timestamp of the next run; null/undefined renders an em dash. */
  nextRunAt: string | null | undefined;
  className?: string;
}

/**
 * Live countdown to an ISO timestamp (cron `next_run_at` today, but
 * generic). Ticks on the shared 30 s ticker, dropping to 1 s inside the
 * final two minutes. Past-due renders `overdue` in the warning tone
 * (C5); null/unparseable renders `—`.
 */
export function NextRunCountdown({
  nextRunAt,
  className,
}: NextRunCountdownProps) {
  const targetSeconds = normalizeEpochSeconds(nextRunAt);
  // First pass renders from the slow tier's snapshot; once remaining time
  // is known to be inside the fast window we resubscribe at 1 s. The slow
  // tick crossing the boundary re-renders us and flips the cadence.
  const slowNowMs = useNowMs();
  const slowRemainingMs =
    targetSeconds === null ? null : targetSeconds * 1000 - slowNowMs;
  const fast =
    slowRemainingMs !== null &&
    slowRemainingMs > 0 &&
    slowRemainingMs < FAST_TICK_WINDOW_MS;
  const nowMs = useNowMs(fast);

  if (targetSeconds === null) {
    return (
      <span className={cn("font-mono-ui tabular-nums", className)}>—</span>
    );
  }

  const remainingMs = targetSeconds * 1000 - nowMs;
  return (
    <span
      title={new Date(targetSeconds * 1000).toLocaleString()}
      className={cn(
        "font-mono-ui tabular-nums",
        remainingMs < 0 && "text-warning",
        className,
      )}
    >
      {formatCountdown(remainingMs)}
    </span>
  );
}
