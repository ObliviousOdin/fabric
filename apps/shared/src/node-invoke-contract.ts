/**
 * Canonical client reference implementation for the `fabric.node` v1 wire
 * contract (`node.announce` / `node.invoke` / `node.result` / `node.reject`).
 *
 * All timestamps on this contract — including `NodeInvocation.expires_at` —
 * are integer Unix epoch **milliseconds**, matching every `fabric.work`
 * timestamp.
 */

/** Reasons a node may return from `node.reject` (ARCHITECTURE.md §3). */
export const NODE_REJECT_REASONS = [
  "denied",
  "unsupported",
  "foreground_required",
  "grant_expired",
  "permission_denied",
  "capture_failed",
  "expired",
] as const;

/**
 * Ceiling on any in-memory node grant lifetime, in seconds
 * (ARCHITECTURE.md §3 fail-closed rule 4).
 */
export const NODE_GRANT_MAX_TTL_SECONDS = 900;

export type NodeRejectReason = (typeof NODE_REJECT_REASONS)[number];

export type NodeJsonValue =
  | null
  | boolean
  | number
  | string
  | NodeJsonValue[]
  | { [key: string]: NodeJsonValue };
export type NodeJsonObject = { [key: string]: NodeJsonValue };

export interface NodeAnnounceResult {
  accepted: readonly string[];
  node_token: string;
  routable: readonly string[];
}

export interface NodeInvocation {
  invocation_id: string;
  session_id: string;
  capability: string;
  reason: string;
  params: NodeJsonObject;
  /** Unix epoch milliseconds; the invocation is expired at this instant. */
  expires_at: number;
}

export type NodeAnnounceParseResult =
  | { kind: "verified"; result: NodeAnnounceResult }
  | { kind: "invalid"; message: string };

export type NodeInvocationParseResult =
  | { kind: "verified"; invocation: NodeInvocation }
  | { kind: "invalid"; message: string };

export type NodeValidationResult =
  | { kind: "valid" }
  | { kind: "invalid"; message: string };

class NodeDecodeError extends Error {}

function fail(message: string): never {
  throw new NodeDecodeError(message);
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
    fail(`${path}.${key} is required.`);
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

function arrayValue(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) fail(`${path} must be an array.`);
  return value;
}

function jsonValue(value: unknown, path: string): NodeJsonValue {
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
    const result: NodeJsonObject = {};
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

function jsonObject(value: unknown, path: string): NodeJsonObject {
  const parsed = jsonValue(record(value, path), path);
  return parsed as NodeJsonObject;
}

function capabilitySet(
  value: unknown,
  path: string,
  superset: { values: readonly string[]; name: string } | null,
): string[] {
  const parsed = arrayValue(value, path).map((item, index) =>
    stringValue(item, `${path}[${index}]`, { max: 128 }),
  );
  if (new Set(parsed).size !== parsed.length) {
    fail(`${path} must not contain duplicates.`);
  }
  if (superset !== null) {
    for (const capability of parsed) {
      if (!superset.values.includes(capability)) {
        fail(`${path} must be a subset of ${superset.name}.`);
      }
    }
  }
  return parsed;
}

/**
 * Parse the `node.announce` result against the capability set this node
 * actually announced. Fail-closed: `accepted` ⊆ announced, `routable` ⊆
 * `accepted`, no duplicates, non-empty `node_token` — any violation makes the
 * whole result invalid, so a partially implemented capability can never look
 * available.
 */
export function parseNodeAnnounceResult(
  value: unknown,
  announced: readonly string[],
): NodeAnnounceParseResult {
  try {
    const raw = record(value, "node.announce result");
    const accepted = capabilitySet(
      required(raw, "accepted", "node.announce result"),
      "node.announce result.accepted",
      { values: announced, name: "the announced capability set" },
    );
    const nodeToken = stringValue(
      required(raw, "node_token", "node.announce result"),
      "node.announce result.node_token",
      { max: 512 },
    );
    const routable = capabilitySet(
      required(raw, "routable", "node.announce result"),
      "node.announce result.routable",
      { values: accepted, name: "the accepted capability set" },
    );
    return {
      kind: "verified",
      result: { accepted, node_token: nodeToken, routable },
    };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof NodeDecodeError
          ? error.message
          : "node.announce result is malformed.",
    };
  }
}

/**
 * Parse one inbound `node.invoke` event frame. Strict: every field is
 * required and any mistyped field invalidates the whole invocation —
 * a malformed invocation is rejected, never partially executed.
 */
