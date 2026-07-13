import { useState } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import type { AuxiliaryModelsResponse } from "@/lib/api";
import { cn, themedBody } from "@/lib/utils";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { AUX_TASKS } from "./aux-tasks";

type PickerTarget = { kind: "aux"; task: string };

/**
 * Per-task auxiliary override modal (M2 auxiliary row). Internals frozen
 * (N16): per-task `ModelPickerDialog`, the `__reset__` reset-all
 * semantics, confirm dialog — moved verbatim out of the pre-split
 * ModelsPage.
 */
export function AuxiliaryTasksModal({
  aux,
  refreshKey,
  onSaved,
  onClose,
}: {
  aux: AuxiliaryModelsResponse | null;
  refreshKey: number;
  onSaved(): void;
  onClose(): void;
}) {
  const [picker, setPicker] = useState<PickerTarget | null>(null);
  const [resetBusy, setResetBusy] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const modalRef = useModalBehavior({ open: true, onClose });

  const resetAllAux = async () => {
    setConfirmReset(false);
    setResetBusy(true);
    try {
      await api.setModelAssignment({
        scope: "auxiliary",
        task: "__reset__",
        provider: "",
        model: "",
      });
      onSaved();
    } finally {
      setResetBusy(false);
    }
  };

  return (
    <div
      ref={modalRef}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="aux-modal-title"
    >
      <div className={cn(themedBody, "relative w-full max-w-2xl max-h-[80vh] border border-border bg-card shadow-2xl flex flex-col")}>
        <Button
          ghost
          size="icon"
          onClick={onClose}
          className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
          aria-label="Close"
        >
          <X />
        </Button>

        <header className="p-5 pb-3 border-b border-border">
          <div className="flex items-center justify-between gap-3 pr-8">
            <h2
              id="aux-modal-title"
              className="font-mondwest text-display text-base tracking-wider"
            >
              Auxiliary Tasks
            </h2>
            <Button
              size="sm"
              outlined
              onClick={() => setConfirmReset(true)}
              disabled={resetBusy}
              className="h-6 text-xs uppercase"
              prefix={resetBusy ? <Spinner /> : null}
            >
              Reset all to auto
            </Button>
          </div>
          <p className="text-xs text-text-secondary mt-2">
            Auxiliary tasks handle side-jobs like vision, session search, and
            compression. <span className="font-mono">auto</span> means
            &quot;use the main model&quot;. Override per-task when you want a
            cheap/fast model for a specific job.
          </p>
        </header>

        <div className="flex-1 overflow-y-auto p-5 space-y-1">
          {AUX_TASKS.map((t) => {
            const cur = aux?.tasks.find((a) => a.task === t.key);
            const isAuto =
              !cur || cur.provider === "auto" || !cur.provider;
            return (
              <div
                key={t.key}
                className="flex items-center justify-between gap-3 px-3 py-2 border border-border/30 bg-card/50 hover:bg-muted/20 transition-colors motion-reduce:transition-none"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs font-medium">{t.label}</span>
                    <span className="text-xs text-text-tertiary">
                      {t.hint}
                    </span>
                  </div>
                  <div className="text-xs font-mono text-text-secondary truncate">
                    {isAuto
                      ? "auto (use main model)"
                      : `${cur?.provider} · ${cur?.model || "(provider default)"}`}
                  </div>
                </div>
                <Button
                  size="sm"
                  outlined
                  onClick={() => setPicker({ kind: "aux", task: t.key })}
                  className="h-6 text-xs uppercase"
                >
                  Change
                </Button>
              </div>
            );
          })}
        </div>

        {picker && picker.kind === "aux" && (
          <ModelPickerDialog
            key={`picker-${refreshKey}`}
            loader={api.getModelOptions}
            alwaysGlobal
            title={`Set Auxiliary: ${
              AUX_TASKS.find((t) => t.key === picker.task)?.label ??
              picker.task
            }`}
            onApply={async ({ provider, model, confirmExpensiveModel }) => {
              const result = await api.setModelAssignment({
                confirm_expensive_model: confirmExpensiveModel,
                scope: "auxiliary",
                task: picker.task,
                provider,
                model,
              });
              if (!result.confirm_required) onSaved();
              return result;
            }}
            onClose={() => setPicker(null)}
          />
        )}
        <ConfirmDialog
          open={confirmReset}
          onCancel={() => setConfirmReset(false)}
          onConfirm={() => void resetAllAux()}
          title="Reset auxiliary models"
          description="Reset every auxiliary task to 'auto'? This overrides any per-task overrides you've set."
          destructive
          confirmLabel="Reset all"
          loading={resetBusy}
        />
      </div>
    </div>
  );
}
