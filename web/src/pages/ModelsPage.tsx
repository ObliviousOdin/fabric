import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Cpu, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type {
  AuxiliaryModelsResponse,
  ModelsAnalyticsModelEntry,
  ModelsAnalyticsResponse,
} from "@/lib/api";
import { formatCost, formatTokens } from "@/lib/format";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Stats } from "@nous-research/ui/ui/components/stats";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { EmptyState, Skeleton } from "@/components/ui";
import { LoadoutCard } from "@/components/models/LoadoutCard";
import { ModelCard } from "@/components/models/ModelCard";
import { modelVendor } from "@/components/models/aux-tasks";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useI18n } from "@/i18n";
import { PluginSlot } from "@/plugins";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

/**
 * MODELS — "the loadout's brain" (spec M1–M11). Top-to-bottom: plugin
 * slot, assignment surface (`LoadoutCard`, M2 — full-width hero), fleet
 * stats strip (▲ token/cost items gated by CAP8), model usage cards
 * (`ModelCard`, M6), plugin slot. Ordering/keys of the cards are
 * server-sorted and unchanged (M7).
 */
export default function ModelsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<ModelsAnalyticsResponse | null>(null);
  const [aux, setAux] = useState<AuxiliaryModelsResponse | null>(null);
  // M9: the assignment surface skeletons until the first
  // `/api/model/auxiliary` round-trip settles (success or failure).
  const [auxLoaded, setAuxLoaded] = useState(false);
  // M11: aux failures are non-fatal — rows render `(unset)` plus a
  // one-line inline warning instead of silently blank.
  const [auxFailed, setAuxFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveKey, setSaveKey] = useState(0);
  // Gate the token/cost UI on `dashboard.show_token_analytics`.  See
  // fabric_cli/config.py for the rationale: the numbers exclude auxiliary
  // calls and retries, so they're misleading next to provider billing.
  const [showTokens, setShowTokens] = useState(false);
  const { t } = useI18n();
  const L = t.models.loadout;
  const { setAfterTitle, setEnd } = usePageHeader();

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        const dash = (cfg?.dashboard ?? {}) as { show_token_analytics?: unknown };
        setShowTokens(dash.show_token_analytics === true);
      })
      .catch(() => {
        // Default to hidden on any failure — safer than showing wrong numbers.
        setShowTokens(false);
      });
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.getModelsAnalytics(days),
      api
        .getAuxiliaryModels()
        .then((auxData) => {
          setAuxFailed(false);
          return auxData;
        })
        .catch(() => {
          setAuxFailed(true);
          return null;
        }),
    ])
      .then(([models, auxData]) => {
        setData(models);
        setAux(auxData);
      })
      .catch((err) => setError(String(err)))
      .finally(() => {
        setLoading(false);
        setAuxLoaded(true);
      });
  }, [days]);

  const refreshAux = useCallback(() => {
    api
      .getAuxiliaryModels()
      .then((auxData) => {
        setAux(auxData);
        setAuxFailed(false);
      })
      .catch(() => {});
  }, []);

  const onAssigned = useCallback(() => {
    // Reload aux state after any assignment change.
    refreshAux();
    setSaveKey((k) => k + 1);
  }, [refreshAux]);

  useLayoutEffect(() => {
    // Period selector + refresh both live in afterTitle so the controls
    // sit immediately next to the page title instead of being pinned to
    // the far-right `end` slot. The active period is conveyed by the
    // filled (non-outlined) button — no redundant period badge.
    setAfterTitle(
      <div className="flex flex-wrap items-center gap-1.5">
        {PERIODS.map((p) => (
          <Button
            key={p.label}
            type="button"
            size="sm"
            outlined={days !== p.days}
            onClick={() => setDays(p.days)}
            className="uppercase"
          >
            {p.label}
          </Button>
        ))}
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
      </div>,
    );
    setEnd(null);
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [days, loading, load, setAfterTitle, setEnd, t.common.refresh]);

  useEffect(() => {
    load();
  }, [load]);

  // Model assignments can change outside this page (config editor, chat
  // /model --global, CLI), so refetch them when the page regains focus.
  useEffect(() => {
    let last = 0;
    const onFocus = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - last < 1000) return;
      last = Date.now();
      refreshAux();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refreshAux]);

  // M2: capability chips for the main model, resolved from the
  // already-fetched analytics entry match — no new fetch; null (hidden)
  // when no entry matches. Match semantics mirror `ModelCard.isMain`.
  const mainCapabilities: ModelsAnalyticsModelEntry["capabilities"] | null =
    (data &&
      aux?.main.model &&
      data.models.find(
        (m) =>
          (m.provider || modelVendor(m.model)) === aux.main.provider &&
          m.model === aux.main.model,
      )?.capabilities) ||
    null;

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-6">
      <PluginSlot name="models:top" />

      {/* Assignment surface (M1.2/M2) — the page's hero, full width. */}
      {!auxLoaded ? (
        <div aria-busy="true">
          <Skeleton variant="block" className="h-40" />
        </div>
      ) : (
        <LoadoutCard
          aux={aux}
          auxFailed={auxFailed}
          mainCapabilities={mainCapabilities}
          refreshKey={saveKey}
          onSaved={onAssigned}
        />
      )}

      {/* Fleet stats strip (M1.3/M4) — ▲ items per CAP8. */}
      {!data && loading && <Skeleton variant="block" className="h-40" />}

      {data && (
        <Card className="min-w-0 max-w-full overflow-hidden">
          <CardContent className="min-w-0 py-6">
            <div className="min-w-0 max-w-full [&_div.grid]:grid-cols-[auto_minmax(0,1fr)_auto]">
              <Stats
                className="min-w-0"
                items={
                  showTokens
                    ? [
                        {
                          label: t.models.modelsUsed,
                          value: String(data.totals.distinct_models),
                        },
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
                          label: t.models.estimatedCost,
                          value: formatCost(data.totals.total_estimated_cost),
                        },
                        {
                          label: t.analytics.totalSessions,
                          value: String(data.totals.total_sessions),
                        },
                      ]
                    : [
                        {
                          label: t.models.modelsUsed,
                          value: String(data.totals.distinct_models),
                        },
                        {
                          label: t.analytics.totalSessions,
                          value: String(data.totals.total_sessions),
                        },
                      ]
                }
              />
            </div>
            {/* CAP8: compact one-row gate notice (Observe A1.2 pattern) —
                the full divergence explainer lives on Analytics (R12). */}
            {!showTokens && (
              <div
                className="mt-4 flex items-center gap-2 border border-warning/30 bg-warning/[0.04] px-3 py-2 text-xs"
                title="Enable dashboard.show_token_analytics in Config to show the local debug estimate."
              >
                <AlertTriangle
                  aria-hidden="true"
                  className="h-3.5 w-3.5 shrink-0 text-warning"
                />
                <span className="min-w-0 flex-1 text-muted-foreground">
                  {L?.tokensHiddenSummary ??
                    "token & cost estimates hidden — local counts diverge from provider billing"}{" "}
                  &#183;{" "}
                  <Link to="/config" className="underline">
                    {L?.configLink ?? "Config"}
                  </Link>
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {loading && !data && (
        <div
          className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-3"
          aria-busy="true"
        >
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} variant="block" className="h-44" />
          ))}
        </div>
      )}

      {/* M11: shared destructive-tinted 1px banner + Retry. */}
      {error && (
        <div className="flex flex-wrap items-center gap-3 border border-destructive/30 bg-destructive/[0.06] px-3 py-2">
          <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
          <span className="min-w-0 flex-1 text-sm text-destructive">
            {L?.loadFailed ?? "Failed to load model analytics"}
            <span className="ml-2 font-mono text-xs">{error}</span>
          </span>
          <Button outlined size="sm" className="shrink-0" onClick={load}>
            {t.common.retry}
          </Button>
        </div>
      )}

      {data && (
        <>
          {data.models.length > 0 ? (
            <div className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.models.map((m, i) => (
                <ModelCard
                  key={`${m.model}:${m.provider}`}
                  entry={m}
                  rank={i + 1}
                  main={aux?.main ?? null}
                  aux={aux?.tasks ?? []}
                  onAssigned={onAssigned}
                  showTokens={showTokens}
                />
              ))}
            </div>
          ) : (
            <Card>
              <CardContent className="p-0">
                <EmptyState
                  icon={Cpu}
                  title={t.models.noModelsData}
                  description={t.models.startSession}
                  action={
                    <Button
                      size="sm"
                      outlined
                      className="uppercase"
                      onClick={load}
                    >
                      {t.common.refresh}
                    </Button>
                  }
                />
              </CardContent>
            </Card>
          )}
        </>
      )}

      <PluginSlot name="models:bottom" />
    </div>
  );
}
