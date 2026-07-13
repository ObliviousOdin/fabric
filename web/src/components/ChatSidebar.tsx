/**
 * ChatSidebar — structured-events panel that sits next to the xterm.js
 * terminal in the dashboard Chat tab.
 *
 * Two WebSockets, one per concern:
 *
 *   1. **JSON-RPC sidecar** (`GatewayClient` → /api/ws) — a lightweight
 *      session used only for connection state (the "live" badge) and
 *      credential warnings. Independent of the PTY pane's session by
 *      design. The model badge does NOT come from here: it reads the
 *      effective config model over REST (`/api/model/info`), and the model
 *      picker writes config over REST (`/api/model/set`) then offers a
 *      dashboard reload so the running chat adopts the new model.
 *
 *   2. **Event subscriber** (/api/events?channel=…) — passive, receives
 *      every dispatcher emit from the PTY-side `tui_gateway.entry` that
 *      the dashboard fanned out.  The sidebar uses it for `session.info`
 *      (live chat title + cwd), `dashboard.new_session_requested`, and the
 *      Activity feed (CH3): `tool.start`/`tool.complete` rows,
 *      `message.*`/`reasoning.delta`/`thinking.delta` state lines,
 *      `approval.request` pin, `status.update` lines — all folded through
 *      the pure reducer in `chat/activity-feed.ts` and throttle-flushed so
 *      a delta storm never becomes a render storm. The `channel` id ties
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
import {
  EMPTY_ACTIVITY_FEED,
  reduceActivityEvent,
  type ActivityFeedState,
} from "@/components/chat/activity-feed";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { ModelReloadConfirm } from "@/components/ModelReloadConfirm";
import { ReasoningPicker } from "@/components/ReasoningPicker";
import { GatewayClient, type ConnectionState } from "@/lib/gatewayClient";
import { api, buildWsUrl } from "@/lib/api";
import { titleFromSessionInfoPayload } from "@/lib/chat-title";

import { cn } from "@/lib/utils";
import { AlertCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface SessionInfo {
  cwd?: string;
  model?: string;
  provider?: string;
  credential_warning?: string;
  title?: string;
}

interface RpcEnvelope {
  method?: string;
  params?: { type?: string; payload?: unknown };
}

/** Trailing-throttle window for Activity-feed state flushes (CH3). */
const FEED_FLUSH_MS = 120;

function cwdFromSessionInfoPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const cwd = (payload as { cwd?: unknown }).cwd;
  return typeof cwd === "string" && cwd.trim() ? cwd : null;
}

interface ChatSidebarProps {
  channel: string;
  /** Chat profile from the dashboard switcher / URL scope. */
  profile?: string;
  className?: string;
  onDashboardNewSessionRequest?: () => void;
  onSessionTitleChange?: (title: string | null) => void;
}

