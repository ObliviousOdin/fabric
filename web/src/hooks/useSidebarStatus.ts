import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { StatusResponse } from "@/lib/api";

const POLL_MS = 10_000;

/**
 * Light-weight status poll for the app shell (sidebar). The Status page uses
 * its own faster interval; we keep this slower to avoid duplicate load.
 */
export function useSidebarStatus(profile: string) {
  const [result, setResult] = useState<{
    profile: string;
    status: StatusResponse;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const clearTimer = () => {
      if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
      }
    };

    const schedule = () => {
      clearTimer();
      if (
        cancelled ||
        (typeof document !== "undefined" && document.visibilityState === "hidden")
      ) {
        return;
      }
      timer = setTimeout(load, POLL_MS);
    };

    const load = () => {
      if (
        cancelled ||
        (typeof document !== "undefined" && document.visibilityState === "hidden")
      ) {
        schedule();
        return;
      }
      // Schedule only after this request settles so a slow backend can never
      // accumulate overlapping shell polls.
      void api
        .getStatus()
        .then((next) => {
          if (!cancelled) setResult({ profile, status: next });
        })
        .catch(() => {})
        .finally(schedule);
    };

    const handleVisibilityChange = () => {
      clearTimer();
      if (document.visibilityState === "visible") load();
    };

    load();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      cancelled = true;
      clearTimer();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [profile]);

  return result?.profile === profile ? result.status : null;
}
