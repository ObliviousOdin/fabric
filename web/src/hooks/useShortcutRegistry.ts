import { useEffect, useRef, useSyncExternalStore } from "react";

/**
 * Global keyboard-shortcut registry.
 *
 * A single module-level `keydown` listener on `window` dispatches to
 * registered shortcuts (attached while at least one registration exists).
 * Components register via `useShortcut`; the live registration list is
 * readable via `useShortcutRegistry` so the shortcuts-help dialog always
 * reflects what is actually bound — nothing is hardcoded there.
 *
 * Dispatch rules:
 * - events with `defaultPrevented`, IME composition, or key auto-repeat are
 *   ignored;
 * - events originating from editable targets (input / textarea / select /
 *   contenteditable) or from inside the embedded terminal
 *   (`.hermes-chat-xterm-host` / `.xterm`) are ignored — the terminal and
 *   form fields own their own keys;
 * - when several registrations match the same combo, the most recently
 *   registered one wins (lets a focused surface shadow a global binding).
 */
export interface ShortcutRegistration {
  /**
   * Key combo such as `"mod+k"`, `"shift+/"`, `"?"` or `"["`.
   * `mod` means ⌘ on macOS and Ctrl elsewhere (either satisfies the match).
   */
  combo: string;
  /** Human-readable description (already translated) for the help dialog. */
  description: string;
  handler: (event: KeyboardEvent) => void;
  /** Group label (already translated) in the help dialog; defaults to the global scope. */
  scope?: string;
}

export interface RegisteredShortcut {
  combo: string;
  description: string;
  id: number;
  scope?: string;
}

interface ParsedCombo {
  alt: boolean;
  ctrl: boolean;
  key: string;
  meta: boolean;
  mod: boolean;
  shift: boolean;
}

function parseCombo(combo: string): ParsedCombo {
  const parts = combo.toLowerCase().split("+");
  const key = parts.pop() ?? "";
  return {
    alt: parts.includes("alt"),
    ctrl: parts.includes("ctrl"),
    key,
    meta: parts.includes("meta") || parts.includes("cmd"),
    mod: parts.includes("mod"),
    shift: parts.includes("shift"),
  };
}

/**
 * Whether a keyboard event satisfies a combo string.
 *
 * The key is compared against `event.key` (lowercased), so shifted
 * punctuation works naturally: registering `"?"` matches the event produced
 * by Shift+/ without declaring shift, while `"["` does not fire for `{`.
 * Combos without a modifier require Ctrl/Meta/Alt to be up, so plain `"["`
 * never swallows browser chords like Cmd+[.
 */
export function matchesCombo(event: KeyboardEvent, combo: string): boolean {
  const parsed = parseCombo(combo);
  if (!parsed.key) return false;
  if (event.key.toLowerCase() !== parsed.key) return false;

  if (parsed.mod) {
    if (!event.metaKey && !event.ctrlKey) return false;
  } else {
    if (event.ctrlKey !== parsed.ctrl) return false;
    if (event.metaKey !== parsed.meta) return false;
  }
  if (event.altKey !== parsed.alt) return false;
  if (parsed.shift && !event.shiftKey) return false;
  // Undeclared Shift is only tolerated for shifted punctuation ("?"), where
  // the event key already encodes the shift state. For letters and named
  // keys ("enter") Shift does not change `event.key`, so it marks a
  // different chord: "mod+k" must not swallow Cmd/Ctrl+Shift+K.
  if (
    !parsed.shift &&
    event.shiftKey &&
    (parsed.key.length > 1 || /^[a-z]$/.test(parsed.key))
  ) {
    return false;
  }
  return true;
}

/** True when the event target is a form field, contenteditable region, or inside the embedded terminal. */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if ((target as HTMLElement).isContentEditable) return true;
  // jsdom does not implement `isContentEditable`; the attribute selector
  // keeps the guard honest there and for plaintext-only regions.
  if (
    target.closest(
      '[contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"]',
    )
  ) {
    return true;
  }
  if (target.closest(".hermes-chat-xterm-host, .xterm")) return true;
  return false;
}

function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const source = `${navigator.platform ?? ""} ${navigator.userAgent ?? ""}`;
  return /mac|iphone|ipad|ipod/i.test(source);
}

const KEY_DISPLAY: Record<string, string> = {
  arrowdown: "↓",
  arrowleft: "←",
  arrowright: "→",
  arrowup: "↑",
  enter: "↵",
  escape: "Esc",
  " ": "Space",
};

