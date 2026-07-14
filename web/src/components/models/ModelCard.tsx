import { DollarSign, Star, Zap } from "lucide-react";
import type {
  AuxiliaryTaskAssignment,
  ModelsAnalyticsModelEntry,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatCost, formatTokenCount, formatTokens } from "@/lib/format";
import { Badge } from "@nous-research/ui/ui/components/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { RelativeTime } from "@/components/ui";
import { useI18n } from "@/i18n";
import { CapabilityBadges } from "./CapabilityChips";
import { TokenBar } from "./TokenBar";
import { UseAsMenu } from "./UseAsMenu";
import { modelVendor, shortModelName } from "./aux-tasks";

/**
 * Per-model analytics card in CAP1 zone order (M6). Deliberately a Card,
 * not a `CapabilityRow` — an analytics card with a stacked token bar and a
 * 3-stat grid is a different density class (CAP3); it stays page-local.
 *
 * - Identity: `#rank` mono · short model name mono (full id in `title`) ·
 *   provenance: provider Badge + ctx/out counts.
 * - State: `main` chip — the one sanctioned primary-accent chip on the
 *   page, since assignment ≈ selection (G11) — and the muted `aux · task`
 *   chip.
 * - Usage evidence (▲ = CAP8-gated): TokenBar, 3-stat grid, cost +
 *   tool-call footer (conditional, R4), `RelativeTime(last_used_at)`.
 * - Actions: `UseAsMenu`, flow unchanged (N16).
 */
export function ModelCard({
  entry,
  rank,
  main,
  aux,
  onAssigned,
  showTokens,
}: {
  entry: ModelsAnalyticsModelEntry;
  rank: number;
  main: { provider: string; model: string } | null;
  aux: AuxiliaryTaskAssignment[];
  onAssigned(): void;
  showTokens: boolean;
}) {
  const { t } = useI18n();
  const provider = entry.provider || modelVendor(entry.model);
  const totalTokens = entry.input_tokens + entry.output_tokens;
  const caps = entry.capabilities;

  const isMain =
    !!main &&
    main.provider === provider &&
    main.model === entry.model;

  // First aux task currently using this model (if any).
  const mainAuxTask =
    aux.find(
      (a) => a.provider === provider && a.model === entry.model,
    )?.task ?? null;

  return (
    <Card
      className={cn("min-w-0 max-w-full", isMain && "ring-1 ring-primary/40")}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-text-tertiary text-xs font-mono">
                #{rank}
              </span>
              <CardTitle
                className="text-sm font-mono-ui truncate"
                title={entry.model}
              >
                {shortModelName(entry.model)}
              </CardTitle>
              {isMain && (
                <span className="inline-flex items-center gap-0.5 bg-primary/15 px-1.5 py-0.5 text-display text-xs font-medium tracking-wider text-primary">
                  <Star className="h-2.5 w-2.5" /> main
                </span>
              )}
              {mainAuxTask && (
                <span className="inline-flex items-center bg-muted px-1.5 py-0.5 text-display text-xs font-medium tracking-wider text-text-secondary">
                  aux · {mainAuxTask}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1">
              {provider && (
                <Badge tone="secondary" className="text-xs">
                  {provider}
                </Badge>
              )}
              {(caps.context_window ?? 0) > 0 && (
                <span className="text-xs text-text-secondary">
                  {formatTokenCount(caps.context_window!)} ctx
                </span>
              )}
              {(caps.max_output_tokens ?? 0) > 0 && (
                <span className="text-xs text-text-secondary">
                  {formatTokenCount(caps.max_output_tokens!)} out
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 shrink-0">
            {showTokens ? (
              <div className="text-right">
                <div className="text-xs font-mono font-semibold tabular-nums">
                  {formatTokens(totalTokens)}
                </div>
                <div className="text-xs text-text-tertiary">
                  {t.models.tokens}
                </div>
              </div>
            ) : (
              entry.sessions > 0 && (
                <div className="text-right">
                  <div className="text-xs font-mono font-semibold tabular-nums">
                    {entry.sessions}
                  </div>
                  <div className="text-xs text-text-tertiary">
                    {t.models.sessions}
                  </div>
                </div>
              )
            )}
            <UseAsMenu
              provider={provider}
              model={entry.model}
              isMain={isMain}
              mainAuxTask={mainAuxTask}
              onAssigned={onAssigned}
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-3">
        {showTokens && (
          <>
            <TokenBar
              input={entry.input_tokens}
              output={entry.output_tokens}
              cacheRead={entry.cache_read_tokens}
              reasoning={entry.reasoning_tokens}
            />

            <div className="grid grid-cols-3 gap-2 text-xs">
              <div className="text-center">
                <div className="font-mono font-semibold tabular-nums">
                  {entry.sessions}
                </div>
                <div className="text-xs text-text-tertiary">
                  {t.models.sessions}
                </div>
              </div>
              <div className="text-center">
                <div className="font-mono font-semibold tabular-nums">
                  {formatTokens(entry.avg_tokens_per_session)}
                </div>
                <div className="text-xs text-text-tertiary">
                  {t.models.avgPerSession}
                </div>
              </div>
              <div className="text-center">
                <div className="font-mono font-semibold tabular-nums">
                  {entry.api_calls > 0 ? formatTokens(entry.api_calls) : "—"}
                </div>
                <div className="text-xs text-text-tertiary">
                  {t.models.apiCalls}
                </div>
              </div>
            </div>
          </>
        )}

        <div className="flex items-center justify-between text-xs text-text-secondary border-t border-border/30 pt-2">
          <div className="flex items-center gap-3">
            {showTokens && entry.estimated_cost > 0 && (
              <span className="flex items-center gap-0.5 tabular-nums">
                <DollarSign className="h-2.5 w-2.5" />
                {formatCost(entry.estimated_cost)}
              </span>
            )}
            {showTokens && entry.tool_calls > 0 && (
              <span className="flex items-center gap-0.5 tabular-nums">
                <Zap className="h-2.5 w-2.5" />
                {entry.tool_calls} {t.models.toolCalls}
              </span>
            )}
          </div>
          {/* CAP5: every rendered timestamp goes through RelativeTime
              (shared 30 s ticker, absolute value in `title`). */}
          {entry.last_used_at > 0 && (
            <RelativeTime value={entry.last_used_at} className="text-xs" />
          )}
        </div>

        <CapabilityBadges capabilities={entry.capabilities} />
      </CardContent>
    </Card>
  );
}
