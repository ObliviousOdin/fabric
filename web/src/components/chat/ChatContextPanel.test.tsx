// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

vi.mock("@/components/ChatSidebar", () => ({
  ChatSidebar: () => null,
}));

import { ChatContextTabs } from "./ChatContextPanel";
import {
  EMPTY_CHAT_CONTEXT_STATE,
  reduceChatContextEvent,
  type ChatContextState,
} from "./chat-context-state";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function liveContext(): ChatContextState {
  return reduceChatContextEvent(EMPTY_CHAT_CONTEXT_STATE, {
    type: "session.info",
    sessionId: "session-123",
    payload: {
      cwd: "/workspace/fabric",
      running: true,
      title: "Fix dashboard context",
    },
  });
}

describe("reduceChatContextEvent", () => {
  it("projects the PTY session and tool stream into task and evidence state", () => {
    let state = liveContext();
    state = reduceChatContextEvent(state, {
      type: "tool.start",
      sessionId: "session-123",
      payload: {
        tool_id: "tool-1",
        name: "write_file",
        context: "Writing report.md",
      },
    });
    state = reduceChatContextEvent(state, {
      type: "tool.complete",
      sessionId: "session-123",
      payload: {
        tool_id: "tool-1",
        name: "write_file",
        args: { file_path: "/workspace/fabric/report.md" },
        duration_s: 1.25,
        result: { output_path: "/workspace/fabric/report.md" },
        todos: [
          { id: "inspect", content: "Inspect the UI", status: "completed" },
          { id: "fix", content: "Wire live context", status: "in_progress" },
        ],
      },
    });

    expect(state).toMatchObject({
      connected: true,
      cwd: "/workspace/fabric",
      running: true,
      sessionId: "session-123",
      title: "Fix dashboard context",
    });
    expect(state.todos.map((todo) => todo.content)).toEqual([
      "Inspect the UI",
      "Wire live context",
    ]);
    expect(state.evidence[0]).toMatchObject({
      durationS: 1.25,
      name: "write_file",
      running: false,
    });
    expect(state.artifacts).toEqual([
      expect.objectContaining({
        label: "report.md",
        source: "write_file",
        value: "/workspace/fabric/report.md",
      }),
    ]);
  });

  it("collects bounded subagent artifacts without treating commands as files", () => {
    let state = reduceChatContextEvent(EMPTY_CHAT_CONTEXT_STATE, {
      type: "tool.complete",
      payload: {
        name: "terminal",
        args: { command: "curl https://example.com/not-an-artifact" },
        result: { stdout: "ok" },
      },
    });
    expect(state.artifacts).toEqual([]);

    state = reduceChatContextEvent(state, {
      type: "subagent.complete",
      payload: {
        tool_name: "designer",
        files_written: Array.from(
          { length: 25 },
          (_, index) => `/workspace/mockup-${index}.png`,
        ),
      },
    });
    expect(state.artifacts).toHaveLength(20);
    expect(state.artifacts[0]).toMatchObject({
      source: "designer",
      value: "/workspace/mockup-19.png",
    });
  });

  it("tracks message lifecycle without getting stuck after an error", () => {
    let state = reduceChatContextEvent(EMPTY_CHAT_CONTEXT_STATE, {
      type: "message.start",
      sessionId: "session-123",
    });
    expect(state).toMatchObject({
      connected: true,
      running: true,
      sessionId: "session-123",
    });

    state = reduceChatContextEvent(state, {
      type: "error",
      sessionId: "session-123",
    });
    expect(state.running).toBe(false);

    state = reduceChatContextEvent(state, {
      type: "message.start",
      sessionId: "session-123",
    });
    state = reduceChatContextEvent(state, {
      type: "message.complete",
      sessionId: "session-123",
    });
    expect(state.running).toBe(false);
  });

  it("applies the async session.title event to the live chat projection", () => {
    const state = reduceChatContextEvent(liveContext(), {
      type: "session.title",
      sessionId: "session-123",
      payload: { title: "Renamed after first turn" },
    });

    expect(state.title).toBe("Renamed after first turn");
    expect(state.sessionId).toBe("session-123");
  });

  it("clears prior conversation context when the channel starts a new session", () => {
    let state = reduceChatContextEvent(liveContext(), {
      type: "tool.complete",
      sessionId: "session-123",
      payload: {
        files_written: ["/workspace/old-report.md"],
        name: "write_file",
        todos: [{ content: "Old task", id: "old", status: "completed" }],
        tool_id: "old-tool",
      },
    });
    expect(state.evidence).toHaveLength(1);
    expect(state.todos).toHaveLength(1);
    expect(state.artifacts).toHaveLength(1);

    state = reduceChatContextEvent(state, {
      type: "session.info",
      sessionId: "session-456",
      payload: {
        cwd: "/workspace/new-chat",
        running: false,
        title: "Fresh conversation",
      },
    });

    expect(state).toEqual({
      ...EMPTY_CHAT_CONTEXT_STATE,
      connected: true,
      cwd: "/workspace/new-chat",
      sessionId: "session-456",
      title: "Fresh conversation",
    });
  });
});

