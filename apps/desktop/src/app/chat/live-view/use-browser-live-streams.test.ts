import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $liveViews,
  $liveViewStreamFrames,
  completeLiveViewTool,
  hideLiveView,
  resetLiveViewsForTest,
  setLiveViewPaused,
  startLiveViewTool
} from '@/store/live-view'

import { useBrowserLiveStreams } from './use-browser-live-streams'

type RequestGateway = Parameters<typeof useBrowserLiveStreams>[0]['requestVisualGateway']

function setDocumentVisibility(visibilityState: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: visibilityState })
  document.dispatchEvent(new Event('visibilitychange'))
}

function gatewayPull(frame = 'frame') {
  const mock = vi.fn(async (method: string) => {
    if (method === 'visual.status') {
      return { available: true, min_interval_ms: 500, transport: 'gateway_pull' }
    }

    if (method === 'visual.frame') {
      return { available: true, data: frame, mime_type: 'image/jpeg' }
    }

    throw new Error(`unexpected method: ${method}`)
  })

  return { mock, request: mock as unknown as RequestGateway }
}

function startBrowserAction(sessionId = 'session-1', toolId = 'browser-1'): void {
  startLiveViewTool(sessionId, {
    args: { url: 'https://example.com' },
    name: 'browser_navigate',
    tool_id: toolId
  })
}

function completeBrowserAction(sessionId = 'session-1', toolId = 'browser-1'): void {
  completeLiveViewTool(sessionId, {
    name: 'browser_navigate',
    result: { title: 'Example', url: 'https://example.com' },
    tool_id: toolId
  })
}

function prepareCompletedBrowser(sessionId = 'session-1'): void {
  startBrowserAction(sessionId)
  completeBrowserAction(sessionId)
}

async function flushAsync(): Promise<void> {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

const originalWebSocket = globalThis.WebSocket
let webSocketConstructor: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(0)
  webSocketConstructor = vi.fn()
  ;(globalThis as { WebSocket: unknown }).WebSocket = webSocketConstructor
  setDocumentVisibility('visible')
  resetLiveViewsForTest()
})

afterEach(() => {
  cleanup()
  vi.clearAllTimers()
  vi.useRealTimers()
  ;(globalThis as { WebSocket: unknown }).WebSocket = originalWebSocket
  Reflect.deleteProperty(document, 'visibilityState')
  resetLiveViewsForTest()
})

