import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import { KeyRound, MessageSquare, Settings, Zap } from "lucide-react";
import { api } from "@/lib/api";
import type { EnvVarInfo } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";
import { Skeleton } from "@/components/ui";
import type { EnvRowSharedProps } from "@/components/env/EnvVarRow";
import {
  ProviderGroupCard,
  type ProviderGroup,
} from "@/components/env/ProviderGroupCard";
import {
  EnvCategoryCard,
  type EnvCategorySection,
} from "@/components/env/EnvCategoryCard";
import { CustomKeysCard } from "@/components/env/CustomKeysCard";
import {
  providerProbeOutcome,
  type ProviderProbeOutcome,
} from "@/components/env/env-validate";

/* ------------------------------------------------------------------ */
/*  Provider grouping                                                  */
/* ------------------------------------------------------------------ */

/** Map env-var key prefixes to a human-friendly provider name + ordering.
 *  Frontend-owned mirror of the provider catalog — drift risk noted (R28). */
const PROVIDER_GROUPS: { prefix: string; name: string; priority: number }[] = [
  // Nous Portal first
  { prefix: "NOUS_", name: "Nous Portal", priority: 0 },
  // Then alphabetical by display name
  { prefix: "ANTHROPIC_", name: "Anthropic", priority: 1 },
  { prefix: "DASHSCOPE_", name: "DashScope (Qwen)", priority: 2 },
  { prefix: "DEEPSEEK_", name: "DeepSeek", priority: 3 },
  { prefix: "GOOGLE_", name: "Gemini", priority: 4 },
  { prefix: "GEMINI_", name: "Gemini", priority: 4 },
  { prefix: "GLM_", name: "GLM / Z.AI", priority: 5 },
  { prefix: "ZAI_", name: "GLM / Z.AI", priority: 5 },
  { prefix: "Z_AI_", name: "GLM / Z.AI", priority: 5 },
  { prefix: "HF_", name: "Hugging Face", priority: 6 },
  { prefix: "KIMI_", name: "Kimi / Moonshot", priority: 7 },
  { prefix: "MINIMAX_CN_", name: "MiniMax (China)", priority: 9 },
  { prefix: "MINIMAX_", name: "MiniMax", priority: 8 },
  { prefix: "OPENCODE_GO_", name: "OpenCode Go", priority: 10 },
  { prefix: "OPENCODE_ZEN_", name: "OpenCode Zen", priority: 11 },
  { prefix: "OPENROUTER_", name: "OpenRouter", priority: 12 },
  { prefix: "XIAOMI_", name: "Xiaomi MiMo", priority: 13 },
];

function getProviderGroup(key: string): string {
  for (const g of PROVIDER_GROUPS) {
    if (key.startsWith(g.prefix)) return g.name;
  }
  return "Other";
}

function getProviderPriority(groupName: string): number {
  const entry = PROVIDER_GROUPS.find((g) => g.name === groupName);
  return entry?.priority ?? 99;
}

const CATEGORY_META_ICONS: Record<string, typeof KeyRound> = {
  provider: Zap,
  tool: KeyRound,
  messaging: MessageSquare,
  setting: Settings,
};

/* ------------------------------------------------------------------ */
/*  Main page                                                          */
/* ------------------------------------------------------------------ */

