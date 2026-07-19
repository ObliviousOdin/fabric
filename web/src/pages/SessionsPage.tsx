import {
  useEffect,
  useLayoutEffect,
  useState,
  useCallback,
  useRef,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Search,
  Trash2,
  Clock,
  X,
  Eraser,
  Archive,
} from "lucide-react";
import { api } from "@/lib/api";
import { shouldRefreshSessions } from "@/lib/session-refresh";
import type {
  SessionInfo,
  SessionSearchResult,
  SessionStoreStats,
  StatusResponse,
} from "@/lib/api";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  FilterGroup,
  Segmented,
} from "@nous-research/ui/ui/components/segmented";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Badge } from "@/components/fabric/Badge";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { Input } from "@nous-research/ui/ui/components/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@nous-research/ui/ui/components/dialog";
import { EmptyState, PageToolbar, Skeleton } from "@/components/ui";
import { GatewayStrip } from "@/components/sessions/GatewayStrip";
import { SessionRunRow } from "@/components/sessions/SessionRunRow";
import { SessionsSummaryStrip } from "@/components/sessions/SessionsSummaryStrip";
import { useSystemActions } from "@/contexts/useSystemActions";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";

const PAGE_SIZE = 20;

/** S1.3 — server-side `source=` filter values ("all" = no filter). */
const SOURCE_FILTERS = [
  "all",
  "cli",
  "telegram",
  "discord",
  "slack",
  "whatsapp",
  "cron",
] as const;

function SessionsPagination({
  className,
  compact = false,
  onPageChange,
  page,
  total,
}: SessionsPaginationProps) {
  const { t } = useI18n();
  const pageCount = Math.ceil(total / PAGE_SIZE);

  return (
    <div
      className={`flex items-center ${compact ? "gap-1" : "justify-between pt-2"}${className ? ` ${className}` : ""}`}
    >
      {!compact && (
        <span className="text-xs text-muted-foreground tabular-nums">
          {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)}{" "}
          {t.common.of} {total}
        </span>
      )}

      <div className="flex items-center gap-1">
        <Button
          outlined
          size="icon"
          disabled={page === 0}
          onClick={() => onPageChange(page - 1)}
          aria-label={t.sessions.previousPage}
        >
          <ChevronLeft />
        </Button>
        <span className="px-2 text-xs text-muted-foreground tabular-nums">
          {t.common.page} {page + 1} {t.common.of} {pageCount}
        </span>
        <Button
          outlined
          size="icon"
          disabled={(page + 1) * PAGE_SIZE >= total}
          onClick={() => onPageChange(page + 1)}
          aria-label={t.sessions.nextPage}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}

