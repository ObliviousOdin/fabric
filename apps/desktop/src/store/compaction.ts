import { atom, computed } from 'nanostores'

import { $activeSessionId } from './session'

// Per-session flag while auto-compaction runs mid-turn. Without it the
// transcript looks like it reset; per-session so a background chat can't
// clobber the foreground view.
const keyFor = (sessionId: string | null | undefined): string => sessionId ?? ''

// session key → operation id of the active compaction. Presence of a key means
// that session is compacting. The op id makes clears precise: a late or
// duplicate "complete" carrying an OLDER operation's id can't dismiss the
// indicator for a newer compaction that's still running (#62). An empty-string
// op means "unknown" (e.g. an older backend that didn't send one), which any
// clear is still allowed to dismiss so the indicator can never get stuck.
export const $compactingSessions = atom<Record<string, string>>({})

export const $compactionActive = computed(
  [$compactingSessions, $activeSessionId],
  (sessions, activeId) => keyFor(activeId) in sessions
)

/**
 * Set or clear the compacting indicator for a session.
 *
 * @param active  true on compaction start, false on completion/error or a
 *                turn-boundary cleanup.
 * @param op      the compaction operation id (from the gateway). On a clear,
 *                the indicator is only dismissed when this matches the stored
 *                op — EXCEPT when `op` is undefined (a turn-boundary
 *                force-clear from message.start/complete/error), or the stored
 *                op is '' (unknown), both of which always clear.
 */
export function setSessionCompacting(
  sessionId: string | null | undefined,
  active: boolean,
  op?: string
): void {
  const key = keyFor(sessionId)
  const sessions = $compactingSessions.get()

  if (active) {
    const nextOp = op ?? ''

    if (sessions[key] === nextOp) {
      return
    }

    // A newer start always wins — it overwrites any older op so its own
    // completion is the one that clears the indicator.
    $compactingSessions.set({ ...sessions, [key]: nextOp })

    return
  }

  const current = sessions[key]

  if (current === undefined) {
    return
  }

  // Op-scoped completion: ignore a stale "complete" for an operation that is
  // no longer the active one. A force-clear (undefined op) or an unknown
  // stored op ('') always clears.
  if (op !== undefined && current !== '' && current !== op) {
    return
  }

  const next = { ...sessions }
  delete next[key]
  $compactingSessions.set(next)
}
