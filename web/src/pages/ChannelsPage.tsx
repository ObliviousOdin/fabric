import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Radio, RotateCw, WifiOff } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { EmptyState, Skeleton } from "@/components/ui";
import { RestartBanner } from "@/components/RestartBanner";
import { ChannelConfigModal } from "@/components/channels/ChannelConfigModal";
import { ChannelRow } from "@/components/channels/ChannelRow";
import { TelegramOnboardingPanel } from "@/components/channels/TelegramOnboardingPanel";
import { WhatsAppOnboardingPanel } from "@/components/channels/WhatsAppOnboardingPanel";
import { useGatewayRestart } from "@/hooks/useGatewayRestart";
import { api } from "@/lib/api";
import { publicCliCommand } from "@/lib/public-identity";
import type { MessagingPlatform } from "@/lib/api";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";

/**
 * CHANNELS — "what the agent listens on" (spec H1–H6): platform roster on
 * `CapabilityRow` with the CN1 two-axis state (config chip vs runtime
 * `AgentStatusBadge`, never merged), sessions-by-source usage evidence
 * (H6), and the shared CN3 gateway-restart lifecycle (`useGatewayRestart`
 * + `RestartBanner`) replacing the page's fire-and-forget restart and the
 * onboarding panels' hand-rolled watchers. QR onboarding and the env
 * config modal are frozen flows (H3/H4, N23) that moved to
 * `components/channels/`.
 */