export function parseNodeInvocation(value: unknown): NodeInvocationParseResult {
  try {
    const raw = record(value, "node.invoke");
    return {
      kind: "verified",
      invocation: {
        invocation_id: stringValue(
          required(raw, "invocation_id", "node.invoke"),
          "node.invoke.invocation_id",
          { max: 128 },
        ),
        session_id: stringValue(
          required(raw, "session_id", "node.invoke"),
          "node.invoke.session_id",
          { max: 512 },
        ),
        capability: stringValue(
          required(raw, "capability", "node.invoke"),
          "node.invoke.capability",
          { max: 128 },
        ),
        reason: stringValue(
          required(raw, "reason", "node.invoke"),
          "node.invoke.reason",
          { max: 512, nonempty: false },
        ),
        params: jsonObject(
          required(raw, "params", "node.invoke"),
          "node.invoke.params",
        ),
        expires_at: safeInteger(
          required(raw, "expires_at", "node.invoke"),
          "node.invoke.expires_at",
        ),
      },
    };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof NodeDecodeError
          ? error.message
          : "node.invoke event is malformed.",
    };
  }
}

/**
 * Whether an invocation has expired at `nowMs` (Unix epoch milliseconds,
 * the same unit as `expires_at`). The deadline is exclusive: an invocation
 * is executable only while `expires_at` is strictly in the future
 * (ARCHITECTURE.md §3 fail-closed rule 3 — else `node.reject expired`).
 */
export function isNodeInvocationExpired(
  invocation: NodeInvocation,
  nowMs: number,
): boolean {
  return nowMs >= invocation.expires_at;
}

/**
 * Validate the `node.result` / `node.reject` receipt. The gateway must echo
 * the invocation it settled with `accepted: true` — anything else means the
 * settlement cannot be trusted and the caller must treat the send as failed.
 */
export function validateNodeReceipt(
  value: unknown,
  expectedInvocationId: string,
): NodeValidationResult {
  try {
    const raw = record(value, "node receipt");
    const invocationId = stringValue(
      required(raw, "invocation_id", "node receipt"),
      "node receipt.invocation_id",
      { max: 128 },
    );
    if (required(raw, "accepted", "node receipt") !== true) {
      fail("node receipt.accepted must be true.");
    }
    if (invocationId !== expectedInvocationId) {
      fail("node receipt.invocation_id must echo the settled invocation.");
    }
    return { kind: "valid" };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof NodeDecodeError
          ? error.message
          : "node receipt is malformed.",
    };
  }
}

/**
 * Validate an outbound `node.result` data payload before it is sent: a
 * non-empty mime, exactly one carrier (`bytes_b64` or `json`), optional
 * positive integer dimensions, and redaction entries whose optional
 * `region` is `[x, y, w, h]` non-negative integers.
 */
export function validateNodeCapturedData(
  value: unknown,
): NodeValidationResult {
  try {
    const raw = record(value, "node data");
    stringValue(required(raw, "mime", "node data"), "node data.mime", {
      max: 128,
    });
    const hasBytes = Object.prototype.hasOwnProperty.call(raw, "bytes_b64");
    const hasJson = Object.prototype.hasOwnProperty.call(raw, "json");
    if (hasBytes === hasJson) {
      fail("node data must carry exactly one of bytes_b64 and json.");
    }
    if (hasBytes) stringValue(raw.bytes_b64, "node data.bytes_b64");
    if (hasJson) jsonValue(raw.json, "node data.json");
    for (const key of ["width", "height"]) {
      if (Object.prototype.hasOwnProperty.call(raw, key)) {
        safeInteger(raw[key], `node data.${key}`, { minimum: 1 });
      }
    }
    const redactions = arrayValue(
      required(raw, "redactions", "node data"),
      "node data.redactions",
    );
    redactions.forEach((entry, index) => {
      const path = `node data.redactions[${index}]`;
      const redaction = record(entry, path);
      stringValue(required(redaction, "kind", path), `${path}.kind`, {
        max: 128,
      });
      if (Object.prototype.hasOwnProperty.call(redaction, "region")) {
        const region = arrayValue(redaction.region, `${path}.region`);
        if (region.length !== 4) {
          fail(`${path}.region must be [x, y, w, h].`);
        }
        region.forEach((component, componentIndex) =>
          safeInteger(component, `${path}.region[${componentIndex}]`),
        );
      }
    });
    return { kind: "valid" };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof NodeDecodeError
          ? error.message
          : "node data is malformed.",
    };
  }
}
