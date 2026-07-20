/** Canonical client reference implementation for the `fabric.work` v1 wire contract. */

export const WORK_CLIENT_CONTRACT_VERSION = 1;
export const WORK_SYNC_MAX_BYTES = 1024 * 1024;
export const WORK_SYNC_MAX_ITEMS = 500;
export const WORK_SUBJECT_MAX_BYTES = 32 * 1024;
export const WORK_RESULT_PREVIEW_MAX_BYTES = 4 * 1024;
export const WORK_ERROR_PREVIEW_MAX_BYTES = 8 * 1024;

export const WORK_JOB_KINDS = ["background_prompt"] as const;
export const WORK_JOB_STATUSES = [
  "queued",
  "claimed",
  "running",
  "waiting_attention",
  "cancel_requested",
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
] as const;
export const WORK_ATTENTION_KINDS = [
  "approval",
  "clarify",
  "sudo",
  "secret",
] as const;
export const WORK_ATTENTION_STATES = [
  "pending",
  "resolving",
  "resolved",
  "denied",
  "expired",
  "cancelled",
  "orphaned",
] as const;
export const WORK_ATTENTION_ACTIONS = [
  "once",
  "session",
  "always",
  "deny",
  "submit",
  "cancel",
] as const;
export const WORK_RUN_RUNTIME_KINDS = ["in_process_agent"] as const;
export const WORK_RUN_OWNER_STATES = ["creator_bound"] as const;
export const WORK_RESTART_BEHAVIORS = ["interrupt"] as const;
export const WORK_RESULT_OMITTED_REASONS = ["sensitive_input"] as const;
export const WORK_SYNC_MODES = ["bootstrap", "delta"] as const;
export const WORK_SUBJECT_TYPES = ["job", "attention"] as const;

export type WorkJobKind = (typeof WORK_JOB_KINDS)[number];
export type WorkJobStatus = (typeof WORK_JOB_STATUSES)[number];
export type WorkAttentionKind = (typeof WORK_ATTENTION_KINDS)[number];
export type WorkAttentionState = (typeof WORK_ATTENTION_STATES)[number];
export type WorkAttentionAction = (typeof WORK_ATTENTION_ACTIONS)[number];
export type WorkSyncMode = (typeof WORK_SYNC_MODES)[number];
export type WorkSubjectType = (typeof WORK_SUBJECT_TYPES)[number];

export type WorkJsonValue =
  | null
  | boolean
  | number
  | string
  | WorkJsonValue[]
  | { [key: string]: WorkJsonValue };
export type WorkJsonObject = { [key: string]: WorkJsonValue };

export interface WorkUnknownEnum {
  field: string;
  raw: string;
}

export interface WorkContractDescriptor {
  name: "fabric.work";
  version: number;
  min_compatible: number;
}

export interface WorkRunSummary {
  run_id: string;
  attempt: number;
  version: number;
  status: string;
  runtime_kind: string;
  owner_state: string;
  restart_behavior: string;
  claimed_at: number | null;
  started_at: number | null;
  updated_at: number;
  finished_at: number | null;
  actionable: boolean;
  unknown_enums: readonly WorkUnknownEnum[];
}

export interface WorkJobSummary {
  object_type: "job";
  job_id: string;
  version: number;
  kind: string;
  status: string;
  title: string;
  summary: string | null;
  source: string;
  source_session_key: string | null;
  runtime_session_id: string | null;
  attempt_count: number;
  open_attention_count: number;
  created_at: number;
  started_at: number | null;
  updated_at: number;
  finished_at: number | null;
  cancel_requested_at: number | null;
  runtime: WorkJsonObject;
  current_run: WorkRunSummary | null;
  result_preview: WorkJsonValue;
  result_ref: string | null;
  result_omitted_reason: string | null;
  error: WorkJsonValue;
  actionable: boolean;
  unknown_enums: readonly WorkUnknownEnum[];
}

