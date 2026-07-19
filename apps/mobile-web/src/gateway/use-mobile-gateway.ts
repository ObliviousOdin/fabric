import {
  JsonRpcGatewayClient,
  appendOptimisticUserMessage,
  appendRemoteSystemMessage,
  createEmptyRemoteSession,
  hydrateRemoteSession,
  normalizeRemoteGatewayBaseUrl,
  reduceRemoteSessionEvent,
  replayRemoteSessionEvents,
  resolveRemoteGatewayWebSocketUrl,
  type ConnectionState,
  type GatewayEvent,
  type RemoteBlockingPrompt,
  type RemoteGatewayConnection,
  type RemoteGatewayEventPayload,
  type RemoteSessionResumePayload,
  type RemoteSessionState,
  type RemoteSessionSummary,
} from "@fabric/shared";
import { useCallback, useEffect, useRef, useState } from "react";

import { resolveMobileSlashCommand } from "./slash";

interface SessionListResponse {
  sessions?: RemoteSessionSummary[];
}

interface CreateSessionOptions {
  cwd?: string;
  model?: string;
  provider?: string;
}

interface SendResult {
  prefill?: string;
}

export interface MobileGatewayApi {
  activeSession: RemoteSessionState;
  clearError: () => void;
  connect: (connection: RemoteGatewayConnection) => Promise<void>;
  connection: null | RemoteGatewayConnection;
  connectionState: ConnectionState;
  createSession: (options?: CreateSessionOptions) => Promise<RemoteSessionState>;
  disconnect: () => void;
  error: null | string;
  interrupt: () => Promise<void>;
  reconnect: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  respondToPrompt: (value: string, approvalChoice?: string) => Promise<void>;
  resumeSession: (storedSessionId: string) => Promise<void>;
  send: (text: string) => Promise<SendResult>;
  sessions: RemoteSessionSummary[];
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function viewportColumns(): number {
  if (typeof window === "undefined") {
    return 80;
  }
  return Math.max(48, Math.min(120, Math.floor(window.innerWidth / 8)));
}

export function useMobileGateway(): MobileGatewayApi {
  const [activeSession, setActiveSession] = useState(createEmptyRemoteSession);
  const [connection, setConnection] = useState<null | RemoteGatewayConnection>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [error, setError] = useState<null | string>(null);
  const [sessions, setSessions] = useState<RemoteSessionSummary[]>([]);

  const activeRuntimeIdRef = useRef<null | string>(null);
  const activeSessionRef = useRef(activeSession);
  const clientRef = useRef<JsonRpcGatewayClient | null>(null);
  const connectionRef = useRef<null | RemoteGatewayConnection>(null);
  const eventQueueRef = useRef<GatewayEvent<RemoteGatewayEventPayload>[]>([]);
  const generationRef = useRef(0);
  const hydratingRef = useRef(false);
  const repairInFlightRef = useRef(new Set<string>());
  const resumeSequenceRef = useRef(0);
  const runtimeByStoredRef = useRef(new Map<string, string>());
  const stateByRuntimeRef = useRef(new Map<string, RemoteSessionState>());
  const unsubscribeRef = useRef<Array<() => void>>([]);
  const applyEventRef = useRef<(event: GatewayEvent<RemoteGatewayEventPayload>) => void>(
    () => undefined,
  );

  const commitActive = useCallback((state: RemoteSessionState) => {
    activeSessionRef.current = state;
    activeRuntimeIdRef.current = state.runtimeSessionId;
    if (state.runtimeSessionId) {
      stateByRuntimeRef.current.set(state.runtimeSessionId, state);
    }
    if (state.runtimeSessionId && state.storedSessionId) {
      runtimeByStoredRef.current.set(state.storedSessionId, state.runtimeSessionId);
    }
    setActiveSession(state);
  }, []);

  const updateRuntime = useCallback(
    (runtimeId: string, updater: (state: RemoteSessionState) => RemoteSessionState) => {
      const current =
        stateByRuntimeRef.current.get(runtimeId) ??
        (activeRuntimeIdRef.current === runtimeId
          ? activeSessionRef.current
          : createEmptyRemoteSession());
      const next = updater(current);
      stateByRuntimeRef.current.set(runtimeId, next);
      if (activeRuntimeIdRef.current === runtimeId) {
        commitActive(next);
      }
      return next;
    },
    [commitActive],
  );

  const closeIdleRuntime = useCallback(
    (client: JsonRpcGatewayClient, runtimeId: null | string) => {
      if (!runtimeId || stateByRuntimeRef.current.get(runtimeId)?.running) {
        return;
      }
      stateByRuntimeRef.current.delete(runtimeId);
      for (const [storedId, mappedRuntime] of runtimeByStoredRef.current) {
        if (mappedRuntime === runtimeId) {
          runtimeByStoredRef.current.delete(storedId);
        }
      }
      void client
        .request("session.close", { session_id: runtimeId })
        .catch(() => undefined);
    },
    [],
  );

  const refreshSessionsWith = useCallback(async (client: JsonRpcGatewayClient) => {
    const result = await client.request<SessionListResponse>("session.list", {
      limit: 200,
    });
    setSessions(Array.isArray(result.sessions) ? result.sessions : []);
  }, []);

  const refreshSessions = useCallback(async () => {
    const client = clientRef.current;
    if (!client || client.connectionState !== "open") {
      return;
    }
    try {
      await refreshSessionsWith(client);
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, [refreshSessionsWith]);

  const hydrateWithClient = useCallback(
    async (
      client: JsonRpcGatewayClient,
      storedSessionId: string,
      generation: number,
    ): Promise<RemoteSessionState | null> => {
      const sequence = ++resumeSequenceRef.current;
      hydratingRef.current = true;
      eventQueueRef.current = [];

      try {
        const payload = await client.request<RemoteSessionResumePayload>(
          "session.resume",
          {
            cols: viewportColumns(),
            session_id: storedSessionId,
            source: "mobile-web",
          },
          45_000,
        );
        if (
          generation !== generationRef.current ||
          sequence !== resumeSequenceRef.current ||
          client !== clientRef.current
        ) {
          return null;
        }

        const previousRuntime = activeRuntimeIdRef.current;
        let hydrated = hydrateRemoteSession(
          payload,
          runtimeByStoredRef.current.has(storedSessionId)
            ? stateByRuntimeRef.current.get(
                runtimeByStoredRef.current.get(storedSessionId) as string,
              )
            : activeSessionRef.current,
        );
        const queued = eventQueueRef.current;
        eventQueueRef.current = [];
        hydratingRef.current = false;

        const replay = replayRemoteSessionEvents(
          hydrated,
          queued,
          payload.session_id,
        );
        hydrated = replay.state;

        stateByRuntimeRef.current.set(payload.session_id, hydrated);
        runtimeByStoredRef.current.set(storedSessionId, payload.session_id);
        commitActive(hydrated);
        setError(null);
        for (const deferredEvent of replay.deferredEvents) {
          applyEventRef.current(deferredEvent);
        }

        if (
          previousRuntime &&
          previousRuntime !== payload.session_id &&
          !stateByRuntimeRef.current.get(previousRuntime)?.running
        ) {
          closeIdleRuntime(client, previousRuntime);
        }
        void refreshSessionsWith(client).catch(() => undefined);
        return hydrated;
      } catch (requestError) {
        if (generation === generationRef.current && sequence === resumeSequenceRef.current) {
          setError(errorMessage(requestError));
        }
        throw requestError;
      } finally {
        if (sequence === resumeSequenceRef.current) {
          hydratingRef.current = false;
          const queued = eventQueueRef.current;
          eventQueueRef.current = [];
          for (const queuedEvent of queued) {
            applyEventRef.current(queuedEvent);
          }
        }
      }
    },
    [closeIdleRuntime, commitActive, refreshSessionsWith],
  );

  const applyGatewayEvent = useCallback(
    (event: GatewayEvent<RemoteGatewayEventPayload>) => {
      if (hydratingRef.current) {
        eventQueueRef.current.push(event);
        return;
      }

      const runtimeId = event.session_id || activeRuntimeIdRef.current;
      if (!runtimeId) {
        return;
      }
      const next = updateRuntime(runtimeId, (state) =>
        reduceRemoteSessionEvent(state, event),
      );

      if (event.type === "session.title" || event.type === "message.complete") {
        const client = clientRef.current;
        if (client?.connectionState === "open") {
          void refreshSessionsWith(client).catch(() => undefined);
        }
      }

      if (
        event.type === "message.complete" &&
        next.needsAuthoritativeResume &&
        next.storedSessionId &&
        activeRuntimeIdRef.current === runtimeId &&
        !repairInFlightRef.current.has(next.storedSessionId)
      ) {
        const client = clientRef.current;
        const generation = generationRef.current;
        if (client?.connectionState === "open") {
          repairInFlightRef.current.add(next.storedSessionId);
          queueMicrotask(() => {
            void hydrateWithClient(client, next.storedSessionId as string, generation)
              .catch(() => undefined)
              .finally(() => {
                repairInFlightRef.current.delete(next.storedSessionId as string);
              });
          });
        }
      }
    },
    [hydrateWithClient, refreshSessionsWith, updateRuntime],
  );
  applyEventRef.current = applyGatewayEvent;

  const disposeClient = useCallback((close: boolean) => {
    for (const unsubscribe of unsubscribeRef.current) {
      unsubscribe();
    }
    unsubscribeRef.current = [];
    const client = clientRef.current;
    clientRef.current = null;
    if (close) {
      client?.close();
    }
  }, []);

  const openConnection = useCallback(
    async (
      nextConnection: RemoteGatewayConnection,
      restoreStoredSessionId: null | string,
    ) => {
      const generation = ++generationRef.current;
      disposeClient(true);
      setConnectionState("connecting");
      setError(null);

      const client = new JsonRpcGatewayClient({
        connectTimeoutMs: 12_000,
        requestTimeoutMs: 30_000,
      });
      clientRef.current = client;
      unsubscribeRef.current = [
        client.onEvent((event) => {
          if (client === clientRef.current && generation === generationRef.current) {
            applyGatewayEvent(event as GatewayEvent<RemoteGatewayEventPayload>);
          }
        }),
        client.onState((state) => {
          if (client !== clientRef.current || generation !== generationRef.current) {
            return;
          }
          setConnectionState(state);
          if (state === "error") {
            setError("The gateway connection failed.");
          }
        }),
      ];

      try {
        const wsUrl = await resolveRemoteGatewayWebSocketUrl(nextConnection);
        if (generation !== generationRef.current) {
          return;
        }
        await client.connect(wsUrl);
        await refreshSessionsWith(client);
        if (restoreStoredSessionId) {
          stateByRuntimeRef.current.clear();
          runtimeByStoredRef.current.clear();
          activeRuntimeIdRef.current = null;
          await hydrateWithClient(
            client,
            restoreStoredSessionId,
            generation,
          );
        }
      } catch (connectionError) {
        if (generation === generationRef.current) {
          setError(errorMessage(connectionError));
          setConnectionState("error");
        }
        throw connectionError;
      }
    },
    [applyGatewayEvent, disposeClient, hydrateWithClient, refreshSessionsWith],
  );

  const connect = useCallback(
    async (nextConnection: RemoteGatewayConnection) => {
      const normalized = {
        ...nextConnection,
        baseUrl: normalizeRemoteGatewayBaseUrl(nextConnection.baseUrl),
      };
      connectionRef.current = normalized;
      setConnection(normalized);
      await openConnection(normalized, null);
    },
    [openConnection],
  );

  const reconnect = useCallback(async () => {
    const current = connectionRef.current;
    if (!current) {
      return;
    }
    const storedSessionId = activeSessionRef.current.storedSessionId;
    await openConnection(current, storedSessionId);
  }, [openConnection]);

  const disconnect = useCallback(() => {
    ++generationRef.current;
    resumeSequenceRef.current += 1;
    connectionRef.current = null;
    setConnection(null);
    disposeClient(true);
    stateByRuntimeRef.current.clear();
    runtimeByStoredRef.current.clear();
    commitActive(createEmptyRemoteSession());
    setConnectionState("idle");
    setSessions([]);
  }, [commitActive, disposeClient]);

  const createSession = useCallback(
    async (options: CreateSessionOptions = {}) => {
      const client = clientRef.current;
      if (!client || client.connectionState !== "open") {
        throw new Error("Connect to a Fabric gateway first");
      }

      const payload = await client.request<RemoteSessionResumePayload>(
        "session.create",
        {
          cols: viewportColumns(),
          source: "mobile-web",
          ...(options.cwd?.trim() ? { cwd: options.cwd.trim() } : {}),
          ...(options.model?.trim() ? { model: options.model.trim() } : {}),
          ...(options.provider?.trim()
            ? { provider: options.provider.trim() }
            : {}),
        },
      );
      const previousRuntime = activeRuntimeIdRef.current;
      const hydrated = hydrateRemoteSession(payload, createEmptyRemoteSession());
      commitActive(hydrated);
      if (previousRuntime !== hydrated.runtimeSessionId) {
        closeIdleRuntime(client, previousRuntime);
      }
      setError(null);
      return hydrated;
    },
    [closeIdleRuntime, commitActive],
  );

  const resumeSession = useCallback(
    async (storedSessionId: string) => {
      const client = clientRef.current;
      if (!client || client.connectionState !== "open") {
        throw new Error("Connect to a Fabric gateway first");
      }

      const warmRuntime = runtimeByStoredRef.current.get(storedSessionId);
      const warmState = warmRuntime
        ? stateByRuntimeRef.current.get(warmRuntime)
        : undefined;
      if (warmState) {
        const previousRuntime = activeRuntimeIdRef.current;
        commitActive(warmState);
        if (previousRuntime !== warmRuntime) {
          closeIdleRuntime(client, previousRuntime);
        }
        return;
      }

      await hydrateWithClient(client, storedSessionId, generationRef.current);
    },
    [closeIdleRuntime, commitActive, hydrateWithClient],
  );

  const send = useCallback(
    async (rawText: string): Promise<SendResult> => {
      const text = rawText.trim();
      if (!text) {
        return {};
      }
      const client = clientRef.current;
      if (!client || client.connectionState !== "open") {
        throw new Error("Connect to a Fabric gateway first");
      }

      let runtimeId = activeRuntimeIdRef.current;
      if (!runtimeId) {
        runtimeId = (await createSession()).runtimeSessionId;
      }
      if (!runtimeId) {
        throw new Error("Fabric did not create a live session");
      }

      let prompt = text;
      if (text.startsWith("/")) {
        const resolution = await resolveMobileSlashCommand(
          <T,>(method: string, params?: Record<string, unknown>) =>
            client.request<T>(method, params),
          runtimeId,
          text,
        );
        if (resolution.type === "prefill") {
          return { prefill: resolution.text };
        }
        if (resolution.type === "display") {
          updateRuntime(runtimeId, (state) =>
            appendRemoteSystemMessage(state, resolution.text),
          );
          return {};
        }
        prompt = resolution.text;
      }

      updateRuntime(runtimeId, (state) =>
        appendOptimisticUserMessage(state, prompt),
      );
      try {
        await client.request("prompt.submit", {
          session_id: runtimeId,
          text: prompt,
        });
      } catch (requestError) {
        const message = errorMessage(requestError);
        setError(message);
        updateRuntime(runtimeId, (state) => ({
          ...state,
          error: message,
          running: false,
          status: "error",
        }));
        throw requestError;
      }
      return {};
    },
    [createSession, updateRuntime],
  );

  const interrupt = useCallback(async () => {
    const client = clientRef.current;
    const runtimeId = activeRuntimeIdRef.current;
    if (!client || !runtimeId) {
      return;
    }
    await client.request("session.interrupt", { session_id: runtimeId });
    updateRuntime(runtimeId, (state) => ({
      ...state,
      pendingInteractions: [],
      running: false,
      status: "idle",
    }));
  }, [updateRuntime]);

  const respondToPrompt = useCallback(
    async (value: string, approvalChoice?: string) => {
      const client = clientRef.current;
      const runtimeId = activeRuntimeIdRef.current;
      const prompt: RemoteBlockingPrompt | null =
        activeSessionRef.current.pendingInteractions[0] ?? null;
      if (!client || !runtimeId || !prompt) {
        return;
      }

      if (prompt.type === "approval") {
        await client.request("approval.respond", {
          choice: approvalChoice || value || "deny",
          request_id: prompt.requestId,
          session_id: runtimeId,
        });
      } else if (prompt.type === "clarify") {
        await client.request("clarify.respond", {
          answer: value,
          request_id: prompt.requestId,
        });
      } else if (prompt.type === "sudo") {
        await client.request("sudo.respond", {
          password: value,
          request_id: prompt.requestId,
        });
      } else {
        await client.request("secret.respond", {
          request_id: prompt.requestId,
          value,
        });
      }

      updateRuntime(runtimeId, (state) => ({
        ...state,
        pendingInteractions: state.pendingInteractions.slice(1),
        status:
          state.pendingInteractions.length > 1
            ? "waiting"
            : state.running
              ? "working"
              : "idle",
      }));
    },
    [updateRuntime],
  );

  useEffect(() => {
    const restoreIfClosed = () => {
      if (
        document.visibilityState === "visible" &&
        navigator.onLine &&
        connectionRef.current &&
        clientRef.current?.connectionState !== "open" &&
        clientRef.current?.connectionState !== "connecting"
      ) {
        void reconnect().catch(() => undefined);
      }
    };
    const revalidateAfterWake = () => {
      if (
        document.visibilityState === "visible" &&
        navigator.onLine &&
        connectionRef.current &&
        clientRef.current?.connectionState !== "connecting"
      ) {
        // A mobile browser can freeze a socket without delivering `close`.
        // Always replace it on foreground and authoritatively resume the
        // durable session rather than trusting the stale readyState.
        void reconnect().catch(() => undefined);
      }
    };
    window.addEventListener("online", restoreIfClosed);
    document.addEventListener("visibilitychange", revalidateAfterWake);
    return () => {
      window.removeEventListener("online", restoreIfClosed);
      document.removeEventListener("visibilitychange", revalidateAfterWake);
    };
  }, [reconnect]);

  useEffect(
    () => () => {
      ++generationRef.current;
      disposeClient(true);
    },
    [disposeClient],
  );

  return {
    activeSession,
    clearError: () => setError(null),
    connect,
    connection,
    connectionState,
    createSession,
    disconnect,
    error,
    interrupt,
    reconnect,
    refreshSessions,
    respondToPrompt,
    resumeSession,
    send,
    sessions,
  };
}
