import { Play, Power, RotateCw } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { AgentStatusBadge, gatewayAgentStatus } from "@/components/ui";
import type { StatusResponse } from "@/lib/api";

export type GatewayVerb = "start" | "stop" | "restart";

export interface GatewayCardProps {
  status: StatusResponse | null;
  onVerb: (verb: GatewayVerb) => void;
}

/**
 * Gateway card (Y2): the process state adopts the shared agent-status
 * vocabulary via `gatewayAgentStatus` (draining/degraded ride the
 * warning-toned `paused` with truthful labels). The meta line stays mono:
 * raw `gateway_state` · `pid {n}`. Start/Restart/Stop are frozen behavior
 * (disabled gating on `gateway_running`, `gateway-*` action names).
 */
export function GatewayCard({ status, onVerb }: GatewayCardProps) {
  const gatewayRunning = status?.gateway_running;
  const derived = gatewayAgentStatus(
    status?.gateway_state ?? null,
    !!gatewayRunning,
  );

  return (
    <Card>
      <CardContent className="flex flex-col items-stretch gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <AgentStatusBadge status={derived.status} label={derived.label} />
          <span className="font-mono-ui text-sm tabular-nums text-muted-foreground">
            {status?.gateway_state ?? "—"}
            {status?.gateway_pid ? ` · pid ${status.gateway_pid}` : ""}
          </span>
        </div>
        <div className="grid w-full grid-cols-3 gap-2 sm:flex sm:w-auto sm:items-center">
          <Button
            size="sm"
            className="uppercase"
            onClick={() => onVerb("start")}
            disabled={gatewayRunning}
            prefix={<Play className="h-3.5 w-3.5" />}
          >
            Start
          </Button>
          <Button
            size="sm"
            className="uppercase"
            onClick={() => onVerb("restart")}
            prefix={<RotateCw className="h-3.5 w-3.5" />}
          >
            Restart
          </Button>
          <Button
            size="sm"
            className="uppercase text-warning"
            ghost
            onClick={() => onVerb("stop")}
            disabled={!gatewayRunning}
            prefix={<Power className="h-3.5 w-3.5" />}
          >
            Stop
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
