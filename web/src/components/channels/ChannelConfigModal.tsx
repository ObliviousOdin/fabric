import { useState } from "react";
import { ExternalLink, Info, X } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { api } from "@/lib/api";
import type {
  MessagingPlatform,
  MessagingPlatformEnvVar,
  MessagingPlatformUpdate,
} from "@/lib/api";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { cn, themedBody } from "@/lib/utils";
import { validateMessagingEnvField } from "./channel-env-validation";

export interface ChannelConfigModalProps {
  platform: MessagingPlatform;
  onClose: () => void;
  /** Runs after a successful save (toast already shown): close + flag
   *  restart-needed + reload — the page owns that sequence. */
  onSaved: () => void | Promise<void>;
  showToast: (message: string, type: "success" | "error") => void;
}

/**
 * Per-platform env config modal (H3 — behavior frozen): per-field prompt/
 * help/description, password inputs, `is_set` placeholder ("set — leave
 * blank to keep"), only-filled-fields sent, required-and-unset check, the
 * Slack validation mirrors, field-error clearing on edit, "Save & enable"
 * (`{env, enabled: true}`), docs-url "Setup guide" link.
 */
export function ChannelConfigModal({
  platform,
  onClose,
  onSaved,
  showToast,
}: ChannelConfigModalProps) {
  const [draftEnv, setDraftEnv] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    platform.env_vars.forEach((v) => {
      initial[v.key] = "";
    });
    return initial;
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const modalRef = useModalBehavior({ open: true, onClose });

  const handleSave = async () => {
    // Only send fields the user actually filled in — leaving a field blank
    // preserves the existing value rather than clobbering it.
    const env: Record<string, string> = {};
    Object.entries(draftEnv).forEach(([k, v]) => {
      if (v.trim()) env[k] = v.trim();
    });
    if (Object.keys(env).length === 0) {
      showToast("Nothing to save — fill in at least one field.", "error");
      return;
    }
    const missing = platform.env_vars.filter(
      (v) => v.required && !v.is_set && !env[v.key],
    );
    if (missing.length > 0) {
      showToast(`${missing[0].prompt || missing[0].key} is required`, "error");
      return;
    }
    const nextFieldErrors: Record<string, string> = {};
    platform.env_vars.forEach((field) => {
      const message = validateMessagingEnvField(field, draftEnv[field.key] || "");
      if (message) nextFieldErrors[field.key] = message;
    });
    if (Object.keys(nextFieldErrors).length > 0) {
      setFieldErrors(nextFieldErrors);
      showToast("Fix the highlighted fields before saving.", "error");
      return;
    }
    setSaving(true);
    try {
      const body: MessagingPlatformUpdate = { env, enabled: true };
      await api.updateMessagingPlatform(platform.id, body);
      showToast(`${platform.name} saved`, "success");
      await onSaved();
    } catch (e) {
      showToast(`Failed to save: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      ref={modalRef}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="channel-config-title"
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
            id="channel-config-title"
            className="font-mondwest text-display text-base tracking-wider"
          >
            Configure {platform.name}
          </h2>
          {platform.docs_url && (
            <a
              href={platform.docs_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              Setup guide <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </header>

        <div className="p-5 grid gap-4 overflow-y-auto">
          <p className="text-xs text-muted-foreground">{platform.description}</p>
          {platform.env_vars.map((field: MessagingPlatformEnvVar) => (
            <div className="grid gap-1.5" key={field.key}>
              <div className="flex items-center gap-1.5">
                <Label htmlFor={`field-${field.key}`}>
                  {field.prompt || field.key}
                  {field.required ? " *" : ""}
                </Label>
                {field.help && (
                  <span
                    aria-label={field.help}
                    className="inline-flex text-muted-foreground hover:text-foreground"
                    role="img"
                    title={field.help}
                  >
                    <Info className="h-3.5 w-3.5" />
                  </span>
                )}
              </div>
              {field.description && (
                <span className="text-xs text-muted-foreground">
                  {field.description}
                </span>
              )}
              <Input
                id={`field-${field.key}`}
                type={field.is_password ? "password" : "text"}
                placeholder={
                  field.is_set
                    ? field.redacted_value || "•••••• (set — leave blank to keep)"
                    : field.key
                }
                value={draftEnv[field.key] ?? ""}
                aria-invalid={Boolean(fieldErrors[field.key])}
                onChange={(e) => {
                  const nextValue = e.target.value;
                  setDraftEnv((prev) => ({ ...prev, [field.key]: nextValue }));
                  setFieldErrors((prev) => {
                    if (!prev[field.key]) return prev;
                    const next = { ...prev };
                    delete next[field.key];
                    return next;
                  });
                }}
              />
              {fieldErrors[field.key] && (
                <span className="text-xs text-destructive">
                  {fieldErrors[field.key]}
                </span>
              )}
            </div>
          ))}

          <div className="flex justify-end gap-2 pt-1">
            <Button ghost size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="uppercase"
              size="sm"
              onClick={handleSave}
              disabled={saving}
              prefix={saving ? <Spinner /> : undefined}
            >
              {saving ? "Saving…" : "Save & enable"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
