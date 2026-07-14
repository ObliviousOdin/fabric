// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatSideSheet } from "./ChatSideSheet";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("ChatSideSheet", () => {
  let container: HTMLDivElement;
  let opener: HTMLButtonElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    opener = document.createElement("button");
    opener.textContent = "Open conversations";
    document.body.appendChild(opener);
    opener.focus();

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    opener.remove();
    document.body.style.overflow = "";
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("traps focus, closes on Escape, and restores the opener", async () => {
    const onClose = vi.fn();
    await act(async () => {
      root.render(
        <ChatSideSheet
          id="chat-conversations-sheet"
          onClose={onClose}
          side="left"
          title="Conversations"
        >
          <button type="button">First conversation</button>
          <button type="button">Last conversation</button>
        </ChatSideSheet>,
      );
      await Promise.resolve();
    });

    const dialog = document.body.querySelector<HTMLElement>(
      '#chat-conversations-sheet[role="dialog"]',
    );
    expect(dialog).not.toBeNull();
    expect(dialog?.dataset.side).toBe("left");
    expect(dialog?.getAttribute("aria-modal")).toBe("true");
    expect(document.body.style.overflow).toBe("hidden");
    expect(dialog?.contains(document.activeElement)).toBe(true);

    const focusable = Array.from(
      dialog?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    expect(focusable.length).toBeGreaterThan(1);

    last.focus();
    await act(async () => {
      last.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "Tab",
        }),
      );
    });
    expect(document.activeElement).toBe(first);

    await act(async () => {
      first.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "Escape",
        }),
      );
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    await act(async () => root.render(null));
    expect(document.activeElement).toBe(opener);
    expect(document.body.style.overflow).toBe("");
  });
});
