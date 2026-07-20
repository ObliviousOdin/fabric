import type { GatewayEvent } from "./json-rpc-gateway";

export type RemoteMessageRole = "assistant" | "system" | "tool" | "user";

export interface RemoteTextPart {
  text: string;
  type: "text";
}

export interface RemoteReasoningPart {
  text: string;
  type: "reasoning";
}

export interface RemoteToolPart {
  args: Record<string, unknown>;
  error?: boolean;
  id: string;
  name: string;
  result?: unknown;
  status: "complete" | "running";
  type: "tool";
}

export type RemoteMessagePart =
  | RemoteReasoningPart
  | RemoteTextPart
  | RemoteToolPart;

export interface RemoteMessageMetadata {
  codexReasoningItems?: unknown;
  reasoningDetails?: unknown;
}

export interface RemoteMessage {
  error?: string;
  id: string;
  metadata?: RemoteMessageMetadata;
  parts: RemoteMessagePart[];
  pending?: boolean;
  role: Exclude<RemoteMessageRole, "tool">;
  timestamp?: number;
}

export interface StoredGatewayMessage {
  codex_reasoning_items?: unknown;
  content?: unknown;
  context?: unknown;
  name?: string;
  reasoning?: null | string;
  reasoning_content?: null | string;
  reasoning_details?: unknown;
  role: RemoteMessageRole;
  text?: unknown;
  timestamp?: number;
  tool_call_id?: null | string;
  tool_calls?: unknown;
  tool_name?: string;
}

export interface RemoteSessionSummary {
  id: string;
  message_count: number;
  preview: string;
  source: string;
  started_at: number;
  title: string;
}

export interface RemoteSessionRuntimeInfo {
  branch?: string;
  cwd?: string;
  desktop_contract?: number;
  fast?: boolean;
  lazy?: boolean;
  model?: string;
  personality?: string;
  profile_name?: string;
  provider?: string;
  reasoning_effort?: string;
  running?: boolean;
  service_tier?: string;
  usage?: Record<string, unknown>;
  version?: string;
  work_profile_id?: string;
  yolo?: boolean;
}

export interface RemoteInflightSnapshot {
  assistant?: unknown;
  assistant_text?: unknown;
  reasoning?: unknown;
  reasoning_text?: unknown;
  tools?: unknown;
  user?: unknown;
  user_text?: unknown;
}

export interface RemoteSessionResumePayload {
  history_version?: number;
  info?: RemoteSessionRuntimeInfo;
  inflight?: null | RemoteInflightSnapshot;
  message_count?: number;
  messages?: StoredGatewayMessage[];
  pending_interactions?: Array<{
    payload?: RemoteGatewayEventPayload;
    type: string;
  }>;
  resumed?: string;
  running?: boolean;
  session_id: string;
  session_key?: string;
  started_at?: number;
  status?: string;
  stored_session_id?: string;
}

export type RemoteBlockingPrompt =
  | {
      choices: null | string[];
      question: string;
      requestId: string;
      type: "clarify";
    }
  | {
      allowPermanent: boolean;
      command: string;
      description: string;
      requestId: string;
      type: "approval";
    }
  | {
      requestId: string;
      type: "sudo";
    }
  | {
      envVar: string;
      prompt: string;
      requestId: string;
      type: "secret";
    };

export interface RemoteSessionState {
  pendingInteractions: RemoteBlockingPrompt[];
  error: null | string;
  historyVersion: null | number;
  info: RemoteSessionRuntimeInfo;
  messages: RemoteMessage[];
  needsAuthoritativeResume: boolean;
  persistenceWarning: null | string;
  running: boolean;
  runtimeSessionId: null | string;
  status: string;
  storedSessionId: null | string;
}

