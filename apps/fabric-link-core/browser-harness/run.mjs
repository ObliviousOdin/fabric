import { createServer } from 'node:http'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'

const harnessDir = fileURLToPath(new URL('.', import.meta.url))
const crateDir = fileURLToPath(new URL('..', import.meta.url))
const repoDir = fileURLToPath(new URL('../../..', import.meta.url))
const chromeStartupTimeoutMs = 30_000
const harnessTimeoutMs = 60_000
const allowedFiles = new Map([
  ['/', join(harnessDir, 'index.html')],
  ['/index.html', join(harnessDir, 'index.html')],
  ['/harness.js', join(harnessDir, 'harness.js')],
  ['/wasm/fabric_link_core.js', join(crateDir, 'target', 'browser', 'fabric_link_core.js')],
  [
    '/wasm/fabric_link_core_bg.wasm',
    join(crateDir, 'target', 'browser', 'fabric_link_core_bg.wasm'),
  ],
  [
    '/fixtures/v3-interoperability.json',
    join(repoDir, 'fabric_link', 'fixtures', 'v3-interoperability.json'),
  ],
])
const contentTypes = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.wasm', 'application/wasm'],
])
const csp = [
  "default-src 'none'",
  "script-src 'self' 'wasm-unsafe-eval'",
  "connect-src 'self'",
  "img-src 'none'",
  "style-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join('; ')

function chromeCandidates() {
  if (process.platform === 'darwin') {
    return [
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
    ]
  }
  if (process.platform === 'win32') {
    const roots = [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)']].filter(Boolean)
    return roots.map(root => join(root, 'Google', 'Chrome', 'Application', 'chrome.exe'))
  }
  return ['google-chrome', 'chromium', 'chromium-browser']
}

async function runChrome(binary, url, profileDir) {
  const child = spawn(
    binary,
    [
      '--headless=new',
      '--disable-gpu',
      '--disable-background-networking',
      '--disable-component-update',
      '--disable-default-apps',
      '--disable-extensions',
      '--disable-sync',
      '--metrics-recording-only',
      '--no-first-run',
      '--no-default-browser-check',
      '--remote-debugging-port=0',
      `--user-data-dir=${profileDir}`,
      'about:blank',
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  )
  let stderr = ''
  child.stderr.setEncoding('utf8')
  child.stderr.on('data', chunk => {
    stderr += chunk
  })
  await new Promise((resolve, reject) => {
    child.once('spawn', resolve)
    child.once('error', reject)
  })

  try {
    const startupDeadline = Date.now() + chromeStartupTimeoutMs
    let devToolsPort
    while (Date.now() < startupDeadline) {
      try {
        const activePort = await readFile(join(profileDir, 'DevToolsActivePort'), 'utf8')
        devToolsPort = Number(activePort.split(/\r?\n/, 1)[0])
        if (Number.isInteger(devToolsPort) && devToolsPort > 0) break
      } catch (error) {
        if (error?.code !== 'ENOENT') throw error
      }
      await delay(25)
    }
    if (!devToolsPort) throw new Error(`Chrome DevTools did not start: ${stderr}`)

    const targetResponse = await fetch(
      `http://127.0.0.1:${devToolsPort}/json/new?${encodeURIComponent(url)}`,
      { method: 'PUT' },
    )
    if (!targetResponse.ok) {
      throw new Error(`could not create browser target: ${targetResponse.status}`)
    }
    const target = await targetResponse.json()
    const socket = new WebSocket(target.webSocketDebuggerUrl)
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true })
      socket.addEventListener('error', reject, { once: true })
    })

    let commandId = 0
    const pending = new Map()
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data)
      if (!message.id || !pending.has(message.id)) return
      const { resolve, reject } = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) reject(new Error(JSON.stringify(message.error)))
      else resolve(message.result)
    })
    const command = (method, params = {}) =>
      new Promise((resolve, reject) => {
        const id = ++commandId
        pending.set(id, { reject, resolve })
        socket.send(JSON.stringify({ id, method, params }))
      })

    await command('Runtime.enable')
    const harnessDeadline = Date.now() + harnessTimeoutMs
    let result = {
      href: 'unknown',
      readyState: 'unknown',
      status: 'loading',
      text: 'missing result',
    }
    while (Date.now() < harnessDeadline) {
      const evaluation = await command('Runtime.evaluate', {
        expression: `(() => {
          const output = document.querySelector('#result')
          return {
            href: window.location.href,
            readyState: document.readyState,
            status: output?.dataset.status || 'loading',
            text: output?.textContent || 'missing result',
          }
        })()`,
        returnByValue: true,
      })
      result = evaluation.result.value
      if (result.status === 'passed' || result.status === 'failed') break
      await delay(25)
    }
    socket.close()
    if (result.status !== 'passed') {
      throw new Error(
        `browser harness ${result.status} at ${result.href} ` +
          `(${result.readyState}): ${result.text}`,
      )
    }
    return result.text
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      const closed = new Promise(resolve => child.once('close', resolve))
      if (child.kill('SIGKILL')) await closed
    }
  }
}

const server = createServer(async (request, response) => {
  if (request.url === '/clear') {
    response.writeHead(200, {
      'cache-control': 'no-store',
      'clear-site-data': '"storage"',
      'content-security-policy': csp,
      'content-type': 'text/plain; charset=utf-8',
      'cross-origin-opener-policy': 'same-origin',
      'referrer-policy': 'no-referrer',
      'x-content-type-options': 'nosniff',
    })
    response.end('cleared')
    return
  }
  const path = allowedFiles.get(request.url || '')
  if (!path) {
    response.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' })
    response.end('not found')
    return
  }
  try {
    const body = await readFile(path)
    response.writeHead(200, {
      'cache-control': 'no-store',
      'content-security-policy': csp,
      'content-type': contentTypes.get(extname(path)),
      'cross-origin-opener-policy': 'same-origin',
      'referrer-policy': 'no-referrer',
      'x-content-type-options': 'nosniff',
    })
    response.end(body)
  } catch (error) {
    response.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' })
    response.end(String(error))
  }
})

const profileDir = await mkdtemp(join(tmpdir(), 'fabric-link-browser-'))
try {
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  const url = `http://127.0.0.1:${address.port}/`
  let lastError
  let result
  for (const candidate of chromeCandidates()) {
    try {
      result = await runChrome(candidate, url, profileDir)
      break
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
      lastError = error
    }
  }
  if (!result) throw lastError || new Error('Chrome or Chromium was not found')
  console.log(result)
} finally {
  await new Promise(resolve => server.close(resolve))
  await rm(profileDir, {
    recursive: true,
    force: true,
    maxRetries: 5,
    retryDelay: 100,
  })
}
