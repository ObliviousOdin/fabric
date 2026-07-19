import { afterEach, describe, expect, it } from 'vitest'

import { $approvalSoundEnabled, setApprovalSoundEnabled } from '@/store/approval-sound'
import { $hapticsMuted, setHapticsMuted } from '@/store/haptics'

import { shouldPlayApprovalSound } from './approval-sound'

// Covers the "muted" and "disabled" cases required by issue #50's acceptance
// criteria. The audio itself is a no-op under jsdom (no AudioContext), so the
// meaningful, observable behavior is the preference gate.
describe('shouldPlayApprovalSound', () => {
  afterEach(() => {
    setApprovalSoundEnabled(true)
    setHapticsMuted(false)
  })

  it('plays when enabled and not globally muted', () => {
    setApprovalSoundEnabled(true)
    setHapticsMuted(false)
    expect(shouldPlayApprovalSound()).toBe(true)
  })

  it('is suppressed when the approval sound preference is disabled', () => {
    setApprovalSoundEnabled(false)
    setHapticsMuted(false)
    expect(shouldPlayApprovalSound()).toBe(false)
  })

  it('is suppressed by the global mute even when the preference is enabled', () => {
    setApprovalSoundEnabled(true)
    setHapticsMuted(true)
    expect(shouldPlayApprovalSound()).toBe(false)
  })

  it('reflects live changes to either control', () => {
    setApprovalSoundEnabled(true)
    setHapticsMuted(false)
    expect(shouldPlayApprovalSound()).toBe(true)

    $hapticsMuted.set(true)
    expect(shouldPlayApprovalSound()).toBe(false)

    $hapticsMuted.set(false)
    $approvalSoundEnabled.set(false)
    expect(shouldPlayApprovalSound()).toBe(false)
  })
})
