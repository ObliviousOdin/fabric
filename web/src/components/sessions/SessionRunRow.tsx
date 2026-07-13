import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Download, Pencil, Play, Trash2, X } from "lucide-react";
import type { SessionInfo } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import {
  RunRow,
  formatCompact,
  formatCost,
  sessionAgentStatus,
  sourceIcon,
} from "@/components/ui";
import { useI18n } from "@/i18n";
import { SnippetHighlight } from "./SnippetHighlight";
import { SessionTimeline } from "./SessionTimeline";

export interface SessionRunRowProps {
  session: SessionInfo;
  snippet?: string;
  searchQuery?: string;
  isExpanded: boolean;
  isSelected: boolean;
  onToggle: () => void;
  onSelectClick: (event: React.MouseEvent) => void;
  onDelete: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onExport: (id: string) => void;
  resumeInChatEnabled: boolean;
}

/**
 * One session as a "run" in the ledger (S2): shared `RunRow` chrome,
 * inline rename editor, preserved action set (resume / rename / export /
 * delete), FTS snippet subline, and the S4 timeline as the expansion body.
 */
export function SessionRunRow({
  session,
  snippet,
  searchQuery,
  isExpanded,
  isSelected,
  onToggle,
  onSelectClick,
  onDelete,
  onRename,
  onExport,
  resumeInChatEnabled,
}: SessionRunRowProps) {
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(session.title ?? "");
  const [renameSaving, setRenameSaving] = useState(false);
  const { t } = useI18n();
  const navigate = useNavigate();

  const hasTitle = session.title && session.title !== "Untitled";

  const submitRename = async () => {
    const value = renameValue.trim();
    if (!value || value === session.title) {
      setRenaming(false);
      return;
    }
    setRenameSaving(true);
    try {
      await onRename(session.id, value);
      setRenaming(false);
    } finally {
      setRenameSaving(false);
    }
  };

  const title = renaming ? (
    <span
      className="flex min-w-0 items-center gap-1.5"
      onClick={(e) => e.stopPropagation()}
    >
      <Input
        autoFocus
        value={renameValue}
        onChange={(e) => setRenameValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void submitRename();
          else if (e.key === "Escape") setRenaming(false);
        }}
        placeholder="Session title"
        className="h-7 min-w-0 flex-1 py-0 text-sm"
        disabled={renameSaving}
      />
      <Button
        ghost
        size="icon"
        className="text-muted-foreground hover:text-success"
        aria-label="Save title"
        title="Save title"
        disabled={renameSaving}
        onClick={() => void submitRename()}
      >
        {renameSaving ? <Spinner className="text-sm" /> : <Check />}
      </Button>
      <Button
        ghost
        size="icon"
        className="text-muted-foreground hover:text-foreground"
        aria-label="Cancel rename"
        title="Cancel rename"
        disabled={renameSaving}
        onClick={() => setRenaming(false)}
      >
        <X />
      </Button>
    </span>
  ) : (
    <span className={hasTitle ? "font-medium" : "text-muted-foreground italic"}>
      {hasTitle
        ? session.title
        : session.preview
          ? session.preview.slice(0, 60)
          : t.sessions.untitledSession}
    </span>
  );

  // Meta counters (S2): mono, `·`-separated; zero-valued segments render
  // conditionally so rows never show `↑0 ↓0` / `$0.00` noise (R4).
  const metaParts: ReactNode[] = [
    <span key="msgs" className="font-mono-ui tabular-nums shrink-0">
      {session.message_count} {t.common.msgs}
    </span>,
  ];
  if (session.tool_call_count > 0) {
    metaParts.push(
      <span key="tools" className="font-mono-ui tabular-nums shrink-0">
        {session.tool_call_count} {t.common.tools}
      </span>,
    );
  }
  if (session.input_tokens > 0 || session.output_tokens > 0) {
    metaParts.push(
      <span key="tokens" className="font-mono-ui tabular-nums shrink-0">
        &#8593;{formatCompact(session.input_tokens)} &#8595;
        {formatCompact(session.output_tokens)}
      </span>,
    );
  }
  if (session.estimated_cost_usd != null && session.estimated_cost_usd > 0) {
    metaParts.push(
      <span key="cost" className="font-mono-ui tabular-nums shrink-0">
        {formatCost(session.estimated_cost_usd)}
      </span>,
    );
  }

  const actions = (
    <>
      {resumeInChatEnabled && (
        <Button
          ghost
          size="icon"
          className="text-muted-foreground hover:text-success"
          aria-label={t.sessions.resumeInChat}
          title={t.sessions.resumeInChat}
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/chat?resume=${encodeURIComponent(session.id)}`);
          }}
        >
          <Play />
        </Button>
      )}

      <Button
        ghost
        size="icon"
        className="text-muted-foreground hover:text-foreground"
        aria-label="Rename session"
        title="Rename session"
        onClick={(e) => {
          e.stopPropagation();
          setRenameValue(
            session.title && session.title !== "Untitled" ? session.title : "",
          );
          setRenaming(true);
        }}
      >
        <Pencil />
      </Button>

      <Button
        ghost
        size="icon"
        className="text-muted-foreground hover:text-foreground"
        aria-label="Export session"
        title="Export session JSON"
        onClick={(e) => {
          e.stopPropagation();
          onExport(session.id);
        }}
      >
        <Download />
      </Button>

      <Button
        ghost
        destructive
        size="icon"
        aria-label={t.sessions.deleteSession}
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
      >
        <Trash2 />
      </Button>
    </>
  );

  return (
    <RunRow
      title={title}
      status={sessionAgentStatus(session)}
      id={session.id}
      sourceIcon={sourceIcon(session.source)}
      model={(session.model ?? t.common.unknown).split("/").pop()}
      meta={metaParts.map((node, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <span aria-hidden="true" className="text-border">
              &#183;
            </span>
          )}
          {node}
        </Fragment>
      ))}
      timestamp={session.last_active}
      subline={snippet ? <SnippetHighlight snippet={snippet} /> : undefined}
      selected={isSelected}
      onSelectClick={onSelectClick}
      expanded={isExpanded}
      onToggle={onToggle}
      actions={actions}
    >
      <div className="min-w-0 bg-background/50 p-4">
        <SessionTimeline session={session} searchQuery={searchQuery} />
      </div>
    </RunRow>
  );
}
