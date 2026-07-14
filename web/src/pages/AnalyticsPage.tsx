import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  BarChart3,
  Brain,
  ChevronDown,
  Cpu,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AnalyticsResponse,
  AnalyticsDailyEntry,
  AnalyticsModelEntry,
  AnalyticsSkillEntry,
  SessionInfo,
  SessionStoreStats,
} from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { formatTokens } from "@/lib/format";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Stats } from "@nous-research/ui/ui/components/stats";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import {
  DataTable,
  EmptyState,
  PageToolbar,
  Skeleton,
  formatCost,
} from "@/components/ui";
import type { DataTableColumn } from "@/components/ui";
import { RecentRunsCard } from "@/components/analytics/RecentRunsCard";
import { RunsBySourceCard } from "@/components/analytics/RunsBySourceCard";
import { ToolsTable } from "@/components/analytics/ToolsTable";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useI18n } from "@/i18n";
import { PluginSlot } from "@/plugins";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

const CHART_HEIGHT_PX = 160;

/** Honest bound for the recent-runs ledger excerpt (A6). */
const RECENT_RUNS_LIMIT = 20;

/** Mono numeric readout (G12 — `tabular-nums` for every number). */
const VALUE_CN = "font-mono-ui tabular-nums";

function formatDate(day: string): string {
  try {
    const d = new Date(day + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return day;
  }
}

/**
 * Compact expandable variant of the old full-page explainer (A1.2): the
 * one-row notice carries the caveat; the full three-paragraph explanation
 * (verbatim from the previous card — good copy, no longer load-bearing)
 * lives in the `<details>` expansion. This is the only place the
 * token/cost-divergence caveat is stated (R12).
 */
function TokenEstimateNotice() {
  const { t } = useI18n();
  const W = t.analytics.workload;

  return (
    <details className="group border border-warning/30 bg-warning/[0.04] px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs [&::-webkit-details-marker]:hidden">
        <AlertTriangle
          aria-hidden="true"
          className="h-3.5 w-3.5 shrink-0 text-warning"
        />
        <span className="min-w-0 flex-1 text-muted-foreground">
          {W?.estimatesHiddenSummary ??
            "token & cost estimates hidden — local counts diverge from provider billing"}{" "}
          &#183;{" "}
          <Link to="/config" className="underline">
            {W?.configLink ?? "Config"}
          </Link>
        </span>
        <ChevronDown
          aria-hidden="true"
          className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none group-open:rotate-180"
        />
      </summary>
      <div className="mt-3 flex max-w-2xl flex-col gap-3 text-sm text-muted-foreground">
        <p>
          The token, cost, and per-day analytics on this page are a
          local debug estimate. They only count successful main-agent
          responses with a usable <span className="font-mono">usage</span>{" "}
          block, and silently exclude auxiliary calls (context
          compression, title generation, vision, session search, web
          extract, smart approvals, MCP routing, plugin LLM access)
          plus provider-side retries and fallback attempts. Cache
          writes are missing entirely.
        </p>
        <p>
          On models with heavy auxiliary traffic (Kimi K2.6, MiniMax
          M2.7) the local total can be 10x–100x lower than what your
          provider bills. Hiding these numbers is safer than letting
          them look authoritative.
        </p>
        <p>
          Check your provider dashboard (OpenRouter, Anthropic, etc.)
          for actual usage and billing. To re-enable the local debug
          estimate anyway, set{" "}
          <span className="font-mono">
            dashboard.show_token_analytics: true
          </span>{" "}
          in <Link to="/config" className="underline">Config</Link>.
        </p>
      </div>
    </details>
  );
}

function TokenBarChart({ daily }: { daily: AnalyticsDailyEntry[] }) {
  const { t } = useI18n();
  const W = t.analytics.workload;
  if (daily.length === 0) return null;

  const maxTokens = Math.max(
    ...daily.map((d) => d.input_tokens + d.output_tokens),
    1,
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">
            {t.analytics.dailyTokenUsage}
          </CardTitle>
        </div>
        <div className="flex items-center gap-4 font-mondwest normal-case text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <div
              className="h-2.5 w-2.5"
              style={{ backgroundColor: "var(--series-input-token)" }}
            />
            {t.analytics.input}
          </div>
          <div className="flex items-center gap-1.5">
            <div
              className="h-2.5 w-2.5"
              style={{ backgroundColor: "var(--series-output-token)" }}
            />
            {t.analytics.output}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div
          className="flex items-end gap-[2px]"
          style={{ height: CHART_HEIGHT_PX }}
        >
          {daily.map((d) => {
            const total = d.input_tokens + d.output_tokens;
            const inputH = Math.round(
              (d.input_tokens / maxTokens) * CHART_HEIGHT_PX,
            );
            const outputH = Math.round(
              (d.output_tokens / maxTokens) * CHART_HEIGHT_PX,
            );
            const dayLabel = [
              formatDate(d.day),
              `${t.analytics.input}: ${formatTokens(d.input_tokens)}`,
              `${t.analytics.output}: ${formatTokens(d.output_tokens)}`,
              `${t.analytics.total}: ${formatTokens(total)}`,
              `${W?.runs ?? "runs"}: ${d.sessions}`,
            ].join(", ");
            return (
              <div
                key={d.day}
                // Focusable with an accessible day summary so the per-day
                // breakdown is reachable by keyboard, touch (tap focuses),
                // and screen readers — not mouse-hover only.
                tabIndex={0}
                role="img"
                aria-label={dayLabel}
                className="flex-1 min-w-0 group relative flex flex-col justify-end focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
                style={{ height: CHART_HEIGHT_PX }}
              >
                <div
                  aria-hidden="true"
                  className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block group-focus:block z-10 pointer-events-none"
                >
                  <div className="font-mondwest normal-case bg-card border border-border px-2.5 py-1.5 text-xs text-foreground shadow-lg whitespace-nowrap">
                    <div className="font-medium">{formatDate(d.day)}</div>
                    <div>
                      {t.analytics.input}: {formatTokens(d.input_tokens)}
                    </div>
                    <div>
                      {t.analytics.output}: {formatTokens(d.output_tokens)}
                    </div>
                    <div>
                      {t.analytics.total}: {formatTokens(total)}
                    </div>
                    {/* A4: already-fetched per-day fields ride along in the
                        tooltip; cost line only when > 0 (R4/R12). */}
                    <div>
                      {W?.runs ?? "runs"}: {d.sessions}
                    </div>
                    {d.estimated_cost > 0 && (
                      <div>
                        {W?.estCost ?? "est. cost"}:{" "}
                        {formatCost(d.estimated_cost)}
                      </div>
                    )}
                  </div>
                </div>

                <div
                  className="w-full"
                  style={{
                    backgroundColor:
                      "color-mix(in srgb, var(--series-input-token) 70%, transparent)",
                    height: Math.max(inputH, total > 0 ? 1 : 0),
                  }}
                />

                <div
                  className="w-full"
                  style={{
                    backgroundColor:
                      "color-mix(in srgb, var(--series-output-token) 70%, transparent)",
                    height: Math.max(outputH, d.output_tokens > 0 ? 1 : 0),
                  }}
                />
              </div>
            );
          })}
        </div>

        <div className="flex justify-between mt-2 font-mondwest normal-case text-xs text-text-tertiary">
          <span>{daily.length > 0 ? formatDate(daily[0].day) : ""}</span>
          {daily.length > 2 && (
            <span>{formatDate(daily[Math.floor(daily.length / 2)].day)}</span>
          )}
          <span>
            {daily.length > 1 ? formatDate(daily[daily.length - 1].day) : ""}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function DailyTable({ daily }: { daily: AnalyticsDailyEntry[] }) {
  const { t } = useI18n();
  const W = t.analytics.workload;

  if (daily.length === 0) return null;

  const columns: DataTableColumn<AnalyticsDailyEntry>[] = [
    {
      key: "day",
      header: t.analytics.date,
      sortable: true,
      render: (d) => <span className="font-medium">{formatDate(d.day)}</span>,
    },
    {
      key: "sessions",
      header: t.sessions.title,
      sortable: true,
      align: "right",
      mono: true,
      cellClassName: "text-muted-foreground",
    },
    {
      key: "input_tokens",
      header: t.analytics.input,
      sortable: true,
      align: "right",
      mono: true,
      render: (d) => (
        <span style={{ color: "var(--series-input-token)" }}>
          {formatTokens(d.input_tokens)}
        </span>
      ),
    },
    {
      key: "output_tokens",
      header: t.analytics.output,
      sortable: true,
      align: "right",
      mono: true,
      render: (d) => (
        <span style={{ color: "var(--series-output-token)" }}>
          {formatTokens(d.output_tokens)}
        </span>
      ),
    },
    {
      // A4: served-but-unused `estimated_cost`; `—` when 0 (R12).
      key: "estimated_cost",
      header: W?.estCost ?? "Est. Cost",
      sortable: true,
      align: "right",
      mono: true,
      render: (d) =>
        d.estimated_cost > 0 ? formatCost(d.estimated_cost) : "—",
    },
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">
            {t.analytics.dailyBreakdown}
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          rows={daily}
          rowKey={(d) => d.day}
          defaultSortKey="day"
        />
      </CardContent>
    </Card>
  );
}

function ModelTable({ models }: { models: AnalyticsModelEntry[] }) {
  const { t } = useI18n();
  const W = t.analytics.workload;

  if (models.length === 0) return null;

  const columns: DataTableColumn<AnalyticsModelEntry>[] = [
    { key: "model", header: t.analytics.model, sortable: true, mono: true },
    {
      key: "sessions",
      header: t.sessions.title,
      sortable: true,
      align: "right",
      mono: true,
      cellClassName: "text-muted-foreground",
    },
    {
      key: "input_tokens",
      header: t.analytics.tokens,
      sortable: true,
      align: "right",
      mono: true,
      render: (m) => (
        <>
          <span style={{ color: "var(--series-input-token)" }}>
            {formatTokens(m.input_tokens)}
          </span>
          {" / "}
          <span style={{ color: "var(--series-output-token)" }}>
            {formatTokens(m.output_tokens)}
          </span>
        </>
      ),
    },
    {
      // A5: served-but-unused `api_calls`.
      key: "api_calls",
      header: W?.apiCalls ?? "API Calls",
      sortable: true,
      align: "right",
      mono: true,
      cellClassName: "text-muted-foreground",
    },
    {
      // A5: served-but-unused `estimated_cost`; `—` when 0 (R12).
      key: "estimated_cost",
      header: W?.estCost ?? "Est. Cost",
      sortable: true,
      align: "right",
      mono: true,
      render: (m) =>
        m.estimated_cost > 0 ? formatCost(m.estimated_cost) : "—",
    },
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Cpu className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">
            {t.analytics.perModelBreakdown}
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          rows={models}
          rowKey={(m) => m.model}
          defaultSortKey="input_tokens"
        />
      </CardContent>
    </Card>
  );
}

function SkillTable({ skills }: { skills: AnalyticsSkillEntry[] }) {
  const { t } = useI18n();

  if (skills.length === 0) return null;

  const columns: DataTableColumn<AnalyticsSkillEntry>[] = [
    { key: "skill", header: t.analytics.skill, sortable: true, mono: true },
    {
      key: "view_count",
      header: t.analytics.loads,
      sortable: true,
      align: "right",
      mono: true,
      cellClassName: "text-muted-foreground",
    },
    {
      key: "manage_count",
      header: t.analytics.edits,
      sortable: true,
      align: "right",
      mono: true,
      cellClassName: "text-muted-foreground",
    },
    {
      key: "total_count",
      header: t.analytics.total,
      sortable: true,
      align: "right",
      mono: true,
    },
    {
      key: "last_used_at",
      header: t.analytics.lastUsed,
      sortable: true,
      align: "right",
      cellClassName: "text-muted-foreground",
      render: (s) => (s.last_used_at ? timeAgo(s.last_used_at) : "—"),
    },
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">{t.analytics.topSkills}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          rows={skills}
          rowKey={(s) => s.skill}
          defaultSortKey="total_count"
        />
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Supplementary fetches (recent runs + by-source stats). Their errors
  // degrade silently to hidden cards (A11) — a broken supplementary card
  // must never take down the report.
  const [recent, setRecent] = useState<SessionInfo[] | null>(null);
  const [recentFailed, setRecentFailed] = useState(false);
  const [stats, setStats] = useState<SessionStoreStats | null>(null);
  // `dashboard.show_token_analytics` (default off) is now tile-level (A2):
  // it hides only the token/cost surfaces (▲ tiles, TokenBarChart, daily/
  // model tables) because local token counts exclude auxiliary calls and
  // provider retries. Run/skill/tool counts are exact local facts and
  // render regardless.
  const [showTokens, setShowTokens] = useState<boolean | null>(null);
  const { t } = useI18n();
  const navigate = useNavigate();
  const { setAfterTitle, setEnd } = usePageHeader();
  const W = t.analytics.workload;

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        const dash = (cfg?.dashboard ?? {}) as { show_token_analytics?: unknown };
        setShowTokens(dash.show_token_analytics === true);
      })
      .catch(() => setShowTokens(false));
  }, []);

  // Bumping the nonce refetches usage without the effect body itself
  // calling setState (react-hooks/set-state-in-effect stays clean —
  // SkillsPage precedent).
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    // Always fetch (A2): skills/tools/session aggregates come from the same
    // response; the gate only shapes which tiles display.
    let cancelled = false;
    api
      .getAnalytics(days)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days, reloadNonce]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    setReloadNonce((n) => n + 1);
  }, []);

  // One fetch on mount + on refresh; no poll (A6/O7 — Analytics is a
  // report, not a monitor; Sessions owns liveness).
  const loadSupplements = useCallback(() => {
    api
      .getSessions(RECENT_RUNS_LIMIT, 0, undefined, "recent")
      .then((res) => {
        setRecent(res.sessions);
        setRecentFailed(false);
      })
      .catch((err) => {
        console.error("analytics: recent-runs fetch failed", err);
        setRecentFailed(true);
      });
    api
      .getSessionStats()
      .then(setStats)
      .catch((err) => {
        console.error("analytics: session-stats fetch failed", err);
        setStats(null);
      });
  }, []);

  useLayoutEffect(() => {
    // Period selector + refresh both live in afterTitle so the controls
    // sit immediately next to the page title instead of being pinned to
    // the far-right `end` slot. Always rendered (A1.1) — the page always
    // has content now that the gate is tile-level.
    setAfterTitle(
      <PageToolbar
        label={t.analytics.period}
        filters={
          <div className="flex flex-wrap items-center gap-1.5">
            {PERIODS.map((p) => (
              <Button
                key={p.label}
                type="button"
                size="sm"
                outlined={days !== p.days}
                onClick={() => {
                  if (days === p.days) return;
                  // Handler-side loading flip (not effect-side) keeps the
                  // refresh spinner behavior of the old `load()` path.
                  setDays(p.days);
                  setLoading(true);
                  setError(null);
                }}
              >
                {p.label}
              </Button>
            ))}
          </div>
        }
        actions={
          <Button
            type="button"
            ghost
            size="icon"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => {
              reload();
              loadSupplements();
            }}
            disabled={loading}
            aria-label={t.common.refresh}
          >
            {loading ? <Spinner /> : <RefreshCw />}
          </Button>
        }
      />,
    );
    setEnd(null);
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    days,
    loading,
    reload,
    loadSupplements,
    setAfterTitle,
    setEnd,
    t.analytics.period,
    t.common.refresh,
  ]);

  useEffect(() => {
    loadSupplements();
  }, [loadSupplements]);

  // A10: the all-empty state also requires an empty tools list and an
  // empty (resolved) recent-runs fetch.
  const allEmpty =
    data !== null &&
    data.daily.length === 0 &&
    data.by_model.length === 0 &&
    data.skills.top_skills.length === 0 &&
    data.tools.length === 0 &&
    recent !== null &&
    recent.length === 0;

  const toolCallTotal = data
    ? data.tools.reduce((sum, tool) => sum + tool.count, 0)
    : 0;

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="analytics:top" />

      {showTokens === false && <TokenEstimateNotice />}

      {loading && !data && (
        <div className="flex flex-col gap-6" aria-busy="true">
          <div className="grid gap-6 lg:grid-cols-2">
            <Skeleton variant="block" className="h-40" />
            <Skeleton variant="block" className="h-40" />
          </div>
          <Skeleton variant="row-list" rows={6} />
        </div>
      )}

      {error && (
        <Card>
          <CardContent className="py-6">
            <div className="flex flex-col items-center gap-3">
              <p className="text-sm text-destructive text-center">{error}</p>
              <Button type="button" outlined size="sm" onClick={reload}>
                {t.common.retry}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {data && !allEmpty && (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Workload summary strip (A1.3): run/api/skill/tool counts are
                ungated exact local facts; token + cost tiles are ▲gated. */}
            <Card>
              <CardContent className="py-6">
                <Stats
                  items={[
                    {
                      label: W?.runs ?? "runs",
                      value: {
                        key: "runs",
                        node: (
                          <span className={VALUE_CN}>
                            {data.totals.total_sessions} (~
                            {(data.totals.total_sessions / days).toFixed(1)}
                            {t.analytics.perDayAvg})
                          </span>
                        ),
                      },
                    },
                    {
                      label: W?.apiCalls ?? "api calls",
                      value: {
                        key: "api-calls",
                        node: (
                          <span className={VALUE_CN}>
                            {/* SQL SUM over zero rows yields null — fall
                                back to the per-day api_calls (not sessions). */}
                            {data.totals.total_api_calls ??
                              data.daily.reduce(
                                (sum, d) => sum + d.api_calls,
                                0,
                              )}
                          </span>
                        ),
                      },
                    },
                    {
                      label: W?.skillActions ?? "skill actions",
                      value: {
                        key: "skill-actions",
                        node: (
                          <span className={VALUE_CN}>
                            {data.skills.summary.total_skill_actions}
                          </span>
                        ),
                      },
                    },
                    {
                      label: W?.toolCalls ?? "tool calls",
                      value: {
                        key: "tool-calls",
                        node: (
                          <span className={VALUE_CN}>{toolCallTotal}</span>
                        ),
                      },
                    },
                    ...(showTokens
                      ? [
                          {
                            label: W?.tokens ?? "tokens",
                            value: {
                              key: "tokens",
                              node: (
                                <span className={VALUE_CN}>
                                  {formatTokens(
                                    data.totals.total_input +
                                      data.totals.total_output,
                                  )}
                                </span>
                              ),
                            },
                          },
                        ]
                      : []),
                    ...(showTokens && data.totals.total_estimated_cost > 0
                      ? [
                          {
                            label: W?.estCost ?? "est. cost",
                            value: {
                              key: "est-cost",
                              node: (
                                <span className={VALUE_CN}>
                                  {formatCost(
                                    data.totals.total_estimated_cost,
                                  )}
                                </span>
                              ),
                            },
                          },
                        ]
                      : []),
                  ]}
                />
              </CardContent>
            </Card>

            {/* A1.4: chart when the gate is on; the by-source meter takes
                the fold slot when it's off so the fold stays two-up. */}
            {showTokens ? (
              <TokenBarChart daily={data.daily} />
            ) : stats ? (
              <RunsBySourceCard stats={stats} />
            ) : null}
          </div>
        </>
      )}

      {/* A9: the recent-runs ledger resolves independently of the usage
          fetch — it renders (with its own skeleton) even while usage is
          still loading or has errored; a failed supplementary fetch hides
          the card silently (A11). */}
      {!allEmpty && !recentFailed && (
        <RecentRunsCard sessions={recent} limit={RECENT_RUNS_LIMIT} />
      )}

      {data && !allEmpty && (
        <>
          {showTokens && stats && <RunsBySourceCard stats={stats} />}

          {showTokens && <DailyTable daily={data.daily} />}
          {showTokens && <ModelTable models={data.by_model} />}

          {(data.skills.top_skills.length > 0 || data.tools.length > 0) && (
            <div className="grid items-start gap-6 lg:grid-cols-2">
              <SkillTable skills={data.skills.top_skills} />
              <ToolsTable tools={data.tools} />
            </div>
          )}
        </>
      )}

      {allEmpty && (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={BarChart3}
              title={t.analytics.noUsageData}
              description={t.analytics.startSession}
              action={
                <Button
                  type="button"
                  outlined
                  size="sm"
                  onClick={() => navigate("/chat")}
                >
                  {W?.openChat ?? "Open chat"}
                </Button>
              }
            />
          </CardContent>
        </Card>
      )}
      <PluginSlot name="analytics:bottom" />
    </div>
  );
}
