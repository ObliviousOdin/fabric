import { useEffect, useState } from "react";
import { AlertTriangle, Brain, Cpu, Settings2, Star } from "lucide-react";
import { api } from "@/lib/api";
import type {
  AuxiliaryModelsResponse,
  ModelsAnalyticsModelEntry,
  MoaConfigResponse,
} from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { ModelReloadConfirm } from "@/components/ModelReloadConfirm";
import { LocalOllamaSetupCard } from "@/components/LocalOllamaSetupCard";
import { useI18n } from "@/i18n";
import { AuxiliaryTasksModal } from "./AuxiliaryTasksModal";
import { MoaModelsModal } from "./MoaModelsModal";
import { CapabilityBadges } from "./CapabilityChips";
import { AUX_TASKS, shortModelName } from "./aux-tasks";

type PickerTarget = { kind: "main" } | { kind: "aux"; task: string };

const ROW_CN =
  "flex min-w-0 flex-col gap-2 bg-muted/20 border border-border/50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3";

/**
 * The page's assignment surface (M2) — "what model is the agent running",
 * legible above the fold before any analytics. Evolves the old
 * `ModelSettingsPanel` into the explicit loadout hero: main row (with
 * capability chips resolved from the already-fetched analytics match),
 * auxiliary summary (override list in `title`, M3), MoA summary, and the
 * local Ollama runtime rows inlined (M2 — loadout setup, not credential
 * management; discovery stays explicit, N14).
 *
 * Assignment logic is frozen (N16): `ModelPickerDialog` internals, the
 * expensive-model `confirm_required` round-trip, `ModelReloadConfirm`, aux
 * `__reset__` semantics, MoA preset CRUD, and the "applies to new
 * sessions" contract are all bit-for-bit the pre-split flows.
 */
