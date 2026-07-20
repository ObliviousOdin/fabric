import {
  GatewayRpcError,
  OPTIONAL_GATEWAY_FEATURE_METHODS,
  WorkSyncApplyError,
  applyWorkCursorReset,
  applyWorkSyncPage,
  createWorkProjection,
  parseWorkCursorReset,
  parseWorkSyncPage,
  type GatewayCompatibility,
  type WorkAttention,
  type WorkAttentionAction,
  type WorkCursorReset,
  type WorkEvent,
  type WorkJobSummary,
  type WorkProjection,
  type WorkSyncPage,
  type WorkSyncScope,
} from "@fabric/shared";

export type WorkGatewayRequest = <T>(
  method: string,
  params?: Record<string, unknown>,
  timeoutMs?: number,
) => Promise<T>;

export type AdvertisedWorkProtocol = "durable" | "legacy" | "unavailable";

export interface WorkJobMutationReceipt {
  job: WorkJobSummary;
  mutation_id: string;
  replayed: boolean;
  runtime_started?: boolean;
  task_id?: string;
}

export interface WorkAttentionMutationReceipt {
  attention_id: string;
  attention_version: number;
  delivered: boolean;
  mutation_id: string;
  replayed: boolean;
  state: string;
}

export interface WorkJobListResponse {
  jobs: readonly WorkJobSummary[];
  next_before: string | null;
}

export interface WorkAttentionListResponse {
  attention: readonly WorkAttention[];
  next_before: string | null;
}

export interface WorkJobEventsResponse {
  cursor: number;
  events: readonly WorkEvent[];
}

export interface WorkBackgroundMutation {
  gateway_id: string;
  idempotency_key: string;
  profile_id: string;
  text: string;
  title: string;
}

export interface WorkSyncCommit {
  page: WorkSyncPage | null;
  projection: WorkProjection;
}

export type WorkSyncResult =
  | { kind: "current"; projection: WorkProjection }
  | { kind: "stale"; projection: WorkProjection };

export class WorkContractIncompatibleError extends Error {
  readonly minimum: number;

  constructor(minimum: number) {
    super(`This gateway requires fabric.work contract ${minimum}.`);
    this.name = "WorkContractIncompatibleError";
    this.minimum = minimum;
  }
}

export class WorkContractInvalidError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WorkContractInvalidError";
  }
}

export class WorkCursorResetError extends Error {
  readonly reset: WorkCursorReset;

