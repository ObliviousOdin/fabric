/** Canonical client reference implementation for the `fabric.trust` v1 wire contract. */

export const TRUST_CLIENT_CONTRACT_VERSION = 1;
export const TRUST_AUDIT_LIST_MAX_ENTRIES = 200;
export const TRUST_AUDIT_SUMMARY_MAX_CHARS = 512;

export const TRUST_AUDIT_ACTORS = ["agent", "user", "system"] as const;
export const TRUST_AUDIT_KINDS = [
  "capability_invocation",
  "approval",
  "grant_change",
  "node_change",
  "auth",
] as const;
export const TRUST_AUDIT_DECISIONS = ["allowed", "denied", "auto"] as const;
export const TRUST_GRANT_SCOPES = ["session", "always", "scoped"] as const;
export const TRUST_GRANT_SOURCES = ["mobile", "desktop", "cli"] as const;

export type TrustAuditActor = (typeof TRUST_AUDIT_ACTORS)[number];
export type TrustAuditKind = (typeof TRUST_AUDIT_KINDS)[number];
export type TrustAuditDecision = (typeof TRUST_AUDIT_DECISIONS)[number];
export type TrustGrantScope = (typeof TRUST_GRANT_SCOPES)[number];
export type TrustGrantSource = (typeof TRUST_GRANT_SOURCES)[number];

export interface TrustUnknownEnum {
  field: string;
  raw: string;
}

export interface TrustContractDescriptor {
  name: "fabric.trust";
  version: number;
  min_compatible: number;
}

export interface TrustAuditEntry {
  entry_id: number;
  at: number;
  actor: string;
  kind: string;
  method: string;
  session_id: string | null;
  session_title: string | null;
  node_id: string | null;
  grant_id: string | null;
  decision: string | null;
  summary: string;
  redacted: true;
  actionable: boolean;
  unknown_enums: readonly TrustUnknownEnum[];
}

export interface TrustAuditPage {
  contract: TrustContractDescriptor;
  cursor: number;
  next_before: number | null;
  entries: readonly TrustAuditEntry[];
  actionable: boolean;
  unknown_enums: readonly TrustUnknownEnum[];
}

export type TrustAuditPageParseResult =
  | { kind: "verified"; page: TrustAuditPage }
  | { kind: "incompatible"; minimum: number }
  | { kind: "invalid"; message: string };

export interface TrustGrant {
  grant_id: string;
  capability: string;
  scope: string;
  version: number;
  session_id: string | null;
  node_id: string | null;
  granted_at: number;
  expires_at: number | null;
  last_used_at: number | null;
  use_count: number;
  source: string;
  revocable: boolean;
  actionable: boolean;
  unknown_enums: readonly TrustUnknownEnum[];
}

export type TrustGrantListParseResult =
  | { kind: "verified"; grants: readonly TrustGrant[] }
  | { kind: "invalid"; message: string };

export interface TrustGrantRevokeReceipt {
  grant_id: string;
  revoked: boolean;
  revoked_at: number | null;
  grant_version: number;
  mutation_id: string;
  replayed: boolean;
}

export type TrustGrantRevokeReceiptParseResult =
  | { kind: "verified"; receipt: TrustGrantRevokeReceipt }
  | { kind: "invalid"; message: string };

export interface TrustScopedGrantReceipt {
  grant_id: string;
  expires_at: number | null;
}

export type TrustScopedGrantReceiptParseResult =
  | { kind: "verified"; receipt: TrustScopedGrantReceipt }
  | { kind: "none" }
  | { kind: "invalid"; message: string };

export interface TrustCursorReset {
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

export type TrustCursorResetParseResult =
  | { kind: "verified"; reset: TrustCursorReset }
  | { kind: "invalid"; message: string };

const TRUST_LEDGER_ID_PATTERN = /^ledger_[0-9a-f]{32}$/;

class TrustDecodeError extends Error {}

function fail(message: string): never {
  throw new TrustDecodeError(message);
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

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") fail(`${path} must be a boolean.`);
  return value;
}

function arrayValue(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) fail(`${path} must be an array.`);
  return value;
}

function optionalString(
  raw: Record<string, unknown>,
  key: string,
  path: string,
  options: { max?: number; nonempty?: boolean } = {},
): string | null {
  if (!Object.prototype.hasOwnProperty.call(raw, key) || raw[key] === null) {
    return null;
  }
  return stringValue(raw[key], `${path}.${key}`, options);
}

