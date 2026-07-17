import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { PREVIEW_PANE_ID } from '@/store/layout'
import type { LiveViewState } from '@/store/live-view'
import { $paneOpen, $paneStates } from '@/store/panes'

import { useActiveLiveViewPane } from './use-active-live-view-pane'

function liveView(sessionId: string): LiveViewState {
  return {
    actions: [],
    kind: 'browser',
    paused: false,
    presentation: 'docked',
    sessionId,
    status: 'running',
    updatedAt: 1
  }
}

beforeEach(() => {
  $paneStates.set({})
})

describe('useActiveLiveViewPane', () => {
  it('does not open the global pane for an inactive session, then opens it when that session becomes active', () => {
    const liveViews = { inactive: liveView('inactive') }

    const { rerender } = renderHook(({ activeSessionId }) => useActiveLiveViewPane(activeSessionId, liveViews), {
      initialProps: { activeSessionId: 'active' as null | string }
    })

    expect($paneOpen(PREVIEW_PANE_ID).get()).toBe(false)

    rerender({ activeSessionId: 'inactive' })

    expect($paneOpen(PREVIEW_PANE_ID).get()).toBe(true)
  })

  it('does not reopen a hidden active-session view', () => {
    const hidden = { ...liveView('active'), presentation: 'hidden' as const }

    renderHook(() => useActiveLiveViewPane('active', { active: hidden }))

    expect($paneOpen(PREVIEW_PANE_ID).get()).toBe(false)
  })
})