  constructor(reset: WorkCursorReset) {
    super(reset.message);
    this.name = "WorkCursorResetError";
    this.reset = reset;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: Record<string, unknown>, key: string): string {
  const candidate = value[key];
  if (typeof candidate !== "string" || !candidate) {
    throw new WorkContractInvalidError(`Work response ${key} is invalid.`);
  }
  return candidate;
}

function requiredBoolean(value: Record<string, unknown>, key: string): boolean {
  const candidate = value[key];
  if (typeof candidate !== "boolean") {
    throw new WorkContractInvalidError(`Work response ${key} is invalid.`);
  }
  return candidate;
}

function requiredInteger(value: Record<string, unknown>, key: string): number {
  const candidate = value[key];
  if (!Number.isSafeInteger(candidate)) {
    throw new WorkContractInvalidError(`Work response ${key} is invalid.`);
  }
  return candidate as number;
}

function parseJobMutationReceipt(value: unknown): WorkJobMutationReceipt {
  if (!isRecord(value) || !isRecord(value.job)) {
    throw new WorkContractInvalidError("Job mutation receipt is invalid.");
  }
  const rawJob = value.job;
  const jobId = requiredString(rawJob, "job_id");
  const version = requiredInteger(rawJob, "version");
  if (!/^job_[0-9a-f]{32}$/.test(jobId) || version < 1) {
    throw new WorkContractInvalidError(
      "Job mutation receipt has an invalid Job.",
    );
  }
  const receipt: WorkJobMutationReceipt = {
    job: rawJob as unknown as WorkJobSummary,
    mutation_id: requiredString(value, "mutation_id"),
    replayed: requiredBoolean(value, "replayed"),
  };
  if (value.runtime_started !== undefined) {
    receipt.runtime_started = requiredBoolean(value, "runtime_started");
  }
  if (value.task_id !== undefined) {
    receipt.task_id = requiredString(value, "task_id");
  }
  return receipt;
}

function parseAttentionMutationReceipt(
  value: unknown,
): WorkAttentionMutationReceipt {
  if (!isRecord(value)) {
    throw new WorkContractInvalidError(
      "Attention mutation receipt is invalid.",
    );
  }
  const attentionId = requiredString(value, "attention_id");
  const attentionVersion = requiredInteger(value, "attention_version");
  if (!/^attn_[0-9a-f]{32}$/.test(attentionId) || attentionVersion < 1) {
    throw new WorkContractInvalidError(
      "Attention mutation receipt has an invalid Attention item.",
    );
  }
  return {
    attention_id: attentionId,
    attention_version: attentionVersion,
    delivered: requiredBoolean(value, "delivered"),
    mutation_id: requiredString(value, "mutation_id"),
    replayed: requiredBoolean(value, "replayed"),
    state: requiredString(value, "state"),
  };
}

/** The gateway feature is trusted only when negotiation verified its methods. */
export function advertisedWorkProtocol(
  compatibility: GatewayCompatibility | { kind: "negotiating" } | null,
): AdvertisedWorkProtocol {
  if (compatibility?.kind === "legacy") {
    return "legacy";
  }
  if (compatibility?.kind !== "verified") {
    return "unavailable";
  }
  if (compatibility.capabilities.features.durable_work) {
    const methods = new Set(compatibility.capabilities.methods);
    return OPTIONAL_GATEWAY_FEATURE_METHODS.durable_work.every((method) =>
      methods.has(method),
    )
      ? "durable"
      : "unavailable";
  }
  return compatibility.capabilities.methods.includes("prompt.background")
    ? "legacy"
    : "unavailable";
}

export function createBackgroundMutation(
  scope: WorkSyncScope,
  text: string,
  options: {
    createIdempotencyKey?: () => string;
    title?: string;
  } = {},
): WorkBackgroundMutation {
  const trimmed = text.trim();
  if (!trimmed) throw new TypeError("Background work requires a prompt.");
  const title = (options.title ?? "Background work").trim();
  if (!title) throw new TypeError("Background work requires a title.");
  const createIdempotencyKey =
    options.createIdempotencyKey ?? (() => globalThis.crypto.randomUUID());
  const idempotencyKey = createIdempotencyKey();
  if (idempotencyKey.length < 16 || idempotencyKey.length > 128) {
    throw new TypeError("Background work idempotency key is invalid.");
  }
  return {
    gateway_id: scope.gateway_id,
    idempotency_key: idempotencyKey,
    profile_id: scope.profile_id,
    text: trimmed,
    title,
  };
}

export function mutationMatchesScope(
  mutation: WorkBackgroundMutation,
  scope: WorkSyncScope,
): boolean {
  return (
    mutation.gateway_id === scope.gateway_id &&
    mutation.profile_id === scope.profile_id
  );
}

export class FabricWorkRpc {
  constructor(private readonly request: WorkGatewayRequest) {}

  async createBackgroundJob(
    sessionId: string,
    mutation: WorkBackgroundMutation,
  ): Promise<WorkJobMutationReceipt> {
    const raw = await this.request<unknown>("job.create", {
      idempotency_key: mutation.idempotency_key,
      kind: "background_prompt",
      session_id: sessionId,
      text: mutation.text,
      title: mutation.title,
    });
    const receipt = parseJobMutationReceipt(raw);
    if (
      receipt.job.kind !== "background_prompt" ||
      receipt.job.title !== mutation.title
    ) {
      throw new WorkContractInvalidError(
        "Job creation receipt did not match the submitted durable intent.",
      );
    }
    return receipt;
  }

