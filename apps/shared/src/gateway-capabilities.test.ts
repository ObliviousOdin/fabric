import { describe, expect, it, vi } from "vitest";

import familiesFixture from "../../mobile/contracts/gateway-capabilities-families-v1.json";
import familyContradictionFixture from "../../mobile/contracts/gateway-capabilities-family-contradiction.json";
import incompatibleFixture from "../../mobile/contracts/gateway-capabilities-incompatible.json";
import malformedFixture from "../../mobile/contracts/gateway-capabilities-malformed.json";
import validFixture from "../../mobile/contracts/gateway-capabilities-v1.json";
import registryFixture from "../../mobile/contracts/gateway-feature-registry-v1.json";
import legacyMethodsFixture from "../../mobile/contracts/legacy-mobile-methods.json";
import { GatewayRpcError } from "./json-rpc-gateway";
import {
  GATEWAY_CLIENT_CONTRACT_VERSION,
  GATEWAY_FEATURE_METHODS,
  LEGACY_MOBILE_METHODS,
  OPTIONAL_GATEWAY_FEATURE_FLAGS,
  OPTIONAL_GATEWAY_FEATURE_METHODS,
  negotiateGatewayCapabilities,
  parseGatewayCapabilities,
  supportsGatewayFeature,
  supportsGatewayMethod,
  type GatewayCapabilityClient,
} from "./gateway-capabilities";

const NEW_OPTIONAL_FAMILIES = [
  "artifact_fetch",
  "connected_nodes",
  "device_node",
  "node_invoke",
  "push",
  "session_admin",
  "trust_center",
  "workspace_read",
] as const;

function clientReturning(value: unknown): GatewayCapabilityClient {
  return {
    request: vi.fn(async () => value) as GatewayCapabilityClient["request"],
  };
}

function clientRejecting(error: unknown): GatewayCapabilityClient {
  return {
    request: vi.fn(async () => {
      throw error;
    }) as GatewayCapabilityClient["request"],
  };
}

describe("gateway capability parsing", () => {
  it("accepts the canonical version-1 contract", () => {
    const result = parseGatewayCapabilities(validFixture);

    expect(result).toMatchObject({
      kind: "verified",
      capabilities: {
        contract: { name: "fabric.gateway", version: 1, min_compatible: 1 },
        execution: {
          location: "gateway",
          survives_client_disconnect: true,
          survives_gateway_restart: false,
          requires_gateway_host_online: true,
        },
        features: {
          code_session_baseline: true,
          durable_work: false,
        },
      },
    });
    expect(
      result.kind === "verified" && result.capabilities.features,
    ).not.toHaveProperty("voice");
    expect(
      result.kind === "verified" && result.capabilities.features,
    ).not.toHaveProperty("code");
    expect(
      result.kind === "verified" && result.capabilities.methods,
    ).not.toContain("voice.record");
    expect(
      result.kind === "verified" && result.capabilities.methods,
    ).not.toContain("voice.tts");
  });

  it("accepts an additive durable Work feature only with its complete method set", () => {
    const additive = structuredClone(validFixture) as Record<string, unknown>;
    const features = additive.features as Record<string, unknown>;
    const methods = additive.methods as string[];
    const durableMethods = [
      "job.create",
      "job.sync",
      "job.get",
      "job.list",
      "job.events",
      "job.cancel",
      "attention.get",
      "attention.list",
      "attention.respond",
    ];
    features.durable_work = true;
    methods.push(...durableMethods);

    expect(parseGatewayCapabilities(additive)).toMatchObject({
      kind: "verified",
      capabilities: { features: { durable_work: true } },
    });

    methods.pop();
    expect(parseGatewayCapabilities(additive)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("durable_work"),
    });
  });

  it("accepts compatible future versions, fields, and methods", () => {
    const additive = structuredClone(validFixture) as Record<string, unknown>;
    const contract = additive.contract as Record<string, unknown>;
    const server = additive.server as Record<string, unknown>;
    contract.version = GATEWAY_CLIENT_CONTRACT_VERSION + 1;
    contract.future_contract_field = true;
    server.channel = "stable";
    additive.future_top_level = { safe: true };
    (additive.methods as string[]).push("future.safe_method");

    const result = parseGatewayCapabilities(additive);

    expect(result.kind).toBe("verified");
    expect(result.kind === "verified" && result.capabilities.methods).toContain(
      "future.safe_method",
    );
  });

  it("classifies a valid higher minimum as incompatible", () => {
    expect(parseGatewayCapabilities(incompatibleFixture)).toEqual({
      kind: "incompatible",
      minimum: 2,
    });
  });

  it("rejects malformed or contradictory contracts instead of treating them as legacy", () => {
    expect(parseGatewayCapabilities(malformedFixture)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("execution contract"),
    });

    const contradictory = structuredClone(validFixture);
    contradictory.features.files = false;
    expect(parseGatewayCapabilities(contradictory)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("files"),
    });
  });

  it("rejects duplicate, empty, and non-string method names", () => {
    for (const methods of [
      [...validFixture.methods, validFixture.methods[0]],
      [...validFixture.methods, ""],
      [...validFixture.methods, 42],
    ]) {
      expect(
        parseGatewayCapabilities({ ...validFixture, methods }),
      ).toMatchObject({
        kind: "invalid",
      });
    }
  });
});

