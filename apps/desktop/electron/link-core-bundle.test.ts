import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { resolveBundledLinkCore } from './link-core-bundle'

const COMMIT = 'a'.repeat(40)

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-link-bundle-'))
  const linkRoot = path.join(root, 'link-core')
  fs.mkdirSync(linkRoot)
  const name = 'fabric_link_core-0.21.0-py3-none-linux_x86_64.whl'
  const wheelPath = path.join(linkRoot, name)
  const payload = Buffer.from('reviewed-native-wheel')
  fs.writeFileSync(wheelPath, payload)

  const manifest = {
    schema_version: 1,
    source_sha: COMMIT,
    version: '0.21.0',
    platform: 'linux',
    wheel: {
      name,
      sha256: crypto.createHash('sha256').update(payload).digest('hex'),
      size: payload.length
    }
  }

  fs.writeFileSync(path.join(linkRoot, 'link-core-manifest.json'), JSON.stringify(manifest))

  return { manifest, root, wheelPath }
}

test('resolves only a same-commit, same-platform, checksum-matched wheel', t => {
  const { manifest, root, wheelPath } = fixture()
  t.after(() => fs.rmSync(root, { force: true, recursive: true }))

  assert.deepEqual(
    resolveBundledLinkCore({
      installCommit: COMMIT,
      platform: 'linux',
      resourcesPath: root
    }),
    {
      path: wheelPath,
      sha256: manifest.wheel.sha256
    }
  )
})

test('rejects a wheel modified after release staging', t => {
  const { root, wheelPath } = fixture()
  t.after(() => fs.rmSync(root, { force: true, recursive: true }))
  fs.writeFileSync(wheelPath, 'tampered-native-wheel')

  assert.throws(
    () =>
      resolveBundledLinkCore({
        installCommit: COMMIT,
        platform: 'linux',
        resourcesPath: root
      }),
    /wrong size|checksum mismatch/
  )
})

test('rejects a release bundle from another source revision', t => {
  const { root } = fixture()
  t.after(() => fs.rmSync(root, { force: true, recursive: true }))

  assert.throws(
    () =>
      resolveBundledLinkCore({
        installCommit: 'b'.repeat(40),
        platform: 'linux',
        resourcesPath: root
      }),
    /manifest contract/
  )
})
