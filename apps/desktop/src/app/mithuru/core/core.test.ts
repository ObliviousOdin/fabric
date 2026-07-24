import { describe, expect, it } from 'vitest'

import {
  formatMithuruDateTime,
  missingMithuruTranslationKeys,
  MITHURU_LOCALES,
  mithuruTranslate,
  normalizeMithuruLocale,
  pseudolocalizeMithuru
} from './localization'
import { normalizeMithuruPreferences } from './preferences'

describe('Mithuru localization', () => {
  it('has every key for every supported locale', () => {
    for (const locale of MITHURU_LOCALES) {
      expect(missingMithuruTranslationKeys(locale)).toEqual([])
    }
  })

  it('normalizes regional locales and interpolates variables', () => {
    expect(normalizeMithuruLocale('si_LK')).toBe('si-LK')
    expect(normalizeMithuruLocale('ta-IN')).toBe('ta-LK')
    expect(mithuruTranslate('en-LK', 'confirm.send', { recipient: 'Nimal' })).toContain('Nimal')
  })

  it('formats date and time using the selected locale and device timezone', () => {
    expect(formatMithuruDateTime(new Date('2026-07-24T12:30:00Z'), 'en-LK', 'Asia/Colombo')).toContain('6:00')
  })

  it('provides a bounded pseudolocalization layout stress transform', () => {
    expect(pseudolocalizeMithuru('Talk')).toMatch(/^［.*···］$/u)
  })
})

describe('Mithuru preferences', () => {
  it('normalizes locale and clamps speech rate', () => {
    expect(
      normalizeMithuruPreferences({ preferredLocale: 'si', speechRate: 4, experienceMode: 'simple' })
    ).toMatchObject({ preferredLocale: 'si-LK', speechRate: 1, experienceMode: 'simple' })
  })

  it('does not silently enable online speech', () => {
    expect(normalizeMithuruPreferences({}).cloudSpeechAllowed).toBe(false)
  })

  it('clears stale voice consent in text-only mode', () => {
    expect(
      normalizeMithuruPreferences({
        interactionMode: 'text',
        voiceEnabled: true,
        cloudSpeechAllowed: true
      })
    ).toMatchObject({ voiceEnabled: false, cloudSpeechAllowed: false })
  })
})