export default function EnvPage() {
  const [vars, setVars] = useState<Record<string, EnvVarInfo> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(true); // Show all providers by default
  // E7: per-key probe in-flight + session-local last outcomes. Never
  // persisted, never auto-run — an explicit Test action only.
  const [testing, setTesting] = useState<string | null>(null);
  const [probeOutcomes, setProbeOutcomes] = useState<
    Record<string, ProviderProbeOutcome>
  >({});
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setAfterTitle } = usePageHeader();

  const load = useCallback(() => {
    api
      .getEnvVars()
      .then((res) => {
        setVars(res);
        setLoadError(null);
      })
      .catch((e) => {
        // E8: the silent catch becomes a banner + Retry — a blank page is
        // not a recoverable state.
        setLoadError(String(e));
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Scroll-to sub-nav in the page header
  const sections = useMemo(() => {
    const items: { id: string; label: string }[] = [
      { id: "section-oauth", label: "OAuth" },
      { id: "section-providers", label: "Providers" },
    ];
    if (vars) {
      const categories = ["tool", "messaging", "setting"];
      const CATEGORY_LABELS: Record<string, string> = {
        tool: "Tools",
        messaging: t.common.gateway ?? "Gateway",
        setting: "Settings",
      };
      for (const cat of categories) {
        const hasEntries = Object.values(vars).some(
          (info) => info.category === cat && !info.channel_managed,
        );
        if (hasEntries) {
          items.push({ id: `section-${cat}`, label: CATEGORY_LABELS[cat] ?? cat });
        }
      }
      // Custom keys section is always present (it carries the add-key form).
      items.push({ id: "section-custom", label: t.env.customTitle });
    }
    return items;
  }, [vars, t]);

  useLayoutEffect(() => {
    if (!vars) {
      setAfterTitle(null);
      return;
    }
    const scrollTo = (id: string) => {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    setAfterTitle(
      <nav
        className="flex shrink-0 flex-nowrap items-center gap-1"
        aria-label="Jump to section"
      >
        {sections.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => scrollTo(s.id)}
            className="shrink-0 cursor-pointer px-2 py-0.5 font-mondwest text-display text-xs tracking-wider text-text-secondary hover:text-foreground border border-border/50 hover:border-foreground/30 transition-colors"
          >
            {s.label}
          </button>
        ))}
      </nav>,
    );
    return () => {
      setAfterTitle(null);
    };
  }, [vars, sections, setAfterTitle]);

  const handleSave = async (key: string) => {
    const value = edits[key];
    if (!value) return;
    setSaving(key);
    try {
      await api.setEnvVar(key, value);
      setVars((prev) =>
        prev
          ? {
              ...prev,
              [key]: {
                ...prev[key],
                is_set: true,
                // Short secrets must be fully masked — head+tail slices of a
                // value under 9 chars overlap and echo the whole secret back.
                redacted_value:
                  value.length > 8
                    ? value.slice(0, 4) + "..." + value.slice(-4)
                    : "••••••••",
              },
            }
          : prev,
      );
      setEdits((prev) => {
        const n = { ...prev };
        delete n[key];
        return n;
      });
      setRevealed((prev) => {
        const n = { ...prev };
        delete n[key];
        return n;
      });
      showToast(`${key} ${t.common.save.toLowerCase()}d`, "success");
    } catch (e) {
      showToast(`${t.config.failedToSave} ${key}: ${e}`, "error");
    } finally {
      setSaving(null);
    }
  };

  const keyClear = useConfirmDelete({
    onDelete: useCallback(
      async (key: string) => {
        setSaving(key);
        try {
          await api.deleteEnvVar(key);
          setVars((prev) =>
            prev
              ? {
                  ...prev,
                  [key]: { ...prev[key], is_set: false, redacted_value: null },
                }
              : prev,
          );
          setEdits((prev) => {
            const n = { ...prev };
            delete n[key];
            return n;
          });
          setRevealed((prev) => {
            const n = { ...prev };
            delete n[key];
            return n;
          });
          // A cleared key's last probe outcome describes a value that no
          // longer exists — drop it.
          setProbeOutcomes((prev) => {
            const n = { ...prev };
            delete n[key];
            return n;
          });
          showToast(`${key} ${t.common.removed}`, "success");
        } catch (e) {
          showToast(`${t.common.failedToRemove} ${key}: ${e}`, "error");
          throw e;
        } finally {
          setSaving(null);
        }
      },
      [showToast, t.common.removed, t.common.failedToRemove],
    ),
  });

  const handleReveal = async (key: string) => {
    if (revealed[key]) {
      setRevealed((prev) => {
        const n = { ...prev };
        delete n[key];
        return n;
      });
      return;
    }
    try {
      const resp = await api.revealEnvVar(key);
      setRevealed((prev) => ({ ...prev, [key]: resp.value }));
    } catch (e) {
      // E3: the reveal endpoint is rate-limited (5 per 30 s → 429, §0.7);
      // say so specifically instead of a generic failure.
      const rateLimited = e instanceof Error && e.message.startsWith("429");
      showToast(
        rateLimited
          ? (t.env.revealRateLimited ??
              "Reveal rate-limited — try again in a moment")
          : `${t.common.failedToReveal} ${key}`,
        "error",
      );
    }
  };

  const cancelEdit = (key: string) => {
    setEdits((prev) => {
      const n = { ...prev };
      delete n[key];
      return n;
    });
    // The chip described the discarded draft — drop it with the edit.
    setProbeOutcomes((prev) => {
      const n = { ...prev };
      delete n[key];
      return n;
    });
  };

  // E7: explicit live probe of the draft value before it's saved. The
  // OPENAI_BASE_URL branch also forwards a drafted OPENAI_API_KEY (if any)
  // so auth-gated /v1/models endpoints can enumerate their catalog.
  const handleTest = async (key: string) => {
    const value = (edits[key] ?? "").trim();
    if (!value) return;
    setTesting(key);
    try {
      const apiKey =
        key === "OPENAI_BASE_URL" ? (edits["OPENAI_API_KEY"] ?? "").trim() : "";
      const res = await api.validateProviderKey(key, value, apiKey);
      setProbeOutcomes((prev) => ({ ...prev, [key]: providerProbeOutcome(res) }));
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    } finally {
      setTesting(null);
    }
  };

  // Add a custom key: register an unset row in local state and open it for
  // editing. The value isn't persisted until the user types one and saves
  // (reusing the normal handleSave → PUT /api/env path); on save the backend
  // surfaces it back as a custom row, so the new entry is durable.
  const handleAddKey = (key: string) => {
    setVars((prev) =>
      prev && prev[key]
        ? prev
        : {
            ...(prev ?? {}),
            [key]: {
              is_set: false,
              redacted_value: null,
              description: "",
              url: null,
              category: "custom",
              is_password: true,
              tools: [],
              advanced: false,
              custom: true,
            },
          },
    );
    setEdits((prev) => ({ ...prev, [key]: "" }));
  };

  /* ---- Build provider groups ---- */
  const { providerGroups, nonProviderGrouped, customEntries } = useMemo(() => {
    if (!vars)
      return {
        providerGroups: [] as ProviderGroup[],
        nonProviderGrouped: [] as EnvCategorySection[],
        customEntries: [] as [string, EnvVarInfo][],
      };

    const providerEntries = Object.entries(vars).filter(
      ([, info]) =>
        info.category === "provider" && (showAdvanced || !info.advanced),
    );

    // Group by provider
    const groupMap = new Map<string, [string, EnvVarInfo][]>();
    for (const entry of providerEntries) {
      const groupName = getProviderGroup(entry[0]);
      if (!groupMap.has(groupName)) groupMap.set(groupName, []);
      groupMap.get(groupName)!.push(entry);
    }

    const groups: ProviderGroup[] = Array.from(groupMap.entries())
      .map(([name, entries]) => ({
        name,
        priority: getProviderPriority(name),
        entries,
        hasAnySet: entries.some(([, info]) => info.is_set),
      }))
      .sort((a, b) => a.priority - b.priority);

    // Non-provider categories — use translated labels. Platform credentials
    // (channel_managed) are configured on the Channels page, so the messaging
    // category here is trimmed down to cross-cutting gateway / API / proxy
    // settings and relabelled accordingly. (E1: the channel-managed exclusion
    // is canonical, `_channel_managed_env_keys` in fabric_cli/web_server.py.)
    const CATEGORY_META_LABELS: Record<string, string> = {
      tool: t.app.nav.keys,
      messaging: t.common.gateway ?? "Gateway",
      setting: t.app.nav.config,
    };
    const CATEGORY_META_HINTS: Record<string, string | undefined> = {
      messaging:
        t.common.gatewayHint ??
        "Messaging platforms, the API server and webhooks are configured on the Channels page. These are gateway-wide settings (proxy/relay mode and the global allowlist).",
    };
    const otherCategories = ["tool", "messaging", "setting"];
    const nonProvider: EnvCategorySection[] = otherCategories.map((cat) => {
      const entries = Object.entries(vars).filter(
        ([, info]) =>
          info.category === cat &&
          !info.channel_managed &&
          (showAdvanced || !info.advanced),
      );
      const setEntries = entries.filter(([, info]) => info.is_set);
      const unsetEntries = entries.filter(([, info]) => !info.is_set);
      return {
        label: CATEGORY_META_LABELS[cat] ?? cat,
        hint: CATEGORY_META_HINTS[cat],
        icon: CATEGORY_META_ICONS[cat] ?? KeyRound,
        category: cat,
        setEntries,
        unsetEntries,
        totalEntries: entries.length,
      };
    });

    // Custom keys: user-added vars the backend flagged as not in any catalog.
    // Sorted alphabetically; an in-flight (just-added, unsaved) row carries the
    // custom category locally so it shows here immediately.
    const customEntries = Object.entries(vars)
      .filter(([, info]) => info.category === "custom" && !info.channel_managed)
      .sort(([a], [b]) => a.localeCompare(b));

    return {
      providerGroups: groups,
      nonProviderGrouped: nonProvider,
      customEntries,
    };
  }, [vars, showAdvanced, t]);

  if (!vars) {
    if (loadError) {
      return (
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center justify-between gap-2 border border-destructive/40 bg-destructive/10 px-3 py-2">
            <p className="text-xs text-destructive">
              {(t.env.loadFailed ?? "Could not load environment keys")}:{" "}
              {loadError}
            </p>
            <Button outlined size="sm" onClick={load}>
              {t.common.retry}
            </Button>
          </div>
        </div>
      );
    }
    // E8/G13: layout-shaped Skeleton (OAuth card slot + provider rows)
    // instead of a full-page Spinner.
    return (
      <div aria-busy="true" aria-live="polite" className="flex flex-col gap-6">
        <span className="sr-only">{t.common.loading}</span>

        <Skeleton variant="block" className="h-40" />

        <div className="border border-border p-4">
          <Skeleton variant="row-list" rows={6} />
        </div>
      </div>
    );
  }

  const totalProviders = providerGroups.length;
  const configuredProviders = providerGroups.filter((g) => g.hasAnySet).length;

  const pendingClearKey = keyClear.pendingId;
  const pendingKeyDescription =
    pendingClearKey && vars ? vars[pendingClearKey]?.description : undefined;

  const rowProps: EnvRowSharedProps = {
    edits,
    setEdits,
    revealed,
    saving,
    onSave: handleSave,
    onClear: keyClear.requestDelete,
    onReveal: handleReveal,
    onCancelEdit: cancelEdit,
    clearDialogOpen: keyClear.isOpen,
    testing,
    probeOutcomes,
    onTest: handleTest,
  };

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="env:top" />
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={keyClear.isOpen}
        onCancel={keyClear.cancel}
        onConfirm={keyClear.confirm}
        title={t.env.confirmClearTitle}
        description={
          pendingClearKey
            ? `${pendingClearKey}${pendingKeyDescription ? ` — ${pendingKeyDescription}` : ""}. ${t.env.confirmClearMessage}`
            : t.env.confirmClearMessage
        }
        loading={keyClear.isDeleting}
      />

      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-muted-foreground">
            {t.env.description} <code>~/.fabric/.env</code>
          </p>
          <p className="text-xs text-text-tertiary">
            {t.env.changesNote}
          </p>
        </div>
        <Button
          size="sm"
          outlined
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          {showAdvanced ? t.env.hideAdvanced : t.env.showAdvanced}
        </Button>
      </div>

      <div id="section-oauth">
        <OAuthProvidersCard
          onError={(msg) => showToast(msg, "error")}
          onSuccess={(msg) => showToast(msg, "success")}
        />
      </div>

      <Card id="section-providers">
        <CardHeader className="border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">{t.env.llmProviders}</CardTitle>
          </div>
          <CardDescription className="tabular-nums">
            {t.env.providersConfigured
              .replace("{configured}", String(configuredProviders))
              .replace("{total}", String(totalProviders))}
          </CardDescription>
        </CardHeader>

        <CardContent className="grid gap-0 p-0">
          {providerGroups.map((group) => (
            <ProviderGroupCard key={group.name} group={group} {...rowProps} />
          ))}
        </CardContent>
      </Card>

      {nonProviderGrouped.map((section) => {
        if (section.totalEntries === 0) return null;

        return (
          <EnvCategoryCard
            key={section.category}
            section={section}
            {...rowProps}
          />
        );
      })}
      <CustomKeysCard
        entries={customEntries}
        onAddKey={handleAddKey}
        {...rowProps}
      />
      <PluginSlot name="env:bottom" />
    </div>
  );
}
