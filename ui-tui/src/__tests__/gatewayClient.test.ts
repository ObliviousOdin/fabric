import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

interface ListenerEntry {
  callback: (event: any) => void
  once: boolean
}

const { FakeWebSocket } = vi.hoisted(() => {
  class FakeWebSocket {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSING = 2
    static CLOSED = 3
    static instances: FakeWebSocket[] = []

    readyState = FakeWebSocket.CONNECTING
    failNextSend = false
    sent: string[] = []
    readonly url: string
    private listeners = new Map<string, ListenerEntry[]>()

    constructor(url: string) {
      this.url = url
      FakeWebSocket.instances.push(this)
    }

    static reset() {
      FakeWebSocket.instances = []
    }

    addEventListener(type: string, callback: (event: any) => void, options?: unknown) {
      const once =
        typeof options === 'object' &&
        options !== null &&
        'once' in options &&
        Boolean((options as { once?: unknown }).once)

      const entries = this.listeners.get(type) ?? []

      entries.push({ callback, once })
      this.listeners.set(type, entries)
    }

    removeEventListener(type: string, callback: (event: any) => void) {
      const entries = this.listeners.get(type)

      if (!entries) {
        return
      }

      this.listeners.set(
        type,
        entries.filter(entry => entry.callback !== callback)
      )
    }

    send(payload: string) {
      if (this.failNextSend) {
        this.failNextSend = false
        throw new Error('send failed')
      }

      if (this.readyState !== FakeWebSocket.OPEN) {
        throw new Error('socket not open')
      }

      this.sent.push(payload)
    }

    close(code = 1000) {
      if (this.readyState === FakeWebSocket.CLOSED) {
        return
      }

      this.readyState = FakeWebSocket.CLOSED
      this.emit('close', { code })
    }

    open() {
      this.readyState = FakeWebSocket.OPEN
      this.emit('open', {})
    }

    message(data: string) {
      this.emit('message', { data })
    }

    error() {
      this.emit('error', {})
    }

    private emit(type: string, event: any) {
      const entries = [...(this.listeners.get(type) ?? [])]

      for (const entry of entries) {
        entry.callback(event)

        if (entry.once) {
          this.removeEventListener(type, entry.callback)
        }
      }
    }
  }

  return { FakeWebSocket }
})

vi.mock('undici', () => ({ WebSocket: FakeWebSocket }))

import type { TuiLaunchContext } from '../config/launchContext.js'
import { GatewayClient } from '../gatewayClient.js'

