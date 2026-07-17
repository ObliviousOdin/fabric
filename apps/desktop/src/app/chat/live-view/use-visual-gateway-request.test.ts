import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FabricConnection } from '@/global'

import { useVisualGatewayRequest } from './use-visual-gateway-request'

type Listener = (event: { data?: string }) => void

class FakeWebSocket {
  static CLOSED = 3
  static CONNECTING = 0
  static OPEN = 1
  static autoOpen = true
  static instances: FakeWebSocket[] = []

  readonly sent: Array<{ id: number; jsonrpc: string; method: string; params: Record<string, unknown> }> = []
  readyState = FakeWebSocket.CONNECTING
  private readonly listeners = new Map<string, Set<Listener>>()

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this)

    if (FakeWebSocket.autoOpen) {
      window.setTimeout(() => this.open(), 0)
    }
  }

  addEventListener(type: string, listener: Listener): void {
    const listeners = this.listeners.get(type) ?? new Set<Listener>()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener)
  }

  close(): void {
    if (this.readyState === FakeWebSocket.CLOSED) {
      return
    }

    this.readyState = FakeWebSocket.CLOSED
    this.emit('close', {})
  }

  open(): void {
    if (this.readyState !== FakeWebSocket.CONNECTING) {
      return
    }

    this.readyState = FakeWebSocket.OPEN
    this.emit('open', {})
  }

  send(raw: string): void {
    const request = JSON.parse(raw) as {
      id: number
      jsonrpc: string
      method: string
      params: Record<string, unknown>
    }

    this.sent.push(request)

    const result =
      request.method === 'visual.status'
        ? { available: true, transport: 'gateway_pull' }
        : { available: true, data: 'jpeg', mime_type: 'image/jpeg' }

    window.setTimeout(() => {
      this.emit('message', { data: JSON.stringify({ id: request.id, jsonrpc: '2.0', result }) })
    }, 0)
  }

  private emit(type: string, event: { data?: string }): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event)
    }
  }
}

function localConnection(profile = 'default'): FabricConnection {
  return {
    authMode: 'token',
    baseUrl: 'http://127.0.0.1:8080',
    isFullscreen: false,
    mode: 'local',
    nativeOverlayWidth: 0,
    profile,
    token: 'secret',
    windowButtonPosition: null,
    wsUrl: `ws://127.0.0.1:8080/api/ws?token=${profile}`,
    logs: []
  }
}

async function flush(): Promise<void> {
  await act(async () => {
    for (let index = 0; index < 4; index += 1) {
      await Promise.resolve()
      await vi.advanceTimersByTimeAsync(1)
    }
  })
}

const originalWebSocket = globalThis.WebSocket
let getGatewayWsUrl: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.instances = []
  FakeWebSocket.autoOpen = true
  ;(globalThis as { WebSocket: unknown }).WebSocket = FakeWebSocket
  getGatewayWsUrl = vi.fn(async (profile?: string | null) => `ws://visual.test/api/ws?token=${profile ?? 'default'}`)
  ;(window as { fabricDesktop?: unknown }).fabricDesktop = { getGatewayWsUrl }
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  ;(globalThis as { WebSocket: unknown }).WebSocket = originalWebSocket
  delete (window as { fabricDesktop?: unknown }).fabricDesktop
})

