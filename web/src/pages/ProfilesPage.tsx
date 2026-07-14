import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { useProfileScope } from "@/contexts/useProfileScope";
import { Check, Users } from "lucide-react";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { api } from "@/lib/api";
import type { ActiveProfileInfo, ProfileInfo } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { EmptyState, Skeleton } from "@/components/ui";
import { ProfileCard } from "@/components/profiles/ProfileCard";
import {
  ProfileCreateModal,
  type ModelChoice,
} from "@/components/profiles/ProfileCreateModal";
import {
  ProfileEditorDialog,
  type ProfileEditorKind,
} from "@/components/profiles/ProfileEditorDialog";
import { PROFILE_NAME_RE } from "@/components/profiles/profile-name";

export default function ProfilesPage() {
  const navigate = useNavigate();
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [activeInfo, setActiveInfo] = useState<ActiveProfileInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setEnd } = usePageHeader();
  const { setProfile } = useProfileScope();

  // Locale strings with English fallbacks. The enriched keys are optional in
  // the i18n type so untranslated locales don't break the build — they render
  // the English literal until translated.
  const L = useMemo(() => {
    const p = t.profiles;
    return {
      activeProfile: p.activeProfile ?? "Active profile",
      activeBadge: p.activeBadge ?? "active",
      setActive: p.setActive ?? "Set as active",
      activeSet: p.activeSet ?? "Active profile set",
      gatewayRunning: p.gatewayRunning ?? "Gateway running",
      gatewayStopped: p.gatewayStopped ?? "Gateway stopped",
      gatewayRunningWarning:
        p.gatewayRunningWarning ??
        "This profile's gateway is running — it will be stopped.",
      aliasBadge: p.aliasBadge ?? "alias",
      description: p.description ?? "Description",
      descriptionPlaceholder:
        p.descriptionPlaceholder ??
        "What is this profile good at? Used to route kanban tasks by role.",
      noDescription: p.noDescription ?? "No description",
      editDescription: p.editDescription ?? "Edit description",
      descriptionSaved: p.descriptionSaved ?? "Description saved",
      reviewBadge: p.reviewBadge ?? "review",
      autoGenerate: p.autoGenerate ?? "Auto-generate",
      generating: p.generating ?? "Generating…",
      describeFailed: p.describeFailed ?? "Could not generate description",
      modelLoading: p.modelLoading ?? "Loading models…",
      modelNone:
        p.modelNone ?? "No authenticated providers — set a key first",
      editModel: p.editModel ?? "Change model",
      modelSaved: p.modelSaved ?? "Model updated",
      modelSelect: p.modelSelect ?? "Select a model",
      actions: p.actions ?? "Actions",
      manageSkills: p.manageSkills ?? "Manage skills & tools",
      activeSetHint:
        p.activeSetHint ??
        "Dashboard switched to manage {name}. New CLI/gateway runs will use this profile too.",
      // PR1 active-vs-current legibility: verified backend semantics (§0.5) —
      // `active` is the sticky default POST /api/profiles/active writes;
      // `current` is the profile this dashboard process is scoped to.
      activeVsCurrentTitle:
        p.activeVsCurrentTitle ??
        "Active is the sticky default new CLI/gateway runs use; current is the profile this dashboard process is scoped to.",
      loadFailed: p.loadFailed ?? "Could not load profiles",
    };
  }, [t.profiles]);

  // Create modal open state (field drafts live inside ProfileCreateModal).
  const [createModalOpen, setCreateModalOpen] = useState(false);
  // Model picker (lazy-loaded the first time a picker is opened). Choices are
  // shared between the create modal and the model editor dialog.
  const [modelChoices, setModelChoices] = useState<ModelChoice[] | null>(null);
  const modelChoicesLoading = useRef(false);

  // Inline rename state
  const [renamingFrom, setRenamingFrom] = useState<string | null>(null);
  const [renameTo, setRenameTo] = useState("");

  // Inline SOUL editor state
  const [editingSoulFor, setEditingSoulFor] = useState<string | null>(null);
  const [soulText, setSoulText] = useState("");
  const [soulLoading, setSoulLoading] = useState(false);
  const [soulSaving, setSoulSaving] = useState(false);
  // Tracks the latest SOUL request so out-of-order responses don't overwrite
  // newer state when the user switches profiles or closes the editor.
  const activeSoulRequest = useRef<string | null>(null);

  // Inline description editor state
  const [editingDescFor, setEditingDescFor] = useState<string | null>(null);
  const [descText, setDescText] = useState("");
  const [descSaving, setDescSaving] = useState(false);
  const [describing, setDescribing] = useState(false);
  // Tracks the latest description request (save / auto-describe) so a late
  // response can't overwrite state for a different, newly-opened editor.
  const activeDescRequest = useRef<string | null>(null);
  // Counts in-flight save / auto-describe requests so the saving indicator
  // is only cleared when the last concurrent request settles.
  const descSavingCount = useRef(0);
  const describingCount = useRef(0);

  // Inline model editor state
  const [editingModelFor, setEditingModelFor] = useState<string | null>(null);
  const [modelEditChoice, setModelEditChoice] = useState("");
  const [modelSaving, setModelSaving] = useState(false);

  // Per-profile "set active" in-flight name
  const [settingActive, setSettingActive] = useState<string | null>(null);

  const modelKey = (provider: string | null, model: string | null) =>
    provider && model ? `${provider}\u0000${model}` : "";

  const loadModelChoices = useCallback(() => {
    if (modelChoices !== null || modelChoicesLoading.current) return;
    modelChoicesLoading.current = true;
    api
      .getModelOptions()
      .then((res) => {
        const flat: ModelChoice[] = [];
        for (const prov of res.providers ?? []) {
          for (const m of prov.models ?? []) {
            flat.push({
              provider: prov.slug,
              model: m,
              label: `${prov.name} · ${m}`,
            });
          }
        }
        setModelChoices(flat);
      })
      .catch(() => setModelChoices([]))
      .finally(() => {
        modelChoicesLoading.current = false;
      });
  }, [modelChoices]);

  const load = useCallback(() => {
    Promise.all([api.getProfiles(), api.getActiveProfile().catch(() => null)])
      .then(([res, active]) => {
        setProfiles(res.profiles);
        setActiveInfo(active);
        setLoadError(null);
      })
      .catch((e) => {
        // PR7: keep the toast, surface a persistent banner + Retry too — a
        // toast over a blank page is not a recoverable state.
        setLoadError(String(e));
        showToast(`${t.status.error}: ${e}`, "error");
      })
      .finally(() => setLoading(false));
  }, [showToast, t.status.error]);

  useEffect(() => {
    load();
  }, [load]);

  // Lazily load the model picker the first time the create modal opens.
  useEffect(() => {
    if (createModalOpen) loadModelChoices();
  }, [createModalOpen, loadModelChoices]);

  const isActive = useCallback(
    (p: ProfileInfo) =>
      activeInfo != null &&
      (activeInfo.active === p.name ||
        (activeInfo.active === "default" && p.is_default)),
    [activeInfo],
  );

  const handleRenameSubmit = async () => {
    if (!renamingFrom) return;
    const target = renameTo.trim();
    if (!target || target === renamingFrom) {
      setRenamingFrom(null);
      setRenameTo("");
      return;
    }
    if (!PROFILE_NAME_RE.test(target)) {
      showToast(`${t.profiles.invalidName}: ${t.profiles.nameRule}`, "error");
      return;
    }
    try {
      await api.renameProfile(renamingFrom, target);
      showToast(`${t.profiles.renamed}: ${renamingFrom} → ${target}`, "success");
      setRenamingFrom(null);
      setRenameTo("");
      load();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const handleSetActive = async (name: string) => {
    setSettingActive(name);
    try {
      // The backend normalizes/validates the name; trust the canonical
      // value it returns rather than the raw input.
      const { active } = await api.setActiveProfile(name);
      setProfile(active);
      showToast(
        `${L.activeSet}: ${active} — ${L.activeSetHint.replace("{name}", active)}`,
        "success",
      );
      setActiveInfo((prev) =>
        prev ? { ...prev, active } : { active, current: active },
      );
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    } finally {
      setSettingActive(null);
    }
  };

  // Closes whichever editor dialog is open (model / description / SOUL).
  const closeEditor = useCallback(() => {
    activeSoulRequest.current = null;
    activeDescRequest.current = null;
    setEditingModelFor(null);
    setEditingDescFor(null);
    setEditingSoulFor(null);
  }, []);

  const openSoulEditor = useCallback(
    async (name: string) => {
      // Re-selecting the action for the already-open editor collapses it,
      // matching the chevron-down affordance in the actions menu.
      if (editingSoulFor === name) {
        closeEditor();
        return;
      }
      setEditingDescFor(null);
      setEditingModelFor(null);
      setEditingSoulFor(name);
      setSoulText("");
      setSoulLoading(true);
      activeSoulRequest.current = name;
      try {
        const soul = await api.getProfileSoul(name);
        if (activeSoulRequest.current === name) {
          setSoulText(soul.content);
          setSoulLoading(false);
        }
      } catch (e) {
        if (activeSoulRequest.current === name) {
          // Close rather than leave an empty editable buffer — saving it
          // would overwrite the profile's real SOUL file with "".
          setEditingSoulFor(null);
          setSoulLoading(false);
          showToast(`${t.status.error}: ${e}`, "error");
        }
      }
    },
    [closeEditor, editingSoulFor, showToast, t.status.error],
  );

  const handleSaveSoul = async (name: string) => {
    setSoulSaving(true);
    try {
      await api.updateProfileSoul(name, soulText);
      showToast(`${t.profiles.soulSaved}: ${name}`, "success");
      activeSoulRequest.current = null;
      setEditingSoulFor(null);
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    } finally {
      setSoulSaving(false);
    }
  };

  const openDescEditor = useCallback(
    (p: ProfileInfo) => {
      if (editingDescFor === p.name) {
        closeEditor();
        return;
      }
      activeDescRequest.current = p.name;
      setEditingSoulFor(null);
      setEditingModelFor(null);
      setEditingDescFor(p.name);
      setDescText(p.description ?? "");
    },
    [closeEditor, editingDescFor],
  );

  const handleSaveDesc = async (name: string) => {
    descSavingCount.current += 1;
    setDescSaving(true);
    activeDescRequest.current = name;
    try {
      const res = await api.updateProfileDescription(name, descText);
      // Profile-list state always reflects the persisted result, but only
      // touch the open editor if it's still showing this profile.
      setProfiles((prev) =>
        prev.map((p) =>
          p.name === name
            ? {
                ...p,
                description: res.description,
                description_auto: res.description_auto,
              }
            : p,
        ),
      );
      if (activeDescRequest.current === name) {
        showToast(`${L.descriptionSaved}: ${name}`, "success");
        setEditingDescFor(null);
      }
    } catch (e) {
      if (activeDescRequest.current === name) {
        showToast(`${t.status.error}: ${e}`, "error");
      }
    } finally {
      descSavingCount.current -= 1;
      if (descSavingCount.current === 0) setDescSaving(false);
    }
  };

  const handleAutoDescribe = async (name: string) => {
    describingCount.current += 1;
    setDescribing(true);
    activeDescRequest.current = name;
    try {
      const res = await api.describeProfileAuto(name);
      const current = activeDescRequest.current === name;
      if (res.ok && res.description != null) {
        if (current) setDescText(res.description);
        setProfiles((prev) =>
          prev.map((p) =>
            p.name === name
              ? {
                  ...p,
                  description: res.description ?? "",
                  description_auto: res.description_auto,
                }
              : p,
          ),
        );
        if (current) showToast(`${L.descriptionSaved}: ${name}`, "success");
      } else if (current) {
        showToast(`${L.describeFailed}: ${res.reason}`, "error");
      }
    } catch (e) {
      if (activeDescRequest.current === name) {
        showToast(`${t.status.error}: ${e}`, "error");
      }
    } finally {
      describingCount.current -= 1;
      if (describingCount.current === 0) setDescribing(false);
    }
  };

  const openModelEditor = useCallback(
    (p: ProfileInfo) => {
      if (editingModelFor === p.name) {
        closeEditor();
        return;
      }
      setEditingSoulFor(null);
      setEditingDescFor(null);
      setEditingModelFor(p.name);
      setModelEditChoice(modelKey(p.provider, p.model));
      loadModelChoices();
    },
    [closeEditor, editingModelFor, loadModelChoices],
  );

  const handleSaveModel = async (name: string) => {
    const picked = modelEditChoice
      ? modelChoices?.find(
          (c) => modelKey(c.provider, c.model) === modelEditChoice,
        )
      : undefined;
    if (!picked) return;
    setModelSaving(true);
    try {
      await api.setProfileModel(name, picked.provider, picked.model);
      showToast(`${L.modelSaved}: ${picked.model}`, "success");
      setProfiles((prev) =>
        prev.map((p) =>
          p.name === name
            ? { ...p, model: picked.model, provider: picked.provider }
            : p,
        ),
      );
      setEditingModelFor(null);
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    } finally {
      setModelSaving(false);
    }
  };

  // Exactly one editor is open at a time; derive which profile + kind so a
  // single dialog can render the right body.
  const editorName = editingModelFor ?? editingDescFor ?? editingSoulFor;
  const editorKind: ProfileEditorKind | null = editingModelFor
    ? "model"
    : editingDescFor
      ? "desc"
      : editingSoulFor
        ? "soul"
        : null;

  const handleCopyTerminalCommand = async (name: string) => {
    let cmd: string;
    try {
      const res = await api.getProfileSetupCommand(name);
      cmd = res.command;
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
      return;
    }
    try {
      await navigator.clipboard.writeText(cmd);
      showToast(`${t.profiles.commandCopied}: ${cmd}`, "success");
    } catch {
      showToast(`${t.profiles.copyFailed}: ${cmd}`, "error");
    }
  };

  const profileDelete = useConfirmDelete<string>({
    onDelete: useCallback(
      async (name: string) => {
        try {
          await api.deleteProfile(name);
          showToast(`${t.profiles.deleted}: ${name}`, "success");
          load();
        } catch (e) {
          showToast(`${t.status.error}: ${e}`, "error");
          throw e;
        }
      },
      [load, showToast, t.profiles.deleted, t.status.error],
    ),
  });

  const pendingName = profileDelete.pendingId;
  const pendingProfile = pendingName
    ? profiles.find((p) => p.name === pendingName)
    : undefined;
  const deleteMessage = (() => {
    if (!pendingName) return t.profiles.confirmDeleteMessage;
    const base = t.profiles.confirmDeleteMessage.replace("{name}", pendingName);
    return pendingProfile?.gateway_running
      ? `${base}\n\n${L.gatewayRunningWarning}`
      : base;
  })();

  // Put "Build" (full builder) + "Create" (quick modal) buttons in header
  useLayoutEffect(() => {
    setEnd(
      <div className="flex items-center gap-2">
        <Button
          className="uppercase"
          size="sm"
          outlined
          onClick={() => navigate("/profiles/new")}
        >
          Build
        </Button>
        <Button
          className="uppercase"
          size="sm"
          onClick={() => setCreateModalOpen(true)}
        >
          {t.common.create}
        </Button>
      </div>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, t.common.create, loading, navigate]);

  if (loading) {
    // PR7/G13: layout-shaped Skeleton (banner line + identity-card grid)
    // instead of the bespoke braille spinner — token bars, motion-reduce safe.
    return (
      <div aria-busy="true" aria-live="polite" className="flex flex-col gap-6">
        <span className="sr-only">{t.common.loading}</span>

        <Skeleton variant="block" className="h-12" />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} variant="block" className="h-40" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={profileDelete.isOpen}
        onCancel={profileDelete.cancel}
        onConfirm={profileDelete.confirm}
        title={t.profiles.confirmDeleteTitle}
        description={deleteMessage}
        loading={profileDelete.isDeleting}
      />

      <ProfileCreateModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        profiles={profiles}
        modelChoices={modelChoices}
        onCreated={load}
        showToast={showToast}
      />

      {/* PR7: load failure keeps the toast and gains a persistent banner + Retry. */}
      {loadError && (
        <div className="flex flex-wrap items-center justify-between gap-2 border border-destructive/40 bg-destructive/10 px-3 py-2">
          <p className="text-xs text-destructive">
            {L.loadFailed}: {loadError}
          </p>
          <Button outlined size="sm" onClick={load}>
            {t.common.retry}
          </Button>
        </div>
      )}

      {/* Active identity banner (PR1): `active` = sticky default for new
          runs, `current` = this dashboard's scope — the title spells out the
          distinction (§6.1 decision, copy only). */}
      {activeInfo && (
        <Card>
          <CardContent
            className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3 text-xs"
            title={L.activeVsCurrentTitle}
          >
            <span className="flex items-center gap-2 text-muted-foreground">
              <Check className="h-3.5 w-3.5 text-success" />

              <span>
                {L.activeProfile}:{" "}
                <span className="font-medium text-foreground">
                  {activeInfo.active}
                </span>
              </span>
            </span>

            {activeInfo.current !== activeInfo.active && (
              <span className="font-mono text-muted-foreground/80">
                ({activeInfo.current})
              </span>
            )}
          </CardContent>
        </Card>
      )}

      {/* Identity roster (PR2) */}
      <div className="flex flex-col gap-3">
        <H2
          variant="sm"
          className="flex items-center gap-2 text-muted-foreground"
        >
          <Users className="h-4 w-4" />
          {t.profiles.allProfiles} (
          <span className="tabular-nums">{profiles.length}</span>)
        </H2>

        {profiles.length === 0 && !loadError && (
          <Card>
            <EmptyState
              icon={Users}
              title={t.profiles.noProfiles}
              action={
                <Button
                  className="uppercase"
                  size="sm"
                  onClick={() => setCreateModalOpen(true)}
                >
                  {t.common.create}
                </Button>
              }
            />
          </Card>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {profiles.map((p) => (
            <ProfileCard
              key={p.name}
              profile={p}
              active={isActive(p)}
              settingActive={settingActive === p.name}
              isEditingDesc={editingDescFor === p.name}
              isEditingModel={editingModelFor === p.name}
              isEditingSoul={editingSoulFor === p.name}
              isRenaming={renamingFrom === p.name}
              renameTo={renameTo}
              onRenameToChange={setRenameTo}
              onRenameSubmit={handleRenameSubmit}
              onRenameCancel={() => setRenamingFrom(null)}
              labels={{
                activeBadge: L.activeBadge,
                defaultBadge: t.profiles.defaultBadge,
                aliasBadge: L.aliasBadge,
                hasEnv: t.profiles.hasEnv,
                gatewayRunning: L.gatewayRunning,
                gatewayStopped: L.gatewayStopped,
                noDescription: L.noDescription,
                reviewBadge: L.reviewBadge,
                model: t.profiles.model,
                skills: t.profiles.skills,
                invalidName: t.profiles.invalidName,
                nameRule: t.profiles.nameRule,
                save: t.common.save,
                cancel: t.common.cancel,
              }}
              menuLabels={{
                actions: L.actions,
                setActive: L.setActive,
                editModel: L.editModel,
                editDescription: L.editDescription,
                editSoul: t.profiles.editSoul,
                manageSkills: L.manageSkills,
                openInTerminal: t.profiles.openInTerminal,
                rename: t.profiles.rename,
                delete: t.common.delete,
              }}
              onCopyCommand={() => handleCopyTerminalCommand(p.name)}
              onDelete={() => profileDelete.requestDelete(p.name)}
              onEditDescription={() => openDescEditor(p)}
              onEditModel={() => openModelEditor(p)}
              onEditSoul={() => openSoulEditor(p.name)}
              onManageSkills={() =>
                navigate(`/skills?profile=${encodeURIComponent(p.name)}`)
              }
              onRename={() => {
                setRenamingFrom(p.name);
                setRenameTo(p.name);
              }}
              onSetActive={() => handleSetActive(p.name)}
            />
          ))}
        </div>
      </div>

      {/* Editor dialog — model / description / SOUL for the selected profile */}
      <ProfileEditorDialog
        editorName={editorName}
        editorKind={editorKind}
        onClose={closeEditor}
        labels={{
          editModel: L.editModel,
          description: L.description,
          descriptionPlaceholder: L.descriptionPlaceholder,
          autoGenerate: L.autoGenerate,
          generating: L.generating,
          modelLoading: L.modelLoading,
          modelNone: L.modelNone,
          modelSelect: L.modelSelect,
        }}
        modelChoices={modelChoices}
        modelEditChoice={modelEditChoice}
        onModelEditChoiceChange={setModelEditChoice}
        modelSaving={modelSaving}
        onSaveModel={handleSaveModel}
        descText={descText}
        onDescTextChange={setDescText}
        descSaving={descSaving}
        describing={describing}
        onSaveDesc={handleSaveDesc}
        onAutoDescribe={handleAutoDescribe}
        soulText={soulText}
        onSoulTextChange={setSoulText}
        soulLoading={soulLoading}
        soulSaving={soulSaving}
        onSaveSoul={handleSaveSoul}
      />
    </div>
  );
}
