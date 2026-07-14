import { AlertTriangle } from "lucide-react";
import type { StatusResponse } from "@/lib/api";
import { AgentStatusBadge, channelRuntimeStatus } from "@/components/ui";
import { themedChrome } from "@/lib/utils";
import { useI18n } from "@/i18n";

export interface GatewayStripProps {
  status: StatusResponse;
}

/**
 * Conditional gateway strip (S1.2): failures (gateway `startup_failed`,
 * platform `fatal`/`disconnected`) as a destructive-tinted 1px box;
 * healthy platforms as a one-line row of name + status chips (replaces
 * the old `PlatformsCard`). Renders nothing when there is nothing to say.
 */
export function GatewayStrip({ status }: GatewayStripProps) {
  const { t } = useI18n();
  const L = t.sessions.ledger;

  const platformEntries = Object.entries(status.gateway_platforms ?? {});

  const alerts: { message: string; detail?: string }[] = [];
  if (status.gateway_state === "startup_failed") {
    alerts.push({
      message: t.status.gatewayFailedToStart,
      detail: status.gateway_exit_reason ?? undefined,
    });
  }
  const failedEntries = platformEntries.filter(
    ([, info]) => info.state === "fatal" || info.state === "disconnected",
  );
  for (const [name, info] of failedEntries) {
    const stateLabel =
      info.state === "fatal"
        ? t.status.platformError
        : t.status.platformDisconnected;
    alerts.push({
      message: `${name.charAt(0).toUpperCase() + name.slice(1)} ${stateLabel}`,
      detail: info.error_message ?? undefined,
    });
  }

  const healthyEntries = platformEntries.filter(
    ([, info]) => info.state !== "fatal" && info.state !== "disconnected",
  );

  if (alerts.length === 0 && healthyEntries.length === 0) return null;

  return (
    <>
      {alerts.length > 0 && (
        <div className="border border-destructive/30 bg-destructive/[0.06] p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="flex flex-col gap-2 min-w-0">
              {alerts.map((alert, i) => (
                <div key={i}>
                  <p className="text-sm font-medium text-destructive">
                    {alert.message}
                  </p>
                  {alert.detail && (
                    <p className="text-xs text-destructive mt-0.5">
                      {alert.detail}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {healthyEntries.length > 0 && (
        <div
          role="group"
          aria-label={t.status.connectedPlatforms}
          className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5 border border-border px-3 py-2"
        >
          <span
            className={`${themedChrome} text-xs text-muted-foreground`}
          >
            {L?.gatewayLabel ?? "gateway"}
          </span>
          {healthyEntries.map(([name, info]) => {
            // Healthy-chip vocabulary comes from the shared CN2 runtime
            // mapper so a channel wears the same words here and on the
            // Channels page. The `disabled` branch is kept as dead-code
            // insurance: `/api/status` only relays gateway-persisted
            // runtime states, so it is unreachable from this payload (R24).
            const derived =
              info.state === "disabled"
                ? null
                : channelRuntimeStatus(info.state);
            return (
              <span key={name} className="flex shrink-0 items-center gap-1.5">
                <span className="font-mono-ui text-xs">{name}</span>
                {derived ? (
                  <AgentStatusBadge status={derived.status} label={derived.label} />
                ) : info.state === "disabled" ? (
                  <AgentStatusBadge status="paused" label={t.common.disabled} />
                ) : (
                  <AgentStatusBadge status="idle" label={info.state} />
                )}
              </span>
            );
          })}
        </div>
      )}
    </>
  );
}
