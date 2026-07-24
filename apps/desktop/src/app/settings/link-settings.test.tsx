import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const requestGateway = vi.fn()
const notify = vi.fn()
const notifyError = vi.fn()

vi.mock('../gateway/hooks/use-gateway-request', () => ({
  useGatewayRequest: () => ({ requestGateway })
}))

vi.mock('@/store/notifications', () => ({
  notify: (value: unknown) => notify(value),
  notifyError: (error: unknown, fallback: string) => notifyError(error, fallback)
}))

beforeEach(() => {
  requestGateway.mockImplementation(async (method: string) => {
    if (method === 'link.controller.list') {
      return { controllers: [] }
    }

    throw new Error(`unexpected method: ${method}`)
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('LinkSettings', () => {
  it('consumes every bounded event page before advancing to the high watermark', async () => {
    const { nextBoundedEventCursor } = await import('./link-settings')

    expect(
      nextBoundedEventCursor(0, {
        events: Array.from({ length: 100 }, (_, index) => ({
          event_seq: index + 1,
          frame: {}
        })),
        high_watermark: 101
      })
    ).toBe(100)
    expect(nextBoundedEventCursor(100, { events: [], high_watermark: 101 })).toBe(101)
  })

  it('keeps host comparison separate from completion and never asks for social login', async () => {
    requestGateway.mockImplementation(async (method: string) => {
      if (method === 'link.controller.list') {
        return { controllers: [] }
      }

      if (method === 'link.controller.enrollment.start') {
        return {
          controller_id: 'controller_1234567890',
          expires_at: Math.floor(Date.now() / 1000) + 300,
          label: 'Fabric Desktop',
          machine_fingerprint: 'ABCD-EFGH-IJKL',
          relay_origin: 'https://relay.example',
          short_auth_string: 'amber-lake-4821'
        }
      }

      if (method === 'link.controller.enrollment.finish') {
        return {
          grants: ['observe', 'chat', 'dispatch'],
          id: 'controller_1234567890',
          label: 'Target Mac',
          machine_fingerprint: 'ABCD-EFGH-IJKL',
          platform: 'desktop',
          relay: 'https://relay.example',
          status: 'active'
        }
      }

      throw new Error(`unexpected method: ${method}`)
    })
    const { LinkSettings } = await import('./link-settings')
    render(<LinkSettings />)

    fireEvent.change(screen.getByLabelText('Fabric Link pairing URL'), {
      target: { value: 'https://relay.example/link/pair#pair=opaque' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Start secure pairing' }))

    expect(await screen.findByText('amber-lake-4821')).toBeTruthy()
    expect(screen.getByText('Machine: ABCD-EFGH-IJKL')).toBeTruthy()
    expect(screen.queryByText(/GitHub sign/i)).toBeNull()
    expect(screen.queryByText(/Google sign/i)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'I compared it — wait for host approval' }))

    await waitFor(() =>
      expect(requestGateway).toHaveBeenCalledWith(
        'link.controller.enrollment.finish',
        expect.objectContaining({ controller_id: 'controller_1234567890' }),
        310_000
      )
    )
    await waitFor(() => expect(notify).toHaveBeenCalledWith({ kind: 'success', message: 'Fabric Link machine paired' }))
  })

  it('dispatches one durable intent with one generated idempotency key', async () => {
    const randomUUID = vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001')
    requestGateway.mockImplementation(async (method: string) => {
      if (method === 'link.controller.list') {
        return {
          controllers: [
            {
              grants: ['dispatch', 'observe'],
              id: 'controller_1234567890',
              label: 'Studio Mac',
              machine_fingerprint: 'ABCD-EFGH-IJKL',
              platform: 'desktop',
              relay: 'https://relay.example',
              status: 'active'
            }
          ]
        }
      }

      if (method === 'link.controller.dispatch') {
        return { response: { job: { id: 'job-1', status: 'queued' } } }
      }

      throw new Error(`unexpected method: ${method}`)
    })
    const { LinkSettings } = await import('./link-settings')
    render(<LinkSettings />)

    fireEvent.click(await screen.findByRole('button', { name: 'Dispatch' }))
    fireEvent.change(screen.getByLabelText('Dispatch prompt'), {
      target: { value: 'Run the release checks' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Dispatch Work' }))

    await waitFor(() =>
      expect(requestGateway).toHaveBeenCalledWith(
        'link.controller.dispatch',
        expect.objectContaining({
          controller_id: 'controller_1234567890',
          idempotency_key: '00000000-0000-4000-8000-000000000001',
          prompt: 'Run the release checks'
        }),
        130_000
      )
    )
    expect(randomUUID).toHaveBeenCalledTimes(1)
  })
})
