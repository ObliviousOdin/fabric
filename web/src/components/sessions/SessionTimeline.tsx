import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/lib/api";
import type { SessionInfo, SessionMessage } from "@/lib/api";
import { Markdown } from "@/components/Markdown";
import { Button } from "@nous-research/ui/ui/components/button";
import { ListItem } from "@nous-research/ui/ui/components/list-item";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import {
  MonoId,
  Skeleton,
  TimelineNode,
  type TimelineNodeKind,
} from "@/components/ui";
import { useI18n } from "@/i18n";
import { splitCompactionContent } from "./compaction";

/** S5: sessions longer than this fetch the tail first and page backwards. */
const TAIL_LIMIT = 200;

function ToolCallBlock({
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
    <div className="mt-2 border border-warning/20 bg-warning/5">
      <ListItem
        onClick={() => setOpen(!open)}
        aria-label={`${open ? t.common.collapse : t.common.expand} tool call ${toolCall.function.name}`}
        aria-expanded={open}
        className="px-3 py-2 text-xs text-warning hover:bg-warning/10 hover:text-warning"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span className="font-mono-ui font-medium">
          {toolCall.function.name}
        </span>
        <span className="ml-auto">
          <MonoId id={toolCall.id} className="text-muted-foreground" />
        </span>
      </ListItem>
      {open && (
        <pre className="border-t border-warning/20 px-3 py-2 text-xs text-muted-foreground overflow-x-auto whitespace-pre-wrap font-mono">
          {args}
        </pre>
      )}
    </div>
  );
}

const KNOWN_KINDS: ReadonlySet<string> = new Set([
  "user",
  "assistant",
  "system",
  "tool",
]);

/**
 * One transcript message → one (or two, for merged compaction handoffs)
 * `TimelineNode`s. Role → kind mapping per S4; the #29824 compaction
 * split is retained verbatim and feeds `kind="handoff"`.
 */
function MessageNode({
  msg,
  highlight,
}: {
  msg: SessionMessage;
  highlight?: string;
}) {
  const { t } = useI18n();

  // When a compaction handoff is merged into the front of the first
  // tail message (the compressor's double-collision path —
  // ``_merge_summary_into_tail`` in ``agent/context_compressor.py``),
  // the message we received is ``[CONTEXT COMPACTION ...] + END_MARKER
  // + <original assistant reply>``. Split it back into two visual
  // nodes so the operator's actual answer survives as a readable node
  // next to the (clearly-labelled) handoff metadata (#29824).
  const compactionSplit =
    typeof msg.content === "string"
      ? splitCompactionContent(msg.content)
      : null;

  if (compactionSplit && compactionSplit.remainder) {
    return (
      <>
        <MessageNode
          msg={{ ...msg, content: compactionSplit.summary }}
          highlight={highlight}
        />
        {/* The remainder is the original reply the compressor pre-pended
            the summary to — ``splitCompactionContent`` returns null on
            the stripped content, so it renders with its real role. */}
        <MessageNode
          msg={{ ...msg, content: compactionSplit.remainder }}
          highlight={highlight}
        />
      </>
    );
  }

  const isCompaction = compactionSplit !== null;
  const kind: TimelineNodeKind = isCompaction
    ? "handoff"
    : KNOWN_KINDS.has(msg.role)
      ? msg.role
      : "system";
  const roleLabel =
    t.sessions.roles[
      (KNOWN_KINDS.has(msg.role) ? msg.role : "system") as
        | "user"
        | "assistant"
        | "system"
        | "tool"
    ];
  const label = isCompaction
    ? "Context handoff"
    : msg.tool_name
      ? `${t.sessions.roles.tool}: ${msg.tool_name}`
      : roleLabel;

  // Check if any search term appears anywhere in the content (existing
  // FTS hit heuristic, preserved — N2).
  const isHit = (() => {
    if (!highlight || !msg.content) return false;
    const content = msg.content.toLowerCase();
    const terms = highlight.toLowerCase().split(/\s+/).filter(Boolean);
    return terms.some((term) => content.includes(term));
  })();

  const highlightTerms =
    isHit && highlight ? highlight.split(/\s+/).filter(Boolean) : undefined;

  return (
    <TimelineNode kind={kind} label={label} timestamp={msg.timestamp} hit={isHit}>
      {msg.content &&
        (msg.role === "system" ? (
          <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
            {msg.content}
          </div>
        ) : (
          <Markdown content={msg.content} highlightTerms={highlightTerms} />
        ))}
      {msg.tool_calls && msg.tool_calls.length > 0 && (
        <div className="mt-1">
          {msg.tool_calls.map((tc) => (
            <ToolCallBlock key={tc.id} toolCall={tc} />
          ))}
        </div>
      )}
    </TimelineNode>
  );
}

export interface SessionTimelineProps {
  session: SessionInfo;
  /** Active FTS query — drives hit rings + auto-scroll-to-first-hit. */
  searchQuery?: string;
}

/**
 * Row-expansion chronology (S4): context header (S6), tail-first fetch
 * with backwards paging for long transcripts (S5), `TimelineNode`s with
 * the preserved #29824 compaction split, and inline fetch errors with
 * Retry (S11).
 */
