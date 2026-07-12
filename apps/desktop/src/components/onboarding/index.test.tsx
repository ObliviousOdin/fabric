import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $desktopOnboarding,
  clearPendingProviderOAuth,
  type DesktopOnboardingState,
  type OnboardingContext,
  startManualProviderOAuth
} from '@/store/onboarding'
import type { OAuthProvider } from '@/types/hermes'

import { DesktopOnboardingOverlay, Picker } from '.'

function provider(id: string, name = id): OAuthProvider {
  return {
    cli_command: `hermes login ${id}`,
    docs_url: `https://example.com/${id}`,
    flow: 'pkce',
    id,
    name,
    status: { logged_in: false }
  }
}

function setProviders(providers: OAuthProvider[]) {
  $desktopOnboarding.set({
    configured: false,
    flow: { status: 'idle' },
    mode: 'oauth',
    providers,
    reason: null,
    requested: false,
    firstRunSkipped: false,
    manual: false,
    localEndpoint: false
  } satisfies DesktopOnboardingState)
}

const ctx: OnboardingContext = { requestGateway: async () => undefined as never }

beforeEach(() => {
  // Node 22 can expose an unavailable experimental global localStorage that
  // shadows jsdom's implementation unless --localstorage-file is supplied.
  // Keep this unit test hermetic instead of depending on the runner flag.
  if (!window.localStorage) {
    const values = new Map<string, string>()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        clear: () => values.clear(),
        getItem: (key: string) => values.get(key) ?? null,
        key: (index: number) => [...values.keys()][index] ?? null,
        get length() {
          return values.size
        },
        removeItem: (key: string) => values.delete(key),
        setItem: (key: string, value: string) => values.set(key, String(value))
      } satisfies Storage
    })
  }
})

afterEach(() => {
  cleanup()
  clearPendingProviderOAuth()

  try {
    window.localStorage.clear()
  } catch {
    // jsdom localStorage should always be present; ignore if not.
  }

  $desktopOnboarding.set({
    configured: null,
    flow: { status: 'idle' },
    mode: 'oauth',
    providers: null,
    reason: null,
    requested: false,
    firstRunSkipped: false,
    manual: false,
    localEndpoint: false
  })
  Reflect.deleteProperty(window, 'hermesDesktop')
  vi.restoreAllMocks()
})

describe('onboarding Picker', () => {
  it('shows every provider uniformly without a featured badge or disclosure', () => {
    setProviders([provider('anthropic', 'Anthropic Claude'), provider('nous', 'Nous Portal')])
    render(<Picker ctx={ctx} />)

    expect(screen.getByText('Nous Portal')).toBeTruthy()
    expect(screen.getByText('Anthropic API Key')).toBeTruthy()
    expect(screen.queryByText('Recommended')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Other providers' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Collapse' })).toBeNull()
  })

  it('shows every provider directly when Nous Portal is absent', () => {
    setProviders([
      provider('anthropic', 'Anthropic Claude'),
      provider('openai-codex', 'OpenAI Codex / ChatGPT'),
      provider('xai-oauth', 'xAI Grok')
    ])
    render(<Picker ctx={ctx} />)

    expect(screen.getByText('Anthropic API Key')).toBeTruthy()
    expect(screen.getByText('ChatGPT subscription (OpenAI Codex)')).toBeTruthy()
    expect(screen.getByText('Grok subscription (xAI)')).toBeTruthy()
    expect(screen.queryByText('Other sign-in options')).toBeNull()
    expect(screen.queryByText('Recommended')).toBeNull()
  })

  it('offers native Ollama directly without routing through API-key or OAuth setup', async () => {
    setProviders([provider('nous', 'Nous Portal')])
    render(<Picker ctx={ctx} />)

    fireEvent.click(screen.getByRole('button', { name: /Ollama \(native local\)/ }))

    expect($desktopOnboarding.get().mode).toBe('ollama')
    expect(await screen.findByPlaceholderText('http://127.0.0.1:11434')).toBeTruthy()
    expect(screen.queryByPlaceholderText('Paste API key')).toBeNull()
  })

  it('offers "choose later" on first run and persists the skip', () => {
    setProviders([provider('nous', 'Nous Portal')])
    render(<Picker ctx={ctx} />)

    const skip = screen.getByRole('button', { name: "I'll choose a provider later" })

    fireEvent.click(skip)

    expect($desktopOnboarding.get().firstRunSkipped).toBe(true)
    expect(window.localStorage.getItem('hermes-onboarding-skipped-v1')).toBe('1')
  })

  it('hides "choose later" in manual (add-provider) mode', () => {
    setProviders([provider('nous', 'Nous Portal')])
    $desktopOnboarding.set({ ...$desktopOnboarding.get(), manual: true })
    render(<Picker ctx={ctx} />)

    expect(screen.queryByRole('button', { name: "I'll choose a provider later" })).toBeNull()
  })

  it('routes the direct Settings handoff through account ownership before OAuth starts', async () => {
    const selected = provider('openai-codex', 'OpenAI Codex / ChatGPT')

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/oauth') {
        return { providers: [selected] }
      }

      if (path.startsWith('/api/model/options')) {
        return { providers: [] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    Object.defineProperty(window, 'hermesDesktop', {
      configurable: true,
      value: { api }
    })
    setProviders([selected])
    $desktopOnboarding.set({ ...$desktopOnboarding.get(), configured: true })

    startManualProviderOAuth(selected.id)
    render(<DesktopOnboardingOverlay enabled={false} requestGateway={async () => undefined as never} />)

    await waitFor(() => expect($desktopOnboarding.get().flow.status).toBe('choosing_account'))

    expect(screen.getByText('Which account should this Fabric use?')).toBeTruthy()
    expect(screen.getByRole('button', { name: /My account/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Fabric-managed/ })).toBeTruthy()
    expect(api.mock.calls.some(([request]) => request.path.endsWith('/start'))).toBe(false)
  })
})
