import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $compactingSessions, $compactionActive, setSessionCompacting } from './compaction'
import { $activeSessionId } from './session'

describe('compaction store', () => {
  beforeEach(() => {
    $compactingSessions.set({})
    $activeSessionId.set(null)
  })

  afterEach(() => {
    $compactingSessions.set({})
    $activeSessionId.set(null)
  })

  it('tracks compaction per session independently', () => {
    setSessionCompacting('session-a', true)
    setSessionCompacting('session-b', true)

    // Value is the operation id ('' when the backend sent none); presence is
    // what marks a session as compacting.
    expect(Object.keys($compactingSessions.get()).sort()).toEqual(['session-a', 'session-b'])
  })

  it('exposes only the active session via the focus-scoped view', () => {
    setSessionCompacting('session-a', true)

    expect($compactionActive.get()).toBe(false)

    $activeSessionId.set('session-a')
    expect($compactionActive.get()).toBe(true)

    $activeSessionId.set('session-b')
    expect($compactionActive.get()).toBe(false)
  })

  it('clears a session without disturbing the others', () => {
    setSessionCompacting('session-a', true)
    setSessionCompacting('session-b', true)

    setSessionCompacting('session-a', false)

    expect(Object.keys($compactingSessions.get())).toEqual(['session-b'])
  })

  it('is a no-op when clearing an unknown session', () => {
    setSessionCompacting('session-a', true)
    const before = $compactingSessions.get()

    setSessionCompacting('session-missing', false)

    expect($compactingSessions.get()).toBe(before)
  })

  // ── #62: op-scoped lifecycle ──────────────────────────────────────────────

  it('shows on start and clears on the matching completion', () => {
    setSessionCompacting('s1', true, '1')
    expect('s1' in $compactingSessions.get()).toBe(true)

    setSessionCompacting('s1', false, '1')
    expect('s1' in $compactingSessions.get()).toBe(false)
  })

  it('ignores a stale completion for an older operation', () => {
    setSessionCompacting('s1', true, '1')
    setSessionCompacting('s1', false, '1')
    setSessionCompacting('s1', true, '2')
    expect($compactingSessions.get().s1).toBe('2')

    // A late/duplicate completion for op 1 must NOT clear op 2's indicator.
    setSessionCompacting('s1', false, '1')
    expect($compactingSessions.get().s1).toBe('2')

    setSessionCompacting('s1', false, '2')
    expect('s1' in $compactingSessions.get()).toBe(false)
  })

  it('lets a newer start win so its own completion clears', () => {
    setSessionCompacting('s1', true, '1')
    setSessionCompacting('s1', true, '2')
    expect($compactingSessions.get().s1).toBe('2')
  })

  it('force-clears on a turn boundary regardless of op (undefined op)', () => {
    setSessionCompacting('s1', true, '7')
    setSessionCompacting('s1', false)
    expect('s1' in $compactingSessions.get()).toBe(false)
  })

  it('never gets stuck when the backend sent no op', () => {
    setSessionCompacting('s1', true, undefined)
    expect($compactingSessions.get().s1).toBe('')

    // An unknown ('') op is cleared by any completion so it can't strand.
    setSessionCompacting('s1', false, '1')
    expect('s1' in $compactingSessions.get()).toBe(false)
  })
})
