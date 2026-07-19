/**
 * Normalize 24-bit color advertisement before chalk / supports-color imports.
 *
 * macOS Terminal.app before Tahoe 26 does not support RGB SGR, so do not
 * infer truecolor from TERM_PROGRAM=Apple_Terminal.
 */

const isAppleTerminal = (env: NodeJS.ProcessEnv = process.env) => (env.TERM_PROGRAM ?? '').trim() === 'Apple_Terminal'

const isAdvertisedTruecolor = (env: NodeJS.ProcessEnv = process.env) => {
  const colorTerm = (env.COLORTERM ?? '').trim().toLowerCase()
  const forceColor = (env.FORCE_COLOR ?? '').trim()

  return colorTerm === 'truecolor' || colorTerm === '24bit' || forceColor === '3'
}

export function shouldDowngradeAppleTerminalTruecolor(env: NodeJS.ProcessEnv = process.env): boolean {
  if (!isAppleTerminal(env)) {
    return false
  }

  return isAdvertisedTruecolor(env)
}

if (shouldDowngradeAppleTerminalTruecolor()) {
  // Terminal.app may advertise truecolor even when RGB SGR paths render
  // incorrectly. Keep Fabric on the safer TERM-driven 256-color path.
  delete process.env.COLORTERM

  if ((process.env.FORCE_COLOR ?? '').trim() === '3') {
    delete process.env.FORCE_COLOR
  }
}

export {}
