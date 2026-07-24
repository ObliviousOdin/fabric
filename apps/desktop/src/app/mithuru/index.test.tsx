import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { clearClarifyRequest, setClarifyRequest } from '@/store/clarify'
import { $gateway } from '@/store/gateway'
import { clearAllPrompts, setApprovalRequest, setSecretRequest, setSudoRequest } from '@/store/prompts'
import { $activeSessionId } from '@/store/session'

import { MithuruSimpleMode } from '.'

const profile = `mithuru-test-${Math.random()}`

function renderMode(overrides: Partial<React.ComponentProps<typeof MithuruSimpleMode>> = {}) {
  const props = {
    attachments: [],
    busy: false,
    connected: true,
    messages: [],
    onChooseDocument: vi.fn(),
    onClearAttachments: vi.fn(),
    onExit: vi.fn(),
    onRemoveAttachment: vi.fn(),
    onRespondToApproval: vi.fn(async () => undefined),
    onSubmit: vi.fn(() => true),
    onTranscribeAudio: vi.fn(async () => 'test transcript'),
    profile,
    speechToTextEnabled: true,
    ...overrides
  } satisfies React.ComponentProps<typeof MithuruSimpleMode>

  return render(<MithuruSimpleMode {...props} />)
}

afterEach(() => {
  cleanup()
  clearAllPrompts()
  clearClarifyRequest()
  $gateway.set(null)
  $activeSessionId.set(null)
  window.localStorage.clear()
})

