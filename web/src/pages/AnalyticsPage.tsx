import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { BarChart3, Brain, Cpu, RefreshCw, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import type {
  AnalyticsResponse,
  AnalyticsDailyEntry,
  AnalyticsModelEntry,
  AnalyticsSkillEntry,
} from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Stats } from "@nous-research/ui/ui/components/stats";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { DataTable, EmptyState, PageToolbar, Skeleton } from "@/components/ui";
import type { DataTableColumn } from "@/components/ui";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useI18n } from "@/i18n";
import { PluginSlot } from "@/plugins";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

const CHART_HEIGHT_PX = 160;

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatDate(day: string): string {
  try {
    const d = new Date(day + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return day;
  }
}

function TokenBarChart({ daily }: { daily: AnalyticsDailyEntry[] }) {
  const { t } = useI18n();
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
            return (
              <div
                key={d.day}
                className="flex-1 min-w-0 group relative flex flex-col justify-end"
                style={{ height: CHART_HEIGHT_PX }}
              >
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-10 pointer-events-none">
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
  // Gated on `dashboard.show_token_analytics` (default off).  When off the
  // page renders an explanation card instead of fetching analytics — the
  // local token counts exclude auxiliary calls and provider retries, so
  // they diverge from provider billing in ways that mislead users.
  const [showTokens, setShowTokens] = useState<boolean | null>(null);
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        const dash = (cfg?.dashboard ?? {}) as { show_token_analytics?: unknown };
        setShowTokens(dash.show_token_analytics === true);
      })
      .catch(() => setShowTokens(false));
  }, []);

  const load = useCallback(() => {
    if (!showTokens) return;
    setLoading(true);
    setError(null);
    api
      .getAnalytics(days)
      .then(setData)
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [days, showTokens]);

  useLayoutEffect(() => {
    // Period selector + refresh both live in afterTitle so the controls
    // sit immediately next to the page title instead of being pinned to
    // the far-right `end` slot. The active period is conveyed by the
    // filled (non-outlined) button — no redundant period badge.
    setAfterTitle(
      showTokens === false ? null : (
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
                  onClick={() => setDays(p.days)}
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
              onClick={load}
              disabled={loading}
              aria-label={t.common.refresh}
            >
              {loading ? <Spinner /> : <RefreshCw />}
            </Button>
          }
        />
      ),
    );
    setEnd(null);
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    days,
    loading,
    load,
    setAfterTitle,
    setEnd,
    t.analytics.period,
    t.common.refresh,
    showTokens,
  ]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="analytics:top" />

      {showTokens === false && (
        <Card>
          <CardContent className="py-12">
            <div className="mx-auto flex max-w-2xl flex-col gap-3 text-sm text-muted-foreground">
              <h2 className="font-mondwest text-display text-base tracking-wider text-foreground">
                Token analytics hidden
              </h2>
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
                in <a href="/config" className="underline">Config</a>.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {showTokens && loading && !data && (
        <div className="flex flex-col gap-6" aria-busy="true">
          <div className="grid gap-6 lg:grid-cols-2">
            <Skeleton variant="block" className="h-40" />
            <Skeleton variant="block" className="h-40" />
          </div>
          <Skeleton variant="row-list" rows={6} />
        </div>
      )}

      {showTokens && error && (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-destructive text-center">{error}</p>
          </CardContent>
        </Card>
      )}

      {showTokens && data && (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardContent className="py-6">
                <Stats
                  items={[
                    {
                      label: t.analytics.totalTokens,
                      value: formatTokens(
                        data.totals.total_input + data.totals.total_output,
                      ),
                    },
                    {
                      label: t.analytics.input,
                      value: formatTokens(data.totals.total_input),
                    },
                    {
                      label: t.analytics.output,
                      value: formatTokens(data.totals.total_output),
                    },
                    {
                      label: t.analytics.totalSessions,
                      value: `${data.totals.total_sessions} (~${(data.totals.total_sessions / days).toFixed(1)}${t.analytics.perDayAvg})`,
                    },
                    {
                      label: t.analytics.apiCalls,
                      value: String(
                        data.totals.total_api_calls ??
                          data.daily.reduce((sum, d) => sum + d.sessions, 0),
                      ),
                    },
                  ]}
                />
              </CardContent>
            </Card>

            <TokenBarChart daily={data.daily} />
          </div>

          <DailyTable daily={data.daily} />
          <ModelTable models={data.by_model} />
          <SkillTable skills={data.skills.top_skills} />
        </>
      )}

      {data &&
        data.daily.length === 0 &&
        data.by_model.length === 0 &&
        data.skills.top_skills.length === 0 && (
          <Card>
            <CardContent className="p-0">
              <EmptyState
                icon={BarChart3}
                title={t.analytics.noUsageData}
                description={t.analytics.startSession}
              />
            </CardContent>
          </Card>
        )}
      <PluginSlot name="analytics:bottom" />
    </div>
  );
}
