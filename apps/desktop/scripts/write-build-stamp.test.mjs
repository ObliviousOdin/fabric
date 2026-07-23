import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveReleaseChannel } from './write-build-stamp.mjs'

test('release channel is explicit and every other build remains source mode', () => {
  assert.equal(resolveReleaseChannel('release'), 'release')
  assert.equal(resolveReleaseChannel(' RELEASE '), 'release')
  assert.equal(resolveReleaseChannel('ci'), 'source')
  assert.equal(resolveReleaseChannel(''), 'source')
})
