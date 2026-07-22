import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $liveViews, setLiveViewStreamFrame, setLiveViewStreaming } from '@/store/live-view'

interface BrowserStreamStatus {
  available?: boolean
  min_interval_ms?: number
  reason?: string
  transport?: string
}

interface BrowserFrameResponse {
  available?: boolean
  data?: unknown
  mime_type?: unknown
  reason?: string
  retry_after_ms?: number
}

interface StreamHandle {
  abortController: AbortController | null
  frameIntervalMs: number
  pollTimer: number | null
  retryAttempt: number
  retryTimer: number | null
  stopped: boolean
  // Adaptive idle backoff (#64): a completed Browser Live View keeps polling,
  // but a static page returns byte-identical frames. Track the last frame and
  // how many identical ones we've seen in a row so a motionless view slows its
  // poll cadence instead of decoding/transporting the same JPEG at full rate.
  lastFrame: string | null
  idleStreak: number
}

type GatewayRequest = <T>(
  method: string,
  params?: Record<string, unknown>,
  timeoutMs?: number,
  signal?: AbortSignal
) => Promise<T>

const FRAME_INTERVAL_MS = 500
const FRAME_REQUEST_TIMEOUT_MS = 4_000
const RETRY_BASE_DELAY_MS = 500
const RETRY_MAX_DELAY_MS = 8_000
const RETRY_MAX_ATTEMPTS = 5
// Frames use a dedicated local gateway socket, separate from model/tool event
// streaming. Keep the payload bounded as defense in depth for renderer memory,
// IPC, and PiP fan-out; remote gateways are disabled by the caller.
const MAX_FRAME_BASE64_CHARS = 256_000
const MAX_SERVER_INTERVAL_MS = 60_000
const TRANSIENT_FRAME_REASONS = new Set(['browser_session_busy', 'frame_throttled'])
// Idle backoff (#64): once this many consecutive frames are byte-identical the
// page is treated as static and the poll interval grows (doubling per extra
// identical frame) up to the cap. A single changed frame resets to full
// cadence, so worst-case staleness is bounded by the cap while a motionless
// view stops polling at 500 ms forever.
const IDLE_FRAME_BACKOFF_AFTER = 2
const IDLE_FRAME_MAX_INTERVAL_MS = 4_000

// The effective poll delay for a handle given how long the view has been
// static. Returns the base cadence while active, then backs off geometrically.
function idleIntervalMs(handle: StreamHandle): number {
  if (handle.idleStreak < IDLE_FRAME_BACKOFF_AFTER) {
    return handle.frameIntervalMs
  }

  const steps = handle.idleStreak - IDLE_FRAME_BACKOFF_AFTER + 1

  return Math.min(IDLE_FRAME_MAX_INTERVAL_MS, handle.frameIntervalMs * 2 ** steps)
}

function browserFrame(response: BrowserFrameResponse): string | null {
  if (
    response.available !== true ||
    response.mime_type !== 'image/jpeg' ||
    typeof response.data !== 'string' ||
    response.data.length === 0 ||
    response.data.length > MAX_FRAME_BASE64_CHARS
  ) {
    return null
  }

  return `data:image/jpeg;base64,${response.data}`
}

function closeHandle(sessionId: string, handle: StreamHandle): void {
  handle.stopped = true
  handle.abortController?.abort()
  handle.abortController = null

  if (handle.pollTimer !== null) {
    window.clearTimeout(handle.pollTimer)
    handle.pollTimer = null
  }

  if (handle.retryTimer !== null) {
    window.clearTimeout(handle.retryTimer)
    handle.retryTimer = null
  }

  setLiveViewStreaming(sessionId, false)
}

function useDocumentVisible(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState === 'visible')

  useEffect(() => {
    const sync = () => setVisible(document.visibilityState === 'visible')

    document.addEventListener('visibilitychange', sync)

    return () => document.removeEventListener('visibilitychange', sync)
  }, [])

  return visible
}

