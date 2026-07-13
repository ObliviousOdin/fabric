import { useState } from "react";
import type { Translations } from "@/i18n/types";
import { api } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Switch } from "@nous-research/ui/ui/components/switch";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";

/** The install identifier input's DOM id — the P7 empty-state CTA focuses it. */
export const PLUGIN_INSTALL_INPUT_ID = "install-url";

export interface PluginInstallCardProps {
  /**
   * Called after a successful install (P4): the page reloads the hub and
   * scrolls/flashes the new roster row so the loadout change is visible
   * where the loadout lives.
   */
  onInstalled: (pluginName: string) => Promise<void> | void;
  showToast: (msg: string, variant: "success" | "error") => void;
  t: Translations;
}

/**
 * The install card (spec P4): identifier Input (mono) + force/enable
 * Switches + Install button + hint lines. Behavior frozen (N18) — toasts
 * for warnings/missing_env, identifier cleared on success — with the one
 * P4 addition delegated to `onInstalled`.
 */
export function PluginInstallCard({ onInstalled, showToast, t }: PluginInstallCardProps) {
  const [installId, setInstallId] = useState("");
  const [installForce, setInstallForce] = useState(false);
  const [installEnable, setInstallEnable] = useState(true);
  const [installBusy, setInstallBusy] = useState(false);

  const onInstall = async () => {
    const id = installId.trim();
    if (!id) {
      showToast(t.pluginsPage.installHint, "error");
      return;
    }
    setInstallBusy(true);
    try {
      const r = await api.installAgentPlugin({
        identifier: id,
        force: installForce,
        enable: installEnable,
      });
      showToast(`${r.plugin_name ?? id} installed`, "success");
      if ((r.warnings?.length ?? 0) > 0) showToast(r.warnings!.join(" "), "error");
      if ((r.missing_env?.length ?? 0) > 0)
        showToast(`${t.pluginsPage.missingEnvWarn} ${r.missing_env!.join(", ")}`, "error");
      setInstallId("");
      await onInstalled(r.plugin_name ?? id);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Install failed", "error");
    } finally {
      setInstallBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.pluginsPage.installHeading}</CardTitle>
        <p className="text-xs tracking-[0.08em] text-text-tertiary">
          {t.pluginsPage.installHint}
        </p>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor={PLUGIN_INSTALL_INPUT_ID}>{t.pluginsPage.identifierLabel}</Label>

          <Input
            className="font-mono-ui lowercase"
            id={PLUGIN_INSTALL_INPUT_ID}
            placeholder="owner/repo, owner/repo/subdir, or https://..."
            spellCheck={false}
            value={installId}
            onChange={(e) => setInstallId(e.target.value)}
          />
        </div>

        <div className="flex flex-wrap items-center gap-8">
          <div className="flex items-center gap-3">
            <Switch checked={installForce} onCheckedChange={setInstallForce} />
            <span className="text-xs tracking-[0.06em] text-text-secondary">
              {t.pluginsPage.forceReinstall}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <Switch checked={installEnable} onCheckedChange={setInstallEnable} />
            <span className="text-xs tracking-[0.06em] text-text-secondary">
              {t.pluginsPage.enableAfterInstall}
            </span>
          </div>
        </div>

        <Button
          className="w-fit uppercase"
          size="sm"
          disabled={installBusy}
          onClick={() => void onInstall()}
          prefix={installBusy ? <Spinner /> : undefined}
        >
          {t.pluginsPage.installBtn}
        </Button>

        <p className="text-xs tracking-[0.06em] text-text-tertiary">
          {t.pluginsPage.rescanHint}
        </p>

        <p className="text-xs tracking-[0.06em] text-text-tertiary">
          {t.pluginsPage.removeHint}
        </p>
      </CardContent>
    </Card>
  );
}
