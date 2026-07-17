'use strict'

import path from 'node:path'

/**
 * Ordered Python candidates for a source checkout.
 *
 * Prefer checkout-local environments, then the managed Fabric environment.
 * The managed fallback lets git worktrees share the canonical installation's
 * dependencies instead of falling through to an incompatible system Python.
 */
export function pythonCandidatesForRoot(
  root: string,
  managedVenvRoot: string,
  platform = process.platform
): string[] {
  const pathApi = platform === 'win32' ? path.win32 : path.posix
  const executable = platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']

  const candidates = [
    pathApi.join(root, '.venv', ...executable),
    pathApi.join(root, 'venv', ...executable),
    pathApi.join(managedVenvRoot, ...executable)
  ]

  return [...new Set(candidates.map(candidate => pathApi.resolve(candidate)))]
}
