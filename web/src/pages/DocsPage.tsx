import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { BookX, ExternalLink } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";

export const FABRIC_DOCS_URL = "https://obliviousodin.github.io/fabric/";

/** Reachability probe budget. GitHub Pages responds in well under this;
 *  past it we assume we're offline / blocked and show the fallback. */
const PROBE_TIMEOUT_MS = 8000;

const DS_BUTTON_OUTLINED_LINK_CN = cn(
  "group relative inline-grid grid-cols-[auto_1fr_auto] items-center",
  "px-[.9em_.75em] py-[1.25em] gap-2",
  "leading-0 font-bold tracking-[0.2em] uppercase",
  "text-foreground bg-transparent",
  "border border-border rounded-sm",
  "hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
);

type DocsState = "loading" | "ready" | "failed";

export default function DocsPage() {
  const { t } = useI18n();
  const { setEnd } = usePageHeader();
  const [state, setState] = useState<DocsState>("loading");
  // Bumping remounts the iframe and re-runs the probe (Retry).
  const [attempt, setAttempt] = useState(0);

  useLayoutEffect(() => {
    setEnd(
      <a
        href={FABRIC_DOCS_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={DS_BUTTON_OUTLINED_LINK_CN}
      >
        <ExternalLink className="size-3.5" />
        {t.app.openDocumentation}
      </a>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, t]);

  // Cross-origin iframes fire `load` even for some error documents and fire
  // nothing at all when the network is down — Fabric is local-first, so an
  // offline dashboard is a normal condition, not an edge case. A no-cors
  // HEAD probe distinguishes "site reachable" (opaque success) from
  // "unreachable" (network rejection / timeout) and drives the fallback.
  useEffect(() => {
    // `cancelled` distinguishes the cleanup's own abort (unmount/retry —
    // must not touch state) from a genuine timeout/network failure.
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
    fetch(FABRIC_DOCS_URL, {
      method: "HEAD",
      mode: "no-cors",
      cache: "no-store",
      signal: controller.signal,
    })
      .then(() => {
        if (!cancelled) {
          setState((prev) => (prev === "loading" ? "ready" : prev));
        }
      })
      .catch(() => {
        if (!cancelled) setState("failed");
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      cancelled = true;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setState("loading");
    setAttempt((n) => n + 1);
  }, []);

  return (
    <div
      className={cn(
        "flex min-h-0 w-full min-w-0 flex-1 flex-col",
        "pt-1 sm:pt-2",
      )}
    >
      <PluginSlot name="docs:top" />
      {state === "failed" ? (
        <EmptyState
          icon={BookX}
          title={t.app.docsUnreachableTitle ?? "Documentation unreachable"}
          description={
            t.app.docsUnreachableDescription ??
            "The docs site could not be reached. Fabric keeps working offline — reconnect to browse the documentation, or open it in a new tab to retry there."
          }
          action={
            <div className="flex items-center gap-2">
              <Button outlined size="sm" className="uppercase" onClick={retry}>
                {t.common.retry}
              </Button>
              <a
                href={FABRIC_DOCS_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs underline"
              >
                {t.app.openDocumentation}
              </a>
            </div>
          }
          className="flex-1"
        />
      ) : (
        <div className="relative min-h-0 w-full min-w-0 flex-1">
          {state === "loading" && (
            <div
              aria-hidden
              className="absolute inset-0 z-10 flex flex-col gap-3 rounded-sm border border-current/20 bg-background-base p-6"
            >
              <Skeleton className="h-8 w-1/3" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-64 w-full" />
            </div>
          )}
          <iframe
            key={attempt}
            title={t.app.nav.documentation}
            src={FABRIC_DOCS_URL}
            onLoad={() =>
              setState((prev) => (prev === "loading" ? "ready" : prev))
            }
            className={cn(
              "h-full min-h-0 w-full min-w-0",
              "rounded-sm border border-current/20",
              // Docusaurus paints over a transparent <html> / <body> and
              // relies on the browser's canvas color (light by default) to
              // fill the viewport. Inheriting the dashboard's dark color
              // scheme makes that canvas dark, so the docs body text — which
              // is tuned for a light canvas — becomes near-invisible. Force a
              // light color scheme + white background on the iframe element so
              // the docs render cleanly regardless of the active dashboard
              // theme or the user's prefers-color-scheme.
              "[color-scheme:light] bg-white",
            )}
            sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>
      )}
      <PluginSlot name="docs:bottom" />
    </div>
  );
}
