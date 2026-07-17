/**
 * ChatPage — embeds `fabric --tui` inside the dashboard.
 *
 *   <div host> (dashboard chrome)                                         .
 *     └─ <div wrapper> (rounded, dark bg, padded — the "terminal window"  .
 *         look that gives the page a distinct visual identity)            .
 *         └─ @xterm/xterm Terminal (WebGL renderer, Unicode 11 widths)    .
 *              │ onData      keystrokes → WebSocket → PTY master          .
 *              │ onResize    terminal resize → `\x1b[RESIZE:cols;rows]`   .
 *              │ write(data) PTY output bytes → VT100 parser              .
 *              ▼                                                          .
 *     WebSocket /api/pty?token=<session>                                  .
 *          ▼                                                              .
 *     FastAPI pty_ws  (fabric_cli/web_server.py)                          .
 *          ▼                                                              .
 *     POSIX PTY → `node ui-tui/dist/entry.js` → tui_gateway + AIAgent     .
 */

import { FitAddon } from "@xterm/addon-fit";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { WebglAddon } from "@xterm/addon-webgl";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { Button } from "@nous-research/ui/ui/components/button";
import { cn } from "@/lib/utils";
import { Copy, MessagesSquare, PanelRight, RotateCcw } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { ChatSessionList } from "@/components/ChatSessionList";
import { ChatContextPanel } from "@/components/chat/ChatContextPanel";
import { ChatSideSheet } from "@/components/chat/ChatSideSheet";
import { ChatWorkspaceLayout } from "@/components/chat/ChatWorkspaceLayout";
import { useChatViewportMode } from "@/components/chat/useChatViewportMode";
import {
  chatLocationWithSearch,
  createFreshChatRequestId,
  FRESH_CHAT_QUERY_PARAM,
  reconcilePersistentChatLocation,
  usePersistentChatIdentity,
  useValueForChatIdentity,
} from "@/components/chat/usePersistentChatIdentity";
import { usePageHeader } from "@/contexts/usePageHeader";
import { api } from "@/lib/api";
import { composerDraftPayload, sanitizeComposerDraft } from "@/lib/chat-draft";
import { normalizeSessionTitle } from "@/lib/chat-title";
import {
  DEFAULT_TERMINAL_BACKGROUND,
  DEFAULT_TERMINAL_FOREGROUND,
} from "@/lib/terminal-theme";
import {
  getTerminalFontChoice,
  resolveTerminalTheme,
  terminalFontFamily,
} from "@/lib/terminal-schemes";
import { PluginSlot } from "@/plugins";
import { useTheme } from "@/themes";
import { useProfileScope } from "@/contexts/useProfileScope";
import { useI18n } from "@/i18n";

// Stable per-browser token identifying THIS chat tab's keep-alive PTY session.
// Sent as ?attach=; lets a refresh/disconnect reattach to the same live process
// instead of spawning a fresh one. Per-localStorage, so other devices can't grab it.
// ``rotate`` mints a new token — used when the user explicitly starts a fresh
// session so the old keep-alive PTY is NOT reattached (the registry reaps it).
const PTY_ATTACH_TOKEN_KEY = "fabric.pty.token.chat";
const LEGACY_PTY_ATTACH_TOKEN_KEY = "hermes.pty.token.chat";
function ptyAttachToken(rotate = false): string {
  let t = "";
  if (!rotate) {
    try {
      t =
        window.localStorage.getItem(PTY_ATTACH_TOKEN_KEY) ??
        window.localStorage.getItem(LEGACY_PTY_ATTACH_TOKEN_KEY) ??
        "";
      if (t) {
        window.localStorage.setItem(PTY_ATTACH_TOKEN_KEY, t);
        window.localStorage.removeItem(LEGACY_PTY_ATTACH_TOKEN_KEY);
      }
    } catch {
      /* private mode / storage blocked */
    }
  }
  if (!t) {
    const a = new Uint8Array(16);
    crypto.getRandomValues(a);
    t = Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
    try {
      window.localStorage.setItem(PTY_ATTACH_TOKEN_KEY, t);
      window.localStorage.removeItem(LEGACY_PTY_ATTACH_TOKEN_KEY);
    } catch {
      /* ignore */
    }
  }
  return t;
}

// Terminal body colors come from the active theme via the shared
// theme-aware builder — it derives the full 16-color ANSI ramp (AA-legible
// on light and dark canvases) rather than leaving xterm's dark-tuned
// defaults to wash out on light themes. The TUI's skin engine paints the
// content; the ramp is what SGR-colored output resolves against. A user
// terminal pref (ThemeSwitcher → Terminal) can pin a catalog scheme
// instead, and override the terminal font family / size.

/**
 * CSS width for xterm font tiers.
 *
 * Prefer the terminal host's `clientWidth` — Chrome DevTools device mode often
 * keeps `window.innerWidth` at the full desktop value while the *drawn* layout
 * is phone-sized, which made us pick desktop font sizes (~14px) and look huge.
 */
function terminalTierWidthPx(host: HTMLElement | null): number {
  if (typeof window === "undefined") return 1280;
  const fromHost = host?.clientWidth ?? 0;
  if (fromHost > 2) return Math.round(fromHost);
  const doc = document.documentElement?.clientWidth ?? 0;
  const vv = window.visualViewport;
  const inner = window.innerWidth;
  const vvw = vv?.width ?? inner;
  const layout = Math.min(inner, vvw, doc > 0 ? doc : inner);
  return Math.max(1, Math.round(layout));
}

function terminalFontSizeForWidth(layoutWidthPx: number): number {
  if (layoutWidthPx < 300) return 7;
  if (layoutWidthPx < 360) return 8;
  if (layoutWidthPx < 420) return 9;
  if (layoutWidthPx < 520) return 10;
  if (layoutWidthPx < 720) return 11;
  if (layoutWidthPx < 1024) return 12;
  return 14;
}

