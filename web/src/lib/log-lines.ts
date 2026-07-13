/**
 * Pure log-line grammar for the Logs activity stream (spec L2, no React).
 *
 * Mirrors the backend line grammar exactly — `fabric_logging._LOG_FORMAT`
 * is `%(asctime)s %(levelname)s%(session_tag)s %(name)s: %(message)s`, and
 * the four regexes below are 1:1 ports of `fabric_cli/logs.py`
 * (`_TS_RE`, `_LEVEL_RE`, `_LOGGER_NAME_RE` and the session-tag shape).
 * Keep them in lockstep with the Python side; do not "improve" them here.
 *
 * `mcp` / `desktop` files are raw subprocess/Electron output outside this
 * grammar — parsing degrades to the keyword heuristic for those lines.
 */

export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export type LineClassification = "error" | "warning" | "info" | "debug";

export interface ParsedLogLine {
  /** Verbatim line text — always rendered as-is (copy fidelity, N12). */
  raw: string;
  /** Word-bounded level token, when the line carries one. */
  level: LogLevel | null;
  /** Session id from the ` [tag]` between level and logger name. */
  sessionId: string | null;
  /** Dotted logger name (e.g. `gateway.telegram`), when parseable. */
  loggerName: string | null;
  /** No leading timestamp — traceback/wrapped continuation line. */
  isContinuation: boolean;
  /** Display tone. Continuations inherit the previous line's tone. */
  classification: LineClassification;
}

// `fabric_cli/logs.py` `_TS_RE` — "2026-04-05 22:35:00,123" or without ms.
const TS_RE = /^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}/;

// `_LEVEL_RE` — word-bounded token (" INFO "), so an INFO line whose
// *message* mentions "error" is not misclassified (unlike the old
// substring heuristic, which stays fallback-only).
const LEVEL_RE = /\s(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s/;

// `_LOGGER_NAME_RE` — after level and optional session tag, the next
// non-space token before ":".
const LOGGER_NAME_RE =
  /\s(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)(?:\s+\[.*?\])?\s+(\S+):/;

// Session tag — ` LEVEL [<session_id>] ` (spec §0.1).
const SESSION_TAG_RE = /\s(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\[([^\]]+)\]\s/;

const LEVEL_CLASSIFICATION: Record<LogLevel, LineClassification> = {
  DEBUG: "debug",
  INFO: "info",
  WARNING: "warning",
  ERROR: "error",
  // Folds into the ERROR facet, matching `_LEVEL_ORDER`'s ≥ semantics.
  CRITICAL: "error",
};

/**
 * Substring keyword heuristic — the pre-revamp `classifyLine`, retained as
 * the *fallback* for lines outside the grammar (`mcp`/`desktop` output with
 * no level token). Deliberately loose; the word-bounded token above always
 * wins when present.
 */
export function classifyLineKeyword(line: string): LineClassification {
  const upper = line.toUpperCase();
  if (
    upper.includes("ERROR") ||
    upper.includes("CRITICAL") ||
    upper.includes("FATAL")
  )
    return "error";
  if (upper.includes("WARNING") || upper.includes("WARN")) return "warning";
  if (upper.includes("DEBUG")) return "debug";
  return "info";
}

/**
 * Parse one verbatim line. Pass the previous line's parse as `prev` so
 * continuation lines (no leading timestamp) inherit its classification —
 * tracebacks stay one tone end-to-end instead of flickering per keyword.
 */
export function parseLogLine(raw: string, prev?: ParsedLogLine): ParsedLogLine {
  const isContinuation = !TS_RE.test(raw);
  const level = (LEVEL_RE.exec(raw)?.[1] as LogLevel | undefined) ?? null;
  const sessionId = SESSION_TAG_RE.exec(raw)?.[1] ?? null;
  const loggerName = LOGGER_NAME_RE.exec(raw)?.[1] ?? null;

  let classification: LineClassification;
  if (level) {
    classification = LEVEL_CLASSIFICATION[level];
  } else if (isContinuation && prev) {
    classification = prev.classification;
  } else {
    classification = classifyLineKeyword(raw);
  }

  return { raw, level, sessionId, loggerName, isContinuation, classification };
}

/** Parse a fetched window in order, threading continuation inheritance. */
export function parseLogLines(lines: string[]): ParsedLogLine[] {
  const out: ParsedLogLine[] = [];
  for (const line of lines) {
    out.push(parseLogLine(line, out[out.length - 1]));
  }
  return out;
}

/**
 * Pause-pin overlap diffing (spec L11): find the **last** occurrence of the
 * `anchor` subsequence (up to 3 raw lines captured when follow disengaged)
 * inside a freshly fetched window. Returns the index of the anchor's final
 * line, or -1 when the anchor scrolled out of the window (≥window new lines
 * or file rotation) — the caller degrades to the honest `+N+` label.
 *
 * Searching from the end makes false positives on repetitive logs pick the
 * newest match, which minimizes the delta error (R11: a wrong `+N` is the
 * worst case, never data loss).
 */
export function findAnchorIndex(lines: string[], anchor: string[]): number {
  if (anchor.length === 0 || lines.length < anchor.length) return -1;
  for (let end = lines.length - 1; end >= anchor.length - 1; end--) {
    let matched = true;
    for (let j = 0; j < anchor.length; j++) {
      if (lines[end - anchor.length + 1 + j] !== anchor[j]) {
        matched = false;
        break;
      }
    }
    if (matched) return end;
  }
  return -1;
}