export interface WorkAttention {
  object_type: "attention";
  attention_id: string;
  version: number;
  job_id: string | null;
  run_id: string | null;
  source_session_key: string | null;
  runtime_session_id: string | null;
  request_id: string;
  kind: string;
  state: string;
  blocking: boolean;
  sensitive: boolean;
  title: string;
  public_payload: WorkJsonObject;
  allowed_actions: readonly string[];
  created_at: number;
  updated_at: number;
  expires_at: number | null;
  resolved_at: number | null;
  terminal_reason: string | null;
  actionable: boolean;
  unknown_enums: readonly WorkUnknownEnum[];
}

export interface WorkUnknownSubject {
  object_type: "unknown";
  raw: WorkJsonObject;
  actionable: false;
  unknown_enums: readonly WorkUnknownEnum[];
}

export type WorkEventSubject =
  | WorkJobSummary
  | WorkAttention
  | WorkUnknownSubject;

export interface WorkEvent {
  event_id: number;
  event_type: string;
  subject_type: string;
  subject_id: string;
  job_id: string | null;
  run_id: string | null;
  subject_version: number;
  subject: WorkEventSubject | null;
  tombstone: boolean;
  created_at: number;
  actionable: boolean;
  unknown_enums: readonly WorkUnknownEnum[];
}

export interface WorkSyncPage {
  contract: WorkContractDescriptor;
  ledger_id: string;
  work_profile_id: string;
  mode: string;
  watermark: number;
  cursor: number;
  has_more: boolean;
  next_page_token: string | null;
  jobs: readonly WorkJobSummary[];
  attention: readonly WorkAttention[];
  events: readonly WorkEvent[];
  encoded_bytes: number;
  actionable: boolean;
  unknown_enums: readonly WorkUnknownEnum[];
}

export type WorkContractParseResult =
  | { kind: "verified"; page: WorkSyncPage }
  | { kind: "incompatible"; minimum: number }
  | { kind: "invalid"; message: string };

export interface WorkCursorReset {
  code: -32047;
  message: string;
  data: {
    code: "cursor_expired";
    bootstrap: true;
    reason: string | null;
    ledger_id: string | null;
    event_floor: number | null;
    high_water: number | null;
  };
}

export type WorkCursorResetParseResult =
  | { kind: "verified"; reset: WorkCursorReset }
  | { kind: "invalid"; message: string };

const WORK_ID_PATTERNS = {
  attention: /^attn_[0-9a-f]{32}$/,
  job: /^job_[0-9a-f]{32}$/,
  ledger: /^ledger_[0-9a-f]{32}$/,
  profile: /^profile_[0-9a-f]{32}$/,
  run: /^run_[0-9a-f]{32}$/,
} as const;

class WorkDecodeError extends Error {}

function fail(message: string): never {
  throw new WorkDecodeError(message);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) fail(`${path} must be an object.`);
  return value;
}

function required(
  value: Record<string, unknown>,
  key: string,
  path: string,
): unknown {
  if (!Object.prototype.hasOwnProperty.call(value, key)) {
    fail(`${path}.${key} is required, including when its value is null.`);
  }
  return value[key];
}

function stringValue(
  value: unknown,
  path: string,
  options: { max?: number; nonempty?: boolean } = {},
): string {
  if (typeof value !== "string") fail(`${path} must be a string.`);
  if (options.nonempty !== false && !value.trim()) {
    fail(`${path} must be a non-empty string.`);
  }
  if (options.max !== undefined && Array.from(value).length > options.max) {
    fail(`${path} must contain at most ${options.max} characters.`);
  }
  return value;
}

function nullableString(
  value: unknown,
  path: string,
  options: { max?: number; nonempty?: boolean } = {},
): string | null {
  if (value === null) return null;
  return stringValue(value, path, {
    ...options,
    nonempty: options.nonempty ?? false,
  });
}

function safeInteger(
  value: unknown,
  path: string,
  options: { minimum?: number } = {},
): number {
  const minimum = options.minimum ?? 0;
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  ) {
    fail(`${path} must be a safe integer greater than or equal to ${minimum}.`);
  }
  return value;
}

