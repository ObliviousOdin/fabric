import { describe, expect, it } from "vitest";

import taxonomyFixture from "../../mobile/contracts/gateway-error-taxonomy-v1.json";
import { GatewayRpcError } from "./json-rpc-gateway";
import {
  GATEWAY_ERROR_CLASSES,
  GATEWAY_RPC_ERROR_CODE_CLASSES,
  GATEWAY_TRANSPORT_KIND_CLASSES,
  classifyGatewayError,
  type GatewayErrorClass,
} from "./gateway-errors";

describe("gateway error taxonomy fixture parity", () => {
  it("mirrors the canonical class list exactly", () => {
    expect([...GATEWAY_ERROR_CLASSES]).toEqual(taxonomyFixture.classes);
  });

  it("mirrors the canonical rpc code map exactly", () => {
    const fixtureCodes = Object.fromEntries(
      Object.entries(taxonomyFixture.rpc_codes).map(([code, cls]) => [
        Number(code),
        cls,
      ]),
    );
    expect({ ...GATEWAY_RPC_ERROR_CODE_CLASSES }).toEqual(fixtureCodes);
  });

  it("mirrors the canonical transport kind map exactly", () => {
    expect({ ...GATEWAY_TRANSPORT_KIND_CLASSES }).toEqual(
      taxonomyFixture.transport_kinds,
    );
  });
});

describe("classifyGatewayError", () => {
  it("classifies every mapped rpc code per the taxonomy", () => {
    for (const [code, expected] of Object.entries(taxonomyFixture.rpc_codes)) {
      const error = new GatewayRpcError("rpc", "rpc failure", {
        code: Number(code),
      });
      expect(classifyGatewayError(error), code).toBe(expected);
    }
  });

  it("classifies every transport kind per the taxonomy", () => {
    for (const [kind, expected] of Object.entries(
      taxonomyFixture.transport_kinds,
    )) {
      const error = new GatewayRpcError(
        kind as ConstructorParameters<typeof GatewayRpcError>[0],
        "transport failure",
      );
      expect(classifyGatewayError(error), kind).toBe(expected);
    }
  });

  it("returns unknown for an unmapped rpc code", () => {
    const error = new GatewayRpcError("rpc", "novel failure", { code: 5099 });
    expect(classifyGatewayError(error)).toBe("unknown");
  });

  it("returns unknown for an rpc error carrying no code", () => {
    const error = new GatewayRpcError("rpc", "codeless failure");
    expect(classifyGatewayError(error)).toBe("unknown");
  });

  it("returns unknown for non-GatewayRpcError values", () => {
    expect(classifyGatewayError(new Error("plain"))).toBe("unknown");
    expect(classifyGatewayError("string failure")).toBe("unknown");
    expect(classifyGatewayError(null)).toBe("unknown");
    expect(classifyGatewayError(undefined)).toBe("unknown");
    expect(classifyGatewayError({ kind: "rpc", code: -32601 })).toBe("unknown");
  });

  it("reserves needs_reauth and denied: no producing code or kind exists yet", () => {
    const reserved: GatewayErrorClass[] = ["needs_reauth", "denied"];
    const produced = new Set<GatewayErrorClass>([
      ...Object.values(GATEWAY_RPC_ERROR_CODE_CLASSES),
      ...Object.values(GATEWAY_TRANSPORT_KIND_CLASSES),
      "unknown",
    ]);
    for (const cls of reserved) {
      expect(produced.has(cls), cls).toBe(false);
    }
  });
});
