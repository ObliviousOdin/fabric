// @vitest-environment jsdom

import {
  act,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  buildWsUrl: vi.fn(async () => "ws://dashboard.test/api/events?channel=chat"),
  getModelInfo: vi.fn(async () => ({
    capabilities: { supports_reasoning: false },
    effective_context_length: 200_000,
    model: "openai/gpt-5",
  })),
  sidecarConstructed: vi.fn(),
}));

vi.mock("@nous-research/ui/ui/components/button", () => ({
  Button: ({
    children,
    prefix,
    ...props
  }: ButtonHTMLAttributes<HTMLButtonElement> & { prefix?: ReactNode }) => {
    void prefix;
    return <button {...props}>{children}</button>;
  },
}));
vi.mock("@nous-research/ui/ui/components/card", () => ({
  Card: ({ children, ...props }: HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
}));
vi.mock("@/components/chat/ActivityFeed", () => ({
  ActivityFeed: ({
    feed,
  }: {
    feed: { rows: Array<{ name?: string; text?: string }> };
  }) => (
    <output data-testid="activity-feed">
      {feed.rows.map((row) => row.name ?? row.text ?? "").join(",")}
    </output>
  ),
}));
vi.mock("@/components/chat/AgentCard", () => ({
  AgentCard: ({
    connection,
    cwd,
    title,
  }: {
    connection: string;
    cwd?: string | null;
    title?: string | null;
  }) => (
    <div
      data-testid="agent-card"
      data-connection={connection}
      data-cwd={cwd ?? ""}
      data-title={title ?? ""}
    />
  ),
}));
vi.mock("@/components/ModelPickerDialog", () => ({
  ModelPickerDialog: () => null,
}));
vi.mock("@/components/ModelReloadConfirm", () => ({
  ModelReloadConfirm: () => null,
}));
vi.mock("@/components/ReasoningPicker", () => ({ ReasoningPicker: () => null }));
vi.mock("@/plugins", () => ({ PluginSlot: () => null }));
vi.mock("@/lib/api", () => ({
  api: { getModelInfo: mocks.getModelInfo },
  buildWsUrl: mocks.buildWsUrl,
}));
vi.mock("@/lib/gatewayClient", () => ({
  GatewayClient: class {
    constructor() {
      mocks.sidecarConstructed();
    }
  },
}));

import { ChatSidebar } from "./ChatSidebar";

interface ListenerEntry {
  callback: (event: unknown) => void;
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  private listeners = new Map<string, ListenerEntry[]>();
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, callback: (event: unknown) => void) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push({ callback });
    this.listeners.set(type, listeners);
  }

  close() {
    this.emit("close", { code: 1000 });
  }

  emit(type: string, event: unknown) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener.callback(event);
    }
  }

  event(type: string, payload: unknown, sessionId = "sid-1") {
    this.emit("message", {
      data: JSON.stringify({
        method: "event",
        params: { payload, session_id: sessionId, type },
      }),
    });
  }
}

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("ChatSidebar PTY event transport", () => {
  let container: HTMLDivElement;
  let root: Root;
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    FakeWebSocket.instances = [];
    mocks.buildWsUrl.mockClear();
    mocks.getModelInfo.mockClear();
    mocks.sidecarConstructed.mockClear();
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    globalThis.WebSocket = originalWebSocket;
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("uses only the real PTY events socket and projects session.info/session.title", async () => {
    const onContextEvent = vi.fn();
    const onSessionTitleChange = vi.fn();

    await act(async () => {
      root.render(
        <ChatSidebar
          channel="chat"
          onContextEvent={onContextEvent}
          onSessionTitleChange={onSessionTitleChange}
        />,
      );
    });
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0]!;

    expect(socket.url).toContain("/api/events");
    expect(mocks.sidecarConstructed).not.toHaveBeenCalled();
    await act(async () => socket.emit("open", {}));
    expect(
      container
        .querySelector('[data-testid="agent-card"]')
        ?.getAttribute("data-connection"),
    ).toBe("connecting");
    await act(async () => {
      socket.event("session.info", {
        credential_warning: "refresh credentials",
        cwd: "/workspace/fabric",
        title: "Initial task",
      });
      socket.event("message.delta", { text: "stream token" });
      socket.event("session.title", { title: "Renamed live" });
    });

    const card = container.querySelector('[data-testid="agent-card"]');
    expect(card?.getAttribute("data-connection")).toBe("open");
    expect(card?.getAttribute("data-cwd")).toBe("/workspace/fabric");
    expect(card?.getAttribute("data-title")).toBe("Renamed live");
    expect(container.textContent).toContain("refresh credentials");
    expect(onSessionTitleChange).toHaveBeenLastCalledWith("Renamed live");
    expect(onContextEvent.mock.calls.map(([event]) => event.type)).toEqual([
      "session.info",
      "session.title",
    ]);
  });

  it("clears prior activity when a new TUI session reuses the channel", async () => {
    vi.useFakeTimers();
    const onSessionTitleChange = vi.fn();
    try {
      await act(async () => {
        root.render(
          <ChatSidebar
            channel="chat"
            onSessionTitleChange={onSessionTitleChange}
          />,
        );
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(FakeWebSocket.instances).toHaveLength(1);
      const socket = FakeWebSocket.instances[0]!;

      await act(async () => {
        socket.emit("open", {});
        socket.event(
          "session.info",
          {
            credential_warning: "old warning",
            cwd: "/workspace/old-chat",
            title: "Old chat",
          },
          "sid-old",
        );
        socket.event(
          "tool.start",
          { name: "old_tool", tool_id: "tool-old" },
          "sid-old",
        );
        await vi.advanceTimersByTimeAsync(120);
      });
      expect(
        container.querySelector('[data-testid="activity-feed"]')?.textContent,
      ).toContain("old_tool");
      expect(container.textContent).toContain("old warning");

      await act(async () => {
        socket.event("session.info", { running: false }, "sid-new");
      });
      expect(
        container.querySelector('[data-testid="activity-feed"]')?.textContent,
      ).toBe("");
      const card = container.querySelector('[data-testid="agent-card"]');
      expect(card?.getAttribute("data-cwd")).toBe("");
      expect(card?.getAttribute("data-title")).toBe("");
      expect(container.textContent).not.toContain("old warning");
      expect(onSessionTitleChange).toHaveBeenLastCalledWith(null);
    } finally {
      vi.useRealTimers();
    }
  });
});
