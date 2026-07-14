// @vitest-environment jsdom

import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWorkspaceLayout } from "./ChatWorkspaceLayout";
import type { ChatViewportMode } from "./useChatViewportMode";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("ChatWorkspaceLayout", () => {
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

  async function render(mode: ChatViewportMode, active = true) {
    await act(async () => {
      root.render(
        <ChatWorkspaceLayout
          active={active}
          context={<div data-panel="context">Context rail</div>}
          conversations={
            <div data-panel="conversations">Conversation rail</div>
          }
          mode={mode}
          terminal={<div data-panel="terminal">Persistent terminal</div>}
        />,
      );
    });
  }

  it("renders three distinct landmarks at 1440px-and-up mode", async () => {
    await render("wide");

    expect(
      container.querySelector('nav[aria-label="Conversations"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('section[aria-label="Agent chat"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('aside[aria-label="Task and agent context"]'),
    ).not.toBeNull();
    expect(container.querySelectorAll("aside")).toHaveLength(1);
    expect(
      container.querySelectorAll('[data-panel="conversations"]'),
    ).toHaveLength(1);
    expect(container.querySelectorAll('[data-panel="terminal"]')).toHaveLength(
      1,
    );
    expect(container.querySelectorAll('[data-panel="context"]')).toHaveLength(
      1,
    );
  });

  it("keeps the terminal mounted while viewport modes change", async () => {
    await render("compact");
    const terminal = container.querySelector('[data-panel="terminal"]');
    expect(terminal).not.toBeNull();

    await render("medium");
    expect(container.querySelector('[data-panel="terminal"]')).toBe(terminal);

    await render("wide");
    expect(container.querySelector('[data-panel="terminal"]')).toBe(terminal);
  });

  it("mounts only the selected medium rail and supports arrow-key switching", async () => {
    const conversationsMounted = vi.fn();
    const conversationsUnmounted = vi.fn();
    const contextMounted = vi.fn();

    function ConversationsProbe() {
      useEffect(() => {
        conversationsMounted();
        return conversationsUnmounted;
      }, []);
      return <div data-panel="conversations">Conversation rail</div>;
    }

    function ContextProbe() {
      useEffect(() => {
        contextMounted();
      }, []);
      return <div data-panel="context">Context rail</div>;
    }

    await act(async () => {
      root.render(
        <ChatWorkspaceLayout
          active
          context={<ContextProbe />}
          conversations={<ConversationsProbe />}
          mode="medium"
          terminal={<div data-panel="terminal">Persistent terminal</div>}
        />,
      );
    });

    expect(conversationsMounted).toHaveBeenCalledTimes(1);
    expect(contextMounted).not.toHaveBeenCalled();
    expect(container.querySelector('[data-panel="context"]')).toBeNull();

    const conversationsTab = container.querySelector<HTMLButtonElement>(
      '[role="tab"][aria-selected="true"]',
    );
    expect(conversationsTab?.textContent).toContain("Conversations");
    conversationsTab?.focus();
    await act(async () => {
      conversationsTab?.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "ArrowRight",
        }),
      );
    });

    expect(contextMounted).toHaveBeenCalledTimes(1);
    expect(conversationsUnmounted).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-panel="conversations"]')).toBeNull();
    expect(container.querySelector('[data-panel="context"]')).not.toBeNull();
    expect(document.activeElement?.textContent).toContain("Context");
  });

  it("renders only the center terminal below 1024px and while inactive", async () => {
    await render("compact");
    expect(container.querySelector('[data-panel="terminal"]')).not.toBeNull();
    expect(container.querySelector('[data-panel="conversations"]')).toBeNull();
    expect(container.querySelector('[data-panel="context"]')).toBeNull();

    await render("wide", false);
    expect(container.querySelector('[data-panel="terminal"]')).not.toBeNull();
    expect(container.querySelector('[data-panel="conversations"]')).toBeNull();
    expect(container.querySelector('[data-panel="context"]')).toBeNull();
  });
});
