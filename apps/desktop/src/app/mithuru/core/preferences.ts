import { type MithuruLocale, normalizeMithuruLocale } from './localization'

export type MithuruExperienceMode = 'standard' | 'simple'
export type MithuruInteractionMode = 'voice' | 'text' | 'both'
export type MithuruTextScale = 'large' | 'extra-large' | 'maximum'

export interface MithuruPreferences {
  experienceMode: MithuruExperienceMode
  preferredLocale: MithuruLocale
  interactionMode: MithuruInteractionMode
  voiceEnabled: boolean
  cloudSpeechAllowed: boolean
  speechRate: number
  textScale: MithuruTextScale
  caregiverModeConfigured: boolean
}

export const DEFAULT_MITHURU_PREFERENCES: Readonly<MithuruPreferences> = {
  experienceMode: 'standard',
  preferredLocale: 'en-LK',
  interactionMode: 'both',
  voiceEnabled: true,
  cloudSpeechAllowed: false,
  speechRate: 0.8,
  textScale: 'large',
  caregiverModeConfigured: false
}

export function normalizeMithuruPreferences(value: unknown): MithuruPreferences {
  const row = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  const experienceMode = row.experienceMode === 'simple' ? 'simple' : 'standard'

  const interactionMode = ['voice', 'text', 'both'].includes(String(row.interactionMode))
    ? (row.interactionMode as MithuruInteractionMode)
    : DEFAULT_MITHURU_PREFERENCES.interactionMode

  const textScale = ['large', 'extra-large', 'maximum'].includes(String(row.textScale))
    ? (row.textScale as MithuruTextScale)
    : DEFAULT_MITHURU_PREFERENCES.textScale

  const requestedRate = typeof row.speechRate === 'number' ? row.speechRate : DEFAULT_MITHURU_PREFERENCES.speechRate

  return {
    experienceMode,
    preferredLocale: normalizeMithuruLocale(typeof row.preferredLocale === 'string' ? row.preferredLocale : 'en-LK'),
    interactionMode,
    voiceEnabled: row.voiceEnabled !== false,
    cloudSpeechAllowed: row.cloudSpeechAllowed === true,
    speechRate: Math.min(1, Math.max(0.5, requestedRate)),
    textScale,
    caregiverModeConfigured: row.caregiverModeConfigured === true
  }
}
