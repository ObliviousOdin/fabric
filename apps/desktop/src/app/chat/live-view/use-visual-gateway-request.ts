import { resolveGatewayWsUrl } from '@fabric/shared'
import { useCallback, useEffect, useRef } from 'react'

import type { HermesConnection } from '@/global'
import { HermesGateway } from '@/hermes'

type VisualGatewayRequest = <T>(
  method: string,
  params?: Record<string, unknown>,
  timeoutMs?: number,
  signal?: AbortSignal
) => Promise<T>

interface VisualGatewayState {
  connection: HermesConnection | null
  connecting: Promise<HermesGateway> | null
  enabled: boolean
  epoch: number
  gateway: HermesGateway | null
  lifecycle: AbortController
}

const VISUAL_METHODS = new Set(['visual.frame', 'visual.status'])

function aborted(): DOMException {
  return new DOMException('Aborted', 'AbortError')
}

function waitWithSignal<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) {
    return promise
  }

  if (signal.aborted) {
    return Promise.reject(aborted())
  }

  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener('abort', onAbort)
      reject(aborted())
    }

    signal.addEventListener('abort', onAbort, { once: true })
    promise.then(
      value => {
        signal.removeEventListener('abort', onAbort)
        resolve(value)
      },
      error => {
        signal.removeEventListener('abort', onAbort)
        reject(error)
      }
    )
  })
}

function closeGateway(state: VisualGatewayState): void {
  state.epoch += 1
  state.lifecycle.abort()
  state.connecting = null
  state.gateway?.close()
  state.gateway = null
}

/**
 * Own the Browser Live View transport.
 *
 * Frames deliberately travel over a second authenticated WebSocket instead of
 * the chat gateway. A large JPEG therefore cannot sit ahead of model deltas,
 * tool events, or approvals in the chat socket's send queue.
 */
export function useVisualGatewayRequest({
  connection,
  enabled
}: {
  connection: HermesConnection | null
  enabled: boolean
}): { requestVisualGateway: VisualGatewayRequest } {
  const connectionKey = connection
    ? JSON.stringify([connection.authMode, connection.baseUrl, connection.mode, connection.profile, connection.wsUrl])
    : ''

  const latestConnectionRef = useRef(connection)
  latestConnectionRef.current = connection

  const stateRef = useRef<VisualGatewayState>({
    connection,
    connecting: null,
    enabled,
    epoch: 0,
    gateway: null,
    lifecycle: new AbortController()
  })

  useEffect(() => {
    const state = stateRef.current
    closeGateway(state)
    state.connection = latestConnectionRef.current
    state.enabled = enabled
    state.lifecycle = new AbortController()

    return () => closeGateway(state)
  }, [connectionKey, enabled])

  const requestVisualGateway = useCallback(
    async <T>(
      method: string,
      params: Record<string, unknown> = {},
      timeoutMs?: number,
      signal?: AbortSignal
    ): Promise<T> => {
      if (!VISUAL_METHODS.has(method)) {
        throw new Error(`Unsupported visual gateway method: ${method}`)
      }

      if (signal?.aborted) {
        throw aborted()
      }

      const state = stateRef.current
      const desktop = window.hermesDesktop
      const connection = state.connection

      if (!state.enabled || connection?.mode !== 'local' || !desktop) {
        throw new Error('Visual gateway unavailable')
      }

      let gateway = state.gateway

      if (gateway?.connectionState !== 'open') {
        if (!state.connecting) {
          gateway?.close()
          const nextGateway = new HermesGateway()
          state.gateway = nextGateway
          const epoch = state.epoch
          const lifecycleSignal = state.lifecycle.signal

          const connecting = (async () => {
            const wsUrl = await waitWithSignal(resolveGatewayWsUrl(desktop, connection), lifecycleSignal)

            if (state.epoch !== epoch || state.gateway !== nextGateway) {
              throw aborted()
            }

            await waitWithSignal(nextGateway.connect(wsUrl), lifecycleSignal)

            if (state.epoch !== epoch || state.gateway !== nextGateway) {
              nextGateway.close()
              throw aborted()
            }

            return nextGateway
          })().catch(error => {
            if (state.gateway === nextGateway) {
              state.gateway = null
            }

            nextGateway.close()
            throw error
          })

          state.connecting = connecting

          void connecting
            .finally(() => {
              if (state.connecting === connecting) {
                state.connecting = null
              }
            })
            .catch(() => undefined)
        }

        gateway = await waitWithSignal(state.connecting, signal)
      }

      if (signal?.aborted) {
        throw aborted()
      }

      return gateway.request<T>(method, params, timeoutMs, signal)
    },
    []
  )

  return { requestVisualGateway }
}
