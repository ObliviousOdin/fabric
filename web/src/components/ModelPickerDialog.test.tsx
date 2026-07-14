// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModelPickerDialog } from "./ModelPickerDialog";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("ModelPickerDialog mobile modal behavior", () => {
  let container: HTMLDivElement;
  let opener: HTMLButtonElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    opener = document.createElement("button");
    opener.textContent = "Open model picker";
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
        <ModelPickerDialog
          loader={vi.fn().mockResolvedValue({
            model: "gpt-5",
            provider: "openai",
            providers: [
              {
                name: "OpenAI",
                slug: "openai",
                models: ["gpt-5"],
                is_current: true,
              },
            ],
          })}
          onApply={vi.fn()}
          onClose={onClose}
        />,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    const dialog = document.body.querySelector<HTMLElement>("[role=dialog]");
    expect(dialog).not.toBeNull();
    // The picker can be launched from Chat's z-200 compact context sheet.
    expect(dialog?.classList.contains("z-[300]")).toBe(true);
    expect(dialog?.contains(document.activeElement)).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");

    const focusable = Array.from(
      dialog?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    expect(focusable.length).toBeGreaterThan(1);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

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

    await act(async () => root.unmount());
    root = createRoot(container);
    expect(document.activeElement).toBe(opener);
    expect(document.body.style.overflow).toBe("");
  });
});
