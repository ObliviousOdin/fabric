import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { api } from "@/lib/api";

export interface McpInstallLogCardProps {
  /** Spawned action name returned by `POST /api/mcp/catalog/install`. */
  action: string;
  /** Fired once when the action stops running (reload both lists here —
   *  today's immediate reload shows nothing changed for slow clones, X8). */
  onFinished(): void;
  onDismiss(): void;
}

/**
 * Live log tail for a background catalog install (spec X8) — the CAP10
 * action-log idiom lifted from the skills hub: poll
 * `GET /api/actions/{name}/status` on a bounded 1.2 s cadence while
 * `running`, mono `pre` tail, running/done Badge, dismiss when finished.
 * No new polling loops beyond this bounded one (N20).
 *
 * Render with `key={action}` — a new action remounts the card so the
 * tail state resets without effect-time setState.
 */
export function McpInstallLogCard({
  action,
  onFinished,
  onDismiss,
}: McpInstallLogCardProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const st = await api.getActionStatus(action, 200);
        if (cancelled) return;
        setLines(st.lines);
        setRunning(st.running);
        if (st.running) {
          timer = setTimeout(poll, 1200);
        } else {
          onFinished();
        }
      } catch {
        if (!cancelled) {
          setRunning(false);
          onFinished();
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // onFinished is intentionally not a dependency: the poll loop is keyed
    // by the action it tails, and re-running it on a parent re-render
    // would restart the tail from scratch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action]);

  return (
    <Card>
      <CardContent className="py-3">
        <div className="flex items-center gap-2 mb-2">
          <Download className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="font-mono text-xs">{action}</span>
          {running ? (
            <Badge tone="warning">running</Badge>
          ) : (
            <Badge tone="success">done</Badge>
          )}
          {!running && (
            <Button
              ghost
              size="xs"
              className="ml-auto text-muted-foreground"
              onClick={onDismiss}
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words bg-background/50 border border-border p-2 text-xs font-mono text-muted-foreground">
          {lines.length ? lines.join("\n") : "Starting…"}
        </pre>
      </CardContent>
    </Card>
  );
}
