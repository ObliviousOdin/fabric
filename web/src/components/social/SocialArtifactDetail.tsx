import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@nous-research/ui/ui/components/dialog";

import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import type { SocialArtifact } from "@fabric/shared";

import type { SessionInfo } from "@/lib/api";

import { CopyButton } from "./CopyButton";
import { WorkspaceImage } from "./WorkspaceImage";

/**
 * Full-screen-on-mobile view of one conversation's post-ready content: the
 * image to post, the exact caption to paste, and a prominent Copy button. This
 * is the "click a conversation -> copy and paste on your phone" surface.
 */
export function SocialArtifactDetail({
  artifacts,
  onClose,
  open,
  session,
}: {
  artifacts: SocialArtifact[];
  onClose: () => void;
  open: boolean;
  session: SessionInfo;
}) {
  const { t } = useI18n();
  const s = t.social ?? en.social!;
  const title = session.title || session.preview || "Untitled conversation";

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[92vh] w-full max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="truncate">{title}</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {artifacts.map((artifact) => (
            <article
              key={artifact.id}
              className="space-y-3 border-t border-border pt-4 first:border-t-0 first:pt-0"
            >
              {artifact.imagePath && (
                <WorkspaceImage
                  alt={s.imageAlt}
                  className="max-h-80 w-full border border-border"
                  cwd={session.cwd}
                  path={artifact.imagePath}
                />
              )}

              <div className="space-y-1.5">
                <span className="text-xs font-medium uppercase tracking-wide text-text-tertiary">
                  {s.captionLabel}
                </span>
                <p className="whitespace-pre-wrap break-words border border-border bg-background-surface/60 p-3 text-sm leading-6 text-text-primary">
                  {artifact.caption}
                </p>
              </div>

              <CopyButton
                className="w-full sm:w-auto"
                copiedLabel={s.copied}
                label={s.copyCaption}
                text={artifact.caption}
              />
            </article>
          ))}

          <div className="border-t border-border pt-4">
            <Link
              className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-text-secondary underline decoration-border underline-offset-4 transition-colors hover:text-primary hover:decoration-primary"
              to={`/workspace/chat?resume=${encodeURIComponent(session.id)}`}
            >
              {s.openConversation}
              <ExternalLink aria-hidden className="size-3.5" />
            </Link>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
