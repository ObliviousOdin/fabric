import {
  Brain,
  CheckCircle2,
  Circle,
  FileOutput,
  ListTodo,
  SearchCheck,
  type LucideIcon,
} from "lucide-react";
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { ChatSidebar } from "@/components/ChatSidebar";
import {
  EMPTY_CHAT_CONTEXT_STATE,
  reduceChatContextEvent,
  type ChatContextEvent,
  type ChatContextState,
} from "@/components/chat/chat-context-state";
import { StatusSignal } from "@/components/fabric/StatusSignal";
import {
  api,
  type MemorySelectionState,
  type MemoryStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ContextTabId = "task" | "evidence" | "memory" | "artifacts";

interface ContextTab {
  id: ContextTabId;
  icon: LucideIcon;
  label: string;
}

const CONTEXT_TABS: ContextTab[] = [
  { id: "task", label: "Task", icon: ListTodo },
  { id: "evidence", label: "Evidence", icon: SearchCheck },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "artifacts", label: "Artifacts", icon: FileOutput },
];

export interface ChatContextPanelProps {
  channel: string;
  isActive?: boolean;
  onDashboardNewSessionRequest?: () => void;
  onNavigate?: (path: string) => void;
  onSessionTitleChange?: (title: string | null) => void;
  profile?: string;
}

interface ScopedChatContextState {
  channel: string;
  context: ChatContextState;
}

export function ChatContextPanel({
  channel,
  isActive = true,
  onDashboardNewSessionRequest,
  onNavigate,
  onSessionTitleChange,
  profile,
}: ChatContextPanelProps) {
  const [scopedContext, setScopedContext] = useState<ScopedChatContextState>({
    channel,
    context: EMPTY_CHAT_CONTEXT_STATE,
  });
  const context =
    scopedContext.channel === channel
      ? scopedContext.context
      : EMPTY_CHAT_CONTEXT_STATE;
  const onContextEvent = useCallback(
    (event: ChatContextEvent) => {
      setScopedContext((current) => ({
        channel,
        context: reduceChatContextEvent(
          current.channel === channel
            ? current.context
            : EMPTY_CHAT_CONTEXT_STATE,
          event,
        ),
      }));
    },
    [channel],
  );
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <section
        aria-label="Agent status and live activity"
        className="min-h-0 max-h-[48%] shrink-0 overflow-y-auto border-b border-border/70 pb-4"
      >
        <ChatSidebar
          channel={channel}
          contextSnapshot={context}
          isActive={isActive}
          profile={profile}
          onContextEvent={onContextEvent}
          onDashboardNewSessionRequest={onDashboardNewSessionRequest}
          onNavigate={onNavigate}
          onSessionTitleChange={onSessionTitleChange}
        />
      </section>

      <section
        aria-label="Conversation context"
        className="flex min-h-[13rem] flex-1 flex-col overflow-hidden pt-3"
      >
        <ChatContextTabs
          context={context}
          onNavigate={onNavigate}
          profile={profile}
        />
      </section>
    </div>
  );
}

export interface ChatContextTabsProps {
  context?: ChatContextState;
  onNavigate?: (path: string) => void;
  profile?: string;
}

interface MemoryLoadState {
  memory: MemoryStatus | null;
  profile: string;
  status: "loading" | "ready" | "error";
}

