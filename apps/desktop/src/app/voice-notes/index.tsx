import type * as React from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useMicRecorder } from '@/app/chat/composer/hooks/use-mic-recorder'
import { PAGE_INSET_X } from '@/app/layout-constants'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { ErrorBanner } from '@/components/ui/error-state'
import { Loader } from '@/components/ui/loader'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n'
import { Download, FileText, Mic, RefreshCw, Send, StopFilled, Trash2 } from '@/lib/icons'
import { cn } from '@/lib/utils'

import { buildVoiceNotePrompt, recordingFileExtension } from './workflow'

type VoiceNotePhase = 'idle' | 'recording' | 'review' | 'transcribing'

export interface VoiceNoteCreateRequest {
  prompt: string
  transcript: string
}

export interface VoiceNotesViewProps extends React.ComponentProps<'section'> {
  maxRecordingSeconds: number
  onConfigureSpeechToText: () => void
  onCreateNote: (request: VoiceNoteCreateRequest) => void
  onTranscribeAudio: (audio: Blob) => Promise<string>
  sttEnabled: boolean
}

function formatDuration(seconds: number): string {
  const wholeSeconds = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(wholeSeconds / 60)

  return `${minutes}:${String(wholeSeconds % 60).padStart(2, '0')}`
}

function downloadRecording(audio: Blob) {
  const url = URL.createObjectURL(audio)
  const anchor = document.createElement('a')

  anchor.href = url
  anchor.download = `fabric-voice-note.${recordingFileExtension(audio.type)}`
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function VoiceNotesView({
  className,
  maxRecordingSeconds,
  onConfigureSpeechToText,
  onCreateNote,
  onTranscribeAudio,
  sttEnabled,
  ...props
}: VoiceNotesViewProps) {
  const { t } = useI18n()
  const copy = t.voiceNotes
  const recorder = useMicRecorder(t.notifications.voice)
  const [audio, setAudio] = useState<Blob | null>(null)
  const [durationSeconds, setDurationSeconds] = useState(0)
  const [error, setError] = useState('')
  const [phase, setPhase] = useState<VoiceNotePhase>('idle')
  const [submitting, setSubmitting] = useState(false)
  const [transcript, setTranscript] = useState('')
  const startedAtRef = useRef(0)
  const stopInFlightRef = useRef(false)

  const recordingLimit = useMemo(
    () => Math.max(1, Math.min(600, Math.floor(maxRecordingSeconds) || 120)),
    [maxRecordingSeconds]
  )

  const reset = useCallback(() => {
    recorder.handle.cancel()
    stopInFlightRef.current = false
    setAudio(null)
    setDurationSeconds(0)
    setError('')
    setPhase('idle')
    setSubmitting(false)
    setTranscript('')
  }, [recorder.handle])

  const transcribe = useCallback(
    async (recordedAudio: Blob) => {
      setError('')
      setPhase('transcribing')

      try {
        const nextTranscript = await onTranscribeAudio(recordedAudio)

        if (!nextTranscript.trim()) {
          throw new Error(t.notifications.voice.noSpeechDetected)
        }

        setTranscript(nextTranscript.trim())
      } catch (transcriptionError) {
        setError(
          transcriptionError instanceof Error ? transcriptionError.message : t.notifications.voice.transcriptionFailed
        )
      } finally {
        setPhase('review')
      }
    },
    [onTranscribeAudio, t.notifications.voice.noSpeechDetected, t.notifications.voice.transcriptionFailed]
  )

  const stopRecording = useCallback(async () => {
    if (stopInFlightRef.current || phase !== 'recording') {
      return
    }

    stopInFlightRef.current = true
    setPhase('transcribing')

    try {
      const recording = await recorder.handle.stop()

      if (!recording) {
        setError(t.notifications.voice.recordingFailed)
        setPhase('idle')

        return
      }

      setAudio(recording.audio)
      setDurationSeconds(recording.durationMs / 1000)
      await transcribe(recording.audio)
    } catch (recordingError) {
      setError(recordingError instanceof Error ? recordingError.message : t.notifications.voice.recordingFailed)
      setPhase('idle')
    } finally {
      stopInFlightRef.current = false
    }
  }, [phase, recorder.handle, t.notifications.voice.recordingFailed, transcribe])

  const stopRecordingRef = useRef(stopRecording)
  stopRecordingRef.current = stopRecording

  useEffect(() => {
    if (phase !== 'recording') {
      return
    }

    const updateElapsed = () => {
      setDurationSeconds(Math.min(recordingLimit, (Date.now() - startedAtRef.current) / 1000))
    }

    const interval = window.setInterval(updateElapsed, 250)
    const timeout = window.setTimeout(() => void stopRecordingRef.current(), recordingLimit * 1000)

    updateElapsed()

    return () => {
      window.clearInterval(interval)
      window.clearTimeout(timeout)
    }
  }, [phase, recordingLimit])

  const startRecording = useCallback(async () => {
    if (!sttEnabled) {
      setError(t.desktop.sttDisabled)

      return
    }

    recorder.handle.cancel()
    setAudio(null)
    setDurationSeconds(0)
    setError('')
    setSubmitting(false)
    setTranscript('')

    try {
      await recorder.handle.start({
        onError: recordingError => {
          setError(recordingError.message)
          setPhase('idle')
        }
      })
      startedAtRef.current = Date.now()
      setPhase('recording')
    } catch (recordingError) {
      setError(recordingError instanceof Error ? recordingError.message : t.notifications.voice.recordingFailed)
      setPhase('idle')
    }
  }, [recorder.handle, sttEnabled, t.desktop.sttDisabled, t.notifications.voice.recordingFailed])

  const createNote = () => {
    if (!transcript.trim() || submitting) {
      return
    }

    const reviewedTranscript = transcript.trim()

    setSubmitting(true)
    onCreateNote({
      prompt: buildVoiceNotePrompt(reviewedTranscript),
      transcript: reviewedTranscript
    })
  }

  return (
    <section
      {...props}
      className={cn(
        'flex h-full min-w-0 flex-col overflow-y-auto bg-(--ui-chat-surface-background) pt-(--titlebar-height)',
        className
      )}
    >
      <div className={cn('mx-auto flex w-full max-w-4xl flex-1 flex-col pb-8 pt-8', PAGE_INSET_X)}>
        <header className="border-b border-(--ui-stroke-tertiary) pb-6">
          <div className="mb-3 flex size-8 items-center justify-center rounded-[4px] bg-(--ui-bg-tertiary) text-(--ui-text-secondary)">
            <Codicon name="record" size="1.1rem" />
          </div>
          <h1 className="text-lg font-semibold tracking-[-0.015em] text-(--ui-text-primary)">{copy.title}</h1>
          <p className="mt-1.5 max-w-2xl text-xs leading-5 text-(--ui-text-secondary)">{copy.subtitle}</p>
        </header>

        <div className="grid flex-1 gap-8 pt-7 lg:grid-cols-[minmax(0,1fr)_17rem] lg:gap-10">
          <main className="min-w-0">
            {!sttEnabled ? (
              <div className="border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4">
                <h2 className="text-sm font-semibold text-(--ui-text-primary)">{copy.setupTitle}</h2>
                <p className="mt-1 text-xs leading-5 text-(--ui-text-secondary)">{copy.setupDescription}</p>
                <Button className="mt-4" onClick={onConfigureSpeechToText} size="sm" variant="outline">
                  {copy.configure}
                </Button>
              </div>
            ) : null}

            {phase === 'idle' ? (
              <div className="flex min-h-64 flex-col items-center justify-center border border-(--ui-stroke-tertiary) bg-(--ui-bg-secondary) px-6 py-10 text-center">
                <div className="flex size-12 items-center justify-center rounded-full bg-(--ui-bg-quaternary) text-(--ui-text-primary)">
                  <Mic className="size-5" />
                </div>
                <h2 className="mt-4 text-sm font-semibold text-(--ui-text-primary)">{copy.readyTitle}</h2>
                <p className="mt-1 max-w-md text-xs leading-5 text-(--ui-text-secondary)">
                  {copy.readyDescription(recordingLimit)}
                </p>
                <Button className="mt-5" disabled={!sttEnabled} onClick={() => void startRecording()}>
                  <Mic />
                  {copy.startRecording}
                </Button>
              </div>
            ) : null}

            {phase === 'recording' ? (
              <div className="flex min-h-64 flex-col items-center justify-center border border-(--ui-stroke-tertiary) bg-(--ui-bg-secondary) px-6 py-10 text-center">
                <div aria-hidden className="flex h-12 items-end gap-1">
                  {Array.from({ length: 9 }, (_, index) => (
                    <span
                      className="w-1 rounded-full bg-(--ui-text-primary) transition-[height] duration-75"
                      key={index}
                      style={{ height: `${Math.max(12, recorder.level * (22 + index * 5))}%` }}
                    />
                  ))}
                </div>
                <div aria-live="polite" className="mt-4 font-mono text-lg tabular-nums text-(--ui-text-primary)">
                  {formatDuration(durationSeconds)}
                  <span className="text-(--ui-text-tertiary)"> / {formatDuration(recordingLimit)}</span>
                </div>
                <p className="mt-1 text-xs text-(--ui-text-secondary)">{copy.recording}</p>
                <div className="mt-5 flex items-center gap-2">
                  <Button onClick={() => void stopRecording()}>
                    <StopFilled />
                    {copy.stopRecording}
                  </Button>
                  <Button onClick={reset} variant="text">
                    {t.common.cancel}
                  </Button>
                </div>
              </div>
            ) : null}

            {phase === 'transcribing' ? (
              <div
                aria-live="polite"
                className="flex min-h-64 flex-col items-center justify-center border border-(--ui-stroke-tertiary) bg-(--ui-bg-secondary) px-6 py-10 text-center"
              >
                <Loader className="size-8" label={copy.transcribing} type="lemniscate-bloom" />
                <h2 className="mt-4 text-sm font-semibold text-(--ui-text-primary)">{copy.transcribing}</h2>
                <p className="mt-1 text-xs text-(--ui-text-secondary)">{copy.transcribingDescription}</p>
              </div>
            ) : null}

            {phase === 'review' ? (
              <div>
                <div className="flex items-baseline justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold text-(--ui-text-primary)">{copy.reviewTitle}</h2>
                    <p className="mt-1 text-xs leading-5 text-(--ui-text-secondary)">{copy.reviewDescription}</p>
                  </div>
                  <span className="shrink-0 font-mono text-[11px] text-(--ui-text-tertiary)">
                    {formatDuration(durationSeconds)}
                  </span>
                </div>

                {error ? (
                  <div aria-live="assertive" className="mt-4" role="alert">
                    <ErrorBanner>{error}</ErrorBanner>
                  </div>
                ) : null}

                <label
                  className="mb-2 mt-5 block text-xs font-medium text-(--ui-text-primary)"
                  htmlFor="voice-note-transcript"
                >
                  {copy.transcriptLabel}
                </label>
                <Textarea
                  autoCapitalize="sentences"
                  autoCorrect="on"
                  className="min-h-64 resize-y py-2.5 text-sm leading-5"
                  id="voice-note-transcript"
                  onChange={event => setTranscript(event.target.value)}
                  placeholder={copy.transcriptPlaceholder}
                  spellCheck
                  value={transcript}
                />

                <div className="mt-5 flex flex-wrap items-center gap-2">
                  <Button disabled={!transcript.trim() || submitting} onClick={createNote}>
                    <Send />
                    {submitting ? copy.creating : copy.createNote}
                  </Button>
                  {audio && error ? (
                    <Button onClick={() => void transcribe(audio)} variant="outline">
                      <RefreshCw />
                      {copy.retryTranscription}
                    </Button>
                  ) : null}
                  <Button onClick={() => void startRecording()} variant="outline">
                    <Mic />
                    {copy.recordAgain}
                  </Button>
                  {audio ? (
                    <Button onClick={() => downloadRecording(audio)} variant="text">
                      <Download />
                      {copy.saveRecording}
                    </Button>
                  ) : null}
                  <Button onClick={reset} variant="text">
                    <Trash2 />
                    {copy.discard}
                  </Button>
                </div>
              </div>
            ) : null}
          </main>

          <aside className="space-y-5 text-xs leading-5 text-(--ui-text-secondary)">
            <div>
              <FileText className="mb-2 size-4 text-(--ui-text-primary)" />
              <h2 className="font-semibold text-(--ui-text-primary)">{copy.outputTitle}</h2>
              <p className="mt-1">{copy.outputDescription}</p>
              <ul className="mt-3 space-y-1 text-(--ui-text-tertiary)">
                {copy.outputSections.map(section => (
                  <li key={section}>• {section}</li>
                ))}
              </ul>
            </div>
            <div className="border-t border-(--ui-stroke-tertiary) pt-5">
              <h2 className="font-semibold text-(--ui-text-primary)">{copy.privacyTitle}</h2>
              <p className="mt-1">{copy.privacyDescription}</p>
            </div>
          </aside>
        </div>
      </div>
    </section>
  )
}