/**
 * Pull visible Browser frames through a dedicated authenticated gateway.
 *
 * Fabric deliberately avoids agent-browser's full-rate CDP screencast here:
 * renderer-side coalescing would not reduce browser capture or transport work.
 * This hook instead requests exactly one upstream capture at a time, with
 * starts separated by at least 500 ms. The gateway independently enforces the
 * same ceiling before it reaches Chromium.
 */
export function useBrowserLiveStreams({
  activeSessionId,
  enabled,
  requestVisualGateway
}: {
  activeSessionId: string | null
  enabled: boolean
  requestVisualGateway: GatewayRequest
}) {
  const liveViews = useStore($liveViews)
  const documentVisible = useDocumentVisible()
  const handlesRef = useRef(new Map<string, StreamHandle>())

  const desiredSessions = useMemo(
    () =>
      Object.values(liveViews)
        .filter(
          state =>
            enabled &&
            state.kind === 'browser' &&
            !state.paused &&
            ((state.presentation === 'pip' && state.pipVisible !== false) ||
              (documentVisible && state.presentation === 'docked' && state.sessionId === activeSessionId)) &&
            state.actions.length > 0 &&
            !state.actions.some(action => action.status === 'running')
        )
        .map(state => ({
          key: `${state.sessionId}:${state.presentation}:${state.actions.at(-1)?.id ?? ''}:${state.actions.at(-1)?.status ?? ''}`,
          sessionId: state.sessionId
        })),
    [activeSessionId, documentVisible, enabled, liveViews]
  )

  const desiredKey = desiredSessions
    .map(({ key }) => key)
    .sort()
    .join('|')

  const desiredSessionsRef = useRef(desiredSessions)
  const desiredRef = useRef(new Set<string>())
  desiredSessionsRef.current = desiredSessions
  desiredRef.current = new Set(desiredSessions.map(({ sessionId }) => sessionId))

  useEffect(() => {
    const desired = new Set(desiredSessionsRef.current.map(({ sessionId }) => sessionId))
    desiredRef.current = desired

    const isCurrent = (sessionId: string, handle: StreamHandle) =>
      !handle.stopped && desiredRef.current.has(sessionId) && handlesRef.current.get(sessionId) === handle

    const stopCurrent = (sessionId: string, handle: StreamHandle) => {
      if (handlesRef.current.get(sessionId) === handle) {
        handlesRef.current.delete(sessionId)
      }

      closeHandle(sessionId, handle)
    }

    function scheduleRetry(sessionId: string, handle: StreamHandle): void {
      if (!isCurrent(sessionId, handle) || handle.retryTimer !== null) {
        return
      }

      setLiveViewStreaming(sessionId, false)

      if (handle.retryAttempt >= RETRY_MAX_ATTEMPTS) {
        stopCurrent(sessionId, handle)

        return
      }

      const delay = Math.min(RETRY_MAX_DELAY_MS, RETRY_BASE_DELAY_MS * 2 ** handle.retryAttempt)
      handle.retryAttempt += 1
      handle.retryTimer = window.setTimeout(() => {
        handle.retryTimer = null

        if (isCurrent(sessionId, handle)) {
          connect(sessionId, handle)
        }
      }, delay)
    }

    function schedulePull(sessionId: string, handle: StreamHandle, delay: number): void {
      if (!isCurrent(sessionId, handle) || handle.pollTimer !== null) {
        return
      }

      handle.pollTimer = window.setTimeout(
        () => {
          handle.pollTimer = null

          if (isCurrent(sessionId, handle)) {
            pullFrame(sessionId, handle)
          }
        },
        Math.max(0, delay)
      )
    }

    function pullFrame(sessionId: string, handle: StreamHandle): void {
      if (!isCurrent(sessionId, handle) || handle.abortController) {
        return
      }

      const startedAt = Date.now()
      const abortController = new AbortController()
      handle.abortController = abortController

      void requestVisualGateway<BrowserFrameResponse>(
        'visual.frame',
        { session_id: sessionId },
        FRAME_REQUEST_TIMEOUT_MS,
        abortController.signal
      )
        .then(response => {
          if (handle.abortController === abortController) {
            handle.abortController = null
          }

          if (!isCurrent(sessionId, handle)) {
            return
          }

          const frame = browserFrame(response)

          if (frame) {
            handle.retryAttempt = 0

            // Static-page backoff: count byte-identical frames so a motionless
            // view polls progressively slower; any change snaps back to full
            // cadence so live motion stays responsive (#64).
            if (frame === handle.lastFrame) {
              handle.idleStreak += 1
            } else {
              handle.idleStreak = 0
              handle.lastFrame = frame
            }

            setLiveViewStreaming(sessionId, true)
            setLiveViewStreamFrame(sessionId, frame)
          } else if (!TRANSIENT_FRAME_REASONS.has(response.reason ?? '')) {
            scheduleRetry(sessionId, handle)

            return
          }

          const elapsed = Math.max(0, Date.now() - startedAt)
          const rawServerDelay = Number(response.retry_after_ms)

          const serverDelay = Number.isFinite(rawServerDelay)
            ? Math.min(MAX_SERVER_INTERVAL_MS, Math.max(0, rawServerDelay))
            : 0

          schedulePull(sessionId, handle, Math.max(serverDelay, idleIntervalMs(handle) - elapsed))
        })
        .catch(() => {
          if (handle.abortController === abortController) {
            handle.abortController = null
          }

          if (isCurrent(sessionId, handle)) {
            scheduleRetry(sessionId, handle)
          }
        })
    }

    function connect(sessionId: string, handle: StreamHandle): void {
      if (!isCurrent(sessionId, handle) || handle.abortController || handle.pollTimer !== null) {
        return
      }

      const abortController = new AbortController()
      handle.abortController = abortController

      void requestVisualGateway<BrowserStreamStatus>(
        'visual.status',
        { session_id: sessionId },
        5_000,
        abortController.signal
      )
        .then(status => {
          if (handle.abortController === abortController) {
            handle.abortController = null
          }

          if (!isCurrent(sessionId, handle)) {
            return
          }

          if (status.available !== true || status.transport !== 'gateway_pull') {
            scheduleRetry(sessionId, handle)

            return
          }

          const serverInterval = Number(status.min_interval_ms)
          handle.frameIntervalMs = Math.min(
            MAX_SERVER_INTERVAL_MS,
            Math.max(FRAME_INTERVAL_MS, Number.isFinite(serverInterval) ? serverInterval : FRAME_INTERVAL_MS)
          )
          setLiveViewStreaming(sessionId, true)
          pullFrame(sessionId, handle)
        })
        .catch(() => {
          if (handle.abortController === abortController) {
            handle.abortController = null
          }

          if (isCurrent(sessionId, handle)) {
            scheduleRetry(sessionId, handle)
          }
        })
    }

    for (const [sessionId, handle] of handlesRef.current) {
      if (!desired.has(sessionId)) {
        stopCurrent(sessionId, handle)
      }
    }

    for (const sessionId of desired) {
      if (handlesRef.current.has(sessionId)) {
        continue
      }

      const handle: StreamHandle = {
        abortController: null,
        frameIntervalMs: FRAME_INTERVAL_MS,
        pollTimer: null,
        retryAttempt: 0,
        retryTimer: null,
        stopped: false,
        lastFrame: null,
        idleStreak: 0
      }

      handlesRef.current.set(sessionId, handle)
      connect(sessionId, handle)
    }
  }, [desiredKey, requestVisualGateway])

  useEffect(
    () => () => {
      for (const [sessionId, handle] of handlesRef.current) {
        closeHandle(sessionId, handle)
      }

      handlesRef.current.clear()
    },
    []
  )
}