function nullableTimestamp(value: unknown, path: string): number | null {
  return value === null ? null : safeInteger(value, path);
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") fail(`${path} must be a boolean.`);
  return value;
}

function arrayValue(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) fail(`${path} must be an array.`);
  return value;
}

function workId(
  value: unknown,
  kind: keyof typeof WORK_ID_PATTERNS,
  path: string,
): string {
  const parsed = stringValue(value, path);
  if (!WORK_ID_PATTERNS[kind].test(parsed)) {
    fail(`${path} must be a 128-bit ${kind} identifier.`);
  }
  return parsed;
}

function nullableWorkId(
  value: unknown,
  kind: keyof typeof WORK_ID_PATTERNS,
  path: string,
): string | null {
  return value === null ? null : workId(value, kind, path);
}

function jsonValue(value: unknown, path: string): WorkJsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail(`${path} contains a non-finite number.`);
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item, index) => jsonValue(item, `${path}[${index}]`));
  }
  if (isRecord(value)) {
    const result: WorkJsonObject = {};
    for (const [key, child] of Object.entries(value)) {
      Object.defineProperty(result, key, {
        configurable: true,
        enumerable: true,
        value: jsonValue(child, `${path}.${key}`),
        writable: true,
      });
    }
    return result;
  }
  return fail(`${path} must contain only JSON values.`);
}

function jsonObject(value: unknown, path: string): WorkJsonObject {
  const parsed = jsonValue(record(value, path), path);
  return parsed as WorkJsonObject;
}

export function workJsonByteLength(value: unknown): number {
  let encoded: string;
  try {
    encoded = JSON.stringify(value);
  } catch {
    return fail("Work payload must be JSON serializable.");
  }
  if (encoded === undefined)
    return fail("Work payload must be JSON serializable.");
  return new TextEncoder().encode(encoded).byteLength;
}

function enforceByteLimit(value: unknown, maximum: number, path: string): void {
  if (workJsonByteLength(value) > maximum) {
    fail(`${path} exceeds its ${maximum}-byte wire limit.`);
  }
}

function enumValue(
  value: unknown,
  known: readonly string[],
  path: string,
  unknown: WorkUnknownEnum[],
): string {
  const parsed = stringValue(value, path, { max: 128 });
  if (!known.includes(parsed)) unknown.push({ field: path, raw: parsed });
  return parsed;
}

export function displayWorkEnum(
  value: string,
  known: readonly string[],
): string {
  return known.includes(value) ? value : `unknown(${value})`;
}

function parseRunSummary(value: unknown, path: string): WorkRunSummary {
  const raw = record(value, path);
  const unknown: WorkUnknownEnum[] = [];
  const result: WorkRunSummary = {
    run_id: workId(required(raw, "run_id", path), "run", `${path}.run_id`),
    attempt: safeInteger(required(raw, "attempt", path), `${path}.attempt`, {
      minimum: 1,
    }),
    version: safeInteger(required(raw, "version", path), `${path}.version`, {
      minimum: 1,
    }),
    status: enumValue(
      required(raw, "status", path),
      WORK_JOB_STATUSES,
      `${path}.status`,
      unknown,
    ),
    runtime_kind: enumValue(
      required(raw, "runtime_kind", path),
      WORK_RUN_RUNTIME_KINDS,
      `${path}.runtime_kind`,
      unknown,
    ),
    owner_state: enumValue(
      required(raw, "owner_state", path),
      WORK_RUN_OWNER_STATES,
      `${path}.owner_state`,
      unknown,
    ),
    restart_behavior: enumValue(
      required(raw, "restart_behavior", path),
      WORK_RESTART_BEHAVIORS,
      `${path}.restart_behavior`,
      unknown,
    ),
    claimed_at: nullableTimestamp(
      required(raw, "claimed_at", path),
      `${path}.claimed_at`,
    ),
    started_at: nullableTimestamp(
      required(raw, "started_at", path),
      `${path}.started_at`,
    ),
    updated_at: safeInteger(
      required(raw, "updated_at", path),
      `${path}.updated_at`,
    ),
    finished_at: nullableTimestamp(
      required(raw, "finished_at", path),
      `${path}.finished_at`,
    ),
    actionable: false,
    unknown_enums: unknown,
  };
  result.actionable = unknown.length === 0;
  return result;
}

