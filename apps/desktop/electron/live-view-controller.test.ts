import assert from 'node:assert/strict'
import test from 'node:test'

import { createLiveViewController } from './live-view-controller'
import { createLiveViewWindowRegistry } from './live-view-windows'

type Listener = (...args: unknown[]) => void

class FakeEmitter {
  private readonly listeners = new Map<string, Set<Listener>>()

  emit(name: string, ...args: unknown[]): void {
    for (const listener of [...(this.listeners.get(name) ?? [])]) {
      listener(...args)
    }
  }

  listenerCount(name: string): number {
    return this.listeners.get(name)?.size ?? 0
  }

  on(name: string, listener: Listener): this {
    const listeners = this.listeners.get(name) ?? new Set<Listener>()

    listeners.add(listener)
    this.listeners.set(name, listeners)

    return this
  }

  once(name: string, listener: Listener): this {
    return this.on(name, listener)
  }

  removeListener(name: string, listener: Listener): this {
    this.listeners.get(name)?.delete(listener)

    return this
  }
}

interface SentMessage {
  channel: string
  payload: unknown
}

class FakeWebContents extends FakeEmitter {
  destroyed = false
  readonly messages: SentMessage[] = []

  isDestroyed(): boolean {
    return this.destroyed
  }

  send(channel: string, payload: unknown): void {
    this.messages.push({ channel, payload })
  }
}

class FakeWindow extends FakeEmitter {
  destroyed = false
  focused = 0
  shown = 0
  readonly webContents = new FakeWebContents()

  destroy(): void {
    if (this.destroyed) {
      return
    }

    this.destroyed = true
    this.emit('closed')
  }

  focus(): void {
    this.focused += 1
  }

  isDestroyed(): boolean {
    return this.destroyed
  }

  show(): void {
    this.shown += 1
  }
}

class FakeClock {
  readonly tasks: Array<{ callback: () => void; cancelled: boolean; timeoutMs: number; unrefed: boolean }> = []

  runActive(): void {
    for (const task of [...this.tasks]) {
      if (!task.cancelled) {
        task.callback()
      }
    }
  }

  schedule(callback: () => void, timeoutMs: number) {
    const task = { callback, cancelled: false, timeoutMs, unrefed: false }

    this.tasks.push(task)

    return {
      cancel: () => {
        task.cancelled = true
      },
      unref: () => {
        task.unrefed = true
      }
    }
  }
}

function validState(sessionId: string) {
  return {
    actions: [],
    frameUrl: 'data:image/jpeg;base64,frame',
    kind: 'browser',
    paused: false,
    presentation: 'pip',
    sessionId,
    status: 'running',
    updatedAt: 1
  }
}

function createHarness({ readyTimeoutMs = 8_000 }: { readyTimeoutMs?: number } = {}) {
  const attachedSenders = new Set<FakeWebContents>()
  const clock = new FakeClock()
  const registry = createLiveViewWindowRegistry<FakeWindow>()
  const windows = new Map<string, FakeWindow>()
  let controller!: ReturnType<typeof createLiveViewController<FakeWindow>>

  controller = createLiveViewController<FakeWindow>({
    clock,
    focusWindow: win => win?.focus(),
    isSenderAttached: sender => attachedSenders.has(sender),
    readyTimeoutMs,
    registry,
    spawnWindow: sessionId => {
      const win = new FakeWindow()

      windows.set(sessionId, win)
      controller.bindWindow(sessionId, win)

      return win
    }
  })

  async function openReady(owner: FakeWebContents, sessionId: string): Promise<FakeWindow> {
    attachedSenders.add(owner)
    const pending = controller.open(owner, sessionId)
    const win = registry.get(sessionId)

    assert.ok(win)
    controller.control(win.webContents, { sessionId, type: 'ready' })
    assert.deepEqual(await pending, { ok: true })

    return win
  }

  return { attachedSenders, clock, controller, openReady, registry, windows }
}

test('controller binds one exact owner, forwards bounded state, and focuses on conflicting ownership', async () => {
  const harness = createHarness()
  const owner = new FakeWebContents()
  const otherOwner = new FakeWebContents()

  harness.attachedSenders.add(owner)
  harness.attachedSenders.add(otherOwner)

  const pending = harness.controller.open(owner, 'session-1')
  const win = harness.registry.get('session-1')

  assert.ok(win)

  harness.controller.pushState(otherOwner, validState('session-1'))
  assert.equal(win.webContents.messages.length, 0)

  harness.controller.pushState(owner, validState('session-1'))
  assert.equal(win.webContents.messages.length, 1)

  harness.controller.control(win.webContents, { sessionId: 'session-1', type: 'ready' })
  assert.deepEqual(await pending, { ok: true })
  assert.equal(win.webContents.messages.length, 2, 'ready replays the latest state after an early owner push')

  assert.deepEqual(await harness.controller.open(otherOwner, 'session-1'), { ok: false })
  assert.equal(win.focused, 1)
  assert.equal(harness.controller.close(otherOwner, 'session-1').ok, false)
  assert.equal(win.destroyed, false)
})

