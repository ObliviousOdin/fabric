function parseReadyPort(line) {
  try {
    const record = JSON.parse(String(line))
    const port = record?.port

    return record?.type === 'backend.ready' &&
      typeof port === 'number' &&
      Number.isInteger(port) &&
      port > 0 &&
      port <= 65_535
      ? port
      : null
  } catch {
    return null
  }
}

// The announcement clock starts the instant the backend process is spawned —
// before uvicorn binds its socket. On a cold install the child must first
// compile and import the whole `fabric_cli.main` → `web_server` → FastAPI/
// uvicorn chain, and on Windows real-time AV (Defender) scans every freshly
// written `.pyc`. That pre-bind cost can run 30-60s on a slow disk, so a tight
// 45s deadline kills a *healthy but still-starting* backend and respawns it,
// piling up orphaned processes (issue #50209). A roomier default absorbs the
// cold-start cost; a warm start still announces in well under a second.
const DEFAULT_PORT_ANNOUNCE_TIMEOUT_MS = 90_000

function backendProcessUnavailable(child) {
  if (!child?.stdout || typeof child.on !== 'function' || typeof child.stdout.on !== 'function') {
    return new Error('Fabric backend process is unavailable before port announcement')
  }

  if (child.exitCode !== null && child.exitCode !== undefined) {
    return new Error(`Fabric backend: exited before port announcement (${child.signalCode || child.exitCode})`)
  }

  return null
}

function resolvePortAnnounceTimeoutMs() {
  return DEFAULT_PORT_ANNOUNCE_TIMEOUT_MS
}

/**
 * Watch a child process's stdout for the structured ``backend.ready`` JSON
 * record that web_server.py prints after uvicorn binds its socket.
 *
 * Returns the parsed port. Rejects if:
 *   - the child exits before emitting the line
 *   - the child emits an `error` event
 *   - no line arrives within the timeout
 *
 * The default timeout is cold-start tolerant (see
 * DEFAULT_PORT_ANNOUNCE_TIMEOUT_MS) because the clock starts before the
 * backend has even bound its port. Pass an explicit `timeoutMs` to override.
 *
 * A single `cleanup()` tears down every listener (data/exit/error/timeout)
 * on every terminal path — resolve, reject, or timeout — so repeated
 * backend spawns don't leak listener slots on the child.
 */
function waitForDashboardPort(child, timeoutMs = resolvePortAnnounceTimeoutMs()) {
  const unavailable = backendProcessUnavailable(child)

  if (unavailable) {
    return Promise.reject(unavailable)
  }

  return new Promise((resolve, reject) => {
    let buf = ''
    let done = false

    function cleanup() {
      if (done) {
        return
      }

      done = true
      clearTimeout(timer)
      child.stdout.off('data', onData)
      child.off('exit', onExit)
      child.off('error', onError)
    }

    function onData(chunk) {
      buf += chunk.toString()
      let nl

      while ((nl = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, nl)
        buf = buf.slice(nl + 1)
        const port = parseReadyPort(line)

        if (port) {
          cleanup()
          resolve(port)

          return
        }
      }
    }

    function onExit(code, signal) {
      cleanup()
      reject(new Error(`Fabric backend: exited before port announcement (${signal || code})`))
    }

    function onError(err) {
      cleanup()
      reject(err)
    }

    const timer = setTimeout(() => {
      cleanup()
      reject(new Error(`Timed out waiting for Fabric backend port announcement (${timeoutMs}ms)`))
    }, timeoutMs)

    child.stdout.on('data', onData)
    child.on('exit', onExit)
    child.on('error', onError)
  })
}

function waitForDashboardPortAnnouncement(child, options: { timeoutMs?: number } = {}) {
  const timeoutMs = options.timeoutMs ?? resolvePortAnnounceTimeoutMs()

  return waitForDashboardPort(child, timeoutMs)
}

export {
  DEFAULT_PORT_ANNOUNCE_TIMEOUT_MS,
  parseReadyPort,
  resolvePortAnnounceTimeoutMs,
  waitForDashboardPort,
  waitForDashboardPortAnnouncement
}
