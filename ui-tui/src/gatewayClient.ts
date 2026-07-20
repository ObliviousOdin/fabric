import { type ChildProcess, spawn } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { existsSync, unlinkSync } from 'node:fs'
import { delimiter, resolve } from 'node:path'
import { createInterface } from 'node:readline'

import { WebSocket as UndiciWebSocket } from 'undici'

import { writeTuiLaunchContext } from './config/launchContext.js'
import type { GatewayRuntimeOptions } from './config/runtime.js'
import type { GatewayEvent } from './gatewayTypes.js'
import { CircularBuffer } from './lib/circularBuffer.js'
import { recordParentLifecycle } from './lib/parentLog.js'

const MAX_GATEWAY_LOG_LINES = 200
const MAX_LOG_LINE_BYTES = 4096
const MAX_BUFFERED_EVENTS = 2000
const MAX_BUFFERED_SIDECAR_FRAMES = 256
const MAX_SIDECAR_FRAME_BYTES = 32 * 1024
const MAX_SIDECAR_LIST_ITEMS = 20
const MAX_SIDECAR_INPUT_LIST_SCAN = 128
const MAX_SIDECAR_ARTIFACT_SCAN_NODES = 128
const MAX_SIDECAR_FIELD_CHARS = 8 * 1024
const MAX_SIDECAR_EVENT_TYPE_CHARS = 128
const MAX_SIDECAR_SESSION_ID_CHARS = 512
const MAX_LOG_PREVIEW = 240
const STARTUP_TIMEOUT_MS = 15_000
const REQUEST_TIMEOUT_MS = 120_000
const WS_CONNECTING = 0
const WS_OPEN = 1
const WS_CLOSING = 2
const WS_CLOSED = 3
const SIDECAR_MAX_RECONNECT_ATTEMPTS = 5
const SIDECAR_RECONNECT_COOLDOWN_MS = 10_000
const SIDECAR_STREAM_ONLY_EVENTS = new Set(['message.delta', 'reasoning.delta', 'thinking.delta'])

const SIDECAR_SESSION_INFO_KEYS = new Set([
  'credential_warning',
  'cwd',
  'model',
  'provider',
  'running',
  'session_id',
  'title'
])

const SIDECAR_EVENT_PAYLOAD_KEYS: Readonly<Record<string, ReadonlySet<string>>> = {
  'approval.request': new Set(['request_id']),
  'dashboard.new_session_requested': new Set(['reason']),
  error: new Set(['message']),
  'session.info': SIDECAR_SESSION_INFO_KEYS,
  'session.title': new Set(['session_id', 'title']),
  'status.update': new Set(['kind', 'text']),
  'subagent.complete': new Set([
    'child_session_id',
    'depth',
    'duration_seconds',
    'error',
    'files_written',
    'parent_id',
    'status',
    'subagent_id',
    'summary',
    'task_count',
    'task_index',
    'tool_name'
  ]),
  'tool.start': new Set(['context', 'name', 'tool_id', 'todos']),
  'tool.complete': new Set(['duration_s', 'error', 'files_written', 'name', 'summary', 'tool_id', 'todos'])
}

const SIDECAR_ACCEPTED_EVENTS = new Set([
  'approval.request',
  'dashboard.new_session_requested',
  'error',
  'message.complete',
  'message.start',
  'session.info',
  'session.title',
  'status.update',
  'subagent.complete',
  'tool.complete',
  'tool.start'
])

const SIDECAR_EMPTY_PAYLOAD_KEYS = new Set<string>()
const SIDECAR_ARTIFACT_KEY_RE = /(?:^|[._-])(artifact|download|file|image|output|path|target|url)(?:s|$|[._-])/i

const SIDECAR_ARTIFACT_EXT_RE =
  /\.(?:bmp|csv|gif|gz|jpe?g|json|md|mov|mp3|mp4|pdf|png|svg|tar|txt|wav|webp|zip)(?:[?#].*)?$/i

const _sidecarEncoder = new TextEncoder()

class SidecarProjectionTooLarge extends Error {}

const asObjectRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null

const compactSidecarTodos = (value: unknown): Array<Record<string, string>> => {
  if (!Array.isArray(value)) {
    return []
  }

  const compact: Array<Record<string, string>> = []

  for (let index = 0; index < value.length && index < MAX_SIDECAR_INPUT_LIST_SCAN; index += 1) {
    const item = value[index]
    const record = asObjectRecord(item)
    const content = typeof record?.content === 'string' ? record.content : ''

    if (content.length > MAX_SIDECAR_FIELD_CHARS) {
      throw new SidecarProjectionTooLarge('todo content exceeds sidecar field cap')
    }

    if (!content.trim()) {
      continue
    }

    const todo: Record<string, string> = { content }

    for (const key of ['id', 'status'] as const) {
      if (typeof record?.[key] === 'string') {
        if (record[key].length > MAX_SIDECAR_FIELD_CHARS) {
          throw new SidecarProjectionTooLarge(`todo ${key} exceeds sidecar field cap`)
        }

        todo[key] = record[key]
      }
    }

    compact.push(todo)

    if (compact.length >= MAX_SIDECAR_LIST_ITEMS) {
      break
    }
  }

  return compact
}

const compactSidecarFiles = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }

  const compact: string[] = []

  for (let index = 0; index < value.length && index < MAX_SIDECAR_INPUT_LIST_SCAN; index += 1) {
    const item = value[index]

    if (typeof item !== 'string') {
      continue
    }

    if (item.length > 2048) {
      throw new SidecarProjectionTooLarge('artifact path exceeds sidecar field cap')
    }

    compact.push(item)

    if (compact.length >= MAX_SIDECAR_LIST_ITEMS) {
      break
    }
  }

  return compact
}

