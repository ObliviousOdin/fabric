import { useCallback } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { api } from "@/lib/api";
import type { MemoryStatus, MemorySelectionState } from "@/lib/api";
import { formatBytes, type ShowToast } from "./format";

// Must match the backend's memory-selection enum — unknown values from a
// newer backend fall back to the derivation below rather than crashing
// (R18/R28 drift watch).
const MEMORY_SELECTION_LABEL: Record<MemorySelectionState, string> = {
  builtin_only: "built-in only",
  tiers_disabled: "tiers disabled",
  missing: "missing",
  needs_config: "needs setup",
  unavailable: "unavailable",
  readiness_unknown: "readiness unknown",
  eligible: "eligible next session",
};

const MEMORY_SELECTION_TONE: Record<
  MemorySelectionState,
  "success" | "warning" | "destructive" | "secondary"
> = {
  builtin_only: "secondary",
  tiers_disabled: "warning",
  missing: "destructive",
  needs_config: "warning",
  unavailable: "destructive",
  readiness_unknown: "warning",
  eligible: "success",
};

export interface MemoryCardProps {
  memory: MemoryStatus | null;
  showToast: ShowToast;
  reload: () => void;
}

/**
 * Memory card (Y4, frozen behavior): read-only provider display + "Change
 * in Plugins →" links (the Plugins page is canonical — the provider
 * dropdown was intentionally dropped from this card during the admin-panel
 * refresh), selection-state badge, honesty notices, external-capture
 * policy line, built-in file sizes, and the reset confirms.
 */
export function MemoryCard({ memory, showToast, reload }: MemoryCardProps) {
  const memoryReset = useConfirmDelete({
    onDelete: useCallback(
      async (target: string) => {
        try {
          const res = await api.resetMemory(target as "all" | "memory" | "user");
          showToast(`Reset: ${res.deleted.join(", ") || "nothing"}`, "success");
          reload();
        } catch (e) {
          showToast(`Reset failed: ${e}`, "error");
          throw e;
        }
      },
      [reload, showToast],
    ),
  });

  const configuredMemoryProvider = memory?.active
    ? memory.providers.find((provider) => provider.name === memory.active)
    : null;
  const memorySelectionState: MemorySelectionState =
    memory?.selection?.state ??
    (configuredMemoryProvider?.status === "missing"
      ? "missing"
      : configuredMemoryProvider?.status === "needs_config"
        ? "needs_config"
        : configuredMemoryProvider?.status === "unavailable"
          ? "unavailable"
          : memory?.active
            ? "eligible"
            : "builtin_only");

  return (
    <Card>
      <DeleteConfirmDialog
        open={memoryReset.isOpen}
        onCancel={memoryReset.cancel}
        onConfirm={memoryReset.confirm}
        title="Reset memory"
        description="This permanently erases only the selected built-in memory files. It cannot be undone and does not erase copies held by an external memory provider."
        loading={memoryReset.isDeleting}
      />
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>
            Configured provider:{" "}
            <span className="font-mono text-foreground">
              {memory?.active || "built-in only"}
            </span>
          </span>
          <Badge tone={MEMORY_SELECTION_TONE[memorySelectionState]}>
            {MEMORY_SELECTION_LABEL[memorySelectionState]}
          </Badge>
          <Link to="/plugins" className="underline">
            Change in Plugins →
          </Link>
          <span className="ml-auto">
            Provider setup:{" "}
            <Link to="/plugins" className="underline">
              configure in Plugins
            </Link>
          </span>
        </div>

        {memorySelectionState === "missing" && (
          <p className="border border-destructive/50 px-3 py-2 text-xs text-destructive">
            The configured provider is no longer installed. Switch to built-in memory or configure another provider in Plugins.
          </p>
        )}

        {memorySelectionState === "tiers_disabled" && (
          <p className="border border-warning/50 px-3 py-2 text-xs text-muted-foreground">
            The provider is configured but cannot start because MEMORY.md and USER.md are both disabled.
          </p>
        )}

        {memory?.selection && memorySelectionState === "eligible" && (
          <p className="text-xs text-muted-foreground">
            Static prerequisites passed for a new session. Live initialization and provider health have not been checked.
          </p>
        )}

        <p className="text-xs text-muted-foreground">
          External capture: {!memory?.write_policy?.external_provider_writes
            ? "unknown — policy not reported"
            : memory.write_policy.external_provider_writes.state === "allowed"
              ? "allowed by explicit profile consent"
              : memory.write_policy.external_provider_writes.consent_valid === false
                ? "blocked — consent must be a YAML boolean"
                : "blocked — profile consent required"}
        </p>

        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
          <span className="text-xs text-muted-foreground">
            Built-in files — MEMORY.md:{" "}
            {memory?.tiers?.memory.enabled === false ? "disabled · " : ""}
            {formatBytes(memory?.builtin_files.memory ?? 0)} · USER.md:{" "}
            {memory?.tiers?.user.enabled === false ? "disabled · " : ""}
            {formatBytes(memory?.builtin_files.user ?? 0)}
          </span>
          <div className="flex items-center gap-2 ml-auto">
            <Button
              size="sm"
              ghost
              className="text-destructive"
              onClick={() => memoryReset.requestDelete("memory")}
            >
              Reset MEMORY.md
            </Button>
            <Button
              size="sm"
              ghost
              className="text-destructive"
              onClick={() => memoryReset.requestDelete("user")}
            >
              Reset USER.md
            </Button>
            <Button
              size="sm"
              ghost
              className="text-destructive"
              onClick={() => memoryReset.requestDelete("all")}
            >
              Reset all
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
