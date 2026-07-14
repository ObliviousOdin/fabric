import { useEffect } from "react";

interface BodyScrollLockState {
  body: HTMLElement;
  count: number;
  overflow: string;
  priority: string;
}

const lockStates = new WeakMap<Document, BodyScrollLockState>();

/**
 * Acquire a document-scoped body scroll lock.
 *
 * The first caller snapshots the inline overflow declaration and the final
 * caller restores it. Each release is idempotent, so parent and portaled-child
 * modals can unmount in any order without leaving the page locked or unlocking
 * it while another modal is still open.
 */
export function acquireBodyScrollLock(targetDocument?: Document): () => void {
  const ownerDocument =
    targetDocument ?? (typeof document === "undefined" ? undefined : document);
  const body = ownerDocument?.body;
  if (!ownerDocument || !body) return () => {};

  let state = lockStates.get(ownerDocument);
  if (!state) {
    state = {
      body,
      count: 0,
      overflow: body.style.getPropertyValue("overflow"),
      priority: body.style.getPropertyPriority("overflow"),
    };
    lockStates.set(ownerDocument, state);
  }

  state.count += 1;
  state.body.style.setProperty("overflow", "hidden");

  let released = false;
  return () => {
    if (released) return;
    released = true;

    state.count -= 1;
    if (state.count > 0) return;

    if (state.overflow) {
      state.body.style.setProperty("overflow", state.overflow, state.priority);
    } else {
      state.body.style.removeProperty("overflow");
    }
    lockStates.delete(ownerDocument);
  };
}

/** Keep body scrolling locked for the lifetime of an active modal. */
export function useBodyScrollLock(active = true): void {
  useEffect(() => {
    if (!active) return;
    return acquireBodyScrollLock();
  }, [active]);
}
