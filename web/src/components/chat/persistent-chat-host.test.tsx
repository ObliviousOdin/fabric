// @vitest-environment jsdom

import {
  lazy,
  Suspense,
  useEffect,
} from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  shouldRenderPersistentChat,
  usePersistentActiveMount,
} from "./persistent-chat-host";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("persistent Chat host lifecycle", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("does not mount a first hidden PTY when loading finishes after route-away", () => {
    expect(shouldRenderPersistentChat(true, false, true)).toBe(false);
    expect(shouldRenderPersistentChat(false, false, false)).toBe(false);
  });

  it("retains only a lazy child that actually committed while active", async () => {
    const module = deferred<{ default: typeof LazyChat }>();
    const mounted = vi.fn();

    function LazyChat({
      active,
      onActiveMount,
    }: {
      active: boolean;
      onActiveMount: () => void;
    }) {
      useEffect(() => {
        mounted(active);
        if (active) onActiveMount();
      }, [active, onActiveMount]);
      return <div data-chat-active={String(active)}>Chat</div>;
    }

    const DeferredChat = lazy(() => module.promise);
    function Harness({ active }: { active: boolean }) {
      const { hasMountedActiveChat, markActiveChatMounted } =
        usePersistentActiveMount();
      if (!active && !hasMountedActiveChat) return null;
      return (
        <Suspense fallback={<span>Loading</span>}>
          <DeferredChat
            active={active}
            onActiveMount={markActiveChatMounted}
          />
        </Suspense>
      );
    }

    await act(async () => root.render(<Harness active />));
    expect(container.textContent).toBe("Loading");
    await act(async () => root.render(<Harness active={false} />));
    await act(async () => module.resolve({ default: LazyChat }));
    expect(mounted).not.toHaveBeenCalled();
    expect(container.textContent).toBe("");

    await act(async () => root.render(<Harness active />));
    expect(mounted).toHaveBeenLastCalledWith(true);
    await act(async () => root.render(<Harness active={false} />));
    expect(container.querySelector("[data-chat-active=false]")).not.toBeNull();
  });
});
