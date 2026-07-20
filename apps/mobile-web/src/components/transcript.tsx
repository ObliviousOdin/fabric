import type {
  RemoteMessage,
  RemoteReasoningPart,
  RemoteToolPart,
} from "@fabric/shared";
import {
  IconAlertCircle,
  IconArrowDown,
  IconCheck,
  IconChevronRight,
  IconLoader2,
  IconTerminal2,
} from "@tabler/icons-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

const Streamdown = lazy(async () => {
  const module = await import("streamdown");
  return { default: module.Streamdown };
});

interface TranscriptProps {
  connected: boolean;
  messages: RemoteMessage[];
  onSuggestion: (text: string) => void;
  running: boolean;
}

interface MarkdownContentProps {
  children: string;
  mode: "static" | "streaming";
}

function MarkdownContent({ children, mode }: MarkdownContentProps) {
  return (
    <Suspense fallback={<span className="markdown-fallback">{children}</span>}>
      <Streamdown controls={false} mode={mode}>{children}</Streamdown>
    </Suspense>
  );
}

function stringify(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function ToolPart({ part }: { part: RemoteToolPart }) {
  const result = stringify(part.result);
  return (
    <details className={`tool-part ${part.error ? "failed" : ""}`}>
      <summary>
        <span className="tool-part-chevron"><IconChevronRight size={14} /></span>
        <span className="tool-part-icon">
          {part.status === "running" ? (
            <IconLoader2 className="spin" size={15} />
          ) : part.error ? (
            <IconAlertCircle size={15} />
          ) : (
            <IconCheck size={15} />
          )}
        </span>
        <span className="tool-part-name">{part.name}</span>
        <span className="tool-part-status">
          {part.status === "running" ? "Running" : part.error ? "Failed" : "Done"}
        </span>
      </summary>
      <div className="tool-detail">
        {Object.keys(part.args).length > 0 && (
          <section>
            <h4>Input</h4>
            <pre>{stringify(part.args)}</pre>
          </section>
        )}
        {result && (
          <section>
            <h4>Result</h4>
            <pre>{result}</pre>
          </section>
        )}
      </div>
    </details>
  );
}

function Reasoning({ parts, pending }: { parts: RemoteReasoningPart[]; pending: boolean }) {
  const text = parts.map((part) => part.text).join("");
  if (!text) {
    return null;
  }
  return (
    <details className="reasoning-block" open={pending || undefined}>
      <summary>
        {pending && <IconLoader2 className="spin" size={14} />}
        {pending ? "Working through it" : "Reasoning"}
      </summary>
      <div className="reasoning-copy">{text}</div>
    </details>
  );
}

function AssistantMessage({ message }: { message: RemoteMessage }) {
  const reasoning = message.parts.filter(
    (part): part is RemoteReasoningPart => part.type === "reasoning",
  );

  return (
    <article className="message assistant-message" aria-live={message.pending ? "polite" : undefined}>
      <div className="assistant-mark" aria-hidden="true">
        <img src={`${import.meta.env.BASE_URL}fabric-mark-32.png`} alt="" />
      </div>
      <div className="message-content">
        <Reasoning parts={reasoning} pending={Boolean(message.pending)} />
        {message.parts.map((part, index) => {
          if (part.type === "reasoning") {
            return null;
          }
          if (part.type === "tool") {
            return <ToolPart key={`${part.id}-${index}`} part={part} />;
          }
          return (
            <div className="markdown-body" key={`text-${index}`}>
              <MarkdownContent mode={message.pending ? "streaming" : "static"}>
                {part.text}
              </MarkdownContent>
            </div>
          );
        })}
        {message.pending && message.parts.length === 0 && (
          <div className="thinking-line"><span /><span /><span /></div>
        )}
        {message.error && <p className="message-error">{message.error}</p>}
      </div>
    </article>
  );
}

function MessageRow({ message }: { message: RemoteMessage }) {
  if (message.role === "assistant") {
    return <AssistantMessage message={message} />;
  }
  const text = message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
  if (message.role === "system") {
    return (
      <article className="system-message">
        <IconTerminal2 size={15} />
        <div className="markdown-body compact">
          <MarkdownContent mode="static">{text}</MarkdownContent>
        </div>
      </article>
    );
  }
  return (
    <article className="message user-message">
      <div className="user-bubble">{text}</div>
    </article>
  );
}

const SUGGESTIONS = [
  "What changed in this project since yesterday?",
  "Review the current branch and flag the highest-risk issue.",
  "Run the relevant tests and summarize any failures.",
];

function EmptyTranscript({
  connected,
  onSuggestion,
}: Pick<TranscriptProps, "connected" | "onSuggestion">) {
  return (
    <div className="empty-transcript">
      <img src={`${import.meta.env.BASE_URL}fabric-mark-192.png`} alt="" />
      <p className="eyebrow">
        {connected ? "Ready on your gateway" : "Gateway disconnected"}
      </p>
      <h2>{connected ? "What are we working on?" : "Reconnect to continue."}</h2>
      <p>
        {connected
          ? "Start a task here or resume a session from the sidebar."
          : "Your draft is safe. Reconnect to refresh this gateway's sessions and work."}
      </p>
      {connected && (
        <div className="suggestion-list">
          {SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" onClick={() => onSuggestion(suggestion)}>
              <span>{suggestion}</span>
              <IconChevronRight size={16} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Transcript({
  connected,
  messages,
  onSuggestion,
  running,
}: TranscriptProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const streamVersion = useMemo(
    () =>
      messages
        .at(-1)
        ?.parts.map((part) =>
          part.type === "tool"
            ? `${part.id}:${part.status}`
            : `${part.type}:${part.text.length}`,
        )
        .join("|") ?? "",
    [messages],
  );

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const scroller = scrollerRef.current;
    if (scroller) {
      scroller.scrollTo({ behavior, top: scroller.scrollHeight });
    }
  };

  useEffect(() => {
    if (atBottom) {
      scrollToBottom(messages.length < 3 ? "auto" : "smooth");
    }
  }, [atBottom, messages.length, streamVersion]);

  const updateBottom = () => {
    const scroller = scrollerRef.current;
    if (!scroller) {
      return;
    }
    setAtBottom(scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 96);
  };

  return (
    <div className="transcript-shell">
      <div className="transcript" ref={scrollerRef} onScroll={updateBottom}>
        <div className="transcript-inner">
          {messages.length ? (
            messages.map((message) => <MessageRow key={message.id} message={message} />)
          ) : (
            <EmptyTranscript connected={connected} onSuggestion={onSuggestion} />
          )}
          {running && messages.at(-1)?.role !== "assistant" && (
            <div className="waiting-for-agent"><IconLoader2 className="spin" size={16} /> Starting agent…</div>
          )}
        </div>
      </div>
      {!atBottom && (
        <button className="jump-latest" type="button" onClick={() => scrollToBottom()}>
          <IconArrowDown size={16} /> Latest
        </button>
      )}
    </div>
  );
}
