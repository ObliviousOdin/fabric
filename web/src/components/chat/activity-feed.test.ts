import { describe, expect, it } from "vitest";

import {
  EMPTY_ACTIVITY_FEED,
  MAX_FEED_ROWS,
  MAX_TOOL_ROWS,
  formatCompactCount,
  formatToolDuration,
  reduceActivityEvent,
  type ActivityFeedState,
  type ToolFeedRow,
} from "./activity-feed";

const NOW = 1_750_000_000_000;

function feedEvents(
  events: Array<[string, unknown]>,
  start: ActivityFeedState = EMPTY_ACTIVITY_FEED,
): ActivityFeedState {
  return events.reduce(
    (state, [type, payload]) => reduceActivityEvent(state, type, payload, NOW),
    start,
  );
}

describe("CH3 activity-feed reducer", () => {
  it("stays hidden (seenAny=false) until the first activity event", () => {
    const afterInfo = reduceActivityEvent(
      EMPTY_ACTIVITY_FEED,
      "session.info",
      { title: "hello" },
      NOW,
    );
    expect(afterInfo.seenAny).toBe(false);
    // No change → same reference, so throttled flushes bail out of renders.
    expect(afterInfo).toBe(EMPTY_ACTIVITY_FEED);
  });

  it("appends a running tool row on tool.start and finalizes it on tool.complete", () => {
    const started = feedEvents([
      ["tool.start", { tool_id: "t1", name: "web_search", context: "cats" }],
    ]);
    expect(started.seenAny).toBe(true);
    expect(started.rows).toHaveLength(1);
    const row = started.rows[0] as ToolFeedRow;
    expect(row).toMatchObject({
      rowKind: "tool",
      toolId: "t1",
      name: "web_search",
      context: "cats",
      running: true,
    });

    const completed = feedEvents(
      [
        [
          "tool.complete",
          {
            tool_id: "t1",
            name: "web_search",
            duration_s: 1.83,
            summary: "Did 3 searches in 1.8s",
          },
        ],
      ],
      started,
    );
    expect(completed.rows).toHaveLength(1);
    expect(completed.rows[0]).toMatchObject({
      running: false,
      durationS: 1.83,
      summary: "Did 3 searches in 1.8s",
    });
  });

  it("keeps render keys unique when a provider reuses tool_call ids across turns", () => {
    // Some providers number tool calls per turn ("call_0"…), so the same
    // tool_id legitimately recurs while older rows are still retained.
    const state = feedEvents([
      ["tool.start", { tool_id: "call_0", name: "bash" }],
      ["tool.complete", { tool_id: "call_0", name: "bash", duration_s: 1 }],
      ["tool.start", { tool_id: "call_0", name: "web_search" }],
    ]);
    expect(state.rows).toHaveLength(2);
    const keys = state.rows.map((r) => r.key);
    expect(new Set(keys).size).toBe(keys.length);
    // The second start is a fresh running row; the first stays completed.
    expect(state.rows[0]).toMatchObject({ name: "web_search", running: true });
    expect(state.rows[1]).toMatchObject({ name: "bash", running: false });
  });

  it("prepends an already-done row for an unmatched tool.complete", () => {
    const state = feedEvents([
      ["tool.complete", { tool_id: "orphan", name: "bash", duration_s: 4 }],
    ]);
    expect(state.rows).toHaveLength(1);
    expect(state.rows[0]).toMatchObject({ running: false, name: "bash" });
  });

  it("caps retention at MAX_TOOL_ROWS tool rows, newest first (FIFO)", () => {
    const events: Array<[string, unknown]> = [];
    for (let i = 0; i < MAX_TOOL_ROWS + 5; i++) {
      events.push(["tool.start", { tool_id: `t${i}`, name: `tool${i}` }]);
    }
    const state = feedEvents(events);
    expect(state.rows).toHaveLength(MAX_TOOL_ROWS);
    expect((state.rows[0] as ToolFeedRow).toolId).toBe(
      `t${MAX_TOOL_ROWS + 4}`,
    );
    // Oldest five evicted.
    expect(
      state.rows.some((r) => r.rowKind === "tool" && r.toolId === "t4"),
    ).toBe(false);
    expect(state.rows.length).toBeLessThanOrEqual(MAX_FEED_ROWS);
  });

  it("treats message/reasoning deltas as one mutually exclusive state line and batches no-ops by reference", () => {
    const responding = feedEvents([["message.start", undefined]]);
    expect(responding.stateLine).toBe("responding");

    // Delta storm while already responding → same reference every time.
    const again = reduceActivityEvent(
      responding,
      "message.delta",
      { text: "hi" },
      NOW,
    );
    expect(again).toBe(responding);

    const reasoning = feedEvents(
      [["reasoning.delta", { text: "hmm" }]],
      responding,
    );
    expect(reasoning.stateLine).toBe("reasoning");
    expect(
      reduceActivityEvent(reasoning, "thinking.delta", { text: "…" }, NOW),
    ).toBe(reasoning);

    const done = feedEvents([["message.complete", { text: "hi" }]], reasoning);
    expect(done.stateLine).toBeNull();
    // tool.start also clears the state line — a tool run supersedes it.
    const withTool = feedEvents(
      [
        ["message.start", undefined],
        ["tool.start", { tool_id: "t1", name: "bash" }],
      ],
      done,
    );
    expect(withTool.stateLine).toBeNull();
  });

  it("pins approval.request until ANY subsequent event arrives", () => {
    const pinned = feedEvents([
      ["tool.start", { tool_id: "t1", name: "bash" }],
      ["approval.request", { command: "rm -rf ./dist" }],
    ]);
    expect(pinned.approvalPending).toBe(true);
    // Idempotent while pending.
    expect(
      reduceActivityEvent(pinned, "approval.request", {}, NOW),
    ).toBe(pinned);

    // Even an unhandled event type lifts the pin.
    const lifted = reduceActivityEvent(pinned, "session.info", {}, NOW);
    expect(lifted.approvalPending).toBe(false);
  });

  it("appends muted status.update rows and ignores empty ones", () => {
    const state = feedEvents([
      ["status.update", { kind: "status", text: "Summarizing…" }],
      ["status.update", { kind: "status", text: "   " }],
    ]);
    expect(state.rows).toHaveLength(1);
    expect(state.rows[0]).toMatchObject({
      rowKind: "status",
      text: "Summarizing…",
    });
  });
});

describe("mono formatters", () => {
  it("formats tool durations compactly", () => {
    expect(formatToolDuration(1.83)).toBe("1.8s");
    expect(formatToolDuration(42.4)).toBe("42s");
    expect(formatToolDuration(102)).toBe("1m 42s");
    expect(formatToolDuration(-1)).toBe("—");
  });

  it("formats compact counts for the ctx line", () => {
    expect(formatCompactCount(200_000)).toBe("200k");
    expect(formatCompactCount(8_192)).toBe("8.2k");
    expect(formatCompactCount(1_200_000)).toBe("1.2m");
    expect(formatCompactCount(512)).toBe("512");
    expect(formatCompactCount(0)).toBe("");
  });
});