describe('useVisualGatewayRequest', () => {
  it('uses a dedicated authenticated socket for visual RPCs', async () => {
    const { result } = renderHook(() => useVisualGatewayRequest({ connection: localConnection(), enabled: true }))

    const pending = result.current.requestVisualGateway('visual.status', { session_id: 'session-1' })
    await flush()

    await expect(pending).resolves.toEqual({ available: true, transport: 'gateway_pull' })
    expect(getGatewayWsUrl).toHaveBeenCalledWith('default')
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.instances[0].url).toBe('ws://visual.test/api/ws?token=default')
    expect(FakeWebSocket.instances[0].sent).toEqual([
      { id: 1, jsonrpc: '2.0', method: 'visual.status', params: { session_id: 'session-1' } }
    ])
  })

  it('refuses non-visual methods before opening a socket', async () => {
    const { result } = renderHook(() => useVisualGatewayRequest({ connection: localConnection(), enabled: true }))

    await expect(result.current.requestVisualGateway('prompt.submit')).rejects.toThrow(
      'Unsupported visual gateway method'
    )
    expect(getGatewayWsUrl).not.toHaveBeenCalled()
    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it('does not connect for remote or disabled gateways', async () => {
    const remote: FabricConnection = { ...localConnection(), mode: 'remote' }

    const { result, rerender } = renderHook(
      ({ connection, enabled }: { connection: FabricConnection; enabled: boolean }) =>
        useVisualGatewayRequest({ connection, enabled }),
      { initialProps: { connection: remote, enabled: true } }
    )

    await expect(result.current.requestVisualGateway('visual.status')).rejects.toThrow('Visual gateway unavailable')
    rerender({ connection: localConnection(), enabled: false })
    await expect(result.current.requestVisualGateway('visual.status')).rejects.toThrow('Visual gateway unavailable')
    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it('closes the old socket when the active backend changes', async () => {
    const { result, rerender } = renderHook(
      ({ connection }) => useVisualGatewayRequest({ connection, enabled: true }),
      { initialProps: { connection: localConnection('default') } }
    )

    const first = result.current.requestVisualGateway('visual.status')
    await flush()
    await first
    const firstSocket = FakeWebSocket.instances[0]

    rerender({ connection: localConnection('worker') })
    expect(firstSocket.readyState).toBe(FakeWebSocket.CLOSED)

    const second = result.current.requestVisualGateway('visual.frame')
    await flush()
    await second

    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(FakeWebSocket.instances[1].url).toBe('ws://visual.test/api/ws?token=worker')
  })

  it('honors an already-aborted request without opening a socket', async () => {
    const { result } = renderHook(() => useVisualGatewayRequest({ connection: localConnection(), enabled: true }))
    const controller = new AbortController()
    controller.abort()

    await expect(
      result.current.requestVisualGateway('visual.frame', {}, 4_000, controller.signal)
    ).rejects.toMatchObject({ name: 'AbortError' })
    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it('closes its dedicated socket on unmount', async () => {
    const { result, unmount } = renderHook(() =>
      useVisualGatewayRequest({ connection: localConnection(), enabled: true })
    )

    const pending = result.current.requestVisualGateway('visual.status')
    await flush()
    await pending
    const socket = FakeWebSocket.instances[0]

    unmount()

    expect(socket.readyState).toBe(FakeWebSocket.CLOSED)
  })

  it('cannot leave a stale socket open when the backend changes during connect', async () => {
    FakeWebSocket.autoOpen = false

    const { result, rerender } = renderHook(
      ({ connection }) => useVisualGatewayRequest({ connection, enabled: true }),
      { initialProps: { connection: localConnection('default') } }
    )

    const staleRequest = result.current.requestVisualGateway('visual.status')
    const staleRejection = expect(staleRequest).rejects.toMatchObject({ name: 'AbortError' })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(FakeWebSocket.instances).toHaveLength(1)
    const staleSocket = FakeWebSocket.instances[0]
    expect(staleSocket.readyState).toBe(FakeWebSocket.CONNECTING)

    rerender({ connection: localConnection('worker') })

    expect(staleSocket.readyState).toBe(FakeWebSocket.CLOSED)
    await staleRejection

    FakeWebSocket.autoOpen = true
    const currentRequest = result.current.requestVisualGateway('visual.frame')
    await flush()
    await expect(currentRequest).resolves.toMatchObject({ available: true, mime_type: 'image/jpeg' })
    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(FakeWebSocket.instances[1].url).toBe('ws://visual.test/api/ws?token=worker')
  })

  it('cannot open a stale socket when the backend changes during URL resolution', async () => {
    let resolveStaleUrl!: (url: string) => void
    getGatewayWsUrl
      .mockImplementationOnce(
        () =>
          new Promise<string>(resolve => {
            resolveStaleUrl = resolve
          })
      )
      .mockResolvedValueOnce('ws://visual.test/api/ws?token=worker')

    const { result, rerender } = renderHook(
      ({ connection }) => useVisualGatewayRequest({ connection, enabled: true }),
      { initialProps: { connection: localConnection('default') } }
    )

    const staleRequest = result.current.requestVisualGateway('visual.status')
    const staleRejection = expect(staleRequest).rejects.toMatchObject({ name: 'AbortError' })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(getGatewayWsUrl).toHaveBeenCalledWith('default')
    expect(FakeWebSocket.instances).toHaveLength(0)

    rerender({ connection: localConnection('worker') })
    await staleRejection

    resolveStaleUrl('ws://stale.test/api/ws?token=default')
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(FakeWebSocket.instances).toHaveLength(0)

    const currentRequest = result.current.requestVisualGateway('visual.status')
    await flush()
    await currentRequest

    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.instances[0].url).toBe('ws://visual.test/api/ws?token=worker')
  })
})
