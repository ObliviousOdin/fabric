import {
  JsonRpcGatewayClient,
  appendOptimisticUserMessage,
  appendRemoteSystemMessage,
  createEmptyRemoteSession,
  createWorkProjection,
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
  type WorkAttentionAction,
  type WorkProjection,
  type WorkSyncScope,
} from "@fabric/shared";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  capabilityUnavailableMessage,
  mobileGatewaySupports,
  negotiateMobileGatewayConnection,
  type MobileGatewayCapabilityState,
} from "./capabilities";
import { resolveMobileSlashCommand } from "./slash";
import {
  FabricWorkRpc,
  WorkContractIncompatibleError,
  advertisedWorkProtocol,
  createBackgroundMutation,
  mutationMatchesScope,
  submitBackgroundMutation,
  synchronizeWorkProjection,
  workMutationErrorIsRetryable,
  type WorkBackgroundMutation,
  type WorkGatewayRequest,
} from "./work-client";

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

export type MobileWorkStatus =
  | "unavailable"
  | "legacy"
  | "syncing"
  | "current"
  | "incompatible"
  | "error";

export interface MobileBackgroundSubmission {
  error: string | null;
  jobId: string | null;
  retryable: boolean;
  status: "idle" | "submitting" | "retryable" | "failed" | "started";
}

interface PendingBackgroundSubmission {
  durableAttempted: boolean;
  mutation: WorkBackgroundMutation;
  protocol: "durable";
  status: "failed" | "retryable" | "submitting";
}

interface PendingAttentionMutation {
  action: WorkAttentionAction;
  idempotencyKey: string;
  kind: string;
  value: string | undefined;
  version: number;
}