  async sync(
    sessionId: string,
    params: {
      after?: number;
      ledger_id?: string;
      limit?: number;
      page_token?: string;
    } = {},
  ): Promise<WorkSyncPage> {
    let raw: unknown;
    try {
      raw = await this.request<unknown>("job.sync", {
        ...params,
        session_id: sessionId,
      });
    } catch (error) {
      if (error instanceof GatewayRpcError && error.code === -32047) {
        const parsed = parseWorkCursorReset({
          code: error.code,
          data: error.data,
          message: error.message,
        });
        if (parsed.kind === "verified") {
          throw new WorkCursorResetError(parsed.reset);
        }
      }
      throw error;
    }
    const parsed = parseWorkSyncPage(raw);
    if (parsed.kind === "incompatible") {
      throw new WorkContractIncompatibleError(parsed.minimum);
    }
    if (parsed.kind === "invalid") {
      throw new WorkContractInvalidError(parsed.message);
    }
    return parsed.page;
  }

  getJob(sessionId: string, jobId: string): Promise<WorkJobSummary> {
    return this.request("job.get", { job_id: jobId, session_id: sessionId });
  }

  listJobs(
    sessionId: string,
    params: Record<string, unknown> = {},
  ): Promise<WorkJobListResponse> {
    return this.request("job.list", { ...params, session_id: sessionId });
  }

  listJobEvents(
    sessionId: string,
    after: number,
    params: Record<string, unknown> = {},
  ): Promise<WorkJobEventsResponse> {
    return this.request("job.events", {
      ...params,
      after,
      session_id: sessionId,
    });
  }

  async cancelJob(
    sessionId: string,
    jobId: string,
    expectedVersion: number,
    idempotencyKey: string,
  ): Promise<WorkJobMutationReceipt> {
    const raw = await this.request<unknown>("job.cancel", {
      expected_version: expectedVersion,
      idempotency_key: idempotencyKey,
      job_id: jobId,
      session_id: sessionId,
    });
    return parseJobMutationReceipt(raw);
  }

  getAttention(sessionId: string, attentionId: string): Promise<WorkAttention> {
    return this.request("attention.get", {
      attention_id: attentionId,
      session_id: sessionId,
    });
  }

  listAttention(
    sessionId: string,
    params: Record<string, unknown> = {},
  ): Promise<WorkAttentionListResponse> {
    return this.request("attention.list", {
      ...params,
      session_id: sessionId,
    });
  }

