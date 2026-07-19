// Tiny FPS tracker fed by Ink's onFrame callback. Each entry is a real Ink
// frame (React commits and drain-only frames), matching user-perceived motion.
// When disabled, trackFrame is undefined and entry.tsx omits onFrame entirely.

import { atom } from 'nanostores'

import { SHOW_FPS } from '../config/diagnostics.js'

const WINDOW_SIZE = 30

export interface FpsState {
  fps: number
  lastDurationMs: number
  totalFrames: number
}

export const $fpsState = atom<FpsState>({ fps: 0, lastDurationMs: 0, totalFrames: 0 })

const timestamps: number[] = []
let totalFrames = 0

export const trackFrame = SHOW_FPS
  ? (durationMs: number) => {
      timestamps.push(performance.now())

      if (timestamps.length > WINDOW_SIZE) {
        timestamps.shift()
      }

      totalFrames++

      if (timestamps.length < 2) {
        return
      }

      const elapsed = (timestamps[timestamps.length - 1]! - timestamps[0]!) / 1000

      if (elapsed > 0) {
        $fpsState.set({
          fps: Math.round(((timestamps.length - 1) / elapsed) * 10) / 10,
          lastDurationMs: Math.round(durationMs * 100) / 100,
          totalFrames
        })
      }
    }
  : undefined