export default function SessionsPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  // Server-side source filter (S1.3). "all" = no source param.
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<
    SessionSearchResult[] | null
  >(null);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);
  const logScrollRef = useRef<HTMLPreElement | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [overviewSessions, setOverviewSessions] = useState<SessionInfo[]>([]);
  // Count of empty (no-message, ended, non-archived) sessions across the
  // entire DB, populated by /api/sessions/empty/count. Used to:
  //   • hide the "Delete empty" button when there's nothing to clean up
  //   • show "(N)" alongside the label
  //   • surface the count in the confirm dialog body
  // Refreshed on mount, after single-session deletes, and after the bulk
  // delete itself — none of those code paths can update the global empty
  // count from local state alone (per-page list != global DB count).
  const [emptyCount, setEmptyCount] = useState(0);
  const [deleteEmptyOpen, setDeleteEmptyOpen] = useState(false);
  const [deletingEmpty, setDeletingEmpty] = useState(false);
  // Bulk-select-then-delete state. ``selectedIds`` is a Set so per-row
  // checkbox toggles and ``has()`` lookups are O(1); we wrap mutations
  // in a fresh Set so React notices the change (mutating in place
  // wouldn't trigger a re-render).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // Index of the last row whose checkbox was clicked WITHOUT shift,
  // resolved against the currently visible (post-search) ``filtered``
  // list. Used as the anchor for shift-click range select — matches the
  // Gmail / Notion / file-explorer convention. ``null`` means "no
  // anchor yet", in which case shift-click degrades to a plain toggle.
  const lastClickedIndexRef = useRef<number | null>(null);
  const [deleteSelectedOpen, setDeleteSelectedOpen] = useState(false);
  const [deletingSelected, setDeletingSelected] = useState(false);
  const [stats, setStats] = useState<SessionStoreStats | null>(null);
  const [pruneOpen, setPruneOpen] = useState(false);
  const [pruneDays, setPruneDays] = useState("90");
  const [pruning, setPruning] = useState(false);
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const L = t.sessions.ledger;
  const navigate = useNavigate();
  const { setAfterTitle, setEnd } = usePageHeader();
  const { activeAction, actionStatus, dismissLog } = useSystemActions();

  const refreshEmptyCount = useCallback(() => {
    api
      .getEmptySessionsCount()
      .then((r) => setEmptyCount(r.count))
      .catch(() => {});
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
    lastClickedIndexRef.current = null;
  }, []);

  useLayoutEffect(() => {
    if (loading) {
      setAfterTitle(null);
      return;
    }
    setAfterTitle(
      <Badge tone="secondary" className="text-xs tabular-nums">
        {total}
      </Badge>,
    );
    return () => {
      setAfterTitle(null);
    };
  }, [loading, setAfterTitle, total]);

  useEffect(() => {
    setEnd(
      <Button
        outlined
        size="sm"
        onClick={() => setPruneOpen(true)}
        prefix={<Archive />}
      >
        Prune old sessions
      </Button>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd]);

  const loadSessions = useCallback(
    (p: number, silent = false) => {
      // ``silent`` skips the loading skeleton so background refreshes
      // (triggered when the overview poll detects a new session from
      // another process) don't flicker the whole page or drop the user's
      // scroll position.
      if (!silent) setLoading(true);
      api
        .getSessions(
          PAGE_SIZE,
          p * PAGE_SIZE,
          undefined,
          "created",
          sourceFilter === "all" ? undefined : sourceFilter,
        )
        .then((resp) => {
          setSessions(resp.sessions);
          setTotal(resp.total);
          setListError(null);
        })
        // S11: list-fetch failures surface a destructive banner + Retry
        // instead of being swallowed. Silent-refresh failures land in the
        // same banner while the stale list stays visible.
        .catch((err) => setListError(String(err)))
        .finally(() => {
          if (!silent) setLoading(false);
        });
    },
    [sourceFilter],
  );

  const loadStats = useCallback(() => {
    api
      .getSessionStats()
      .then(setStats)
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // Refs for the overview poll's new-session detection. The poll effect
  // below reads the current page and the last-seen newest session id
  // through refs instead of capturing stale values. ``newestSeenRef``
  // starts null so the first poll sets a baseline without triggering a
  // redundant reload (mount already loads).
  const newestSeenRef = useRef<string | null>(null);
  const pageRef = useRef(page);
  useEffect(() => {
    // Ref writes are not allowed during render; the poll callbacks that
    // read pageRef fire from timers, so an effect-timed sync is early
    // enough.
    pageRef.current = page;
  }, [page]);

  useEffect(() => {
    // Next-frame hop: loadSessions flips loading state synchronously,
    // which inside an effect body forces a cascading render. `loading`
    // already starts true, so the initial paint is unaffected.
    const frame = requestAnimationFrame(() => {
      loadSessions(page);
      refreshEmptyCount();
    });
    return () => cancelAnimationFrame(frame);
  }, [loadSessions, page, refreshEmptyCount]);

  useEffect(() => {
    // S7: the 5 s overview poll + head-id change detection is the only
    // liveness mechanism for the ledger AND the "active now" stat — keep
    // exactly as-is (a global event channel is Appendix B1, not this pass).
    const loadOverview = () => {
      api
        .getStatus()
        .then(setStatus)
        .catch(() => {});
      api
        .getSessions(50)
        .then((r) => {
          setOverviewSessions(r.sessions);
          // The dashboard server and a terminal CLI are separate
          // processes sharing one session DB — there is no push channel,
          // so we detect sessions created in another process here. The
          // overview poll already fetches the 50 newest sessions, so we
          // reuse its head id as a cheap change signal: when it changes,
          // silently refresh the paginated list so the new session shows
          // up in real time without a visible loading flicker.
          const newest = r.sessions[0]?.id ?? null;
          if (shouldRefreshSessions(newestSeenRef.current, newest)) {
            loadSessions(pageRef.current, true);
          }
          newestSeenRef.current = newest;
        })
        .catch(() => {});
    };
    loadOverview();
    const id = setInterval(loadOverview, 5000);
    return () => clearInterval(id);
  }, [loadSessions]);

  useEffect(() => {
    const el = logScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [actionStatus?.lines]);

  // Wrapped setters that ALSO clear the bulk selection. The user's
  // mental model is "I'm selecting what I can see" — carrying a
  // selection across a page change, search input, or filter change
  // would arm invisible rows for deletion, which is the exact footgun
  // the confirm dialog can't catch. Doing this at the call sites
  // instead of in a ``useEffect`` keeps us out of the
  // react-hooks/set-state-in-effect lint trap and the cascading
  // re-render it warns about.
  const goToPage = useCallback(
    (p: number) => {
      setPage(p);
      clearSelection();
    },
    [clearSelection],
  );
  const updateSearch = useCallback(
    (value: string) => {
      setSearch(value);
      clearSelection();
    },
    [clearSelection],
  );
  // Source filter changes reset the page and clear the selection, same
  // contract as ``updateSearch`` (S1.3).
  const updateSourceFilter = useCallback(
    (value: string) => {
      setSourceFilter(value);
      setPage(0);
      clearSelection();
    },
    [clearSelection],
  );

  // Debounced FTS search. The immediate state flips (reset on clear, the
  // spinner while the debounce runs) hop to the next frame — synchronous
  // setState in an effect body forces a cascading render.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!search.trim()) {
      const frame = requestAnimationFrame(() => {
        setSearchResults(null);
        setSearching(false);
      });
      return () => cancelAnimationFrame(frame);
    }

    const frame = requestAnimationFrame(() => setSearching(true));
    debounceRef.current = setTimeout(() => {
      api
        .searchSessions(search.trim())
        .then((resp) => setSearchResults(resp.results))
        .catch(() => setSearchResults(null))
        .finally(() => setSearching(false));
    }, 300);

    return () => {
      cancelAnimationFrame(frame);
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [search]);

  const sessionDelete = useConfirmDelete({
    onDelete: useCallback(
      async (id: string) => {
        try {
          await api.deleteSession(id);
          setSessions((prev) => prev.filter((s) => s.id !== id));
          setTotal((prev) => prev - 1);
          if (expandedId === id) setExpandedId(null);
          // Drop the deleted ID from any active bulk-select set — it
          // can't bulk-delete a row that's already gone.
          setSelectedIds((prev) => {
            if (!prev.has(id)) return prev;
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
          // A single-session delete might have been an empty one — re-fetch
          // the global empty count so the button hides itself / its badge
          // ticks down without waiting for the next page navigation.
          refreshEmptyCount();
          showToast(t.sessions.sessionDeleted, "success");
          loadStats();
        } catch {
          showToast(t.sessions.failedToDelete, "error");
          throw new Error("delete failed");
        }
      },
      [
        expandedId,
        refreshEmptyCount,
        showToast,
        loadStats,
        t.sessions.sessionDeleted,
        t.sessions.failedToDelete,
      ],
    ),
  });

  /** Toggle one row's selection. When ``event.shiftKey`` is true AND we
   *  have a previous anchor, every row between the anchor and the
   *  current index (inclusive) is set to the current row's NEW state —
   *  matches Gmail/Notion/file-explorer semantics. ``visibleList`` must
   *  be the currently rendered list (post-search), since indices are
   *  resolved against what the user is actually looking at.
   */
  const handleSelectClick = useCallback(
    (event: React.MouseEvent, index: number, visibleList: SessionInfo[]) => {
      const id = visibleList[index]?.id;
      if (!id) return;
      setSelectedIds((prev) => {
        const next = new Set(prev);
        const wasSelected = next.has(id);
        const willSelect = !wasSelected;

        const anchor = lastClickedIndexRef.current;
        // Shift-click extends the selection from the anchor to here.
        // Skip if there's no anchor or the anchor is outside the
        // visible list — in those cases fall through to a plain toggle
        // (the click also resets the anchor below).
        if (event.shiftKey && anchor !== null && anchor < visibleList.length) {
          const [lo, hi] =
            anchor <= index ? [anchor, index] : [index, anchor];
          for (let i = lo; i <= hi; i++) {
            const rowId = visibleList[i]?.id;
            if (!rowId) continue;
            if (willSelect) next.add(rowId);
            else next.delete(rowId);
          }
        } else if (willSelect) {
          next.add(id);
        } else {
          next.delete(id);
        }
        return next;
      });
      // Always update the anchor to the most recent click — even when
      // it was a shift-click that extended a range, the user's next
      // shift-click should anchor from here, not from two steps back.
      lastClickedIndexRef.current = index;
    },
    [],
  );

  const selectAllOnPage = useCallback((visibleList: SessionInfo[]) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const s of visibleList) next.add(s.id);
      return next;
    });
  }, []);

  const handleDeleteSelected = useCallback(async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      setDeleteSelectedOpen(false);
      return;
    }
    setDeletingSelected(true);
    try {
      const resp = await api.bulkDeleteSessions(ids);
      showToast(
        t.sessions.selectedSessionsDeleted.replace(
          "{count}",
          String(resp.deleted),
        ),
        "success",
      );
      setDeleteSelectedOpen(false);
      // Drop deleted rows out of the visible list immediately rather
      // than waiting for the reload. The reload still runs so total /
      // pagination stays correct, and so any rows the reload pulls in
      // from later pages render in place.
      const deletedSet = new Set(ids);
      setSessions((prev) => prev.filter((s) => !deletedSet.has(s.id)));
      setTotal((prev) => Math.max(0, prev - resp.deleted));
      if (expandedId && deletedSet.has(expandedId)) setExpandedId(null);
      clearSelection();
      loadSessions(page);
      refreshEmptyCount();
    } catch {
      showToast(t.sessions.failedToDeleteSelected, "error");
    } finally {
      setDeletingSelected(false);
    }
  }, [
    clearSelection,
    expandedId,
    loadSessions,
    page,
    refreshEmptyCount,
    selectedIds,
    showToast,
    t.sessions.failedToDeleteSelected,
    t.sessions.selectedSessionsDeleted,
  ]);

  const handleDeleteEmpty = useCallback(async () => {
    setDeletingEmpty(true);
    try {
      const resp = await api.deleteEmptySessions();
      // Show count in the toast so users get confirmation of the actual
      // number removed (which may differ slightly from `emptyCount` if a
      // session entered/left the "empty" set between the count fetch and
      // the delete — e.g. an active session just ended without sending
      // any messages).
      showToast(
        t.sessions.emptySessionsDeleted.replace(
          "{count}",
          String(resp.deleted),
        ),
        "success",
      );
      setDeleteEmptyOpen(false);
      // Reload the current page so any newly-vanished empty sessions
      // drop out of the visible list, and re-fetch the empty count so
      // the button hides itself.
      loadSessions(page);
      refreshEmptyCount();
    } catch {
      showToast(t.sessions.failedToDeleteEmpty, "error");
    } finally {
      setDeletingEmpty(false);
    }
  }, [
    loadSessions,
    page,
    refreshEmptyCount,
    showToast,
    t.sessions.emptySessionsDeleted,
    t.sessions.failedToDeleteEmpty,
  ]);

  const handleRename = useCallback(
    async (id: string, title: string) => {
      try {
        await api.renameSession(id, title);
        setSessions((prev) =>
          prev.map((s) => (s.id === id ? { ...s, title } : s)),
        );
        setOverviewSessions((prev) =>
          prev.map((s) => (s.id === id ? { ...s, title } : s)),
        );
        showToast("Session renamed", "success");
        loadStats();
      } catch {
        showToast("Failed to rename session", "error");
      }
    },
    [showToast, loadStats],
  );

  const handleExport = useCallback(
    async (id: string) => {
      try {
        const res = await fetch(api.exportSessionUrl(id), {
          credentials: "include",
          headers: {
            "X-Fabric-Session-Token":
              (window as unknown as { __DASHBOARD_AUTH_TOKEN__?: string })
                .__DASHBOARD_AUTH_TOKEN__ ?? "",
          },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `session-${id}.json`;
        a.click();
        URL.revokeObjectURL(url);
      } catch {
        showToast("Failed to export session", "error");
      }
    },
    [showToast],
  );

  const handlePrune = useCallback(async () => {
    const days = parseInt(pruneDays, 10);
    if (!Number.isFinite(days) || days < 0) {
      showToast("Enter a valid number of days", "error");
      return;
    }
    setPruning(true);
    try {
      const resp = await api.pruneSessions(days);
      showToast(
        `Pruned ${resp.removed} session${resp.removed === 1 ? "" : "s"}`,
        "success",
      );
      setPruneOpen(false);
      loadSessions(0);
      setPage(0);
      loadStats();
    } catch {
      showToast("Failed to prune sessions", "error");
    } finally {
      setPruning(false);
    }
  }, [pruneDays, showToast, loadSessions, loadStats]);

  const pendingSession = sessionDelete.pendingId
    ? sessions.find((s) => s.id === sessionDelete.pendingId)
    : null;

  // Build snippet map from search results (session_id → snippet)
  const snippetMap = new Map<string, string>();
  if (searchResults) {
    for (const r of searchResults) {
      snippetMap.set(r.session_id, r.snippet);
    }
  }

  // When searching, filter sessions to those with FTS matches;
  // when not searching, show all sessions (N2 — the current-page
  // filter quirk is deliberately preserved, no server round trip).
  const filtered = searchResults
    ? sessions.filter((s) => snippetMap.has(s.id))
    : sessions;

  const isSearching = Boolean(search.trim());
  const showPagination = !searchResults && total > PAGE_SIZE;
  // "active now" = live rows in the freshest overview fetch (S1.1) —
  // `stats.active_store` is store-active, a different signal.
  const activeNow = overviewSessions.filter((s) => s.is_active).length;

  if (loading) {
    // S9: layout-shaped skeletons — summary strip, toolbar, ledger.
    return (
      <div
        aria-busy="true"
        className="flex min-w-0 w-full max-w-full flex-col gap-4"
      >
        <Skeleton variant="line" />
        <Skeleton variant="block" className="h-10" />
        <Skeleton variant="row-list" rows={6} />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 w-full max-w-full flex-col gap-4">
      <PluginSlot name="sessions:top" />
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={sessionDelete.isOpen}
        onCancel={sessionDelete.cancel}
        onConfirm={sessionDelete.confirm}
        title={t.sessions.confirmDeleteTitle}
        description={
          pendingSession?.title && pendingSession.title !== "Untitled"
            ? `"${pendingSession.title}" — ${t.sessions.confirmDeleteMessage}`
            : t.sessions.confirmDeleteMessage
        }
        loading={sessionDelete.isDeleting}
      />

      <DeleteConfirmDialog
        open={deleteEmptyOpen}
        onCancel={() => setDeleteEmptyOpen(false)}
        onConfirm={handleDeleteEmpty}
        title={t.sessions.deleteEmptyConfirmTitle}
        description={t.sessions.deleteEmptyConfirmMessage.replace(
          "{count}",
          String(emptyCount),
        )}
        loading={deletingEmpty}
      />

      <DeleteConfirmDialog
        open={deleteSelectedOpen}
        onCancel={() => setDeleteSelectedOpen(false)}
        onConfirm={handleDeleteSelected}
        title={t.sessions.deleteSelectedConfirmTitle.replace(
          "{count}",
          String(selectedIds.size),
        )}
        description={t.sessions.deleteSelectedConfirmMessage.replace(
          "{count}",
          String(selectedIds.size),
        )}
        loading={deletingSelected}
      />

      <Dialog
        open={pruneOpen}
        onOpenChange={(open) => {
          if (!pruning) setPruneOpen(open);
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Prune old sessions</DialogTitle>
            <DialogDescription>
              Permanently remove archived sessions whose last activity is older
              than the given number of days. Active sessions are never pruned.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="prune-days"
              className="text-xs font-medium text-muted-foreground"
            >
              Older than (days)
            </label>
            <Input
              id="prune-days"
              type="number"
              min={0}
              value={pruneDays}
              onChange={(e) => setPruneDays(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handlePrune();
              }}
              disabled={pruning}
            />
          </div>
          <DialogFooter>
            <Button
              outlined
              onClick={() => setPruneOpen(false)}
              disabled={pruning}
            >
              {t.common.cancel}
            </Button>
            <Button
              destructive
              onClick={() => void handlePrune()}
              disabled={pruning}
              className="gap-1.5"
            >
              {pruning && <Spinner className="text-sm" />}
              Prune
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {stats && <SessionsSummaryStrip stats={stats} activeNow={activeNow} />}

      {status && <GatewayStrip status={status} />}

      {activeAction && (
        <div className="border border-border bg-background-base/50">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
              {actionStatus?.running ? (
                <Spinner className="shrink-0 text-[0.875rem] text-warning" />
              ) : actionStatus?.exit_code === 0 ? (
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />
              ) : actionStatus !== null ? (
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" />
              ) : (
                <Spinner className="shrink-0 text-[0.875rem] text-muted-foreground" />
              )}

              <span className="text-xs font-mondwest tracking-[0.12em] truncate">
                {activeAction === "restart"
                  ? t.status.restartGateway
                  : t.status.updateFabric}
              </span>

              <Badge
                tone={
                  actionStatus?.running
                    ? "warning"
                    : actionStatus?.exit_code === 0
                      ? "success"
                      : actionStatus
                        ? "destructive"
                        : "outline"
                }
                className="text-xs shrink-0"
              >
                {actionStatus?.running
                  ? t.status.running
                  : actionStatus?.exit_code === 0
                    ? t.status.actionFinished
                    : actionStatus
                      ? `${t.status.actionFailed} (${actionStatus.exit_code ?? "?"})`
                      : t.common.loading}
              </Badge>
            </div>

            <Button
              ghost
              size="icon"
              onClick={dismissLog}
              className="shrink-0 text-text-secondary hover:text-foreground"
              aria-label={t.common.close}
            >
              <X />
            </Button>
          </div>

          <pre
            ref={logScrollRef}
            className="max-h-72 overflow-auto px-3 py-2 font-mono-ui text-xs leading-relaxed whitespace-pre-wrap break-all"
          >
            {actionStatus?.lines && actionStatus.lines.length > 0
              ? actionStatus.lines.join("\n")
              : t.status.waitingForOutput}
          </pre>
        </div>
      )}

      <PageToolbar
        label={L?.toolbarLabel ?? "Session filters"}
        filters={
          <>
            <div className="relative min-w-0 w-full sm:w-auto sm:min-w-[12rem] sm:max-w-md sm:flex-1">
              {searching ? (
                <Spinner className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[0.875rem] text-primary" />
              ) : (
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              )}
              <Input
                placeholder={t.sessions.searchPlaceholder}
                value={search}
                onChange={(e) => updateSearch(e.target.value)}
                className="h-8 py-0 pr-7 pl-8 text-xs leading-none"
              />
              {search && (
                <Button
                  ghost
                  size="xs"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  onClick={() => updateSearch("")}
                  aria-label={t.common.clear}
                >
                  <X />
                </Button>
              )}
            </div>

            <FilterGroup
              label={L?.sourceFilterLabel ?? "source"}
              className="flex min-w-0 w-full flex-col items-start gap-1.5 sm:w-auto sm:max-w-full sm:flex-row sm:items-center"
            >
              <Segmented
                className="w-fit max-w-full flex-wrap justify-start self-start"
                size="sm"
                value={sourceFilter}
                onChange={updateSourceFilter}
                options={SOURCE_FILTERS.map((src) => ({
                  value: src,
                  label: src === "all" ? (L?.allSources ?? "all") : src,
                }))}
              />
            </FilterGroup>
          </>
        }
        actions={
          <>
            {emptyCount > 0 && !isSearching && (
              <Button
                outlined
                destructive
                size="sm"
                className="shrink-0"
                onClick={() => setDeleteEmptyOpen(true)}
                aria-label={t.sessions.deleteEmpty}
                title={t.sessions.deleteEmpty}
                prefix={<Eraser />}
              >
                <span className="font-mondwest normal-case text-xs">
                  {t.sessions.deleteEmpty} ({emptyCount})
                </span>
              </Button>
            )}

            {showPagination && (
              <SessionsPagination
                compact
                className="shrink-0"
                page={page}
                total={total}
                onPageChange={goToPage}
              />
            )}
          </>
        }
      />

      {listError && (
        <div className="flex flex-wrap items-center gap-3 border border-destructive/30 bg-destructive/[0.06] px-3 py-2">
          <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
          <span className="min-w-0 flex-1 text-sm text-destructive">
            {L?.loadFailed ?? "Failed to load sessions"}
          </span>
          <Button
            outlined
            size="sm"
            className="shrink-0"
            onClick={() => loadSessions(page)}
          >
            {t.common.retry}
          </Button>
        </div>
      )}

      {selectedIds.size > 0 && (
        <div
          className="flex flex-wrap items-center gap-2 border border-primary/30 bg-primary/[0.06] px-3 py-2"
          role="region"
          aria-label={t.sessions.selectedCount.replace(
            "{count}",
            String(selectedIds.size),
          )}
        >
          <span className="font-mondwest normal-case text-xs text-primary tabular-nums">
            {t.sessions.selectedCount.replace(
              "{count}",
              String(selectedIds.size),
            )}
          </span>
          {filtered.some((s) => !selectedIds.has(s.id)) && (
            <Button
              ghost
              size="sm"
              onClick={() => selectAllOnPage(filtered)}
              aria-label={t.sessions.selectAllOnPage}
              title={t.sessions.selectAllOnPage}
            >
              <span className="font-mondwest normal-case text-xs">
                {t.sessions.selectAllOnPage}
              </span>
            </Button>
          )}
          <Button
            ghost
            size="sm"
            onClick={clearSelection}
            aria-label={t.sessions.clearSelection}
            title={t.sessions.clearSelection}
          >
            <span className="font-mondwest normal-case text-xs">
              {t.sessions.clearSelection}
            </span>
          </Button>
          <Button
            outlined
            destructive
            size="sm"
            className="ml-auto"
            onClick={() => setDeleteSelectedOpen(true)}
            aria-label={t.sessions.deleteSelected.replace(
              "{count}",
              String(selectedIds.size),
            )}
            title={t.sessions.deleteSelected.replace(
              "{count}",
              String(selectedIds.size),
            )}
            prefix={<Trash2 />}
          >
            <span className="font-mondwest normal-case text-xs">
              {t.sessions.deleteSelected.replace(
                "{count}",
                String(selectedIds.size),
              )}
            </span>
          </Button>
        </div>
      )}

      {filtered.length === 0 ? (
        isSearching ? (
          <EmptyState
            icon={Clock}
            title={t.sessions.noMatch}
            action={
              <Button outlined size="sm" onClick={() => updateSearch("")}>
                {L?.clearSearch ?? "Clear search"}
              </Button>
            }
          />
        ) : sourceFilter !== "all" ? (
          <EmptyState
            icon={Clock}
            title={L?.noSourceTitle ?? "No sessions from this source"}
            description={(
              L?.noSourceDescription ?? "No sessions with source “{source}”."
            ).replace("{source}", sourceFilter)}
            action={
              <Button
                outlined
                size="sm"
                onClick={() => updateSourceFilter("all")}
              >
                {L?.clearFilter ?? "Clear filter"}
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={Clock}
            title={t.sessions.noSessions}
            description={t.sessions.startConversation}
            action={
              <Button outlined size="sm" onClick={() => navigate("/workspace/chat")}>
                {L?.openChat ?? "Open chat"}
              </Button>
            }
          />
        )
      ) : (
        <>
          <div className="flex min-w-0 flex-col gap-1.5">
            {filtered.map((s, index) => (
              <SessionRunRow
                key={s.id}
                session={s}
                snippet={snippetMap.get(s.id)}
                searchQuery={search || undefined}
                isExpanded={expandedId === s.id}
                isSelected={selectedIds.has(s.id)}
                onToggle={() =>
                  setExpandedId((prev) => (prev === s.id ? null : s.id))
                }
                onSelectClick={(event) =>
                  handleSelectClick(event, index, filtered)
                }
                onDelete={() => sessionDelete.requestDelete(s.id)}
                onRename={handleRename}
                onExport={handleExport}
              />
            ))}
          </div>

          {showPagination && (
            <SessionsPagination
              page={page}
              total={total}
              onPageChange={goToPage}
            />
          )}
        </>
      )}

      <PluginSlot name="sessions:bottom" />
    </div>
  );
}

interface SessionsPaginationProps {
  className?: string;
  compact?: boolean;
  onPageChange: (page: number) => void;
  page: number;
  total: number;
}
