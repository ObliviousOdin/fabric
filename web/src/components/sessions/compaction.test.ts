import { describe, expect, it } from "vitest";
import {
  COMPACTION_END_MARKER,
  splitCompactionContent,
} from "./compaction";

describe("splitCompactionContent", () => {
  it("returns null for regular message content", () => {
    expect(splitCompactionContent("hello there")).toBeNull();
    expect(splitCompactionContent("")).toBeNull();
  });

  it("detects a standalone compaction summary (no end marker)", () => {
    const content = "[CONTEXT SUMMARY]: earlier we discussed X";
    expect(splitCompactionContent(content)).toEqual({
      summary: content,
      remainder: "",
    });
  });

  it("detects prefixes after leading whitespace", () => {
    const content = "\n  [CONTEXT COMPACTION — REFERENCE ONLY]\nbody";
    const split = splitCompactionContent(content);
    expect(split).not.toBeNull();
    expect(split?.remainder).toBe("");
  });

  it("splits a merged summary + tail reply on the end marker (#29824)", () => {
    const summary = "[CONTEXT COMPACTION - REFERENCE ONLY]\nsummary body\n";
    const reply = "the actual assistant reply";
    const split = splitCompactionContent(
      `${summary}${COMPACTION_END_MARKER}\n\n${reply}`,
    );
    expect(split).toEqual({ summary, remainder: reply });
    // The stripped remainder no longer parses as a compaction block, so
    // it re-renders with its real role.
    expect(splitCompactionContent(reply)).toBeNull();
  });
});
