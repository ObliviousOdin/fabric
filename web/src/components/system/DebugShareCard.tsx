import { useCallback, useState } from "react";
import { Check, Clock, Copy, Link2, Share2 } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Checkbox } from "@nous-research/ui/ui/components/checkbox";
import { Label } from "@nous-research/ui/ui/components/label";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { api } from "@/lib/api";
import type { DebugShareResponse } from "@/lib/api";
import type { ShowToast } from "./format";

/**
 * Debug-share card (Y8, frozen): redact default **true**, uploading state,
 * result block (uploaded/redacted badges, auto-delete hours, per-link copy
 * + copy-all, failures line). Unlike the fire-and-forget ops, `debug
 * share` produces shareable paste URLs that are the whole point — so they
 * surface as real, copyable mono links rather than a log tail.
 */
export function DebugShareCard({ showToast }: { showToast: ShowToast }) {
  const [shareRedact, setShareRedact] = useState(true);
  const [sharing, setSharing] = useState(false);
  const [shareResult, setShareResult] = useState<DebugShareResponse | null>(
    null,
  );
  const [copiedLabel, setCopiedLabel] = useState<string | null>(null);

  const copyToClipboard = useCallback(
    async (text: string, label: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopiedLabel(label);
        setTimeout(
          () => setCopiedLabel((cur) => (cur === label ? null : cur)),
          1500,
        );
      } catch {
        showToast("Couldn't copy to clipboard", "error");
      }
    },
    [showToast],
  );

  const runDebugShare = useCallback(async () => {
    setSharing(true);
    setShareResult(null);
    try {
      const res = await api.runDebugShare({ redact: shareRedact });
      setShareResult(res);
      const n = Object.keys(res.urls).length;
      showToast(
        `Uploaded ${n} paste${n === 1 ? "" : "s"}${
          res.redacted ? " (redacted)" : ""
        }`,
        "success",
      );
    } catch (e) {
      showToast(`Debug share failed: ${e}`, "error");
    } finally {
      setSharing(false);
    }
  }, [shareRedact, showToast]);

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-2">
            <Share2 className="h-4 w-4 mt-0.5 text-muted-foreground" />
            <div className="flex flex-col">
              <span className="text-sm font-medium">Share debug report</span>
              <span className="text-xs text-muted-foreground max-w-prose">
                Uploads system info + logs to a public paste service and
                returns links to send the Fabric team. Pastes auto-delete
                after 6 hours.
              </span>
            </div>
          </div>
          <Button
            size="sm"
            disabled={sharing}
            prefix={
              sharing ? (
                <Spinner className="h-3.5 w-3.5" />
              ) : (
                <Share2 className="h-3.5 w-3.5" />
              )
            }
            onClick={() => void runDebugShare()}
          >
            {sharing ? "Uploading…" : "Generate share link"}
          </Button>
        </div>

        <div className="flex items-center gap-2.5">
          <Checkbox
            checked={shareRedact}
            disabled={sharing}
            id="share-redact"
            onCheckedChange={(checked) => setShareRedact(checked === true)}
          />

          <Label
            className="cursor-pointer select-none text-xs font-normal normal-case tracking-normal text-muted-foreground"
            htmlFor="share-redact"
          >
            Redact credential-shaped tokens before upload (recommended)
          </Label>
        </div>

        {shareResult && (
          <div className="flex flex-col gap-2 border-t border-border pt-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Badge tone="success">uploaded</Badge>
                {shareResult.redacted ? (
                  <Badge tone="outline">redacted</Badge>
                ) : (
                  <Badge tone="warning">not redacted</Badge>
                )}
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  auto-deletes in{" "}
                  {Math.round(shareResult.auto_delete_seconds / 3600)}h
                </span>
              </div>
              {Object.keys(shareResult.urls).length > 1 && (
                <Button
                  size="sm"
                  ghost
                  prefix={
                    copiedLabel === "__all__" ? (
                      <Check className="h-3.5 w-3.5" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )
                  }
                  onClick={() =>
                    void copyToClipboard(
                      Object.entries(shareResult.urls)
                        .map(([label, url]) => `${label}: ${url}`)
                        .join("\n"),
                      "__all__",
                    )
                  }
                >
                  Copy all
                </Button>
              )}
            </div>

            {Object.entries(shareResult.urls).map(([label, url]) => (
              <div
                key={label}
                className="flex items-center gap-2 bg-background/50 border border-border px-3 py-2"
              >
                <Link2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="font-mono text-xs shrink-0 w-24 truncate text-muted-foreground">
                  {label}
                </span>
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-xs truncate flex-1 text-primary hover:underline"
                >
                  {url}
                </a>
                <Button
                  ghost
                  size="icon"
                  aria-label={`Copy ${label} link`}
                  onClick={() => void copyToClipboard(url, label)}
                >
                  {copiedLabel === label ? <Check /> : <Copy />}
                </Button>
              </div>
            ))}

            {shareResult.failures.length > 0 && (
              <span className="text-xs text-destructive">
                Some logs failed to upload: {shareResult.failures.join("; ")}
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
