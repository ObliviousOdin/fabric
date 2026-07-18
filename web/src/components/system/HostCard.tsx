import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  Cpu,
  Download,
  Gauge,
  HardDrive,
  MemoryStick,
  RotateCw,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/fabric/Badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { ConfirmDialog } from "@nous-research/ui/ui/components/confirm-dialog";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { api } from "@/lib/api";
import type { SystemStats, UpdateCheckResponse } from "@/lib/api";
import { publicCliCommand } from "@/lib/public-identity";
import { Sparkline } from "./Sparkline";
import {
  formatBytes,
  formatDuration,
  formatRate,
  type ShowToast,
} from "./format";

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
/** Live refresh cadence + how many samples the sparklines retain. */
const POLL_MS = 2000;
const HISTORY = 40;

type Series =
  | "cpu"
  | "mem"
  | "disk"
  | "load"
  | "down"
  | "up"
  | "gpu"
  | "vram";
type History = Partial<Record<Series, number[]>>;

/** Small live-metric cell: label, mono readout, and a rolling sparkline. */
function MetricTile({
  icon: Icon,
  label,
  value,
  unit,
  sub,
  subTitle,
  values,
  max,
  sparkClassName = "text-muted-foreground",
}: {
  icon?: LucideIcon;
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  subTitle?: string;
  values: number[];
  max?: number;
  sparkClassName?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1">
        {Icon && <Icon className="h-3 w-3" />} {label}
      </div>
      <div className={`${NUM_CN} flex items-baseline gap-1`}>
        <span>{value}</span>
        {unit && (
          <span className="text-[11px] font-normal text-muted-foreground">
            {unit}
          </span>
        )}
        {sub && (
          <span
            className="ml-auto min-w-0 truncate text-[11px] font-normal text-muted-foreground"
            title={subTitle ?? sub}
          >
            {sub}
          </span>
        )}
      </div>
      <div className="mt-1.5">
        <Sparkline
          values={values}
          max={max}
          className={sparkClassName}
          ariaLabel={`${label} trend`}
        />
      </div>
    </div>
  );
}

