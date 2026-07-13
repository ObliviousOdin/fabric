/**
 * Activity-feed state machine for the Chat rail (CH3) — pure module, no
 * React. `ChatSidebar` feeds every `/api/events` frame through
 * `reduceActivityEvent` and throttle-flushes the result into state, so a
 * `reasoning.delta` token storm costs ref writes, not render storms.
 *
 * Event payload shapes verified against `tui_gateway/server.py` `_emit`
 * call sites (rebroadcast verbatim by `fabric_cli/web_server.py`):
 *
 *   tool.start        {tool_id, name, context, args_text?}
 *   tool.complete     {tool_id, name, args, duration_s?, result, summary?, …}
 *   message.start     (no payload) / message.delta|complete {text, rendered?}
 *   reasoning.delta   {text, verbose?}      thinking.delta {text}
 *   status.update     {kind, text}
 *   approval.request  {command?, …}
 *
 * The rail is a ticker, not a transcript: no result bodies, no
 * `inline_diff` (the terminal already renders those).
 */

export type ActivityStateLine = "responding" | "reasoning";

export interface ToolFeedRow {
  rowKind: "tool";
  /** Stable render key (tool_id, seq-suffixed when the id is missing). */
  key: string;
  toolId: string;
  name: string;
  context?: string;
  running: boolean;
  durationS?: number;
  summary?: string;
  startedAtMs: number;
}

export interface StatusFeedRow {
  rowKind: "status";
  key: string;
  kind: string;
  text: string;
  atMs: number;
}

export type ActivityFeedRow = ToolFeedRow | StatusFeedRow;

export interface ActivityFeedState {
  /** Newest first. Bounded: ≤ MAX_TOOL_ROWS tool rows, ≤ MAX_FEED_ROWS total. */
  rows: ActivityFeedRow[];
  /** Single mutually-exclusive transient state line at the feed head. */
  stateLine: ActivityStateLine | null;
  /** approval.request pin — cleared by ANY subsequent event (CH3). */
  approvalPending: boolean;
  /** False until the first activity event: the card stays hidden (CH11). */
  seenAny: boolean;
  /** Monotonic key source for rows without a natural id. */
  seq: number;
}

/** FIFO retention for tool rows (CH3: "keep the last 20 tool rows"). */
export const MAX_TOOL_ROWS = 20;
/** Hard cap on the whole list so status rows can't grow it unboundedly. */
export const MAX_FEED_ROWS = 40;

export const EMPTY_ACTIVITY_FEED: ActivityFeedState = {
  rows: [],
  stateLine: null,
  approvalPending: false,
  seenAny: false,
  seq: 0,
};

function asRecord(payload: unknown): Record<string, unknown> | null {
  return payload && typeof payload === "object"
    ? (payload as Record<string, unknown>)
    : null;
}

function asTrimmedString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** Prepend a row, then trim to the tool/total retention bounds. */
function prependRow(
  rows: ActivityFeedRow[],
  row: ActivityFeedRow,
): ActivityFeedRow[] {
  const next: ActivityFeedRow[] = [];
  let toolCount = 0;
  for (const candidate of [row, ...rows]) {
    if (next.length >= MAX_FEED_ROWS) break;
    if (candidate.rowKind === "tool") {
      if (toolCount >= MAX_TOOL_ROWS) continue;
      toolCount += 1;
    }
    next.push(candidate);
  }
  return next;
}

/** Compact `1.8s` / `42s` / `1m 42s` mono duration for tool.complete. */
export function formatToolDuration(durationS: number): string {
  if (!Number.isFinite(durationS) || durationS < 0) return "—";
  if (durationS < 10) return `${durationS.toFixed(1)}s`;
  if (durationS < 60) return `${Math.round(durationS)}s`;
  const minutes = Math.floor(durationS / 60);
  return `${minutes}m ${Math.round(durationS % 60)}s`;
}

/** Compact token/context count: 200000 → `200k`, 1200000 → `1.2m`. */
export function formatCompactCount(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "";
  if (n >= 1_000_000) {
    const m = n / 1_000_000;
    return `${m >= 10 || Number.isInteger(m) ? Math.round(m) : m.toFixed(1)}m`;
  }
  if (n >= 1_000) {
    const k = n / 1_000;
    return `${k >= 10 || Number.isInteger(k) ? Math.round(k) : k.toFixed(1)}k`;
  }
  return String(n);
}

