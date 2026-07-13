import { useCallback, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";

/**
 * Ghost icon button: copy `value` to the clipboard with a transient check
 * glyph. Shared by the webhook subscription rows (endpoint URL) and the
 * create modal's secret-shown-once panel (W2/W3).
 */
export function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {});
  }, [value]);
  return (
    <Button
      ghost
      size="icon"
      title="Copy"
      aria-label="Copy"
      onClick={handleCopy}
      className="text-muted-foreground hover:text-foreground"
    >
      {copied ? <Check /> : <Copy />}
    </Button>
  );
}
