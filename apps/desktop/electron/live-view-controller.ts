import {
  normalizeLiveViewSessionId,
  sanitizeLiveViewControlPayload,
  sanitizeLiveViewStatePayload
} from './live-view-windows'

const DEFAULT_READY_TIMEOUT_MS = 8_000

interface ScheduledTask {
  cancel: () => void
  unref?: () => void
}

interface LiveViewClock {
  schedule: (callback: () => void, timeoutMs: number) => ScheduledTask
}

interface LiveViewEventEmitterLike {
  on: (name: string, callback: (...args: unknown[]) => void) => unknown
  once: (name: string, callback: (...args: unknown[]) => void) => unknown
  removeListener: (name: string, callback: (...args: unknown[]) => void) => unknown
}

export interface LiveViewWebContentsLike extends LiveViewEventEmitterLike {
  isDestroyed: () => boolean
  send: (channel: string, payload: unknown) => void
}

export interface LiveViewControllerWindowLike extends LiveViewEventEmitterLike {
  isDestroyed: () => boolean
  webContents: LiveViewWebContentsLike
}

export interface LiveViewControllerRegistry<TWindow extends LiveViewControllerWindowLike> {
  close: (sessionId: string) => boolean
  get: (sessionId: string) => TWindow | undefined
  hasWebContents: (webContents: unknown) => boolean
  openOrFocus: (sessionId: string, factory: (sessionId: string) => TWindow | null) => TWindow | null
}

interface LiveViewReadyWaiter<TWindow> {
  promise: Promise<boolean>
  resolve: (ready: boolean) => void
  timer: ScheduledTask
  win: TWindow
}

export interface CreateLiveViewControllerOptions<TWindow extends LiveViewControllerWindowLike> {
  clock?: LiveViewClock
  focusWindow: (win: TWindow | undefined) => void
  isSenderAttached: (sender: TWindow['webContents']) => boolean
  readyTimeoutMs?: number
  registry: LiveViewControllerRegistry<TWindow>
  spawnWindow: (sessionId: string) => TWindow | null
}

function systemClock(): LiveViewClock {
  return {
    schedule(callback, timeoutMs) {
      const timer = setTimeout(callback, timeoutMs)

      return {
        cancel: () => clearTimeout(timer),
        unref: () => timer.unref?.()
      }
    }
  }
}

/**
 * Owns the security- and lifecycle-sensitive IPC state for Agent Live View.
 *
 * Electron objects enter only through the small structural interfaces above,
 * keeping exact-sender checks, readiness, owner teardown, and PiP teardown
 * covered without loading or mocking the Electron main process.
 */
