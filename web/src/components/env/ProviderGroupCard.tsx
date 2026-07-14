import { useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import type { EnvVarInfo } from "@/lib/api";
import { Badge } from "@/components/fabric/Badge";
import { ListItem } from "@nous-research/ui/ui/components/list-item";
import { useI18n } from "@/i18n";
import { CAPABILITY_STATE_TONES } from "@/components/ui";
import { EnvVarRow, type EnvRowSharedProps } from "./EnvVarRow";

export interface ProviderGroup {
  name: string;
  priority: number;
  entries: [string, EnvVarInfo][];
  hasAnySet: boolean;
}

/**
 * E2 — one collapsible LLM-provider group (API keys → base URLs → other),
 * behavior kept: expand/collapse ListItem header, `N set` success badge,
 * representative "Get key" link, compact rows inside.
 */
export function ProviderGroupCard({
  group,
  ...rowProps
}: { group: ProviderGroup } & EnvRowSharedProps) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useI18n();

  // Separate API keys from base URLs and other settings
  const apiKeys = group.entries.filter(
    ([k]) => k.endsWith("_API_KEY") || k.endsWith("_TOKEN"),
  );
  const baseUrls = group.entries.filter(([k]) => k.endsWith("_BASE_URL"));
  const other = group.entries.filter(
    ([k]) =>
      !k.endsWith("_API_KEY") &&
      !k.endsWith("_TOKEN") &&
      !k.endsWith("_BASE_URL"),
  );
  const hasAnyConfigured = group.entries.some(([, info]) => info.is_set);
  const configuredCount = group.entries.filter(
    ([, info]) => info.is_set,
  ).length;

  // Get a representative URL for "Get key" link
  const keyUrl = apiKeys.find(([, info]) => info.url)?.[1]?.url ?? null;

  return (
    <div className="border border-border">
      {/* Header — always visible */}
      <ListItem
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="justify-between gap-3 px-4 py-3 hover:bg-primary/5"
      >
        <div className="flex items-center gap-3 min-w-0">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          )}
          <span className="font-semibold text-sm tracking-wide">
            {group.name === "Other" ? t.common.other : group.name}
          </span>
          {hasAnyConfigured && (
            <Badge
              tone={CAPABILITY_STATE_TONES.enabled}
              className="text-xs tabular-nums"
            >
              {configuredCount} {t.common.set.toLowerCase()}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {keyUrl && (
            <a
              href={keyUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {t.env.getKey} <ExternalLink className="h-2.5 w-2.5" />
            </a>
          )}
          <span className="text-xs text-text-tertiary tabular-nums">
            {t.env.keysCount
              .replace("{count}", String(group.entries.length))
              .replace("{s}", group.entries.length !== 1 ? "s" : "")}
          </span>
        </div>
      </ListItem>

      {expanded && (
        <div className="border-t border-border px-4 py-3 grid gap-2">
          {apiKeys.map(([key, info]) => (
            <EnvVarRow key={key} varKey={key} info={info} compact {...rowProps} />
          ))}

          {baseUrls.map(([key, info]) => (
            <EnvVarRow key={key} varKey={key} info={info} compact {...rowProps} />
          ))}

          {other.map(([key, info]) => (
            <EnvVarRow key={key} varKey={key} info={info} compact {...rowProps} />
          ))}
        </div>
      )}
    </div>
  );
}