describe('Mithuru Simple Mode', () => {
  it('finishes one-question-at-a-time onboarding and shows the simple home', () => {
    renderMode()

    expect(screen.getByRole('heading', { name: 'Which language would you like?' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'English (Sri Lanka)' }))
    expect(screen.getByRole('heading', { name: 'How would you like to use Mithuru?' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Speak and listen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Large' }))
    fireEvent.click(screen.getByRole('button', { name: 'Normal' }))
    fireEvent.click(screen.getByRole('button', { name: 'No' }))
    fireEvent.click(screen.getByRole('button', { name: 'No' }))

    expect(screen.getByRole('button', { name: 'Talk' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Standard Fabric' })).toBeTruthy()
    expect(screen.queryByText(/provider|model|token/i)).toBeNull()
  })

  it('lets a user leave Simple Mode before completing onboarding', () => {
    const onExit = vi.fn()

    renderMode({ onExit, profile: `${profile}-onboarding-exit` })
    fireEvent.click(screen.getByRole('button', { name: 'Standard Fabric' }))

    expect(onExit).toHaveBeenCalledTimes(1)
  })

  it('keeps the recognized transcript editable before sending', async () => {
    const completedProfile = `${profile}-completed`
    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({
        onboardingCompleted: true,
        preferences: {
          experienceMode: 'simple',
          preferredLocale: 'en-LK',
          interactionMode: 'both',
          voiceEnabled: true,
          cloudSpeechAllowed: false,
          speechRate: 1,
          textScale: 'large',
          caregiverModeConfigured: false
        }
      })
    )

    renderMode({ profile: completedProfile })
    const input = screen.getByRole('textbox', { name: 'Correct what I heard' })

    fireEvent.change(input, { target: { value: 'Corrected request' } })
    expect(input).toHaveProperty('value', 'Corrected request')
    expect(screen.getByRole('button', { name: 'Send' })).toBeTruthy()
  })

  it('skips voice-only questions and controls when text-only mode is selected', () => {
    const textProfile = `${profile}-text-only`

    renderMode({ profile: textProfile })
    fireEvent.click(screen.getByRole('button', { name: 'English (Sri Lanka)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Read and type' }))
    fireEvent.click(screen.getByRole('button', { name: 'Large' }))

    expect(screen.getByRole('heading', { name: 'Is a family member helping with setup?' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'No' }))

    expect(screen.queryByRole('button', { name: 'Talk' })).toBeNull()
    expect(screen.queryByText('Can Mithuru use an online speech service?')).toBeNull()
    expect(JSON.parse(window.localStorage.getItem(`fabric.desktop.mithuru.v1:${textProfile}`) ?? '{}')).toMatchObject({
      onboardingCompleted: true,
      preferences: { cloudSpeechAllowed: false, interactionMode: 'text', voiceEnabled: false }
    })
  })

  it('persists the final online-speech choice from onboarding', () => {
    const cloudProfile = `${profile}-cloud-choice`

    renderMode({ profile: cloudProfile })
    fireEvent.click(screen.getByRole('button', { name: 'English (Sri Lanka)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Speak and listen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Large' }))
    fireEvent.click(screen.getByRole('button', { name: 'Normal' }))
    fireEvent.click(screen.getByRole('button', { name: 'No' }))
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))

    expect(JSON.parse(window.localStorage.getItem(`fabric.desktop.mithuru.v1:${cloudProfile}`) ?? '{}')).toMatchObject({
      onboardingCompleted: true,
      preferences: { cloudSpeechAllowed: true }
    })
  })

  it('does not send microphone audio without explicit online-speech consent', () => {
    const completedProfile = `${profile}-no-cloud`
    const onTranscribeAudio = vi.fn(async () => 'must not run')
    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({
        onboardingCompleted: true,
        preferences: {
          experienceMode: 'simple',
          preferredLocale: 'en-LK',
          interactionMode: 'both',
          voiceEnabled: true,
          cloudSpeechAllowed: false,
          speechRate: 1,
          textScale: 'large',
          caregiverModeConfigured: false
        }
      })
    )

    renderMode({ onTranscribeAudio, profile: completedProfile })
    fireEvent.click(screen.getByRole('button', { name: 'Talk' }))

    expect(onTranscribeAudio).not.toHaveBeenCalled()
    expect(
      screen.getByText(
        'Online speech is off, so no audio was uploaded. Turn it on under Speech privacy or type instead.'
      )
    ).toBeTruthy()
  })

  it('allows only one response for the exact pending approval', async () => {
    const completedProfile = `${profile}-approval`
    let releaseResponse: (() => void) | undefined

    const onRespondToApproval = vi.fn(
      () =>
        new Promise<void>(resolve => {
          releaseResponse = resolve
        })
    )

    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({ onboardingCompleted: true, preferences: { experienceMode: 'simple' } })
    )
    $activeSessionId.set('session-mithuru')
    setApprovalRequest({
      allowPermanent: true,
      command: 'delete the selected export',
      description: 'Delete an export',
      requestId: 'approval-mithuru',
      sessionId: 'session-mithuru'
    })

    renderMode({ onRespondToApproval, profile: completedProfile })
    const allowOnce = screen.getByRole('button', { name: 'Allow once' })

    expect(document.activeElement).toBe(allowOnce)
    expect(screen.getByRole('textbox', { name: 'Correct what I heard' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Call or message family' })).toHaveProperty('disabled', true)
    fireEvent.click(allowOnce)
    fireEvent.click(screen.getByRole('button', { name: 'Deny' }))

    expect(screen.queryByRole('button', { name: /always/i })).toBeNull()
    expect(onRespondToApproval).toHaveBeenCalledTimes(1)
    expect(onRespondToApproval).toHaveBeenCalledWith('session-mithuru', 'approval-mithuru', 'approve')
    releaseResponse?.()
    await waitFor(() => expect(allowOnce).toHaveProperty('disabled', false))
  })

  it('requires document disclosure before opening the existing attachment picker', () => {
    const completedProfile = `${profile}-document`
    const onChooseDocument = vi.fn()
    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({ onboardingCompleted: true, preferences: { experienceMode: 'simple' } })
    )

    renderMode({ onChooseDocument, profile: completedProfile })
    fireEvent.click(screen.getByRole('button', { name: 'Explain a letter' }))

    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(onChooseDocument).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Yes, continue' }))
    expect(onChooseDocument).toHaveBeenCalledTimes(1)
  })

  it('mounts clarification, sudo, and secret response surfaces in Simple Mode', () => {
    const completedProfile = `${profile}-blocking-prompts`
    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({ onboardingCompleted: true, preferences: { experienceMode: 'simple' } })
    )
    $activeSessionId.set('session-prompts')

    setClarifyRequest({
      choices: ['Today', 'Tomorrow'],
      question: 'Which day?',
      requestId: 'clarify-mithuru',
      sessionId: 'session-prompts'
    })
    renderMode({ profile: completedProfile })
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Which day?' })).toBeTruthy()

    cleanup()
    clearClarifyRequest()
    setSudoRequest({ requestId: 'sudo-mithuru', sessionId: 'session-prompts' })
    renderMode({ profile: completedProfile })
    expect(document.querySelector('input[type="password"]')).toBeTruthy()

    cleanup()
    clearAllPrompts()
    setSecretRequest({
      envVar: 'EXAMPLE_TOKEN',
      prompt: 'Enter the token',
      requestId: 'secret-mithuru',
      sessionId: 'session-prompts'
    })
    renderMode({ profile: completedProfile })
    expect(screen.getByRole('heading', { name: 'EXAMPLE_TOKEN' })).toBeTruthy()
    expect(document.querySelector('input[type="password"]')).toBeTruthy()
  })

  it('allows only one response for the exact blocking prompt', async () => {
    const completedProfile = `${profile}-prompt-lock`
    let releaseResponse: (() => void) | undefined

    const request = vi.fn(
      () =>
        new Promise<{ request_id: string }>(resolve => {
          releaseResponse = () => resolve({ request_id: 'clarify-locked' })
        })
    )

    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({ onboardingCompleted: true, preferences: { experienceMode: 'simple' } })
    )
    $gateway.set({ request } as unknown as ReturnType<typeof $gateway.get>)
    $activeSessionId.set('session-prompts')
    setClarifyRequest({
      choices: ['Today', 'Tomorrow'],
      question: 'Which day?',
      requestId: 'clarify-locked',
      sessionId: 'session-prompts'
    })

    renderMode({ profile: completedProfile })
    fireEvent.click(screen.getByRole('button', { name: 'Today' }))
    fireEvent.click(screen.getByRole('button', { name: 'Tomorrow' }))

    expect(request).toHaveBeenCalledTimes(1)
    expect(request).toHaveBeenCalledWith('clarify.respond', {
      answer: 'Today',
      request_id: 'clarify-locked',
      session_id: 'session-prompts'
    })
    releaseResponse?.()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('requires staged attachments to be visible and reviewed before send', () => {
    const completedProfile = `${profile}-attachments`
    const onRemoveAttachment = vi.fn()
    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({ onboardingCompleted: true, preferences: { experienceMode: 'simple' } })
    )

    renderMode({
      attachments: [{ id: 'attachment-1', kind: 'file', label: 'medical-letter.pdf' }],
      onRemoveAttachment,
      profile: completedProfile
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Correct what I heard' }), {
      target: { value: 'Explain this' }
    })

    const send = screen.getByRole('button', { name: 'Send' })
    expect(screen.getByText('medical-letter.pdf')).toBeTruthy()
    expect(send).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('button', { name: 'Review and include these documents' }))
    expect(send).toHaveProperty('disabled', false)
    fireEvent.click(screen.getByRole('button', { name: 'Remove medical-letter.pdf' }))
    expect(onRemoveAttachment).toHaveBeenCalledWith('attachment-1')
  })

  it('blocks review and send while an attachment upload is unresolved', () => {
    const completedProfile = `${profile}-attachment-upload`
    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({ onboardingCompleted: true, preferences: { experienceMode: 'simple' } })
    )

    renderMode({
      attachments: [{ id: 'attachment-uploading', kind: 'file', label: 'pending.pdf', uploadState: 'uploading' }],
      profile: completedProfile
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Correct what I heard' }), {
      target: { value: 'Explain this' }
    })

    expect(screen.getByRole('button', { name: 'Review and include these documents' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Send' })).toHaveProperty('disabled', true)
  })

  it('consumes reviewed attachments after a successful send', async () => {
    const completedProfile = `${profile}-attachment-consume`
    const onClearAttachments = vi.fn()
    const onSubmit = vi.fn(() => true)
    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({ onboardingCompleted: true, preferences: { experienceMode: 'simple' } })
    )

    renderMode({
      attachments: [{ id: 'attachment-1', kind: 'file', label: 'medical-letter.pdf' }],
      onClearAttachments,
      onSubmit,
      profile: completedProfile
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Correct what I heard' }), {
      target: { value: 'Explain this' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Review and include these documents' }))
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(onSubmit).toHaveBeenCalledWith('Explain this')
    await waitFor(() => expect(onClearAttachments).toHaveBeenCalledTimes(1))
  })

  it('allows persisted online-speech consent to be revoked immediately', () => {
    const completedProfile = `${profile}-revoke-cloud`
    window.localStorage.setItem(
      `fabric.desktop.mithuru.v1:${completedProfile}`,
      JSON.stringify({
        onboardingCompleted: true,
        preferences: { experienceMode: 'simple', interactionMode: 'both', voiceEnabled: true, cloudSpeechAllowed: true }
      })
    )

    renderMode({ profile: completedProfile })
    fireEvent.click(screen.getByRole('button', { name: 'Speech privacy' }))
    fireEvent.click(screen.getByRole('button', { name: 'Turn off online speech' }))

    expect(
      JSON.parse(window.localStorage.getItem(`fabric.desktop.mithuru.v1:${completedProfile}`) ?? '{}')
    ).toMatchObject({
      preferences: { cloudSpeechAllowed: false }
    })
  })
})
