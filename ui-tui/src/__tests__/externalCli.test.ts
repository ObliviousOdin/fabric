import { describe, expect, it } from 'vitest'

import { resolveFabricBin } from '../lib/externalCli.js'

describe('resolveFabricBin', () => {
  it('uses the Fabric executable on a clean install', () => {
    expect(resolveFabricBin({})).toBe('fabric')
  })

  it('prefers the Fabric override and preserves the Fabric override as a legacy fallback', () => {
    expect(resolveFabricBin({ FABRIC_BIN: '/opt/fabric/bin/fabric', FABRIC_BIN: '/opt/legacy/hermes' })).toBe(
      '/opt/fabric/bin/fabric'
    )
    expect(resolveFabricBin({ FABRIC_BIN: '  ', FABRIC_BIN: '/opt/legacy/hermes' })).toBe('/opt/legacy/hermes')
  })
})