export interface RemoteGatewayEventPayload {
  allow_permanent?: boolean;
  args?: unknown;
  arguments?: unknown;
  branch?: string;
  choices?: null | unknown[];
  command?: string;
  context?: string;
  cwd?: string;
  description?: string;
  duration_s?: number;
  env_var?: string;
  error?: boolean | string;
  fast?: boolean;
  history_persisted?: boolean;
  history_version?: number;
  id?: string;
  inline_diff?: string;
  input?: unknown;
  kind?: string;
  message?: string;
  model?: string;
  name?: string;
  personality?: string;
  preview?: string;
  prompt?: string;
  provider?: string;
  question?: string;
  reasoning_effort?: string;
  rendered?: string;
  request_id?: string;
  result?: unknown;
  running?: boolean;
  service_tier?: string;
  status?: string;
  summary?: string;
  text?: string;
  title?: string;
  tool_call_id?: string;
  tool_id?: string;
  usage?: Record<string, unknown>;
  warning?: string;
  work_profile_id?: string;
  yolo?: boolean;
}

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const asString = (value: unknown): string =>
  typeof value === "string" ? value : "";

function textFromUnknown(value: unknown, depth = 0): string {
  if (typeof value === "string") {
    return value;
  }

  if (value === null || value === undefined || depth > 3) {
    return "";
  }

  if (Array.isArray(value)) {
    return value.map((item) => textFromUnknown(item, depth + 1)).join("");
  }

  const row = record(value);
  if (row) {
    for (const key of ["text", "output_text", "content", "message", "summary"]) {
      const nested = textFromUnknown(row[key], depth + 1);
      if (nested) {
        return nested;
      }
    }

    return "";
  }

  return String(value);
}

function parseObject(value: unknown): Record<string, unknown> {
  const direct = record(value);
  if (direct) {
    return direct;
  }

  if (typeof value !== "string" || !value.trim()) {
    return {};
  }

  try {
    return record(JSON.parse(value)) ?? {};
  } catch {
    return {};
  }
}

function parseResult(value: unknown): unknown {
  if (typeof value !== "string") {
    return value;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return value;
  }
}

function reasoningText(message: StoredGatewayMessage): string {
  if (message.reasoning) {
    return message.reasoning;
  }
  if (message.reasoning_content) {
    return message.reasoning_content;
  }
  return textFromUnknown(message.reasoning_details);
}

function storedToolPart(call: unknown, fallbackId: string): RemoteToolPart {
  const row = record(call) ?? {};
  const fn = record(row.function);
  const input = record(row.input);
  const id = String(row.id || row.tool_call_id || fallbackId);
  const name = String(row.name || row.tool_name || fn?.name || input?.name || "tool");
  const args = parseObject(
    fn?.arguments ?? row.arguments ?? row.args ?? input?.arguments ?? row.input,
  );

  return {
    args,
    id,
    name,
    status: "running",
    type: "tool",
  };
}

function toolMessageResult(message: StoredGatewayMessage): unknown {
  return parseResult(
    message.content ?? message.text ?? message.context ?? message.name ?? "",
  );
}

function applyStoredToolResult(
  messages: RemoteMessage[],
  message: StoredGatewayMessage,
): boolean {
  const wantedId = message.tool_call_id || "";
  const wantedName = message.tool_name || message.name || "tool";

  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const candidate = messages[messageIndex];
    if (candidate.role !== "assistant") {
      continue;
    }

    const partIndex = candidate.parts.findIndex(
      (part) =>
        part.type === "tool" &&
        ((wantedId && part.id === wantedId) || (!wantedId && part.name === wantedName)),
    );
    if (partIndex < 0) {
      continue;
    }

    const parts = [...candidate.parts];
    const part = parts[partIndex] as RemoteToolPart;
    parts[partIndex] = {
      ...part,
      error: false,
      result: toolMessageResult(message),
      status: "complete",
    };
    messages[messageIndex] = { ...candidate, parts };
    return true;
  }

  return false;
}

function messageId(namespace: string, role: RemoteMessageRole, index: number): string {
  return `${namespace}-${index}-${role}`;
}

function hasTool(parts: RemoteMessagePart[]): boolean {
  return parts.some((part) => part.type === "tool");
}

