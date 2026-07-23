import { EyeOff, Megaphone } from "lucide-react";
import { useLayoutEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@nous-research/ui/ui/components/button";
import { Segmented } from "@nous-research/ui/ui/components/segmented";

import { SocialComposer } from "@/components/social/SocialComposer";
import { SocialLibrary } from "@/components/social/SocialLibrary";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useSocialStudioEnabled } from "@/hooks/useSocialStudioEnabled";
import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";

type Tab = "compose" | "library";

/**
 * Social Studio: draft a post from a brief (Compose) and browse the
 * conversations that already produced one (Library). Gated behind the
 * Social Studio preference — the sidebar entry only appears when enabled, but
 * the page stays reachable by URL, so it also offers to enable itself.
 */
export default function SocialPage() {
  const { setTitle } = usePageHeader();
  const { t } = useI18n();
  const s = t.social ?? en.social!;
  const navigate = useNavigate();
  const [enabled, setEnabled] = useSocialStudioEnabled();
  const [tab, setTab] = useState<Tab>("compose");

  useLayoutEffect(() => {
    setTitle(s.title);
    return () => setTitle(null);
  }, [s.title, setTitle]);

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

      <div className="pt-6">
        <Segmented
          className="mb-6"
          value={tab}
          onChange={(value) => setTab(value as Tab)}
          options={[
            { value: "compose", label: s.tabCompose },
            { value: "library", label: s.tabLibrary },
          ]}
        />

        {tab === "compose" ? <SocialComposer /> : <SocialLibrary />}
      </div>

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
