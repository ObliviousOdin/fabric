import { GatewayRpcError, type GatewayCapabilityClient } from "@fabric/shared";
import { describe, expect, it, vi } from "vitest";

import validFixture from "../../../mobile/contracts/gateway-capabilities-v1.json";
import {
  capabilityUnavailableMessage,
  mobileGatewaySupports,
  negotiateMobileGatewayConnection,
  type MobileGatewayCapabilityState,
} from "./capabilities";

function clientWith(
  implementation: () => Promise<unknown>,
  calls: string[],
): GatewayCapabilityClient {
  return {
    request: vi.fn(async (method: string) => {
      calls.push(method);
      return implementation();
    }) as GatewayCapabilityClient["request"],
  };
}

describe("mobile gateway capability lifecycle", () => {
  it("publishes negotiation before listing sessions", async () => {
    const calls: string[] = [];
    const published: string[] = [];

    await negotiateMobileGatewayConnection({
      client: clientWith(async () => validFixture, calls),
      isCurrent: () => true,
      publish: (state) => {
        published.push(state.kind);
        calls.push("publish");
      },
      refreshSessions: async () => {
        calls.push("session.list");
      },
    });

    expect(published).toEqual(["verified"]);
    expect(calls).toEqual(["gateway.capabilities", "publish", "session.list"]);
  });

  it("suppresses a late result from a superseded connection generation", async () => {
    let resolve!: (value: unknown) => void;
    const response = new Promise<unknown>((next) => {
      resolve = next;
    });
    let current = true;
    const publish = vi.fn();
    const refreshSessions = vi.fn(async () => undefined);
    const attempt = negotiateMobileGatewayConnection({
      client: clientWith(() => response, []),
      isCurrent: () => current,
      publish,
      refreshSessions,
    });

    current = false;
    resolve(validFixture);

    await expect(attempt).resolves.toBeNull();
    expect(publish).not.toHaveBeenCalled();
    expect(refreshSessions).not.toHaveBeenCalled();
  });

  it("preserves shipped session listing on a legacy gateway", async () => {
    const published: string[] = [];
    const refreshSessions = vi.fn(async () => undefined);

    await negotiateMobileGatewayConnection({
      client: clientWith(async () => {
        throw new GatewayRpcError("rpc", "method not found", { code: -32601 });
      }, []),
      isCurrent: () => true,
      publish: (state) => published.push(state.kind),
      refreshSessions,
    });

    expect(published).toEqual(["legacy"]);
    expect(refreshSessions).toHaveBeenCalledOnce();
  });

  it("publishes invalid contracts but issues no session call", async () => {
    const publish = vi.fn();
    const refreshSessions = vi.fn(async () => undefined);

    await negotiateMobileGatewayConnection({
      client: clientWith(async () => ({ nope: true }), []),
      isCurrent: () => true,
      publish,
      refreshSessions,
    });

    expect(publish).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "invalid" }),
    );
    expect(refreshSessions).not.toHaveBeenCalled();
  });
});

describe("mobile method gating", () => {
  it("uses exact verified methods and explicit legacy methods", () => {
    const verified = {
      kind: "verified",
      capabilities: validFixture,
    } as MobileGatewayCapabilityState;

    expect(mobileGatewaySupports(verified, "file.attach")).toBe(true);
    expect(mobileGatewaySupports(verified, "voice.record")).toBe(false);
    expect(mobileGatewaySupports(verified, "session.close")).toBe(true);
    expect(mobileGatewaySupports({ kind: "legacy" }, "prompt.submit")).toBe(
      true,
    );
    expect(mobileGatewaySupports({ kind: "legacy" }, "session.close")).toBe(
      true,
    );
    expect(mobileGatewaySupports({ kind: "legacy" }, "voice.record")).toBe(
      false,
    );
    expect(mobileGatewaySupports({ kind: "negotiating" }, "session.list")).toBe(
      false,
    );
    expect(mobileGatewaySupports(null, "session.list")).toBe(false);
  });

  it("describes blocked controls without collapsing invalid into legacy", () => {
    expect(
      capabilityUnavailableMessage({ kind: "negotiating" }, "session.list"),
    ).toContain("Checking");
    expect(
      capabilityUnavailableMessage(
        { kind: "incompatible", minimum: 2 },
        "session.list",
      ),
    ).toContain("contract 2");
    expect(
      capabilityUnavailableMessage(
        { kind: "invalid", message: "bad" },
        "session.list",
      ),
    ).toContain("invalid");
  });
});