function parseJobSummary(value: unknown, path: string): WorkJobSummary {
  const raw = record(value, path);
  enforceByteLimit(raw, WORK_SUBJECT_MAX_BYTES, path);
  const unknown: WorkUnknownEnum[] = [];
  const currentRunRaw = required(raw, "current_run", path);
  const resultPreview = jsonValue(
    required(raw, "result_preview", path),
    `${path}.result_preview`,
  );
  const error = jsonValue(required(raw, "error", path), `${path}.error`);
  enforceByteLimit(
    resultPreview,
    WORK_RESULT_PREVIEW_MAX_BYTES,
    `${path}.result_preview`,
  );
  enforceByteLimit(error, WORK_ERROR_PREVIEW_MAX_BYTES, `${path}.error`);
  const omittedRaw = required(raw, "result_omitted_reason", path);
  const omitted =
    omittedRaw === null
      ? null
      : enumValue(
          omittedRaw,
          WORK_RESULT_OMITTED_REASONS,
          `${path}.result_omitted_reason`,
          unknown,
        );
  if (omitted !== null && resultPreview !== null) {
    fail(`${path}.result_preview must be null when a result is omitted.`);
  }
  const runtime = jsonObject(required(raw, "runtime", path), `${path}.runtime`);
  enforceByteLimit(runtime, WORK_SUBJECT_MAX_BYTES, `${path}.runtime`);
  const currentRun =
    currentRunRaw === null
      ? null
      : parseRunSummary(currentRunRaw, `${path}.current_run`);
  if (currentRun !== null) unknown.push(...currentRun.unknown_enums);

  const result: WorkJobSummary = {
    object_type: "job",
    job_id: workId(required(raw, "job_id", path), "job", `${path}.job_id`),
    version: safeInteger(required(raw, "version", path), `${path}.version`, {
      minimum: 1,
    }),
    kind: enumValue(
      required(raw, "kind", path),
      WORK_JOB_KINDS,
      `${path}.kind`,
      unknown,
    ),
    status: enumValue(
      required(raw, "status", path),
      WORK_JOB_STATUSES,
      `${path}.status`,
      unknown,
    ),
    title: stringValue(required(raw, "title", path), `${path}.title`, {
      max: 200,
    }),
    summary: nullableString(required(raw, "summary", path), `${path}.summary`),
    source: stringValue(required(raw, "source", path), `${path}.source`, {
      max: 128,
    }),
    source_session_key: nullableString(
      required(raw, "source_session_key", path),
      `${path}.source_session_key`,
      { max: 512 },
    ),
    runtime_session_id: nullableString(
      required(raw, "runtime_session_id", path),
      `${path}.runtime_session_id`,
      { max: 512 },
    ),
    attempt_count: safeInteger(
      required(raw, "attempt_count", path),
      `${path}.attempt_count`,
    ),
    open_attention_count: safeInteger(
      required(raw, "open_attention_count", path),
      `${path}.open_attention_count`,
    ),
    created_at: safeInteger(
      required(raw, "created_at", path),
      `${path}.created_at`,
    ),
    started_at: nullableTimestamp(
      required(raw, "started_at", path),
      `${path}.started_at`,
    ),
    updated_at: safeInteger(
      required(raw, "updated_at", path),
      `${path}.updated_at`,
    ),
    finished_at: nullableTimestamp(
      required(raw, "finished_at", path),
      `${path}.finished_at`,
    ),
    cancel_requested_at: nullableTimestamp(
      required(raw, "cancel_requested_at", path),
      `${path}.cancel_requested_at`,
    ),
    runtime,
    current_run: currentRun,
    result_preview: resultPreview,
    result_ref: nullableString(
      required(raw, "result_ref", path),
      `${path}.result_ref`,
      { max: 2048 },
    ),
    result_omitted_reason: omitted,
    error,
    actionable: false,
    unknown_enums: unknown,
  };
  if (currentRun !== null && currentRun.attempt > result.attempt_count) {
    fail(`${path}.current_run.attempt cannot exceed attempt_count.`);
  }
  result.actionable = unknown.length === 0;
  return result;
}

