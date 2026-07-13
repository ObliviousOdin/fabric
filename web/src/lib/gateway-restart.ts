/**
 * Pure gateway-restart outcome logic (CN3) — the single implementation of
 * the restart watcher that was previously copy-pasted across WebhooksPage
 * and the Telegram/WhatsApp onboarding panels in ChannelsPage. React state
 * plumbing lives in `hooks/useGatewayRestart.ts`; this module stays
 * dependency-injectable so the outcome classification is unit-testable
 * (R25 — the exit-code semantics here are the top regression risk of the
 * extraction).
 */

/** The spawned action name `POST /api/gateway/restart` reports under. */
export const GATEWAY_RESTART_ACTION = "gateway-restart";

/** Poll cadence of the shipped watcher: up to 20 polls, 1.5 s apart (≤30 s). */
export const RESTART_WATCH_ATTEMPTS = 20;
export const RESTART_WATCH_INTERVAL_MS = 1500;

/** Shipped "give the gateway a moment to come up" delay before reloading. */
export const RESTART_RELOAD_DELAY_MS = 4000;

/** How the restart attempt ended, as far as the dashboard can tell. */
export type GatewayRestartOutcome =
  /** A settled poll reported exit 0 — or exit null, which counts as success. */
  | { kind: "success" }
  /** The `fabric gateway restart` child exited non-zero. */
  | { kind: "failed"; exitCode: number }
  /**
   * The watch window closed without a settled poll (still running, or the
   * dashboard never reached the server). NOT a failure — in no-service
   * installs the child never exits (see `watchGatewayRestartOutcome`).
   * Shipped behavior on this path was "stop saying 'restarting…', change
   * nothing else", which differs from `success` only in that it does not
   * clear a previously raised `restartNeeded`/`restartError`.
   */
  | { kind: "window-closed" };

export interface RestartActionStatus {
  running: boolean;
  exit_code: number | null;
}

/**
 * Classify one `GET /api/actions/gateway-restart/status` poll.
 *
 * `exit_code === null` on a settled action counts as SUCCESS, exactly like
 * `0` — never treat it as a failure (R25). See `watchGatewayRestartOutcome`
 * for why.
 */
export function classifyRestartPoll(
  st: RestartActionStatus,
): "pending" | "success" | "failed" {
  if (st.running) return "pending";
  if (st.exit_code !== 0 && st.exit_code !== null) return "failed";
  return "success";
}

/**
 * The exact shipped watch algorithm, centralized: poll the action status up
 * to `attempts` times, `intervalMs` apart (sleep first, then poll — the
 * child needs a moment to exist at all).
 *
 * restart_started only means the `fabric gateway restart` child spawned —
 * not that the restart will succeed (e.g. systemd linger missing, service
 * manager failure). Poll the action status briefly and surface a non-zero
 * exit via the manual-restart banner. Note: in no-service installs the
 * child becomes the foreground gateway and never exits, so "still running
 * when the window closes" counts as success.
 *
 * Transient fetch errors keep polling (the dashboard may briefly lose its
 * connection while the gateway restarts); a window that closes without a
 * settled poll resolves as success per the comment above.
 */
export async function watchGatewayRestartOutcome({
  getStatus,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  attempts = RESTART_WATCH_ATTEMPTS,
  intervalMs = RESTART_WATCH_INTERVAL_MS,
}: {
  getStatus: () => Promise<RestartActionStatus>;
  sleep?: (ms: number) => Promise<void>;
  attempts?: number;
  intervalMs?: number;
}): Promise<GatewayRestartOutcome> {
  for (let i = 0; i < attempts; i++) {
    await sleep(intervalMs);
    try {
      const st = await getStatus();
      const verdict = classifyRestartPoll(st);
      if (verdict === "pending") continue;
      if (verdict === "failed") {
        // classifyRestartPoll only says "failed" for settled non-zero,
        // non-null exit codes, so the cast below is safe.
        return { kind: "failed", exitCode: st.exit_code as number };
      }
      return { kind: "success" };
    } catch {
      // transient fetch error; keep polling
    }
  }
  return { kind: "window-closed" };
}
