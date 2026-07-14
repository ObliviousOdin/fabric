import {
  Brain,
  FileOutput,
  ListTodo,
  SearchCheck,
  type LucideIcon,
} from "lucide-react";
import { type KeyboardEvent, useId, useRef, useState } from "react";

import { ChatSidebar } from "@/components/ChatSidebar";
import { StatusSignal } from "@/components/fabric/StatusSignal";
import { cn } from "@/lib/utils";

type ContextTabId = "task" | "evidence" | "memory" | "artifacts";

interface ContextTab {
  description: string;
  id: ContextTabId;
  icon: LucideIcon;
  label: string;
  title: string;
}

const CONTEXT_TABS: ContextTab[] = [
  {
    id: "task",
    label: "Task",
    icon: ListTodo,
    title: "Task context is unavailable",
    description:
      "This terminal-backed chat does not expose linked task data to the dashboard yet.",
  },
  {
    id: "evidence",
    label: "Evidence",
    icon: SearchCheck,
    title: "Evidence is unavailable",
    description:
      "Live evidence is not exposed to this panel yet. Tool output remains visible in the center transcript.",
  },
  {
    id: "memory",
    label: "Memory",
    icon: Brain,
    title: "Memory context is unavailable",
    description:
      "Retrieved memory, provenance, and correction history are not exposed to this panel yet.",
  },
  {
    id: "artifacts",
    label: "Artifacts",
    icon: FileOutput,
    title: "Artifact previews are unavailable",
    description:
      "Artifact previews are not exposed to this panel yet. Created files remain visible through terminal output.",
  },
];

export interface ChatContextPanelProps {
  channel: string;
  isActive?: boolean;
  onDashboardNewSessionRequest?: () => void;
  onNavigate?: (path: string) => void;
  onSessionTitleChange?: (title: string | null) => void;
  profile?: string;
}

export function ChatContextPanel({
  channel,
  isActive = true,
  onDashboardNewSessionRequest,
  onNavigate,
  onSessionTitleChange,
  profile,
}: ChatContextPanelProps) {
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <section
        aria-label="Agent status and live activity"
        className="min-h-0 max-h-[48%] shrink-0 overflow-y-auto border-b border-border/70 pb-4"
      >
        <ChatSidebar
          channel={channel}
          isActive={isActive}
          profile={profile}
          onDashboardNewSessionRequest={onDashboardNewSessionRequest}
          onNavigate={onNavigate}
          onSessionTitleChange={onSessionTitleChange}
        />
      </section>

      <section
        aria-label="Conversation context"
        className="flex min-h-[13rem] flex-1 flex-col overflow-hidden pt-3"
      >
        <ChatContextTabs />
      </section>
    </div>
  );
}

export function ChatContextTabs() {
  const [active, setActive] = useState<ContextTabId>("task");
  const baseId = useId();
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
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
        className="relative flex min-h-0 flex-1 flex-col items-start justify-start px-4 py-6 text-left"
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
          className="mb-5 h-5 w-5 text-text-tertiary"
        />
        <StatusSignal label="Contract not connected" tone="neutral" />
        <p className="mt-4 text-sm font-medium text-foreground">
          {activeTab.title}
        </p>
        <p className="mt-1 max-w-64 text-sm leading-relaxed text-text-secondary">
          {activeTab.description}
        </p>
        <p className="mt-5 text-xs text-text-tertiary">
          Unavailable in this view · source remains the terminal transcript
        </p>
      </div>
    </>
  );
}
