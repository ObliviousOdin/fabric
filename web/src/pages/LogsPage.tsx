import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { ArrowDown, FileText, RefreshCw, X } from "lucide-react";
import { api } from "@/lib/api";
import {
  findAnchorIndex,
  parseLogLines,
  type LineClassification,
} from "@/lib/log-lines";
import { cn } from "@/lib/utils";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { FilterGroup, Segmented } from "@nous-research/ui/ui/components/segmented";
import { Input } from "@nous-research/ui/ui/components/input";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import {
  AgentStatusBadge,
  EmptyState,
  MonoId,
  PageToolbar,
  Skeleton,
} from "@/components/ui";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";

// All six server-side LOG_FILES keys (spec L6) — `gui`/`desktop`/`mcp` were
// served but never exposed.
const FILES = ["agent", "errors", "gateway", "gui", "desktop", "mcp"] as const;
const LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"] as const;
const COMPONENTS = [
  "all",
  "gateway",
  "agent",
  "tools",
  "cli",
  "cron",
  "gui",
] as const;
const LINE_COUNTS = [50, 100, 200, 500] as const;

const POLL_INTERVAL_MS = 2000;
/**
 * Backoff while a search/session filter is active (spec L8/R10): each such
 * request makes the server scan a 2000-line raw window — a monitoring tab
 * must not do that every 2 s. Load-bearing; do not "simplify" back to 2 s.
 */
const SEARCH_POLL_INTERVAL_MS = 5000;
/** Same debounce constant as the Sessions page search (spec L9). */
const SEARCH_DEBOUNCE_MS = 300;
/** Within this many px of the bottom still counts as "at the bottom". */
const FOLLOW_THRESHOLD_PX = 32;
/** Live-stream default persists across visits (spec §2.1). */
const AUTO_REFRESH_STORAGE_KEY = "fabric.logs.autoRefresh";

/**
 * Raw subprocess/Electron output outside the log grammar — no logger names,
 * so any component prefix filter would blank the stream server-side
 * (`_line_matches_component` returns False for unparseable lines, spec L7).
 */
const UNSTRUCTURED_FILES: ReadonlySet<string> = new Set(["mcp", "desktop"]);

const LINE_COLORS: Record<LineClassification, string> = {
  error: "text-destructive",
  warning: "text-warning",
  info: "text-foreground",
  debug: "text-text-tertiary",
};

/** Min-level radio rank, mirroring the server's `_LEVEL_ORDER` ≥ semantics. */
const LEVEL_RANK: Record<(typeof LEVELS)[number], number> = {
  ALL: -1,
  DEBUG: 0,
  INFO: 1,
  WARNING: 2,
  ERROR: 3,
};

const formatFilterLabel = (value: string) => value.toUpperCase();

const toSegmentOptions = <T extends string>(values: readonly T[]) =>
  values.map((v) => ({ value: v, label: formatFilterLabel(v) }));

const filterGroupClass =
  "flex min-w-0 w-full flex-col items-start gap-1.5 sm:w-auto sm:max-w-full sm:flex-row sm:items-center";

const segmentedClass =
  "w-fit max-w-full flex-wrap justify-start self-start";

interface WindowCounts {
  error: number;
  warning: number;
  info: number;
  debug: number;
}

/**
 * Level facet chips (spec L5) — replaces the level Segmented but keeps its
 * **min-level radio semantics** (the server filter is `>=`; we don't fake
 * exact-match multi-select). Counts are window-scoped exact classifications
 * of currently rendered lines; chips below the active threshold render
 * muted without counts (their lines aren't in the window — showing 0 would
 * lie). Page-local on purpose: single consumer.
 */
