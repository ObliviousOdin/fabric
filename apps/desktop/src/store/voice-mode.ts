import { atom } from 'nanostores'

import { $newChatProfile, ensureGatewayProfile, normalizeProfileKey, requestFreshSession } from './profile'

export type VoiceModePresentation = 'chat' | 'pip'

export interface VoiceModePreferences {
  attitude: string
  presentation: VoiceModePresentation
  voiceRef: string
}

export interface VoiceModeAttitudeOption {
  id: string
  label: string
}

export interface PendingVoiceModeSession extends VoiceModePreferences {
  profile: string
}

const DEFAULT_PREFERENCES: VoiceModePreferences = {
  attitude: 'profile_default',
  presentation: 'chat',
  voiceRef: 'profile_default'
}

export const $pendingVoiceModeSession = atom<PendingVoiceModeSession | null>(null)

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  return value as Record<string, unknown>
}

function nonEmptyString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

/** Read only profile-safe, non-secret preferences from a complete config record. */
export function voiceModePreferencesFromConfig(config: unknown): VoiceModePreferences {
  const voice = asRecord(asRecord(config)?.voice)
  const experience = asRecord(voice?.experience)
  const presentation = experience?.presentation === 'pip' ? 'pip' : 'chat'

  return {
    attitude: nonEmptyString(experience?.attitude, DEFAULT_PREFERENCES.attitude),
    presentation,
    voiceRef: nonEmptyString(experience?.voice_ref, DEFAULT_PREFERENCES.voiceRef)
  }
}

/**
 * Returns names only. Personality prompt text is intentionally never projected
 * into the launcher, even though the underlying profile config contains it.
 */
export function voiceModeAttitudesFromConfig(config: unknown): VoiceModeAttitudeOption[] {
  const personalities = asRecord(asRecord(asRecord(config)?.agent)?.personalities)
  const names = Object.keys(personalities ?? {}).sort((a, b) => a.localeCompare(b))

  return [{ id: 'profile_default', label: 'Profile default' }, ...names.map(name => ({ id: name, label: name }))]
}

/** Preserve provider setup and credentials while updating the profile-scoped launcher choices. */
export function mergeVoiceModePreferences(
  config: Record<string, unknown>,
  preferences: VoiceModePreferences
): Record<string, unknown> {
  const voice = asRecord(config.voice) ?? {}
  const tts = asRecord(config.tts)

  const usesElevenLabs =
    String(tts?.provider ?? '')
      .trim()
      .toLowerCase() === 'elevenlabs'

  const selectedElevenLabsVoice =
    usesElevenLabs && preferences.voiceRef !== DEFAULT_PREFERENCES.voiceRef
      ? { ...(asRecord(tts?.elevenlabs) ?? {}), voice_id: preferences.voiceRef }
      : null

  return {
    ...config,
    ...(selectedElevenLabsVoice && tts ? { tts: { ...tts, elevenlabs: selectedElevenLabsVoice } } : {}),
    voice: {
      ...voice,
      experience: {
        attitude: nonEmptyString(preferences.attitude, DEFAULT_PREFERENCES.attitude),
        presentation: preferences.presentation === 'pip' ? 'pip' : 'chat',
        voice_ref: nonEmptyString(preferences.voiceRef, DEFAULT_PREFERENCES.voiceRef)
      }
    }
  }
}

/**
 * Prepare the normal new-chat path before microphone capture begins. The backend
 * session remains lazy until the first spoken turn, but it is guaranteed to be
 * created for this profile with this immutable voice-session plan.
 */
export async function prepareVoiceModeSession(plan: PendingVoiceModeSession): Promise<void> {
  const profile = normalizeProfileKey(plan.profile)

  const preferences = voiceModePreferencesFromConfig({
    voice: {
      experience: {
        attitude: plan.attitude,
        presentation: plan.presentation,
        voice_ref: plan.voiceRef
      }
    }
  })

  await ensureGatewayProfile(profile)
  $newChatProfile.set(profile)
  $pendingVoiceModeSession.set({ ...preferences, profile })
  requestFreshSession()
}

/** Return the one-shot plan only when this new session was explicitly prepared for its profile. */
export function pendingVoiceModeSessionForProfile(profile: string): PendingVoiceModeSession | null {
  const pending = $pendingVoiceModeSession.get()

  return pending && normalizeProfileKey(profile) === pending.profile ? pending : null
}

/** Consume the one-shot plan only for the profile it was explicitly prepared for. */
export function consumePendingVoiceModeSession(profile: string): PendingVoiceModeSession | null {
  const pending = pendingVoiceModeSessionForProfile(profile)

  if (!pending) {
    return null
  }

  $pendingVoiceModeSession.set(null)

  return pending
}

/** Cancel a prepared one-shot session before the first turn consumes it. */
export function clearPendingVoiceModeSession(): void {
  $pendingVoiceModeSession.set(null)
}

export function resetVoiceModeSessionForTest(): void {
  clearPendingVoiceModeSession()
}
