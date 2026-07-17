import { describe, expect, it } from 'vitest'

import type { SessionInfo } from '@/types/hermes'

import { buildPetOverlaySessions } from './pet-overlay-sessions'

function session(id: string, lastActive: number, extra: Partial<SessionInfo> = {}): SessionInfo {
  return {
    ended_at: null,
    id,
    input_tokens: 0,
    is_active: false,
    last_active: lastActive,
    message_count: 1,
    model: null,
    output_tokens: 0,
    preview: null,
    source: 'desktop',
    started_at: lastActive,
    title: id,
    tool_call_count: 0,
    ...extra
  }
}

describe('buildPetOverlaySessions', () => {
  it('puts needs-input and running sessions ahead of active and recent sessions', () => {
    const rows = buildPetOverlaySessions({
      activeId: 'active',
      attentionIds: ['attention'],
      groups: [[session('recent', 50), session('active', 10), session('running', 20), session('attention', 5)]],
      workingIds: ['running', 'attention']
    })

    expect(rows.map(row => [row.id, row.status])).toEqual([
      ['attention', 'attention'],
      ['running', 'working'],
      ['active', 'active'],
      ['recent', 'idle']
    ])
  })

  it('matches live state through a compression lineage root', () => {
    const [row] = buildPetOverlaySessions({
      activeId: 'root',
      attentionIds: [],
      groups: [[session('tip', 1, { _lineage_root_id: 'root' })]],
      workingIds: []
    })

    expect(row.status).toBe('active')
  })

  it('deduplicates groups, omits archived rows, and bounds the IPC payload', () => {
    const rows = buildPetOverlaySessions({
      activeId: null,
      attentionIds: [],
      groups: [
        [session('same', 1), session('archived', 100, { archived: true })],
        [session('same', 9, { model: 'new' }), session('second', 8), session('third', 7)]
      ],
      limit: 2,
      workingIds: []
    })

    expect(rows.map(row => row.id)).toEqual(['same', 'second'])
    expect(rows[0].model).toBe('new')
  })
})
