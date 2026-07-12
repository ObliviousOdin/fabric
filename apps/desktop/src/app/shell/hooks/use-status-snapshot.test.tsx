import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getStatus } from '@/hermes'
import { evaluateRuntimeReadiness } from '@/lib/runtime-readiness'
import { $activeGatewayProfile } from '@/store/profile'

import { useStatusSnapshot } from './use-status-snapshot'

vi.mock('@/hermes', () => ({
  getProfiles: vi.fn(),
  getStatus: vi.fn(),
  setApiRequestProfile: vi.fn(),
  STARTUP_REQUEST_TIMEOUT_MS: 15_000
}))
vi.mock('@/lib/runtime-readiness', () => ({ evaluateRuntimeReadiness: vi.fn() }))

function requestGateway<T = unknown>(
  _method: string,
  _params?: Record<string, unknown>
): Promise<T> {
  return Promise.resolve(undefined as T)
}

function Harness() {
  useStatusSnapshot('open', requestGateway)

  return null
}

describe('useStatusSnapshot', () => {
  beforeEach(() => {
    $activeGatewayProfile.set('default')
    vi.mocked(getStatus).mockResolvedValue({} as never)
    vi.mocked(evaluateRuntimeReadiness).mockResolvedValue({
      checksDisagree: false,
      ready: true,
      reason: null,
      source: 'gateway'
    } as never)
  })

  afterEach(() => {
    cleanup()
    $activeGatewayProfile.set('default')
    vi.clearAllMocks()
  })

  it('refreshes readiness immediately when the active gateway profile changes', async () => {
    render(<Harness />)

    await waitFor(() =>
      expect(evaluateRuntimeReadiness).toHaveBeenCalledWith(requestGateway, {
        profile: 'default'
      })
    )

    act(() => $activeGatewayProfile.set('field-fabric'))

    await waitFor(() =>
      expect(evaluateRuntimeReadiness).toHaveBeenLastCalledWith(requestGateway, {
        profile: 'field-fabric'
      })
    )
    expect(evaluateRuntimeReadiness).toHaveBeenCalledTimes(2)
  })
})