describe('useBrowserLiveStreams', () => {
  it('waits for a completed Browser action before requesting live-view status', async () => {
    startBrowserAction()
    const gateway = gatewayPull()

    renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-1', enabled: true, requestVisualGateway: gateway.request })
    )
    await flushAsync()

    expect(gateway.mock).not.toHaveBeenCalled()

    act(() => completeBrowserAction())
    await flushAsync()

    expect(gateway.mock.mock.calls.map(([method]) => method)).toEqual(['visual.status', 'visual.frame'])
  })

  it('waits until every overlapping Browser action completes regardless of action order', async () => {
    startBrowserAction('session-1', 'browser-1')
    startBrowserAction('session-1', 'browser-2')
    completeBrowserAction('session-1', 'browser-2')
    const gateway = gatewayPull()

    renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-1', enabled: true, requestVisualGateway: gateway.request })
    )
    await flushAsync()

    expect(gateway.mock).not.toHaveBeenCalled()

    act(() => completeBrowserAction('session-1', 'browser-1'))
    await flushAsync()

    expect(gateway.mock.mock.calls.map(([method]) => method)).toEqual(['visual.status', 'visual.frame'])
  })

  it('uses authenticated gateway pulls and never constructs a WebSocket', async () => {
    prepareCompletedBrowser()
    const gateway = gatewayPull('jpeg-one')

    renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-1', enabled: true, requestVisualGateway: gateway.request })
    )
    await flushAsync()

    expect(gateway.mock).toHaveBeenNthCalledWith(
      1,
      'visual.status',
      { session_id: 'session-1' },
      5_000,
      expect.any(AbortSignal)
    )
    expect(gateway.mock).toHaveBeenNthCalledWith(
      2,
      'visual.frame',
      { session_id: 'session-1' },
      4_000,
      expect.any(AbortSignal)
    )
    expect(webSocketConstructor).not.toHaveBeenCalled()
    expect($liveViewStreamFrames.get()['session-1']).toBe('data:image/jpeg;base64,jpeg-one')
    expect($liveViews.get()['session-1'].streaming).toBe(true)
  })

  it('starts sequential upstream frame pulls no faster than every 500 ms', async () => {
    prepareCompletedBrowser()
    const starts: number[] = []

    const requestMock = vi.fn(async (method: string) => {
      if (method === 'visual.status') {
        return { available: true, min_interval_ms: 100, transport: 'gateway_pull' }
      }

      starts.push(Date.now())

      return { available: true, data: `frame-${starts.length}`, mime_type: 'image/jpeg' }
    })

    renderHook(() =>
      useBrowserLiveStreams({
        activeSessionId: 'session-1',
        enabled: true,
        requestVisualGateway: requestMock as unknown as RequestGateway
      })
    )
    await flushAsync()

    expect(starts).toEqual([0])
    await advance(499)
    expect(starts).toEqual([0])
    await advance(1)
    expect(starts).toEqual([0, 500])
    await advance(500)
    expect(starts).toEqual([0, 500, 1_000])
    expect(webSocketConstructor).not.toHaveBeenCalled()
  })

  it('never overlaps frame pulls when a prior capture is still pending', async () => {
    prepareCompletedBrowser()
    let resolveFrame!: (value: { available: boolean; data: string; mime_type: string }) => void

    const pendingFrame = new Promise<{ available: boolean; data: string; mime_type: string }>(resolve => {
      resolveFrame = resolve
    })

    const requestMock = vi.fn((method: string) => {
      if (method === 'visual.status') {
        return Promise.resolve({ available: true, min_interval_ms: 500, transport: 'gateway_pull' })
      }

      return pendingFrame
    })

    renderHook(() =>
      useBrowserLiveStreams({
        activeSessionId: 'session-1',
        enabled: true,
        requestVisualGateway: requestMock as unknown as RequestGateway
      })
    )
    await flushAsync()
    await advance(5_000)

    expect(requestMock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(1)

    resolveFrame({ available: true, data: 'late-frame', mime_type: 'image/jpeg' })
    await flushAsync()
    // The first request started 5 seconds ago, so a second can start as soon
    // as it resolves without violating the start-to-start cadence.
    await advance(0)
    expect(requestMock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(2)
    await advance(499)
    expect(requestMock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(2)
    await advance(1)
    expect(requestMock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(3)
  })

  it('honors a server throttle delay longer than the local interval', async () => {
    prepareCompletedBrowser()
    const starts: number[] = []

    const requestMock = vi.fn(async (method: string) => {
      if (method === 'visual.status') {
        return { available: true, min_interval_ms: 500, transport: 'gateway_pull' }
      }

      starts.push(Date.now())

      return starts.length === 1
        ? { available: false, reason: 'frame_throttled', retry_after_ms: 750 }
        : { available: true, data: 'frame', mime_type: 'image/jpeg' }
    })

    renderHook(() =>
      useBrowserLiveStreams({
        activeSessionId: 'session-1',
        enabled: true,
        requestVisualGateway: requestMock as unknown as RequestGateway
      })
    )
    await flushAsync()
    await advance(749)
    expect(starts).toEqual([0])
    await advance(1)
    expect(starts).toEqual([0, 750])
  })

  it('aborts an in-flight pull and stops polling while paused', async () => {
    prepareCompletedBrowser()
    let frameSignal: AbortSignal | undefined

    const requestMock = vi.fn((method: string, _params: unknown, _timeout: number, signal: AbortSignal) => {
      if (method === 'visual.status') {
        return Promise.resolve({ available: true, min_interval_ms: 500, transport: 'gateway_pull' })
      }

      frameSignal = signal

      return new Promise(() => undefined)
    })

    renderHook(() =>
      useBrowserLiveStreams({
        activeSessionId: 'session-1',
        enabled: true,
        requestVisualGateway: requestMock as unknown as RequestGateway
      })
    )
    await flushAsync()
    expect(frameSignal?.aborted).toBe(false)

    act(() => setLiveViewPaused('session-1', true))
    await flushAsync()
    await advance(10_000)

    expect(frameSignal?.aborted).toBe(true)
    expect(requestMock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(1)
    expect($liveViews.get()['session-1'].streaming).toBe(false)
  })

  it('stops pulling as soon as a new model Browser action starts', async () => {
    prepareCompletedBrowser()
    const gateway = gatewayPull()

    renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-1', enabled: true, requestVisualGateway: gateway.request })
    )
    await flushAsync()
    expect(gateway.mock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(1)

    act(() => startBrowserAction('session-1', 'browser-2'))
    await flushAsync()
    await advance(5_000)

    expect(gateway.mock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(1)
    expect($liveViews.get()['session-1'].streaming).toBe(false)
  })

  it('stops a docked viewer while hidden and resumes it when visible', async () => {
    prepareCompletedBrowser()
    const gateway = gatewayPull()

    renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-1', enabled: true, requestVisualGateway: gateway.request })
    )
    await flushAsync()

    act(() => setDocumentVisibility('hidden'))
    await flushAsync()
    await advance(5_000)
    expect(gateway.mock.mock.calls.filter(([method]) => method === 'visual.status')).toHaveLength(1)

    act(() => setDocumentVisibility('visible'))
    await flushAsync()
    expect(gateway.mock.mock.calls.filter(([method]) => method === 'visual.status')).toHaveLength(2)
  })

  it('keeps a visible PiP pulling while the main document is hidden', async () => {
    prepareCompletedBrowser()
    $liveViews.set({
      ...$liveViews.get(),
      'session-1': { ...$liveViews.get()['session-1'], presentation: 'pip' }
    })
    const gateway = gatewayPull()

    renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-1', enabled: true, requestVisualGateway: gateway.request })
    )
    await flushAsync()
    act(() => setDocumentVisibility('hidden'))
    await flushAsync()
    await advance(500)

    expect(gateway.mock.mock.calls.filter(([method]) => method === 'visual.status')).toHaveLength(1)
    expect(gateway.mock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(2)
  })

  it('does not pull for an invisible PiP or a hidden viewer', async () => {
    prepareCompletedBrowser()
    $liveViews.set({
      ...$liveViews.get(),
      'session-1': { ...$liveViews.get()['session-1'], pipVisible: false, presentation: 'pip' }
    })
    const gateway = gatewayPull()

    renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-1', enabled: true, requestVisualGateway: gateway.request })
    )
    await flushAsync()
    expect(gateway.mock).not.toHaveBeenCalled()

    act(() => hideLiveView('session-1'))
    await flushAsync()
    await advance(5_000)
    expect(gateway.mock).not.toHaveBeenCalled()
  })

  it('retries failed status requests with bounded exponential delays', async () => {
    prepareCompletedBrowser()
    const requestMock = vi.fn(async () => Promise.reject(new Error('not ready')))

    renderHook(() =>
      useBrowserLiveStreams({
        activeSessionId: 'session-1',
        enabled: true,
        requestVisualGateway: requestMock as unknown as RequestGateway
      })
    )
    await flushAsync()
    expect(requestMock).toHaveBeenCalledOnce()

    await advance(500)
    expect(requestMock).toHaveBeenCalledTimes(2)
    await advance(1_000)
    expect(requestMock).toHaveBeenCalledTimes(3)
    await advance(2_000 + 4_000 + 8_000)
    expect(requestMock).toHaveBeenCalledTimes(6)
    await advance(60_000)
    expect(requestMock).toHaveBeenCalledTimes(6)
  })

  it('stops retrying persistent frame failures even when status stays available', async () => {
    prepareCompletedBrowser()

    const requestMock = vi.fn(async (method: string) => {
      if (method === 'visual.status') {
        return { available: true, min_interval_ms: 500, transport: 'gateway_pull' }
      }

      throw new Error('capture failed')
    })

    renderHook(() =>
      useBrowserLiveStreams({
        activeSessionId: 'session-1',
        enabled: true,
        requestVisualGateway: requestMock as unknown as RequestGateway
      })
    )
    await flushAsync()

    expect(requestMock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(1)

    await advance(500 + 1_000 + 2_000 + 4_000 + 8_000)

    expect(requestMock.mock.calls.filter(([method]) => method === 'visual.status')).toHaveLength(6)
    expect(requestMock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(6)

    await advance(60_000)
    expect(requestMock).toHaveBeenCalledTimes(12)
    expect($liveViews.get()['session-1'].streaming).toBe(false)
  })

  it('ignores a stale status response after pause and resume', async () => {
    prepareCompletedBrowser()
    let resolveStatusA!: (status: object) => void
    let resolveStatusB!: (status: object) => void

    const statusA = new Promise<object>(resolve => {
      resolveStatusA = resolve
    })

    const statusB = new Promise<object>(resolve => {
      resolveStatusB = resolve
    })

    const requests = [statusA, statusB]

    const requestMock = vi.fn((method: string) =>
      method === 'visual.status'
        ? (requests.shift() as Promise<object>)
        : Promise.resolve({ available: true, data: 'frame', mime_type: 'image/jpeg' })
    )

    renderHook(() =>
      useBrowserLiveStreams({
        activeSessionId: 'session-1',
        enabled: true,
        requestVisualGateway: requestMock as unknown as RequestGateway
      })
    )
    await flushAsync()
    act(() => setLiveViewPaused('session-1', true))
    await flushAsync()
    act(() => setLiveViewPaused('session-1', false))
    await flushAsync()

    resolveStatusA({ available: true, min_interval_ms: 500, transport: 'gateway_pull' })
    await flushAsync()
    expect(requestMock).toHaveBeenCalledTimes(2)

    resolveStatusB({ available: true, min_interval_ms: 500, transport: 'gateway_pull' })
    await flushAsync()
    expect(requestMock).toHaveBeenCalledTimes(3)
    expect(requestMock.mock.calls.at(-1)?.[0]).toBe('visual.frame')
  })

  it('aborts pending work on unmount and remains disabled behind the gateway gate', async () => {
    prepareCompletedBrowser()
    const gateway = gatewayPull()

    const { unmount } = renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-1', enabled: true, requestVisualGateway: gateway.request })
    )

    await flushAsync()
    unmount()
    await advance(5_000)
    expect(gateway.mock.mock.calls.filter(([method]) => method === 'visual.frame')).toHaveLength(1)

    resetLiveViewsForTest()
    prepareCompletedBrowser('session-2')
    const disabled = gatewayPull()
    renderHook(() =>
      useBrowserLiveStreams({ activeSessionId: 'session-2', enabled: false, requestVisualGateway: disabled.request })
    )
    await flushAsync()
    expect(disabled.mock).not.toHaveBeenCalled()
  })
})
