import { Sparkles, X } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { useI18n } from "@/i18n";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { cn, themedBody } from "@/lib/utils";
import type { ModelChoice } from "./ProfileCreateModal";

export type ProfileEditorKind = "model" | "desc" | "soul";

export interface ProfileEditorLabels {
  editModel: string;
  description: string;
  descriptionPlaceholder: string;
  autoGenerate: string;
  generating: string;
  modelLoading: string;
  modelNone: string;
  modelSelect: string;
}

export interface ProfileEditorDialogProps {
  /** Profile the open editor targets; null renders nothing. */
  editorName: string | null;
  editorKind: ProfileEditorKind | null;
  onClose: () => void;
  labels: ProfileEditorLabels;
  // Model editor (PR5): choices shared with the create modal, page-owned.
  modelChoices: ModelChoice[] | null;
  modelEditChoice: string;
  onModelEditChoiceChange: (value: string) => void;
  modelSaving: boolean;
  onSaveModel: (name: string) => void;
  // Description editor (PR5): saving/auto-describe in-flight state is owned
  // by the page (per-request refs + concurrent counters live there).
  descText: string;
  onDescTextChange: (value: string) => void;
  descSaving: boolean;
  describing: boolean;
  onSaveDesc: (name: string) => void;
  onAutoDescribe: (name: string) => void;
  // SOUL editor (PR5): lazy fetch + stale-request guard live in the page.
  soulText: string;
  onSoulTextChange: (value: string) => void;
  /** True while the SOUL content fetch is in flight — editing and Save are
   *  blocked so a not-yet-loaded (empty) buffer can't be saved over the
   *  profile's real SOUL file. */
  soulLoading: boolean;
  soulSaving: boolean;
  onSaveSoul: (name: string) => void;
}

/**
 * PR5 — the single editor dialog (model / description / SOUL). Purely
 * presentational: exactly-one-open derivation, request-guarding refs and all
 * save flows stay in the page so the split can't perturb their semantics.
 */
export function ProfileEditorDialog({
  editorName,
  editorKind,
  onClose,
  labels: L,
  modelChoices,
  modelEditChoice,
  onModelEditChoiceChange,
  modelSaving,
  onSaveModel,
  descText,
  onDescTextChange,
  descSaving,
  describing,
  onSaveDesc,
  onAutoDescribe,
  soulText,
  onSoulTextChange,
  soulLoading,
  soulSaving,
  onSaveSoul,
}: ProfileEditorDialogProps) {
  const { t } = useI18n();
  const editorModalRef = useModalBehavior({
    open: editorName != null,
    onClose,
  });

  if (!editorName || !editorKind) return null;

  return (
    <div
      ref={editorModalRef}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="profile-editor-title"
    >
      <div
        className={cn(
          themedBody,
          "relative w-full max-w-lg border border-border bg-card shadow-2xl flex flex-col max-h-[90vh]",
        )}
      >
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
          <h2
            id="profile-editor-title"
            className="font-mondwest text-display text-base tracking-wider"
          >
            {editorKind === "model"
              ? L.editModel
              : editorKind === "desc"
                ? L.description
                : t.profiles.soulSection}
            <span className="text-muted-foreground"> · {editorName}</span>
          </h2>
        </header>

        <div
          className={cn(
            "p-5 grid gap-4",
            editorKind === "soul" && "min-h-0 overflow-y-auto",
          )}
        >
          {editorKind === "model" &&
            (modelChoices !== null && modelChoices.length === 0 ? (
              <p className="text-xs text-muted-foreground">{L.modelNone}</p>
            ) : (
              <>
                <Select
                  value={modelEditChoice}
                  disabled={modelChoices === null}
                  placeholder={
                    modelChoices === null ? L.modelLoading : L.modelSelect
                  }
                  onValueChange={onModelEditChoiceChange}
                >
                  {(modelChoices ?? []).map((c) => (
                    <SelectOption
                      key={`${c.provider}\u0000${c.model}`}
                      value={`${c.provider}\u0000${c.model}`}
                    >
                      {c.label}
                    </SelectOption>
                  ))}
                </Select>

                <div className="flex justify-end">
                  <Button
                    size="sm"
                    className="uppercase"
                    onClick={() => onSaveModel(editorName)}
                    disabled={
                      modelSaving ||
                      !modelChoices?.some(
                        (c) =>
                          `${c.provider}\u0000${c.model}` === modelEditChoice,
                      )
                    }
                  >
                    {modelSaving ? t.common.saving : t.common.save}
                  </Button>
                </div>
              </>
            ))}

          {editorKind === "desc" && (
            <>
              <div className="flex items-center justify-between gap-2">
                <Label
                  htmlFor="profile-desc-editor"
                  className="font-mondwest text-display text-xs tracking-wider text-muted-foreground"
                >
                  {L.description}
                </Label>

                <Button
                  size="sm"
                  ghost
                  className="gap-1.5"
                  disabled={describing}
                  onClick={() => onAutoDescribe(editorName)}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {describing ? L.generating : L.autoGenerate}
                </Button>
              </div>

              <textarea
                id="profile-desc-editor"
                className="flex min-h-[96px] w-full border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder={L.descriptionPlaceholder}
                value={descText}
                onChange={(e) => onDescTextChange(e.target.value)}
              />

              <div className="flex justify-end">
                <Button
                  size="sm"
                  className="uppercase"
                  onClick={() => onSaveDesc(editorName)}
                  disabled={descSaving}
                >
                  {descSaving ? t.common.saving : t.common.save}
                </Button>
              </div>
            </>
          )}

          {editorKind === "soul" && (
            <>
              <Label
                htmlFor="profile-soul-editor"
                className="font-mondwest text-display text-xs tracking-wider text-muted-foreground"
              >
                {t.profiles.soulSection}
              </Label>

              <textarea
                id="profile-soul-editor"
                className="flex min-h-[280px] w-full border border-input bg-transparent px-3 py-2 text-sm font-mono shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
                placeholder={
                  soulLoading ? t.common.loading : t.profiles.soulPlaceholder
                }
                value={soulText}
                onChange={(e) => onSoulTextChange(e.target.value)}
                disabled={soulLoading}
              />

              <div className="flex justify-end">
                <Button
                  size="sm"
                  className="uppercase"
                  onClick={() => onSaveSoul(editorName)}
                  disabled={soulSaving || soulLoading}
                >
                  {soulSaving ? t.common.saving : t.common.save}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
