import { describe, expect, it } from 'vitest'

import { loadMithuruProfile, mithuruStorageKey, saveMithuruProfile } from './preferences'

function memoryStorage(): Pick<Storage, 'getItem' | 'setItem'> {
  const values = new Map<string, string>()

  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => void values.set(key, value)
  }
}

describe('Mithuru profile preferences', () => {
  it('namespaces choices by Fabric profile', () => {
    expect(mithuruStorageKey('parent')).not.toBe(mithuruStorageKey('default'))
  })

  it('round trips onboarding and clamps unsafe preference values', () => {
    const storage = memoryStorage()
    saveMithuruProfile(
      'parent',
      {
        onboardingCompleted: true,
        preferences: {
          experienceMode: 'simple',
          preferredLocale: 'ta-LK',
          interactionMode: 'both',
          voiceEnabled: true,
          cloudSpeechAllowed: false,
          speechRate: 9,
          textScale: 'maximum',
          caregiverModeConfigured: true
        }
      },
      storage
    )

    expect(loadMithuruProfile('parent', storage)).toMatchObject({
      onboardingCompleted: true,
      preferences: { preferredLocale: 'ta-LK', speechRate: 1, textScale: 'maximum' }
    })
    expect(loadMithuruProfile('other', storage).onboardingCompleted).toBe(false)
  })

  it('recovers from malformed storage without exposing a technical error', () => {
    const storage = { getItem: () => '{bad json', setItem: () => undefined }
    expect(loadMithuruProfile('default', storage)).toMatchObject({
      onboardingCompleted: false,
      preferences: { preferredLocale: 'en-LK' }
    })
  })
})
