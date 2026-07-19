import { afterEach, describe, expect, it, vi } from "vitest";

import {
  GatewayRpcError,
  JsonRpcGatewayClient,
  type WebSocketLike,
} from "./json-rpc-gateway";

class FakeWebSocket extends EventTarget {
  static readonly CLOSED = 3;
  static readonly CLOSING = 2;
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;

  readyState = FakeWebSocket.CONNECTING;
  readonly sent: string[] = [];

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatchEvent(new Event("close"));
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatchEvent(new Event("open"));
  }

  receive(frame: unknown): void {
    this.dispatchEvent(
      new MessageEvent("message", { data: JSON.stringify(frame) }),
    );
  }

  send(value: string): void {
    this.sent.push(value);
  }
}

function clientWith(socket: FakeWebSocket): JsonRpcGatewayClient {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  return new JsonRpcGatewayClient({
    connectTimeoutMs: 100,
    socketFactory: () => socket as unknown as WebSocketLike,
  });
}

async function openClient(
  client: JsonRpcGatewayClient,
  socket: FakeWebSocket,
): Promise<void> {
  const connecting = client.connect("ws://fabric.test/api/ws");
  socket.open();
  await connecting;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("JsonRpcGatewayClient errors", () => {
  it("preserves JSON-RPC code, data, and method", async () => {
    const socket = new FakeWebSocket();
    const client = clientWith(socket);
    await openClient(client, socket);

    const response = client.request("session.resume", { session_id: "stored" });
    const request = JSON.parse(socket.sent[0]) as { id: string };
    socket.receive({
      error: {
        code: 4007,
        data: { session_id: "stored" },
        message: "session not found",
      },
      id: request.id,
      jsonrpc: "2.0",
    });

    await expect(response).rejects.toMatchObject({
      code: 4007,
      data: { session_id: "stored" },
      kind: "rpc",
      message: "session not found",
      method: "session.resume",
      name: "GatewayRpcError",
    });
  });

  it("classifies request timeout without losing the method", async () => {
    vi.useFakeTimers();
    const socket = new FakeWebSocket();
    const client = clientWith(socket);
    await openClient(client, socket);

    const response = client.request("prompt.submit", {}, 25);
    const rejection = expect(response).rejects.toMatchObject({
      kind: "timeout",
      method: "prompt.submit",
    });
    await vi.advanceTimersByTimeAsync(25);
    await rejection;
  });

  it("classifies requests attempted on a closed socket", async () => {
    const client = clientWith(new FakeWebSocket());

    await expect(client.request("session.list")).rejects.toEqual(
      expect.objectContaining<Partial<GatewayRpcError>>({
        kind: "closed",
        method: "session.list",
      }),
    );
  });
});
