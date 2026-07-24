import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

export interface BundledLinkCore {
  path: string
  sha256: string
}

interface ResolveBundledLinkCoreOptions {
  installCommit: string
  platform: NodeJS.Platform
  resourcesPath: string
}

const PLATFORM_NAMES: Partial<Record<NodeJS.Platform, string>> = {
  darwin: 'mac',
  linux: 'linux',
  win32: 'win'
}

export function resolveBundledLinkCore({
  installCommit,
  platform,
  resourcesPath
}: ResolveBundledLinkCoreOptions): BundledLinkCore {
  const root = path.join(resourcesPath, 'link-core')
  const manifestPath = path.join(root, 'link-core-manifest.json')
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  const wheel = manifest?.wheel

  if (
    manifest?.schema_version !== 1 ||
    manifest?.source_sha !== installCommit ||
    manifest?.platform !== PLATFORM_NAMES[platform] ||
    !wheel ||
    typeof wheel.name !== 'string' ||
    path.basename(wheel.name) !== wheel.name ||
    typeof wheel.sha256 !== 'string' ||
    !/^[0-9a-f]{64}$/.test(wheel.sha256) ||
    !Number.isSafeInteger(wheel.size) ||
    wheel.size <= 0
  ) {
    throw new Error('Fabric Link core manifest contract mismatch')
  }

  const wheelPath = path.join(root, wheel.name)
  const wheelStat = fs.lstatSync(wheelPath)

  if (!wheelStat.isFile() || wheelStat.isSymbolicLink() || wheelStat.size !== wheel.size) {
    throw new Error('Fabric Link core wheel is missing, linked, or has the wrong size')
  }

  const actual = crypto.createHash('sha256').update(fs.readFileSync(wheelPath)).digest()
  const expected = Buffer.from(wheel.sha256, 'hex')

  if (actual.length !== expected.length || !crypto.timingSafeEqual(actual, expected)) {
    throw new Error('Fabric Link core wheel checksum mismatch')
  }

  return { path: wheelPath, sha256: wheel.sha256 }
}