describe("gateway capability negotiation", () => {
  it("requests the authenticated capability method and parses its result", async () => {
    const client = clientReturning(validFixture);

    await expect(negotiateGatewayCapabilities(client)).resolves.toMatchObject({
      kind: "verified",
    });
    expect(client.request).toHaveBeenCalledWith("gateway.capabilities");
  });

  it("classifies only JSON-RPC method-not-found as legacy", async () => {
    const legacy = clientRejecting(
      new GatewayRpcError("rpc", "method not found", { code: -32601 }),
    );
    await expect(negotiateGatewayCapabilities(legacy)).resolves.toEqual({
      kind: "legacy",
    });

    for (const error of [
      new GatewayRpcError("timeout", "timed out"),
      new GatewayRpcError("closed", "closed"),
      new GatewayRpcError("rpc", "server error", { code: 5000 }),
      new Error("transport failed"),
    ]) {
      await expect(
        negotiateGatewayCapabilities(clientRejecting(error)),
      ).rejects.toBe(error);
    }
  });
});

describe("gateway method support", () => {
  it("keeps the explicit shipped-v1 legacy set in sync with the shared fixture", () => {
    expect([...LEGACY_MOBILE_METHODS].sort()).toEqual(
      [...legacyMethodsFixture].sort(),
    );
  });

  it("uses exact advertised methods for verified gateways", () => {
    const verified = parseGatewayCapabilities(validFixture);
    expect(supportsGatewayMethod(verified, "file.attach")).toBe(true);
    expect(supportsGatewayMethod(verified, "voice.record")).toBe(false);
    expect(supportsGatewayMethod(verified, "future.missing")).toBe(false);
  });

  it("allows only shipped-v1 methods for legacy and fails closed otherwise", () => {
    expect(supportsGatewayMethod({ kind: "legacy" }, "prompt.submit")).toBe(
      true,
    );
    expect(supportsGatewayMethod({ kind: "legacy" }, "session.close")).toBe(
      true,
    );
    expect(supportsGatewayMethod({ kind: "legacy" }, "voice.record")).toBe(
      false,
    );
    expect(
      supportsGatewayMethod(
        { kind: "incompatible", minimum: 2 },
        "prompt.submit",
      ),
    ).toBe(false);
    expect(
      supportsGatewayMethod(
        { kind: "invalid", message: "bad" },
        "prompt.submit",
      ),
    ).toBe(false);
  });
});

describe("gateway feature registry governance", () => {
  it("keeps the canonical registry fixture in parity with the TypeScript reference", () => {
    expect(registryFixture.contract).toEqual({
      name: "fabric.gateway",
      version: GATEWAY_CLIENT_CONTRACT_VERSION,
    });
    expect(registryFixture.baseline_features).toEqual(GATEWAY_FEATURE_METHODS);
    expect(registryFixture.optional_features).toEqual(
      OPTIONAL_GATEWAY_FEATURE_METHODS,
    );
    expect(registryFixture.flag_only_optional_features).toEqual([
      ...OPTIONAL_GATEWAY_FEATURE_FLAGS,
    ]);
    expect(new Set(registryFixture.legacy_mobile_methods)).toEqual(
      LEGACY_MOBILE_METHODS,
    );
  });
});