function optionalTimestamp(
  raw: Record<string, unknown>,
  key: string,
  path: string,
): number | null {
  if (!Object.prototype.hasOwnProperty.call(raw, key) || raw[key] === null) {
    return null;
  }
  return safeInteger(raw[key], `${path}.${key}`);
}

function enumValue(
  value: unknown,
  known: readonly string[],
  path: string,
  unknown: TrustUnknownEnum[],
): string {
  const parsed = stringValue(value, path, { max: 128 });
  if (!known.includes(parsed)) unknown.push({ field: path, raw: parsed });
  return parsed;
}

function parseContract(
  raw: Record<string, unknown>,
): TrustContractDescriptor | { incompatible: number } {
  const contract = record(required(raw, "contract", "trust"), "trust.contract");
  if (required(contract, "name", "trust.contract") !== "fabric.trust") {
    fail("trust.contract.name must be fabric.trust.");
  }
  const version = safeInteger(
    required(contract, "version", "trust.contract"),
    "trust.contract.version",
    { minimum: 1 },
  );
  const minimum = safeInteger(
    required(contract, "min_compatible", "trust.contract"),
    "trust.contract.min_compatible",
    { minimum: 1 },
  );
  if (minimum > version) {
    fail("trust.contract.min_compatible cannot exceed contract.version.");
  }
  if (minimum > TRUST_CLIENT_CONTRACT_VERSION) return { incompatible: minimum };
  return { name: "fabric.trust", version, min_compatible: minimum };
}

function parseAuditEntry(value: unknown, path: string): TrustAuditEntry {
  const raw = record(value, path);
  const unknown: TrustUnknownEnum[] = [];
  const decisionRaw = Object.prototype.hasOwnProperty.call(raw, "decision")
    ? raw.decision
    : null;
  const decision =
    decisionRaw === null
      ? null
      : enumValue(decisionRaw, TRUST_AUDIT_DECISIONS, `${path}.decision`, unknown);
  if (required(raw, "redacted", path) !== true) {
    fail(`${path}.redacted must be exactly true; unredacted audit material is never accepted.`);
  }
  const result: TrustAuditEntry = {
    entry_id: safeInteger(required(raw, "entry_id", path), `${path}.entry_id`, {
      minimum: 1,
    }),
    at: safeInteger(required(raw, "at", path), `${path}.at`),
    actor: enumValue(
      required(raw, "actor", path),
      TRUST_AUDIT_ACTORS,
      `${path}.actor`,
      unknown,
    ),
    kind: enumValue(
      required(raw, "kind", path),
      TRUST_AUDIT_KINDS,
      `${path}.kind`,
      unknown,
    ),
    method: stringValue(required(raw, "method", path), `${path}.method`, {
      max: 128,
    }),
    session_id: optionalString(raw, "session_id", path, { max: 512 }),
    session_title: optionalString(raw, "session_title", path, { max: 200 }),
    node_id: optionalString(raw, "node_id", path, { max: 128 }),
    grant_id: optionalString(raw, "grant_id", path, { max: 128 }),
    decision,
    summary: stringValue(required(raw, "summary", path), `${path}.summary`, {
      max: TRUST_AUDIT_SUMMARY_MAX_CHARS,
      nonempty: false,
    }),
    redacted: true,
    actionable: false,
    unknown_enums: unknown,
  };
  result.actionable = unknown.length === 0;
  return result;
}

/**
 * Parse and normalize one `trust.audit.list` page.
 *
 * Mirrors the `fabric.work` descriptor discipline: an embedded contract with a
 * `min_compatible` beyond this client is an honest incompatible result, never a
 * partial page. Every entry must be server-redacted (`redacted: true` exactly)
 * or the whole page is invalid, while compatible future enum values remain in
 * their raw fields and only make the containing entry non-actionable.
 */
