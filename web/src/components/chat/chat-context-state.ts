export interface ChatContextEvent {
  payload?: unknown;
  sessionId?: string;
  type: string;
}

export interface ChatContextTodo {
  content: string;
  id: string;
  status: string;
}

export interface ChatContextEvidence {
  context?: string;
  durationS?: number;
  key: string;
  name: string;
  running: boolean;
  summary?: string;
  toolId: string;
}

export interface ChatContextArtifact {
  key: string;
  label: string;
  source: string;
  value: string;
}

export interface ChatContextState {
  artifacts: ChatContextArtifact[];
  connected: boolean;
  cwd: string | null;
  evidence: ChatContextEvidence[];
  running: boolean;
  seq: number;
  sessionId: string | null;
  title: string | null;
  todos: ChatContextTodo[];
}

export const EMPTY_CHAT_CONTEXT_STATE: ChatContextState = {
  artifacts: [],
  connected: false,
  cwd: null,
  evidence: [],
  running: false,
  seq: 0,
  sessionId: null,
  title: null,
  todos: [],
};

const MAX_CONTEXT_ROWS = 20;
const MAX_ARTIFACT_SCAN_NODES = 500;
const ARTIFACT_KEY_RE =
  /(?:^|[._-])(artifact|download|file|image|output|path|target|url)(?:s|$|[._-])/i;
const ARTIFACT_EXT_RE =
  /\.(?:bmp|csv|gif|gz|jpe?g|json|md|mov|mp3|mp4|pdf|png|svg|tar|txt|wav|webp|zip)(?:[?#].*)?$/i;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function trimmed(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function normalizedArtifactValue(value: string): string {
  return value.trim().replace(/[),.;]+$/, "");
}

function looksLikeArtifact(value: string, keyPath: string): boolean {
  if (!value || value.length > 2048 || value.startsWith("data:")) return false;
  const pathLike = /^(?:file:\/\/|\/|~\/|\.\.?\/|[A-Za-z]:[\\/])/.test(value);
  const urlLike = /^https?:\/\//i.test(value);
  if (urlLike) return ARTIFACT_EXT_RE.test(value);
  return (
    pathLike && (ARTIFACT_KEY_RE.test(keyPath) || ARTIFACT_EXT_RE.test(value))
  );
}

function artifactLabel(value: string): string {
  try {
    const url = new URL(value);
    return url.pathname.split("/").filter(Boolean).at(-1) || value;
  } catch {
    return value.split(/[\\/]/).filter(Boolean).at(-1) || value;
  }
}

function collectArtifacts(
  value: unknown,
  source: string,
  found: Map<string, ChatContextArtifact>,
  budget: { remaining: number },
  keyPath = "",
  depth = 0,
): void {
  if (
    found.size >= MAX_CONTEXT_ROWS ||
    budget.remaining <= 0 ||
    depth > 6
  )
    return;
  budget.remaining -= 1;
  if (typeof value === "string") {
    const normalized = normalizedArtifactValue(value);
    if (looksLikeArtifact(normalized, keyPath) && !found.has(normalized)) {
      found.set(normalized, {
        key: normalized,
        label: artifactLabel(normalized),
        source,
        value: normalized,
      });
    }
    return;
  }
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      if (found.size >= MAX_CONTEXT_ROWS || budget.remaining <= 0) break;
      collectArtifacts(
        value[index],
        source,
        found,
        budget,
        `${keyPath}.${index}`,
        depth + 1,
      );
    }
    return;
  }
  const record = asRecord(value);
  if (!record) return;
  for (const [key, child] of Object.entries(record)) {
    if (found.size >= MAX_CONTEXT_ROWS || budget.remaining <= 0) break;
    collectArtifacts(
      child,
      source,
      found,
      budget,
      keyPath ? `${keyPath}.${key}` : key,
      depth + 1,
    );
  }
}

function parseTodos(value: unknown): ChatContextTodo[] | null {
  if (!Array.isArray(value)) return null;
  return value
    .map((entry, index) => {
      const record = asRecord(entry);
      const content = trimmed(record?.content);
      if (!content) return null;
      return {
        content,
        id: trimmed(record?.id) || `todo-${index}`,
        status: trimmed(record?.status) || "pending",
      };
    })
    .filter((todo): todo is ChatContextTodo => todo !== null)
    .slice(0, MAX_CONTEXT_ROWS);
}

