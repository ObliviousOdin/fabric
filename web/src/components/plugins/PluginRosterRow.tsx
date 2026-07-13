import { useState } from "react";
import { Eye, EyeOff, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import type { Translations } from "@/i18n/types";
import { api } from "@/lib/api";
import type { HubAgentPluginRow } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { CommandBlock } from "@nous-research/ui/ui/components/command-block";
import { ConfirmDialog } from "@nous-research/ui/ui/components/confirm-dialog";
import {
  CAPABILITY_STATE_TONES,
  CapabilityRow,
  pluginCapabilityState,
} from "@/components/ui";
import { cn } from "@/lib/utils";

export interface PluginRosterRowProps {
  row: HubAgentPluginRow;
  /** A mutation for this row is in flight — body dims, actions disable. */
  busy: boolean;
  /** P4 roster flash: highlight the just-installed row. */
  flash?: boolean;
  /** The page's per-row mutation runner (busy set + hub reload + error toast). */
  runAction: (name: string, fn: () => Promise<unknown>) => Promise<void>;
  showToast: (msg: string, variant: "success" | "error") => void;
  t: Translations;
}

/**
 * Plugin roster row (spec P2) — `CapabilityRow` consumer #3. Identity is
 * the mono plugin id; state comes from the shared CAP2 mapper (fixing the
 * old disabled-as-destructive tone bug — disabled is a choice, not a
 * failure) with `auth_required` as a separate warning `needs auth` chip
 * (needs setup, not broken). No usage meta — no plugin telemetry exists
 * (CAP1.4 honesty, B19). All action flows are frozen (N18).
 */
export function PluginRosterRow({
  row,
  busy,
  flash,
  runAction,
  showToast,
  t,
}: PluginRosterRowProps) {
  const [confirmRemove, setConfirmRemove] = useState(false);

  const dm = row.dashboard_manifest;
  const tabPath = dm?.tab && !dm.tab.hidden ? dm.tab.override ?? dm.tab.path : null;
  const state = pluginCapabilityState(row);
  // R16: enabled ≠ running — plugin toggles apply when the agent reloads
  // its plugins, so the state badge carries the "takes effect…" copy.
  const effectNote =
    t.pluginsPage.agents?.stateEffectNote ?? "Takes effect when the agent next loads plugins";

  const hasDetail = Boolean(
    dm?.slots?.length || row.auth_required || (!row.has_dashboard_manifest && !dm),
  );

  return (
    <>
      <CapabilityRow
        name={row.name}
        dimmed={busy}
        className={cn(
          flash && "bg-primary/5 ring-1 ring-primary/40",
        )}
        badges={
          <>
            <Badge tone={CAPABILITY_STATE_TONES[state.state]} title={effectNote}>
              {state.label}
            </Badge>
            <Badge className="font-mono-ui tabular-nums" tone="outline">
              {row.version ? `v${row.version}` : "—"}
            </Badge>
            <Badge tone="outline">
              {t.pluginsPage.sourceBadge}: {row.source}
            </Badge>
            {row.auth_required ? (
              <Badge tone={CAPABILITY_STATE_TONES["needs-setup"]}>
                {t.pluginsPage.agents?.needsAuth ?? "needs auth"}
              </Badge>
            ) : null}
          </>
        }
        description={row.description ? row.description : undefined}
        detail={
          hasDetail ? (
            <div className="flex flex-col gap-2 pt-1">
              {dm?.slots?.length ? (
                <p className="font-mono-ui text-xs tracking-[0.05em] text-text-tertiary">
                  {t.pluginsPage.dashboardSlots}: {dm.slots.join(", ")}
                </p>
              ) : null}

              {row.auth_required ? (
                <CommandBlock
                  label={t.pluginsPage.authRequiredHint}
                  code={row.auth_command}
                />
              ) : null}

              {!row.has_dashboard_manifest && !dm ? (
                <p className="text-xs italic text-text-disabled">
                  {t.pluginsPage.noDashboardTab}
                </p>
              ) : null}
            </div>
          ) : undefined
        }
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            {row.runtime_status === "enabled" ? (
              <Button
                disabled={busy}
                ghost
                size="sm"
                onClick={() => {
                  void runAction(row.name, async () => {
                    await api.disableAgentPlugin(row.name);
                    showToast(t.pluginsPage.disableRuntime, "success");
                  });
                }}
              >
                {t.pluginsPage.disableRuntime}
              </Button>
            ) : (
              <Button
                disabled={busy}
                ghost
                size="sm"
                onClick={() => {
                  void runAction(row.name, async () => {
                    await api.enableAgentPlugin(row.name);
                    showToast(t.pluginsPage.enableRuntime, "success");
                  });
                }}
              >
                {t.pluginsPage.enableRuntime}
              </Button>
            )}

            {tabPath ? (
              <Link
                className={cn(
                  "inline-flex items-center rounded-none px-3 py-1.5",
                  "border border-current/25 hover:bg-current/10",
                  "font-mondwest text-display text-xs tracking-[0.1em]",
                )}
                to={tabPath}
              >
                {t.pluginsPage.openTab}
              </Link>
            ) : null}

            {row.can_update_git ? (
              <Button
                disabled={busy}
                ghost
                size="sm"
                onClick={() => {
                  void runAction(row.name, async () => {
                    await api.updateAgentPlugin(row.name);
                    showToast(t.pluginsPage.updateGit, "success");
                  });
                }}
              >
                {busy ? <Spinner /> : null}
                {t.pluginsPage.updateGit}
              </Button>
            ) : null}

            {row.has_dashboard_manifest ? (
              <Button
                disabled={busy}
                ghost
                size="sm"
                title={row.user_hidden ? t.pluginsPage.showInSidebar : t.pluginsPage.hideFromSidebar}
                onClick={() => {
                  void runAction(row.name, async () => {
                    await api.setPluginVisibility(row.name, !row.user_hidden);
                  });
                }}
              >
                {row.user_hidden ? (
                  <EyeOff className="h-3.5 w-3.5" />
                ) : (
                  <Eye className="h-3.5 w-3.5" />
                )}
                {row.user_hidden ? t.pluginsPage.showInSidebar : t.pluginsPage.hideFromSidebar}
              </Button>
            ) : null}

            {row.can_remove ? (
              <Button
                destructive
                disabled={busy}
                ghost
                size="sm"
                aria-label={t.common.delete}
                onClick={() => setConfirmRemove(true)}
              >
                {busy ? <Spinner /> : <Trash2 className="h-3.5 w-3.5" />}
              </Button>
            ) : null}
          </div>
        }
      />

      <ConfirmDialog
        open={confirmRemove}
        onCancel={() => setConfirmRemove(false)}
        onConfirm={() => {
          setConfirmRemove(false);
          void runAction(row.name, async () => {
            await api.removeAgentPlugin(row.name);
            showToast(`${row.name} removed`, "success");
          });
        }}
        title={t.pluginsPage.removeConfirm}
        description={`This will remove the "${row.name}" plugin from your agent.`}
        destructive
        confirmLabel={t.common.delete}
      />
    </>
  );
}
