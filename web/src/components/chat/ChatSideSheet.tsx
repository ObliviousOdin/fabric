import { X } from "lucide-react";
import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
} from "react";
import { createPortal } from "react-dom";

import { Button } from "@nous-research/ui/ui/components/button";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";
import { cn } from "@/lib/utils";

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export interface ChatSideSheetProps {
  children: ReactNode;
  id: string;
  onClose: () => void;
  side: "left" | "right";
  title: string;
}

/**
 * Accessible compact-chat sheet. It is mounted only while open, so content
 * with effects cannot keep fetching behind an off-screen transform.
 */
export function ChatSideSheet({
  children,
  id,
  onClose,
  side,
  title,
}: ChatSideSheetProps) {
  const titleId = useId();
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  useBodyScrollLock();

  useEffect(() => {
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const first =
        sheetRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (first ?? sheetRef.current)?.focus();
    });

    return () => {
      cancelled = true;
      restoreFocusRef.current?.focus();
    };
  }, []);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Portaled descendants still bubble through their React parent tree. A
    // nested dialog owns its own keyboard lifecycle; the sheet behind it must
    // not close or move focus in response to those keys.
    if (
      event.target instanceof Node &&
      !sheetRef.current?.contains(event.target)
    ) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = Array.from(
      sheetRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? [],
    );
    if (focusable.length === 0) {
      event.preventDefault();
      sheetRef.current?.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const current = document.activeElement;
    if (
      event.shiftKey &&
      (current === first || !sheetRef.current?.contains(current))
    ) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && current === last) {
      event.preventDefault();
      first.focus();
    }
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-[200]">
      <button
        aria-label={`Close ${title}`}
        className="absolute inset-0 bg-black/55 backdrop-blur-[2px]"
        onClick={onClose}
        type="button"
      />
      <div
        ref={sheetRef}
        aria-labelledby={titleId}
        aria-modal="true"
        className={cn(
          "absolute inset-y-0 flex w-[min(92vw,22rem)] min-w-0 flex-col",
          "border-current/15 bg-background-base shadow-2xl",
          side === "left" ? "left-0 border-r" : "right-0 border-l",
        )}
        data-side={side}
        id={id}
        onKeyDown={handleKeyDown}
        role="dialog"
        tabIndex={-1}
      >
        <div className="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-current/10 px-4">
          <h2 id={titleId} className="text-base font-semibold text-foreground">
            {title}
          </h2>
          <Button
            ghost
            size="icon"
            aria-label={`Close ${title}`}
            className="min-h-11 min-w-11 text-text-secondary hover:text-foreground"
            onClick={onClose}
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden p-3">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
