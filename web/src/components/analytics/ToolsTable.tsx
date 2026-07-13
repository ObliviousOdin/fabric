import { Wrench } from "lucide-react";
import type { AnalyticsToolEntry } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { DataTable } from "@/components/ui";
import type { DataTableColumn } from "@/components/ui";
import { useI18n } from "@/i18n";

const MAX_ROWS = 15;

/**
 * Busiest tools (Observe spec A7): per-tool call counts served by
 * `/api/analytics/usage` — the purest "agent workload" signal the backend
 * has. Mirrors the SkillTable card idiom. Top 15 with a muted `+N more`
 * footer; the header icon's `title` carries the accuracy footnote (R14 —
 * counts are a best-effort merge, never billing-grade).
 */
export function ToolsTable({ tools }: { tools: AnalyticsToolEntry[] }) {
  const { t } = useI18n();
  const W = t.analytics.workload;

  if (tools.length === 0) return null;

  const columns: DataTableColumn<AnalyticsToolEntry>[] = [
    {
      key: "tool_name",
      header: W?.tool ?? "Tool",
      sortable: true,
      mono: true,
    },
    {
      key: "count",
      header: W?.calls ?? "Calls",
      sortable: true,
      align: "right",
      mono: true,
    },
  ];

  const shown = tools.slice(0, MAX_ROWS);
  const overflow = tools.length - shown.length;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Wrench
            className="h-5 w-5 text-muted-foreground"
            aria-hidden="true"
            // R14 disclosure: InsightsEngine merges two extraction paths and
            // takes max() on overlap — an activity signal, not billing.
          />
          <CardTitle
            className="text-base"
            title={
              W?.toolCountsNote ??
              "Best-effort counts merged from two extraction paths — an activity signal, not billing-grade"
            }
          >
            {W?.busiestTools ?? "Busiest Tools"}
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          rows={shown}
          rowKey={(row) => row.tool_name}
          defaultSortKey="count"
        />
        {overflow > 0 && (
          <p className="mt-2 font-mono-ui text-xs tabular-nums text-text-tertiary">
            {(W?.moreTools ?? "+{count} more").replace(
              "{count}",
              String(overflow),
            )}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