export function normalizeStoredMessages(
  messages: StoredGatewayMessage[],
  namespace = "stored",
): RemoteMessage[] {
  const result: RemoteMessage[] = [];

  messages.forEach((message, index) => {
    if (message.role === "tool") {
      if (applyStoredToolResult(result, message)) {
        return;
      }

      const tool: RemoteToolPart = {
        args: {},
        id: message.tool_call_id || `${namespace}-tool-message-${index}`,
        name: message.tool_name || message.name || "tool",
        result: toolMessageResult(message),
        status: "complete",
        type: "tool",
      };
      const previous = result.at(-1);
      if (previous?.role === "assistant") {
        result[result.length - 1] = {
          ...previous,
          parts: [...previous.parts, tool],
          timestamp: message.timestamp ?? previous.timestamp,
        };
      } else {
        result.push({
          id: messageId(namespace, message.role, index),
          parts: [tool],
          role: "assistant",
          timestamp: message.timestamp,
        });
      }
      return;
    }

    const parts: RemoteMessagePart[] = [];
    const reasoning = message.role === "assistant" ? reasoningText(message) : "";
    const content = textFromUnknown(
      message.content ?? message.text ?? message.context ?? message.name,
    );

    if (reasoning) {
      parts.push({ text: reasoning, type: "reasoning" });
    }
    if (content) {
      parts.push({ text: content, type: "text" });
    }
    if (message.role === "assistant" && Array.isArray(message.tool_calls)) {
      parts.push(
        ...message.tool_calls.map((call, callIndex) =>
          storedToolPart(call, `${namespace}-tool-${index}-${callIndex}`),
        ),
      );
    }

    if (!parts.length) {
      return;
    }

    const metadata: RemoteMessageMetadata = {};
    if (message.codex_reasoning_items !== undefined) {
      metadata.codexReasoningItems = message.codex_reasoning_items;
    }
    if (message.reasoning_details !== undefined) {
      metadata.reasoningDetails = message.reasoning_details;
    }

    const next: RemoteMessage = {
      id: messageId(namespace, message.role, index),
      ...(Object.keys(metadata).length ? { metadata } : {}),
      parts,
      role: message.role,
      timestamp: message.timestamp,
    };
    const previous = result.at(-1);

    if (
      next.role === "assistant" &&
      previous?.role === "assistant" &&
      (hasTool(previous.parts) || hasTool(next.parts))
    ) {
      result[result.length - 1] = {
        ...previous,
        metadata: { ...previous.metadata, ...next.metadata },
        parts: [...previous.parts, ...next.parts],
        timestamp: next.timestamp ?? previous.timestamp,
      };
      return;
    }

    result.push(next);
  });

  return result;
}

export function createEmptyRemoteSession(): RemoteSessionState {
  return {
    pendingInteractions: [],
    error: null,
    historyVersion: 0,
    info: {},
    messages: [],
    needsAuthoritativeResume: false,
    persistenceWarning: null,
    running: false,
    runtimeSessionId: null,
    status: "idle",
    storedSessionId: null,
  };
}

function lastAssistantIndex(messages: RemoteMessage[]): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === "assistant") {
      return index;
    }
    if (messages[index].role === "user") {
      break;
    }
  }
  return -1;
}

function ensureStreamingAssistant(messages: RemoteMessage[]): {
  index: number;
  messages: RemoteMessage[];
} {
  const existingIndex = lastAssistantIndex(messages);
  if (existingIndex >= 0 && messages[existingIndex].pending) {
    return { index: existingIndex, messages };
  }

  const next = [...messages];
  next.push({
    id: `assistant-live-${next.length}`,
    parts: [],
    pending: true,
    role: "assistant",
  });
  return { index: next.length - 1, messages: next };
}

function appendStreamingPart(
  messages: RemoteMessage[],
  type: "reasoning" | "text",
  delta: string,
  replace = false,
): RemoteMessage[] {
  if (!delta && !replace) {
    return messages;
  }

  const ensured = ensureStreamingAssistant(messages);
  const next = [...ensured.messages];
  const assistant = next[ensured.index];
  const parts = [...assistant.parts];
  let targetIndex = -1;

  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index];
    if (part.type === type) {
      targetIndex = index;
      break;
    }
    if (part.type === "tool") {
      break;
    }
  }

  if (targetIndex >= 0) {
    const current = parts[targetIndex] as RemoteReasoningPart | RemoteTextPart;
    parts[targetIndex] = {
      ...current,
      text: replace ? delta : `${current.text}${delta}`,
    };
  } else if (delta) {
    parts.push({ text: delta, type });
  }

  next[ensured.index] = { ...assistant, parts, pending: true };
  return next;
}

