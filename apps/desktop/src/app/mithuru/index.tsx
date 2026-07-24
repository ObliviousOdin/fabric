import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useMicRecorder } from '@/app/chat/composer/hooks/use-mic-recorder'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { chatMessageText } from '@/lib/chat-messages'
import type { ChatMessage } from '@/lib/chat-messages'
import { HelpCircle, Mic, MicOff, Pencil, Send, Volume2, VolumeX } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $approvalRequest } from '@/store/prompts'

import { MITHURU_LOCALE_NAMES, MITHURU_LOCALES, type MithuruLocale, mithuruTranslate } from './core/localization'
import type { MithuruInteractionMode, MithuruPreferences, MithuruTextScale } from './core/preferences'
import { loadMithuruProfile, saveMithuruProfile } from './preferences'

type MithuruVoiceState = 'idle' | 'listening' | 'processing' | 'speaking' | 'needs-confirmation' | 'offline' | 'error'

interface MithuruSimpleModeProps {
  busy: boolean
  connected: boolean
  messages: ChatMessage[]
  profile: string
  speechToTextEnabled: boolean
  onChooseDocument: () => Promise<void> | void
  onExit: () => void
  onRespondToApproval: (sessionId: null | string, requestId: string, action: 'approve' | 'reject') => Promise<void>
  onSubmit: (text: string) => Promise<boolean> | boolean
  onTranscribeAudio: (audio: Blob) => Promise<string>
}

type OnboardingStep = 'language' | 'interaction' | 'text-size' | 'speech-rate' | 'family' | 'cloud'

const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  'language',
  'interaction',
  'text-size',
  'speech-rate',
  'family',
  'cloud'
]

const SUGGESTIONS = [
  'suggest.messages',
  'suggest.family',
  'suggest.reminder',
  'suggest.document',
  'suggest.appointments'
] as const

function textScaleClass(scale: MithuruTextScale): string {
  if (scale === 'maximum') {
    return 'text-[1.35rem]'
  }

  if (scale === 'extra-large') {
    return 'text-[1.2rem]'
  }

  return 'text-[1.075rem]'
}

function statusIcon(state: MithuruVoiceState) {
  if (state === 'listening') {
    return <Mic className="size-6" />
  }

  if (state === 'speaking') {
    return <Volume2 className="size-6" />
  }

  if (state === 'offline' || state === 'error') {
    return <MicOff className="size-6" />
  }

  return <span aria-hidden className="size-3 rounded-full bg-current" />
}

