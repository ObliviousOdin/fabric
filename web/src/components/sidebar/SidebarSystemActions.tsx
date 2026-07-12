import {
  useEffect,
  useMemo,
  useState,
  type ComponentType,
  type FocusEvent,
  type MouseEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import { Download, RotateCw } from "lucide-react";
import { ConfirmDialog } from "@nous-research/ui/ui/components/confirm-dialog";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { SidebarStatusStrip } from "@/components/SidebarStatusStrip";
import { useSystemActions } from "@/contexts/useSystemActions";
import type { SystemAction } from "@/contexts/system-actions-context";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import type { StatusResponse, UpdateCheckResponse } from "@/lib/api";
import { publicCliCommand } from "@/lib/public-identity";
import { cn } from "@/lib/utils";
import { GatewayDot } from "./GatewayDot";
import { SidebarTooltip, type TooltipWarmRef } from "./SidebarTooltip";

export function SidebarSystemActions({
  collapsed,
  onNavigate,
  status,
  tooltipWarmRef,
}: SidebarSystemActionsProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { activeAction, isBusy, isRunning, pendingAction, runAction } =
    useSystemActions();
  const canUpdateHermes = status?.can_update_hermes === true;
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);
  const [updateConfirmOpen, setUpdateConfirmOpen] = useState(false);
  const [updateConfirmInfo, setUpdateConfirmInfo] =
    useState<UpdateCheckResponse | null>(null);
  const [updateConfirmChecking, setUpdateConfirmChecking] = useState(false);

  useEffect(() => {
    if (!updateConfirmOpen) {
      setUpdateConfirmInfo(null);
      return;
    }
    let cancelled = false;
    setUpdateConfirmChecking(true);
    api
      .checkHermesUpdate(false)
      .then((info) => {
        if (!cancelled) setUpdateConfirmInfo(info);
      })
      .catch(() => {
        if (!cancelled) setUpdateConfirmInfo(null);
      })
      .finally(() => {
        if (!cancelled) setUpdateConfirmChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [updateConfirmOpen]);

  const updateConfirmDescription = useMemo(() => {
    if (updateConfirmInfo?.behind && updateConfirmInfo.behind > 0) {
      const cmd = publicCliCommand(updateConfirmInfo.update_command);
      const n = updateConfirmInfo.behind;
      return `This will run '${cmd}' and pull ${n} new commit${n === 1 ? "" : "s"}. The gateway restarts when the update finishes; the current session keeps its prompt cache until then.`;
    }
    const cmd = publicCliCommand(updateConfirmInfo?.update_command);
    return (
      t.status.updateHermesConfirmMessage ??
      `This will run '${cmd}' and restart the gateway when it finishes.`
    );
  }, [t.status.updateHermesConfirmMessage, updateConfirmInfo]);

  const items: SystemActionItem[] = [
    {
      action: "restart",
      icon: RotateCw,
      label: t.status.restartGateway,
      runningLabel: t.status.restartingGateway,
      spin: true,
    },
  ];
  if (canUpdateHermes) {
    items.push({
      action: "update",
      icon: Download,
      label: t.status.updateHermes,
      runningLabel: t.status.updatingHermes,
      spin: false,
    });
  }

  const handleClick = (action: SystemAction) => {
    if (isBusy) return;
    if (action === "restart") {
      setRestartConfirmOpen(true);
      return;
    }
    if (action === "update") {
      setUpdateConfirmOpen(true);
      return;
    }
    void runAction(action);
    navigate("/sessions");
    onNavigate();
  };

  const confirmRestart = () => {
    setRestartConfirmOpen(false);
    void runAction("restart");
    navigate("/sessions");
    onNavigate();
  };

  const confirmUpdate = () => {
    setUpdateConfirmOpen(false);
    void runAction("update");
    navigate("/sessions");
    onNavigate();
  };

  return (
    <>
      <div className={cn("shrink-0 flex flex-col", "border-t border-current/10", "py-1")}>
        {/* Labeled "Gateway" (not "System") so it doesn't collide with the
            SYSTEM nav section that now sits at the bottom of the nav list. */}
        <span
          className={cn(
            "px-5 pt-1 pb-0.5",
            "font-sans text-display text-xs uppercase tracking-[0.12em] text-text-tertiary",
            collapsed && "lg:hidden",
          )}
        >
          {t.status.gateway}
        </span>

        <div className={cn(collapsed && "lg:hidden")}>
          <SidebarStatusStrip status={status} />
        </div>

        <GatewayDot
          collapsed={collapsed}
          status={status}
          tooltipWarmRef={tooltipWarmRef}
        />

        <ul className="flex flex-col">
          {items.map((item) => (
            <SystemActionButton
              key={item.action}
              collapsed={collapsed}
              disabled={
                isBusy &&
                !(
                  pendingAction === item.action ||
                  (activeAction === item.action && isRunning)
                )
              }
              tooltipWarmRef={tooltipWarmRef}
              isPending={pendingAction === item.action}
              isRunning={
                activeAction === item.action &&
                isRunning &&
                pendingAction !== item.action
              }
              item={item}
              onClick={() => handleClick(item.action)}
            />
          ))}
        </ul>
      </div>

      <ConfirmDialog
        cancelLabel={t.common.cancel}
        confirmLabel={t.status.restartGateway}
        description={
          t.status.restartGatewayConfirmMessage ??
          "This restarts the Fabric gateway process. Connected channels and active sessions will reconnect afterward."
        }
        loading={pendingAction === "restart"}
        onCancel={() => setRestartConfirmOpen(false)}
        onConfirm={confirmRestart}
        open={restartConfirmOpen}
        title={
          t.status.restartGatewayConfirmTitle ?? `${t.status.restartGateway}?`
        }
      />

      <ConfirmDialog
        cancelLabel={t.common.cancel}
        confirmLabel={t.status.updateHermesConfirmNow ?? "Update now"}
        description={
          updateConfirmChecking ? t.common.loading : updateConfirmDescription
        }
        loading={pendingAction === "update" || updateConfirmChecking}
        onCancel={() => setUpdateConfirmOpen(false)}
        onConfirm={confirmUpdate}
        open={updateConfirmOpen}
        title={t.status.updateHermesConfirmTitle ?? `${t.status.updateHermes}?`}
      />
    </>
  );
}

function SystemActionButton({
  collapsed,
  disabled,
  isPending,
  isRunning: isActionRunning,
  item,
  onClick,
  tooltipWarmRef,
}: SystemActionButtonProps) {
  const { icon: Icon, label, runningLabel, spin } = item;
  const [hovered, setHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<HTMLElement | null>(null);
  const busy = isPending || isActionRunning;
  const displayLabel = isActionRunning ? runningLabel : label;
  const showTooltip = (
    event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>,
  ) => {
    setHovered(true);
    setTooltipAnchor(event.currentTarget);
  };
  const hideTooltip = () => {
    setHovered(false);
    setTooltipAnchor(null);
  };

  return (
    <li
      onMouseEnter={collapsed ? showTooltip : undefined}
      onMouseLeave={collapsed ? hideTooltip : undefined}
    >
      <button
        onClick={onClick}
        disabled={disabled}
        aria-busy={busy}
        aria-label={collapsed ? displayLabel : undefined}
        onFocus={collapsed ? showTooltip : undefined}
        onBlur={collapsed ? hideTooltip : undefined}
        type="button"
        className={cn(
          "relative flex h-9 w-full items-center gap-3 px-5",
          "font-sans text-sm",
          "whitespace-nowrap transition-colors cursor-pointer",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          busy
            ? "bg-midground/10 text-midground"
            : "text-text-secondary hover:bg-midground/5 hover:text-midground",
          "disabled:text-text-disabled disabled:cursor-not-allowed disabled:hover:bg-transparent",
        )}
      >
        {isPending ? (
          <Spinner className="shrink-0 text-[0.875rem]" />
        ) : isActionRunning && spin ? (
          <Spinner className="shrink-0 text-[0.875rem]" />
        ) : (
          <Icon
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              isActionRunning && !spin && "animate-pulse",
            )}
          />
        )}

        <span
          className={cn(
            "truncate transition-opacity duration-300",
            collapsed ? "lg:opacity-0" : "lg:opacity-100",
          )}
        >
          {displayLabel}
        </span>

        {busy && (
          <span
            aria-hidden
            className="absolute left-0 top-0 bottom-0 w-px bg-midground"
          />
        )}
      </button>

      {collapsed && hovered && tooltipAnchor && (
        <SidebarTooltip
          anchor={tooltipAnchor}
          label={displayLabel}
          warmRef={tooltipWarmRef}
        />
      )}
    </li>
  );
}

interface SidebarSystemActionsProps {
  collapsed: boolean;
  onNavigate: () => void;
  status: StatusResponse | null;
  tooltipWarmRef: TooltipWarmRef;
}

interface SystemActionButtonProps {
  collapsed: boolean;
  disabled: boolean;
  isPending: boolean;
  isRunning: boolean;
  item: SystemActionItem;
  onClick: () => void;
  tooltipWarmRef: TooltipWarmRef;
}

interface SystemActionItem {
  action: SystemAction;
  icon: ComponentType<{ className?: string }>;
  label: string;
  runningLabel: string;
  spin: boolean;
}
