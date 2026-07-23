import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveNotarizationCredentials } from './notarize.mjs'

test('local unsigned builds may skip notarization when no credential is present', () => {
  assert.deepEqual(resolveNotarizationCredentials({}), { mode: 'skip' })
})

test('release builds fail loudly when notarization credentials are missing or partial', () => {
  assert.throws(
    () => resolveNotarizationCredentials({ FABRIC_REQUIRE_NOTARIZATION: 'true' }),
    /configured together/
  )
  assert.throws(
    () =>
      resolveNotarizationCredentials({
        APPLE_API_KEY: 'key',
        APPLE_API_KEY_ID: 'id'
      }),
    /configured together/
  )
})

test('complete API-key credentials and keychain profiles are accepted', () => {
  assert.deepEqual(
    resolveNotarizationCredentials({
      APPLE_API_KEY: 'key',
      APPLE_API_KEY_ID: 'id',
      APPLE_API_ISSUER: 'issuer'
    }),
    { mode: 'api-key', rawApiKey: 'key', keyId: 'id', issuer: 'issuer' }
  )
  assert.deepEqual(resolveNotarizationCredentials({ APPLE_NOTARY_PROFILE: 'fabric-release' }), {
    mode: 'profile',
    profile: 'fabric-release'
  })
})