export function MithuruSimpleMode(props: MithuruSimpleModeProps) {
  const [stored, setStored] = useState(() => loadMithuruProfile(props.profile))
  const [stepIndex, setStepIndex] = useState(0)
  const [draft, setDraft] = useState('')
  const [state, setState] = useState<MithuruVoiceState>(props.connected ? 'idle' : 'offline')
  const [error, setError] = useState('')
  const [showHelp, setShowHelp] = useState(false)
  const [documentConsent, setDocumentConsent] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const approvalButtonRef = useRef<HTMLButtonElement>(null)
  const transcriptEndRef = useRef<HTMLDivElement>(null)
  const wasBusyRef = useRef(props.busy)
  const approval = useStore($approvalRequest)
  const preferences = stored.preferences
  const locale = preferences.preferredLocale

  const t = useCallback(
    (key: Parameters<typeof mithuruTranslate>[1], variables?: Record<string, string>) =>
      mithuruTranslate(locale, key, variables),
    [locale]
  )

  const micCopy = useMemo(
    () => ({
      microphoneAccessDenied: t('error.permission'),
      microphoneConstraintsUnsupported: t('error.hearing'),
      microphoneInUse: t('error.hearing'),
      microphonePermissionDenied: t('error.permission'),
      microphoneStartFailed: t('error.hearing'),
      microphoneUnsupported: t('error.speechUnsupported'),
      noMicrophone: t('error.speechUnsupported')
    }),
    [t]
  )

  const recorder = useMicRecorder(micCopy)

  useEffect(() => {
    setStored(loadMithuruProfile(props.profile))
    setStepIndex(0)
  }, [props.profile])

  useEffect(() => {
    if (!props.connected && state !== 'listening') {
      setState('offline')
    }

    if (props.connected && state === 'offline') {
      setState('idle')
    }
  }, [props.connected, state])

  useEffect(() => {
    const wasBusy = wasBusyRef.current

    wasBusyRef.current = props.busy

    if (props.busy && state !== 'listening' && state !== 'speaking') {
      setState('processing')
    } else if (wasBusy && state === 'processing') {
      setState(props.connected ? 'idle' : 'offline')
    }
  }, [props.busy, props.connected, state])

  useEffect(() => {
    if (approval) {
      approvalButtonRef.current?.focus()
    }
  }, [approval])

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [props.messages.length])

  const updatePreferences = (next: Partial<MithuruPreferences>) => {
    setStored(current => ({ ...current, preferences: { ...current.preferences, ...next } }))
  }

  const persist = (next = stored) => {
    saveMithuruProfile(props.profile, next)
    setStored(next)
  }

  const stopSpeaking = useCallback(() => {
    window.speechSynthesis?.cancel()
    setSpeaking(false)
    setState(props.connected ? 'idle' : 'offline')
  }, [props.connected])

  const speak = useCallback(
    (text: string) => {
      if (!('speechSynthesis' in window) || !text.trim()) {
        setError(t('voice.unavailable'))
        setState('error')

        return
      }

      const language = locale === 'en-LK' ? 'en-LK' : locale
      const voices = window.speechSynthesis.getVoices()
      const voice = voices.find(item => item.lang.toLowerCase() === language.toLowerCase())
      const languageCode = language.split('-')[0].toLowerCase()
      const languageVoice = voice ?? voices.find(item => item.lang.toLowerCase().startsWith(languageCode))

      if (!languageVoice && languageCode !== 'en') {
        setError(t('voice.unavailable'))
        setState('error')

        return
      }

      stopSpeaking()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = language
      utterance.rate = preferences.speechRate

      if (languageVoice) {
        utterance.voice = languageVoice
      }

      utterance.onend = () => {
        setSpeaking(false)
        setState(props.connected ? 'idle' : 'offline')
      }

      utterance.onerror = () => {
        setSpeaking(false)
        setError(t('voice.unavailable'))
        setState('error')
      }

      setSpeaking(true)
      setState('speaking')
      window.speechSynthesis.speak(utterance)
    },
    [locale, preferences.speechRate, props.connected, stopSpeaking, t]
  )

  const lastAssistantText = useMemo(
    () =>
      [...props.messages]
        .reverse()
        .find(message => message.role === 'assistant' && chatMessageText(message).trim())
        ?.parts.filter(part => part.type === 'text')
        .map(part => ('text' in part ? part.text : ''))
        .join('') ?? '',
    [props.messages]
  )

  const stopListening = useCallback(async () => {
    const recording = await recorder.handle.stop()

    if (!recording?.audio.size) {
      setError(t('error.hearing'))
      setState('error')

      return
    }

    setState('processing')

    try {
      const text = (await props.onTranscribeAudio(recording.audio)).trim()

      if (!text) {
        throw new Error('empty transcript')
      }

      setDraft(text)
      setState(props.connected ? 'idle' : 'offline')
      setError('')
    } catch {
      setError(t('error.hearing'))
      setState('error')
    }
  }, [props, recorder.handle, t])

  const startListening = useCallback(async () => {
    stopSpeaking()
    setError('')

    if (!props.speechToTextEnabled) {
      setError(t('error.speechUnsupported'))
      setState('error')

      return
    }

    // Desktop transcription uses the configured Fabric speech service. Until
    // a verifiably on-device provider is advertised, do not send microphone
    // audio without the user's explicit online-speech choice.
    if (!preferences.cloudSpeechAllowed) {
      setError(t('error.speechUnsupported'))
      setState('error')

      return
    }

    try {
      await recorder.handle.start({ onError: () => setState('error') })
      setState('listening')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.hearing'))
      setState('error')
    }
  }, [preferences.cloudSpeechAllowed, props.speechToTextEnabled, recorder.handle, stopSpeaking, t])

  const toggleListening = useCallback(() => {
    if (recorder.recording) {
      void stopListening()
    } else {
      void startListening()
    }
  }, [recorder.recording, startListening, stopListening])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.altKey &&
        event.code === 'Space' &&
        !event.repeat &&
        preferences.voiceEnabled &&
        !approval &&
        !props.busy
      ) {
        event.preventDefault()
        toggleListening()
      }

      if (event.key === 'Escape' && speaking) {
        stopSpeaking()
      }
    }

    window.addEventListener('keydown', onKeyDown)

    return () => window.removeEventListener('keydown', onKeyDown)
  }, [approval, preferences.voiceEnabled, props.busy, speaking, stopSpeaking, toggleListening])

  const sendDraft = async () => {
    const text = draft.trim()

    if (!text || approval || props.busy || !props.connected) {
      return
    }

    setState('processing')
    const sent = await props.onSubmit(text)

    if (sent) {
      setDraft('')
      setError('')
    } else {
      setError(t('error.notSent'))
    }

    setState(sent ? 'idle' : 'error')
  }

  if (!stored.onboardingCompleted) {
    const onboardingSteps =
      preferences.interactionMode === 'text'
        ? ONBOARDING_STEPS.filter(step => step !== 'speech-rate' && step !== 'cloud')
        : ONBOARDING_STEPS

    return (
      <MithuruOnboarding
        onBack={() => setStepIndex(index => Math.max(0, index - 1))}
        onFinish={finalValues => {
          const next = {
            onboardingCompleted: true,
            preferences: { ...preferences, ...finalValues, experienceMode: 'simple' as const }
          }

          persist(next)
        }}
        onNext={() => setStepIndex(index => Math.min(onboardingSteps.length - 1, index + 1))}
        onUpdate={updatePreferences}
        preferences={preferences}
        step={onboardingSteps[stepIndex]}
      />
    )
  }

  const visibleMessages = props.messages.filter(
    message => !message.hidden && ['user', 'assistant'].includes(message.role)
  )

  const stateKey = `state.${state === 'needs-confirmation' ? 'needsConfirmation' : state}` as const

  return (
    <div
      className={cn(
        'flex h-full min-h-0 flex-col bg-background text-foreground',
        textScaleClass(preferences.textScale)
      )}
    >
      <header className="flex min-h-16 flex-wrap items-center gap-3 border-b border-border px-5 py-3">
        <strong className="mr-auto text-2xl">{t('brand.name')}</strong>
        <label className="sr-only" htmlFor="mithuru-language">
          {t('nav.language')}
        </label>
        <select
          className="min-h-12 rounded-lg border border-border bg-background px-4 text-base font-medium"
          id="mithuru-language"
          onChange={event => {
            const next = event.target.value as MithuruLocale
            const nextStored = { ...stored, preferences: { ...preferences, preferredLocale: next } }
            persist(nextStored)
          }}
          value={locale}
        >
          {MITHURU_LOCALES.map(item => (
            <option key={item} value={item}>
              {MITHURU_LOCALE_NAMES[item]}
            </option>
          ))}
        </select>
        <Button className="min-h-12 px-4 text-base" onClick={() => setShowHelp(value => !value)} variant="outline">
          <HelpCircle className="size-5" /> {t('nav.help')}
        </Button>
        <Button
          className="min-h-12 px-4 text-base"
          onClick={() => {
            persist({ ...stored, preferences: { ...preferences, experienceMode: 'standard' } })
            props.onExit()
          }}
          variant="textStrong"
        >
          {t('nav.standardMode')}
        </Button>
      </header>

      <div className="grid min-h-0 flex-1 gap-5 overflow-hidden p-5 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,30rem)]">
        <section className="flex min-h-0 flex-col rounded-xl border border-border bg-card">
          <div
            aria-label={t('accessibility.status')}
            aria-live="polite"
            className={cn(
              'flex min-h-16 items-center gap-3 border-b border-border px-5 py-3 font-semibold',
              state === 'error' || state === 'offline' ? 'text-destructive' : 'text-foreground'
            )}
            role="status"
          >
            {statusIcon(approval ? 'needs-confirmation' : state)}
            <span>{approval ? t('state.needsConfirmation') : t(stateKey)}</span>
          </div>

          <div aria-label={t('home.transcriptPlaceholder')} className="min-h-0 flex-1 overflow-y-auto p-5">
            {visibleMessages.length === 0 ? (
              <p className="text-xl text-muted-foreground">{t('home.transcriptPlaceholder')}</p>
            ) : (
              <ol className="grid list-none gap-5 p-0">
                {visibleMessages.map(message => {
                  const text = chatMessageText(message).trim()

                  if (!text) {
                    return null
                  }

                  return (
                    <li
                      className={cn(
                        'max-w-[90%] whitespace-pre-wrap rounded-xl border border-border px-5 py-4 leading-relaxed',
                        message.role === 'user' ? 'ml-auto bg-muted' : 'mr-auto bg-background'
                      )}
                      key={message.id}
                    >
                      {text}
                    </li>
                  )
                })}
              </ol>
            )}
            <div ref={transcriptEndRef} />
          </div>

          {approval && (
            <div
              className="m-4 rounded-xl border-2 border-amber-600 bg-amber-50 p-5 text-slate-950 dark:bg-amber-950 dark:text-white"
              role="alertdialog"
            >
              <h2 className="text-xl font-bold">{t('confirm.title')}</h2>
              <p className="mt-3 leading-relaxed">{approval.description || t('confirm.share')}</p>
              {approval.command && (
                <div className="mt-3">
                  <strong className="text-sm">{t('confirm.command')}</strong>
                  <code className="mt-1 block overflow-x-auto rounded-md bg-black/10 p-3 text-sm dark:bg-white/10">
                    {approval.command}
                  </code>
                </div>
              )}
              {approval.cwd && (
                <p className="mt-2 break-all text-sm">
                  <strong>{t('confirm.location')}:</strong> {approval.cwd}
                </p>
              )}
              <p className="mt-2 text-sm">{t('state.needsConfirmation')}</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <Button
                  className="min-h-14 text-base"
                  onClick={() => void props.onRespondToApproval(approval.sessionId, approval.requestId, 'approve')}
                  ref={approvalButtonRef}
                >
                  {t('confirm.allowOnce')}
                </Button>
                <Button
                  className="min-h-14 text-base"
                  onClick={() => void props.onRespondToApproval(approval.sessionId, approval.requestId, 'reject')}
                  variant="outline"
                >
                  {t('confirm.deny')}
                </Button>
              </div>
            </div>
          )}

          {error && (
            <div className="mx-4 mb-3 rounded-lg border border-destructive p-4" role="alert">
              {error}
            </div>
          )}

          <div className="grid gap-3 border-t border-border p-4">
            <textarea
              aria-label={t('home.editTranscript')}
              className="min-h-24 w-full resize-y rounded-xl border border-border bg-background p-4 text-[1em] leading-relaxed outline-none focus:ring-4 focus:ring-ring/40"
              disabled={Boolean(approval)}
              onChange={event => setDraft(event.target.value)}
              placeholder={t('home.inputPlaceholder')}
              value={draft}
            />
            <div className={cn('grid gap-3', preferences.voiceEnabled && 'sm:grid-cols-2')}>
              {preferences.voiceEnabled && (
                <Button
                  aria-label={recorder.recording ? t('home.stopListening') : t('home.talk')}
                  className="min-h-16 rounded-xl text-lg"
                  disabled={Boolean(approval) || state === 'processing' || props.busy}
                  onClick={toggleListening}
                  title="Alt+Space"
                >
                  {recorder.recording ? <MicOff className="size-7" /> : <Mic className="size-7" />}
                  {recorder.recording ? t('home.stopListening') : t('home.talk')}
                </Button>
              )}
              <Button
                className="min-h-16 rounded-xl text-lg"
                disabled={Boolean(approval) || !draft.trim() || props.busy || !props.connected}
                onClick={() => void sendDraft()}
                variant="outline"
              >
                <Send className="size-6" /> {t('home.send')}
              </Button>
            </div>
            {preferences.voiceEnabled && (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Button
                    className="min-h-14 text-base"
                    disabled={!lastAssistantText}
                    onClick={() => speak(lastAssistantText)}
                    variant="secondary"
                  >
                    <Volume2 className="size-5" /> {t('home.repeat')}
                  </Button>
                  <Button
                    className="min-h-14 text-base"
                    disabled={!speaking}
                    onClick={stopSpeaking}
                    variant="secondary"
                  >
                    <VolumeX className="size-5" /> {t('home.stopSpeaking')}
                  </Button>
                </div>
                <p className="text-sm text-muted-foreground">
                  {preferences.cloudSpeechAllowed ? t('home.privacy.cloud') : t('home.privacy.local')}
                </p>
              </>
            )}
          </div>
        </section>

        <aside className="min-h-0 overflow-y-auto rounded-xl border border-border bg-card p-5">
          <h1 className="text-2xl font-semibold">{t('home.greeting')}</h1>
          {showHelp && (
            <div className="mt-4 rounded-lg border border-border bg-background p-4">
              <strong>{t('help.title')}</strong>
              <p className="mt-2 leading-relaxed">{t('help.body')}</p>
            </div>
          )}
          <div className="mt-5 grid gap-3">
            {SUGGESTIONS.map(key => (
              <Button
                className="min-h-14 h-auto justify-start whitespace-normal px-4 py-3 text-left text-base"
                disabled={Boolean(approval)}
                key={key}
                onClick={() => {
                  if (key === 'suggest.document') {
                    setDocumentConsent(true)
                  } else {
                    setDraft(t(key))
                  }
                }}
                variant="outline"
              >
                <Pencil className="size-5" /> {t(key)}
              </Button>
            ))}
          </div>
          {preferences.caregiverModeConfigured && (
            <div className="mt-6 rounded-lg border border-border p-4">
              <h2 className="font-semibold">{t('family.title')}</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t('family.privacy')}</p>
              <Button
                className="mt-3 min-h-12 w-full text-base"
                disabled={Boolean(approval)}
                onClick={() => setDraft(t('family.contact'))}
                variant="secondary"
              >
                {t('family.contact')}
              </Button>
            </div>
          )}
        </aside>
      </div>

      <Dialog onOpenChange={setDocumentConsent} open={documentConsent}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-xl">{t('confirm.title')}</DialogTitle>
            <DialogDescription className="pt-3 text-base leading-relaxed text-foreground">
              {t('document.cloudConsent')}
            </DialogDescription>
          </DialogHeader>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Button
              className="min-h-14 text-base"
              onClick={() => {
                setDocumentConsent(false)
                setDraft(t('suggest.document'))
                void props.onChooseDocument()
              }}
            >
              {t('confirm.yes')}
            </Button>
            <Button className="min-h-14 text-base" onClick={() => setDocumentConsent(false)} variant="outline">
              {t('confirm.no')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function MithuruOnboarding({
  onBack,
  onFinish,
  onNext,
  onUpdate,
  preferences,
  step
}: {
  onBack: () => void
  onFinish: (finalValues: Partial<MithuruPreferences>) => void
  onNext: () => void
  onUpdate: (next: Partial<MithuruPreferences>) => void
  preferences: MithuruPreferences
  step: OnboardingStep
}) {
  const locale = preferences.preferredLocale
  const t = (key: Parameters<typeof mithuruTranslate>[1]) => mithuruTranslate(locale, key)

  const choose = (value: Partial<MithuruPreferences>) => {
    const finishesOnThisStep = step === 'cloud' || (step === 'family' && preferences.interactionMode === 'text')

    if (finishesOnThisStep) {
      onFinish(value)
    } else {
      onUpdate(value)
      onNext()
    }
  }

  let title = t('onboarding.language.title')

  let options: Array<{ label: string; value: Partial<MithuruPreferences> }> = MITHURU_LOCALES.slice(0, 3).map(item => ({
    label: MITHURU_LOCALE_NAMES[item],
    value: { preferredLocale: item }
  }))

  if (step === 'interaction') {
    title = t('onboarding.interaction.title')
    options = (
      [
        ['voice', 'onboarding.interaction.voice'],
        ['text', 'onboarding.interaction.text'],
        ['both', 'onboarding.interaction.both']
      ] as const
    ).map(([value, key]) => ({
      label: t(key),
      value: {
        cloudSpeechAllowed: value === 'text' ? false : preferences.cloudSpeechAllowed,
        interactionMode: value as MithuruInteractionMode,
        voiceEnabled: value !== 'text'
      }
    }))
  } else if (step === 'text-size') {
    title = t('onboarding.textSize.title')
    options = (
      [
        ['large', 'onboarding.textSize.large'],
        ['extra-large', 'onboarding.textSize.extraLarge'],
        ['maximum', 'onboarding.textSize.maximum']
      ] as const
    ).map(([value, key]) => ({ label: t(key), value: { textScale: value } }))
  } else if (step === 'speech-rate') {
    title = t('onboarding.speechRate.title')
    options = [
      { label: t('onboarding.speechRate.slow'), value: { speechRate: 0.7 } },
      { label: t('onboarding.speechRate.normal'), value: { speechRate: 1 } }
    ]
  } else if (step === 'family') {
    title = t('onboarding.family.title')
    options = [
      { label: t('onboarding.family.yes'), value: { caregiverModeConfigured: true } },
      { label: t('onboarding.family.no'), value: { caregiverModeConfigured: false } }
    ]
  } else if (step === 'cloud') {
    title = t('onboarding.cloud.title')
    options = [
      { label: t('onboarding.family.yes'), value: { cloudSpeechAllowed: true } },
      { label: t('onboarding.family.no'), value: { cloudSpeechAllowed: false } }
    ]
  }

  return (
    <main
      className={cn(
        'grid h-full place-items-center overflow-y-auto bg-background p-6 text-foreground',
        textScaleClass(preferences.textScale)
      )}
    >
      <section className="w-full max-w-2xl rounded-xl border border-border bg-card p-6 shadow-lg">
        <p className="text-lg font-semibold text-muted-foreground">{t('onboarding.title')}</p>
        <h1 className="mt-4 text-3xl font-bold leading-tight">{title}</h1>
        {step === 'cloud' && <p className="mt-4 leading-relaxed">{t('onboarding.cloud.explanation')}</p>}
        {step === 'family' && <p className="mt-4 leading-relaxed text-muted-foreground">{t('family.privacy')}</p>}
        <div className="mt-7 grid gap-4">
          {options.map(option => (
            <Button
              className="min-h-16 h-auto justify-start whitespace-normal px-5 py-4 text-left text-lg"
              key={option.label}
              onClick={() => choose(option.value)}
              variant="outline"
            >
              {option.label}
            </Button>
          ))}
        </div>
        {step !== 'language' && (
          <Button className="mt-5 min-h-12 text-base" onClick={onBack} variant="textStrong">
            {t('onboarding.back')}
          </Button>
        )}
      </section>
    </main>
  )
}
