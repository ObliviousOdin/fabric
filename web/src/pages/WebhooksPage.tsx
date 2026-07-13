import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { Plus, Webhook } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { api } from "@/lib/api";
import type { WebhookRoute, WebhooksResponse } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { EmptyState, Skeleton } from "@/components/ui";
import { RestartBanner } from "@/components/RestartBanner";
import { WebhookCreateModal } from "@/components/webhooks/WebhookCreateModal";
import { WebhookRow } from "@/components/webhooks/WebhookRow";
import { useGatewayRestart } from "@/hooks/useGatewayRestart";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";

/**
 * WEBHOOKS — "HTTP events in" (spec W1–W4): receiver gate card →
 * `RestartBanner` (the shared CN3 lifecycle replaces the page's three
 * hand-rolled banner Cards and its `watchRestartOutcome` copy) →
 * subscription roster on `CapabilityRow` (W2) → create modal with the
 * frozen secret-shown-once panel (W3, CN9). No delivery evidence is
 * rendered because none is served (§3.1 — `created_at` is the only
 * temporal fact; telemetry is B24).
 */
export default function WebhooksPage() {
  const [data, setData] = useState<WebhooksResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [togglingName, setTogglingName] = useState<string | null>(null);
  const { t } = useI18n();
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  const enabled = data?.enabled ?? false;
  const subscriptions = data?.subscriptions ?? [];

  const loadWebhooks = useCallback(() => {
    return api
      .getWebhooks()
      .then((res) => {
        setData(res);
        setLoadError(false);
      })
      .catch(() => {
        setLoadError(true);
        showToast("Failed to load webhooks", "error");
      })
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => {
    loadWebhooks();
  }, [loadWebhooks]);

  // One gateway-restart lifecycle (CN3): restartNeeded / restarting /
  // message / error state plus the exact shipped outcome watch — the
  // page-local `watchRestartOutcome` copy is gone.
  const restartControls = useGatewayRestart({ reload: loadWebhooks, showToast });

  const handleEnableWebhooks = useCallback(async () => {
    setEnabling(true);
    restartControls.clearRestartNeeded();
    try {
      const result = await api.enableWebhooks();
      await loadWebhooks();
      if (result.restart_started) {
        showToast("Webhooks enabled; gateway restarting…", "success");
        restartControls.noteRestartStarted("Webhooks enabled; gateway restarting…");
      } else {
        const detail = result.restart_error ? `: ${result.restart_error}` : ".";
        restartControls.markRestartNeeded(`Gateway restart failed${detail}`);
        showToast(`Webhooks enabled; gateway restart failed${detail}`, "error");
      }
    } catch (e) {
      showToast(`Failed to enable webhooks: ${e}`, "error");
    } finally {
      setEnabling(false);
    }
  }, [loadWebhooks, restartControls, showToast]);

  const handleToggleEnabled = useCallback(
    async (subName: string, nextEnabled: boolean) => {
      setTogglingName(subName);
      try {
        await api.setWebhookEnabled(subName, nextEnabled);
        showToast(
          nextEnabled ? `Enabled: "${subName}"` : `Disabled: "${subName}"`,
          "success",
        );
        loadWebhooks();
      } catch (e) {
        showToast(`Error: ${e}`, "error");
      } finally {
        setTogglingName(null);
      }
    },
    [loadWebhooks, showToast],
  );

  const webhookDelete = useConfirmDelete({
    onDelete: useCallback(
      async (name: string) => {
        try {
          await api.deleteWebhook(name);
          showToast(`Deleted: "${name}"`, "success");
          loadWebhooks();
        } catch (e) {
          showToast(`Error: ${e}`, "error");
          throw e;
        }
      },
      [loadWebhooks, showToast],
    ),
  });

  // Put "New subscription" button in page header
  useLayoutEffect(() => {
    setEnd(
      <Button
        className="uppercase"
        size="sm"
        disabled={!enabled || enabling}
        prefix={<Plus />}
        onClick={() => setCreateModalOpen(true)}
      >
        New subscription
      </Button>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, enabled, enabling, loading]);

  if (loading) {
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        <Skeleton variant="block" className="h-24" />
        <Skeleton variant="row-list" rows={4} />
      </div>
    );
  }

  const pendingName = webhookDelete.pendingId ?? "";

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={webhookDelete.isOpen}
        onCancel={webhookDelete.cancel}
        onConfirm={webhookDelete.confirm}
        title="Delete webhook"
        description={
          pendingName
            ? `"${pendingName}" — this will permanently remove this webhook subscription.`
            : "This will permanently remove this webhook subscription."
        }
        loading={webhookDelete.isDeleting}
      />

      {/* Create subscription modal (W3, frozen flow) */}
      <WebhookCreateModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        onCreated={() => void loadWebhooks()}
        showToast={showToast}
      />

      {loadError && (
        <div className="flex flex-col gap-3 border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive sm:flex-row sm:items-center sm:justify-between">
          <span>{t.webhooks?.loadFailed ?? "Failed to load webhooks."}</span>
          <Button
            size="sm"
            outlined
            className="uppercase shrink-0"
            onClick={() => void loadWebhooks()}
          >
            {t.common.retry}
          </Button>
        </div>
      )}

      {!loadError && (
        <>
          {/* Receiver gate card (W1, copy kept verbatim) */}
          {!enabled && (
            <Card className="border-warning/50">
              <CardContent className="flex flex-col gap-4 py-6 text-sm sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3">
                  <Webhook className="h-5 w-5 shrink-0 text-warning" />
                  <div className="flex flex-col gap-1">
                    <span className="font-medium">Webhook receiver disabled</span>
                    <span className="text-muted-foreground">
                      Webhooks are their own gateway platform. Enable them here to
                      accept incoming HTTP events; chat channels are only needed
                      when a subscription delivers to Telegram, Discord, Slack, or
                      another channel.
                    </span>
                  </div>
                </div>
                <Button
                  size="sm"
                  className="uppercase shrink-0"
                  onClick={handleEnableWebhooks}
                  disabled={enabling}
                  prefix={enabling ? <Spinner /> : <Webhook className="h-4 w-4" />}
                >
                  {enabling ? "Enabling…" : "Enable webhooks"}
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Restart banner states (CN3) */}
          <RestartBanner
            controls={restartControls}
            neededMessage="Webhooks are enabled, but the gateway still needs a restart before the receiver can come online."
            actionLabel="Restart gateway"
          />

          <div className="flex flex-col gap-3">
            <H2
              variant="sm"
              className="flex items-center gap-2 text-muted-foreground"
            >
              <Webhook className="h-4 w-4" />
              Subscriptions ({subscriptions.length})
            </H2>

            {/* The hot-reload asymmetry is real and load-bearing (CN8). */}
            <p className="text-xs text-muted-foreground -mt-1">
              Subscription changes hot-reload once the webhook receiver is running.
              Disabled subscriptions reject incoming events.
            </p>

            {subscriptions.length === 0 && (
              <Card>
                <CardContent className="p-0">
                  <EmptyState
                    icon={Webhook}
                    title={
                      t.webhooks?.noSubscriptionsTitle ??
                      "No webhook subscriptions yet"
                    }
                    description={
                      t.webhooks?.noSubscriptionsDescription ??
                      "Create one with “New subscription” — each gets its own URL and signing secret."
                    }
                    action={
                      <Button
                        size="sm"
                        outlined
                        className="uppercase"
                        disabled={!enabled || enabling}
                        prefix={<Plus />}
                        onClick={() => setCreateModalOpen(true)}
                      >
                        New subscription
                      </Button>
                    }
                  />
                </CardContent>
              </Card>
            )}

            {subscriptions.map((sub: WebhookRoute) => (
              <WebhookRow
                key={sub.name}
                sub={sub}
                toggling={togglingName === sub.name}
                onToggle={(next) => void handleToggleEnabled(sub.name, next)}
                onDelete={() => webhookDelete.requestDelete(sub.name)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
