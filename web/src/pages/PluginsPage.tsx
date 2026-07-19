import { useCallback, useEffect, useRef, useState } from "react";
import { Blocks, ExternalLink, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type { HubAgentPluginRow, PluginsHubResponse } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { EmptyState, Skeleton } from "@/components/ui";
import { PluginEnginesCard } from "@/components/plugins/PluginEnginesCard";
import {
  PLUGIN_INSTALL_INPUT_ID,
  PluginInstallCard,
} from "@/components/plugins/PluginInstallCard";
import { PluginRosterRow } from "@/components/plugins/PluginRosterRow";
import { IntegrationCapabilityDirectory } from "@/components/plugins/IntegrationCapabilityDirectory";
import { useI18n } from "@/i18n";
import { PluginSlot } from "@/plugins";
import { usePageHeader } from "@/contexts/usePageHeader";

function prefersReducedMotion() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * PLUGINS — "what extends the agent" (spec §4). The parent-route capability
 * directory keeps its Skills and MCP siblings discoverable, then the
 * loadout-first order (P1) remains roster → orphan dashboard plugins →
 * engines (memory/context assignment surface, P3) → install (P4). All write
 * flows are frozen (N18); the row grammar and corrected state tones come from
 * the shared CAP2/CAP3 primitives.
 */
export default function PluginsPage() {
  const [hub, setHub] = useState<PluginsHubResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rescanBusy, setRescanBusy] = useState(false);
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  // P4: the just-installed plugin's roster row scrolls into view + flashes.
  const [flashName, setFlashName] = useState<string | null>(null);
  const flashRef = useRef<HTMLLIElement | null>(null);

  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setAfterTitle } = usePageHeader();

  const loadHub = useCallback(() => {
    return (
      api
        .getPluginsHub()
        .then((h) => {
          setHub(h);
          setLoadError(null);
        })
        // P8: load failures render as a destructive banner + Retry (was a
        // mislabeled `t.common.loading` toast). Mutation error toasts stay.
        .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
    );
  }, []);

  useEffect(() => {
    void loadHub().finally(() => setLoading(false));
  }, [loadHub]);

  const onRescan = useCallback(async () => {
    setRescanBusy(true);
    try {
      const rc = await api.rescanPlugins();
      showToast(`${t.pluginsPage.refreshDashboard} (${rc.count})`, "success");
      await loadHub();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Rescan failed", "error");
    } finally {
      setRescanBusy(false);
    }
  }, [loadHub, showToast, t.pluginsPage.refreshDashboard]);

  useEffect(() => {
    setAfterTitle(
      <Button
        ghost
        size="icon"
        className="shrink-0 text-muted-foreground hover:text-foreground"
        disabled={loading || rescanBusy}
        onClick={() => void onRescan()}
        aria-label={t.pluginsPage.refreshDashboard}
      >
        {rescanBusy ? <Spinner /> : <RefreshCw />}
      </Button>,
    );
    return () => setAfterTitle(null);
  }, [
    loading,
    onRescan,
    rescanBusy,
    setAfterTitle,
    t.pluginsPage.refreshDashboard,
  ]);

  const setRuntimeLoading = async (
    name: string,
    fn: () => Promise<unknown>,
  ) => {
    setRowBusy(name);
    try {
      await fn();
      await loadHub();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed", "error");
    } finally {
      setRowBusy(null);
    }
  };

  const onInstalled = async (pluginName: string) => {
    await loadHub();
    setFlashName(pluginName);
  };

  useEffect(() => {
    if (!flashName) return;
    flashRef.current?.scrollIntoView({
      block: "nearest",
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
    const timer = window.setTimeout(() => setFlashName(null), 2400);
    return () => window.clearTimeout(timer);
  }, [flashName]);

  // P7: the empty-roster CTA points at where installing actually happens.
  const focusInstallInput = () => {
    const el = document.getElementById(PLUGIN_INSTALL_INPUT_ID);
    if (!el) return;
    el.scrollIntoView({
      block: "center",
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
    el.focus({ preventScroll: true });
  };

  const rows = hub?.plugins ?? [];
  const providers = hub?.providers;
  const orphans = hub?.orphan_dashboard_plugins ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PluginSlot name="plugins:top" />

      <div className="flex w-full flex-col gap-8">
        {loadError && (
          <div className="flex items-center gap-3 border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
            <span className="min-w-0 flex-1 truncate" title={loadError}>
              {t.pluginsPage.agents?.hubLoadFailed ?? "Could not load plugins"}
            </span>
            <Button
              ghost
              size="sm"
              className="uppercase"
              onClick={() => void loadHub()}
            >
              {t.common.retry}
            </Button>
          </div>
        )}

        <IntegrationCapabilityDirectory />

        {loading ? (
          // P6: layout-shaped skeletons instead of the inline spinner.
          <div aria-busy="true" className="flex flex-col gap-8">
            <div className="flex flex-col gap-3">
              <h3 className="text-sm font-semibold text-foreground">
                {t.pluginsPage.pluginListHeading}
              </h3>
              <Skeleton variant="row-list" rows={4} />
            </div>
            <Skeleton variant="block" className="h-64" />
          </div>
        ) : (
          <>
            {/* P1/P2 — the roster is the loadout; it leads the page. */}
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-3">
                <span aria-hidden className="h-px w-6 bg-primary" />
                <h3 className="text-sm font-semibold text-foreground">
                  {t.pluginsPage.pluginListHeading}
                </h3>
              </div>

              {rows.length === 0 ? (
                !loadError && (
                  <EmptyState
                    icon={Blocks}
                    title={
                      t.pluginsPage.agents?.noPluginsTitle ??
                      "No plugins installed"
                    }
                    description={
                      t.pluginsPage.agents?.noPluginsDescription ??
                      "Install one from a Git repository with the install card below."
                    }
                    action={
                      <Button
                        size="sm"
                        className="uppercase"
                        onClick={focusInstallInput}
                      >
                        {t.pluginsPage.agents?.installCta ?? "Install a plugin"}
                      </Button>
                    }
                  />
                )
              ) : (
                <ul className="divide-y divide-border/75 border-y border-border/80">
                  {rows.map((row: HubAgentPluginRow) => (
                    <li
                      key={row.name}
                      ref={row.name === flashName ? flashRef : undefined}
                    >
                      <PluginRosterRow
                        busy={rowBusy === row.name}
                        flash={row.name === flashName}
                        row={row}
                        runAction={setRuntimeLoading}
                        showToast={showToast}
                        t={t}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* P5 — dashboard-only manifests, muted, 1px-box idiom. */}
            {orphans.length > 0 ? (
              <div className="flex flex-col gap-3 opacity-95">
                <h3 className="text-sm font-semibold text-foreground">
                  {t.pluginsPage.orphanHeading}
                </h3>

                <ul className="flex flex-col gap-2 border border-border p-4">
                  {orphans.map((m) => (
                    <li className="text-xs text-text-secondary" key={m.name}>
                      {m.label ?? m.name} — {m.description || m.tab?.path}
                      {!m.tab?.hidden ? (
                        <Link
                          className="ml-3 inline-flex items-center gap-1 underline"
                          to={m.tab.path}
                        >
                          <ExternalLink className="h-3 w-3 opacity-65" />
                          {t.pluginsPage.openTab}
                        </Link>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {/* P3 — engines: the page's assignment surface (memory/context). */}
            {providers && (
              <PluginEnginesCard
                providers={providers}
                reloadHub={loadHub}
                showToast={showToast}
                t={t}
              />
            )}

            {/* P4 — install last: the loadout answers first, forms follow. */}
            <PluginInstallCard
              onInstalled={onInstalled}
              showToast={showToast}
              t={t}
            />
          </>
        )}
      </div>

      <Toast toast={toast} />
      <PluginSlot name="plugins:bottom" />
    </div>
  );
}
