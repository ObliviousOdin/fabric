import { mkdtempSync, readdirSync, rmSync, statSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { performHeapDump } from './memory.js'

describe('performHeapDump', () => {
  let dir: string

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'fabric-heapdump-test-'))
  })

  afterEach(() => {
    rmSync(dir, { force: true, recursive: true })
  })

  it('writes diagnostics only for automatic high-memory triggers', async () => {
    const result = await performHeapDump('auto-high', { directory: dir })

    expect(result.success).toBe(true)
    expect(result.diagPath).toBeDefined()
    expect(result.heapPath).toBeUndefined()

    const files = readdirSync(dir)
    expect(files.some(f => f.endsWith('.diagnostics.json'))).toBe(true)
    expect(files.some(f => f.endsWith('.heapsnapshot'))).toBe(false)
  })

  it('writes diagnostics only for automatic critical-memory triggers', async () => {
    const result = await performHeapDump('auto-critical', { directory: dir })

    expect(result.success).toBe(true)
    expect(result.diagPath).toBeDefined()
    expect(result.heapPath).toBeUndefined()
    expect(readdirSync(dir).some(f => f.endsWith('.heapsnapshot'))).toBe(false)
  })

  it('writes diagnostics and a snapshot for an explicit manual trigger', async () => {
    const result = await performHeapDump('manual', { directory: dir })

    expect(result.success).toBe(true)
    expect(result.diagPath).toBeDefined()
    expect(result.heapPath).toBeDefined()

    const files = readdirSync(dir)
    expect(files.some(f => f.endsWith('.heapsnapshot'))).toBe(true)
  })
})

describe('heapdump retention guard', () => {
  let dir: string

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'fabric-heapdump-prune-'))
  })

  afterEach(() => {
    rmSync(dir, { force: true, recursive: true })
  })

  it('evicts oldest files when total bytes exceed the cap, retaining the newest', async () => {
    const blob = 'x'.repeat(1024)
    const now = Date.now()

    for (let i = 0; i < 4; i++) {
      const path = join(dir, `old-${i}.heapsnapshot`)
      writeFileSync(path, blob)
      const timestamp = (now - (4 - i) * 60_000) / 1000
      utimesSync(path, timestamp, timestamp)
    }

    const result = await performHeapDump('auto-high', {
      directory: dir,
      maxBytes: 2 * 1024
    })
    expect(result.success).toBe(true)

    const remaining = readdirSync(dir)
    const totalBytes = remaining.reduce((acc, file) => acc + statSync(join(dir, file)).size, 0)
    expect(totalBytes <= 2 * 1024 || remaining.length === 1).toBe(true)
    expect(remaining.length).toBeLessThan(5)
    expect(remaining.some(file => file.endsWith('.diagnostics.json'))).toBe(true)
  })
})
