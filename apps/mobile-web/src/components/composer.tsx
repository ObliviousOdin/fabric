import {
  IconArrowUp,
  IconPaperclip,
  IconPlayerStopFilled,
} from "@tabler/icons-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

interface ComposerProps {
  branch?: string;
  disabled: boolean;
  model?: string;
  onInterrupt: () => Promise<void>;
  onSend: (text: string) => Promise<{ prefill?: string }>;
  onTextChange: (text: string) => void;
  running: boolean;
  text: string;
}

export function Composer({
  branch,
  disabled,
  model,
  onInterrupt,
  onSend,
  onTextChange,
  running,
  text,
}: ComposerProps) {
  const [sending, setSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(160, Math.max(24, textarea.scrollHeight))}px`;
  }, [text]);

  const submit = async () => {
    const value = text.trim();
    if (!value || disabled || sending) {
      return;
    }
    setSending(true);
    onTextChange("");
    try {
      const result = await onSend(value);
      if (result.prefill) {
        onTextChange(result.prefill);
        requestAnimationFrame(() => textareaRef.current?.focus());
      }
    } catch {
      onTextChange(value);
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <footer className="composer-shell">
      <div className="composer">
        <textarea
          ref={textareaRef}
          aria-label="Message Fabric"
          autoFocus
          disabled={disabled}
          placeholder={disabled ? "Reconnect to continue" : "Message Fabric"}
          rows={1}
          value={text}
          onChange={(event) => onTextChange(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="composer-controls">
          <button
            className="icon-button attachment-button"
            type="button"
            aria-label="Attachments require the native file bridge"
            title="Attachments arrive with the native file bridge"
            disabled
          >
            <IconPaperclip size={19} />
          </button>
          <div className="composer-context" aria-label="Session context">
            {model && <span>{model}</span>}
            {branch && <span>{branch}</span>}
          </div>
          {running ? (
            <button className="send-button stop" type="button" aria-label="Stop agent" onClick={() => void onInterrupt()}>
              <IconPlayerStopFilled size={14} />
            </button>
          ) : (
            <button
              className="send-button"
              type="button"
              aria-label="Send message"
              disabled={!text.trim() || disabled || sending}
              onClick={() => void submit()}
            >
              <IconArrowUp size={19} stroke={2.2} />
            </button>
          )}
        </div>
      </div>
      <p className="composer-hint">Enter to send · Shift Enter for a new line · / for commands</p>
    </footer>
  );
}
