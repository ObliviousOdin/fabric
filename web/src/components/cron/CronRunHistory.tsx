import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, ChevronRight, Clock, ExternalLink } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { api } from "@/lib/api";
import type { SessionInfo, SessionMessage } from "@/lib/api";
import { Markdown } from "@/components/Markdown";
import {
  EmptyState,
  MonoId,
  RunRow,
  Skeleton,
  TimelineNode,
  type TimelineNodeKind,
} from "@/components/ui";
import { useI18n } from "@/i18n";
import { splitCompactionContent } from "@/components/sessions/compaction";
import { formatCompactCount, formatRunDuration } from "./job-utils";

/**
 * C6 — per-job run-history drawer. Runs are ordinary sessions
 * (`cron_{job}_{ts}`) served by `GET /api/cron/jobs/{id}/runs`, rendered
 * with the shared `RunRow` and expandable into the S4 chronology
 * (`TimelineNode`s over `getSessionMessages`). Run state/error/loading
 * ownership stays in `CronPage` (the C7 trigger-follow poll writes into
 * the same entry); this component only renders it.
 */

export interface CronRunsEntry {
  loading: boolean;
  error: string | null;
  runs: SessionInfo[] | null;
}

const META_SEPARATOR = (
  <span aria-hidden="true" className="text-border">
    &#183;
  </span>
);

// #29824 compaction-handoff detection is shared with the Sessions timeline
// (`@/components/sessions/compaction`) — one copy of the prefixes/END
// marker keeps this drawer in sync with ``agent/context_compressor.py``.

/** Collapsed tool-call block: mono name + `MonoId` of the call id, pretty-printed args on expand (S4). */
function RunToolCall({
  toolCall,
}: {
  toolCall: { id: string; function: { name: string; arguments: string } };
}) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();

  let args = toolCall.function.arguments;
  try {
    args = JSON.stringify(JSON.parse(args), null, 2);
  } catch {
    // keep as-is
  }

  return (
    <div className="mt-1 border border-warning/20 bg-warning/5">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-label={`${open ? t.common.collapse : t.common.expand} ${toolCall.function.name}`}
          className="flex min-w-0 flex-1 items-center gap-2 text-left text-xs text-warning hover:text-warning"
        >
          {open ? (
            <ChevronDown aria-hidden="true" className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronRight aria-hidden="true" className="h-3 w-3 shrink-0" />
          )}
          <span className="font-mono-ui truncate font-medium">
            {toolCall.function.name}
          </span>
        </button>
        <MonoId id={toolCall.id} className="shrink-0 text-warning/60" />
      </div>
      {open && (
        <pre className="overflow-x-auto whitespace-pre-wrap border-t border-warning/20 px-2 py-1.5 font-mono text-xs text-warning/80">
          {args}
        </pre>
      )}
    </div>
  );
}

function nodeBody(msg: SessionMessage) {
  return (
    <>
      {msg.content &&
        (msg.role === "system" ? (
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
            {msg.content}
          </div>
        ) : (
          <Markdown content={msg.content} />
        ))}
      {msg.tool_calls && msg.tool_calls.length > 0 && (
        <div className="mt-1">
          {msg.tool_calls.map((tc) => (
            <RunToolCall key={tc.id} toolCall={tc} />
          ))}
        </div>
      )}
    </>
  );
}

/** S4 chronology over a run transcript, reused inside the cron drawer (C6). */
function CronRunTimeline({ messages }: { messages: SessionMessage[] }) {
  const { t } = useI18n();

  const nodes: React.ReactNode[] = [];
  messages.forEach((msg, i) => {
    const split =
      typeof msg.content === "string"
        ? splitCompactionContent(msg.content)
        : null;

    if (split) {
      nodes.push(
        <TimelineNode
          key={`${i}-handoff`}
          kind="handoff"
          label="Context handoff"
          timestamp={msg.timestamp}
        >
          <div className="whitespace-pre-wrap text-xs italic leading-relaxed text-muted-foreground">
            {split.summary}
          </div>
        </TimelineNode>,
      );
      if (!split.remainder) return;
      // The remainder is the original reply the compressor prefixed the
      // summary onto — render it as its own normal node (#29824).
      msg = { ...msg, content: split.remainder };
    }

    const kind: TimelineNodeKind =
      msg.role === "user" ||
      msg.role === "assistant" ||
      msg.role === "system" ||
      msg.role === "tool"
        ? msg.role
        : "system";
    const label =
      kind === "tool" && msg.tool_name
        ? `${t.sessions.roles.tool}: ${msg.tool_name}`
        : t.sessions.roles[kind];
    nodes.push(
      <TimelineNode key={i} kind={kind} label={label} timestamp={msg.timestamp}>
        {nodeBody(msg)}
      </TimelineNode>,
    );
  });

  return (
    <div className="max-h-[420px] overflow-y-auto p-3">{nodes}</div>
  );
}

