import { MessagesSquare, PanelRight } from "lucide-react";
import {
  type KeyboardEvent,
  type ReactNode,
  useId,
  useRef,
  useState,
} from "react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import type { ChatViewportMode } from "./useChatViewportMode";

type SecondaryPanel = "conversations" | "context";

export interface ChatWorkspaceLayoutProps {
  active: boolean;
  context: ReactNode;
  conversations: ReactNode;
  mode: ChatViewportMode;
  terminal: ReactNode;
}

const SECONDARY_PANELS: SecondaryPanel[] = ["conversations", "context"];

/**
 * Presentation-only layout for the persistent PTY chat. The terminal is
 * always keyed and mounted; only the visible data rail enters the tree.
 */
export function ChatWorkspaceLayout({
  active,
  context,
  conversations,
  mode,
  terminal,
}: ChatWorkspaceLayoutProps) {
  const { t } = useI18n();
  const labels = t.chatWorkspace;
  const [secondary, setSecondary] = useState<SecondaryPanel>("conversations");
  const tabsId = useId();
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const selectSecondary = (panel: SecondaryPanel, focus = false) => {
    setSecondary(panel);
    if (focus) {
      const index = SECONDARY_PANELS.indexOf(panel);
      tabRefs.current[index]?.focus();
    }
  };

  const handleTabKey = (
    event: KeyboardEvent<HTMLButtonElement>,
    panel: SecondaryPanel,
  ) => {
    const index = SECONDARY_PANELS.indexOf(panel);
    let nextIndex: number | null = null;

    if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % SECONDARY_PANELS.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex =
        (index - 1 + SECONDARY_PANELS.length) % SECONDARY_PANELS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = SECONDARY_PANELS.length - 1;
    }

    if (nextIndex === null) return;
    event.preventDefault();
    selectSecondary(SECONDARY_PANELS[nextIndex], true);
  };

  const railClass = cn(
    "min-h-0 min-w-0 overflow-hidden bg-card/20",
  );

  return (
    <div
      className="flex min-h-0 flex-1 overflow-hidden border-y border-border/70"
      data-chat-layout={mode}
    >
      {active && mode === "wide" && (
        <nav
          key="conversations"
          aria-label={labels?.conversations ?? "Conversations"}
          className={cn(railClass, "w-72 shrink-0 border-r border-border/70 px-3 py-4")}
        >
          {conversations}
        </nav>
      )}

      <section
        key="terminal"
        aria-label={labels?.agentChat ?? "Agent chat"}
        className="flex min-h-0 min-w-0 flex-1"
      >
        {terminal}
      </section>

      {active && mode === "wide" && (
        <aside
          key="context"
          aria-label={labels?.taskAndAgentContext ?? "Task and agent context"}
          className={cn(railClass, "w-80 shrink-0 border-l border-border/70 px-3 py-4")}
        >
          {context}
        </aside>
      )}

      {active && mode === "medium" && (
        <section
          key="secondary"
          aria-label={labels?.secondaryPanel ?? "Chat secondary panel"}
          className={cn(
            railClass,
            "flex w-72 shrink-0 flex-col gap-2 border-l border-border/70 px-3 py-4 xl:w-80",
          )}
        >
          <div
            aria-label={labels?.chooseSecondaryPanel ?? "Choose secondary panel"}
            className="grid h-11 shrink-0 grid-cols-2 rounded-md bg-midground/5 p-1"
            role="tablist"
          >
            {SECONDARY_PANELS.map((panel, index) => {
              const selected = secondary === panel;
              const label =
                panel === "conversations"
                  ? labels?.conversations ?? "Conversations"
                  : labels?.context ?? "Context";
              const Icon =
                panel === "conversations" ? MessagesSquare : PanelRight;
              return (
                <button
                  key={panel}
                  ref={(node) => {
                    tabRefs.current[index] = node;
                  }}
                  aria-controls={`${tabsId}-${panel}-panel`}
                  aria-selected={selected}
                  className={cn(
                    "inline-flex min-w-0 items-center justify-center gap-1.5 rounded px-2",
                    "text-sm font-medium transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45",
                    selected
                      ? "bg-background-base text-foreground shadow-sm"
                      : "text-text-secondary hover:text-foreground",
                  )}
                  id={`${tabsId}-${panel}-tab`}
                  onClick={() => selectSecondary(panel)}
                  onKeyDown={(event) => handleTabKey(event, panel)}
                  role="tab"
                  tabIndex={selected ? 0 : -1}
                  type="button"
                >
                  <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
                  <span className="truncate">{label}</span>
                </button>
              );
            })}
          </div>

          <div
            aria-labelledby={`${tabsId}-${secondary}-tab`}
            className="min-h-0 flex-1 overflow-hidden"
            id={`${tabsId}-${secondary}-panel`}
            role="tabpanel"
          >
            {secondary === "conversations" ? conversations : context}
          </div>
        </section>
      )}
    </div>
  );
}
