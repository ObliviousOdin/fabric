import type { MouseTrackingMode } from '@fabric/ink'

import { isTermuxTuiMode } from '../lib/termux.js'

import { TUI_LAUNCH_CONTEXT } from './runtime.js'

export interface TuiDisplayMode {
  dashboardTuiMode: boolean
  inlineMode: boolean
  mouseTracking: MouseTrackingMode
  termuxTuiMode: boolean
}

export const resolveTuiDisplayMode = (
  dashboardTuiMode = TUI_LAUNCH_CONTEXT.dashboard === true,
  env: NodeJS.ProcessEnv = process.env,
  termuxTuiMode = isTermuxTuiMode(env)
): TuiDisplayMode => {
  return {
    dashboardTuiMode,
    inlineMode: termuxTuiMode || dashboardTuiMode,
    mouseTracking: termuxTuiMode || dashboardTuiMode ? 'off' : 'all',
    termuxTuiMode
  }
}

const DISPLAY_MODE = resolveTuiDisplayMode()
export const TERMUX_TUI_MODE = DISPLAY_MODE.termuxTuiMode

export const STARTUP_RESUME_ID = (TUI_LAUNCH_CONTEXT.resume ?? '').trim()
export const STARTUP_QUERY = (TUI_LAUNCH_CONTEXT.query ?? '').trim()
export const STARTUP_IMAGE = (TUI_LAUNCH_CONTEXT.image ?? '').trim()

// Set by the dashboard PTY launcher. Dashboard mode is the single contract for
// browser-safe primary-buffer rendering, native scrollback, and no mouse
// capture; it also disables idle-exit paths elsewhere in the TUI.
export const DASHBOARD_TUI_MODE = DISPLAY_MODE.dashboardTuiMode

// Config owns the final mouse-tracking mode. The boot default stays off in
// dashboard and Termux modes so browser/touch selection is not intercepted
// before config arrives.
export const MOUSE_TRACKING: MouseTrackingMode = DISPLAY_MODE.mouseTracking

// Skip AlternateScreen — TUI renders into the primary buffer so the host
// terminal's native scrollback captures whatever scrolls off the top.
//
// Dashboard PTYs and Termux both stay in the primary buffer so host-native
// scrollback, review, and copy/paste remain reliable.
export const INLINE_MODE = DISPLAY_MODE.inlineMode