/** One run row: shared `RunRow`, "Open in Sessions" action, expand-to-timeline. */
function CronRunItem({ run, profile }: { run: SessionInfo; profile: string }) {
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<SessionMessage[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const navigate = useNavigate();

  const loadMessages = () => {
    setLoading(true);
    setError(null);
    api
      .getSessionMessages(run.id, profile)
      .then((resp) => setMessages(resp.messages))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  };

  // Event-driven fetch (not an effect): first expand loads the transcript,
  // re-expands reuse it; Retry is the explicit refresh path.
  const handleToggle = () => {
    if (!expanded && messages === null && !loading && !error) loadMessages();
    setExpanded((v) => !v);
  };

  const duration = formatRunDuration(run.started_at, run.ended_at);
  const tokens = (run.input_tokens ?? 0) + (run.output_tokens ?? 0);

  const meta = (
    <>
      {duration && (
        <>
          <span className="font-mono-ui tabular-nums">{duration}</span>
          {META_SEPARATOR}
        </>
      )}
      <span className="font-mono-ui tabular-nums">
        {run.message_count} {t.common.msgs}
      </span>
      {run.tool_call_count > 0 && (
        <>
          {META_SEPARATOR}
          <span className="font-mono-ui tabular-nums">
            {run.tool_call_count} {t.common.tools}
          </span>
        </>
      )}
      {tokens > 0 && (
        <>
          {META_SEPARATOR}
          {/* R4: only render token arrows when either count is non-zero. */}
          <span className="font-mono-ui tabular-nums">
            &#8593;{formatCompactCount(run.input_tokens ?? 0)} &#8595;
            {formatCompactCount(run.output_tokens ?? 0)}
          </span>
        </>
      )}
    </>
  );

  return (
    <RunRow
      title={
        run.title ?? (
          <span className="italic text-muted-foreground">
            {t.common.untitled}
          </span>
        )
      }
      // C6: outcome is job-level only (B5) — runs are neutral `done`
      // unless the newest one is still active.
      status={run.is_active ? "live" : "done"}
      id={run.id}
      sourceIcon={Clock}
      model={run.model}
      meta={meta}
      timestamp={run.started_at}
      expanded={expanded}
      onToggle={handleToggle}
      actions={
        <Button
          ghost
          size="icon"
          title={t.cron.agents?.openInSessions ?? "Open in Sessions"}
          aria-label={t.cron.agents?.openInSessions ?? "Open in Sessions"}
          onClick={(e) => {
            e.stopPropagation();
            navigate("/sessions");
          }}
        >
          <ExternalLink />
        </Button>
      }
    >
      {loading && <Skeleton variant="row-list" rows={3} className="p-3" />}
      {error && (
        <div className="flex items-center gap-3 p-3 text-xs text-destructive">
          <span className="min-w-0 flex-1 truncate" title={error}>
            {error}
          </span>
          <Button
            ghost
            size="sm"
            className="uppercase"
            onClick={(e) => {
              e.stopPropagation();
              loadMessages();
            }}
          >
            {t.common.retry}
          </Button>
        </div>
      )}
      {messages !== null && <CronRunTimeline messages={messages} />}
    </RunRow>
  );
}

export interface CronRunHistoryProps {
  /** The job's own profile — run lookups must never use the dashboard profile (R6). */
  profile: string;
  entry: CronRunsEntry | undefined;
  onRetry: () => void;
  /** Same handler as the row's Zap button (C12 empty-state CTA). */
  onTrigger: () => void;
}

export function CronRunHistory({
  profile,
  entry,
  onRetry,
  onTrigger,
}: CronRunHistoryProps) {
  const { t } = useI18n();
  const runs = entry?.runs;

  return (
    <div className="flex flex-col gap-2 p-3">
      <span className="font-mondwest text-display text-xs tracking-wider text-muted-foreground">
        {t.cron.agents?.runHistory ?? "Run history"}
      </span>

      {/* C11: drawer loading — keep any already-loaded rows visible while
          the C7 follow poll refreshes them silently. */}
      {(!entry || (entry.loading && !runs)) && (
        <Skeleton variant="row-list" rows={3} />
      )}

      {entry?.error && !runs && (
        <div className="flex items-center gap-3 border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
          <span className="min-w-0 flex-1 truncate" title={entry.error}>
            {t.cron.agents?.runsLoadFailed ?? "Could not load run history"}
          </span>
          <Button ghost size="sm" className="uppercase" onClick={onRetry}>
            {t.common.retry}
          </Button>
        </div>
      )}

      {runs && runs.length === 0 && (
        <EmptyState
          className="py-6"
          title={t.cron.agents?.noRunsTitle ?? "No runs yet"}
          description={
            t.cron.agents?.noRunsDescription ??
            "Trigger now to run this job immediately."
          }
          action={
            <Button size="sm" className="uppercase" onClick={onTrigger}>
              {t.cron.triggerNow}
            </Button>
          }
        />
      )}

      {runs && runs.length > 0 && (
        <div className="flex flex-col gap-2">
          {runs.map((run) => (
            <CronRunItem key={run.id} run={run} profile={profile} />
          ))}
        </div>
      )}
    </div>
  );
}