const looksLikeSidecarArtifact = (value: string, keyPath: string) => {
  if (!value || value.length > 2048 || value.startsWith('data:')) {
    return false
  }

  const pathLike = /^(?:file:\/\/|\/|~\/|\.\.?\/|[A-Za-z]:[\\/])/.test(value)
  const urlLike = /^https?:\/\//i.test(value)

  if (urlLike) {
    return SIDECAR_ARTIFACT_EXT_RE.test(value)
  }

  return pathLike && (SIDECAR_ARTIFACT_KEY_RE.test(keyPath) || SIDECAR_ARTIFACT_EXT_RE.test(value))
}

const compactSidecarArtifacts = (payload: Record<string, unknown>): string[] => {
  const found = new Set(compactSidecarFiles(payload.files_written))
  const budget = { remaining: MAX_SIDECAR_ARTIFACT_SCAN_NODES }

  const visit = (value: unknown, keyPath: string, depth: number) => {
    if (found.size >= MAX_SIDECAR_LIST_ITEMS || budget.remaining <= 0 || depth > 6) {
      return
    }

    budget.remaining -= 1

    if (typeof value === 'string') {
      if (value.length > 2048) {
        return
      }

      const normalized = value.trim().replace(/[),.;]+$/, '')

      if (looksLikeSidecarArtifact(normalized, keyPath)) {
        found.add(normalized)
      }

      return
    }

    if (Array.isArray(value)) {
      for (
        let index = 0;
        index < value.length && budget.remaining > 0 && found.size < MAX_SIDECAR_LIST_ITEMS;
        index += 1
      ) {
        visit(value[index], `${keyPath}.${index}`, depth + 1)
      }

      return
    }

    const record = asObjectRecord(value)

    if (!record) {
      return
    }

    for (const key in record) {
      if (budget.remaining <= 0 || found.size >= MAX_SIDECAR_LIST_ITEMS) {
        break
      }

      if (Object.prototype.hasOwnProperty.call(record, key)) {
        visit(record[key], keyPath ? `${keyPath}.${key}` : key, depth + 1)
      }
    }
  }

  visit(payload.args, 'args', 0)
  visit(payload.result, 'result', 0)

  return Array.from(found).slice(0, MAX_SIDECAR_LIST_ITEMS)
}

const sidecarPayloadKeys = (eventType: string): ReadonlySet<string> => {
  return SIDECAR_EVENT_PAYLOAD_KEYS[eventType] ?? SIDECAR_EMPTY_PAYLOAD_KEYS
}

const compactSidecarPayload = (eventType: string, value: unknown): Record<string, unknown> => {
  const payload = asObjectRecord(value)

  if (!payload) {
    return {}
  }

  const compact: Record<string, unknown> = {}

  for (const key of sidecarPayloadKeys(eventType)) {
    const field = payload[key]

    if (key === 'todos') {
      const todos = compactSidecarTodos(field)

      if (todos.length) {
        compact[key] = todos
      }
    } else if (key === 'files_written') {
      const files = eventType === 'tool.complete' ? compactSidecarArtifacts(payload) : compactSidecarFiles(field)

      if (files.length) {
        compact[key] = files
      }
    } else if (
      typeof field === 'string' ||
      typeof field === 'boolean' ||
      (typeof field === 'number' && Number.isFinite(field))
    ) {
      if (typeof field === 'string' && field.length > MAX_SIDECAR_FIELD_CHARS) {
        throw new SidecarProjectionTooLarge(`${eventType}.${key} exceeds sidecar field cap`)
      }

      compact[key] = field
    }
  }

  return compact
}

const getWebSocketCtor = (): typeof WebSocket =>
  typeof WebSocket === 'undefined' ? (UndiciWebSocket as unknown as typeof WebSocket) : WebSocket

const truncateLine = (line: string) =>
  line.length > MAX_LOG_LINE_BYTES ? `${line.slice(0, MAX_LOG_LINE_BYTES)}… [truncated ${line.length} bytes]` : line

