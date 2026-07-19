// Opt-in instrumentation for the full TUI render pipeline. PerfPane records
// React commit time per pane; logFrameEvent records Ink phase timings and
// scroll fast-path counters. With direct-entry diagnostics disabled, children
// pass through and entry.tsx does not install an onFrame callback.

import { appendFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

import type { FrameEvent } from '@fabric/ink'
import { scrollFastPathStats } from '@fabric/ink'
import { Profiler, type ProfilerOnRenderCallback, type ReactNode } from 'react'

import { PERF_ENABLED, PERF_LOG_PATH, PERF_THRESHOLD_MS } from '../config/diagnostics.js'

let logReady = false

const writeRow = (row: Record<string, unknown>) => {
  if (!logReady) {
    logReady = true

    try {
      mkdirSync(dirname(PERF_LOG_PATH), { recursive: true })
    } catch {
      // Best effort: instrumentation must never crash the TUI.
    }
  }

  try {
    appendFileSync(PERF_LOG_PATH, `${JSON.stringify(row)}\n`)
  } catch {
    // Best effort: a read-only or full diagnostics directory is non-fatal.
  }
}

const round2 = (value: number) => Math.round(value * 100) / 100

const onRender: ProfilerOnRenderCallback = (id, phase, actualMs, baseMs, startTime, commitTime) => {
  if (actualMs < PERF_THRESHOLD_MS) {
    return
  }

  writeRow({
    actualMs: round2(actualMs),
    baseMs: round2(baseMs),
    commitTimeMs: round2(commitTime),
    id,
    phase,
    src: 'react',
    startTimeMs: round2(startTime),
    ts: Date.now()
  })
}

export function PerfPane({ children, id }: { children: ReactNode; id: string }) {
  if (!PERF_ENABLED) {
    return children
  }

  return (
    <Profiler id={id} onRender={onRender}>
      {children}
    </Profiler>
  )
}

export const logFrameEvent = PERF_ENABLED
  ? (event: FrameEvent) => {
      if (event.durationMs < PERF_THRESHOLD_MS) {
        return
      }

      writeRow({
        durationMs: round2(event.durationMs),
        fastPath: { ...scrollFastPathStats, declined: { ...scrollFastPathStats.declined } },
        flickers: event.flickers.length ? event.flickers : undefined,
        phases: event.phases
          ? {
              ...event.phases,
              commit: round2(event.phases.commit),
              diff: round2(event.phases.diff),
              optimize: round2(event.phases.optimize),
              prevFrameDrainMs: round2(event.phases.prevFrameDrainMs),
              renderer: round2(event.phases.renderer),
              write: round2(event.phases.write),
              yoga: round2(event.phases.yoga)
            }
          : undefined,
        src: 'frame',
        ts: Date.now()
      })
    }
  : undefined
