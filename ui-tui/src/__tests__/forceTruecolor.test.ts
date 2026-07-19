import { describe, expect, it } from 'vitest'

const ENV_KEYS = ['COLORTERM', 'FORCE_COLOR', 'NO_COLOR', 'TERM', 'TERM_PROGRAM'] as const
let importId = 0

async function withCleanEnv(setup: () => void, body: () => Promise<void>) {
  const saved: Record<string, string | undefined> = {}

  for (const k of ENV_KEYS) {
    saved[k] = process.env[k]
    delete process.env[k]
  }

  try {
    setup()
    await body()
  } finally {
    for (const k of ENV_KEYS) {
      if (saved[k] === undefined) {
        delete process.env[k]
      } else {
        process.env[k] = saved[k]
      }
    }
  }
}

describe('forceTruecolor', () => {
  it('does not force truecolor by default', async () => {
    await withCleanEnv(
      () => {},
      async () => {
        await import('../lib/forceTruecolor.js?t=default-' + importId++)
        expect(process.env.COLORTERM).toBeUndefined()
        expect(process.env.FORCE_COLOR).toBeUndefined()
      }
    )
  })

  it('does not infer truecolor from Apple Terminal on pre-Tahoe macOS', async () => {
    await withCleanEnv(
      () => {
        process.env.TERM_PROGRAM = 'Apple_Terminal'
        process.env.TERM = 'xterm-256color'
      },
      async () => {
        await import('../lib/forceTruecolor.js?t=apple-' + importId++)
        expect(process.env.COLORTERM).toBeUndefined()
        expect(process.env.FORCE_COLOR).toBeUndefined()
      }
    )
  })

  it('downgrades Apple Terminal when truecolor is only advertised by env', async () => {
    await withCleanEnv(
      () => {
        process.env.TERM_PROGRAM = 'Apple_Terminal'
        process.env.COLORTERM = 'truecolor'
        process.env.FORCE_COLOR = '3'
      },
      async () => {
        const mod = await import('../lib/forceTruecolor.js?t=downgrade-' + importId++)
        expect(
          mod.shouldDowngradeAppleTerminalTruecolor({
            TERM_PROGRAM: 'Apple_Terminal',
            COLORTERM: 'truecolor',
            FORCE_COLOR: '3'
          } as NodeJS.ProcessEnv)
        ).toBe(true)
        expect(process.env.COLORTERM).toBeUndefined()
        expect(process.env.FORCE_COLOR).toBeUndefined()
      }
    )
  })

  it('keeps non-Apple terminals untouched when they advertise truecolor', async () => {
    await withCleanEnv(
      () => {
        process.env.TERM_PROGRAM = 'vscode'
        process.env.COLORTERM = 'truecolor'
        process.env.FORCE_COLOR = '3'
      },
      async () => {
        const mod = await import('../lib/forceTruecolor.js?t=keep-non-apple-' + importId++)
        expect(
          mod.shouldDowngradeAppleTerminalTruecolor({
            TERM_PROGRAM: 'vscode',
            COLORTERM: 'truecolor',
            FORCE_COLOR: '3'
          } as NodeJS.ProcessEnv)
        ).toBe(false)
        expect(process.env.COLORTERM).toBe('truecolor')
        expect(process.env.FORCE_COLOR).toBe('3')
      }
    )
  })

  it('leaves a non-Apple FORCE_COLOR setting untouched', async () => {
    await withCleanEnv(
      () => {
        process.env.FORCE_COLOR = ''
      },
      async () => {
        await import('../lib/forceTruecolor.js?t=force-color-' + importId++)
        expect(process.env.COLORTERM).toBeUndefined()
        expect(process.env.FORCE_COLOR).toBe('')
      }
    )
  })
})
