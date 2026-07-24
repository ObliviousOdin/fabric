import { describe, expect, it } from 'vitest'

import {
  $pendingVoiceModeSession,
  clearPendingVoiceModeSession,
  mergeVoiceModePreferences,
  voiceModeAttitudesFromConfig,
  voiceModePreferencesFromConfig
} from './voice-mode'

describe('voice mode preferences', () => {
  it('clears a prepared one-shot session when Voice Mode is abandoned', () => {
    $pendingVoiceModeSession.set({
      attitude: 'focused',
      presentation: 'chat',
      profile: 'default',
      voiceRef: 'profile_default'
    })

    clearPendingVoiceModeSession()

    expect($pendingVoiceModeSession.get()).toBeNull()
  })

  it('uses safe defaults when profile config has no voice experience block', () => {
    expect(voiceModePreferencesFromConfig({})).toEqual({
      attitude: 'profile_default',
      presentation: 'chat',
      voiceRef: 'profile_default'
    })
  })

  it('keeps only a supported presentation and non-empty attitude from profile config', () => {
    expect(
      voiceModePreferencesFromConfig({
        voice: {
          experience: {
            attitude: 'decisive',
            presentation: 'pip',
            voice_ref: 'nova'
          }
        }
      })
    ).toEqual({ attitude: 'decisive', presentation: 'pip', voiceRef: 'nova' })

    expect(
      voiceModePreferencesFromConfig({
        voice: { experience: { attitude: [], presentation: 'terminal-mirror', voice_ref: 12 } }
      })
    ).toEqual({ attitude: 'profile_default', presentation: 'chat', voiceRef: 'profile_default' })
  })

  it('writes only non-secret launcher preferences without replacing existing voice provider configuration', () => {
    const next = mergeVoiceModePreferences(
      {
        voice: {
          auto_tts: true,
          provider: 'elevenlabs',
          elevenlabs: { model_id: 'eleven_multilingual_v2', voice_id: 'existing-voice' }
        }
      },
      { attitude: 'focused', presentation: 'pip', voiceRef: 'existing-voice' }
    )

    expect(next).toEqual({
      voice: {
        auto_tts: true,
        provider: 'elevenlabs',
        elevenlabs: { model_id: 'eleven_multilingual_v2', voice_id: 'existing-voice' },
        experience: { attitude: 'focused', presentation: 'pip', voice_ref: 'existing-voice' }
      }
    })
  })

  it('offers only a profile default plus configured personality names, never personality prompt text', () => {
    expect(
      voiceModeAttitudesFromConfig({
        agent: {
          personalities: {
            focused: { description: 'Stay concise', system_prompt: 'secret prompt content' },
            operator: 'another prompt that must not reach the UI'
          }
        }
      })
    ).toEqual([
      { id: 'profile_default', label: 'Profile default' },
      { id: 'focused', label: 'focused' },
      { id: 'operator', label: 'operator' }
    ])
  })

  it('applies a selected ElevenLabs voice to the canonical TTS provider configuration', () => {
    expect(
      mergeVoiceModePreferences(
        { tts: { elevenlabs: { voice_id: 'old' }, provider: 'elevenlabs' } },
        { attitude: 'profile_default', presentation: 'chat', voiceRef: 'new' }
      )
    ).toMatchObject({
      tts: { elevenlabs: { voice_id: 'new' }, provider: 'elevenlabs' },
      voice: { experience: { voice_ref: 'new' } }
    })
  })
})
