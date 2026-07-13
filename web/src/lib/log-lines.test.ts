import { describe, expect, it } from "vitest";

import {
  classifyLineKeyword,
  findAnchorIndex,
  parseLogLine,
  parseLogLines,
} from "./log-lines";

const INFO_TAGGED =
  "2026-07-13 09:41:22,318 INFO [tg_12345_67] gateway.telegram: message text";
const ERROR_LINE =
  "2026-07-13 09:41:22,318 ERROR agent.run_agent: Traceback (most recent call last):";

describe("parseLogLine", () => {
  it("parses a fully structured line with a session tag", () => {
    const p = parseLogLine(INFO_TAGGED);
    expect(p.raw).toBe(INFO_TAGGED);
    expect(p.level).toBe("INFO");
    expect(p.sessionId).toBe("tg_12345_67");
    expect(p.loggerName).toBe("gateway.telegram");
    expect(p.isContinuation).toBe(false);
    expect(p.classification).toBe("info");
  });

  it("parses a structured line without a session tag", () => {
    const p = parseLogLine(ERROR_LINE);
    expect(p.level).toBe("ERROR");
    expect(p.sessionId).toBeNull();
    expect(p.loggerName).toBe("agent.run_agent");
    expect(p.isContinuation).toBe(false);
    expect(p.classification).toBe("error");
  });

  it("accepts timestamps without milliseconds", () => {
    const p = parseLogLine("2026-04-05 22:35:00 WARNING cron.scheduler: late");
    expect(p.isContinuation).toBe(false);
    expect(p.level).toBe("WARNING");
    expect(p.classification).toBe("warning");
  });

  it("folds CRITICAL into the error classification", () => {
    const p = parseLogLine(
      "2026-07-13 09:41:22,318 CRITICAL agent.run_agent: gone",
    );
    expect(p.level).toBe("CRITICAL");
    expect(p.classification).toBe("error");
  });

  it("classifies DEBUG lines as debug", () => {
    const p = parseLogLine("2026-07-13 09:41:22,318 DEBUG tools.web: fetch");
    expect(p.level).toBe("DEBUG");
    expect(p.classification).toBe("debug");
  });

  it("word-bounded level beats substring: INFO line mentioning 'error'", () => {
    const p = parseLogLine(
      "2026-07-13 09:41:22,318 INFO gateway.run: retrying after error in poll",
    );
    expect(p.level).toBe("INFO");
    // The old substring heuristic would have called this "error".
    expect(p.classification).toBe("info");
  });

  it("marks lines without a leading timestamp as continuations", () => {
    const p = parseLogLine('  File "agent/run_agent.py", line 10, in run');
    expect(p.isContinuation).toBe(true);
    expect(p.level).toBeNull();
    expect(p.sessionId).toBeNull();
    expect(p.loggerName).toBeNull();
  });

  it("continuation lines inherit the previous classification", () => {
    const prev = parseLogLine(ERROR_LINE);
    const p = parseLogLine("    raise ValueError('nope')", prev);
    expect(p.isContinuation).toBe(true);
    expect(p.classification).toBe("error");
  });

  it("continuation without prev falls back to the keyword heuristic", () => {
    expect(parseLogLine("something failed with error").classification).toBe(
      "error",
    );
    expect(parseLogLine("warn: disk almost full").classification).toBe(
      "warning",
    );
    expect(parseLogLine("plain stderr output").classification).toBe("info");
  });

  it("does not extract a session id from bracketed message text", () => {
    // The tag slot sits between the level token and the logger name; a
    // bracket later in the message must not match.
    const p = parseLogLine(
      "2026-07-13 09:41:22,318 INFO gateway.run: saw [not_a_tag] in body",
    );
    expect(p.sessionId).toBeNull();
  });
});

describe("parseLogLines", () => {
  it("threads inheritance through a multi-line traceback", () => {
    const parsed = parseLogLines([
      INFO_TAGGED,
      ERROR_LINE,
      '  File "agent/run_agent.py", line 10, in run',
      "    do_thing()",
      "ValueError: nope",
      "2026-07-13 09:41:23,001 INFO agent.run_agent: recovered",
    ]);
    expect(parsed.map((p) => p.classification)).toEqual([
      "info",
      "error",
      "error",
      "error",
      "error",
      "info",
    ]);
    expect(parsed.map((p) => p.isContinuation)).toEqual([
      false,
      false,
      true,
      true,
      true,
      false,
    ]);
  });

  it("returns an empty array for an empty window", () => {
    expect(parseLogLines([])).toEqual([]);
  });
});

describe("classifyLineKeyword", () => {
  it("keeps the loose substring semantics for unstructured lines", () => {
    expect(classifyLineKeyword("FATAL: boom")).toBe("error");
    expect(classifyLineKeyword("Warning: deprecated")).toBe("warning");
    expect(classifyLineKeyword("debug trace on")).toBe("debug");
    expect(classifyLineKeyword("hello")).toBe("info");
  });
});

describe("findAnchorIndex", () => {
  const window = ["a", "b", "c", "d", "e"];

  it("finds the anchor's final line index", () => {
    expect(findAnchorIndex(window, ["b", "c", "d"])).toBe(3);
    expect(findAnchorIndex(window, ["c", "d", "e"])).toBe(4);
  });

  it("supports short anchors (fewer than 3 captured lines)", () => {
    expect(findAnchorIndex(window, ["a"])).toBe(0);
    expect(findAnchorIndex(window, ["d", "e"])).toBe(4);
  });

  it("returns -1 when the anchor scrolled out of the window", () => {
    expect(findAnchorIndex(window, ["x", "y", "z"])).toBe(-1);
    expect(findAnchorIndex([], ["a"])).toBe(-1);
    expect(findAnchorIndex(window, [])).toBe(-1);
  });

  it("prefers the newest occurrence on repetitive logs", () => {
    const repetitive = ["tick", "tock", "tick", "tock", "tick"];
    expect(findAnchorIndex(repetitive, ["tick", "tock"])).toBe(3);
    expect(findAnchorIndex(repetitive, ["tick"])).toBe(4);
  });

  it("does not match a partial suffix overlap", () => {
    expect(findAnchorIndex(["a", "b"], ["b", "c", "d"])).toBe(-1);
  });
});
