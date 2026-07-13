import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";

export interface MonoIdProps {
  id: string;
  /** Chars shown, default 8. */
  chars?: number;
  /** Click-to-copy the full id (default true). */
  copy?: boolean;
  className?: string;
}

const BASE_CN = "font-mono-ui text-xs tabular-nums text-muted-foreground";

/** How long the "copied" check icon stays visible. */
const COPIED_MS = 1500;

/**
 * Truncated technical id (session ids, cron job ids, run ids, tool_call
 * ids): mono, muted, `title` = full id, click-to-copy with a transient
 * check icon.
 */
export function MonoId({ id, chars = 8, copy = true, className }: MonoIdProps) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const shown = id.slice(0, chars);

  if (!copy) {
    return (
      <span title={id} className={cn(BASE_CN, className)}>
        {shown}
      </span>
    );
  }

  const handleClick = async (e: React.MouseEvent) => {
    // Ids live inside clickable rows — copying must not toggle expansion.
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(id);
    } catch {
      // Clipboard unavailable (insecure context / permissions) — no toast
      // spam for a micro-affordance; the title still exposes the full id.
      return;
    }
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), COPIED_MS);
  };

  return (
    <button
      type="button"
      title={id}
      aria-label={`${t.common.copyId ?? "Copy ID"} ${id}`}
      onClick={(e) => void handleClick(e)}
      className={cn(
        BASE_CN,
        "inline-flex cursor-pointer items-center gap-1 transition-colors hover:text-foreground",
        className,
      )}
    >
      {shown}
      {copied && (
        <Check aria-hidden="true" className="h-3 w-3 shrink-0 text-success" />
      )}
    </button>
  );
}