function validActionsForKind(kind: string): readonly string[] {
  if (kind === "approval") return ["once", "session", "always", "deny"];
  if (kind === "clarify" || kind === "sudo" || kind === "secret") {
    return ["submit", "cancel"];
  }
  return [];
}

function parseAttention(value: unknown, path: string): WorkAttention {
  const raw = record(value, path);
  enforceByteLimit(raw, WORK_SUBJECT_MAX_BYTES, path);
  const unknown: WorkUnknownEnum[] = [];
  const kind = enumValue(
    required(raw, "kind", path),
    WORK_ATTENTION_KINDS,
    `${path}.kind`,
    unknown,
  );
  const state = enumValue(
    required(raw, "state", path),
    WORK_ATTENTION_STATES,
    `${path}.state`,
    unknown,
  );
  const actions = arrayValue(
    required(raw, "allowed_actions", path),
    `${path}.allowed_actions`,
  ).map((item, index) =>
    enumValue(
      item,
      WORK_ATTENTION_ACTIONS,
      `${path}.allowed_actions[${index}]`,
      unknown,
    ),
  );
  if (new Set(actions).size !== actions.length) {
    fail(`${path}.allowed_actions must not contain duplicates.`);
  }
  const validActions = validActionsForKind(kind);
  const containsUnknownEnum = unknown.length > 0;
  if (
    !containsUnknownEnum &&
    validActions.length > 0 &&
    actions.some((action) => !validActions.includes(action))
  ) {
    fail(`${path}.allowed_actions contains an action invalid for ${kind}.`);
  }
  if (
    !containsUnknownEnum &&
    state === "pending" &&
    validActions.length > 0 &&
    actions.length === 0
  ) {
    fail(`${path}.allowed_actions cannot be empty while Attention is pending.`);
  }
  if (!containsUnknownEnum && state !== "pending" && actions.length > 0) {
    fail(
      `${path}.allowed_actions must be empty when Attention is not pending.`,
    );
  }
  const publicPayload = jsonObject(
    required(raw, "public_payload", path),
    `${path}.public_payload`,
  );
  enforceByteLimit(
    publicPayload,
    WORK_SUBJECT_MAX_BYTES,
    `${path}.public_payload`,
  );
  const result: WorkAttention = {
    object_type: "attention",
    attention_id: workId(
      required(raw, "attention_id", path),
      "attention",
      `${path}.attention_id`,
    ),
    version: safeInteger(required(raw, "version", path), `${path}.version`, {
      minimum: 1,
    }),
    job_id: nullableWorkId(
      required(raw, "job_id", path),
      "job",
      `${path}.job_id`,
    ),
    run_id: nullableWorkId(
      required(raw, "run_id", path),
      "run",
      `${path}.run_id`,
    ),
    source_session_key: nullableString(
      required(raw, "source_session_key", path),
      `${path}.source_session_key`,
      { max: 512 },
    ),
    runtime_session_id: nullableString(
      required(raw, "runtime_session_id", path),
      `${path}.runtime_session_id`,
      { max: 512 },
    ),
    request_id: stringValue(
      required(raw, "request_id", path),
      `${path}.request_id`,
      { max: 128 },
    ),
    kind,
    state,
    blocking: booleanValue(required(raw, "blocking", path), `${path}.blocking`),
    sensitive: booleanValue(
      required(raw, "sensitive", path),
      `${path}.sensitive`,
    ),
    title: stringValue(required(raw, "title", path), `${path}.title`, {
      max: 200,
    }),
    public_payload: publicPayload,
    allowed_actions: actions,
    created_at: safeInteger(
      required(raw, "created_at", path),
      `${path}.created_at`,
    ),
    updated_at: safeInteger(
      required(raw, "updated_at", path),
      `${path}.updated_at`,
    ),
    expires_at: nullableTimestamp(
      required(raw, "expires_at", path),
      `${path}.expires_at`,
    ),
    resolved_at: nullableTimestamp(
      required(raw, "resolved_at", path),
      `${path}.resolved_at`,
    ),
    terminal_reason: nullableString(
      required(raw, "terminal_reason", path),
      `${path}.terminal_reason`,
      { max: 256 },
    ),
    actionable: false,
    unknown_enums: unknown,
  };
  result.actionable = unknown.length === 0 && state === "pending";
  return result;
}

