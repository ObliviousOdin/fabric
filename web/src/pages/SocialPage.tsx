import { EyeOff, Lock, Megaphone } from "lucide-react";
import { useEffect, useLayoutEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@nous-research/ui/ui/components/button";

import { Badge } from "@/components/fabric/Badge";
import { SocialBrainstorm } from "@/components/social/SocialBrainstorm";
import { SocialComposer } from "@/components/social/SocialComposer";
import { SocialLibrary } from "@/components/social/SocialLibrary";
import { Skeleton } from "@/components/ui";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useSocialArtifactScan } from "@/hooks/useSocialArtifactScan";
import { useSocialStudioEnabled } from "@/hooks/useSocialStudioEnabled";
import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import {
  hasBrainstormed,
  markBrainstormed,
  resolveSocialStages,
  type SocialStage,
} from "@/lib/social-brainstorm";
import { cn } from "@/lib/utils";

/**
 * Social Studio: a progressive surface that unlocks as the work happens.
 * The landing stage is a brainstorm interview that sets up a post sequence
 * and hands it to Chat; Compose (the single-post brief) unlocks after the
 * first brainstorm; the Library unlocks only when a conversation actually
 * contains a post-ready artifact — nothing is shown for an empty library.
 * Gated behind the Social Studio preference — the sidebar entry only appears
 * when enabled, but the page stays reachable by URL, so it also offers to
 * enable itself.
 */
export default function SocialPage() {
  const { setTitle } = usePageHeader();
  const { t } = useI18n();
  const s = t.social ?? en.social!;
  const navigate = useNavigate();
  const [enabled, setEnabled] = useSocialStudioEnabled();

  const scan = useSocialArtifactScan();
  const [brainstormed, setBrainstormed] = useState(hasBrainstormed);
  const [stage, setStage] = useState<SocialStage | null>(null);

  const access = resolveSocialStages({
    hasArtifacts: scan.results.length > 0,
    hasBrainstormed: brainstormed,
  });

  useLayoutEffect(() => {
    setTitle(s.title);
    return () => setTitle(null);
  }, [s.title, setTitle]);

  // Land on the right stage once the first scan settles, and snap back to it
  // if the open stage ever loses its unlock (e.g. a rescan empties the
  // library).
  useEffect(() => {
    if (!scan.settled) return;
    if (stage === null) {
      setStage(access.initialStage);
      return;
    }
    if (stage === "library" && !access.libraryUnlocked) {
      setStage(access.initialStage);
    } else if (stage === "compose" && !access.composeUnlocked) {
      setStage(access.initialStage);
    }
  }, [access, scan.settled, stage]);

  const unlockCompose = () => {
    markBrainstormed();
    setBrainstormed(true);
  };

  const stageDefs: {
    blurb: string;
    id: SocialStage;
    label: string;
    locked: boolean;
    lockedHint: string | null;
  }[] = [
    {
      blurb: s.stageBrainstormBlurb,
      id: "brainstorm",
      label: s.tabBrainstorm,
      locked: false,
      lockedHint: null,
    },
    {
      blurb: s.stageComposeBlurb,
      id: "compose",
      label: s.tabCompose,
      locked: !access.composeUnlocked,
      lockedHint: s.lockedComposeHint,
    },
    {
      blurb: s.stageLibraryBlurb,
      id: "library",
      label: s.tabLibrary,
      locked: !access.libraryUnlocked,
      lockedHint: s.lockedLibraryHint,
    },
  ];

  return (
    <div className="mx-auto w-full max-w-5xl px-1 py-6 sm:px-2 sm:py-8">
      <header className="border-b border-border pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <div className="mb-3 flex size-9 items-center justify-center border border-border bg-background-surface text-text-secondary">
              <Megaphone className="size-4" aria-hidden />
            </div>
            <h2 className="text-xl font-semibold tracking-[-0.02em] text-text-primary">
              {s.title}
            </h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-text-secondary">
              {s.subtitle}
            </p>
          </div>

          {enabled ? (
            <Button
              ghost
              size="sm"
              prefix={<EyeOff />}
              onClick={() => setEnabled(false)}
            >
              {s.disable}
            </Button>
          ) : (
            <Button size="sm" onClick={() => setEnabled(true)}>
              {s.enable}
            </Button>
          )}
        </div>
      </header>

      {stage === null ? (
        <div className="pt-6" aria-busy="true">
          <div className="mb-6 grid grid-cols-3 gap-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} variant="block" className="h-16" />
            ))}
          </div>
          <p className="text-xs text-text-tertiary">{s.checkingLibrary}</p>
        </div>
      ) : (
        <div className="pt-6">
          <div
            aria-label={s.title}
            className="mb-6 grid grid-cols-3 gap-2"
            role="tablist"
          >
            {stageDefs.map((def, index) => {
              const current = stage === def.id;
              return (
                <button
                  aria-selected={current}
                  className={cn(
                    "flex min-h-11 flex-col items-start gap-0.5 border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                    current
                      ? "border-primary bg-primary/[0.08]"
                      : def.locked
                        ? "cursor-not-allowed border-border bg-background-surface/20 text-text-tertiary"
                        : "border-border bg-background-surface/40 hover:border-primary/50",
                  )}
                  disabled={def.locked}
                  key={def.id}
                  onClick={() => setStage(def.id)}
                  role="tab"
                  title={def.locked ? (def.lockedHint ?? undefined) : undefined}
                  type="button"
                >
                  <span className="flex w-full items-center justify-between gap-2">
                    <span className="font-mono text-xs text-text-tertiary">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    {def.locked ? (
                      <Lock aria-hidden className="size-3.5" />
                    ) : def.id === "library" && scan.results.length > 0 ? (
                      <Badge tone="secondary" className="text-xs">
                        {scan.results.length}
                      </Badge>
                    ) : null}
                  </span>
                  <span
                    className={cn(
                      "text-sm font-medium",
                      def.locked ? "text-text-tertiary" : "text-text-primary",
                    )}
                  >
                    {def.label}
                  </span>
                  <span className="hidden text-xs leading-5 text-text-tertiary sm:block">
                    {def.locked ? def.lockedHint : def.blurb}
                  </span>
                </button>
              );
            })}
          </div>

          {stage === "brainstorm" && (
            <SocialBrainstorm
              onLaunched={unlockCompose}
              onSkip={() => {
                unlockCompose();
                setStage("compose");
              }}
            />
          )}
          {stage === "compose" && <SocialComposer />}
          {stage === "library" && <SocialLibrary scan={scan} />}
        </div>
      )}

      {!enabled && (
        <p className="mt-8 border-t border-border pt-4 text-xs leading-5 text-text-tertiary">
          {s.disabledNote}{" "}
          <button
            type="button"
            className="underline decoration-border underline-offset-4 hover:text-primary"
            onClick={() => navigate("/workspace/home")}
          >
            {s.backHome}
          </button>
        </p>
      )}
    </div>
  );
}
