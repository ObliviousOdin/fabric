import { sessionTitle } from '@/lib/chat-runtime'
import type { SessionInfo } from '@/types/fabric'

export type PetOverlaySessionStatus = 'active' | 'attention' | 'idle' | 'working'

export interface PetOverlaySession {
  id: string
  lastActive: number
  model?: null | string
  profile?: string
  status: PetOverlaySessionStatus
  title: string
}

interface PetOverlaySessionsInput {
  activeId: null | string
  attentionIds: readonly string[]
  groups: ReadonlyArray<readonly SessionInfo[]>
  limit?: number
  workingIds: readonly string[]
}

const STATUS_RANK: Record<PetOverlaySessionStatus, number> = {
  attention: 0,
  working: 1,
  active: 2,
  idle: 3
}

function matches(session: SessionInfo, ids: ReadonlySet<string>): boolean {
  return ids.has(session.id) || Boolean(session._lineage_root_id && ids.has(session._lineage_root_id))
}

/**
 * Build the small, privacy-bounded session snapshot mirrored to the gateway-less
 * pet window. Actionable rows lead; the remaining slots are filled by recency.
 */
export function buildPetOverlaySessions({
  activeId,
  attentionIds,
  groups,
  limit = 6,
  workingIds
}: PetOverlaySessionsInput): PetOverlaySession[] {
  const attention = new Set(attentionIds)
  const working = new Set(workingIds)
  const active = activeId ? new Set([activeId]) : new Set<string>()
  const sessions = new Map<string, SessionInfo>()

  for (const group of groups) {
    for (const session of group) {
      if (session.archived) {
        continue
      }

      const previous = sessions.get(session.id)

      if (!previous || session.last_active > previous.last_active) {
        sessions.set(session.id, session)
      }
    }
  }

  return [...sessions.values()]
    .map(session => {
      const status: PetOverlaySessionStatus = matches(session, attention)
        ? 'attention'
        : matches(session, working)
          ? 'working'
          : matches(session, active)
            ? 'active'
            : 'idle'

      return {
        id: session.id,
        lastActive: session.last_active || session.started_at,
        model: session.model,
        profile: session.profile,
        status,
        title: sessionTitle(session)
      }
    })
    .sort((left, right) => STATUS_RANK[left.status] - STATUS_RANK[right.status] || right.lastActive - left.lastActive)
    .slice(0, Math.max(0, limit))
}
