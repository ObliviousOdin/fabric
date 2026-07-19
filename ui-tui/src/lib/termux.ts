const TERMUX_PREFIX = '/data/data/com.termux/files/usr'

export const isTermuxEnv = (env: NodeJS.ProcessEnv = process.env): boolean => {
  const prefix = String(env.PREFIX ?? '')

  return Boolean(env.TERMUX_VERSION) || prefix.includes(TERMUX_PREFIX)
}

/**
 * Return true when Fabric should enable Termux-focused TUI defaults.
 *
 * Termux is detected from its standard environment markers.
 */
export const isTermuxTuiMode = (env: NodeJS.ProcessEnv = process.env): boolean => {
  return isTermuxEnv(env)
}
