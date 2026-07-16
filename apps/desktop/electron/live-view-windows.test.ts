import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildLiveViewWindowUrl,
  createLiveViewWindowRegistry,
  normalizeLiveViewSessionId,
  sanitizeLiveViewControlPayload,
  sanitizeLiveViewStatePayload
} from './live-view-windows'

function fakeWindow() {
  const listeners = new Map<string, () => void>()
  const webContents = {}

  return {
    closed: false,
    focused: 0,
    shown: 0,
    webContents,
    close() {
      this.closed = true
      listeners.get('closed')?.()
    },
    destroy() {
      this.closed = true
      listeners.get('closed')?.()
    },
    focus() {
      this.focused += 1
    },
    isDestroyed() {
      return this.closed
    },
    on(name: string, callback: () => void) {
      listeners.set(name, callback)
    },
    show() {
      this.shown += 1
    }
  }
}

test('buildLiveViewWindowUrl puts the renderer mode before the hash route', () => {
  assert.equal(
    buildLiveViewWindowUrl('session / 1', { devServer: 'http://127.0.0.1:5174/', rendererIndexPath: '/unused' }),
    'http://127.0.0.1:5174/?win=live-view&session=session%20%2F%201#/'
  )
})

test('normalizeLiveViewSessionId trims valid ids and rejects oversized ids without collisions', () => {
  assert.equal(normalizeLiveViewSessionId('  session-1  '), 'session-1')
  assert.equal(normalizeLiveViewSessionId('x'.repeat(256)), 'x'.repeat(256))
  assert.equal(normalizeLiveViewSessionId('x'.repeat(257)), null)
  assert.equal(normalizeLiveViewSessionId('   '), null)
})

test('live view registry focuses an existing session window', () => {
  const registry = createLiveViewWindowRegistry()
  const win = fakeWindow()
  let created = 0

  assert.equal(
    registry.openOrFocus('s1', () => {
      created += 1

      return win
    }),
    win
  )
  assert.equal(
    registry.openOrFocus('s1', () => fakeWindow()),
    win
  )
  assert.equal(created, 1)
  assert.equal(win.focused, 1)
  assert.equal(win.shown, 1)
})

test('live view registry closes and removes a session window', () => {
  const registry = createLiveViewWindowRegistry()
  const win = fakeWindow()

  registry.openOrFocus('s1', () => win)
  assert.equal(registry.close('s1'), true)
  assert.equal(win.closed, true)
  assert.equal(registry.size, 0)
  assert.equal(registry.close('s1'), false)
})

test('live view registry retains a closing window until its closed event', () => {
  let onClosed: (() => void) | undefined
  let destroyed = false
  let destroyRequested = false

  const closingWindow = {
    destroy() {
      destroyRequested = true
    },
    isDestroyed() {
      return destroyed
    },
    on(name: string, callback: () => void) {
      if (name === 'closed') {
        onClosed = callback
      }
    },
    webContents: {}
  }

  const registry = createLiveViewWindowRegistry({ maxWindows: 1 })

  registry.openOrFocus('s1', () => closingWindow)
  assert.equal(registry.close('s1'), true)
  assert.equal(destroyRequested, true)
  assert.equal(registry.size, 1)
  assert.equal(
    registry.openOrFocus('s1', () => fakeWindow()),
    null
  )
  assert.equal(
    registry.openOrFocus('s2', () => fakeWindow()),
    null
  )

  destroyed = true
  const replacement = fakeWindow()

  assert.equal(
    registry.openOrFocus('s1', () => replacement),
    replacement
  )
  assert.equal(registry.size, 1)
  onClosed?.()

  assert.equal(registry.size, 1)
  assert.equal(registry.get('s1'), replacement)
})

test('live view registry caps PiP windows and identifies their renderers', () => {
  const registry = createLiveViewWindowRegistry({ maxWindows: 1 })
  const first = fakeWindow()

  assert.equal(
    registry.openOrFocus('s1', () => first),
    first
  )
  assert.equal(registry.hasWebContents(first.webContents), true)
  assert.equal(
    registry.openOrFocus('s2', () => fakeWindow()),
    null
  )
  assert.equal(registry.size, 1)
})

test('sanitizeLiveViewStatePayload strips unknown fields and bounds images', () => {
  const base = {
    actions: [
      {
        id: 'a1',
        startedAt: 1,
        status: 'complete',
        toolName: 'browser_navigate',
        secret: 'not forwarded'
      }
    ],
    frameUrl: 'data:image/jpeg;base64,frame',
    kind: 'browser',
    paused: false,
    presentation: 'pip',
    sessionId: 's1',
    status: 'complete',
    updatedAt: 2,
    arbitraryToolResult: { token: 'not forwarded' }
  }

  assert.deepEqual(sanitizeLiveViewStatePayload(base, 's1'), {
    actions: [
      {
        id: 'a1',
        startedAt: 1,
        status: 'complete',
        toolName: 'browser_navigate'
      }
    ],
    frameUrl: 'data:image/jpeg;base64,frame',
    kind: 'browser',
    paused: false,
    presentation: 'pip',
    sessionId: 's1',
    status: 'complete',
    updatedAt: 2
  })

  assert.equal(sanitizeLiveViewStatePayload({ ...base, sessionId: 'other' }, 's1'), null)
  assert.equal(sanitizeLiveViewStatePayload({ ...base, presentation: 'docked' }, 's1'), null)

  const oversized = sanitizeLiveViewStatePayload(
    { ...base, frameUrl: `data:image/png;base64,${'a'.repeat(4_000_001)}` },
    's1'
  )

  assert.equal('frameUrl' in (oversized ?? {}), false)
})

test('sanitizeLiveViewControlPayload rebuilds only valid narrow controls', () => {
  assert.deepEqual(
    sanitizeLiveViewControlPayload({ extra: 'drop', paused: true, sessionId: 's1', type: 'pause' }, 's1'),
    { paused: true, sessionId: 's1', type: 'pause' }
  )
  assert.deepEqual(sanitizeLiveViewControlPayload({ extra: 'drop', sessionId: 's1', type: 'dock' }, 's1'), {
    sessionId: 's1',
    type: 'dock'
  })
  assert.deepEqual(
    sanitizeLiveViewControlPayload({ extra: 'drop', sessionId: 's1', type: 'visibility', visible: false }, 's1'),
    { sessionId: 's1', type: 'visibility', visible: false }
  )
  assert.equal(sanitizeLiveViewControlPayload({ paused: 'yes', sessionId: 's1', type: 'pause' }, 's1'), null)
  assert.equal(sanitizeLiveViewControlPayload({ sessionId: 's1', type: 'visibility', visible: 'no' }, 's1'), null)
  assert.equal(sanitizeLiveViewControlPayload({ sessionId: 'other', type: 'hide' }, 's1'), null)
})
