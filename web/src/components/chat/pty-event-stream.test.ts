import { describe, expect, it } from "vitest";

import {
  EVENT_STREAM_MAX_RECONNECT_ATTEMPTS,
  eventStreamReconnectDelay,
  isSemanticPtyEvent,
  ptySessionMetadata,
} from "./pty-event-stream";

describe("PTY event stream policy", () => {
  it("keeps reconnects exponential, capped, and bounded", () => {
    expect(eventStreamReconnectDelay(1)).toBe(250);
    expect(eventStreamReconnectDelay(4)).toBe(2_000);
    expect(eventStreamReconnectDelay(5)).toBe(3_000);
    expect(
      eventStreamReconnectDelay(EVENT_STREAM_MAX_RECONNECT_ATTEMPTS + 1),
    ).toBeNull();
  });

  it("drops transcript token streams while retaining semantic events", () => {
    expect(isSemanticPtyEvent("message.delta")).toBe(false);
    expect(isSemanticPtyEvent("reasoning.delta")).toBe(false);
    expect(isSemanticPtyEvent("thinking.delta")).toBe(false);
    expect(isSemanticPtyEvent("message.start")).toBe(true);
    expect(isSemanticPtyEvent("tool.complete")).toBe(true);
  });

  it("derives title, cwd, and warnings from the real PTY session events", () => {
    expect(
      ptySessionMetadata("session.info", {
        credential_warning: "refresh credentials",
        cwd: " /workspace/fabric ",
        model: "openai/gpt-5",
        title: " Initial task ",
      }),
    ).toEqual({
      credentialWarning: "refresh credentials",
      cwd: "/workspace/fabric",
      model: "openai/gpt-5",
      title: "Initial task",
    });
    expect(
      ptySessionMetadata("session.title", { title: " Renamed live " }),
    ).toEqual({ title: "Renamed live" });
  });
});