describe("ChatContextTabs", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    vi.spyOn(api, "getMemory").mockResolvedValue({
      active: "holographic",
      builtin_files: { memory: 2048, user: 1024 },
      providers: [],
      selection: {
        configured: "holographic",
        runtime_active: "unknown",
        state: "eligible",
      },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <ChatContextTabs context={liveContext()} profile="default" />,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("exposes live Task, Evidence, Memory, and Artifacts as an accessible tab set", () => {
    const tablist = container.querySelector(
      '[role="tablist"][aria-label="Context type"]',
    );
    expect(tablist).not.toBeNull();

    const tabs = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    );
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Task",
      "Evidence",
      "Memory",
      "Artifacts",
    ]);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");

    const panel = container.querySelector('[role="tabpanel"]');
    expect(panel?.textContent).toContain("Working in current chat");
    expect(panel?.textContent).toContain("Fix dashboard context");
    expect(panel?.textContent).toContain(
      "the Work card above counts only durable items",
    );
    expect(panel?.textContent).not.toContain("Contract not connected");
  });

  it("supports arrow, Home, and End keyboard navigation", async () => {
    const selected = () =>
      container.querySelector<HTMLButtonElement>(
        '[role="tab"][aria-selected="true"]',
      );

    selected()?.focus();
    await act(async () => {
      selected()?.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "ArrowRight",
        }),
      );
    });
    expect(selected()?.textContent).toBe("Evidence");
    expect(document.activeElement).toBe(selected());
    expect(container.querySelector('[role="tabpanel"]')?.textContent).toContain(
      "No tool evidence yet",
    );

    await act(async () => {
      selected()?.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "End",
        }),
      );
    });
    expect(selected()?.textContent).toBe("Artifacts");
    expect(container.querySelector('[role="tabpanel"]')?.textContent).toContain(
      "No artifacts detected yet",
    );

    await act(async () => {
      selected()?.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "Home",
        }),
      );
    });
    expect(selected()?.textContent).toBe("Task");
  });

  it("shows real profile memory readiness instead of a placeholder", async () => {
    const memoryTab = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    ).find((tab) => tab.textContent === "Memory")!;

    await act(async () => memoryTab.click());

    const panel = container.querySelector('[role="tabpanel"]');
    expect(api.getMemory).toHaveBeenCalledWith("default");
    expect(panel?.textContent).toContain("Built-in memory files available");
    expect(panel?.textContent).toContain("Configured provider · holographic");
    expect(panel?.textContent).toContain("Selection state · eligible next session");
    expect(panel?.textContent).toContain("MEMORY.md · 2.0 KB");
    expect(panel?.textContent).toContain("USER.md · 1.0 KB");
  });
});
