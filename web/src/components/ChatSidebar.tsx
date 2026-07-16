/**
 * ChatSidebar — structured-events panel that sits next to the xterm.js
 * terminal in the dashboard Chat tab.
 *
 * One passive **event subscriber** (`/api/events?channel=…`) receives
 *      every dispatcher emit from the PTY-side `tui_gateway.entry` that
 *      the dashboard fanned out. The sidebar uses it for `session.info`
 *      and `session.title`
 *      (live chat title + cwd), `dashboard.new_session_requested`, and the
 *      Activity feed (CH3): `tool.start`/`tool.complete` rows,
 *      `approval.request` pin, `status.update` lines — all folded through
 *      the pure reducer in `chat/activity-feed.ts` and throttle-flushed so
 *      a burst never becomes a render storm. Token/reasoning deltas are
 *      deliberately ignored because xterm already renders them. The `channel` id ties
 *      this listener to the same chat tab's PTY child — see `ChatPage.tsx`
 *      for where the id is generated.
 *
 * Best-effort throughout: WS failures show in the badge / banner, the
 * terminal pane keeps working unimpaired.
 */

import { Button } from "@nous-research/ui/ui/components/button";
import { Card } from "@nous-research/ui/ui/components/card";

import { ActivityFeed } from "@/components/chat/ActivityFeed";
import { AgentCard } from "@/components/chat/AgentCard";
import type {
  ChatContextEvent,
  ChatContextState,
} from "@/components/chat/chat-context-state";
import {
  EMPTY_ACTIVITY_FEED,
  reduceActivityEvent,
  type ActivityFeedState,
} from "@/components/chat/activity-feed";
import {
  eventStreamReconnectDelay,
  isSemanticPtyEvent,
  ptySessionMetadata,
} from "@/components/chat/pty-event-stream";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { ModelReloadConfirm } from "@/components/ModelReloadConfirm";
import { ReasoningPicker } from "@/components/ReasoningPicker";
import type { ConnectionState } from "@/lib/gatewayClient";
import { api, buildWsUrl } from "@/lib/api";
import { PluginSlot } from "@/plugins";

