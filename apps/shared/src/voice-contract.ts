export const TRANSCRIPTION_SCHEMA = "fabric.transcription" as const;
export const TRANSCRIPTION_VERSION = 1 as const;
export const PHONE_AUDIO_CONTRACT = "fabric.phone_audio" as const;
export const PHONE_AUDIO_VERSION = 1 as const;

export const TRANSCRIPTION_STATUSES = [
  "completed",
  "no_speech",
  "cancelled",
  "failed",
] as const;
export const PHONE_AUDIO_MODES = [
  "dictate",
  "voice_note",
  "ask_fabric",
  "chat",
] as const;

export type TranscriptionStatus = (typeof TRANSCRIPTION_STATUSES)[number];
export type PhoneAudioMode = (typeof PHONE_AUDIO_MODES)[number];

export interface TranscriptionSegmentV1 {
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface TranscriptionErrorV1 {
  code: string;
  message: string;
  retryable: boolean;
}

export interface TranscriptionResultV1 {
  schema: typeof TRANSCRIPTION_SCHEMA;
  version: typeof TRANSCRIPTION_VERSION;
  request_id: string;
  status: TranscriptionStatus;
  text: string;
  provider?: string;
  language?: string;
  duration_ms?: number;
  processing_ms?: number;
  model?: string;
  segments: readonly TranscriptionSegmentV1[];
  warnings: readonly string[];
  error?: TranscriptionErrorV1;
}

export interface PhoneAudioEnvelopeV1 {
  contract: typeof PHONE_AUDIO_CONTRACT;
  version: typeof PHONE_AUDIO_VERSION;
  capture_id: string;
  mode: PhoneAudioMode;
  mime_type: string;
  duration_ms: number;
  result: TranscriptionResultV1;
}

export type VoiceContractParseResult<T> =
  | { kind: "verified"; value: T }
  | { kind: "incompatible"; contract: string; version: number }
  | { kind: "invalid"; message: string };

const MAX_AUDIO_MS = 3_600_000;
const MAX_TEXT_CHARS = 1_000_000;

class VoiceDecodeError extends Error {}
class VoiceIncompatibleError extends Error {
  readonly contract: string;
  readonly version: number;

