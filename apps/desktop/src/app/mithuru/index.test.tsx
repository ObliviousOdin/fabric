import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { clearAllPrompts, setApprovalRequest } from '@/store/prompts'
import { $activeSessionId } from '@/store/session'

import { MithuruSimpleMode } from '.'

const profile = `mithuru-test-${Math.random()}`

function renderMode(overrides: Partial<React.ComponentProps<typeof MithuruSimpleMode>> = {}) {
  return render(
    <MithuruSimpleMode
      busy={false}
      connected
      messages={[]}
      onChooseDocument={vi.fn()}
      onExit={vi.fn()}
      onRespondToApproval={vi.fn()}
      onSubmit={vi.fn(() => true)}
      onTranscribeAudio={vi.fn(async () => 'test transcript')}
      profile={profile}
      speechToTextEnabled
      {...overrides}
    />
  )
}

afterEach(() => {
  cleanup()
  clearAllPrompts()
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
      screen.getByText('This language is not available for speech on this device. You can type instead.')
    ).toBeTruthy()
  })

  it('shows only allow-once and deny controls for the exact pending approval', () => {
    const completedProfile = `${profile}-approval`
    const onRespondToApproval = vi.fn()
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
    expect(onRespondToApproval).toHaveBeenNthCalledWith(1, 'session-mithuru', 'approval-mithuru', 'approve')
    expect(onRespondToApproval).toHaveBeenNthCalledWith(2, 'session-mithuru', 'approval-mithuru', 'reject')
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
})
