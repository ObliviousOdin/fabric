import type { ReactNode } from "react";
import { Wrench } from "lucide-react";
import type { ToolsetInfo } from "@/lib/api";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  CAPABILITY_STATE_TONES,
  CapabilityRow,
  toolsetCapabilityState,
} from "@/components/ui";
import { toolsetIcon } from "./skills-meta";

export interface ToolsetRowProps {
  toolset: ToolsetInfo;
  /** Localized CAP2 state label override (active/inactive/needs setup);
   *  falls back to the mapper's English label. */
  stateLabel?: string;
  /** R16 `title` copy on the state badge — toggles apply to new sessions. */
  stateTitle: string;
  /** Pre-formatted `N tools` segment (or the no-tools fallback copy). */
  toolsLabel: string | null;
  /** Pre-formatted `~N calls · 30d` segment; null while analytics are
   *  unresolved or the sum is 0 (R4/R20). */
  callsLabel: string | null;
  /** Best-effort caveat for the calls segment `title` (R14/R20). */
  callsTitle?: string;
  onConfigure: () => void;
}

/**
 * One toolset in the single-column list — `CapabilityRow` consumer (K7):
 * monochrome toolset glyph, sans human label (mono technical name +
 * full tool inventory live in the meta `title` — a 20-chip dump per row
 * fails signal-per-pixel), CAP2 state badge (needs-setup replaces the old
 * amber literal, G10), description, mono meta (`N tools · ~N calls · 30d`),
 * trailing Configure → `ToolsetConfigDrawer`.
 */
export function ToolsetRow({
  toolset,
  stateLabel,
  stateTitle,
  toolsLabel,
  callsLabel,
  callsTitle,
  onConfigure,
}: ToolsetRowProps) {
  const state = toolsetCapabilityState(toolset);
  const labelText = toolset.label.trim() || toolset.name;
  // Mono technical name + resolved tool names, hoverable on the meta line.
  const toolsTitle =
    toolset.tools.length > 0
      ? `${toolset.name}: ${toolset.tools.join(", ")}`
      : toolset.name;

  const metaSegments: ReactNode[] = [];
  if (toolsLabel) {
    metaSegments.push(
      <span key="tools" title={toolsTitle}>
        {toolsLabel}
      </span>,
    );
  }
  if (callsLabel) {
    metaSegments.push(
      <span key="calls" title={callsTitle}>
        {callsLabel}
      </span>,
    );
  }

  return (
    <CapabilityRow
      name={labelText}
      mono={false}
      icon={toolsetIcon(toolset.name)}
      badges={
        <Badge
          tone={CAPABILITY_STATE_TONES[state.state]}
          className="text-xs"
          title={stateTitle}
        >
          {stateLabel || state.label}
        </Badge>
      }
      description={toolset.description}
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
      dimmed={!toolset.enabled}
      actions={
        <Button size="sm" outlined onClick={onConfigure} prefix={<Wrench />}>
          Configure
        </Button>
      }
    />
  );
}
