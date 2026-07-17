import { pathToFileURL } from 'node:url'

export const LIVE_VIEW_DEFAULT_HEIGHT = 420
export const LIVE_VIEW_DEFAULT_WIDTH = 520
export const LIVE_VIEW_MIN_HEIGHT = 260
export const LIVE_VIEW_MIN_WIDTH = 360
export const LIVE_VIEW_MAX_WINDOWS = 4

const LIVE_VIEW_MAX_ACTIONS = 16
const LIVE_VIEW_MAX_FRAME_URL_CHARS = 4_000_000
const LIVE_VIEW_MAX_SESSION_ID_CHARS = 256
const LIVE_VIEW_MAX_TEXT_CHARS = 1_024

export function normalizeLiveViewSessionId(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }

  const trimmed = value.trim()

  return trimmed && trimmed.length <= LIVE_VIEW_MAX_SESSION_ID_CHARS ? trimmed : null
}

function boundedString(value: unknown, maxChars = LIVE_VIEW_MAX_TEXT_CHARS): string | undefined {
  if (typeof value !== 'string') {
    return undefined
  }

  const trimmed = value.trim()

  return trimmed ? trimmed.slice(0, maxChars) : undefined
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/**
 * Rebuild renderer-provided PiP state from a deliberately small schema.
 *
 * The renderer is sandboxed but still untrusted at this boundary: never retain
 * arbitrary tool output or forward an unbounded data URL to a second process.
 */
export function sanitizeLiveViewStatePayload(
  value: unknown,
  expectedSessionId: string
): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const input = value as Record<string, unknown>
  const sessionId = normalizeLiveViewSessionId(input.sessionId)

  if (!sessionId || sessionId !== expectedSessionId) {
    return null
  }

  const kind = input.kind === 'browser' || input.kind === 'desktop' ? input.kind : null
  const presentation = input.presentation === 'pip' ? 'pip' : null
  const status = ['complete', 'error', 'running'].includes(String(input.status)) ? String(input.status) : null

  if (!kind || !presentation || !status || typeof input.paused !== 'boolean') {
    return null
  }

  const actions = Array.isArray(input.actions)
    ? input.actions.slice(-LIVE_VIEW_MAX_ACTIONS).flatMap(rawAction => {
        if (!rawAction || typeof rawAction !== 'object' || Array.isArray(rawAction)) {
          return []
        }

        const action = rawAction as Record<string, unknown>
        const id = boundedString(action.id, 256)
        const toolName = boundedString(action.toolName, 128)

        const actionStatus = ['complete', 'error', 'running'].includes(String(action.status))
          ? String(action.status)
          : null

        const startedAt = finiteNumber(action.startedAt)

        if (!id || !toolName || !actionStatus || startedAt === undefined) {
          return []
        }

        const clean: Record<string, unknown> = { id, startedAt, status: actionStatus, toolName }
        const completedAt = finiteNumber(action.completedAt)
        const durationS = finiteNumber(action.durationS)
        const detail = boundedString(action.detail)

        if (completedAt !== undefined) {
          clean.completedAt = completedAt
        }

        if (durationS !== undefined) {
          clean.durationS = durationS
        }

        if (detail) {
          clean.detail = detail
        }

        return [clean]
      })
    : []

  const clean: Record<string, unknown> = {
    actions,
    kind,
    paused: input.paused,
    presentation,
    sessionId,
    status,
    updatedAt: finiteNumber(input.updatedAt) ?? Date.now()
  }

  const frameUrl = typeof input.frameUrl === 'string' ? input.frameUrl : ''
  const target = boundedString(input.target)

  if (
    frameUrl.length <= LIVE_VIEW_MAX_FRAME_URL_CHARS &&
    (frameUrl.startsWith('data:image/jpeg;base64,') || frameUrl.startsWith('data:image/png;base64,'))
  ) {
    clean.frameUrl = frameUrl
  }

  if (typeof input.streaming === 'boolean') {
    clean.streaming = input.streaming
  }

  if (target) {
    clean.target = target
  }

  return clean
}

