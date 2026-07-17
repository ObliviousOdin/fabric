import { describe, expect, it } from 'vitest'

import { en } from '@/i18n/en'

import { liveViewStatusLabel } from '.'

describe('liveViewStatusLabel', () => {
  it.each([
    [{ kind: 'browser', paused: true, status: 'running' } as const, 'Paused'],
    [{ kind: 'browser', paused: false, status: 'error' } as const, 'Failed'],
    [{ kind: 'browser', paused: false, status: 'running' } as const, 'Live'],
    [{ kind: 'desktop', paused: false, status: 'running' } as const, 'Working'],
    [{ kind: 'desktop', paused: false, status: 'complete' } as const, 'Ready']
  ])('returns the explicit translated state for %o', (state, expected) => {
    expect(liveViewStatusLabel(state, en.liveView)).toBe(expected)
  })
})