describe('GatewayClient websocket attach mode', () => {
  const originalWebSocket = globalThis.WebSocket
  const launchContext: TuiLaunchContext = { version: 1 }

  beforeEach(() => {
    launchContext.gateway_url = ''
    launchContext.sidecar_url = ''
    FakeWebSocket.reset()
    ;(globalThis as { WebSocket?: unknown }).WebSocket = FakeWebSocket as unknown as typeof WebSocket
  })

  afterEach(() => {
    vi.useRealTimers()

    FakeWebSocket.reset()

    if (originalWebSocket) {
      globalThis.WebSocket = originalWebSocket
    } else {
      delete (globalThis as { WebSocket?: unknown }).WebSocket
    }
  })

  it('waits for websocket open and resolves RPC requests', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    const req = gw.request<{ ok: boolean }>('session.create', { cols: 80 })

    expect(gatewaySocket.sent).toHaveLength(0)
    gatewaySocket.open()
    await vi.waitFor(() => expect(gatewaySocket.sent).toHaveLength(1))

    const frame = JSON.parse(gatewaySocket.sent[0] ?? '{}') as { id: string; method: string }
    expect(frame.method).toBe('session.create')

    gatewaySocket.message(JSON.stringify({ id: frame.id, jsonrpc: '2.0', result: { ok: true } }))
    await expect(req).resolves.toEqual({ ok: true })

    gw.kill()
  })

  it('drains buffered events on a later microtask, not synchronously inside drain()', async () => {
    // Regression for #36658: in attach mode the already-running gateway
    // replays `gateway.ready` the instant the socket connects, so it lands in
    // bufferedEvents BEFORE the consumer's mount-time subscribe effect runs.
    // If drain() emitted those synchronously, the gateway.ready handler's
    // setState cascade would run inside React's first commit -> "Too many
    // re-renders" (#301). drain() must defer the buffered flush so the first
    // commit settles first.
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    // Server replays ready BEFORE the consumer subscribes (attach-mode timing):
    gatewaySocket.message(
      JSON.stringify({ jsonrpc: '2.0', method: 'event', params: { type: 'gateway.ready', payload: {} } })
    )

    const order: string[] = []

    gw.on('event', ev => order.push(`event:${ev.type}`))
    gw.drain()
    order.push('after-drain')

    // Buffered event must NOT have fired synchronously inside drain():
    expect(order).toEqual(['after-drain'])

    // ...and must arrive on the next microtask.
    await vi.waitFor(() => expect(order).toContain('event:gateway.ready'))
    expect(order).toEqual(['after-drain', 'event:gateway.ready'])

    gw.kill()
  })

  it('preserves FIFO order when a live event arrives before the deferred flush', async () => {
    // #36658 hardening: `subscribed` must NOT flip synchronously in drain().
    // A live event delivered in the window between drain() returning and the
    // deferred microtask running must still queue BEHIND the chronologically
    // earlier buffered events, not jump ahead of them.
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    // Buffered first (replayed on connect, before subscribe):
    gatewaySocket.message(
      JSON.stringify({ jsonrpc: '2.0', method: 'event', params: { type: 'gateway.ready', payload: {} } })
    )

    const order: string[] = []

    gw.on('event', ev => order.push(ev.type))
    gw.drain()

    // A LIVE event arrives synchronously in the post-drain / pre-microtask gap:
    gatewaySocket.message(
      JSON.stringify({ jsonrpc: '2.0', method: 'event', params: { type: 'session.info', payload: {} } })
    )

    // Nothing emitted yet (subscribed stays false until the microtask):
    expect(order).toEqual([])

    await vi.waitFor(() => expect(order.length).toBe(2))
    // FIFO preserved: the earlier-buffered gateway.ready precedes the live one.
    expect(order).toEqual(['gateway.ready', 'session.info'])

    gw.kill()
  })

  it('mirrors event frames to sidecar websocket when configured', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'

    const gw = new GatewayClient({ launchContext })
    const seen: string[] = []

    gw.on('event', ev => seen.push(ev.type))
    gw.start()

    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))

    const sidecarSocket = FakeWebSocket.instances[1]!

    sidecarSocket.open()
    gw.drain()
    // drain() flips `subscribed` on a microtask now (#36658); let it settle so
    // the subsequent live event takes the synchronous publish path.
    await Promise.resolve()

    const eventFrame = JSON.stringify({
      jsonrpc: '2.0',
      method: 'event',
      params: { type: 'tool.start', payload: { tool_id: 't1' } }
    })

    gatewaySocket.message(eventFrame)

    expect(seen).toContain('tool.start')
    expect(sidecarSocket.sent).toContain(eventFrame)

    gw.kill()
  })

  it('buffers semantic frames until the sidecar opens and strips heavy session metadata', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))
    const sidecarSocket = FakeWebSocket.instances[1]!

    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: {
          type: 'session.info',
          session_id: 'sid-1',
          private_transport_metadata: 'strip-me',
          payload: {
            cwd: '/repo',
            model: 'openai/gpt-5',
            running: true,
            title: 'Live task',
            system_prompt: 'private',
            tools: { terminal: {} },
            skills: { private: {} },
            mcp_servers: ['private']
          }
        }
      })
    )

    expect(sidecarSocket.sent).toEqual([])
    sidecarSocket.open()
    expect(sidecarSocket.sent).toHaveLength(1)
    expect(JSON.parse(sidecarSocket.sent[0] ?? '{}').params).toEqual({
      type: 'session.info',
      session_id: 'sid-1',
      payload: {
        cwd: '/repo',
        model: 'openai/gpt-5',
        running: true,
        title: 'Live task'
      }
    })

    gw.kill()
  })

  it('does not mirror transcript or reasoning token deltas', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))
    const sidecarSocket = FakeWebSocket.instances[1]!
    sidecarSocket.open()

    for (const type of ['message.delta', 'reasoning.delta', 'thinking.delta']) {
      gatewaySocket.message(
        JSON.stringify({ jsonrpc: '2.0', method: 'event', params: { type, payload: { text: 'token' } } })
      )
    }

    for (const type of ['subagent.text', 'subagent.progress', 'background.complete', 'pet.hatch.progress']) {
      gatewaySocket.message(
        JSON.stringify({ jsonrpc: '2.0', method: 'event', params: { type, payload: { text: 'ignored' } } })
      )
    }

    expect(sidecarSocket.sent).toEqual([])

    gw.kill()
  })

  it('projects tool lifecycle fields and artifacts without mirroring raw results or final text', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))
    const sidecarSocket = FakeWebSocket.instances[1]!

    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: {
          type: 'tool.complete',
          session_id: 'sid-1',
          payload: {
            args: { path: '/repo/output/report.md', prompt: 'private prompt' },
            duration_s: 1.5,
            inline_diff: 'private diff',
            name: 'write_file',
            result: {
              download_url: 'https://example.test/export/report.pdf',
              raw: 'private result body'
            },
            result_text: 'private result text',
            summary: 'Wrote report',
            tool_id: 'tool-1',
            todos: [{ content: 'Verify report', id: 'todo-1', private: 'strip-me', status: 'pending' }]
          }
        }
      })
    )
    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: {
          type: 'message.complete',
          session_id: 'sid-1',
          payload: { reasoning: 'private reasoning', rendered: 'private ansi', text: 'private final answer' }
        }
      })
    )

    sidecarSocket.open()
    expect(sidecarSocket.sent.map(frame => JSON.parse(frame).params)).toEqual([
      {
        type: 'tool.complete',
        session_id: 'sid-1',
        payload: {
          duration_s: 1.5,
          files_written: ['/repo/output/report.md', 'https://example.test/export/report.pdf'],
          name: 'write_file',
          summary: 'Wrote report',
          tool_id: 'tool-1',
          todos: [{ content: 'Verify report', id: 'todo-1', status: 'pending' }]
        }
      },
      { type: 'message.complete', session_id: 'sid-1' }
    ])
    expect(sidecarSocket.sent.join('\n')).not.toContain('private')

    gw.kill()
  })

  it('rejects oversized semantic frames before retaining them', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))
    const sidecarSocket = FakeWebSocket.instances[1]!

    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: { type: 'status.update', payload: { kind: 'process', text: 'x'.repeat(40_000) } }
      })
    )
    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: { type: 'tool.start', payload: { name: 'terminal', tool_id: 'small' } }
      })
    )

    sidecarSocket.open()
    expect(sidecarSocket.sent).toHaveLength(1)
    expect(JSON.parse(sidecarSocket.sent[0] ?? '{}').params.payload.tool_id).toBe('small')

    gw.kill()
  })

  it('caps adversarial todo-list scans before sidecar retention', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))
    const sidecarSocket = FakeWebSocket.instances[1]!
    let reads = 0

    const todos = new Proxy([], {
      get(target, property, receiver) {
        if (property === 'length') {
          return 1_000_000
        }

        if (typeof property === 'string' && /^\d+$/.test(property)) {
          reads += 1

          if (Number(property) >= 128) {
            throw new Error('todo compactor scanned beyond its cap')
          }

          return {}
        }

        return Reflect.get(target, property, receiver)
      }
    })

    gw.drain()
    await Promise.resolve()
    gw.publishLocalEvent({
      payload: { name: 'todo', todos, tool_id: 'bounded' },
      type: 'tool.complete'
    } as any)
    sidecarSocket.open()

    expect(reads).toBe(128)
    expect(JSON.parse(sidecarSocket.sent[0] ?? '{}').params).toEqual({
      type: 'tool.complete',
      payload: { name: 'todo', tool_id: 'bounded' }
    })

    gw.kill()
  })

  it('reconnects the sidecar with backoff and flushes queued semantic frames', async () => {
    vi.useFakeTimers()
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    const firstSidecar = FakeWebSocket.instances[1]!
    firstSidecar.open()
    firstSidecar.close(1006)

    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: { type: 'tool.start', payload: { tool_id: 'queued' } }
      })
    )
    expect(FakeWebSocket.instances).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(100)
    expect(FakeWebSocket.instances).toHaveLength(3)
    const secondSidecar = FakeWebSocket.instances[2]!
    secondSidecar.open()
    expect(JSON.parse(secondSidecar.sent[0] ?? '{}').params.type).toBe('tool.start')

    gw.kill()
    vi.useRealTimers()
  })

  it('reconnects and preserves the frame when an open sidecar send throws', async () => {
    vi.useFakeTimers()
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    const firstSidecar = FakeWebSocket.instances[1]!
    firstSidecar.open()
    firstSidecar.failNextSend = true

    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: { type: 'tool.complete', payload: { tool_id: 'preserved' } }
      })
    )
    expect(firstSidecar.readyState).toBe(FakeWebSocket.CLOSED)
    await vi.advanceTimersByTimeAsync(100)
    const secondSidecar = FakeWebSocket.instances[2]!
    secondSidecar.open()
    expect(JSON.parse(secondSidecar.sent[0] ?? '{}').params).toEqual({
      type: 'tool.complete',
      payload: { tool_id: 'preserved' }
    })

    gw.kill()
    vi.useRealTimers()
  })

  it('bounds sidecar reconnect attempts when construction keeps failing', async () => {
    vi.useFakeTimers()
    let sidecarAttempts = 0
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    ;(globalThis as { WebSocket?: unknown }).WebSocket = class FailingSidecarWebSocket extends FakeWebSocket {
      constructor(url: string) {
        if (url.includes('/api/pub')) {
          sidecarAttempts += 1
          throw new Error('sidecar unavailable')
        }

        super(url)
      }
    } as unknown as typeof WebSocket
    const gw = new GatewayClient({ launchContext })

    gw.start()
    FakeWebSocket.instances[0]!.open()
    await vi.advanceTimersByTimeAsync(10_000)

    // Initial attempt plus five bounded retries; no timer remains after that.
    expect(sidecarAttempts).toBe(6)
    expect(gw.getLogTail(20)).toContain('[sidecar] reconnect attempts exhausted')

    gw.kill()
    vi.useRealTimers()
  })

  it('restarts a bounded reconnect cycle on the next semantic event after cooldown', async () => {
    vi.useFakeTimers()
    let sidecarAttempts = 0
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'
    ;(globalThis as { WebSocket?: unknown }).WebSocket = class RecoveringSidecarWebSocket extends FakeWebSocket {
      constructor(url: string) {
        if (url.includes('/api/pub')) {
          sidecarAttempts += 1

          if (sidecarAttempts <= 6) {
            throw new Error('sidecar unavailable')
          }
        }

        super(url)
      }
    } as unknown as typeof WebSocket
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(sidecarAttempts).toBe(6)

    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: { type: 'status.update', payload: { kind: 'process', text: 'queued during cooldown' } }
      })
    )
    expect(sidecarAttempts).toBe(6)

    await vi.advanceTimersByTimeAsync(4_000)
    gatewaySocket.message(
      JSON.stringify({
        jsonrpc: '2.0',
        method: 'event',
        params: { type: 'tool.start', payload: { name: 'terminal', tool_id: 'recovered' } }
      })
    )
    expect(sidecarAttempts).toBe(7)
    const recoveredSidecar = FakeWebSocket.instances[1]!
    recoveredSidecar.open()
    expect(recoveredSidecar.sent.map(frame => JSON.parse(frame).params.type)).toEqual(['status.update', 'tool.start'])

    gw.kill()
    vi.useRealTimers()
  })

  it('publishes local dashboard-control events to the sidecar websocket', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = 'ws://gateway.test/api/pub?token=abc&channel=demo'

    const gw = new GatewayClient({ launchContext })
    const seen: string[] = []

    gw.on('event', ev => seen.push(ev.type))
    gw.start()

    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))

    const sidecarSocket = FakeWebSocket.instances[1]!

    sidecarSocket.open()
    gw.drain()
    // drain() flips `subscribed` on a microtask now (#36658); let it settle.
    await Promise.resolve()

    gw.publishLocalEvent({
      payload: { reason: 'idle_exit_hotkey' },
      session_id: 'sid-old',
      type: 'dashboard.new_session_requested'
    })

    expect(seen).toContain('dashboard.new_session_requested')
    expect(JSON.parse(sidecarSocket.sent.at(-1) ?? '{}')).toEqual({
      jsonrpc: '2.0',
      method: 'event',
      params: {
        payload: { reason: 'idle_exit_hotkey' },
        session_id: 'sid-old',
        type: 'dashboard.new_session_requested'
      }
    })

    gw.kill()
  })

  it('emits exit when attached websocket closes', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient({ launchContext })
    const exits: Array<null | number> = []

    gw.on('exit', code => exits.push(code))
    gw.start()

    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    gw.drain()
    // drain() flips `subscribed` on a microtask now (#36658); let it settle so
    // the close below takes the synchronous exit path.
    await Promise.resolve()
    gatewaySocket.close(1011)

    expect(exits).toEqual([1011])
    expect(gw.getLogTail(20)).toContain('[lifecycle] websocket close code=1011')
    expect(gw.getLogTail(20)).toContain('[lifecycle] transport exit code=1011')
  })

  it('rejects pending RPCs with websocket wording when the attached socket closes', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    gw.drain()

    const req = gw.request('session.create', {})
    await vi.waitFor(() => expect(gatewaySocket.sent.length).toBeGreaterThan(0))

    gatewaySocket.close(1011)

    await expect(req).rejects.toThrow(/gateway websocket closed \(1011\)/)
  })

  it('rejects pending RPCs when kill() closes the attached websocket', async () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    gw.drain()

    const req = gw.request('session.create', {})
    await vi.waitFor(() => expect(gatewaySocket.sent.length).toBeGreaterThan(0))

    gw.kill('test.shutdown')

    await expect(req).rejects.toThrow(/gateway closed/)
    expect(gw.getLogTail(20)).toContain('[lifecycle] GatewayClient.kill reason=test.shutdown')
  })

  it('reattaches when the launch-context gateway URL rotates between requests', async () => {
    launchContext.gateway_url = 'ws://gateway-old.test/api/ws?token=abc'
    const gw = new GatewayClient({ launchContext })

    gw.start()
    const firstSocket = FakeWebSocket.instances[0]!

    firstSocket.open()
    gw.drain()

    const stale = gw.request('session.create', {})
    await vi.waitFor(() => expect(firstSocket.sent.length).toBeGreaterThan(0))

    launchContext.gateway_url = 'ws://gateway-new.test/api/ws?token=xyz'
    const next = gw.request('session.create', {})

    await expect(stale).rejects.toThrow(/gateway attach url changed/)
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))

    const secondSocket = FakeWebSocket.instances[1]!
    expect(secondSocket.url).toContain('gateway-new.test')

    secondSocket.open()
    await vi.waitFor(() => expect(secondSocket.sent.length).toBeGreaterThan(0))

    const frame = JSON.parse(secondSocket.sent[0] ?? '{}') as { id: string }
    secondSocket.message(JSON.stringify({ id: frame.id, jsonrpc: '2.0', result: { ok: true } }))

    await expect(next).resolves.toEqual({ ok: true })
    gw.kill()
  })

  it('uses the undici WebSocket fallback when global WebSocket is unavailable', () => {
    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=hunter2&channel=secret'
    delete (globalThis as { WebSocket?: unknown }).WebSocket

    const gw = new GatewayClient({ launchContext })

    gw.start()
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.instances[0]?.url).toBe('ws://gateway.test/api/ws?token=hunter2&channel=secret')

    gw.kill()
  })

  it('redacts attach URL secrets when the WebSocket constructor throws', () => {
    const secretUrl = 'ws://gateway.test/api/ws?token=hunter2&channel=secret'

    launchContext.gateway_url = secretUrl
    ;(globalThis as { WebSocket?: unknown }).WebSocket = class ThrowingWebSocket extends FakeWebSocket {
      constructor(url: string) {
        throw new TypeError(`Invalid URL: ${url}`)
      }
    } as unknown as typeof WebSocket

    const gw = new GatewayClient({ launchContext })

    gw.start()
    gw.drain()

    const tail = gw.getLogTail(20)
    expect(tail).not.toContain('hunter2')
    expect(tail).not.toContain('channel=secret')
    expect(tail).not.toContain(secretUrl)
    expect(tail).toContain('ws://gateway.test/api/ws?***')

    gw.kill()
  })

  it('redacts sidecar URL secrets when the WebSocket constructor throws', async () => {
    const sidecarUrl = 'ws://gateway.test/api/pub?token=hunter2&channel=secret'

    launchContext.gateway_url = 'ws://gateway.test/api/ws?token=abc'
    launchContext.sidecar_url = sidecarUrl
    ;(globalThis as { WebSocket?: unknown }).WebSocket = class ThrowingSidecarWebSocket extends FakeWebSocket {
      constructor(url: string) {
        if (url.includes('/api/pub')) {
          throw new TypeError(`Invalid URL: ${url}`)
        }

        super(url)
      }
    } as unknown as typeof WebSocket

    const gw = new GatewayClient({ launchContext })

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(gw.getLogTail(20)).toContain('[sidecar] failed to connect'))

    const tail = gw.getLogTail(20)
    expect(tail).not.toContain('hunter2')
    expect(tail).not.toContain('channel=secret')
    expect(tail).not.toContain(sidecarUrl)
    expect(tail).toContain('ws://gateway.test/api/pub?***')

    gw.kill()
  })

  it('redacts user-info credentials even on URLs the WHATWG parser rejects', () => {
    // Port 99999 is outside the WHATWG URL parser's valid 0–65535
    // range and survives `.trim()`, so the fixture deterministically
    // exercises `redactUrl()`'s fallback branch across Node versions.
    // (An earlier `%zz` user-info fixture did NOT actually throw in
    // recent Node — WHATWG accepts malformed percent escapes there —
    // which silently routed the test through the structured-URL path.)
    const fixture = 'ws://alice:hunter2@gateway.test:99999/api/ws?token=secret'
    expect(() => new URL(fixture)).toThrow()

    launchContext.gateway_url = fixture
    ;(globalThis as { WebSocket?: unknown }).WebSocket = class ThrowingWebSocket extends FakeWebSocket {
      constructor(url: string) {
        throw new TypeError(`Invalid URL: ${url}`)
      }
    } as unknown as typeof WebSocket

    const gw = new GatewayClient({ launchContext })

    gw.start()
    gw.drain()

    const tail = gw.getLogTail(20)
    expect(tail).not.toContain('alice')
    expect(tail).not.toContain('hunter2')
    expect(tail).not.toContain('token=secret')

    gw.kill()
  })
})
