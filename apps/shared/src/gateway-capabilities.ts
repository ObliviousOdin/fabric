import { GatewayRpcError, type JsonRpcGatewayClient } from "./json-rpc-gateway";

export const GATEWAY_CLIENT_CONTRACT_VERSION = 1;

// Gateway-host voice RPCs are deliberately absent: they record/play on the
// gateway machine, not the phone. Mobile voice needs a phone-audio contract.
export const GATEWAY_FEATURE_METHODS = {
  automation: ["cron.manage"],
  background_work: [
    "session.active_list",
    "prompt.background",
    "session.steer",
  ],
  baseline_chat: [
    "session.create",
    "session.list",
    "session.resume",
    "prompt.submit",
  ],
  code_session_baseline: [
    "projects.discover_repos",
    "session.branch",
    "session.undo",
  ],
  delegation: ["delegation.status", "spawn_tree.list"],
  files: ["image.attach_bytes", "pdf.attach", "file.attach"],
  handoff: ["handoff.request"],
  live_view: ["visual.status", "visual.frame"],
} as const;

/**
 * Additive feature gates introduced after the original version-1 fixture.
 * Their absence means "not advertised" so an older gateway remains a valid
 * version-1 peer; when present, the same method/feature invariant applies.
 */
export const OPTIONAL_GATEWAY_FEATURE_METHODS = {
  artifact_fetch: ["artifact.list", "artifact.fetch"],
  connected_nodes: ["node.list", "node.revoke"],
  device_node: ["node.enroll"],
  durable_work: [
    "job.create",
    "job.sync",
    "job.get",
    "job.list",
    "job.events",
    "job.cancel",
    "attention.get",
    "attention.list",
    "attention.respond",
  ],
  node_invoke: ["node.announce", "node.result", "node.reject"],
  push: ["push.register_device", "push.deregister_device"],
  session_admin: ["session.rename", "session.archive"],
  trust_center: [
    "trust.audit.list",
    "grant.list",
    "grant.create",
    "grant.revoke",
  ],
  workspace_read: ["fs.list", "fs.read"],
} as const;

/**
 * Optional features advertised as a bare boolean with no dedicated methods
 * (scoped_grants extends approval.respond params), so no method/feature
 * consistency check applies. Absence still means "not advertised" → false.
 */
export const OPTIONAL_GATEWAY_FEATURE_FLAGS = ["scoped_grants"] as const;

export type GatewayFeatureName =
  | keyof typeof GATEWAY_FEATURE_METHODS
  | keyof typeof OPTIONAL_GATEWAY_FEATURE_METHODS
  | (typeof OPTIONAL_GATEWAY_FEATURE_FLAGS)[number];

export const LEGACY_MOBILE_METHODS: ReadonlySet<string> = new Set([
  "approval.respond",
  "clarify.respond",
  "commands.catalog",
  "computer.screenshot",
  "process.kill",
  "process.list",
  "prompt.background",
  "prompt.submit",
  "secret.respond",
  "session.active_list",
  "session.close",
  "session.create",
  "session.interrupt",
  "session.list",
  "session.resume",
  "session.steer",
  "slash.exec",
  "sudo.respond",
]);

export interface GatewayCapabilities {
  contract: {
    min_compatible: number;
    name: "fabric.gateway";
    version: number;
  };
  execution: {
    location: "gateway";
    requires_gateway_host_online: true;
    survives_client_disconnect: true;
    survives_gateway_restart: false;
    tool_execution: "gateway";
  };
  features: Record<GatewayFeatureName, boolean>;
  methods: string[];
  server: {
    release_date: string;
    version: string;
  };
}

export type GatewayCompatibility =
  | { kind: "verified"; capabilities: GatewayCapabilities }
  | { kind: "legacy" }
  | { kind: "incompatible"; minimum: number }
  | { kind: "invalid"; message: string };

export type GatewayCapabilityClient = Pick<JsonRpcGatewayClient, "request">;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

function invalid(message: string): GatewayCompatibility {
  return { kind: "invalid", message };
}

/**
 * Parse the process-scoped mobile gateway contract.
 *
 * Unknown fields and method names are deliberately accepted. The execution
 * truth and known feature relationships are version-1 safety invariants, so a
 * contradictory response is invalid rather than silently treated as legacy.
 */
