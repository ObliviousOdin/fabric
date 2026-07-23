import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { useEffect, useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientSessionState } from '@/app/types'
import { createClientSessionState } from '@/lib/chat-runtime'
import { $liveViews, resetLiveViewsForTest } from '@/store/live-view'
import type { RpcEvent } from '@/types/fabric'

import { useMessageStream } from './index'

const SID = 'session-1'
let handleEvent: ((event: RpcEvent) => void) | null = null

function Harness() {
  const activeSessionIdRef = useRef<string | null>(SID)
  const sessionStateByRuntimeIdRef = useRef(new Map<string, ClientSessionState>())
  const queryClientRef = useRef(new QueryClient())

  const stream = useMessageStream({
    activeSessionIdRef,
    hydrateFromStoredSession: vi.fn(async () => undefined),
    queryClient: queryClientRef.current,
    refreshFabricConfig: vi.fn(async () => undefined),
    refreshSessions: vi.fn(async () => undefined),
    sessionStateByRuntimeIdRef,
    updateSessionState: (sessionId, updater) => {
      const current = sessionStateByRuntimeIdRef.current.get(sessionId) ?? createClientSessionState()
      const next = updater(current)

      sessionStateByRuntimeIdRef.current.set(sessionId, next)

      return next
    }
  })

  useEffect(() => {
    handleEvent = stream.handleGatewayEvent
  }, [stream.handleGatewayEvent])

  return null
}

async function mountStream(): Promise<void> {
  render(<Harness />)
  await waitFor(() => expect(handleEvent).not.toBeNull())
}

describe('useMessageStream Live View fallback events', () => {
  beforeEach(() => {
    handleEvent = null
    resetLiveViewsForTest()
  })

  afterEach(() => {
    cleanup()
    resetLiveViewsForTest()
    vi.restoreAllMocks()
  })

  it('updates Live View when transcript tool progress is disabled', async () => {
    await mountStream()

    act(() => {
      handleEvent!({
        payload: { context: 'Browsing https://example.com', name: 'browser_navigate', tool_id: 'browser-1' },
        session_id: SID,
        type: 'visual.start'
      })
    })

    expect($liveViews.get()[SID]).toMatchObject({ kind: 'browser', presentation: 'docked', status: 'running' })

    act(() => {
      handleEvent!({
        payload: {
          name: 'browser_navigate',
          result: {
            content: [{ image_url: { url: 'data:image/png;base64,frame' } }],
            title: 'Example'
          },
          tool_id: 'browser-1'
        },
        session_id: SID,
        type: 'visual.complete'
      })
    })

    expect($liveViews.get()[SID]).toMatchObject({
      frameUrl: 'data:image/png;base64,frame',
      status: 'complete',
      target: 'Example'
    })
  })

  it('ignores raw transcript tool events so typed input cannot reach Live View', async () => {
    await mountStream()
    const secret = 'voice-mode-raw-tool-secret'

    act(() => {
      handleEvent!({
        payload: { args: { ref: 'e12', text: secret }, name: 'browser_type', tool_id: 'browser-secret' },
        session_id: SID,
        type: 'tool.start'
      })
      handleEvent!({
        payload: {
          name: 'browser_type',
          result: { raw_secret: secret, success: true },
          tool_id: 'browser-secret'
        },
        session_id: SID,
        type: 'tool.complete'
      })
    })

    expect($liveViews.get()).toEqual({})

    act(() => {
      handleEvent!({
        payload: { args: { ref: 'e12' }, name: 'browser_type', tool_id: 'browser-secret' },
        session_id: SID,
        type: 'visual.start'
      })
    })

    expect($liveViews.get()[SID]).toMatchObject({ kind: 'browser', status: 'running' })
    expect(JSON.stringify($liveViews.get())).not.toContain(secret)
  })
})
