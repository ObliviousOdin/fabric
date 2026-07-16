import { normalizeSessionTitle } from "@/lib/chat-title";

export const EVENT_STREAM_MAX_RECONNECT_ATTEMPTS = 5;

const STREAM_ONLY_EVENT_TYPES = new Set([
  "message.delta",
  "reasoning.delta",
  "thinking.delta",
]);

export interface PtySessionMetadata {
  credentialWarning?: string | null;
  cwd?: string | null;
  model?: string;
  provider?: string;
  title?: string | null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

/**
 * The dashboard rail is an operational summary, not a second transcript.
 * Per-token frames already render in xterm and would otherwise create needless
 * browser work while also crowding out durable tool/status events.
 */
export function isSemanticPtyEvent(type: string): boolean {
  return !STREAM_ONLY_EVENT_TYPES.has(type);
}

/** One-based exponential retry delay, capped and bounded per outage. */
export function eventStreamReconnectDelay(attempt: number): number | null {
  if (
    !Number.isInteger(attempt) ||
    attempt < 1 ||
    attempt > EVENT_STREAM_MAX_RECONNECT_ATTEMPTS
  ) {
    return null;
  }
  return Math.min(250 * 2 ** (attempt - 1), 3_000);
}

/** Metadata carried by the real PTY session's semantic event stream. */
export function ptySessionMetadata(
  type: string,
  payload: unknown,
): PtySessionMetadata | null {
  if (type !== "session.info" && type !== "session.title") return null;
  const record = asRecord(payload);
  if (!record) return null;

  if (type === "session.title") {
    return { title: normalizeSessionTitle(record.title) };
  }

  const cwd = optionalString(record.cwd);
  const credentialWarning = optionalString(record.credential_warning);
  const model = optionalString(record.model);
  const provider = optionalString(record.provider);
  return {
    ...(credentialWarning !== undefined
      ? { credentialWarning: credentialWarning.trim() || null }
      : {}),
    ...(cwd !== undefined ? { cwd: cwd.trim() || null } : {}),
    ...(model !== undefined ? { model } : {}),
    ...(provider !== undefined ? { provider } : {}),
    ...(Object.prototype.hasOwnProperty.call(record, "title")
      ? { title: normalizeSessionTitle(record.title) }
      : {}),
  };
}
