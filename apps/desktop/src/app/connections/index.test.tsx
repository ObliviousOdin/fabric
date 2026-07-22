// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { McpCatalogEntry, MessagingPlatformInfo, OAuthProvider } from '@/types/fabric'

const getMessagingPlatforms = vi.fn()
const getMcpCatalog = vi.fn()
const listOAuthProviders = vi.fn()
const updateMessagingPlatform = vi.fn()
const startManualProviderOAuth = vi.fn()

vi.mock('@/fabric', () => ({
  getMessagingPlatforms: () => getMessagingPlatforms(),
  getMcpCatalog: () => getMcpCatalog(),
  listOAuthProviders: () => listOAuthProviders(),
  updateMessagingPlatform: (id: string, body: unknown) => updateMessagingPlatform(id, body)
}))

vi.mock('@/store/notifications', () => ({
  notify: vi.fn(),
  notifyError: vi.fn()
}))

vi.mock('@/store/system-actions', () => ({
  runGatewayRestart: vi.fn()
}))

vi.mock('@/store/onboarding', () => ({
  startManualProviderOAuth: (id: string) => startManualProviderOAuth(id)
}))

function platform(patch: Partial<MessagingPlatformInfo> = {}): MessagingPlatformInfo {
  return {
    configured: true,
    description: 'A platform.',
    docs_url: '',
    enabled: false,
    env_vars: [],
    gateway_running: true,
    id: 'slack',
    name: 'Slack',
    state: 'disabled',
    ...patch
  }
}

function tool(patch: Partial<McpCatalogEntry> = {}): McpCatalogEntry {
  return {
    args: [],
    auth_type: 'oauth',
    bootstrap: [],
    command: null,
    default_enabled: null,
    description: 'Work with issues and PRs.',
    enabled: false,
    install_ref: null,
    install_url: null,
    installed: false,
    name: 'github',
    needs_install: false,
    post_install: '',
    required_env: [],
    source: 'curated',
    transport: 'http',
    url: 'https://example.test/mcp',
    ...patch
  }
}

function provider(patch: Partial<OAuthProvider> = {}): OAuthProvider {
  return {
    cli_command: '',
    docs_url: '',
    flow: 'pkce',
    id: 'anthropic',
    name: 'Anthropic',
    status: { logged_in: false },
    ...patch
  }
}

beforeEach(() => {
  getMessagingPlatforms.mockResolvedValue({ platforms: [platform()] })
  getMcpCatalog.mockResolvedValue({ diagnostics: [], entries: [tool()] })
  listOAuthProviders.mockResolvedValue({ providers: [provider()] })
  updateMessagingPlatform.mockResolvedValue({ ok: true, platform: 'slack' })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

async function renderConnections() {
  const { ConnectionsView } = await import('./index')

  return render(
    <MemoryRouter>
      <ConnectionsView />
    </MemoryRouter>
  )
}

describe('ConnectionsView', () => {
  it('federates messaging, tool, and account connections into one hub', async () => {
    await renderConnections()

    // Messaging platform (real gateway status) + curated tool + provider account
    // all render on the same page.
    expect(await screen.findByText('Slack')).toBeTruthy()
    expect(screen.getByText('Github')).toBeTruthy()
    expect(screen.getByText('Anthropic')).toBeTruthy()
    // Network section is always present (gateway + tailscale remote access).
    expect(screen.getByText('Tailscale remote access')).toBeTruthy()
  })

  it('enables a messaging platform inline without leaving the hub', async () => {
    await renderConnections()

    const toggle = await screen.findByRole('switch', { name: 'Enable Slack' })
    fireEvent.click(toggle)

    await waitFor(() => expect(updateMessagingPlatform).toHaveBeenCalledWith('slack', { enabled: true }))
  })

  it('starts provider sign-in from an account card', async () => {
    await renderConnections()

    const connect = await screen.findByRole('button', { name: 'Connect' })
    fireEvent.click(connect)

    await waitFor(() => expect(startManualProviderOAuth).toHaveBeenCalledWith('anthropic'))
  })

  it('degrades gracefully when a source fails to load', async () => {
    getMcpCatalog.mockRejectedValue(new Error('offline'))

    await renderConnections()

    // Messaging still renders even though the tool catalog failed.
    expect(await screen.findByText('Slack')).toBeTruthy()
  })

  it('leads an unconfigured platform with Set up, not a misleading toggle', async () => {
    getMessagingPlatforms.mockResolvedValue({ platforms: [platform({ configured: false, state: 'not_configured' })] })
    // Keep the tool catalog empty so the only "Set up" affordance is the
    // messaging card's (an uninstalled tool would also render one).
    getMcpCatalog.mockResolvedValue({ diagnostics: [], entries: [] })

    await renderConnections()

    expect(await screen.findByRole('button', { name: 'Set up' })).toBeTruthy()
    expect(screen.queryByRole('switch', { name: 'Enable Slack' })).toBeNull()
  })

  it('shows a retry affordance for a failed section instead of hiding it', async () => {
    getMcpCatalog.mockRejectedValue(new Error('offline'))

    await renderConnections()

    // The Tools heading and a retry control survive a catalog failure.
    expect(await screen.findByText('Slack')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })
})
