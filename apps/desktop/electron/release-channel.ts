const OFFICIAL_REPOSITORY = 'ObliviousOdin/fabric'
const OFFICIAL_RELEASE_BASE = `https://github.com/${OFFICIAL_REPOSITORY}/releases/download`
const RELEASE_TAG_RE = /^v20\d{2}\.(?:[1-9]|1[0-2])\.(?:[1-9]|[12]\d|3[01])(?:\.[2-9]\d*)?$/
const SOURCE_SHA_RE = /^[0-9a-f]{40}$/
const STAMP_SHA_RE = /^[0-9a-f]{7,40}$/i
const SEMVER_RE = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/
const SHA256_RE = /^[0-9a-f]{64}$/

export interface InstallStamp {
  schemaVersion: 1 | 2
  commit: string
  branch: string | null
  builtAt: string | null
  dirty: boolean
  source: string | null
  channel: 'release' | 'source'
  path?: string
}

export interface BootstrapMarker {
  schemaVersion?: number
  pinnedCommit?: string
}

export interface DesktopReleaseFile {
  name: string
  ext: string
  arch: string
  platform: 'mac' | 'win' | 'linux'
  size: number
  sha256: string
}

export interface DesktopReleaseManifest {
  schema_version: 1
  repository: typeof OFFICIAL_REPOSITORY
  tag: string
  source_sha: string
  desktop_app_version: string
  platforms: Array<'mac' | 'win' | 'linux'>
  files: DesktopReleaseFile[]
}

export interface SelectedInstaller {
  asset: DesktopReleaseFile
  downloadUrl: string
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

export function normalizeInstallStamp(value: unknown, stampPath?: string): InstallStamp | null {
  const stamp = objectValue(value)
  if (!stamp || (stamp.schemaVersion !== 1 && stamp.schemaVersion !== 2)) {
    return null
  }
  if (typeof stamp.commit !== 'string' || !STAMP_SHA_RE.test(stamp.commit)) {
    return null
  }

  const channel = stamp.schemaVersion === 2 ? stamp.channel : 'source'
  if (channel !== 'release' && channel !== 'source') {
    return null
  }

  return Object.freeze({
    schemaVersion: stamp.schemaVersion,
    commit: stamp.commit,
    branch: typeof stamp.branch === 'string' && stamp.branch ? stamp.branch : null,
    builtAt: typeof stamp.builtAt === 'string' && stamp.builtAt ? stamp.builtAt : null,
    dirty: Boolean(stamp.dirty),
    source: typeof stamp.source === 'string' && stamp.source ? stamp.source : null,
    channel,
    ...(stampPath ? { path: stampPath } : {})
  })
}

export function requiresManagedBackendAlignment(
  installStamp: InstallStamp | null,
  marker: BootstrapMarker | null,
  activeCommit?: string | null
): boolean {
  if (installStamp?.channel !== 'release' || !marker || marker.schemaVersion !== 1) {
    return false
  }

  if (
    typeof marker.pinnedCommit !== 'string' ||
    marker.pinnedCommit.toLowerCase() !== installStamp.commit.toLowerCase()
  ) {
    return true
  }

  return (
    typeof activeCommit !== 'string' ||
    activeCommit.toLowerCase() !== installStamp.commit.toLowerCase()
  )
}

export function usesPackagedInstallerUpdates(installStamp: InstallStamp | null): boolean {
  return installStamp?.channel === 'release'
}

function parseSemver(version: string): [number, number, number, string | null] | null {
  const match = SEMVER_RE.exec(version)
  if (!match) {
    return null
  }

  return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] || null]
}

export function compareDesktopVersions(left: string, right: string): number | null {
  const a = parseSemver(left)
  const b = parseSemver(right)
  if (!a || !b) {
    return null
  }

  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) {
      return Number(a[index]) > Number(b[index]) ? 1 : -1
    }
  }

  if (a[3] === b[3]) return 0
  if (a[3] === null) return 1
  if (b[3] === null) return -1
  return a[3].localeCompare(b[3])
}

function isExpectedArtifactName(file: DesktopReleaseFile, version: string): boolean {
  return file.name === `Fabric-${version}-${file.platform}-${file.arch}.${file.ext}`
}

