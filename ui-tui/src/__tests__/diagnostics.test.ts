import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

const originalArgv = [...process.argv]
let importId = 0

const loadDiagnostics = async (...args: string[]) => {
  process.argv = [originalArgv[0] ?? 'node', originalArgv[1] ?? 'entry.js', ...args]

  try {
    return await import('../config/diagnostics.js?case=' + importId++)
  } finally {
    process.argv = [...originalArgv]
  }
}

const loadRuntimeDiagnostics = async (...args: string[]) => {
  process.argv = [originalArgv[0] ?? 'node', originalArgv[1] ?? 'entry.js', ...args]
  vi.resetModules()

  try {
    const [fps, perf] = await Promise.all([import('../lib/fpsStore.js'), import('../lib/perfPane.js')])

    return { fps, perf }
  } finally {
    process.argv = [...originalArgv]
  }
}

describe('TUI direct-entry diagnostics', () => {
  it('is inert by default', async () => {
    const diagnostics = await loadDiagnostics()

    expect(diagnostics.HEAPDUMP_ON_START).toBe(false)
    expect(diagnostics.PERF_ENABLED).toBe(false)
    expect(diagnostics.PERF_LOG_PATH).toBe(join(homedir(), '.fabric', 'perf.log'))
    expect(diagnostics.PERF_THRESHOLD_MS).toBe(2)
    expect(diagnostics.SHOW_FPS).toBe(false)
  })

  it('enables profiling and accepts a zero threshold', async () => {
    const diagnostics = await loadDiagnostics('--tui-perf', '--tui-perf-threshold-ms', '0')

    expect(diagnostics.PERF_ENABLED).toBe(true)
    expect(diagnostics.PERF_THRESHOLD_MS).toBe(0)
  })

  it('accepts an inline log path and clamps a negative threshold', async () => {
    const diagnostics = await loadDiagnostics('--tui-perf-log=/tmp/fabric-tui-perf.jsonl', '--tui-perf-threshold-ms=-5')

    expect(diagnostics.PERF_ENABLED).toBe(true)
    expect(diagnostics.PERF_LOG_PATH).toBe('/tmp/fabric-tui-perf.jsonl')
    expect(diagnostics.PERF_THRESHOLD_MS).toBe(0)
  })

  it('does not mistake a following flag for an option value', async () => {
    const diagnostics = await loadDiagnostics('--tui-perf-threshold-ms', '--tui-fps')

    expect(diagnostics.PERF_ENABLED).toBe(false)
    expect(diagnostics.PERF_THRESHOLD_MS).toBe(2)
    expect(diagnostics.SHOW_FPS).toBe(true)
  })

  it('enables the FPS overlay and startup heap dump independently', async () => {
    const diagnostics = await loadDiagnostics('--tui-fps', '--tui-heapdump-on-start')

    expect(diagnostics.HEAPDUMP_ON_START).toBe(true)
    expect(diagnostics.PERF_ENABLED).toBe(false)
    expect(diagnostics.SHOW_FPS).toBe(true)
  })

  it('leaves both frame consumers undefined when diagnostics are disabled', async () => {
    const { fps, perf } = await loadRuntimeDiagnostics()

    expect(fps.trackFrame).toBeUndefined()
    expect(perf.logFrameEvent).toBeUndefined()
    expect(perf.PerfPane({ children: 'content', id: 'transcript' })).toBe('content')
  })

  it('installs the FPS frame consumer only when requested', async () => {
    const { fps, perf } = await loadRuntimeDiagnostics('--tui-fps')

    expect(fps.trackFrame).toBeTypeOf('function')
    expect(perf.logFrameEvent).toBeUndefined()
  })

  it('writes frame samples to the requested log', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'fabric-tui-perf-'))
    const logPath = join(directory, 'frames.jsonl')

    try {
      const { perf } = await loadRuntimeDiagnostics(
        '--tui-perf',
        '--tui-perf-log',
        logPath,
        '--tui-perf-threshold-ms',
        '0'
      )

      expect(perf.logFrameEvent).toBeTypeOf('function')
      perf.logFrameEvent?.({ durationMs: 1.234, flickers: [] })

      const row = JSON.parse((await readFile(logPath, 'utf8')).trim())

      expect(row).toMatchObject({ durationMs: 1.23, src: 'frame' })
    } finally {
      await rm(directory, { force: true, recursive: true })
    }
  })
})
