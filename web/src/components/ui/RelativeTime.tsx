import { cn, timeAgo } from "@/lib/utils";
import { normalizeEpochSeconds, useNowMs } from "./time";

export interface RelativeTimeProps {
  /** Epoch seconds (sessions dialect) OR ISO string (cron dialect). */
  value: number | string | null | undefined;
  className?: string;
}

const MONO_CN = "font-mono-ui tabular-nums";

/**
 * Relative timestamp ("4m ago") via the existing `timeAgo()` util, with
 * the absolute `toLocaleString()` in `title`. Normalizes both backend
 * timestamp dialects through `normalizeEpochSeconds` (R3) and re-renders
 * on the shared 30 s ticker (one module-level interval, not one per
 * instance). Nullish/unparseable values render an em dash.
 */
export function RelativeTime({ value, className }: RelativeTimeProps) {
  // Subscribing is what re-renders us each tick; timeAgo reads the clock.
  useNowMs();
  const seconds = normalizeEpochSeconds(value);
  if (seconds === null) {
    return <span className={cn(MONO_CN, className)}>—</span>;
  }
  const date = new Date(seconds * 1000);
  return (
    <time
      dateTime={date.toISOString()}
      title={date.toLocaleString()}
      className={cn(MONO_CN, className)}
    >
      {timeAgo(seconds)}
    </time>
  );
}
