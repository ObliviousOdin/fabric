import { ImageOff } from "lucide-react";
import { useEffect, useState } from "react";

import { isRemoteImage } from "@fabric/shared";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

import { resolveWorkspaceImagePath } from "./workspace-image-path";

type LoadState = "loading" | "ready" | "error";

/**
 * Render an image an agent produced for a post. Remote `http(s)` URLs load
 * directly; workspace-relative paths are fetched through the managed-files
 * endpoint (`api.readFile`), which returns a ready-to-use `data_url`. When the
 * file can't be resolved (e.g. a relative path outside the managed root) the
 * component degrades to a labelled placeholder instead of a broken image — the
 * caption is always the important part and stays copyable regardless.
 */
export function WorkspaceImage({
  alt,
  className,
  cwd,
  path,
}: {
  alt: string;
  className?: string;
  cwd?: string | null;
  path: string;
}) {
  const resolvedPath = resolveWorkspaceImagePath(path, cwd);
  const remote = isRemoteImage(resolvedPath);
  const [src, setSrc] = useState<string | null>(remote ? resolvedPath : null);
  const [state, setState] = useState<LoadState>(remote ? "ready" : "loading");

  useEffect(() => {
    if (isRemoteImage(resolvedPath)) {
      setSrc(resolvedPath);
      setState("ready");
      return;
    }
    let active = true;
    setState("loading");
    setSrc(null);
    api
      .readFile(resolvedPath)
      .then((file) => {
        if (!active) return;
        if (file.data_url && file.mime_type?.startsWith("image/")) {
          setSrc(file.data_url);
          setState("ready");
        } else {
          setState("error");
        }
      })
      .catch(() => {
        if (active) setState("error");
      });
    return () => {
      active = false;
    };
  }, [resolvedPath]);

  if (state === "error") {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center gap-2 border border-dashed border-border bg-background-surface p-4 text-center text-text-tertiary",
          className,
        )}
      >
        <ImageOff aria-hidden className="size-5" />
        <span className="text-xs leading-4">
          Image preview unavailable. Open the conversation to view it.
        </span>
      </div>
    );
  }

  if (state === "loading" || !src) {
    return (
      <div
        aria-busy="true"
        className={cn("animate-pulse bg-background-surface", className)}
      />
    );
  }

  return <img alt={alt} className={cn("object-cover", className)} src={src} />;
}