export function parseTrustAuditPage(value: unknown): TrustAuditPageParseResult {
  try {
    const raw = record(value, "trust");
    const contract = parseContract(raw);
    if ("incompatible" in contract) {
      return { kind: "incompatible", minimum: contract.incompatible };
    }
    const cursor = safeInteger(
      required(raw, "cursor", "trust"),
      "trust.cursor",
    );
    const nextBefore = optionalTimestamp(raw, "next_before", "trust");
    const entries = arrayValue(
      required(raw, "entries", "trust"),
      "trust.entries",
    ).map((entry, index) => parseAuditEntry(entry, `trust.entries[${index}]`));
    if (entries.length > TRUST_AUDIT_LIST_MAX_ENTRIES) {
      fail(
        `trust.entries cannot exceed ${TRUST_AUDIT_LIST_MAX_ENTRIES} entries per page.`,
      );
    }
    let priorEntryId = 0;
    const unknown: TrustUnknownEnum[] = [];
    for (const entry of entries) {
      if (entry.entry_id <= priorEntryId) {
        fail("trust.entries entry_id values must be strictly increasing.");
      }
      priorEntryId = entry.entry_id;
      unknown.push(...entry.unknown_enums);
    }
    return {
      kind: "verified",
      page: {
        contract,
        cursor,
        next_before: nextBefore,
        entries,
        actionable: unknown.length === 0,
        unknown_enums: unknown,
      },
    };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof TrustDecodeError
          ? error.message
          : "Trust audit page is malformed.",
    };
  }
}

function parseGrant(value: unknown, path: string): TrustGrant {
  const raw = record(value, path);
  const unknown: TrustUnknownEnum[] = [];
  const result: TrustGrant = {
    grant_id: stringValue(required(raw, "grant_id", path), `${path}.grant_id`, {
      max: 128,
    }),
    capability: stringValue(
      required(raw, "capability", path),
      `${path}.capability`,
      { max: 128 },
    ),
    scope: enumValue(
      required(raw, "scope", path),
      TRUST_GRANT_SCOPES,
      `${path}.scope`,
      unknown,
    ),
    version: safeInteger(required(raw, "version", path), `${path}.version`, {
      minimum: 1,
    }),
    session_id: optionalString(raw, "session_id", path, { max: 512 }),
    node_id: optionalString(raw, "node_id", path, { max: 128 }),
    granted_at: safeInteger(
      required(raw, "granted_at", path),
      `${path}.granted_at`,
    ),
    expires_at: optionalTimestamp(raw, "expires_at", path),
    last_used_at: optionalTimestamp(raw, "last_used_at", path),
    use_count: safeInteger(
      required(raw, "use_count", path),
      `${path}.use_count`,
    ),
    source: enumValue(
      required(raw, "source", path),
      TRUST_GRANT_SOURCES,
      `${path}.source`,
      unknown,
    ),
    revocable: booleanValue(
      required(raw, "revocable", path),
      `${path}.revocable`,
    ),
    actionable: false,
    unknown_enums: unknown,
  };
  result.actionable = unknown.length === 0;
  return result;
}

/**
 * Parse the server-authoritative `grant.list` result.
 *
 * Grants carrying an unknown scope or source stay visible with their raw
 * values preserved but are non-actionable, so a v1 client never revokes or
 * renders controls for semantics it does not understand.
 */
export function parseTrustGrantList(value: unknown): TrustGrantListParseResult {
  try {
    const raw = record(value, "trust grants");
    const grants = arrayValue(
      required(raw, "grants", "trust grants"),
      "trust grants.grants",
    ).map((grant, index) => parseGrant(grant, `trust grants.grants[${index}]`));
    const grantIds = grants.map((grant) => grant.grant_id);
    if (new Set(grantIds).size !== grantIds.length) {
      fail("trust grants.grants contains a duplicate grant_id.");
    }
    return { kind: "verified", grants };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof TrustDecodeError
          ? error.message
          : "Trust grant list is malformed.",
    };
  }
}

/** True only when every enum on the grant is understood by this client. */
export function isTrustGrantActionable(grant: TrustGrant): boolean {
  return grant.unknown_enums.length === 0;
}

/**
 * Validate the `grant.revoke` receipt against the mutation it acknowledges.
 *
 * The receipt-echo discipline mirrors durable Work's `job.cancel`: the receipt
 * must echo the revoked grant_id, advance past the optimistic
 * `expected_version`, and carry the mutation_id/replayed idempotency evidence,
 * or the mutation is treated as unacknowledged.
 */
