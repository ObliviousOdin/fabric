import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $liveViews,
  $liveViewStreamFrames,
  completeLiveViewTool,
  dockLiveView,
  finishLiveViewTurn,
  hideLiveView,
  liveViewFrameFromResult,
  popOutLiveView,
  resetLiveViewsForTest,
  setLiveViewPaused,
  setLiveViewStreamFrame,
  startLiveViewTool
} from './live-view'

const open = vi.fn(async () => ({ ok: true }))
const close = vi.fn(async () => ({ ok: true }))
const pushState = vi.fn()

beforeEach(() => {
  resetLiveViewsForTest()
  open.mockClear()
  close.mockClear()
  pushState.mockClear()
  window.hermesDesktop = {
    ...(window.hermesDesktop ?? ({} as Window['hermesDesktop'])),
    liveView: {
      close,
      control: vi.fn(),
      onControl: vi.fn(() => () => {}),
      onState: vi.fn(() => () => {}),
      open,
      pushState
    }
  }
})

describe('live view tool lifecycle', () => {
  it('ignores tools that cannot produce a visual activity stream', () => {
    startLiveViewTool('s1', { name: 'terminal', tool_id: 't1' })

    expect($liveViews.get()).toEqual({})
  })

  it('opens a browser activity in the dock and records its target', () => {
    startLiveViewTool('s1', {
      args: { url: 'https://example.com' },
      name: 'browser_navigate',
      tool_id: 't1'
    })

    expect($liveViews.get().s1).toMatchObject({
      kind: 'browser',
      presentation: 'docked',
      status: 'running',
      target: 'https://example.com'
    })
    expect($liveViews.get().s1.actions).toHaveLength(1)
  })

  it('bounds tool-derived target and action detail retained in session state', () => {
    const oversizedUrl = `https://example.com/${'x'.repeat(2_000)}`

    startLiveViewTool('s1', {
      args: { url: oversizedUrl },
      name: 'browser_navigate',
      tool_id: 't1'
    })

    expect($liveViews.get().s1.target).toHaveLength(1_024)
    expect($liveViews.get().s1.actions[0].detail).toHaveLength(1_024)
  })

  it('uses a nested multimodal screenshot as the latest ephemeral frame', () => {
    startLiveViewTool('s1', { name: 'computer_use', tool_id: 't1' })
    completeLiveViewTool('s1', {
      name: 'computer_use',
      result: {
        _multimodal: true,
        content: [
          { type: 'text', text: 'capture' },
          { type: 'image_url', image_url: { url: 'data:image/png;base64,abc' } }
        ]
      },
      tool_id: 't1'
    })

    expect($liveViews.get().s1).toMatchObject({
      frameUrl: 'data:image/png;base64,abc',
      kind: 'desktop',
      status: 'complete'
    })
    expect($liveViews.get().s1.actions[0].status).toBe('complete')
  })

  it('switches surface kind when a cross-kind completion arrives without its start event', () => {
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 'browser-1' })
    completeLiveViewTool('s1', { name: 'browser_navigate', result: { success: true }, tool_id: 'browser-1' })

    completeLiveViewTool('s1', {
      name: 'computer_use',
      result: { content: [{ image_url: { url: 'data:image/png;base64,desktop-frame' } }] },
      tool_id: 'desktop-1'
    })

    expect($liveViews.get().s1).toMatchObject({
      frameUrl: 'data:image/png;base64,desktop-frame',
      kind: 'desktop',
      status: 'complete'
    })
  })

  it('freezes the displayed frame while visual updates are paused', () => {
    startLiveViewTool('s1', { name: 'browser_vision', tool_id: 't1' })
    completeLiveViewTool('s1', {
      name: 'browser_vision',
      result: { content: [{ image_url: { url: 'data:image/png;base64,first' } }] },
      tool_id: 't1'
    })
    setLiveViewPaused('s1', true)
    startLiveViewTool('s1', { name: 'browser_vision', tool_id: 't2' })
    completeLiveViewTool('s1', {
      name: 'browser_vision',
      result: { content: [{ image_url: { url: 'data:image/png;base64,second' } }] },
      tool_id: 't2'
    })

    expect($liveViews.get().s1.frameUrl).toBe('data:image/png;base64,first')
  })

  it('keeps Browser stream frames out of session metadata', () => {
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })
    const metadata = $liveViews.get()

    setLiveViewStreamFrame('s1', 'data:image/jpeg;base64,frame')

    expect($liveViews.get()).toBe(metadata)
    expect($liveViews.get().s1.frameUrl).toBeUndefined()
    expect($liveViewStreamFrames.get().s1).toBe('data:image/jpeg;base64,frame')
  })

  it('clears stored and streaming frames when the viewer is dismissed', () => {
    startLiveViewTool('s1', { name: 'browser_vision', tool_id: 't1' })
    completeLiveViewTool('s1', {
      name: 'browser_vision',
      result: { content: [{ image_url: { url: 'data:image/png;base64,tool-frame' } }] },
      tool_id: 't1'
    })
    setLiveViewStreamFrame('s1', 'data:image/jpeg;base64,stream-frame')

    hideLiveView('s1')

    expect($liveViews.get().s1).toMatchObject({ presentation: 'hidden', streaming: false })
    expect($liveViews.get().s1.frameUrl).toBeUndefined()
    expect($liveViewStreamFrames.get().s1).toBeUndefined()
  })

  it('keeps the aggregate running while overlapping actions are still active', () => {
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })
    startLiveViewTool('s1', { name: 'browser_click', tool_id: 't2' })

    completeLiveViewTool('s1', { name: 'browser_navigate', result: { success: true }, tool_id: 't1' })

    expect($liveViews.get().s1.status).toBe('running')
    expect($liveViews.get().s1.actions.find(action => action.id === 't2')?.status).toBe('running')

    completeLiveViewTool('s1', { name: 'browser_click', result: { success: true }, tool_id: 't2' })

    expect($liveViews.get().s1.status).toBe('complete')
  })

  it('reports an error after a concurrent activity batch settles, then resets for the next batch', () => {
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })
    startLiveViewTool('s1', { name: 'browser_click', tool_id: 't2' })
    completeLiveViewTool('s1', { error: 'navigation failed', name: 'browser_navigate', tool_id: 't1' })
    completeLiveViewTool('s1', { name: 'browser_click', result: { success: true }, tool_id: 't2' })

    expect($liveViews.get().s1.status).toBe('error')

    startLiveViewTool('s1', { name: 'browser_vision', tool_id: 't3' })
    completeLiveViewTool('s1', { name: 'browser_vision', result: { success: true }, tool_id: 't3' })

    expect($liveViews.get().s1.status).toBe('complete')
  })

  it('finalizes orphan running actions when the turn ends', () => {
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })
    startLiveViewTool('s1', { name: 'browser_click', tool_id: 't2' })

    finishLiveViewTurn('s1', true)

    expect($liveViews.get().s1.status).toBe('error')
    expect($liveViews.get().s1.actions).toEqual([
      expect.objectContaining({ completedAt: expect.any(Number), id: 't1', status: 'error' }),
      expect.objectContaining({ completedAt: expect.any(Number), id: 't2', status: 'error' })
    ])
  })

  it('keeps a dismissed in-flight viewer hidden instead of reopening every action', () => {
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })
    hideLiveView('s1')
    startLiveViewTool('s1', { name: 'browser_click', tool_id: 't2' })

    expect($liveViews.get().s1.presentation).toBe('hidden')
  })
})

