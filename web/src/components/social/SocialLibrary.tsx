import { AlertTriangle, ImageIcon, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";

import { Badge } from "@/components/fabric/Badge";
import { EmptyState, Skeleton } from "@/components/ui";
import type {
  SocialArtifactScan,
  SocialSessionArtifacts,
} from "@/hooks/useSocialArtifactScan";
import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";

import { CopyButton } from "./CopyButton";
import { SocialArtifactDetail } from "./SocialArtifactDetail";
import { WorkspaceImage } from "./WorkspaceImage";

function preview(caption: string, max = 160): string {
  const flat = caption.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

/**
 * The Social Studio library. Renders the artifacts found by the page-owned
 * scan (`useSocialArtifactScan`) — the page uses the same scan to keep this
 * stage locked until a post actually exists, so the library never opens onto
 * scaffolding with nothing in it.
 */
export function SocialLibrary({ scan }: { scan: SocialArtifactScan }) {
  const { t } = useI18n();
  const s = t.social ?? en.social!;

  const { error, loading, rescan, results, scanMore, scanned } = scan;
  const [selected, setSelected] = useState<SocialSessionArtifacts | null>(null);

  if (loading && results.length === 0) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} variant="block" className="h-56" />
        ))}
      </div>
    );
  }

  if (error && results.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-3 border border-destructive/30 bg-destructive/[0.06] px-3 py-2">
        <AlertTriangle className="size-4 shrink-0 text-destructive" />
        <span className="min-w-0 flex-1 text-sm text-destructive">
          {s.loadFailed}
        </span>
        <Button outlined size="sm" onClick={rescan}>
          {s.retry}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-text-tertiary">
          {s.scannedNote.replace("{count}", String(scanned))}
        </p>
        <div className="flex items-center gap-2">
          <Button
            ghost
            size="sm"
            onClick={rescan}
            prefix={loading ? <Spinner /> : <RefreshCw />}
            disabled={loading}
          >
            {s.scan}
          </Button>
          <Button outlined size="sm" onClick={scanMore} disabled={loading}>
            {s.scanMore}
          </Button>
        </div>
      </div>

      {results.length === 0 ? (
        <EmptyState
          icon={Sparkles}
          title={s.emptyTitle}
          description={s.emptyBody}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {results.map((row) => {
            const latest = row.artifacts[row.artifacts.length - 1];
            const title =
              row.session.title || row.session.preview || "Untitled conversation";
            return (
              <div
                key={row.session.id}
                className="flex flex-col border border-border bg-background-surface/40 transition-colors hover:border-primary/50"
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  onClick={() => setSelected(row)}
                >
                  {latest.imagePath ? (
                    <WorkspaceImage
                      alt={s.imageAlt}
                      className="h-40 w-full border-b border-border"
                      cwd={row.session.cwd}
                      path={latest.imagePath}
                    />
                  ) : (
                    <div className="flex h-40 w-full items-center justify-center border-b border-border bg-background-base text-text-tertiary">
                      <ImageIcon aria-hidden className="size-6 opacity-40" />
                    </div>
                  )}
                  <div className="space-y-1.5 p-3">
                    <span className="block truncate text-sm font-medium text-text-primary">
                      {title}
                    </span>
                    <span className="block text-xs leading-5 text-text-secondary line-clamp-3">
                      {preview(latest.caption)}
                    </span>
                  </div>
                </button>
                <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
                  <Badge tone="secondary" className="text-xs">
                    {row.artifacts.length > 1
                      ? s.drafts.replace("{count}", String(row.artifacts.length))
                      : latest.imagePath
                        ? s.withImage
                        : s.textOnly}
                  </Badge>
                  <CopyButton
                    ghost
                    copiedLabel={s.copied}
                    label={s.copyCaption}
                    size="sm"
                    text={latest.caption}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {selected && (
        <SocialArtifactDetail
          artifacts={selected.artifacts}
          open={selected !== null}
          onClose={() => setSelected(null)}
          session={selected.session}
        />
      )}
    </div>
  );
}
