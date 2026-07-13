import { useEffect, useState } from "react";
import { ChevronDown, Star } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { AUX_TASKS } from "./aux-tasks";

/**
 * Per-card "Use as" assignment shortcut (M6 actions zone). The entire flow
 * — assign main/aux, `confirm_required` expensive-model round-trip via
 * `ConfirmDialog`, outside-click close — is frozen (N16); this component
 * moved verbatim out of the pre-split ModelsPage.
 */
export function UseAsMenu({
  provider,
  model,
  isMain,
  mainAuxTask,
  onAssigned,
}: {
  provider: string;
  model: string;
  /** True when this card's model+provider match config.yaml's main slot. */
  isMain: boolean;
  /** If this model is assigned to a specific aux task, that task's key. */
  mainAuxTask: string | null;
  onAssigned(): void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<{
    message: string;
    scope: "main" | "auxiliary";
    task: string;
  } | null>(null);

  const assign = async (
    scope: "main" | "auxiliary",
    task: string,
    confirmExpensiveModel = false,
  ) => {
    if (!provider || !model) {
      setError("Missing provider/model");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.setModelAssignment({
        confirm_expensive_model: confirmExpensiveModel,
        scope,
        provider,
        model,
        task,
      });
      if (result.confirm_required) {
        setPendingConfirm({
          scope,
          task,
          message:
            result.confirm_message ||
            "This model has unusually high known pricing.",
        });
        return;
      }
      onAssigned();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && !target.closest?.("[data-use-as-menu]")) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div className={cn("relative", open && "z-20")} data-use-as-menu>
      <Button
        size="sm"
        outlined
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        className="h-6 px-2 text-xs uppercase"
        prefix={busy ? <Spinner /> : null}
      >
        Use as <ChevronDown className="h-3 w-3" />
      </Button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[220px] border border-border bg-card shadow-lg">
          <button
            type="button"
            onClick={() => assign("main", "")}
            disabled={busy}
            className="flex w-full items-center justify-between px-3 py-2 text-xs uppercase hover:bg-muted/50 disabled:opacity-40"
          >
            <span className="flex items-center gap-2">
              <Star className="h-3 w-3" />
              Main model
            </span>
            {isMain && (
              <span className="text-display text-xs tracking-wider text-primary">
                current
              </span>
            )}
          </button>

          <div className="border-t border-border/50 px-3 py-1.5 text-display text-xs tracking-wider text-text-tertiary">
            Auxiliary task
          </div>

          <button
            type="button"
            onClick={() => assign("auxiliary", "")}
            disabled={busy}
            className="flex w-full items-center justify-between px-3 py-1.5 text-xs uppercase hover:bg-muted/50 disabled:opacity-40"
          >
            <span>All auxiliary tasks</span>
          </button>

          {AUX_TASKS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => assign("auxiliary", t.key)}
              disabled={busy}
              className="flex w-full items-center justify-between px-3 py-1.5 text-xs uppercase hover:bg-muted/50 disabled:opacity-40"
            >
              <span>{t.label}</span>
              {mainAuxTask === t.key && (
                <span className="text-display text-xs tracking-wider text-primary">
                  current
                </span>
              )}
            </button>
          ))}

          {error && (
            <div className="px-3 py-2 text-xs text-destructive border-t border-border/50">
              {error}
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={!!pendingConfirm}
        title="Expensive Model Warning"
        description={pendingConfirm?.message}
        destructive
        confirmLabel="Switch anyway"
        cancelLabel="Cancel"
        loading={busy}
        onCancel={() => setPendingConfirm(null)}
        onConfirm={() => {
          const pending = pendingConfirm;
          if (!pending) return;
          setPendingConfirm(null);
          void assign(pending.scope, pending.task, true);
        }}
      />
    </div>
  );
}