/** Render a combo for UI hints: `"mod+k"` → `"⌘K"` on macOS, `"Ctrl+K"` elsewhere. */
export function formatCombo(combo: string): string {
  const mac = isMacPlatform();
  const parsed = parseCombo(combo);
  const parts: string[] = [];
  if (parsed.mod) parts.push(mac ? "⌘" : "Ctrl");
  if (parsed.ctrl) parts.push(mac ? "⌃" : "Ctrl");
  if (parsed.alt) parts.push(mac ? "⌥" : "Alt");
  if (parsed.shift) parts.push(mac ? "⇧" : "Shift");
  if (parsed.meta) parts.push(mac ? "⌘" : "Meta");
  const key =
    KEY_DISPLAY[parsed.key] ??
    (parsed.key.length === 1
      ? parsed.key.toUpperCase()
      : parsed.key.charAt(0).toUpperCase() + parsed.key.slice(1));
  parts.push(key);
  return parts.join(mac ? "" : "+");
}

/* ------------------------------------------------------------------ */
/*  Module-level registry (single window listener)                     */
/* ------------------------------------------------------------------ */

interface StoredShortcut extends RegisteredShortcut {
  handler: (event: KeyboardEvent) => void;
}

const registry = new Map<number, StoredShortcut>();
const registryListeners = new Set<() => void>();
let registryVersion = 0;
let nextId = 0;
let windowListenerAttached = false;

function notifyRegistryChanged() {
  registryVersion += 1;
  for (const listener of registryListeners) listener();
}

function onWindowKeyDown(event: KeyboardEvent) {
  if (event.defaultPrevented) return;
  if (event.isComposing || event.repeat) return;
  if (isEditableTarget(event.target)) return;

  // Most recently registered wins on combo collisions.
  const stored = [...registry.values()];
  for (let i = stored.length - 1; i >= 0; i--) {
    const entry = stored[i];
    if (!matchesCombo(event, entry.combo)) continue;
    event.preventDefault();
    entry.handler(event);
    return;
  }
}

function syncWindowListener() {
  if (typeof window === "undefined") return;
  const shouldAttach = registry.size > 0;
  if (shouldAttach && !windowListenerAttached) {
    window.addEventListener("keydown", onWindowKeyDown);
    windowListenerAttached = true;
  } else if (!shouldAttach && windowListenerAttached) {
    window.removeEventListener("keydown", onWindowKeyDown);
    windowListenerAttached = false;
  }
}

/**
 * Low-level (non-React) registration. Returns the unregister function.
 * Prefer `useShortcut` from components.
 */
export function registerShortcut(registration: ShortcutRegistration): () => void {
  const id = nextId++;
  registry.set(id, { id, ...registration });
  syncWindowListener();
  notifyRegistryChanged();
  return () => {
    registry.delete(id);
    syncWindowListener();
    notifyRegistryChanged();
  };
}

function subscribeToRegistry(listener: () => void): () => void {
  registryListeners.add(listener);
  return () => registryListeners.delete(listener);
}

function getRegistryVersion(): number {
  return registryVersion;
}

/**
 * Register a global shortcut for the lifetime of the component.
 *
 * The handler is kept fresh via a ref so callers can pass inline closures;
 * the registration itself is only churned when combo / description / scope
 * / enabled change (e.g. locale switch), which also refreshes the help
 * dialog. Pass `enabled: false` to unbind without unmounting.
 */
export function useShortcut(
  registration: ShortcutRegistration & { enabled?: boolean },
): void {
  const { combo, description, scope, enabled = true } = registration;
  const handlerRef = useRef(registration.handler);
  useEffect(() => {
    handlerRef.current = registration.handler;
  });
  useEffect(() => {
    if (!enabled) return;
    return registerShortcut({
      combo,
      description,
      handler: (event) => handlerRef.current(event),
      scope,
    });
  }, [combo, description, enabled, scope]);
}

/**
 * Live list of currently registered shortcuts, in registration order.
 * Re-renders subscribers whenever a shortcut is (un)registered.
 */
export function useShortcutRegistry(): RegisteredShortcut[] {
  useSyncExternalStore(
    subscribeToRegistry,
    getRegistryVersion,
    getRegistryVersion,
  );
  return [...registry.values()].map(({ combo, description, id, scope }) => ({
    combo,
    description,
    id,
    scope,
  }));
}
