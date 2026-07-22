import { Check, Copy } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@nous-research/ui/ui/components/button";

import { copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";

/**
 * Copy-to-clipboard button with a transient "Copied" confirmation. This is the
 * core Social Studio interaction: on a phone the user taps Copy, switches to the
 * LinkedIn app, and pastes. Uses the shared `copyTextToClipboard` helper, which
 * already falls back to a hidden-textarea copy when the async Clipboard API is
 * unavailable (older mobile webviews / non-secure contexts).
 */
export function CopyButton({
  className,
  ghost = false,
  label = "Copy",
  copiedLabel = "Copied",
  outlined = false,
  size = "sm",
  text,
  onCopied,
}: {
  className?: string;
  ghost?: boolean;
  label?: string;
  copiedLabel?: string;
  outlined?: boolean;
  size?: "sm" | "default" | "xs";
  text: string;
  onCopied?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const handleCopy = useCallback(async () => {
    const ok = await copyTextToClipboard(text);
    if (!ok) return;
    setCopied(true);
    onCopied?.();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 2_000);
  }, [onCopied, text]);

  return (
    <Button
      aria-label={copied ? copiedLabel : label}
      className={cn(className)}
      ghost={ghost}
      onClick={() => void handleCopy()}
      outlined={outlined}
      prefix={copied ? <Check /> : <Copy />}
      size={size}
      type="button"
    >
      {copied ? copiedLabel : label}
    </Button>
  );
}