function liveToolArgs(payload: RemoteGatewayEventPayload): Record<string, unknown> {
  const input = parseObject(payload.input);
  const fn = record(input.function);
  const nested = parseObject(
    input.args ?? input.arguments ?? input.parameters ?? fn?.arguments ?? fn?.args,
  );
  return {
    ...input,
    ...nested,
    ...parseObject(payload.arguments),
    ...parseObject(payload.args),
    ...(payload.context ? { context: payload.context } : {}),
    ...(payload.preview ? { preview: payload.preview } : {}),
  };
}

function liveToolResult(payload: RemoteGatewayEventPayload): unknown {
  const parsed = parseResult(payload.result);
  if (record(parsed)) {
    return {
      ...(parsed as Record<string, unknown>),
      ...(payload.inline_diff ? { inline_diff: payload.inline_diff } : {}),
      ...(payload.summary ? { summary: payload.summary } : {}),
      ...(payload.message ? { message: payload.message } : {}),
      ...(payload.duration_s !== undefined
        ? { duration_s: payload.duration_s }
        : {}),
      ...(payload.error ? { error: payload.error } : {}),
    };
  }
  return parsed ?? payload.summary ?? payload.message ?? payload.preview ?? "";
}

function upsertLiveTool(
  messages: RemoteMessage[],
  payload: RemoteGatewayEventPayload,
  status: "complete" | "running",
): RemoteMessage[] {
  const ensured = ensureStreamingAssistant(messages);
  const next = [...ensured.messages];
  const assistant = next[ensured.index];
  const parts = [...assistant.parts];
  const stableId = payload.tool_id || payload.tool_call_id || payload.id || "";
  const name = payload.name || "tool";
  let partIndex = stableId
    ? parts.findIndex((part) => part.type === "tool" && part.id === stableId)
    : -1;

  if (partIndex < 0) {
    const candidates = parts.flatMap((part, index) =>
      part.type === "tool" && part.name === name && part.status === "running"
        ? [index]
        : [],
    );
    partIndex =
      status === "complete" ? (candidates[0] ?? -1) : (candidates.at(-1) ?? -1);
  }

  const previous = partIndex >= 0 ? (parts[partIndex] as RemoteToolPart) : null;
  const hasResult =
    payload.result !== undefined ||
    payload.inline_diff !== undefined ||
    payload.summary !== undefined ||
    payload.message !== undefined ||
    payload.duration_s !== undefined ||
    payload.error !== undefined;
  const tool: RemoteToolPart = {
    args: { ...(previous?.args ?? {}), ...liveToolArgs(payload) },
    ...(previous?.error !== undefined ? { error: previous.error } : {}),
    ...(previous?.result !== undefined ? { result: previous.result } : {}),
    ...(status === "complete"
      ? {
          error: Boolean(payload.error),
          ...(hasResult ? { result: liveToolResult(payload) } : {}),
        }
      : {}),
    id: stableId || previous?.id || `live-tool-${name}-${ensured.index}-${parts.length}`,
    name,
    status,
    type: "tool",
  };

  if (partIndex >= 0) {
    parts[partIndex] = tool;
  } else {
    parts.push(tool);
  }
  next[ensured.index] = { ...assistant, parts, pending: true };
  return next;
}

export function remoteMessageText(message: RemoteMessage): string {
  return message.parts
    .filter((part): part is RemoteTextPart => part.type === "text")
    .map((part) => part.text)
    .join("");
}

function completeAssistant(
  messages: RemoteMessage[],
  finalText: string,
): { messages: RemoteMessage[]; needsAuthoritativeResume: boolean } {
  const ensured = ensureStreamingAssistant(messages);
  const next = [...ensured.messages];
  const assistant = next[ensured.index];
  const streamedText = remoteMessageText(assistant);
  let needsAuthoritativeResume = false;
  let parts = [...assistant.parts];

  if (finalText && !streamedText) {
    parts.push({ text: finalText, type: "text" });
  } else if (finalText && finalText !== streamedText) {
    needsAuthoritativeResume = true;
  }

  next[ensured.index] = { ...assistant, parts, pending: false };
  return { messages: next, needsAuthoritativeResume };
}