function parseUnknownSubject(
  value: unknown,
  path: string,
  subjectType: string,
): WorkUnknownSubject {
  return {
    object_type: "unknown",
    raw: jsonObject(value, path),
    actionable: false,
    unknown_enums: [{ field: `${path}.subject_type`, raw: subjectType }],
  };
}

function parseEvent(value: unknown, path: string): WorkEvent {
  const raw = record(value, path);
  enforceByteLimit(raw, WORK_SUBJECT_MAX_BYTES, path);
  const unknown: WorkUnknownEnum[] = [];
  const subjectType = enumValue(
    required(raw, "subject_type", path),
    WORK_SUBJECT_TYPES,
    `${path}.subject_type`,
    unknown,
  );
  const subjectId = stringValue(
    required(raw, "subject_id", path),
    `${path}.subject_id`,
    { max: 128 },
  );
  if (subjectType === "job") workId(subjectId, "job", `${path}.subject_id`);
  if (subjectType === "attention") {
    workId(subjectId, "attention", `${path}.subject_id`);
  }
  const subjectVersion = safeInteger(
    required(raw, "subject_version", path),
    `${path}.subject_version`,
    { minimum: 1 },
  );
  const tombstone = booleanValue(
    required(raw, "tombstone", path),
    `${path}.tombstone`,
  );
  const subjectRaw = required(raw, "subject", path);
  let subject: WorkEventSubject | null;
  if (tombstone) {
    if (subjectRaw !== null)
      fail(`${path}.subject must be null for a tombstone.`);
    subject = null;
  } else {
    if (subjectRaw === null)
      fail(`${path}.subject is required for a live event.`);
    subject =
      subjectType === "job"
        ? parseJobSummary(subjectRaw, `${path}.subject`)
        : subjectType === "attention"
          ? parseAttention(subjectRaw, `${path}.subject`)
          : parseUnknownSubject(subjectRaw, `${path}.subject`, subjectType);
    const actualId =
      subject.object_type === "job"
        ? subject.job_id
        : subject.object_type === "attention"
          ? subject.attention_id
          : subjectId;
    const actualVersion =
      subject.object_type === "unknown" ? subjectVersion : subject.version;
    if (actualId !== subjectId || actualVersion !== subjectVersion) {
      fail(`${path}.subject must match subject_id and subject_version.`);
    }
    unknown.push(...subject.unknown_enums);
  }
  const result: WorkEvent = {
    event_id: safeInteger(required(raw, "event_id", path), `${path}.event_id`, {
      minimum: 1,
    }),
    event_type: stringValue(
      required(raw, "event_type", path),
      `${path}.event_type`,
      { max: 128 },
    ),
    subject_type: subjectType,
    subject_id: subjectId,
    job_id: nullableWorkId(
      required(raw, "job_id", path),
      "job",
      `${path}.job_id`,
    ),
    run_id: nullableWorkId(
      required(raw, "run_id", path),
      "run",
      `${path}.run_id`,
    ),
    subject_version: subjectVersion,
    subject,
    tombstone,
    created_at: safeInteger(
      required(raw, "created_at", path),
      `${path}.created_at`,
    ),
    actionable: false,
    unknown_enums: unknown,
  };
  result.actionable =
    unknown.length === 0 &&
    (tombstone || (subject !== null && subject.actionable));
  return result;
}

