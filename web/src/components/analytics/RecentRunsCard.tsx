import { Fragment } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, ArrowUpRight } from "lucide-react";
import type { SessionInfo } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { EmptyState, RunRow, Skeleton, sessionAgentStatus } from "@/components/ui";
import { useI18n } from "@/i18n";
import { formatCompact, formatCost, sourceIcon } from "./source-icons";

export interface RecentRunsCardProps {
  /** `null` while the sessions fetch is in flight (A9 — own skeleton). */
  sessions: SessionInfo[] | null;
  /** Honest bound shown in the header qualifier (A6 — "last N"). */
  limit: number;
}

const SEPARATOR = (
  <span aria-hidden="true" className="text-border">
    &#183;
  </span>
);

/**
 * The fleet ledger excerpt (Observe spec A6): last-N sessions rendered on
 * the shared `RunRow` primitive — third consumer after the Sessions ledger
 * and the Cron run-history drawer. No poll (Analytics is a report, not a
 * monitor; Sessions owns liveness), no checkbox, no expansion; the single
 * action navigates to the Sessions page.
 */
export function RecentRunsCard({ sessions, limit }: RecentRunsCardProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const W = t.analytics.workload;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">
            {W?.recentRuns ?? "Recent Runs"}
          </CardTitle>
          <span className="font-mono-ui text-xs tabular-nums text-text-tertiary">
            {W?.lastRunsQualifier ?? `last ${limit}`}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {sessions === null ? (
          <Skeleton variant="row-list" rows={4} />
        ) : sessions.length === 0 ? (
          <EmptyState
            icon={Activity}
            title={W?.noRunsYet ?? "No runs yet"}
            description={W?.noRunsHint ?? "Runs appear here once an agent has done work"}
            className="py-8"
          />
        ) : (
          <div className="flex flex-col gap-2">
            {sessions.map((session) => {
              const hasTitle = session.title && session.title !== "Untitled";
              // Meta counters mirror the Sessions ledger (S2): mono,
              // `·`-separated, zero-valued segments omitted (R4). Cost is
              // ungated here on purpose — the same run already shows its
              // `$est` on the Sessions page (A6).
              const metaParts: ReactNode[] = [
                <span key="msgs" className="font-mono-ui tabular-nums shrink-0">
                  {session.message_count} {t.common.msgs}
                </span>,
              ];
              if (session.tool_call_count > 0) {
                metaParts.push(
                  <span
                    key="tools"
                    className="font-mono-ui tabular-nums shrink-0"
                  >
                    {session.tool_call_count} {t.common.tools}
                  </span>,
                );
              }
              if (session.input_tokens > 0 || session.output_tokens > 0) {
                metaParts.push(
                  <span
                    key="tokens"
                    className="font-mono-ui tabular-nums shrink-0"
                  >
                    &#8593;{formatCompact(session.input_tokens)} &#8595;
                    {formatCompact(session.output_tokens)}
                  </span>,
                );
              }
              if (
                session.estimated_cost_usd != null &&
                session.estimated_cost_usd > 0
              ) {
                metaParts.push(
                  <span
                    key="cost"
                    className="font-mono-ui tabular-nums shrink-0"
                  >
                    {formatCost(session.estimated_cost_usd)}
                  </span>,
                );
              }

              return (
                <RunRow
                  key={session.id}
                  title={
                    <span
                      className={
                        hasTitle
                          ? "font-medium"
                          : "text-muted-foreground italic"
                      }
                    >
                      {hasTitle
                        ? session.title
                        : session.preview
                          ? session.preview.slice(0, 60)
                          : t.sessions.untitledSession}
                    </span>
                  }
                  status={sessionAgentStatus(session)}
                  id={session.id}
                  sourceIcon={sourceIcon(session.source)}
                  model={(session.model ?? t.common.unknown).split("/").pop()}
                  meta={metaParts.map((node, i) => (
                    <Fragment key={i}>
                      {i > 0 && SEPARATOR}
                      {node}
                    </Fragment>
                  ))}
                  timestamp={session.last_active}
                  actions={
                    <Button
                      ghost
                      size="icon"
                      className="text-muted-foreground hover:text-foreground"
                      aria-label={W?.openInSessions ?? "Open in Sessions"}
                      title={W?.openInSessions ?? "Open in Sessions"}
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate("/sessions");
                      }}
                    >
                      <ArrowUpRight />
                    </Button>
                  }
                />
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
