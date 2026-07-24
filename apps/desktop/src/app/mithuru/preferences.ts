import { DEFAULT_MITHURU_PREFERENCES, type MithuruPreferences, normalizeMithuruPreferences } from './core/preferences'

const PREFIX = 'fabric.desktop.mithuru.v1'

export interface StoredMithuruProfile {
  onboardingCompleted: boolean
  preferences: MithuruPreferences
}

export function mithuruStorageKey(profile: string): string {
  const normalized = profile.trim() || 'default'

  return `${PREFIX}:${normalized}`
}

export function loadMithuruProfile(
  profile: string,
  storage: Pick<Storage, 'getItem'> = window.localStorage
): StoredMithuruProfile {
  try {
    const raw = storage.getItem(mithuruStorageKey(profile))
    const parsed = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}

    return {
      onboardingCompleted: parsed.onboardingCompleted === true,
      preferences: normalizeMithuruPreferences(parsed.preferences)
    }
  } catch {
    return { onboardingCompleted: false, preferences: { ...DEFAULT_MITHURU_PREFERENCES } }
  }
}

export function saveMithuruProfile(
  profile: string,
  value: StoredMithuruProfile,
  storage: Pick<Storage, 'setItem'> = window.localStorage
): void {
  storage.setItem(
    mithuruStorageKey(profile),
    JSON.stringify({
      onboardingCompleted: value.onboardingCompleted,
      preferences: normalizeMithuruPreferences(value.preferences)
    })
  )
}
