import type { ReactNode } from "react";
import { Pencil } from "lucide-react";
import type { SkillInfo } from "@/lib/api";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { CapabilityRow } from "@/components/ui";
import { provenanceVisual } from "./skills-meta";

export interface SkillListRowProps {
  skill: SkillInfo;
  /** Toggle write in flight (per-skill busy set). */
  toggling: boolean;
  onToggle: () => void;
  onEdit: () => void;
  noDescriptionLabel: string;
  /** Localized provenance chip label (`agent` → "custom"); tone comes
   *  from `provenanceVisual`. */
  provenanceLabel: string;
  /** Pre-formatted `N uses` segment; null hides it (R4 — no 0-noise). */
  usesLabel: string | null;
  /** Category segment; null when the rail already filters to it (K4). */
  categoryLabel: string | null;
  /** R16 `title` copy on the provenance/state zone. */
  appliesNewSessionsTitle: string;
}

/**
 * One skill on the Skills list — `CapabilityRow` consumer #1 (K4): leading
 * enable Switch (the Switch IS the state zone — no duplicate enabled
 * Badge), mono name, provenance chip, clamped description, mono
 * usage/category meta line, hover-reveal Edit action.
 */
export function SkillListRow({
  skill,
  toggling,
  onToggle,
  onEdit,
  noDescriptionLabel,
  provenanceLabel,
  usesLabel,
  categoryLabel,
  appliesNewSessionsTitle,
}: SkillListRowProps) {
  const prov = provenanceVisual(skill.provenance);

  const metaSegments: ReactNode[] = [];
  if (usesLabel) {
    metaSegments.push(<span key="uses">{usesLabel}</span>);
  }
  if (categoryLabel) {
    metaSegments.push(<span key="category">{categoryLabel}</span>);
  }

  return (
    <CapabilityRow
      // Borderless inside the card's bordered list container (CAP3);
      // `group` drives the hover-reveal Edit affordance.
      className="group border-0"
      name={skill.name}
      switch={{
        checked: skill.enabled,
        onChange: onToggle,
        busy: toggling,
        ariaLabel: `${skill.name}: ${skill.enabled ? "disable" : "enable"}`,
      }}
      badges={
        <Badge
          tone={prov.tone}
          className="text-xs"
          title={appliesNewSessionsTitle}
        >
          {provenanceLabel || prov.label}
        </Badge>
      }
      description={skill.description || noDescriptionLabel}
      meta={
        metaSegments.length > 0
          ? metaSegments.flatMap((seg, i) =>
              i > 0
                ? [
                    <span key={`sep-${i}`} aria-hidden="true">
                      ·
                    </span>,
                    seg,
                  ]
                : [seg],
            )
          : undefined
      }
      dimmed={!skill.enabled}
      actions={
        <Button
          ghost
          size="icon"
          className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:text-foreground"
          title="Edit SKILL.md"
          aria-label={`Edit ${skill.name}`}
          onClick={onEdit}
        >
          <Pencil />
        </Button>
      }
    />
  );
}
