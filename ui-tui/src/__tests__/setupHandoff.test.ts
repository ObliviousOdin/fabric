import { beforeEach, describe, expect, it, vi } from 'vitest'

import { runExternalSetup, type RunExternalSetupOptions } from '../app/setupHandoff.js'
import { getUiState, resetUiState } from '../app/uiStore.js'

const makeContext = () => {
  const rpc = vi.fn().mockResolvedValue({ provider_configured: true })
  const newSession = vi.fn()
  const sys = vi.fn()

  const ctx = {
    gateway: { rpc },
    session: { newSession },
    transcript: { sys }
  } as unknown as RunExternalSetupOptions['ctx']

  return { ctx, newSession, rpc, sys }
}

describe('runExternalSetup', () => {
  beforeEach(() => resetUiState())

  it('launches and reports the Fabric setup command', async () => {
    const { ctx, newSession, rpc, sys } = makeContext()
    const launcher = vi.fn().mockResolvedValue({ code: 0 })

    await runExternalSetup({
      args: ['setup', '--profile', 'dev'],
      ctx,
      done: 'setup complete',
      launcher,
      suspend: async run => void (await run())
    })

    expect(launcher).toHaveBeenCalledWith(['setup', '--profile', 'dev'])
    expect(sys).toHaveBeenNthCalledWith(1, 'launching `fabric setup --profile dev`…')
    expect(sys).toHaveBeenNthCalledWith(2, 'setup complete')
    expect(rpc).toHaveBeenCalledWith('setup.status', {})
    expect(newSession).toHaveBeenCalledTimes(1)
  })

  it('keeps launch failures Fabric-branded', async () => {
    const { ctx, newSession, rpc, sys } = makeContext()

    await runExternalSetup({
      args: ['setup'],
      ctx,
      done: 'setup complete',
      launcher: vi.fn().mockResolvedValue({ code: null, error: 'spawn fabric ENOENT' }),
      suspend: async run => void (await run())
    })

    expect(sys).toHaveBeenNthCalledWith(1, 'launching `fabric setup`…')
    expect(sys).toHaveBeenNthCalledWith(2, 'error launching fabric: spawn fabric ENOENT')
    expect(getUiState().status).toBe('setup required')
    expect(rpc).not.toHaveBeenCalled()
    expect(newSession).not.toHaveBeenCalled()
  })
})