  async respondToAttention(
    sessionId: string,
    attention: WorkAttention,
    input: {
      action: WorkAttentionAction;
      idempotency_key: string;
      reason?: string;
      value?: string;
    },
  ): Promise<WorkAttentionMutationReceipt> {
    const raw = await this.request<unknown>("attention.respond", {
      action: input.action,
      attention_id: attention.attention_id,
      expected_version: attention.version,
      idempotency_key: input.idempotency_key,
      session_id: sessionId,
      ...(input.reason === undefined ? {} : { reason: input.reason }),
      ...(input.value === undefined ? {} : { value: input.value }),
    });
    const receipt = parseAttentionMutationReceipt(raw);
    const expectedState =
      input.action === "deny" || input.action === "cancel"
        ? "denied"
        : "resolved";
    if (
      receipt.attention_id !== attention.attention_id ||
      receipt.attention_version <= attention.version ||
      receipt.state !== expectedState ||
      !receipt.delivered
    ) {
      throw new WorkContractInvalidError(
        "Attention response did not match the pending durable item.",
      );
    }
    return receipt;
  }
}

function sameScope(projection: WorkProjection, scope: WorkSyncScope): boolean {
  return (
    projection.gateway_id === scope.gateway_id &&
    projection.profile_id === scope.profile_id
  );
}

/**
 * Bring one profile projection current. Every page is parsed and fully applied
 * before its immutable projection (and therefore its cursor) is committed.
 */
export async function synchronizeWorkProjection(options: {
  commit: (commit: WorkSyncCommit) => void;
  initial: WorkProjection;
  isCurrent: () => boolean;
  rpc: FabricWorkRpc;
  scope: WorkSyncScope;
  sessionId: string;
}): Promise<WorkSyncResult> {
  const { commit, isCurrent, rpc, scope, sessionId } = options;
  let projection = options.initial;
  let bootstrap =
    !sameScope(projection, scope) || projection.phase !== "current";
  let pageToken: string | null = null;
  let resetCount = 0;
  const seenBootstrapTokens = new Set<string>();

  if (bootstrap) {
    projection = createWorkProjection(scope);
    if (isCurrent()) commit({ page: null, projection });
  }

  // A completed bootstrap is always followed by a delta from its fixed
  // watermark before callers publish Work as current.
  while (true) {
    if (!isCurrent()) return { kind: "stale", projection };
    let page: WorkSyncPage;
    try {
      page = bootstrap
        ? await rpc.sync(sessionId, {
            ...(pageToken === null ? {} : { page_token: pageToken }),
          })
        : await rpc.sync(sessionId, {
            after: projection.cursor as number,
            ledger_id: projection.ledger_id as string,
          });
    } catch (error) {
      if (error instanceof WorkCursorResetError && resetCount === 0) {
        if (!isCurrent()) return { kind: "stale", projection };
        projection = applyWorkCursorReset(projection, error.reset, scope);
        commit({ page: null, projection });
        bootstrap = true;
        pageToken = null;
        seenBootstrapTokens.clear();
        resetCount += 1;
        continue;
      }
      throw error;
    }
    if (!isCurrent()) return { kind: "stale", projection };
    if (
      (bootstrap && page.mode !== "bootstrap") ||
      (!bootstrap && page.mode !== "delta")
    ) {
      throw new WorkContractInvalidError(
        `job.sync returned ${page.mode} while the client requested ${bootstrap ? "bootstrap" : "delta"}.`,
      );
    }
    if (
      bootstrap &&
      page.has_more &&
      page.next_page_token !== null &&
      seenBootstrapTokens.has(page.next_page_token)
    ) {
      throw new WorkContractInvalidError(
        "job.sync repeated a bootstrap page token without completing bootstrap.",
      );
    }

    try {
      projection = applyWorkSyncPage(projection, page, {
        ...scope,
        ...(bootstrap
          ? { page_token: pageToken }
          : { after: projection.cursor as number }),
      });
    } catch (error) {
      if (
        error instanceof WorkSyncApplyError &&
        error.code === "ledger_changed" &&
        resetCount === 0
      ) {
        projection = createWorkProjection(scope);
        commit({ page: null, projection });
        bootstrap = true;
        pageToken = null;
        seenBootstrapTokens.clear();
        resetCount += 1;
        continue;
      }
      throw error;
    }
    commit({ page, projection });

    if (bootstrap && page.has_more) {
      pageToken = page.next_page_token;
      seenBootstrapTokens.add(pageToken as string);
      continue;
    }
    if (bootstrap) {
      bootstrap = false;
      pageToken = null;
      continue;
    }
    if (page.has_more) continue;
    return { kind: "current", projection };
  }
}

/** A durable call is never retried through the legacy method after failure. */
export async function submitBackgroundMutation(options: {
  mutation: WorkBackgroundMutation;
  protocol: Exclude<AdvertisedWorkProtocol, "unavailable">;
  request: WorkGatewayRequest;
  sessionId: string;
}): Promise<WorkJobMutationReceipt | { task_id: string | null }> {
  if (options.protocol === "durable") {
    return new FabricWorkRpc(options.request).createBackgroundJob(
      options.sessionId,
      options.mutation,
    );
  }
  const result = await options.request<unknown>("prompt.background", {
    session_id: options.sessionId,
    text: options.mutation.text,
  });
  return {
    task_id:
      isRecord(result) && typeof result.task_id === "string"
        ? result.task_id
        : null,
  };
}

export function workMutationErrorIsRetryable(error: unknown): boolean {
  if (!(error instanceof GatewayRpcError)) return false;
  if (["closed", "connect", "send", "timeout"].includes(error.kind)) {
    return true;
  }
  return (
    error.kind === "rpc" &&
    isRecord(error.data) &&
    error.data.retryable === true
  );
}