function terminalLineHeightForWidth(layoutWidthPx: number): number {
  return layoutWidthPx < 1024 ? 1.02 : 1.15;
}

export default function ChatPage({
  isActive = true,
  onActiveMount,
}: {
  isActive?: boolean;
  onActiveMount?: () => void;
}) {
  const { t } = useI18n();
  const chatLabels = t.chatWorkspace;
  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pendingComposerDraftRef = useRef<string | null>(null);
  // Exposed to the main metrics-sync effect so it can refit the terminal
  // the moment `isActive` flips back to true (display:none → display:flex
  // collapses the host's box, so ResizeObserver never fires on return).
  const syncMetricsRef = useRef<(() => void) | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const isActiveRef = useRef(isActive);
  useLayoutEffect(() => {
    isActiveRef.current = isActive;
  }, [isActive]);
  useEffect(() => {
    if (isActive) onActiveMount?.();
  }, [isActive, onActiveMount]);
  // Lazy-init: the missing-token check happens at construction so the effect
  // body doesn't have to setState (React 19's set-state-in-effect rule).
  // In gated (OAuth) mode the server intentionally omits the session token —
  // the dashboard API layer authenticates the WS via a single-use ticket,
  // so a missing token there is expected, not an error.
  const [banner, setBanner] = useState<string | null>(() =>
    typeof window !== "undefined" &&
    !window.__FABRIC_SESSION_TOKEN__ &&
    !window.__FABRIC_AUTH_REQUIRED__
      ? "Session token unavailable. Open this page through `Fabric dashboard`, not directly."
      : null,
  );
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");
  const copyResetRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const forceFreshPtyRef = useRef(false);
  const handledFreshRequestRef = useRef<string | null>(null);
  // NS-504: when the agent process exits cleanly (the user typed `/exit`, or
  // started a new session that ended the current PTY child), the PTY socket
  // closes with a normal code. Before this fix the terminal just printed
  // "[session ended]" and went dead — the only recovery was a full page
  // refresh. `sessionEnded` flips on that clean close and renders an explicit
  // "Start new session" affordance; clicking it bumps `reconnectNonce`, which
  // is a dependency of the connect effect, so a fresh PTY spawns in place.
  const [sessionEnded, setSessionEnded] = useState(false);
  const [reconnectNonce, setReconnectNonce] = useState(0);
  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);
  const reconnect = useCallback(() => {
    forceFreshPtyRef.current = true;
    reconnectAttemptRef.current = 0;
    clearReconnectTimer();
    setSessionEnded(false);
    setBanner(null);
    setReconnectNonce((n) => n + 1);
  }, [clearReconnectTimer]);
  const startFreshDashboardChat = useCallback(() => {
    const next = new URLSearchParams(searchParams);

    next.delete("resume");
    next.set(FRESH_CHAT_QUERY_PARAM, createFreshChatRequestId());
    reconnectAttemptRef.current = 0;
    clearReconnectTimer();
    navigate(chatLocationWithSearch(location, next), { replace: true });
    setSessionEnded(false);
    setBanner(null);
  }, [clearReconnectTimer, location, navigate, searchParams]);
  const viewportMode = useChatViewportMode();
  const [compactPanelRaw, setCompactPanelRaw] = useState<
    "conversations" | "context" | null
  >(null);
  // ChatPage stays mounted while another dashboard route is active. Derive
  // compact-panel visibility from `isActive` so a sheet can never retain the
  // body scroll lock or keep a data rail connected behind another page.
  const compactPanel =
    isActive && viewportMode === "compact" ? compactPanelRaw : null;

  const draftSeed = searchParams.get("draft");
  useEffect(() => {
    if (!isActive || !draftSeed) return;

    const next = new URLSearchParams(searchParams);
    next.delete("draft");
    setSearchParams(next, { replace: true });

    const draft = sanitizeComposerDraft(draftSeed);
    if (!draft) return;

    pendingComposerDraftRef.current = draft;
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      try {
        ws.send(composerDraftPayload(draft));
        pendingComposerDraftRef.current = null;
      } catch {
        /* keep the draft pending so the next successful reconnect can place it */
      }
    }
  }, [draftSeed, isActive, searchParams, setSearchParams]);
  const { setEnd, setTitle } = usePageHeader();
  const [sessionTitleState, setSessionTitleState] = useState<{
    scope: string;
    title: string | null;
  }>({ scope: "", title: null });
  const closeCompactPanel = useCallback(() => setCompactPanelRaw(null), []);
  const navigateFromChatRail = useCallback(
    (path: string) => {
      closeCompactPanel();
      navigate(path);
    },
    [closeCompactPanel, navigate],
  );

  // CH8: refresh nonce for ChatSessionList, derived from `sessionEnded` so
  // the connect effect stays untouched (N1). Each end→restart cycle changes
  // the value twice (1 → 0), which just means one extra cheap list refetch
  // when a fresh PTY spawns — and the freshly finalized conversation shows
  // up in the switcher the moment the session ends.
  const sessionListRefreshSignal = sessionEnded ? 1 : 0;

  const { theme, terminalPrefs } = useTheme();
  const terminalBg = theme.terminalBackground ?? DEFAULT_TERMINAL_BACKGROUND;
  const terminalFg = theme.terminalForeground ?? DEFAULT_TERMINAL_FOREGROUND;
  const terminalTheme = useMemo(
    () => resolveTerminalTheme(terminalPrefs.scheme, terminalBg, terminalFg),
    [terminalPrefs.scheme, terminalBg, terminalFg],
  );
  // Font prefs apply live (no PTY palette involved, unlike colors). The ref
  // lets the terminal-creation effect and syncTerminalMetrics — created once
  // per PTY session — read the current prefs without re-running on change;
  // the live-update effect below pushes changes into the running terminal.
  const terminalPrefsRef = useRef(terminalPrefs);
  useEffect(() => {
    terminalPrefsRef.current = terminalPrefs;
  }, [terminalPrefs]);

  // The dashboard keeps ChatPage mounted persistently so the PTY survives tab
  // switches. That is great for ordinary /chat navigation, but it means query
  // param changes do NOT remount the component. Resume-in-chat from the
  // Sessions page relies on `/chat?resume=<id>` changing at runtime, so we must
  // treat the current resume target as part of the PTY identity and rebuild the
  // terminal session when it changes.
  const routeResumeParam = searchParams.get("resume");
  const routeFreshRequest = searchParams.get(FRESH_CHAT_QUERY_PARAM);
  // Profile-scoped chat: spawn the PTY under the globally selected
  // management profile. Changing it remounts the terminal (key below /
  // effect dep) so the user explicitly starts a fresh scoped session.
  const { profile: scopedProfile } = useProfileScope();
  const chatIdentity = usePersistentChatIdentity(
    isActive,
    routeResumeParam,
    scopedProfile,
    routeFreshRequest,
  );
  const {
    channel,
    profile: chatProfile,
    resumeParam,
  } = chatIdentity;
  // The TUI chooses its light/dark true-color palette at process spawn. Keep
  // xterm on that same canvas/palette for the life of the PTY; recoloring only
  // the browser mid-session makes dark muted text disappear on a light canvas.
  // A fresh/resumed/profile-switched Chat rotates `channel` and captures the
  // then-current dashboard theme without discarding a running conversation.
  const terminalSessionTheme = useValueForChatIdentity(channel, terminalTheme);
  useLayoutEffect(() => {
    if (
      !isActive ||
      !routeFreshRequest ||
      handledFreshRequestRef.current === routeFreshRequest
    ) {
      return;
    }

    // Mark the one-shot intent before the passive PTY connection effect runs,
    // so this channel rotates its attach token and cannot reattach the prior
    // process. Reconciliation below then removes the directive from the URL.
    handledFreshRequestRef.current = routeFreshRequest;
    forceFreshPtyRef.current = true;
  }, [isActive, routeFreshRequest]);
  const titleScope = `${channel}\0${reconnectNonce}`;
  const sessionTitle =
    sessionTitleState.scope === titleScope ? sessionTitleState.title : null;
  const handleSessionTitleChange = useCallback(
    (title: string | null) => setSessionTitleState({ scope: titleScope, title }),
    [titleScope],
  );

  useEffect(() => {
    if (!isActive) return;

    const replacement = reconcilePersistentChatLocation(location, resumeParam);
    if (replacement) navigate(replacement, { replace: true });
  }, [isActive, location, navigate, resumeParam]);

  useEffect(() => {
    if (!isActive) return;

    setTitle(sessionTitle);
    return () => {
      if (isActiveRef.current) setTitle(null);
    };
  }, [isActive, sessionTitle, setTitle]);

  useEffect(() => {
    if (!resumeParam) return;

    let cancelled = false;

    api
      .getSessionDetail(resumeParam, chatProfile)
      .then((session) => {
        if (cancelled) return;
        handleSessionTitleChange(normalizeSessionTitle(session.title));
      })
      .catch(() => {
        // Best-effort: the PTY-side session.info stream can still supply it.
      });

    return () => {
      cancelled = true;
    };
  }, [resumeParam, chatProfile, handleSessionTitleChange]);

  useEffect(() => {
    if (!isActive || !resumeParam) return;

    let cancelled = false;

    api
      .getSessionLatestDescendant(resumeParam, chatProfile)
      .then((res) => {
        if (cancelled || !res.session_id || res.session_id === resumeParam) {
          return;
        }

        const next = new URLSearchParams(searchParams);
        next.set("resume", res.session_id);
        setSearchParams(next, { replace: true });
      })
      .catch(() => {
        // Best-effort: old servers or missing sessions should not block chat.
      });

    return () => {
      cancelled = true;
    };
  }, [isActive, resumeParam, chatProfile, searchParams, setSearchParams]);

  useEffect(() => {
    // Compact chat keeps the terminal first and opens its two independent
    // data rails on demand. Hidden routes and wider layouts own no header end
    // controls, so they cannot leave a stale sheet trigger behind.
    if (!isActive) return;
    if (viewportMode !== "compact") {
      setEnd(null);
      return;
    }
    setEnd(
      <div
        aria-label={chatLabels?.panels ?? "Chat panels"}
        className="flex shrink-0 items-center gap-1"
        role="group"
      >
        <Button
          ghost
          aria-controls="chat-conversations-sheet"
          aria-expanded={compactPanel === "conversations"}
          aria-label={chatLabels?.openConversations ?? "Open conversations"}
          className="min-h-11 min-w-11 px-2 text-text-secondary hover:text-foreground"
          onClick={() => setCompactPanelRaw("conversations")}
          title={chatLabels?.conversations ?? "Conversations"}
        >
          <span className="inline-flex items-center gap-1.5">
            <MessagesSquare aria-hidden="true" className="h-4 w-4 shrink-0" />
            <span className="hidden min-[720px]:inline">
              {chatLabels?.conversations ?? "Conversations"}
            </span>
          </span>
        </Button>
        <Button
          ghost
          aria-controls="chat-context-sheet"
          aria-expanded={compactPanel === "context"}
          aria-label={chatLabels?.openContext ?? "Open context"}
          className="min-h-11 min-w-11 px-2 text-text-secondary hover:text-foreground"
          onClick={() => setCompactPanelRaw("context")}
          title={chatLabels?.context ?? "Context"}
        >
          <span className="inline-flex items-center gap-1.5">
            <PanelRight aria-hidden="true" className="h-4 w-4 shrink-0" />
            <span className="hidden min-[720px]:inline">
              {chatLabels?.context ?? "Context"}
            </span>
          </span>
        </Button>
      </div>,
    );
    return () => {
      if (isActiveRef.current) setEnd(null);
    };
  }, [chatLabels, compactPanel, isActive, setEnd, viewportMode]);

  const handleCopyLast = () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    // Send the slash as a burst, wait long enough for Ink's tokenizer to
    // emit a keypress event for each character (not coalesce them into a
    // paste), then send Return as its own event.  The timing here is
    // empirical — 100ms is safely past Node's default stdin coalescing
    // window and well inside UI responsiveness.
    ws.send("/copy");
    setTimeout(() => {
      const s = wsRef.current;
      if (s && s.readyState === WebSocket.OPEN) s.send("\r");
    }, 100);
    setCopyState("copied");
    if (copyResetRef.current) clearTimeout(copyResetRef.current);
    copyResetRef.current = setTimeout(() => setCopyState("idle"), 1500);
    termRef.current?.focus();
  };

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const token = window.__FABRIC_SESSION_TOKEN__;
    const gated = !!window.__FABRIC_AUTH_REQUIRED__;
    // Banner already initialised above; just bail before wiring xterm/WS.
    // In gated mode the token is absent by design — api.buildWsUrl() mints
    // a WS ticket instead, so don't bail; let the effect reach that path.
    if (!token && !gated) {
      return;
    }

    const tierW0 = terminalTierWidthPx(host);
    const prefs0 = terminalPrefsRef.current;
    const term = new Terminal({
      allowProposedApi: true,
      cursorBlink: true,
      fontFamily: terminalFontFamily(prefs0.font),
      fontSize:
        prefs0.size === "auto" ? terminalFontSizeForWidth(tierW0) : prefs0.size,
      lineHeight: terminalLineHeightForWidth(tierW0),
      letterSpacing: 0,
      fontWeight: "400",
      fontWeightBold: "700",
      macOptionIsMeta: true,
      // Hold Option (Alt on Linux/Windows) to force native text selection
      // even when the inner Fabric TUI has enabled xterm mouse-events
      // mode (CSI ?1000h family). Without this, click-and-drag in the
      // chat canvas selects nothing and Cmd+C falls back to copying the
      // entire visible buffer, which is rarely what the user wants.
      // See #25720.
      macOptionClickForcesSelection: true,
      // Right-click selects the word under the pointer. xterm.js default
      // is false; enabling it gives users a single-action selection
      // path on top of the modifier-based bypass above.
      rightClickSelectsWord: true,
      // Browser-embedded chat runs the TUI in inline mode. Keep transcript
      // history in xterm.js so the browser wheel can scroll it directly.
      scrollback: 5000,
      theme: terminalSessionTheme,
    });
    termRef.current = term;

    // --- Clipboard integration ---------------------------------------
    //
    // Three independent paths all route to the system clipboard:
    //
    //   1. **Selection → Ctrl+C (or Cmd+C on macOS).**  Ink's own handler
    //      in useInputHandlers.ts turns Ctrl+C into a copy when the
    //      terminal has a selection, then emits an OSC 52 escape.  Our
    //      OSC 52 handler below decodes that escape and writes to the
    //      browser clipboard — so the flow works just like it does in
    //      `fabric --tui`.
    //
    //   2. **Ctrl/Cmd+Shift+C.**  Belt-and-suspenders shortcut that
    //      operates directly on xterm's selection, useful if the TUI
    //      ever stops listening (e.g. overlays / pickers) or if the user
    //      has selected with the mouse outside of Ink's selection model.
    //
    //   3. **Ctrl/Cmd+Shift+V.**  Reads the system clipboard and feeds
    //      it to the terminal as keyboard input.  xterm's paste() wraps
    //      it with bracketed-paste if the host has that mode enabled.
    //
    // OSC 52 reads (terminal asking to read the clipboard) are not
    // supported — that would let any content the TUI renders exfiltrate
    // the user's clipboard.
    term.parser.registerOscHandler(52, (data) => {
      // Format: "<targets>;<base64 | '?'>"
      const semi = data.indexOf(";");
      if (semi < 0) return false;
      const payload = data.slice(semi + 1);
      if (payload === "?" || payload === "") return false; // read/clear — ignore
      try {
        const binary = atob(payload);
        const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
        const text = new TextDecoder("utf-8").decode(bytes);
        navigator.clipboard.writeText(text).catch((err) => {
          // Most common reason: the Clipboard API requires a user gesture.
          // This can fail when the OSC 52 response arrives outside the
          // original keydown event's activation. Log to aid debugging.
          console.warn("[dashboard clipboard] OSC 52 write failed:", err.message);
        });
      } catch {
        console.warn("[dashboard clipboard] malformed OSC 52 payload");
      }
      return true;
    });

    const isMac =
      typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

    term.attachCustomKeyEventHandler((ev) => {
      if (ev.type !== "keydown") return true;

      // Copy: Cmd+C on macOS, Ctrl+Shift+C on other platforms. Bare Ctrl+C
      // is reserved for SIGINT to the TUI child — matches xterm / gnome-terminal /
      // konsole / Windows Terminal. Ctrl+Shift+C only copies if a selection exists;
      // without a selection it passes through to the TUI so agents can still
      // react to the keypress.
      // Paste: Cmd+Shift+V on macOS, Ctrl+Shift+V on others.
      const copyModifier = isMac ? ev.metaKey : ev.ctrlKey && ev.shiftKey;
      const pasteModifier = isMac ? ev.metaKey : ev.ctrlKey && ev.shiftKey;

      if (copyModifier && ev.key.toLowerCase() === "c") {
        const sel = term.getSelection();
        if (sel) {
          // Direct writeText inside the keydown handler preserves the user
          // gesture — async round-trips through OSC 52 can lose activation
          // and fail with "Document is not focused".
          navigator.clipboard.writeText(sel).catch((err) => {
            console.warn("[dashboard clipboard] direct copy failed:", err.message);
          });
          // Clear xterm.js's highlight after copy (matches gnome-terminal).
          term.clearSelection();
          ev.preventDefault();
          return false;
        }
        // No selection → fall through so the TUI receives Ctrl+Shift+C
        // (or the bare ev if the user used a different modifier).
      }

      if (pasteModifier && ev.key.toLowerCase() === "v") {
        navigator.clipboard
          .readText()
          .then((text) => {
            if (text) term.paste(text);
          })
          .catch((err) => {
            console.warn("[dashboard clipboard] paste failed:", err.message);
          });
        ev.preventDefault();
        return false;
      }

      return true;
    });

    const fit = new FitAddon();
    fitRef.current = fit;
    term.loadAddon(fit);

    // Dashboard chat should scroll the browser-side transcript, not send
    // mouse-wheel protocol bytes through the PTY.
    term.attachCustomWheelEventHandler((ev) => {
      const delta = ev.deltaY;
      if (!delta) {
        return false;
      }

      const step = Math.max(1, Math.round(Math.abs(delta) / 50));
      term.scrollLines(delta > 0 ? step : -step);

      ev.preventDefault();
      ev.stopPropagation();
      return false;
    });

    const unicode11 = new Unicode11Addon();
    term.loadAddon(unicode11);
    term.unicode.activeVersion = "11";

    term.loadAddon(new WebLinksAddon());

    term.open(host);

    // WebGL draws from a texture atlas sized with device pixels. On phones and
    // in DevTools device mode that often produces *visually* much larger cells
    // than `fontSize` suggests — users see "huge" text even at 7–9px settings.
    // The canvas/DOM renderer tracks `fontSize` faithfully; use it for narrow
    // hosts.  Wide layouts still get WebGL for crisp box-drawing.
    const useWebgl = terminalTierWidthPx(host) >= 768;
    if (useWebgl) {
      try {
        const webgl = new WebglAddon();
        webgl.onContextLoss(() => webgl.dispose());
        term.loadAddon(webgl);
      } catch (err) {
        console.warn(
          "[fabric-chat] WebGL renderer unavailable; falling back to default",
          err,
        );
      }
    }

    // Initial fit + resize observer.  fit.fit() reads the container's
    // current bounding box and resizes the terminal grid to match.
    //
    // The subtle bit: the dashboard has CSS transitions on the container
    // (backdrop fade-in, rounded corners settling as fonts load).  If we
    // call fit() at mount time, the bounding box we measure is often 1-2
    // cell widths off from the final size.  ResizeObserver *does* fire
    // when the container settles, but if the pixel delta happens to be
    // smaller than one cell's width, fit() computes the same integer
    // (cols, rows) as before and doesn't emit onResize — so the PTY
    // never learns the final size.  Users see truncated long lines until
    // they resize the browser window.
    //
    // We force one extra fit + explicit RESIZE send after two animation
    // frames.  rAF→rAF guarantees one layout commit between the two
    // callbacks, giving CSS transitions and font metrics time to finalize
    // before we take the authoritative measurement.
    let hostSyncRaf = 0;
    const scheduleHostSync = () => {
      if (hostSyncRaf) return;
      hostSyncRaf = requestAnimationFrame(() => {
        hostSyncRaf = 0;
        syncTerminalMetrics();
      });
    };

    let metricsDebounce: ReturnType<typeof setTimeout> | null = null;
    const syncTerminalMetrics = () => {
      // display:none hosts have clientWidth/Height = 0, which fit() turns
      // into a 1x1 terminal.  Skip entirely while hidden; the visibility
      // effect below runs another fit as soon as the tab is shown again.
      if (!host.isConnected || host.clientWidth <= 0 || host.clientHeight <= 0) {
        return;
      }
      const w = terminalTierWidthPx(host);
      const sizePref = terminalPrefsRef.current.size;
      const nextSize =
        sizePref === "auto" ? terminalFontSizeForWidth(w) : sizePref;
      const nextLh = terminalLineHeightForWidth(w);
      const fontChanged =
        term.options.fontSize !== nextSize ||
        term.options.lineHeight !== nextLh;
      if (fontChanged) {
        term.options.fontSize = nextSize;
        term.options.lineHeight = nextLh;
      }
      try {
        fit.fit();
      } catch {
        return;
      }
      if (fontChanged && term.rows > 0) {
        try {
          term.refresh(0, term.rows - 1);
        } catch {
          /* ignore */
        }
      }
      if (
        fontChanged &&
        wsRef.current &&
        wsRef.current.readyState === WebSocket.OPEN
      ) {
        wsRef.current.send(`\x1b[RESIZE:${term.cols};${term.rows}]`);
      }
    };
    syncMetricsRef.current = syncTerminalMetrics;

    const scheduleSyncTerminalMetrics = () => {
      if (metricsDebounce) clearTimeout(metricsDebounce);
      metricsDebounce = setTimeout(() => {
        metricsDebounce = null;
        syncTerminalMetrics();
      }, 60);
    };

    const ro = new ResizeObserver(() => scheduleHostSync());
    ro.observe(host);

    window.addEventListener("resize", scheduleSyncTerminalMetrics);
    window.visualViewport?.addEventListener("resize", scheduleSyncTerminalMetrics);
    scheduleHostSync();
    requestAnimationFrame(() => scheduleHostSync());

    // Double-rAF authoritative fit.  On the second frame the layout has
    // committed at least once since mount; fit.fit() then reads the
    // stable container size.  We always send a RESIZE escape afterwards
    // (even if fit's cols/rows didn't change, so the PTY has the same
    // dims registered as our JS state — prevents a drift where Ink
    // thinks the terminal is one col bigger than what's on screen).
    let settleRaf1 = 0;
    let settleRaf2 = 0;
    settleRaf1 = requestAnimationFrame(() => {
      settleRaf1 = 0;
      settleRaf2 = requestAnimationFrame(() => {
        settleRaf2 = 0;
        syncTerminalMetrics();
      });
    });

    // WebSocket. In gated mode (``window.__FABRIC_AUTH_REQUIRED__``) this
    // awaits a single-use ticket via /api/auth/ws-ticket before opening;
    // in loopback mode it resolves synchronously against the injected
    // session token. The IIFE keeps the outer effect synchronous so its
    // ``return cleanup`` stays at the top level; handlers + disposables
    // are hoisted to ``let`` bindings the cleanup closes over.
    let unmounting = false;
    let onDataDisposable: { dispose(): void } | null = null;
    let onResizeDisposable: { dispose(): void } | null = null;
    const forceFresh = forceFreshPtyRef.current;
    forceFreshPtyRef.current = false;
    const scheduleReconnect = (code: number) => {
      if (reconnectTimerRef.current) {
        return;
      }
      const attempt = Math.min(reconnectAttemptRef.current + 1, 5);
      reconnectAttemptRef.current = attempt;
      const delayMs = Math.min(250 * 2 ** (attempt - 1), 3000);
      setSessionEnded(false);
      setBanner(
        `Chat connection interrupted (code ${code}). Reconnecting…`,
      );
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        setReconnectNonce((n) => n + 1);
      }, delayMs);
    };
    void (async () => {
      if (unmounting) return;
      const params: Record<string, string> = { channel };
      if (resumeParam) params.resume = resumeParam;
      if (forceFresh) params.fresh = "1";
      // Keep-alive identity: reattach to this tab's living PTY across
      // refresh/transient drops. A forced-fresh start rotates the token so
      // the previous keep-alive PTY is not reattached (registry reaps it).
      params.attach = ptyAttachToken(forceFresh);
      // Profile-scoped chat: the PTY child gets FABRIC_HOME pointed at the
      // selected profile, so the conversation runs with that profile's model,
      // skills, memory, and sessions (see web_server._resolve_chat_argv).
      if (chatProfile) params.profile = chatProfile;
      // Terminal canvas hint: the server forwards this as
      // FABRIC_TUI_BACKGROUND so the TUI child picks the light/dark
      // palette matching the xterm canvas it will actually render on.
      params.bg = terminalSessionTheme.background;
      const url = await api.buildWsUrl("/api/pty", params);
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        clearReconnectTimer();
        reconnectAttemptRef.current = 0;
        setBanner(null);
        setSessionEnded(false);
        // Connected — cancel any pending reconnect from a prior transient drop.
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = null;
        }
        // Send the initial RESIZE immediately so Ink has *a* size to lay
        // out against on its first paint.  The double-rAF block above will
        // follow up with the authoritative measurement — at worst Ink
        // reflows once after the PTY boots, which is imperceptible.
        ws.send(`\x1b[RESIZE:${term.cols};${term.rows}]`);
        const pendingDraft = pendingComposerDraftRef.current;
        if (pendingDraft) {
          // A cold /workspace/chat?draft= load reaches this branch before
          // Ink's composer mounts. Bracketed paste fills the composer without
          // submitting it so the user can review the generated brief.
          setTimeout(() => {
            try {
              if (
                wsRef.current?.readyState === WebSocket.OPEN &&
                pendingComposerDraftRef.current === pendingDraft
              ) {
                wsRef.current.send(composerDraftPayload(pendingDraft));
                pendingComposerDraftRef.current = null;
              }
            } catch {
              /* PTY not ready / closed — leave the draft pending for reconnect */
            }
          }, 800);
        }
        // One-shot: a ?learn=<text> param (set by the Skills page "Learn a
        // skill" panel) is typed into the composer as a /learn command once the
        // PTY is up. /learn resolves via command.dispatch → a normal agent turn,
        // so this reuses the existing composer path — no special PTY protocol.
        const learnSeed = searchParams.get("learn");
        if (learnSeed) {
          const next = new URLSearchParams(searchParams);
          next.delete("learn");
          setSearchParams(next, { replace: true });
          const cmd = `/learn ${learnSeed}`.trim();
          // Delay so Ink's composer has mounted and grabbed focus before input.
          setTimeout(() => {
            try {
              wsRef.current?.send(cmd + "\r");
            } catch {
              /* PTY not ready / closed — user can retype */
            }
          }, 800);
        }
      };

      ws.onmessage = (ev) => {
        if (typeof ev.data === "string") {
          term.write(ev.data);
        } else {
          term.write(new Uint8Array(ev.data as ArrayBuffer));
        }
      };

      ws.onclose = (ev) => {
        wsRef.current = null;
        if (unmounting) {
          return;
        }
        // Surface the real cause to the browser console on every close so a
        // "chat won't connect" report can be diagnosed without server access.
        // The server sends a machine-parseable reason on every rejection (see
        // pty_ws in web_server.py); echo it verbatim alongside the close code.
        const why = ev.reason ? ` reason=${ev.reason}` : "";
        console.warn(`[chat] PTY WebSocket closed code=${ev.code}${why}`);
        if (ev.code === 4401) {
          setBanner(
            ev.reason
              ? `Auth failed (${ev.reason}). Reload to refresh the session.`
              : "Auth failed. Reload the page to refresh the session token.",
          );
          return;
        }
        if (ev.code === 4403) {
          // Host/Origin mismatch (DNS-rebinding guard).
          setBanner(
            ev.reason
              ? `Refused: ${ev.reason}.`
              : "Refused: request host/origin doesn't match the dashboard.",
          );
          return;
        }
        if (ev.code === 4404) {
          setBanner(
            ev.reason
              ? `Chat websocket unavailable: ${ev.reason}.`
              : "Chat websocket unavailable on this server.",
          );
          return;
        }
        if (ev.code === 4408) {
          setBanner(
            ev.reason
              ? `Refused: ${ev.reason}.`
              : "Refused: your client isn't permitted (server bound to localhost only).",
          );
          return;
        }
        if (ev.code === 1011) {
          // Server already wrote an ANSI error frame.
          return;
        }
        // Keep-alive close-code contract (web_server.pty_ws + pty_session):
        //   4410 = the agent PROCESS exited (real end) → restart affordance.
        //   4409 = superseded by a newer tab attaching the same token → stay quiet.
        if (ev.code === 4410) {
          term.write(`\r\n\x1b[90m[session ended]\x1b[0m\r\n`);
          setSessionEnded(true);
          return;
        }
        if (ev.code === 4409) {
          return;
        }
        if (!ev.wasClean || ev.code === 1001 || ev.code === 1006) {
          // Transient transport drop (refresh, sleep/wake, signal loss).
          // Reconnect with backoff; the same ?attach= token reattaches to
          // the still-living PTY, so the conversation continues in place.
          scheduleReconnect(ev.code);
          return;
        }
        // Normal/clean exit: the agent process ended (e.g. the user typed
        // `/exit`, or started a new session). NS-504: surface an explicit
        // restart affordance instead of leaving a dead terminal that only a
        // full page refresh could recover.
      term.write(
        `\r\n\x1b[90m[session ended (code ${ev.code})]\x1b[0m\r\n`,
      );
        setSessionEnded(true);
      };

      // Keystrokes → PTY.
      //
      // IMPORTANT:
      // The embedded web chat has occasionally surfaced stray letters/digits
      // in the input line after a turn completes. The most likely culprit is
      // browser-side terminal control traffic being forwarded back into the
      // PTY as if it were user text. SGR mouse tracking is the highest-risk
      // path here: xterm.js emits raw CSI reports (`\x1b[<...`) that look like
      // ordinary bytes to the backend.
      //
      // For the browser embed we prefer input stability over terminal-style
      // mouse reporting, so we drop SGR mouse reports entirely instead of
      // forwarding them into Fabric. Keyboard input, paste, and resize still
      // behave normally.
      // eslint-disable-next-line no-control-regex -- intentional ESC byte in xterm SGR mouse report parser
      const SGR_MOUSE_RE = /^\x1b\[<(\d+);(\d+);(\d+)([Mm])$/;
      onDataDisposable = term.onData((data) => {
        if (ws.readyState !== WebSocket.OPEN) return;

        if (SGR_MOUSE_RE.test(data)) {
          return;
        }

        ws.send(data);
      });

      onResizeDisposable = term.onResize(({ cols, rows }) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(`\x1b[RESIZE:${cols};${rows}]`);
        }
      });
    })();

    term.focus();

    return () => {
      unmounting = true;
      syncMetricsRef.current = null;
      onDataDisposable?.dispose();
      onResizeDisposable?.dispose();
      if (metricsDebounce) clearTimeout(metricsDebounce);
      window.removeEventListener("resize", scheduleSyncTerminalMetrics);
      window.visualViewport?.removeEventListener(
        "resize",
        scheduleSyncTerminalMetrics,
      );
      ro.disconnect();
      if (hostSyncRaf) cancelAnimationFrame(hostSyncRaf);
      if (settleRaf1) cancelAnimationFrame(settleRaf1);
      if (settleRaf2) cancelAnimationFrame(settleRaf2);
      clearReconnectTimer();
      // Phase 5.3: ``ws`` is local to the IIFE that opens it (the gated-mode
      // ticket fetch makes the open async). The cleanup runs at the outer
      // effect's top level so it can't reach into that scope — close via
      // the ref instead. ``?.`` covers the race where unmount fires before
      // the ticket fetch resolves and ``wsRef.current`` was never assigned.
      wsRef.current?.close();
      wsRef.current = null;
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      if (copyResetRef.current) {
        clearTimeout(copyResetRef.current);
        copyResetRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
    // Dashboard theme changes intentionally do not replace
    // `terminalSessionTheme` until `channel` rotates. `searchParams` is read
    // only for one-shot directives and may be rewritten inside this effect;
    // depending on it would respawn the PTY and break persistent Chat.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    channel,
    clearReconnectTimer,
    resumeParam,
    chatProfile,
    reconnectNonce,
    terminalSessionTheme,
  ]);

  // Terminal font prefs apply to the RUNNING terminal (unlike colors, which
  // stay pinned per PTY session — see terminalSessionTheme): update xterm's
  // options in place, then re-run the shared metrics sync so the grid
  // refits to the new cell size and the PTY learns any cols/rows change
  // (fit → term.onResize → RESIZE escape).
  useEffect(() => {
    const term = termRef.current;
    if (!term) return;
    const family = terminalFontFamily(terminalPrefs.font);
    if (term.options.fontFamily !== family) {
      term.options.fontFamily = family;
    }
    syncMetricsRef.current?.();
    // First-time selection of an uncached webfont: the fit above measured
    // the fallback face (the provider injects the stylesheet async). Refit
    // when the real glyphs arrive so cell metrics match what's rendered.
    // `load()` covers a face that's already registered; the `loadingdone`
    // listener covers the stylesheet finishing after this effect ran.
    const choice = getTerminalFontChoice(terminalPrefs.font);
    if (!choice || typeof document === "undefined" || !document.fonts) {
      return;
    }
    const refit = () => syncMetricsRef.current?.();
    document.fonts.load(`16px ${choice.family}`).then(refit).catch(() => {});
    document.fonts.addEventListener("loadingdone", refit);
    return () => document.fonts.removeEventListener("loadingdone", refit);
  }, [terminalPrefs.font, terminalPrefs.size]);

  // When the user returns to the chat tab (isActive: false → true), the
  // terminal host just transitioned from display:none to display:flex.
  // ResizeObserver won't fire on that kind of style-driven box change —
  // xterm thinks its grid is still whatever it was when the tab was
  // hidden (or 0×0, if it was hidden before first fit).  Force a refit
  // after two animation frames so layout has committed.
  //
  // Focus handling: we only steal focus back into the terminal when
  // nothing else inside ChatPage was holding it (typically the first
  // activation after mount, where document.activeElement is <body>; or
  // a return after the user had been typing in the terminal, where
  // focus was already on the xterm textarea before the tab got hidden
  // and has since fallen back to <body>).  If the user had clicked
  // into the sidebar (model picker, tool-call entry) before switching
  // tabs, we must not yank focus away from wherever they left it when
  // they come back — that's a surprise and an a11y foot-gun.
  useEffect(() => {
    if (!isActive) return;
    let raf1 = 0;
    let raf2 = 0;
    raf1 = requestAnimationFrame(() => {
      raf1 = 0;
      raf2 = requestAnimationFrame(() => {
        raf2 = 0;
        syncMetricsRef.current?.();
        const host = hostRef.current;
        const active = typeof document !== "undefined"
          ? document.activeElement
          : null;
        const focusIsElsewhereInChatPage =
          active !== null &&
          active !== document.body &&
          host !== null &&
          !host.contains(active);
        if (!focusIsElsewhereInChatPage) {
          termRef.current?.focus();
        }
      });
    });
    return () => {
      if (raf1) cancelAnimationFrame(raf1);
      if (raf2) cancelAnimationFrame(raf2);
    };
  }, [isActive]);

  // Each rail is represented once. ChatWorkspaceLayout mounts only the rail
  // visible at the current breakpoint; compact sheets mount their content
  // only while open. This keeps session REST and context WebSocket traffic
  // proportional to what the user can actually see.
  const conversationsPanel = (
    <ChatSessionList
      activeSessionId={resumeParam}
      profile={chatProfile}
      onPicked={closeCompactPanel}
      onNewChat={startFreshDashboardChat}
      refreshSignal={sessionListRefreshSignal}
    />
  );
  const contextPanel = (
    <ChatContextPanel
      channel={channel}
      isActive={isActive}
      profile={chatProfile}
      onDashboardNewSessionRequest={startFreshDashboardChat}
      onNavigate={navigateFromChatRail}
      onSessionTitleChange={handleSessionTitleChange}
    />
  );

  const terminalPane = (
    <div
      className={cn(
        "relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
        "p-2 sm:p-3 lg:p-4",
      )}
      style={{
        backgroundColor: terminalSessionTheme.background,
      }}
    >
      <div
        ref={hostRef}
        className="fabric-chat-xterm-host min-h-0 min-w-0 flex-1"
      />

      {/* NS-504: the agent process exited (e.g. `/exit` or a new session).
          Offer an in-place restart so the user never has to refresh the
          whole page to get a working chat back. */}
      {sessionEnded && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-black/60">
          <div className="text-sm tracking-wide text-white/80">
            Session ended.
          </div>
          <Button
            onClick={reconnect}
            prefix={<RotateCcw className="h-4 w-4" />}
            aria-label="Start a new chat session"
          >
            Start new session
          </Button>
        </div>
      )}

      <Button
        ghost
        onClick={handleCopyLast}
        title="Copy last assistant response as raw markdown"
        aria-label="Copy last assistant response"
        className={cn(
          "absolute z-10",
          "normal-case tracking-normal font-normal",
          "rounded border border-current/30",
          "bg-black/20",
          "opacity-70 hover:opacity-100 hover:border-current/60",
          "transition-opacity duration-150",
          "bottom-2 right-2 px-2 py-1 text-xs sm:bottom-3 sm:right-3 sm:px-2.5 sm:py-1.5",
          "lg:bottom-4 lg:right-4",
        )}
        style={{ color: terminalFg }}
      >
        <span className="inline-flex items-center gap-1.5">
          <Copy className="h-3 w-3 shrink-0" />
          <span className="hidden min-[400px]:inline tracking-wide">
            {copyState === "copied" ? "copied" : "copy last response"}
          </span>
        </span>
      </Button>
    </div>
  );

  const compactSheet =
    compactPanel === "conversations" ? (
      <ChatSideSheet
        id="chat-conversations-sheet"
        onClose={closeCompactPanel}
        side="left"
        title={chatLabels?.conversations ?? "Conversations"}
      >
        {conversationsPanel}
      </ChatSideSheet>
    ) : compactPanel === "context" ? (
      <ChatSideSheet
        id="chat-context-sheet"
        onClose={closeCompactPanel}
        side="right"
        title={chatLabels?.context ?? "Context"}
      >
        {contextPanel}
      </ChatSideSheet>
    ) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PluginSlot name="chat:top" />
      {compactSheet}

      {banner && (
        <div className="border border-warning/50 bg-warning/10 text-warning px-3 py-2 text-xs tracking-wide">
          {banner}
        </div>
      )}

      <ChatWorkspaceLayout
        active={isActive}
        context={contextPanel}
        conversations={conversationsPanel}
        mode={viewportMode}
        terminal={terminalPane}
      />
      <PluginSlot name="chat:bottom" />
    </div>
  );
}

declare global {
  interface Window {
    __FABRIC_SESSION_TOKEN__?: string;
    __FABRIC_AUTH_REQUIRED__?: boolean;
  }
}
