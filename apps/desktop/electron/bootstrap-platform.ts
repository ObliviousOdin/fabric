import fs from 'node:fs'

function isWslEnvironment(env = process.env, platform = process.platform, kernelRelease = null) {
  if (platform !== 'linux') {
    return false
  }

  if (env.WSL_DISTRO_NAME || env.WSL_INTEROP) {
    return true
  }

  try {
    const release = kernelRelease ?? fs.readFileSync('/proc/sys/kernel/osrelease', 'utf8')

    return /microsoft|wsl/i.test(release)
  } catch {
    return false
  }
}

function isWindowsBinaryPathInWsl(
  filePath,
  options: { isWsl?: boolean; env?: NodeJS.ProcessEnv; platform?: NodeJS.Platform } = {}
) {
  const isWsl = options.isWsl ?? isWslEnvironment(options.env, options.platform)

  if (!isWsl) {
    return false
  }

  const normalized = String(filePath || '')
    .replace(/\\/g, '/')
    .toLowerCase()

  return (
    normalized.endsWith('.exe') ||
    normalized.endsWith('.cmd') ||
    normalized.endsWith('.bat') ||
    normalized.endsWith('.ps1')
  )
}

function bundledRuntimeImportCheck(platform = process.platform) {
  return platform === 'win32' ? 'import fastapi, uvicorn, winpty' : 'import fastapi, uvicorn, ptyprocess'
}

/**
 * Decide whether the app is being shown over a remote/forwarded display, where
 * Chromium's GPU compositor produces an unstable, flickering surface (it can't
 * present accelerated layers cleanly over the wire). Native local Windows/macOS
 * sessions composite locally and never hit this, so we only fall back to
 * software rendering when a remote display is detected.
 *
 * Returns a short reason string when GPU acceleration should be disabled, or
 * null to keep it enabled.
 *
 * Pure + dependency-free so it can be unit-tested and called before app ready.
 */
function detectRemoteDisplay(options: { env?: NodeJS.ProcessEnv; platform?: NodeJS.Platform } = {}) {
  const env = options.env ?? process.env
  const platform = options.platform ?? process.platform

  // Launched from an SSH session → the display is X11-forwarded or otherwise
  // remote. Covers the common `ssh user@box` + GUI-forwarding case.
  if (env.SSH_CONNECTION || env.SSH_CLIENT || env.SSH_TTY) {
    return 'ssh-session'
  }

  if (platform === 'linux') {
    // X11 forwarding sets DISPLAY to "<host>:N" (e.g. "localhost:10.0"); a
    // local X server is ":0"/":1" with no host part before the colon.
    // NB: WSLg deliberately isn't treated as remote — it reports
    // GPU-accelerated vGPU surfaces locally and doesn't show the flicker.
    const display = String(env.DISPLAY || '')

    if (display.includes(':') && display.split(':')[0]) {
      return `x11-forwarding (DISPLAY=${display})`
    }
  }

  if (platform === 'win32') {
    // RDP sessions report SESSIONNAME like "RDP-Tcp#7"; the local console is
    // "Console".
    const sessionName = String(env.SESSIONNAME || '')

    if (/^rdp-/i.test(sessionName)) {
      return `rdp (SESSIONNAME=${sessionName})`
    }
  }

  return null
}

export { bundledRuntimeImportCheck, detectRemoteDisplay, isWindowsBinaryPathInWsl, isWslEnvironment }
