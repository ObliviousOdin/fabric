import { afterEach, describe, expect, it } from 'vitest'

import { readKey } from '@/lib/storage'

import { $approvalSoundEnabled, setApprovalSoundEnabled } from './approval-sound'

const STORAGE_KEY = 'fabric.desktop.approvalSoundEnabled'

describe('approval-sound store', () => {
  afterEach(() => {
    setApprovalSoundEnabled(true)
  })

  it('defaults to enabled', () => {
    expect($approvalSoundEnabled.get()).toBe(true)
  })

  it('persists the preference across the storage choke point', () => {
    setApprovalSoundEnabled(false)
    expect($approvalSoundEnabled.get()).toBe(false)
    expect(readKey(STORAGE_KEY)).toBe('false')

    setApprovalSoundEnabled(true)
    expect($approvalSoundEnabled.get()).toBe(true)
    expect(readKey(STORAGE_KEY)).toBe('true')
  })
})
