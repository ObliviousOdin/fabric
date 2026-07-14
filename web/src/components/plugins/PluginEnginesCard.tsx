import { useEffect, useRef, useState } from "react";
import { ExternalLink, Eye, EyeOff } from "lucide-react";
import type { Translations } from "@/i18n/types";
import { api } from "@/lib/api";
import type {
  MemoryProviderConfig,
  MemoryProviderField,
  MemoryProviderSetupResult,
  MemorySelectionState,
  PluginsHubProviders,
} from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Badge } from "@/components/fabric/Badge";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Switch } from "@nous-research/ui/ui/components/switch";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import {
  CAPABILITY_STATE_TONES,
  memoryProviderCapabilityState,
} from "@/components/ui";
import { MemoryProviderSetupHint } from "./MemoryProviderSetup";

/** Select value for built-in memory (`config` uses empty string). Never use `""` — UI Select maps empty value to an empty label. */
const MEMORY_PROVIDER_BUILTIN = "__hermes_memory_builtin__";

type MemoryFormValue = string | boolean;

// Must match the backend memory-selection enum (R18); unknown values fall
// back to the raw string / outline tone at the call site.
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

function fieldInitialValue(field: MemoryProviderField): MemoryFormValue {
  if (field.kind === "secret") return "";
  if (field.kind === "boolean") return Boolean(field.value);
  return String(field.value ?? "");
}

function fieldIsVisible(field: MemoryProviderField, values: Record<string, MemoryFormValue>) {
  if (!field.when) return true;
  return Object.entries(field.when).every(([key, expected]) => {
    const current = values[key];
    return String(current ?? "") === String(expected);
  });
}

export interface PluginEnginesCardProps {
  providers: PluginsHubProviders;
  /** Refetch the hub payload; selection state re-syncs when `providers` changes. */
  reloadHub: () => Promise<void>;
  showToast: (msg: string, variant: "success" | "error") => void;
  t: Translations;
}

/**
 * The engines card (spec P3): memory-provider + context-engine selection —
 * the page's assignment surface, parallel to Models' loadout (M2). All
 * write flows are frozen (N18): selection Select, provider status Badge
 * (now via the shared CAP2 mapper), selection-state Badge, capabilities
 * box, deletion-guarantee warning, setup hint, dynamic config fields
 * (secret show/hide, `when` visibility, leave-blank-keeps-secret) and the
 * Save buttons all behave exactly as before the split.
 */
