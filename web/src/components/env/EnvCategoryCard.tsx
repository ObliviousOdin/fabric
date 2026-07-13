import { useState } from "react";
import type { EnvVarInfo } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { useI18n } from "@/i18n";
import { EnvVarRow, type EnvRowSharedProps } from "./EnvVarRow";

export interface EnvCategorySection {
  category: string;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  setEntries: [string, EnvVarInfo][];
  totalEntries: number;
  unsetEntries: [string, EnvVarInfo][];
}

/**
 * E5 — Tools / Gateway / Settings category card, behavior kept: set entries
 * always visible, unset behind Show more/less (auto-open when none
 * configured), configured-count line. The Gateway section's hint copy is the
 * cross-page contract with Channels (E1) and rides in `section.hint`.
 */
export function EnvCategoryCard({
  section,
  ...rowProps
}: { section: EnvCategorySection } & EnvRowSharedProps) {
  const noneConfigured = section.setEntries.length === 0;
  const [showAll, setShowAll] = useState(noneConfigured);
  const { t } = useI18n();
  const Icon = section.icon;
  const hasContent = section.setEntries.length > 0 || showAll;

  return (
    <Card id={`section-${section.category}`}>
      <CardHeader
        className={`bg-card${hasContent ? " border-b border-border" : ""}`}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Icon className="h-5 w-5 shrink-0 text-muted-foreground" />
            <CardTitle className="text-base">{section.label}</CardTitle>
          </div>

          {section.unsetEntries.length > 0 && (
            <button
              type="button"
              onClick={() => setShowAll((open) => !open)}
              aria-expanded={showAll}
              className="shrink-0 cursor-pointer border-0 bg-transparent p-0 font-mondwest text-xs tracking-[0.08em] text-text-secondary transition-colors hover:text-foreground"
            >
              {showAll ? t.env.showLess : t.env.showMore}
            </button>
          )}
        </div>

        <CardDescription className="tabular-nums">
          {section.setEntries.length} {t.common.of} {section.totalEntries}{" "}
          {t.common.configured}
        </CardDescription>

        {section.hint && (
          <CardDescription className="text-text-tertiary">
            {section.hint}
          </CardDescription>
        )}
      </CardHeader>

      {hasContent && (
        <CardContent className="grid gap-3 overflow-hidden pt-4">
          {section.setEntries.map(([key, info]) => (
            <EnvVarRow key={key} varKey={key} info={info} {...rowProps} />
          ))}

          {showAll &&
            section.unsetEntries.map(([key, info]) => (
              <EnvVarRow key={key} varKey={key} info={info} {...rowProps} />
            ))}
        </CardContent>
      )}
    </Card>
  );
}