function upsertCompletedEvidence(
  state: ChatContextState,
  record: Record<string, unknown> | null,
): { evidence: ChatContextEvidence[]; seq: number } {
  const toolId = trimmed(record?.tool_id);
  const index = toolId
    ? state.evidence.findIndex((row) => row.running && row.toolId === toolId)
    : -1;
  const durationRaw = record?.duration_s;
  const durationS =
    typeof durationRaw === "number" && Number.isFinite(durationRaw)
      ? durationRaw
      : undefined;
  const summary = trimmed(record?.summary) || undefined;
  if (index >= 0) {
    const evidence = state.evidence.slice();
    evidence[index] = {
      ...evidence[index],
      durationS,
      running: false,
      summary,
    };
    return { evidence, seq: state.seq };
  }
  const seq = state.seq + 1;
  return {
    evidence: [
      {
        durationS,
        key: toolId ? `${toolId}#${seq}` : `tool-${seq}`,
        name: trimmed(record?.name) || "tool",
        running: false,
        summary,
        toolId,
      },
      ...state.evidence,
    ].slice(0, MAX_CONTEXT_ROWS),
    seq,
  };
}

function collectEventArtifacts(
  state: ChatContextState,
  record: Record<string, unknown> | null,
  source: string,
): ChatContextArtifact[] {
  const discovered = new Map<string, ChatContextArtifact>();
  const budget = { remaining: MAX_ARTIFACT_SCAN_NODES };
  collectArtifacts(record?.args, source, discovered, budget, "args");
  collectArtifacts(record?.result, source, discovered, budget, "result");
  collectArtifacts(
    record?.files_written,
    source,
    discovered,
    budget,
    "files_written",
  );
  const values = new Set(discovered.keys());
  return [
    ...Array.from(discovered.values()).reverse(),
    ...state.artifacts.filter((artifact) => !values.has(artifact.value)),
  ].slice(0, MAX_CONTEXT_ROWS);
}

/**
 * Project the existing PTY event stream into the four Chat context tabs.
 * This is deliberately a read model: no new model tool, prompt mutation, or
 * synthetic task is introduced just to populate the dashboard.
 */
export function reduceChatContextEvent(
  state: ChatContextState,
  event: ChatContextEvent,
): ChatContextState {
  const record = asRecord(event.payload);
  const sessionId = trimmed(event.sessionId) || state.sessionId;

  switch (event.type) {
    case "session.info":
      return {
        ...state,
        connected: true,
        cwd: trimmed(record?.cwd) || state.cwd,
        running:
          typeof record?.running === "boolean" ? record.running : state.running,
        sessionId,
        title: trimmed(record?.title) || state.title,
      };

    case "tool.start": {
      const toolId = trimmed(record?.tool_id);
      const seq = state.seq + 1;
      return {
        ...state,
        connected: state.connected || !!sessionId,
        evidence: [
          {
            context: trimmed(record?.context) || undefined,
            key: toolId ? `${toolId}#${seq}` : `tool-${seq}`,
            name: trimmed(record?.name) || "tool",
            running: true,
            toolId,
          },
          ...state.evidence,
        ].slice(0, MAX_CONTEXT_ROWS),
        running: true,
        seq,
        sessionId,
      };
    }

    case "tool.complete": {
      const completed = upsertCompletedEvidence(state, record);
      return {
        ...state,
        artifacts: collectEventArtifacts(
          state,
          record,
          trimmed(record?.name) || "tool",
        ),
        connected: state.connected || !!sessionId,
        evidence: completed.evidence,
        seq: completed.seq,
        sessionId,
        todos: parseTodos(record?.todos) ?? state.todos,
      };
    }

    case "subagent.complete":
      return {
        ...state,
        artifacts: collectEventArtifacts(
          state,
          { files_written: record?.files_written },
          trimmed(record?.tool_name) || "subagent",
        ),
        connected: state.connected || !!sessionId,
        sessionId,
      };

    case "message.start":
    case "message.delta":
    case "reasoning.delta":
    case "thinking.delta":
      return {
        ...state,
        connected: state.connected || !!sessionId,
        running: true,
        sessionId,
      };

    case "message.complete":
    case "error":
      return {
        ...state,
        connected: state.connected || !!sessionId,
        running: false,
        sessionId,
      };

    default:
      return sessionId && sessionId !== state.sessionId
        ? { ...state, sessionId }
        : state;
  }
}