export function PluginEnginesCard({ providers, reloadHub, showToast, t }: PluginEnginesCardProps) {
  const [memorySel, setMemorySel] = useState(
    providers.memory_provider ? providers.memory_provider : MEMORY_PROVIDER_BUILTIN,
  );
  const [memoryConfig, setMemoryConfig] = useState<MemoryProviderConfig | null>(null);
  const [memoryValues, setMemoryValues] = useState<Record<string, MemoryFormValue>>({});
  const [memoryConfigBusy, setMemoryConfigBusy] = useState(false);
  const [secretVisible, setSecretVisible] = useState<Record<string, boolean>>({});
  const [contextSel, setContextSel] = useState(providers.context_engine || "compressor");
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memorySetupBusy, setMemorySetupBusy] = useState(false);
  const [memorySetupResults, setMemorySetupResults] = useState<MemoryProviderSetupResult[] | null>(null);
  const [contextBusy, setContextBusy] = useState(false);

  // The setup flow keeps the just-set-up provider selected across the hub
  // reload (previously `loadHub(memorySelection)` on the page).
  const pendingMemorySelRef = useRef<string | null>(null);

  // Every hub reload re-syncs selection from the server payload — the same
  // semantics the page-level `loadHub` had before the split.
  useEffect(() => {
    const override = pendingMemorySelRef.current;
    pendingMemorySelRef.current = null;
    setMemorySel(
      override ?? (providers.memory_provider ? providers.memory_provider : MEMORY_PROVIDER_BUILTIN),
    );
    setContextSel(providers.context_engine || "compressor");
  }, [providers]);

  useEffect(() => {
    const provider = memorySel === MEMORY_PROVIDER_BUILTIN ? "" : memorySel;
    let cancelled = false;

    void Promise.resolve().then(() => {
      if (cancelled) return;
      setSecretVisible({});
      setMemorySetupResults(null);

      if (!provider) {
        setMemoryConfig(null);
        setMemoryValues({});
        setMemoryConfigBusy(false);
        return;
      }

      setMemoryConfigBusy(true);
      api
        .getMemoryProviderConfig(provider)
        .then((config) => {
          if (cancelled) return;
          setMemoryConfig(config);
          setMemoryValues(
            Object.fromEntries(
              config.fields.map((field) => [field.key, fieldInitialValue(field)]),
            ),
          );
        })
        .catch((e) => {
          if (!cancelled) {
            setMemoryConfig(null);
            setMemoryValues({});
            showToast(e instanceof Error ? e.message : "Failed to load provider config", "error");
          }
        })
        .finally(() => {
          if (!cancelled) setMemoryConfigBusy(false);
        });
    });

    return () => {
      cancelled = true;
    };
  }, [memorySel, showToast]);

  const onSaveMemoryProvider = async () => {
    const provider = memorySel === MEMORY_PROVIDER_BUILTIN ? "" : memorySel;
    setMemoryBusy(true);
    try {
      if (!provider) {
        await api.setMemoryProvider("");
      } else {
        const visibleValues = Object.fromEntries(
          Object.entries(memoryValues).filter(([key]) => {
            const field = memoryConfig?.fields.find((candidate) => candidate.key === key);
            return field ? fieldIsVisible(field, memoryValues) : true;
          }),
        );
        await api.updateMemoryProviderConfig(provider, visibleValues);
      }
      showToast(t.pluginsPage.savedProviders, "success");
      await reloadHub();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setMemoryBusy(false);
    }
  };

  const currentVisibleMemoryValues = () =>
    Object.fromEntries(
      Object.entries(memoryValues).filter(([key]) => {
        const field = memoryConfig?.fields.find((candidate) => candidate.key === key);
        return field ? fieldIsVisible(field, memoryValues) : true;
      }),
    );

  const onSetupMemoryProvider = async () => {
    const provider = memorySel === MEMORY_PROVIDER_BUILTIN ? "" : memorySel;
    if (!provider) return;

    setMemorySetupBusy(true);
    setMemorySetupResults(null);
    try {
      const result = await api.setupMemoryProvider(provider, currentVisibleMemoryValues());
      setMemorySetupResults(result.results);
      const failed = result.results.filter((row) => row.status === "failed");
      if (failed.length) {
        const names = Array.from(new Set(failed.map((row) => row.name))).join(", ");
        showToast(`Provider setup failed: ${names || provider}. See setup results below.`, "error");
      } else {
        showToast("Provider setup finished", "success");
      }
      pendingMemorySelRef.current = provider;
      await reloadHub();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Provider setup failed", "error");
    } finally {
      setMemorySetupBusy(false);
    }
  };

  const onSaveContextEngine = async () => {
    setContextBusy(true);
    try {
      await api.savePluginProviders({ context_engine: contextSel });
      showToast(t.pluginsPage.savedProviders, "success");
      await reloadHub();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setContextBusy(false);
    }
  };

  const selectedMemoryName = memorySel === MEMORY_PROVIDER_BUILTIN ? "" : memorySel;
  const selectedMemoryInfo = selectedMemoryName
    ? providers.memory_options.find((provider) => provider.name === selectedMemoryName)
    : null;
  const activeMemoryInfo = providers.memory_provider
    ? providers.memory_options.find((provider) => provider.name === providers.memory_provider)
    : null;
  const memorySelectionState = providers.memory_selection?.state;
  const visibleMemoryFields =
    memoryConfig?.fields.filter((field) => fieldIsVisible(field, memoryValues)) ?? [];
  const selectedMemoryState = selectedMemoryInfo
    ? memoryProviderCapabilityState(selectedMemoryInfo)
    : null;

  return (
    <Card>
      <CardHeader>
        <p className="text-[0.625rem] uppercase tracking-[0.16em] text-text-tertiary">
          {t.pluginsPage.agents?.enginesLabel ?? "engines"}
        </p>
        <CardTitle>{t.pluginsPage.providersHeading}</CardTitle>
        <p className="text-xs tracking-[0.08em] text-text-tertiary">
          Configure memory providers and runtime context engine selection.
        </p>
      </CardHeader>

      <CardContent className="flex flex-col gap-6">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(260px,0.65fr)]">
          <div className="flex flex-col gap-4 min-w-0">
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Label htmlFor="mem-provider">{t.pluginsPage.memoryProviderLabel}</Label>
                {selectedMemoryName && selectedMemoryState && (
                  <Badge tone={CAPABILITY_STATE_TONES[selectedMemoryState.state]}>
                    {selectedMemoryState.label}
                  </Badge>
                )}
                {selectedMemoryName && selectedMemoryName === providers.memory_provider && (
                  <Badge tone={memorySelectionState ? MEMORY_SELECTION_TONE[memorySelectionState] : "outline"}>
                    {memorySelectionState ? MEMORY_SELECTION_LABEL[memorySelectionState] : "configured"}
                  </Badge>
                )}
                {!selectedMemoryName && !providers.memory_provider && (
                  <Badge tone={memorySelectionState ? MEMORY_SELECTION_TONE[memorySelectionState] : "secondary"}>
                    {memorySelectionState ? MEMORY_SELECTION_LABEL[memorySelectionState] : "built-in only"}
                  </Badge>
                )}
              </div>

              <Select
                id="mem-provider"
                className="w-full font-mono-ui"
                value={memorySel}
                onValueChange={setMemorySel}
              >
                <SelectOption value={MEMORY_PROVIDER_BUILTIN}>
                  {`(${t.pluginsPage.providerDefaults})`}
                </SelectOption>

                {providers.memory_options.map((o) => (
                  <SelectOption key={o.name} value={o.name}>
                    {o.name}
                  </SelectOption>
                ))}
              </Select>
            </div>

            {!selectedMemoryName && (
              <p className="text-xs text-muted-foreground">
                Fabric will use the built-in MEMORY.md and USER.md files.
              </p>
            )}

            {activeMemoryInfo?.status === "missing" && (
              <p className="border border-destructive/50 px-3 py-2 text-xs text-destructive">
                Configured provider{" "}
                <span className="font-mono-ui">{providers.memory_provider}</span> is no longer
                installed. Select another provider and save.
              </p>
            )}

            {selectedMemoryName && selectedMemoryInfo?.description && (
              <p className="text-xs text-muted-foreground">
                {selectedMemoryInfo.description}
              </p>
            )}

            {selectedMemoryName && selectedMemoryInfo?.capabilities && (
              <div className="border border-border px-3 py-2 text-xs text-muted-foreground">
                <p>
                  Adapter potential: {Object.entries(selectedMemoryInfo.capabilities)
                    .filter(([, support]) => support === "supported")
                    .map(([operation]) => operation.replaceAll("_", " "))
                    .sort()
                    .join(", ") || "not declared"}.
                </p>
                <p className="mt-1">
                  Mode and configuration can disable these operations. Live initialization and health are not checked here.
                </p>
                {selectedMemoryInfo.capabilities.deletion_guarantee !== "supported" && (
                  <p className="mt-1 text-warning">
                    Deletion is not guaranteed across provider replicas or backups. Resetting Fabric&apos;s built-in files does not erase external copies.
                  </p>
                )}
              </div>
            )}

            {selectedMemoryName && selectedMemoryInfo && (
              <MemoryProviderSetupHint
                installing={memorySetupBusy}
                onInstall={() => void onSetupMemoryProvider()}
                provider={selectedMemoryInfo}
                results={memorySetupResults}
              />
            )}

            {selectedMemoryName && selectedMemoryInfo?.status === "needs_config" && (
              <p className="border border-warning/50 px-3 py-2 text-xs text-warning">
                Provider dependencies are installed. Add the required credentials or self-hosted URL below, then save the provider.
              </p>
            )}

            {selectedMemoryName && memoryConfigBusy && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner /> Loading provider settings…
              </div>
            )}

            {selectedMemoryName && !memoryConfigBusy && visibleMemoryFields.length === 0 && (
              <p className="text-xs text-muted-foreground">
                This provider does not expose dashboard settings.
              </p>
            )}

            {selectedMemoryName && !memoryConfigBusy && visibleMemoryFields.length > 0 && (
              <div className="grid gap-4 border border-border p-4">
                {visibleMemoryFields.map((field) => {
                  const value = memoryValues[field.key];
                  const secretIsVisible = !!secretVisible[field.key];
                  return (
                    <div key={field.key} className="grid gap-2 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Label htmlFor={`memory-${field.key}`}>{field.label}</Label>
                        {field.required && <Badge tone="outline">required</Badge>}
                        {field.kind === "secret" && field.is_set && !value && (
                          <Badge tone="success">set</Badge>
                        )}
                        {field.url && (
                          <a
                            href={field.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-xs underline"
                          >
                            Open <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>

                      {field.kind === "select" ? (
                        <Select
                          id={`memory-${field.key}`}
                          className="w-full"
                          value={String(value ?? "")}
                          onValueChange={(next) =>
                            setMemoryValues((current) => ({ ...current, [field.key]: next }))
                          }
                        >
                          {field.options.map((option) => (
                            <SelectOption key={option.value} value={option.value}>
                              {option.label}
                            </SelectOption>
                          ))}
                        </Select>
                      ) : field.kind === "boolean" ? (
                        <Switch
                          checked={Boolean(value)}
                          onCheckedChange={(next) =>
                            setMemoryValues((current) => ({ ...current, [field.key]: next }))
                          }
                        />
                      ) : (
                        <div className="flex items-center gap-2">
                          <Input
                            id={`memory-${field.key}`}
                            type={field.kind === "secret" && !secretIsVisible ? "password" : "text"}
                            value={String(value ?? "")}
                            placeholder={
                              field.kind === "secret" && field.is_set
                                ? "Leave blank to keep existing value"
                                : field.placeholder
                            }
                            onChange={(event) =>
                              setMemoryValues((current) => ({
                                ...current,
                                [field.key]: event.target.value,
                              }))
                            }
                          />
                          {field.kind === "secret" && (
                            <Button
                              ghost
                              size="icon"
                              aria-label={secretIsVisible ? "Hide secret" : "Show secret"}
                              onClick={() =>
                                setSecretVisible((current) => ({
                                  ...current,
                                  [field.key]: !current[field.key],
                                }))
                              }
                            >
                              {secretIsVisible ? (
                                <EyeOff className="h-3.5 w-3.5" />
                              ) : (
                                <Eye className="h-3.5 w-3.5" />
                              )}
                            </Button>
                          )}
                        </div>
                      )}

                      {field.description && (
                        <p className="text-xs text-muted-foreground">{field.description}</p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <Button
              className="w-fit uppercase"
              size="sm"
              disabled={memoryBusy || memoryConfigBusy || memorySetupBusy}
              onClick={() => void onSaveMemoryProvider()}
              prefix={memoryBusy ? <Spinner /> : undefined}
            >
              Save memory provider
            </Button>
          </div>

          <div className="grid content-start gap-3 min-w-0">
            <Label htmlFor="ctx-engine">{t.pluginsPage.contextEngineLabel}</Label>

            <Select
              id="ctx-engine"
              className="w-full font-mono-ui"
              value={contextSel}
              onValueChange={setContextSel}
            >
              <SelectOption value="compressor">compressor</SelectOption>

              {providers.context_options
                .filter((o) => o.name !== "compressor")
                .map((o) => (
                  <SelectOption key={o.name} value={o.name}>
                    {o.name}
                  </SelectOption>
                ))}
            </Select>

            <Button
              className="w-fit uppercase"
              size="sm"
              disabled={contextBusy}
              onClick={() => void onSaveContextEngine()}
              prefix={contextBusy ? <Spinner /> : undefined}
            >
              Save context engine
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
