import { describe, expect, it, vi } from "vitest";

import incompatibleFixture from "../../mobile/contracts/gateway-capabilities-incompatible.json";
import malformedFixture from "../../mobile/contracts/gateway-capabilities-malformed.json";
import validFixture from "../../mobile/contracts/gateway-capabilities-v1.json";
import legacyMethodsFixture from "../../mobile/contracts/legacy-mobile-methods.json";
import { GatewayRpcError } from "./json-rpc-gateway";
import {
  GATEWAY_CLIENT_CONTRACT_VERSION,
  LEGACY_MOBILE_METHODS,
  negotiateGatewayCapabilities,
  parseGatewayCapabilities,
  supportsGatewayMethod,
  type GatewayCapabilityClient,
} from "./gateway-capabilities";

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
