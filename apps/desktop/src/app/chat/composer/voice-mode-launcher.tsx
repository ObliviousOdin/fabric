import { useStore } from '@nanostores/react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getElevenLabsVoices, getFabricConfigRecordForProfile, saveFabricConfig } from '@/fabric'
import { triggerHaptic } from '@/lib/haptics'
import { AudioLines, iconSize, Loader2 } from '@/lib/icons'
import { notifyError } from '@/store/notifications'
import { $activeGatewayProfile, $profiles, refreshProfiles } from '@/store/profile'
import {
  mergeVoiceModePreferences,
  type PendingVoiceModeSession,
  type VoiceModeAttitudeOption,
  voiceModeAttitudesFromConfig,
  voiceModePreferencesFromConfig
} from '@/store/voice-mode'

const VOICE_MODE_TRIGGER_CLASS =
  'size-(--composer-control-primary-size,var(--composer-control-size)) shrink-0 rounded-full p-0 bg-foreground text-background hover:bg-foreground/90 disabled:bg-foreground/30 disabled:text-background disabled:opacity-100'

interface VoiceOption {
  id: string
  label: string
}

/**
 * The Voice Mode entry point is intentionally a launcher, not a second settings
 * page. It reads and saves only profile-scoped non-secret preferences, then
 * hands a one-shot session plan to the normal composer/session creation path.
 */
export function VoiceModeLauncher({
  disabled,
  onStart
}: {
  disabled: boolean
  onStart: (plan: PendingVoiceModeSession) => Promise<void>
}) {
  const activeProfile = useStore($activeGatewayProfile)
  const profiles = useStore($profiles)
  const [open, setOpen] = useState(false)
  const [selectedProfile, setSelectedProfile] = useState(activeProfile)

  const [attitudes, setAttitudes] = useState<VoiceModeAttitudeOption[]>([
    { id: 'profile_default', label: 'Profile default' }
  ])

  const [attitude, setAttitude] = useState('profile_default')
  const [presentation, setPresentation] = useState<'chat' | 'pip'>('chat')
  const [voiceRef, setVoiceRef] = useState('profile_default')
  const [voices, setVoices] = useState<VoiceOption[]>([])
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const profileOptions = useMemo(() => {
    const names = profiles.map(profile => profile.name).filter(Boolean)

    return names.length > 0 ? names : [activeProfile]
  }, [activeProfile, profiles])

  const voiceOptions = useMemo(() => {
    const selected = voiceRef !== 'profile_default' ? [{ id: voiceRef, label: voiceRef }] : []

    const unique = new Map<string, VoiceOption>(
      [{ id: 'profile_default', label: 'Profile default' }, ...selected, ...voices].map(option => [option.id, option])
    )

    return [...unique.values()]
  }, [voiceRef, voices])

  useEffect(() => {
    if (!open) {
      return
    }

    void refreshProfiles().catch(() => undefined)
  }, [open])

  useEffect(() => {
    if (!open || !selectedProfile) {
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    void Promise.all([
      getFabricConfigRecordForProfile(selectedProfile),
      getElevenLabsVoices(selectedProfile).catch(() => null)
    ])
      .then(([config, elevenLabs]) => {
        if (cancelled) {
          return
        }

        const preferences = voiceModePreferencesFromConfig(config)
        const nextAttitudes = voiceModeAttitudesFromConfig(config)
        const knownAttitude = nextAttitudes.some(option => option.id === preferences.attitude)
        setAttitudes(nextAttitudes)
        setAttitude(knownAttitude ? preferences.attitude : 'profile_default')
        setPresentation(preferences.presentation)
        setVoiceRef(preferences.voiceRef)
        setVoices((elevenLabs?.voices ?? []).map(voice => ({ id: voice.voice_id, label: voice.label })))
      })
      .catch(loadError => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Voice Mode could not load this profile.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [open, selectedProfile])

  const begin = async () => {
    if (loading || starting) {
      return
    }

    setStarting(true)
    setError(null)

    try {
      // Re-read on submit so a settings save in another window cannot be
      // overwritten by stale launcher state. Raw config never enters React state.
      const config = await getFabricConfigRecordForProfile(selectedProfile)
      const plan: PendingVoiceModeSession = { attitude, presentation, profile: selectedProfile, voiceRef }
      const result = await saveFabricConfig(mergeVoiceModePreferences(config, plan), selectedProfile)

      if (!result.ok) {
        throw new Error('Fabric did not save the Voice Mode choices.')
      }

      await onStart(plan)
      setOpen(false)
      triggerHaptic('success')
    } catch (startError) {
      const message = startError instanceof Error ? startError.message : 'Voice Mode could not start.'
      setError(message)
      notifyError(startError, 'Voice Mode could not start.')
    } finally {
      setStarting(false)
    }
  }

  return (
    <Popover
      onOpenChange={nextOpen => {
        setOpen(nextOpen)

        if (nextOpen) {
          triggerHaptic('open')
          setSelectedProfile(current => current || activeProfile)
        }
      }}
      open={open}
    >
      <PopoverTrigger asChild>
        <Button
          aria-label="Start Voice Mode"
          className={VOICE_MODE_TRIGGER_CLASS}
          disabled={disabled}
          size="icon"
          type="button"
        >
          <AudioLines className={iconSize.sm} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-3">
        <div className="mb-3 space-y-0.5">
          <p className="text-sm font-semibold">Voice Mode</p>
          <p className="text-xs text-muted-foreground">Start a fresh, profile-scoped voice session.</p>
        </div>

        <div className="space-y-3">
          <LauncherSelect label="Profile" onValueChange={setSelectedProfile} value={selectedProfile}>
            {profileOptions.map(profile => (
              <SelectItem key={profile} value={profile}>
                {profile}
              </SelectItem>
            ))}
          </LauncherSelect>

          <LauncherSelect label="Voice" onValueChange={setVoiceRef} value={voiceRef}>
            {voiceOptions.map(voice => (
              <SelectItem key={voice.id} value={voice.id}>
                {voice.label}
              </SelectItem>
            ))}
          </LauncherSelect>

          <LauncherSelect label="Attitude" onValueChange={setAttitude} value={attitude}>
            {attitudes.map(option => (
              <SelectItem key={option.id} value={option.id}>
                {option.label}
              </SelectItem>
            ))}
          </LauncherSelect>

          <LauncherSelect
            label="Display"
            onValueChange={value => setPresentation(value === 'pip' ? 'pip' : 'chat')}
            value={presentation}
          >
            <SelectItem value="chat">Chat only</SelectItem>
            <SelectItem value="pip">Watch work in PiP</SelectItem>
          </LauncherSelect>
        </div>

        <p className="mt-3 text-[0.6875rem] leading-relaxed text-muted-foreground">
          PiP opens only after Fabric begins an already-authorized visual Browser or Computer Use activity.
        </p>
        {error ? (
          <p className="mt-2 text-xs text-destructive" role="alert">
            {error}
          </p>
        ) : null}

        <Button className="mt-3 w-full" disabled={loading || starting} onClick={() => void begin()} type="button">
          {loading || starting ? <Loader2 className="animate-spin" /> : <AudioLines />}
          {starting ? 'Preparing…' : 'Start Voice Mode'}
        </Button>
      </PopoverContent>
    </Popover>
  )
}

function LauncherSelect({
  children,
  label,
  onValueChange,
  value
}: {
  children: ReactNode
  label: string
  onValueChange: (value: string) => void
  value: string
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <Select onValueChange={onValueChange} value={value}>
        <SelectTrigger className="h-8 w-full text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>{children}</SelectContent>
      </Select>
    </label>
  )
}
