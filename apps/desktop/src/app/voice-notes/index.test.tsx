// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const recorder = vi.hoisted(() => ({
  handle: {
    cancel: vi.fn(),
    start: vi.fn(),
    stop: vi.fn()
  },
  level: 0.4,
  recording: false
}))

vi.mock('@/app/chat/composer/hooks/use-mic-recorder', () => ({
  useMicRecorder: () => recorder
}))

import { VoiceNotesView } from './index'

beforeEach(() => {
  recorder.handle.cancel.mockReset()
  recorder.handle.start.mockReset().mockResolvedValue(undefined)
  recorder.handle.stop.mockReset().mockResolvedValue({
    audio: new Blob(['voice'], { type: 'audio/webm;codecs=opus' }),
    durationMs: 4200,
    heardSpeech: true
  })
})

afterEach(() => cleanup())

describe('VoiceNotesView', () => {
  it('guides an STT-disabled user to provider settings', () => {
    const configure = vi.fn()

    render(
      <VoiceNotesView
        maxRecordingSeconds={120}
        onConfigureSpeechToText={configure}
        onCreateNote={vi.fn()}
        onTranscribeAudio={vi.fn()}
        sttEnabled={false}
      />
    )

    expect(screen.getByRole('button', { name: 'Start recording' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('button', { name: 'Configure speech-to-text' }))
    expect(configure).toHaveBeenCalledOnce()
  })

  it('records, transcribes, reviews, and hands a grounded Markdown prompt to Fabric', async () => {
    const createNote = vi.fn()
    const transcribe = vi.fn().mockResolvedValue('Alice will draft the release note.')

    render(
      <VoiceNotesView
        maxRecordingSeconds={120}
        onConfigureSpeechToText={vi.fn()}
        onCreateNote={createNote}
        onTranscribeAudio={transcribe}
        sttEnabled
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
    await waitFor(() => expect(recorder.handle.start).toHaveBeenCalledOnce())

    fireEvent.click(await screen.findByRole('button', { name: 'Stop and transcribe' }))

    const transcript = await screen.findByLabelText('Transcript')
    expect(transcribe).toHaveBeenCalledOnce()
    expect(transcript).toHaveProperty('value', 'Alice will draft the release note.')

    fireEvent.change(transcript, { target: { value: 'Alice will draft and publish the release note.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create note with Fabric' }))

    expect(createNote).toHaveBeenCalledOnce()
    expect(createNote.mock.calls[0]?.[0].transcript).toBe('Alice will draft and publish the release note.')
    expect(createNote.mock.calls[0]?.[0].prompt).toContain(
      JSON.stringify('Alice will draft and publish the release note.')
    )
    expect(createNote.mock.calls[0]?.[0].prompt).toContain('## Decisions\n## Tasks\n## Follow-up\n## Transcript')
  })

  it('keeps a failed recording available for an explicit transcription retry', async () => {
    const transcribe = vi
      .fn()
      .mockRejectedValueOnce(new Error('Provider unavailable'))
      .mockResolvedValueOnce('Retry worked')

    render(
      <VoiceNotesView
        maxRecordingSeconds={120}
        onConfigureSpeechToText={vi.fn()}
        onCreateNote={vi.fn()}
        onTranscribeAudio={transcribe}
        sttEnabled
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Stop and transcribe' }))

    expect(await screen.findByText('Provider unavailable')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry transcription' }))

    expect(await screen.findByDisplayValue('Retry worked')).toBeTruthy()
    expect(transcribe).toHaveBeenCalledTimes(2)
  })
})