export function SessionTimeline({ session, searchQuery }: SessionTimelineProps) {
  const [messages, setMessages] = useState<SessionMessage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped by the Retry button to re-run the fetch effect.
  const [fetchNonce, setFetchNonce] = useState(0);
  // Offset of the earliest fetched message within the full transcript;
  // 0 = the whole history is loaded. Derived from `message_count` — the
  // messages endpoint returns no total (spec §0.1).
  const [earliestOffset, setEarliestOffset] = useState(0);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();
  const L = t.sessions.ledger;

  // Loading is derived (no synchronous setState in the fetch effect):
  // nothing fetched yet and no error → we're loading.
  const loading = messages === null && error === null;

  useEffect(() => {
    let cancelled = false;
    const tailOffset =
      session.message_count > TAIL_LIMIT
        ? session.message_count - TAIL_LIMIT
        : 0;
    const fetchPromise =
      tailOffset > 0
        ? api.getSessionMessages(session.id, undefined, {
            limit: TAIL_LIMIT,
            offset: tailOffset,
          })
        : api.getSessionMessages(session.id);
    fetchPromise
      .then((resp) => {
        if (cancelled) return;
        setMessages(resp.messages);
        setEarliestOffset(tailOffset);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [session.id, session.message_count, fetchNonce]);

  // S11: Retry re-runs the initial fetch (from an event handler, so the
  // reset back to the loading state is legal here).
  const retry = useCallback(() => {
    setMessages(null);
    setError(null);
    setFetchNonce((n) => n + 1);
  }, []);

  const loadEarlier = useCallback(() => {
    if (earliestOffset <= 0 || loadingEarlier) return;
    setLoadingEarlier(true);
    const newOffset = Math.max(0, earliestOffset - TAIL_LIMIT);
    api
      .getSessionMessages(session.id, undefined, {
        limit: earliestOffset - newOffset,
        offset: newOffset,
      })
      .then((resp) => {
        setMessages((prev) => [...resp.messages, ...(prev ?? [])]);
        setEarliestOffset(newOffset);
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoadingEarlier(false));
  }, [earliestOffset, loadingEarlier, session.id]);

  // Auto-scroll to the first FTS hit after render (preserved — N2), with
  // a motion-reduce guard on the smooth behavior.
  useEffect(() => {
    if (!searchQuery || !containerRef.current) return;
    const timer = setTimeout(() => {
      const hit = containerRef.current?.querySelector("[data-search-hit]");
      if (hit) {
        const reduceMotion = window.matchMedia?.(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        hit.scrollIntoView({
          behavior: reduceMotion ? "auto" : "smooth",
          block: "center",
        });
      }
    }, 50);
    return () => clearTimeout(timer);
  }, [messages, searchQuery]);

  // S6: one mono context line above the timeline.
  const contextSegments: { key: string; title: string; value: string }[] = [];
  if (session.cwd) {
    contextSegments.push({
      key: "cwd",
      title: L?.contextCwd ?? "working directory",
      value: session.cwd,
    });
  }
  if (session.git_branch) {
    contextSegments.push({
      key: "branch",
      title: L?.contextBranch ?? "git branch",
      value: session.git_branch,
    });
  }
  if (session.ended_at !== null && session.end_reason) {
    contextSegments.push({
      key: "end",
      title: L?.contextEndReason ?? "end reason",
      value: session.end_reason,
    });
  }
  if (session.model) {
    contextSegments.push({
      key: "model",
      title: L?.contextModel ?? "model",
      value: session.model,
    });
  }

  return (
    <div className="min-w-0">
      {contextSegments.length > 0 && (
        <div className="mb-3 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 font-mono-ui text-xs text-muted-foreground">
          {contextSegments.map((seg, i) => (
            <Fragment key={seg.key}>
              {i > 0 && (
                <span aria-hidden="true" className="text-border">
                  &#183;
                </span>
              )}
              <span
                title={`${seg.title}: ${seg.value}`}
                className="max-w-full truncate"
              >
                {seg.value}
              </span>
            </Fragment>
          ))}
        </div>
      )}

      {loading && <Skeleton variant="row-list" rows={4} className="py-2" />}

      {error && (
        <div className="flex flex-col items-center gap-2 py-4">
          <p className="text-sm text-destructive text-center">{error}</p>
          <Button outlined size="sm" onClick={retry}>
            {t.common.retry}
          </Button>
        </div>
      )}

      {messages && messages.length === 0 && !error && (
        <p className="text-sm text-muted-foreground py-4 text-center">
          {t.sessions.noMessages}
        </p>
      )}

      {messages && messages.length > 0 && (
        <div
          ref={containerRef}
          className="flex max-h-[600px] flex-col overflow-y-auto pr-2"
        >
          {earliestOffset > 0 && (
            <ListItem
              onClick={loadEarlier}
              aria-label={L?.loadEarlier ?? "Load earlier messages"}
              className="mb-2 justify-center border border-border py-1.5 text-xs text-muted-foreground"
            >
              {loadingEarlier ? (
                <Spinner className="text-sm" />
              ) : (
                <>
                  <span className="font-mondwest normal-case">
                    {L?.loadEarlier ?? "Load earlier messages"}
                  </span>
                  <span className="font-mono-ui tabular-nums">
                    ({earliestOffset})
                  </span>
                </>
              )}
            </ListItem>
          )}
          {messages.map((msg, i) => (
            <MessageNode key={i} msg={msg} highlight={searchQuery} />
          ))}
        </div>
      )}
    </div>
  );
}