export function createLiveViewController<TWindow extends LiveViewControllerWindowLike>({
  clock = systemClock(),
  focusWindow,
  isSenderAttached,
  readyTimeoutMs = DEFAULT_READY_TIMEOUT_MS,
  registry,
  spawnWindow
}: CreateLiveViewControllerOptions<TWindow>) {
  const latestState = new Map<string, Record<string, unknown>>()
  const ownerCleanup = new Map<string, () => void>()
  const owners = new Map<string, TWindow['webContents']>()
  const readyWaiters = new Map<string, LiveViewReadyWaiter<TWindow>>()
  const readyWindows = new WeakSet<TWindow>()
  const suppressClosed = new WeakSet<TWindow>()

  function settleReady(sessionId: string, win: TWindow, ready: boolean): void {
    const waiter = readyWaiters.get(sessionId)

    if (!waiter || waiter.win !== win) {
      return
    }

    waiter.timer.cancel()
    readyWaiters.delete(sessionId)
    waiter.resolve(ready)
  }

  function clearOwner(sessionId: string): void {
    ownerCleanup.get(sessionId)?.()
    ownerCleanup.delete(sessionId)
    owners.delete(sessionId)
  }

  function notifyClosed(sessionId: string): void {
    const owner = owners.get(sessionId)

    if (owner && !owner.isDestroyed()) {
      owner.send('hermes:live-view:control', { sessionId, type: 'closed' })
    }
  }

  function closeWindow(sessionId: string, suppressOwnerNotification = true): boolean {
    const win = registry.get(sessionId)

    if (win) {
      settleReady(sessionId, win, false)
    }

    if (suppressOwnerNotification && win) {
      suppressClosed.add(win)
    }

    const closed = registry.close(sessionId)

    if (!closed && win) {
      suppressClosed.delete(win)
    }

    clearOwner(sessionId)
    latestState.delete(sessionId)

    return closed
  }

  function bindOwner(sessionId: string, owner: TWindow['webContents']): void {
    if (owners.get(sessionId) === owner) {
      return
    }

    clearOwner(sessionId)

    const onDestroyed = () => {
      if (owners.get(sessionId) === owner) {
        closeWindow(sessionId)
      }
    }

    const onMainFrameNavigation = (...args: unknown[]) => {
      const [event, _url, isInPlace, isMainFrame] = args

      const navigationEvent =
        event && typeof event === 'object' ? (event as { isMainFrame?: unknown; isSameDocument?: unknown }) : null

      const mainFrame =
        typeof navigationEvent?.isMainFrame === 'boolean' ? navigationEvent.isMainFrame : isMainFrame === true

      const sameDocument =
        typeof navigationEvent?.isSameDocument === 'boolean' ? navigationEvent.isSameDocument : isInPlace === true

      if (mainFrame && !sameDocument) {
        onDestroyed()
      }
    }

    owner.once('destroyed', onDestroyed)
    owner.once('render-process-gone', onDestroyed)
    owner.on('did-start-navigation', onMainFrameNavigation)
    owners.set(sessionId, owner)
    ownerCleanup.set(sessionId, () => {
      owner.removeListener('destroyed', onDestroyed)
      owner.removeListener('render-process-gone', onDestroyed)
      owner.removeListener('did-start-navigation', onMainFrameNavigation)
    })
  }

  function waitForReady(sessionId: string, win: TWindow): Promise<boolean> {
    if (readyWindows.has(win)) {
      return Promise.resolve(true)
    }

    const current = readyWaiters.get(sessionId)

    if (current?.win === win) {
      return current.promise
    }

    if (current) {
      settleReady(sessionId, current.win, false)
    }

    let resolveReady: (ready: boolean) => void = () => undefined

    const promise = new Promise<boolean>(resolve => {
      resolveReady = resolve
    })

    const timer = clock.schedule(() => {
      if (registry.get(sessionId) === win) {
        notifyClosed(sessionId)
        closeWindow(sessionId)
      }

      settleReady(sessionId, win, false)
    }, readyTimeoutMs)

    timer.unref?.()
    readyWaiters.set(sessionId, { promise, resolve: resolveReady, timer, win })

    return promise
  }

  function bindWindow(sessionId: string, win: TWindow): void {
    let returningToDock = false

    const returnToDock = () => {
      if (returningToDock || suppressClosed.has(win) || registry.get(sessionId) !== win) {
        return
      }

      returningToDock = true
      settleReady(sessionId, win, false)
      notifyClosed(sessionId)
      closeWindow(sessionId)
    }

    // Never strand a stale always-on-top frame if the small renderer crashes,
    // fails its main navigation, or becomes unobservable.
    win.webContents.once('render-process-gone', returnToDock)
    win.webContents.on('did-fail-load', (...args: unknown[]) => {
      if (args[4] === true) {
        returnToDock()
      }
    })
    win.on('minimize', returnToDock)
    win.on('hide', returnToDock)
    win.on('closed', () => {
      if (registry.get(sessionId) !== win) {
        return
      }

      const suppressed = suppressClosed.has(win)

      suppressClosed.delete(win)
      settleReady(sessionId, win, false)

      if (!suppressed) {
        notifyClosed(sessionId)
      }

      clearOwner(sessionId)
      latestState.delete(sessionId)
    })
  }

  async function open(sender: TWindow['webContents'], rawSessionId: unknown): Promise<{ ok: boolean }> {
    const sessionId = normalizeLiveViewSessionId(rawSessionId)

    if (!sessionId || !isSenderAttached(sender) || registry.hasWebContents(sender)) {
      return { ok: false }
    }

    const owner = owners.get(sessionId)

    if (owner && !owner.isDestroyed() && owner !== sender) {
      focusWindow(registry.get(sessionId))

      return { ok: false }
    }

    const win = registry.openOrFocus(sessionId, () => spawnWindow(sessionId))

    if (!win) {
      return { ok: false }
    }

    bindOwner(sessionId, sender)

    const ready = await waitForReady(sessionId, win)

    return {
      ok: ready && registry.get(sessionId) === win && !win.isDestroyed() && owners.get(sessionId) === sender
    }
  }

  function close(sender: TWindow['webContents'], rawSessionId: unknown): { ok: boolean } {
    const sessionId = normalizeLiveViewSessionId(rawSessionId)

    if (sessionId && owners.get(sessionId) === sender) {
      closeWindow(sessionId)

      return { ok: true }
    }

    return { ok: false }
  }

  function pushState(sender: TWindow['webContents'], payload: unknown): void {
    const sessionId = normalizeLiveViewSessionId(
      payload && typeof payload === 'object' && !Array.isArray(payload)
        ? (payload as Record<string, unknown>).sessionId
        : undefined
    )

    const win = sessionId ? registry.get(sessionId) : undefined

    if (!sessionId || !win || win.isDestroyed() || owners.get(sessionId) !== sender) {
      return
    }

    const state = sanitizeLiveViewStatePayload(payload, sessionId)

    if (!state) {
      return
    }

    latestState.set(sessionId, state)
    win.webContents.send('hermes:live-view:state', state)
  }

  function control(sender: TWindow['webContents'], payload: unknown): void {
    const sessionId = normalizeLiveViewSessionId(
      payload && typeof payload === 'object' && !Array.isArray(payload)
        ? (payload as Record<string, unknown>).sessionId
        : undefined
    )

    const win = sessionId ? registry.get(sessionId) : undefined

    if (!sessionId || !win || win.isDestroyed() || win.webContents !== sender) {
      return
    }

    const cleanControl = sanitizeLiveViewControlPayload(payload, sessionId)

    if (!cleanControl) {
      return
    }

    if (cleanControl.type === 'ready') {
      readyWindows.add(win)
      settleReady(sessionId, win, true)

      const latest = latestState.get(sessionId)

      if (latest) {
        sender.send('hermes:live-view:state', latest)
      }

      return
    }

    const owner = owners.get(sessionId)

    if (owner && !owner.isDestroyed()) {
      owner.send('hermes:live-view:control', cleanControl)
    }

    if (cleanControl.type === 'dock' || cleanControl.type === 'hide') {
      closeWindow(sessionId)
    }
  }

  return {
    bindWindow,
    close,
    control,
    open,
    pushState
  }
}
