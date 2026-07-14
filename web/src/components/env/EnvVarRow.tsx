import {
  ExternalLink,
  Eye,
  EyeOff,
  Pencil,
  Save,
  Trash2,
  X,
} from "lucide-react";
import type { EnvVarInfo } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Badge } from "@/components/fabric/Badge";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import { CAPABILITY_STATE_TONES } from "@/components/ui";
import {
  PROVIDER_PROBE_KEYS,
  type ProviderProbeOutcome,
} from "./env-validate";

/**
 * The shared prop bag every env row consumer (provider groups, category
 * cards, custom keys) drills through. Edit drafts, reveal cache and probe
 * outcomes are page-owned so a row can move between cards without losing
 * state.
 */
export interface EnvRowSharedProps {
  edits: Record<string, string>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  revealed: Record<string, string>;
  saving: string | null;
  onSave: (key: string) => void;
  onClear: (key: string) => void;
  onReveal: (key: string) => void;
  onCancelEdit: (key: string) => void;
  clearDialogOpen?: boolean;
  /** E7 — per-key probe in-flight key (null = none). */
  testing?: string | null;
  /** E7 — session-local last probe outcome per key. */
  probeOutcomes?: Record<string, ProviderProbeOutcome>;
  /** E7 — explicit probe action; only rendered for PROVIDER_PROBE_KEYS. */
  onTest?: (key: string) => void;
}

/**
 * Single env-key row (E3, behaviors frozen): compact unset / boxed unset /
 * full set-or-editing densities with an inline editor. Deliberately NOT a
 * `CapabilityRow` (R21 — a three-density inline-editor row is a different
 * interaction class); it shares tokens and the CAP2 badge tones only.
 */