/**
 * Fold one event into the feed. Returns the SAME state reference when the
 * event changes nothing observable (e.g. another `reasoning.delta` while
 * the "reasoning…" line is already up) so callers can skip re-renders.
 *
 * Any event type may be passed in — unrecognized ones only clear a pending
 * approval pin, matching CH3's "until any subsequent event arrives".
 */
export function reduceActivityEvent(
  state: ActivityFeedState,
  type: string,
  payload: unknown,
  nowMs: number = Date.now(),
): ActivityFeedState {
  const record = asRecord(payload);

  switch (type) {
    case "tool.start": {
      const name = asTrimmedString(record?.name) || "tool";
      const toolId = asTrimmedString(record?.tool_id);
      const seq = state.seq + 1;
      const row: ToolFeedRow = {
        rowKind: "tool",
        key: toolId || `tool-${seq}`,
        toolId,
        name,
        context: asTrimmedString(record?.context) || undefined,
        running: true,
        startedAtMs: nowMs,
      };
      return {
        ...state,
        rows: prependRow(state.rows, row),
        // A tool run supersedes the responding/reasoning state line.
        stateLine: null,
        approvalPending: false,
        seenAny: true,
        seq,
      };
    }

    case "tool.complete": {
      const toolId = asTrimmedString(record?.tool_id);
      const durationRaw = record?.duration_s;
      const durationS =
        typeof durationRaw === "number" && Number.isFinite(durationRaw)
          ? durationRaw
          : undefined;
      const summary = asTrimmedString(record?.summary) || undefined;
      const index = toolId
        ? state.rows.findIndex(
            (r) => r.rowKind === "tool" && r.running && r.toolId === toolId,
          )
        : -1;
      if (index >= 0) {
        const rows = state.rows.slice();
        rows[index] = {
          ...(rows[index] as ToolFeedRow),
          running: false,
          durationS,
          summary,
        };
        return {
          ...state,
          rows,
          approvalPending: false,
          seenAny: true,
        };
      }
      // Unmatched completion (missed start / subagent mirror): append done.
      const seq = state.seq + 1;
      const row: ToolFeedRow = {
        rowKind: "tool",
        key: toolId || `tool-${seq}`,
        toolId,
        name: asTrimmedString(record?.name) || "tool",
        running: false,
        durationS,
        summary,
        startedAtMs: nowMs,
      };
      return {
        ...state,
        rows: prependRow(state.rows, row),
        approvalPending: false,
        seenAny: true,
        seq,
      };
    }

    case "message.start":
    case "message.delta": {
      if (
        state.stateLine === "responding" &&
        !state.approvalPending &&
        state.seenAny
      ) {
        return state;
      }
      return {
        ...state,
        stateLine: "responding",
        approvalPending: false,
        seenAny: true,
      };
    }

    case "message.complete": {
      if (state.stateLine === null && !state.approvalPending && state.seenAny) {
        return state;
      }
      return {
        ...state,
        stateLine: null,
        approvalPending: false,
        seenAny: true,
      };
    }

    case "reasoning.delta":
    case "thinking.delta": {
      if (
        state.stateLine === "reasoning" &&
        !state.approvalPending &&
        state.seenAny
      ) {
        return state;
      }
      return {
        ...state,
        stateLine: "reasoning",
        approvalPending: false,
        seenAny: true,
      };
    }

    case "status.update": {
      const text = asTrimmedString(record?.text);
      if (!text) {
        return state.approvalPending
          ? { ...state, approvalPending: false }
          : state;
      }
      const seq = state.seq + 1;
      const row: StatusFeedRow = {
        rowKind: "status",
        key: `status-${seq}`,
        kind: asTrimmedString(record?.kind) || "status",
        text,
        atMs: nowMs,
      };
      return {
        ...state,
        rows: prependRow(state.rows, row),
        approvalPending: false,
        seenAny: true,
        seq,
      };
    }

    case "approval.request":
      if (state.approvalPending) return state;
      return { ...state, approvalPending: true, seenAny: true };

    default:
      // Non-activity events (session.info, moa.*, …) only lift the pin.
      return state.approvalPending
        ? { ...state, approvalPending: false }
        : state;
  }
}
