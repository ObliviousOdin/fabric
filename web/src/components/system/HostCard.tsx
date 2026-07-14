import { useCallback, useState } from "react";
import { Cpu, Download, HardDrive, RotateCw } from "lucide-react";
import { Badge } from "@/components/fabric/Badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { ConfirmDialog } from "@nous-research/ui/ui/components/confirm-dialog";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { api } from "@/lib/api";
import type { SystemStats, UpdateCheckResponse } from "@/lib/api";
import { publicCliCommand } from "@/lib/public-identity";
import { formatBytes, formatDuration, type ShowToast } from "./format";

export interface HostCardProps {
  stats: SystemStats | null;
  /** `status.can_update_hermes !== false` — gates the whole update UI (Y9). */
  canUpdateHermes: boolean;
  updateInfo: UpdateCheckResponse | null;
  /** Forced re-checks write back so the version badge stays current (Y9). */
  setUpdateInfo: (info: UpdateCheckResponse) => void;
  /** Starts watching a spawned action in the shared log viewer (CN10). */
  setActiveAction: (name: string) => void;
  showToast: ShowToast;
}

/** Numeric readouts are tabular mono (Y11/G9/G12). */
const NUM_CN = "font-mono-ui tabular-nums";

/**
 * Host card (Y11): system-stats grid + the Fabric version row with the
 * update-check/apply flow (Y9 — frozen behavior: cached check happens in
 * the page's loadAll; this card owns the forced re-check + confirm+apply).
 */
export function HostCard({
  stats,
  canUpdateHermes,
  updateInfo,
  setUpdateInfo,
  setActiveAction,
  showToast,
}: HostCardProps) {
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [updateConfirmOpen, setUpdateConfirmOpen] = useState(false);

  // Auto-check (cached) runs inside the page's loadAll on mount; this is
  // the user-triggered forced re-check from the "Check for updates" button.
  const checkForUpdate = useCallback(
    async (force = false) => {
      if (!canUpdateHermes) return;
      setCheckingUpdate(true);
      try {
        const info = await api.checkHermesUpdate(force);
        setUpdateInfo(info);
        if (force) {
          if (info.update_available) {
            showToast(
              info.behind && info.behind > 0
                ? `Update available — ${info.behind} commit${info.behind === 1 ? "" : "s"} behind`
                : "Update available",
              "success",
            );
          } else if (info.behind === 0) {
            showToast("You're on the latest version", "success");
          } else if (info.message) {
            showToast(info.message, "error");
          }
        }
      } catch (e) {
        showToast(`Update check failed: ${e}`, "error");
      } finally {
        setCheckingUpdate(false);
      }
    },
    [canUpdateHermes, setUpdateInfo, showToast],
  );

  const applyUpdate = async () => {
    setUpdateConfirmOpen(false);
    if (!canUpdateHermes) {
      showToast("Fabric updates are managed outside this dashboard.", "success");
      return;
    }
    try {
      const resp = await api.updateHermes();
      if (!resp.ok) {
        showToast(
          resp.message ?? "Updates don't apply from this dashboard.",
          "success",
        );
        return;
      }
      setActiveAction(resp.name ?? "hermes-update");
      showToast("Update started", "success");
    } catch (e) {
      showToast(`Update failed: ${e}`, "error");
    }
  };

  return (
    <Card>
      <ConfirmDialog
        open={canUpdateHermes && updateConfirmOpen}
        onCancel={() => setUpdateConfirmOpen(false)}
        onConfirm={() => void applyUpdate()}
        title="Update Fabric?"
        description={
          updateInfo && updateInfo.behind && updateInfo.behind > 0
            ? `This will run '${publicCliCommand(updateInfo.update_command)}' and pull ${updateInfo.behind} new commit${updateInfo.behind === 1 ? "" : "s"}. The gateway restarts when the update finishes; the current session keeps its prompt cache until then.`
            : `This will run '${publicCliCommand(updateInfo?.update_command)}' and restart the gateway when it finishes.`
        }
        confirmLabel="Update now"
      />
      <CardContent className="py-4">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-6 text-sm">
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">OS</div>
            <div>{stats ? `${stats.os} ${stats.os_release}` : "—"}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Arch</div>
            <div>{stats?.arch ?? "—"}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Host</div>
            <div className="truncate">{stats?.hostname ?? "—"}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Python</div>
            <div>
              {stats?.python_impl}{" "}
              <span className={NUM_CN}>{stats?.python_version}</span>
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Fabric</div>
            <div className="flex items-center gap-2">
              <span className={NUM_CN}>
                {stats?.hermes_version ? `v${stats.hermes_version}` : "—"}
              </span>
              {canUpdateHermes &&
                updateInfo &&
                (updateInfo.update_available ? (
                  <Badge tone="warning">
                    {updateInfo.behind && updateInfo.behind > 0
                      ? `${updateInfo.behind} behind`
                      : "update available"}
                  </Badge>
                ) : updateInfo.behind === 0 ? (
                  <Badge tone="success">latest</Badge>
                ) : null)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <Cpu className="h-3 w-3" /> CPU
            </div>
            <div className={NUM_CN}>
              {stats?.cpu_count ?? "—"} cores
              {typeof stats?.cpu_percent === "number"
                ? ` · ${stats.cpu_percent.toFixed(0)}%`
                : ""}
            </div>
          </div>
          {stats?.memory && (
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground">Memory</div>
              <div className={NUM_CN}>
                {formatBytes(stats.memory.used)} / {formatBytes(stats.memory.total)} ({stats.memory.percent}%)
              </div>
            </div>
          )}
          {stats?.disk && (
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <HardDrive className="h-3 w-3" /> Disk
              </div>
              <div className={NUM_CN}>
                {formatBytes(stats.disk.used)} / {formatBytes(stats.disk.total)} ({stats.disk.percent}%)
              </div>
            </div>
          )}
          {typeof stats?.uptime_seconds === "number" && (
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground">Uptime</div>
              <div className={NUM_CN}>{formatDuration(stats.uptime_seconds)}</div>
            </div>
          )}
          {stats?.load_avg && stats.load_avg.length >= 3 && (
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground">Load avg</div>
              <div className={NUM_CN}>
                {stats.load_avg.map((n) => n.toFixed(2)).join(" / ")}
              </div>
            </div>
          )}
        </div>
        {stats && !stats.psutil && (
          <p className="mt-3 text-xs text-muted-foreground">
            Install the <span className="font-mono">psutil</span> extra for
            CPU / memory / disk metrics.
          </p>
        )}
        {canUpdateHermes && (
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
            <Button
              size="sm"
              ghost
              disabled={checkingUpdate}
              prefix={
                checkingUpdate ? (
                  <Spinner className="h-3.5 w-3.5" />
                ) : (
                  <RotateCw className="h-3.5 w-3.5" />
                )
              }
              onClick={() => void checkForUpdate(true)}
            >
              Check for updates
            </Button>
            {updateInfo?.update_available && updateInfo.can_apply && (
              <Button
                size="sm"
                prefix={<Download className="h-3.5 w-3.5" />}
                onClick={() => setUpdateConfirmOpen(true)}
              >
                Update now
              </Button>
            )}
            {updateInfo &&
              !updateInfo.can_apply &&
              updateInfo.update_available && (
                <span className="text-xs text-muted-foreground">
                  Update with{" "}
                  <span className="font-mono">
                    {publicCliCommand(updateInfo.update_command)}
                  </span>
                </span>
              )}
            {updateInfo?.message && !updateInfo.update_available && (
              <span className="text-xs text-muted-foreground">
                {updateInfo.message}
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