function parseContract(
  raw: Record<string, unknown>,
): WorkContractDescriptor | { incompatible: number } {
  const contract = record(required(raw, "contract", "work"), "work.contract");
  if (required(contract, "name", "work.contract") !== "fabric.work") {
    fail("work.contract.name must be fabric.work.");
  }
  const version = safeInteger(
    required(contract, "version", "work.contract"),
    "work.contract.version",
    { minimum: 1 },
  );
  const minimum = safeInteger(
    required(contract, "min_compatible", "work.contract"),
    "work.contract.min_compatible",
    { minimum: 1 },
  );
  if (minimum > version) {
    fail("work.contract.min_compatible cannot exceed contract.version.");
  }
  if (minimum > WORK_CLIENT_CONTRACT_VERSION) return { incompatible: minimum };
  return { name: "fabric.work", version, min_compatible: minimum };
}

/**
 * Parse and normalize one complete sync page.
 *
 * Required nullable fields must be present, unknown object keys are omitted,
 * and compatible future enum values remain in their raw fields while making
 * only their containing object non-actionable.
 */
export function parseWorkSyncPage(
  value: unknown,
  options: { encodedBytes?: number } = {},
): WorkContractParseResult {
  try {
    const measuredBytes = workJsonByteLength(value);
    const encodedBytes = options.encodedBytes ?? measuredBytes;
    if (
      !Number.isSafeInteger(encodedBytes) ||
      encodedBytes < 0 ||
      encodedBytes > WORK_SYNC_MAX_BYTES ||
      measuredBytes > WORK_SYNC_MAX_BYTES
    ) {
      fail(
        `work sync page exceeds its ${WORK_SYNC_MAX_BYTES}-byte wire limit.`,
      );
    }
    const raw = record(value, "work");
    const contract = parseContract(raw);
    if ("incompatible" in contract) {
      return { kind: "incompatible", minimum: contract.incompatible };
    }
    const unknown: WorkUnknownEnum[] = [];
    const mode = enumValue(
      required(raw, "mode", "work"),
      WORK_SYNC_MODES,
      "work.mode",
      unknown,
    );
    const watermark = safeInteger(
      required(raw, "watermark", "work"),
      "work.watermark",
    );
    const cursor = safeInteger(required(raw, "cursor", "work"), "work.cursor");
    if (cursor > watermark) fail("work.cursor cannot exceed work.watermark.");
    const hasMore = booleanValue(
      required(raw, "has_more", "work"),
      "work.has_more",
    );
    const nextPageToken = nullableString(
      required(raw, "next_page_token", "work"),
      "work.next_page_token",
      { max: 4096, nonempty: true },
    );
    const jobs = arrayValue(required(raw, "jobs", "work"), "work.jobs").map(
      (job, index) => parseJobSummary(job, `work.jobs[${index}]`),
    );
    const attention = arrayValue(
      required(raw, "attention", "work"),
      "work.attention",
    ).map((item, index) => parseAttention(item, `work.attention[${index}]`));
    const events = arrayValue(
      required(raw, "events", "work"),
      "work.events",
    ).map((event, index) => parseEvent(event, `work.events[${index}]`));

    if (mode === "bootstrap") {
      if (events.length !== 0) fail("bootstrap pages cannot contain events.");
      if (jobs.length + attention.length > WORK_SYNC_MAX_ITEMS) {
        fail(`bootstrap pages cannot exceed ${WORK_SYNC_MAX_ITEMS} subjects.`);
      }
      if (cursor !== watermark) {
        fail("bootstrap page cursor must equal its fixed watermark.");
      }
      if (hasMore !== (nextPageToken !== null)) {
        fail("bootstrap has_more must match next_page_token presence.");
      }
    } else if (mode === "delta") {
      if (jobs.length !== 0 || attention.length !== 0) {
        fail("delta pages carry subjects only inside events.");
      }
      if (events.length > WORK_SYNC_MAX_ITEMS) {
        fail(`delta pages cannot exceed ${WORK_SYNC_MAX_ITEMS} events.`);
      }
      if (nextPageToken !== null) {
        fail("delta next_page_token must be null.");
      }
      if (hasMore && events.length === 0) {
        fail("a truncated delta page must advance with at least one event.");
      }
      if (!hasMore && cursor !== watermark) {
        fail("a complete delta page cursor must equal its watermark.");
      }
      let priorEventId = 0;
      for (const event of events) {
        if (event.event_id <= priorEventId) {
          fail("delta event_id values must be strictly increasing.");
        }
        if (event.event_id > cursor) {
          fail("delta events cannot exceed the returned cursor.");
        }
        priorEventId = event.event_id;
      }
      if (events.length > 0 && events.at(-1)?.event_id !== cursor) {
        fail("a delta cursor must equal its final event_id.");
      }
    }

    const jobIds = jobs.map((job) => job.job_id);
    const attentionIds = attention.map((item) => item.attention_id);
    if (new Set(jobIds).size !== jobIds.length) {
      fail("work.jobs contains a duplicate job_id.");
    }
    if (new Set(attentionIds).size !== attentionIds.length) {
      fail("work.attention contains a duplicate attention_id.");
    }

    return {
      kind: "verified",
      page: {
        contract,
        ledger_id: workId(
          required(raw, "ledger_id", "work"),
          "ledger",
          "work.ledger_id",
        ),
        work_profile_id: workId(
          required(raw, "work_profile_id", "work"),
          "profile",
          "work.work_profile_id",
        ),
        mode,
        watermark,
        cursor,
        has_more: hasMore,
        next_page_token: nextPageToken,
        jobs,
        attention,
        events,
        encoded_bytes: encodedBytes,
        actionable: unknown.length === 0,
        unknown_enums: unknown,
      },
    };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof WorkDecodeError
          ? error.message
          : "Work sync page is malformed.",
    };
  }
}