const describeChild = (proc: ChildProcess | null) => {
  if (!proc) {
    return 'pid=none'
  }

  return `pid=${proc.pid ?? 'unknown'} killed=${proc.killed} exitCode=${proc.exitCode ?? 'null'} signal=${proc.signalCode ?? 'null'}`
}

const resolveGatewayAttachUrl = (runtime: GatewayRuntimeOptions) => {
  const raw = runtime.launchContext.gateway_url?.trim()

  return raw ? raw : null
}

const resolveSidecarUrl = (runtime: GatewayRuntimeOptions) => {
  const raw = runtime.launchContext.sidecar_url?.trim()

  return raw ? raw : null
}

const resolvePython = (root: string, launcherPython?: string) => {
  const configured = launcherPython?.trim() || process.env.PYTHON?.trim()

  if (configured) {
    return configured
  }

  const venv = process.env.VIRTUAL_ENV?.trim()

  const hit = [
    venv && resolve(venv, 'bin/python'),
    venv && resolve(venv, 'Scripts/python.exe'),
    resolve(root, '.venv/bin/python'),
    resolve(root, '.venv/bin/python3'),
    resolve(root, 'venv/bin/python'),
    resolve(root, 'venv/bin/python3')
  ].find(p => p && existsSync(p))

  return hit || (process.platform === 'win32' ? 'python' : 'python3')
}

const asGatewayEvent = (value: unknown): GatewayEvent | null =>
  value && typeof value === 'object' && !Array.isArray(value) && typeof (value as { type?: unknown }).type === 'string'
    ? (value as GatewayEvent)
    : null

const sidecarFrameForEvent = (ev: GatewayEvent): string | null => {
  if (
    !ev.type ||
    ev.type.length > MAX_SIDECAR_EVENT_TYPE_CHARS ||
    !SIDECAR_ACCEPTED_EVENTS.has(ev.type) ||
    SIDECAR_STREAM_ONLY_EVENTS.has(ev.type)
  ) {
    return null
  }

  try {
    const projected: Record<string, unknown> = { type: ev.type }

    if (typeof ev.session_id === 'string') {
      if (ev.session_id.length > MAX_SIDECAR_SESSION_ID_CHARS) {
        return null
      }

      projected.session_id = ev.session_id
    }

    const payload = compactSidecarPayload(ev.type, ev.payload)

    if (Object.keys(payload).length) {
      projected.payload = payload
    }

    const frame = JSON.stringify({ jsonrpc: '2.0', method: 'event', params: projected })

    return _sidecarEncoder.encode(frame).byteLength <= MAX_SIDECAR_FRAME_BYTES ? frame : null
  } catch (err) {
    if (err instanceof SidecarProjectionTooLarge) {
      return null
    }

    throw err
  }
}

// Hoisted decoder: attach mode can drive high-frequency binary frames
// (tool deltas, reasoning streams) and constructing a fresh TextDecoder
// per message creates avoidable GC pressure. One module-level instance
// is fine because UTF-8 is stateless and we always pass entire frames.
const _wireDecoder = new TextDecoder()

const asWireText = (raw: unknown): string | null => {
  if (typeof raw === 'string') {
    return raw
  }

  if (raw instanceof ArrayBuffer || ArrayBuffer.isView(raw)) {
    return _wireDecoder.decode(raw as any as ArrayBuffer)
  }

  return null
}

