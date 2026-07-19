// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  formatCombo,
  isEditableTarget,
  matchesCombo,
  registerShortcut,
} from "@/hooks/useShortcutRegistry";

function keydown(init: KeyboardEventInit): KeyboardEvent {
  return new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
}

const disposers: Array<() => void> = [];

function register(
  combo: string,
  handler: (e: KeyboardEvent) => void,
): () => void {
  const dispose = registerShortcut({ combo, description: combo, handler });
  disposers.push(dispose);
  return dispose;
}

afterEach(() => {
  while (disposers.length) disposers.pop()!();
  document.body.innerHTML = "";
});

describe("matchesCombo", () => {
  it("matches mod+k for either ctrl or meta", () => {
    expect(matchesCombo(keydown({ key: "k", ctrlKey: true }), "mod+k")).toBe(true);
    expect(matchesCombo(keydown({ key: "k", metaKey: true }), "mod+k")).toBe(true);
    expect(matchesCombo(keydown({ key: "K", metaKey: true }), "mod+k")).toBe(true);
    expect(matchesCombo(keydown({ key: "k" }), "mod+k")).toBe(false);
  });

  it("matches letter combos by physical position on non-Latin layouts", () => {
    // Russian layout: the physical K key produces "л" in event.key.
    expect(
      matchesCombo(keydown({ key: "л", code: "KeyK", ctrlKey: true }), "mod+k"),
    ).toBe(true);
    // Latin layouts keep strict event.key matching — a remapped layout
    // producing "j" on KeyK must not fire the "k" binding.
    expect(
      matchesCombo(keydown({ key: "j", code: "KeyK", ctrlKey: true }), "mod+k"),
    ).toBe(false);
    // Punctuation never falls back to event.code.
    expect(matchesCombo(keydown({ key: "х", code: "BracketLeft" }), "[")).toBe(
      false,
    );
  });

  it("matches shifted punctuation by the produced key", () => {
    // Shift+/ produces "?" — registering "?" must match without declaring shift.
    expect(matchesCombo(keydown({ key: "?", shiftKey: true }), "?")).toBe(true);
    expect(matchesCombo(keydown({ key: "/", shiftKey: true }), "?")).toBe(false);
  });

  it("rejects extra modifiers on bare-key combos", () => {
    expect(matchesCombo(keydown({ key: "[" }), "[")).toBe(true);
    expect(matchesCombo(keydown({ key: "[", ctrlKey: true }), "[")).toBe(false);
    expect(matchesCombo(keydown({ key: "[", metaKey: true }), "[")).toBe(false);
    expect(matchesCombo(keydown({ key: "[", altKey: true }), "[")).toBe(false);
    // Shift+[ produces "{", which must not fire the "[" binding.
    expect(matchesCombo(keydown({ key: "{", shiftKey: true }), "[")).toBe(false);
  });

  it("enforces shift when declared", () => {
    expect(matchesCombo(keydown({ key: "/", shiftKey: true }), "shift+/")).toBe(true);
    expect(matchesCombo(keydown({ key: "/" }), "shift+/")).toBe(false);
  });
});

describe("isEditableTarget", () => {
  it("flags form fields and contenteditable regions", () => {
    for (const tag of ["input", "textarea", "select"]) {
      const el = document.createElement(tag);
      document.body.appendChild(el);
      expect(isEditableTarget(el)).toBe(true);
    }
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    const inner = document.createElement("span");
    editable.appendChild(inner);
    document.body.appendChild(editable);
    expect(isEditableTarget(editable)).toBe(true);
    expect(isEditableTarget(inner)).toBe(true);
  });

  it("flags descendants of the xterm host but not plain elements", () => {
    const host = document.createElement("div");
    host.className = "fabric-chat-xterm-host";
    const inner = document.createElement("div");
    host.appendChild(inner);
    document.body.appendChild(host);
    expect(isEditableTarget(inner)).toBe(true);

    const xterm = document.createElement("div");
    xterm.className = "xterm";
    document.body.appendChild(xterm);
    expect(isEditableTarget(xterm)).toBe(true);

    const plain = document.createElement("div");
    document.body.appendChild(plain);
    expect(isEditableTarget(plain)).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });
});

describe("registerShortcut dispatch", () => {
  it("invokes the handler and prevents default on a match", () => {
    const handler = vi.fn();
    register("mod+k", handler);

    const event = keydown({ key: "k", ctrlKey: true });
    window.dispatchEvent(event);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it("ignores already-handled, repeated, and editable-target events", () => {
    const handler = vi.fn();
    register("[", handler);

    const prevented = keydown({ key: "[" });
    prevented.preventDefault();
    window.dispatchEvent(prevented);

    window.dispatchEvent(keydown({ key: "[", repeat: true }));

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.dispatchEvent(keydown({ key: "[" }));

    expect(handler).not.toHaveBeenCalled();
  });

  it("gives the most recent registration priority and stops after one handler", () => {
    const first = vi.fn();
    const second = vi.fn();
    register("mod+k", first);
    const disposeSecond = register("mod+k", second);

    window.dispatchEvent(keydown({ key: "k", metaKey: true }));
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();

    disposeSecond();
    window.dispatchEvent(keydown({ key: "k", metaKey: true }));
    expect(first).toHaveBeenCalledTimes(1);
  });

  it("stops dispatching after unregistering", () => {
    const handler = vi.fn();
    const dispose = register("?", handler);
    dispose();

    window.dispatchEvent(keydown({ key: "?", shiftKey: true }));
    expect(handler).not.toHaveBeenCalled();
  });
});

describe("formatCombo", () => {
  it("renders non-mac combos with Ctrl and + separators", () => {
    // jsdom reports no mac platform.
    expect(formatCombo("mod+k")).toBe("Ctrl+K");
    expect(formatCombo("?")).toBe("?");
    expect(formatCombo("[")).toBe("[");
    expect(formatCombo("shift+/")).toBe("Shift+/");
  });
});
