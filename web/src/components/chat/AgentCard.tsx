import { Button } from "@nous-research/ui/ui/components/button";
import { Card } from "@nous-research/ui/ui/components/card";
import { ChevronDown } from "lucide-react";

import { AgentStatusBadge, chatConnectionAgentStatus } from "@/components/ui";
import type { ConnectionState } from "@/lib/gatewayClient";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { formatCompactCount } from "./activity-feed";

export interface AgentCardProps {
  /** Live chat title mirrored into the rail (CH4); null until known. */
  title: string | null;
  /** Full effective model id ("—" until known); goes in the `title` attr. */
  modelName: string;
  /** Short display name (last path segment of the model id). */
  modelLabel: string;
  /** Opens the ModelPickerDialog — flow owned by ChatSidebar (N5). */
  onOpenModelPicker: () => void;
  /** `effective_context_length` from /api/model/info; ≤0 hides the row. */
  contextLength: number;
  /** JSON-RPC sidecar connection state → AgentStatusBadge (G1). */
  connection: ConnectionState;
  /** PTY session cwd from `session.info` (events channel), when known. */
  cwd?: string | null;
}

/**
 * Agent card (CH2) — the evolution of the old model card: chrome label
 * `agent` + connection badge in the header, then the mirrored session
 * title, the model picker row (behavior unchanged — REST read/write, see
 * ChatSidebar), a read-only `ctx` line, and the session cwd.
 */
export function AgentCard({
  title,
  modelName,
  modelLabel,
  onOpenModelPicker,
  contextLength,
  connection,
  cwd,
}: AgentCardProps) {
  const { t } = useI18n();
  const derived = chatConnectionAgentStatus(connection);
  const ctx = contextLength > 0 ? formatCompactCount(contextLength) : "";

  return (
    <Card className="flex shrink-0 flex-col gap-1 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-display text-xs tracking-wider text-text-tertiary">
          {t.chatRail?.agent ?? "agent"}
        </div>
        <AgentStatusBadge status={derived.status} label={derived.label} />
      </div>

      {title && (
        <div
          className="truncate text-sm font-medium normal-case tracking-normal text-foreground"
          title={title}
        >
          {title}
        </div>
      )}

      <Button
        ghost
        size="sm"
        onClick={onOpenModelPicker}
        className={cn(
          "max-w-full min-w-0 px-0 py-0",
          "self-start normal-case tracking-normal text-sm font-medium",
          "hover:underline disabled:no-underline",
        )}
        title={modelName === "—" ? "switch model" : modelName}
      >
        <span className="flex min-w-0 max-w-full items-center gap-1">
          <span className="truncate font-mono-ui">{modelLabel}</span>
          <ChevronDown className="size-3.5 shrink-0 text-text-secondary" />
        </span>
      </Button>

      {ctx && (
        <div className="font-mono-ui text-xs tabular-nums text-text-secondary">
          ctx {ctx}
        </div>
      )}

      {cwd && (
        <div
          className="truncate font-mono-ui text-xs text-text-tertiary"
          title={cwd}
        >
          {cwd}
        </div>
      )}
    </Card>
  );
}
