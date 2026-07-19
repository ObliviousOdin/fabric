import { describe, expect, it } from 'vitest'

import { resolveFabricBin } from '../lib/externalCli.js'

describe('resolveFabricBin', () => {
  it('uses the Fabric executable on a clean install', () => {
    expect(resolveFabricBin({})).toBe('fabric')
  })

  it('uses the Fabric executable override when configured', () => {
    expect(resolveFabricBin({ FABRIC_BIN: '/opt/fabric/bin/fabric' })).toBe('/opt/fabric/bin/fabric')
    expect(resolveFabricBin({ FABRIC_BIN: '  ' })).toBe('fabric')
  })
})
