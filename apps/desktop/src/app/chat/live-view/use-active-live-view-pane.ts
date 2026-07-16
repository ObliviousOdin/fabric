import { useEffect } from 'react'

import { PREVIEW_PANE_ID } from '@/store/layout'
import type { LiveViewState } from '@/store/live-view'
import { setPaneOpen } from '@/store/panes'

export function useActiveLiveViewPane(activeSessionId: null | string, liveViews: Record<string, LiveViewState>): void {
  const presentation = activeSessionId ? liveViews[activeSessionId]?.presentation : undefined

  useEffect(() => {
    if (activeSessionId && presentation === 'docked') {
      setPaneOpen(PREVIEW_PANE_ID, true)
    }
  }, [activeSessionId, presentation])
}