// Matches `<scheme>://user:pass@host…` style user-info segments in
// otherwise-malformed URLs that the WHATWG `URL` parser can't accept.
// Used by the `redactUrl` fallback so embedded credentials are
// scrubbed from log lines even when the URL is unparseable.
const _USERINFO_FALLBACK_RE = /^([a-z][a-z0-9+.-]*:\/\/)[^/?#@]*@/i

// Connection URLs (gateway, sidecar) often carry bearer tokens in the query
// string. We surface them in user-facing log lines and the
// `gateway.start_timeout` payload, so always strip the query string and any
// embedded user-info before logging.
const redactUrl = (raw: string): string => {
  if (!raw) {
    return raw
  }

  try {
    const url = new URL(raw)
    const userInfo = url.username || url.password ? '***@' : ''
    const query = url.search ? '?***' : ''

    return `${url.protocol}//${userInfo}${url.host}${url.pathname}${query}`
  } catch {
    // WHATWG URL rejected the input. Best-effort: strip an embedded
    // `user:pass@` segment AND the query string so a malformed token
    // bearer can never escape into the log tail.
    const noUserInfo = raw.replace(_USERINFO_FALLBACK_RE, '$1***@')
    const queryIdx = noUserInfo.indexOf('?')

    return queryIdx >= 0 ? `${noUserInfo.slice(0, queryIdx)}?***` : noUserInfo
  }
}

interface Pending {
  id: string
  method: string
  reject: (e: Error) => void
  resolve: (v: unknown) => void
  timeout: ReturnType<typeof setTimeout>
}

export class GatewayClient extends EventEmitter {
  private proc: ChildProcess | null = null
  private ws: WebSocket | null = null
  private wsConnectPromise: Promise<void> | null = null
  private sidecarWs: WebSocket | null = null
  private sidecarReconnectTimer: ReturnType<typeof setTimeout> | null = null
  private sidecarReconnectAttempt = 0
  private sidecarReconnectCooldownUntil = 0
  private attachUrl: null | string = null
  private sidecarUrl: null | string = null
  private reqId = 0
  private logs = new CircularBuffer<string>(MAX_GATEWAY_LOG_LINES)
  private pending = new Map<string, Pending>()
  private bufferedEvents = new CircularBuffer<GatewayEvent>(MAX_BUFFERED_EVENTS)
  private bufferedSidecarFrames = new CircularBuffer<string>(MAX_BUFFERED_SIDECAR_FRAMES)
  private pendingExit: number | null | undefined
  private ready = false
  private readyTimer: ReturnType<typeof setTimeout> | null = null
  private subscribed = false
  private drainGeneration = 0
  private stdoutRl: ReturnType<typeof createInterface> | null = null
  private stderrRl: ReturnType<typeof createInterface> | null = null
  private runtime: GatewayRuntimeOptions
  private gatewayLaunchContextPath: null | string = null

  constructor(runtime: GatewayRuntimeOptions = { launchContext: { version: 1 } }) {
    super()
    this.runtime = runtime
    // useInput / createGatewayEventHandler can legitimately attach many
    // listeners. Default 10-cap triggers spurious warnings.
    this.setMaxListeners(0)
  }

  private publish(ev: GatewayEvent) {
    if (ev.type === 'gateway.ready') {
      this.ready = true

      if (this.readyTimer) {
        clearTimeout(this.readyTimer)
        this.readyTimer = null
      }
    }

    if (this.subscribed) {
      return void this.emit('event', ev)
    }

    this.bufferedEvents.push(ev)
  }

  private clearReadyTimer() {
    if (this.readyTimer) {
      clearTimeout(this.readyTimer)
      this.readyTimer = null
    }
  }

  private closeSidecarSocket() {
    if (this.sidecarReconnectTimer) {
      clearTimeout(this.sidecarReconnectTimer)
      this.sidecarReconnectTimer = null
    }

    this.sidecarReconnectAttempt = 0
    this.sidecarReconnectCooldownUntil = 0
    this.bufferedSidecarFrames.clear()
    const ws = this.sidecarWs
    this.sidecarWs = null

    try {
      ws?.close()
    } catch {
      // best effort
    }
  }

  private closeGatewaySocket() {
    // Null the active reference BEFORE invoking close(): real WebSocket
    // implementations dispatch the 'close' event after a microtask hop,
    // so by the time the handler runs `this.ws` should already be null
    // and the identity guard will correctly classify the close as
    // belonging to a discarded socket. (Test fakes emit synchronously,
    // so doing the swap up front is also what makes the identity guard
    // match real timing in tests.)
    const ws = this.ws
    this.ws = null
    this.wsConnectPromise = null

    try {
      ws?.close()
    } catch {
      // best effort
    }
  }

  private resetStartupState() {
    // Reject any in-flight RPCs left over from the previous transport
    // before we swap. Otherwise the old transport's stale exit/close
    // handlers (now identity-gated to ignore unrelated transports)
    // never fire `rejectPending`, leaving callers hanging on promises
    // attached to a discarded child / socket.
    this.rejectPending(new Error('gateway restarting'))
    this.ready = false
    this.subscribed = false
    // Invalidate any pending deferred drain() flush from a prior transport so
    // its queued microtask becomes a no-op (it captured the old generation).
    this.drainGeneration += 1
    this.bufferedEvents.clear()
    this.pendingExit = undefined
    this.stdoutRl?.close()
    this.stderrRl?.close()
    this.stdoutRl = null
    this.stderrRl = null
    this.clearReadyTimer()
  }

  private startReadyTimer(python: string, cwd: string) {
    this.readyTimer = setTimeout(() => {
      if (this.ready) {
        return
      }

      // Append the most recent gateway stderr/log lines to the timeout
      // event so users can tell apart "wrong python", "missing dep",
      // and "config parse failure" from one glance instead of having
      // to dig through `/logs`.  Capped to keep the activity feed
      // readable on slow boots.
      const stderrTail = this.getLogTail(20)

      this.lifecycle(`[startup] timed out waiting for gateway.ready (python=${python}, cwd=${cwd})`)
      this.publish({
        type: 'gateway.start_timeout',
        payload: { cwd, python, stderr_tail: stderrTail }
      })
    }, STARTUP_TIMEOUT_MS)
  }

  private handleTransportExit(code: null | number, reason?: string) {
    this.clearReadyTimer()
    this.closeSidecarSocket()
    this.lifecycle(`[lifecycle] transport exit code=${code ?? 'null'} reason=${reason ?? 'none'}`)
    this.rejectPending(new Error(reason || `gateway exited${code === null ? '' : ` (${code})`}`))

    if (this.subscribed) {
      this.emit('exit', code)
    } else {
      this.pendingExit = code
    }
  }

  private connectSidecarMirror() {
    if (!this.sidecarUrl || this.sidecarWs || this.sidecarReconnectTimer) {
      return
    }

    const WebSocketCtor = getWebSocketCtor()

    if (typeof WebSocketCtor === 'undefined') {
      this.pushLog(`[sidecar] WebSocket unavailable; skipping mirror to ${redactUrl(this.sidecarUrl)}`)

      return
    }

    try {
      const ws = new WebSocketCtor(this.sidecarUrl)

      this.sidecarWs = ws
      ws.addEventListener('open', () => {
        if (this.sidecarWs !== ws) {
          return
        }

        this.sidecarReconnectAttempt = 0
        const pending = this.bufferedSidecarFrames.drain()

        for (let index = 0; index < pending.length; index += 1) {
          try {
            ws.send(pending[index]!)
          } catch {
            for (const frame of pending.slice(index)) {
              this.bufferedSidecarFrames.push(frame)
            }

            this.failSidecarSocket(ws)

            break
          }
        }
      })
      ws.addEventListener('close', () => {
        if (this.sidecarWs === ws) {
          this.sidecarWs = null
          this.scheduleSidecarReconnect()
        }
      })
      ws.addEventListener('error', () => {
        if (this.sidecarWs !== ws) {
          return
        }

        this.pushLog('[sidecar] mirror connection error')
        this.failSidecarSocket(ws)
      })
    } catch (err) {
      this.pushLog(`[sidecar] failed to connect ${redactUrl(this.sidecarUrl)} (constructor error)`)
      this.sidecarWs = null
      this.scheduleSidecarReconnect()
    }
  }

  private failSidecarSocket(ws: WebSocket) {
    if (this.sidecarWs !== ws) {
      return
    }

    this.sidecarWs = null

    try {
      ws.close()
    } catch {
      // best effort
    }

    this.scheduleSidecarReconnect()
  }

  private scheduleSidecarReconnect() {
    if (!this.sidecarUrl || this.sidecarReconnectTimer) {
      return
    }

    if (this.sidecarReconnectAttempt >= SIDECAR_MAX_RECONNECT_ATTEMPTS) {
      this.sidecarReconnectCooldownUntil = Date.now() + SIDECAR_RECONNECT_COOLDOWN_MS
      this.pushLog('[sidecar] reconnect attempts exhausted')

      return
    }

    const attempt = ++this.sidecarReconnectAttempt
    const delayMs = Math.min(100 * 2 ** (attempt - 1), 2_000)

    this.sidecarReconnectTimer = setTimeout(() => {
      this.sidecarReconnectTimer = null
      this.connectSidecarMirror()
    }, delayMs)
    this.sidecarReconnectTimer.unref?.()
  }

  private mirrorEventToSidecar(ev: GatewayEvent) {
    const frame = sidecarFrameForEvent(ev)

    if (!frame) {
      return
    }

    const ws = this.sidecarWs

    if (!ws || ws.readyState !== WS_OPEN) {
      this.bufferedSidecarFrames.push(frame)

      // After the bounded burst has failed, remain completely idle during a
      // cooldown. The next semantic event after that cooldown restarts one
      // bounded cycle, avoiding both permanent silence and a background retry
      // loop when the dashboard is absent.
      if (
        !this.sidecarWs &&
        !this.sidecarReconnectTimer &&
        this.sidecarReconnectAttempt >= SIDECAR_MAX_RECONNECT_ATTEMPTS &&
        Date.now() >= this.sidecarReconnectCooldownUntil
      ) {
        this.sidecarReconnectAttempt = 0
        this.sidecarReconnectCooldownUntil = 0
        this.connectSidecarMirror()
      }

      return
    }

    try {
      ws.send(frame)
    } catch {
      this.bufferedSidecarFrames.push(frame)
      this.failSidecarSocket(ws)
    }
  }

  publishLocalEvent(ev: GatewayEvent) {
    this.mirrorEventToSidecar(ev)
    this.publish(ev)
  }

  private handleWebSocketFrame(raw: unknown) {
    const text = asWireText(raw)

    if (!text) {
      return
    }

    try {
      const frame = JSON.parse(text) as Record<string, unknown>

      if (frame.method === 'event') {
        const ev = asGatewayEvent(frame.params)

        if (ev) {
          this.mirrorEventToSidecar(ev)
        }
      }

      this.dispatch(frame)
    } catch {
      const preview = text.trim().slice(0, MAX_LOG_PREVIEW) || '(empty frame)'

      this.pushLog(`[protocol] malformed websocket frame: ${preview}`)
      this.publish({ type: 'gateway.protocol_error', payload: { preview } })
    }
  }

  private startSpawnedGateway(root: string) {
    const python = resolvePython(root, this.runtime.python)
    const cwd = this.runtime.launchContext.cwd?.trim() || root
    const env = { ...process.env }
    const pyPath = env.PYTHONPATH?.trim()

    env.PYTHONPATH = pyPath ? `${root}${delimiter}${pyPath}` : root
    this.startReadyTimer(python, cwd)
    const args = ['-m', 'tui_gateway.entry', '--source-root', root]

    if (this.runtime.packageRevision) {
      args.push('--package-revision', this.runtime.packageRevision)
    }

    this.cleanupGatewayLaunchContext()
    this.gatewayLaunchContextPath = writeTuiLaunchContext(this.runtime.launchContext)
    args.push('--launch-context', this.gatewayLaunchContextPath)

    try {
      this.proc = spawn(python, args, { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] })
    } catch (error) {
      this.cleanupGatewayLaunchContext()
      throw error
    }

    this.lifecycle(`[lifecycle] spawned gateway child ${describeChild(this.proc)} python=${python} cwd=${cwd}`)

    this.stdoutRl = createInterface({ input: this.proc.stdout! })
    this.stdoutRl.on('line', raw => {
      try {
        this.dispatch(JSON.parse(raw))
      } catch {
        const preview = raw.trim().slice(0, MAX_LOG_PREVIEW) || '(empty line)'

        this.pushLog(`[protocol] malformed stdout: ${preview}`)
        this.publish({ type: 'gateway.protocol_error', payload: { preview } })
      }
    })

    this.stderrRl = createInterface({ input: this.proc.stderr! })
    this.stderrRl.on('line', raw => {
      const line = truncateLine(raw.trim())

      if (!line) {
        return
      }

      this.pushLog(line)
      this.publish({ type: 'gateway.stderr', payload: { line } })
    })

    const ownedProc = this.proc
    this.proc.on('error', err => {
      this.cleanupGatewayLaunchContext()

      // Skip stale errors on an already-replaced child.
      if (this.proc !== ownedProc) {
        this.pushLog(`[lifecycle] stale child error ignored ${describeChild(ownedProc)} message=${err.message}`)

        return
      }

      const line = `[spawn] ${err.message}`

      this.lifecycle(`[lifecycle] child error ${describeChild(ownedProc)} message=${err.message}`)
      this.pushLog(line)
      this.publish({ type: 'gateway.stderr', payload: { line } })
      // Detach the reference up front so the late `exit` event for
      // this same child is identity-skipped (we don't want to emit
      // 'exit' twice). Then run the full teardown — clears the
      // startup timer so we don't fire a misleading
      // `gateway.start_timeout`, rejects pending RPCs, and emits or
      // queues a single `exit`.
      this.proc = null
      this.handleTransportExit(1, `gateway error: ${err.message}`)
    })
    this.proc.on('exit', (code, signal) => {
      this.cleanupGatewayLaunchContext()

      // start() can replace `this.proc` while an old child is still
      // tearing down. Skip stale exits so we don't clear the new
      // startup timer or reject newly-issued pending requests.
      if (this.proc !== ownedProc) {
        this.pushLog(
          `[lifecycle] stale child exit ignored ${describeChild(ownedProc)} code=${code ?? 'null'} signal=${signal ?? 'null'}`
        )

        return
      }

      this.lifecycle(
        `[lifecycle] child exit ${describeChild(ownedProc)} code=${code ?? 'null'} signal=${signal ?? 'null'}`
      )
      this.handleTransportExit(code)
    })
  }

  private startAttachedGateway(attachUrl: string) {
    const safeAttachUrl = redactUrl(attachUrl)
    this.startReadyTimer('websocket', safeAttachUrl)

    const WebSocketCtor = getWebSocketCtor()

    if (typeof WebSocketCtor === 'undefined') {
      const line = `[startup] WebSocket API unavailable; cannot attach to ${safeAttachUrl}`

      this.pushLog(line)
      this.publish({ type: 'gateway.stderr', payload: { line } })
      this.handleTransportExit(1, 'gateway websocket unavailable')

      return
    }

    try {
      const ws = new WebSocketCtor(attachUrl)
      let settled = false

      this.ws = ws

      const connectPromise = new Promise<void>((resolve, reject) => {
        ws.addEventListener(
          'open',
          () => {
            if (!settled) {
              settled = true
              resolve()
            }

            this.connectSidecarMirror()
          },
          { once: true }
        )

        ws.addEventListener(
          'error',
          () => {
            if (!settled) {
              this.pushLog('[startup] gateway websocket connect error')
              settled = true
              reject(new Error('gateway websocket connection failed'))
            }
          },
          { once: true }
        )
        ws.addEventListener(
          'close',
          ev => {
            if (!settled) {
              settled = true
              reject(new Error(`gateway websocket closed (${ev.code}) during connect`))
            }
          },
          { once: true }
        )
      })

      // The connect promise is only awaited by RPCs that arrive while
      // the socket is still connecting. If no request races the open
      // (or a teardown drops the reference before anyone observes it),
      // a connect-error / early-close rejection would surface as an
      // unhandled promise rejection in Node. Attach a no-op handler to
      // ensure the rejection is always observed.
      connectPromise.catch(() => {})
      this.wsConnectPromise = connectPromise

      ws.addEventListener('message', ev => this.handleWebSocketFrame(ev.data))
      ws.addEventListener('close', ev => {
        // Skip close events from sockets that have already been
        // replaced — start() / closeGatewaySocket() can swap `this.ws`
        // before an in-flight close lands, and we must not clear the
        // new ready timer or reject the new pending requests on behalf
        // of a stale socket.
        if (this.ws !== ws) {
          this.pushLog(`[lifecycle] stale websocket close ignored code=${ev.code}`)

          return
        }

        this.pushLog(`[lifecycle] websocket close code=${ev.code}`)
        this.ws = null
        this.wsConnectPromise = null
        this.handleTransportExit(ev.code, `gateway websocket closed${ev.code ? ` (${ev.code})` : ''}`)
      })
      ws.addEventListener('error', () => {
        const line = '[gateway] websocket transport error'

        this.pushLog(line)
        this.publish({ type: 'gateway.stderr', payload: { line } })
      })
    } catch (err) {
      this.pushLog(`[startup] failed to connect websocket gateway ${safeAttachUrl} (constructor error)`)
      this.handleTransportExit(1, 'gateway websocket startup failed')
    }
  }

  start() {
    const root = this.runtime.sourceRoot ?? resolve(import.meta.dirname, '../../')
    const attachUrl = resolveGatewayAttachUrl(this.runtime)
    const sidecarUrl = resolveSidecarUrl(this.runtime)

    this.attachUrl = attachUrl
    this.sidecarUrl = sidecarUrl
    this.resetStartupState()

    if (this.proc && !this.proc.killed && this.proc.exitCode === null) {
      this.lifecycle(`[lifecycle] replacing live gateway child ${describeChild(this.proc)}`)
      this.proc.kill()
    }

    this.proc = null
    this.cleanupGatewayLaunchContext()
    this.closeGatewaySocket()
    this.closeSidecarSocket()

    if (attachUrl) {
      this.startAttachedGateway(attachUrl)

      return
    }

    this.startSpawnedGateway(root)
  }

  private dispatch(msg: Record<string, unknown>) {
    const id = msg.id as string | undefined
    const p = id ? this.pending.get(id) : undefined

    if (p) {
      this.settle(p, msg.error ? this.toError(msg.error) : null, msg.result)

      return
    }

    if (msg.method === 'event') {
      const ev = asGatewayEvent(msg.params)

      if (ev) {
        this.publish(ev)
      }
    }
  }

  private cleanupGatewayLaunchContext() {
    const path = this.gatewayLaunchContextPath

    this.gatewayLaunchContextPath = null

    if (!path) {
      return
    }

    try {
      unlinkSync(path)
    } catch {
      // The gateway consumes and removes the descriptor during import.
    }
  }

  private toError(raw: unknown): Error {
    const err = raw as { message?: unknown } | null | undefined

    return new Error(typeof err?.message === 'string' ? err.message : 'request failed')
  }

  private settle(p: Pending, err: Error | null, result: unknown) {
    clearTimeout(p.timeout)
    this.pending.delete(p.id)

    if (err) {
      p.reject(err)
    } else {
      p.resolve(result)
    }
  }

  private pushLog(line: string) {
    this.logs.push(truncateLine(line))
  }

  // Death-explaining breadcrumbs (spawn / exit / kill / replace) — kept in the
  // in-memory tail for /logs AND persisted to the gateway crash log so the
  // reason survives a parent exit and lands next to the child's SIGTERM panic.
  private lifecycle(line: string) {
    this.pushLog(line)
    recordParentLifecycle(line)
  }

  private rejectPending(err: Error) {
    for (const p of this.pending.values()) {
      clearTimeout(p.timeout)
      p.reject(err)
    }

    this.pending.clear()
  }

  // Arrow class-field — stable identity, so `setTimeout(this.onTimeout, …, id)`
  // doesn't allocate a bound function per request.
  private onTimeout = (id: string) => {
    const p = this.pending.get(id)

    if (p) {
      this.pending.delete(id)
      p.reject(new Error(`timeout: ${p.method}`))
    }
  }

  drain() {
    // Defer the buffered-event replay to the next microtask, and DO NOT flip
    // `subscribed` until that microtask runs.
    //
    // `drain()` is called from the consumer's mount-time subscribe effect
    // (ui-tui/src/app/useMainApp.ts). In *attach* mode the gateway is already
    // running, so it replays `gateway.ready` / `session.info` the instant the
    // socket connects — those land in `bufferedEvents` *before* the consumer
    // subscribes. If we emitted them synchronously here, the `gateway.ready`
    // handler's `patchUiState` / `setHistoryItems` cascade would run while
    // React is still inside the first commit, tripping "Too many re-renders"
    // (Minified React error #301) — issue #36658. Spawn/inline/sidecar modes
    // don't hit this because `gateway.ready` only arrives after the Python
    // child boots, i.e. on a later async tick.
    //
    // Crucially, `subscribed` stays false until the flush so any LIVE event
    // arriving in the gap between here and the microtask keeps buffering
    // (publish() pushes when !subscribed) instead of emitting synchronously
    // and jumping ahead of the chronologically-earlier replayed events. The
    // flush re-drains the buffer right after flipping `subscribed`, so any
    // in-window arrivals are delivered in FIFO order. A generation token makes
    // the queued microtask a no-op if the transport was reset/killed meanwhile.
    const generation = this.drainGeneration

    queueMicrotask(() => {
      if (this.drainGeneration !== generation) {
        return
      }

      this.subscribed = true

      // Replay everything buffered up to now, then any events that arrived in
      // the gap before this microtask ran — all in chronological order.
      for (const ev of this.bufferedEvents.drain()) {
        this.emit('event', ev)
      }

      if (this.pendingExit !== undefined) {
        const code = this.pendingExit

        this.pendingExit = undefined
        this.emit('exit', code)
      }
    })
  }

  getLogTail(limit = 20): string {
    return this.logs.tail(Math.max(1, limit)).join('\n')
  }

  private async ensureAttachedWebSocket(method: string): Promise<WebSocket> {
    if (!this.attachUrl) {
      throw new Error('gateway not running')
    }

    if (!this.ws || this.ws.readyState === WS_CLOSED || this.ws.readyState === WS_CLOSING) {
      this.start()
    }

    if (this.ws?.readyState === WS_CONNECTING) {
      try {
        await this.wsConnectPromise
      } catch (err) {
        throw err instanceof Error ? err : new Error(String(err))
      }
    }

    if (!this.ws || this.ws.readyState !== WS_OPEN) {
      throw new Error(`gateway not connected: ${method}`)
    }

    return this.ws
  }

  private requestOverWebSocket<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return this.ensureAttachedWebSocket(method).then(
      ws =>
        new Promise<T>((resolve, reject) => {
          const id = `r${++this.reqId}`
          const timeout = setTimeout(this.onTimeout, REQUEST_TIMEOUT_MS, id)

          timeout.unref?.()
          this.pending.set(id, {
            id,
            method,
            reject,
            resolve: v => resolve(v as T),
            timeout
          })

          try {
            ws.send(JSON.stringify({ id, jsonrpc: '2.0', method, params }))
          } catch (e) {
            const pending = this.pending.get(id)

            if (pending) {
              clearTimeout(pending.timeout)
              this.pending.delete(id)
            }

            reject(e instanceof Error ? e : new Error(String(e)))
          }
        })
    )
  }

  request<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const attachUrl = resolveGatewayAttachUrl(this.runtime)

    if (attachUrl) {
      if (this.attachUrl !== attachUrl) {
        // The launch-context URL rotated at runtime — restart the transport so
        // switching from spawned-gateway mode to attach mode also
        // tears down the old Python child. Merely closing `this.ws`
        // would leave a previously spawned gateway process alive.
        this.rejectPending(new Error('gateway attach url changed'))
        this.start()
      }

      return this.requestOverWebSocket<T>(method, params)
    }

    if (!this.proc?.stdin || this.proc.killed || this.proc.exitCode !== null) {
      this.start()
    }

    if (!this.proc?.stdin) {
      return Promise.reject(new Error('gateway not running'))
    }

    const id = `r${++this.reqId}`

    return new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(this.onTimeout, REQUEST_TIMEOUT_MS, id)

      timeout.unref?.()

      this.pending.set(id, {
        id,
        method,
        reject,
        resolve: v => resolve(v as T),
        timeout
      })

      try {
        this.proc!.stdin!.write(JSON.stringify({ id, jsonrpc: '2.0', method, params }) + '\n')
      } catch (e) {
        const pending = this.pending.get(id)

        if (pending) {
          clearTimeout(pending.timeout)
          this.pending.delete(id)
        }

        reject(e instanceof Error ? e : new Error(String(e)))
      }
    })
  }

  kill(reason = 'requested') {
    const proc = this.proc
    const killed = proc?.kill()

    this.lifecycle(
      `[lifecycle] GatewayClient.kill reason=${reason} ${describeChild(proc)} killResult=${killed ?? 'none'}`
    )
    this.closeGatewaySocket()
    this.closeSidecarSocket()
    this.clearReadyTimer()
    // The ws 'close' handler is identity-gated on `this.ws === ws`
    // and we just nulled `this.ws`, so it will short-circuit and
    // skip handleTransportExit. Reject pending RPCs explicitly so
    // attach-mode promises do not hang after an intentional kill.
    this.rejectPending(new Error('gateway closed'))
  }
}
