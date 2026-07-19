/**
 * Tests for electron/backend-ready.ts.
 *
 * Run with: node --test electron/backend-ready.test.ts
 * (Wired into npm test:desktop:platforms in package.json.)
 *
 * Covers the cold-start port-announcement deadline (issue #50209): the clock
 * starts before the backend binds its port, so a tight 45s deadline killed a
 * healthy-but-still-compiling backend on cold Windows installs. The default is
 * now cold-start tolerant.
 */

import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'

import {
  DEFAULT_PORT_ANNOUNCE_TIMEOUT_MS,
  parseReadyPort,
  resolvePortAnnounceTimeoutMs,
  waitForDashboardPort,
  waitForDashboardPortAnnouncement
} from './backend-ready'

type FakeChildProcess = EventEmitter & {
  exitCode: number | null
  signalCode: NodeJS.Signals | null
  stdout: EventEmitter
}

// A minimal stand-in for a spawned child process: an EventEmitter with a
// stdout EventEmitter, matching the surface waitForDashboardPort consumes
// (child.stdout.on('data'), child.on('exit'|'error') + the .off() teardown).
function makeFakeChild(): FakeChildProcess {
  const child = new EventEmitter() as FakeChildProcess
  child.exitCode = null
  child.signalCode = null
  child.stdout = new EventEmitter()

  return child
}

// ---------------------------------------------------------------------------
// resolvePortAnnounceTimeoutMs
// ---------------------------------------------------------------------------

test('uses the cold-start-tolerant deadline', () => {
  assert.equal(resolvePortAnnounceTimeoutMs(), DEFAULT_PORT_ANNOUNCE_TIMEOUT_MS)
})

// ---------------------------------------------------------------------------
// waitForDashboardPort
// ---------------------------------------------------------------------------

test('resolves with the announced port', async () => {
  const child = makeFakeChild()
  const p = waitForDashboardPort(child, 1000)
  child.stdout.emit('data', 'noise before\n{"type":"backend.ready","port":54321}\n')
  assert.equal(await p, 54321)
})

test('ready-line parser rejects malformed or unrelated records', () => {
  assert.equal(parseReadyPort('{"type":"backend.ready","port":"nope"}'), null)
  assert.equal(parseReadyPort('{"type":"other.ready","port":43210}'), null)
  assert.equal(parseReadyPort('Fabric Web UI → http://127.0.0.1:43210'), null)
})

test('rejects descriptively when the backend process is unavailable', async () => {
  await assert.rejects(waitForDashboardPort(null, 1000), /process is unavailable/)
})

test('rejects immediately when the backend exited before listeners attached', async () => {
  const child = makeFakeChild()
  child.exitCode = 1

  await assert.rejects(waitForDashboardPort(child, 1000), /exited before port announcement \(1\)/)
})

test('parses the port even when the line arrives split across chunks', async () => {
  const child = makeFakeChild()
  const p = waitForDashboardPort(child, 1000)
  child.stdout.emit('data', '{"type":"backend.re')
  child.stdout.emit('data', 'ady","port":8080}\n')
  assert.equal(await p, 8080)
})

test('rejects when the child exits before announcing', async () => {
  const child = makeFakeChild()
  const p = waitForDashboardPort(child, 1000)
  child.emit('exit', 1, null)
  await assert.rejects(p, /exited before port announcement/)
})

test('rejects on a child error event', async () => {
  const child = makeFakeChild()
  const p = waitForDashboardPort(child, 1000)
  child.emit('error', new Error('spawn ENOENT'))
  await assert.rejects(p, /spawn ENOENT/)
})

test('rejects with the timeout message after the deadline', async () => {
  const child = makeFakeChild()
  await assert.rejects(
    waitForDashboardPort(child, 20),
    /Timed out waiting for Fabric backend port announcement \(20ms\)/
  )
})

test('a late announcement after timeout does not throw (listeners torn down)', async () => {
  const child = makeFakeChild()
  await assert.rejects(waitForDashboardPort(child, 20), /Timed out/)
  // The orphaned backend may still print its readiness record later; the watcher
  // must have detached so this emit is a no-op rather than a double-settle.
  assert.doesNotThrow(() => {
    child.stdout.emit('data', '{"type":"backend.ready","port":9999}\n')
  })
})

test('waitForDashboardPortAnnouncement accepts an explicit timeout', async () => {
  const child = makeFakeChild()
  const p = waitForDashboardPortAnnouncement(child, { timeoutMs: 1000 })
  child.stdout.emit('data', '{"type":"backend.ready","port":9876}\n')
  assert.equal(await p, 9876)
})