export interface MobileGatewayApi {
  activeSession: RemoteSessionState;
  abandonBackgroundRetry: () => void;
  backgroundSubmission: MobileBackgroundSubmission;
  capabilityState: MobileGatewayCapabilityState;
  clearError: () => void;
  connect: (connection: RemoteGatewayConnection) => Promise<void>;
  connection: null | RemoteGatewayConnection;
  connectionState: ConnectionState;
  createSession: (
    options?: CreateSessionOptions,
  ) => Promise<RemoteSessionState>;
  disconnect: () => void;
  error: null | string;
  interrupt: () => Promise<void>;
  reconnect: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  respondToWorkAttention: (
    attentionId: string,
    action: WorkAttentionAction,
    value?: string,
  ) => Promise<void>;
  respondToPrompt: (value: string, approvalChoice?: string) => Promise<void>;
  retryBackground: () => Promise<void>;
  runInBackground: (text: string) => Promise<void>;
  resumeSession: (storedSessionId: string) => Promise<void>;
  send: (text: string) => Promise<SendResult>;
  sessions: RemoteSessionSummary[];
  supportsMethod: (method: string) => boolean;
  syncWork: () => Promise<void>;
  workProjection: WorkProjection | null;
  workStatus: MobileWorkStatus;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function assertMatchingInteractionReceipt(
  receipt: unknown,
  requestId: string,
  options: { approval?: boolean } = {},
): void {
  if (
    typeof receipt !== "object" ||
    receipt === null ||
    (receipt as { request_id?: unknown }).request_id !== requestId ||
    (options.approval && (receipt as { resolved?: unknown }).resolved !== 1)
  ) {
    throw new Error("Response did not match the pending request");
  }
}

function viewportColumns(): number {
  if (typeof window === "undefined") {
    return 80;
  }
  return Math.max(48, Math.min(120, Math.floor(window.innerWidth / 8)));
}

const WORK_PROFILE_ID_PATTERN = /^profile_[0-9a-f]{32}$/;

function workScopeFor(
  state: RemoteSessionState,
  gatewayIdentity: string,
): WorkSyncScope | null {
  const profileId = state.info.work_profile_id?.trim();
  if (
    !gatewayIdentity ||
    !profileId ||
    !WORK_PROFILE_ID_PATTERN.test(profileId)
  ) {
    return null;
  }
  return {
    gateway_id: gatewayIdentity,
    profile_id: profileId,
  };
}

function missingWorkScopeError(): Error {
  return new Error(
    "Durable Work was advertised without a stable work_profile_id in session.info.",
  );
}

function workRequestFor(client: JsonRpcGatewayClient): WorkGatewayRequest {
  return <T>(
    method: string,
    params?: Record<string, unknown>,
    timeoutMs?: number,
  ) => client.request<T>(method, params, timeoutMs);
}

function initialBackgroundSubmission(): MobileBackgroundSubmission {
  return {
    error: null,
    jobId: null,
    retryable: false,
    status: "idle",
  };
}

export function useMobileGateway(): MobileGatewayApi {
  const [activeSession, setActiveSession] = useState(createEmptyRemoteSession);
  const [backgroundSubmission, setBackgroundSubmission] =
    useState<MobileBackgroundSubmission>(initialBackgroundSubmission);
  const [capabilityState, setCapabilityState] =
    useState<MobileGatewayCapabilityState>(null);
  const [connection, setConnection] = useState<null | RemoteGatewayConnection>(
    null,
  );
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("idle");
  const [error, setError] = useState<null | string>(null);
  const [sessions, setSessions] = useState<RemoteSessionSummary[]>([]);
  const [workProjection, setWorkProjection] = useState<WorkProjection | null>(
    null,
  );
  const [workStatus, setWorkStatus] = useState<MobileWorkStatus>("unavailable");

  const activeRuntimeIdRef = useRef<null | string>(null);
  const activeSessionRef = useRef(activeSession);
  const capabilityStateRef = useRef<MobileGatewayCapabilityState>(null);
  const clientRef = useRef<JsonRpcGatewayClient | null>(null);
  const connectionRef = useRef<null | RemoteGatewayConnection>(null);
  const connectionIdentityRef = useRef("");
  const eventQueueRef = useRef<GatewayEvent<RemoteGatewayEventPayload>[]>([]);
  const generationRef = useRef(0);
  const hydratingRef = useRef(false);
  const pendingAttentionMutationRef = useRef(
    new Map<string, PendingAttentionMutation>(),
  );
  const pendingBackgroundRef = useRef<PendingBackgroundSubmission | null>(null);
  const repairInFlightRef = useRef(new Set<string>());
  const resumeSequenceRef = useRef(0);
  const runtimeByStoredRef = useRef(new Map<string, string>());
  const stateByRuntimeRef = useRef(new Map<string, RemoteSessionState>());
  const unsubscribeRef = useRef<Array<() => void>>([]);
  const workProjectionRef = useRef<WorkProjection | null>(null);
  const workStatusRef = useRef<MobileWorkStatus>("unavailable");
  const workSyncInFlightRef = useRef<{
    client: JsonRpcGatewayClient;
    gatewayId: string;
    generation: number;
    profileId: string;
    promise: Promise<void>;
    runtimeId: string;
    trailing: boolean;
  } | null>(null);
  const workSyncSequenceRef = useRef(0);
  const retryBackgroundRef = useRef<() => Promise<void>>(async () => undefined);
  const applyEventRef = useRef<
    (event: GatewayEvent<RemoteGatewayEventPayload>) => void
  >(() => undefined);

  const commitWorkStatus = useCallback((status: MobileWorkStatus) => {
    workStatusRef.current = status;
    setWorkStatus(status);
  }, []);

  const commitWorkProjection = useCallback(
    (projection: WorkProjection | null) => {
      for (const [
        attentionId,
        pending,
      ] of pendingAttentionMutationRef.current) {
        const attention = projection?.attention[attentionId];
        if (
          !attention ||
          attention.state !== "pending" ||
          !attention.actionable ||
          attention.kind !== pending.kind ||
          attention.version !== pending.version
        ) {
          pendingAttentionMutationRef.current.delete(attentionId);
        }
      }
      workProjectionRef.current = projection;
      setWorkProjection(projection);
    },
    [],
  );

  const commitCapabilityState = useCallback(
    (state: MobileGatewayCapabilityState) => {
      capabilityStateRef.current = state;
      setCapabilityState(state);
    },
    [],
  );

  const supportsMethod = useCallback(
    (method: string) =>
      mobileGatewaySupports(capabilityStateRef.current, method),
    [],
  );

  const requireMethod = useCallback((method: string) => {
    if (!mobileGatewaySupports(capabilityStateRef.current, method)) {
      throw new Error(
        capabilityUnavailableMessage(capabilityStateRef.current, method),
      );
    }
  }, []);

  const commitActive = useCallback(
    (state: RemoteSessionState) => {
      activeSessionRef.current = state;
      activeRuntimeIdRef.current = state.runtimeSessionId;
      const scope = workScopeFor(state, connectionIdentityRef.current);
      const pendingBackground = pendingBackgroundRef.current;
      if (
        pendingBackground &&
        scope &&
        !mutationMatchesScope(pendingBackground.mutation, scope)
      ) {
        pendingBackgroundRef.current = null;
        setBackgroundSubmission(initialBackgroundSubmission());
      }
      const currentWork = workProjectionRef.current;
      if (currentWork) {
        if (
          !scope ||
          currentWork.gateway_id !== scope.gateway_id ||
          currentWork.profile_id !== scope.profile_id
        ) {
          workSyncSequenceRef.current += 1;
          pendingAttentionMutationRef.current.clear();
          commitWorkProjection(null);
          commitWorkStatus("syncing");
        }
      }
      if (state.runtimeSessionId) {
        stateByRuntimeRef.current.set(state.runtimeSessionId, state);
      }
      if (state.runtimeSessionId && state.storedSessionId) {
        runtimeByStoredRef.current.set(
          state.storedSessionId,
          state.runtimeSessionId,
        );
      }
      setActiveSession(state);
    },
    [commitWorkProjection, commitWorkStatus],
  );

  const updateRuntime = useCallback(
    (
      runtimeId: string,
      updater: (state: RemoteSessionState) => RemoteSessionState,
    ) => {
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
      if (!mobileGatewaySupports(capabilityStateRef.current, "session.close")) {
        return;
      }
      void client
        .request("session.close", { session_id: runtimeId })
        .catch(() => undefined);
    },
    [],
  );

  const refreshSessionsWith = useCallback(
    async (client: JsonRpcGatewayClient) => {
      requireMethod("session.list");
      const generation = generationRef.current;
      const result = await client.request<SessionListResponse>("session.list", {
        limit: 200,
      });
      if (
        client !== clientRef.current ||
        generation !== generationRef.current
      ) {
        return;
      }
      setSessions(Array.isArray(result.sessions) ? result.sessions : []);
    },
    [requireMethod],
  );

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

  const syncWorkWith = useCallback(
    async (
      client: JsonRpcGatewayClient,
      runtimeId: string,
      sessionState: RemoteSessionState,
      generation: number,
    ) => {
      const protocol = advertisedWorkProtocol(capabilityStateRef.current);
      if (protocol !== "durable") {
        commitWorkProjection(null);
        commitWorkStatus(protocol === "legacy" ? "legacy" : "unavailable");
        return;
      }
      const sequence = ++workSyncSequenceRef.current;
      const scope = workScopeFor(sessionState, connectionIdentityRef.current);
      if (!scope) {
        if (
          client === clientRef.current &&
          generation === generationRef.current &&
          sequence === workSyncSequenceRef.current
        ) {
          const scopeError = missingWorkScopeError();
          commitWorkProjection(null);
          commitWorkStatus("error");
          setError(scopeError.message);
          throw scopeError;
        }
        return;
      }
      const initial = workProjectionRef.current ?? createWorkProjection(scope);
      commitWorkStatus("syncing");

      try {
        const result = await synchronizeWorkProjection({
          commit: ({ projection }) => {
            if (
              client === clientRef.current &&
              generation === generationRef.current &&
              sequence === workSyncSequenceRef.current
            ) {
              commitWorkProjection(projection);
            }
          },
          initial,
          isCurrent: () =>
            client === clientRef.current &&
            generation === generationRef.current &&
            sequence === workSyncSequenceRef.current,
          rpc: new FabricWorkRpc(workRequestFor(client)),
          scope,
          sessionId: runtimeId,
        });
        if (
          result.kind === "current" &&
          client === clientRef.current &&
          generation === generationRef.current &&
          sequence === workSyncSequenceRef.current
        ) {
          commitWorkProjection(result.projection);
          commitWorkStatus("current");
        }
      } catch (syncError) {
        if (
          client !== clientRef.current ||
          generation !== generationRef.current ||
          sequence !== workSyncSequenceRef.current
        ) {
          return;
        }
        if (syncError instanceof WorkContractIncompatibleError) {
          commitWorkProjection(null);
          commitWorkStatus("incompatible");
          return;
        }
        commitWorkStatus("error");
        setError(errorMessage(syncError));
        throw syncError;
      }
    },
    [commitWorkProjection, commitWorkStatus],
  );

  const queueWorkSyncWith = useCallback(
    (
      client: JsonRpcGatewayClient,
      runtimeId: string,
      sessionState: RemoteSessionState,
      generation: number,
    ): Promise<void> => {
      const inflight = workSyncInFlightRef.current;
      const scope = workScopeFor(sessionState, connectionIdentityRef.current);
      if (
        inflight &&
        inflight.client === client &&
        inflight.generation === generation &&
        inflight.runtimeId === runtimeId &&
        inflight.gatewayId === scope?.gateway_id &&
        inflight.profileId === scope?.profile_id
      ) {
        inflight.trailing = true;
        return inflight.promise.then(() => {
          if (!inflight.trailing) return;
          inflight.trailing = false;
          const currentRuntimeId = activeRuntimeIdRef.current;
          const currentSessionState = activeSessionRef.current;
          const currentScope = workScopeFor(
            currentSessionState,
            connectionIdentityRef.current,
          );
          if (
            workSyncInFlightRef.current !== null ||
            client !== clientRef.current ||
            generation !== generationRef.current ||
            !currentRuntimeId ||
            !currentScope ||
            currentScope.gateway_id !== inflight.gatewayId ||
            currentScope.profile_id !== inflight.profileId
          ) {
            return;
          }
          return queueWorkSyncWith(
            client,
            currentRuntimeId,
            currentSessionState,
            generation,
          );
        });
      }
      const promise = syncWorkWith(
        client,
        runtimeId,
        sessionState,
        generation,
      ).finally(() => {
        if (workSyncInFlightRef.current?.promise === promise) {
          workSyncInFlightRef.current = null;
        }
      });
      workSyncInFlightRef.current = {
        client,
        gatewayId: scope?.gateway_id ?? "",
        generation,
        profileId: scope?.profile_id ?? "",
        promise,
        runtimeId,
        trailing: false,
      };
      return promise;
    },
    [syncWorkWith],
  );

  const syncWork = useCallback(async () => {
    const client = clientRef.current;
    const runtimeId = activeRuntimeIdRef.current;
    if (!client || !runtimeId || client.connectionState !== "open") return;
    await queueWorkSyncWith(
      client,
      runtimeId,
      activeSessionRef.current,
      generationRef.current,
    );
  }, [queueWorkSyncWith]);

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
        requireMethod("session.resume");
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
        if (
          generation === generationRef.current &&
          sequence === resumeSequenceRef.current
        ) {
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
    [closeIdleRuntime, commitActive, refreshSessionsWith, requireMethod],
  );

  const applyGatewayEvent = useCallback(
    (event: GatewayEvent<RemoteGatewayEventPayload>) => {
      if (event.type === "work.changed") {
        const client = clientRef.current;
        const runtimeId = activeRuntimeIdRef.current;
        if (client?.connectionState === "open" && runtimeId) {
          void queueWorkSyncWith(
            client,
            runtimeId,
            activeSessionRef.current,
            generationRef.current,
          ).catch(() => undefined);
        }
        return;
      }
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
            void hydrateWithClient(
              client,
              next.storedSessionId as string,
              generation,
            )
              .catch(() => undefined)
              .finally(() => {
                repairInFlightRef.current.delete(
                  next.storedSessionId as string,
                );
              });
          });
        }
      }
    },
    [hydrateWithClient, queueWorkSyncWith, refreshSessionsWith, updateRuntime],
  );
  applyEventRef.current = applyGatewayEvent;

  const disposeClient = useCallback(
    (close: boolean) => {
      workSyncSequenceRef.current += 1;
      workSyncInFlightRef.current = null;
      for (const unsubscribe of unsubscribeRef.current) {
        unsubscribe();
      }
      unsubscribeRef.current = [];
      const client = clientRef.current;
      clientRef.current = null;
      commitCapabilityState(null);
      if (close) {
        client?.close();
      }
    },
    [commitCapabilityState],
  );

  const openConnection = useCallback(
    async (
      nextConnection: RemoteGatewayConnection,
      restoreStoredSessionId: null | string,
    ) => {
      const generation = ++generationRef.current;
      disposeClient(true);
      commitCapabilityState({ kind: "negotiating" });
      setError(null);
      setSessions([]);
      const existingWork = workProjectionRef.current;
      const gatewayId =
        connectionIdentityRef.current ||
        normalizeRemoteGatewayBaseUrl(nextConnection.baseUrl);
      if (existingWork && existingWork.gateway_id !== gatewayId) {
        commitWorkProjection(null);
      }
      commitWorkStatus("syncing");

      const client = new JsonRpcGatewayClient({
        connectTimeoutMs: 12_000,
        requestTimeoutMs: 30_000,
      });
      clientRef.current = client;
      unsubscribeRef.current = [
        client.onEvent((event) => {
          if (
            client === clientRef.current &&
            generation === generationRef.current
          ) {
            applyGatewayEvent(event as GatewayEvent<RemoteGatewayEventPayload>);
          }
        }),
        client.onState((state) => {
          if (
            client !== clientRef.current ||
            generation !== generationRef.current
          ) {
            return;
          }
          setConnectionState(state);
          if (state === "closed" || state === "error") {
            commitCapabilityState(null);
          }
          if (state === "error") {
            setError("The gateway connection failed.");
          }
        }),
      ];
      setConnectionState("connecting");

      try {
        const wsUrl = await resolveRemoteGatewayWebSocketUrl(nextConnection);
        if (generation !== generationRef.current) {
          return;
        }
        await client.connect(wsUrl);
        const compatibility = await negotiateMobileGatewayConnection({
          client,
          isCurrent: () =>
            client === clientRef.current &&
            generation === generationRef.current,
          publish: commitCapabilityState,
          refreshSessions: () => refreshSessionsWith(client),
        });
        if (
          !compatibility ||
          client !== clientRef.current ||
          generation !== generationRef.current ||
          !mobileGatewaySupports(compatibility, "session.list")
        ) {
          return;
        }
        const workProtocol = advertisedWorkProtocol(compatibility);
        if (workProtocol !== "durable") {
          commitWorkProjection(null);
          commitWorkStatus(
            workProtocol === "legacy" ? "legacy" : "unavailable",
          );
        }
        if (
          restoreStoredSessionId &&
          mobileGatewaySupports(compatibility, "session.resume")
        ) {
          stateByRuntimeRef.current.clear();
          runtimeByStoredRef.current.clear();
          activeRuntimeIdRef.current = null;
          const hydrated = await hydrateWithClient(
            client,
            restoreStoredSessionId,
            generation,
          );
          if (hydrated?.runtimeSessionId) {
            await queueWorkSyncWith(
              client,
              hydrated.runtimeSessionId,
              hydrated,
              generation,
            ).catch(() => undefined);
            await retryBackgroundRef.current().catch(() => undefined);
          }
        } else if (restoreStoredSessionId) {
          setError(
            capabilityUnavailableMessage(compatibility, "session.resume"),
          );
        }
      } catch (connectionError) {
        if (generation === generationRef.current) {
          commitCapabilityState(null);
          setError(errorMessage(connectionError));
          setConnectionState("error");
        }
        throw connectionError;
      }
    },
    [
      applyGatewayEvent,
      commitCapabilityState,
      commitWorkProjection,
      commitWorkStatus,
      disposeClient,
      hydrateWithClient,
      queueWorkSyncWith,
      refreshSessionsWith,
    ],
  );

  const connect = useCallback(
    async (nextConnection: RemoteGatewayConnection) => {
      const normalized = {
        ...nextConnection,
        baseUrl: normalizeRemoteGatewayBaseUrl(nextConnection.baseUrl),
      };
      connectionIdentityRef.current = `${normalized.baseUrl}#${globalThis.crypto.randomUUID()}`;
      workSyncSequenceRef.current += 1;
      pendingBackgroundRef.current = null;
      pendingAttentionMutationRef.current.clear();
      commitWorkProjection(null);
      commitWorkStatus("syncing");
      setBackgroundSubmission(initialBackgroundSubmission());
      connectionRef.current = normalized;
      setConnection(normalized);
      await openConnection(normalized, null);
    },
    [commitWorkProjection, commitWorkStatus, openConnection],
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
    connectionIdentityRef.current = "";
    setConnection(null);
    disposeClient(true);
    stateByRuntimeRef.current.clear();
    runtimeByStoredRef.current.clear();
    pendingAttentionMutationRef.current.clear();
    pendingBackgroundRef.current = null;
    commitWorkProjection(null);
    commitWorkStatus("unavailable");
    setBackgroundSubmission(initialBackgroundSubmission());
    commitActive(createEmptyRemoteSession());
    setConnectionState("idle");
    setSessions([]);
  }, [commitActive, commitWorkProjection, commitWorkStatus, disposeClient]);

  const createSession = useCallback(
    async (options: CreateSessionOptions = {}) => {
      const client = clientRef.current;
      if (!client || client.connectionState !== "open") {
        throw new Error("Connect to a Fabric gateway first");
      }

      requireMethod("session.create");
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
      const hydrated = hydrateRemoteSession(
        payload,
        createEmptyRemoteSession(),
      );
      commitActive(hydrated);
      if (previousRuntime !== hydrated.runtimeSessionId) {
        closeIdleRuntime(client, previousRuntime);
      }
      setError(null);
      if (hydrated.runtimeSessionId) {
        void queueWorkSyncWith(
          client,
          hydrated.runtimeSessionId,
          hydrated,
          generationRef.current,
        ).catch(() => undefined);
      }
      return hydrated;
    },
    [closeIdleRuntime, commitActive, queueWorkSyncWith, requireMethod],
  );

  const resumeSession = useCallback(
    async (storedSessionId: string) => {
      const client = clientRef.current;
      if (!client || client.connectionState !== "open") {
        throw new Error("Connect to a Fabric gateway first");
      }
      requireMethod("session.resume");

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
        if (warmRuntime) {
          await queueWorkSyncWith(
            client,
            warmRuntime,
            warmState,
            generationRef.current,
          );
        }
        return;
      }

      const hydrated = await hydrateWithClient(
        client,
        storedSessionId,
        generationRef.current,
      );
      if (hydrated?.runtimeSessionId) {
        await queueWorkSyncWith(
          client,
          hydrated.runtimeSessionId,
          hydrated,
          generationRef.current,
        );
      }
    },
    [
      closeIdleRuntime,
      commitActive,
      hydrateWithClient,
      queueWorkSyncWith,
      requireMethod,
    ],
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
          <T>(method: string, params?: Record<string, unknown>) => {
            requireMethod(method);
            return client.request<T>(method, params);
          },
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

      requireMethod("prompt.submit");
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
    [createSession, requireMethod, updateRuntime],
  );

  const submitBackgroundWith = useCallback(
    async (mutation: WorkBackgroundMutation) => {
      const client = clientRef.current;
      const runtimeId = activeRuntimeIdRef.current;
      const currentConnection = connectionRef.current;
      const submissionGatewayId = connectionIdentityRef.current;
      const submissionGeneration = generationRef.current;
      if (
        !client ||
        !runtimeId ||
        !currentConnection ||
        client.connectionState !== "open"
      ) {
        throw new Error("Connect to a Fabric gateway first");
      }
      const protocol = advertisedWorkProtocol(capabilityStateRef.current);
      const priorDurableAttempt = Boolean(
        pendingBackgroundRef.current?.mutation === mutation &&
        pendingBackgroundRef.current.durableAttempted,
      );
      if (priorDurableAttempt && protocol !== "durable") {
        throw new Error(
          "The durable submission cannot safely fall back after its first attempt. Reconnect to a compatible Work gateway or dismiss it.",
        );
      }
      if (protocol === "durable") {
        const scope = workScopeFor(
          activeSessionRef.current,
          connectionIdentityRef.current,
        );
        if (!scope) throw missingWorkScopeError();
        if (!mutationMatchesScope(mutation, scope)) {
          pendingBackgroundRef.current = {
            durableAttempted: priorDurableAttempt,
            mutation,
            protocol: "durable",
            status: "failed",
          };
          setBackgroundSubmission({
            error:
              "This background submission belongs to another gateway or profile. Dismiss it before starting new work.",
            jobId: null,
            retryable: false,
            status: "failed",
          });
          throw new Error("Background submission identity changed");
        }
        if (
          workStatusRef.current !== "current" ||
          workProjectionRef.current?.gateway_id !== scope.gateway_id ||
          workProjectionRef.current?.profile_id !== scope.profile_id
        ) {
          await queueWorkSyncWith(
            client,
            runtimeId,
            activeSessionRef.current,
            generationRef.current,
          );
        }
        if (workStatusRef.current === "incompatible") {
          throw new Error(
            "This gateway advertises Durable Work but requires an incompatible fabric.work contract.",
          );
        }
        if (
          workStatusRef.current !== "current" ||
          workProjectionRef.current?.gateway_id !== scope.gateway_id ||
          workProjectionRef.current?.profile_id !== scope.profile_id
        ) {
          throw new Error("Durable Work is not current on this gateway.");
        }
      }
      if (protocol === "unavailable") {
        throw new Error("Background work is unavailable on this gateway.");
      }

      let pendingAttempt: PendingBackgroundSubmission | null = null;
      if (protocol === "durable") {
        pendingAttempt = {
          durableAttempted: priorDurableAttempt,
          mutation,
          protocol: "durable",
          status: "submitting",
        };
        pendingBackgroundRef.current = pendingAttempt;
      }
      setBackgroundSubmission({
        error: null,
        jobId: null,
        retryable: false,
        status: "submitting",
      });

      const resultIsCurrent = () => {
        if (connectionIdentityRef.current !== submissionGatewayId) return false;
        if (protocol === "durable") {
          const currentScope = workScopeFor(
            activeSessionRef.current,
            connectionIdentityRef.current,
          );
          return Boolean(
            pendingAttempt &&
            pendingBackgroundRef.current === pendingAttempt &&
            currentScope &&
            mutationMatchesScope(mutation, currentScope),
          );
        }
        return (
          client === clientRef.current &&
          submissionGeneration === generationRef.current &&
          runtimeId === activeRuntimeIdRef.current
        );
      };

      try {
        if (pendingAttempt) {
          pendingAttempt.durableAttempted = true;
        }
        const receipt = await submitBackgroundMutation({
          mutation,
          protocol,
          request: workRequestFor(client),
          sessionId: runtimeId,
        });
        if (!resultIsCurrent()) return;
        const jobId = "job" in receipt ? receipt.job.job_id : null;
        const taskId =
          "job" in receipt ? (receipt.task_id ?? null) : receipt.task_id;
        const currentClient = clientRef.current;
        const currentRuntimeId = activeRuntimeIdRef.current;
        pendingBackgroundRef.current = null;
        setBackgroundSubmission({
          error: null,
          jobId,
          retryable: false,
          status: "started",
        });
        if (currentRuntimeId) {
          updateRuntime(currentRuntimeId, (state) =>
            appendRemoteSystemMessage(
              state,
              `Background task started${jobId ? ` (${jobId})` : taskId ? ` (${taskId})` : ""}.`,
            ),
          );
        }
        if (
          protocol === "durable" &&
          currentClient?.connectionState === "open" &&
          currentRuntimeId
        ) {
          void queueWorkSyncWith(
            currentClient,
            currentRuntimeId,
            activeSessionRef.current,
            generationRef.current,
          ).catch(() => undefined);
        }
      } catch (submissionError) {
        if (!resultIsCurrent()) throw submissionError;
        const message = errorMessage(submissionError);
        const retryable =
          protocol === "durable" &&
          workMutationErrorIsRetryable(submissionError);
        if (pendingAttempt) {
          pendingAttempt.durableAttempted = true;
          pendingAttempt.status = retryable ? "retryable" : "failed";
        } else {
          pendingBackgroundRef.current = null;
        }
        setBackgroundSubmission({
          error: message,
          jobId: null,
          retryable,
          status: retryable ? "retryable" : "failed",
        });
        setError(message);
        throw submissionError;
      }
    },
    [queueWorkSyncWith, updateRuntime],
  );

  const runInBackground = useCallback(
    async (rawText: string) => {
      const text = rawText.trim();
      if (!text) return;
      if (pendingBackgroundRef.current) {
        throw new Error(
          "Retry or dismiss the pending background submission before starting another.",
        );
      }
      let state = activeSessionRef.current;
      if (!state.runtimeSessionId) state = await createSession();
      const currentConnection = connectionRef.current;
      const client = clientRef.current;
      if (!state.runtimeSessionId || !currentConnection || !client) {
        throw new Error("Fabric did not create a live session");
      }
      const protocol = advertisedWorkProtocol(capabilityStateRef.current);
      let scope: WorkSyncScope;
      if (protocol === "durable") {
        try {
          await queueWorkSyncWith(
            client,
            state.runtimeSessionId,
            state,
            generationRef.current,
          );
        } catch (syncError) {
          const message = errorMessage(syncError);
          setBackgroundSubmission({
            error: message,
            jobId: null,
            retryable: false,
            status: "failed",
          });
          throw syncError;
        }
        const durableScope = workScopeFor(state, connectionIdentityRef.current);
        if (
          !durableScope ||
          workStatusRef.current !== "current" ||
          workProjectionRef.current?.gateway_id !== durableScope.gateway_id ||
          workProjectionRef.current?.profile_id !== durableScope.profile_id
        ) {
          const scopeError = !durableScope
            ? missingWorkScopeError()
            : new Error(
                workStatusRef.current === "incompatible"
                  ? "This gateway advertises Durable Work but requires an incompatible fabric.work contract."
                  : "Durable Work is not current on this gateway.",
              );
          setBackgroundSubmission({
            error: scopeError.message,
            jobId: null,
            retryable: false,
            status: "failed",
          });
          throw scopeError;
        }
        scope = durableScope;
      } else if (protocol === "legacy") {
        scope = {
          gateway_id: connectionIdentityRef.current,
          profile_id: "legacy",
        };
      } else {
        const unavailableError = new Error(
          "Background work is unavailable on this gateway.",
        );
        setBackgroundSubmission({
          error: unavailableError.message,
          jobId: null,
          retryable: false,
          status: "failed",
        });
        throw unavailableError;
      }
      const mutation = createBackgroundMutation(scope, text);
      if (protocol === "durable") {
        pendingBackgroundRef.current = {
          durableAttempted: false,
          mutation,
          protocol: "durable",
          status: "submitting",
        };
      }
      try {
        await submitBackgroundWith(mutation);
      } catch (submissionError) {
        const pending = pendingBackgroundRef.current;
        const currentScope = workScopeFor(
          activeSessionRef.current,
          connectionIdentityRef.current,
        );
        if (
          pending?.mutation === mutation &&
          pending.status === "submitting" &&
          currentScope &&
          mutationMatchesScope(mutation, currentScope)
        ) {
          const retryable = workMutationErrorIsRetryable(submissionError);
          // Any failed call on the advertised durable path closes the legacy
          // fallback door. The server may have acted even when the client did
          // not receive a receipt; only the same durable key is safe afterward.
          pending.durableAttempted = true;
          pending.status = retryable ? "retryable" : "failed";
          setBackgroundSubmission({
            error: errorMessage(submissionError),
            jobId: null,
            retryable,
            status: retryable ? "retryable" : "failed",
          });
        }
        throw submissionError;
      }
    },
    [createSession, queueWorkSyncWith, submitBackgroundWith],
  );

  const retryBackground = useCallback(async () => {
    const pending = pendingBackgroundRef.current;
    if (!pending || pending.status !== "retryable") return;
    try {
      await submitBackgroundWith(pending.mutation);
    } catch (retryError) {
      if (
        pendingBackgroundRef.current === pending &&
        !workMutationErrorIsRetryable(retryError)
      ) {
        pending.status = "failed";
        setBackgroundSubmission({
          error: errorMessage(retryError),
          jobId: null,
          retryable: false,
          status: "failed",
        });
      }
      throw retryError;
    }
  }, [submitBackgroundWith]);
  retryBackgroundRef.current = retryBackground;

  const abandonBackgroundRetry = useCallback(() => {
    pendingBackgroundRef.current = null;
    setBackgroundSubmission(initialBackgroundSubmission());
  }, []);

  const respondToWorkAttention = useCallback(
    async (
      attentionId: string,
      action: WorkAttentionAction,
      value?: string,
    ) => {
      const client = clientRef.current;
      const runtimeId = activeRuntimeIdRef.current;
      const attention = workProjectionRef.current?.attention[attentionId];
      if (
        !client ||
        !runtimeId ||
        !attention ||
        workStatusRef.current !== "current"
      ) {
        throw new Error("This durable Attention item is no longer actionable.");
      }
      if (!attention.allowed_actions.includes(action)) {
        throw new Error(
          "This response is not allowed for the current Attention item.",
        );
      }
      const submissionScope = workScopeFor(
        activeSessionRef.current,
        connectionIdentityRef.current,
      );
      if (
        !submissionScope ||
        submissionScope.gateway_id !== workProjectionRef.current?.gateway_id ||
        submissionScope.profile_id !== workProjectionRef.current?.profile_id
      ) {
        throw new Error(
          "This durable Attention item belongs to another scope.",
        );
      }
      const existing = pendingAttentionMutationRef.current.get(attentionId);
      const pendingMutation =
        existing &&
        existing.action === action &&
        existing.kind === attention.kind &&
        existing.value === value &&
        existing.version === attention.version
          ? existing
          : {
              action,
              idempotencyKey: globalThis.crypto.randomUUID(),
              kind: attention.kind,
              value,
              version: attention.version,
            };
      pendingAttentionMutationRef.current.set(attentionId, pendingMutation);
      const mutationIsCurrent = () => {
        const currentScope = workScopeFor(
          activeSessionRef.current,
          connectionIdentityRef.current,
        );
        return Boolean(
          pendingAttentionMutationRef.current.get(attentionId) ===
            pendingMutation &&
          currentScope &&
          currentScope.gateway_id === submissionScope.gateway_id &&
          currentScope.profile_id === submissionScope.profile_id,
        );
      };
      try {
        await new FabricWorkRpc(workRequestFor(client)).respondToAttention(
          runtimeId,
          attention,
          {
            action,
            idempotency_key: pendingMutation.idempotencyKey,
            ...(value === undefined ? {} : { value }),
          },
        );
      } catch (responseError) {
        if (
          mutationIsCurrent() &&
          !workMutationErrorIsRetryable(responseError)
        ) {
          pendingAttentionMutationRef.current.delete(attentionId);
        }
        throw responseError;
      }
      if (!mutationIsCurrent()) return;
      pendingAttentionMutationRef.current.delete(attentionId);

      // Delivery succeeded. Reconciliation is a separate operation: a sync
      // failure may leave the card stale, but must not invite a second mutation.
      const currentClient = clientRef.current;
      const currentRuntimeId = activeRuntimeIdRef.current;
      if (!currentClient || !currentRuntimeId) return;
      await queueWorkSyncWith(
        currentClient,
        currentRuntimeId,
        activeSessionRef.current,
        generationRef.current,
      ).catch(() => undefined);
    },
    [queueWorkSyncWith],
  );

  const interrupt = useCallback(async () => {
    const client = clientRef.current;
    const runtimeId = activeRuntimeIdRef.current;
    if (!client || !runtimeId) {
      return;
    }
    requireMethod("session.interrupt");
    await client.request("session.interrupt", { session_id: runtimeId });
    updateRuntime(runtimeId, (state) => ({
      ...state,
      pendingInteractions: [],
      running: false,
      status: "idle",
    }));
  }, [requireMethod, updateRuntime]);

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
        requireMethod("approval.respond");
        const receipt = await client.request<{
          choice?: string;
          request_id?: string;
          resolved?: number;
        }>("approval.respond", {
          choice: approvalChoice || value || "deny",
          request_id: prompt.requestId,
          session_id: runtimeId,
        });
        assertMatchingInteractionReceipt(receipt, prompt.requestId, {
          approval: true,
        });
      } else if (prompt.type === "clarify") {
        requireMethod("clarify.respond");
        const receipt = await client.request<{ request_id?: string }>(
          "clarify.respond",
          {
            answer: value,
            request_id: prompt.requestId,
            session_id: runtimeId,
          },
        );
        assertMatchingInteractionReceipt(receipt, prompt.requestId);
      } else if (prompt.type === "sudo") {
        requireMethod("sudo.respond");
        const receipt = await client.request<{ request_id?: string }>(
          "sudo.respond",
          {
            password: value,
            request_id: prompt.requestId,
            session_id: runtimeId,
          },
        );
        assertMatchingInteractionReceipt(receipt, prompt.requestId);
      } else {
        requireMethod("secret.respond");
        const receipt = await client.request<{ request_id?: string }>(
          "secret.respond",
          {
            request_id: prompt.requestId,
            session_id: runtimeId,
            value,
          },
        );
        assertMatchingInteractionReceipt(receipt, prompt.requestId);
      }

      updateRuntime(runtimeId, (state) => {
        const pendingInteractions = state.pendingInteractions.filter(
          (candidate) =>
            candidate.type !== prompt.type ||
            candidate.requestId !== prompt.requestId,
        );
        return {
          ...state,
          pendingInteractions,
          status:
            pendingInteractions.length > 0
              ? "waiting"
              : state.running
                ? "working"
                : "idle",
        };
      });
    },
    [requireMethod, updateRuntime],
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
      pendingAttentionMutationRef.current.clear();
      pendingBackgroundRef.current = null;
      disposeClient(true);
    },
    [disposeClient],
  );

  return {
    activeSession,
    abandonBackgroundRetry,
    backgroundSubmission,
    capabilityState,
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
    respondToWorkAttention,
    respondToPrompt,
    retryBackground,
    runInBackground,
    resumeSession,
    send,
    sessions,
    supportsMethod,
    syncWork,
    workProjection,
    workStatus,
  };
}
