import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  checkFabricUpdate,
  getActionStatus,
  getStatus,
  restartGateway,
  setApiRequestProfile,
  setModelAssignment,
  updateFabric,
  validateProviderCredential
} from './hermes'

// Contract: every backend-targeted action helper must carry the active gateway
// profile, so a multi-profile / global-remote user's restart, status poll, and
// update hit the backend they're actually on — not the primary/default. The
// System-panel "restart does nothing" bug was these helpers dropping it.
describe('backend action helpers are profile-scoped', () => {
  const api = vi.fn(async (_req: { path: string; profile?: string }) => ({}) as never)

  beforeEach(() => {
    ;(window as { fabricDesktop?: unknown }).fabricDesktop = { api }
    api.mockClear()
  })

  afterEach(() => {
    setApiRequestProfile(null)
    delete (window as { fabricDesktop?: unknown }).fabricDesktop
  })

  const lastProfile = () => api.mock.calls.at(-1)?.[0].profile

  it('omits profile when none is active (single-profile users unaffected)', () => {
    void getStatus()
    expect(lastProfile()).toBeUndefined()
  })

  it('forwards the active profile to every backend action', () => {
    setApiRequestProfile('coder')

    void getStatus()
    void restartGateway()
    void updateFabric()
    void checkFabricUpdate()
    void getActionStatus('gateway-restart')

    for (const call of api.mock.calls) {
      expect(call[0].profile).toBe('coder')
    }
  })

  it('lets a multi-step flow pin validation and persistence to its originating profile', () => {
    setApiRequestProfile('current-profile')

    void validateProviderCredential('OPENAI_BASE_URL', 'https://models.example.test/v1', 'secret', 'origin-profile')
    void setModelAssignment(
      {
        api_key: 'secret',
        base_url: 'https://models.example.test/v1',
        model: 'model-a',
        provider: 'custom',
        scope: 'main'
      },
      'origin-profile'
    )

    expect(api.mock.calls).toHaveLength(2)

    for (const call of api.mock.calls) {
      expect(call[0].profile).toBe('origin-profile')
    }
  })
})