describe("optional gateway capability families", () => {
  it("verifies the families fixture with every new family true and durable_work dark", () => {
    const result = parseGatewayCapabilities(familiesFixture);

    expect(result.kind).toBe("verified");
    if (result.kind !== "verified") {
      return;
    }
    for (const family of NEW_OPTIONAL_FAMILIES) {
      expect(result.capabilities.features[family]).toBe(true);
    }
    expect(result.capabilities.features.scoped_grants).toBe(true);
    expect(result.capabilities.features.durable_work).toBe(false);
  });

  it("rejects a family whose required method set is missing", () => {
    expect(parseGatewayCapabilities(familyContradictionFixture)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("trust_center"),
    });
  });

  it("still verifies the original version-1 fixture with every new family false", () => {
    const result = parseGatewayCapabilities(validFixture);

    expect(result.kind).toBe("verified");
    if (result.kind !== "verified") {
      return;
    }
    for (const family of NEW_OPTIONAL_FAMILIES) {
      expect(result.capabilities.features[family]).toBe(false);
    }
    expect(result.capabilities.features.scoped_grants).toBe(false);
  });

  it("rejects an advertised-false family whose methods are all present", () => {
    const contradictory = structuredClone(familiesFixture) as Record<
      string,
      unknown
    >;
    (contradictory.features as Record<string, unknown>).push = false;

    expect(parseGatewayCapabilities(contradictory)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("push"),
    });
  });

  it("supports pets only when advertised true with its complete method set", () => {
    const additive = structuredClone(validFixture) as Record<string, unknown>;
    const features = additive.features as Record<string, unknown>;
    const methods = additive.methods as string[];
    features.pets = true;
    methods.push(
      "pet.info",
      "pet.info.meta",
      "pet.gallery",
      "pet.select",
      "pet.disable",
      "pet.thumb",
    );

    const result = parseGatewayCapabilities(additive);
    expect(result).toMatchObject({
      kind: "verified",
      capabilities: { features: { pets: true } },
    });
    expect(supportsGatewayFeature(result, "pets")).toBe(true);
  });

  it("rejects pets advertised true without its required methods", () => {
    const contradictory = structuredClone(validFixture) as Record<
      string,
      unknown
    >;
    (contradictory.features as Record<string, unknown>).pets = true;

    expect(parseGatewayCapabilities(contradictory)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("pets"),
    });
  });

  it("treats an absent pets family as not advertised", () => {
    const result = parseGatewayCapabilities(validFixture);

    expect(result.kind).toBe("verified");
    expect(
      result.kind === "verified" && result.capabilities.features.pets,
    ).toBe(false);
    expect(supportsGatewayFeature(result, "pets")).toBe(false);
  });

  it("treats scoped_grants as a pure flag with no method-set check", () => {
    const absent = parseGatewayCapabilities(validFixture);
    expect(
      absent.kind === "verified" && absent.capabilities.features.scoped_grants,
    ).toBe(false);

    const nonBoolean = structuredClone(validFixture) as Record<string, unknown>;
    (nonBoolean.features as Record<string, unknown>).scoped_grants = "yes";
    expect(parseGatewayCapabilities(nonBoolean)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("scoped_grants"),
    });

    const explicitFalse = structuredClone(validFixture) as Record<
      string,
      unknown
    >;
    (explicitFalse.features as Record<string, unknown>).scoped_grants = false;
    const result = parseGatewayCapabilities(explicitFalse);
    expect(result.kind).toBe("verified");
    expect(
      result.kind === "verified" && result.capabilities.features.scoped_grants,
    ).toBe(false);
  });
});

describe("gateway feature support", () => {
  it("supports a feature only on a verified contract advertising it true", () => {
    const families = parseGatewayCapabilities(familiesFixture);
    expect(supportsGatewayFeature(families, "trust_center")).toBe(true);
    expect(supportsGatewayFeature(families, "scoped_grants")).toBe(true);
    expect(supportsGatewayFeature(families, "durable_work")).toBe(false);

    const verified = parseGatewayCapabilities(validFixture);
    expect(supportsGatewayFeature(verified, "baseline_chat")).toBe(true);
    expect(supportsGatewayFeature(verified, "trust_center")).toBe(false);
  });

  it("never supports a feature for legacy, incompatible, or invalid states", () => {
    // Legacy gateways advertise every baseline_chat method, but a feature is
    // only real on a verified contract.
    expect(supportsGatewayFeature({ kind: "legacy" }, "baseline_chat")).toBe(
      false,
    );
    expect(supportsGatewayFeature({ kind: "legacy" }, "trust_center")).toBe(
      false,
    );
    expect(
      supportsGatewayFeature(
        { kind: "incompatible", minimum: 2 },
        "baseline_chat",
      ),
    ).toBe(false);
    expect(
      supportsGatewayFeature(
        { kind: "invalid", message: "bad" },
        "baseline_chat",
      ),
    ).toBe(false);
  });
});
