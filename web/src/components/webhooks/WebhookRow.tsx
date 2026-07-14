import { Trash2 } from "lucide-react";
import { Badge } from "@/components/fabric/Badge";
import { Button } from "@nous-research/ui/ui/components/button";
import type { WebhookRoute } from "@/lib/api";
import { CapabilityRow, RelativeTime } from "@/components/ui";
import { CopyButton } from "./CopyButton";

export interface WebhookRowProps {
  sub: WebhookRoute;
  toggling: boolean;
  onToggle: (nextEnabled: boolean) => void;
  onDelete: () => void;
}

/**
 * Webhook subscription row (CapabilityRow consumer #7, spec W2): the
 * Switch is the state zone (replaces the ghost Enable/Disable button and
 * the redundant warning `disabled` badge — CAP1.2, no double indicator);
 * name is the server-validated slug (mono); `deliver`/`deliver only` are
 * provenance badges; events chips ride in the detail zone; the meta line
 * is the endpoint URL + `RelativeTime(created_at)` + skills count — the
 * only temporal fact served is `created_at`, so no delivery evidence is
 * invented (§3.1 decision, B24).
 */
export function WebhookRow({ sub, toggling, onToggle, onDelete }: WebhookRowProps) {
  return (
    <CapabilityRow
      name={sub.name}
      dimmed={!sub.enabled}
      switch={{
        checked: sub.enabled,
        onChange: () => onToggle(!sub.enabled),
        busy: toggling,
        ariaLabel: `Enable ${sub.name}`,
      }}
      badges={
        <>
          <Badge tone="outline">{sub.deliver}</Badge>
          {sub.deliver_only && <Badge tone="secondary">deliver only</Badge>}
        </>
      }
      description={sub.description || undefined}
      detail={
        <div className="flex flex-wrap items-center gap-1">
          {sub.events.length === 0 ? (
            <Badge tone="secondary">(all)</Badge>
          ) : (
            sub.events.map((evt) => (
              <Badge key={evt} tone="secondary">
                {evt}
              </Badge>
            ))
          )}
        </div>
      }
      meta={
        <>
          <span className="flex min-w-0 items-center gap-1">
            <span className="min-w-0 truncate" title={sub.url}>
              {sub.url}
            </span>
            <CopyButton value={sub.url} />
          </span>
          {sub.created_at && (
            <>
              <span aria-hidden="true">·</span>
              <RelativeTime value={sub.created_at} />
            </>
          )}
          {sub.skills.length > 0 && (
            <>
              <span aria-hidden="true">·</span>
              <span title={sub.skills.join(", ")}>
                {sub.skills.length} {sub.skills.length === 1 ? "skill" : "skills"}
              </span>
            </>
          )}
        </>
      }
      actions={
        <Button
          ghost
          destructive
          size="icon"
          title="Delete"
          aria-label="Delete"
          onClick={onDelete}
        >
          <Trash2 />
        </Button>
      }
    />
  );
}