test('controller rejects detached senders and nested PiP renderers', async () => {
  const harness = createHarness()
  const detached = new FakeWebContents()

  assert.deepEqual(await harness.controller.open(detached, 'session-1'), { ok: false })
  assert.equal(harness.registry.get('session-1'), undefined)

  const owner = new FakeWebContents()
  const win = await harness.openReady(owner, 'session-1')

  harness.attachedSenders.add(win.webContents)
  assert.deepEqual(await harness.controller.open(win.webContents, 'nested-session'), { ok: false })
  assert.equal(harness.registry.get('nested-session'), undefined)
})

test('controller times out an unready PiP, returns it to the dock, and clears owner listeners', async () => {
  const harness = createHarness({ readyTimeoutMs: 25 })
  const owner = new FakeWebContents()

  harness.attachedSenders.add(owner)
  const pending = harness.controller.open(owner, 'session-timeout')
  const win = harness.registry.get('session-timeout')

  assert.ok(win)
  assert.equal(harness.clock.tasks[0]?.timeoutMs, 25)
  assert.equal(harness.clock.tasks[0]?.unrefed, true)

  harness.clock.runActive()

  assert.deepEqual(await pending, { ok: false })
  assert.equal(win.destroyed, true)
  assert.deepEqual(owner.messages, [
    {
      channel: 'hermes:live-view:control',
      payload: { sessionId: 'session-timeout', type: 'closed' }
    }
  ])
  assert.equal(owner.listenerCount('destroyed'), 0)
  assert.equal(owner.listenerCount('render-process-gone'), 0)
  assert.equal(owner.listenerCount('did-start-navigation'), 0)
})

test('owner crash and full main-frame navigation tear down only the owned PiP', async () => {
  const crashHarness = createHarness()
  const crashedOwner = new FakeWebContents()
  const crashWindow = await crashHarness.openReady(crashedOwner, 'session-crash')

  crashedOwner.emit('render-process-gone')
  assert.equal(crashWindow.destroyed, true)
  assert.equal(crashedOwner.messages.length, 0)

  const navigationHarness = createHarness()
  const navigatingOwner = new FakeWebContents()
  const navigationWindow = await navigationHarness.openReady(navigatingOwner, 'session-navigation')

  navigatingOwner.emit('did-start-navigation', {}, 'https://example.com/frame', false, false)
  navigatingOwner.emit('did-start-navigation', { isMainFrame: true, isSameDocument: true }, '#anchor', false, false)
  assert.equal(navigationWindow.destroyed, false)

  navigatingOwner.emit(
    'did-start-navigation',
    { isMainFrame: true, isSameDocument: false },
    'https://example.com/next',
    true,
    false
  )
  assert.equal(navigationWindow.destroyed, true)
  assert.equal(navigatingOwner.messages.length, 0)
})

for (const lifecycleEvent of ['hide', 'minimize', 'render-process-gone'] as const) {
  test(`PiP ${lifecycleEvent} returns the session to the dock exactly once`, async () => {
    const harness = createHarness()
    const owner = new FakeWebContents()
    const win = await harness.openReady(owner, `session-${lifecycleEvent}`)

    if (lifecycleEvent === 'render-process-gone') {
      win.webContents.emit(lifecycleEvent)
      win.webContents.emit(lifecycleEvent)
    } else {
      win.emit(lifecycleEvent)
      win.emit(lifecycleEvent)
    }

    assert.equal(win.destroyed, true)
    assert.deepEqual(owner.messages, [
      {
        channel: 'hermes:live-view:control',
        payload: { sessionId: `session-${lifecycleEvent}`, type: 'closed' }
      }
    ])
  })
}

test('a failed PiP main-frame load returns the session to the dock but a subframe failure does not', async () => {
  const harness = createHarness()
  const owner = new FakeWebContents()
  const win = await harness.openReady(owner, 'session-load')

  win.webContents.emit('did-fail-load', {}, -1, 'subframe failed', 'https://example.com/frame', false)
  assert.equal(win.destroyed, false)

  win.webContents.emit('did-fail-load', {}, -2, 'main frame failed', 'https://example.com', true)
  assert.equal(win.destroyed, true)
  assert.equal(owner.messages.length, 1)
})

for (const type of ['dock', 'hide'] as const) {
  test(`${type} control requires the exact PiP sender, forwards once, and tears down`, async () => {
    const harness = createHarness()
    const owner = new FakeWebContents()
    const spoofedPip = new FakeWebContents()
    const sessionId = `session-${type}`
    const win = await harness.openReady(owner, sessionId)

    harness.controller.control(spoofedPip, { sessionId, type })
    assert.equal(win.destroyed, false)
    assert.equal(owner.messages.length, 0)

    harness.controller.control(win.webContents, { extra: 'drop', sessionId, type })

    assert.equal(win.destroyed, true)
    assert.deepEqual(owner.messages, [
      {
        channel: 'hermes:live-view:control',
        payload: { sessionId, type }
      }
    ])
    assert.equal(owner.listenerCount('destroyed'), 0)
    assert.equal(owner.listenerCount('render-process-gone'), 0)
    assert.equal(owner.listenerCount('did-start-navigation'), 0)
  })
}
