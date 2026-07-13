import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AlertTriangle,
  Filter,
  Package,
  Plus,
  Search,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SkillInfo, ToolsetInfo } from "@/lib/api";
import { useProfileScope } from "@/contexts/useProfileScope";
import { ToolsetConfigDrawer } from "@/components/ToolsetConfigDrawer";
import { SkillEditorDialog } from "@/components/SkillEditorDialog";
import { HubBrowser } from "@/components/skills/HubBrowser";
import { LearnSkillDialog } from "@/components/skills/LearnSkillDialog";
import { SkillListRow } from "@/components/skills/SkillListRow";
import { ToolsetRow } from "@/components/skills/ToolsetRow";
import {
  PROVENANCE_ORDER,
  prettyCategory,
} from "@/components/skills/skills-meta";
import {
  EmptyState,
  Skeleton,
  toolsetCapabilityState,
} from "@/components/ui";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Toast } from "@nous-research/ui/ui/components/toast";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { ListItem } from "@nous-research/ui/ui/components/list-item";
import { cn } from "@/lib/utils";
import { Input } from "@nous-research/ui/ui/components/input";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";

/* ------------------------------------------------------------------ */
/*  SKILLS page — "what the agent knows" (spec K1–K11)                 */
/*                                                                     */
/*  Rows render in the shared CapabilityRow five-zone grammar (CAP1/   */
/*  CAP3); provenance (hub/bundled/agent) is surfaced as rail filter   */
/*  chips + per-row chips (K2/K4); skill `usage` and the best-effort   */
/*  toolset call join are the honest, in-place usage evidence (CAP7).  */
/* ------------------------------------------------------------------ */

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [toolsets, setToolsets] = useState<ToolsetInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"skills" | "toolsets" | "hub">("skills");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  // K2: provenance filter — radio-toggle like categories.
  const [activeProvenance, setActiveProvenance] = useState<string | null>(null);
  const [togglingSkills, setTogglingSkills] = useState<Set<string>>(new Set());
  const [configToolset, setConfigToolset] = useState<ToolsetInfo | null>(null);
  // Skill editor dialog: open + which skill is being edited (null = create).
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorSkill, setEditorSkill] = useState<string | null>(null);
  const [learnOpen, setLearnOpen] = useState(false);
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  // Optional i18n group (O5 pattern) — English fallbacks at every call site.
  const inv = t.skills.inventory;

  // ── Profile scoping ──
  // The write target comes from the GLOBAL profile switcher (sidebar) via
  // ProfileContext — one selector for the whole dashboard, deep-linkable
  // as ?profile=<name>. This page just consumes it: the fetchJSON layer
  // appends the param automatically; we still pass it explicitly where the
  // call signature supports it (clearer, and robust if a caller bypasses
  // the auto-injection).
  const {
    profile: selectedProfile,
  } = useProfileScope();

  useEffect(() => {
    // Promise-chain shape: setState fires only inside async callbacks so the
    // effect body stays lint-clean (react-hooks/set-state-in-effect). On a
    // profile switch the old list stays visible until the new one arrives.
    let cancelled = false;
    Promise.all([
      api.getSkills(selectedProfile || undefined),
      api.getToolsets(selectedProfile || undefined),
    ])
      .then(([s, tsets]) => {
        if (cancelled) return;
        setSkills(s);
        setToolsets(tsets);
        setLoadError(false);
      })
      // K11: initial-load failure renders as an in-pane destructive banner
      // + Retry (the old toast mislabeled the error as t.common.loading).
      .catch(() => !cancelled && setLoadError(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [selectedProfile, reloadKey]);

  /* ---- Toolset usage evidence: lazy client-side analytics join ----
   * One `getAnalytics(30)` fetch on first toolsets-view activation
   * (re-fetched on profile switch); per-toolset call counts are the sum of
   * `tools[].count` over each `ToolsetInfo.tools` — the join the server
   * comment prescribes. Best-effort (R14/R20): labeled `~`, caveat in
   * `title`, and a fetch failure degrades to no meta segment. */
  const [toolCallCounts, setToolCallCounts] = useState<Record<
    string,
    number
  > | null>(null);
  const toolCountsProfileRef = useRef<string | null>(null);
  useEffect(() => {
    if (view !== "toolsets") return;
    const profileKey = selectedProfile || "";
    if (toolCountsProfileRef.current === profileKey) return;
    toolCountsProfileRef.current = profileKey;
    // Drop the previous profile's counts while the new join is in flight —
    // otherwise a failed refetch would leave the wrong profile's numbers
    // standing (rows omit the segment until counts resolve, R20).
    setToolCallCounts(null);
    api
      .getAnalytics(30, selectedProfile || undefined)
      .then((r) => {
        const counts: Record<string, number> = {};
        for (const entry of r.tools) counts[entry.tool_name] = entry.count;
        setToolCallCounts(counts);
      })
      .catch((e) => {
        // R20: never let an analytics failure break the toolsets view.
        console.warn("Toolset usage analytics unavailable:", e);
      });
  }, [view, selectedProfile]);

  /* ---- Toggle skill ---- */
  const handleToggleSkill = async (skill: SkillInfo) => {
    setTogglingSkills((prev) => new Set(prev).add(skill.name));
    try {
      await api.toggleSkill(skill.name, !skill.enabled, selectedProfile || undefined);
      setSkills((prev) =>
        prev.map((s) =>
          s.name === skill.name ? { ...s, enabled: !s.enabled } : s,
        ),
      );
      showToast(
        `${skill.name} ${skill.enabled ? t.common.disabled : t.common.enabled}`,
        "success",
      );
    } catch {
      showToast(`${t.common.failedToToggle} ${skill.name}`, "error");
    } finally {
      setTogglingSkills((prev) => {
        const next = new Set(prev);
        next.delete(skill.name);
        return next;
      });
    }
  };

  /* ---- Refresh toolsets after a config change ---- */
  const refreshToolsets = useCallback(async () => {
    try {
      // R19 fix: pass the page's profile scope like the initial load does —
      // without it, a drawer change on a non-default profile refreshed the
      // wrong profile's toolsets.
      const tsets = await api.getToolsets(selectedProfile || undefined);
      setToolsets(tsets);
    } catch {
      /* non-fatal: the drawer already toasted on the failing write */
    }
  }, [selectedProfile]);

  /* ---- Skill editor (create / edit SKILL.md) ---- */
  const openCreateEditor = useCallback(() => {
    setEditorSkill(null);
    setEditorOpen(true);
  }, []);
  const openEditEditor = useCallback((skillName: string) => {
    setEditorSkill(skillName);
    setEditorOpen(true);
  }, []);
  const handleEditorSaved = useCallback(
    (skillName: string) => {
      showToast(`${skillName} saved ✓`, "success");
      // Reload the list so a newly created skill (or an edited description)
      // shows up immediately.
      api
        .getSkills(selectedProfile || undefined)
        .then(setSkills)
        .catch(() => {});
    },
    [selectedProfile, showToast],
  );

  /* ---- Derived data ---- */
  const lowerSearch = search.toLowerCase();
  const isSearching = search.trim().length > 0;

  const provenanceLabelFor = useCallback(
    (provenance: string): string => {
      switch (provenance) {
        case "hub":
          return inv?.provenanceHub ?? "hub";
        case "bundled":
          return inv?.provenanceBundled ?? "bundled";
        case "agent":
          // `agent` is labeled "custom" in UI copy (K2).
          return inv?.provenanceAgent ?? "custom";
        default:
          return provenance; // Unknown value — raw string, never crash (R18).
      }
    },
    [inv],
  );

  const searchMatchedSkills = useMemo(() => {
    if (!isSearching) return [];
    return skills.filter(
      (s) =>
        s.name.toLowerCase().includes(lowerSearch) ||
        s.description.toLowerCase().includes(lowerSearch) ||
        (s.category ?? "").toLowerCase().includes(lowerSearch) ||
        // K3: search additionally matches provenance (raw + display label).
        s.provenance.toLowerCase().includes(lowerSearch) ||
        provenanceLabelFor(s.provenance).toLowerCase().includes(lowerSearch),
    );
  }, [skills, isSearching, lowerSearch, provenanceLabelFor]);

  const activeSkills = useMemo(() => {
    if (isSearching) return [];
    let list = skills;
    if (activeProvenance) {
      list = list.filter((s) => s.provenance === activeProvenance);
    }
    if (activeCategory) {
      list = list.filter((s) =>
        activeCategory === "__none__"
          ? !s.category
          : s.category === activeCategory,
      );
    }
    // Display-only evidence: alphabetical sort kept (K5).
    return [...list].sort((a, b) => a.name.localeCompare(b.name));
  }, [skills, activeCategory, activeProvenance, isSearching]);

  const allCategories = useMemo(() => {
    const cats = new Map<string, number>();
    for (const s of skills) {
      const key = s.category || "__none__";
      cats.set(key, (cats.get(key) || 0) + 1);
    }
    return [...cats.entries()]
      .sort((a, b) => {
        if (a[0] === "__none__") return -1;
        if (b[0] === "__none__") return 1;
        return a[0].localeCompare(b[0]);
      })
      .map(([key, count]) => ({
        key,
        name: prettyCategory(key === "__none__" ? null : key, t.common.general),
        count,
      }));
  }, [skills, t]);

  // K2: provenance chip counts (over all skills, like category counts).
  const provenanceCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of skills) {
      counts[s.provenance] = (counts[s.provenance] || 0) + 1;
    }
    return counts;
  }, [skills]);

  const enabledCount = skills.filter((s) => s.enabled).length;

  useLayoutEffect(() => {
    if (loading) {
      setAfterTitle(null);
      setEnd(null);
      return;
    }
    setAfterTitle(
      <span className="flex items-center gap-2 whitespace-nowrap text-xs text-muted-foreground">
        {t.skills.enabledOf
          .replace("{enabled}", String(enabledCount))
          .replace("{total}", String(skills.length))}
      </span>,
    );
    setEnd(
      <div className="relative w-full min-w-0 sm:max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          className="h-8 rounded-none pl-8 pr-7 text-xs"
          placeholder={t.common.search}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <Button
            ghost
            size="xs"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onClick={() => setSearch("")}
            aria-label={t.common.clear}
          >
            <X />
          </Button>
        )}
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    enabledCount,
    loading,
    search,
    setAfterTitle,
    setEnd,
    skills.length,
    t,
  ]);

  const filteredToolsets = useMemo(() => {
    return toolsets.filter(
      (ts) =>
        !search ||
        ts.name.toLowerCase().includes(lowerSearch) ||
        ts.label.toLowerCase().includes(lowerSearch) ||
        ts.description.toLowerCase().includes(lowerSearch),
    );
  }, [toolsets, search, lowerSearch]);

  /* ---- Row-formatting helpers (i18n with English fallbacks) ---- */
  const usesLabelFor = (usage: number): string | null => {
    if (usage <= 0) return null; // R4: no 0-noise.
    return (inv?.uses ?? "{count} use{s}")
      .replace("{count}", String(usage))
      .replace("{s}", usage !== 1 ? "s" : "");
  };
  const appliesTitle = inv?.appliesNewSessions ?? "Applies to new sessions";
  const toolsLabelFor = (ts: ToolsetInfo): string | null => {
    if (ts.tools.length > 0) {
      return (inv?.toolCount ?? "{count} tool{s}")
        .replace("{count}", String(ts.tools.length))
        .replace("{s}", ts.tools.length !== 1 ? "s" : "");
    }
    // No resolved tools — keep the pre-revamp explanatory copy.
    return ts.enabled
      ? t.skills.toolsetLabel.replace("{name}", ts.name)
      : t.skills.disabledForCli;
  };
  const callsLabelFor = (ts: ToolsetInfo): string | null => {
    if (!toolCallCounts) return null; // Analytics unresolved — omit (R20).
    const sum = ts.tools.reduce(
      (acc, tool) => acc + (toolCallCounts[tool] ?? 0),
      0,
    );
    if (sum <= 0) return null; // R4: no 0-noise.
    return (inv?.callsMeta ?? "~{count} calls · 30d").replace(
      "{count}",
      String(sum),
    );
  };
  const toolsetStateLabelFor = (ts: ToolsetInfo): string | undefined => {
    const cap = t.capabilities;
    if (!cap) return undefined; // English fallback lives in the mapper.
    switch (toolsetCapabilityState(ts).state) {
      case "enabled":
        return cap.active;
      case "needs-setup":
        return cap.needsSetup;
      default:
        return cap.inactive;
    }
  };

  const renderSkillRow = (skill: SkillInfo) => (
    <SkillListRow
      key={skill.name}
      skill={skill}
      toggling={togglingSkills.has(skill.name)}
      onToggle={() => void handleToggleSkill(skill)}
      onEdit={() => openEditEditor(skill.name)}
      noDescriptionLabel={t.skills.noDescription}
      provenanceLabel={provenanceLabelFor(skill.provenance)}
      usesLabel={usesLabelFor(skill.usage)}
      // K4: category segment only when the rail isn't already filtering to it.
      categoryLabel={
        !activeCategory && skill.category
          ? prettyCategory(skill.category, t.common.general)
          : null
      }
      appliesNewSessionsTitle={appliesTitle}
    />
  );

  /* ---- Loading (K9): layout-shaped skeletons, not a page spinner ---- */
  if (loading) {
    return (
      <div
        aria-busy="true"
        className="flex flex-col sm:flex-row sm:items-start gap-4"
      >
        <aside className="sm:w-56 sm:shrink-0">
          <Skeleton variant="block" className="h-48" />
        </aside>
        <div className="flex-1 min-w-0 pt-1">
          <Skeleton
            variant="row-list"
            rows={view === "toolsets" ? 4 : 8}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PluginSlot name="skills:top" />
      <Toast toast={toast} />

      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        <aside aria-label={t.skills.title} className="sm:w-56 sm:shrink-0">
          <div className="sm:sticky sm:top-0">
            <div className="flex flex-col rounded-none border border-border bg-muted/20">
              <div className="hidden sm:flex items-center gap-2 px-3 py-2 border-b border-border">
                <Filter className="h-3 w-3 text-text-tertiary" />
                <span className="font-mondwest text-display text-xs tracking-[0.12em] text-text-secondary">
                  {t.skills.filters}
                </span>
              </div>

              <div className="flex sm:flex-col gap-1 overflow-x-auto sm:overflow-x-visible scrollbar-none p-2">
                <PanelItem
                  icon={Package}
                  label={`${t.skills.all} (${skills.length})`}
                  active={view === "skills" && !isSearching}
                  onClick={() => {
                    setView("skills");
                    setActiveCategory(null);
                    setActiveProvenance(null);
                    setSearch("");
                  }}
                />
                <PanelItem
                  icon={Wrench}
                  label={`${t.skills.toolsets} (${toolsets.length})`}
                  active={view === "toolsets"}
                  onClick={() => {
                    setView("toolsets");
                    setSearch("");
                  }}
                />
                <PanelItem
                  icon={Search}
                  label="Browse hub"
                  active={view === "hub"}
                  onClick={() => {
                    setView("hub");
                    setSearch("");
                  }}
                />
              </div>

              {/* K2: provenance filter chips (hub / bundled / custom). */}
              {view === "skills" && !isSearching && skills.length > 0 && (
                <div className="hidden sm:flex flex-col border-t border-border">
                  <div className="px-3 pt-2 pb-1 font-mondwest text-display text-xs tracking-[0.12em] text-text-tertiary">
                    {inv?.provenance ?? "Provenance"}
                  </div>
                  <div className="flex flex-wrap gap-1 p-2 pt-1">
                    {PROVENANCE_ORDER.filter((p) => provenanceCounts[p]).map(
                      (p) => {
                        const isActive = activeProvenance === p;
                        return (
                          <button
                            key={p}
                            type="button"
                            aria-pressed={isActive}
                            onClick={() =>
                              setActiveProvenance(isActive ? null : p)
                            }
                            className={cn(
                              "border px-1.5 py-0.5 font-mono-ui text-[0.65rem] tabular-nums transition-colors",
                              isActive
                                ? "border-transparent bg-foreground/90 text-background"
                                : "border-border text-muted-foreground hover:text-foreground",
                            )}
                          >
                            {provenanceLabelFor(p)} ({provenanceCounts[p]})
                          </button>
                        );
                      },
                    )}
                  </div>
                </div>
              )}

              {view === "skills" &&
                !isSearching &&
                allCategories.length > 0 && (
                  <div className="hidden sm:flex flex-col border-t border-border">
                    <div className="px-3 pt-2 pb-1 font-mondwest text-display text-xs tracking-[0.12em] text-text-tertiary">
                      {t.skills.categories}
                    </div>
                    <div className="flex flex-col p-2 pt-1 gap-px max-h-[calc(100vh-340px)] overflow-y-auto">
                      {allCategories.map(({ key, name, count }) => {
                        const isActive = activeCategory === key;

                        return (
                          <ListItem
                            key={key}
                            active={isActive}
                            onClick={() =>
                              setActiveCategory(isActive ? null : key)
                            }
                            className="rounded-none px-2 py-1 text-xs"
                          >
                            <span className="flex-1 truncate">{name}</span>
                            <span
                              className={`text-xs tabular-nums ${
                                isActive
                                  ? "text-text-secondary"
                                  : "text-text-tertiary"
                              }`}
                            >
                              {count}
                            </span>
                          </ListItem>
                        );
                      })}
                    </div>
                  </div>
                )}
            </div>
          </div>
        </aside>

        <div className="flex-1 min-w-0">
          {/* K11: load failure — destructive banner + Retry in the pane. */}
          {loadError && (
            <div className="mb-3 flex flex-wrap items-center gap-3 border border-destructive/30 bg-destructive/[0.06] px-3 py-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
              <span className="min-w-0 flex-1 text-sm text-destructive">
                {inv?.loadFailed ?? "Failed to load skills and toolsets"}
              </span>
              <Button
                outlined
                size="sm"
                onClick={() => setReloadKey((k) => k + 1)}
              >
                {t.common.retry}
              </Button>
            </div>
          )}

          {isSearching ? (
            <Card className="rounded-none">
              <CardHeader className="py-3 px-4">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Search className="h-4 w-4" />
                    {t.skills.title}
                  </CardTitle>
                  <Badge tone="secondary" className="text-xs">
                    {t.skills.resultCount
                      .replace("{count}", String(searchMatchedSkills.length))
                      .replace(
                        "{s}",
                        searchMatchedSkills.length !== 1 ? "s" : "",
                      )}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                {searchMatchedSkills.length === 0 ? (
                  <EmptyState
                    icon={Search}
                    title={inv?.noMatchTitle ?? "No matching skills"}
                    description={t.skills.noSkillsMatch}
                    action={
                      <Button size="sm" outlined onClick={() => setSearch("")}>
                        {inv?.clearSearch ?? "Clear search"}
                      </Button>
                    }
                  />
                ) : (
                  <div className="grid gap-1">
                    {searchMatchedSkills.map(renderSkillRow)}
                  </div>
                )}
              </CardContent>
            </Card>
          ) : view === "skills" ? (
            /* Skills list */
            <Card className="rounded-none">
              <CardHeader className="py-3 px-4">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Package className="h-4 w-4" />
                    {activeCategory
                      ? prettyCategory(
                          activeCategory === "__none__" ? null : activeCategory,
                          t.common.general,
                        )
                      : t.skills.all}
                  </CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge tone="secondary" className="text-xs">
                      {t.skills.skillCount
                        .replace("{count}", String(activeSkills.length))
                        .replace("{s}", activeSkills.length !== 1 ? "s" : "")}
                    </Badge>
                    <Button
                      size="sm"
                      outlined
                      onClick={() => setLearnOpen(true)}
                      prefix={<Sparkles />}
                    >
                      Learn a skill
                    </Button>
                    <Button
                      size="sm"
                      outlined
                      onClick={openCreateEditor}
                      prefix={<Plus />}
                    >
                      New skill
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                {activeSkills.length === 0 ? (
                  skills.length === 0 ? (
                    <EmptyState
                      icon={Package}
                      title={inv?.noSkillsTitle ?? "No skills yet"}
                      description={t.skills.noSkills}
                      action={
                        <Button
                          size="sm"
                          outlined
                          onClick={openCreateEditor}
                          prefix={<Plus />}
                        >
                          New skill
                        </Button>
                      }
                    />
                  ) : (
                    <EmptyState
                      icon={Package}
                      title={inv?.noMatchTitle ?? "No matching skills"}
                      description={t.skills.noSkillsMatch}
                      action={
                        <Button
                          size="sm"
                          outlined
                          onClick={() => {
                            setActiveCategory(null);
                            setActiveProvenance(null);
                          }}
                        >
                          {inv?.clearFilter ?? "Clear filter"}
                        </Button>
                      }
                    />
                  )
                ) : (
                  <div className="grid gap-1">
                    {activeSkills.map(renderSkillRow)}
                  </div>
                )}
              </CardContent>
            </Card>
          ) : view === "toolsets" ? (
            /* K7: toolsets — single-column CapabilityRow list. */
            <>
              {filteredToolsets.length === 0 ? (
                <Card className="rounded-none">
                  <EmptyState
                    icon={Wrench}
                    title={inv?.noToolsetsTitle ?? "No matching toolsets"}
                    description={t.skills.noToolsetsMatch}
                  />
                </Card>
              ) : (
                <div className="flex flex-col gap-2">
                  {filteredToolsets.map((ts) => (
                    <ToolsetRow
                      key={ts.name}
                      toolset={ts}
                      stateLabel={toolsetStateLabelFor(ts)}
                      stateTitle={appliesTitle}
                      toolsLabel={toolsLabelFor(ts)}
                      callsLabel={callsLabelFor(ts)}
                      callsTitle={
                        inv?.callsCaveat ??
                        "Best-effort: summed from tool-call analytics over the last 30 days; extraction is approximate."
                      }
                      onConfigure={() => setConfigToolset(ts)}
                    />
                  ))}
                </div>
              )}
            </>
          ) : (
            <HubBrowser
              showToast={showToast}
              profile={selectedProfile || undefined}
            />
          )}
        </div>
      </div>
      {configToolset && (
        <ToolsetConfigDrawer
          toolset={configToolset}
          profile={selectedProfile || undefined}
          onClose={() => setConfigToolset(null)}
          onChanged={() => void refreshToolsets()}
        />
      )}
      <SkillEditorDialog
        open={editorOpen}
        editName={editorSkill}
        profile={selectedProfile || undefined}
        onClose={() => setEditorOpen(false)}
        onSaved={handleEditorSaved}
      />
      <LearnSkillDialog open={learnOpen} onOpenChange={setLearnOpen} />
      <PluginSlot name="skills:bottom" />
    </div>
  );
}

function PanelItem({ active, icon: Icon, label, onClick }: PanelItemProps) {
  return (
    <ListItem
      active={active}
      onClick={onClick}
      className={cn(
        "rounded-none whitespace-nowrap px-2.5 py-1.5",
        "font-mondwest text-[0.7rem] tracking-[0.08em] uppercase",
        active && "bg-foreground/90 text-background hover:text-background",
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="flex-1 truncate">{label}</span>
    </ListItem>
  );
}

interface PanelItemProps {
  active: boolean;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
}
