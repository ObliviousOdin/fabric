import { useSyncExternalStore } from "react";

/**
 * Time infrastructure for `RelativeTime` / `NextRunCountdown`: the shared
 * re-render ticker, the epoch-vs-ISO normalization both dialects funnel
 * through (R3), and the pure countdown formatter. Component-free module so
 * fast refresh keeps working and the logic stays unit-testable.
 */

// ── Shared ticker ─────────────────────────────────────────────────────
// One module-level interval per cadence, not one interval per mounted
// instance: a Sessions ledger renders dozens of RelativeTimes and a
// per-instance interval would wake the tab dozens of times per tick.
// The fast (1 s) cadence exists for NextRunCountdown's final two minutes;
// each timer runs only while it has subscribers.

type TickListener = () => void;

const SLOW_TICK_MS = 30_000;
const FAST_TICK_MS = 1_000;

const slowListeners = new Set<TickListener>();
const fastListeners = new Set<TickListener>();
let slowTimer: ReturnType<typeof setInterval> | null = null;
let fastTimer: ReturnType<typeof setInterval> | null = null;

// Snapshot for useSyncExternalStore: advances only on tick/subscribe so
// renders read a stable value (calling Date.now() during render violates
// the react-hooks purity contract and can loop useSyncExternalStore).
let cachedNowMs = Date.now();

function notify(listeners: Set<TickListener>): void {
  cachedNowMs = Date.now();
  // Copy first: a listener re-render may (un)subscribe during iteration.
  for (const listener of [...listeners]) listener();
}

function syncTimers(): void {
  if (slowListeners.size > 0 && slowTimer === null) {
    slowTimer = setInterval(() => notify(slowListeners), SLOW_TICK_MS);
  } else if (slowListeners.size === 0 && slowTimer !== null) {
    clearInterval(slowTimer);
    slowTimer = null;
  }
  if (fastListeners.size > 0 && fastTimer === null) {
    fastTimer = setInterval(() => notify(fastListeners), FAST_TICK_MS);
  } else if (fastListeners.size === 0 && fastTimer !== null) {
    clearInterval(fastTimer);
    fastTimer = null;
  }
}

/** Subscribe to the shared 30 s ticker (or the 1 s tier with `fast`). */
export function subscribeSharedTick(
  listener: TickListener,
  fast = false,
): () => void {
  // Refresh the snapshot at subscribe time so a component mounting long
  // after the last tick doesn't render a stale "now". React re-checks the
  // snapshot right after subscribing and re-renders on change.
  cachedNowMs = Date.now();
  const listeners = fast ? fastListeners : slowListeners;
  listeners.add(listener);
  syncTimers();
  return () => {
    listeners.delete(listener);
    syncTimers();
  };
}

// Stable subscribe identities per cadence (useSyncExternalStore
// resubscribes whenever the subscribe function identity changes).
const subscribeSlow = (listener: TickListener) =>
  subscribeSharedTick(listener, false);
const subscribeFast = (listener: TickListener) =>
  subscribeSharedTick(listener, true);

function getNowMs(): number {
  return cachedNowMs;
}

/**
 * Current epoch ms, updated on the shared ticker — the render-safe way for
 * time-displaying components to both re-render on tick and read "now".
 */
export function useNowMs(fast = false): number {
  return useSyncExternalStore(fast ? subscribeFast : subscribeSlow, getNowMs);
}

// ── Timestamp-dialect normalization ───────────────────────────────────

/**
 * Normalize the two backend timestamp dialects to epoch seconds: sessions
 * serve epoch-seconds floats, cron serves ISO strings (R3 — every render
 * path must go through here so the off-by-1000 class of bug has one home).
 * Millisecond-magnitude numbers (and numeric strings) are down-converted;
 * unparseable input returns null.
 */
export function normalizeEpochSeconds(
  value: number | string | null | undefined,
): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value <= 0) return null;
    // Epoch seconds put "now" near 1.7e9; anything past 1e12 is epoch ms.
    return value > 1e12 ? value / 1000 : value;
  }
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (/^\d+(\.\d+)?$/.test(trimmed)) {
    return normalizeEpochSeconds(Number(trimmed));
  }
  const ms = Date.parse(trimmed);
  return Number.isNaN(ms) ? null : ms / 1000;
}

// ── Countdown formatting ──────────────────────────────────────────────

/** Below this remaining window the countdown ticks at 1 s (G5). */
export const FAST_TICK_WINDOW_MS = 2 * 60_000;

/**
 * Format a remaining-time delta as a compact mono countdown:
 * `in 2d 4h` / `in 2h 14m` / `in 14m` / `in 1m 30s` / `in 45s`.
 * Seconds only show inside the final two minutes — the shared ticker only
 * runs at 1 s resolution there, so coarser windows never display a stale
 * seconds digit. Negative deltas render `overdue` (C5).
 */
export function formatCountdown(remainingMs: number): string {
  if (remainingMs < 0) return "overdue";
  const totalSeconds = Math.floor(remainingMs / 1000);
  if (totalSeconds < 60) return `in ${totalSeconds}s`;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalSeconds < 120) return `in ${totalMinutes}m ${totalSeconds % 60}s`;
  if (totalMinutes < 60) return `in ${totalMinutes}m`;
  const totalHours = Math.floor(totalMinutes / 60);
  if (totalHours < 24) return `in ${totalHours}h ${totalMinutes % 60}m`;
  return `in ${Math.floor(totalHours / 24)}d ${totalHours % 24}h`;
}