function LevelChips({
  value,
  onChange,
  counts,
  total,
  inViewHint,
  groupLabel,
}: {
  value: (typeof LEVELS)[number];
  onChange: (level: (typeof LEVELS)[number]) => void;
  counts: WindowCounts;
  total: number;
  inViewHint: string;
  /** Accessible name for the radiogroup (the FilterGroup label is visual only). */
  groupLabel: string;
}) {
  const chipCount: Record<(typeof LEVELS)[number], number> = {
    ALL: total,
    DEBUG: counts.debug,
    INFO: counts.info,
    // ERROR folds in CRITICAL via the parser's classification (spec L5).
    WARNING: counts.warning,
    ERROR: counts.error,
  };
  return (
    <div
      role="radiogroup"
      aria-label={groupLabel}
      className="flex w-fit max-w-full flex-wrap gap-1 self-start"
    >
      {LEVELS.map((chip) => {
        const active = chip === value;
        const belowThreshold =
          value !== "ALL" && chip !== "ALL" && LEVEL_RANK[chip] < LEVEL_RANK[value];
        return (
          <button
            key={chip}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(chip)}
            title={inViewHint}
            className={cn(
              "flex items-center gap-1.5 border px-2 py-1 text-[11px] uppercase tracking-[0.08em] transition-colors",
              active
                ? "border-primary/40 bg-primary/[0.06] text-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
              belowThreshold && "text-text-tertiary",
            )}
          >
            {chip}
            {!belowThreshold && (
              <span
                className={cn(
                  "font-mono-ui text-[10px] tabular-nums",
                  // Severity tints the count only, never the chip surface.
                  chip === "ERROR"
                    ? "text-destructive"
                    : chip === "WARNING"
                      ? "text-warning"
                      : "text-text-tertiary",
                )}
              >
                {chipCount[chip]}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Pause-pin divider (spec L11): display-only element *between* line divs —
 * never part of the copyable stream text (N12).
 */
function PinDivider({ label }: { label: string }) {
  return (
    <div
      aria-hidden="true"
      className="my-1 flex select-none items-center gap-2 font-sans"
    >
      <span className="min-w-4 flex-1 border-t border-warning/40" />
      <span className="whitespace-nowrap text-[10px] uppercase tracking-[0.12em] text-warning">
        — {label} —
      </span>
      <span className="min-w-4 flex-1 border-t border-warning/40" />
    </div>
  );
}

export default function LogsPage() {
  const [file, setFile] = useState<(typeof FILES)[number]>("agent");
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("ALL");
  const [component, setComponent] =
    useState<(typeof COMPONENTS)[number]>("all");
  const [lineCount, setLineCount] = useState<(typeof LINE_COUNTS)[number]>(100);
  // Live by default (spec §2.1): a monitoring page that starts frozen
  // delivers zero signal. Sticky per browser via localStorage.
  const [autoRefresh, setAutoRefresh] = useState(() => {
    try {
      return localStorage.getItem(AUTO_REFRESH_STORAGE_KEY) !== "false";
    } catch {
      return true;
    }
  });
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Search / session filter (spec L9): one server `search` slot shared by
  // the free-text input and session-tag clicks — last action wins; the
  // MonoId chip form shows whenever the term came from a tag click.
  const [searchDraft, setSearchDraft] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [sessionFilter, setSessionFilter] = useState<string | null>(null);
  // Follow mode: pinned to the tail while the user is at the bottom;
  // disengaged the moment they scroll up to read history. State drives the
  // "jump to latest" chip; the ref lets the pin effect read the current
  // value without re-subscribing.
  const [follow, setFollow] = useState(true);
  const followRef = useRef(true);
  // Pause pin (spec L11): the last ≤3 raw lines at the moment follow
  // disengaged — an overlap key for diffing fresh windows into a `+N` delta.
  const [pauseAnchor, setPauseAnchor] = useState<string[] | null>(null);
  const linesRef = useRef<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  // Force component=all for unstructured files (spec L7) — a prefix filter
  // would blank the stream server-side. The FilterGroup hides too.
  const componentHidden = UNSTRUCTURED_FILES.has(file);
  const effectiveComponent = componentHidden ? "all" : component;
  const activeSearch = sessionFilter ?? (appliedSearch.trim() || null);

  useEffect(() => {
    try {
      localStorage.setItem(AUTO_REFRESH_STORAGE_KEY, String(autoRefresh));
    } catch {
      // Storage unavailable (private mode) — the toggle still works for
      // this visit.
    }
  }, [autoRefresh]);

  // Debounce free-text search into the applied term (spec L9).
  useEffect(() => {
    const handle = setTimeout(
      () => setAppliedSearch(searchDraft),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(handle);
  }, [searchDraft]);

  const setFollowing = useCallback((next: boolean) => {
    followRef.current = next;
    setFollow(next);
    if (next) {
      // Re-engaging follow (jump click, scroll to bottom, filter change)
      // always clears the pin (spec L11).
      setPauseAnchor(null);
    } else {
      const tail = linesRef.current.slice(-3);
      setPauseAnchor(tail.length > 0 ? tail : null);
    }
  }, []);

  const fetchLogs = useCallback(
    (opts?: { background?: boolean }) => {
      // Background (poll) fetches skip the loading flag so the refresh
      // button doesn't strobe every couple of seconds.
      if (!opts?.background) setLoading(true);
      setError(null);
      api
        .getLogs({
          file,
          lines: lineCount,
          level,
          component: effectiveComponent,
          search: activeSearch ?? undefined,
        })
        .then((resp) => {
          linesRef.current = resp.lines;
          setLines(resp.lines);
        })
        .catch((err) => setError(String(err)))
        .finally(() => {
          if (!opts?.background) setLoading(false);
        });
    },
    [file, lineCount, level, effectiveComponent, activeSearch],
  );

  const applySessionFilter = useCallback((id: string) => {
    setSearchDraft("");
    setAppliedSearch("");
    setSessionFilter(id);
  }, []);

  const clearSearch = useCallback(() => {
    setSearchDraft("");
    setAppliedSearch("");
    setSessionFilter(null);
  }, []);

  const parsed = useMemo(() => parseLogLines(lines), [lines]);

  // Window-scoped facet counts (spec L5/L5b). Unleveled continuation lines
  // count under their inherited/heuristic classification (R9) so the four
  // buckets always sum to the visible line count.
  const counts = useMemo<WindowCounts>(() => {
    const c: WindowCounts = { error: 0, warning: 0, info: 0, debug: 0 };
    for (const p of parsed) c[p.classification] += 1;
    return c;
  }, [parsed]);

  // Pause-pin placement + resume delta (spec L11). `afterIndex === -1`
  // means the anchor scrolled out of the fetched window — degrade honestly
  // to a top-of-stream divider and a `+{lines}+` label.
  const pin = useMemo(() => {
    if (follow || !pauseAnchor || lines.length === 0) return null;
    const idx = findAnchorIndex(lines, pauseAnchor);
    if (idx === -1) return { afterIndex: -1, delta: null as number | null };
    return { afterIndex: idx, delta: lines.length - 1 - idx };
  }, [follow, pauseAnchor, lines]);

  const inViewHint = (
    t.logs.inViewHint ?? "of the last {n} fetched lines"
  ).replace("{n}", String(lines.length));

  useLayoutEffect(() => {
    setAfterTitle(
      <span className="flex items-center gap-1.5">
        <Badge tone="secondary" className="text-xs">
          {formatFilterLabel(file)} · {formatFilterLabel(level)} ·{" "}
          {formatFilterLabel(effectiveComponent)}
          {activeSearch ? ` · "${activeSearch}"` : ""}
        </Badge>
        <Button
          type="button"
          ghost
          size="icon"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => fetchLogs()}
          disabled={loading}
          aria-label={t.common.refresh}
        >
          {loading ? <Spinner /> : <RefreshCw />}
        </Button>
      </span>,
    );
    // Live control (spec L4): one AgentStatusBadge toggle. `idle` when the
    // stream is off — not the warning-toned `paused` status, which is cron
    // lifecycle vocabulary (O2/G1).
    setEnd(
      <div className="flex w-full min-w-0 flex-wrap items-center justify-start gap-2 sm:justify-end sm:gap-3">
        <button
          type="button"
          aria-pressed={autoRefresh}
          aria-label={t.logs.autoRefresh}
          onClick={() => setAutoRefresh((v) => !v)}
          className="cursor-pointer"
        >
          {autoRefresh ? (
            <AgentStatusBadge
              status="live"
              pulse={follow}
              label={
                follow
                  ? (t.logs.streaming ?? "streaming")
                  : (t.logs.streamingScrolled ?? "streaming (scrolled)")
              }
            />
          ) : (
            <AgentStatusBadge
              status="idle"
              label={t.logs.streamPaused ?? "paused"}
            />
          )}
        </button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    autoRefresh,
    activeSearch,
    effectiveComponent,
    file,
    follow,
    level,
    loading,
    setAfterTitle,
    setEnd,
    t,
    fetchLogs,
  ]);

  useEffect(() => {
    // Filter change (or mount): re-engage follow so the view pins to the
    // tail of the newly selected slice (this also resets the pause pin).
    setFollowing(true);
    fetchLogs();
  }, [fetchLogs, setFollowing]);

  useEffect(() => {
    if (!autoRefresh) return;
    const tick = () => {
      // Poll only while the tab is visible — a hidden dashboard shouldn't
      // hit the gateway every 2s. The visibilitychange listener does an
      // immediate catch-up fetch when the tab comes back.
      if (document.visibilityState !== "visible") return;
      fetchLogs({ background: true });
    };
    const interval = setInterval(
      tick,
      activeSearch ? SEARCH_POLL_INTERVAL_MS : POLL_INTERVAL_MS,
    );
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [autoRefresh, activeSearch, fetchLogs]);

  // Keep the view pinned to the newest lines while follow is engaged.
  useLayoutEffect(() => {
    if (!followRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_THRESHOLD_PX;
    if (atBottom !== followRef.current) setFollowing(atBottom);
  }, [setFollowing]);

  const jumpToLatest = useCallback(() => {
    setFollowing(true);
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [setFollowing]);

  const renderLine = (raw: string, i: number): ReactNode => {
    const p = parsed[i];
    let content: ReactNode = raw;
    // Session tag → click-to-filter (spec L3/L9). The span contains exactly
    // the original `[…]` characters, so selection/copy stays byte-identical
    // to the file.
    if (p?.sessionId) {
      const tag = `[${p.sessionId}]`;
      const at = raw.indexOf(tag);
      if (at !== -1) {
        const sessionId = p.sessionId;
        content = (
          <>
            {raw.slice(0, at)}
            <span
              role="button"
              tabIndex={0}
              title={t.logs.filterSession ?? "Filter this session"}
              className="cursor-pointer underline decoration-dotted underline-offset-2 hover:text-foreground"
              onClick={() => applySessionFilter(sessionId)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  applySessionFilter(sessionId);
                }
              }}
            >
              {tag}
            </span>
            {raw.slice(at + tag.length)}
          </>
        );
      }
    }
    return (
      <div
        className={cn(
          LINE_COLORS[p?.classification ?? "info"],
          "hover:bg-secondary/20 px-1 -mx-1",
          // Soft indent for continuation lines — padding, not inserted
          // characters, so copy fidelity is preserved (N12).
          p?.isContinuation && "pl-4",
        )}
      >
        {content}
      </div>
    );
  };

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-4">
      <PluginSlot name="logs:top" />
      <PageToolbar
        label={t.logs.title}
        filters={
          <>
            <FilterGroup label={t.logs.file} className={filterGroupClass}>
              <Segmented
                className={segmentedClass}
                value={file}
                onChange={setFile}
                options={toSegmentOptions(FILES)}
              />
            </FilterGroup>

            <FilterGroup label={t.logs.level} className={filterGroupClass}>
              <LevelChips
                value={level}
                onChange={setLevel}
                counts={counts}
                total={lines.length}
                inViewHint={inViewHint}
                groupLabel={t.logs.level}
              />
            </FilterGroup>

            {!componentHidden && (
              <FilterGroup
                label={t.logs.component}
                className={filterGroupClass}
              >
                <Segmented
                  className={segmentedClass}
                  value={component}
                  onChange={setComponent}
                  options={toSegmentOptions(COMPONENTS)}
                />
              </FilterGroup>
            )}

            <FilterGroup label={t.logs.lines} className={filterGroupClass}>
              <Segmented
                className={segmentedClass}
                value={String(lineCount)}
                onChange={(v) =>
                  setLineCount(Number(v) as (typeof LINE_COUNTS)[number])
                }
                options={LINE_COUNTS.map((n) => ({
                  value: String(n),
                  label: String(n),
                }))}
              />
            </FilterGroup>
          </>
        }
        actions={
          <FilterGroup label={t.common.search} className={filterGroupClass}>
            {sessionFilter ? (
              <span className="flex h-8 items-center gap-1.5 border border-border bg-secondary/30 px-2">
                <MonoId id={sessionFilter} copy={false} />
                <button
                  type="button"
                  aria-label={t.logs.clearSearch ?? "Clear search"}
                  onClick={clearSearch}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
              </span>
            ) : (
              <Input
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
                placeholder={t.logs.searchPlaceholder ?? "search lines…"}
                aria-label={t.common.search}
                className="h-8 w-full min-w-0 font-mono-ui text-xs sm:w-56"
              />
            )}
          </FilterGroup>
        }
      />

      <Card className="min-w-0 max-w-full overflow-hidden">
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-sm flex items-center gap-2">
            <FileText className="h-4 w-4" />
            <span className="font-mono-ui normal-case">{file}.log</span>
            {lines.length > 0 && (
              // In-view tally (spec L5b): glanceable "is anything on fire"
              // readout; window-scoped, never presented as file totals (L10).
              <span
                className="ml-auto font-mono-ui text-[11px] font-normal normal-case tracking-normal tabular-nums text-muted-foreground"
                title={inViewHint}
              >
                {lines.length} {t.logs.lines.toLowerCase()}
                {counts.error > 0 && (
                  <span className="text-destructive">
                    {" "}
                    · {counts.error} {t.logs.errAbbrev ?? "err"}
                  </span>
                )}
                {counts.warning > 0 && (
                  <span className="text-warning">
                    {" "}
                    · {counts.warning} {t.logs.warnAbbrev ?? "warn"}
                  </span>
                )}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="relative p-0">
          {error && (
            <div className="bg-destructive/10 border-b border-destructive/20 flex flex-wrap items-center justify-between gap-2 p-3">
              <p className="text-sm text-destructive">{error}</p>
              <Button type="button" outlined size="sm" onClick={() => fetchLogs()}>
                {t.common.retry}
              </Button>
            </div>
          )}

          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="max-w-full min-h-[400px] max-h-[calc(100vh-220px)] overflow-auto p-4 font-mono-ui text-xs leading-5 break-words"
          >
            {loading && lines.length === 0 && (
              <Skeleton variant="row-list" rows={12} />
            )}
            {lines.length === 0 && !loading && !error && (
              <EmptyState
                icon={FileText}
                // Reset to the themed sans stack: the scroller's font-mono-ui
                // would otherwise leak into the empty-state copy, which is
                // prose, not a technical readout.
                className="font-sans"
                title={t.logs.noLogLines}
                description={
                  activeSearch
                    ? (
                        t.logs.noMatchesFor ?? 'No lines match "{term}".'
                      ).replace("{term}", activeSearch)
                    : (t.logs.noLinesHint ??
                      "Try another file, level, or component filter.")
                }
                action={
                  activeSearch ? (
                    <Button type="button" outlined size="sm" onClick={clearSearch}>
                      {t.logs.clearSearch ?? "Clear search"}
                    </Button>
                  ) : undefined
                }
              />
            )}
            {pin?.afterIndex === -1 && (
              <PinDivider
                label={
                  t.logs.earlierScrolledOut ?? "earlier lines scrolled out"
                }
              />
            )}
            {lines.map((line, i) => (
              // Index keys: lines are a sliding window without identity (B9).
              <Fragment key={i}>
                {renderLine(line, i)}
                {pin !== null && pin.afterIndex === i && (
                  <PinDivider label={t.logs.pausedHere ?? "paused here"} />
                )}
              </Fragment>
            ))}
          </div>

          {!follow && lines.length > 0 && (
            <button
              type="button"
              onClick={jumpToLatest}
              className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 border border-border bg-card px-3 py-1.5 text-xs uppercase tracking-[0.12em] text-muted-foreground hover:text-foreground"
            >
              <ArrowDown className="h-3 w-3" aria-hidden="true" />
              {t.logs.jumpToLatest ?? "Jump to latest"}
              {pin !== null && (pin.delta === null || pin.delta > 0) && (
                <span className="font-mono-ui normal-case tracking-normal tabular-nums">
                  · {pin.delta === null ? `+${lineCount}+` : `+${pin.delta}`}
                </span>
              )}
            </button>
          )}
        </CardContent>
      </Card>
      <PluginSlot name="logs:bottom" />
    </div>
  );
}
