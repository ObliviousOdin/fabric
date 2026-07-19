import { describe, expect, it } from 'vitest'

import { resolveTuiDisplayMode } from '../config/env.js'

describe('resolveTuiDisplayMode', () => {
  it('uses the dashboard marker as the complete embedded-PTY contract', () => {
    expect(resolveTuiDisplayMode(true, {}, false)).toEqual({
      dashboardTuiMode: true,
      inlineMode: true,
      mouseTracking: 'off',
      termuxTuiMode: false
    })
  })

  it('keeps regular terminals in alternate-screen mouse mode', () => {
    expect(resolveTuiDisplayMode(false, {}, false)).toEqual({
      dashboardTuiMode: false,
      inlineMode: false,
      mouseTracking: 'all',
      termuxTuiMode: false
    })
  })

  it('preserves the Termux primary-buffer behavior', () => {
    expect(resolveTuiDisplayMode(false, {}, true)).toEqual({
      dashboardTuiMode: false,
      inlineMode: true,
      mouseTracking: 'off',
      termuxTuiMode: true
    })
  })
})