export function ChatSidebar({
  channel,
  profile,
  className,
  onDashboardNewSessionRequest,
  onSessionTitleChange,
}: ChatSidebarProps) {
  // `version` bumps on reconnect; gw is derived so we never call setState
  // for it inside an effect (React 19's set-state-in-effect rule). The
  // counter is the dependency on purpose — it's not read in the memo body,
  // it's the signal that says "rebuild the client".
  const [version, setVersion] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const gw = useMemo(() => new GatewayClient(), [version]);

  const [state, setState] = useState<ConnectionState>("idle");
  const [info, setInfo] = useState<SessionInfo>({});
  const [modelOpen, setModelOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The badge shows config.yaml's main model (`model.default`) via
  // `/api/model/info` — the same value the Models page writes and a new chat
  // session boots from. We deliberately don't use the sidecar's `session.info`
  // model: that's a one-time snapshot of the throwaway sidecar agent taken when
  // its session is created, and it never updates when the model is changed
  // elsewhere, so the badge would go stale. Pass the chat profile explicitly so
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
  // CH2: the PTY session cwd from the events channel (preferred over the
  // sidecar's own cwd — the sidecar is a separate throwaway session).
  const [ptyCwd, setPtyCwd] = useState<string | null>(null);

  // ── Activity feed (CH3) ──────────────────────────────────────────────
  // Events fold into a ref via the pure reducer; a trailing 120 ms timer
  // flushes the ref into React state. reasoning.delta / message.delta
  // storms therefore cost ref writes + at most ~8 renders/s — and the
  // reducer returns the same reference for no-op events, so those flushes
  // bail out of rendering entirely (Object.is).
  const feedRef = useRef<ActivityFeedState>(EMPTY_ACTIVITY_FEED);
  const [feed, setFeed] = useState<ActivityFeedState>(EMPTY_ACTIVITY_FEED);
  const feedFlushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleFeedFlush = useCallback(() => {
    if (feedFlushTimer.current !== null) return;
    feedFlushTimer.current = setTimeout(() => {
      feedFlushTimer.current = null;
      setFeed(feedRef.current);
    }, FEED_FLUSH_MS);
  }, []);
  const resetFeed = useCallback(() => {
    if (feedFlushTimer.current !== null) {
      clearTimeout(feedFlushTimer.current);
      feedFlushTimer.current = null;
    }
    feedRef.current = EMPTY_ACTIVITY_FEED;
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

  // Profile or PTY channel change tears down both WebSockets. Bump `version`
  // (same path as the manual Reconnect button) so the gateway client is
  // recreated and the events feed resubscribes — otherwise the old events
  // socket's close handler can leave a stale error banner after a switch.
  const scopeKey = `${channel}\0${profile ?? ""}`;
  const prevScopeKey = useRef<string | null>(null);
  useEffect(() => {
    if (prevScopeKey.current === null) {
      prevScopeKey.current = scopeKey;
      return;
    }
    if (prevScopeKey.current === scopeKey) return;
    prevScopeKey.current = scopeKey;
    setError(null);
    setVersion((v) => v + 1);
  }, [scopeKey]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setInfo({});
      setError(null);
      // Scope switch / reconnect: the rail identifies a new PTY run — drop
      // the previous run's title, cwd, and activity (CH3 reset contract).
      setRailTitle(null);
      setPtyCwd(null);
      resetFeed();
    });
    const offState = gw.onState(setState);

    const offSessionInfo = gw.on<SessionInfo>("session.info", (ev) => {
      if (ev.payload) {
        setInfo((prev) => ({ ...prev, ...ev.payload }));
      }
    });

    const offError = gw.on<{ message?: string }>("error", (ev) => {
      const message = ev.payload?.message;

      if (message) {
        setError(message);
      }
    });

    // Create the sidecar session so the gateway surfaces session-scoped
    // signals (connection state, credential warnings). It's independent of the
    // PTY pane's session by design. The model picker no longer rides this
    // session — it writes config.yaml over REST — so we don't track its id.
    gw.connect()
      .then(() => {
        if (cancelled) {
          return;
        }
        // close_on_disconnect: the gateway reaps this sidecar session (and its
        // slash_worker subprocess) when the WS drops, instead of leaking it.
        return gw.request<{ session_id: string }>("session.create", {
          close_on_disconnect: true,
          source: "tool",
          ...(profile ? { profile } : {}),
        });
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setError(e.message);
        }
      });

    return () => {
      cancelled = true;
      offState();
      offSessionInfo();
      offError();
      gw.close();
    };
    // `profile` is read from render; scope changes bump `version` → new `gw`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw]);

  // Event subscriber WebSocket — receives the rebroadcast of every
  // dispatcher emit from the PTY child's gateway.  See /api/pub +
  // /api/events in fabric_cli/web_server.py for the broadcast hop.
  //
  // Failures (auth/loopback rejection, server too old to expose the
  // endpoint, transient drops) surface in the same banner as the
  // JSON-RPC sidecar so the sidebar matches its documented best-effort
  // UX and the user always has a reconnect affordance.
  useEffect(() => {
    if (!channel) {
      return;
    }
    // In loopback mode the legacy ?token=<session> path is fine; in gated
    // mode we have to mint a single-use ticket from the cookie. The IIFE
    // keeps the outer effect synchronous so its ``return cleanup`` stays
    // at the top level; the local ``ws`` is hoisted to a closed-over
    // binding the cleanup reads via ``wsRef``.
    let unmounting = false;
    let ws: WebSocket | null = null;
    void (async () => {
      const url = await buildWsUrl("/api/events", { channel });
      if (unmounting) {
        return;
      }
      ws = new WebSocket(url);

      // `unmounting` suppresses the banner during cleanup — `ws.close()`
      // from the effect's return fires a close event with code 1005 that
      // would otherwise look like an unexpected drop.
      const DISCONNECTED = "events feed disconnected — tool calls may not appear";
      const surface = (msg: string) => !unmounting && setError(msg);

      ws.addEventListener("error", () => surface(DISCONNECTED));

      ws.addEventListener("close", (ev) => {
        if (ev.code === 4401 || ev.code === 4403) {
          surface(`events feed rejected (${ev.code}) — reload the page`);
        } else if (ev.code !== 1000) {
          surface(DISCONNECTED);
        }
      });

      ws.addEventListener("message", (ev) => {
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

        if (type === "session.info") {
          const title = titleFromSessionInfoPayload(payload);
          if (title !== undefined) {
            onSessionTitleChange?.(title);
            setRailTitle(title);
          }
          const cwd = cwdFromSessionInfoPayload(payload);
          if (cwd) {
            setPtyCwd(cwd);
          }
        } else if (type === "dashboard.new_session_requested") {
          onDashboardNewSessionRequest?.();
        }

        // Activity feed (CH3): fold every event through the pure reducer.
        // Own try/catch (R7) so a malformed frame can never break the
        // title / new-session handlers above.
        try {
          if (type) {
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
    })();

    return () => {
      unmounting = true;
      ws?.close();
    };
  }, [
    channel,
    onDashboardNewSessionRequest,
    onSessionTitleChange,
    scheduleFeedFlush,
    version,
  ]);

  // Seed the badge on mount and re-read it whenever the sockets are rebuilt
  // (a profile/channel switch bumps `version`).
  useEffect(() => {
    refreshEffectiveModel();
  }, [refreshEffectiveModel, version]);

  const reconnect = useCallback(() => {
    setError(null);
    setModelNotice(null);
    setPendingReloadModel(null);
    setVersion((v) => v + 1);
  }, []);

  // The picker writes config.yaml over REST and reloads — it doesn't ride the
  // sidecar gateway session, so it's available whenever the sidebar is mounted.
  const modelName = effectiveModel || info.model || "—";
  const modelLabel = modelName.split("/").slice(-1)[0] ?? "—";
  const banner = error ?? info.credential_warning ?? null;

  return (
    <aside
      className={cn(
        "flex h-full w-full min-w-0 shrink-0 flex-col gap-3 overflow-y-auto overflow-x-hidden pr-1",
        className,
      )}
    >
      {/* CH1 rail order: Agent card → Reasoning → Activity → notices. */}
      <AgentCard
        title={railTitle}
        modelName={modelName}
        modelLabel={modelLabel}
        onOpenModelPicker={() => setModelOpen(true)}
        contextLength={contextLength}
        connection={state}
        cwd={ptyCwd ?? info.cwd ?? null}
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
    </aside>
  );
}
