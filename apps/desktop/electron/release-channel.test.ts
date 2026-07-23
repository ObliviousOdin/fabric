import assert from 'node:assert/strict'
import test from 'node:test'

import {
  compareDesktopVersions,
  normalizeInstallStamp,
  releaseAssetUrl,
  requiresManagedBackendAlignment,
  selectInstallerForRuntime,
  usesPackagedInstallerUpdates,
  validateDesktopReleaseManifest
} from './release-channel'

const manifest = {
  schema_version: 1,
  repository: 'ObliviousOdin/fabric',
  tag: 'v2026.7.23',
  source_sha: 'a'.repeat(40),
  desktop_app_version: '0.22.0',
  platforms: ['linux', 'mac', 'win'],
  files: [
    {
      name: 'Fabric-0.22.0-mac-arm64.dmg',
      ext: 'dmg',
      arch: 'arm64',
      platform: 'mac',
      size: 10,
      sha256: 'b'.repeat(64)
    },
    {
      name: 'Fabric-0.22.0-win-x64.exe',
      ext: 'exe',
      arch: 'x64',
      platform: 'win',
      size: 20,
      sha256: 'c'.repeat(64)
    },
    {
      name: 'Fabric-0.22.0-linux-x86_64.AppImage',
      ext: 'AppImage',
      arch: 'x86_64',
      platform: 'linux',
      size: 30,
      sha256: 'd'.repeat(64)
    }
  ]
}

test('normalizes schema v1 as source and schema v2 with explicit release channel', () => {
  assert.equal(
    normalizeInstallStamp({ schemaVersion: 1, commit: 'a'.repeat(40) })?.channel,
    'source'
  )
  assert.equal(
    normalizeInstallStamp({ schemaVersion: 2, commit: 'b'.repeat(40), channel: 'release' })?.channel,
    'release'
  )
  assert.equal(normalizeInstallStamp({ schemaVersion: 3, commit: 'a'.repeat(40) }), null)
  assert.equal(normalizeInstallStamp({ schemaVersion: 2, commit: 'a'.repeat(40), channel: 'mystery' }), null)
})

test('release stamp requires exact managed marker alignment', () => {
  const stamp = normalizeInstallStamp({
    schemaVersion: 2,
    commit: 'a'.repeat(40),
    channel: 'release'
  })

  assert.equal(
    requiresManagedBackendAlignment(stamp, { schemaVersion: 1, pinnedCommit: 'b'.repeat(40) }, 'b'.repeat(40)),
    true
  )
  assert.equal(
    requiresManagedBackendAlignment(stamp, { schemaVersion: 1, pinnedCommit: 'a'.repeat(40) }, 'a'.repeat(40)),
    false
  )
  assert.equal(
    requiresManagedBackendAlignment(stamp, { schemaVersion: 1, pinnedCommit: 'a'.repeat(40) }, 'b'.repeat(40)),
    true
  )
  assert.equal(
    requiresManagedBackendAlignment(
      normalizeInstallStamp({ schemaVersion: 1, commit: 'a'.repeat(40) }),
      { schemaVersion: 1, pinnedCommit: 'b'.repeat(40) },
      'b'.repeat(40)
    ),
    false
  )
})

test('only an explicit release stamp routes updates to packaged installers', () => {
  assert.equal(
    usesPackagedInstallerUpdates(
      normalizeInstallStamp({ schemaVersion: 2, commit: 'a'.repeat(40), channel: 'release' })
    ),
    true
  )
  assert.equal(
    usesPackagedInstallerUpdates(normalizeInstallStamp({ schemaVersion: 1, commit: 'a'.repeat(40) })),
    false
  )
  assert.equal(usesPackagedInstallerUpdates(null), false)
})

test('compares desktop semantic versions conservatively', () => {
  assert.equal(compareDesktopVersions('0.22.0', '0.21.9'), 1)
  assert.equal(compareDesktopVersions('0.22.0', '0.22.0'), 0)
  assert.equal(compareDesktopVersions('0.22.0-beta.1', '0.22.0'), -1)
  assert.equal(compareDesktopVersions('invalid', '0.22.0'), null)
})

test('validates the release manifest and selects the platform installer', () => {
  const valid = validateDesktopReleaseManifest(manifest)

  assert.equal(selectInstallerForRuntime(valid, 'darwin', 'arm64')?.asset.ext, 'dmg')
  assert.equal(selectInstallerForRuntime(valid, 'win32', 'x64')?.asset.ext, 'exe')
  assert.equal(selectInstallerForRuntime(valid, 'linux', 'x64')?.asset.ext, 'AppImage')
  assert.equal(selectInstallerForRuntime(valid, 'darwin', 'x64'), null)
})

test('rejects traversal and noncanonical manifests', () => {
  assert.throws(
    () =>
      validateDesktopReleaseManifest({
        ...manifest,
        files: [{ ...manifest.files[0], name: '../Fabric-0.22.0-mac-arm64.dmg' }]
      }),
    /invalid file entry/
  )
  assert.throws(
    () => validateDesktopReleaseManifest({ ...manifest, repository: 'someone/fork' }),
    /unexpected repository/
  )
  assert.throws(() => releaseAssetUrl('latest', 'Fabric.exe'), /invalid tag/)
})