export function sanitizeLiveViewControlPayload(
  value: unknown,
  expectedSessionId: string
): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const input = value as Record<string, unknown>

  if (normalizeLiveViewSessionId(input.sessionId) !== expectedSessionId) {
    return null
  }

  if (input.type === 'pause') {
    return typeof input.paused === 'boolean'
      ? { paused: input.paused, sessionId: expectedSessionId, type: 'pause' }
      : null
  }

  if (input.type === 'visibility') {
    return typeof input.visible === 'boolean'
      ? { sessionId: expectedSessionId, type: 'visibility', visible: input.visible }
      : null
  }

  return ['dock', 'hide', 'ready'].includes(String(input.type))
    ? { sessionId: expectedSessionId, type: String(input.type) }
    : null
}

export function buildLiveViewWindowUrl(
  sessionId: string,
  { devServer, rendererIndexPath }: { devServer?: string; rendererIndexPath: string }
): string {
  const query = `?win=live-view&session=${encodeURIComponent(sessionId)}`

  if (devServer) {
    const base = devServer.endsWith('/') ? devServer.slice(0, -1) : devServer

    return `${base}/${query}#/`
  }

  return `${pathToFileURL(rendererIndexPath).toString()}${query}#/`
}

interface LiveViewWindowLike {
  close?: () => void
  destroy?: () => void
  focus?: () => void
  isDestroyed: () => boolean
  on: (name: 'closed', callback: () => void) => unknown
  show?: () => void
  webContents: unknown
}

export function createLiveViewWindowRegistry<TWindow extends LiveViewWindowLike = LiveViewWindowLike>({
  maxWindows = LIVE_VIEW_MAX_WINDOWS
}: { maxWindows?: number } = {}) {
  const windows = new Map<string, TWindow>()
  const closing = new Set<string>()

  function openOrFocus(sessionId: string, factory: (sessionId: string) => TWindow | null) {
    const key = normalizeLiveViewSessionId(sessionId)

    if (!key) {
      return null
    }

    const existing = windows.get(key)

    if (existing?.isDestroyed()) {
      windows.delete(key)
      closing.delete(key)
    }

    if (existing && !existing.isDestroyed()) {
      if (closing.has(key)) {
        return null
      }

      existing.show?.()
      existing.focus?.()

      return existing
    }

    if (windows.size >= Math.max(1, maxWindows)) {
      return null
    }

    const win = factory(key)

    if (!win) {
      return null
    }

    windows.set(key, win)
    win.on?.('closed', () => {
      if (windows.get(key) === win) {
        windows.delete(key)
        closing.delete(key)
      }
    })

    return win
  }

  function close(sessionId: string): boolean {
    const key = normalizeLiveViewSessionId(sessionId)

    if (!key) {
      return false
    }

    const win = windows.get(key)

    if (!win) {
      return false
    }

    if (!win.isDestroyed()) {
      closing.add(key)

      // Live View is in-memory and has no unload work. `destroy()` avoids a
      // cancellable close leaving an ownerless always-on-top window behind.
      if (typeof win.destroy === 'function') {
        win.destroy()
      } else {
        win.close?.()
      }
    } else if (windows.get(key) === win) {
      windows.delete(key)
      closing.delete(key)
    }

    return true
  }

  function closeAll(): void {
    for (const key of [...windows.keys()]) {
      close(key)
    }
  }

  return {
    close,
    closeAll,
    get: (sessionId: string) => {
      const key = normalizeLiveViewSessionId(sessionId)

      return key ? windows.get(key) : undefined
    },
    hasWebContents: (webContents: unknown) =>
      [...windows.values()].some(win => !win.isDestroyed() && win.webContents === webContents),
    openOrFocus,
    get size() {
      return windows.size
    }
  }
}