/**
 * Host card (Y11): live system-stats grid + the Fabric version row with the
 * update-check/apply flow (Y9). The card polls `/api/system/stats` every
 * {@link POLL_MS}ms and keeps a rolling {@link HISTORY}-sample window so CPU,
 * memory, disk, load, network throughput and GPU render as live sparklines.
 * The initial `stats` prop (from the page's loadAll) paints the first frame
 * before the first poll settles.
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

  // Live-refreshed stats layered over the initial prop, plus per-metric
  // history for the sparklines.
  const [live, setLive] = useState<SystemStats | null>(null);
  const [history, setHistory] = useState<History>({});
  const s = live ?? stats;

  const pushHistory = useCallback((next: SystemStats) => {
    setHistory((prev) => {
      const out: History = { ...prev };
      const add = (key: Series, v: number | null | undefined) => {
        if (typeof v !== "number" || Number.isNaN(v)) return;
        const arr = (prev[key] ?? []).concat(v);
        out[key] = arr.length > HISTORY ? arr.slice(-HISTORY) : arr;
      };
      add("cpu", next.cpu_percent);
      add("mem", next.memory?.percent);
      add("disk", next.disk?.percent);
      add("load", next.load_avg?.[0]);
      // Throughput in MB/s keeps the sparkline autoscale readable.
      add(
        "down",
        next.net?.recv_per_sec != null
          ? next.net.recv_per_sec / (1024 * 1024)
          : undefined,
      );
      add(
        "up",
        next.net?.sent_per_sec != null
          ? next.net.sent_per_sec / (1024 * 1024)
          : undefined,
      );
      const gpu = next.gpus?.[0];
      add("gpu", gpu?.util_percent);
      add("vram", gpu?.mem_percent ?? undefined);
      return out;
    });
  }, []);

  // Seed the first sparkline point from the prop until live polling takes over.
  useEffect(() => {
    if (stats && !live) pushHistory(stats);
  }, [stats, live, pushHistory]);

  // Live polling loop. A transient failure keeps the last frame (the page's
  // loadAll owns the failure banner, so the card must not blank on a blip).
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const next = await api.getSystemStats();
        if (!alive) return;
        setLive(next);
        pushHistory(next);
      } catch {
        /* keep the last successful frame */
      }
    };
    const id = window.setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [pushHistory]);

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

  const gpu = s?.gpus?.[0];

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
        {/* Identity + version (static, refreshed each poll). */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-6 text-sm">
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">OS</div>
            <div>{s ? `${s.os} ${s.os_release}` : "—"}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Arch</div>
            <div>{s?.arch ?? "—"}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Host</div>
            <div className="truncate">{s?.hostname ?? "—"}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Python</div>
            <div>
              {s?.python_impl}{" "}
              <span className={NUM_CN}>{s?.python_version}</span>
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Fabric</div>
            <div className="flex items-center gap-2">
              <span className={NUM_CN}>
                {s?.hermes_version ? `v${s.hermes_version}` : "—"}
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
          {typeof s?.uptime_seconds === "number" && (
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground">Uptime</div>
              <div className={NUM_CN}>{formatDuration(s.uptime_seconds)}</div>
            </div>
          )}
        </div>

        {/* Live metrics grid — sparklines over the rolling window (Y11). */}
        {s?.psutil ? (
          <div className="mt-4 border-t border-border pt-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-xs uppercase tracking-wider text-muted-foreground">
                Live metrics
              </div>
              <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground font-mono-ui">
                <span className="relative flex h-1.5 w-1.5" aria-hidden="true">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-500/60 motion-safe:animate-ping" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                </span>
                live · {POLL_MS / 1000}s
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-4">
              {typeof s.cpu_percent === "number" && (
                <MetricTile
                  icon={Cpu}
                  label="CPU"
                  value={s.cpu_percent.toFixed(0)}
                  unit="%"
                  sub={s.cpu_count ? `${s.cpu_count}c` : undefined}
                  values={history.cpu ?? []}
                  max={100}
                  sparkClassName="text-primary"
                />
              )}
              {s.memory && (
                <MetricTile
                  icon={MemoryStick}
                  label="Memory"
                  value={s.memory.percent.toFixed(0)}
                  unit="%"
                  sub={`${formatBytes(s.memory.used)} / ${formatBytes(s.memory.total)}`}
                  values={history.mem ?? []}
                  max={100}
                />
              )}
              {s.disk && (
                <MetricTile
                  icon={HardDrive}
                  label="Disk"
                  value={s.disk.percent.toFixed(0)}
                  unit="%"
                  sub={`${formatBytes(s.disk.used)} / ${formatBytes(s.disk.total)}`}
                  values={history.disk ?? []}
                  max={100}
                />
              )}
              {s.load_avg && s.load_avg.length >= 3 && (
                <MetricTile
                  icon={Activity}
                  label="Load avg"
                  value={s.load_avg[0].toFixed(2)}
                  sub={s.load_avg.map((n) => n.toFixed(2)).join(" / ")}
                  subTitle="1 / 5 / 15 min"
                  values={history.load ?? []}
                />
              )}
              {s.net && (
                <>
                  <MetricTile
                    icon={ArrowDownToLine}
                    label="Net down"
                    value={formatRate(s.net.recv_per_sec)}
                    values={history.down ?? []}
                  />
                  <MetricTile
                    icon={ArrowUpFromLine}
                    label="Net up"
                    value={formatRate(s.net.sent_per_sec)}
                    values={history.up ?? []}
                  />
                </>
              )}
              {gpu && (
                <>
                  <MetricTile
                    icon={Gauge}
                    label="GPU"
                    value={gpu.util_percent.toFixed(0)}
                    unit="%"
                    sub={gpu.name}
                    values={history.gpu ?? []}
                    max={100}
                    sparkClassName="text-primary"
                  />
                  {gpu.mem_percent != null && (
                    <MetricTile
                      icon={MemoryStick}
                      label="VRAM"
                      value={gpu.mem_percent.toFixed(0)}
                      unit="%"
                      sub={`${formatBytes(gpu.mem_used)} / ${formatBytes(gpu.mem_total)}`}
                      values={history.vram ?? []}
                      max={100}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        ) : (
          s && (
            <p className="mt-3 text-xs text-muted-foreground">
              Install the <span className="font-mono">psutil</span> extra for
              CPU / memory / disk / network metrics.
            </p>
          )
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
