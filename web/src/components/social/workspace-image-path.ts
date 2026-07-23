import { isRemoteImage } from "@fabric/shared";

function isAbsolutePath(path: string) {
  return path.startsWith("/") || path.startsWith("~") || /^[A-Za-z]:[\\/]/.test(path);
}

/** Resolve agent-written relative artifact paths in the producing session's cwd. */
export function resolveWorkspaceImagePath(path: string, cwd?: string | null) {
  const candidate = path.trim();
  if (!cwd || isRemoteImage(candidate) || isAbsolutePath(candidate)) return candidate;
  return `${cwd.replace(/[\\/]+$/, "")}/${candidate.replace(/^\.\//, "")}`;
}
