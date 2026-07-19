import { describe, expect, it } from "vitest";

import {
  appendOptimisticUserMessage,
  createEmptyRemoteSession,
  hydrateRemoteSession,
  normalizeStoredMessages,
  reduceRemoteSessionEvent,
  replayRemoteSessionEvents,
  remoteMessageText,
} from "./remote-session";

const event = (
  type: string,
  payload: Record<string, unknown>,
  sessionId = "runtime-1",
) => ({ payload, session_id: sessionId, type });

describe("normalizeStoredMessages", () => {
  it("preserves reasoning and tool chronology in one assistant turn", () => {
    const messages = normalizeStoredMessages([
      { content: "Inspect it", role: "user", timestamp: 1 },
      {
        content: "",
        reasoning: "I should read the file.",
        role: "assistant",
        timestamp: 2,
        tool_calls: [
          {
            function: { arguments: '{"path":"README.md"}', name: "read_file" },
            id: "call-1",
          },
        ],
      },
      {
        content: '{"content":"hello"}',
        role: "tool",
        timestamp: 3,
        tool_call_id: "call-1",
      },
      { content: "The file says hello.", role: "assistant", timestamp: 4 },
    ]);

    expect(messages).toHaveLength(2);
    expect(messages[1].role).toBe("assistant");
    expect(messages[1].parts.map((part) => part.type)).toEqual([
      "reasoning",
      "tool",
      "text",
    ]);
    expect(messages[1].parts[1]).toMatchObject({
      id: "call-1",
      name: "read_file",
      result: { content: "hello" },
      status: "complete",
    });
  });

  it("keeps structured reasoning metadata even when there is no visible text", () => {
    const reasoningDetails = [{ type: "reasoning.summary", summary: "Checked" }];
    const messages = normalizeStoredMessages([
      {
        codex_reasoning_items: [{ id: "item-1" }],
        reasoning_details: reasoningDetails,
        role: "assistant",
      },
    ]);

    expect(messages).toHaveLength(1);
    expect(messages[0].metadata).toEqual({
      codexReasoningItems: [{ id: "item-1" }],
      reasoningDetails,
    });
    expect(messages[0].parts).toEqual([
      { text: "Checked", type: "reasoning" },
    ]);
  });
});

describe("hydrateRemoteSession", () => {
  it("replaces local projection with authoritative history before restoring inflight state", () => {
    const previous = appendOptimisticUserMessage(
      createEmptyRemoteSession(),
      "stale optimistic prompt",
    );
    const hydrated = hydrateRemoteSession(
      {
        history_version: 7,
        inflight: {
          assistant: "partial answer",
          reasoning: "working",
          user: "new prompt",
        },
        messages: [{ content: "persisted", role: "user" }],
        running: true,
        session_id: "runtime-2",
        session_key: "stored-2",
      },
      previous,
    );

    expect(hydrated.runtimeSessionId).toBe("runtime-2");
    expect(hydrated.storedSessionId).toBe("stored-2");
    expect(hydrated.historyVersion).toBe(7);
    expect(hydrated.running).toBe(true);
    expect(hydrated.messages.map(remoteMessageText)).toEqual([
      "persisted",
      "new prompt",
      "partial answer",
    ]);
    expect(
      hydrated.messages.at(-1)?.parts.map((part) => part.type),
    ).toEqual(["reasoning", "text"]);
  });
});

