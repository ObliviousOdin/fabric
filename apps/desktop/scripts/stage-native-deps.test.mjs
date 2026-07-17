import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { ensureExecutable, ensurePackedNodePtyHelpersExecutable } from './stage-native-deps.mjs'

test('ensureExecutable sets the +x bit on a non-executable file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-spawn-helper-'))
  try {
    const helper = path.join(dir, 'spawn-helper')
    fs.writeFileSync(helper, '#!/bin/sh\necho ok\n', { mode: 0o644 })
    assert.equal((fs.statSync(helper).mode & 0o111) === 0, true, 'fixture starts non-executable')

    assert.equal(ensureExecutable(helper), true)
    assert.notEqual(fs.statSync(helper).mode & 0o111, 0, 'helper must be executable after ensureExecutable')
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('ensureExecutable is a no-op for missing paths', () => {
  assert.equal(ensureExecutable('/tmp/definitely-does-not-exist-fabric-spawn-helper'), false)
  assert.equal(ensureExecutable(''), false)
})

test('ensurePackedNodePtyHelpersExecutable chmods spawn-helper under app.asar.unpacked', () => {
  const appOutDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-after-pack-'))
  try {
    const helperDir = path.join(
      appOutDir,
      'Contents',
      'Resources',
      'app.asar.unpacked',
      'dist',
      'node_modules',
      'node-pty',
      'prebuilds',
      'darwin-arm64'
    )
    fs.mkdirSync(helperDir, { recursive: true })
    const helper = path.join(helperDir, 'spawn-helper')
    fs.writeFileSync(helper, '#!/bin/sh\necho ok\n', { mode: 0o644 })

    const fixed = ensurePackedNodePtyHelpersExecutable(appOutDir)
    assert.equal(fixed.length, 1)
    assert.equal(fixed[0], helper)
    assert.notEqual(fs.statSync(helper).mode & 0o111, 0)
  } finally {
    fs.rmSync(appOutDir, { recursive: true, force: true })
  }
})