export function appendRemoteSystemMessage(
  state: RemoteSessionState,
  text: string,
): RemoteSessionState {
  if (!text.trim()) {
    return state;
  }

  return {
    ...state,
    messages: [
      ...state.messages,
      {
        id: `system-${state.messages.length}`,
        parts: [{ text, type: "text" }],
        role: "system",
      },
    ],
  };
}

export function appendOptimisticUserMessage(
  state: RemoteSessionState,
  text: string,
): RemoteSessionState {
  return {
    ...state,
    error: null,
    messages: [
      ...state.messages,
      {
        id: `user-${state.messages.length}`,
        parts: [{ text, type: "text" }],
        role: "user",
      },
    ],
    running: true,
    status: "working",
  };
}

function runtimeInfoPatch(
  payload: RemoteGatewayEventPayload,
): RemoteSessionRuntimeInfo {
  const patch: RemoteSessionRuntimeInfo = {};
  for (const [source, target] of [
    ["model", "model"],
    ["provider", "provider"],
    ["cwd", "cwd"],
    ["branch", "branch"],
    ["personality", "personality"],
    ["reasoning_effort", "reasoning_effort"],
    ["service_tier", "service_tier"],
    ["work_profile_id", "work_profile_id"],
  ] as const) {
    if (typeof payload[source] === "string") {
      patch[target] = payload[source] as never;
    }
  }
  for (const key of ["fast", "yolo", "running"] as const) {
    if (typeof payload[key] === "boolean") {
      patch[key] = payload[key];
    }
  }
  if (record(payload.usage)) {
    patch.usage = payload.usage;
  }
  return patch;
}

function enqueueInteraction(
  state: RemoteSessionState,
  prompt: RemoteBlockingPrompt,
): RemoteBlockingPrompt[] {
  const key = `${prompt.type}:${prompt.requestId}`;
  return [
    ...state.pendingInteractions.filter((candidate) => {
      const candidateKey = `${candidate.type}:${candidate.requestId}`;
      return candidateKey !== key;
    }),
    prompt,
  ];
}