export function parseGrantRevokeReceipt(
  value: unknown,
  expectation: { grantId: string; expectedVersion: number },
): TrustGrantRevokeReceiptParseResult {
  try {
    const raw = record(value, "trust revoke");
    const grantId = stringValue(
      required(raw, "grant_id", "trust revoke"),
      "trust revoke.grant_id",
      { max: 128 },
    );
    if (grantId !== expectation.grantId) {
      fail("trust revoke.grant_id must echo the revoked grant_id.");
    }
    const grantVersion = safeInteger(
      required(raw, "grant_version", "trust revoke"),
      "trust revoke.grant_version",
      { minimum: 1 },
    );
    if (grantVersion <= expectation.expectedVersion) {
      fail("trust revoke.grant_version must exceed the expected version.");
    }
    return {
      kind: "verified",
      receipt: {
        grant_id: grantId,
        revoked: booleanValue(
          required(raw, "revoked", "trust revoke"),
          "trust revoke.revoked",
        ),
        revoked_at: optionalTimestamp(raw, "revoked_at", "trust revoke"),
        grant_version: grantVersion,
        mutation_id: stringValue(
          required(raw, "mutation_id", "trust revoke"),
          "trust revoke.mutation_id",
          { max: 128 },
        ),
        replayed: booleanValue(
          required(raw, "replayed", "trust revoke"),
          "trust revoke.replayed",
        ),
      },
    };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof TrustDecodeError
          ? error.message
          : "Trust revoke receipt is malformed.",
    };
  }
}

/**
 * Parse the additive scoped-grant extension of the `approval.respond` receipt.
 *
 * An older gateway omits `grant_id` entirely, which is the compatible "none"
 * result rather than an error; a receipt that does carry `grant_id` must carry
 * it as a non-empty string.
 */
export function parseScopedGrantReceipt(
  value: unknown,
): TrustScopedGrantReceiptParseResult {
  try {
    const raw = record(value, "trust scoped grant");
    if (!Object.prototype.hasOwnProperty.call(raw, "grant_id")) {
      return { kind: "none" };
    }
    return {
      kind: "verified",
      receipt: {
        grant_id: stringValue(raw.grant_id, "trust scoped grant.grant_id", {
          max: 128,
        }),
        expires_at: optionalTimestamp(raw, "expires_at", "trust scoped grant"),
      },
    };
  } catch (error) {
    return {
      kind: "invalid",
      message:
        error instanceof TrustDecodeError
          ? error.message
          : "Trust scoped grant receipt is malformed.",
    };
  }
}

/** Parse the sanitized `cursor_expired` reset returned by `trust.audit.list`. */
export function parseTrustCursorReset(
  value: unknown,
): TrustCursorResetParseResult {
  try {
    const raw = record(value, "trust reset");
    if (required(raw, "code", "trust reset") !== -32047) {
      fail("trust reset.code must be -32047.");
    }
    const data = record(
      required(raw, "data", "trust reset"),
      "trust reset.data",
    );
    if (required(data, "code", "trust reset.data") !== "cursor_expired") {
      fail("trust reset.data.code must be cursor_expired.");
    }
    if (required(data, "bootstrap", "trust reset.data") !== true) {
      fail("trust reset.data.bootstrap must be true.");
    }
    const optionalInteger = (key: string): number | null => {
      if (
        !Object.prototype.hasOwnProperty.call(data, key) ||
        data[key] === null
      ) {
        return null;
      }
      return safeInteger(data[key], `trust reset.data.${key}`);
    };
    const ledger =
      !Object.prototype.hasOwnProperty.call(data, "ledger_id") ||
      data.ledger_id === null
        ? null
        : stringValue(data.ledger_id, "trust reset.data.ledger_id");
    if (ledger !== null && !TRUST_LEDGER_ID_PATTERN.test(ledger)) {
      fail("trust reset.data.ledger_id must be a 128-bit ledger identifier.");
    }
    const eventFloor = optionalInteger("event_floor");
    const highWater = optionalInteger("high_water");
    if (
      eventFloor !== null &&
      highWater !== null &&
      eventFloor > highWater + 1
    ) {
      fail("trust reset event_floor cannot exceed high_water + 1.");
    }
    return {
      kind: "verified",
      reset: {
        code: -32047,
        message: stringValue(
          required(raw, "message", "trust reset"),
          "trust reset.message",
          { max: 512 },
        ),
        data: {
          code: "cursor_expired",
          bootstrap: true,
          reason:
            !Object.prototype.hasOwnProperty.call(data, "reason") ||
            data.reason === null
              ? null
              : stringValue(data.reason, "trust reset.data.reason", {
                  max: 128,
                }),
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
        error instanceof TrustDecodeError
          ? error.message
          : "Trust cursor reset is malformed.",
    };
  }
}
