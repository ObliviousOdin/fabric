import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { $desktopOnboarding, type OnboardingContext, type OnboardingFlow } from '@/store/onboarding'
import type { OAuthProvider } from '@/types/hermes'

import { FlowPanel } from './flow'

const ctx: OnboardingContext = { requestGateway: async () => undefined as never }

function provider(id: string, name: string): OAuthProvider {
  return {
    cli_command: `hermes login ${id}`,
    docs_url: `https://example.test/${id}`,
    flow: 'device_code',
    id,
    name,
    status: { logged_in: false }
  }
}

function renderFlow(flow: OnboardingFlow) {
  render(<FlowPanel ctx={ctx} flow={flow} leaving={false} onBegin={vi.fn()} />)
}

afterEach(() => {
  cleanup()
  $desktopOnboarding.set({ ...$desktopOnboarding.get(), flow: { status: 'idle' } })
})

describe('desktop onboarding account routing', () => {
  it('shows Fabric-owned managed guidance and a server-backed request action', () => {
    renderFlow({ status: 'managed_info', profile: 'default', provider: provider('openai-codex', 'OpenAI Codex') })

    const guide = screen.getByRole('link', { name: /View enterprise guide/ })
    const email = screen.getByRole('button', { name: 'Open email handoff' })

    expect(guide.getAttribute('href')).toBe('https://obliviousodin.github.io/fabric/guides/chatgpt-codex-subscription')
    expect(email.getAttribute('href')).toBeNull()
  })

  it('shows an explicit takeover action for a conflicting OAuth ceremony', () => {
    renderFlow({
      status: 'error',
      profile: 'default',
      provider: provider('openai-codex', 'OpenAI Codex'),
      message: 'Another sign-in is already in progress for this account.',
      takeoverAvailable: true
    })

    expect(screen.getByRole('button', { name: 'Take over sign-in' })).toBeTruthy()
  })

  it('warns users never to forward a device code', () => {
    renderFlow({
      status: 'polling',
      profile: 'default',
      provider: provider('xai-oauth', 'xAI Grok'),
      copied: false,
      start: {
        expires_in: 900,
        flow: 'device_code',
        poll_interval: 5,
        session_id: 'local-session',
        user_code: 'GROK-1234',
        verification_url: 'https://auth.example.test/device'
      }
    })

    expect(screen.getByText(/Never forward this device code by email or chat/)).toBeTruthy()
  })

  it('requires an explicit choice when a local endpoint advertises multiple models', () => {
    const flow: Extract<OnboardingFlow, { status: 'confirming_local_model' }> = {
      status: 'confirming_local_model',
      apiKey: '',
      baseUrl: 'http://127.0.0.1:11434/v1',
      currentModel: '',
      localProvider: 'custom',
      models: ['llama3.2:3b', 'qwen2.5-coder:7b'],
      profile: 'default',
      saving: false
    }

    $desktopOnboarding.set({ ...$desktopOnboarding.get(), flow })
    renderFlow(flow)

    expect((screen.getByRole('button', { name: 'Connect' }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(screen.getByRole('option', { name: 'qwen2.5-coder:7b' }))

    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'confirming_local_model',
      currentModel: 'qwen2.5-coder:7b'
    })
  })
})
