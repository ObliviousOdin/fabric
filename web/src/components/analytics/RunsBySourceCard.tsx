import { Network } from "lucide-react";
import type { SessionStoreStats } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { useI18n } from "@/i18n";
import { sourceIcon } from "./source-icons";

export interface RunsBySourceCardProps {
  stats: SessionStoreStats;
}

/**
 * Runs-by-source meter (Observe spec A8): one row per source from
 * `GET /api/sessions/stats` `by_source` — monochrome glyph (G11) + name +
 * mono count + a proportional 1px-high bar. A meter, not a chart: no
 * series colors, no axes.
 */
export function RunsBySourceCard({ stats }: RunsBySourceCardProps) {
  const { t } = useI18n();
  const W = t.analytics.workload;

  const rows = Object.entries(stats.by_source).sort((a, b) => b[1] - a[1]);
  if (rows.length === 0) return null;

  const max = Math.max(rows[0][1], 1);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Network className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">
            {W?.runsBySource ?? "Runs by Source"}
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2.5">
          {rows.map(([source, count]) => {
            const Icon = sourceIcon(source);
            return (
              <li key={source} className="flex items-center gap-3">
                <Icon
                  aria-hidden="true"
                  className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                />
                <span className="w-24 shrink-0 truncate text-xs text-muted-foreground">
                  {source}
                </span>
                <span className="min-w-0 flex-1" aria-hidden="true">
                  <span
                    className="block h-px bg-primary/40 transition-[width] motion-reduce:transition-none"
                    style={{ width: `${Math.max((count / max) * 100, 1)}%` }}
                  />
                </span>
                <span className="font-mono-ui text-xs tabular-nums">
                  {count}
                </span>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