/** Parse the sanitized `cursor_expired` reset returned by `job.sync`. */
export function parseWorkCursorReset(
  value: unknown,
): WorkCursorResetParseResult {
  try {
    const raw = record(value, "work reset");
    if (required(raw, "code", "work reset") !== -32047) {
      fail("work reset.code must be -32047.");
    }
    const data = record(required(raw, "data", "work reset"), "work reset.data");
    if (required(data, "code", "work reset.data") !== "cursor_expired") {
      fail("work reset.data.code must be cursor_expired.");
    }
    if (required(data, "bootstrap", "work reset.data") !== true) {
      fail("work reset.data.bootstrap must be true.");
    }
    const optionalInteger = (key: string): number | null => {
      if (
        !Object.prototype.hasOwnProperty.call(data, key) ||
        data[key] === null
      ) {
        return null;
      }
      return safeInteger(data[key], `work reset.data.${key}`);
    };
    const optionalString = (key: string): string | null => {
      if (
        !Object.prototype.hasOwnProperty.call(data, key) ||
        data[key] === null
      ) {
        return null;
      }
      return stringValue(data[key], `work reset.data.${key}`, { max: 128 });
    };
    const ledger =
      !Object.prototype.hasOwnProperty.call(data, "ledger_id") ||
      data.ledger_id === null
        ? null
        : workId(data.ledger_id, "ledger", "work reset.data.ledger_id");
    const eventFloor = optionalInteger("event_floor");
    const highWater = optionalInteger("high_water");
    if (
      eventFloor !== null &&
      highWater !== null &&
      eventFloor > highWater + 1
    ) {
      fail("work reset event_floor cannot exceed high_water + 1.");
    }
    return {
      kind: "verified",
      reset: {
        code: -32047,
        message: stringValue(
          required(raw, "message", "work reset"),
          "work reset.message",
          { max: 512 },
        ),
        data: {
          code: "cursor_expired",
          bootstrap: true,
          reason: optionalString("reason"),
          ledger_id: ledger,
          event_floor: eventFloor,
          high_water: highWater,
        },
      },
    };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof WorkDecodeError
          ? error.message
          : "Work cursor reset is malformed.",
    };
  }
}
