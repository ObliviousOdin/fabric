import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { requestModelOptions } from '@/lib/model-options'
import * as notifications from '@/store/notifications'
import { $activeGatewayProfile } from '@/store/profile'
import type { OAuthProvider } from '@/types/hermes'

import {
  $desktopOnboarding,
  cancelOnboardingFlow,
  clearPendingProviderOAuth,
  closeManualOnboarding,
  confirmOnboardingLocalModel,
  confirmOnboardingModel,
  continuePersonalProviderOAuth,
  type DesktopOnboardingState,
  type OnboardingContext,
  peekPendingProviderOAuth,
  recheckExternalSignin,
  refreshOnboarding,
  requestDesktopOnboarding,
  requestManagedProviderAccess,
  saveOnboardingApiKey,
  saveOnboardingLocalEndpoint,
  saveOnboardingNativeOllama,
  setOnboardingLocalModel,
  setOnboardingMode,
  setOnboardingModel,
  showManagedProviderInfo,
  showProviderAccountChoice,
  startManualProviderOAuth,
  startProviderOAuth,
  submitOnboardingCode,
  takeoverProviderOAuth
} from './onboarding'

function provider(id: string, name = id): OAuthProvider {
  return {
    cli_command: `fabric login ${id}`,
    docs_url: `https://example.com/${id}`,
    flow: 'pkce',
    id,
    name,
    status: { logged_in: false }
  }
}

function deviceProvider(id: string, name = id): OAuthProvider {
  return { ...provider(id, name), flow: 'device_code' }
}

function baseState(overrides: Partial<DesktopOnboardingState> = {}): DesktopOnboardingState {
  return {
    configured: false,
    flow: { status: 'idle' },
    mode: 'oauth',
    providers: null,
    reason: null,
    requested: false,
    firstRunSkipped: false,
    manual: false,
    localEndpoint: false,
    ...overrides
  }
}

function installApiMock(api: (request: { path: string }) => Promise<unknown>) {
  const openExternal = vi.fn(async (_url: string): Promise<unknown> => true)
  Object.defineProperty(window, 'fabricDesktop', {
    configurable: true,
    value: { api, openExternal }
  })

  return openExternal
}

function managedAccessFixture() {
  const request = {
    request_id: 'par_0123456789abcdef01234567',
    provider_id: 'openai-codex',
    status: 'requested',
    handoff_state: 'offered',
    device_label: 'Fabric Desktop',
    requested_at: '2026-07-11T12:00:00Z',
    updated_at: '2026-07-11T12:00:00Z',
    expires_at: '2026-07-18T12:00:00Z',
    notification_handoff_at: null,
    decision_at: null,
    decision_source: null,
    decision_reason: null
  }

  const snapshot = (revision: number) => ({
    provider_id: 'openai-codex',
    revision,
    ownership_epoch: revision === 0 ? 0 : 1,
    desired_ownership: revision === 0 ? 'unselected' : 'fabric_managed',
    active_request_id: revision === 0 ? null : request.request_id,
    active_request: revision === 0 ? null : request,
    pruned_terminal_count: 0,
    requests: revision === 0 ? [] : [request],
    handoff:
      revision === 0
        ? null
        : {
            channel: 'email',
            delivery_verified: false,
            uri: 'mailto:server-owned@example.test?subject=SERVER%20OWNED'
          }
  })

  return { request, snapshot }
}

function runtimeMismatchGateway(): OnboardingContext['requestGateway'] {
  return async method => {
    if (method === 'setup.status') {
      return { provider_configured: true } as never
    }

    if (method === 'setup.runtime_check') {
      return { error: 'Selected runtime is not available.', ok: false } as never
    }

    throw new Error(`unexpected gateway method: ${method}`)
  }
}

function onboardingContext(requestGateway: OnboardingContext['requestGateway']): OnboardingContext {
  return { requestGateway }
}

function ensureLocalStorage() {
  // Node 22 can expose an unavailable experimental global localStorage that
  // shadows jsdom's implementation unless --localstorage-file is supplied.
  if (window.localStorage) {
    return
  }

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

function fallbackTimeoutGateway(): OnboardingContext['requestGateway'] {
  return async method => {
    if (method === 'setup.status' || method === 'setup.runtime_check') {
      throw new Error(`request timed out: ${method}`)
    }

    throw new Error(`unexpected gateway method: ${method}`)
  }
}

describe('refreshOnboarding', () => {
  beforeEach(() => {
    ensureLocalStorage()
    window.localStorage.clear()
    $desktopOnboarding.set(baseState())
  })

  afterEach(() => {
    window.localStorage.clear()
    $desktopOnboarding.set(baseState())
    vi.restoreAllMocks()
  })

  it('refreshes OAuth providers again when onboarding was explicitly requested', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/oauth') {
        return { providers: [provider('fresh')] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $desktopOnboarding.set(baseState({ providers: [provider('cached')] }))
    requestDesktopOnboarding('Need provider setup')

    const ready = await refreshOnboarding(onboardingContext(runtimeMismatchGateway()))

    expect(ready).toBe(false)
    expect(api).toHaveBeenCalledTimes(1)
    expect($desktopOnboarding.get().providers?.map(p => p.id)).toEqual(['fresh'])
    expect($desktopOnboarding.get().reason).toContain('Selected runtime is not available.')
    expect($desktopOnboarding.get().reason).toContain('setup.status reports configured credentials')
  })

  it('keeps cached providers when onboarding was not re-requested', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/oauth') {
        return { providers: [provider('fresh')] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $desktopOnboarding.set(baseState({ providers: [provider('cached')] }))

    const ready = await refreshOnboarding(onboardingContext(runtimeMismatchGateway()))

    expect(ready).toBe(false)
    expect(api).not.toHaveBeenCalled()
    expect($desktopOnboarding.get().providers?.map(p => p.id)).toEqual(['cached'])
  })

  it('does not downgrade configured=true on fallback-only readiness failures', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/oauth') {
        return { providers: [provider('fresh')] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    // Simulate a returning user: cache is set and store is configured.
    window.localStorage.setItem('hermes-desktop-onboarded-v1', '1')
    $desktopOnboarding.set(
      baseState({
        configured: true,
        providers: [provider('cached')],
        reason: null,
        requested: false
      })
    )

    const ready = await refreshOnboarding(onboardingContext(fallbackTimeoutGateway()))

    expect(ready).toBe(false)
    expect(api).not.toHaveBeenCalled()
    expect($desktopOnboarding.get().configured).toBe(true)
    expect($desktopOnboarding.get().reason).toBeNull()
    // The cache must survive the refresh — proving we didn't downgrade.
    expect(window.localStorage.getItem('hermes-desktop-onboarded-v1')).toBe('1')
  })

  it('shows a non-blocking notification when preserving configured on fallback', async () => {
    const notifySpy = vi.spyOn(notifications, 'notify')

    installApiMock(vi.fn())
    $desktopOnboarding.set(
      baseState({
        configured: true,
        providers: [provider('cached')],
        reason: null,
        requested: false
      })
    )

    await refreshOnboarding(onboardingContext(fallbackTimeoutGateway()))

    expect(notifySpy).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'runtime-not-ready',
        kind: 'error'
      })
    )
    expect($desktopOnboarding.get().configured).toBe(true)
  })

  it('does not preserve configured when onboarding was explicitly requested', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/oauth') {
        return { providers: [provider('fresh')] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $desktopOnboarding.set(
      baseState({
        configured: true,
        providers: [provider('cached')],
        reason: null,
        requested: true
      })
    )

    const ready = await refreshOnboarding(onboardingContext(fallbackTimeoutGateway()))

    expect(ready).toBe(false)
    // requested overrides preservation — should downgrade.
    expect($desktopOnboarding.get().configured).toBe(false)
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('still surfaces onboarding when fallback failure happens before configured state', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/oauth') {
        return { providers: [provider('fresh')] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $desktopOnboarding.set(baseState({ configured: false, providers: null, requested: true }))

    const ready = await refreshOnboarding(onboardingContext(fallbackTimeoutGateway()))

    expect(ready).toBe(false)
    expect(api).toHaveBeenCalledTimes(1)
    expect($desktopOnboarding.get().configured).toBe(false)
    expect($desktopOnboarding.get().reason).toContain('request timed out')
  })

  it('deduplicates concurrent provider refresh calls', async () => {
    let resolveProviders!: (value: { providers: OAuthProvider[] }) => void

    const providersPromise = new Promise<{ providers: OAuthProvider[] }>(resolve => {
      resolveProviders = value => {
        resolve(value)
      }
    })

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/oauth') {
        return providersPromise
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $desktopOnboarding.set(baseState({ requested: true }))

    const first = refreshOnboarding(onboardingContext(runtimeMismatchGateway()))
    const second = refreshOnboarding(onboardingContext(runtimeMismatchGateway()))

    await vi.waitFor(() => expect(api).toHaveBeenCalledTimes(1))

    resolveProviders({ providers: [provider('shared')] })
    await Promise.all([first, second])

    expect($desktopOnboarding.get().providers?.map(p => p.id)).toEqual(['shared'])
  })
})