describe("reduceRemoteSessionEvent", () => {
  it("streams text around a completed tool without fabricating extra messages", () => {
    let state = appendOptimisticUserMessage(createEmptyRemoteSession(), "go");
    state = reduceRemoteSessionEvent(state, event("message.start", {}));
    state = reduceRemoteSessionEvent(
      state,
      event("reasoning.delta", { text: "Checking." }),
    );
    state = reduceRemoteSessionEvent(
      state,
      event("tool.start", {
        arguments: { path: "README.md" },
        name: "read_file",
        tool_call_id: "call-1",
      }),
    );
    state = reduceRemoteSessionEvent(
      state,
      event("tool.complete", {
        name: "read_file",
        result: { content: "hello" },
        tool_call_id: "call-1",
      }),
    );
    state = reduceRemoteSessionEvent(
      state,
      event("message.delta", { text: "Done." }),
    );
    state = reduceRemoteSessionEvent(
      state,
      event("message.complete", { text: "Done." }),
    );

    expect(state.messages).toHaveLength(2);
    expect(state.messages[1].parts.map((part) => part.type)).toEqual([
      "reasoning",
      "tool",
      "text",
    ]);
    expect(remoteMessageText(state.messages[1])).toBe("Done.");
    expect(state.needsAuthoritativeResume).toBe(false);
    expect(state.running).toBe(false);
  });

  it("requests authoritative hydration when completion conflicts with streamed text", () => {
    let state = appendOptimisticUserMessage(createEmptyRemoteSession(), "go");
    state = reduceRemoteSessionEvent(
      state,
      event("message.delta", { text: "streamed answer" }),
    );
    state = reduceRemoteSessionEvent(
      state,
      event("message.complete", {
        history_persisted: true,
        history_version: 9,
        text: "different final answer",
      }),
    );

    expect(remoteMessageText(state.messages[1])).toBe("streamed answer");
    expect(state.needsAuthoritativeResume).toBe(true);
    expect(state.historyVersion).toBe(9);
  });

  it("projects clarify and approval requests as blocking prompts", () => {
    const clarify = reduceRemoteSessionEvent(
      createEmptyRemoteSession(),
      event("clarify.request", {
        choices: ["A", "B"],
        question: "Choose",
        request_id: "request-1",
      }),
    );
    expect(clarify.pendingInteractions[0]).toEqual({
      choices: ["A", "B"],
      question: "Choose",
      requestId: "request-1",
      type: "clarify",
    });

    const approval = reduceRemoteSessionEvent(
      clarify,
      event("approval.request", {
        allow_permanent: false,
        command: "rm file",
        description: "Delete file",
        request_id: "approval-1",
      }),
    );
    expect(approval.pendingInteractions).toEqual([
      clarify.pendingInteractions[0],
      {
        allowPermanent: false,
        command: "rm file",
        description: "Delete file",
        requestId: "approval-1",
        type: "approval",
      },
    ]);

    const duplicateCommand = reduceRemoteSessionEvent(
      approval,
      event("approval.request", {
        command: "rm file",
        description: "Delete file",
        request_id: "approval-2",
      }),
    );
    expect(duplicateCommand.pendingInteractions.map((item) => item.requestId)).toEqual([
      "request-1",
      "approval-1",
      "approval-2",
    ]);
  });

  it("ignores approval requests without an authoritative request id", () => {
    const initial = createEmptyRemoteSession();
    const missing = reduceRemoteSessionEvent(
      initial,
      event("approval.request", {
        command: "rm file",
        description: "Delete file",
      }),
    );
    const blank = reduceRemoteSessionEvent(
      initial,
      event("approval.request", {
        command: "rm file",
        description: "Delete file",
        request_id: "   ",
      }),
    );

    expect(missing).toBe(initial);
    expect(blank).toBe(initial);
  });
});

describe("authoritative reconciliation", () => {
  it("derives stable row identities from the durable session binding", () => {
    const payload = {
      messages: [{ content: "persisted", role: "user" as const }],
      session_id: "runtime-1",
      session_key: "stored-1",
    };

    expect(hydrateRemoteSession(payload).messages[0].id).toBe(
      hydrateRemoteSession(payload).messages[0].id,
    );
    expect(hydrateRemoteSession(payload).historyVersion).toBeNull();
  });

  it("does not repair a missing streamed suffix heuristically", () => {
    let state = appendOptimisticUserMessage(createEmptyRemoteSession(), "go");
    state = reduceRemoteSessionEvent(
      state,
      event("message.delta", { text: "partial" }),
    );
    state = reduceRemoteSessionEvent(
      state,
      event("message.complete", {
        history_persisted: true,
        history_version: 2,
        text: "partial answer",
      }),
    );

    expect(remoteMessageText(state.messages[1])).toBe("partial");
    expect(state.needsAuthoritativeResume).toBe(true);
  });

  it("surfaces an unsaved completion without requesting a futile resume", () => {
    let state = appendOptimisticUserMessage(createEmptyRemoteSession(), "go");
    state = reduceRemoteSessionEvent(
      state,
      event("message.delta", { text: "visible stream" }),
    );
    state = reduceRemoteSessionEvent(
      state,
      event("message.complete", {
        history_persisted: false,
        history_version: 3,
        text: "different unsaved completion",
        warning: "History changed; this response was not saved.",
      }),
    );

    expect(remoteMessageText(state.messages[1])).toBe("visible stream");
    expect(state.needsAuthoritativeResume).toBe(false);
    expect(state.persistenceWarning).toBe(
      "History changed; this response was not saved.",
    );
  });

  it("drops every buffered event in a turn covered by the resume barrier", () => {
    const hydrated = hydrateRemoteSession({
      history_version: 4,
      messages: [
        { content: "go", role: "user" },
        { content: "authoritative", role: "assistant" },
      ],
      session_id: "runtime-1",
      session_key: "stored-1",
    });
    const replay = replayRemoteSessionEvents(
      hydrated,
      [
        event("message.start", {}),
        event("reasoning.delta", { text: "duplicate reasoning" }),
        event("tool.start", { name: "read_file", tool_id: "call-1" }),
        event("message.delta", { text: "duplicate" }),
        event("message.complete", {
          history_persisted: true,
          history_version: 4,
          text: "authoritative",
        }),
      ],
      "runtime-1",
    );

    expect(replay.state.messages).toHaveLength(2);
    expect(remoteMessageText(replay.state.messages[1])).toBe("authoritative");
    expect(replay.state.messages[1].parts).toEqual([
      { text: "authoritative", type: "text" },
    ]);
  });

  it("returns other-session events to the caller instead of discarding them", () => {
    const state = hydrateRemoteSession({
      history_version: 0,
      session_id: "runtime-1",
    });
    const other = event("message.delta", { text: "other" }, "runtime-2");
    const replay = replayRemoteSessionEvents(state, [other], "runtime-1");

    expect(replay.deferredEvents).toEqual([other]);
    expect(replay.state.messages).toEqual([]);
  });
});