export function EnvVarRow({
  varKey,
  info,
  edits,
  setEdits,
  revealed,
  saving,
  onSave,
  onClear,
  onReveal,
  onCancelEdit,
  clearDialogOpen = false,
  compact = false,
  testing = null,
  probeOutcomes,
  onTest,
}: EnvRowSharedProps & {
  varKey: string;
  info: EnvVarInfo;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const isEditing = edits[varKey] !== undefined;
  const isRevealed = !!revealed[varKey];
  const displayValue = isRevealed
    ? revealed[varKey]
    : (info.redacted_value ?? "---");

  // E7: Test renders only for keys the server can actually probe — no fake
  // coverage — and only fires explicitly (never auto-runs, N14 discipline).
  const probeSupported = onTest != null && PROVIDER_PROBE_KEYS.has(varKey);
  const probeOutcome = probeOutcomes?.[varKey];
  const probeBusy = testing === varKey;
  const testLabel = t.env.testKey ?? "Test";
  const testingLabel = t.env.testingKey ?? "Testing…";
  const probeChipLabel = probeOutcome
    ? probeOutcome.kind === "accepted" && probeOutcome.label === "key accepted"
      ? (t.env.keyAccepted ?? probeOutcome.label)
      : probeOutcome.kind === "unreachable"
        ? (t.env.keyUnreachable ?? probeOutcome.label)
        : probeOutcome.label
    : null;

  // Compact inline row for unset, non-editing keys (used inside provider groups)
  if (compact && !info.is_set && !isEditing) {
    return (
      <div className="flex items-center justify-between gap-3 py-1.5 min-w-0 overflow-hidden text-text-secondary hover:text-foreground transition-colors">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono-ui text-xs">
            {varKey}
          </span>
          <span className="text-xs text-text-tertiary truncate hidden sm:block">
            {info.description}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {info.url && (
            <a
              href={info.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              {t.env.getKey} <ExternalLink className="h-2.5 w-2.5" />
            </a>
          )}
          <Button
            size="sm"
            outlined
            prefix={<Pencil />}
            onClick={() => setEdits((prev) => ({ ...prev, [varKey]: "" }))}
          >
            {t.common.set}
          </Button>
        </div>
      </div>
    );
  }

  // Non-compact unset row
  if (!info.is_set && !isEditing) {
    return (
      <div className="flex items-center justify-between gap-3 border border-border/50 px-4 py-2.5 min-w-0 overflow-hidden text-text-secondary hover:text-foreground transition-colors">
        <div className="flex items-center gap-3 min-w-0">
          <Label className="font-mono-ui text-xs">
            {varKey}
          </Label>
          <span className="text-xs text-text-tertiary truncate hidden sm:block">
            {info.description}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {info.url && (
            <a
              href={info.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              {t.env.getKey} <ExternalLink className="h-2.5 w-2.5" />
            </a>
          )}
          <Button
            size="sm"
            outlined
            prefix={<Pencil />}
            onClick={() => setEdits((prev) => ({ ...prev, [varKey]: "" }))}
          >
            {t.common.set}
          </Button>
        </div>
      </div>
    );
  }

  // Full expanded row for set keys or keys being edited
  return (
    <div className="grid gap-2 border border-border p-4 min-w-0 overflow-hidden">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <Label className="font-mono-ui text-xs">{varKey}</Label>
          {/* CAP2 tones (E6): set = enabled/success, unset = outline. */}
          <Badge
            tone={info.is_set ? CAPABILITY_STATE_TONES.enabled : "outline"}
          >
            {info.is_set ? t.common.set : t.env.notSet}
          </Badge>
        </div>
        {info.url && (
          <a
            href={info.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            {t.env.getKey} <ExternalLink className="h-2.5 w-2.5" />
          </a>
        )}
      </div>

      <p className="text-xs text-muted-foreground">{info.description}</p>

      {info.tools.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {info.tools.map((tool) => (
            <Badge
              key={tool}
              tone="secondary"
              className="text-xs py-0 px-1.5"
            >
              {tool}
            </Badge>
          ))}
        </div>
      )}

      {!isEditing && (
        <div className="flex items-center gap-2">
          <div
            className={`flex-1 border border-border px-3 py-2 font-mono-ui text-xs ${
              isRevealed
                ? "bg-background text-foreground select-all"
                : "bg-muted/30 text-muted-foreground"
            }`}
          >
            {info.is_set ? displayValue : "---"}
          </div>

          {info.is_set && (
            <Button
              ghost
              size="icon"
              onClick={() => onReveal(varKey)}
              title={isRevealed ? t.env.hideValue : t.env.showValue}
              aria-label={isRevealed ? `Hide ${varKey}` : `Reveal ${varKey}`}
            >
              {isRevealed ? <EyeOff /> : <Eye />}
            </Button>
          )}

          <Button
            size="sm"
            outlined
            prefix={<Pencil />}
            onClick={() => setEdits((prev) => ({ ...prev, [varKey]: "" }))}
          >
            {info.is_set ? t.common.replace : t.common.set}
          </Button>

          {info.is_set && (
            <Button
              size="sm"
              outlined
              destructive
              prefix={<Trash2 />}
              onClick={() => onClear(varKey)}
              disabled={saving === varKey || clearDialogOpen}
            >
              {saving === varKey ? "..." : t.common.clear}
            </Button>
          )}
        </div>
      )}

      {isEditing && (
        <div className="flex items-center gap-2">
          <Input
            autoFocus
            type="text"
            value={edits[varKey]}
            onChange={(e) =>
              setEdits((prev) => ({ ...prev, [varKey]: e.target.value }))
            }
            placeholder={
              info.is_set
                ? t.env.replaceCurrentValue.replace(
                    "{preview}",
                    info.redacted_value ?? "---",
                  )
                : t.env.enterValue
            }
            className="flex-1 font-mono-ui text-xs"
          />
          <Button
            size="sm"
            onClick={() => onSave(varKey)}
            prefix={<Save />}
            disabled={saving === varKey || !edits[varKey]}
          >
            {saving === varKey ? "..." : t.common.save}
          </Button>
          {probeSupported && (
            <Button
              size="sm"
              outlined
              onClick={() => onTest?.(varKey)}
              disabled={probeBusy || !edits[varKey]?.trim()}
              title="Live-check this value against the provider before saving"
            >
              {probeBusy ? testingLabel : testLabel}
            </Button>
          )}
          <Button
            size="sm"
            outlined
            prefix={<X />}
            onClick={() => onCancelEdit(varKey)}
          >
            {t.common.cancel}
          </Button>
        </div>
      )}

      {/* E7 last-outcome chip (session-local, MCP /test precedent). */}
      {probeOutcome && probeChipLabel && (
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            tone={probeOutcome.tone}
            className="shrink-0 lowercase text-xs"
          >
            {probeChipLabel}
          </Badge>
          {probeOutcome.message && (
            <span
              className={cn(
                "text-xs",
                probeOutcome.kind === "rejected"
                  ? "text-destructive"
                  : "text-muted-foreground",
              )}
            >
              {probeOutcome.message}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