export function reduceRemoteSessionEvent(
  state: RemoteSessionState,
  event: GatewayEvent<RemoteGatewayEventPayload>,
): RemoteSessionState {
  const payload = event.payload ?? {};

  switch (event.type) {
    case "gateway.ready":
      return state;
    case "session.info": {
      const running =
        typeof payload.running === "boolean" ? payload.running : state.running;
      return {
        ...state,
        info: { ...state.info, ...runtimeInfoPatch(payload) },
        running,
        status: running ? "working" : state.status,
      };
    }
    case "message.start":
      return {
        ...state,
        pendingInteractions: [],
        error: null,
        messages: ensureStreamingAssistant(state.messages).messages,
        running: true,
        status: "working",
      };
    case "message.delta":
      return {
        ...state,
        messages: appendStreamingPart(state.messages, "text", asString(payload.text)),
        running: true,
        status: "working",
      };
    case "reasoning.delta":
      return {
        ...state,
        messages: appendStreamingPart(
          state.messages,
          "reasoning",
          asString(payload.text),
        ),
        running: true,
        status: "working",
      };
    case "reasoning.available":
      return {
        ...state,
        messages: appendStreamingPart(
          state.messages,
          "reasoning",
          asString(payload.text),
          true,
        ),
      };
    case "tool.start":
    case "tool.progress":
    case "tool.generating":
      return {
        ...state,
        messages: upsertLiveTool(state.messages, payload, "running"),
        running: true,
        status: "working",
      };
    case "tool.complete":
      return {
        ...state,
        messages: upsertLiveTool(state.messages, payload, "complete"),
      };
    case "clarify.request": {
      const requestId = asString(payload.request_id).trim();
      const question = asString(payload.question);
      if (!requestId || !question) {
        return state;
      }
      const prompt: RemoteBlockingPrompt = {
        choices: Array.isArray(payload.choices)
          ? payload.choices.filter(
              (choice): choice is string => typeof choice === "string",
            )
          : null,
        question,
        requestId,
        type: "clarify",
      };
      return {
        ...state,
        pendingInteractions: enqueueInteraction(state, prompt),
        status: "waiting",
      };
    }
    case "approval.request": {
      const command = asString(payload.command);
      const description = asString(payload.description) || "Dangerous command";
      const requestId = asString(payload.request_id).trim();
      if (!requestId) {
        return state;
      }
      return {
        ...state,
        pendingInteractions: enqueueInteraction(state, {
          allowPermanent: payload.allow_permanent !== false,
          command,
          description,
          requestId,
          type: "approval",
        }),
        status: "waiting",
      };
    }
    case "sudo.request": {
      const requestId = asString(payload.request_id).trim();
      return requestId
        ? {
            ...state,
            pendingInteractions: enqueueInteraction(state, {
              requestId,
              type: "sudo",
            }),
            status: "waiting",
          }
        : state;
    }
    case "secret.request": {
      const requestId = asString(payload.request_id).trim();
      return requestId
        ? {
            ...state,
            pendingInteractions: enqueueInteraction(state, {
              envVar: asString(payload.env_var),
              prompt: asString(payload.prompt),
              requestId,
              type: "secret",
            }),
            status: "waiting",
          }
        : state;
    }
    case "message.complete": {
      const finalText = asString(payload.text) || asString(payload.rendered);
      const completed = completeAssistant(state.messages, finalText);
      const persisted = payload.history_persisted !== false;
      return {
        ...state,
        pendingInteractions: [],
        historyVersion:
          typeof payload.history_version === "number"
            ? payload.history_version
            : state.historyVersion,
        messages: completed.messages,
        needsAuthoritativeResume:
          state.needsAuthoritativeResume ||
          (persisted && completed.needsAuthoritativeResume),
        persistenceWarning: persisted
          ? null
          : asString(payload.warning) ||
            "This response is visible but was not saved to session history.",
        running: false,
        status: "idle",
      };
    }
    case "status.update":
      return {
        ...state,
        status: payload.kind === "compacting" ? "compacting" : state.status,
      };
    case "review.summary":
      return appendRemoteSystemMessage(state, asString(payload.text));
    case "background.complete":
      return appendRemoteSystemMessage(
        state,
        asString(payload.message) || asString(payload.text),
      );
    case "error": {
      const error = asString(payload.message) || "Fabric reported an error";
      const ensured = ensureStreamingAssistant(state.messages);
      const messages = [...ensured.messages];
      messages[ensured.index] = {
        ...messages[ensured.index],
        error,
        pending: false,
      };
      return {
        ...state,
        pendingInteractions: [],
        error,
        messages,
        running: false,
        status: "error",
      };
    }
    default:
      return state;
  }
}

const BUFFERED_TURN_EVENT_TYPES = new Set([
  "approval.request",
  "clarify.request",
  "message.delta",
  "message.start",
  "reasoning.available",
  "reasoning.delta",
  "secret.request",
  "status.update",
  "sudo.request",
  "thinking.delta",
  "tool.complete",
  "tool.generating",
  "tool.progress",
  "tool.start",
]);

export interface RemoteSessionReplayResult {
  deferredEvents: GatewayEvent<RemoteGatewayEventPayload>[];
  state: RemoteSessionState;
}

