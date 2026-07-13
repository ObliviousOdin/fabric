import { useMemo, useState } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import type { ProfileInfo } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Checkbox } from "@nous-research/ui/ui/components/checkbox";
import { useI18n } from "@/i18n";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { cn, themedBody } from "@/lib/utils";
import { PROFILE_NAME_RE } from "./profile-name";

export interface ModelChoice {
  provider: string;
  model: string;
  label: string;
}

export interface ProfileCreateModalProps {
  open: boolean;
  onClose: () => void;
  profiles: ProfileInfo[];
  /** Lazily loaded by the page (shared with the model editor); null = loading. */
  modelChoices: ModelChoice[] | null;
  onCreated: () => void;
  showToast: (message: string, kind: "success" | "error") => void;
}

/**
 * PR3 — the create/clone modal, behavior frozen: `PROFILE_NAME_RE` mirror,
 * clone-from select (default preselected, "none" branch), clone-all only when
 * cloning, no-skills only when not cloning, optional description, lazy model
 * picker ("\u0000" composite keys), `model_set === false` follow-up warning
 * toast, field reset on success. The component stays mounted while closed so
 * draft fields survive open/close exactly as before the split.
 */
export function ProfileCreateModal({
  open,
  onClose,
  profiles,
  modelChoices,
  onCreated,
  showToast,
}: ProfileCreateModalProps) {
  const { t } = useI18n();

  // Locale strings with English fallbacks (O5 pattern) — optional keys render
  // the English literal until translated.
  const L = useMemo(() => {
    const p = t.profiles;
    return {
      descriptionPlaceholder:
        p.descriptionPlaceholder ??
        "What is this profile good at? Used to route kanban tasks by role.",
      advancedOptions: p.advancedOptions ?? "Advanced options",
      cloneAll:
        p.cloneAll ?? "Clone everything (memories, sessions, skills, state)",
      noSkillsOption: p.noSkillsOption ?? "Don't seed bundled skills",
      descriptionOptional: p.descriptionOptional ?? "Description (optional)",
      modelOptional: p.modelOptional ?? "Model (optional)",
      modelInherit: p.modelInherit ?? "Inherit from clone / default",
      modelLoading: p.modelLoading ?? "Loading models…",
      modelNone: p.modelNone ?? "No authenticated providers — set a key first",
    };
  }, [t.profiles]);

  const [newName, setNewName] = useState("");
  const [cloneFrom, setCloneFrom] = useState<string | null>("default");
  const [cloneAll, setCloneAll] = useState(false);
  const [noSkills, setNoSkills] = useState(false);
  const [newDescription, setNewDescription] = useState("");
  const [creating, setCreating] = useState(false);
  // modelChoice is a "slug\u0000model" key, or "" to inherit from clone/default.
  const [modelChoice, setModelChoice] = useState("");

  const modalRef = useModalBehavior({ open, onClose });

  const cloning = cloneFrom !== null;

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) {
      showToast(t.profiles.nameRequired, "error");
      return;
    }
    if (!PROFILE_NAME_RE.test(name)) {
      showToast(`${t.profiles.invalidName}: ${t.profiles.nameRule}`, "error");
      return;
    }
    setCreating(true);
    try {
      const picked = modelChoice
        ? modelChoices?.find(
            (c) => `${c.provider}\u0000${c.model}` === modelChoice,
          )
        : undefined;
      const res = await api.createProfile({
        name,
        clone_from: cloneFrom,
        clone_all: cloning && cloneAll,
        no_skills: cloning ? false : noSkills,
        description: newDescription.trim() || undefined,
        provider: picked?.provider,
        model: picked?.model,
      });
      showToast(`${t.profiles.created}: ${name}`, "success");
      if (picked && res.model_set === false) {
        showToast(
          `Profile created, but the model could not be saved — set it from the profile editor.`,
          "error",
        );
      }
      setNewName("");
      setNewDescription("");
      setNoSkills(false);
      setCloneAll(false);
      setCloneFrom("default");
      setModelChoice("");
      onClose();
      onCreated();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  if (!open) return null;

  return (
    <div
      ref={modalRef}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-profile-title"
    >
      <div
        className={cn(
          themedBody,
          "relative w-full max-w-md border border-border bg-card shadow-2xl flex flex-col max-h-[90vh]",
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
            id="create-profile-title"
            className="font-mondwest text-display text-base tracking-wider"
          >
            {t.profiles.newProfile}
          </h2>
        </header>

        <div className="min-h-0 overflow-y-auto p-5 grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="profile-name">{t.profiles.name}</Label>

            <Input
              id="profile-name"
              autoFocus
              placeholder={t.profiles.namePlaceholder}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
              }}
              aria-invalid={
                newName.trim() !== "" && !PROFILE_NAME_RE.test(newName.trim())
              }
            />

            <p className="text-xs text-muted-foreground">
              {t.profiles.nameRule}
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="clone-from">{t.profiles.cloneFrom}</Label>
            <Select
              id="clone-from"
              value={cloneFrom ?? ""}
              onValueChange={(v) => {
                const next = v || null;
                setCloneFrom(next);
                if (next === null) setCloneAll(false);
              }}
            >
              <SelectOption value="">{t.profiles.cloneFromNone}</SelectOption>
              {profiles.map((profile) => (
                <SelectOption key={profile.name} value={profile.name}>
                  {profile.name}
                </SelectOption>
              ))}
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="profile-description">{L.descriptionOptional}</Label>

            <textarea
              id="profile-description"
              className="flex min-h-[64px] w-full border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              placeholder={L.descriptionPlaceholder}
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="profile-model">{L.modelOptional}</Label>

            <Select
              id="profile-model"
              value={modelChoice}
              disabled={modelChoices === null}
              onValueChange={setModelChoice}
            >
              <SelectOption value="">
                {modelChoices === null ? L.modelLoading : L.modelInherit}
              </SelectOption>

              {(modelChoices ?? []).map((c) => (
                <SelectOption
                  key={`${c.provider}\u0000${c.model}`}
                  value={`${c.provider}\u0000${c.model}`}
                >
                  {c.label}
                </SelectOption>
              ))}
            </Select>

            {modelChoices !== null && modelChoices.length === 0 && (
              <p className="text-xs text-muted-foreground">{L.modelNone}</p>
            )}
          </div>

          <fieldset className="grid gap-3 border-t border-border pt-4">
            <legend className="font-mondwest text-display text-xs tracking-wider text-muted-foreground">
              {L.advancedOptions}
            </legend>

            <div className="flex items-center gap-2.5">
              <Checkbox
                checked={cloneAll}
                disabled={!cloning}
                id="clone-all"
                onCheckedChange={(checked) => setCloneAll(checked === true)}
              />

              <Label
                className={cn(
                  "font-mondwest normal-case tracking-normal text-sm cursor-pointer",
                  !cloning && "opacity-50",
                )}
                htmlFor="clone-all"
              >
                {L.cloneAll}
              </Label>
            </div>

            <div className="flex items-center gap-2.5">
              <Checkbox
                checked={noSkills}
                id="no-skills"
                disabled={cloning}
                onCheckedChange={(checked) => setNoSkills(checked === true)}
              />

              <Label
                className={cn(
                  "font-mondwest normal-case tracking-normal text-sm cursor-pointer",
                  cloning && "opacity-50",
                )}
                htmlFor="no-skills"
              >
                {L.noSkillsOption}
              </Label>
            </div>
          </fieldset>

          <div className="flex justify-end">
            <Button
              className="uppercase"
              size="sm"
              onClick={handleCreate}
              disabled={creating}
            >
              {creating ? t.common.creating : t.common.create}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