export function parseGatewayCapabilities(raw: unknown): GatewayCompatibility {
  if (!isRecord(raw)) {
    return invalid("Gateway capabilities must be an object.");
  }

  const contract = raw.contract;
  if (!isRecord(contract)) {
    return invalid("Gateway capabilities are missing a contract object.");
  }
  if (contract.name !== "fabric.gateway") {
    return invalid("Gateway capability contract name must be fabric.gateway.");
  }
  if (!isPositiveInteger(contract.version)) {
    return invalid(
      "Gateway capability contract version must be a positive integer.",
    );
  }
  if (!isPositiveInteger(contract.min_compatible)) {
    return invalid(
      "Gateway minimum compatible version must be a positive integer.",
    );
  }
  if (contract.min_compatible > contract.version) {
    return invalid(
      "Gateway minimum compatible version cannot exceed its contract version.",
    );
  }

  const server = raw.server;
  if (
    !isRecord(server) ||
    typeof server.version !== "string" ||
    !server.version.trim() ||
    typeof server.release_date !== "string" ||
    !server.release_date.trim()
  ) {
    return invalid("Gateway capabilities contain invalid server metadata.");
  }

  const execution = raw.execution;
  if (!isRecord(execution)) {
    return invalid("Gateway capabilities are missing execution semantics.");
  }
  if (
    execution.location !== "gateway" ||
    execution.tool_execution !== "gateway" ||
    execution.survives_client_disconnect !== true ||
    execution.survives_gateway_restart !== false ||
    execution.requires_gateway_host_online !== true
  ) {
    return invalid(
      "Gateway capabilities contradict the version-1 execution contract.",
    );
  }

  if (!Array.isArray(raw.methods)) {
    return invalid("Gateway capability methods must be an array.");
  }
  const methods: string[] = [];
  const methodSet = new Set<string>();
  for (const method of raw.methods) {
    if (typeof method !== "string" || !method.trim()) {
      return invalid("Gateway capability methods must be non-empty strings.");
    }
    if (methodSet.has(method)) {
      return invalid(`Gateway capability method is duplicated: ${method}.`);
    }
    methods.push(method);
    methodSet.add(method);
  }

  const rawFeatures = raw.features;
  if (!isRecord(rawFeatures)) {
    return invalid("Gateway capabilities are missing feature availability.");
  }
  const features = {} as Record<GatewayFeatureName, boolean>;
  for (const feature of Object.keys(
    GATEWAY_FEATURE_METHODS,
  ) as (keyof typeof GATEWAY_FEATURE_METHODS)[]) {
    const value = rawFeatures[feature];
    if (typeof value !== "boolean") {
      return invalid(`Gateway feature ${feature} must be a boolean.`);
    }
    const expected = GATEWAY_FEATURE_METHODS[feature].every((method) =>
      methodSet.has(method),
    );
    if (value !== expected) {
      return invalid(
        `Gateway feature ${feature} contradicts its advertised methods.`,
      );
    }
    features[feature] = value;
  }
  for (const feature of Object.keys(
    OPTIONAL_GATEWAY_FEATURE_METHODS,
  ) as (keyof typeof OPTIONAL_GATEWAY_FEATURE_METHODS)[]) {
    const value = rawFeatures[feature];
    const required = OPTIONAL_GATEWAY_FEATURE_METHODS[feature];
    const expected = required.every((method) => methodSet.has(method));
    if (value === undefined) {
      features[feature] = false;
      continue;
    }
    if (typeof value !== "boolean") {
      return invalid(`Gateway feature ${feature} must be a boolean.`);
    }
    if (value !== expected) {
      return invalid(
        `Gateway feature ${feature} contradicts its advertised methods.`,
      );
    }
    features[feature] = value;
  }
  for (const feature of OPTIONAL_GATEWAY_FEATURE_FLAGS) {
    const value = rawFeatures[feature];
    if (value === undefined) {
      features[feature] = false;
      continue;
    }
    if (typeof value !== "boolean") {
      return invalid(`Gateway feature ${feature} must be a boolean.`);
    }
    features[feature] = value;
  }

  if (contract.min_compatible > GATEWAY_CLIENT_CONTRACT_VERSION) {
    return { kind: "incompatible", minimum: contract.min_compatible };
  }

  return {
    kind: "verified",
    capabilities: {
      contract: {
        min_compatible: contract.min_compatible,
        name: "fabric.gateway",
        version: contract.version,
      },
      execution: {
        location: "gateway",
        requires_gateway_host_online: true,
        survives_client_disconnect: true,
        survives_gateway_restart: false,
        tool_execution: "gateway",
      },
      features,
      methods,
      server: {
        release_date: server.release_date,
        version: server.version,
      },
    },
  };
}

export async function negotiateGatewayCapabilities(
  client: GatewayCapabilityClient,
): Promise<GatewayCompatibility> {
  try {
    const raw = await client.request<unknown>("gateway.capabilities");
    return parseGatewayCapabilities(raw);
  } catch (error) {
    if (
      error instanceof GatewayRpcError &&
      error.kind === "rpc" &&
      error.code === -32601
    ) {
      return { kind: "legacy" };
    }
    throw error;
  }
}

/**
 * Whether a feature family is usable on this gateway. Mirrors the durable_work
 * precedent: an optional family only exists when a verified contract advertises
 * it true — a legacy gateway predates every optional family, and an
 * incompatible or invalid contract fails closed, even when the raw method
 * names would appear to overlap.
 */
export function supportsGatewayFeature(
  state: GatewayCompatibility,
  feature: GatewayFeatureName,
): boolean {
  return (
    state.kind === "verified" && state.capabilities.features[feature] === true
  );
}

export function supportsGatewayMethod(
  state: GatewayCompatibility,
  method: string,
): boolean {
  if (state.kind === "verified") {
    return state.capabilities.methods.includes(method);
  }
  return state.kind === "legacy" && LEGACY_MOBILE_METHODS.has(method);
}