export function validateDesktopReleaseManifest(value: unknown): DesktopReleaseManifest {
  const manifest = objectValue(value)
  if (!manifest || manifest.schema_version !== 1) {
    throw new Error('Desktop release manifest has an unsupported schema.')
  }
  if (manifest.repository !== OFFICIAL_REPOSITORY) {
    throw new Error('Desktop release manifest names an unexpected repository.')
  }
  if (typeof manifest.tag !== 'string' || !RELEASE_TAG_RE.test(manifest.tag)) {
    throw new Error('Desktop release manifest has an invalid production tag.')
  }
  if (typeof manifest.source_sha !== 'string' || !SOURCE_SHA_RE.test(manifest.source_sha)) {
    throw new Error('Desktop release manifest has an invalid source SHA.')
  }
  if (typeof manifest.desktop_app_version !== 'string' || !parseSemver(manifest.desktop_app_version)) {
    throw new Error('Desktop release manifest has an invalid desktop version.')
  }
  if (!Array.isArray(manifest.platforms) || !Array.isArray(manifest.files)) {
    throw new Error('Desktop release manifest is missing platform or file data.')
  }

  const validPlatforms = new Set(['mac', 'win', 'linux'])
  const names = new Set<string>()
  const files = manifest.files.map(raw => {
    const file = objectValue(raw)
    if (
      !file ||
      typeof file.name !== 'string' ||
      file.name !== file.name.split(/[\\/]/).pop() ||
      typeof file.ext !== 'string' ||
      typeof file.arch !== 'string' ||
      typeof file.platform !== 'string' ||
      !validPlatforms.has(file.platform) ||
      typeof file.size !== 'number' ||
      !Number.isSafeInteger(file.size) ||
      file.size <= 0 ||
      typeof file.sha256 !== 'string' ||
      !SHA256_RE.test(file.sha256)
    ) {
      throw new Error('Desktop release manifest contains an invalid file entry.')
    }

    const normalized = file as unknown as DesktopReleaseFile
    if (!isExpectedArtifactName(normalized, manifest.desktop_app_version as string)) {
      throw new Error(`Desktop release manifest contains an unexpected artifact name: ${file.name}`)
    }
    if (names.has(normalized.name)) {
      throw new Error(`Desktop release manifest contains duplicate artifact ${normalized.name}.`)
    }
    names.add(normalized.name)
    return normalized
  })

  if (files.length === 0) {
    throw new Error('Desktop release manifest contains no installers.')
  }

  return {
    schema_version: 1,
    repository: OFFICIAL_REPOSITORY,
    tag: manifest.tag,
    source_sha: manifest.source_sha,
    desktop_app_version: manifest.desktop_app_version,
    platforms: manifest.platforms.filter(
      (platform): platform is 'mac' | 'win' | 'linux' =>
        typeof platform === 'string' && validPlatforms.has(platform)
    ),
    files
  }
}

function targetForRuntime(
  runtimePlatform: NodeJS.Platform,
  runtimeArch: string
): { platform: DesktopReleaseFile['platform']; arch: string; ext: string } | null {
  if (runtimePlatform === 'darwin' && runtimeArch === 'arm64') {
    return { platform: 'mac', arch: 'arm64', ext: 'dmg' }
  }
  if (runtimePlatform === 'win32' && runtimeArch === 'x64') {
    return { platform: 'win', arch: 'x64', ext: 'exe' }
  }
  if (runtimePlatform === 'linux' && runtimeArch === 'x64') {
    return { platform: 'linux', arch: 'x86_64', ext: 'AppImage' }
  }
  return null
}

export function releaseAssetUrl(tag: string, name: string): string {
  if (!RELEASE_TAG_RE.test(tag) || name !== name.split(/[\\/]/).pop()) {
    throw new Error('Cannot build a release URL from an invalid tag or asset name.')
  }
  return `${OFFICIAL_RELEASE_BASE}/${encodeURIComponent(tag)}/${encodeURIComponent(name)}`
}

export function selectInstallerForRuntime(
  manifest: DesktopReleaseManifest,
  runtimePlatform: NodeJS.Platform,
  runtimeArch: string
): SelectedInstaller | null {
  const target = targetForRuntime(runtimePlatform, runtimeArch)
  if (!target) {
    return null
  }

  const asset = manifest.files.find(
    file => file.platform === target.platform && file.arch === target.arch && file.ext === target.ext
  )
  return asset ? { asset, downloadUrl: releaseAssetUrl(manifest.tag, asset.name) } : null
}

export { OFFICIAL_REPOSITORY }