import { cn } from "@/lib/utils";
import { AlertCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

interface SessionInfo {
  cwd?: string;
  model?: string;
  provider?: string;
  credential_warning?: string;
  title?: string;
}

interface RpcEnvelope {
  method?: string;
  params?: { type?: string; payload?: unknown; session_id?: string };
}

/** Trailing-throttle window for Activity-feed state flushes (CH3). */
const FEED_FLUSH_MS = 120;

interface ChatSidebarProps {
  channel: string;
  /** Live PTY read model projected by the parent context rail. */
  contextSnapshot?: ChatContextState;
  /** Chat profile from the dashboard switcher / URL scope. */
  profile?: string;
  /** Whether the persistently-mounted Chat route is currently visible. */
  isActive?: boolean;
  className?: string;
  onDashboardNewSessionRequest?: () => void;
  onSessionTitleChange?: (title: string | null) => void;
  onContextEvent?: (event: ChatContextEvent) => void;
  /** Navigate from a supporting Chat-rail card without replacing Chat itself. */
  onNavigate?: (path: string) => void;
}

export function ChatSidebar({
  channel,
  contextSnapshot,
  profile,
  isActive = true,
  className,
  onDashboardNewSessionRequest,
  onSessionTitleChange,
  onContextEvent,
  onNavigate,
}: ChatSidebarProps) {
  // `version` tears down/rebuilds the passive PTY event subscriber.
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<ConnectionState>("idle");
  const [info, setInfo] = useState<SessionInfo>({});
  const [modelOpen, setModelOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The badge shows config.yaml's main model (`model.default`) via
  // `/api/model/info` — the same value the Models page writes and a new chat
  // session boots from. We deliberately don't use the event stream's
  // `session.info` model as the authority: it is a running-session snapshot and
  // does not update when config changes elsewhere. Pass the chat profile so
  // this card stays scoped to the PTY even if the global dashboard switcher
  // changes while the chat is open.
  const [effectiveModel, setEffectiveModel] = useState("");
  // CH2: read-only `ctx` line from the same /api/model/info fetch.
  const [contextLength, setContextLength] = useState(0);
  // Whether the effective model supports reasoning effort — gates the
  // ReasoningPicker. Read from the same `/api/model/info` capabilities the
  // (currently unused) ModelInfoCard surfaces, so the dashboard exposes a
  // control to *set* the level, not just a read-only "Reasoning" badge.
  const [supportsReasoning, setSupportsReasoning] = useState(false);
  // Bumped on model change/save so ReasoningPicker re-reads the saved effort
  // (config is profile-scoped the same way the model badge is).
  const [modelRefreshKey, setModelRefreshKey] = useState(0);
  // Set after the picker saves a model and the user declines the reload: config
  // is updated but the running session keeps its model until rebuilt.
  const [modelNotice, setModelNotice] = useState<string | null>(null);
  // Short name of a just-saved model awaiting confirm to reload (a fresh chat
  // session is how the running chat adopts it; we confirm before discarding it).
  const [pendingReloadModel, setPendingReloadModel] = useState<string | null>(
    null,
  );
  // CH4: the PTY session title mirrored into the Agent card (same
  // `session.info` payload that feeds `onSessionTitleChange`).
  const [railTitle, setRailTitle] = useState<string | null>(null);
  // CH2: the real PTY session cwd from the events channel.
  const [ptyCwd, setPtyCwd] = useState<string | null>(null);

  // ── Activity feed (CH3) ──────────────────────────────────────────────
  // Semantic events fold into a ref via the pure reducer; a trailing 120 ms
  // timer flushes the ref into React state. Token/reasoning deltas are filtered
  // before this point, and reducer no-ops bail out via Object.is.
  const feedRef = useRef<ActivityFeedState>(EMPTY_ACTIVITY_FEED);
  const feedSessionIdRef = useRef<string | null>(null);
  const [feed, setFeed] = useState<ActivityFeedState>(EMPTY_ACTIVITY_FEED);
  const feedFlushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleFeedFlush = useCallback(() => {
    if (feedFlushTimer.current !== null) return;
    feedFlushTimer.current = setTimeout(() => {
      feedFlushTimer.current = null;
      setFeed(feedRef.current);
    }, FEED_FLUSH_MS);
  }, []);
  const resetFeed = useCallback((sessionId: string | null = null) => {
    if (feedFlushTimer.current !== null) {
      clearTimeout(feedFlushTimer.current);
      feedFlushTimer.current = null;
    }
    feedRef.current = EMPTY_ACTIVITY_FEED;
    feedSessionIdRef.current = sessionId;
    setFeed(EMPTY_ACTIVITY_FEED);
  }, []);
  useEffect(
    () => () => {
      if (feedFlushTimer.current !== null) clearTimeout(feedFlushTimer.current);
    },
    [],
  );

  const refreshEffectiveModel = useCallback(() => {
    void api
      .getModelInfo(profile)
      .then((r) => {
        if (r?.model) setEffectiveModel(String(r.model));
        setSupportsReasoning(!!r?.capabilities?.supports_reasoning);
        const ctx = Number(r?.effective_context_length);
        setContextLength(Number.isFinite(ctx) && ctx > 0 ? ctx : 0);
        // Bump so ReasoningPicker re-reads the saved effort for the new model.
        setModelRefreshKey((k) => k + 1);
      })
      .catch(() => {
        // Best-effort: keep the last known label rather than blanking it.
      });
  }, [profile]);

  // Event subscriber WebSocket — receives the rebroadcast of every
  // dispatcher emit from the PTY child's gateway.  See /api/pub +
  // /api/events in fabric_cli/web_server.py for the broadcast hop.
  //
  // This is the only chat-observation socket. Connection state, warnings,
  // title, and cwd all come from the real PTY session rather than a throwaway
  // `session.create`. Transient drops retry with bounded exponential backoff.
  useEffect(() => {
    if (!channel) {
      return;
    }
    let unmounting = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempt = 0;
    const DISCONNECTED = "events feed disconnected — reconnecting";

    queueMicrotask(() => {
      if (unmounting) return;
      setInfo({});
      setError(null);
      setRailTitle(null);
      setPtyCwd(null);
      resetFeed();
    });

    const connect = async (): Promise<void> => {
      if (unmounting) return;
      setState("connecting");
      let url: string;
      try {
        url = await buildWsUrl("/api/events", { channel });
      } catch {
        scheduleReconnect();
        return;
      }
      if (unmounting) return;
      let ownedWs: WebSocket;
      try {
        ownedWs = new WebSocket(url);
      } catch {
        scheduleReconnect();
        return;
      }
      ws = ownedWs;

      ownedWs.addEventListener("open", () => {
        if (unmounting || ws !== ownedWs) return;
        reconnectAttempt = 0;
        // The browser reaching /api/events only proves the passive subscriber
        // is attached. Stay in Connecting until the PTY publisher identifies
        // a real session; otherwise a dead/missing TUI would look falsely live.
        setState("connecting");
        setError(null);
      });

      ownedWs.addEventListener("error", () => {
        if (unmounting || ws !== ownedWs) return;
        ws = null;
        try {
          ownedWs.close();
        } catch {
          // Best-effort; the retry does not depend on close succeeding.
        }
        scheduleReconnect();
      });

      ownedWs.addEventListener("close", (ev) => {
        if (unmounting || ws !== ownedWs) return;
        ws = null;
        if (ev.code === 4401 || ev.code === 4403) {
          setState("error");
          setError(`events feed rejected (${ev.code}) — reload the page`);
          return;
        }
        scheduleReconnect();
      });

      ownedWs.addEventListener("message", (ev) => {
        let frame: RpcEnvelope;

        try {
          frame = JSON.parse(ev.data);
        } catch {
          return;
        }

        if (frame.method !== "event" || !frame.params) {
          return;
        }

        const { type, payload } = frame.params;
        const incomingSessionId =
          typeof frame.params.session_id === "string"
            ? frame.params.session_id.trim()
            : "";

        if (incomingSessionId) {
          if (
            feedSessionIdRef.current &&
            feedSessionIdRef.current !== incomingSessionId
          ) {
            resetFeed(incomingSessionId);
            setInfo({});
            setRailTitle(null);
            setPtyCwd(null);
            onSessionTitleChange?.(null);
          } else {
            feedSessionIdRef.current = incomingSessionId;
          }
        }

        if (type === "session.info") setState("open");

        if (type && isSemanticPtyEvent(type)) {
          onContextEvent?.({
            payload,
            sessionId: frame.params.session_id,
            type,
          });
        }

        const metadata = type ? ptySessionMetadata(type, payload) : null;
        if (metadata) {
          setInfo((prev) => ({
            ...prev,
            ...(metadata.credentialWarning !== undefined
              ? { credential_warning: metadata.credentialWarning ?? undefined }
              : {}),
            ...(metadata.cwd !== undefined
              ? { cwd: metadata.cwd ?? undefined }
              : {}),
            ...(metadata.model !== undefined ? { model: metadata.model } : {}),
            ...(metadata.provider !== undefined
              ? { provider: metadata.provider }
              : {}),
            ...(metadata.title !== undefined
              ? { title: metadata.title ?? undefined }
              : {}),
          }));
          if (metadata.title !== undefined) {
            onSessionTitleChange?.(metadata.title);
            setRailTitle(metadata.title);
          }
          if (metadata.cwd !== undefined) setPtyCwd(metadata.cwd);
        } else if (type === "dashboard.new_session_requested") {
          onDashboardNewSessionRequest?.();
        }

        // Activity feed (CH3): fold every event through the pure reducer.
        // Own try/catch (R7) so a malformed frame can never break the
        // title / new-session handlers above.
        try {
          if (type && isSemanticPtyEvent(type)) {
            const next = reduceActivityEvent(feedRef.current, type, payload);
            if (next !== feedRef.current) {
              feedRef.current = next;
              scheduleFeedFlush();
            }
          }
        } catch {
          // Best-effort ticker — drop the frame, keep the feed alive.
        }
      });
    };

    function scheduleReconnect(): void {
      if (unmounting || reconnectTimer !== null) return;
      reconnectAttempt += 1;
      const delay = eventStreamReconnectDelay(reconnectAttempt);
      if (delay === null) {
        setState("error");
        setError("events feed disconnected — automatic retries exhausted");
        return;
      }
      setState("connecting");
      setError(DISCONNECTED);
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    }

    void connect();

    return () => {
      unmounting = true;
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [
    channel,
    onDashboardNewSessionRequest,
    onContextEvent,
    onSessionTitleChange,
    scheduleFeedFlush,
    profile,
    resetFeed,
    version,
  ]);

  // Seed the badge on mount and re-read it after a manual event reconnect.
  useEffect(() => {
    refreshEffectiveModel();
  }, [refreshEffectiveModel, version]);

  const reconnect = useCallback(() => {
    setError(null);
    setModelNotice(null);
    setPendingReloadModel(null);
    setVersion((v) => v + 1);
  }, []);

  // The picker writes config.yaml over REST and does not need an agent session.
  const modelName = effectiveModel || info.model || "—";
  const modelLabel = modelName.split("/").slice(-1)[0] ?? "—";
  const banner = error ?? info.credential_warning ?? null;

  return (
    <div
      className={cn(
        "flex h-full w-full min-w-0 shrink-0 flex-col gap-3 overflow-y-auto overflow-x-hidden pr-1",
        className,
      )}
    >
      {/* CH1 rail order: Agent → Work actions → Reasoning → Activity → notices. */}
      <AgentCard
        title={railTitle}
        modelName={modelName}
        modelLabel={modelLabel}
        onOpenModelPicker={() => setModelOpen(true)}
        contextLength={contextLength}
        connection={state}
        cwd={ptyCwd ?? info.cwd ?? null}
      />

      <PluginSlot
        name="chat:rail"
        slotProps={{
          active: isActive,
          currentChat: contextSnapshot
            ? {
                id: contextSnapshot.sessionId,
                status: contextSnapshot.connected
                  ? contextSnapshot.running
                    ? "working"
                    : "ready"
                  : "connecting",
                title: contextSnapshot.title,
              }
            : undefined,
          ...(onNavigate ? { navigate: onNavigate } : {}),
        }}
      />

      {supportsReasoning && (
        <Card className="py-0">
          <ReasoningPicker
            currentModel={modelName}
            profile={profile}
            refreshKey={modelRefreshKey}
            onChanged={(effort) =>
              setModelNotice(
                `Reasoning effort set to ${effort}. Run /new or refresh the page to apply it to this chat.`,
              )
            }
          />
        </Card>
      )}

      <ActivityFeed feed={feed} />

      {modelNotice && (
        <Card className="flex items-start gap-2 border-warning/40 bg-warning/5 px-3 py-2 text-xs">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />

          <div className="wrap-break-word min-w-0 flex-1 text-text-secondary">
            {modelNotice}
          </div>
        </Card>
      )}

      {banner && (
        <Card className="flex items-start gap-2 border-destructive/40 bg-destructive/5 px-3 py-2 text-xs">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />

          <div className="min-w-0 flex-1">
            <div className="wrap-break-word text-destructive">{banner}</div>

            {error && (
              <Button
                size="sm"
                outlined
                className="mt-1"
                onClick={reconnect}
                prefix={<RefreshCw />}
              >
                reconnect
              </Button>
            )}
          </div>
        </Card>
      )}

      {modelOpen && (
        <ModelPickerDialog
          // Same path the Models page uses (REST /api/model/set), not the
          // sidecar config.set RPC, which didn't reliably land in the
          // config.yaml the agent boots from. Always persisted (alwaysGlobal).
          loader={() => api.getModelOptions(profile)}
          alwaysGlobal
          onApply={async ({ provider, model, confirmExpensiveModel }) => {
            setModelNotice(null);
            setPendingReloadModel(null);
            const result = await api.setModelAssignment(
              {
                confirm_expensive_model: confirmExpensiveModel,
                scope: "main",
                provider,
                model,
              },
              profile,
            );
            // confirm_required => the dialog shows the expensive-model prompt
            // and calls back; don't announce until the user confirms.
            if (!result.confirm_required) {
              refreshEffectiveModel();
              // Ask before reloading: applying the model starts a fresh chat.
              setPendingReloadModel(model.split("/").slice(-1)[0]);
            }
            return result;
          }}
          onClose={() => {
            setModelOpen(false);
            refreshEffectiveModel();
          }}
        />
      )}

      <ModelReloadConfirm
        model={pendingReloadModel}
        onCancel={() => {
          const m = pendingReloadModel;
          setPendingReloadModel(null);
          setModelNotice(
            `Model set to ${m}. Run /new or refresh the page to apply it to this chat.`,
          );
        }}
      />
    </div>
  );
}
