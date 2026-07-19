// Live frame-rate overlay for direct-entry diagnostics. The caller also gates
// the surrounding layout so this component costs no row when disabled.

import { Text } from '@fabric/ink'
import { useStore } from '@nanostores/react'

import { SHOW_FPS } from '../config/diagnostics.js'
import { $fpsState } from '../lib/fpsStore.js'
import type { Theme } from '../theme.js'

const fpsColor = (fps: number, theme: Theme) =>
  fps >= 50 ? theme.color.statusGood : fps >= 30 ? theme.color.statusWarn : theme.color.error

export function FpsOverlay({ theme }: { theme: Theme }) {
  if (!SHOW_FPS) {
    return null
  }

  return <FpsOverlayInner theme={theme} />
}

function FpsOverlayInner({ theme }: { theme: Theme }) {
  const { fps, lastDurationMs, totalFrames } = useStore($fpsState)

  return (
    <Text color={fpsColor(fps, theme)}>
      {fps.toFixed(1).padStart(5)}fps · {lastDurationMs.toFixed(1).padStart(5)}ms · #{totalFrames}
    </Text>
  )
}
