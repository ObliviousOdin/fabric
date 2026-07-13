import { useCallback } from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { api } from "@/lib/api";
import type { CheckpointsResponse } from "@/lib/api";
import { formatBytes, type ShowToast } from "./format";

export interface CheckpointsCardProps {
  checkpoints: CheckpointsResponse | null;
  setActiveAction: (name: string) => void;
  showToast: ShowToast;
}

/** Checkpoints card: count + size readout, destructive prune behind the
 *  shared confirm (N28 — frozen flow). */
export function CheckpointsCard({
  checkpoints,
  setActiveAction,
  showToast,
}: CheckpointsCardProps) {
  const checkpointsPrune = useConfirmDelete({
    onDelete: useCallback(async () => {
      try {
        const res = await api.pruneCheckpoints();
        setActiveAction(res.name);
        showToast("Checkpoint prune started", "success");
      } catch (e) {
        showToast(`Prune failed: ${e}`, "error");
        throw e;
      }
    }, [setActiveAction, showToast]),
  });

  return (
    <Card>
      <DeleteConfirmDialog
        open={checkpointsPrune.isOpen}
        onCancel={checkpointsPrune.cancel}
        onConfirm={checkpointsPrune.confirm}
        title="Prune checkpoints"
        description="Delete the rollback checkpoint shadow store? Existing /rollback points will be lost."
        loading={checkpointsPrune.isDeleting}
      />
      <CardContent className="flex items-center justify-between py-4">
        <span className="text-sm tabular-nums text-muted-foreground">
          {checkpoints?.sessions.length ?? 0} session(s) ·{" "}
          {formatBytes(checkpoints?.total_bytes ?? 0)}
        </span>
        <Button
          size="sm"
          ghost
          className="text-destructive"
          disabled={!checkpoints?.sessions.length}
          prefix={<Trash2 className="h-3.5 w-3.5" />}
          onClick={() => checkpointsPrune.requestDelete("all")}
        >
          Prune
        </Button>
      </CardContent>
    </Card>
  );
}
