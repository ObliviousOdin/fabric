import { Badge } from "@/components/fabric/Badge";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { AGENT_STATUS_TONES, type AgentStatus } from "./agent-status";

export type {
  AgentStatus,
  DerivedAgentStatus,
} from "./agent-status";

export interface AgentStatusBadgeProps {
  status: AgentStatus;
  /** Override the default label (e.g. "connecting…", "disabled"); default = status word. */
  label?: string;
  /** Force/suppress the pulsing dot; default: true only for "live". */
  pulse?: boolean;
  className?: string;
}

/**
 * The shared status badge for the canonical `AgentStatus` vocabulary
 * (mapping helpers live in `./agent-status`): DS `Badge` with the G1 tone
 * and an optional pulsing dot (the exact idiom SessionsPage already uses
 * for "live"). Labels lowercase, `text-xs`.
 */
export function AgentStatusBadge({
  status,
  label,
  pulse,
  className,
}: AgentStatusBadgeProps) {
  const { t } = useI18n();
  const showDot = pulse ?? status === "live";
  return (
    <Badge
      tone={AGENT_STATUS_TONES[status]}
      className={cn("shrink-0 lowercase text-xs", className)}
    >
      {showDot && (
        <span
          aria-hidden="true"
          className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none"
        />
      )}
      {label ?? t.agentStatus?.[status] ?? status}
    </Badge>
  );
}
