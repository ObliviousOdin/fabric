import { useEffect, useState } from "react";

export type ChatViewportMode = "compact" | "medium" | "wide";

export const CHAT_MEDIUM_MIN_WIDTH = 1024;
export const CHAT_WIDE_MIN_WIDTH = 1440;

export function chatViewportModeForWidth(width: number): ChatViewportMode {
  if (width >= CHAT_WIDE_MIN_WIDTH) return "wide";
  if (width >= CHAT_MEDIUM_MIN_WIDTH) return "medium";
  return "compact";
}

function currentViewportMode(): ChatViewportMode {
  if (typeof window === "undefined") return "wide";
  if (window.matchMedia(`(min-width: ${CHAT_WIDE_MIN_WIDTH}px)`).matches) {
    return "wide";
  }
  if (window.matchMedia(`(min-width: ${CHAT_MEDIUM_MIN_WIDTH}px)`).matches) {
    return "medium";
  }
  return "compact";
}

/**
 * JS viewport mode intentionally mirrors the layout breakpoints. Chat rails
 * contain data-fetching components, so CSS-only hiding would leave duplicate
 * trees connected and fetching off-screen.
 */
export function useChatViewportMode(): ChatViewportMode {
  const [mode, setMode] = useState<ChatViewportMode>(currentViewportMode);

  useEffect(() => {
    const medium = window.matchMedia(`(min-width: ${CHAT_MEDIUM_MIN_WIDTH}px)`);
    const wide = window.matchMedia(`(min-width: ${CHAT_WIDE_MIN_WIDTH}px)`);
    const sync = () => setMode(currentViewportMode());

    medium.addEventListener("change", sync);
    wide.addEventListener("change", sync);
    return () => {
      medium.removeEventListener("change", sync);
      wide.removeEventListener("change", sync);
    };
  }, []);

  return mode;
}
