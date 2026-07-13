import { AlertTriangle, RotateCw } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import type { GatewayRestartControls } from "@/hooks/useGatewayRestart";
import { useI18n } from "@/i18n";

export interface RestartBannerProps {
  /** The `useGatewayRestart` state + actions this banner renders. */
  controls: Pick<
    GatewayRestartControls,
    "restartNeeded" | "restarting" | "restartMessage" | "restartError" | "restart"
  >;
  /**
   * Copy for the restart-needed state when no `restartError` overrides it.
   * Pages own this sentence (Channels: "Changes are saved…", Webhooks:
   * "Webhooks are enabled, but…").
   */
  neededMessage?: string;
  /** Action label override (default "Restart now"). */
  actionLabel?: string;
}

/**
 * The shared gateway-restart banner (CN3): one warning-tinted 1px box for
 * "saved but not live" + a muted informational box while a watched restart
 * is in flight — replaces the hand-rolled banner Cards on Webhooks and
 * Channels. Renders nothing when there is nothing to say.
 */
export function RestartBanner({
  controls,
  neededMessage,
  actionLabel,
}: RestartBannerProps) {
  const { t } = useI18n();
  const { restartNeeded, restarting, restartMessage, restartError } = controls;

  if (restartNeeded) {
    return (
      <Card className="border-warning/50">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>
              {restartError ??
                neededMessage ??
                t.gatewayRestart?.needed ??
                "Changes are saved. Restart the gateway for them to take effect."}
            </span>
          </div>
          <Button
            size="sm"
            className="uppercase shrink-0"
            onClick={() => void controls.restart()}
            disabled={restarting}
            prefix={restarting ? <Spinner /> : <RotateCw className="h-4 w-4" />}
          >
            {restarting
              ? (t.gatewayRestart?.restarting ?? "Restarting…")
              : (actionLabel ?? t.gatewayRestart?.restartNow ?? "Restart now")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (restartMessage) {
    return (
      <Card className="border-border">
        <CardContent className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
          <RotateCw className="h-4 w-4 shrink-0 text-warning" />
          <span>{restartMessage}</span>
        </CardContent>
      </Card>
    );
  }

  return null;
}