describe('live view PiP bridge', () => {
  it('opens the PiP with the same state and never creates a second activity', async () => {
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })
    setLiveViewStreamFrame('s1', 'data:image/jpeg;base64,stream-frame')
    await expect(popOutLiveView('s1')).resolves.toBe(true)

    expect(open).toHaveBeenCalledWith({ sessionId: 's1' })
    expect($liveViews.get().s1.presentation).toBe('pip')
    expect($liveViews.get().s1.actions).toHaveLength(1)
    expect(pushState).toHaveBeenCalledWith(
      expect.objectContaining({ frameUrl: 'data:image/jpeg;base64,stream-frame', sessionId: 's1', presentation: 'pip' })
    )
  })

  it('remains docked when the PiP window cannot be opened', async () => {
    open.mockResolvedValueOnce({ ok: false })
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })

    await expect(popOutLiveView('s1')).resolves.toBe(false)

    expect($liveViews.get().s1.presentation).toBe('docked')
    expect(pushState).not.toHaveBeenCalled()
  })

  it('remains docked when opening the PiP window rejects', async () => {
    open.mockRejectedValueOnce(new Error('window failed'))
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })

    await expect(popOutLiveView('s1')).resolves.toBe(false)

    expect($liveViews.get().s1.presentation).toBe('docked')
    expect(pushState).not.toHaveBeenCalled()
  })

  it('does not enter PiP if the window closes before the open handshake resolves', async () => {
    let resolveOpen!: (result: { ok: boolean }) => void

    open.mockImplementationOnce(
      () =>
        new Promise(resolve => {
          resolveOpen = resolve
        })
    )
    startLiveViewTool('s1', { name: 'browser_navigate', tool_id: 't1' })

    const pending = popOutLiveView('s1')
    dockLiveView('s1')
    resolveOpen({ ok: true })

    await expect(pending).resolves.toBe(false)
    expect($liveViews.get().s1.presentation).toBe('docked')
  })
})

describe('live view frame extraction', () => {
  it('does not mistake a normal page URL for an image frame', () => {
    expect(
      liveViewFrameFromResult({
        url: 'https://example.com',
        content: [{ image_url: { url: 'data:image/jpeg;base64,frame' } }]
      })
    ).toBe('data:image/jpeg;base64,frame')
  })

  it('rejects oversized inline frames before they reach state', () => {
    const oversized = `data:image/png;base64,${'a'.repeat(4 * 1024 * 1024)}`

    expect(liveViewFrameFromResult({ image_url: { url: oversized } })).toBeUndefined()
  })

  it('rejects executable and unsupported inline image formats', () => {
    expect(liveViewFrameFromResult({ image_url: { url: 'data:image/svg+xml;base64,PHN2Zz4=' } })).toBeUndefined()
    expect(liveViewFrameFromResult({ image_url: { url: 'data:image/webp;base64,frame' } })).toBeUndefined()
  })

  it('bounds retained sessions and clears evicted stream frames', () => {
    startLiveViewTool('session-0', { name: 'browser_navigate', tool_id: 't0' })
    setLiveViewStreamFrame('session-0', 'data:image/jpeg;base64,frame')

    for (let index = 1; index <= 24; index += 1) {
      startLiveViewTool(`session-${index}`, { name: 'browser_navigate', tool_id: `t${index}` })
    }

    expect(Object.keys($liveViews.get())).toHaveLength(24)
    expect($liveViews.get()['session-0']).toBeUndefined()
    expect($liveViewStreamFrames.get()['session-0']).toBeUndefined()
    expect(close).toHaveBeenCalledWith('session-0')
  })
})
