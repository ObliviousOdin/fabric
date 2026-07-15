import {
  buildDesignPrompt,
  DESIGN_ARTIFACT_OPTIONS,
  DESIGN_SYSTEM_OPTIONS,
  type DesignArtifactKind,
  type DesignFidelity,
  type DesignSystemPreset,
} from "@fabric/shared";
import { Palette, WandSparkles } from "lucide-react";
import { useLayoutEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@nous-research/ui/ui/components/button";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";

import { usePageHeader } from "@/contexts/usePageHeader";
import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import { cn } from "@/lib/utils";
import {
  createFreshChatRequestId,
  FRESH_CHAT_QUERY_PARAM,
} from "@/components/chat/usePersistentChatIdentity";

export default function DesignPage() {
  const navigate = useNavigate();
  const { setTitle } = usePageHeader();
  const { t } = useI18n();
  const design = t.design ?? en.design!;
  const [brief, setBrief] = useState("");
  const [artifact, setArtifact] = useState<DesignArtifactKind>("prototype");
  const [fidelity, setFidelity] = useState<DesignFidelity>("high");
  const [system, setSystem] = useState<DesignSystemPreset>("project");

  useLayoutEffect(() => {
    setTitle(design.title);
    return () => setTitle(null);
  }, [design.title, setTitle]);

  const startDesign = () => {
    if (!brief.trim()) return;

    const draft = buildDesignPrompt({ artifact, brief, fidelity, system });
    const params = new URLSearchParams({
      [FRESH_CHAT_QUERY_PARAM]: createFreshChatRequestId(),
      draft,
    });
    navigate(`/workspace/chat?${params.toString()}`);
  };

  return (
    <div className="mx-auto w-full max-w-5xl px-1 py-6 sm:px-2 sm:py-8">
      <header className="max-w-2xl border-b border-border pb-6">
        <div className="mb-3 flex size-9 items-center justify-center border border-border bg-background-surface text-text-secondary">
          <Palette className="size-4" aria-hidden />
        </div>
        <h2 className="text-xl font-semibold tracking-[-0.02em] text-text-primary">
          {design.title}
        </h2>
        <p className="mt-2 max-w-xl text-sm leading-6 text-text-secondary">
          {design.subtitle}
        </p>
      </header>

      <div className="grid gap-8 pt-7 lg:grid-cols-[minmax(0,1fr)_19rem] lg:gap-10">
        <form
          className="min-w-0 space-y-6"
          onSubmit={(event) => {
            event.preventDefault();
            startDesign();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="design-brief">{design.briefLabel}</Label>
            <textarea
              autoFocus
              className="flex min-h-40 w-full resize-y border border-border bg-background/40 px-3 py-2.5 text-sm leading-6 text-text-primary shadow-sm placeholder:text-muted-foreground focus-visible:border-foreground/25 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30"
              id="design-brief"
              maxLength={4000}
              onChange={(event) => setBrief(event.target.value)}
              placeholder={design.briefPlaceholder}
              value={brief}
            />
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="design-deliverable">
                {design.deliverableLabel}
              </Label>
              <Select
                id="design-deliverable"
                onValueChange={(value) =>
                  setArtifact(value as DesignArtifactKind)
                }
                value={artifact}
              >
                {DESIGN_ARTIFACT_OPTIONS.map((option) => (
                  <SelectOption key={option.id} value={option.id}>
                    {option.label}
                  </SelectOption>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="design-system">{design.systemLabel}</Label>
              <Select
                id="design-system"
                onValueChange={(value) =>
                  setSystem(value as DesignSystemPreset)
                }
                value={system}
              >
                {DESIGN_SYSTEM_OPTIONS.map((option) => (
                  <SelectOption key={option.id} value={option.id}>
                    {option.label}
                  </SelectOption>
                ))}
              </Select>
            </div>
          </div>

          <fieldset>
            <legend className="mb-2 text-sm font-medium text-text-primary">
              {design.fidelity}
            </legend>
            <div className="inline-flex border border-border bg-background-surface p-0.5">
              {(["wireframe", "high"] as const).map((value) => (
                <button
                  aria-pressed={fidelity === value}
                  className={cn(
                    "min-h-11 px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30",
                    fidelity === value
                      ? "bg-foreground text-background"
                      : "text-text-secondary hover:bg-background-base hover:text-text-primary",
                  )}
                  key={value}
                  onClick={() => setFidelity(value)}
                  type="button"
                >
                  {value === "wireframe"
                    ? design.fidelityWireframe
                    : design.fidelityHigh}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
            <Button disabled={!brief.trim()} type="submit">
              <WandSparkles className="size-4" aria-hidden />
              {design.start}
            </Button>
            <span className="max-w-sm text-xs leading-5 text-text-secondary">
              {design.reviewHint}
            </span>
          </div>
        </form>

        <aside className="border-t border-border pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          <h3 className="text-sm font-semibold text-text-primary">
            {design.contractTitle}
          </h3>
          <p className="mt-2 text-xs leading-5 text-text-secondary">
            {design.contractDescription}
          </p>
          <ol className="mt-6 space-y-4">
            {design.phases.map((phase, index) => (
              <li
                className="grid grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-2"
                key={phase}
              >
                <span className="font-mono text-xs leading-5 text-text-secondary">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="text-sm leading-5 text-text-secondary">
                  {phase}
                </span>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </div>
  );
}
