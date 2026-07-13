import { Play } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { AgentStatusBadge, RelativeTime } from "@/components/ui";
import type { DerivedAgentStatus } from "@/components/ui";
import type { CuratorStatus } from "@/lib/api";

/**
 * Y3: a curator *is* a scheduled agent, so the badge mapping follows the
 * cron precedent exactly — `paused → paused`, enabled → `scheduled` with
 * label "active", disabled → `paused` with label "disabled". Page-local
 * two-liner rather than a contorted `cronJobAgentStatus()` call.
 */
function curatorAgentStatus(curator: CuratorStatus | null): DerivedAgentStatus {
  if (curator?.paused) return { status: "paused" };
  if (curator?.enabled) return { status: "scheduled", label: "active" };
  return { status: "paused", label: "disabled" };
}

export interface CuratorCardProps {
  curator: CuratorStatus | null;
  onTogglePaused: () => void;
  onRunNow: () => void;
}

/**
 * Skill-curator card (Y3): shared status vocabulary + mono meta line
 * (`every {n}h` · relative last run / "never run"). Pause/Resume and
 * Run now are frozen behavior.
 */
export function CuratorCard({
  curator,
  onTogglePaused,
  onRunNow,
}: CuratorCardProps) {
  const derived = curatorAgentStatus(curator);
  return (
    <Card>
      <CardContent className="flex items-center justify-between py-4">
        <div className="flex items-center gap-3">
          <AgentStatusBadge status={derived.status} label={derived.label} />
          <span className="font-mono-ui flex flex-wrap items-center gap-x-1.5 text-sm tabular-nums text-muted-foreground">
            {curator?.interval_hours ? (
              <span>every {curator.interval_hours}h</span>
            ) : null}
            {curator?.interval_hours ? <span aria-hidden="true">·</span> : null}
            {curator?.last_run_at ? (
              <span>
                last run <RelativeTime value={curator.last_run_at} />
              </span>
            ) : (
              <span>never run</span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" ghost onClick={onTogglePaused}>
            {curator?.paused ? "Resume" : "Pause"}
          </Button>
          <Button
            size="sm"
            ghost
            prefix={<Play className="h-3.5 w-3.5" />}
            onClick={onRunNow}
          >
            Run now
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