describe('OAuth onboarding', () => {
  beforeEach(() => {
    ensureLocalStorage()
    $activeGatewayProfile.set('default')
    window.localStorage.clear()
    $desktopOnboarding.set(baseState())
  })

  afterEach(() => {
    cancelOnboardingFlow()
    clearPendingProviderOAuth()
    $activeGatewayProfile.set('default')
    window.localStorage.clear()
    $desktopOnboarding.set(baseState())
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it.each([
    ['openai-codex', 'OpenAI Codex'],
    ['xai-oauth', 'xAI Grok']
  ])('asks who owns the %s account before creating an OAuth session', async (id, name) => {
    const api = vi.fn()
    const selected = deviceProvider(id, name)

    installApiMock(api)

    await startProviderOAuth(selected, { requestGateway: vi.fn() })

    expect($desktopOnboarding.get().flow).toEqual({
      status: 'choosing_account',
      profile: 'default',
      provider: selected
    })
    expect(api).not.toHaveBeenCalled()

    showManagedProviderInfo()

    expect($desktopOnboarding.get().flow).toEqual({
      status: 'managed_info',
      profile: 'default',
      provider: selected,
      requesting: false
    })
    expect(api).not.toHaveBeenCalled()
  })

  it('opens the server-owned durable managed-access handoff', async () => {
    const selected = deviceProvider('openai-codex', 'OpenAI Codex')

    const request = {
      request_id: 'par_0123456789abcdef01234567',
      provider_id: 'openai-codex',
      status: 'requested',
      handoff_state: 'offered',
      device_label: 'Fabric Desktop',
      requested_at: '2026-07-11T12:00:00Z',
      updated_at: '2026-07-11T12:00:00Z',
      expires_at: '2026-07-18T12:00:00Z',
      notification_handoff_at: null,
      decision_at: null,
      decision_source: null,
      decision_reason: null
    }

    const snapshot = (revision: number) => ({
      provider_id: 'openai-codex',
      revision,
      ownership_epoch: revision === 0 ? 0 : 1,
      desired_ownership: revision === 0 ? 'unselected' : 'fabric_managed',
      active_request_id: revision === 0 ? null : request.request_id,
      active_request: revision === 0 ? null : request,
      pruned_terminal_count: 0,
      requests: revision === 0 ? [] : [request],
      handoff:
        revision === 0
          ? null
          : {
              channel: 'email',
              delivery_verified: false,
              uri: 'mailto:server-owned@example.test?subject=SERVER%20OWNED'
            }
    })

    const ordering: string[] = []

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/accounts/openai-codex') {
        return { created: null, request: null, snapshot: snapshot(0) }
      }

      if (path === '/api/providers/accounts/openai-codex/managed-request') {
        return { created: true, request, snapshot: snapshot(1) }
      }

      if (path === '/api/providers/accounts/openai-codex/handoff-attempted') {
        ordering.push('record-launch-attempt')
        throw new Error('handoff audit temporarily unavailable')
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const openExternal = installApiMock(api)

    openExternal.mockImplementation(async () => {
      ordering.push('invoke-email-app')

      return true
    })
    await startProviderOAuth(selected, { requestGateway: vi.fn() })
    showManagedProviderInfo()
    await requestManagedProviderAccess()

    expect(api.mock.calls.map(([value]) => value.path)).toEqual([
      '/api/providers/accounts/openai-codex',
      '/api/providers/accounts/openai-codex/managed-request',
      '/api/providers/accounts/openai-codex/handoff-attempted'
    ])
    expect(api.mock.calls[1]?.[0]).toMatchObject({
      body: { device_label: 'Fabric Desktop', expected_revision: 0 },
      profile: 'default'
    })
    expect(api.mock.calls[2]?.[0]).toMatchObject({
      body: { expected_revision: 1, request_id: request.request_id },
      profile: 'default'
    })
    expect(openExternal).toHaveBeenCalledWith('mailto:server-owned@example.test?subject=SERVER%20OWNED')
    expect(ordering).toEqual(['invoke-email-app', 'record-launch-attempt'])
    expect($desktopOnboarding.get().flow).toMatchObject({ status: 'managed_info', requesting: false })
  })

  it('records an unverified managed handoff when the email app rejects and reports the request as created', async () => {
    const selected = deviceProvider('openai-codex', 'OpenAI Codex')
    const { request, snapshot } = managedAccessFixture()

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/accounts/openai-codex') {
        return { created: null, request: null, snapshot: snapshot(0) }
      }

      if (path === '/api/providers/accounts/openai-codex/managed-request') {
        return { created: true, request, snapshot: snapshot(1) }
      }

      if (path === '/api/providers/accounts/openai-codex/handoff-attempted') {
        return {
          created: null,
          request: { ...request, handoff_state: 'launch_attempted_unverified' },
          snapshot: snapshot(2)
        }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const openExternal = installApiMock(api)

    openExternal.mockResolvedValue(false)
    await startProviderOAuth(selected, { requestGateway: vi.fn() })
    showManagedProviderInfo()
    await requestManagedProviderAccess()

    expect(openExternal).toHaveBeenCalledTimes(1)
    expect(
      api.mock.calls.filter(([value]) => value.path === '/api/providers/accounts/openai-codex/handoff-attempted')
    ).toHaveLength(1)
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'managed_info',
      requesting: false,
      message: expect.stringContaining('Request created, but the email app could not be opened')
    })
    expect(String(($desktopOnboarding.get().flow as { message?: string }).message)).not.toContain(
      'Could not create request:'
    )
  })

  it('does not let a rejected managed email launch corrupt an away-and-back flow epoch', async () => {
    const selected = deviceProvider('openai-codex', 'OpenAI Codex')
    const { request, snapshot } = managedAccessFixture()
    let resolveOpen!: (opened: boolean) => void

    const openResult = new Promise<boolean>(resolve => {
      resolveOpen = resolve
    })

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/accounts/openai-codex') {
        return { created: null, request: null, snapshot: snapshot(0) }
      }

      if (path === '/api/providers/accounts/openai-codex/managed-request') {
        return { created: true, request, snapshot: snapshot(1) }
      }

      if (path === '/api/providers/accounts/openai-codex/handoff-attempted') {
        return { created: null, request, snapshot: snapshot(2) }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const openExternal = installApiMock(api)

    openExternal.mockReturnValue(openResult)
    await startProviderOAuth(selected, { requestGateway: vi.fn() })
    showManagedProviderInfo()
    const staleLaunch = requestManagedProviderAccess()

    await vi.waitFor(() => {
      expect(
        api.mock.calls.filter(([value]) => value.path === '/api/providers/accounts/openai-codex/handoff-attempted')
      ).toHaveLength(1)
    })
    showProviderAccountChoice()
    showManagedProviderInfo()
    resolveOpen(false)
    await staleLaunch

    expect(openExternal).toHaveBeenCalledTimes(1)
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'managed_info',
      provider: selected,
      requesting: false
    })
    expect(($desktopOnboarding.get().flow as { message?: string }).message).toBeUndefined()
  })

  it('invalidates a managed handoff across an away-and-back ABA transition', async () => {
    const selected = deviceProvider('openai-codex', 'OpenAI Codex')
    let resolveAccount!: (value: unknown) => void

    const account = new Promise(resolve => {
      resolveAccount = resolve
    })

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/accounts/openai-codex') {
        return account
      }

      throw new Error(`stale operation reached unexpected path: ${path}`)
    })

    const openExternal = installApiMock(api)

    await startProviderOAuth(selected, { requestGateway: vi.fn() })
    showManagedProviderInfo()
    const staleRequest = requestManagedProviderAccess()
    showProviderAccountChoice()
    showManagedProviderInfo()
    resolveAccount({ snapshot: { revision: 0 } })
    await staleRequest

    expect(api).toHaveBeenCalledTimes(1)
    expect(openExternal).not.toHaveBeenCalled()
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'managed_info',
      profile: 'default',
      provider: selected,
      requesting: false
    })
  })

  it('keeps a Settings provider handoff pinned while its provider list loads', async () => {
    const selected = deviceProvider('openai-codex', 'OpenAI Codex')

    installApiMock(vi.fn())
    $activeGatewayProfile.set('origin-profile')
    startManualProviderOAuth(selected.id)
    $activeGatewayProfile.set('other-profile')

    expect(peekPendingProviderOAuth()).toBe(selected.id)
    const originatingProfile = clearPendingProviderOAuth()
    await startProviderOAuth(selected, { requestGateway: vi.fn() }, originatingProfile)

    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'choosing_account',
      profile: 'origin-profile',
      provider: selected
    })
  })

  it('starts the real ChatGPT device-code flow only after My account is selected', async () => {
    const selected = deviceProvider('openai-codex', 'OpenAI Codex')

    const api = vi.fn(async ({ body, path }: { body?: unknown; path: string }) => {
      if (path === '/api/providers/accounts/openai-codex') {
        return { snapshot: { revision: 7 } }
      }

      if (path === '/api/providers/oauth/openai-codex/start') {
        expect(body).toEqual({ expected_revision: 7 })

        return {
          expires_in: 900,
          flow: 'device_code',
          poll_interval: 5,
          session_id: 'personal-session',
          user_code: 'CHAT-GPT1',
          verification_url: 'https://auth.example/device'
        }
      }

      if (path === '/api/providers/oauth/openai-codex/sessions/personal-session') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const openExternal = installApiMock(api)

    await startProviderOAuth(selected, { requestGateway: vi.fn() })
    expect(api).not.toHaveBeenCalled()

    await continuePersonalProviderOAuth({ requestGateway: vi.fn() })

    expect(api).toHaveBeenCalledWith(expect.objectContaining({ path: '/api/providers/oauth/openai-codex/start' }))
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'polling',
      provider: selected,
      start: {
        session_id: 'personal-session',
        user_code: 'CHAT-GPT1',
        verification_url: 'https://auth.example/device'
      }
    })
    expect(openExternal).toHaveBeenCalledWith('https://auth.example/device')
  })

  it('surfaces blocked navigation and cancels the created OAuth session', async () => {
    const selected = deviceProvider('openai-codex', 'OpenAI Codex')

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/accounts/openai-codex') {
        return { snapshot: { revision: 2 } }
      }

      if (path === '/api/providers/oauth/openai-codex/start') {
        return {
          expires_in: 900,
          flow: 'device_code',
          poll_interval: 5,
          session_id: 'blocked-session',
          user_code: 'CODE-1234',
          verification_url: 'https://auth.openai.com/codex/device'
        }
      }

      if (path === '/api/providers/oauth/openai-codex/sessions/blocked-session') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const openExternal = installApiMock(api)
    openExternal.mockResolvedValue(false)
    const popup = vi.spyOn(window, 'open').mockReturnValue(null)

    await startProviderOAuth(selected, { requestGateway: vi.fn() })
    await continuePersonalProviderOAuth({ requestGateway: vi.fn() })

    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'error',
      message: expect.stringContaining('sign-in page could not be opened')
    })
    expect(popup).not.toHaveBeenCalled()
    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'DELETE',
        path: '/api/providers/oauth/openai-codex/sessions/blocked-session'
      })
    )
  })

  it('offers and executes an explicit takeover after an OAuth conflict', async () => {
    const selected = deviceProvider('xai-oauth', 'xAI Grok')
    let accountReads = 0
    let starts = 0

    const api = vi.fn(async ({ body, path }: { body?: unknown; path: string }) => {
      if (path === '/api/providers/accounts/xai-oauth') {
        accountReads += 1

        return { snapshot: { revision: accountReads } }
      }

      if (path === '/api/providers/oauth/xai-oauth/start') {
        starts += 1

        if (starts === 1) {
          throw new Error('409: {"error":{"code":"oauth_in_progress"}}')
        }

        expect(body).toEqual({ expected_revision: 2, takeover: true })

        return {
          expires_in: 900,
          flow: 'device_code',
          poll_interval: 5,
          session_id: 'takeover-session',
          user_code: 'GROK-1234',
          verification_url: 'https://accounts.x.ai/device'
        }
      }

      if (path === '/api/providers/oauth/xai-oauth/sessions/takeover-session') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    const ctx = { requestGateway: vi.fn() }

    await startProviderOAuth(selected, ctx)
    await continuePersonalProviderOAuth(ctx)
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'error',
      takeoverAvailable: true
    })

    await takeoverProviderOAuth(ctx)

    expect(starts).toBe(2)
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'polling',
      start: { session_id: 'takeover-session' }
    })
  })

  it('cancels a pending device-code session and stops polling when manual onboarding closes', async () => {
    vi.useFakeTimers()
    vi.spyOn(window, 'open').mockReturnValue(null)

    const selected = deviceProvider('openai-codex', 'OpenAI Codex')

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/accounts/openai-codex') {
        return { snapshot: { revision: 0 } }
      }

      if (path === '/api/providers/oauth/openai-codex/start') {
        return {
          expires_in: 900,
          flow: 'device_code',
          poll_interval: 5,
          session_id: 'codex-session',
          user_code: 'CODE-1234',
          verification_url: 'https://auth.example/device'
        }
      }

      if (path === '/api/providers/oauth/openai-codex/sessions/codex-session') {
        return { ok: true }
      }

      if (path === '/api/providers/oauth/openai-codex/poll/codex-session') {
        return { session_id: 'codex-session', status: 'pending' }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $activeGatewayProfile.set('origin-profile')
    $desktopOnboarding.set(
      baseState({
        configured: true,
        manual: true,
        providers: [selected],
        requested: true
      })
    )

    const ctx = { requestGateway: vi.fn() }

    await startProviderOAuth(selected, ctx)
    await continuePersonalProviderOAuth(ctx)
    expect($desktopOnboarding.get().flow.status).toBe('polling')

    $activeGatewayProfile.set('other-profile')
    closeManualOnboarding()
    await vi.advanceTimersByTimeAsync(2_500)

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'DELETE',
        path: '/api/providers/oauth/openai-codex/sessions/codex-session',
        profile: 'origin-profile'
      })
    )
    expect(api.mock.calls.some(([request]) => request.path.includes('/poll/'))).toBe(false)
    expect($desktopOnboarding.get()).toMatchObject({
      configured: true,
      flow: { status: 'idle' },
      manual: false,
      requested: false
    })
  })

  it('keeps device-code polling single-flight while a request is pending', async () => {
    vi.useFakeTimers()
    vi.spyOn(window, 'open').mockReturnValue(null)

    const selected = deviceProvider('openai-codex', 'OpenAI Codex')
    let resolvePoll!: (value: { session_id: string; status: 'pending' }) => void

    const pendingPoll = new Promise<{ session_id: string; status: 'pending' }>(resolve => {
      resolvePoll = resolve
    })

    let pollCalls = 0

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/accounts/openai-codex') {
        return { snapshot: { revision: 0 } }
      }

      if (path === '/api/providers/oauth/openai-codex/start') {
        return {
          expires_in: 900,
          flow: 'device_code',
          poll_interval: 5,
          session_id: 'codex-single-flight',
          user_code: 'CODE-1234',
          verification_url: 'https://auth.example/device'
        }
      }

      if (path === '/api/providers/oauth/openai-codex/poll/codex-single-flight') {
        pollCalls += 1

        return pendingPoll
      }

      if (path === '/api/providers/oauth/openai-codex/sessions/codex-single-flight') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    await startProviderOAuth(selected, { requestGateway: vi.fn() })
    await continuePersonalProviderOAuth({ requestGateway: vi.fn() })

    vi.advanceTimersByTime(4_100)
    await Promise.resolve()

    expect(pollCalls).toBe(1)

    resolvePoll({ session_id: 'codex-single-flight', status: 'pending' })
    await Promise.resolve()
    await Promise.resolve()
    vi.advanceTimersByTime(2_000)
    await Promise.resolve()

    expect(pollCalls).toBe(2)
  })

  it('cancels and ignores an in-flight poll when switching away from OAuth setup', async () => {
    vi.useFakeTimers()
    vi.spyOn(window, 'open').mockReturnValue(null)

    const selected = deviceProvider('xai-oauth', 'xAI Grok')
    let resolvePoll!: (value: { session_id: string; status: 'approved' }) => void

    const pendingPoll = new Promise<{ session_id: string; status: 'approved' }>(resolve => {
      resolvePoll = resolve
    })

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/accounts/xai-oauth') {
        return { snapshot: { revision: 0 } }
      }

      if (path === '/api/providers/oauth/xai-oauth/start') {
        return {
          expires_in: 900,
          flow: 'device_code',
          poll_interval: 5,
          session_id: 'xai-session',
          user_code: 'GROK-1234',
          verification_url: 'https://auth.example/grok-device'
        }
      }

      if (path === '/api/providers/oauth/xai-oauth/poll/xai-session') {
        return pendingPoll
      }

      if (path === '/api/providers/oauth/xai-oauth/sessions/xai-session') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $desktopOnboarding.set(
      baseState({
        configured: true,
        manual: true,
        providers: [selected],
        requested: true
      })
    )

    const ctx = { requestGateway: vi.fn() }

    await startProviderOAuth(selected, ctx)
    await continuePersonalProviderOAuth(ctx)
    vi.advanceTimersByTime(2_000)
    expect(api.mock.calls.some(([request]) => request.path.includes('/poll/'))).toBe(true)

    setOnboardingMode('apikey')
    resolvePoll({ session_id: 'xai-session', status: 'approved' })
    await Promise.resolve()
    await Promise.resolve()

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'DELETE',
        path: '/api/providers/oauth/xai-oauth/sessions/xai-session'
      })
    )
    expect(api.mock.calls.some(([request]) => request.path.startsWith('/api/model/options'))).toBe(false)
    expect($desktopOnboarding.get()).toMatchObject({
      configured: true,
      flow: { status: 'idle' },
      manual: true,
      mode: 'apikey'
    })
  })

  it('pins an approved OAuth flow and every post-auth write to its originating profile', async () => {
    vi.useFakeTimers()
    vi.spyOn(window, 'open').mockReturnValue(null)

    const selected = deviceProvider('openai-codex', 'OpenAI Codex')
    const model = 'openai-codex/gpt-5.4'
    let resolvePoll!: (value: { session_id: string; status: 'approved' }) => void

    const pendingPoll = new Promise<{ session_id: string; status: 'approved' }>(resolve => {
      resolvePoll = resolve
    })

    const apiCalls: Array<{ body?: unknown; path: string; profile?: string }> = []

    installApiMock(async request => {
      const { body, path, profile } = request as { body?: unknown; path: string; profile?: string }
      apiCalls.push({ body, path, profile })

      if (path === '/api/providers/accounts/openai-codex') {
        return { snapshot: { revision: 4 } }
      }

      if (path === '/api/providers/oauth/openai-codex/start') {
        return {
          expires_in: 900,
          flow: 'device_code',
          poll_interval: 5,
          session_id: 'origin-session',
          user_code: 'ORIGIN-1234',
          verification_url: 'https://auth.example/device'
        }
      }

      if (path === '/api/providers/oauth/openai-codex/poll/origin-session') {
        return pendingPoll
      }

      if (path.startsWith('/api/model/options')) {
        return { providers: [{ name: 'OpenAI Codex', slug: 'openai-codex', models: [model] }] }
      }

      if (path.startsWith('/api/model/recommended-default?')) {
        return { provider: 'openai-codex', model, free_tier: null }
      }

      if (path === '/api/model/set') {
        return { ok: true, provider: 'openai-codex', model, gateway_tools: [] }
      }

      if (path === '/api/providers/oauth/openai-codex/sessions/origin-session') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const gatewayCalls: Array<{ method: string; params?: Record<string, unknown> }> = []

    const requestGateway: OnboardingContext['requestGateway'] = async (method, params) => {
      gatewayCalls.push({ method, params })

      if (method === 'reload.env') {
        return {} as never
      }

      if (method === 'setup.status') {
        return { provider_configured: true } as never
      }

      if (method === 'setup.runtime_check') {
        return { ok: true } as never
      }

      throw new Error(`unexpected gateway method: ${method}`)
    }

    $activeGatewayProfile.set('origin-profile')
    await startProviderOAuth(selected, { requestGateway })
    await continuePersonalProviderOAuth({ requestGateway })
    await vi.advanceTimersByTimeAsync(2_000)

    expect(apiCalls.some(call => call.path.includes('/poll/'))).toBe(true)

    $activeGatewayProfile.set('other-profile')
    resolvePoll({ session_id: 'origin-session', status: 'approved' })
    await vi.advanceTimersByTimeAsync(0)

    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'confirming_model',
      profile: 'origin-profile',
      providerSlug: 'openai-codex'
    })
    expect(
      apiCalls.filter(call => call.path.startsWith('/api/')).every(call => call.profile === 'origin-profile')
    ).toBe(true)
    expect(apiCalls).not.toContainEqual(expect.objectContaining({ profile: 'other-profile' }))
    expect(gatewayCalls).toContainEqual({ method: 'reload.env', params: { profile: 'origin-profile' } })
    expect(gatewayCalls).toContainEqual({ method: 'setup.status', params: { profile: 'origin-profile' } })
    expect(gatewayCalls).toContainEqual({
      method: 'setup.runtime_check',
      params: { profile: 'origin-profile', provider: 'openai-codex' }
    })
  })

  it('pins Fabric-managed external sign-in instructions to the originating profile', async () => {
    const selected: OAuthProvider = {
      ...provider('qwen-oauth', 'Qwen CLI'),
      cli_command: 'fabric auth add qwen-oauth',
      flow: 'external'
    }

    installApiMock(vi.fn())
    $activeGatewayProfile.set('origin-profile')

    await startProviderOAuth(selected, { requestGateway: vi.fn() })
    $activeGatewayProfile.set('other-profile')

    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'external_pending',
      profile: 'origin-profile',
      provider: { cli_command: 'fabric --profile origin-profile auth add qwen-oauth' }
    })

    cancelOnboardingFlow()
    $activeGatewayProfile.set('default')
    await startProviderOAuth(selected, { requestGateway: vi.fn() })

    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'external_pending',
      profile: 'default',
      provider: { cli_command: 'fabric --profile default auth add qwen-oauth' }
    })

    cancelOnboardingFlow()
    $activeGatewayProfile.set('origin-profile')
    await startProviderOAuth(
      { ...selected, id: 'copilot-acp', cli_command: 'copilot /login' },
      { requestGateway: vi.fn() }
    )

    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'external_pending',
      profile: 'origin-profile',
      provider: { cli_command: 'copilot /login' }
    })
  })

  it('pins PKCE submission and post-auth completion across an active-profile switch', async () => {
    const model = 'nous/hermes-4'
    let resolveSubmit!: (value: { ok: boolean; status: 'approved' }) => void

    const pendingSubmit = new Promise<{ ok: boolean; status: 'approved' }>(resolve => {
      resolveSubmit = resolve
    })

    const apiCalls: Array<{ body?: unknown; path: string; profile?: string }> = []

    installApiMock(async request => {
      apiCalls.push(request)

      if (request.path === '/api/providers/oauth/nous/submit') {
        return pendingSubmit
      }

      if (request.path.startsWith('/api/model/options')) {
        return { providers: [{ name: 'Nous Portal', slug: 'nous', models: [model] }] }
      }

      if (request.path.startsWith('/api/model/recommended-default?')) {
        return { provider: 'nous', model, free_tier: false }
      }

      if (request.path === '/api/model/set') {
        return { ok: true, gateway_tools: [] }
      }

      throw new Error(`unexpected api path: ${request.path}`)
    })
    const gatewayCalls: Array<{ method: string; params?: Record<string, unknown> }> = []

    const requestGateway: OnboardingContext['requestGateway'] = async (method, params) => {
      gatewayCalls.push({ method, params })

      if (method === 'reload.env') {
        return {} as never
      }

      if (method === 'setup.status') {
        return { provider_configured: true } as never
      }

      if (method === 'setup.runtime_check') {
        return { ok: true } as never
      }

      throw new Error(`unexpected gateway method: ${method}`)
    }

    $activeGatewayProfile.set('origin-profile')
    $desktopOnboarding.set(
      baseState({
        flow: {
          status: 'awaiting_user',
          code: 'fresh-code',
          profile: 'origin-profile',
          provider: provider('nous', 'Nous Portal'),
          start: {
            auth_url: 'https://portal.example/auth',
            expires_in: 600,
            flow: 'pkce',
            session_id: 'origin-session'
          }
        }
      })
    )

    const pending = submitOnboardingCode({ requestGateway })
    await vi.waitFor(() => expect(apiCalls.some(call => call.path.endsWith('/submit'))).toBe(true))
    $activeGatewayProfile.set('other-profile')
    resolveSubmit({ ok: true, status: 'approved' })
    await pending

    expect(apiCalls.every(call => call.profile === 'origin-profile')).toBe(true)
    expect(gatewayCalls).toContainEqual({ method: 'reload.env', params: { profile: 'origin-profile' } })
    expect(gatewayCalls).toContainEqual({ method: 'setup.status', params: { profile: 'origin-profile' } })
    expect(gatewayCalls).toContainEqual({
      method: 'setup.runtime_check',
      params: { profile: 'origin-profile', provider: 'nous' }
    })
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'confirming_model',
      profile: 'origin-profile',
      providerSlug: 'nous'
    })
  })

  it('rechecks external sign-in entirely inside the profile that displayed its command', async () => {
    const model = 'qwen/qwen3-coder'
    const apiCalls: Array<{ body?: unknown; path: string; profile?: string }> = []

    installApiMock(async request => {
      apiCalls.push(request)

      if (request.path.startsWith('/api/model/options')) {
        return { providers: [{ name: 'Qwen CLI', slug: 'qwen-oauth', models: [model] }] }
      }

      if (request.path.startsWith('/api/model/recommended-default?')) {
        return { provider: 'qwen-oauth', model, free_tier: null }
      }

      if (request.path === '/api/model/set') {
        return { ok: true, gateway_tools: [] }
      }

      throw new Error(`unexpected api path: ${request.path}`)
    })
    const gatewayCalls: Array<{ method: string; params?: Record<string, unknown> }> = []

    const requestGateway: OnboardingContext['requestGateway'] = async (method, params) => {
      gatewayCalls.push({ method, params })

      return method === 'setup.runtime_check' ? ({ ok: true } as never) : ({ provider_configured: true } as never)
    }

    $desktopOnboarding.set(
      baseState({
        flow: {
          status: 'external_pending',
          copied: false,
          profile: 'origin-profile',
          provider: { ...provider('qwen-oauth', 'Qwen CLI'), flow: 'external' }
        }
      })
    )
    $activeGatewayProfile.set('other-profile')

    await recheckExternalSignin({ requestGateway })

    expect(apiCalls.every(call => call.profile === 'origin-profile')).toBe(true)
    expect(gatewayCalls).toContainEqual({ method: 'reload.env', params: { profile: 'origin-profile' } })
    expect(gatewayCalls).toContainEqual({ method: 'setup.status', params: { profile: 'origin-profile' } })
    expect(gatewayCalls).toContainEqual({
      method: 'setup.runtime_check',
      params: { profile: 'origin-profile', provider: 'qwen-oauth' }
    })
  })

  it('does not mark the newly active profile configured on a no-default OAuth fast path', async () => {
    const onCompleted = vi.fn()
    const apiCalls: Array<{ path: string; profile?: string }> = []

    installApiMock(async request => {
      apiCalls.push(request)

      if (request.path.startsWith('/api/model/options')) {
        return { providers: [] }
      }

      throw new Error(`unexpected api path: ${request.path}`)
    })

    const requestGateway: OnboardingContext['requestGateway'] = async method => {
      if (method === 'reload.env') {
        return {} as never
      }

      if (method === 'setup.status') {
        return { provider_configured: true } as never
      }

      if (method === 'setup.runtime_check') {
        return { ok: true } as never
      }

      throw new Error(`unexpected gateway method: ${method}`)
    }

    $desktopOnboarding.set(
      baseState({
        flow: {
          status: 'external_pending',
          copied: false,
          profile: 'origin-profile',
          provider: { ...provider('qwen-oauth', 'Qwen CLI'), flow: 'external' }
        }
      })
    )
    $activeGatewayProfile.set('other-profile')

    await recheckExternalSignin({ onCompleted, requestGateway })

    expect(apiCalls.every(call => call.profile === 'origin-profile')).toBe(true)
    expect($desktopOnboarding.get().configured).toBe(false)
    expect($desktopOnboarding.get().flow).toEqual({ status: 'idle' })
    expect(onCompleted).not.toHaveBeenCalled()
    expect(window.localStorage.getItem('hermes-desktop-onboarded-v1')).toBeNull()
  })

  it('does not finalize an origin confirmation after another profile becomes active', () => {
    const onCompleted = vi.fn()

    $desktopOnboarding.set(
      baseState({
        flow: {
          status: 'confirming_model',
          currentModel: 'origin-model',
          label: 'Origin provider',
          profile: 'origin-profile',
          providerSlug: 'origin-provider',
          saving: false
        }
      })
    )
    $activeGatewayProfile.set('other-profile')

    confirmOnboardingModel({ onCompleted, requestGateway: vi.fn() })

    expect($desktopOnboarding.get().configured).toBe(false)
    expect($desktopOnboarding.get().flow).toEqual({ status: 'idle' })
    expect(onCompleted).not.toHaveBeenCalled()
    expect(window.localStorage.getItem('hermes-desktop-onboarded-v1')).toBeNull()
  })

  it('does not let a late model-change response overwrite a newer profile confirmation', async () => {
    let resolveModelSet!: (value: { ok: boolean }) => void

    const pendingModelSet = new Promise<{ ok: boolean }>(resolve => {
      resolveModelSet = resolve
    })

    installApiMock(async ({ path }: { path: string }) => {
      if (path === '/api/model/set') {
        return pendingModelSet
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    $desktopOnboarding.set(
      baseState({
        flow: {
          status: 'confirming_model',
          currentModel: 'origin-default',
          label: 'Origin provider',
          profile: 'origin-profile',
          providerSlug: 'origin-provider',
          saving: false
        }
      })
    )

    const staleChange = setOnboardingModel('origin-alternate')
    await vi.waitFor(() => expect($desktopOnboarding.get().flow).toMatchObject({ saving: true }))

    cancelOnboardingFlow()
    $desktopOnboarding.set(
      baseState({
        flow: {
          status: 'confirming_model',
          currentModel: 'new-default',
          label: 'New provider',
          profile: 'other-profile',
          providerSlug: 'new-provider',
          saving: false
        }
      })
    )
    resolveModelSet({ ok: true })
    await staleChange

    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'confirming_model',
      currentModel: 'new-default',
      profile: 'other-profile',
      providerSlug: 'new-provider',
      saving: false
    })
  })

  it('persists a changed model and its selected provider on the confirmation profile', async () => {
    const calls: Array<{ body?: Record<string, unknown>; path: string; profile?: string }> = []

    installApiMock(async request => {
      calls.push(request)

      if (request.path === '/api/model/set') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${request.path}`)
    })
    $activeGatewayProfile.set('other-profile')
    $desktopOnboarding.set(
      baseState({
        flow: {
          status: 'confirming_model',
          currentModel: 'origin-default',
          label: 'Origin provider',
          profile: 'origin-profile',
          providerSlug: 'origin-provider',
          saving: false
        }
      })
    )

    await setOnboardingModel('alternate-model', 'alternate-provider')

    expect(calls).toContainEqual(
      expect.objectContaining({
        path: '/api/model/set',
        profile: 'origin-profile',
        body: {
          model: 'alternate-model',
          provider: 'alternate-provider',
          scope: 'main'
        }
      })
    )
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'confirming_model',
      currentModel: 'alternate-model',
      profile: 'origin-profile',
      providerSlug: 'alternate-provider',
      saving: false
    })
  })

  it('pins confirmation model-option reads even after the active profile changes', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/model/options?explicit_only=1') {
        return { model: 'origin-model', provider: 'origin-provider', providers: [] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $activeGatewayProfile.set('other-profile')

    await requestModelOptions({ profile: 'origin-profile' })

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({
        path: '/api/model/options?explicit_only=1',
        profile: 'origin-profile'
      })
    )
  })

  it('does not revive a cancelled API-key flow after its profile-scoped write resolves', async () => {
    let resolveEnvWrite!: (value: { ok: boolean }) => void

    const pendingEnvWrite = new Promise<{ ok: boolean }>(resolve => {
      resolveEnvWrite = resolve
    })

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/env') {
        return pendingEnvWrite
      }

      if (path.startsWith('/api/model/options')) {
        return { providers: [] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    $activeGatewayProfile.set('origin-profile')

    const pendingSave = saveOnboardingApiKey('OPENROUTER_API_KEY', 'sk-origin', 'OpenRouter', {
      requestGateway: fallbackTimeoutGateway()
    })

    await vi.waitFor(() => expect(api).toHaveBeenCalledWith(expect.objectContaining({ profile: 'origin-profile' })))
    setOnboardingMode('oauth')
    resolveEnvWrite({ ok: true })

    await expect(pendingSave).resolves.toMatchObject({ ok: false, message: expect.stringContaining('cancelled') })
    expect(api.mock.calls.some(([request]) => request.path.startsWith('/api/model/options'))).toBe(false)
    expect($desktopOnboarding.get().flow).toEqual({ status: 'idle' })
    expect($desktopOnboarding.get().configured).toBe(false)
  })

  it('pins API-key model lookup, assignment, reload, and readiness after a profile switch', async () => {
    const model = 'openrouter/auto'
    let resolveEnvWrite!: (value: { ok: boolean }) => void

    const pendingEnvWrite = new Promise<{ ok: boolean }>(resolve => {
      resolveEnvWrite = resolve
    })

    const apiCalls: Array<{ path: string; profile?: string }> = []

    installApiMock(async request => {
      apiCalls.push(request)

      if (request.path === '/api/env') {
        return pendingEnvWrite
      }

      if (request.path.startsWith('/api/model/options')) {
        return { providers: [{ name: 'OpenRouter', slug: 'openrouter', models: [model] }] }
      }

      if (request.path.startsWith('/api/model/recommended-default?')) {
        return { provider: 'openrouter', model, free_tier: null }
      }

      if (request.path === '/api/model/set') {
        return { ok: true, gateway_tools: [] }
      }

      throw new Error(`unexpected api path: ${request.path}`)
    })
    const gatewayCalls: Array<{ method: string; params?: Record<string, unknown> }> = []

    const requestGateway: OnboardingContext['requestGateway'] = async (method, params) => {
      gatewayCalls.push({ method, params })

      if (method === 'reload.env') {
        return {} as never
      }

      if (method === 'setup.status') {
        return { provider_configured: true } as never
      }

      if (method === 'setup.runtime_check') {
        return { ok: true } as never
      }

      throw new Error(`unexpected gateway method: ${method}`)
    }

    $activeGatewayProfile.set('origin-profile')
    const pendingSave = saveOnboardingApiKey('OPENROUTER_API_KEY', 'sk-origin', 'OpenRouter', { requestGateway })
    await vi.waitFor(() => expect(apiCalls.some(call => call.path === '/api/env')).toBe(true))
    $activeGatewayProfile.set('other-profile')
    resolveEnvWrite({ ok: true })

    await expect(pendingSave).resolves.toEqual({ ok: true })
    expect(apiCalls.every(call => call.profile === 'origin-profile')).toBe(true)
    expect(gatewayCalls).toContainEqual({ method: 'reload.env', params: { profile: 'origin-profile' } })
    expect(gatewayCalls).toContainEqual({ method: 'setup.status', params: { profile: 'origin-profile' } })
    expect(gatewayCalls).toContainEqual({
      method: 'setup.runtime_check',
      params: { profile: 'origin-profile', provider: 'openrouter' }
    })
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'confirming_model',
      profile: 'origin-profile',
      providerSlug: 'openrouter'
    })
  })

  it('clears stale readiness errors after OAuth succeeds and model confirmation is shown', async () => {
    const model = 'anthropic/claude-opus-4.8'
    const calls: { body?: unknown; path: string }[] = []

    installApiMock(async ({ body, path }: { body?: unknown; path: string }) => {
      calls.push({ body, path })

      if (path === '/api/providers/oauth/nous/submit') {
        return { ok: true, status: 'approved' }
      }

      if (path.startsWith('/api/model/options')) {
        return {
          providers: [
            {
              name: 'Nous Portal',
              slug: 'nous',
              models: [model]
            }
          ]
        }
      }

      if (path.startsWith('/api/model/recommended-default?')) {
        return { provider: 'nous', model, free_tier: false }
      }

      if (path === '/api/model/set') {
        return { ok: true, provider: 'nous', model, gateway_tools: [] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const requestGateway: OnboardingContext['requestGateway'] = async (method, params) => {
      if (method === 'reload.env') {
        return {} as never
      }

      if (method === 'setup.status') {
        return { provider_configured: true } as never
      }

      if (method === 'setup.runtime_check') {
        expect(params).toEqual({ provider: 'nous' })

        return { ok: true } as never
      }

      throw new Error(`unexpected gateway method: ${method}`)
    }

    $desktopOnboarding.set(
      baseState({
        flow: {
          status: 'awaiting_user',
          profile: 'default',
          provider: provider('nous', 'Nous Portal'),
          start: {
            auth_url: 'https://portal.example/auth',
            expires_in: 600,
            flow: 'pkce',
            session_id: 'portal-session'
          },
          code: 'fresh-code'
        },
        reason:
          'No access token found for Nous Portal login. setup.status reports configured credentials, but runtime resolution still failed.',
        requested: true
      })
    )

    await submitOnboardingCode(onboardingContext(requestGateway))

    const state = $desktopOnboarding.get()
    expect(state.reason).toBeNull()
    expect(state.flow.status).toBe('confirming_model')

    if (state.flow.status === 'confirming_model') {
      expect(state.flow.label).toBe('Nous Portal')
      expect(state.flow.currentModel).toBe(model)
    }

    expect(calls.some(c => c.path === '/api/model/set')).toBe(true)

    const optionsIndex = calls.findIndex(c => c.path.startsWith('/api/model/options'))
    const recommendedIndex = calls.findIndex(c => c.path.startsWith('/api/model/recommended-default'))
    const setIndex = calls.findIndex(c => c.path === '/api/model/set')

    expect(optionsIndex).toBeGreaterThanOrEqual(0)
    expect(recommendedIndex).toBeGreaterThan(optionsIndex)
    expect(setIndex).toBeGreaterThan(recommendedIndex)
  })
})

describe('saveOnboardingLocalEndpoint', () => {
  beforeEach(() => {
    ensureLocalStorage()
    $activeGatewayProfile.set('default')
    window.localStorage.clear()
    $desktopOnboarding.set(baseState())
  })

  afterEach(() => {
    $activeGatewayProfile.set('default')
    window.localStorage.clear()
    $desktopOnboarding.set(baseState())
    vi.restoreAllMocks()
  })

  function readyGateway(): OnboardingContext['requestGateway'] {
    return async method => {
      if (method === 'reload.env') {
        return {} as never
      }

      if (method === 'setup.status') {
        return { provider_configured: true } as never
      }

      if (method === 'setup.runtime_check') {
        return { ok: true } as never
      }

      throw new Error(`unexpected gateway method: ${method}`)
    }
  }

  it('errors when the endpoint advertises no models (nothing to route to)', async () => {
    const calls: string[] = []
    installApiMock(async ({ path }: { path: string }) => {
      calls.push(path)

      if (path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: [] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const result = await saveOnboardingLocalEndpoint('http://127.0.0.1:8000/v1', '', {
      requestGateway: readyGateway()
    })

    expect(result.ok).toBe(false)
    expect(result.message).toContain('no models')
    // Must not attempt to persist an assignment without a model.
    expect(calls).not.toContain('/api/model/set')
  })

  it('does not silently persist the first model when an endpoint advertises multiple choices', async () => {
    const calls: { body?: unknown; path: string }[] = []

    installApiMock(async ({ body, path }: { body?: unknown; path: string }) => {
      calls.push({ body, path })

      if (path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: ['llama-3.1-8b', 'qwen2.5-7b'] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const result = await saveOnboardingLocalEndpoint('http://127.0.0.1:8000/v1', '', {
      requestGateway: readyGateway()
    })

    expect(result.ok).toBe(true)
    expect(calls.some(call => call.path === '/api/model/set')).toBe(false)
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'confirming_local_model',
      baseUrl: 'http://127.0.0.1:8000/v1',
      models: ['llama-3.1-8b', 'qwen2.5-7b'],
      currentModel: ''
    })
  })

  it('auto-discovers one unique model and persists provider=custom + base_url, then finishes', async () => {
    const calls: { body?: unknown; path: string; profile?: string }[] = []

    const api = vi.fn(async ({ body, path, profile }: { body?: unknown; path: string; profile?: string }) => {
      calls.push({ body, path, profile })

      if (path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: ['llama-3.1-8b', '', 'llama-3.1-8b'] }
      }

      if (path === '/api/model/set') {
        return { ok: true, provider: 'custom', model: 'llama-3.1-8b', base_url: 'http://127.0.0.1:8000/v1' }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    const onCompleted = vi.fn()
    const gatewayCalls: Array<{ method: string; params?: Record<string, unknown> }> = []
    const baseGateway = readyGateway()

    const requestGateway: OnboardingContext['requestGateway'] = async (method, params) => {
      gatewayCalls.push({ method, params })

      return baseGateway(method, params)
    }

    $activeGatewayProfile.set('origin-profile')

    const result = await saveOnboardingLocalEndpoint('http://127.0.0.1:8000/v1', '', {
      onCompleted,
      requestGateway
    })

    expect(result.ok).toBe(true)

    const assign = calls.find(c => c.path === '/api/model/set')
    const probe = calls.find(c => c.path === '/api/providers/validate')
    expect(probe?.profile).toBe('origin-profile')
    expect(assign?.profile).toBe('origin-profile')
    expect(assign?.body).toMatchObject({
      scope: 'main',
      provider: 'custom',
      model: 'llama-3.1-8b',
      base_url: 'http://127.0.0.1:8000/v1'
    })

    expect(onCompleted).toHaveBeenCalledTimes(1)
    expect($desktopOnboarding.get().configured).toBe(true)
    expect(gatewayCalls).toContainEqual({ method: 'reload.env', params: { profile: 'origin-profile' } })
  })

  it('persists the explicitly selected model with the endpoint credentials', async () => {
    const calls: { body?: unknown; path: string }[] = []

    installApiMock(async ({ body, path }: { body?: unknown; path: string }) => {
      calls.push({ body, path })

      if (path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: ['llama-3.1-8b', 'qwen2.5-7b'] }
      }

      if (path === '/api/model/set') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const ctx = {
      onCompleted: vi.fn(),
      requestGateway: readyGateway()
    }

    await saveOnboardingLocalEndpoint('https://models.example.test/v1', 'sk-secret', ctx)

    expect(calls.some(call => call.path === '/api/model/set')).toBe(false)

    setOnboardingLocalModel('qwen2.5-7b')
    const result = await confirmOnboardingLocalModel(ctx)

    expect(result.ok).toBe(true)
    expect(calls.find(call => call.path === '/api/model/set')?.body).toMatchObject({
      scope: 'main',
      provider: 'custom',
      model: 'qwen2.5-7b',
      base_url: 'https://models.example.test/v1',
      api_key: 'sk-secret'
    })
    expect(ctx.onCompleted).toHaveBeenCalledTimes(1)
  })

  it('cancels a multi-model choice without persisting an assignment', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: ['model-a', 'model-b'] }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)
    await saveOnboardingLocalEndpoint('http://127.0.0.1:8000/v1', '', {
      requestGateway: readyGateway()
    })

    cancelOnboardingFlow()
    const result = await confirmOnboardingLocalModel({ requestGateway: readyGateway() })

    expect(result.ok).toBe(false)
    expect($desktopOnboarding.get().flow).toEqual({ status: 'idle' })
    expect(api.mock.calls.some(([request]) => request.path === '/api/model/set')).toBe(false)
  })

  it('cancels a pending multi-model choice when the active profile changes', async () => {
    const calls: { body?: Record<string, unknown>; path: string; profile?: string }[] = []

    installApiMock(async request => {
      calls.push(request)

      if (request.path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: ['model-a', 'model-b'] }
      }

      if (request.path === '/api/model/set') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${request.path}`)
    })

    $activeGatewayProfile.set('origin-profile')
    const ctx = { requestGateway: readyGateway() }

    await saveOnboardingLocalEndpoint('https://models.example.test/v1', 'origin-secret', ctx)
    setOnboardingLocalModel('model-b')
    $activeGatewayProfile.set('other-profile')

    const result = await confirmOnboardingLocalModel(ctx)

    expect(result).toMatchObject({ ok: false })
    expect($desktopOnboarding.get().flow).toEqual({ status: 'idle' })
    expect(calls.find(call => call.path === '/api/providers/validate')?.profile).toBe('origin-profile')
    expect(calls.some(call => call.path === '/api/model/set')).toBe(false)
  })

  it('keeps an in-flight model write on its originating profile and cancels follow-up work after a switch', async () => {
    const calls: { body?: Record<string, unknown>; path: string; profile?: string }[] = []
    const gatewayCalls: string[] = []
    let resolveModelSet!: (value: { ok: boolean }) => void

    const pendingModelSet = new Promise<{ ok: boolean }>(resolve => {
      resolveModelSet = resolve
    })

    installApiMock(async request => {
      calls.push(request)

      if (request.path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: ['model-a', 'model-b'] }
      }

      if (request.path === '/api/model/set') {
        return pendingModelSet
      }

      throw new Error(`unexpected api path: ${request.path}`)
    })

    const requestGateway: OnboardingContext['requestGateway'] = async method => {
      gatewayCalls.push(method)

      return {} as never
    }

    const ctx = { requestGateway }

    $activeGatewayProfile.set('origin-profile')
    await saveOnboardingLocalEndpoint('https://models.example.test/v1', 'origin-secret', ctx)
    setOnboardingLocalModel('model-b')

    const confirmation = confirmOnboardingLocalModel(ctx)
    await vi.waitFor(() => expect(calls.some(call => call.path === '/api/model/set')).toBe(true))

    $activeGatewayProfile.set('other-profile')
    resolveModelSet({ ok: true })

    const result = await confirmation
    const writes = calls.filter(call => call.path === '/api/model/set')

    expect(result).toMatchObject({ ok: false, message: expect.stringContaining('cancelled') })
    expect(writes).toHaveLength(1)
    expect(writes[0]).toMatchObject({
      profile: 'origin-profile',
      body: {
        api_key: 'origin-secret',
        base_url: 'https://models.example.test/v1',
        model: 'model-b',
        provider: 'custom',
        scope: 'main'
      }
    })
    expect(calls.some(call => call.path === '/api/model/set' && call.profile === 'other-profile')).toBe(false)
    expect(gatewayCalls).toEqual([])
    expect($desktopOnboarding.get().flow).toEqual({ status: 'idle' })
  })

  it('ignores a model probe that resolves after local endpoint setup is closed', async () => {
    let resolveProbe!: (value: { message: string; models: string[]; ok: boolean; reachable: boolean }) => void

    const probe = new Promise<{ message: string; models: string[]; ok: boolean; reachable: boolean }>(resolve => {
      resolveProbe = resolve
    })

    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path === '/api/providers/validate') {
        return probe
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)

    const pending = saveOnboardingLocalEndpoint('http://127.0.0.1:8000/v1', '', {
      requestGateway: readyGateway()
    })

    await vi.waitFor(() => expect(api).toHaveBeenCalledTimes(1))
    cancelOnboardingFlow()
    resolveProbe({ ok: true, reachable: true, message: '', models: ['model-a', 'model-b'] })

    const result = await pending

    expect(result.ok).toBe(false)
    expect(result.message).toContain('cancelled')
    expect($desktopOnboarding.get().flow).toEqual({ status: 'idle' })
    expect(api.mock.calls.some(([request]) => request.path === '/api/model/set')).toBe(false)
  })

  it('forwards the API key to the probe and persists it for auth-gated endpoints', async () => {
    const calls: { body?: unknown; path: string }[] = []

    const api = vi.fn(async ({ body, path }: { body?: unknown; path: string }) => {
      calls.push({ body, path })

      if (path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: ['gpt-oss-120b'] }
      }

      if (path === '/api/model/set') {
        return { ok: true, provider: 'custom', model: 'gpt-oss-120b', base_url: 'https://text.example.com/v1' }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    installApiMock(api)

    const result = await saveOnboardingLocalEndpoint('https://text.example.com/v1', 'sk-secret', {
      requestGateway: readyGateway()
    })

    expect(result.ok).toBe(true)

    // The probe must receive the key so an auth-gated /v1/models enumerates.
    const probe = calls.find(c => c.path === '/api/providers/validate')
    expect(probe?.body).toMatchObject({
      key: 'OPENAI_BASE_URL',
      value: 'https://text.example.com/v1',
      api_key: 'sk-secret'
    })

    // And the key must be persisted alongside the endpoint for runtime auth.
    const assign = calls.find(c => c.path === '/api/model/set')
    expect(assign?.body).toMatchObject({
      scope: 'main',
      provider: 'custom',
      model: 'gpt-oss-120b',
      base_url: 'https://text.example.com/v1',
      api_key: 'sk-secret'
    })
  })

  it('reports the runtime reason when resolution still fails after saving', async () => {
    installApiMock(async ({ path }: { path: string }) => {
      if (path === '/api/providers/validate') {
        return { ok: true, reachable: true, message: '', models: ['llama-3.1-8b'] }
      }

      if (path === '/api/model/set') {
        return { ok: true }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const failingGateway: OnboardingContext['requestGateway'] = async method => {
      if (method === 'reload.env') {
        return {} as never
      }

      if (method === 'setup.status') {
        return { provider_configured: false } as never
      }

      if (method === 'setup.runtime_check') {
        return { ok: false, error: 'No provider can serve the selected model.' } as never
      }

      throw new Error(`unexpected gateway method: ${method}`)
    }

    const result = await saveOnboardingLocalEndpoint('http://127.0.0.1:8000/v1', '', {
      requestGateway: failingGateway
    })

    expect(result.ok).toBe(false)
    expect(result.message).toContain('No provider can serve the selected model.')
    expect($desktopOnboarding.get().configured).not.toBe(true)
  })
})

describe('saveOnboardingNativeOllama', () => {
  beforeEach(() => {
    ensureLocalStorage()
    $activeGatewayProfile.set('default')
    window.localStorage.clear()
    $desktopOnboarding.set(baseState())
  })

  afterEach(() => {
    $activeGatewayProfile.set('default')
    window.localStorage.clear()
    $desktopOnboarding.set(baseState())
    vi.restoreAllMocks()
  })

  const readyGateway: OnboardingContext['requestGateway'] = async method => {
    if (method === 'reload.env') {return {} as never}

    if (method === 'setup.status') {return { provider_configured: true } as never}

    if (method === 'setup.runtime_check') {return { ok: true } as never}
    throw new Error(`unexpected gateway method: ${method}`)
  }

  it('discovers and configures one native model without persisting a synthetic env key', async () => {
    const calls: Array<{ body?: Record<string, unknown>; path: string }> = []
    installApiMock(async ({ body, path }: { body?: Record<string, unknown>; path: string }) => {
      calls.push({ body, path })

      if (path === '/api/providers/local/ollama/discover') {
        return {
          provider: 'ollama',
          base_url: 'http://127.0.0.1:11434',
          state: 'reachable',
          models: ['qwen3:latest'],
          issue_code: null
        }
      }

      if (path === '/api/providers/local/ollama/configure') {
        return {
          ok: true,
          provider: 'ollama',
          model: 'qwen3:latest',
          base_url: 'http://127.0.0.1:11434',
          local_ai_enabled: true
        }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const result = await saveOnboardingNativeOllama('http://127.0.0.1:11434', {
      requestGateway: readyGateway
    })

    expect(result.ok).toBe(true)
    expect(calls.map(call => call.path)).toEqual([
      '/api/providers/local/ollama/discover',
      '/api/providers/local/ollama/configure'
    ])
    expect(calls.some(call => call.path === '/api/env')).toBe(false)
    expect(calls[1].body).toEqual({ base_url: 'http://127.0.0.1:11434', model: 'qwen3:latest' })
  })

  it('requires an explicit model choice when native Ollama advertises several models', async () => {
    installApiMock(async ({ path }: { path: string }) => {
      if (path === '/api/providers/local/ollama/discover') {
        return {
          provider: 'ollama',
          base_url: 'http://127.0.0.1:11434',
          state: 'reachable',
          models: ['qwen3:latest', 'llama3.2:latest'],
          issue_code: null
        }
      }

      throw new Error(`unexpected api path: ${path}`)
    })

    const result = await saveOnboardingNativeOllama('http://127.0.0.1:11434', {
      requestGateway: readyGateway
    })

    expect(result.ok).toBe(true)
    expect($desktopOnboarding.get().flow).toMatchObject({
      status: 'confirming_local_model',
      localProvider: 'ollama',
      baseUrl: 'http://127.0.0.1:11434',
      models: ['qwen3:latest', 'llama3.2:latest'],
      currentModel: ''
    })
  })
})
