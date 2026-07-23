/**
 * Client-side preference for the Social Studio surface.
 *
 * Social Studio is a Workspace tool that turns a conversation into ready-to-post
 * social content (LinkedIn first). It ships **off by default** and is revealed
 * once the user opts in — the sidebar entry appears, and the Workspace Home card
 * flips from "enable" to "open". This mirrors the established UI-preference
 * pattern in the dashboard (sidebar-collapse, language) rather than a
 * server-side `config.yaml` flag: it is a per-browser display choice, not agent
 * behaviour, so it lives in `localStorage` and needs no backend round-trip.
 *
 * The store is a tiny external store so `useSyncExternalStore` consumers (the
 * app shell that builds the sidebar, the Home card, the page header) all
 * re-render the moment the preference flips — including across browser tabs via
 * the native `storage` event.
 */

export const SOCIAL_STUDIO_ENABLED_KEY = "fabric.social-studio.enabled";

type Listener = () => void;

const listeners = new Set<Listener>();

// Cached snapshot so `getSnapshot` is stable between notifications and reads
// don't hit `localStorage` on every render. `null` means "not yet read".
let cached: boolean | null = null;

function readStored(): boolean {
  try {
    return localStorage.getItem(SOCIAL_STUDIO_ENABLED_KEY) === "true";
  } catch {
    // localStorage can throw in private-browsing / sandboxed contexts.
    return false;
  }
}

function notify(): void {
  for (const listener of listeners) listener();
}

/** Current preference. Reads storage once, then serves the cached snapshot. */
export function isSocialStudioEnabled(): boolean {
  if (cached === null) cached = readStored();
  return cached;
}

/** Persist the preference and notify every subscriber (this tab). */
export function setSocialStudioEnabled(enabled: boolean): void {
  cached = enabled;
  try {
    localStorage.setItem(SOCIAL_STUDIO_ENABLED_KEY, String(enabled));
  } catch {
    // Ignore persistence failures — the in-memory snapshot still updates so
    // the current session reflects the choice.
  }
  notify();
}

let storageBound = false;

/** Subscribe to preference changes; returns an unsubscribe function. */
export function subscribeSocialStudio(listener: Listener): () => void {
  listeners.add(listener);

  // Bind the cross-tab `storage` listener lazily on first subscription so the
  // module has no side effects at import time (SSR / test friendliness).
  if (!storageBound && typeof window !== "undefined") {
    storageBound = true;
    window.addEventListener("storage", (event) => {
      if (event.key !== null && event.key !== SOCIAL_STUDIO_ENABLED_KEY) return;
      cached = readStored();
      notify();
    });
  }

  return () => {
    listeners.delete(listener);
  };
}

/** Test-only: reset the cached snapshot so the next read re-hits storage. */
export function resetSocialStudioCache(): void {
  cached = null;
}
