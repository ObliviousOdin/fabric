import os from 'node:os'
import path from 'node:path'

// Match the POSIX fallback surface used by the Python terminal environment.
// macOS apps launched from Finder/Dock often inherit only /usr/bin:/bin:/usr/sbin:/sbin,
// which misses Apple Silicon Homebrew and user-installed CLI tools such as codex.
const POSIX_SANE_PATH_ENTRIES = Object.freeze([
  '/opt/homebrew/bin',
  '/opt/homebrew/sbin',
  '/usr/local/sbin',
  '/usr/local/bin',
  '/usr/sbin',
  '/usr/bin',
  '/sbin',
  '/bin'
])

function delimiterForPlatform(platform = process.platform) {
  return platform === 'win32' ? ';' : ':'
}

function pathModuleForPlatform(platform = process.platform) {
  return platform === 'win32' ? path.win32 : path.posix
}

function pathEnvKey(env = process.env, platform = process.platform) {
  if (platform !== 'win32') {
    return 'PATH'
  }

  return Object.keys(env || {}).find(key => key.toUpperCase() === 'PATH') || 'PATH'
}

function currentPathValue(env = process.env, platform = process.platform) {
  const key = pathEnvKey(env, platform)

  return env?.[key] || ''
}

function appendUniquePathEntries(entries, { delimiter = path.delimiter } = {}) {
  const seen = new Set()
  const ordered = []

  for (const entry of entries) {
    if (!entry) {
      continue
    }
    const parts = Array.isArray(entry) ? entry : String(entry).split(delimiter)

    for (const part of parts) {
      if (!part || seen.has(part)) {
        continue
      }
      seen.add(part)
      ordered.push(part)
    }
  }

  return ordered.join(delimiter)
}

function buildDesktopBackendPath({
  fabricHome,
  venvRoot,
  home,
  currentPath = '',
  platform = process.platform,
  pathModule = pathModuleForPlatform(platform)
}: any = {}) {
  const delimiter = delimiterForPlatform(platform)
  const fabricNodeBin = fabricHome ? pathModule.join(fabricHome, 'node', 'bin') : null
  const venvBin = venvRoot ? pathModule.join(venvRoot, platform === 'win32' ? 'Scripts' : 'bin') : null
  // Finder/Dock-launched macOS apps inherit a minimal PATH even though user-level
  // installers place Fabric and companion binaries (for example cua-driver) in
  // ~/.local/bin. Keep it ahead of the inherited PATH, alongside the managed
  // runtime bins, so the backend sees the same user tools as a login shell.
  const userLocalBin = platform === 'win32' || !home ? null : pathModule.join(home, '.local', 'bin')
  const saneEntries = platform === 'win32' ? [] : POSIX_SANE_PATH_ENTRIES

  return appendUniquePathEntries([fabricNodeBin, venvBin, userLocalBin, currentPath, saneEntries], { delimiter })
}

function normalizeFabricHomeRoot(fabricHome, { pathModule = pathModuleForPlatform(process.platform) }: any = {}) {
  if (!fabricHome) {
    return fabricHome
  }
  const resolved = pathModule.resolve(String(fabricHome))
  const parent = pathModule.dirname(resolved)

  if (pathModule.basename(parent).toLowerCase() === 'profiles') {
    return pathModule.dirname(parent)
  }

  return resolved
}

/**
 * Resolve the desktop's global Fabric state root without touching Electron.
 * FABRIC_HOME is canonical; FABRIC_HOME and legacy default directories remain
 * readable so an installed Fabric desktop can upgrade in place without
 * orphaning config, sessions, credentials, or logs.
 */
function resolveDesktopHome({
  env = process.env,
  platform = process.platform,
  home,
  localAppData,
  userDataOverride,
  directoryExists = () => false,
  readRegistryValue = () => null,
  pathModule = pathModuleForPlatform(platform)
}: any = {}) {
  const normalize = value => normalizeFabricHomeRoot(value, { pathModule })
  const fabricOverride = String(env?.FABRIC_HOME || '').trim()
  const fabricOverride = String(env?.FABRIC_HOME || '').trim()

  if (fabricOverride) {
    return normalize(fabricOverride)
  }
  if (fabricOverride) {
    return normalize(fabricOverride)
  }
  if (userDataOverride) {
    return pathModule.join(pathModule.resolve(String(userDataOverride)), 'fabric-home')
  }

  if (platform === 'win32') {
    // Explorer-launched apps can have a stale login-time process.env. Read the
    // live user registry in the same canonical-then-compatibility order.
    const registryFabric = String(readRegistryValue('FABRIC_HOME') || '').trim()
    const registryFabric = String(readRegistryValue('FABRIC_HOME') || '').trim()

    if (registryFabric) {
      return normalize(registryFabric)
    }
    if (registryFabric) {
      return normalize(registryFabric)
    }
  }

  const resolvedHome = pathModule.resolve(String(home || ''))
  const base =
    platform === 'win32'
      ? pathModule.resolve(
          String(localAppData || env?.LOCALAPPDATA || pathModule.join(resolvedHome, 'AppData', 'Local'))
        )
      : resolvedHome
  const modern = platform === 'win32' ? pathModule.join(base, 'fabric') : pathModule.join(base, '.fabric')
  const legacy = platform === 'win32' ? pathModule.join(base, 'hermes') : pathModule.join(base, '.hermes')

  if (!directoryExists(modern) && directoryExists(legacy)) {
    return legacy
  }

  return modern
}

function buildDesktopBackendEnv({
  fabricHome,
  pythonPathEntries = [],
  venvRoot,
  currentEnv = process.env,
  platform = process.platform,
  pathModule = pathModuleForPlatform(platform)
}: any = {}) {
  const delimiter = delimiterForPlatform(platform)
  const currentPythonPath = currentEnv?.PYTHONPATH || ''
  const key = pathEnvKey(currentEnv, platform)
  const home = currentEnv?.HOME || (platform === process.platform ? os.homedir() : '')

  return {
    FABRIC_HOME: fabricHome,
    FABRIC_HOME: fabricHome,
    PYTHONPATH: appendUniquePathEntries([...pythonPathEntries, currentPythonPath], { delimiter }),
    [key]: buildDesktopBackendPath({
      fabricHome,
      venvRoot,
      home,
      currentPath: currentPathValue(currentEnv, platform),
      platform,
      pathModule
    })
  }
}

export {
  appendUniquePathEntries,
  buildDesktopBackendEnv,
  buildDesktopBackendPath,
  delimiterForPlatform,
  normalizeFabricHomeRoot,
  pathEnvKey,
  POSIX_SANE_PATH_ENTRIES,
  resolveDesktopHome
}
