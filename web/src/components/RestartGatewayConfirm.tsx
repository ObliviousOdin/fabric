import { useNavigate } from "react-router-dom";
import { ConfirmDialog } from "@nous-research/ui/ui/components/confirm-dialog";
import { useSystemActions } from "@/contexts/useSystemActions";
import { useI18n } from "@/i18n";

/**
 * Shared restart-gateway confirmation flow: on confirm it closes, dispatches
 * the restart and returns to /sessions so the reconnect is visible. Rendered
 * from every surface that offers a gateway restart (sidebar system actions,
 * command palette) so the copy and the confirm flow can't drift.
 */
export function RestartGatewayConfirm({
  onClose,
  onConfirmed,
  open,
}: RestartGatewayConfirmProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { pendingAction, runAction } = useSystemActions();

  return (
    <ConfirmDialog
      cancelLabel={t.common.cancel}
      confirmLabel={t.status.restartGateway}
      description={
        t.status.restartGatewayConfirmMessage ??
        "This restarts the Fabric gateway process. Connected channels and active sessions will reconnect afterward."
      }
      loading={pendingAction === "restart"}
      onCancel={onClose}
      onConfirm={() => {
        onClose();
        void runAction("restart");
        navigate("/sessions");
        onConfirmed?.();
      }}
      open={open}
      title={
        t.status.restartGatewayConfirmTitle ?? `${t.status.restartGateway}?`
      }
    />
  );
}

interface RestartGatewayConfirmProps {
  /** Close the dialog; called on cancel and first thing on confirm. */
  onClose: () => void;
  /** Runs after the restart is dispatched (e.g. close the mobile nav). */
  onConfirmed?: () => void;
  open: boolean;
}
