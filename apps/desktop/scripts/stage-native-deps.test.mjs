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

test('ensurePackedNodePtyHelpersExecutable finds spawn-helper inside macOS .app under appOutDir', () => {
  // electron-builder afterPack on darwin: appOutDir is the parent of Fabric.app
  // (see notarize.mjs: path.join(appOutDir, `${appName}.app`)).
  const appOutDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-after-pack-mac-'))
  try {
    const helperDir = path.join(
      appOutDir,
      'Fabric.app',
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

    const fixedByName = ensurePackedNodePtyHelpersExecutable(appOutDir, {
      productFilename: 'Fabric'
    })
    assert.equal(fixedByName.length, 1)
    assert.equal(fixedByName[0], helper)
    assert.notEqual(fs.statSync(helper).mode & 0o111, 0)

    // Reset and ensure bare discovery via readdir of *.app still works.
    fs.chmodSync(helper, 0o644)
    const fixedByDiscover = ensurePackedNodePtyHelpersExecutable(appOutDir)
    assert.equal(fixedByDiscover.length, 1)
    assert.notEqual(fs.statSync(helper).mode & 0o111, 0)
  } finally {
    fs.rmSync(appOutDir, { recursive: true, force: true })
  }
})
