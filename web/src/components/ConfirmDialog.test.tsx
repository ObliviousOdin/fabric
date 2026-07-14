// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useModalBehavior } from "@/hooks/useModalBehavior";
import { ConfirmDialog } from "./ConfirmDialog";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function ParentModal({
  confirmOpen,
  onCancel,
  onClose,
}: {
  confirmOpen: boolean;
  onCancel: () => void;
  onClose: () => void;
}) {
  const modalRef = useModalBehavior({ open: true, onClose });

  return (
    <div ref={modalRef} aria-label="Parent modal" role="dialog">
      <button type="button">Parent action</button>
      {confirmOpen && (
        <ConfirmDialog
          onCancel={onCancel}
          onConfirm={() => {}}
          open
          title="Confirm model switch"
        />
      )}
    </div>
  );
}

describe("ConfirmDialog nested modal behavior", () => {
  let container: HTMLDivElement;
  let opener: HTMLButtonElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    document.body.style.setProperty("overflow", "scroll", "important");

    opener = document.createElement("button");
    opener.textContent = "Open parent modal";
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
    document.body.style.removeProperty("overflow");
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("isolates nested keys, traps focus, and restores the shared scroll lock", async () => {
    const onCancel = vi.fn();
    const onParentClose = vi.fn();
    await act(async () => {
      root.render(
        <ParentModal
          confirmOpen={false}
          onCancel={onCancel}
          onClose={onParentClose}
        />,
      );
    });
    expect(document.body.style.overflow).toBe("hidden");

    // Open the portaled child after its parent already owns the first lock.
    // A simultaneous unmount used to let the child's "hidden" snapshot win.
    await act(async () => {
      root.render(
        <ParentModal confirmOpen onCancel={onCancel} onClose={onParentClose} />,
      );
    });

    const dialog = document.body.querySelector<HTMLElement>(
      '[role="dialog"][aria-labelledby="confirm-dialog-title"]',
    );
    expect(dialog).not.toBeNull();
    expect(dialog?.classList.contains("z-[400]")).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");

    const buttons = Array.from(
      dialog?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ??
        [],
    );
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    expect(buttons).toHaveLength(2);
    expect(document.activeElement).toBe(last);

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
          key: "Tab",
          shiftKey: true,
        }),
      );
    });
    expect(document.activeElement).toBe(last);

    await act(async () => {
      last.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "Escape",
        }),
      );
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onParentClose).not.toHaveBeenCalled();

    await act(async () => root.render(null));
    expect(document.body.style.overflow).toBe("scroll");
    expect(document.body.style.getPropertyPriority("overflow")).toBe(
      "important",
    );
    expect(document.activeElement).toBe(opener);
  });
});