/** Reconcile events buffered behind an authoritative session.resume snapshot. */
export function replayRemoteSessionEvents(
  initialState: RemoteSessionState,
  events: GatewayEvent<RemoteGatewayEventPayload>[],
  runtimeSessionId: string,
): RemoteSessionReplayResult {
  let state = initialState;
  let turn: GatewayEvent<RemoteGatewayEventPayload>[] = [];
  const deferredEvents: GatewayEvent<RemoteGatewayEventPayload>[] = [];

  const flushTurn = () => {
    for (const event of turn) {
      state = reduceRemoteSessionEvent(state, event);
    }
    turn = [];
  };

  for (const event of events) {
    if (event.session_id && event.session_id !== runtimeSessionId) {
      deferredEvents.push(event);
      continue;
    }

    if (event.type === "message.complete") {
      const payload = event.payload ?? {};
      const version = payload.history_version;
      const covered =
        payload.history_persisted === true &&
        state.historyVersion !== null &&
        typeof version === "number" &&
        version <= state.historyVersion;

      if (covered) {
        // The snapshot already contains the whole turn. Dropping only the
        // completion would still duplicate its buffered deltas and tools.
        turn = [];
        state = {
          ...state,
          pendingInteractions: [],
          persistenceWarning: null,
          running: false,
          status: "idle",
        };
        continue;
      }

      const unversionedSnapshot =
        payload.history_persisted === true &&
        state.historyVersion === null &&
        turn.length > 0;
      flushTurn();
      state = reduceRemoteSessionEvent(state, event);
      if (unversionedSnapshot) {
        state = { ...state, needsAuthoritativeResume: true };
      }
      continue;
    }

    if (BUFFERED_TURN_EVENT_TYPES.has(event.type)) {
      turn.push(event);
      continue;
    }

    flushTurn();
    state = reduceRemoteSessionEvent(state, event);
  }

  flushTurn();
  return { deferredEvents, state };
}

function appendInflightSnapshot(
  messages: RemoteMessage[],
  snapshot: RemoteInflightSnapshot,
): RemoteMessage[] {
  let next = messages;
  const userText = textFromUnknown(snapshot.user ?? snapshot.user_text).trim();
  const lastUser = [...next].reverse().find((message) => message.role === "user");
  if (userText && (!lastUser || remoteMessageText(lastUser).trim() !== userText)) {
    next = [
      ...next,
      {
        id: `inflight-user-${next.length}`,
        parts: [{ text: userText, type: "text" }],
        role: "user",
      },
    ];
  }

  const reasoning = textFromUnknown(
    snapshot.reasoning ?? snapshot.reasoning_text,
  );
  const assistant = textFromUnknown(
    snapshot.assistant ?? snapshot.assistant_text,
  );
  if (reasoning) {
    next = appendStreamingPart(next, "reasoning", reasoning);
  }
  if (assistant) {
    next = appendStreamingPart(next, "text", assistant);
  }

  if (Array.isArray(snapshot.tools)) {
    for (const tool of snapshot.tools) {
      const payload = (record(tool) ?? {}) as RemoteGatewayEventPayload;
      next = upsertLiveTool(
        next,
        payload,
        payload.result !== undefined ? "complete" : "running",
      );
    }
  }
  return next;
}

export function hydrateRemoteSession(
  payload: RemoteSessionResumePayload,
  previous: RemoteSessionState = createEmptyRemoteSession(),
): RemoteSessionState {
  const running = payload.running ?? payload.info?.running ?? false;
  const namespace =
    payload.session_key ||
    payload.stored_session_id ||
    payload.resumed ||
    payload.session_id;
  let messages = normalizeStoredMessages(payload.messages ?? [], namespace);
  if (running && payload.inflight) {
    messages = appendInflightSnapshot(messages, payload.inflight);
  }

  let hydrated: RemoteSessionState = {
    pendingInteractions: [],
    error: null,
    // Versions are scoped to the returned runtime binding. Never carry a
    // barrier across reconnects or compression-continuation targets.
    historyVersion:
      typeof payload.history_version === "number" ? payload.history_version : null,
    info: { ...previous.info, ...payload.info, running },
    messages,
    needsAuthoritativeResume: false,
    persistenceWarning: null,
    running,
    runtimeSessionId: payload.session_id,
    status: payload.status || (running ? "working" : "idle"),
    storedSessionId:
      payload.session_key ||
      payload.stored_session_id ||
      payload.resumed ||
      previous.storedSessionId,
  };
  for (const interaction of payload.pending_interactions ?? []) {
    hydrated = reduceRemoteSessionEvent(hydrated, {
      payload: interaction.payload,
      session_id: payload.session_id,
      type: interaction.type,
    });
  }
  return hydrated;
}
