// @vitest-environment jsdom

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import gatewayFixture from "../../../mobile/contracts/gateway-capabilities-v1.json";
import incompatibleWorkFixture from "../../../mobile/contracts/fabric-work-v1/incompatible.json";
import { useMobileGateway } from "./use-mobile-gateway";

interface RpcRequest {
  id: number | string;
  method: string;
  params: Record<string, unknown>;
}

type RpcOutcome =
  | { error: { code: number; data?: unknown; message: string } }
  | { result: unknown };

class WorkWebSocket extends EventTarget {
  static readonly CLOSED = 3;
  static readonly CLOSING = 2;
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;

  static handler: (
    request: RpcRequest,
    socket: WorkWebSocket,
  ) => Promise<RpcOutcome> | RpcOutcome = () => ({ result: {} });
  static instances: WorkWebSocket[] = [];

  readyState = WorkWebSocket.CONNECTING;

  constructor(readonly url: string) {
    super();
    WorkWebSocket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = WorkWebSocket.OPEN;
      this.dispatchEvent(new Event("open"));
    });
  }

  close(): void {
    if (this.readyState === WorkWebSocket.CLOSED) return;
    this.readyState = WorkWebSocket.CLOSED;
    this.dispatchEvent(new Event("close"));
  }

  send(value: string): void {
    const request = JSON.parse(value) as RpcRequest;
    queueMicrotask(() => {
      void Promise.resolve(WorkWebSocket.handler(request, this)).then(
        (outcome) => {
          this.dispatchEvent(
            new MessageEvent("message", {
              data: JSON.stringify({
                id: request.id,
                jsonrpc: "2.0",
                ...outcome,
              }),
            }),
          );
        },
      );
    });
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

function durableGatewayFixture(): Record<string, unknown> {
  const fixture = structuredClone(gatewayFixture) as Record<string, unknown>;
  const features = fixture.features as Record<string, unknown>;
  const methods = fixture.methods as string[];
  features.durable_work = true;
  methods.push(
    "job.create",
    "job.sync",
    "job.get",
    "job.list",
    "job.events",
    "job.cancel",
    "attention.get",
    "attention.list",
    "attention.respond",
  );
  return fixture;
}

function workPage(
  mode: "bootstrap" | "delta",
  profileId = "profile_11111111111111111111111111111111",
  ledgerId = "ledger_11111111111111111111111111111111",
  attention: readonly Record<string, unknown>[] = [],
) {
  return {
    attention,
    contract: { min_compatible: 1, name: "fabric.work", version: 1 },
    cursor: 0,
    events: [],
    has_more: false,
    jobs: [],
    ledger_id: ledgerId,
    work_profile_id: profileId,
    mode,
    next_page_token: null,
    watermark: 0,
  };
}

function sessionPayload(
  runtimeId: string,
  profileId = "profile_11111111111111111111111111111111",
  storedSessionId = "stored-1",
) {
  return {
    info: {
      profile_name: "default",
      work_profile_id: profileId,
    },
    messages: [],
    running: false,
    session_id: runtimeId,
    session_key: storedSessionId,
    stored_session_id: storedSessionId,
  };
}

function emitWorkChanged(socket: WorkWebSocket, runtimeId: string): void {
  socket.dispatchEvent(
    new MessageEvent("message", {
      data: JSON.stringify({
        jsonrpc: "2.0",
        method: "event",
        params: { session_id: runtimeId, type: "work.changed" },
      }),
    }),
  );
}

function sensitiveAttention(version = 1): Record<string, unknown> {
  return {
    allowed_actions: ["submit", "cancel"],
    attention_id: "attn_ffffffffffffffffffffffffffffffff",
    blocking: true,
    created_at: 1_784_451_606_000,
    expires_at: null,
    job_id: null,
    kind: "secret",
    public_payload: { prompt: "Registry token" },
    request_id: "22222222222222222222222222222222",
    resolved_at: null,
    run_id: null,
    runtime_session_id: "runtime-attention",
    sensitive: true,
    source_session_key: "stored-attention",
    state: "pending",
    terminal_reason: null,
    title: "Authentication is required",
    updated_at: 1_784_451_606_000,
    version,
  };
}

afterEach(() => {
  WorkWebSocket.instances = [];
  WorkWebSocket.handler = () => ({ result: {} });
  vi.unstubAllGlobals();
});

describe("useMobileGateway durable Work adoption", () => {
  it("keeps trailing sync hints scoped when the active profile changes", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const profileA = "profile_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const profileB = "profile_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const ledgerA = "ledger_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const ledgerB = "ledger_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const firstA = deferred<RpcOutcome>();
    const firstB = deferred<RpcOutcome>();
    const syncCalls: Array<{ after: unknown; runtimeId: unknown }> = [];

    WorkWebSocket.handler = (request) => {
      if (request.method === "gateway.capabilities") {
        return { result: durableGatewayFixture() };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return { result: sessionPayload("runtime-a", profileA, "stored-a") };
      }
      if (request.method === "session.resume") {
        return { result: sessionPayload("runtime-b", profileB, "stored-b") };
      }
      if (request.method === "job.sync") {
        syncCalls.push({
          after: request.params.after,
          runtimeId: request.params.session_id,
        });
        if (request.params.session_id === "runtime-a") {
          if (
            syncCalls.filter((call) => call.runtimeId === "runtime-a")
              .length === 1
          ) {
            return firstA.promise;
          }
          return {
            result: workPage(
              request.params.after === undefined ? "bootstrap" : "delta",
              profileA,
              ledgerA,
            ),
          };
        }
        if (
          syncCalls.filter((call) => call.runtimeId === "runtime-b").length ===
          1
        ) {
          return firstB.promise;
        }
        return {
          result: workPage(
            request.params.after === undefined ? "bootstrap" : "delta",
            profileB,
            ledgerB,
          ),
        };
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://gateway.test",
        token: "token",
      });
      await result.current.createSession();
    });
    await waitFor(() => {
      expect(
        syncCalls.filter((call) => call.runtimeId === "runtime-a"),
      ).toHaveLength(1);
    });
    act(() => emitWorkChanged(WorkWebSocket.instances[0]!, "runtime-a"));

    let resume!: Promise<void>;
    act(() => {
      resume = result.current.resumeSession("stored-b");
    });
    await waitFor(() => {
      expect(
        syncCalls.filter((call) => call.runtimeId === "runtime-b"),
      ).toHaveLength(1);
    });
    act(() => emitWorkChanged(WorkWebSocket.instances[0]!, "runtime-b"));

    await act(async () => {
      firstA.resolve({ result: workPage("bootstrap", profileA, ledgerA) });
      await Promise.resolve();
    });
    expect(
      syncCalls.filter((call) => call.runtimeId === "runtime-a"),
    ).toHaveLength(1);

    await act(async () => {
      firstB.resolve({ result: workPage("bootstrap", profileB, ledgerB) });
      await resume;
    });
    await waitFor(() => {
      expect(
        syncCalls.filter((call) => call.runtimeId === "runtime-b"),
      ).toHaveLength(3);
      expect(result.current.workProjection).toMatchObject({
        gateway_id: expect.any(String),
        ledger_id: ledgerB,
        profile_id: profileB,
      });
      expect(result.current.workStatus).toBe("current");
    });
    expect(result.current.activeSession.runtimeSessionId).toBe("runtime-b");
    expect(
      syncCalls.filter((call) => call.runtimeId === "runtime-a"),
    ).toHaveLength(1);
    unmount();
  });

  it("does not restore a stale background failure after an explicit gateway switch", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const delayedCreate = deferred<RpcOutcome>();
    let createCalls = 0;
    WorkWebSocket.handler = (request, socket) => {
      if (request.method === "gateway.capabilities") {
        return { result: durableGatewayFixture() };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return { result: sessionPayload("runtime-a") };
      }
      if (request.method === "job.sync") {
        return {
          result: workPage(
            request.params.after === undefined ? "bootstrap" : "delta",
          ),
        };
      }
      if (request.method === "job.create") {
        expect(socket).toBe(WorkWebSocket.instances[0]);
        createCalls += 1;
        return delayedCreate.promise;
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://gateway-a.test",
        token: "token-a",
      });
    });
    let oldSubmission!: Promise<void>;
    act(() => {
      oldSubmission = result.current.runInBackground("Old gateway work");
    });
    const observedOldSubmission = oldSubmission.catch(
      (error: unknown) => error,
    );
    await waitFor(() => expect(createCalls).toBe(1));

    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://gateway-b.test",
        token: "token-b",
      });
      await observedOldSubmission;
    });
    await act(async () => {
      delayedCreate.resolve({
        result: {
          job: {
            job_id: "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            kind: "background_prompt",
            title: "Background work",
            version: 1,
          },
          mutation_id: "late-mutation",
          replayed: false,
          runtime_started: true,
          task_id: "late-task",
        },
      });
      await Promise.resolve();
    });

    expect(result.current.connection?.baseUrl).toBe("https://gateway-b.test");
    expect(result.current.backgroundSubmission).toEqual({
      error: null,
      jobId: null,
      retryable: false,
      status: "idle",
    });
    expect(result.current.error).toBeNull();
    unmount();
  });

  it("does not commit a delayed background receipt after switching profiles", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const profileA = "profile_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const profileB = "profile_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const delayedCreate = deferred<RpcOutcome>();
    let createCalls = 0;
    WorkWebSocket.handler = (request) => {
      if (request.method === "gateway.capabilities") {
        return { result: durableGatewayFixture() };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return { result: sessionPayload("runtime-a", profileA, "stored-a") };
      }
      if (request.method === "session.resume") {
        return { result: sessionPayload("runtime-b", profileB, "stored-b") };
      }
      if (request.method === "job.sync") {
        const isA = request.params.session_id === "runtime-a";
        return {
          result: workPage(
            request.params.after === undefined ? "bootstrap" : "delta",
            isA ? profileA : profileB,
            isA
              ? "ledger_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
              : "ledger_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          ),
        };
      }
      if (request.method === "job.create") {
        createCalls += 1;
        return delayedCreate.promise;
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://gateway.test",
        token: "token",
      });
    });
    let oldSubmission!: Promise<void>;
    act(() => {
      oldSubmission = result.current.runInBackground("Profile A work");
    });
    await waitFor(() => expect(createCalls).toBe(1));

    await act(async () => {
      await result.current.resumeSession("stored-b");
    });
    expect(result.current.backgroundSubmission.status).toBe("idle");

    await act(async () => {
      delayedCreate.resolve({
        result: {
          job: {
            job_id: "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            kind: "background_prompt",
            title: "Background work",
            version: 1,
          },
          mutation_id: "late-profile-a-mutation",
          replayed: false,
          runtime_started: true,
          task_id: "late-profile-a-task",
        },
      });
      await oldSubmission;
    });

    expect(result.current.activeSession).toMatchObject({
      messages: [],
      running: false,
      runtimeSessionId: "runtime-b",
      status: "idle",
    });
    expect(result.current.backgroundSubmission.status).toBe("idle");
    expect(result.current.workProjection).toMatchObject({
      profile_id: profileB,
    });
    unmount();
  });

  it("retains an Attention key only for the exact kind, revision, action, and value", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const attention = sensitiveAttention();
    const responses: Record<string, unknown>[] = [];
    WorkWebSocket.handler = (request) => {
      if (request.method === "gateway.capabilities") {
        return { result: durableGatewayFixture() };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return {
          result: sessionPayload(
            "runtime-attention",
            undefined,
            "stored-attention",
          ),
        };
      }
      if (request.method === "job.sync") {
        return {
          result: workPage(
            request.params.after === undefined ? "bootstrap" : "delta",
            undefined,
            undefined,
            request.params.after === undefined ? [attention] : [],
          ),
        };
      }
      if (request.method === "attention.respond") {
        responses.push(request.params);
        if (responses.length < 3) {
          return {
            error: {
              code: -32049,
              data: { code: "attention_delivery_pending", retryable: true },
              message: "Delivery status is unknown.",
            },
          };
        }
        return {
          result: {
            attention_id: attention.attention_id,
            attention_version: 2,
            delivered: true,
            mutation_id: "attention-mutation",
            replayed: false,
            state: "resolved",
          },
        };
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://gateway.test",
        token: "token",
      });
      await result.current.createSession();
    });
    await waitFor(() => expect(result.current.workStatus).toBe("current"));

    await expect(
      result.current.respondToWorkAttention(
        String(attention.attention_id),
        "once",
      ),
    ).rejects.toThrow(/not allowed/);
    expect(responses).toHaveLength(0);

    await act(async () => {
      await expect(
        result.current.respondToWorkAttention(
          String(attention.attention_id),
          "submit",
          "first-secret",
        ),
      ).rejects.toMatchObject({ code: -32049 });
      await expect(
        result.current.respondToWorkAttention(
          String(attention.attention_id),
          "submit",
          "first-secret",
        ),
      ).rejects.toMatchObject({ code: -32049 });
      await result.current.respondToWorkAttention(
        String(attention.attention_id),
        "submit",
        "edited-secret",
      );
    });

    expect(responses).toHaveLength(3);
    expect(responses[1]?.idempotency_key).toBe(responses[0]?.idempotency_key);
    expect(responses[2]?.idempotency_key).not.toBe(
      responses[0]?.idempotency_key,
    );
    expect(responses.map((response) => response.value)).toEqual([
      "first-secret",
      "first-secret",
      "edited-secret",
    ]);
    unmount();
  });

  it("keeps a delivered Attention response successful when reconciliation fails", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const attention = sensitiveAttention();
    let syncCalls = 0;
    let responseCalls = 0;
    WorkWebSocket.handler = (request) => {
      if (request.method === "gateway.capabilities") {
        return { result: durableGatewayFixture() };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return {
          result: sessionPayload(
            "runtime-attention",
            undefined,
            "stored-attention",
          ),
        };
      }
      if (request.method === "job.sync") {
        syncCalls += 1;
        if (syncCalls === 3) {
          return {
            error: { code: -32000, message: "Reconciliation unavailable." },
          };
        }
        return {
          result: workPage(
            request.params.after === undefined ? "bootstrap" : "delta",
            undefined,
            undefined,
            request.params.after === undefined ? [attention] : [],
          ),
        };
      }
      if (request.method === "attention.respond") {
        responseCalls += 1;
        return {
          result: {
            attention_id: attention.attention_id,
            attention_version: 2,
            delivered: true,
            mutation_id: "attention-mutation",
            replayed: false,
            state: "resolved",
          },
        };
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://gateway.test",
        token: "token",
      });
      await result.current.createSession();
    });
    await waitFor(() => expect(result.current.workStatus).toBe("current"));

    await act(async () => {
      await expect(
        result.current.respondToWorkAttention(
          String(attention.attention_id),
          "submit",
          "one-time-secret",
        ),
      ).resolves.toBeUndefined();
    });
    await waitFor(() => expect(result.current.workStatus).toBe("error"));
    expect(result.current.error).toBe("Reconciliation unavailable.");
    expect(responseCalls).toBe(1);
    await expect(
      result.current.respondToWorkAttention(
        String(attention.attention_id),
        "submit",
        "one-time-secret",
      ),
    ).rejects.toThrow(/no longer actionable/);
    expect(responseCalls).toBe(1);
    unmount();
  });

  it("retains one job.create key and retries it after reconnect", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const createParams: Record<string, unknown>[] = [];
    let createAttempt = 0;
    WorkWebSocket.handler = (request, socket) => {
      if (request.method === "gateway.capabilities") {
        return { result: durableGatewayFixture() };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return { result: sessionPayload("runtime-1") };
      }
      if (request.method === "session.resume") {
        return { result: sessionPayload("runtime-2") };
      }
      if (request.method === "job.sync") {
        return {
          result:
            request.params.after === undefined
              ? workPage("bootstrap")
              : workPage("delta"),
        };
      }
      if (request.method === "job.create") {
        createParams.push(request.params);
        createAttempt += 1;
        if (createAttempt === 1) {
          return {
            error: {
              code: -32049,
              data: { code: "work_capacity_exceeded", retryable: true },
              message: "Work capacity is temporarily full.",
            },
          };
        }
        expect(socket).toBe(WorkWebSocket.instances[1]);
        return {
          result: {
            job: {
              job_id: "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              kind: "background_prompt",
              title: "Background work",
              version: 1,
            },
            mutation_id: "mutation-1",
            replayed: true,
            runtime_started: false,
            task_id: "bg_replayed",
          },
        };
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://gateway.test",
        token: "token",
      });
    });
    await act(async () => {
      await expect(
        result.current.runInBackground("Review the release"),
      ).rejects.toMatchObject({ code: -32049 });
    });
    expect(result.current.backgroundSubmission).toMatchObject({
      retryable: true,
      status: "retryable",
    });
    expect(result.current.activeSession).toMatchObject({
      running: false,
      status: "idle",
    });

    await act(async () => {
      await result.current.reconnect();
    });
    await waitFor(() => {
      expect(result.current.backgroundSubmission).toMatchObject({
        jobId: "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        status: "started",
      });
    });
    expect(createParams).toHaveLength(2);
    expect(createParams[1]?.idempotency_key).toBe(
      createParams[0]?.idempotency_key,
    );
    expect(createParams[1]?.session_id).toBe("runtime-2");
    expect(result.current.activeSession).toMatchObject({
      running: false,
      status: "idle",
    });
    unmount();
  });

  it("does not cross-fallback when a timed-out durable attempt reconnects to a legacy contract", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const methods: string[] = [];
    WorkWebSocket.handler = (request, socket) => {
      methods.push(request.method);
      if (request.method === "gateway.capabilities") {
        return {
          result:
            socket === WorkWebSocket.instances[0]
              ? durableGatewayFixture()
              : gatewayFixture,
        };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return { result: sessionPayload("runtime-1") };
      }
      if (request.method === "session.resume") {
        return {
          result: {
            ...sessionPayload("runtime-2"),
            info: { profile_name: "legacy" },
          },
        };
      }
      if (request.method === "job.sync") {
        return {
          result:
            request.params.after === undefined
              ? workPage("bootstrap")
              : workPage("delta"),
        };
      }
      if (request.method === "job.create") {
        return {
          error: {
            code: -32049,
            data: { code: "work_capacity_exceeded", retryable: true },
            message: "Work capacity is temporarily full.",
          },
        };
      }
      if (request.method === "prompt.background") {
        return { result: { task_id: "must-not-run" } };
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://gateway.test",
        token: "token",
      });
      await expect(
        result.current.runInBackground("One durable intent"),
      ).rejects.toMatchObject({ code: -32049 });
      await result.current.reconnect();
    });

    expect(methods.filter((method) => method === "job.create")).toHaveLength(1);
    expect(methods).not.toContain("prompt.background");
    expect(result.current.backgroundSubmission).toMatchObject({
      retryable: false,
      status: "failed",
    });
    unmount();
  });

  it("uses prompt.background only when durable Work is not advertised", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const methods: string[] = [];
    WorkWebSocket.handler = (request) => {
      methods.push(request.method);
      if (request.method === "gateway.capabilities") {
        return { result: gatewayFixture };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return { result: sessionPayload("runtime-legacy") };
      }
      if (request.method === "prompt.background") {
        return { result: { task_id: "bg_legacy" } };
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://legacy.test",
        token: "token",
      });
      await result.current.runInBackground("Legacy background task");
    });

    expect(methods).toContain("prompt.background");
    expect(methods).not.toContain("job.create");
    expect(methods).not.toContain("job.sync");
    unmount();
  });

  it("fails closed when advertised Work proves incompatible", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const methods: string[] = [];
    WorkWebSocket.handler = (request) => {
      methods.push(request.method);
      if (request.method === "gateway.capabilities") {
        return { result: durableGatewayFixture() };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return { result: sessionPayload("runtime-incompatible") };
      }
      if (request.method === "job.sync") {
        return { result: incompatibleWorkFixture };
      }
      if (request.method === "prompt.background") {
        return { result: { task_id: "bg_compatibility_adapter" } };
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://future.test",
        token: "token",
      });
      await expect(
        result.current.runInBackground("Use the compatible path"),
      ).rejects.toThrow(/incompatible fabric\.work contract/);
    });

    expect(methods).toContain("job.sync");
    expect(methods).not.toContain("prompt.background");
    expect(methods).not.toContain("job.create");
    expect(result.current.workStatus).toBe("incompatible");
    expect(result.current.backgroundSubmission.status).toBe("failed");
    unmount();
  });

  it("fails advertised durable Work closed without the opaque server scope", async () => {
    vi.stubGlobal("WebSocket", WorkWebSocket);
    const methods: string[] = [];
    WorkWebSocket.handler = (request) => {
      methods.push(request.method);
      if (request.method === "gateway.capabilities") {
        return { result: durableGatewayFixture() };
      }
      if (request.method === "session.list")
        return { result: { sessions: [] } };
      if (request.method === "session.create") {
        return {
          result: {
            ...sessionPayload("runtime-missing-scope"),
            info: { profile_name: "display-name-must-not-be-used" },
          },
        };
      }
      if (request.method === "prompt.background") {
        return { result: { task_id: "must-not-run" } };
      }
      return { error: { code: -32601, message: "method not found" } };
    };

    const { result, unmount } = renderHook(() => useMobileGateway());
    await act(async () => {
      await result.current.connect({
        authMode: "token",
        baseUrl: "https://missing-scope.test",
        token: "token",
      });
      await expect(
        result.current.runInBackground("Must remain local"),
      ).rejects.toThrow(/work_profile_id/);
    });

    expect(methods).not.toContain("job.sync");
    expect(methods).not.toContain("job.create");
    expect(methods).not.toContain("prompt.background");
    expect(result.current.workProjection).toBeNull();
    expect(result.current.workStatus).toBe("error");
    unmount();
  });
});
