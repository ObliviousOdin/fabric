import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import {
  GATEWAY_RESTART_ACTION,
  RESTART_RELOAD_DELAY_MS,
  watchGatewayRestartOutcome,
} from "@/lib/gateway-restart";

export interface UseGatewayRestartOptions {
  /**
   * Page data reload, invoked once ~4 s after any restart is kicked off
   * ("give the gateway a moment to come up, then refresh status" — the
   * shipped delay, `RESTART_RELOAD_DELAY_MS`).
   */
  reload?: () => void | Promise<unknown>;
  /** Toast sink — pages pass their `useToast().showToast`. */
  showToast?: (message: string, type: "success" | "error") => void;
}

export interface GatewayRestartControls {
  /** A saved change (or failed restart) needs a manual gateway restart. */
  restartNeeded: boolean;
  /** `restart()` is in flight (the POST itself, not the watch window). */
  restarting: boolean;
  /** Informational "…restarting…" line while a restart is being watched. */
  restartMessage: string | null;
  /** Why the last restart failed, when known. */
  restartError: string | null;
  /** Full manual-restart flow: POST, toast, delayed reload, outcome watch. */
  restart: () => Promise<void>;
  /** Watch an already-spawned `gateway-restart` action to its outcome. */
  watchOutcome: () => Promise<void>;
  /** Flag that saved changes need a restart (optionally with an error). */
  markRestartNeeded: (error?: string | null) => void;
  /** Clear the needed/error flags (e.g. before an auto-restarting call). */
  clearRestartNeeded: () => void;
  /**
   * A server response reported it already spawned the restart
   * (`restart_started` on webhook enable / onboarding apply): show the
   * message, schedule the delayed reload, and watch the outcome.
   */
  noteRestartStarted: (message?: string | null) => void;
}

/**
 * One gateway-restart lifecycle, not four (CN3): owns the
 * `restartNeeded / restarting / restartMessage / restartError` state that
 * WebhooksPage, ChannelsPage and the Telegram/WhatsApp onboarding panels
 * each hand-rolled, plus the exact shipped outcome-watch algorithm
 * (`lib/gateway-restart.ts` — poll `gateway-restart` up to 20 × 1.5 s;
 * non-zero exit → failure toast + `restartNeeded`; **exit `null` counts as
 * success**, R25).
 *
 * Outcome handling is the union of the shipped copies — each page's
 * observable behavior is preserved:
 * - failure: clear the "restarting…" message, raise `restartNeeded`, set
 *   `restartError` ("Gateway restart failed with exit N."), toast
 *   "restart manually" (all four copies toasted; only WebhooksPage kept
 *   the error string, the others had no error display).
 * - success: clear message/needed/error (WebhooksPage semantics; a no-op
 *   for the panels, which cleared `restartNeeded` before watching).
 * - window closed without a settled poll: clear the message only —
 *   never raise the banner (no-service installs, R25).
 */
export function useGatewayRestart(
  options: UseGatewayRestartOptions = {},
): GatewayRestartControls {
  const [restartNeeded, setRestartNeeded] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [restartMessage, setRestartMessage] = useState<string | null>(null);
  const [restartError, setRestartError] = useState<string | null>(null);

  // Latest-options ref so the returned callbacks stay referentially stable
  // even when callers pass inline `reload`/`showToast` closures.
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const scheduleReload = useCallback(() => {
    window.setTimeout(() => {
      void optionsRef.current.reload?.();
    }, RESTART_RELOAD_DELAY_MS);
  }, []);

  const watchOutcome = useCallback(async () => {
    const outcome = await watchGatewayRestartOutcome({
      getStatus: () => api.getActionStatus(GATEWAY_RESTART_ACTION, 5),
    });
    if (outcome.kind === "failed") {
      setRestartMessage(null);
      setRestartNeeded(true);
      setRestartError(`Gateway restart failed with exit ${outcome.exitCode}.`);
      optionsRef.current.showToast?.(
        `Gateway restart failed (exit ${outcome.exitCode}) — restart manually`,
        "error",
      );
      return;
    }
    if (outcome.kind === "success") {
      setRestartMessage(null);
      setRestartNeeded(false);
      setRestartError(null);
      return;
    }
    // window-closed: still running (or unreachable) when the watch window
    // ended — counts as success, but only the transient message clears.
    setRestartMessage(null);
  }, []);

  const markRestartNeeded = useCallback((error?: string | null) => {
    setRestartMessage(null);
    setRestartNeeded(true);
    setRestartError(error ?? null);
  }, []);

  const clearRestartNeeded = useCallback(() => {
    setRestartNeeded(false);
    setRestartError(null);
  }, []);

  const noteRestartStarted = useCallback(
    (message?: string | null) => {
      setRestartNeeded(false);
      setRestartError(null);
      setRestartMessage(message ?? null);
      scheduleReload();
      void watchOutcome();
    },
    [scheduleReload, watchOutcome],
  );

  const restart = useCallback(async () => {
    setRestarting(true);
    try {
      await api.restartGateway();
      optionsRef.current.showToast?.("Gateway restarting…", "success");
      noteRestartStarted("Gateway restarting…");
    } catch (e) {
      markRestartNeeded(String(e));
      optionsRef.current.showToast?.(`Failed to restart: ${e}`, "error");
    } finally {
      setRestarting(false);
    }
  }, [markRestartNeeded, noteRestartStarted]);

  return {
    restartNeeded,
    restarting,
    restartMessage,
    restartError,
    restart,
    watchOutcome,
    markRestartNeeded,
    clearRestartNeeded,
    noteRestartStarted,
  };
}