  constructor(contract: string, version: number) {
    super(`${contract} version ${version} is incompatible.`);
    this.contract = contract;
    this.version = version;
  }
}

function fail(message: string): never {
  throw new VoiceDecodeError(message);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return fail(`${path} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function required(
  raw: Record<string, unknown>,
  key: string,
  path: string,
): unknown {
  if (!Object.prototype.hasOwnProperty.call(raw, key)) {
    return fail(`${path}.${key} is required.`);
  }
  return raw[key];
}

function text(
  value: unknown,
  path: string,
  maximum: number,
  allowEmpty = false,
): string {
  if (typeof value !== "string") return fail(`${path} must be a string.`);
  if (!allowEmpty && !value.trim()) return fail(`${path} must not be empty.`);
  if (Array.from(value).length > maximum) return fail(`${path} is too long.`);
  return value;
}

function optionalText(
  raw: Record<string, unknown>,
  key: string,
  path: string,
  maximum: number,
): string | undefined {
  return raw[key] === undefined
    ? undefined
    : text(raw[key], `${path}.${key}`, maximum);
}

function integer(value: unknown, path: string, maximum = MAX_AUDIO_MS): number {
  if (
    !Number.isSafeInteger(value) ||
    (value as number) < 0 ||
    (value as number) > maximum
  ) {
    return fail(`${path} must be an integer between 0 and ${maximum}.`);
  }
  return value as number;
}

function parseTranscription(value: unknown): TranscriptionResultV1 {
  const raw = record(value, "transcription");
  if (required(raw, "schema", "transcription") !== TRANSCRIPTION_SCHEMA) {
    return fail("transcription.schema is unsupported.");
  }
  const version = required(raw, "version", "transcription");
  if (!Number.isSafeInteger(version))
    return fail("transcription.version must be an integer.");
  if (version !== TRANSCRIPTION_VERSION) {
    throw new VoiceIncompatibleError(TRANSCRIPTION_SCHEMA, version as number);
  }
  const requestId = text(
    required(raw, "request_id", "transcription"),
    "transcription.request_id",
    128,
  );
  const statusValue = required(raw, "status", "transcription");
  if (!TRANSCRIPTION_STATUSES.includes(statusValue as TranscriptionStatus)) {
    return fail("transcription.status is invalid.");
  }
  const status = statusValue as TranscriptionStatus;
  const transcript = text(
    required(raw, "text", "transcription"),
    "transcription.text",
    MAX_TEXT_CHARS,
    true,
  );
  const duration =
    raw.duration_ms === undefined
      ? undefined
      : integer(raw.duration_ms, "transcription.duration_ms");
  const processing =
    raw.processing_ms === undefined
      ? undefined
      : integer(raw.processing_ms, "transcription.processing_ms");

  const segmentValues = raw.segments ?? [];
  if (!Array.isArray(segmentValues) || segmentValues.length > 10_000) {
    return fail("transcription.segments must be a bounded array.");
  }
  const segments = segmentValues.map((value, index) => {
    const path = `transcription.segments[${index}]`;
    const segment = record(value, path);
    const start = integer(
      required(segment, "start_ms", path),
      `${path}.start_ms`,
    );
    const end = integer(required(segment, "end_ms", path), `${path}.end_ms`);
    if (end < start) return fail(`${path}.end_ms must not precede start_ms.`);
    if (duration !== undefined && end > duration) {
      return fail(`${path}.end_ms exceeds transcription.duration_ms.`);
    }
    return {
      start_ms: start,
      end_ms: end,
      text: text(
        required(segment, "text", path),
        `${path}.text`,
        MAX_TEXT_CHARS,
        true,
      ),
    };
  });

  const warningValues = raw.warnings ?? [];
  if (!Array.isArray(warningValues) || warningValues.length > 64) {
    return fail("transcription.warnings must be a bounded array.");
  }
  const warnings = warningValues.map((value, index) =>
    text(value, `transcription.warnings[${index}]`, 1000, true),
  );

  let transcriptionError: TranscriptionErrorV1 | undefined;
  if (status === "failed") {
    if (transcript) return fail("failed transcription text must be empty.");
    const error = record(
      required(raw, "error", "transcription"),
      "transcription.error",
    );
    const retryable = required(error, "retryable", "transcription.error");
    if (typeof retryable !== "boolean") {
      return fail("transcription.error.retryable must be a boolean.");
    }
    transcriptionError = {
      code: text(
        required(error, "code", "transcription.error"),
        "transcription.error.code",
        128,
      ),
      message: text(
        required(error, "message", "transcription.error"),
        "transcription.error.message",
        4000,
      ),
      retryable,
    };
  } else if (raw.error !== undefined) {
    return fail("only failed transcriptions may contain error.");
  } else if ((status === "no_speech" || status === "cancelled") && transcript) {
    return fail(`${status} transcription text must be empty.`);
  }

  return {
    schema: TRANSCRIPTION_SCHEMA,
    version: TRANSCRIPTION_VERSION,
    request_id: requestId,
    status,
    text: transcript,
    provider: optionalText(raw, "provider", "transcription", 128),
    language: optionalText(raw, "language", "transcription", 64),
    duration_ms: duration,
    processing_ms: processing,
    model: optionalText(raw, "model", "transcription", 128),
    segments,
    warnings,
    error: transcriptionError,
  };
}

function parseResult<T>(
  parser: () => T,
  fallback: string,
): VoiceContractParseResult<T> {
  try {
    return { kind: "verified", value: parser() };
  } catch (error) {
    if (error instanceof VoiceIncompatibleError) {
      return {
        kind: "incompatible",
        contract: error.contract,
        version: error.version,
      };
    }
    return {
      kind: "invalid",
      message: error instanceof VoiceDecodeError ? error.message : fallback,
    };
  }
}

export function parseTranscriptionResult(
  value: unknown,
): VoiceContractParseResult<TranscriptionResultV1> {
  return parseResult(
    () => parseTranscription(value),
    "transcription is malformed.",
  );
}

export function parsePhoneAudio(
  value: unknown,
): VoiceContractParseResult<PhoneAudioEnvelopeV1> {
  return parseResult(() => {
    const raw = record(value, "phone_audio");
    if (required(raw, "contract", "phone_audio") !== PHONE_AUDIO_CONTRACT) {
      return fail("phone_audio.contract is unsupported.");
    }
    const version = required(raw, "version", "phone_audio");
    if (!Number.isSafeInteger(version))
      return fail("phone_audio.version must be an integer.");
    if (version !== PHONE_AUDIO_VERSION) {
      throw new VoiceIncompatibleError(PHONE_AUDIO_CONTRACT, version as number);
    }
    const modeValue = required(raw, "mode", "phone_audio");
    if (!PHONE_AUDIO_MODES.includes(modeValue as PhoneAudioMode)) {
      return fail("phone_audio.mode is invalid.");
    }
    const mimeType = text(
      required(raw, "mime_type", "phone_audio"),
      "phone_audio.mime_type",
      128,
    ).toLowerCase();
    if (!mimeType.startsWith("audio/") && mimeType !== "video/webm") {
      return fail("phone_audio.mime_type must describe audio.");
    }
    return {
      contract: PHONE_AUDIO_CONTRACT,
      version: PHONE_AUDIO_VERSION,
      capture_id: text(
        required(raw, "capture_id", "phone_audio"),
        "phone_audio.capture_id",
        128,
      ),
      mode: modeValue as PhoneAudioMode,
      mime_type: mimeType,
      duration_ms: integer(
        required(raw, "duration_ms", "phone_audio"),
        "phone_audio.duration_ms",
      ),
      result: parseTranscription(required(raw, "result", "phone_audio")),
    };
  }, "phone_audio is malformed.");
}
