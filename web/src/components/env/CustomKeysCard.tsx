import { useState } from "react";
import { KeyRound, Plus } from "lucide-react";
import type { EnvVarInfo } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { useI18n } from "@/i18n";
import { EnvVarRow, type EnvRowSharedProps } from "./EnvVarRow";

// Mirror of the backend env-name guard (fabric_cli/config.py _ENV_VAR_NAME_RE).
export const ENV_VAR_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * E4 — user-added arbitrary env vars + the add-key form, behavior kept:
 * uppercase normalization, invalid-name inline error, add → local unset row
 * + open editor → the normal save path persists it, alphabetical sort
 * (done by the page).
 */
export function CustomKeysCard({
  entries,
  onAddKey,
  ...rowProps
}: {
  entries: [string, EnvVarInfo][];
  onAddKey: (key: string) => void;
} & EnvRowSharedProps) {
  const { t } = useI18n();
  const [newKey, setNewKey] = useState("");
  const trimmed = newKey.trim().toUpperCase();
  const alreadyEditing = rowProps.edits[trimmed] !== undefined;
  const nameValid = ENV_VAR_NAME_RE.test(trimmed);
  const showInvalid = trimmed.length > 0 && !nameValid;

  const handleAdd = () => {
    if (!nameValid || alreadyEditing) return;
    onAddKey(trimmed);
    setNewKey("");
  };

  return (
    <Card id="section-custom">
      <CardHeader className="border-b border-border bg-card">
        <div className="flex items-center gap-2">
          <KeyRound className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">{t.env.customTitle}</CardTitle>
        </div>
        <CardDescription className="tabular-nums">
          {t.env.customConfigured
            .replace("{count}", String(entries.length))
            .replace("{s}", entries.length !== 1 ? "s" : "")}
        </CardDescription>
        <CardDescription className="text-text-tertiary">
          {t.env.customHint}
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-3 overflow-hidden pt-4">
        {entries.map(([key, info]) => (
          <EnvVarRow key={key} varKey={key} info={info} {...rowProps} />
        ))}

        {/* Add-key form */}
        <div className="grid gap-2 border border-dashed border-border p-4">
          <Label className="text-xs font-semibold tracking-wide">
            {t.env.addCustomKey}
          </Label>
          <div className="flex items-start gap-2">
            <div className="flex-1">
              <Input
                type="text"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAdd();
                }}
                placeholder={t.env.customKeyNamePlaceholder}
                aria-label={t.env.customKeyName}
                className="w-full font-mono-ui text-xs"
              />
              {showInvalid && (
                <p className="mt-1 text-xs text-destructive">
                  {t.env.invalidKeyName}
                </p>
              )}
            </div>
            <Button
              size="sm"
              prefix={<Plus />}
              onClick={handleAdd}
              disabled={!nameValid || alreadyEditing}
            >
              {t.env.add}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