export function LoadoutCard({
  aux,
  auxFailed,
  mainCapabilities,
  refreshKey,
  onSaved,
}: {
  aux: AuxiliaryModelsResponse | null;
  /** True when `/api/model/auxiliary` failed — rows render `(unset)` plus
   *  a one-line inline warning instead of silently blank (M11). */
  auxFailed: boolean;
  /** Capabilities of the analytics entry matching the main slot, when
   *  resolvable from already-fetched data (M2 — no new fetch). */
  mainCapabilities: ModelsAnalyticsModelEntry["capabilities"] | null;
  refreshKey: number;
  onSaved(): void;
}) {
  const { t } = useI18n();
  const L = t.models.loadout;
  const [auxModalOpen, setAuxModalOpen] = useState(false);
  const [moaModalOpen, setMoaModalOpen] = useState(false);
  const [moa, setMoa] = useState<MoaConfigResponse | null>(null);
  const [picker, setPicker] = useState<PickerTarget | null>(null);
  const [pendingReloadModel, setPendingReloadModel] = useState<string | null>(
    null,
  );

  const mainProv = aux?.main.provider ?? "";
  const mainModel = aux?.main.model ?? "";
  const unset = L?.unset ?? "(unset)";

  useEffect(() => {
    api.getMoaModels().then(setMoa).catch(() => setMoa(null));
  }, [refreshKey]);

  const applyAssignment = async ({
    scope,
    task,
    provider,
    model,
    confirmExpensiveModel,
  }: {
    confirmExpensiveModel?: boolean;
    scope: "main" | "auxiliary";
    task: string;
    provider: string;
    model: string;
  }) => {
    const result = await api.setModelAssignment({
      confirm_expensive_model: confirmExpensiveModel,
      scope,
      task,
      provider,
      model,
    });
    if (!result.confirm_required) onSaved();
    return result;
  };

  // Aux tasks with explicit overrides ("auto" = use the main model).
  const auxOverrides =
    aux?.tasks.filter((a) => a.provider && a.provider !== "auto") ?? [];
  const auxOverrideCount = auxOverrides.length;
  // M3: hover answers "which overrides" without opening the modal.
  const auxTitle =
    auxOverrideCount > 0
      ? auxOverrides
          .map(
            (a) =>
              `${a.task} → ${a.provider}/${a.model || "(provider default)"}`,
          )
          .join(", ")
      : undefined;

  return (
    <Card className="min-w-0 max-w-full overflow-hidden">
      <CardHeader className="min-w-0 pb-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <Settings2 className="h-4 w-4 shrink-0 text-muted-foreground" />
          {/* Chrome label (G9: uppercase-tracked chrome only). */}
          <CardTitle className="text-display text-xs font-medium uppercase tracking-wider">
            {L?.loadout ?? "loadout"}
          </CardTitle>
          {/* Load-bearing copy — assignments never hot-swap live sessions. */}
          <span className="max-w-full min-w-0 text-xs text-text-secondary [overflow-wrap:anywhere]">
            {L?.appliesToNewSessions ?? "applies to new sessions"}
          </span>
        </div>
      </CardHeader>

      <CardContent className="min-w-0 space-y-3 pt-3">
        {auxFailed && (
          <div className="flex items-center gap-2 border border-warning/30 bg-warning/[0.04] px-3 py-1.5 text-xs text-muted-foreground">
            <AlertTriangle
              aria-hidden="true"
              className="h-3.5 w-3.5 shrink-0 text-warning"
            />
            <span className="min-w-0 flex-1">
              {L?.auxUnavailable ??
                "Couldn't load model assignments — slots show (unset) until they refresh."}
            </span>
          </div>
        )}

        {/* Main row (hero) */}
        <div className={ROW_CN}>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-0.5">
              <Star className="h-3 w-3 text-primary" />
              <span className="text-display text-xs font-medium tracking-wider">
                {L?.mainModel ?? "Main model"}
              </span>
            </div>
            <div
              className="text-xs font-mono text-text-secondary truncate"
              title={
                mainProv && mainModel ? `${mainProv} · ${mainModel}` : undefined
              }
            >
              {mainProv || <span className="italic text-text-tertiary">{unset}</span>}
              {mainProv && mainModel && " · "}
              {mainModel || <span className="italic text-text-tertiary">{unset}</span>}
            </div>
            {mainCapabilities && (
              <div className="mt-1.5">
                <CapabilityBadges capabilities={mainCapabilities} />
              </div>
            )}
          </div>
          <Button
            size="sm"
            onClick={() => setPicker({ kind: "main" })}
            className="shrink-0 self-start text-xs uppercase sm:self-center"
          >
            Change
          </Button>
        </div>

        {/* Auxiliary tasks summary + open modal */}
        <div className={ROW_CN} title={auxTitle}>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-0.5">
              <Cpu className="h-3 w-3 text-text-tertiary" />
              <span className="text-display text-xs font-medium tracking-wider">
                {L?.auxiliaryTasks ?? "Auxiliary tasks"}
              </span>
            </div>
            <div className="text-xs font-mono tabular-nums text-text-secondary truncate">
              {auxOverrideCount > 0
                ? `${auxOverrideCount} override${auxOverrideCount > 1 ? "s" : ""} · ${AUX_TASKS.length - auxOverrideCount} auto`
                : `${AUX_TASKS.length} tasks · all auto`}
            </div>
          </div>
          <Button
            size="sm"
            outlined
            onClick={() => setAuxModalOpen(true)}
            className="shrink-0 self-start text-xs uppercase sm:self-center"
          >
            Configure
          </Button>
        </div>

        {/* Mixture of Agents row */}
        <div className={ROW_CN}>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-0.5">
              <Brain className="h-3 w-3 text-text-tertiary" />
              <span className="text-display text-xs font-medium tracking-wider">
                {L?.mixtureOfAgents ?? "Mixture of Agents"}
              </span>
            </div>
            <div className="text-xs font-mono tabular-nums text-text-secondary truncate">
              {moa
                ? `${moa.reference_models.length} reference${moa.reference_models.length === 1 ? "" : "s"} · ${moa.aggregator.provider}/${shortModelName(moa.aggregator.model)}`
                : "not loaded"}
            </div>
          </div>
          <Button
            size="sm"
            outlined
            onClick={() => setMoaModalOpen(true)}
            disabled={!moa}
            className="shrink-0 self-start text-xs uppercase sm:self-center"
          >
            Configure
          </Button>
        </div>

        {/* Local runtime row group (M2): renders only when
            `GET /api/providers/local` returns rows; explicit-discovery
            behavior verbatim (N14). */}
        <LocalOllamaSetupCard
          embedded
          onConfigured={onSaved}
          refreshKey={refreshKey}
        />

        {picker && (
          <ModelPickerDialog
            key={`picker-${refreshKey}`}
            loader={api.getModelOptions}
            alwaysGlobal
            title="Set Main Model"
            onApply={async ({ provider, model, confirmExpensiveModel }) => {
              const result = await applyAssignment({
                confirmExpensiveModel,
                scope: "main",
                task: "",
                provider,
                model,
              });
              if (!result.confirm_required) {
                setPendingReloadModel(model.split("/").slice(-1)[0]);
              }
              return result;
            }}
            onClose={() => setPicker(null)}
          />
        )}

        {auxModalOpen && (
          <AuxiliaryTasksModal
            aux={aux}
            refreshKey={refreshKey}
            onSaved={onSaved}
            onClose={() => setAuxModalOpen(false)}
          />
        )}

        <ModelReloadConfirm
          model={pendingReloadModel}
          onCancel={() => setPendingReloadModel(null)}
        />
        {moaModalOpen && moa && (
          <MoaModelsModal
            config={moa}
            refreshKey={refreshKey}
            onSaved={(next) => {
              setMoa(next);
              onSaved();
            }}
            onClose={() => setMoaModalOpen(false)}
          />
        )}
      </CardContent>
    </Card>
  );
}