export default function ChannelsPage() {
  const [platforms, setPlatforms] = useState<MessagingPlatform[]>([]);
  const [envPath, setEnvPath] = useState("~/.fabric/.env");
  const [gatewayStartCommand, setGatewayStartCommand] = useState(
    "fabric gateway start",
  );
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  // H6 usage evidence — supplementary data: a failed stats fetch degrades
  // silently to no meta segment, never breaks the roster (H5/A11 rule).
  const [sessionsBySource, setSessionsBySource] = useState<Record<string, number>>({});
  const { t } = useI18n();
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  // Config modal + per-row busy tracking
  const [editing, setEditing] = useState<MessagingPlatform | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const gatewayRunning = platforms.length > 0 && platforms[0].gateway_running;

  const load = useCallback(() => {
    return api
      .getMessagingPlatforms()
      .then((res) => {
        setPlatforms(res.platforms);
        setEnvPath(res.env_path || "~/.fabric/.env");
        setGatewayStartCommand(
          publicCliCommand(res.gateway_start_command, "fabric gateway start"),
        );
        setLoadError(null);
      })
      .catch((e) => {
        setLoadError(String(e));
        showToast(`Error: ${e}`, "error");
      });
  }, [showToast]);

  // One gateway-restart lifecycle (CN3): the hook owns restartNeeded /
  // restarting / message / error and — unlike the previous page-local
  // handleRestart, which never checked whether the spawned restart
  // actually succeeded — watches the `gateway-restart` action outcome.
  const restartControls = useGatewayRestart({ reload: load, showToast });
  // The hook's callbacks are referentially stable; destructuring keeps the
  // header effect's dependency list honest.
  const { restart, restartNeeded, restarting, restartMessage } = restartControls;

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  useEffect(() => {
    // H6: one cheap already-bound fetch; join client-side on platform.id.
    api
      .getSessionStats()
      .then((stats) => setSessionsBySource(stats.by_source ?? {}))
      .catch(() => {});
  }, []);

  const handleToggle = async (platform: MessagingPlatform) => {
    const next = !platform.enabled;
    setTogglingId(platform.id);
    try {
      await api.updateMessagingPlatform(platform.id, { enabled: next });
      // Optimistic overlay lives in component state only (R26): every
      // reload takes server truth wholesale.
      setPlatforms((prev) =>
        prev.map((p) =>
          p.id === platform.id
            ? { ...p, enabled: next, state: next ? "pending_restart" : "disabled" }
            : p,
        ),
      );
      restartControls.markRestartNeeded();
    } catch (e) {
      showToast(`Error: ${e}`, "error");
    } finally {
      setTogglingId(null);
    }
  };

  const handleTest = async (platform: MessagingPlatform) => {
    setTestingId(platform.id);
    try {
      const res = await api.testMessagingPlatform(platform.id);
      showToast(`${platform.name}: ${res.message}`, res.ok ? "success" : "error");
    } catch (e) {
      showToast(`Error: ${e}`, "error");
    } finally {
      setTestingId(null);
    }
  };

  useLayoutEffect(() => {
    setEnd(
      <Button
        className="uppercase"
        size="sm"
        onClick={() => void restart()}
        disabled={restarting}
        prefix={restarting ? <Spinner /> : <RotateCw className="h-4 w-4" />}
      >
        {restarting ? "Restarting…" : "Restart gateway"}
      </Button>,
    );
    return () => setEnd(null);
  }, [setEnd, restart, restarting]);

  const configured = useMemo(
    () => platforms.filter((p) => p.configured).length,
    [platforms],
  );

  if (loading) {
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        <Skeleton className="h-4 w-80" />
        <div className="grid gap-3">
          <Skeleton variant="block" className="h-28" />
          <Skeleton variant="block" className="h-28" />
          <Skeleton variant="block" className="h-28" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      {/* Restart banner (CN3) */}
      <RestartBanner controls={restartControls} />

      {!gatewayRunning && !restartNeeded && !restartMessage && (
        <Card className="border-border">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
            <WifiOff className="h-4 w-4 shrink-0" />
            <span>
              The gateway is not running. Configure channels here, then start the
              gateway with <code className="font-courier">{gatewayStartCommand}</code>{" "}
              (or the Restart button above).
            </span>
          </CardContent>
        </Card>
      )}

      {loadError && (
        <div className="flex flex-col gap-3 border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive sm:flex-row sm:items-center sm:justify-between">
          <span>{t.channels?.loadFailed ?? "Failed to load channels."}</span>
          <Button
            size="sm"
            outlined
            className="uppercase shrink-0"
            onClick={() => void load()}
          >
            {t.common.retry}
          </Button>
        </div>
      )}

      {platforms.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {configured} of {platforms.length} channels configured. Credentials are
          written to <code className="font-courier">{envPath}</code>; the
          gateway connects each enabled channel on its next restart.
        </p>
      )}

      {/* Config modal (H3, frozen flow) */}
      {editing && (
        <ChannelConfigModal
          platform={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            restartControls.markRestartNeeded();
            await load();
          }}
          showToast={showToast}
        />
      )}

      {/* Platform roster (H2) */}
      <div className="grid gap-3">
        {platforms.length === 0 && !loadError && (
          <Card>
            <CardContent className="p-0">
              <EmptyState
                icon={Radio}
                title={t.channels?.noChannelsTitle ?? "No channels available"}
                description={
                  t.channels?.noChannelsDescription ??
                  "The gateway reported no messaging platforms. Refresh once it has finished starting, or check the logs."
                }
                action={
                  <Button
                    size="sm"
                    outlined
                    className="uppercase"
                    onClick={() => void load()}
                  >
                    {t.common.refresh}
                  </Button>
                }
              />
            </CardContent>
          </Card>
        )}
        {platforms.map((platform) => (
          <ChannelRow
            key={platform.id}
            platform={platform}
            sessionsCount={sessionsBySource[platform.id]}
            toggling={togglingId === platform.id}
            testing={testingId === platform.id}
            onToggle={() => void handleToggle(platform)}
            onTest={() => void handleTest(platform)}
            onConfigure={() => setEditing(platform)}
            onboarding={
              platform.id === "telegram" ? (
                <TelegramOnboardingPanel
                  platform={platform}
                  onChanged={load}
                  restart={restartControls}
                  showToast={showToast}
                />
              ) : platform.id === "whatsapp" ? (
                <WhatsAppOnboardingPanel
                  platform={platform}
                  onChanged={load}
                  restart={restartControls}
                  showToast={showToast}
                />
              ) : undefined
            }
          />
        ))}
      </div>
    </div>
  );
}
