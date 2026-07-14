import type { SessionStoreStats } from "@/lib/api";
import { Badge } from "@/components/fabric/Badge";
import { Stats } from "@nous-research/ui/ui/components/stats";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";

export interface SessionsSummaryStripProps {
  stats: SessionStoreStats;
  /**
   * Count of `is_active` rows in the freshest overview fetch — the "live
   * now" signal. `stats.active_store` is *store*-active and stays its own
   * stat (S1.1).
   */
  activeNow: number;
}

const VALUE_CN = "font-mono-ui tabular-nums";

/**
 * Leading summary strip (S1.1, G8): DS `Stats` items — sessions, active
 * now (success-toned when >0), in store, messages, archived — plus a
 * trailing cluster of per-source outline badges.
 */
export function SessionsSummaryStrip({
  stats,
  activeNow,
}: SessionsSummaryStripProps) {
  const { t } = useI18n();
  const L = t.sessions.ledger;

  return (
    <section
      aria-label={L?.statsLabel ?? "Session store summary"}
      className="border border-border bg-background-base/40 px-4 py-3"
    >
      <Stats
        className="gap-1.5"
        items={[
          {
            label: L?.statsSessions ?? "sessions",
            value: {
              key: "sessions",
              node: <span className={VALUE_CN}>{stats.total}</span>,
            },
          },
          {
            label: L?.statsActiveNow ?? "active now",
            value: {
              key: "active-now",
              node: (
                <span className={cn(VALUE_CN, activeNow > 0 && "text-success")}>
                  {activeNow}
                </span>
              ),
            },
          },
          {
            label: L?.statsInStore ?? "in store",
            value: {
              key: "in-store",
              node: <span className={VALUE_CN}>{stats.active_store}</span>,
            },
          },
          {
            label: L?.statsMessages ?? "messages",
            value: {
              key: "messages",
              node: <span className={VALUE_CN}>{stats.messages}</span>,
            },
          },
          {
            label: L?.statsArchived ?? "archived",
            value: {
              key: "archived",
              node: <span className={VALUE_CN}>{stats.archived}</span>,
            },
          },
        ]}
      />

      {Object.keys(stats.by_source).length > 0 && (
        <div className="mt-3 flex min-w-0 flex-wrap items-center gap-1.5">
          {Object.entries(stats.by_source).map(([src, count]) => (
            <Badge key={src} tone="outline" className="text-xs">
              {src}:{" "}
              <span className="font-mono-ui tabular-nums">{count}</span>
            </Badge>
          ))}
        </div>
      )}
    </section>
  );
}
