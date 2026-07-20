// @vitest-environment jsdom

import { act, renderHook, waitFor } from "@testing-library/react";
import type { GatewayCapabilities } from "@fabric/shared";
import { afterEach, describe, expect, it, vi } from "vitest";

import validFixture from "../../../mobile/contracts/gateway-capabilities-v1.json";
import { useMobileGateway } from "./use-mobile-gateway";

interface PendingCapability {
  id: number | string;
  socket: FakeWebSocket;
}

class FakeWebSocket extends EventTarget {
  static readonly CLOSED = 3;
  static readonly CLOSING = 2;
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;

  static pendingSecond: PendingCapability | null = null;

  readyState = FakeWebSocket.CONNECTING;

  constructor(readonly url: string) {
    super();
    queueMicrotask(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.dispatchEvent(new Event("open"));
    });
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatchEvent(new Event("close"));
  }

  send(value: string): void {
    const request = JSON.parse(value) as {
      id: number | string;
      method: string;
    };
    if (
      request.method === "gateway.capabilities" &&
      this.url.includes("second.test")
    ) {
      FakeWebSocket.pendingSecond = { id: request.id, socket: this };
      return;
    }

    queueMicrotask(() => {
      if (request.method === "gateway.capabilities") {
        this.receive(request.id, validFixture);
      } else if (request.method === "session.list") {
        this.receive(request.id, { sessions: [] });
      }
    });
  }

  receive(id: number | string, result: unknown): void {
    this.dispatchEvent(
      new MessageEvent("message", {
        data: JSON.stringify({ id, jsonrpc: "2.0", result }),
      }),
    );
  }
}

afterEach(() => {
  FakeWebSocket.pendingSecond = null;
  vi.unstubAllGlobals();
});

describe("useMobileGateway capability ownership", () => {
  it("clears the previous snapshot while switching gateways and accepts only the new one", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result, unmount } = renderHook(() => useMobileGateway());

    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://first.test",
        token: "first-token",
      });
    });

    expect(result.current.capabilityState?.kind).toBe("verified");
    expect(result.current.supportsMethod("file.attach")).toBe(true);

    let switching!: Promise<void>;
    act(() => {
      switching = result.current.connect({
        authMode: "token",
        baseUrl: "https://second.test",
        token: "second-token",
      });
    });

    await waitFor(() => {
      expect(result.current.capabilityState).toEqual({ kind: "negotiating" });
      expect(result.current.supportsMethod("file.attach")).toBe(false);
      expect(FakeWebSocket.pendingSecond).not.toBeNull();
    });

    const second = structuredClone(
      validFixture,
    ) as unknown as GatewayCapabilities;
    second.methods = second.methods.filter((method) => method !== "file.attach");
    second.features.files = false;
    const pending = FakeWebSocket.pendingSecond;
    if (!pending) {
      throw new Error("Expected a pending second capability request");
    }

    await act(async () => {
      pending.socket.receive(pending.id, second);
      await switching;
    });

    expect(result.current.capabilityState?.kind).toBe("verified");
    expect(result.current.supportsMethod("file.attach")).toBe(false);
    unmount();
  });
});