const MEMORY_SELECTION_LABEL: Record<MemorySelectionState, string> = {
  builtin_only: "built-in only",
  eligible: "eligible next session",
  missing: "provider missing",
  needs_config: "needs setup",
  readiness_unknown: "readiness unknown",
  tiers_disabled: "memory tiers disabled",
  unavailable: "provider unavailable",
};

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function TaskContext({ context }: { context: ChatContextState }) {
  const completed = context.todos.filter(
    (todo) => todo.status === "completed",
  ).length;
  const signal = !context.connected
    ? { label: "Connecting to current chat", tone: "neutral" as const }
    : context.running
      ? { label: "Working in current chat", tone: "live" as const }
      : { label: "Current chat ready", tone: "success" as const };
  return (
    <div className="flex w-full flex-col gap-4">
      <StatusSignal
        label={signal.label}
        pulse={context.running}
        tone={signal.tone}
      />
      <div>
        <p className="text-sm font-medium text-foreground">
          {context.title || "Terminal-backed chat"}
        </p>
        <p className="mt-1 truncate font-mono-ui text-xs text-text-tertiary">
          {context.cwd || context.sessionId || "Waiting for session identity"}
        </p>
      </div>
      {context.todos.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium text-text-secondary">
            Checklist · {completed}/{context.todos.length} complete
          </p>
          <ul
            className="flex flex-col gap-2"
            aria-label="Current chat checklist"
          >
            {context.todos.map((todo) => {
              const done = todo.status === "completed";
              const Icon = done ? CheckCircle2 : Circle;
              return (
                <li key={todo.id} className="flex items-start gap-2 text-sm">
                  <Icon
                    aria-hidden="true"
                    className={cn(
                      "mt-0.5 h-4 w-4 shrink-0",
                      done ? "text-success" : "text-text-tertiary",
                    )}
                  />
                  <span
                    className={
                      done
                        ? "text-text-tertiary line-through"
                        : "text-foreground"
                    }
                  >
                    {todo.content}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <p className="text-sm leading-relaxed text-text-secondary">
          No structured checklist yet. This panel follows the live chat; the
          Work card above counts only durable items added to its selected board.
        </p>
      )}
    </div>
  );
}

function EvidenceContext({ context }: { context: ChatContextState }) {
  if (context.evidence.length === 0) {
    return (
      <div className="flex w-full flex-col gap-4">
        <StatusSignal label="No tool evidence yet" tone="neutral" />
        <p className="text-sm leading-relaxed text-text-secondary">
          Tool names, live state, duration, and result summaries will appear
          here as this chat works.
        </p>
      </div>
    );
  }
  return (
    <div className="flex w-full flex-col gap-3">
      <StatusSignal
        label={`${context.evidence.length} recent tool ${context.evidence.length === 1 ? "event" : "events"}`}
        tone={context.evidence.some((row) => row.running) ? "live" : "success"}
      />
      <ol className="flex flex-col gap-2" aria-label="Current chat evidence">
        {context.evidence.map((row) => (
          <li key={row.key} className="border-l border-border pl-3 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-mono-ui font-medium text-foreground">
                {row.name}
              </span>
              <span className={row.running ? "text-warning" : "text-success"}>
                {row.running
                  ? "running"
                  : row.durationS !== undefined
                    ? `${row.durationS.toFixed(1)}s`
                    : "complete"}
              </span>
            </div>
            {(row.context || row.summary) && (
              <p className="mt-1 line-clamp-2 text-text-tertiary">
                {row.summary || row.context}
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

function MemoryContext({
  load,
  onNavigate,
}: {
  load: MemoryLoadState;
  onNavigate?: (path: string) => void;
}) {
  if (load.status === "loading") {
    return <StatusSignal label="Loading profile memory" pulse tone="live" />;
  }
  if (load.status === "error" || !load.memory) {
    return (
      <div className="flex w-full flex-col gap-4">
        <StatusSignal label="Memory status unavailable" tone="warning" />
        <p className="text-sm text-text-secondary">
          The chat remains usable, but the dashboard could not read this
          profile&apos;s memory configuration.
        </p>
      </div>
    );
  }
  const memory = load.memory;
  const memoryBytes = memory.builtin_files.memory || 0;
  const userBytes = memory.builtin_files.user || 0;
  const configured =
    memory.selection?.configured || memory.active || "built-in only";
  const selectionState: MemorySelectionState =
    memory.selection?.state ||
    (memory.active ? "readiness_unknown" : "builtin_only");
  const selectionLabel =
    MEMORY_SELECTION_LABEL[selectionState] || "readiness unknown";
  return (
    <div className="flex w-full flex-col gap-4">
      <StatusSignal
        label={
          memoryBytes + userBytes > 0
            ? "Built-in memory files available"
            : "Built-in memory files are empty"
        }
        tone={memoryBytes + userBytes > 0 ? "success" : "neutral"}
      />
      <div className="text-sm text-foreground">
        <p>
          <span className="text-text-tertiary">Configured provider</span> ·{" "}
          {configured}
        </p>
        <p className="mt-1">
          <span className="text-text-tertiary">Selection state</span> ·{" "}
          {selectionLabel}
        </p>
        <p className="mt-1">
          <span className="text-text-tertiary">MEMORY.md</span> ·{" "}
          {formatBytes(memoryBytes)}
        </p>
        <p className="mt-1">
          <span className="text-text-tertiary">USER.md</span> ·{" "}
          {formatBytes(userBytes)}
        </p>
      </div>
      <p className="text-xs leading-relaxed text-text-tertiary">
        Live provider activation, retrieval excerpts, and provenance are not
        reported by this terminal session, so this panel does not invent them.
      </p>
      {onNavigate && (
        <button
          className="min-h-9 self-start border border-border px-3 text-xs font-medium text-foreground hover:bg-muted/50"
          onClick={() => onNavigate("/workspace/memory")}
          type="button"
        >
          Open Memory
        </button>
      )}
    </div>
  );
}

function ArtifactsContext({ context }: { context: ChatContextState }) {
  if (context.artifacts.length === 0) {
    return (
      <div className="flex w-full flex-col gap-4">
        <StatusSignal label="No artifacts detected yet" tone="neutral" />
        <p className="text-sm leading-relaxed text-text-secondary">
          File, image, and export paths reported by this chat&apos;s tools will
          appear here automatically.
        </p>
      </div>
    );
  }
  return (
    <div className="flex w-full flex-col gap-3">
      <StatusSignal
        label={`${context.artifacts.length} ${context.artifacts.length === 1 ? "artifact" : "artifacts"}`}
        tone="success"
      />
      <ul className="flex flex-col gap-2" aria-label="Current chat artifacts">
        {context.artifacts.map((artifact) => (
          <li
            key={artifact.key}
            className="min-w-0 border-l border-border pl-3"
          >
            <p
              className="truncate text-sm font-medium text-foreground"
              title={artifact.value}
            >
              {artifact.label}
            </p>
            <p
              className="truncate font-mono-ui text-xs text-text-tertiary"
              title={artifact.value}
            >
              {artifact.value}
            </p>
            <p className="mt-0.5 text-[0.6875rem] text-text-tertiary">
              via {artifact.source}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ChatContextTabs({
  context = EMPTY_CHAT_CONTEXT_STATE,
  onNavigate,
  profile,
}: ChatContextTabsProps) {
  const [active, setActive] = useState<ContextTabId>("task");
  const baseId = useId();
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const profileKey = profile ?? "";
  const [memoryLoad, setMemoryLoad] = useState<MemoryLoadState>({
    memory: null,
    profile: profileKey,
    status: "loading",
  });
  const visibleMemoryLoad =
    memoryLoad.profile === profileKey
      ? memoryLoad
      : { memory: null, profile: profileKey, status: "loading" as const };

  useEffect(() => {
    let cancelled = false;
    void api
      .getMemory(profileKey)
      .then((memory) => {
        if (!cancelled)
          setMemoryLoad({ memory, profile: profileKey, status: "ready" });
      })
      .catch(() => {
        if (!cancelled)
          setMemoryLoad({ memory: null, profile: profileKey, status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [profileKey]);

  const activeTab =
    CONTEXT_TABS.find((tab) => tab.id === active) ?? CONTEXT_TABS[0];
  const ActiveIcon = activeTab.icon;

  const selectTab = (index: number, focus = false) => {
    const tab = CONTEXT_TABS[index];
    setActive(tab.id);
    if (focus) tabRefs.current[index]?.focus();
  };

  const handleKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % CONTEXT_TABS.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + CONTEXT_TABS.length) % CONTEXT_TABS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = CONTEXT_TABS.length - 1;
    }

    if (nextIndex === null) return;
    event.preventDefault();
    selectTab(nextIndex, true);
  };

  const panel =
    active === "task" ? (
      <TaskContext context={context} />
    ) : active === "evidence" ? (
      <EvidenceContext context={context} />
    ) : active === "memory" ? (
      <MemoryContext load={visibleMemoryLoad} onNavigate={onNavigate} />
    ) : (
      <ArtifactsContext context={context} />
    );

  return (
    <>
      <div
        aria-label="Context type"
        className="flex shrink-0 overflow-x-auto border-b border-border/70"
        role="tablist"
      >
        {CONTEXT_TABS.map((tab, index) => {
          const selected = active === tab.id;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                tabRefs.current[index] = node;
              }}
              aria-controls={`${baseId}-${tab.id}-panel`}
              aria-selected={selected}
              className={cn(
                "relative min-h-11 shrink-0 px-2 text-sm font-medium",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/45",
                selected
                  ? "text-foreground after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:bg-primary"
                  : "text-text-secondary hover:text-foreground",
              )}
              id={`${baseId}-${tab.id}-tab`}
              onClick={() => selectTab(index)}
              onKeyDown={(event) => handleKeyDown(event, index)}
              role="tab"
              tabIndex={selected ? 0 : -1}
              type="button"
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div
        aria-labelledby={`${baseId}-${activeTab.id}-tab`}
        className="relative flex min-h-0 flex-1 flex-col items-start justify-start overflow-y-auto px-4 py-6 text-left"
        id={`${baseId}-${activeTab.id}-panel`}
        role="tabpanel"
        tabIndex={0}
      >
        <span
          aria-hidden
          className="absolute bottom-6 left-0 top-6 w-0.5 bg-primary/45"
        />
        <span
          aria-hidden
          className="absolute left-0 top-6 h-0.5 w-4 bg-primary/45"
        />
        <ActiveIcon
          aria-hidden="true"
          className="mb-5 h-5 w-5 shrink-0 text-text-tertiary"
        />
        {panel}
      </div>
    </>
  );
}
